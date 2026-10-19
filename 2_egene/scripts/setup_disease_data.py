#!/usr/bin/env python3
"""Download pinned public disease associations, ontology and gene nomenclature."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from egene.disease_db import setup_main

if __name__ == "__main__":
    raise SystemExit(setup_main())
