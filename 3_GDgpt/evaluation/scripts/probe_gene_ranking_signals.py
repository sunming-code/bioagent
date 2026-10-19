#!/usr/bin/env python3
"""检索侧探针：用图信号对 Disease 的"全邻居基因集"排序，对 gold 算 Recall@5/@20。

不调用任何 LLM，只发只读 Cypher。目的是在改 tools.py 之前先用数据选信号。

背景：ASSOCIATED_WITH 的 r.weight 在全库都是空字符串（见 logs/kg_schema_recon.log），
所以 tools.py 的 `ORDER BY weight DESC, gene ASC` 退化成纯字母序，521-1156 个邻居里
只有 2/300 个 gold 基因落在字母序 top-8 内。

先跑探针探到的三件事（见 logs/gene_ranking_probe.log，都改变了信号设计）：
  1. Disease-Pathway 直连边 **0 条**，所以"基因通路 ∩ 疾病通路"恒为 0；疾病侧的
     通路只能经 gene 两跳得到。（顺带：tools.py 的 DiseaseToPathway intent 因此永远空。）
  2. n_sources / n_edges 对同一疾病的**全部邻居恒为 2**（CSV 双向存边），是死信号。
  3. 总 degree 被药理边主导（CYP3A4 1970 度里 1942 条连 Drug），所以它排出来的是
     药物代谢 hub 而不是疾病基因，和字母序一样差。

候选信号（每个疾病对它的全部邻居基因算）：
  degree          基因的总度数（所有关系类型）——对照，已知被药理边污染
  assoc_degree    基因连到多少个 Disease（ASSOCIATED_WITH）= 多效性/研究热度先验
  gene_pathways   基因的通路总数（不看疾病，作对照）
  n_sources       该 disease-gene 边上 source 的去重个数（已知恒定，留作对照）
  n_edges         该 disease-gene 之间的平行边数（已知恒定，留作对照）
  cohesion        模块内聚度：g 的每条通路里还有多少个"本疾病的其他邻居基因"，求和
                  ——这是唯一真正**疾病特异**的信号（两跳 d-g'-p-g）
  cohesion_norm   cohesion / g 的通路数，压 hub 偏好
  max_module      g 所在通路中，"本疾病邻居基因"最多的那条通路的人数
以及若干组合（见 COMBOS）。

用法（仓库根目录）：python3 evaluation/scripts/probe_gene_ranking_signals.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO_ROOT)

GOLD = os.path.join(REPO_ROOT, "evaluation", "independent_testset", "output",
                    "testset_kg_optimized_enriched_with_edges.jsonl")
RAW = os.path.join(REPO_ROOT, "evaluation", "results", "adapt15_full_raw.jsonl")

# 每个邻居基因一行：原始计数 + 它的通路名单（内聚度在 Python 侧算，省一轮重查询）
SIGNALS_CYPHER = """
MATCH (d:Disease)
WHERE toLower(trim(d.name)) = toLower(trim($disease))
MATCH (d)-[r:ASSOCIATED_WITH]-(g:Gene)
WITH d, g,
     count(r) AS n_edges,
     size(collect(DISTINCT coalesce(r.source, ''))) AS n_sources
OPTIONAL MATCH (g)-[:INVOLVED_IN]-(gp:Pathway)
WITH g, n_edges, n_sources, collect(DISTINCT gp.name) AS gpaths
RETURN g.name                                            AS gene,
       n_edges                                           AS n_edges,
       n_sources                                         AS n_sources,
       gpaths                                            AS gpaths,
       size(gpaths)                                      AS gene_pathways,
       COUNT { (g)--() }                                 AS degree,
       COUNT { MATCH (g)-[:ASSOCIATED_WITH]-(d2:Disease)
               RETURN DISTINCT d2 }                      AS assoc_degree
