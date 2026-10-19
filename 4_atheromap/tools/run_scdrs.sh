#!/usr/bin/env bash
set -euo pipefail
MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(cd -- "$MODULE_DIR/.." && pwd)"
exec bash "$MODULE_DIR/tools/run_in_env.sh" scdrs python "$PROJECT_DIR/run_atheromap_scdrs.py" "$@"
