#!/usr/bin/env bash
# Install isolated CPU environments without modifying the shared base environment.
set -euo pipefail
POPGEN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POPGEN_ENV_ROOT="${POPGEN_ENV_ROOT:-$POPGEN_ROOT/.runtime/envs}"
mkdir -p "$POPGEN_ROOT/.runtime/bin" "$POPGEN_ENV_ROOT"
MAMBA="$POPGEN_ROOT/.runtime/bin/micromamba"
if [[ ! -x "$MAMBA" ]]; then
    ARCHIVE="$(mktemp)"
    curl --fail --location https://micro.mamba.pm/api/micromamba/linux-64/latest -o "$ARCHIVE"
    tar -xjf "$ARCHIVE" -C "$POPGEN_ROOT/.runtime" bin/micromamba
    rm "$ARCHIVE"
fi
export MAMBA_ROOT_PREFIX="$POPGEN_ROOT/.runtime/mamba"
for NAME in popgen popgen_analysis popgen_gnn; do
    case "$NAME" in
        popgen)
            SPEC="$POPGEN_ROOT/envs/preprocess.yml"
            ;;
        popgen_analysis|popgen_gnn)
            SPEC="$POPGEN_ROOT/envs/$NAME.explicit.txt"
            if [[ ! -f "$SPEC" ]]; then
                SPEC="$POPGEN_ROOT/envs/${NAME/popgen_/}.yml"
            fi
            ;;
        *)
            echo "Unknown environment: $NAME" >&2
            exit 1
            ;;
    esac
    if [[ -x "$POPGEN_ENV_ROOT/$NAME/bin/python" ]]; then
        "$MAMBA" install -y -p "$POPGEN_ENV_ROOT/$NAME" -f "$SPEC"
    else
        "$MAMBA" create -y -p "$POPGEN_ENV_ROOT/$NAME" -f "$SPEC"
    fi
done
# Some bioconda bcftools builds retain the GSL 2.6 SONAME while the solver
# selects the ABI-compatible GSL 2.7 package.  Keep the isolated environment
# self-contained so bcftools can start without relying on a host installation.
if [[ ! -e "$POPGEN_ENV_ROOT/popgen/lib/libgsl.so.25" \
      && -e "$POPGEN_ENV_ROOT/popgen/lib/libgsl.so.27.0.0" ]]; then
    ln -s libgsl.so.27.0.0 "$POPGEN_ENV_ROOT/popgen/lib/libgsl.so.25"
fi
"$POPGEN_ENV_ROOT/popgen_gnn/bin/python" -m pip install 'torch==2.1.0+cpu' --index-url https://download.pytorch.org/whl/cpu
"$POPGEN_ENV_ROOT/popgen_gnn/bin/python" -m pip install 'torch-geometric==2.4.0'
export POPGEN_PREFIX="$POPGEN_ENV_ROOT/popgen"
export POPGEN_ANALYSIS_PREFIX="$POPGEN_ENV_ROOT/popgen_analysis"
export POPGEN_GNN_PREFIX="$POPGEN_ENV_ROOT/popgen_gnn"
"$POPGEN_ENV_ROOT/popgen_gnn/bin/python" "$POPGEN_ROOT/scripts/check_runtime.py" --software-only
echo "Prepare reference data, then run: $POPGEN_ENV_ROOT/popgen_gnn/bin/python $POPGEN_ROOT/scripts/check_runtime.py"