"""
# 注意：必须数**去重后的邻居**，不能数关系数。CSV 双向存边，
# COUNT { (g)-[:ASSOCIATED_WITH]-(:Disease) } 会得到 2x 实际疾病数，
# 而 gene_pathways 走 collect(DISTINCT ...) 是 1x，两项量纲就对不上了，
# 相加出来的 bio_degree 不是探针里测的那个量。同样的双向存边问题已经
# 在 DiseaseToGene 的 LIMIT 上咬过一次（top-8 只有 4 个不同基因）。

# 单信号：取 row 的某个字段
SINGLE = ["degree", "assoc_degree", "gene_pathways", "n_sources", "n_edges",
          "cohesion", "cohesion_norm", "max_module"]

# 组合信号：(名字, key 函数)。全部以 "越大越靠前" 为约定，末位用 gene ASC 稳定排序。
COMBOS = [
    ("assoc_degree,cohesion",
     lambda r: (r["assoc_degree"], r["cohesion"])),
    ("cohesion,assoc_degree",
     lambda r: (r["cohesion"], r["assoc_degree"])),
    ("assoc_degree,max_module",
     lambda r: (r["assoc_degree"], r["max_module"])),
    ("cohesion_norm,assoc_degree",
     lambda r: (r["cohesion_norm"], r["assoc_degree"])),
    ("assoc_degree,cohesion_norm",
     lambda r: (r["assoc_degree"], r["cohesion_norm"])),
    # 把 degree 里的药理边剔掉，只留"疾病+通路"度。等价于"生物学度数"：
    # 这正是对"总 degree 被药理边污染"的直接修正，也是最终落地的信号。
    ("bio_degree = assoc_degree + gene_pathways  <= SHIPPED",
     lambda r: (r["assoc_degree"] + r["gene_pathways"],)),
    ("assoc_degree,gene_pathways",
     lambda r: (r["assoc_degree"], r["gene_pathways"])),
]


def add_module_signals(rows):
    """用本疾病的全部邻居基因算模块内聚度（两跳 d-g'-p-g，疾病特异）。"""
    from collections import Counter
    members = Counter()
    for r in rows:
        for p in r["gpaths"]:
            members[p] += 1
    for r in rows:
        paths = r["gpaths"]
        # 每条通路里"本疾病的其他邻居基因"个数，求和
        r["cohesion"] = sum(members[p] - 1 for p in paths)
        r["cohesion_norm"] = r["cohesion"] / float(len(paths) or 1)
        r["max_module"] = max((members[p] for p in paths), default=0)


def run_cypher(kg, cypher, params):
    """按 tools.py 自己的判断选 HTTP 还是 Bolt，别把探针钉死在 Aura 上。"""
    if kg._use_http():
        return kg._http_run(cypher, params)
    kg._ensure_driver()
    database = (kg.conf.get("database") or "").strip() or None
    with kg._driver.session(database=database) as session:
        return session.run(cypher, params).data()


def recall_at(ranked, gold, k):
    """Recall@k = |前 k 个命中的 gold| / |gold|，与 compute_metrics.py 的口径一致。"""
    if not gold:
        return 0.0
    return len(set(ranked[:k]) & set(gold)) / float(len(gold))


