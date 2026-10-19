#!/usr/bin/env python3
"""Check installation readiness; this does not evaluate clinical performance."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-hashes", action="store_true", help="Read all installed database files and check SHA-256")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT / "config/dependencies.lock.json").read_text())
    checks, missing = [], []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(passed), "detail": detail})
        if not passed:
            missing.append(name)

    checkout = ROOT / "vendor/InterVar"
    actual = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True)
    clean = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True)
    record("intervar_commit", actual.returncode == clean.returncode == 0 and actual.stdout.strip() == lock["intervar"]["commit"] and not clean.stdout.strip(), actual.stdout.strip())
    python = ROOT / ".runtime/venv/bin/python"
    if python.is_file():
        version = subprocess.run([str(python), str(checkout / "Intervar.py"), "--version"], capture_output=True, text=True)
        record("intervar_runtime", version.returncode == 0 and "2.2.2" in version.stdout, version.stdout.splitlines()[0] if version.stdout else version.stderr[:200])
    else:
        record("intervar_runtime", False, str(python))
    perl = shutil.which("perl")
    record("perl", bool(perl), perl or "not found")
    annovar = ROOT / "vendor/annovar"
    software_path = ROOT / "data/software_manifest.json"
    software = json.loads(software_path.read_text()) if software_path.exists() else {}
    for name in ("table_annovar.pl", "convert2annovar.pl", "annotate_variation.pl", "coding_change.pl", "retrieve_seq_from_fasta.pl"):
        path = annovar / name
        passed = path.is_file() and path.stat().st_size > 100
        detail = str(path)
        if passed and perl:
            syntax = subprocess.run([perl, "-c", str(path)], cwd=annovar, capture_output=True, text=True)
            passed = syntax.returncode == 0
            detail = syntax.stderr.strip()[:400]
        expected_hash = software.get("annovar_scripts", {}).get(name, {}).get("sha256")
        if passed:
            passed = bool(expected_hash) and digest(path) == expected_hash
            if not passed:
                detail = "Missing software manifest or modified ANNOVAR script"
        record("annovar/" + name, passed, detail)
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / "config/intervar.hg38.ini")
    record("hg38_config", config.get("InterVar", "buildver", fallback=None) == "hg38", str(ROOT / "config/intervar.hg38.ini"))
    aux = ["PVS1.LOF.genes.hg38", "PM1_domains_with_benigns.hg38", "knownGeneCanonical.txt.hg38", "PP2.genes.hg38", "BP1.genes.hg38", "PS1.AA.change.patho.hg38", "PS4.variants.hg38", "BS2_hom_het.hg38", "ext.variants.hg38", "mim_recessive.txt", "mim_domin.txt", "mim_adultonset.txt", "mim_pheno.txt", "mim_orpha.txt", "orpha.txt.utf8"]
    for name in aux:
        path = checkout / "intervardb" / name
        record("intervardb/" + name, path.is_file() and path.stat().st_size > 0, str(path))
    manifest_path = ROOT / "data/dependency_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}
    for spec in lock["downloads"]:
        saved = manifest["files"].get(spec["name"], {})
        by_name = {Path(item["path"]).name: item for item in saved.get("outputs", [])}
        for filename in spec["outputs"]:
            expected = by_name.get(filename)
            path = ROOT / "data" / spec.get("target", "humandb") / filename
            passed = bool(expected) and path.is_file() and path.stat().st_size == expected["bytes"]
            if passed and args.verify_hashes:
                passed = digest(path) == expected["sha256"]
            record("database/" + filename, passed, str(path))
    # Load the actual hg38 auxiliary datasets using the installed InterVar code.
    if config.has_section("InterVar") and not any(x.startswith("intervardb/") or x == "database/mim2gene.txt" for x in missing):
        spec = importlib.util.spec_from_file_location("installed_intervar", checkout / "Intervar.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.paras = dict(config["InterVar"])
        for key in ("lof_genes", "pm1_domain", "knowngenecanonical", "pp2_genes", "bp1_genes", "ps1_aa", "ps4_snps", "bs2_snps", "exclude_snps"):
            module.paras[key] += ".hg38"
        try:
            module.read_datasets()
            counts = {"lof_genes": len(module.lof_genes_dict), "mim2gene": len(module.mim2gene_dict), "canonical_transcripts": len(module.knownGeneCanonical_dict)}
            record("intervar_auxiliary_load", all(counts.values()), json.dumps(counts))
        except (Exception, SystemExit) as error:
            record("intervar_auxiliary_load", False, str(error))
    report = {"status": "ready" if not missing else "incomplete", "assembly": "GRCh38", "missing": missing, "checks": checks}
    path = ROOT / ".runtime/dependency_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not args.quiet:
        print(f"Dependency status: {report['status']} ({len(checks) - len(missing)}/{len(checks)} checks passed)")
    for name in missing:
        print("MISSING " + name, file=sys.stderr)
    if not args.quiet:
        print("Details: " + str(path))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
