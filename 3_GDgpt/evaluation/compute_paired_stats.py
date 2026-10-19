"""
小样本配对统计：GDgpt vs baseline 的逐题配对比较。
用于撑起小样本(N~15)的可信度——skill/文献(NEJM AI 38例)都强调小N必须配对统计+CI。

方法(纯numpy实现,不依赖scipy):
- Wilcoxon 符号秩检验(配对非参数,适合小N非正态)：检验两系统某指标的逐题差异是否显著。
- Bootstrap 置信区间：对配对差值重采样,给出均值差的95% CI。
- 同时报 effect size(中位数差)。

用法:
  python evaluation/compute_paired_stats.py \
    --a evaluation/results/adapt15_full_ext.jsonl \
    --b evaluation/results/exp15_gpt4o_ext.jsonl \
    --gold evaluation/independent_testset/output/testset_kg_optimized_enriched_with_edges.jsonl \
    --metric pathway_f1
（metric 支持: gene_recall / pathway_f1 / bridge_hit / traceability）
"""

import argparse
import json
import math
import numpy as np


def load_by_id(path):
    d = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            r = json.loads(line)
            d[str(r.get("id"))] = r
    return d


def _norm(s):
    return str(s or "").strip().lower()


def per_item_metric(pred, gold, metric):
    """单题指标值(0-1)。"""
    gp = set(_norm(x) for x in gold.get("gold_genes", []))
    gpath = set(_norm(x) for x in gold.get("gold_pathways", []))
    pgenes = set(_norm(x) for x in pred.get("predicted_genes", []))
    ppath = set(_norm(x) for x in pred.get("predicted_pathways", []))

    if metric == "gene_recall":
        return len(gp & pgenes) / len(gp) if gp else float("nan")
    if metric == "pathway_f1":
        if not gpath and not ppath:
            return float("nan")
        tp = len(gpath & ppath)
        prec = tp / len(ppath) if ppath else 0.0
        rec = tp / len(gpath) if gpath else 0.0
        return 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    if metric == "bridge_hit":
        return 1.0 if pred.get("bridge_found") else 0.0
    if metric == "traceability":
        exp = {tuple(sorted([_norm(e[0]), _norm(e[1])]) + [_norm(e[2])])
               for e in gold.get("expected_kg_edges", []) if e}
        cit = {tuple(sorted([_norm(e[0]), _norm(e[1])]) + [_norm(e[2])])
               for e in pred.get("cited_edges", []) if e}
        return len(cit & exp) / len(exp) if exp else float("nan")
    raise ValueError(metric)


def wilcoxon_signed_rank(diffs):
    """纯numpy Wilcoxon符号秩检验,返回(W统计量, 近似p值)。剔除0差值。"""
    d = np.array([x for x in diffs if not math.isnan(x) and x != 0.0], dtype=float)
    n = len(d)
    if n < 1:
        return float("nan"), float("nan")
    ranks = np.argsort(np.argsort(np.abs(d))) + 1  # 秩(简化,未处理并列)
    w_plus = ranks[d > 0].sum()
    w_minus = ranks[d < 0].sum()
    W = min(w_plus, w_minus)
    # 正态近似(n>=10较准;小n仅供参考)
    mean_w = n * (n + 1) / 4
    std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if std_w == 0:
        return W, float("nan")
    z = (W - mean_w) / std_w
    # 双尾p(正态近似)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return float(W), float(p)


def bootstrap_ci(diffs, n_boot=10000, seed=0):
    """配对差值均值的95% bootstrap CI。"""
    d = np.array([x for x in diffs if not math.isnan(x)], dtype=float)
    if len(d) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = [rng.choice(d, size=len(d), replace=True).mean() for _ in range(n_boot)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="系统A预测(如GDgpt)")
    ap.add_argument("--b", required=True, help="系统B预测(如GPT-4o)")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--metric", default="pathway_f1",
                    choices=["gene_recall", "pathway_f1", "bridge_hit", "traceability"])
    args = ap.parse_args()

    A = load_by_id(args.a)
    B = load_by_id(args.b)
    G = load_by_id(args.gold)
    ids = [i for i in A if i in B and i in G]

    a_vals, b_vals, diffs = [], [], []
    for i in ids:
        va = per_item_metric(A[i], G[i], args.metric)
        vb = per_item_metric(B[i], G[i], args.metric)
        if math.isnan(va) or math.isnan(vb):
            continue
        a_vals.append(va); b_vals.append(vb); diffs.append(va - vb)

    n = len(diffs)
    if n == 0:
        print("无可配对样本"); return
    ma, mb = np.mean(a_vals), np.mean(b_vals)
    med_diff = np.median(diffs)
    W, p = wilcoxon_signed_rank(diffs)
    lo, hi = bootstrap_ci(diffs)

    print(f"=== 配对统计: {args.metric} (N={n}) ===")
    print(f"  系统A均值: {ma:.4f}")
    print(f"  系统B均值: {mb:.4f}")
    print(f"  配对差值(A-B) 均值: {np.mean(diffs):.4f}, 中位数: {med_diff:.4f}")
    print(f"  Wilcoxon 符号秩: W={W:.1f}, p≈{p:.4f} {'(显著 p<0.05)' if p < 0.05 else '(未达显著,小样本常见)'}")
    print(f"  差值均值 95% bootstrap CI: [{lo:.4f}, {hi:.4f}] {'(不含0→稳健)' if lo > 0 or hi < 0 else '(含0)'}")
    print(f"  ⚠️ N={n} 为 pilot/feasibility 规模,p值正态近似仅供参考;主看效应量+CI+案例。")


if __name__ == "__main__":
    main()
