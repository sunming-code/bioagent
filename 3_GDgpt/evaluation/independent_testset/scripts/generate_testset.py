#!/usr/bin/env python3
"""
从 Open Targets 和 Reactome 数据生成独立测试集
格式与 evaluation_gold_final.jsonl 兼容
"""

import json
import random
from pathlib import Path
from typing import List, Dict, Any
import hashlib
from datetime import datetime

# 问题模板
QUESTION_TEMPLATES = {
    "disease-centered": [
        "What genes are associated with {disease}?",
        "Which genes play a role in {disease}?",
        "What are the key genes involved in {disease}?",
    ],
    "gene-centered": [
        "What diseases are associated with gene {gene}?",
        "Which diseases involve gene {gene}?",
        "What conditions are linked to {gene}?",
    ],
    "pathway-centered": [
        "What genes are involved in the {pathway} pathway?",
        "Which genes participate in {pathway}?",
        "What are the key genes in the {pathway} pathway?",
    ]
}


def generate_id(content: str) -> str:
    """生成唯一 ID"""
    return hashlib.md5(content.encode()).hexdigest()[:12]


def load_opentargets_data(raw_data_dir: Path) -> tuple:
    """加载 Open Targets 数据"""
    disease_file = raw_data_dir / "opentargets_disease_associations.json"
    gene_file = raw_data_dir / "opentargets_gene_associations.json"
    
    disease_data = []
    gene_data = []
    
    if disease_file.exists():
        with open(disease_file, "r", encoding="utf-8") as f:
            disease_data = json.load(f)
        print(f"✓ Loaded {len(disease_data)} disease records from Open Targets")
    else:
        print(f"⚠️ Disease file not found: {disease_file}")
    
    if gene_file.exists():
        with open(gene_file, "r", encoding="utf-8") as f:
            gene_data = json.load(f)
        print(f"✓ Loaded {len(gene_data)} gene records from Open Targets")
    else:
        print(f"⚠️ Gene file not found: {gene_file}")
    
    return disease_data, gene_data


def load_reactome_data(raw_data_dir: Path) -> List[Dict]:
    """加载 Reactome 数据"""
    pathway_file = raw_data_dir / "reactome_pathway_genes.json"
    
    if pathway_file.exists():
        with open(pathway_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"✓ Loaded {len(data)} pathway records from Reactome")
        return data
    else:
        print(f"⚠️ Pathway file not found: {pathway_file}")
        return []


def create_disease_centered_questions(disease_data: List[Dict], num_questions: int = 20) -> List[Dict]:
    """
    创建 disease-centered 测试问题
    """
    questions = []
    
    # 筛选有足够基因的疾病
    valid_diseases = [d for d in disease_data if len(d.get("filtered_genes", [])) >= 5]
    
    if len(valid_diseases) < num_questions:
        print(f"  ⚠️ Only {len(valid_diseases)} diseases have enough genes")
        num_questions = len(valid_diseases)
    
    # 随机选择疾病
    selected = random.sample(valid_diseases, min(num_questions, len(valid_diseases)))
    
    for disease in selected:
        disease_name = disease["disease_name"]
        template = random.choice(QUESTION_TEMPLATES["disease-centered"])
        question = template.format(disease=disease_name)
        
        # 提取 gold genes（取 top 20 高置信度）
        gold_genes = [
            g["gene_symbol"] 
            for g in sorted(disease["filtered_genes"], 
                          key=lambda x: x["association_score"], 
                          reverse=True)[:20]
        ]
        
        questions.append({
            "id": f"ind_dc_{generate_id(disease_name)}",
            "task_type": "disease-centered",
            "question": question,
            "disease_focus": disease_name,
            "disease_id": disease["disease_id"],
            "gold_genes": gold_genes,
            "gold_pathways": [],  # 需要从其他来源补充
            "gold_drugs": [],
            "gold_phenotypes": [],
            "confidence_scores": {
                g["gene_symbol"]: g["association_score"] 
                for g in disease["filtered_genes"][:20]
            },
            "source": "Open Targets Platform",
            "annotation_status": "independent_source",
            "created_at": datetime.now().isoformat()
        })
    
    return questions


def create_gene_centered_questions(gene_data: List[Dict], num_questions: int = 20) -> List[Dict]:
    """
    创建 gene-centered 测试问题
    """
    questions = []
    
    # 筛选有足够疾病关联的基因
    valid_genes = [g for g in gene_data if len(g.get("filtered_diseases", [])) >= 3]
    
    if len(valid_genes) < num_questions:
        print(f"  ⚠️ Only {len(valid_genes)} genes have enough disease associations")
        num_questions = len(valid_genes)
    
    selected = random.sample(valid_genes, min(num_questions, len(valid_genes)))
    
    for gene in selected:
        gene_symbol = gene["gene_symbol"]
        template = random.choice(QUESTION_TEMPLATES["gene-centered"])
        question = template.format(gene=gene_symbol)
        
        # 提取 gold diseases（取 top 15 高置信度）
        gold_diseases = [
            d["disease_name"]
            for d in sorted(gene["filtered_diseases"],
                          key=lambda x: x["association_score"],
                          reverse=True)[:15]
        ]
        
        questions.append({
            "id": f"ind_gc_{generate_id(gene_symbol)}",
            "task_type": "gene-centered",
            "question": question,
            "gene_focus": gene_symbol,
            "gene_id": gene["gene_id"],
            "gold_genes": [gene_symbol],
            "gold_diseases": gold_diseases,
            "gold_pathways": [],
            "gold_drugs": [],
            "confidence_scores": {
                d["disease_name"]: d["association_score"]
                for d in gene["filtered_diseases"][:15]
            },
            "source": "Open Targets Platform",
            "annotation_status": "independent_source",
            "created_at": datetime.now().isoformat()
        })
    
    return questions


