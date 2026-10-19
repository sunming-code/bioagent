#!/usr/bin/env bash
set -euo pipefail
EGENE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$EGENE_ROOT/.runtime/venv/bin/python" "$EGENE_ROOT/scripts/annotate_variants.py" "$@"
