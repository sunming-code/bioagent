#!/usr/bin/env python3
"""
从 Neo4j Task KG 中为独立测试集补充缺失的 gold 字段。

解决问题：
- disease-centered 和 gene-centered 题目缺少 gold_pathways
- 所有题目缺少 gold_phenotypes, gold_drugs, gold_bridge

用法：
  python evaluation/enrich_testset_gold.py \
    --input evaluation/independent_testset/output/testset_quick.jsonl \
    --output evaluation/independent_testset/output/testset_quick_enriched.jsonl
"""

import argparse
import json
from pathlib import Path
import sys

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def connect_neo4j(uri="neo4j://localhost:7687", user="neo4j", password="password"):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(uri, auth=(user, password))
    # 验证连接
    with driver.session() as session:
        session.run("RETURN 1")
    return driver


def query_disease_to_pathways(session, disease_name: str, k: int = 10) -> list:
    """Disease → Gene → Pathway (Bridge 查询)"""
    result = session.run("""
        MATCH (d:Disease)-[:ASSOCIATED_WITH]-(g:Gene)-[:INVOLVED_IN]-(p:Pathway)
        WHERE toLower(d.name) CONTAINS toLower($disease)
           OR toLower(d.normalized_name) CONTAINS toLower($disease)
        WITH p.name AS pathway, collect(DISTINCT g.name) AS genes, count(DISTINCT g) AS gene_count
        RETURN pathway, genes[0..5] AS sample_genes, gene_count
        ORDER BY gene_count DESC
        LIMIT $k
    """, disease=disease_name, k=k)
    return [r["pathway"] for r in result]


def query_disease_to_phenotypes(session, disease_name: str, k: int = 10) -> list:
    """Disease → Phenotype"""
    result = session.run("""
        MATCH (d:Disease)-[:HAS_PHENOTYPE]-(p:Phenotype)
        WHERE toLower(d.name) CONTAINS toLower($disease)
           OR toLower(d.normalized_name) CONTAINS toLower($disease)
        RETURN DISTINCT p.name AS phenotype
        LIMIT $k
    """, disease=disease_name, k=k)
    return [r["phenotype"] for r in result]


def query_disease_to_drugs(session, disease_name: str, k: int = 10) -> list:
    """Disease → Drug"""
    result = session.run("""
        MATCH (d:Disease)-[:TREATS|INDICATED_FOR]-(dr:Drug)
        WHERE toLower(d.name) CONTAINS toLower($disease)
           OR toLower(d.normalized_name) CONTAINS toLower($disease)
        RETURN DISTINCT dr.name AS drug
        LIMIT $k
    """, disease=disease_name, k=k)
    return [r["drug"] for r in result]


def query_gene_to_pathways(session, gene_name: str, k: int = 10) -> list:
    """Gene → Pathway"""
    result = session.run("""
        MATCH (g:Gene)-[:INVOLVED_IN]-(p:Pathway)
        WHERE toLower(g.name) = toLower($gene)
        RETURN DISTINCT p.name AS pathway
        LIMIT $k
    """, gene=gene_name, k=k)
    return [r["pathway"] for r in result]


def query_gene_to_diseases(session, gene_name: str, k: int = 10) -> list:
    """Gene → Disease"""
    result = session.run("""
        MATCH (g:Gene)-[:ASSOCIATED_WITH]-(d:Disease)
        WHERE toLower(g.name) = toLower($gene)
        RETURN DISTINCT d.name AS disease
        LIMIT $k
    """, gene=gene_name, k=k)
    return [r["disease"] for r in result]


def query_pathway_to_phenotypes(session, pathway_genes: list, k: int = 10) -> list:
    """通过 pathway 的 genes 间接查 phenotype: Gene → Disease → Phenotype"""
    if not pathway_genes:
        return []
    result = session.run("""
        UNWIND $genes AS gene_name
        MATCH (g:Gene)-[:ASSOCIATED_WITH]-(d:Disease)-[:HAS_PHENOTYPE]-(p:Phenotype)
        WHERE toLower(g.name) = toLower(gene_name)
        RETURN DISTINCT p.name AS phenotype
        LIMIT $k
    """, genes=pathway_genes[:5], k=k)
    return [r["phenotype"] for r in result]


