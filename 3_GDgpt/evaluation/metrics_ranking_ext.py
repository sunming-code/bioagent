"""Ranking metrics for retrieved genes (extension to evaluation/compute_metrics.py).

This script does NOT replace compute_metrics.py. It reuses that module's
normalisation and Recall@k so the numbers stay comparable, and adds the
ranking-aware cuts the paper table needs:

  recall@5    -- identical by construction to compute_metrics.py
                 retrieval.gene_recall@5 (we call the same function)
  recall@20   -- same metric at a deeper cut
  hit@5       -- fraction of questions with >= 1 gold gene in the top 5
  ndcg@10     -- nDCG at 10 against an unordered gold set, so the ideal
                 ranking puts min(10, |gold|) relevant items first
  ceiling_recall@5 -- min(5, |gold|) / |gold|. With |gold| = 20 this is 0.25,
                 i.e. a perfect top-5 ranker still scores only 0.25, so a
                 Recall@5 of 0.01 is 4% of what is achievable, not 1%.
  recall@all  -- NO rank cut, using THIS module's alias canonicalisation.
  recall@all_plain_lowercase -- NO rank cut, using plain lowercase with NO
                 alias canonicalisation. This is the exact normalisation
                 evaluation/compute_paired_stats.py uses for
                 --metric gene_recall, so this field -- NOT recall@all and
                 NOT recall@5 -- is the one that reproduces the archived
                 paired_stats_gene_recall.txt number. The two differ because
                 the alias map changes both the matches and the size of the
                 gold set (the recall denominator); keeping both makes the
                 difference visible instead of assumed.

ALL @k METRICS CUT THE SAME LIST. Every @k metric here truncates the
canonicalised prediction list at k WITHOUT de-duplicating first, exactly as
compute_metrics.recall_at_k does. A repeated symbol therefore occupies a rank
and wastes a slot, which is the behaviour you want from a ranking metric and
is also the only way recall@5 can stay identical to compute_metrics.py.
`n_duplicate_predictions` reports how much duplication there is so the effect
is measurable rather than hidden.

Provenance note recorded here on purpose: the predicted_genes lists produced by
evaluation/extract_from_tool_calls.py are ALPHABETICALLY SORTED, not ranked by
evidence. Any @k metric over them therefore measures alphabetical luck. The
`predictions_appear_sorted` flag is computed on the RAW (lowercased, not
alias-canonicalised) list, because alias canonicalisation can reorder a list
that was alphabetical as written and would hide the artefact.

Usage
-----
  python evaluation/metrics_ranking_ext.py \
      --gold evaluation/independent_testset/output/testset_kg_optimized_enriched_with_edges.jsonl \
      --pred evaluation/results/adapt15_full_ext.jsonl \
      [--out evaluation/results/metrics_ext_ranking_<tag>.json]

Writes nothing unless --out is given; always prints the JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse the EXISTING definitions so recall@5 cannot silently drift.
from compute_metrics import (  # noqa: E402
    _canonicalize_gene,
    _load_gene_alias_map,
    load_jsonl,
    normalize_genes,
    recall_at_k,
)

RANK_CUTS = (5, 20)
NDCG_CUT = 10


def _plain(v: Any) -> str:
    """The normalisation compute_paired_stats.py uses: strip + lowercase only."""
    return str(v or "").strip().lower()


def _canon_prefix(pred_genes: List[Any], alias_map: dict, k: Any = None) -> List[str]:
    """The canonicalised top-k prefix, built EXACTLY as compute_metrics does.

    compute_metrics.recall_at_k slices the raw list to k FIRST and only then
    drops blanks and canonicalises, so a blank entry consumes a rank. Doing it
    in the other order would let hit@k and nDCG see a gene that recall@k does
    not, and the three would disagree on the same question. Duplicates are kept
    for the same reason: they occupy ranks.

    k=None means the whole list (used for recall@all).
    """
    window = pred_genes if k is None else pred_genes[:k]
    return [
        c for c in (_canonicalize_gene(str(g), alias_map) for g in window
                    if str(g).strip()) if c
    ]


def _ndcg_at_k(gold_set: set, pred_canon: List[str], k: int):
    """nDCG@k against an UNORDERED gold set (binary relevance).

    Ideal DCG assumes the min(k, |gold|) relevant items occupy ranks 1..n.
    A gold item already credited at an earlier rank is not credited again, so a
    repeated symbol wastes its rank instead of inflating the score.
    Returns None when gold is empty (nothing to rank against).
    """
    if not gold_set:
        return None
    dcg = 0.0
    credited = set()
    for i, g in enumerate(pred_canon[:k], start=1):
        if g in gold_set and g not in credited:
            credited.add(g)
            dcg += 1.0 / math.log2(i + 1)
    ideal_n = min(k, len(gold_set))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_n + 1))
    return dcg / idcg if idcg else None


def _looks_sorted(raw_pred: List[Any]) -> bool:
    """Alphabetical check on the RAW list, before alias canonicalisation."""
    plain = [_plain(g) for g in raw_pred if _plain(g)]
    return len(plain) > 2 and plain == sorted(plain)


def compute(gold_rows: List[dict], pred_by_id: Dict[str, dict]) -> dict:
    alias_map = _load_gene_alias_map()

    per_question: List[dict] = []
    missing: List[str] = []
    skipped_no_gold: List[str] = []

    for gold in gold_rows:
        gid = str(gold.get("id"))
        pred = pred_by_id.get(gid)
        if pred is None:
            missing.append(gid)
            continue

        gold_genes = gold.get("gold_genes", []) or []
        gold_set = normalize_genes(gold_genes, alias_map)
        if not gold_set:
            # compute_metrics.py skips these too (recall_at_k returns None).
            skipped_no_gold.append(gid)
            continue

        raw_pred = pred.get("predicted_genes", []) or []
        pred_all = _canon_prefix(raw_pred, alias_map)

        gold_plain = {p for p in (_plain(g) for g in gold_genes) if p}
        pred_plain = [p for p in (_plain(g) for g in raw_pred) if p]

        row = {
            "id": gid,
            "n_gold": len(gold_set),
            "n_gold_plain_lowercase": len(gold_plain),
            "n_pred": len(pred_all),
            "n_duplicate_predictions": len(pred_all) - len(set(pred_all)),
            "predictions_appear_sorted": _looks_sorted(raw_pred),
        }
        for k in RANK_CUTS:
            # Delegate to compute_metrics.recall_at_k on the RAW list so the
            # value is byte-for-byte the same metric that script reports.
            row["recall@%d" % k] = recall_at_k(gold_genes, raw_pred, k, entity_type="gene")
            # Built by _canon_prefix, i.e. the IDENTICAL prefix recall_at_k uses.
            row["hit@%d" % k] = 1.0 if (gold_set & set(_canon_prefix(raw_pred, alias_map, k))) else 0.0
            row["ceiling_recall@%d" % k] = min(k, len(gold_set)) / len(gold_set)
        row["recall@all"] = len(gold_set & set(pred_all)) / len(gold_set)
        row["recall@all_plain_lowercase"] = (
            len(gold_plain & set(pred_plain)) / len(gold_plain) if gold_plain else None
        )
        row["ndcg@%d" % NDCG_CUT] = _ndcg_at_k(
            gold_set, _canon_prefix(raw_pred, alias_map, NDCG_CUT), NDCG_CUT
        )
        per_question.append(row)

    def avg(key: str):
        vals = [
            r[key] for r in per_question
            if r.get(key) is not None and not _isnan(r[key])
        ]
        return mean(vals) if vals else None

    def avg_ratio(num_key: str, den_key: str):
        """Mean of per-question num/den, skipping rows with a missing or zero den."""
        vals = []
        for r in per_question:
            num, den = r.get(num_key), r.get(den_key)
            if num is None or den in (None, 0) or _isnan(num) or _isnan(den):
                continue
            vals.append(num / den)
        return mean(vals) if vals else None

    r5, ceil5 = avg("recall@5"), avg("ceiling_recall@5")
    genes = {
        "n_scored": len(per_question),
        "recall@5": r5,
        "recall@20": avg("recall@20"),
        "recall@all": avg("recall@all"),
        "recall@all_plain_lowercase": avg("recall@all_plain_lowercase"),
        "hit@5": avg("hit@5"),
        "hit@20": avg("hit@20"),
        "ndcg@10": avg("ndcg@10"),
        "ceiling_recall@5": ceil5,
        "ceiling_recall@20": avg("ceiling_recall@20"),
        # MEAN OF PER-QUESTION RATIOS, which is the quantity the module docstring
        # describes ("a Recall@5 of 0.01 is 4% of what is achievable"). A ratio of
        # means is a different number whenever |gold| varies: on the 38-question
        # set it reads 0.007613 against this 0.021053, a 2.8x understatement of
        # how close the system is to its own ceiling. Both are reported so the
        # distinction is visible rather than a silent choice.
        "recall@5_as_fraction_of_ceiling": avg_ratio("recall@5", "ceiling_recall@5"),
        "recall@5_as_fraction_of_ceiling_ratio_of_means": (
            (r5 / ceil5) if (r5 is not None and ceil5) else None
        ),
        "n_questions_with_sorted_predictions": sum(
            1 for r in per_question if r["predictions_appear_sorted"]
        ),
        "total_duplicate_predictions": sum(r["n_duplicate_predictions"] for r in per_question),
        "per_question": per_question,
    }

    return {
        "num_gold": len(gold_rows),
        "num_predictions": len(pred_by_id),
        "missing_predictions": missing,
        "skipped_questions_without_gold_genes": skipped_no_gold,
        "genes": genes,
        "notes": [
            "recall@5 is computed by calling compute_metrics.recall_at_k, so it "
            "equals compute_metrics.py retrieval.gene_recall@5 on the same inputs.",
            "recall@all_plain_lowercase (NOT recall@all) uses the plain-lowercase "
            "normalisation of compute_paired_stats.py --metric gene_recall and is "
            "the field that reproduces paired_stats_gene_recall.txt.",
            "recall@all uses this module's alias canonicalisation, which changes "
            "both the matches and the gold-set size, so it can differ from "
            "recall@all_plain_lowercase.",
            "ceiling_recall@5 = min(5, |gold|)/|gold|; |gold|=20 gives 0.25.",
            "All @k metrics cut the same non-deduplicated canonicalised list; "
            "total_duplicate_predictions says how much duplication there is.",
            "predictions_appear_sorted is computed on the RAW lowercased list. "
            "true means the predicted gene list is alphabetical, so any @k metric "
            "over it reflects alphabetical position, not retrieval ranking.",
        ],
    }


def _isnan(v: Any) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


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
    ap = argparse.ArgumentParser(description="Ranking metrics for retrieved genes.")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--alias-map", default=None)
    ap.add_argument("--out", default=None, help="Optional NEW json file to write.")
    args = ap.parse_args()

    _load_gene_alias_map(args.alias_map)

    gold_rows = load_jsonl(Path(args.gold))
    pred_by_id = {str(r["id"]): r for r in load_jsonl(Path(args.pred))}

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
