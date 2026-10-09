"""Citation precision / recall: cited_edges vs expected_kg_edges.

WHAT IS ALREADY IN THE REPOSITORY. evaluation/compute_system_metrics.py already
computes citation precision and F1: `traceability_precision` at :151 and
`traceability_f1` at :162, both written into the result at :271-272 per bucket
and :297-298 overall. They are merely absent from the ASCII table its
pretty-printer draws. On adapt15_full_ext x indep38 gold that script reports
traceability 0.0292, traceability_precision 0.0169 and traceability_f1 0.0802.
This script does NOT discover citation precision and its numbers are not a new
measurement of it.

WHAT IS ACTUALLY NEW HERE, and the only thing worth quoting as new:

1. MICRO aggregation. The existing script macro-averages per-question ratios.
   This one also pools true positives, cited and expected counts across
   questions before dividing. Both are reported, because the two answer
   different questions and can diverge badly when per-question edge counts are
   uneven. On the file above they happen to agree to about two decimals, which
   is a coincidence of this input and NOT a reproduction anchor.
2. A 0.0 convention where the existing script yields NaN. The existing
   `traceability_f1` drops 11 of 15 questions to NaN and averages the remaining
   4 to 0.0802; here a question that cited nothing where edges were expected
   scores 0.0 and stays in the average, so an arm cannot raise its score by
   staying silent.
3. A relation-blind variant, so a relation-vocabulary mismatch cannot be
   mistaken for an endpoint retrieval failure.
4. An explicit, self-tested edge normalisation (below), and a guard that refuses
   to report when the gold set contains no expected edges at all.

EDGE NORMALISATION (the whole point of this script -- read before quoting any
number from it)
---------------------------------------------------------------------------
An edge is a triple (a, b, rel). Normalisation is applied in this order:

1. CASE and whitespace. Every component is str()'d, stripped, lowercased, and
   internal runs of whitespace are collapsed to one space. So
   "ERBB2" == "erbb2" and "breast  carcinoma" == "breast carcinoma".

2. DIRECTION. The two endpoints are SORTED, so (a, b, rel) and (b, a, rel)
   are the same edge. This matches compute_system_metrics._norm_edge. It is
   the right call for this KG because the gold edges are written
   disease-first ("breast carcinoma", "ERBB2", "ASSOCIATED_WITH") while the
   KG tool emits them gene-first; treating direction as significant would
   score every correct citation as wrong. The cost is that a genuinely
   directed relation (e.g. a gene -> pathway membership) cannot be caught
   citing the reverse direction. That is a deliberate, documented loss.

3. RELATION NAME. Underscores and hyphens become spaces, whitespace is
   collapsed, and a small synonym table folds the KG's surface forms onto the
   gold vocabulary (e.g. "interacts with" -> "interacts_with" family,
   "indicated for"/"treats" -> "treats"). The table is RELATION_SYNONYMS
   below and is the only place to extend it. Unknown relation names are left
   as their normalised selves rather than dropped, so an unmapped relation
   shows up as a miss we can see, not a silent match.

4. Degenerate edges (fewer than 2 non-empty endpoints) are DROPPED from both
   sides and counted in `dropped_edges` so they cannot inflate precision.

A relation-blind score is reported alongside: identical, except the relation
component is replaced by "" before comparison. Read it as the ceiling the
endpoint matching alone can reach.

Usage
-----
  python evaluation/metrics_citation_ext.py \
      --gold evaluation/independent_testset/output/testset_kg_optimized_enriched_with_edges.jsonl \
      --pred evaluation/results/adapt15_full_ext.jsonl \
      [--out evaluation/results/metrics_ext_citation_<tag>.json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

_WS = re.compile(r"\s+")

# Surface form -> canonical relation name. THE KEYS MUST BE IN THE FORM
# _relation_surface() produces: lowercased, with underscores and hyphens already
# turned into spaces. An underscored key such as "associated_with" can never
# match, because the lookup happens after that substitution; a maintainer adding
# one would get a silent no-op. `_selftest` asserts every key is reachable, so
# adding an unreachable one turns the checks red instead.
RELATION_SYNONYMS = {
    "associated with": "associated_with",
    "association": "associated_with",
    "interacts with": "interacts_with",
    "interaction": "interacts_with",
    "indicated for": "treats",
    "indication": "treats",
    "treats": "treats",
    "target": "targets",
    "targets": "targets",
    "phenotype present": "phenotype_present",
    "parent child": "parent_child",
}

Edge = Tuple[str, str, str]


def _norm_text(v: Any) -> str:
    return _WS.sub(" ", str(v or "").strip().lower())


def _relation_surface(v: Any) -> str:
    """The lookup key: lowercased, separators collapsed to single spaces."""
    s = _norm_text(v).replace("_", " ").replace("-", " ")
    return _WS.sub(" ", s).strip()


def _norm_relation(v: Any) -> str:
    return RELATION_SYNONYMS.get(_relation_surface(v), _relation_surface(v))


def norm_edge(e: Any, relation_blind: bool = False) -> Optional[Edge]:
    """Normalise one edge to a comparable triple, or None if degenerate."""
    if isinstance(e, dict):
        parts = [e.get("from") or e.get("source") or e.get("a"),
                 e.get("to") or e.get("target") or e.get("b"),
                 e.get("type") or e.get("relation") or e.get("rel")]
    else:
        parts = list(e) if isinstance(e, (list, tuple)) else []
    parts = parts + [None] * (3 - len(parts)) if len(parts) < 3 else parts[:3]

    a, b = _norm_text(parts[0]), _norm_text(parts[1])
    if not a or not b:
        return None
    if a > b:
        a, b = b, a
    rel = "" if relation_blind else _norm_relation(parts[2])
    return (a, b, rel)


def norm_edge_set(edges: Iterable[Any], relation_blind: bool = False):
    """Return (set of normalised edges, number dropped as degenerate)."""
    out: Set[Edge] = set()
    dropped = 0
    for e in edges or []:
        ne = norm_edge(e, relation_blind=relation_blind)
        if ne is None:
            dropped += 1
        else:
            out.add(ne)
    return out, dropped


def _prf(cited: Set[Edge], expected: Set[Edge]) -> Dict[str, Optional[float]]:
    """Micro counts plus the per-question P/R/F1.

    Precision, recall and F1 are ALL None only when nothing was cited AND
    nothing was expected, i.e. the question offered nothing to be right or
    wrong about.

    If edges were expected and none were cited, all three are 0.0, NOT None.
    Citing nothing is a complete miss, not an abstention, and the conventional
    IR reading of precision over an empty result set for a query with relevant
    items is 0. Returning None for any of them would let the corresponding
    macro average drop the question and reward silence: an arm perfect on 1 of
    4 questions and silent on 3 would score 1.0 and beat an arm half-right on
    all 4. Round 1 closed this hole for F1 only; precision had the same hole.

    If edges were cited and none were expected, precision is 0.0 (every
    citation is unsupported by the gold set) and recall is None (there was
    nothing to recall), so macro_recall legitimately skips the question while
    macro_precision does not.
    """
    tp = len(cited & expected)
    if not cited and not expected:
        return {"tp": 0, "n_cited": 0, "n_expected": 0,
                "precision": None, "recall": None, "f1": None}
    p = tp / len(cited) if cited else 0.0
    r = (tp / len(expected)) if expected else None
    r_eff = 0.0 if r is None else r
    f1 = (2 * p * r_eff / (p + r_eff)) if (p + r_eff) else 0.0
    return {"tp": tp, "n_cited": len(cited), "n_expected": len(expected),
            "precision": p, "recall": r, "f1": f1}


def _selftest() -> Dict[str, bool]:
    """Prove the documented normalisation properties on synthetic edges."""
    base = ["ERBB2", "breast carcinoma", "ASSOCIATED_WITH"]
    return {
        "case_insensitive": norm_edge(base) == norm_edge(["erbb2", "BREAST CARCINOMA", "associated_with"]),
        "direction_insensitive": norm_edge(base) == norm_edge(["breast carcinoma", "ERBB2", "ASSOCIATED_WITH"]),
        "separator_insensitive": norm_edge(base) == norm_edge(["ERBB2", "breast carcinoma", "associated with"]),
        "whitespace_collapsed": norm_edge(base) == norm_edge([" ERBB2 ", "breast   carcinoma", "ASSOCIATED-WITH"]),
        "relation_synonym_folded": norm_edge(["X", "Y", "indicated for"]) == norm_edge(["X", "Y", "treats"]),
        "distinct_relation_kept_distinct": norm_edge(["X", "Y", "treats"]) != norm_edge(["X", "Y", "targets"]),
        "distinct_endpoints_kept_distinct": norm_edge(["X", "Y", "treats"]) != norm_edge(["X", "Z", "treats"]),
        "dict_form_accepted": norm_edge({"from": "ERBB2", "to": "breast carcinoma", "type": "ASSOCIATED_WITH"}) == norm_edge(base),
        "degenerate_dropped": norm_edge(["", "Y", "treats"]) is None,
        "relation_blind_ignores_relation": (
            norm_edge(["X", "Y", "treats"], relation_blind=True)
            == norm_edge(["X", "Y", "targets"], relation_blind=True)
        ),
        # Every RELATION_SYNONYMS key must survive _relation_surface unchanged,
        # or the lookup can never reach it.
        "every_relation_synonym_key_is_reachable": all(
            _relation_surface(k) == k for k in RELATION_SYNONYMS
        ),
    }


def _load_jsonl(path: Path) -> List[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute(gold_rows: List[dict], pred_by_id: Dict[str, dict]) -> dict:
    per_question: List[dict] = []
    missing: List[str] = []
    micro = {"tp": 0, "cited": 0, "expected": 0}
    micro_blind = {"tp": 0, "cited": 0, "expected": 0}
    dropped_total = {"gold": 0, "pred": 0}

    for gold in gold_rows:
        gid = str(gold.get("id"))
        pred = pred_by_id.get(gid)
        if pred is None:
            missing.append(gid)
            continue

        exp, d_g = norm_edge_set(gold.get("expected_kg_edges"))
        cit, d_p = norm_edge_set(pred.get("cited_edges"))
        dropped_total["gold"] += d_g
        dropped_total["pred"] += d_p

        exp_b, _ = norm_edge_set(gold.get("expected_kg_edges"), relation_blind=True)
        cit_b, _ = norm_edge_set(pred.get("cited_edges"), relation_blind=True)

        strict = _prf(cit, exp)
        blind = _prf(cit_b, exp_b)

        micro["tp"] += strict["tp"]
        micro["cited"] += strict["n_cited"]
        micro["expected"] += strict["n_expected"]
        micro_blind["tp"] += blind["tp"]
        micro_blind["cited"] += blind["n_cited"]
        micro_blind["expected"] += blind["n_expected"]

        per_question.append({"id": gid, "strict": strict, "relation_blind": blind})

    def macro(bucket: str, key: str) -> Optional[float]:
        vals = [q[bucket][key] for q in per_question if q[bucket][key] is not None]
        return mean(vals) if vals else None

    def micro_prf(m: dict) -> dict:
        # Same convention as _prf: 0.0 for "offered nothing where something was
        # expected", None only when there was nothing on either side.
        if not m["cited"] and not m["expected"]:
            return {"precision": None, "recall": None, "f1": None, **m}
        p = (m["tp"] / m["cited"]) if m["cited"] else 0.0
        r = (m["tp"] / m["expected"]) if m["expected"] else None
        r_eff = 0.0 if r is None else r
        f1 = (2 * p * r_eff / (p + r_eff)) if (p + r_eff) else 0.0
        return {"precision": p, "recall": r, "f1": f1, **m}

    n_expect_nothing = sum(1 for q in per_question if q["strict"]["n_expected"] == 0)
    # A gold set with NO expected edges anywhere cannot score citation quality:
    # tp is necessarily 0, so an arm that cites hundreds of correct edges gets
    # precision 0.0 and F1 0.0 while a silent arm gets None on everything and is
    # dropped from the macro averages. The citing system then looks strictly
    # worse than the silent one. Warn as loudly as metrics_drug_by_coverage_ext
    # refuses on an empty node file.
    no_edges_warning = None
    if per_question and n_expect_nothing == len(per_question):
        no_edges_warning = (
            "UNUSABLE GOLD: all %d scored questions have an EMPTY expected_kg_edges "
            "list, so no citation can ever be a true positive. Every precision, recall "
            "and F1 below is an artefact of that, not a measurement: a system citing "
            "only correct edges scores 0.0 and a system citing nothing scores null and "
            "is excluded from the macro averages, which makes the citing system look "
            "worse. Do not quote any number from this run. Use a gold file whose "
            "expected_kg_edges are populated (for example "
            "evaluation/independent_testset/output/"
            "testset_kg_optimized_enriched_with_edges.jsonl)." % len(per_question)
        )

    return {
        "num_gold": len(gold_rows),
        "num_predictions": len(pred_by_id),
        "num_scored": len(per_question),
        "missing_predictions": missing,
        "dropped_degenerate_edges": dropped_total,
        "no_expected_edges_warning": no_edges_warning,
        "n_questions_citing_nothing": sum(
            1 for q in per_question if q["strict"]["n_cited"] == 0
        ),
        "n_questions_expecting_nothing": n_expect_nothing,
        "strict": {
            "micro": micro_prf(micro),
            "macro_precision": macro("strict", "precision"),
            "macro_recall": macro("strict", "recall"),
            "macro_f1": macro("strict", "f1"),
        },
        "relation_blind": {
            "micro": micro_prf(micro_blind),
            "macro_precision": macro("relation_blind", "precision"),
            "macro_recall": macro("relation_blind", "recall"),
            "macro_f1": macro("relation_blind", "f1"),
        },
        "normalisation_selftest": _selftest(),
        "normalisation": {
            "case": "lowercased, stripped, internal whitespace collapsed",
            "direction": "endpoints sorted -> direction ignored",
            "relation": "underscores/hyphens -> spaces, then RELATION_SYNONYMS folding",
            "relation_blind_variant": "relation component replaced by empty string",
        },
        "per_question": per_question,
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
    ap = argparse.ArgumentParser(description="Citation precision/recall for cited_edges vs expected_kg_edges.")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--out", default=None, help="Optional NEW json file to write.")
    args = ap.parse_args()

    gold_rows = _load_jsonl(Path(args.gold))
    pred_by_id = {str(r["id"]): r for r in _load_jsonl(Path(args.pred))}

    result = compute(gold_rows, pred_by_id)
    result["inputs"] = {"gold": args.gold, "pred": args.pred}

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
