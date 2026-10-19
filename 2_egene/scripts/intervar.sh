#!/usr/bin/env bash
set -euo pipefail
EGENE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EGENE_PYTHON="$EGENE_ROOT/.runtime/venv/bin/python"
for argument in "$@"; do
    case "$argument" in
        -h|--help|--version)
            exec "$EGENE_PYTHON" "$EGENE_ROOT/vendor/InterVar/Intervar.py" "$argument" ;;
        -b*|--buildver*|-c*|--config*|-t*|--database_intervar*|-d*|--database_locat*|--table_annovar*|--convert2annovar*|--annotate_variation*)
            echo "This launcher uses the locked hg38 configuration; build/config/database overrides are disabled." >&2
            exit 2 ;;
    esac
done
"$EGENE_PYTHON" "$EGENE_ROOT/scripts/check_dependencies.py" --quiet
exec "$EGENE_PYTHON" "$EGENE_ROOT/vendor/InterVar/Intervar.py" \
    --config "$EGENE_ROOT/config/intervar.hg38.ini" "$@"
