"""Drug-path queries split by whether the asked disease is in the Task KG.

Question this answers: when GDgpt asks the KG for drugs for a disease, how
often does the disease it names actually exist as a Disease node? The Task KG
has only 20 Disease nodes, so a DiseaseToDrug query naming anything else can
only return nothing -- that is a coverage limit, not a retrieval bug, and the
two must be counted apart.

COUNTING GRANULARITY (this is where the earlier 68/60 vs 34/30 disagreement
came from)
------------------------------------------------------------------------
One asked query appears FIVE times in the raw JSONL:

  1. in the agent's planned payload  tool_calls[].query -> {"queries": [...]}
  2. in the executed run            tool_calls[].result.runs[].intent
  3. inside that run's echo         tool_calls[].result.runs[].query_payload.intent
  4. in the run's rendered text     ...runs[].text   "(intent=DiseaseToDrug, k=8)"
  5. in the concatenated text       ...result.text   (same line, again)

So a raw `grep -c DiseaseToDrug` over the file returns 5x the true number
(170), and a scan that counts levels 1 and 2 together returns 2x (68). The
only granularity that corresponds to "an individual query object with its own
result block" is level 2: `tool_calls[].result.runs[]`, each of which carries
its own `records` list. This script counts at THAT level, and reports the
other granularities in `granularity_audit` so the discrepancy is checkable
rather than asserted. Expected outcome: DiseaseToDrug = 34, DrugToDisease = 30
are right; 68/60 double-count; 170/150 quintuple-count.

A second, coarser count is also reported. The agent retries, so the same
(question, intent, disease) is often executed 2-4 times within one question;
`unique_question_disease` counts each distinct (question, intent, disease)
once. Use the run-level count when asking "how many KG calls did we make",
and the unique count when asking "how many distinct things did we ask about".

THREE BUCKETS, NOT TWO. A query that never named a disease at all cannot be
"a disease the KG does not have". GeneToDrug takes a gene and DrugToDisease
takes a drug, so most of their runs carry no disease argument; bucketing those
as off-KG would report a coverage gap that was never tested. Every counted run
therefore lands in exactly one of `in_kg`, `off_kg`, `no_disease_arg`, and
in_kg + off_kg + no_disease_arg == n_queries. Only `in_kg` and `off_kg` carry a
coverage interpretation; `no_disease_arg` is excluded from both.

For the same reason each intent reports TWO hit rates. `hit_rate_all_runs`
spans all three buckets and is a mixed population: for GeneToDrug it is
entirely disease-less runs, so it says nothing about disease coverage.
`hit_rate_disease_named` is over in_kg + off_kg only and is the one to read
next to the coverage split. `coverage_interpretable` is false when no run of
that intent named a disease at all.

DISEASE MATCHING. A query's disease string matches the KG when its normalised
form (lowercased, stripped, whitespace collapsed, trailing punctuation
removed) equals a Disease node's name, normalized_name, or any alias. Match is
EXACT after normalisation -- no substring or fuzzy matching, because
"prostate cancer" vs "prostate carcinoma" are separate nodes here and fuzzy
matching would hide exactly the coverage gap we are measuring. Near misses
are listed in `off_kg.near_misses`, keyed by the asked string with the reason
it looks like an alias (containment, token subset, or two or more shared content
tokens -- see near_miss_reason), so a reader can judge how many are alias
problems rather than true absences. `off_kg.n_near_misses` counts them. An EMPTY
near_misses dict is only evidence of a real coverage ceiling if the detector can
see the alias class in question; the earlier first-word-only test could not.

HIT. A query hit when its `records` list is non-empty.

Source of the 20 Disease nodes: the kg_build node CSV (--kg-nodes), read-only.
config.json is not available in this worktree, so no Neo4j connection is made.

Usage
-----
  python evaluation/metrics_drug_by_coverage_ext.py \
      --pred evaluation/results/pcqa100_gdgpt_raw.jsonl \
      --kg-nodes '/path/to/task_kg_output/task_kg_nodes.csv' \
      [--intents DiseaseToDrug,DrugToDisease,GeneToDrug,DrugTargetDiseaseBridge] \
      [--out evaluation/results/metrics_ext_drugcov_<tag>.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_WS = re.compile(r"\s+")
DEFAULT_INTENTS = ["DiseaseToDrug", "DrugToDisease", "GeneToDrug", "DrugTargetDiseaseBridge"]

# Fields a run's query_payload may carry the asked disease under.
DISEASE_KEYS = ("disease", "disease_name", "condition")


def _norm(v: Any) -> str:
    s = _WS.sub(" ", str(v or "").strip().lower())
    return s.strip(" .,;:!?\"'")


STOPWORDS = {"of", "the", "and", "with", "to", "in", "or", "a", "an"}


def load_disease_nodes(csv_path: Path) -> Dict[str, Any]:
    """Return the Disease nodes and the set of normalised strings that match them.

    `n_disease_nodes_with_aliases` is reported because on this KG the `aliases`
    column is empty for every Disease node and `normalized_name` equals `name`,
    so two of the three documented match arms contribute nothing: 20 nodes yield
    20 surface forms. A reader comparing a disease string against "name,
    normalized_name or any alias" would otherwise assume more coverage than
    exists.
    """
    names: List[str] = []
    surface: Set[str] = set()
    with_aliases = 0
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("type") or "").strip() != "Disease":
                continue
            names.append(row.get("name") or "")
            for key in ("name", "normalized_name"):
                n = _norm(row.get(key))
                if n:
                    surface.add(n)
            had_alias = False
            for alias in (row.get("aliases") or "").split("|"):
                n = _norm(alias)
                if n:
                    surface.add(n)
                    had_alias = True
            if had_alias:
                with_aliases += 1
    return {
        "n": len(names),
        "names": sorted(names),
        "surface_forms": surface,
        "n_disease_nodes_with_aliases": with_aliases,
        "n_distinct_surface_forms": len(surface),
    }


def _content_tokens(s: str) -> Set[str]:
    return {t for t in s.split(" ") if t and t not in STOPWORDS}


def near_miss_reason(asked_norm: str, surface: Set[str]) -> Optional[str]:
    """Why an off-KG disease string looks like an alias of a KG node, or None.

    Disease names in this data differ by PREFIX modifiers -- the KG has
    `lung cancer` while a query asks `non-squamous non-small cell lung cancer`.
    A first-word-only test is structurally blind to exactly that class and
    reported zero near misses on all 30 off-KG DiseaseToDrug queries, which was
    then read as evidence of a genuine coverage ceiling. Three tests are applied
    instead, most specific first:

      containment      -- a KG surface form is a substring of the asked string,
                          or the reverse
      token_subset     -- the KG form's content tokens are a subset of the
                          asked string's, or the reverse
      token_overlap    -- at least two content tokens in common

    Stopwords are excluded so `carcinoma of the X` does not match `Y of the Z`
    on "of" and "the" alone.
    """
    a_tokens = _content_tokens(asked_norm)
    if not asked_norm or not a_tokens:
        return None
    best = None
    for form in surface:
        f_tokens = _content_tokens(form)
        if not f_tokens:
            continue
        if form in asked_norm or asked_norm in form:
            return "containment: KG node %r" % form
        if f_tokens <= a_tokens or a_tokens <= f_tokens:
            best = best or "token_subset: KG node %r" % form
            continue
        shared = f_tokens & a_tokens
        if len(shared) >= 2 and best is None:
            best = "token_overlap(%s): KG node %r" % (",".join(sorted(shared)), form)
    return best


def _iter_runs(rows: List[dict]):
    """Yield (question_id, run) at the one granularity that has its own records."""
    for r in rows:
        qid = str(r.get("id"))
        for tc in r.get("tool_calls") or []:
            res = tc.get("result")
            if not isinstance(res, dict):
                continue
            for run in res.get("runs") or []:
                if isinstance(run, dict):
                    yield qid, run


def _planned_intents(rows: List[dict]) -> Counter:
    """Level-1 granularity: the agent's planned payload (used for the audit only)."""
    c: Counter = Counter()
    for r in rows:
        for tc in r.get("tool_calls") or []:
            try:
                payload = json.loads(tc.get("query") or "{}")
            except (TypeError, ValueError):
                continue
            for q in payload.get("queries") or []:
                if isinstance(q, dict) and q.get("intent"):
                    c[q["intent"]] += 1
    return c


