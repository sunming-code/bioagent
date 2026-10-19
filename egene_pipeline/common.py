"""Shared, standard-library-only helpers for isolated pipeline processes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_spec(path, base=None):
    path = Path(path)
    return {"path": str(path.relative_to(base) if base else path.resolve()),
            "bytes": path.stat().st_size, "sha256": digest(path)}


def local_file(base, relative):
    path = (Path(base) / relative).resolve(strict=True)
    if not path.is_relative_to(Path(base).resolve()) or not path.is_file():
        raise ValueError(f"交付文件必须位于交付目录内: {relative}")
    return path


def verify_files(base, files):
    if not isinstance(files, dict) or not files:
        raise ValueError("清单没有文件校验记录")
    result = {}
    for name, spec in files.items():
        path = local_file(base, spec["path"])
        if path.stat().st_size != spec["bytes"] or digest(path) != spec["sha256"]:
            raise ValueError(f"文件完整性校验失败: {name}")
        result[name] = path
    return result


def verify_manifest(path, stage):
    path = Path(path).resolve(strict=True)
    manifest = read_json(path)
    if (manifest.get("schema_version") != "1.0" or manifest.get("status") != "complete"
            or manifest.get("stage") != stage or manifest.get("assembly") != "GRCh38"
            or not manifest.get("sample_id")):
        raise ValueError(f"清单版本、参考版本、样本或完成状态不兼容: {path}")
    status = read_json(path.parent / "status.json")
    if status.get("stage") != stage or status.get("status") != "complete":
        raise ValueError(f"步骤没有完成状态: {path}")
    files = verify_files(path.parent, manifest["files"])
    return manifest, files


def validate_contract(value, name):
    import jsonschema
    schema = read_json(ROOT / "contracts" / name)
    jsonschema.Draft7Validator(schema).validate(value)


def run_command(argv, cwd, log_path, *, timeout=None, env=None):
    """A failed/timed-out command never leaves its process group running."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(x) for x in argv], cwd=cwd, stdout=log,
                                   stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    if code:
        raise RuntimeError(f"步骤退出码 {code}，详情见 {log_path}")


def files_in(directory, exclude=()):
    directory = Path(directory)
    return {str(p.relative_to(directory)): file_spec(p, directory)
            for p in sorted(directory.rglob("*")) if p.is_file() and p.name not in exclude}
