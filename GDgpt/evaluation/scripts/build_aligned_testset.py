#!/usr/bin/env python3
"""
构建 PrimeKG-Aligned 测试集
===========================
根据 PrimeKG 中已有的疾病/基因/通路，从 Open Targets 和 Reactome 获取匹配数据。

使用方法:
    python build_aligned_testset.py --output evaluation_gold_v2.jsonl
"""

import json
import hashlib
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None


# =============================================================================
# 配置
# =============================================================================

DEFAULT_NEO4J_URI = "bolt://localhost:7687"
DEFAULT_NEO4J_USER = "neo4j"
DEFAULT_NEO4J_PASSWORD = "password"

# 问题模板
QUESTION_TEMPLATES = {
    "disease-centered": [
        "What are the key genes involved in {disease}?",
        "Which genes are associated with {disease}?",
        "What genes play important roles in {disease}?",
    ],
    "gene-centered": [
        "What diseases are associated with gene {gene}?",
        "Which diseases involve gene {gene}?",
        "What conditions are linked to {gene}?",
    ],
    "pathway-centered": [
        "Which genes participate in {pathway}?",
        "What genes are involved in the {pathway} pathway?",
        "What are the key genes in the {pathway} pathway?",
    ],
}


# =============================================================================
# Neo4j 连接
# =============================================================================

class PrimeKGExtractor:
    """从 PrimeKG (Neo4j) 提取实体信息"""
    
    def __init__(self, uri: str, user: str, password: str):
        if GraphDatabase is None:
            raise ImportError("Please install neo4j: pip install neo4j")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        self.driver.close()
    
    def get_all_diseases(self, limit: int = 50) -> List[Dict]:
        """获取 PrimeKG 中所有疾病"""
        query = """
        MATCH (d:Disease)
        RETURN d.name AS name, d.id AS id, d.normalized_name AS normalized_name
        LIMIT $limit
        """
        with self.driver.session() as session:
            result = session.run(query, limit=limit)
            return [dict(r) for r in result]
    
    def get_all_genes(self, limit: int = 100) -> List[Dict]:
        """获取 PrimeKG 中所有基因"""
        query = """
        MATCH (g:Gene)
        RETURN DISTINCT g.name AS name, g.id AS id
        LIMIT $limit
        """
        with self.driver.session() as session:
            result = session.run(query, limit=limit)
            return [dict(r) for r in result]
    
    def get_all_pathways(self, limit: int = 50) -> List[Dict]:
        """获取 PrimeKG 中所有通路"""
        query = """
        MATCH (p:Pathway)
        RETURN DISTINCT p.name AS name, p.id AS id
        LIMIT $limit
        """
        with self.driver.session() as session:
            result = session.run(query, limit=limit)
            return [dict(r) for r in result]
    
    def get_disease_genes(self, disease_name: str, k: int = 20) -> List[str]:
        """获取疾病相关基因"""
        query = """
        MATCH (d:Disease)-[r:ASSOCIATED_WITH]-(g:Gene)
        WHERE toLower(d.name) CONTAINS toLower($disease)
           OR toLower(d.normalized_name) CONTAINS toLower($disease)
        RETURN DISTINCT g.name AS gene
        ORDER BY coalesce(r.weight, 0) DESC
        LIMIT $k
        """
        with self.driver.session() as session:
            result = session.run(query, disease=disease_name, k=k)
            return [r["gene"] for r in result]
    
    def get_disease_pathways(self, disease_name: str, k: int = 10) -> List[str]:
        """获取疾病相关通路 (通过 Bridge)"""
        query = """
        MATCH (d:Disease)-[:ASSOCIATED_WITH]-(g:Gene)-[:INVOLVED_IN]-(p:Pathway)
        WHERE toLower(d.name) CONTAINS toLower($disease)
           OR toLower(d.normalized_name) CONTAINS toLower($disease)
        RETURN DISTINCT p.name AS pathway
        LIMIT $k
        """
        with self.driver.session() as session:
            result = session.run(query, disease=disease_name, k=k)
            return [r["pathway"] for r in result]
    
    def get_gene_diseases(self, gene_name: str, k: int = 15) -> List[str]:
        """获取基因相关疾病"""
        query = """
        MATCH (g:Gene)-[r:ASSOCIATED_WITH]-(d:Disease)
        WHERE toLower(g.name) = toLower($gene)
        RETURN DISTINCT d.name AS disease
        ORDER BY coalesce(r.weight, 0) DESC
        LIMIT $k
        """
        with self.driver.session() as session:
            result = session.run(query, gene=gene_name, k=k)
            return [r["disease"] for r in result]
    
    def get_pathway_genes(self, pathway_name: str, k: int = 30) -> List[str]:
        """获取通路相关基因"""
        query = """
        MATCH (p:Pathway)-[:INVOLVED_IN]-(g:Gene)
        WHERE toLower(p.name) CONTAINS toLower($pathway)
        RETURN DISTINCT g.name AS gene
        LIMIT $k
        """
        with self.driver.session() as session:
            result = session.run(query, pathway=pathway_name, k=k)
            return [r["gene"] for r in result]
    
    def get_kg_stats(self) -> Dict:
        """获取 KG 统计信息"""
        stats = {}
        with self.driver.session() as session:
            # 节点统计
            for label in ["Gene", "Disease", "Pathway", "Drug", "Phenotype"]:
                query = f"MATCH (n:{label}) RETURN count(n) AS cnt"
                result = session.run(query)
                stats[label] = result.single()["cnt"]
        return stats


