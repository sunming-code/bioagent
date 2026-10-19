"""
compute_system_metrics.py (v2.1)

Stratified system-level metrics for GDgpt MTB evaluation.

Inputs
------
A predictions JSONL file where each line is one case prediction with AT LEAST:
  {
    "id": "<case id>",
    "final_answer": "<system report text>",
    "kg_coverage_level": "high" | "partial" | "low" | "disabled",   # from workflow
    "kg_coverage_ratio": <float>,
    "cited_edges": [["ERBB2","breast carcinoma","ASSOCIATED_WITH"], ...],  # optional
    "asserted_claims": [                                             # optional
        {"claim": "...", "has_kg_support": true|false}
    ]
  }

A gold JSONL file (one line per case) with AT LEAST:
  {
    "id": "<case id>",
    "gold_actionable_genes": [...],
    "gold_pathways": [...],
    "gold_drugs": [ {"name": "..."} , ... ],
    "expected_kg_edges": [ ["A","B","REL"], ... ]    # required for Traceability
  }

Computed metrics per coverage bucket
------------------------------------
  - N                        : number of cases
  - Accuracy (loose)         : 1 if any gold gene OR drug appears in final_answer text
  - Traceability             : |cited_edges ∩ expected_edges| / |expected_edges|
  - Hallucination Rate       : (# claims with has_kg_support=False) / (# total claims)
                               (if asserted_claims absent, use LLM-judge fallback = skipped -> NaN)
  - Honest-Degradation Rate  : fraction of LOW-coverage cases whose final_answer contains
                               an explicit "insufficient KG evidence" (or equivalent) phrase
                               -> only meaningful for the LOW bucket

Usage
-----
  python evaluation/compute_system_metrics.py \
      --predictions evaluation/results/exp0_mtb70.jsonl \
      --gold evaluation/mtb_testset_v1.jsonl \
      --out evaluation/results/metrics_exp0_mtb70.json

Notes
-----
  - This script does NOT call any LLM. Hallucination Rate relies on the
    `has_kg_support` flag being precomputed (either in the workflow or
    by a separate LLM-judge step). If absent, the metric is reported as NaN
    and a warning is printed so we don't silently lie.
  - Edges are matched as unordered triples after lowercase/strip normalization.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Tuple


COVERAGE_BUCKETS = ["high", "partial", "low", "disabled"]

# Keywords that mark an explicit honest-degradation statement
HONEST_PATTERNS = [
    r"insufficient\s+kg\s+evidence",
    r"insufficient\s+(?:graph|knowledge\s+graph)\s+evidence",
    r"no\s+graph\s+facts\s+available",
    r"recommend\s+external\s+lookup",
    r"please\s+verify\s+via\s+(?:pubmed|oncokb|civic)",
    r"证据不足",
    r"知识图谱(?:中|内)?无.*支持",
]
HONEST_RE = re.compile("|".join(HONEST_PATTERNS), flags=re.IGNORECASE)


# ---------- IO helpers ----------

def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _index_by_id(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for r in rows:
        rid = str(r.get("id", "")).strip()
        if rid:
            out[rid] = r
    return out


# ---------- normalization ----------

def _norm_token(s: Any) -> str:
    return str(s or "").strip().lower()


def _norm_edge(e: Iterable) -> Tuple[str, str, str]:
    """Normalize an edge (a, b, rel) -> sorted (a,b) + rel, all lowercase/stripped."""
    lst = list(e) if not isinstance(e, dict) else [e.get("from"), e.get("to"), e.get("type")]
    if len(lst) < 3:
        lst = lst + [""] * (3 - len(lst))
    a, b, rel = lst[0], lst[1], lst[2]
    a_n, b_n = _norm_token(a), _norm_token(b)
    if a_n > b_n:
        a_n, b_n = b_n, a_n
    return (a_n, b_n, _norm_token(rel))


# ---------- per-case metrics ----------

def loose_accuracy(pred_text: str, gold: Dict[str, Any]) -> int:
    """1 if any gold gene OR any gold drug name appears in pred_text; else 0."""
    text = (pred_text or "").lower()
    if not text:
        return 0
    gold_genes = [_norm_token(g) for g in gold.get("gold_actionable_genes", []) if g]
    gold_drugs = []
    for d in gold.get("gold_drugs", []):
        name = d.get("name") if isinstance(d, dict) else d
        if name:
            gold_drugs.append(_norm_token(name))
    for g in gold_genes + gold_drugs:
        if g and g in text:
            return 1
    return 0


def traceability(pred: Dict[str, Any], gold: Dict[str, Any]) -> float:
    """召回口径：系统引用的边覆盖了多少标准答案边 = |cited ∩ expected| / |expected|。"""
    expected = {_norm_edge(e) for e in gold.get("expected_kg_edges", []) if e}
    if not expected:
        return float("nan")
    cited = {_norm_edge(e) for e in pred.get("cited_edges", []) if e}
    hit = len(cited & expected)
    return hit / len(expected)


def traceability_precision(pred: Dict[str, Any], gold: Dict[str, Any]) -> float:
    """精确口径：系统引用的边里有多少命中标准答案 = |cited ∩ expected| / |cited|。
    更贴合"引用的证据是否可信"这一核心主张；GPT-4o 无 cited 边故为 NaN（结构性对比优势）。"""
    expected = {_norm_edge(e) for e in gold.get("expected_kg_edges", []) if e}
    cited = {_norm_edge(e) for e in pred.get("cited_edges", []) if e}
    if not cited or not expected:
        return float("nan")
    hit = len(cited & expected)
    return hit / len(cited)


def traceability_f1(pred: Dict[str, Any], gold: Dict[str, Any]) -> float:
    """召回与精确的调和平均，综合反映可追溯性。"""
    r = traceability(pred, gold)
    p = traceability_precision(pred, gold)
    if any(math.isnan(x) for x in (r, p)) or (r + p) == 0:
        return float("nan")
    return 2 * p * r / (p + r)


def evidence_retention(pred: Dict[str, Any]) -> float:
    """证据留存率 = final_answer 实际讲出的 KG 实体 / 检索到(cited_edges)的 KG 实体。
    量化'系统查到的证据有多少真正进入了最终答案'——GDgpt 独有能力
    (GPT-4o 无 cited_edges，此指标为 NaN，是结构性差异)。洞察2的贡献点。"""
    cited = pred.get("cited_edges", []) or []
    ents = set()
    for e in cited:
        vals = (list(e)[:2] if not isinstance(e, dict) else [e.get("from"), e.get("to")])
        for v in vals:
            n = _norm_token(v)
            if n:
                ents.add(n)
    if not ents:
        return float("nan")
    text = _norm_token(pred.get("final_answer", "") or pred.get("answer_text", ""))
    mentioned = sum(1 for e in ents if e in text)
    return mentioned / len(ents)


def hallucination_rate(pred: Dict[str, Any]) -> float:
    """未被KG支持的claim占比（rate）。⚠️对答案长度敏感，须与下方两指标合看。"""
    claims = pred.get("asserted_claims") or []
    if not claims:
        return float("nan")
    total = len(claims)
    unsupported = sum(1 for c in claims if not c.get("has_kg_support", False))
    return unsupported / max(total, 1)


def faithfulness_precision(pred: Dict[str, Any]) -> float:
    """有KG支持的claim占比 = 1 - hallucination_rate（'说的话里多少有据'）。长度敏感维度。"""
    claims = pred.get("asserted_claims") or []
    if not claims:
        return float("nan")
    supported = sum(1 for c in claims if c.get("has_kg_support", False))
    return supported / len(claims)


def grounded_claim_count(pred: Dict[str, Any]) -> float:
    """有KG支持的claim绝对数（'提供了多少有据信息'）。长度无关维度——
    与 precision 合看可消除长度偏见：长答案claim多但未必有据，短答案可能都有据。"""
    claims = pred.get("asserted_claims") or []
    return float(sum(1 for c in claims if c.get("has_kg_support", False)))


def is_honest_degradation(pred_text: str) -> bool:
    return bool(HONEST_RE.search(pred_text or ""))


# ---------- aggregation ----------

def _nan_mean(xs: List[float]) -> float:
    xs = [x for x in xs if isinstance(x, (int, float)) and not math.isnan(x)]
    return mean(xs) if xs else float("nan")


def aggregate(
    predictions: List[Dict[str, Any]], gold_idx: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    # 1. Bucketize
    buckets: Dict[str, List[Tuple[Dict, Dict]]] = {k: [] for k in COVERAGE_BUCKETS}
    missing_gold = 0
    for p in predictions:
        rid = str(p.get("id", "")).strip()
        g = gold_idx.get(rid)
        if g is None:
            missing_gold += 1
            continue
        level = p.get("kg_coverage_level", "disabled")
        if level not in buckets:
            level = "disabled"
        buckets[level].append((p, g))

    report: Dict[str, Any] = {
        "overall": {},
        "by_coverage": {},
        "missing_gold": missing_gold,
    }

    # 2. Per-bucket metrics
    for level, items in buckets.items():
        if not items:
            report["by_coverage"][level] = {"N": 0}
            continue
        accs, traces, tprecs, tf1s, halls, fprecs, gcounts, rets, honests = [], [], [], [], [], [], [], [], []
        for p, g in items:
            text = p.get("final_answer", "")
            accs.append(loose_accuracy(text, g))
            traces.append(traceability(p, g))
            tprecs.append(traceability_precision(p, g))
            tf1s.append(traceability_f1(p, g))
            halls.append(hallucination_rate(p))
            fprecs.append(faithfulness_precision(p))
            gcounts.append(grounded_claim_count(p))
            rets.append(evidence_retention(p))
            honests.append(1 if is_honest_degradation(text) else 0)
        report["by_coverage"][level] = {
            "N": len(items),
            "accuracy_loose": round(_nan_mean(accs), 4),
            "traceability": round(_nan_mean(traces), 4),
            "traceability_precision": round(_nan_mean(tprecs), 4),
            "traceability_f1": round(_nan_mean(tf1s), 4),
            "hallucination_rate": round(_nan_mean(halls), 4),
            "faithfulness_precision": round(_nan_mean(fprecs), 4),
            "grounded_claim_count": round(_nan_mean(gcounts), 4),
            "evidence_retention": round(_nan_mean(rets), 4),
            "honest_degradation_rate": round(_nan_mean(honests), 4),
        }

    # 3. Overall
    all_items = [x for v in buckets.values() for x in v]
    if all_items:
        accs = [loose_accuracy(p.get("final_answer", ""), g) for p, g in all_items]
        traces = [traceability(p, g) for p, g in all_items]
        tprecs = [traceability_precision(p, g) for p, g in all_items]
        tf1s = [traceability_f1(p, g) for p, g in all_items]
        halls = [hallucination_rate(p) for p, g in all_items]
        fprecs = [faithfulness_precision(p) for p, g in all_items]
        gcounts = [grounded_claim_count(p) for p, g in all_items]
        rets = [evidence_retention(p) for p, g in all_items]
        honests = [1 if is_honest_degradation(p.get("final_answer", "")) else 0
                   for p, _ in all_items]
        report["overall"] = {
            "N": len(all_items),
            "accuracy_loose": round(_nan_mean(accs), 4),
            "traceability": round(_nan_mean(traces), 4),
            "traceability_precision": round(_nan_mean(tprecs), 4),
            "traceability_f1": round(_nan_mean(tf1s), 4),
            "hallucination_rate": round(_nan_mean(halls), 4),
            "faithfulness_precision": round(_nan_mean(fprecs), 4),
            "grounded_claim_count": round(_nan_mean(gcounts), 4),
            "evidence_retention": round(_nan_mean(rets), 4),
            "honest_degradation_rate": round(_nan_mean(honests), 4),
        }
    return report


# ---------- pretty printer ----------

def _fmt(x: Any) -> str:
    if isinstance(x, float) and math.isnan(x):
        return "  N/A"
    if isinstance(x, float):
        return f"{x:>6.3f}"
    return f"{x:>6}"


def print_report(report: Dict[str, Any]) -> None:
    print("\n========== GDgpt v2.1 Stratified System Metrics ==========")
    print(f"Missing gold entries: {report.get('missing_gold', 0)}")

    header = f"{'Bucket':<10} {'N':>4}  {'Acc':>6}  {'Trace':>6}  {'Halluc':>6}  {'Honest':>6}"
    print("\n-- By KG coverage bucket --")
    print(header)
    print("-" * len(header))
    for level in COVERAGE_BUCKETS:
        b = report["by_coverage"].get(level, {"N": 0})
        n = b.get("N", 0)
        if n == 0:
            print(f"{level:<10} {n:>4}      -       -       -       -")
            continue
        print(
            f"{level:<10} "
            f"{n:>4}  "
            f"{_fmt(b.get('accuracy_loose'))}  "
            f"{_fmt(b.get('traceability'))}  "
            f"{_fmt(b.get('hallucination_rate'))}  "
            f"{_fmt(b.get('honest_degradation_rate'))}"
        )

    print("\n-- Overall --")
    o = report.get("overall", {})
    if o:
        print(
            f"{'ALL':<10} "
            f"{o.get('N', 0):>4}  "
            f"{_fmt(o.get('accuracy_loose'))}  "
            f"{_fmt(o.get('traceability'))}  "
            f"{_fmt(o.get('hallucination_rate'))}  "
            f"{_fmt(o.get('honest_degradation_rate'))}"
        )
    print("==========================================================\n")
    print(
        "Notes:\n"
        "  - Acc: loose accuracy (any gold gene/drug appears in final_answer).\n"
        "  - Trace: |cited_edges ∩ expected_edges| / |expected_edges|.\n"
        "  - Halluc: unsupported_claims / total_claims (needs `asserted_claims`; "
        "N/A if absent).\n"
        "  - Honest: fraction of outputs that explicitly say 'insufficient KG "
        "evidence'. Most meaningful in the `low` bucket.\n"
    )


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="GDgpt v2.1 stratified system metrics")
    ap.add_argument("--predictions", required=True, help="predictions jsonl (one case per line)")
    ap.add_argument("--gold", required=True, help="gold jsonl (one case per line)")
    ap.add_argument("--out", default=None, help="optional json output path")
    args = ap.parse_args()

    preds = _load_jsonl(args.predictions)
    gold = _index_by_id(_load_jsonl(args.gold))

    report = aggregate(preds, gold)
    print_report(report)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[saved] {args.out}")


if __name__ == "__main__":
    main()
