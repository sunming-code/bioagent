#!/usr/bin/env python3
"""
改进版：验证独立测试集在 PrimeKG (Neo4j) 中的覆盖率
使用模糊匹配和同义词映射提高匹配精度
"""

import json
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional
from datetime import datetime
from collections import defaultdict

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    print("⚠️ neo4j package not installed. Install with: pip install neo4j")


# ============================================================
# 同义词映射表
# ============================================================

# 疾病名称映射（Open Targets 名称 -> PrimeKG 可能的名称）
DISEASE_SYNONYMS = {
    "coronary artery disease": ["coronary heart disease", "ischemic heart disease", "cad"],
    "lung carcinoma": ["lung cancer", "non-small cell lung cancer", "nsclc", "small cell lung cancer"],
    "hypertension": ["high blood pressure", "essential hypertension", "hypertensive disease"],
    "rheumatoid arthritis": ["ra", "arthritis", "rheumatoid"],
    "melanoma": ["malignant melanoma", "cutaneous melanoma", "skin melanoma"],
    "leukemia": ["leukaemia", "acute leukemia", "chronic leukemia", "blood cancer"],
    "glioblastoma multiforme": ["glioblastoma", "gbm", "glioma", "brain tumor", "brain cancer"],
    "ovarian carcinoma": ["ovarian cancer", "ovarian neoplasm", "ovary cancer"],
    "atrial fibrillation": ["afib", "af", "irregular heartbeat"],
    "chronic kidney disease": ["ckd", "chronic renal disease", "kidney disease", "renal failure"],
    "alzheimer disease": ["alzheimer's disease", "ad", "dementia", "alzheimers"],
    "pancreatic carcinoma": ["pancreatic cancer", "pancreas cancer"],
    "obesity": ["obese", "overweight", "adiposity"],
    "heart failure": ["cardiac failure", "congestive heart failure", "chf"],
    "epilepsy": ["seizure disorder", "seizures", "epileptic"],
}

# Pathway 名称映射（Reactome 名称 -> 可能的 PrimeKG 匹配关键词）
PATHWAY_KEYWORDS = {
    "Transmission across Chemical Synapses": ["synapse", "synaptic", "neurotransmitter"],
    "Mitotic G1-G1/S phases": ["cell cycle", "g1", "mitotic", "g1/s"],
    "Extrinsic Pathway for Apoptosis": ["apoptosis", "apoptotic", "extrinsic", "death receptor"],
    "Cytokine Signaling in Immune system": ["cytokine", "immune", "interleukin", "interferon"],
    "Fatty acid metabolism": ["fatty acid", "lipid", "beta-oxidation"],
    "Gene expression (Transcription)": ["transcription", "gene expression", "rna polymerase"],
    "Adaptive Immune System": ["adaptive immune", "t cell", "b cell", "lymphocyte"],
    "VEGF signaling": ["vegf", "vascular endothelial", "angiogenesis"],
    "MAPK family signaling cascades": ["mapk", "erk", "jnk", "p38"],
}


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
    
    # 支持两种配置格式
    if "neo4j" in config:
        neo4j_config = config.get("neo4j", {})
        uri = neo4j_config.get("uri", "bolt://localhost:7687")
        user = neo4j_config.get("user", "neo4j")
        password = neo4j_config.get("password", "")
    else:
        uri = config.get("neo4j_uri", "bolt://localhost:7687")
        user = config.get("neo4j_user", "neo4j")
        password = config.get("neo4j_password", "")
    
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1")
        print(f"✓ Connected to Neo4j at {uri}")
        return driver
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        return None


def normalize_name(name: str) -> str:
    """标准化名称：小写、去除特殊字符"""
    name = name.lower().strip()
    # 去除括号内容
    name = re.sub(r'\([^)]*\)', '', name)
    # 去除特殊字符
    name = re.sub(r'[^\w\s-]', '', name)
    return name.strip()


