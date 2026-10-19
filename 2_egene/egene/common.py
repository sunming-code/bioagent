"""Shared local file and executable helpers; no shared environment mutations."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
GRCH38_LENGTHS = dict(zip(
    [f"chr{i}" for i in range(1, 23)] + ["chrX", "chrY", "chrM"],
    [248956422, 242193529, 198295559, 190214555, 181538259, 170805979,
     159345973, 145138636, 138394717, 133797422, 135086622, 133275309,
     114364328, 107043718, 101991189, 90338345, 83257441, 80373285,
     58617616, 64444167, 46709983, 50818468, 156040895, 57227415, 16569],
))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checksum(path: Path, algorithm: str = "sha256") -> str:
    result = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def canonical_contig(name: str) -> str:
    name = name.removeprefix("chr")
    if name in {"MT", "M"}:
        return "chrM"
    return "chr" + name


def find_bcftools(explicit: str | Path | None = None) -> Path:
    candidates = [explicit, os.environ.get("EGENE_BCFTOOLS"), shutil.which("bcftools")]
    config = ROOT / "config/input.runtime.json"
    if config.is_file():
        candidates.append(json.loads(config.read_text()).get("bcftools"))
    for prefix in (ROOT.parent / "1_popgen/.runtime/envs/popgen_analysis",
                   Path.home() / "project/popgen_analysis",
                   Path.home() / ".conda/envs/popgen_analysis"):
        candidates.append(prefix / "bin/bcftools")
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate).resolve()
        # An explicit override must never silently fall back to another executable.
        if candidate and candidate in (explicit, os.environ.get("EGENE_BCFTOOLS")):
            raise ValueError(f"bcftools 不可执行: {candidate}")
    raise ValueError("找不到 bcftools；请用 --bcftools 指定其绝对路径")
