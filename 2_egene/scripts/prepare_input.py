#!/usr/bin/env python3
"""CLI for step 2: PopGen delivery to normalized VCF and ANNOVAR input."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from egene.ingest import main
except ModuleNotFoundError as error:
    raise SystemExit(f"缺少输入适配依赖 {error.name}；请运行 python scripts/setup_input_runtime.py") from error

if __name__ == "__main__":
    raise SystemExit(main())
