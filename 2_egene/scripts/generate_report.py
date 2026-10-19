#!/usr/bin/env python3
"""Generate the final e-Gene report from a completed disease manifest."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from egene.reporting import main

if __name__ == "__main__":
    raise SystemExit(main())
