#!/usr/bin/env bash
# 启动已完成任务可视化 UI（不重跑步骤 1/2/3）
# 本机: http://127.0.0.1:8008
# 局域网其它电脑: http://<这台服务器IP>:8008
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
cd "$ROOT"
exec python3 -m uvicorn ui.app:app --host 0.0.0.0 --port "${PORT:-8008}" --app-dir "$ROOT"