def check_gene_in_kg_fuzzy(session, gene_symbol: str) -> Tuple[bool, Optional[str]]:
    """模糊匹配检查基因是否在 KG 中"""
    gene_normalized = normalize_name(gene_symbol)
    
    # 精确匹配
    query_exact = """
    MATCH (g:Gene)
    WHERE toLower(g.name) = $gene_name
    RETURN g.name as matched_name
    LIMIT 1
    """
    result = session.run(query_exact, gene_name=gene_normalized)
    record = result.single()
    if record:
        return True, record["matched_name"]
    
    # 部分匹配（名称包含）
    query_contains = """
    MATCH (g:Gene)
    WHERE toLower(g.name) CONTAINS $gene_name
       OR toLower(g.aliases) CONTAINS $gene_name
    RETURN g.name as matched_name
    LIMIT 1
    """
    result = session.run(query_contains, gene_name=gene_normalized)
    record = result.single()
    if record:
        return True, record["matched_name"]
    
    return False, None


def check_disease_in_kg_fuzzy(session, disease_name: str) -> Tuple[bool, Optional[str]]:
    """模糊匹配检查疾病是否在 KG 中"""
    disease_normalized = normalize_name(disease_name)
    
    # 1. 精确匹配
    query_exact = """
    MATCH (d:Disease)
    WHERE toLower(d.name) = $disease_name
    RETURN d.name as matched_name
    LIMIT 1
    """
    result = session.run(query_exact, disease_name=disease_normalized)
    record = result.single()
    if record:
        return True, record["matched_name"]
    
    # 2. 部分匹配
    query_contains = """
    MATCH (d:Disease)
    WHERE toLower(d.name) CONTAINS $disease_name
       OR toLower(d.aliases) CONTAINS $disease_name
    RETURN d.name as matched_name
    LIMIT 1
    """
    result = session.run(query_contains, disease_name=disease_normalized)
    record = result.single()
    if record:
        return True, record["matched_name"]
    
    # 3. 同义词匹配
    synonyms = DISEASE_SYNONYMS.get(disease_name.lower(), [])
    for synonym in synonyms:
        syn_normalized = normalize_name(synonym)
        result = session.run(query_contains, disease_name=syn_normalized)
        record = result.single()
        if record:
            return True, record["matched_name"]
    
    # 4. 关键词匹配（提取核心词）
    keywords = disease_normalized.split()
    for keyword in keywords:
        if len(keyword) > 4:  # 只用较长的关键词
            result = session.run(query_contains, disease_name=keyword)
            record = result.single()
            if record:
                return True, record["matched_name"]
    
    return False, None


def check_pathway_in_kg_fuzzy(session, pathway_name: str) -> Tuple[bool, Optional[str]]:
    """模糊匹配检查通路是否在 KG 中"""
    pathway_normalized = normalize_name(pathway_name)
    
    # 1. 精确匹配
    query_exact = """
    MATCH (p:Pathway)
    WHERE toLower(p.name) = $pathway_name
    RETURN p.name as matched_name
    LIMIT 1
    """
    result = session.run(query_exact, pathway_name=pathway_normalized)
    record = result.single()
    if record:
        return True, record["matched_name"]
    
    # 2. 部分匹配
    query_contains = """
    MATCH (p:Pathway)
    WHERE toLower(p.name) CONTAINS $keyword
    RETURN p.name as matched_name
    LIMIT 1
    """
    
    # 3. 关键词匹配
    keywords = PATHWAY_KEYWORDS.get(pathway_name, [])
    if not keywords:
        # 自动提取关键词
        keywords = [w for w in pathway_normalized.split() if len(w) > 3]
    
    for keyword in keywords:
        result = session.run(query_contains, keyword=keyword.lower())
        record = result.single()
        if record:
            return True, record["matched_name"]
    
    return False, None


