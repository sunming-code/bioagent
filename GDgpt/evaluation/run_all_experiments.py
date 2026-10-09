"""
实验自动化脚本：按配置依次运行多种实验，抽取实体、计算指标，并生成对比图表。

用法：
  cd Lib\\MDTeamGPT
  python evaluation/run_all_experiments.py           # 全量 30 题
  python evaluation/run_all_experiments.py --quick   # 快速验证（3 题）
  python evaluation/run_all_experiments.py --config evaluation/my_config.yaml
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# 脚本所在目录（evaluation/）
EVAL_DIR = Path(__file__).resolve().parent
# 项目根目录（Lib/MDTeamGPT）
PROJECT_ROOT = EVAL_DIR.parent


def load_config(path: Path) -> dict:
    """加载 YAML 配置。"""
    try:
        import yaml
    except ImportError:
        print("错误: 需要 PyYAML。请运行: pip install pyyaml")
        sys.exit(1)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_cmd(cmd: List[str], cwd: Path, capture: bool = False) -> Optional[subprocess.CompletedProcess]:
    """执行命令。capture=True 时捕获输出，否则实时打印。失败时返回 None。"""
    print(f"  $ {' '.join(cmd)}")
    if capture:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    else:
        result = subprocess.run(cmd, cwd=cwd, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(f"  ⚠ 命令返回码 {result.returncode}")
        if capture and (result.stderr or result.stdout):
            print(result.stderr or result.stdout)
        return None
    return result


def main():
    parser = argparse.ArgumentParser(description="实验自动化：多配置批量评测 + 指标汇总 + 可视化")
    parser.add_argument(
        "--config",
        default=str(EVAL_DIR / "experiment_config.yaml"),
        help="配置文件路径",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速验证模式（使用配置中的 gold 文件，仅跑前 3 题）",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        sys.exit(1)

    cfg = load_config(config_path)
    gold = Path(cfg["gold"])
    output_dir = Path(cfg["output_dir"])
    metrics_k = cfg.get("metrics_k", 5)
    experiments = cfg["experiments"]

    if not gold.is_absolute():
        gold = PROJECT_ROOT / gold
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    if args.quick:
        print(f"快速模式: 使用 {gold.name}（仅跑前 3 题）")

    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "config": {"gold": str(gold), "metrics_k": metrics_k, "quick": args.quick},
        "experiments": [],
    }

    for exp in experiments:
        exp_id = exp["id"]
        exp_type = exp["experiment"]
        max_rounds = exp.get("max_rounds", 6)
        desc = exp.get("description", exp_id)

        print(f"\n{'='*60}")
        print(f"[{exp_id}] {desc}")
        print("=" * 60)

        raw_path = output_dir / f"{exp_id}_raw.jsonl"
        pred_path = output_dir / f"{exp_id}.jsonl"

        # Step 1: 批量预测（实时打印进度，支持断点续跑）
        run_cmd(
            [
                sys.executable, "-u",
                str(EVAL_DIR / "run_batch_eval_template.py"),
                "--gold", str(gold),
                "--out", str(raw_path),
                "--max-rounds", str(max_rounds),
                "--experiment", exp_type,
                "--resume",
            ],
            cwd=PROJECT_ROOT,
            capture=False,
        )

        # Step 2: 抽取实体（使用 KG 工具的模式都有 tool_calls）
        if exp_type in {"full", "single_agent", "rag_only"}:
            run_cmd(
                [
                    sys.executable,
                    str(EVAL_DIR / "extract_from_tool_calls.py"),
                    "--pred", str(raw_path),
                    "--out", str(pred_path),
                ],
                cwd=PROJECT_ROOT,
                capture=True,
            )
        else:
            # llm_only / gpt4o_direct 无 tool_calls，直接使用 raw 作为 pred（predicted_* 为空）
            pred_path.write_bytes(raw_path.read_bytes())

        # Step 3: 计算指标
        result = run_cmd(
            [
                sys.executable,
                str(EVAL_DIR / "compute_metrics.py"),
                "--gold", str(gold),
                "--pred", str(pred_path),
                "--k", str(metrics_k),
            ],
            cwd=PROJECT_ROOT,
            capture=True,
        )
        if result and result.stdout:
            metrics = json.loads(result.stdout)
        else:
            print(f"  ⚠ {exp_id} 指标计算失败，跳过")
            metrics = {}
        summary["experiments"].append({
            "id": exp_id,
            "description": desc,
            "retrieval": metrics.get("retrieval", {}),
            "end_to_end": metrics.get("end_to_end", {}),
            "num_predictions": metrics.get("num_predictions", 0),
            "missing_predictions": metrics.get("missing_predictions", []),
        })

    # 写入汇总
    summary_path = output_dir / "results_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n汇总已保存: {summary_path}")

    # Step 4: 画图
    plot_script = EVAL_DIR / "plot_results.py"
    if plot_script.exists():
        run_cmd(
            [
                sys.executable,
                str(plot_script),
                "--input", str(summary_path),
                "--output-dir", str(output_dir),
            ],
            cwd=PROJECT_ROOT,
            capture=True,
        )
        print(f"图表已生成到: {output_dir}")
    else:
        print("提示: plot_results.py 不存在，跳过画图")

    print("\n实验完成。")


if __name__ == "__main__":
    main()