def create_pathway_centered_questions(pathway_data: List[Dict], num_questions: int = 15) -> List[Dict]:
    """
    创建 pathway-centered 测试问题
    """
    questions = []
    
    # 筛选有足够基因的通路
    valid_pathways = [p for p in pathway_data if p.get("gene_count", 0) >= 10]
    
    if len(valid_pathways) < num_questions:
        print(f"  ⚠️ Only {len(valid_pathways)} pathways have enough genes")
        num_questions = len(valid_pathways)
    
    selected = random.sample(valid_pathways, min(num_questions, len(valid_pathways)))
    
    for pathway in selected:
        pathway_name = pathway["pathway_name"]
        template = random.choice(QUESTION_TEMPLATES["pathway-centered"])
        question = template.format(pathway=pathway_name)
        
        # 提取 gold genes（限制数量避免过多）
        gold_genes = pathway["genes"][:30]
        
        questions.append({
            "id": f"ind_pc_{generate_id(pathway_name)}",
            "task_type": "pathway-centered",
            "question": question,
            "pathway_focus": pathway_name,
            "pathway_id": pathway["pathway_id"],
            "gold_genes": gold_genes,
            "gold_pathways": [pathway_name],
            "gold_drugs": [],
            "gene_count": len(gold_genes),
            "source": "Reactome",
            "annotation_status": "independent_source",
            "created_at": datetime.now().isoformat()
        })
    
    return questions


def generate_testset(raw_data_dir: Path, output_dir: Path):
    """
    生成完整的独立测试集
    """
    print("=" * 60)
    print("📦 Generating Independent Test Set")
    print("=" * 60)
    
    # 加载原始数据
    print("\n📂 Loading raw data...")
    disease_data, gene_data = load_opentargets_data(raw_data_dir)
    pathway_data = load_reactome_data(raw_data_dir)
    
    if not disease_data and not gene_data and not pathway_data:
        print("❌ No data available. Please run fetch scripts first:")
        print("   python fetch_opentargets.py")
        print("   python fetch_reactome.py")
        return
    
    # 生成测试问题
    print("\n🔧 Generating test questions...")
    
    all_questions = []
    
    # Disease-centered (20 questions)
    if disease_data:
        print("  Creating disease-centered questions...")
        dc_questions = create_disease_centered_questions(disease_data, num_questions=20)
        all_questions.extend(dc_questions)
        print(f"    ✓ Created {len(dc_questions)} disease-centered questions")
    
    # Gene-centered (20 questions)
    if gene_data:
        print("  Creating gene-centered questions...")
        gc_questions = create_gene_centered_questions(gene_data, num_questions=20)
        all_questions.extend(gc_questions)
        print(f"    ✓ Created {len(gc_questions)} gene-centered questions")
    
    # Pathway-centered (15 questions)
    if pathway_data:
        print("  Creating pathway-centered questions...")
        pc_questions = create_pathway_centered_questions(pathway_data, num_questions=15)
        all_questions.extend(pc_questions)
        print(f"    ✓ Created {len(pc_questions)} pathway-centered questions")
    
    # 随机打乱顺序
    random.shuffle(all_questions)
    
    # 保存测试集
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "independent_gold_final.jsonl"
    
    with open(output_file, "w", encoding="utf-8") as f:
        for q in all_questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    
    print(f"\n✅ Saved {len(all_questions)} test cases to {output_file}")
    
    # 生成摘要报告
    summary = {
        "total_questions": len(all_questions),
        "by_task_type": {
            "disease-centered": len([q for q in all_questions if q["task_type"] == "disease-centered"]),
            "gene-centered": len([q for q in all_questions if q["task_type"] == "gene-centered"]),
            "pathway-centered": len([q for q in all_questions if q["task_type"] == "pathway-centered"]),
        },
        "by_source": {
            "Open Targets": len([q for q in all_questions if q["source"] == "Open Targets Platform"]),
            "Reactome": len([q for q in all_questions if q["source"] == "Reactome"]),
        },
        "generated_at": datetime.now().isoformat(),
        "note": "This test set is constructed from independent data sources (Open Targets, Reactome), separate from PrimeKG used in the system's knowledge graph.",
        "validation_status": "Pending PrimeKG coverage analysis"
    }
    
    summary_file = output_dir / "testset_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"📊 Summary saved to {summary_file}")
    
    # 打印统计
    print("\n" + "=" * 60)
    print("📊 Test Set Statistics")
    print("=" * 60)
    print(f"Total questions: {len(all_questions)}")
    print(f"  - Disease-centered: {summary['by_task_type']['disease-centered']}")
    print(f"  - Gene-centered: {summary['by_task_type']['gene-centered']}")
    print(f"  - Pathway-centered: {summary['by_task_type']['pathway-centered']}")
    print(f"\nData sources:")
    print(f"  - Open Targets: {summary['by_source']['Open Targets']}")
    print(f"  - Reactome: {summary['by_source']['Reactome']}")
    
    return all_questions


if __name__ == "__main__":
    # 设置目录
    script_dir = Path(__file__).parent.parent
    raw_data_dir = script_dir / "raw_data"
    output_dir = script_dir / "output"
    
    print("🚀 Starting test set generation...")
    print(f"   Raw data: {raw_data_dir}")
    print(f"   Output: {output_dir}")
    print()
    
    # 设置随机种子以确保可复现
    random.seed(42)
    
    questions = generate_testset(raw_data_dir, output_dir)
    
    print("\n" + "=" * 60)
    print("✅ Test set generation complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Run: python validate_primekg_coverage.py")
    print("2. Review the coverage analysis")
    print("3. Use independent_gold_final.jsonl for evaluation")
