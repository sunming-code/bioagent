#!/usr/bin/env python3
"""
Analysis by KG Coverage
========================
This script analyzes experimental results by stratifying based on
knowledge graph coverage levels.

Key Insight: PrimeKG only has 20 diseases, so disease-centered questions
may have limited KG support. This script helps identify when KG
augmentation is beneficial vs. when LLM alone performs similarly.

Usage:
    python analysis_by_coverage.py --predictions <path> --gold <path>
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Tuple


# PrimeKG 中已知存在的疾病（基于 coverage 分析）
PRIMEKG_DISEASES = {
    "lung cancer", "lung carcinoma",
    "breast carcinoma", "breast cancer",
    "hepatocellular carcinoma",
    "prostate carcinoma", "prostate cancer",
    "hereditary breast ovarian cancer syndrome",
    "ovarian cancer",
    # 添加更多 PrimeKG 中的疾病...
}

# 基于 coverage 分析的结果
COVERAGE_INFO = {
    "disease-centered": {
        "kg_coverage": 0.444,  # 44.4%
        "high_coverage_diseases": ["lung carcinoma", "breast carcinoma", 
                                    "hepatocellular carcinoma", "prostate carcinoma"],
        "low_coverage_diseases": ["coronary artery disease", "hypertension", 
                                   "melanoma", "Alzheimer disease", "leukemia"],
    },
    "pathway-centered": {
        "kg_coverage": 1.0,  # 100%
        "note": "All pathways are covered in PrimeKG"
    },
    "gene-centered": {
        "kg_coverage": 0.566,  # 56.6%
        "note": "Most important genes are covered"
    }
}


def load_jsonl(path: str) -> List[Dict]:
    """Load JSONL file."""
    data = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def classify_by_coverage(item: Dict) -> str:
    """
    Classify a question by expected KG coverage level.
    
    Returns:
        - "high": KG has good coverage, expect KG to help
        - "medium": KG has partial coverage
        - "low": KG lacks coverage, LLM must handle alone
    """
    task_type = item.get("task_type", "")
    
    if task_type == "pathway-centered":
        return "high"  # 100% pathway coverage
    
    if task_type == "gene-centered":
        # Check if gene is likely covered
        gene = item.get("gene_focus", "")
        # Most important genes are covered
        return "medium"
    
    if task_type == "disease-centered":
        disease = item.get("disease_focus", "").lower()
        
        # Check if disease is in PrimeKG
        for known_disease in PRIMEKG_DISEASES:
            if known_disease.lower() in disease or disease in known_disease.lower():
                return "high"
        
        return "low"
    
    return "unknown"


def compute_metrics(predictions: List[str], gold: List[List[str]]) -> Dict[str, float]:
    """Compute recall, precision, and F1 for a set of predictions."""
    if not predictions or not gold:
        return {"recall": 0.0, "precision": 0.0, "f1": 0.0, "count": len(gold)}
    
    total_recall = 0.0
    total_precision = 0.0
    count = 0
    
    for pred, gold_set in zip(predictions, gold):
        pred_lower = set(p.lower() for p in pred) if isinstance(pred, list) else set()
        gold_lower = set(g.lower() for g in gold_set) if gold_set else set()
        
        if not gold_lower:
            continue
        
        correct = len(pred_lower & gold_lower)
        recall = correct / len(gold_lower) if gold_lower else 0
        precision = correct / len(pred_lower) if pred_lower else 0
        
        total_recall += recall
        total_precision += precision
        count += 1
    
    if count == 0:
        return {"recall": 0.0, "precision": 0.0, "f1": 0.0, "count": 0}
    
    avg_recall = total_recall / count
    avg_precision = total_precision / count
    f1 = 2 * avg_recall * avg_precision / (avg_recall + avg_precision) if (avg_recall + avg_precision) > 0 else 0
    
    return {
        "recall": round(avg_recall, 4),
        "precision": round(avg_precision, 4),
        "f1": round(f1, 4),
        "count": count
    }


def analyze_by_coverage(gold_data: List[Dict], predictions: List[Dict] = None) -> Dict:
    """
    Analyze test set and optionally predictions by KG coverage level.
    """
    # Group by coverage level
    coverage_groups = defaultdict(list)
    
    for item in gold_data:
        coverage_level = classify_by_coverage(item)
        coverage_groups[coverage_level].append(item)
    
    # Generate report
    report = {
        "summary": {
            "total_questions": len(gold_data),
            "coverage_distribution": {}
        },
        "by_coverage_level": {},
        "recommendations": []
    }
    
    for level, items in sorted(coverage_groups.items()):
        report["summary"]["coverage_distribution"][level] = len(items)
        
        # Task type breakdown
        task_breakdown = defaultdict(int)
        for item in items:
            task_breakdown[item.get("task_type", "unknown")] += 1
        
        report["by_coverage_level"][level] = {
            "count": len(items),
            "percentage": f"{100 * len(items) / len(gold_data):.1f}%",
            "task_breakdown": dict(task_breakdown),
            "sample_questions": [item.get("question", "")[:80] for item in items[:3]]
        }
    
    # Add recommendations
    high_count = len(coverage_groups.get("high", []))
    low_count = len(coverage_groups.get("low", []))
    
    if high_count >= 15:
        report["recommendations"].append(
            "✅ Sufficient high-coverage questions for demonstrating KG benefit"
        )
    else:
        report["recommendations"].append(
            f"⚠️ Only {high_count} high-coverage questions. Consider focusing on pathway-centered tasks."
        )
    
    if low_count > 10:
        report["recommendations"].append(
            f"📊 {low_count} questions have low KG coverage. Use these to analyze graceful degradation."
        )
    
    report["recommendations"].append(
        "💡 Report results separately for high/medium/low coverage groups in your paper."
    )
    
    return report


def format_latex_table(results: Dict) -> str:
    """Generate LaTeX table for paper."""
    latex = r"""
