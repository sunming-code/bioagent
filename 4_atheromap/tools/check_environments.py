#!/usr/bin/env python3
"""Check installed environments and exercise dependencies on synthetic data only."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("all", "scdrs", "gsmap", "r"), default="all")
    parser.add_argument("--smoke", action="store_true", help="Also run small numerical tests and Python/R H5AD exchange")
    parser.add_argument("--with-r", action="store_true", help="Include Python/R exchange when checking scdrs alone")
    args = parser.parse_args()
    groups = ("r", "scdrs", "gsmap") if args.group == "all" else (args.group,)
    with tempfile.TemporaryDirectory(prefix="atheromap_env_check_") as tmp:
        env = os.environ.copy()
        original_config = Path(env.get("ATHEROMAP_PATHS_FILE", ROOT / "config/paths.local.env")).expanduser().resolve()
        if "ATHEROMAP_PATHS_FILE" not in env and not original_config.is_file():
            original_config = ROOT / "config/paths.example.env"
        temporary_config = Path(tmp) / "check.env"
        temporary_config.write_text(
            f"source {shlex.quote(str(original_config))}\n"
            f"export ATHEROMAP_SCDRS_WORK_DIR={shlex.quote(str(Path(tmp) / 'scdrs'))}\n"
            f"export ATHEROMAP_GSMAP_WORK_DIR={shlex.quote(str(Path(tmp) / 'gsmap'))}\n"
        )
        env["ATHEROMAP_PATHS_FILE"] = str(temporary_config)
        env["ATHEROMAP_SMOKE_WORKSPACE"] = tmp
        for group in groups:
            print(f"\nChecking {group}", flush=True)
            launcher = ["bash", str(ROOT / "tools/run_in_env.sh"), group]
            if group == "r":
                cmd = ["Rscript", "--vanilla", str(ROOT / "tools/smoke_r.R")]
            else:
                subprocess.run(launcher + ["python", "-m", "pip", "check"], check=True, env=env)
                cmd = ["python", str(ROOT / "tools/smoke_python.py"), group]
                if args.smoke:
                    cmd.append("--smoke")
                    if group == "scdrs" and (args.group == "all" or args.with_r):
                        cmd.append("--with-r")
            subprocess.run(launcher + cmd, check=True, env=env)
    print("\nAll requested environment checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
