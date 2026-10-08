#!/usr/bin/env bash
# 步骤 3：在 popgen_gnn 里训练 GAT 并评测 PCA / ADMIXTURE baseline
# 用法: bash scripts/run_gnn_train.sh [--n-snps 25000 ...]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CONDA_PKGS_DIRS=/home/wangy/miniconda3/pkgs
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
mkdir -p "$ROOT/results/gnn"
conda run --no-capture-output -n popgen_gnn python "$ROOT/steps/03_gnn/train.py" \
  --panel "$ROOT/data/reference/panel_1000g/ref_1000g_pruned" \
  --labels /data/public/1000GP/samples.info \
  --out "$ROOT/steps/03_gnn/model.pt" \
  --results-dir "$ROOT/results/gnn" \
  "$@"