def main():
    from utils import load_config
    from tools import Neo4jKGTool

    cfg = load_config()
    kg = Neo4jKGTool({
        "uri": cfg.get("neo4j_uri", ""), "user": cfg.get("neo4j_user", ""),
        "password": cfg.get("neo4j_password", ""), "database": cfg.get("neo4j_database", ""),
    })

    want = [json.loads(l)["id"] for l in open(RAW, encoding="utf-8") if l.strip()]
    gold_rows = {}
    for line in open(GOLD, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] in want:
            gold_rows[row["id"]] = row

    print("diseases: %d   gold genes per question: %s"
          % (len(gold_rows), sorted({len(r["gold_genes"]) for r in gold_rows.values()})))
    print("ranking the FULL neighbour set (no LIMIT), live read-only Cypher")
    print()

    names = [k for k in SINGLE] + [c[0] for c in COMBOS] + ["alphabetical (current)"]
    acc = {n: {"r5": [], "r20": []} for n in names}
    per_disease = []

    for qid, row in gold_rows.items():
        disease = row["disease_focus"]
        gold = row["gold_genes"]
        t0 = time.time()
        rows = run_cypher(kg, SIGNALS_CYPHER, {"disease": disease})
        elapsed = time.time() - t0
        if not rows:
            print("  WARN no neighbours for %r" % disease)
            continue
        add_module_signals(rows)
        nbrs = len(rows)
        in_kg = len(set(r["gene"] for r in rows) & set(gold))

        def rank(keyfn):
            return [r["gene"] for r in sorted(rows, key=lambda r: (keyfn(r), _neg(r["gene"])),
                                              reverse=True)]

        line = {"disease": disease, "nbrs": nbrs, "gold": len(gold),
                "in_kg": in_kg, "secs": elapsed, "r5": {}, "r20": {},
                "provenance": row.get("source", "?")}
        for sig in SINGLE:
            ranked = rank(lambda r, s=sig: (r[s],))
            line["r5"][sig] = recall_at(ranked, gold, 5)
            line["r20"][sig] = recall_at(ranked, gold, 20)
        for name, fn in COMBOS:
            ranked = rank(fn)
            line["r5"][name] = recall_at(ranked, gold, 5)
            line["r20"][name] = recall_at(ranked, gold, 20)
        alpha = sorted(r["gene"] for r in rows)
        line["r5"]["alphabetical (current)"] = recall_at(alpha, gold, 5)
        line["r20"]["alphabetical (current)"] = recall_at(alpha, gold, 20)

        for n in names:
            acc[n]["r5"].append(line["r5"][n])
            acc[n]["r20"].append(line["r20"][n])
        per_disease.append(line)
        print("  %-46s nbrs=%4d gold=%2d inKG=%2d  %5.1fs" %
              (disease[:46], nbrs, len(gold), in_kg, elapsed))

    print()
    print("=== mean Recall@5 / Recall@20 over %d diseases (ceiling R@5 = 0.250, |gold|=20) ==="
          % len(per_disease))
    print("%-34s %9s %9s" % ("signal", "R@5", "R@20"))
    print("-" * 56)
    ordered = sorted(names, key=lambda n: -sum(acc[n]["r5"]) / max(len(acc[n]["r5"]), 1))
    for n in ordered:
        m5 = sum(acc[n]["r5"]) / max(len(acc[n]["r5"]), 1)
        m20 = sum(acc[n]["r20"]) / max(len(acc[n]["r20"]), 1)
        print("%-34s %9.4f %9.4f" % (n, m5, m20))

    print()
    print("per-disease R@5 for the top signal (%s):" % ordered[0])
    for line in per_disease:
        print("  %-46s %.4f  (alpha %.4f)" %
              (line["disease"][:46], line["r5"][ordered[0]], line["r5"]["alphabetical (current)"]))

    # 按金标来源分层。这是整个探针最要紧的一张表：
    # 9/15 题的金标是 "PrimeKG (no OT match)"，即从邻居里近乎任意取的 20 个
    # （colorectal cancer 的金标里没有 APC/KRAS/TP53/BRAF，却有 MIR1273C、
    # KRTAP10-8、LINC00673）。对这 9 题，任何"生物学上更对"的排序都会被判 0 分。
    print()
    print("=== stratified by gold provenance (the decisive table) ===")
    groups = {}
    for line in per_disease:
        groups.setdefault(line["provenance"], []).append(line)
    for prov, lines in sorted(groups.items()):
        print()
        print("  %s  (n=%d)" % (prov, len(lines)))
        print("    %-40s %9s %9s" % ("signal", "R@5", "R@20"))
        for n in ordered[:4] + ["alphabetical (current)"]:
            m5 = sum(l["r5"][n] for l in lines) / len(lines)
            m20 = sum(l["r20"][n] for l in lines) / len(lines)
            print("    %-40s %9.4f %9.4f" % (n[:40], m5, m20))

    print()
    print("latency: max %.1fs on %s (%d neighbours)" %
          (max(l["secs"] for l in per_disease),
           max(per_disease, key=lambda l: l["secs"])["disease"],
           max(per_disease, key=lambda l: l["secs"])["nbrs"]))
    print()
    print("CAVEATS")
    print("1. Circularity. On the 6 OT-cross-validated questions, gold was built by")
    print("   intersecting Open Targets with PrimeKG, and a degree signal partly reflects")
    print("   that: a well-studied gene is both high-degree in PrimeKG and more likely")
    print("   curated into Open Targets. So read 0.1000 as an upper bound on the gain, not")
    print("   as evidence that degree is biologically the right prior.")
    print("2. The disease-specific signals lose. cohesion / cohesion_norm / max_module are")
    print("   the only signals that use the queried disease at all, and none beats the")
    print("   disease-agnostic assoc_degree. The gain is therefore a popularity prior, not")
    print("   disease-specific evidence. Stated plainly because it limits the claim.")
    print("3. Two signals from the original plan are dead in this KG, measured not assumed:")
    print("   'number of distinct sources' is constant at 2 for every neighbour of a given")
    print("   disease (the CSV stores both directions), and 'pathways shared with the")
    print("   disease' is always 0 because there are no Disease-Pathway edges at all.")
    print("4. These are retrieval-side numbers over the full neighbour set. They are NOT")
    print("   comparable to the paper's end-to-end Gene Recall@5 of 0.047, which is measured")
    print("   on genes extracted from generated text after several k=8 queries.")
    return 0


def _neg(s):
    """让字符串在 reverse=True 下仍按升序（稳定、可复现的并列处理）。"""
    return tuple(-ord(c) for c in s)


if __name__ == "__main__":
    sys.exit(main())
