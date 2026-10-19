"""Step 3: locked ANNOVAR annotation, source mapping and preliminary triage."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import jsonschema

from . import __version__
from .common import ROOT, canonical_contig, checksum, now, write_json
from .ingest import read_json, tsv_value
from .triage import prioritize

PROTOCOLS = ["refGene", "esp6500siv2_all", "1000g2015aug_all", "avsnp147", "dbnsfp42a",
             "clinvar_20210501", "gnomad_genome", "dbscsnv11", "rmsk", "ensGene", "knownGene"]
OPERATIONS = ["g", "f", "f", "f", "f", "f", "f", "f", "r", "g", "g"]
REQUIRED_ANNOTATION = [
    "Chr", "Start", "End", "Ref", "Alt", "CLNALLELEID", "CLNDN", "CLNDISDB", "CLNREVSTAT", "CLNSIG",
    "esp6500siv2_all", "1000g2015aug_all", "avsnp147", "gnomAD_genome_ALL",
    "MetaSVM_score", "REVEL_score", "GERP++_RS", "Interpro_domain",
    "dbscSNV_ADA_SCORE", "dbscSNV_RF_SCORE", "rmsk", "Otherinfo1", "Otherinfo2", "Otherinfo3",
] + [field + "." + gene for gene in ("refGene", "ensGene", "knownGene")
     for field in ("Func", "Gene", "GeneDetail", "ExonicFunc", "AAChange")]
TRIAGE_COLUMNS = [
    "triage_route", "triage_kind", "triage_rank", "priority_review", "triage_reasons",
    "screen_frequency_status", "screen_max_AF", "screen_frequency_sources", "frequency_sources_discordant",
    "clinvar_review_stars", "clinvar_labels", "consequence_functions", "consequence_exonic_functions",
    "acmg_classification",
]
SOFTWARE = ["table_annovar.pl", "annotate_variation.pl", "coding_change.pl",
            "retrieve_seq_from_fasta.pl", "convert2annovar.pl"]


def annovar_key(chrom: str, start: str, end: str, ref: str, alt: str) -> str:
    first, last = int(start), int(end)
    if first < 0 or last < first:
        raise ValueError(f"无效 ANNOVAR 区间: {chrom}:{start}-{end}")
    return json.dumps([canonical_contig(chrom), first, last, ref.upper(), alt.upper()], separators=(",", ":"))


def open_table(path: Path):
    # Some large genes have many transcripts; do not silently truncate long fields.
    csv.field_size_limit(64 * 1024 * 1024)
    return path.open(newline="")


def validate_prepared(path: Path) -> tuple[dict, dict[str, Path]]:
    manifest = read_json(path)
    jsonschema.Draft7Validator(read_json(ROOT / "contracts/prepared_input.schema.json")).validate(manifest)
    status = read_json(path.parent / "status.json")
    if status.get("status") != "complete" or status.get("stage") != "prepare_input":
        raise ValueError("第二步任务尚未成功完成")
    resolved = {}
    for name, spec in manifest["files"].items():
        file = (path.parent / spec["path"]).resolve(strict=True)
        if file.stat().st_size != spec["bytes"] or checksum(file) != spec["sha256"]:
            raise ValueError(f"第二步产物校验失败: {name}")
        resolved[name] = file
    return manifest, resolved


def database_snapshot(verify_hashes: bool = False) -> dict:
    lock_path = ROOT / "config/dependencies.lock.json"
    manifest_path = ROOT / "data/dependency_manifest.json"
    software_path = ROOT / "data/software_manifest.json"
    lock, installed, software = map(read_json, (lock_path, manifest_path, software_path))
    if lock["assembly"] != "GRCh38" or lock["annovar_build"] != "hg38" or lock["protocols"] != PROTOCOLS:
        raise ValueError("数据库锁文件与当前固定 hg38 ANNOVAR 注释协议不一致")
    scripts = {}
    for name in SOFTWARE:
        path = ROOT / "vendor/annovar" / name
        digest = checksum(path)
        if digest != software["annovar_scripts"][name]["sha256"]:
            raise ValueError(f"ANNOVAR 程序与安装清单不符: {name}")
        scripts[name] = {"path": str(path), "sha256": digest}
    databases = {}
    for download in lock["downloads"]:
        if download.get("target", "humandb") != "humandb":
            continue
        recorded = {Path(entry["path"]).name: entry
                    for entry in installed["files"].get(download["name"], {}).get("outputs", [])}
        for name in download["outputs"]:
            path = ROOT / "data/humandb" / name
            entry = recorded.get(name)
            if not entry or not path.is_file() or path.stat().st_size != entry["bytes"]:
                raise ValueError(f"注释数据库缺失或体积不符合安装清单: {name}")
            if verify_hashes and checksum(path) != entry["sha256"]:
                raise ValueError(f"注释数据库 SHA-256 不符合安装清单: {name}")
            databases[name] = {
                "path": str(path), "bytes": entry["bytes"], "installed_sha256": entry["sha256"],
                "source": download["url"], "catalog_date": download.get("catalog_date"),
                "mtime_ns": path.stat().st_mtime_ns,
            }
    return {
        "assembly": "GRCh38", "annovar_build": "hg38", "protocols": PROTOCOLS, "operations": OPERATIONS,
        "annotation_profile": lock["annotation_profile"], "scripts": scripts, "databases": databases,
        "lock_sha256": checksum(lock_path), "installation_manifest_sha256": checksum(manifest_path),
        "software_manifest_sha256": checksum(software_path),
        "verification": "full_sha256" if verify_hashes else "script_sha256_and_database_size; database hashes recorded at installation",
    }


def load_sources(db: sqlite3.Connection, paths: dict[str, Path], manifest: dict) -> tuple[list[str], int]:
    db.executescript("""
        CREATE TABLE variants (
            annokey TEXT PRIMARY KEY, ordinal INTEGER UNIQUE, normalized_id TEXT UNIQUE,
            source TEXT NOT NULL, avinput TEXT, annotation TEXT, triage TEXT,
            route TEXT, priority INTEGER, rank INTEGER
        );
    """)
    count = 0
    with open_table(paths["patient_variants.tsv"]) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        header = reader.fieldnames
        required = {"sample_id", "normalized_id", "ANNOVAR_CHROM", "ANNOVAR_START", "ANNOVAR_END",
                    "ANNOVAR_REF", "ANNOVAR_ALT", "use_for_acmg_ba1_bs1", "af_status", "matched_pop_AF", "matched_pop"}
        if not header or not required <= set(header) or len(set(header)) != len(header):
            raise ValueError("patient_variants.tsv 表头不符合第二步契约")
        for count, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"patient_variants.tsv 第 {count} 行列数异常")
            if row["sample_id"] != manifest["sample_id"] or row["decision"] != "retained":
                raise ValueError("患者侧表包含其他样本或未保留的变异")
            if row["use_for_acmg_ba1_bs1"] != str(manifest["frequency_policy"]["use_for_acmg_ba1_bs1"]).lower():
                raise ValueError("患者侧表与准备清单的 PopGen 频率权限不一致")
            if row["matched_pop"] != manifest["frequency_policy"]["lookup_population"]:
                raise ValueError("患者侧表与准备清单的查表人群不一致")
            key = annovar_key(*(row["ANNOVAR_" + field] for field in ("CHROM", "START", "END", "REF", "ALT")))
            try:
                db.execute("INSERT INTO variants(annokey,ordinal,normalized_id,source) VALUES(?,?,?,?)",
                           (key, count, row["normalized_id"], json.dumps(row, ensure_ascii=False)))
            except sqlite3.IntegrityError as error:
                raise ValueError("患者侧表存在重复标准化 ID 或 ANNOVAR 坐标，拒绝任意合并") from error
    if count != manifest["counts"]["retained_variants"]:
        raise ValueError("患者侧表行数与第二步清单不一致")
    av_count = 0
    with paths["patient.avinput"].open() as handle:
        for av_count, line in enumerate(handle, 1):
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 8:
                raise ValueError(f"patient.avinput 第 {av_count} 行应有 8 列")
            key = annovar_key(*fields[:5])
            original = db.execute("SELECT avinput FROM variants WHERE annokey=?", (key,)).fetchone()
            if original is None or original["avinput"] is not None:
                raise ValueError("ANNOVAR 输入与患者侧表不能唯一对应")
            db.execute("UPDATE variants SET avinput=? WHERE annokey=?", (line.rstrip("\n"), key))
    if av_count != count or db.execute("SELECT count(*) FROM variants WHERE avinput IS NULL").fetchone()[0]:
        raise ValueError("ANNOVAR 输入与患者侧表的变异集合不一致")
    db.commit()
    return header, count


def frequency_exceptions() -> tuple[set[str], dict]:
    path = ROOT / "vendor/InterVar/intervardb/ext.variants.hg38"
    keys = set()
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("固定 InterVar hg38 频率例外表格式异常")
        keys.add(f"GRCh38:{canonical_contig(fields[0])}:{int(fields[1])}:{fields[2].upper()}:{fields[3].upper()}")
    return keys, {"path": str(path), "sha256": checksum(path), "n_variants": len(keys),
                  "role": "historical InterVar frequency exceptions; not a complete or current disease whitelist"}


def annotation_header(path: Path, *, allow_empty: bool = False) -> list[str]:
    with open_table(path) as handle:
        header = next(csv.reader(handle, delimiter="\t"), [])
    if not header and allow_empty:
        return list(REQUIRED_ANNOTATION)
    if not header or len(header) != len(set(header)):
        raise ValueError("ANNOVAR 注释表缺少表头或包含重复列")
    absent = sorted(set(REQUIRED_ANNOTATION) - set(header))
    if absent:
        raise ValueError(f"ANNOVAR 注释结果缺少必需字段: {', '.join(absent)}")
    return header


def run_annovar(paths: dict[str, Path], outdir: Path, snapshot: dict, count: int,
                threads: int, keep_work: bool) -> tuple[Path, list[dict]]:
    raw = outdir / "raw/annovar.hg38_multianno.txt"
    if not count:
        raw.write_text("\t".join(REQUIRED_ANNOTATION) + "\n")
        (outdir / "logs/annovar.log").write_text("No prepared variants; ANNOVAR skipped.\n")
        return raw, []
    # ANNOVAR invokes shell commands internally. All paths it sees are controlled
    # relative aliases inside an ASCII-only private directory, never user paths.
    scratch = Path(tempfile.mkdtemp(prefix="egene_annovar_", dir="/tmp"))
    commands = []
    try:
        (scratch / "annovar").mkdir()
        for name, spec in snapshot["scripts"].items():
            (scratch / "annovar" / name).symlink_to(spec["path"])
        (scratch / "humandb").symlink_to(ROOT / "data/humandb", target_is_directory=True)
        shutil.copyfile(paths["patient.avinput"], scratch / "input.avinput")
        perl = shutil.which("perl")
        if not perl:
            raise ValueError("找不到 Perl")
        args = [
            perl, "annovar/table_annovar.pl", "input.avinput", "humandb/",
            "-buildver", "hg38", "-out", "annovar", "-protocol", ",".join(PROTOCOLS),
            "-operation", ",".join(OPERATIONS), "-nastring", ".", "-otherinfo",
            "-thread", str(threads), "-maxgenethread", str(threads), "-remove",
        ]
        # The result prefix must not collide with the executable directory.
        args[args.index("-out") + 1] = "patient"
        commands.append({"argv": args, "cwd": str(scratch),
                         "path_aliases": {"humandb": str(ROOT / "data/humandb"),
                                          "input.avinput": str(paths["patient.avinput"])}})
        write_json(outdir / "execution.json", {"status": "running", "commands": commands})
        print(f"开始 ANNOVAR：{count:,} 个变异，{len(PROTOCOLS)} 个协议，{threads} 个线程", flush=True)
        with (outdir / "logs/annovar.log").open("w") as log:
            result = subprocess.run(args, cwd=scratch, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise ValueError(f"ANNOVAR 退出码 {result.returncode}；详见 logs/annovar.log")
        output = scratch / "patient.hg38_multianno.txt"
        annotation_header(output)
        shutil.copyfile(output, raw)
        write_json(outdir / "execution.json", {"status": "complete", "commands": commands,
                                              "scratch_directory": str(scratch) if keep_work else None})
    except Exception:
        write_json(outdir / "execution.json", {"status": "failed", "commands": commands,
                                              "scratch_directory": str(scratch)})
        # Keep failure evidence; do not traverse or copy the database symlink.
        raise
    else:
        if not keep_work:
            shutil.rmtree(scratch)
    return raw, commands


def parse_annotations(db: sqlite3.Connection, raw: Path, prepared: dict, policy: dict,
                      exceptions: set[str], expected_count: int) -> tuple[list[str], dict]:
    header = annotation_header(raw)
    counts = Counter()
    function_counts, clinvar_counts, route_counts, kind_counts = Counter(), Counter(), Counter(), Counter()
    warning_counts = Counter()
    annotated = 0
    nonempty_function = 0
    with open_table(raw) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for annotated, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"ANNOVAR 第 {annotated} 行列数与表头不一致")
            key = annovar_key(*(row[name] for name in ("Chr", "Start", "End", "Ref", "Alt")))
            original = db.execute("SELECT * FROM variants WHERE annokey=?", (key,)).fetchone()
            if original is None or original["annotation"] is not None:
                raise ValueError(f"ANNOVAR 输出出现额外或重复变异: {key}")
            tail = original["avinput"].split("\t")[5:]
            if [row["Otherinfo" + str(i)] for i in (1, 2, 3)] != tail:
                raise ValueError("ANNOVAR Otherinfo 与准备输入的基因型/质量字段不一致")
            source = json.loads(original["source"])
            triage = prioritize(source, row, policy,
                                frequency_permission=prepared["frequency_policy"]["use_for_acmg_ba1_bs1"],
                                curated_exception=original["normalized_id"] in exceptions)
            db.execute("""UPDATE variants SET annotation=?,triage=?,route=?,priority=?,rank=? WHERE annokey=?""",
                       (json.dumps(row, ensure_ascii=False), json.dumps(triage, ensure_ascii=False),
                        triage["triage_route"], int(triage["priority_review"]), triage["triage_rank"], key))
            route_counts[triage["triage_route"]] += 1
            kind_counts[triage["triage_kind"]] += 1
            function_counts[row.get("Func.refGene", ".")] += 1
            clinvar_counts[row.get("CLNSIG", ".")] += 1
            counts["annotated_variants"] += 1
            counts["candidate_variants"] += triage["triage_route"] != "background"
            counts["priority_variants"] += triage["priority_review"]
            counts["review_variants"] += triage["triage_route"] == "review"
            counts["background_variants"] += triage["triage_route"] == "background"
            nonempty_function += any(row.get("Func." + name, ".") not in {"", "."} for name in policy["gene_protocols"])
            if triage["screen_frequency_status"] == "unknown":
                warning_counts["frequency_unknown"] += 1
            if triage["frequency_sources_discordant"]:
                warning_counts["frequency_sources_discordant"] += 1
            if source.get("quality_missing") not in {"", "[]"}:
                warning_counts["source_quality_incomplete"] += 1
    if annotated != expected_count or db.execute("SELECT count(*) FROM variants WHERE annotation IS NULL").fetchone()[0]:
        raise ValueError(f"ANNOVAR 注释集合不完整：预期 {expected_count}，实际 {annotated}")
    if expected_count and not nonempty_function:
        raise ValueError("所有变异均缺少基因功能注释，请检查数据库和参考版本")
    db.commit()
    summary = {
        "counts": {name: counts[name] for name in ("annotated_variants", "candidate_variants", "priority_variants",
                                                  "review_variants", "background_variants")},
        "by_route": dict(route_counts), "by_triage_kind": dict(kind_counts),
        "refgene_functions": dict(function_counts), "clinvar_classifications": dict(clinvar_counts),
        "data_flags": dict(warning_counts),
    }
    return header, summary


def export_results(db: sqlite3.Connection, outdir: Path, source_header: list[str], anno_header: list[str]) -> None:
    header = source_header + anno_header + TRIAGE_COLUMNS
    if len(header) != len(set(header)):
        raise ValueError("注释字段与原始侧表/筛选字段重名，拒绝覆盖原始数据")
    names = ["all_variants.tsv", "candidate_variants.tsv", "priority_variants.tsv", "review_variants.tsv"]
    with __import__("contextlib").ExitStack() as stack:
        writers = {}
        for name in names:
            handle = stack.enter_context((outdir / name).open("w", newline=""))
            writers[name] = csv.DictWriter(handle, fieldnames=header, delimiter="\t", lineterminator="\n")
            writers[name].writeheader()
        candidate_av = stack.enter_context((outdir / "candidate.avinput").open("w"))
        candidate_raw = stack.enter_context((outdir / "candidate.hg38_multianno.txt").open("w", newline=""))
        raw_writer = csv.DictWriter(candidate_raw, fieldnames=anno_header, delimiter="\t", lineterminator="\n")
        raw_writer.writeheader()
        structured = stack.enter_context((outdir / "annotated_variants.jsonl").open("w"))
        for record in db.execute("SELECT * FROM variants ORDER BY rank,ordinal"):
            source = json.loads(record["source"])
            annotation = json.loads(record["annotation"])
            triage = json.loads(record["triage"])
            combined = {**source, **annotation, **triage}
            serialized = {name: tsv_value(combined[name]) for name in header}
            writers["all_variants.tsv"].writerow(serialized)
            structured.write(json.dumps({"normalized_id": record["normalized_id"], "patient": source,
                                         "annotation": annotation, "triage": triage}, ensure_ascii=False, allow_nan=False) + "\n")
            if record["route"] != "background":
                writers["candidate_variants.tsv"].writerow(serialized)
                raw_writer.writerow(annotation)
                candidate_av.write(record["avinput"] + "\n")
            if record["priority"]:
                writers["priority_variants.tsv"].writerow(serialized)
            if record["route"] == "review":
                writers["review_variants.tsv"].writerow(serialized)


def annotate(args: argparse.Namespace) -> dict:
    manifest_path = args.prepared_manifest.expanduser().resolve(strict=True)
    prepared, paths = validate_prepared(manifest_path)
    policy_path = args.policy.expanduser().resolve(strict=True)
    policy = read_json(policy_path)
    if (policy.get("schema_version") != "1.0" or
            not isinstance(policy.get("frequency_screen_cutoff"), (float, int)) or
            not 0 < policy["frequency_screen_cutoff"] < 1 or
            policy.get("gene_protocols") != ["refGene", "ensGene", "knownGene"] or
            not isinstance(policy.get("trusted_benign_min_stars"), int) or
            not 0 <= policy["trusted_benign_min_stars"] <= 4):
        raise ValueError("筛选策略版本、频率阈值或基因注释协议不合法")
    snapshot = database_snapshot(args.verify_database_hashes)
    exceptions, exception_info = frequency_exceptions()
    outdir = args.outdir.expanduser().absolute()
    if outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {outdir}")
    outdir.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "logs", "work"):
        (outdir / name).mkdir()
    write_json(outdir / "status.json", {"status": "running", "stage": "annotate_variants", "started_at": now()})
    db = None
    try:
        write_json(outdir / "database_snapshot.json", snapshot)
        write_json(outdir / "triage_policy.json", policy)
        db = sqlite3.connect(outdir / "work/annotation.sqlite")
        db.row_factory = sqlite3.Row
        source_header, count = load_sources(db, paths, prepared)
        raw, commands = run_annovar(paths, outdir, snapshot, count, args.threads, args.keep_work)
        anno_header, summary = parse_annotations(db, raw, prepared, policy, exceptions, count)
        export_results(db, outdir, source_header, anno_header)
        # Detect changes during execution without rereading 75 GB on every run.
        for spec in snapshot["databases"].values():
            path = Path(spec["path"])
            if path.stat().st_size != spec["bytes"] or path.stat().st_mtime_ns != spec["mtime_ns"]:
                raise ValueError(f"处理期间数据库发生变化: {path.name}")
        for name, spec in snapshot["scripts"].items():
            if checksum(Path(spec["path"])) != spec["sha256"]:
                raise ValueError(f"处理期间 ANNOVAR 程序发生变化: {name}")
        for name, spec in prepared["files"].items():
            if checksum(paths[name]) != spec["sha256"]:
                raise ValueError(f"处理期间第二步输入发生变化: {name}")
        if checksum(policy_path) != checksum(outdir / "triage_policy.json"):
            # Compare JSON data rather than formatting when users supply a policy.
            if read_json(policy_path) != policy:
                raise ValueError("处理期间筛选策略发生变化")
        summary.update({
            "sample_id": prepared["sample_id"], "stage": "annotation_and_preliminary_triage",
            "classification_performed": False, "phenotype_and_inheritance_evaluated": False,
            "screening_cutoff": policy["frequency_screen_cutoff"],
            "database_profile": snapshot["annotation_profile"],
            "upstream_input_qc": read_json(paths["input_qc.json"]),
            "file_semantics": {
                "candidate_variants.tsv": "candidate + review routes; for further interpretation, not a pathogenic list",
                "priority_variants.tsv": "evidence-based priority subset, no fixed count or disease probability",
                "review_variants.tsv": "conflicting, special-context or contradictory annotations; overlaps candidates",
                "background_variants": "deprioritized only; all annotations retained in all_variants.tsv",
            },
            "limitations": [
                "InterVar-compatible historical database snapshot, including ClinVar 20210501; not current assertions.",
                "This is annotation prioritization, not ACMG classification or patient diagnosis.",
                "No phenotype or disease-specific frequency threshold has been applied.",
                "Unknown frequency/prediction/quality is not treated as zero, benign, or positive evidence.",
            ],
        })
        write_json(outdir / "annotation_summary.json", summary)
        db.close()
        db = None
        if not args.keep_work:
            shutil.rmtree(outdir / "work")
        output_names = ["raw/annovar.hg38_multianno.txt", "all_variants.tsv", "annotated_variants.jsonl",
                        "candidate_variants.tsv", "priority_variants.tsv", "review_variants.tsv",
                        "candidate.avinput", "candidate.hg38_multianno.txt", "annotation_summary.json",
                        "database_snapshot.json", "triage_policy.json", "execution.json", "logs/annovar.log"]
        if not (outdir / "execution.json").exists():
            write_json(outdir / "execution.json", {"status": "complete", "commands": []})
        result = {
            "schema_version": "1.0", "status": "complete", "stage": "annotate_variants",
            "producer": {"name": "egene.annovar_annotation", "version": __version__, "finished_at": now()},
            "sample_id": prepared["sample_id"], "assembly": "GRCh38", "annovar_build": "hg38",
            "prepared_manifest": {"path": str(manifest_path), "sha256": checksum(manifest_path)},
            "counts": summary["counts"], "classification_performed": False,
            "database_snapshot_sha256": checksum(outdir / "database_snapshot.json"),
            "triage_policy_sha256": checksum(outdir / "triage_policy.json"), "frequency_exceptions": exception_info,
            "frequency_policy": prepared["frequency_policy"],
            "files": {name: {"path": name, "bytes": (outdir / name).stat().st_size,
                             "sha256": checksum(outdir / name)} for name in output_names},
            "commands": commands,
        }
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/annotated_variants.schema.json")).validate(result)
        write_json(outdir / "annotation_manifest.json", result)
        write_json(outdir / "status.json", {"status": "complete", "stage": "annotate_variants",
                                          "finished_at": now(), "counts": summary["counts"]})
        print(f"注释完成：{count:,} 个变异；后续候选 {summary['counts']['candidate_variants']:,} 个，"
              f"优先复核 {summary['counts']['priority_variants']:,} 个\n输出目录：{outdir}", flush=True)
        return result
    except Exception as error:
        if db is not None:
            db.close()
        write_json(outdir / "status.json", {"status": "failed", "stage": "annotate_variants",
                                          "failed_at": now(), "error": str(error)})
        raise


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-manifest", required=True, type=Path, help="Step-2 input_manifest.json")
    parser.add_argument("--outdir", required=True, type=Path, help="New output directory; never overwrite existing results")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--policy", type=Path, default=ROOT / "config/annotation_triage.json")
    parser.add_argument("--verify-database-hashes", action="store_true", help="Rehash every database; reads about 75 GB")
    parser.add_argument("--keep-work", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = argument_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.threads <= 64:
        parser.error("--threads 必须在 1 到 64 之间")
    try:
        annotate(args)
    except (ValueError, OSError, KeyError, sqlite3.Error, jsonschema.ValidationError) as error:
        print(f"注释失败：{error}", file=sys.stderr)
        return 2
    return 0