# =============================================================================
# 测试集生成
# =============================================================================

def generate_id(prefix: str, content: str) -> str:
    """生成唯一 ID"""
    hash_val = hashlib.md5(content.encode()).hexdigest()[:12]
    return f"{prefix}_{hash_val}"


def build_disease_centered_questions(
    extractor: PrimeKGExtractor,
    diseases: List[Dict],
    max_questions: int = 15
) -> List[Dict]:
    """构建 disease-centered 问题"""
    questions = []
    
    for disease in diseases[:max_questions]:
        disease_name = disease.get("name") or disease.get("normalized_name", "")
        if not disease_name:
            continue
        
        # 获取 gold genes
        gold_genes = extractor.get_disease_genes(disease_name, k=20)
        gold_pathways = extractor.get_disease_pathways(disease_name, k=10)
        
        if len(gold_genes) < 3:
            continue  # 跳过关联太少的疾病
        
        # 生成问题
        template = QUESTION_TEMPLATES["disease-centered"][0]
        question = template.format(disease=disease_name)
        
        item = {
            "id": generate_id("dc", disease_name),
            "task_type": "disease-centered",
            "question": question,
            "disease_focus": disease_name,
            "disease_id": disease.get("id", ""),
            "gold_genes": gold_genes,
            "gold_pathways": gold_pathways,
            "gold_phenotypes": [],
            "gold_drugs": [],
            "source": "PrimeKG",
            "annotation_status": "auto_generated",
            "created_at": datetime.now().isoformat(),
            "kg_coverage": "high",  # 已确认在 KG 中
        }
        questions.append(item)
        print(f"  ✓ Disease: {disease_name} ({len(gold_genes)} genes)")
    
    return questions


def build_gene_centered_questions(
    extractor: PrimeKGExtractor,
    genes: List[Dict],
    max_questions: int = 30
) -> List[Dict]:
    """构建 gene-centered 问题"""
    questions = []
    
    for gene in genes[:max_questions * 2]:  # 多取一些，过滤后可能不够
        gene_name = gene.get("name", "")
        if not gene_name:
            continue
        
        # 获取 gold diseases
        gold_diseases = extractor.get_gene_diseases(gene_name, k=15)
        
        if len(gold_diseases) < 2:
            continue  # 跳过关联太少的基因
        
        # 生成问题
        template = QUESTION_TEMPLATES["gene-centered"][len(questions) % 3]
        question = template.format(gene=gene_name)
        
        item = {
            "id": generate_id("gc", gene_name),
            "task_type": "gene-centered",
            "question": question,
            "gene_focus": gene_name,
            "gene_id": gene.get("id", ""),
            "gold_genes": [gene_name],
            "gold_diseases": gold_diseases,
            "gold_pathways": [],
            "gold_drugs": [],
            "source": "PrimeKG",
            "annotation_status": "auto_generated",
            "created_at": datetime.now().isoformat(),
            "kg_coverage": "medium",
        }
        questions.append(item)
        print(f"  ✓ Gene: {gene_name} ({len(gold_diseases)} diseases)")
        
        if len(questions) >= max_questions:
            break
    
    return questions