def get_kg_stats(session) -> Dict:
    """获取 KG 基本统计信息"""
    stats = {}
    
    # 节点统计
    query = """
    MATCH (n)
    RETURN labels(n)[0] as type, count(*) as count
    ORDER BY count DESC
    """
    result = session.run(query)
    stats["node_counts"] = {record["type"]: record["count"] for record in result}
    
    # 关系统计
    query = """
    MATCH ()-[r]->()
    RETURN type(r) as type, count(*) as count
    ORDER BY count DESC
    LIMIT 10
    """
    result = session.run(query)
    stats["relationship_counts"] = {record["type"]: record["count"] for record in result}
    
    return stats


def validate_testset_v2(testset_file: Path, driver) -> Dict[str, Any]:
    """改进版：验证测试集在 PrimeKG 中的覆盖率"""
    
    # 加载测试集
    questions = []
    with open(testset_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))
    
    print(f"\n📊 Validating {len(questions)} test questions against PrimeKG (improved matching)...")
    
    results = {
        "total_questions": len(questions),
        "by_task_type": {},
        "entity_coverage": {
            "genes": {"total": 0, "found": 0, "missing": [], "matched": {}},
            "diseases": {"total": 0, "found": 0, "missing": [], "matched": {}},
            "pathways": {"total": 0, "found": 0, "missing": [], "matched": {}}
        },
        "question_details": [],
        "kg_stats": {}
    }
    
    if not driver:
        print("⚠️ No Neo4j connection. Skipping KG validation.")
        results["error"] = "No Neo4j connection available"
        return results
    
    with driver.session() as session:
        # 获取 KG 统计
        results["kg_stats"] = get_kg_stats(session)
        print(f"\n📈 KG Stats: {results['kg_stats']['node_counts']}")
        
        for i, q in enumerate(questions):
            task_type = q.get("task_type", "unknown")
            q_result = {
                "id": q["id"],
                "task_type": task_type,
                "question": q["question"][:80] + "...",
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
            
            # 检查基因覆盖（使用模糊匹配）
            gold_genes = q.get("gold_genes", [])
            genes_found = 0
            for gene in gold_genes[:10]:
                results["entity_coverage"]["genes"]["total"] += 1
                found, matched_name = check_gene_in_kg_fuzzy(session, gene)
                if found:
                    genes_found += 1
                    results["entity_coverage"]["genes"]["found"] += 1
                    results["entity_coverage"]["genes"]["matched"][gene] = matched_name
                else:
                    if gene not in results["entity_coverage"]["genes"]["missing"]:
                        results["entity_coverage"]["genes"]["missing"].append(gene)
            
            q_result["coverage"]["genes"] = f"{genes_found}/{min(len(gold_genes), 10)}"
            
            # 检查疾病覆盖
            if task_type == "disease-centered":
                disease_name = q.get("disease_focus", "")
                if disease_name:
                    results["entity_coverage"]["diseases"]["total"] += 1
                    found, matched_name = check_disease_in_kg_fuzzy(session, disease_name)
                    if found:
                        results["entity_coverage"]["diseases"]["found"] += 1
                        results["entity_coverage"]["diseases"]["matched"][disease_name] = matched_name
                        q_result["coverage"]["disease_found"] = True
                        q_result["coverage"]["disease_matched"] = matched_name
                    else:
                        results["entity_coverage"]["diseases"]["missing"].append(disease_name)
                        q_result["coverage"]["disease_found"] = False
            
            # 检查通路覆盖
            elif task_type == "pathway-centered":
                pathway_name = q.get("pathway_focus", "")
                if pathway_name:
                    results["entity_coverage"]["pathways"]["total"] += 1
                    found, matched_name = check_pathway_in_kg_fuzzy(session, pathway_name)
                    if found:
                        results["entity_coverage"]["pathways"]["found"] += 1
                        results["entity_coverage"]["pathways"]["matched"][pathway_name] = matched_name
                        q_result["coverage"]["pathway_found"] = True
                        q_result["coverage"]["pathway_matched"] = matched_name
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
            
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(questions)} questions...")
    
    return results


