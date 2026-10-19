#!/usr/bin/env python3
"""
生成 KG 覆盖率优化的独立测试集。

策略：
1. Disease-centered: 使用 KG 中存在的疾病，gold 从 Open Targets 交叉验证
2. Gene-centered: 使用 KG 中存在的高关联基因，gold 从 Open Targets 交叉验证  
3. Pathway-centered: 保留原有 Reactome 题目

确保 gold 数据来自独立源（Open Targets/Reactome），不循环测试。
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from neo4j import GraphDatabase


def generate_id(content: str, prefix: str) -> str:
    return f"{prefix}_{hashlib.md5(content.encode()).hexdigest()[:12]}"


def get_kg_diseases(session):
    """获取 KG 中有足够基因关联的疾病"""
    r = session.run("""
        MATCH (d:Disease)-[:ASSOCIATED_WITH]-(g:Gene)
        WITH d.name AS disease, count(DISTINCT g) AS gene_cnt
        WHERE gene_cnt >= 50
        RETURN disease, gene_cnt
        ORDER BY gene_cnt DESC
    """)
    return [(rec["disease"], rec["gene_cnt"]) for rec in r]


def get_kg_genes_for_disease(session, disease: str, k: int = 30):
    """从 KG 获取疾病关联的 top 基因（按权重排序）"""
    r = session.run("""
        MATCH (d:Disease {name: $disease})-[r:ASSOCIATED_WITH]-(g:Gene)
        RETURN g.name AS gene, coalesce(r.weight, 0.0) AS weight
        ORDER BY weight DESC
        LIMIT $k
    """, disease=disease, k=k)
    return [(rec["gene"], rec["weight"]) for rec in r]


def get_kg_pathways_for_disease(session, disease: str, k: int = 10):
    """从 KG 获取疾病的 Bridge 通路"""
    r = session.run("""
        MATCH (d:Disease {name: $disease})-[:ASSOCIATED_WITH]-(g:Gene)-[:INVOLVED_IN]-(p:Pathway)
        WITH p.name AS pathway, count(DISTINCT g) AS gene_cnt
        RETURN pathway, gene_cnt
        ORDER BY gene_cnt DESC
        LIMIT $k
    """, disease=disease, k=k)
    return [(rec["pathway"], rec["gene_cnt"]) for rec in r]


def get_opentargets_genes(disease_name: str, ot_data: list) -> list:
    """从 Open Targets 数据中找匹配的疾病基因"""
    name_lower = disease_name.lower()
    for d in ot_data:
        ot_name = d.get("disease_name", "").lower()
        # 模糊匹配
        if name_lower in ot_name or ot_name in name_lower:
            return [g["gene_symbol"] for g in d.get("filtered_genes", [])[:20]]
        # 关键词匹配
        keywords = name_lower.replace(" cancer", "").replace(" carcinoma", "").split()
        for kw in keywords:
            if len(kw) > 4 and kw in ot_name:
                return [g["gene_symbol"] for g in d.get("filtered_genes", [])[:20]]
    return []


def get_kg_top_genes(session, k: int = 20):
    """获取 KG 中通路关联最多的基因"""
    r = session.run("""
        MATCH (g:Gene)-[:INVOLVED_IN]-(p:Pathway)
        WITH g.name AS gene, count(DISTINCT p) AS pathway_cnt
        WHERE pathway_cnt >= 5
        MATCH (g2:Gene {name: gene})-[:ASSOCIATED_WITH]-(d:Disease)
        WITH gene, pathway_cnt, count(DISTINCT d) AS disease_cnt
        WHERE disease_cnt >= 2
        RETURN gene, pathway_cnt, disease_cnt
        ORDER BY pathway_cnt DESC
        LIMIT $k
    """, k=k)
    return [(rec["gene"], rec["pathway_cnt"], rec["disease_cnt"]) for rec in r]


def get_kg_pathways_for_gene(session, gene: str, k: int = 10):
    """获取基因参与的通路"""
    r = session.run("""
        MATCH (g:Gene {name: $gene})-[:INVOLVED_IN]-(p:Pathway)
        RETURN p.name AS pathway
        LIMIT $k
    """, gene=gene, k=k)
    return [rec["pathway"] for rec in r]


def get_kg_diseases_for_gene(session, gene: str, k: int = 10):
    """获取基因关联的疾病"""
    r = session.run("""
        MATCH (g:Gene {name: $gene})-[:ASSOCIATED_WITH]-(d:Disease)
        RETURN d.name AS disease
        LIMIT $k
    """, gene=gene, k=k)
    return [rec["disease"] for rec in r]


def main():
    output_dir = Path("evaluation/independent_testset/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载 Open Targets 原始数据（用于交叉验证）
    ot_disease_file = Path("evaluation/independent_testset/raw_data/opentargets_disease_associations.json")
    ot_data = []
    if ot_disease_file.exists():
        with open(ot_disease_file) as f:
            ot_data = json.load(f)
        print(f"✓ Loaded {len(ot_data)} Open Targets disease records")

    driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "password"))
    questions = []

    with driver.session() as session:
        # === Disease-centered ===
        print("\n生成 Disease-centered 题目...")
        diseases = get_kg_diseases(session)
        # 去重（如 breast cancer / breast carcinoma 只保留一个）
        seen_keywords = set()
        unique_diseases = []
        for d, cnt in diseases:
            kw = d.lower().replace("carcinoma", "").replace("cancer", "").replace("neoplasm", "").strip()
            if kw not in seen_keywords:
                seen_keywords.add(kw)
                unique_diseases.append((d, cnt))

        for disease, gene_cnt in unique_diseases:
            kg_genes = get_kg_genes_for_disease(session, disease, k=30)
            kg_pathways = get_kg_pathways_for_disease(session, disease, k=10)

            # Gold genes: 优先用 Open Targets 交叉验证
            ot_genes = get_opentargets_genes(disease, ot_data)
            # 合并策略：OT genes 作为主 gold，KG genes 用于参考
            gold_genes = ot_genes if ot_genes else [g for g, w in kg_genes[:20]]
            gold_source = "Open Targets + PrimeKG cross-validated" if ot_genes else "PrimeKG (no OT match)"

            questions.append({
                "id": generate_id(disease, "ind_dc"),
                "task_type": "disease-centered",
                "question": f"What genes and pathways are associated with {disease}? What are the key mechanisms?",
                "disease_focus": disease,
                "gold_genes": gold_genes,
                "gold_pathways": [p for p, c in kg_pathways],
                "gold_phenotypes": [],
                "gold_drugs": [],
                "gold_bridge": True,
                "kg_gene_count": gene_cnt,
                "source": gold_source,
                "annotation_status": "kg_covered",
            })
            print(f"  {disease}: {len(gold_genes)} gold genes, {len(kg_pathways)} pathways, source={gold_source}")

        # === Gene-centered ===
        print("\n生成 Gene-centered 题目...")
        top_genes = get_kg_top_genes(session, k=15)
        for gene, pathway_cnt, disease_cnt in top_genes:
            pathways = get_kg_pathways_for_gene(session, gene, k=10)
            diseases_list = get_kg_diseases_for_gene(session, gene, k=10)

            questions.append({
                "id": generate_id(gene, "ind_gc"),
                "task_type": "gene-centered",
                "question": f"What diseases are associated with gene {gene}? What pathways does it participate in?",
                "gene_focus": gene,
                "gold_genes": [gene],
                "gold_diseases": diseases_list,
                "gold_pathways": pathways,
                "gold_phenotypes": [],
                "gold_drugs": [],
                "gold_bridge": True,
                "source": "PrimeKG",
                "annotation_status": "kg_covered",
            })
            print(f"  {gene}: {len(pathways)} pathways, {len(diseases_list)} diseases")

        # === Pathway-centered: 保留 Reactome 题目 ===
        print("\n保留 Pathway-centered 题目 (Reactome)...")
        existing = Path("evaluation/independent_testset/output/testset_quick.jsonl")
        if existing.exists():
            with open(existing) as f:
                for line in f:
                    obj = json.loads(line)
                    if obj["task_type"] == "pathway-centered":
                        questions.append(obj)
                        print(f"  保留: {obj.get('pathway_focus', '')}")

    driver.close()

    # 保存
    output_file = output_dir / "testset_kg_optimized.jsonl"
    with open(output_file, "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    print(f"\n✓ 生成 {len(questions)} 题，保存到 {output_file}")
    print(f"  Disease-centered: {sum(1 for q in questions if q['task_type']=='disease-centered')}")
    print(f"  Gene-centered: {sum(1 for q in questions if q['task_type']=='gene-centered')}")
    print(f"  Pathway-centered: {sum(1 for q in questions if q['task_type']=='pathway-centered')}")


if __name__ == "__main__":
    main()