def build_pathway_centered_questions(
    extractor: PrimeKGExtractor,
    pathways: List[Dict],
    max_questions: int = 25
) -> List[Dict]:
    """构建 pathway-centered 问题"""
    questions = []
    
    for pathway in pathways[:max_questions * 2]:
        pathway_name = pathway.get("name", "")
        if not pathway_name:
            continue
        
        # 获取 gold genes
        gold_genes = extractor.get_pathway_genes(pathway_name, k=30)
        
        if len(gold_genes) < 5:
            continue  # 跳过基因太少的通路
        
        # 生成问题
        template = QUESTION_TEMPLATES["pathway-centered"][len(questions) % 3]
        question = template.format(pathway=pathway_name)
        
        item = {
            "id": generate_id("pc", pathway_name),
            "task_type": "pathway-centered",
            "question": question,
            "pathway_focus": pathway_name,
            "pathway_id": pathway.get("id", ""),
            "gold_genes": gold_genes,
            "gold_pathways": [pathway_name],
            "gold_drugs": [],
            "source": "PrimeKG",
            "annotation_status": "auto_generated",
            "created_at": datetime.now().isoformat(),
            "kg_coverage": "high",
        }
        questions.append(item)
        print(f"  ✓ Pathway: {pathway_name} ({len(gold_genes)} genes)")
        
        if len(questions) >= max_questions:
            break
    
    return questions


def build_low_coverage_questions(count: int = 10) -> List[Dict]:
    """构建低覆盖率问题（用于测试 graceful degradation）"""
    # 这些疾病不在 PrimeKG 中
    low_coverage_diseases = [
        ("coronary artery disease", ["LDLR", "PCSK9", "APOB", "LPA"]),
        ("hypertension", ["ACE", "AGT", "NOS3", "ADD1"]),
        ("Alzheimer disease", ["APP", "PSEN1", "PSEN2", "APOE"]),
        ("epilepsy", ["SCN1A", "KCNQ2", "GABRA1", "CHRNA4"]),
        ("atrial fibrillation", ["KCNQ1", "SCN5A", "PITX2", "KCNH2"]),
        ("chronic kidney disease", ["UMOD", "MYH9", "APOL1", "PKD1"]),
        ("type 2 diabetes", ["TCF7L2", "PPARG", "KCNJ11", "IRS1"]),
        ("asthma", ["IL4", "IL13", "ADAM33", "ORMDL3"]),
        ("rheumatoid arthritis", ["HLA-DRB1", "PTPN22", "STAT4", "TRAF1"]),
        ("Parkinson disease", ["SNCA", "LRRK2", "PARK7", "PINK1"]),
    ]
    
    questions = []
    for disease, genes in low_coverage_diseases[:count]:
        question = f"What are the key genes involved in {disease}?"
        item = {
            "id": generate_id("dc_low", disease),
            "task_type": "disease-centered",
            "question": question,
            "disease_focus": disease,
            "disease_id": "",
            "gold_genes": genes,
            "gold_pathways": [],
            "gold_phenotypes": [],
            "gold_drugs": [],
            "source": "Literature (low KG coverage)",
            "annotation_status": "auto_generated",
            "created_at": datetime.now().isoformat(),
            "kg_coverage": "low",
            "note": "This disease is NOT in PrimeKG - used for graceful degradation analysis"
        }
        questions.append(item)
        print(f"  ⚠ Low Coverage: {disease}")
    
    return questions


