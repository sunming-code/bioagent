#!/usr/bin/env python3
"""
根据覆盖率分析结果，筛选高质量测试问题
创建适合 KG 评测的最终测试集
"""

import json
from pathlib import Path
from datetime import datetime

def load_coverage_analysis(filepath: Path) -> dict:
    """加载覆盖率分析结果"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def load_testset(filepath: Path) -> list:
    """加载测试集"""
    questions = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))
    return questions

def filter_testset(questions: list, coverage: dict) -> dict:
    """
    根据覆盖率筛选测试集
    返回分层的测试集
    """
    # 获取已匹配的疾病和通路
    matched_diseases = set(coverage["entity_coverage"]["diseases"]["matched"].keys())
    matched_pathways = set(coverage["entity_coverage"]["pathways"]["matched"].keys())
    
    # 分类问题
    high_quality = []  # 高质量：适合测 KG 检索能力
    medium_quality = []  # 中等质量：部分覆盖
    low_quality = []  # 低质量：覆盖率低，但可测 LLM fallback
    
    for q in questions:
        task_type = q.get("task_type", "unknown")
        
        if task_type == "gene-centered":
            # gene-centered 问题覆盖率最高（95%完全覆盖），都是高质量
            gold_genes = q.get("gold_genes", [])
            high_quality.append({
                **q,
                "quality_tier": "high",
                "reason": f"gene-centered with {len(gold_genes)} gold genes, 95% fully covered in analysis"
            })
        
        elif task_type == "disease-centered":
            disease = q.get("disease_focus", "")
            # 检查疾病是否真正匹配（排除误匹配）
            if disease.lower() in ["lung carcinoma", "breast carcinoma", 
                                    "hepatocellular carcinoma", "prostate carcinoma",
                                    "colorectal carcinoma"]:
                high_quality.append({
                    **q,
                    "quality_tier": "high",
                    "reason": f"disease '{disease}' confirmed in PrimeKG"
                })
            elif disease in matched_diseases:
                # 可能是误匹配，降级为 medium
                medium_quality.append({
                    **q,
                    "quality_tier": "medium",
                    "reason": f"disease '{disease}' may have fuzzy match"
                })
            else:
                low_quality.append({
                    **q,
                    "quality_tier": "low",
                    "reason": f"disease '{disease}' not in PrimeKG"
                })
        
        elif task_type == "pathway-centered":
            pathway = q.get("pathway_focus", "")
            # 检查是否精确匹配（而非模糊匹配）
            exact_matches = ["Cholesterol biosynthesis", "Base Excision Repair", 
                           "Autophagy", "Signaling by NOTCH", "Metabolism"]
            if any(em.lower() in pathway.lower() for em in exact_matches):
                high_quality.append({
                    **q,
                    "quality_tier": "high",
                    "reason": f"pathway '{pathway}' has good match"
                })
            else:
                medium_quality.append({
                    **q,
                    "quality_tier": "medium", 
                    "reason": f"pathway '{pathway}' has fuzzy match"
                })
    
    return {
        "high_quality": high_quality,
        "medium_quality": medium_quality,
        "low_quality": low_quality
    }

def create_final_testsets(filtered: dict, output_dir: Path):
    """创建最终测试集文件"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 高质量测试集（推荐用于 KG 评测）
    high_file = output_dir / "testset_high_quality.jsonl"
    with open(high_file, "w", encoding="utf-8") as f:
        for q in filtered["high_quality"]:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"✅ High quality testset: {len(filtered['high_quality'])} questions → {high_file}")
    
    # 2. 完整测试集（高+中质量）
    combined = filtered["high_quality"] + filtered["medium_quality"]
    combined_file = output_dir / "testset_combined.jsonl"
    with open(combined_file, "w", encoding="utf-8") as f:
        for q in combined:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"✅ Combined testset: {len(combined)} questions → {combined_file}")
    
    # 3. 所有问题（包括低质量，用于测试 LLM fallback）
    all_questions = combined + filtered["low_quality"]
    all_file = output_dir / "testset_all_tiers.jsonl"
    with open(all_file, "w", encoding="utf-8") as f:
        for q in all_questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"✅ All tiers testset: {len(all_questions)} questions → {all_file}")
    
    # 4. 生成摘要
    summary = {
        "created_at": datetime.now().isoformat(),
        "statistics": {
            "high_quality": {
                "count": len(filtered["high_quality"]),
                "description": "Best for KG retrieval evaluation"
            },
            "medium_quality": {
                "count": len(filtered["medium_quality"]),
                "description": "Partial KG coverage, still useful"
            },
            "low_quality": {
                "count": len(filtered["low_quality"]),
                "description": "Low KG coverage, tests LLM fallback"
            }
        },
        "by_task_type": {
            "high_quality": {},
            "medium_quality": {},
            "low_quality": {}
        },
        "recommended_usage": {
            "kg_evaluation": "testset_high_quality.jsonl",
            "full_system_evaluation": "testset_combined.jsonl",
            "ablation_study": "testset_all_tiers.jsonl"
        }
    }
    
    # 统计各类型分布
    for tier_name, tier_questions in filtered.items():
        for q in tier_questions:
            task_type = q.get("task_type", "unknown")
            if task_type not in summary["by_task_type"][tier_name]:
                summary["by_task_type"][tier_name][task_type] = 0
            summary["by_task_type"][tier_name][task_type] += 1
    
    summary_file = output_dir / "testset_summary_filtered.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"✅ Summary: {summary_file}")
    
    return summary