def _asked_disease(run: dict) -> str:
    payload = run.get("query_payload") or {}
    for key in DISEASE_KEYS:
        if payload.get(key):
            return str(payload[key])
    return ""


def compute(rows: List[dict], kg: Dict[str, Any], intents: List[str], raw_text: str) -> dict:
    surface = kg["surface_forms"]

    buckets: Dict[str, dict] = {}
    all_intent_counts: Counter = Counter()

    for qid, run in _iter_runs(rows):
        intent = run.get("intent") or "<none>"
        all_intent_counts[intent] += 1
        if intent not in intents:
            continue

        asked = _asked_disease(run)
        norm = _norm(asked)
        in_kg = bool(norm) and norm in surface
        hit = bool(run.get("records"))

        b = buckets.setdefault(intent, {
            "n_queries": 0,
            "n_hits": 0,
            "in_kg": {"n_queries": 0, "n_hits": 0, "diseases": Counter()},
            "off_kg": {"n_queries": 0, "n_hits": 0, "diseases": Counter(), "near_misses": Counter()},
            "no_disease_arg": {"n_queries": 0, "n_hits": 0},
            "unique_question_disease": set(),
            "unique_in_kg": set(),
        })
        b["n_queries"] += 1
        b["n_hits"] += 1 if hit else 0

        if not norm:
            # Not a coverage observation: this query never named a disease.
            b["no_disease_arg"]["n_queries"] += 1
            b["no_disease_arg"]["n_hits"] += 1 if hit else 0
            continue

        side = b["in_kg"] if in_kg else b["off_kg"]
        side["n_queries"] += 1
        side["n_hits"] += 1 if hit else 0
        side["diseases"][asked] += 1
        if not in_kg:
            reason = near_miss_reason(norm, surface)
            if reason:
                side["near_misses"]["%s -> %s" % (asked, reason)] += 1
        b["unique_question_disease"].add((qid, norm))
        if in_kg:
            b["unique_in_kg"].add((qid, norm))

    by_intent: Dict[str, dict] = {}
    for intent, b in buckets.items():
        uniq = b.pop("unique_question_disease")
        uniq_in = b.pop("unique_in_kg")
        for side in ("in_kg", "off_kg", "no_disease_arg"):
            if "diseases" in b[side]:
                b[side]["diseases"] = dict(b[side]["diseases"].most_common())
            if "near_misses" in b[side]:
                b[side]["n_near_misses"] = sum(b[side]["near_misses"].values())
                b[side]["near_misses"] = dict(b[side]["near_misses"].most_common())
            n_q = b[side]["n_queries"]
            b[side]["hit_rate"] = (b[side]["n_hits"] / n_q) if n_q else None
        # Two hit rates, because one population is a mixture. hit_rate_all_runs
        # spans in-KG, off-KG and disease-less runs together, so for GeneToDrug
        # and DrugToDisease it is dominated by queries that never named a
        # disease and must not be read as a coverage result.
        # hit_rate_disease_named is over the runs the coverage split is about.
        n_named = b["in_kg"]["n_queries"] + b["off_kg"]["n_queries"]
        hits_named = b["in_kg"]["n_hits"] + b["off_kg"]["n_hits"]
        b["hit_rate_all_runs"] = (b["n_hits"] / b["n_queries"]) if b["n_queries"] else None
        b["hit_rate_disease_named"] = (hits_named / n_named) if n_named else None
        b["n_queries_disease_named"] = n_named
        b["buckets_sum_to_total"] = (
            b["in_kg"]["n_queries"] + b["off_kg"]["n_queries"]
            + b["no_disease_arg"]["n_queries"] == b["n_queries"]
        )
        b["coverage_interpretable"] = b["in_kg"]["n_queries"] + b["off_kg"]["n_queries"] > 0
        b["unique_question_disease"] = {
            "n": len(uniq), "n_in_kg": len(uniq_in), "n_off_kg": len(uniq) - len(uniq_in),
            "note": "counted over runs that named a disease; excludes no_disease_arg runs",
        }
        by_intent[intent] = b

    planned = _planned_intents(rows)
    audit = {}
    for intent in intents:
        run_level = all_intent_counts.get(intent, 0)
        audit[intent] = {
            "run_level_correct": run_level,
            "planned_payload_level": planned.get(intent, 0),
            "planned_plus_run_double_count": planned.get(intent, 0) + run_level,
            "raw_substring_occurrences": raw_text.count(intent),
            "verdict": "run_level_correct is the count to use; "
                       "planned_plus_run_double_count is the 2x artefact; "
                       "raw_substring_occurrences is the 5x artefact.",
        }

    return {
        "n_questions": len(rows),
        "n_runs_total": sum(all_intent_counts.values()),
        "intents_counted": intents,
        "all_intent_counts_run_level": dict(all_intent_counts.most_common()),
        "kg_disease_nodes": {
            "n": kg["n"],
            "names": kg["names"],
            "n_disease_nodes_with_aliases": kg["n_disease_nodes_with_aliases"],
            "n_distinct_surface_forms": kg["n_distinct_surface_forms"],
            "note": "n_disease_nodes_with_aliases of 0 means the aliases match arm is "
                    "inert on this KG; normalized_name also equals name on every row, "
                    "so n_distinct_surface_forms equals n.",
        },
        "by_intent": by_intent,
        "granularity_audit": audit,
        "matching": "exact after normalisation (lowercase, strip, collapse "
                    "whitespace, strip trailing punctuation); no fuzzy matching",
    }


