#!/usr/bin/env bash
set -euo pipefail
EGENE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$EGENE_ROOT/.runtime/logs"
exec 9>"$EGENE_ROOT/.runtime/database_download.lock"
if ! flock -n 9; then
    echo "Another database installer is already running." >&2
    exit 2
fi
EGENE_RESULT=1
for EGENE_ATTEMPT in 1 2 3; do
    if "$EGENE_ROOT/.runtime/venv/bin/python" -u "$EGENE_ROOT/scripts/setup_dependencies.py" --workers 4; then
        EGENE_RESULT=0
        break
    else
        EGENE_RESULT=$?
    fi
    # Missing an authorized main program cannot be repaired by retrying data.
    if [[ "$EGENE_RESULT" -eq 2 ]]; then
        break
    fi
    if [[ "$EGENE_ATTEMPT" -lt 3 ]]; then
        sleep 5
    fi
done
printf '%s\n' "$EGENE_RESULT" > "$EGENE_ROOT/.runtime/database_download.exitcode"
exit "$EGENE_RESULT"
