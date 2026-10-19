#!/usr/bin/env bash
# Resolve all PopGen tools from the workspace instead of a named conda env.
# This file is sourced by the shell entry points below.

if [[ -z "${ROOT:-}" ]]; then
  echo "ROOT must be set before sourcing _local_env.sh" >&2
  return 2 2>/dev/null || exit 2
fi

ENV_ROOT="$ROOT/.runtime/envs"
POPGEN_PREFIX="${POPGEN_PREFIX:-$ENV_ROOT/popgen}"
POPGEN_ANALYSIS_PREFIX="${POPGEN_ANALYSIS_PREFIX:-$ENV_ROOT/popgen_analysis}"
POPGEN_GNN_PREFIX="${POPGEN_GNN_PREFIX:-$ENV_ROOT/popgen_gnn}"

for prefix in "$POPGEN_PREFIX" "$POPGEN_ANALYSIS_PREFIX" "$POPGEN_GNN_PREFIX"; do
  if [[ ! -x "$prefix/bin/python" ]]; then
    echo "Missing local PopGen environment: $prefix" >&2
    echo "Run: bash $ROOT/scripts/setup_runtime.sh" >&2
    return 1 2>/dev/null || exit 1
  fi
done

export POPGEN_PREFIX POPGEN_ANALYSIS_PREFIX POPGEN_GNN_PREFIX