def enrich_row(session, row: dict) -> dict:
    """为一条测试数据补充缺失的 gold 字段"""
    task_type = row.get("task_type", "")
    enriched = dict(row)

    if task_type == "disease-centered":
        disease = row.get("disease_focus", "")
        if disease:
            # 补充 gold_pathways
            if not enriched.get("gold_pathways"):
                enriched["gold_pathways"] = query_disease_to_pathways(session, disease)
            # 补充 gold_phenotypes
            if not enriched.get("gold_phenotypes"):
                enriched["gold_phenotypes"] = query_disease_to_phenotypes(session, disease)
            # 补充 gold_drugs
            if not enriched.get("gold_drugs"):
                enriched["gold_drugs"] = query_disease_to_drugs(session, disease)
            # gold_bridge: disease-centered 有 pathway 就设 True
            enriched["gold_bridge"] = bool(enriched.get("gold_pathways"))

    elif task_type == "gene-centered":
        gene = row.get("gene_focus", "")
        if gene:
            # 补充 gold_pathways
            if not enriched.get("gold_pathways"):
                enriched["gold_pathways"] = query_gene_to_pathways(session, gene)
            # 补充 gold_diseases（如果没有）
            if not enriched.get("gold_diseases"):
                enriched["gold_diseases"] = query_gene_to_diseases(session, gene)
            # gold_bridge: gene-centered 如果有 pathway 就设 True
            enriched["gold_bridge"] = bool(enriched.get("gold_pathways"))

    elif task_type == "pathway-centered":
        # pathway-centered 已经有 gold_pathways
        # 补充 phenotypes（通过 genes 间接查）
        genes = row.get("gold_genes", [])
        if not enriched.get("gold_phenotypes"):
            enriched["gold_phenotypes"] = query_pathway_to_phenotypes(session, genes)
        enriched["gold_bridge"] = True  # pathway 题默认 bridge=True

    return enriched


def main():
    parser = argparse.ArgumentParser(description="从 Neo4j 补充测试集的 gold 字段")
    parser.add_argument("--input", required=True, help="输入 JSONL 路径")
    parser.add_argument("--output", required=True, help="输出 JSONL 路径")
    parser.add_argument("--neo4j-uri", default="neo4j://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    args = parser.parse_args()

    print("连接 Neo4j...")
    driver = connect_neo4j(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    print("✓ Neo4j 连接成功")

    rows = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    print(f"读取 {len(rows)} 条测试数据")

    enriched_rows = []
    with driver.session() as session:
        for i, row in enumerate(rows, 1):
            enriched = enrich_row(session, row)
            enriched_rows.append(enriched)

            # 打印进度
            pathways = enriched.get("gold_pathways", [])
            phenotypes = enriched.get("gold_phenotypes", [])
            drugs = enriched.get("gold_drugs", [])
            bridge = enriched.get("gold_bridge", False)
            print(f"  [{i}/{len(rows)}] {row['id']} ({row['task_type']}): "
                  f"pathways={len(pathways)}, phenotypes={len(phenotypes)}, "
                  f"drugs={len(drugs)}, bridge={bridge}")

    driver.close()

    # 写入输出
    with open(args.output, "w", encoding="utf-8") as f:
        for row in enriched_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 统计
    has_pathways = sum(1 for r in enriched_rows if r.get("gold_pathways"))
    has_phenotypes = sum(1 for r in enriched_rows if r.get("gold_phenotypes"))
    has_drugs = sum(1 for r in enriched_rows if r.get("gold_drugs"))
    has_bridge = sum(1 for r in enriched_rows if r.get("gold_bridge"))

    print(f"\n=== 补充后统计 ===")
    print(f"gold_pathways:   {has_pathways}/{len(enriched_rows)}")
    print(f"gold_phenotypes: {has_phenotypes}/{len(enriched_rows)}")
    print(f"gold_drugs:      {has_drugs}/{len(enriched_rows)}")
    print(f"gold_bridge:     {has_bridge}/{len(enriched_rows)}")
    print(f"\n✓ 已保存到 {args.output}")


if __name__ == "__main__":
    main()
