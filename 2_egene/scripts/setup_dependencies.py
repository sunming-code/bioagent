#!/usr/bin/env python3
"""Install the pinned InterVar runtime and public hg38 annotation dependencies."""
from __future__ import annotations

import argparse
import concurrent.futures
import configparser
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config/dependencies.lock.json"
MANIFEST = ROOT / "data/dependency_manifest.json"
ANNOVAR_SCRIPTS = (
    "table_annovar.pl", "convert2annovar.pl", "annotate_variation.pl",
    "coding_change.pl", "retrieve_seq_from_fasta.pl",
)


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def install_intervar(lock: dict) -> None:
    destination = ROOT / "vendor/InterVar"
    if not destination.exists():
        subprocess.run(["git", "clone", lock["intervar"]["repository"], str(destination)], check=True)
        subprocess.run(["git", "-C", str(destination), "checkout", "--detach", lock["intervar"]["commit"]], check=True)
    revision = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if revision != lock["intervar"]["commit"]:
        raise RuntimeError("InterVar checkout differs from the locked commit; refusing to replace it")
    changes = subprocess.check_output(["git", "-C", str(destination), "status", "--porcelain", "--untracked-files=no"], text=True)
    if changes.strip():
        raise RuntimeError("Tracked InterVar source files have local changes")
    prefix = ROOT / ".runtime/venv"
    if not (prefix / "bin/python").exists():
        venv.EnvBuilder(with_pip=False).create(prefix)
    result = subprocess.run([str(prefix / "bin/python"), str(destination / "Intervar.py"), "--version"], check=True, capture_output=True, text=True)
    print(result.stdout.splitlines()[0], flush=True)


def import_annovar(directory: Path | None, archive: Path | None) -> None:
    destination = ROOT / "vendor/annovar"
    if directory:
        source = directory.expanduser().resolve(strict=True)
        if not all((source / name).is_file() for name in ANNOVAR_SCRIPTS):
            raise ValueError("ANNOVAR directory is missing required Perl scripts")
        if destination.exists() or destination.is_symlink():
            if destination.resolve() != source:
                raise ValueError("vendor/annovar already exists with a different source")
        else:
            destination.symlink_to(source, target_is_directory=True)
    if archive:
        if destination.exists() or destination.is_symlink():
            raise ValueError("vendor/annovar already exists; will not overwrite it")
        source = archive.expanduser().resolve(strict=True)
        staging = ROOT / ".runtime/annovar_import"
        if staging.exists():
            raise ValueError("Previous .runtime/annovar_import exists; inspect it before retrying")
        staging.mkdir()
        with tarfile.open(source, "r:*") as bundle:
            for member in bundle.getmembers():
                target = (staging / member.name).resolve()
                if not target.is_relative_to(staging.resolve()) or not (member.isfile() or member.isdir()):
                    raise ValueError("ANNOVAR archive contains unsafe paths or links")
            bundle.extractall(staging, filter="data")
        candidates = [p.parent for p in staging.rglob("table_annovar.pl")]
        if len(candidates) != 1 or not all((candidates[0] / n).is_file() for n in ANNOVAR_SCRIPTS):
            raise ValueError("Archive does not contain one complete ANNOVAR installation")
        shutil.move(str(candidates[0]), destination)
        if staging.exists():
            shutil.rmtree(staging)
        write_json(ROOT / ".runtime/annovar_archive.json", {"archive": source.name, "sha256": sha256(source), "imported_at": now()})


def write_config(lock: dict) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ROOT / "vendor/InterVar/config.ini")
    source = ROOT / "vendor/InterVar/intervardb"
    parser["InterVar"].update({
        "buildver": "hg38", "inputfile": str(ROOT / ".runtime/input_not_configured.avinput"),
        "inputfile_type": "AVinput", "outfile": str(ROOT / ".runtime/intervar_output"),
        "database_intervar": str(source), "mim2gene": str(ROOT / "data/omim/mim2gene.txt"),
        "evidence_file": "None",
        # Match the default in the pinned Python source instead of upstream's example 0.01.
        "disorder_cutoff": "0.005",
    })
    for key, value in list(parser["InterVar"].items()):
        parser["InterVar"][key] = value.replace("%(database_intervar)s", str(source))
    annovar = ROOT / "vendor/annovar"
    parser["Annovar"].update({
        "convert2annovar": str(annovar / "convert2annovar.pl"),
        "table_annovar": str(annovar / "table_annovar.pl"),
        "annotate_variation": str(annovar / "annotate_variation.pl"),
        "database_locat": str(ROOT / "data/humandb"),
        # InterVar checks the bundle keyword against ALL.sites.2015_08.txt.
        # ANNOVAR maps its 1000g2015aug_all annotation protocol to that same file.
        "database_names": "refGene esp6500siv2_all 1000g2015aug avsnp147 dbnsfp42a clinvar_20210501 gnomad_genome dbscsnv11 rmsk ensGene knownGene",
    })
    path = ROOT / "config/intervar.hg38.ini"
    with path.open("w") as handle:
        parser.write(handle)
    runtime = {"assembly": "GRCh38", "annovar_build": "hg38", "python": str(ROOT / ".runtime/venv/bin/python"),
               "perl": shutil.which("perl"), "intervar_script": str(ROOT / "vendor/InterVar/Intervar.py"),
               "intervar_commit": lock["intervar"]["commit"], "config": str(path), "configured_at": now()}
    write_json(ROOT / "config/runtime.json", runtime)


