#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_ROOT="${ATHEROMAP_ENV_ROOT:-$HOME/.conda/envs}"
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$HOME/.cache/atheromap/conda-pkgs}"
export CONDA_CHANNEL_PRIORITY=strict
export PYTHONNOUSERSITE=1
command -v conda >/dev/null || { echo "conda is required" >&2; exit 1; }

SELECTED="${1:-all}"
case "$SELECTED" in
    all) GROUPS_TO_INSTALL=(scdrs gsmap r) ;;
    scdrs|gsmap|r) GROUPS_TO_INSTALL=("$SELECTED") ;;
    *) echo "Usage: bash tools/setup_environments.sh [all|scdrs|gsmap|r]" >&2; exit 2 ;;
esac

for group in "${GROUPS_TO_INSTALL[@]}"; do
    prefix="$ENV_ROOT/atheromap_$group"
    if [[ -e "$prefix" ]]; then
        echo "Refusing to overwrite existing environment: $prefix" >&2
        echo "Select an unused ATHEROMAP_ENV_ROOT to build fresh environments." >&2
        exit 1
    fi
    conda_lock="$MODULE_DIR/environments/locks/$group.conda-linux-64.txt"
    if [[ -f "$conda_lock" && "$(uname -sm)" == "Linux x86_64" ]]; then
        conda create --yes --prefix "$prefix" --file "$conda_lock"
    elif [[ "$group" == r ]]; then
        conda env create --prefix "$prefix" --file "$MODULE_DIR/environments/r.yml"
    else
        conda env create --prefix "$prefix" --file "$MODULE_DIR/environments/python.yml"
    fi
    if [[ "$group" != r ]]; then
        conda env config vars set --prefix "$prefix" PYTHONNOUSERSITE=1 MPLBACKEND=Agg
        if [[ "$group" == gsmap ]]; then
            conda run --no-capture-output --prefix "$prefix" python -m pip install \
                --index-url https://download.pytorch.org/whl/cpu 'torch==2.2.2+cpu'
        fi
        pip_requirements="$MODULE_DIR/environments/locks/$group.pip.txt"
        [[ -f "$pip_requirements" ]] || pip_requirements="$MODULE_DIR/environments/$group.txt"
        conda run --no-capture-output --prefix "$prefix" python -m pip install \
            --requirement "$pip_requirements"
        conda run --no-capture-output --prefix "$prefix" python -m pip check
    fi
done

echo "Installed environments in $ENV_ROOT"
echo "Verify: python $MODULE_DIR/tools/check_environments.py"
