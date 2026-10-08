"""
PopGen Agent - 控制层 / Orchestrator
====================================

一个"逻辑 agent"，内部是一条固定流水线，每一步跑在自己隔离的 conda 环境里。
本文件只负责【机械编排】：按顺序把每一步派发到正确的环境执行，最后把各步产物
汇总成一个 evidence_pack.json 交给 e-Gene。它本身不装任何生信/ML 工具。

数据流：
    FASTQ ─(步骤1: popgen)────────► patient.vcf
    patient.vcf ─(步骤2: popgen_analysis)──► 祖先/频率 (partial evidence)
    patient.vcf ─(步骤3: popgen_gnn)───────► 祖先决策 + 置信度
    汇总 ──────────────────────────► evidence_pack.json ──► e-Gene

设计原则：
    - 每步用 `conda run -n <env>` 拉起对应环境，跑完即退，环境之间零耦合。
    - 步骤之间只通过【文件】传递（vcf / json），不共享 Python 进程状态。
    - 契约固定在 contracts/evidence_pack.schema.json。
"""

import os
import json
import logging
import argparse
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

ROOT = Path(__file__).resolve().parent

# ---- 每一步绑定的 conda 环境（按功能隔离，互不冲突）----
ENV_PREPROCESS = "popgen"           # bwa/gatk/samtools/plink2/nextflow/fastqc
ENV_ANALYSIS = "popgen_analysis"    # plink/smartpca/admixture/treemix/bcftools
ENV_GNN = "popgen_gnn"              # torch/pyg/scikit-allel

STEP_PREPROCESS = ROOT / "steps" / "01_preprocess"
STEP_ANALYSIS = ROOT / "steps" / "02_analysis"
STEP_GNN = ROOT / "steps" / "03_gnn"


def conda_run(env: str, command: str, cwd: Path | None = None) -> None:
    """在指定 conda 环境里执行一条命令（机械派发的核心）。"""
    full = f"conda run --no-capture-output -n {env} {command}"
    logging.info(f"[env={env}] {command}")
    subprocess.run(full, shell=True, check=True, cwd=str(cwd) if cwd else None)


# ---------------- 三个步骤 ---------------- #

def find_patient_vcf(outdir: Path) -> Path:
    """优先用未压缩 patient.vcf，其次 patient.vcf.gz。"""
    for name in ("patient.vcf", "patient.vcf.gz"):
        candidate = outdir / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"步骤 1 未产出 patient.vcf(.gz)：{outdir}")


def run_preprocess(fastq_dir: Path, ref_fasta: Path, outdir: Path) -> Path:
    """步骤 1：FASTQ → VCF（Nextflow，环境 popgen）。返回 patient.vcf 路径。"""
    logging.info("====== 步骤 1 预处理 (FASTQ→VCF) ======")
    if fastq_dir is None:
        fastq_dir = ROOT / "data" / "fastq"
    if ref_fasta is None:
        ref_fasta = ROOT / "data" / "reference" / "GRCh38.fa"
    conda_run(
        ENV_PREPROCESS,
        (
            f"nextflow run main.nf "
            f"--fastq_dir {fastq_dir} --ref {ref_fasta} --outdir {outdir}"
        ),
        cwd=STEP_PREPROCESS,
    )
    return find_patient_vcf(outdir)


def run_analysis(vcf: Path, outdir: Path) -> Path:
    """步骤 2：祖先/频率分析（环境 popgen_analysis）。返回 partial_evidence.json。"""
    logging.info("====== 步骤 2 群体分析 (祖先/频率) ======")
    conda_run(
        ENV_ANALYSIS,
        f"python popgen_agent.py --vcf {vcf} --outdir {outdir}",
        cwd=STEP_ANALYSIS,
    )
    return outdir / "partial_evidence.json"


def run_gnn(vcf: Path, outdir: Path) -> Path:
    """步骤 3：GNN 祖先决策（定位 A，环境 popgen_gnn）。返回 gnn_decision.json。"""
    logging.info("====== 步骤 3 GNN 祖先决策 ======")
    model = STEP_GNN / "model.pt"
    extra = f" --model {model}" if model.exists() else ""
    conda_run(
        ENV_GNN,
        f"python decide.py --vcf {vcf} --outdir {outdir}{extra}",
        cwd=STEP_GNN,
    )
    return outdir / "gnn_decision.json"


# ---------------- 汇总 ---------------- #

def aggregate_evidence_pack(
    partial_evidence: Path,
    gnn_decision: Path | None,
    outdir: Path,
    results_dir: Path | None = None,
) -> Path:
    sys.path.insert(0, str(ROOT))
    from pack import build_evidence_pack, validate_pack

    logging.info("====== 汇总 evidence_pack.json ======")
    src_results = results_dir or outdir
    pack_dir = src_results / "delivery"
    pack_path = build_evidence_pack(
        partial_evidence=partial_evidence,
        gnn_decision=gnn_decision,
        pack_dir=pack_dir,
        results_dir=src_results,
    )
    validate_pack(pack_path)
    logging.info("====== 交付物已生成: %s ======", pack_path)
    return pack_path


# ---------------- 主入口 ---------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="PopGen Agent orchestrator (Part 1 + Part 2)")
    parser.add_argument(
        "--fastq-dir",
        type=Path,
        default=ROOT / "data" / "fastq",
        help="病人双端 FASTQ 目录（默认 data/fastq）",
    )
    parser.add_argument("--vcf", type=Path, help="直接给 VCF（跳过预处理）")
    parser.add_argument(
        "--ref",
        type=Path,
        default=ROOT / "data" / "reference" / "GRCh38.fa",
        help="参考基因组 FASTA (GRCh38)",
    )
    parser.add_argument("--outdir", type=Path, default=ROOT / "results")
    parser.add_argument("--skip-gnn", action="store_true", help="跳过步骤 3（M2 交付应加此开关）")
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="跳过步骤 2，复用 outdir/partial_evidence.json",
    )
    parser.add_argument(
        "--pack-only",
        action="store_true",
        help="不重跑步骤 1/2/3，用已有 partial_evidence 和 gnn_decision 写出 delivery 包",
    )
    args = parser.parse_args()

    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    if args.pack_only:
        partial_evidence = outdir / "partial_evidence.json"
        if not partial_evidence.exists():
            raise FileNotFoundError(partial_evidence)
        gnn_decision = outdir / "gnn_decision.json"
        gnn_path = gnn_decision if gnn_decision.exists() else None
        aggregate_evidence_pack(partial_evidence, gnn_path, outdir, results_dir=outdir)
        return

    if args.vcf:
        vcf = args.vcf.resolve()
        logging.info(f"跳过预处理，直接使用给定 VCF: {vcf}")
    else:
        vcf = run_preprocess(args.fastq_dir.resolve(), args.ref.resolve(), outdir)

    if args.skip_analysis:
        partial_evidence = outdir / "partial_evidence.json"
        if not partial_evidence.exists():
            raise FileNotFoundError(partial_evidence)
        logging.info("跳过步骤 2，复用 %s", partial_evidence)
    else:
        partial_evidence = run_analysis(vcf, outdir)

    gnn_decision = None
    if not args.skip_gnn:
        gnn_decision = run_gnn(vcf, outdir)

    aggregate_evidence_pack(partial_evidence, gnn_decision, outdir, results_dir=outdir)


if __name__ == "__main__":
    main()