def record_software(lock: dict) -> None:
    path = ROOT / "data/software_manifest.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    scripts = {}
    for name in ANNOVAR_SCRIPTS:
        source = ROOT / "vendor/annovar" / name
        if source.is_file():
            checksum = sha256(source)
            old = previous.get("annovar_scripts", {}).get(name)
            if old and old["sha256"] != checksum:
                raise ValueError(f"ANNOVAR script changed since installation: {name}")
            dates = re.findall(r"\$Date: ([^$]+)\$", source.read_text(errors="replace"))
            scripts[name] = {"sha256": checksum, "source_date": dates[0].strip() if dates else None}
    archive = ROOT / ".runtime/annovar_archive.json"
    write_json(path, {"intervar": lock["intervar"], "python": sys.version.split()[0],
                      "perl": subprocess.check_output(["perl", "-e", 'print "$^V"'], text=True),
                      "annovar_scripts": scripts,
                      "annovar_archive": json.loads(archive.read_text()) if archive.exists() else None,
                      "recorded_at": now()})


def copy_and_hash(source, target: Path) -> dict:
    temporary = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    count = 0
    with temporary.open("wb") as destination:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            destination.write(block)
            digest.update(block)
            count += len(block)
    if count == 0:
        raise ValueError(f"Empty dependency: {target.name}")
    temporary.replace(target)
    return {"path": str(target.relative_to(ROOT)), "bytes": count, "sha256": digest.hexdigest()}


