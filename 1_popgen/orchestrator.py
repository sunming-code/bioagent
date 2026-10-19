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
    - 每步调用对应隔离环境的可执行文件，跑完即退，环境之间只通过文件传递。
    - 步骤之间只通过【文件】传递（vcf / json），不共享 Python 进程状态。
    - 契约固定在 contracts/evidence_pack.schema.json。
"""

import logging
import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from runtime import run_in_environment

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

ROOT = Path(__file__).resolve().parent

# ---- 每一步绑定的 conda 环境（按功能隔离，互不冲突）----
ENV_PREPROCESS = "popgen"           # bwa/gatk/samtools/plink2/nextflow/fastqc
ENV_ANALYSIS = "popgen_analysis"    # plink/smartpca/admixture/treemix/bcftools
ENV_GNN = "popgen_gnn"              # torch/pyg/scikit-allel

STEP_PREPROCESS = ROOT / "steps" / "01_preprocess"
STEP_ANALYSIS = ROOT / "steps" / "02_analysis"
STEP_GNN = ROOT / "steps" / "03_gnn"


def _write_timing(
    outdir: Path,
    records: list[dict],
    run_started_at: str,
    run_t0: float,
    *,
    completed: bool,
) -> None:
    """Write a continuously updated, machine-readable stage timing record."""
    payload = {
        "schema_version": 1,
        "run_started_at_utc": run_started_at,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed": completed,
        "total_elapsed_seconds": round(time.perf_counter() - run_t0, 3),
        "stages": records,
    }
    (outdir / "timing.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def timed_stage(
    name: str,
    fn,
    *,
    outdir: Path,
    records: list[dict],
    run_started_at: str,
    run_t0: float,
):
    """Run one pipeline stage and persist its timing even when it fails."""
    started_at = datetime.now(timezone.utc)
    stage_t0 = time.perf_counter()
    logging.info("====== 阶段开始: %s ======", name)
    try:
        result = fn()
    except Exception as exc:
        records.append(
            {
                "name": name,
                "status": "failed",
                "started_at_utc": started_at.isoformat(),
                "ended_at_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.perf_counter() - stage_t0, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        _write_timing(outdir, records, run_started_at, run_t0, completed=False)
        raise
    records.append(
        {
            "name": name,
            "status": "succeeded",
            "started_at_utc": started_at.isoformat(),
            "ended_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.perf_counter() - stage_t0, 3),
        }
    )
    _write_timing(outdir, records, run_started_at, run_t0, completed=False)
    logging.info("====== 阶段完成: %s (%.3fs) ======", name, records[-1]["elapsed_seconds"])
    return result


def conda_run(env: str, command: list[str], cwd: Path | None = None, threads: int = 8) -> None:
    """在指定 conda 环境里执行一条命令（机械派发的核心）。"""
    logging.info("[env=%s] %s", env, command)
    run_in_environment(env, command, cwd=cwd, threads=threads)


# ---------------- 三个步骤 ---------------- #

def find_patient_vcf(outdir: Path) -> Path:
    """优先用未压缩 patient.vcf，其次 patient.vcf.gz。"""
    for name in ("patient.vcf", "patient.vcf.gz"):
        candidate = outdir / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"步骤 1 未产出 patient.vcf(.gz)：{outdir}")


def run_preprocess(fastq_dir: Path, ref_fasta: Path, outdir: Path, threads: int = 8) -> Path:
    """步骤 1：FASTQ → VCF（Nextflow，环境 popgen）。返回 patient.vcf 路径。"""
    logging.info("====== 步骤 1 预处理 (FASTQ→VCF) ======")
    if fastq_dir is None:
        fastq_dir = ROOT / "data" / "fastq"
    if ref_fasta is None:
        ref_fasta = ROOT / "data" / "reference" / "GRCh38.fa"
    conda_run(
        ENV_PREPROCESS,
        ["nextflow", "run", "main.nf", "--fastq_dir", str(fastq_dir), "--ref", str(ref_fasta), "--outdir", str(outdir), "--threads", str(threads)],
        cwd=STEP_PREPROCESS,
    )
    return find_patient_vcf(outdir)


def run_analysis(vcf: Path, outdir: Path, threads: int = 8, skip_cv: bool = False) -> Path:
    """步骤 2：祖先/频率分析（环境 popgen_analysis）。返回 partial_evidence.json。"""
    logging.info("====== 步骤 2 群体分析 (祖先/频率) ======")
    conda_run(
        ENV_ANALYSIS,
        ["python", "popgen_agent.py", "--vcf", str(vcf), "--outdir", str(outdir)] + (["--skip-cv"] if skip_cv else []),
        cwd=STEP_ANALYSIS,
        threads=threads,
    )
    return outdir / "partial_evidence.json"


def run_gnn(vcf: Path, outdir: Path, threads: int = 8) -> Path:
    """步骤 3：GNN 祖先决策（定位 A，环境 popgen_gnn）。返回 gnn_decision.json。"""
    logging.info("====== 步骤 3 GNN 祖先决策 ======")
    model = STEP_GNN / "model.pt"
    conda_run(
        ENV_GNN,
        ["python", "decide.py", "--vcf", str(vcf), "--outdir", str(outdir), "--model", str(model)],
        cwd=STEP_GNN,
        threads=threads,
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
    parser.add_argument("--outdir", type=Path, help="独立任务输出目录；默认自动创建 results/runs/<任务ID>")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--skip-cv", action="store_true", help="仅省略无监督 CV；仍输出监督祖先、频率和 GNN")
    parser.add_argument("--skip-gnn", action="store_true", help="显式跳过 GNN；默认执行冻结模型推理")
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

    if args.threads < 1:
        parser.error("--threads 必须为正整数")
    default_dir = ROOT / "results" if args.pack_only else ROOT / "results" / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    outdir = (args.outdir or default_dir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(timezone.utc).isoformat()
    run_t0 = time.perf_counter()
    timing_records: list[dict] = []

    if args.pack_only:
        partial_evidence = outdir / "partial_evidence.json"
        if not partial_evidence.exists():
            raise FileNotFoundError(partial_evidence)
        gnn_decision = outdir / "gnn_decision.json"
        gnn_path = gnn_decision if gnn_decision.exists() else None
        timed_stage(
            "evidence_pack",
            lambda: aggregate_evidence_pack(partial_evidence, gnn_path, outdir, results_dir=outdir),
            outdir=outdir,
            records=timing_records,
            run_started_at=run_started_at,
            run_t0=run_t0,
        )
        _write_timing(outdir, timing_records, run_started_at, run_t0, completed=True)
        return

    if args.vcf:
        vcf = args.vcf.resolve()
        logging.info(f"跳过预处理，直接使用给定 VCF: {vcf}")
    elif args.skip_analysis and (outdir / "patient.vcf.gz").exists():
        # --skip-analysis means resume the downstream stages from this task's
        # prepared VCF; do not unexpectedly scan the default FASTQ directory.
        vcf = (outdir / "patient.vcf.gz").resolve()
        logging.info("跳过预处理，复用任务目录中的 VCF: %s", vcf)
    else:
        vcf = timed_stage(
            "preprocess_fastq_to_vcf",
            lambda: run_preprocess(args.fastq_dir.resolve(), args.ref.resolve(), outdir, args.threads),
            outdir=outdir,
            records=timing_records,
            run_started_at=run_started_at,
            run_t0=run_t0,
        )

    if not args.skip_analysis:
        if (outdir / "partial_evidence.json").exists() or (outdir / "input_metadata.json").exists():
            raise RuntimeError("输出目录已有任务；请指定新的 --outdir，避免覆盖或混用样本结果")
        logging.info("====== 输入校验与 VCF 整理 ======")
        timed_stage(
            "input_vcf_normalization",
            lambda: conda_run(
                ENV_ANALYSIS,
                ["python", str(ROOT / "input_vcf.py"), "--vcf", str(vcf), "--outdir", str(outdir)],
                threads=args.threads,
            ),
            outdir=outdir,
            records=timing_records,
            run_started_at=run_started_at,
            run_t0=run_t0,
        )
        vcf = outdir / "patient.vcf.gz"
    else:
        prepared = outdir / "patient.vcf.gz"
        if not prepared.exists():
            raise FileNotFoundError("复用分析需要该任务目录中的 patient.vcf.gz")
        vcf = prepared

    if args.skip_analysis:
        partial_evidence = outdir / "partial_evidence.json"
        if not partial_evidence.exists():
            raise FileNotFoundError(partial_evidence)
        logging.info("跳过步骤 2，复用 %s", partial_evidence)
    else:
        partial_evidence = timed_stage(
            "population_analysis",
            lambda: run_analysis(vcf, outdir, args.threads, args.skip_cv),
            outdir=outdir,
            records=timing_records,
            run_started_at=run_started_at,
            run_t0=run_t0,
        )

    gnn_decision = None
    if not args.skip_gnn:
        gnn_decision = timed_stage(
            "gnn_decision",
            lambda: run_gnn(vcf, outdir, args.threads),
            outdir=outdir,
            records=timing_records,
            run_started_at=run_started_at,
            run_t0=run_t0,
        )

    timed_stage(
        "evidence_pack",
        lambda: aggregate_evidence_pack(partial_evidence, gnn_decision, outdir, results_dir=outdir),
        outdir=outdir,
        records=timing_records,
        run_started_at=run_started_at,
        run_t0=run_t0,
    )
    _write_timing(outdir, timing_records, run_started_at, run_t0, completed=True)


if __name__ == "__main__":
    main()
