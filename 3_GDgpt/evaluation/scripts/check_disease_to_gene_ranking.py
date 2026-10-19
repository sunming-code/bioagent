#!/usr/bin/env python3
"""DiseaseToGene 排序回归检查（红先行）。

判据：对 3 个疾病，DiseaseToGene 返回的 top-k 里**至少要有 1 个 gold 基因**。

修复前为什么必失败：ASSOCIATED_WITH 的 r.weight 在全库都是空字符串（不是 0，也不是
null，见 logs/kg_schema_recon.log），所以 `coalesce(r.weight, 0.0)` 返回 ''，
`ORDER BY weight DESC, gene ASC` 的主键恒定、退化成纯字母序。521-1156 个邻居里
只有 2/300 个 gold 基因落在字母序 top-8 内，这 3 个疾病一个都没有。

跑的是 live 只读 Cypher（走 tools.py 真实查询路径），不改 KG。

用法（仓库根目录）：python3 evaluation/scripts/check_disease_to_gene_ranking.py
退出码 0 = 通过，1 = 失败。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO_ROOT)

GOLD = os.path.join(REPO_ROOT, "evaluation", "independent_testset", "output",
                    "testset_kg_optimized_enriched_with_edges.jsonl")

# 只取金标来源是 "Open Targets + PrimeKG cross-validated" 的疾病。
#
# 为什么要排除另外 9 题：它们的金标来源是 "PrimeKG (no OT match)"，是从邻居里
# 近乎任意取的 20 个基因 —— colorectal cancer 的金标里没有 APC / KRAS / TP53 /
# BRAF，却有 MIR1273C、KRTAP10-8、LINC00673、TMEM238L。对这些题，"top-k 里有
# 金标基因" 不是检索质量的判据：任何生物学上更正确的排序都会被判 0 分。拿它们
# 当判据只会逼着排序去拟合一个任意名单。这不是放宽判据，而是把判据放回它能
# 说明问题的那 6 题上；分层证据见 logs/gene_ranking_probe.log。
REQUIRED_PROVENANCE = "Open Targets + PrimeKG cross-validated"
DISEASES = [
    "hereditary breast ovarian cancer syndrome",   # 1156 邻居
    "prostate cancer",                             #  616 邻居
    "hepatocellular carcinoma",                    #  614 邻居
]


def _run(kg, cypher, params):
    """按 tools.py 自己的判断选 HTTP 还是 Bolt，别把检查钉死在 Aura 上。

    Aura 走 HTTP Query API（公司网络封 7687），但 README 里的本地 Neo4j 是
    bolt://localhost:7687；硬写 _http_run 会让这个检查在本地配置下直接崩。
    """
    if kg._use_http():
        return kg._http_run(cypher, params)
    kg._ensure_driver()
    database = (kg.conf.get("database") or "").strip() or None
    with kg._driver.session(database=database) as session:
        return session.run(cypher, params).data()


def load_gold():
    """disease_focus -> (gold_genes, provenance)"""
    out = {}
    with open(GOLD, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("disease_focus"):
                out.setdefault(row["disease_focus"],
                               (row.get("gold_genes", []), row.get("source", "?")))
    return out


def main():
    from utils import load_config
    from tools import Neo4jKGTool

    cfg = load_config()
    kg = Neo4jKGTool({
        "uri": cfg.get("neo4j_uri", ""), "user": cfg.get("neo4j_user", ""),
        "password": cfg.get("neo4j_password", ""), "database": cfg.get("neo4j_database", ""),
    })
    gold_map = load_gold()

    # 走 tools.py 真实的 intent -> Cypher 构造路径，而不是在检查里另写一条查询
    k = 8
    failures = []
    print("k = %d (unchanged)   path: Neo4jKGTool._build_query('DiseaseToGene')" % k)
    print()
    for disease in DISEASES:
        entry = gold_map.get(disease)
        if not entry:
            print("FAIL: no gold_genes for %r in the testset" % disease)
            return 1
        gold, provenance = entry
        # 判据只在金标可信时才成立，所以把来源也钉住：万一测试集换了来源，
        # 这个检查要当场报错，而不是悄悄在一个任意名单上继续"通过"。
        if provenance != REQUIRED_PROVENANCE:
            print("FAIL: %r gold provenance is %r, expected %r"
                  % (disease, provenance, REQUIRED_PROVENANCE))
            return 1
        cypher, params, _label, _cols = kg._build_query(
            {"intent": "DiseaseToGene", "disease": disease, "k": k})
        rows = _run(kg, cypher, params)
        got = [r["gene"] for r in rows]
        if len(set(got)) != len(got):
            # CSV 双向存边，无向 MATCH 会把每个 disease-gene 对匹配两次；
            # 不去重的话 LIMIT 8 实际只有 4 个不同基因。
            print("  FAIL  %-52s duplicate genes in top-%d: %s" % (disease[:52], k, got))
            failures.append(disease + " (duplicates)")
            print()
            continue
        hits = [g for g in got if g in set(gold)]
        ok = len(hits) >= 1
        print("  %-5s %-52s top-%d=%s" % ("ok" if ok else "FAIL", disease[:52], k, got))
        print("        gold hits in top-%d: %d %s" % (k, len(hits), hits or ""))
        if not ok:
            failures.append(disease)
        print()

    if failures:
        print("RESULT: FAIL - no gold gene in top-%d for %d/%d diseases: %s"
              % (k, len(failures), len(DISEASES), failures))
        return 1
    print("RESULT: PASS - every one of the %d diseases has >=1 gold gene in top-%d"
          % (len(DISEASES), k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