def fetch_one(spec: dict, old: dict | None) -> dict:
    directory = ROOT / "data" / spec.get("target", "humandb")
    directory.mkdir(parents=True, exist_ok=True)
    if old and old.get("source") == spec["url"] and old.get("archive_bytes") == spec.get("compressed_bytes") and all((ROOT / item["path"]).is_file() and (ROOT / item["path"]).stat().st_size == item["bytes"] for item in old.get("outputs", [])) and old.get("outputs"):
        print(f"CACHED {spec['name']}", flush=True)
        return old
    cached = ROOT / ".runtime/downloads" / spec["name"]
    partial = cached.with_name(cached.name + ".part")
    expected = spec.get("compressed_bytes")
    headers = {"User-Agent": "e-Gene dependency setup/1.0", "Accept-Encoding": "identity"}
    last_headers = {}
    aria2_control = partial.with_name(partial.name + ".aria2")
    if not cached.exists() and not aria2_control.exists() and expected and partial.is_file() and partial.stat().st_size == expected:
        partial.replace(cached)
    # Large public archives benefit from ranged, resumable transfers. Keep the
    # official ETag as an HTTP precondition and avoid touching shared software.
    aria2 = shutil.which("aria2c")
    if not cached.exists() and aria2 and expected and expected >= 128 * 1024 * 1024 and "www.openbioinformatics.org/" in spec["url"]:
        command = [aria2, "--continue=true", "--allow-overwrite=true", "--auto-file-renaming=false",
                   "--file-allocation=none", "--max-connection-per-server=8", "--split=8",
                   "--min-split-size=8M", "--max-tries=4", "--retry-wait=3", "--timeout=60",
                   "--connect-timeout=20", "--console-log-level=warn", "--summary-interval=0",
                   "--download-result=hide", "--dir=" + str(partial.parent), "--out=" + partial.name]
        if spec.get("etag"):
            command.append("--header=If-Match: " + spec["etag"])
        command.append(spec["url"])
        print(f"DOWNLOAD_ARIA2 {spec['name']} {expected / 1e9:.3f} GB", flush=True)
        transfer_environment = dict(os.environ)
        # aria2 reads lowercase proxy variables, unlike Python urllib. Honor the
        # same existing network configuration without printing credentials.
        for protocol, proxy in urllib.request.getproxies().items():
            if protocol in ("http", "https"):
                transfer_environment[protocol + "_proxy"] = proxy
        result = subprocess.run(command, capture_output=True, text=True, env=transfer_environment)
        if result.returncode:
            raise RuntimeError("aria2 failed: " + (result.stdout + result.stderr)[-1800:])
        if not partial.exists() or partial.stat().st_size != expected:
            raise ValueError(f"aria2 output size mismatch: {partial}")
        partial.replace(cached)
        last_headers = {"ETag": spec.get("etag"), "Last-Modified": spec.get("last_modified"), "Content-Length": str(expected)}
    if not cached.exists():
        for attempt in range(1, 5):
            offset = partial.stat().st_size if partial.exists() else 0
            request_headers = dict(headers)
            if offset:
                request_headers["Range"] = f"bytes={offset}-"
                if spec.get("etag"):
                    request_headers["If-Range"] = spec["etag"]
            print(f"DOWNLOAD {spec['name']} offset={offset} attempt={attempt}", flush=True)
            try:
                with urllib.request.urlopen(urllib.request.Request(spec["url"], headers=request_headers), timeout=60) as response:
                    last_headers = {k: response.headers.get(k) for k in ("ETag", "Last-Modified", "Content-Length")}
                    if spec.get("etag") and response.headers.get("ETag") != spec["etag"]:
                        raise ValueError("Official file changed since the dependency lock was generated")
                    if offset and response.status == 206:
                        if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                            raise ValueError("Incorrect HTTP Content-Range")
                        mode = "ab"
                    else:
                        offset, mode = 0, "wb"
                    size = expected or (offset + int(response.headers.get("Content-Length", "0"))) or None
                    received = offset
                    report_at = time.monotonic()
                    with partial.open(mode) as handle:
                        for block in iter(lambda: response.read(1024 * 1024), b""):
                            handle.write(block)
                            received += len(block)
                            if time.monotonic() - report_at > 30:
                                print(f"PROGRESS {spec['name']} {received / 1e9:.3f}/{(size or 0) / 1e9:.3f} GB", flush=True)
                                report_at = time.monotonic()
                    if size and received != size:
                        raise ValueError(f"Size mismatch: {received} != {size}")
                partial.replace(cached)
                break
            except Exception as error:
                if attempt == 4:
                    raise RuntimeError(f"{spec['name']}: {error}") from error
                time.sleep(attempt * 2)
    if expected and cached.stat().st_size != expected:
        raise ValueError(f"Cached archive size mismatch: {cached}")
    compressed_sha = sha256(cached)
    print(f"UNPACK {spec['name']}", flush=True)
    outputs = []
    if spec["compression"] == "gzip":
        with gzip.open(cached, "rb") as source:
            outputs.append(copy_and_hash(source, directory / spec["outputs"][0]))
    elif spec["compression"] == "zip":
        with zipfile.ZipFile(cached) as bundle:
            for name in spec["outputs"]:
                matches = [n for n in bundle.namelist() if Path(n).name == name]
                if len(matches) != 1:
                    raise ValueError(f"Expected one archive member for {name}: {matches}")
                with bundle.open(matches[0]) as source:
                    outputs.append(copy_and_hash(source, directory / name))
    else:
        with cached.open("rb") as source:
            outputs.append(copy_and_hash(source, directory / spec["outputs"][0]))
    result = {"source": spec["url"], "catalog_date": spec.get("catalog_date"), "downloaded_at": now(),
              "archive_bytes": cached.stat().st_size, "archive_sha256": compressed_sha, "http": last_headers, "outputs": outputs}
    print(f"READY {spec['name']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annovar-dir", type=Path, help="User-authorized ANNOVAR installation directory")
    parser.add_argument("--annovar-archive", type=Path, help="User-authorized ANNOVAR tar archive")
    parser.add_argument("--skip-download", action="store_true", help="Only configure tools and import ANNOVAR")
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    if args.annovar_dir and args.annovar_archive:
        parser.error("Choose --annovar-dir or --annovar-archive")
    lock = json.loads(LOCK.read_text())
    for name in ("vendor", "data/humandb", "data/omim", ".runtime/downloads", ".runtime/logs"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    install_intervar(lock)
    import_annovar(args.annovar_dir, args.annovar_archive)
    write_config(lock)
    record_software(lock)
    failures = []
    if not args.skip_download:
        manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"schema_version": "1.0", "assembly": "GRCh38", "files": {}}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            # Finish small prerequisites (including OMIM) before starting the
            # largest archives, so installation checks remain informative.
            ordered = sorted(lock["downloads"], key=lambda spec: spec.get("compressed_bytes") or 0)
            futures = {pool.submit(fetch_one, spec, manifest["files"].get(spec["name"])): spec for spec in ordered}
            for future in concurrent.futures.as_completed(futures):
                spec = futures[future]
                try:
                    manifest["files"][spec["name"]] = future.result()
                    manifest.get("failures", {}).pop(spec["name"], None)
                except Exception as error:
                    failures.append(spec["name"])
                    manifest.setdefault("failures", {})[spec["name"]] = str(error)
                    print(f"FAILED {spec['name']}: {error}", file=sys.stderr, flush=True)
                manifest["updated_at"] = now()
                write_json(MANIFEST, manifest)
    result = subprocess.run([str(ROOT / ".runtime/venv/bin/python"), str(ROOT / "scripts/check_dependencies.py")])
    return 1 if failures else result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
