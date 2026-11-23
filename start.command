#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import starlette,uvicorn,jsonschema' 2>/dev/null; then .venv/bin/python -m pip install -r pipeline_ui/requirements.txt; fi
exec .venv/bin/python -m uvicorn pipeline_ui.app:app --host 127.0.0.1 --port "${PORT:-8765}"