def json_safe(obj):
    """Replace NaN/Infinity with None so the output is valid RFC 8259 JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Drug-path query counts split by KG disease coverage.")
    ap.add_argument("--pred", required=True)
    ap.add_argument("--kg-nodes", required=True, help="kg_build task_kg_nodes.csv (read-only)")
    ap.add_argument("--intents", default=",".join(DEFAULT_INTENTS))
    ap.add_argument("--out", default=None, help="Optional NEW json file to write.")
    args = ap.parse_args()

    pred_path = Path(args.pred)
    raw_text = pred_path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    kg = load_disease_nodes(Path(args.kg_nodes))
    if kg["n"] == 0:
        # Without Disease nodes every query would be reported off-KG and the
        # headline conclusion would be manufactured by a parse failure. Refuse.
        raise SystemExit(
            "no Disease nodes found in %s -- expected rows with type='Disease'. "
            "Refusing to report a coverage split that would classify every query "
            "as off-KG purely because the node file did not parse." % args.kg_nodes
        )
    intents = [s.strip() for s in args.intents.split(",") if s.strip()]

    result = compute(rows, kg, intents, raw_text)
    result["inputs"] = {"pred": args.pred, "kg_nodes": args.kg_nodes}

    text = json.dumps(json_safe(result), indent=2, ensure_ascii=False, allow_nan=False)
    print(text)
    if args.out:
        out = Path(args.out)
        if out.exists():
            raise SystemExit("refusing to overwrite existing file: %s" % out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