def generate_coverage_report_v2(results: Dict[str, Any], output_dir: Path):
    """生成改进版覆盖率报告"""
    
    entity_cov = results["entity_coverage"]
    gene_coverage = entity_cov["genes"]["found"] / max(entity_cov["genes"]["total"], 1) * 100
    disease_coverage = entity_cov["diseases"]["found"] / max(entity_cov["diseases"]["total"], 1) * 100
    pathway_coverage = entity_cov["pathways"]["found"] / max(entity_cov["pathways"]["total"], 1) * 100
    
    report = {
        "summary": {
            "total_questions": results["total_questions"],
            "validation_time": datetime.now().isoformat(),
            "method": "improved_fuzzy_matching_v2",
            "overall_coverage": {
                "genes": f"{gene_coverage:.1f}%",
                "diseases": f"{disease_coverage:.1f}%",
                "pathways": f"{pathway_coverage:.1f}%"
            }
        },
        "kg_stats": results.get("kg_stats", {}),
        "by_task_type": results["by_task_type"],
        "entity_coverage": {
            "genes": {
                "total_checked": entity_cov["genes"]["total"],
                "found_in_kg": entity_cov["genes"]["found"],
                "coverage_rate": f"{gene_coverage:.1f}%",
                "sample_missing": entity_cov["genes"]["missing"][:15],
                "sample_matched": dict(list(entity_cov["genes"]["matched"].items())[:10])
            },
            "diseases": {
                "total_checked": entity_cov["diseases"]["total"],
                "found_in_kg": entity_cov["diseases"]["found"],
                "coverage_rate": f"{disease_coverage:.1f}%",
                "missing": entity_cov["diseases"]["missing"],
                "matched": entity_cov["diseases"]["matched"]
            },
            "pathways": {
                "total_checked": entity_cov["pathways"]["total"],
                "found_in_kg": entity_cov["pathways"]["found"],
                "coverage_rate": f"{pathway_coverage:.1f}%",
                "missing": entity_cov["pathways"]["missing"],
                "matched": entity_cov["pathways"]["matched"]
            }
        },
        "recommendations": [],
        "usability_assessment": {}
    }
    
    # 评估可用性
    total_fully_covered = sum(t["fully_covered"] for t in results["by_task_type"].values())
    total_partially_covered = sum(t["partially_covered"] for t in results["by_task_type"].values())
    total_questions = results["total_questions"]
    
    usable_ratio = (total_fully_covered + total_partially_covered * 0.5) / total_questions * 100
    
    report["usability_assessment"] = {
        "fully_covered_questions": total_fully_covered,
        "partially_covered_questions": total_partially_covered,
        "total_questions": total_questions,
        "usability_score": f"{usable_ratio:.1f}%",
        "recommendation": "USABLE" if usable_ratio >= 50 else "NEEDS_IMPROVEMENT"
    }
    
    # 添加建议
    if gene_coverage >= 70:
        report["recommendations"].append(f"✅ Gene coverage is good ({gene_coverage:.1f}%).")
    else:
        report["recommendations"].append(
            f"⚠️ Gene coverage ({gene_coverage:.1f}%) could be improved. Consider using gene aliases or NCBI IDs."
        )
    
    if disease_coverage >= 50:
        report["recommendations"].append(f"✅ Disease coverage is acceptable ({disease_coverage:.1f}%).")
    else:
        report["recommendations"].append(
            f"⚠️ Disease coverage is low ({disease_coverage:.1f}%). PrimeKG has limited disease coverage ({results['kg_stats'].get('node_counts', {}).get('Disease', 0)} diseases)."
        )
    
    if pathway_coverage >= 50:
        report["recommendations"].append(f"✅ Pathway coverage is acceptable ({pathway_coverage:.1f}%).")
    else:
        report["recommendations"].append(
            f"⚠️ Pathway coverage ({pathway_coverage:.1f}%) is limited. Reactome pathways may use different naming conventions."
        )
    
    if usable_ratio >= 70:
        report["recommendations"].append("🎯 Overall: Test set is HIGHLY SUITABLE for KG evaluation.")
    elif usable_ratio >= 50:
        report["recommendations"].append("🎯 Overall: Test set is SUITABLE for KG evaluation with some limitations.")
    else:
        report["recommendations"].append("🎯 Overall: Consider filtering to gene-centered questions for better KG evaluation.")
    
    # 保存报告
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "coverage_analysis_v2.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    # 打印摘要
    print("\n" + "=" * 70)
    print("📊 IMPROVED Coverage Analysis Report (v2)")
    print("=" * 70)
    
    print(f"\n🗄️ PrimeKG Statistics:")
    for node_type, count in results.get("kg_stats", {}).get("node_counts", {}).items():
        print(f"   - {node_type}: {count:,}")
    
    print(f"\n📈 Entity Coverage (with fuzzy matching):")
    print(f"   - Genes:    {gene_coverage:5.1f}% ({entity_cov['genes']['found']}/{entity_cov['genes']['total']})")
    print(f"   - Diseases: {disease_coverage:5.1f}% ({entity_cov['diseases']['found']}/{entity_cov['diseases']['total']})")
    print(f"   - Pathways: {pathway_coverage:5.1f}% ({entity_cov['pathways']['found']}/{entity_cov['pathways']['total']})")
    
    print(f"\n📋 By Task Type:")
    for task_type, stats in results["by_task_type"].items():
        total = stats["total"]
        fully = stats["fully_covered"]
        partial = stats["partially_covered"]
        not_cov = stats["not_covered"]
        print(f"   {task_type}:")
        print(f"      Total: {total} | Fully: {fully} | Partial: {partial} | Not covered: {not_cov}")
    
    print(f"\n🎯 Usability Assessment:")
    print(f"   - Fully covered questions:     {total_fully_covered}")
    print(f"   - Partially covered questions: {total_partially_covered}")
    print(f"   - Usability score:             {usable_ratio:.1f}%")
    print(f"   - Assessment:                  {report['usability_assessment']['recommendation']}")
    
    print(f"\n📁 Full report: {report_file}")
    
    print("\n💡 Recommendations:")
    for rec in report["recommendations"]:
        print(f"   {rec}")
    
    # 显示匹配示例
    if entity_cov["diseases"]["matched"]:
        print(f"\n🔗 Disease Matching Examples:")
        for orig, matched in list(entity_cov["diseases"]["matched"].items())[:5]:
            print(f"   '{orig}' → '{matched}'")
    
    if entity_cov["pathways"]["matched"]:
        print(f"\n🔗 Pathway Matching Examples:")
        for orig, matched in list(entity_cov["pathways"]["matched"].items())[:5]:
            print(f"   '{orig}' → '{matched}'")
    
    return report


def main():
    """主函数"""
    script_dir = Path(__file__).parent.parent
    output_dir = script_dir / "output"
    processed_dir = script_dir / "processed"
    
    testset_file = output_dir / "independent_gold_final.jsonl"
    
    print("🔍 PrimeKG Coverage Validation (Improved v2)")
    print("=" * 70)
    
    if not testset_file.exists():
        print(f"❌ Test set not found: {testset_file}")
        print("   Please run generate_testset.py first.")
        return
    
    config = load_config()
    driver = connect_neo4j(config)
    
    try:
        results = validate_testset_v2(testset_file, driver)
        report = generate_coverage_report_v2(results, processed_dir)
        
        print("\n" + "=" * 70)
        print("✅ Validation complete!")
        print("=" * 70)
        
    finally:
        if driver:
            driver.close()


if __name__ == "__main__":
    main()
