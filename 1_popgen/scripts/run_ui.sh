#!/usr/bin/env bash
# 启动 VCF 上传、分析任务和结果看板；单进程顺序运行分析。
# 本机: http://127.0.0.1:8008
# 局域网其它电脑: http://<这台服务器IP>:8008
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
cd "$ROOT"
PYTHON="$(python3 -c 'from runtime import environment_prefix; print(environment_prefix("popgen_gnn") / "bin/python")')"
export LD_LIBRARY_PATH="$(dirname "$(dirname "$PYTHON")")/lib:${LD_LIBRARY_PATH:-}"
exec "$PYTHON" -m uvicorn ui.app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8008}" --workers 1 --app-dir "$ROOT"
