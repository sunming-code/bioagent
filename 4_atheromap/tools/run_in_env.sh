#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${ATHEROMAP_PATHS_FILE:-$MODULE_DIR/config/paths.local.env}"
if [[ ! -f "$CONFIG_FILE" && -z "${ATHEROMAP_PATHS_FILE:-}" ]]; then
    CONFIG_FILE="$MODULE_DIR/config/paths.example.env"
fi
source "$CONFIG_FILE"

if [[ $# -lt 2 ]]; then
    echo "Usage: bash tools/run_in_env.sh {scdrs|gsmap|r} <command> [args...]" >&2
    exit 2
fi
case "$1" in
    scdrs|gsmap|r) ENV_PREFIX="$ATHEROMAP_ENV_ROOT/atheromap_$1" ;;
    *) echo "Unknown environment: $1" >&2; exit 2 ;;
esac
shift

if [[ ! -d "$ENV_PREFIX/conda-meta" ]]; then
    echo "Environment missing: $ENV_PREFIX. Run bash tools/setup_environments.sh first." >&2
    exit 1
fi
export MPLBACKEND="${MPLBACKEND:-Agg}"
export PYTHONNOUSERSITE=1
export PYTHONUNBUFFERED=1
export OPENBLAS_NUM_THREADS="${ATHEROMAP_NUM_THREADS:-4}"
export OMP_NUM_THREADS="${ATHEROMAP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${ATHEROMAP_NUM_THREADS:-4}"
export NUMBA_NUM_THREADS="${ATHEROMAP_NUM_THREADS:-4}"
# Activate before exec so command flags (for example gsmap's --n) cannot
# be interpreted as options belonging to `conda run`.
CONDA_BASE="$(conda info --base)"
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$ENV_PREFIX"
exec "$@"
