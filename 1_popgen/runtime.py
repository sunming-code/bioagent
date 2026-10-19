"""Resolve isolated tool environments without relying on an activated shell."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def environment_prefix(name: str) -> Path:
    override = os.environ.get(f"{name.upper()}_PREFIX")
    candidates = ([Path(override)] if override else []) + [
        ROOT / ".runtime" / "envs" / name,
        Path.home() / "project" / name,
        Path.home() / ".conda" / "envs" / name,
    ]
    registry = Path.home() / ".conda" / "environments.txt"
    if registry.exists():
        candidates += [Path(p) for p in registry.read_text().splitlines() if Path(p).name == name]
    for prefix in candidates:
        if (prefix / "bin" / "python").is_file():
            return prefix.resolve()
    raise RuntimeError(f"缺少环境 {name}；请运行 bash scripts/setup_runtime.sh")


def command_env(name: str, threads: int = 8) -> dict[str, str]:
    prefix = environment_prefix(name)
    env = dict(os.environ)
    env["PATH"] = str(prefix / "bin") + os.pathsep + env.get("PATH", "")
    env["CONDA_PREFIX"] = str(prefix)
    env["LD_LIBRARY_PATH"] = str(prefix / "lib") + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    if (prefix / "bin" / "java").is_file():
        env["JAVA_HOME"] = str(prefix)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = str(threads)
    env["POPGEN_THREADS"] = str(threads)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_in_environment(name: str, args: list[str], *, cwd: Path | None = None, threads: int = 8):
    executable = environment_prefix(name) / "bin" / args[0]
    return subprocess.run([str(executable), *map(str, args[1:])], cwd=cwd,
                          env=command_env(name, threads), check=True)
