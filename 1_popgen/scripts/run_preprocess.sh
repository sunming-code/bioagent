#!/usr/bin/env bash
# 步骤 1：用 HG002 外显子真实 FASTQ 跑 FASTQ→VCF
# 环境：popgen；日志：results/preprocess.log
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_local_env.sh"
export PATH="$POPGEN_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$POPGEN_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
FASTQ_DIR="${FASTQ_DIR:-$ROOT/data/fastq}"
REF="${REF:-$ROOT/data/reference/GRCh38.fa}"
OUTDIR="${OUTDIR:-$ROOT/results}"
mkdir -p "$OUTDIR" "$ROOT/work"

cd "$ROOT/steps/01_preprocess"
exec "$POPGEN_PREFIX/bin/nextflow" run main.nf \
  --fastq_dir "$FASTQ_DIR" \
  --ref "$REF" \
  --outdir "$OUTDIR" \
  -resume
