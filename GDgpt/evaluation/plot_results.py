"""
根据 results_summary.json 生成实验对比图表。

用法：
  python evaluation/plot_results.py --input evaluation/results/results_summary.json
  python evaluation/plot_results.py --input results_summary.json --output-dir evaluation/results
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="根据 results_summary.json 生成对比图表")
    parser.add_argument("--input", required=True, help="results_summary.json 路径")
    parser.add_argument("--output-dir", default=None, help="图表输出目录（默认与 input 同目录）")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在: {input_path}")
        sys.exit(1)

    with input_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
    except ImportError:
        print("错误: 需要 matplotlib。请运行: pip install matplotlib")
        sys.exit(1)

    experiments = data.get("experiments", [])
    if not experiments:
        print("警告: 无实验数据，跳过画图")
        return

    ids = [e["id"] for e in experiments]
    x = range(len(ids))

    # 1. Retrieval 指标
    retrieval_keys = []
    for e in experiments:
        for k in e.get("retrieval", {}).keys():
            if k not in retrieval_keys:
                retrieval_keys.append(k)

    if retrieval_keys:
        fig, ax = plt.subplots(figsize=(10, 5))
        width = 0.8 / len(retrieval_keys)
        for i, key in enumerate(retrieval_keys):
            vals = [e.get("retrieval", {}).get(key, 0) for e in experiments]
            if any(v is None for v in vals):
                vals = [v if v is not None else 0 for v in vals]
            offset = (i - len(retrieval_keys) / 2 + 0.5) * width
            ax.bar([xi + offset for xi in x], vals, width, label=key)
        ax.set_xticks(x)
        ax.set_xticklabels(ids, rotation=15, ha="right")
        ax.set_ylabel("Score")
        ax.set_title("Retrieval Metrics")
        ax.legend(loc="upper right", fontsize=8)
        ax.set_ylim(0, 1.05)
        fig.tight_layout()
        fig.savefig(output_dir / "retrieval_metrics.png", dpi=150)
        plt.close()
        print(f"已保存: {output_dir / 'retrieval_metrics.png'}")

    # 2. End-to-end 指标
    e2e_keys = ["gene_f1", "pathway_f1", "phenotype_f1"]
    e2e_vals = {k: [] for k in e2e_keys}
    for e in experiments:
        ee = e.get("end_to_end", {})
        for k in e2e_keys:
            v = ee.get(k)
            e2e_vals[k].append(v if v is not None else 0)

    if any(e2e_vals[k] for k in e2e_keys):
        fig, ax = plt.subplots(figsize=(10, 5))
        width = 0.8 / len(e2e_keys)
        for i, key in enumerate(e2e_keys):
            vals = e2e_vals[key]
            offset = (i - len(e2e_keys) / 2 + 0.5) * width
            ax.bar([xi + offset for xi in x], vals, width, label=key)
        ax.set_xticks(x)
        ax.set_xticklabels(ids, rotation=15, ha="right")
        ax.set_ylabel("F1")
        ax.set_title("End-to-End Metrics (Gene / Pathway / Phenotype F1)")
        ax.legend(loc="upper right")
        ax.set_ylim(0, 1.05)
        fig.tight_layout()
        fig.savefig(output_dir / "e2e_metrics.png", dpi=150)
        plt.close()
        print(f"已保存: {output_dir / 'e2e_metrics.png'}")


if __name__ == "__main__":
    main()
