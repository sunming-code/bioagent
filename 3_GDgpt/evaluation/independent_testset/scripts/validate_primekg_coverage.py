#!/usr/bin/env python3
"""
验证独立测试集在 PrimeKG (Neo4j) 中的覆盖率
确保测试集既独立又能测试 KG 检索能力
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple
from datetime import datetime

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    print("⚠️ neo4j package not installed. Install with: pip install neo4j")


def load_config() -> Dict:
    """加载 Neo4j 配置"""
    config_file = project_root / "config.json"
    if config_file.exists():
        with open(config_file, "r") as f:
            return json.load(f)
    return {}


def connect_neo4j(config: Dict):
    """连接到 Neo4j 数据库"""
    if not NEO4J_AVAILABLE:
        return None
    
    # 支持两种配置格式：neo4j.uri 或 neo4j_uri
    if "neo4j" in config:
        neo4j_config = config.get("neo4j", {})
        uri = neo4j_config.get("uri", "bolt://localhost:7687")
        user = neo4j_config.get("user", "neo4j")
        password = neo4j_config.get("password", "")
    else:
        # 扁平化配置格式
        uri = config.get("neo4j_uri", "bolt://localhost:7687")
        user = config.get("neo4j_user", "neo4j")
        password = config.get("neo4j_password", "")
    
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        # 测试连接
        with driver.session() as session:
            session.run("RETURN 1")
        print(f"✓ Connected to Neo4j at {uri}")
        return driver
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        return None


def check_gene_in_kg(session, gene_symbol: str) -> bool:
    """检查基因是否在 KG 中"""
    query = """
    MATCH (g:Gene)
    WHERE toLower(g.name) = toLower($gene_symbol)
       OR toLower(g.symbol) = toLower($gene_symbol)
    RETURN count(g) > 0 as exists
    """
    result = session.run(query, gene_symbol=gene_symbol)
    record = result.single()
    return record["exists"] if record else False


def check_disease_in_kg(session, disease_name: str) -> bool:
    """检查疾病是否在 KG 中"""
    query = """
    MATCH (d:Disease)
    WHERE toLower(d.name) CONTAINS toLower($disease_name)
       OR toLower(d.mondo_name) CONTAINS toLower($disease_name)
    RETURN count(d) > 0 as exists
    """
    result = session.run(query, disease_name=disease_name)
    record = result.single()
    return record["exists"] if record else False


def check_pathway_in_kg(session, pathway_name: str) -> bool:
    """检查通路是否在 KG 中"""
    query = """
    MATCH (p:Pathway)
    WHERE toLower(p.name) CONTAINS toLower($pathway_name)
    RETURN count(p) > 0 as exists
    """
    result = session.run(query, pathway_name=pathway_name)
    record = result.single()
    return record["exists"] if record else False


def check_gene_disease_association(session, gene_symbol: str, disease_name: str) -> bool:
    """检查基因-疾病关联是否在 KG 中"""
    query = """
    MATCH (g:Gene)-[:ASSOCIATED_WITH|:CAUSES|:LINKED_TO]-(d:Disease)
    WHERE (toLower(g.name) = toLower($gene_symbol) OR toLower(g.symbol) = toLower($gene_symbol))
      AND (toLower(d.name) CONTAINS toLower($disease_name) OR toLower(d.mondo_name) CONTAINS toLower($disease_name))
    RETURN count(*) > 0 as exists
    """
    result = session.run(query, gene_symbol=gene_symbol, disease_name=disease_name)
    record = result.single()
    return record["exists"] if record else False


def check_gene_pathway_association(session, gene_symbol: str, pathway_name: str) -> bool:
    """检查基因-通路关联是否在 KG 中"""
    query = """
    MATCH (g:Gene)-[:PARTICIPATES_IN|:INVOLVED_IN]-(p:Pathway)
    WHERE (toLower(g.name) = toLower($gene_symbol) OR toLower(g.symbol) = toLower($gene_symbol))
      AND toLower(p.name) CONTAINS toLower($pathway_name)
    RETURN count(*) > 0 as exists
    """
    result = session.run(query, gene_symbol=gene_symbol, pathway_name=pathway_name)
    record = result.single()
    return record["exists"] if record else False


def validate_testset(testset_file: Path, driver) -> Dict[str, Any]:
    """
    验证测试集在 PrimeKG 中的覆盖率
    """
    # 加载测试集
    questions = []
    with open(testset_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))
    
    print(f"\n📊 Validating {len(questions)} test questions against PrimeKG...")
    
    results = {
        "total_questions": len(questions),
        "by_task_type": {},
        "entity_coverage": {
            "genes": {"total": 0, "found": 0, "missing": []},
            "diseases": {"total": 0, "found": 0, "missing": []},
            "pathways": {"total": 0, "found": 0, "missing": []}
        },
        "association_coverage": {
            "gene_disease": {"total": 0, "found": 0},
            "gene_pathway": {"total": 0, "found": 0}
        },
        "question_details": []
    }
    
    if not driver:
        print("⚠️ No Neo4j connection. Skipping KG validation.")
        results["error"] = "No Neo4j connection available"
        return results
    
    with driver.session() as session:
        for i, q in enumerate(questions):
            task_type = q.get("task_type", "unknown")
            q_result = {
                "id": q["id"],
                "task_type": task_type,
                "question": q["question"][:100] + "...",
                "coverage": {}
            }
            
            # 初始化任务类型统计
            if task_type not in results["by_task_type"]:
                results["by_task_type"][task_type] = {
                    "total": 0,
                    "fully_covered": 0,
                    "partially_covered": 0,
                    "not_covered": 0
                }
            results["by_task_type"][task_type]["total"] += 1
            
            # 检查实体覆盖
            gold_genes = q.get("gold_genes", [])
            genes_found = 0
            for gene in gold_genes[:10]:  # 检查前 10 个基因
                results["entity_coverage"]["genes"]["total"] += 1
                if check_gene_in_kg(session, gene):
                    genes_found += 1
                    results["entity_coverage"]["genes"]["found"] += 1
                else:
                    if gene not in results["entity_coverage"]["genes"]["missing"]:
                        results["entity_coverage"]["genes"]["missing"].append(gene)
            
            q_result["coverage"]["genes"] = f"{genes_found}/{min(len(gold_genes), 10)}"
            
            # 根据任务类型检查特定实体
            if task_type == "disease-centered":
                disease_name = q.get("disease_focus", "")
                if disease_name:
                    results["entity_coverage"]["diseases"]["total"] += 1
                    if check_disease_in_kg(session, disease_name):
                        results["entity_coverage"]["diseases"]["found"] += 1
                        q_result["coverage"]["disease_found"] = True
                    else:
                        results["entity_coverage"]["diseases"]["missing"].append(disease_name)
                        q_result["coverage"]["disease_found"] = False
            
            elif task_type == "pathway-centered":
                pathway_name = q.get("pathway_focus", "")
                if pathway_name:
                    results["entity_coverage"]["pathways"]["total"] += 1
                    if check_pathway_in_kg(session, pathway_name):
                        results["entity_coverage"]["pathways"]["found"] += 1
                        q_result["coverage"]["pathway_found"] = True
                    else:
                        results["entity_coverage"]["pathways"]["missing"].append(pathway_name)
                        q_result["coverage"]["pathway_found"] = False
            
            # 计算覆盖程度
            gene_coverage_ratio = genes_found / max(len(gold_genes[:10]), 1)
            if gene_coverage_ratio >= 0.7:
                results["by_task_type"][task_type]["fully_covered"] += 1
            elif gene_coverage_ratio >= 0.3:
                results["by_task_type"][task_type]["partially_covered"] += 1
            else:
                results["by_task_type"][task_type]["not_covered"] += 1
            
            results["question_details"].append(q_result)
            
            # 打印进度
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(questions)} questions...")
    
    return results


def generate_coverage_report(results: Dict[str, Any], output_dir: Path):
    """生成覆盖率报告"""
    
    # 计算总体统计
    entity_cov = results["entity_coverage"]
    gene_coverage = entity_cov["genes"]["found"] / max(entity_cov["genes"]["total"], 1) * 100
    disease_coverage = entity_cov["diseases"]["found"] / max(entity_cov["diseases"]["total"], 1) * 100
    pathway_coverage = entity_cov["pathways"]["found"] / max(entity_cov["pathways"]["total"], 1) * 100
    
    report = {
        "summary": {
            "total_questions": results["total_questions"],
            "validation_time": datetime.now().isoformat(),
            "overall_coverage": {
                "genes": f"{gene_coverage:.1f}%",
                "diseases": f"{disease_coverage:.1f}%",
                "pathways": f"{pathway_coverage:.1f}%"
            }
        },
        "by_task_type": results["by_task_type"],
        "entity_coverage": {
            "genes": {
                "total_checked": entity_cov["genes"]["total"],
                "found_in_kg": entity_cov["genes"]["found"],
                "coverage_rate": f"{gene_coverage:.1f}%",
                "sample_missing": entity_cov["genes"]["missing"][:10]
            },
            "diseases": {
                "total_checked": entity_cov["diseases"]["total"],
                "found_in_kg": entity_cov["diseases"]["found"],
                "coverage_rate": f"{disease_coverage:.1f}%",
                "missing": entity_cov["diseases"]["missing"]
            },
            "pathways": {
                "total_checked": entity_cov["pathways"]["total"],
                "found_in_kg": entity_cov["pathways"]["found"],
                "coverage_rate": f"{pathway_coverage:.1f}%",
                "missing": entity_cov["pathways"]["missing"]
            }
        },
        "recommendations": []
    }
    
    # 添加建议
    if gene_coverage < 70:
        report["recommendations"].append(
            f"Gene coverage is low ({gene_coverage:.1f}%). Consider reviewing gene name mappings or using alternative identifiers."
        )
    if disease_coverage < 70:
        report["recommendations"].append(
            f"Disease coverage is low ({disease_coverage:.1f}%). Consider using standard disease ontologies (MONDO, EFO) for better matching."
        )
    if pathway_coverage < 70:
        report["recommendations"].append(
            f"Pathway coverage is low ({pathway_coverage:.1f}%). Consider mapping Reactome pathways to PrimeKG pathway names."
        )
    
    if gene_coverage >= 70 and disease_coverage >= 70:
        report["recommendations"].append(
            "✅ Coverage is sufficient for evaluating KG retrieval capabilities."
        )
    
    # 保存报告
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "coverage_analysis.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # 打印摘要
    print("\n" + "=" * 60)
    print("📊 Coverage Analysis Report")
    print("=" * 60)
    print(f"\nEntity Coverage:")
    print(f"  - Genes: {gene_coverage:.1f}% ({entity_cov['genes']['found']}/{entity_cov['genes']['total']})")
    print(f"  - Diseases: {disease_coverage:.1f}% ({entity_cov['diseases']['found']}/{entity_cov['diseases']['total']})")
    print(f"  - Pathways: {pathway_coverage:.1f}% ({entity_cov['pathways']['found']}/{entity_cov['pathways']['total']})")
    
    print(f"\nBy Task Type:")
    for task_type, stats in results["by_task_type"].items():
        total = stats["total"]
        fully = stats["fully_covered"]
        partial = stats["partially_covered"]
        not_cov = stats["not_covered"]
        print(f"  - {task_type}: {total} questions")
        print(f"      Fully covered (≥70%): {fully}")
        print(f"      Partially covered: {partial}")
        print(f"      Not covered (<30%): {not_cov}")
    
    print(f"\n📁 Full report saved to: {report_file}")
    
    if report["recommendations"]:
        print("\n💡 Recommendations:")
        for rec in report["recommendations"]:
            print(f"  - {rec}")
    
    return report


def main():
    """主函数"""
    script_dir = Path(__file__).parent.parent
    output_dir = script_dir / "output"
    processed_dir = script_dir / "processed"
    
    testset_file = output_dir / "independent_gold_final.jsonl"
    
    print("🔍 PrimeKG Coverage Validation")
    print("=" * 60)
    
    if not testset_file.exists():
        print(f"❌ Test set not found: {testset_file}")
        print("   Please run generate_testset.py first.")
        return
    
    # 加载配置并连接 Neo4j
    config = load_config()
    driver = connect_neo4j(config)
    
    try:
        # 验证测试集
        results = validate_testset(testset_file, driver)
        
        # 生成报告
        report = generate_coverage_report(results, processed_dir)
        
        print("\n" + "=" * 60)
        print("✅ Validation complete!")
        print("=" * 60)
        
    finally:
        if driver:
            driver.close()


if __name__ == "__main__":
    main()
