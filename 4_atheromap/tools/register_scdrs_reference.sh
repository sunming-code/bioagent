#!/usr/bin/env bash
set -euo pipefail
MODULE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(cd -- "$MODULE_DIR/.." && pwd)"
cd -- "$PROJECT_DIR"
exec bash "$MODULE_DIR/tools/run_in_env.sh" scdrs python -m egene_pipeline.atheromap_reference "$@"
