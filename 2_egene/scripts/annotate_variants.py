#!/usr/bin/env python3
"""CLI for locked ANNOVAR annotation and preliminary candidate selection."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from egene.annotation import main
except ModuleNotFoundError as error:
    raise SystemExit(f"缺少依赖 {error.name}；请运行 python scripts/setup_input_runtime.py") from error

if __name__ == "__main__":
    raise SystemExit(main())
