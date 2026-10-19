#!/usr/bin/env bash
set -euo pipefail
GDGPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$GDGPT_ROOT"
export OPENBLAS_NUM_THREADS="${GDGPT_BLAS_THREADS:-4}"
export OMP_NUM_THREADS="${GDGPT_BLAS_THREADS:-4}"
export HF_HUB_OFFLINE="${GDGPT_HF_OFFLINE:-1}"
exec "$GDGPT_ROOT/.venv/bin/python" "$GDGPT_ROOT/scripts/local_runtime.py" "$@"