def main():
    script_dir = Path(__file__).parent.parent
    output_dir = script_dir / "output"
    processed_dir = script_dir / "processed"
    
    print("🔧 Creating Filtered Test Sets")
    print("=" * 60)
    
    # 加载数据
    coverage_file = processed_dir / "coverage_analysis_v2.json"
    testset_file = output_dir / "independent_gold_final.jsonl"
    
    if not coverage_file.exists():
        print(f"❌ Coverage analysis not found: {coverage_file}")
        print("   Please run validate_primekg_coverage_v2.py first.")
        return
    
    if not testset_file.exists():
        print(f"❌ Test set not found: {testset_file}")
        return
    
    coverage = load_coverage_analysis(coverage_file)
    questions = load_testset(testset_file)
    
    print(f"📊 Loaded {len(questions)} questions")
    print(f"📊 Coverage analysis method: {coverage['summary'].get('method', 'unknown')}")
    
    # 筛选测试集
    filtered = filter_testset(questions, coverage)
    
    print(f"\n📋 Filtering Results:")
    print(f"   - High quality:   {len(filtered['high_quality'])} questions")
    print(f"   - Medium quality: {len(filtered['medium_quality'])} questions")
    print(f"   - Low quality:    {len(filtered['low_quality'])} questions")
    
    # 创建输出文件
    print(f"\n📁 Creating output files...")
    summary = create_final_testsets(filtered, output_dir)
    
    print(f"\n" + "=" * 60)
    print("📊 Final Statistics by Task Type:")
    print("=" * 60)
    
    for tier_name in ["high_quality", "medium_quality", "low_quality"]:
        print(f"\n{tier_name.upper()}:")
        for task_type, count in summary["by_task_type"][tier_name].items():
            print(f"   - {task_type}: {count}")
    
    print(f"\n" + "=" * 60)
    print("🎯 Recommended Usage:")
    print("=" * 60)
    print(f"   - KG Evaluation:          {summary['recommended_usage']['kg_evaluation']}")
    print(f"   - Full System Evaluation: {summary['recommended_usage']['full_system_evaluation']}")
    print(f"   - Ablation Study:         {summary['recommended_usage']['ablation_study']}")
    
    print(f"\n✅ Done!")

if __name__ == "__main__":
    main()