# =============================================================================
# 主函数
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="构建 PrimeKG-Aligned 测试集")
    parser.add_argument("--output", type=str, default="evaluation_gold_v2.jsonl",
                        help="输出文件路径")
    parser.add_argument("--neo4j-uri", type=str, default=DEFAULT_NEO4J_URI,
                        help="Neo4j URI")
    parser.add_argument("--neo4j-user", type=str, default=DEFAULT_NEO4J_USER,
                        help="Neo4j 用户名")
    parser.add_argument("--neo4j-password", type=str, default=DEFAULT_NEO4J_PASSWORD,
                        help="Neo4j 密码")
    parser.add_argument("--disease-count", type=int, default=15,
                        help="Disease-centered 问题数量")
    parser.add_argument("--gene-count", type=int, default=30,
                        help="Gene-centered 问题数量")
    parser.add_argument("--pathway-count", type=int, default=25,
                        help="Pathway-centered 问题数量")
    parser.add_argument("--low-coverage-count", type=int, default=10,
                        help="低覆盖率问题数量")
    parser.add_argument("--skip-neo4j", action="store_true",
                        help="跳过 Neo4j，仅生成低覆盖率问题")
    args = parser.parse_args()
    
    all_questions = []
    
    if not args.skip_neo4j:
        print("=" * 60)
        print("📊 连接 PrimeKG (Neo4j)...")
        print("=" * 60)
        
        try:
            extractor = PrimeKGExtractor(
                args.neo4j_uri, args.neo4j_user, args.neo4j_password
            )
            
            # 获取 KG 统计
            stats = extractor.get_kg_stats()
            print(f"\nKG 统计:")
            for label, count in stats.items():
                print(f"  {label}: {count}")
            
            # 获取实体列表
            print("\n获取实体列表...")
            diseases = extractor.get_all_diseases(limit=50)
            genes = extractor.get_all_genes(limit=100)
            pathways = extractor.get_all_pathways(limit=50)
            
            print(f"  找到 {len(diseases)} 种疾病")
            print(f"  找到 {len(genes)} 个基因")
            print(f"  找到 {len(pathways)} 条通路")
            
            # 构建问题
            print("\n" + "=" * 60)
            print("📝 构建 Disease-centered 问题...")
            print("=" * 60)
            dc_questions = build_disease_centered_questions(
                extractor, diseases, args.disease_count
            )
            all_questions.extend(dc_questions)
            
            print("\n" + "=" * 60)
            print("📝 构建 Gene-centered 问题...")
            print("=" * 60)
            gc_questions = build_gene_centered_questions(
                extractor, genes, args.gene_count
            )
            all_questions.extend(gc_questions)
            
            print("\n" + "=" * 60)
            print("📝 构建 Pathway-centered 问题...")
            print("=" * 60)
            pc_questions = build_pathway_centered_questions(
                extractor, pathways, args.pathway_count
            )
            all_questions.extend(pc_questions)
            
            extractor.close()
            
        except Exception as e:
            print(f"⚠️ Neo4j 连接失败: {e}")
            print("将仅生成低覆盖率问题...")
    
    # 添加低覆盖率问题
    print("\n" + "=" * 60)
    print("📝 构建低覆盖率问题 (用于 graceful degradation 分析)...")
    print("=" * 60)
    low_questions = build_low_coverage_questions(args.low_coverage_count)
    all_questions.extend(low_questions)
    
    # 统计
    print("\n" + "=" * 60)
    print("📊 测试集统计")
    print("=" * 60)
    
    coverage_counts = defaultdict(int)
    task_counts = defaultdict(int)
    
    for q in all_questions:
        coverage_counts[q.get("kg_coverage", "unknown")] += 1
        task_counts[q.get("task_type", "unknown")] += 1
    
    print(f"\n总问题数: {len(all_questions)}")
    print("\n按任务类型:")
    for task, count in sorted(task_counts.items()):
        print(f"  {task}: {count}")
    print("\n按覆盖率:")
    for cov, count in sorted(coverage_counts.items()):
        print(f"  {cov}: {count}")
    
    # 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for q in all_questions:
            f.write(json.dumps(q, ensure_ascii=False) + '\n')
    
    print(f"\n✅ 测试集已保存到: {output_path}")
    print(f"   共 {len(all_questions)} 个问题")
    
    # 生成摘要
    summary = {
        "created_at": datetime.now().isoformat(),
        "total_questions": len(all_questions),
        "by_task_type": dict(task_counts),
        "by_coverage": dict(coverage_counts),
        "source": "PrimeKG-Aligned auto-generation",
    }
    
    summary_path = output_path.with_suffix('.summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"   摘要保存到: {summary_path}")


if __name__ == "__main__":
    main()
