#!/usr/bin/env python3
"""Install the isolated step-2 Python dependencies and configure bcftools."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from egene.common import find_bcftools, now, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bcftools", help="Explicit bcftools executable")
    args = parser.parse_args()
    python = ROOT / ".runtime/venv/bin/python"
    if not python.is_file():
        raise SystemExit("请先完成第一步 scripts/setup_dependencies.py")
    subprocess.run([str(python), "-m", "ensurepip"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "envs/input.requirements.txt")], check=True)
    bcftools = find_bcftools(args.bcftools)
    version = subprocess.check_output([str(bcftools), "--version"], text=True).splitlines()[0]
    write_json(ROOT / "config/input.runtime.json", {
        "python": str(python), "bcftools": str(bcftools), "bcftools_version": version,
        "reference": str(ROOT / "data/reference/GRCh38.fa"), "configured_at": now(),
    })
    versions = subprocess.check_output([
        str(python), "-c",
        "import importlib.metadata,json; print(json.dumps({d.metadata['Name']: d.version for d in importlib.metadata.distributions() if d.metadata['Name'] not in ('pip','setuptools')}))",
    ], text=True)
    write_json(ROOT / "envs/input.runtime.lock.json", {
        "stage": "prepare_input", "python": subprocess.check_output([str(python), "-V"], text=True).strip(),
        "packages": json.loads(versions), "bcftools_version": version,
        "requirements": "envs/input.requirements.txt",
    })
    print(f"输入适配环境已就绪: {version}")


if __name__ == "__main__":
    main()
