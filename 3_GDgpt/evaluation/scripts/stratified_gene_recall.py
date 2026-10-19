#!/usr/bin/env python3
"""端到端 Gene Recall@k，按金标来源分层。

人已决定：Recall@5 与 Recall@20 既报全部 15 题的总值，也单独报金标经 Open Targets
交叉核验的那 6 题，并说清另外 9 题的金标为什么无法奖励更好的检索。不许丢题，
不许重做金标。本脚本就是出这张表的。

两种 recall 定义都算，因为仓库里两个脚本定义不同，而论文的 0.047 来自后者：
  @k      compute_metrics.py 的口径：预测列表先截断到前 k 个再比
  nocut   compute_paired_stats.py 的口径：不截断，拿全部预测基因比
（论文把 nocut 的 0.047 写成了 "Recall@5"。）

用法（仓库根目录）：
  python3 evaluation/scripts/stratified_gene_recall.py <extracted.jsonl> [<extracted.jsonl> ...]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))

GOLD = os.path.join(REPO_ROOT, "evaluation", "independent_testset", "output",
                    "testset_kg_optimized_enriched_with_edges.jsonl")
OT = "Open Targets + PrimeKG cross-validated"


def norm(s):
    return str(s or "").strip().upper()


def load_gold():
    out = {}
    with open(GOLD, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            out[r["id"]] = r
    return out


def recall(gold_genes, pred_genes, k=None):
    g = {norm(x) for x in gold_genes if norm(x)}
    if not g:
        return None
    p = [norm(x) for x in pred_genes if norm(x)]
    if k is not None:
        p = p[:k]
    return len(g & set(p)) / float(len(g))


def report(path, gold):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    groups = {OT: [], "PrimeKG (no OT match)": []}
    for r in rows:
        g = gold.get(r["id"])
        if not g:
            continue
        prov = g.get("source", "?")
        groups.setdefault(prov, []).append((g, r))

    print()
    print("=" * 78)
    print("FILE: %s   (n=%d)" % (os.path.relpath(path, REPO_ROOT), len(rows)))
    print("=" * 78)
    print("%-34s %6s %9s %9s %9s" % ("stratum", "n", "R@5", "R@20", "R nocut"))
    print("-" * 72)

    def line(label, pairs):
        if not pairs:
            return
        r5, r20, rn = [], [], []
        for g, r in pairs:
            pg = r.get("predicted_genes") or []
            for acc, k in ((r5, 5), (r20, 20), (rn, None)):
                v = recall(g.get("gold_genes", []), pg, k)
                if v is not None:
                    acc.append(v)
        m = lambda a: (sum(a) / len(a)) if a else float("nan")
        print("%-34s %6d %9.4f %9.4f %9.4f" % (label, len(pairs), m(r5), m(r20), m(rn)))

    line("ALL 15 questions", [p for ps in groups.values() for p in ps])
    line("  OT cross-validated gold", groups.get(OT, []))
    line("  PrimeKG, no OT match", groups.get("PrimeKG (no OT match)", []))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    gold = load_gold()
    for path in sys.argv[1:]:
        report(path, gold)
    print()
    print("Why the 'no OT match' stratum cannot reward better retrieval: its gold is a")
    print("near-arbitrary sample of the disease's KG neighbours, not a curated gene list.")
    print("Colorectal cancer gold, for instance, carries MIR1273C, KRTAP10-8, LINC00673 and")
    print("TMEM238L but neither APC, KRAS, TP53 nor BRAF. A ranking that surfaces real")
    print("drivers therefore scores 0 there by construction. Both strata are reported and")
    print("no question is dropped, per the human's decision.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
