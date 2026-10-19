#!/usr/bin/env python3
"""Connect completed InterVar results to disease associations and HPO profiles."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from egene.disease import main
except ModuleNotFoundError as error:
    raise SystemExit(f"缺少依赖 {error.name}；请运行 python scripts/setup_input_runtime.py") from error

if __name__ == "__main__":
    raise SystemExit(main())
