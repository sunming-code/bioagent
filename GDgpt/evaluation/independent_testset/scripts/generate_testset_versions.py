#!/usr/bin/env python3
"""
生成两个版本的测试集：
1. 快速验证版 (Quick): 30 题 - 用于快速验证流程
2. 完整测试版 (Full): 80 题 - 用于正式实验和论文
"""

import json
import random
from pathlib import Path
from datetime import datetime
import uuid

# 设置随机种子，确保可复现
random.seed(42)

# 路径配置
SCRIPT_DIR = Path(__file__).parent
RAW_DATA_DIR = SCRIPT_DIR.parent / "raw_data"
OUTPUT_DIR = SCRIPT_DIR.parent / "output"


def load_raw_data():
    """加载原始数据"""
    with open(RAW_DATA_DIR / "opentargets_disease_associations.json", "r") as f:
        disease_list = json.load(f)  # List of disease objects
    
    with open(RAW_DATA_DIR / "opentargets_gene_associations.json", "r") as f:
        gene_list = json.load(f)  # List of gene objects
    
    with open(RAW_DATA_DIR / "reactome_pathway_genes.json", "r") as f:
        pathway_list = json.load(f)  # List of pathway objects
    
    return disease_list, gene_list, pathway_list


def generate_disease_centered_questions(disease_list, count):
    """生成 disease-centered 问题"""
    questions = []
    templates = [
        "What genes are associated with {disease}?",
        "Which genes play a role in {disease}?",
        "What are the key genes involved in {disease}?",
        "List the genes linked to {disease}.",
        "What genetic factors contribute to {disease}?"
    ]
    
    # 随机选择疾病
    selected = random.sample(disease_list, min(count, len(disease_list)))
    
    for disease_obj in selected:
        disease_name = disease_obj.get("disease_name", "")
        disease_id = disease_obj.get("disease_id", "")
        filtered_genes = disease_obj.get("filtered_genes", [])
        
        if not filtered_genes:
            continue
        
        # 按置信度排序，取 top 20 基因
        sorted_genes = sorted(filtered_genes, key=lambda x: x.get("association_score", 0), reverse=True)[:20]
        gold_genes = [g["gene_symbol"] for g in sorted_genes]
        confidence_scores = {g["gene_symbol"]: g.get("association_score", 0) for g in sorted_genes}
        
        question = {
            "id": f"ind_dc_{uuid.uuid4().hex[:12]}",
            "task_type": "disease-centered",
            "question": random.choice(templates).format(disease=disease_name),
            "disease_focus": disease_name,
            "disease_id": disease_id,
            "gold_genes": gold_genes,
            "gold_pathways": [],
            "gold_drugs": [],
            "gold_phenotypes": [],
            "confidence_scores": confidence_scores,
            "source": "Open Targets Platform",
            "annotation_status": "independent_source",
            "created_at": datetime.now().isoformat()
        }
        questions.append(question)
    
    return questions


def generate_gene_centered_questions(gene_list, count):
    """生成 gene-centered 问题"""
    questions = []
    templates = [
        "What diseases are associated with gene {gene}?",
        "Which diseases are linked to {gene} mutations?",
        "What conditions involve the {gene} gene?",
        "List diseases where {gene} plays a role.",
        "What pathologies are connected to {gene}?"
    ]
    
    # 随机选择基因
    selected = random.sample(gene_list, min(count, len(gene_list)))
    
    for gene_obj in selected:
        gene_symbol = gene_obj.get("gene_symbol", "")
        gene_id = gene_obj.get("gene_id", "")
        filtered_diseases = gene_obj.get("filtered_diseases", [])
        
        if not filtered_diseases:
            continue
        
        # 按置信度排序，取 top 15 疾病
        sorted_diseases = sorted(filtered_diseases, key=lambda x: x.get("association_score", 0), reverse=True)[:15]
        gold_diseases = [d["disease_name"] for d in sorted_diseases]
        confidence_scores = {d["disease_name"]: d.get("association_score", 0) for d in sorted_diseases}
        
        question = {
            "id": f"ind_gc_{uuid.uuid4().hex[:12]}",
            "task_type": "gene-centered",
            "question": random.choice(templates).format(gene=gene_symbol),
            "gene_focus": gene_symbol,
            "gene_id": gene_id,
            "gold_genes": [gene_symbol],
            "gold_diseases": gold_diseases,
            "gold_pathways": [],
            "gold_drugs": [],
            "confidence_scores": confidence_scores,
            "source": "Open Targets Platform",
            "annotation_status": "independent_source",
            "created_at": datetime.now().isoformat()
        }
        questions.append(question)
    
    return questions