\begin{table}[h]
\centering
\caption{Performance Analysis by KG Coverage Level}
\begin{tabular}{lccc}
\toprule
Coverage Level & Questions & Recall & F1 \\
\midrule
"""
    
    for level in ["high", "medium", "low"]:
        if level in results.get("by_coverage_level", {}):
            info = results["by_coverage_level"][level]
            count = info["count"]
            latex += f"{level.capitalize()} & {count} & -- & -- \\\\\n"
    
    latex += r"""
\bottomrule
\end{tabular}
\label{tab:coverage_analysis}
\end{table}
"""
    return latex


def main():
    parser = argparse.ArgumentParser(description="Analyze by KG coverage")
    parser.add_argument("--gold", type=str, default="independent_testset/output/testset_high_quality.jsonl",
                        help="Path to gold standard JSONL")
    parser.add_argument("--predictions", type=str, default=None,
                        help="Path to predictions JSONL (optional)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output path for analysis")
    args = parser.parse_args()
    
    # Load data
    gold_path = Path(__file__).parent / args.gold
    if not gold_path.exists():
        gold_path = Path(args.gold)
    
    print(f"Loading gold data from: {gold_path}")
    gold_data = load_jsonl(str(gold_path))
    
    # Run analysis
    report = analyze_by_coverage(gold_data)
    
    # Print report
    print("\n" + "="*60)
    print("📊 KG COVERAGE ANALYSIS REPORT")
    print("="*60)
    
    print(f"\n总问题数: {report['summary']['total_questions']}")
    print(f"覆盖率分布: {report['summary']['coverage_distribution']}")
    
    print("\n--- 按覆盖率分组详情 ---")
    for level, info in report["by_coverage_level"].items():
        print(f"\n[{level.upper()}] {info['count']} 个问题 ({info['percentage']})")
        print(f"  任务类型: {info['task_breakdown']}")
        print(f"  示例问题:")
        for q in info["sample_questions"]:
            print(f"    - {q}...")
    
    print("\n--- 建议 ---")
    for rec in report["recommendations"]:
        print(f"  {rec}")
    
    # Save if output specified
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n报告已保存到: {output_path}")
    
    # Generate LaTeX
    print("\n--- LaTeX 表格模板 ---")
    print(format_latex_table(report))
    
    return report


if __name__ == "__main__":
    main()
