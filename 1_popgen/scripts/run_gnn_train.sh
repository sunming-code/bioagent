#!/usr/bin/env bash
# 步骤 3：在 popgen_gnn 里训练 GAT 并评测 PCA / ADMIXTURE baseline
# 用法: bash scripts/run_gnn_train.sh [--n-snps 25000 ...]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_local_env.sh"
export PATH="$POPGEN_GNN_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$POPGEN_GNN_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$ROOT/.runtime/conda-pkgs}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
mkdir -p "$ROOT/results/gnn"
exec "$POPGEN_GNN_PREFIX/bin/python" "$ROOT/steps/03_gnn/train.py" \
  --panel "$ROOT/data/reference/panel_1000g/ref_1000g_pruned" \
  --labels "${POPGEN_SAMPLES_INFO:-$ROOT/data/1000GP/samples.info}" \
  --out "$ROOT/steps/03_gnn/model.pt" \
  --results-dir "$ROOT/results/gnn" \
  "$@"