def generate_pathway_centered_questions(pathway_list, count):
    """生成 pathway-centered 问题"""
    questions = []
    templates = [
        "What genes are involved in the {pathway} pathway?",
        "Which genes participate in {pathway}?",
        "What are the key genes in the {pathway} pathway?",
        "List the genes that function in {pathway}.",
        "What genes are part of the {pathway} process?"
    ]
    
    # 随机选择通路
    selected = random.sample(pathway_list, min(count, len(pathway_list)))
    
    for pathway_obj in selected:
        pathway_name = pathway_obj.get("pathway_name", "")
        pathway_id = pathway_obj.get("pathway_id", "")
        genes = pathway_obj.get("genes", [])
        
        if not genes:
            continue
        
        # 过滤掉复杂的蛋白质复合物名称，只保留标准基因符号
        clean_genes = [g for g in genes if not any(c in g for c in ['(', ')', '-', 'p-', 'Ac-'])]
        if len(clean_genes) < 5:
            clean_genes = genes  # 如果过滤后太少，就用原始的
        
        # 取前 30 个基因
        gold_genes = clean_genes[:30] if len(clean_genes) > 30 else clean_genes
        
        question = {
            "id": f"ind_pc_{uuid.uuid4().hex[:12]}",
            "task_type": "pathway-centered",
            "question": random.choice(templates).format(pathway=pathway_name),
            "pathway_focus": pathway_name,
            "pathway_id": pathway_id,
            "gold_genes": gold_genes,
            "gold_pathways": [pathway_name],
            "gold_drugs": [],
            "gene_count": len(gold_genes),
            "source": "Reactome",
            "annotation_status": "independent_source",
            "created_at": datetime.now().isoformat()
        }
        questions.append(question)
    
    return questions


def generate_testset(disease_list, gene_list, pathway_list, config):
    """根据配置生成测试集"""
    questions = []
    
    # 生成各类问题
    dc_questions = generate_disease_centered_questions(
        disease_list, config["disease_centered"]
    )
    gc_questions = generate_gene_centered_questions(
        gene_list, config["gene_centered"]
    )
    pc_questions = generate_pathway_centered_questions(
        pathway_list, config["pathway_centered"]
    )
    
    questions.extend(dc_questions)
    questions.extend(gc_questions)
    questions.extend(pc_questions)
    
    # 打乱顺序
    random.shuffle(questions)
    
    return questions


def save_testset(questions, filename, version_name):
    """保存测试集"""
    output_path = OUTPUT_DIR / filename
    
    with open(output_path, "w") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    
    # 生成统计信息
    by_type = {}
    for q in questions:
        t = q["task_type"]
        by_type[t] = by_type.get(t, 0) + 1
    
    summary = {
        "version": version_name,
        "total_questions": len(questions),
        "by_task_type": by_type,
        "by_source": {
            "Open Targets": sum(1 for q in questions if q["source"] == "Open Targets Platform"),
            "Reactome": sum(1 for q in questions if q["source"] == "Reactome")
        },
        "generated_at": datetime.now().isoformat(),
        "note": f"This is the {version_name} version of the independent test set.",
        "data_sources": {
            "Open Targets": "https://platform.opentargets.org/",
            "Reactome": "https://reactome.org/"
        }
    }
    
    summary_path = OUTPUT_DIR / filename.replace(".jsonl", "_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    return output_path, summary


def main():
    print("=" * 60)
    print("生成两个版本的测试集")
    print("=" * 60)
    
    # 加载数据
    print("\n📂 加载原始数据...")
    disease_list, gene_list, pathway_list = load_raw_data()
    
    print(f"  - 疾病数据: {len(disease_list)} 种疾病")
    print(f"  - 基因数据: {len(gene_list)} 个基因")
    print(f"  - 通路数据: {len(pathway_list)} 条通路")
    
    # 配置两个版本
    configs = {
        "quick": {
            "name": "Quick (快速验证版)",
            "filename": "testset_quick.jsonl",
            "disease_centered": 10,
            "gene_centered": 12,
            "pathway_centered": 8,
            "total_target": 30
        },
        "full": {
            "name": "Full (完整测试版)",
            "filename": "testset_full.jsonl",
            "disease_centered": 18,  # 所有疾病
            "gene_centered": 30,      # 所有基因
            "pathway_centered": 32,   # 所有通路
            "total_target": 80
        }
    }
    
    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 生成两个版本
    for version_key, config in configs.items():
        print(f"\n{'='*60}")
        print(f"📝 生成 {config['name']}")
        print(f"{'='*60}")
        
        questions = generate_testset(disease_list, gene_list, pathway_list, config)
        output_path, summary = save_testset(questions, config["filename"], config["name"])
        
        print(f"\n✅ 生成完成!")
        print(f"  - 文件: {output_path}")
        print(f"  - 总题数: {summary['total_questions']}")
        print(f"  - 按类型分布:")
        for task_type, count in summary["by_task_type"].items():
            print(f"      {task_type}: {count}")
    
    # 最终总结
    print("\n" + "=" * 60)
    print("📊 生成完成总结")
    print("=" * 60)
    print("""
┌─────────────────┬──────────┬─────────────────────────────────┐
│     版本        │  题数    │           用途                  │
├─────────────────┼──────────┼─────────────────────────────────┤
│ Quick (快速版)  │   30     │ 快速验证流程、调试代码          │
│ Full (完整版)   │   80     │ 正式实验、论文数据              │
└─────────────────┴──────────┴─────────────────────────────────┘

文件位置:
  - evaluation/independent_testset/output/testset_quick.jsonl
  - evaluation/independent_testset/output/testset_full.jsonl
""")


if __name__ == "__main__":
    main()
