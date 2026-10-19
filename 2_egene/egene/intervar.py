"""Step 4: reuse locked annotations, run InterVar and audit PopGen overrides."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import configparser
import csv
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import jsonschema

from . import __version__
from .annotation import annovar_key, annotation_header, load_sources, open_table, validate_prepared
from .common import ROOT, canonical_contig, checksum, now, write_json
from .frequency_evidence import EXTERNAL_FREQUENCIES, adapt_frequency
from .ingest import read_json, tsv_value
from .triage import clinvar_summary

EVIDENCE_PATTERN = re.compile(
    r"(?:InterVar:\s*)?(Pathogenic|Likely pathogenic|Uncertain significance|Likely benign|Benign)"
    r"\s+PVS1=([01])\s+PS=(\[[^\]]*\])\s+PM=(\[[^\]]*\])\s+PP=(\[[^\]]*\])"
    r"\s+BA1=([01])\s+BS=(\[[^\]]*\])\s+BP=(\[[^\]]*\])"
)
BUILD_SUFFIX_KEYS = {"lof_genes", "pm1_domain", "knowngenecanonical", "pp2_genes", "bp1_genes",
                     "ps1_aa", "ps4_snps", "bs2_snps", "exclude_snps"}
AUX_KEYS = BUILD_SUFFIX_KEYS | {"mim2gene", "mim_recessive", "mim_domin", "mim_adultonset",
                               "mim_pheno", "mim_orpha", "orpha"}


def parse_evidence(text: str) -> tuple[str, dict[str, int]]:
    match = EVIDENCE_PATTERN.fullmatch(text.strip())
    if not match:
        raise ValueError(f"无法解析 InterVar 分类/证据: {text[:180]}")
    label, pvs1, ps, pm, pp, ba1, bs, bp = match.groups()
    evidence = {"PVS1": int(pvs1), "BA1": int(ba1)}
    for prefix, serialized, size, standard in (("PS", ps, 5, 4), ("PM", pm, 7, 6), ("PP", pp, 6, 5),
                                               ("BS", bs, 5, 4), ("BP", bp, 8, 7)):
        try:
            values = ast.literal_eval(serialized)
        except (ValueError, SyntaxError) as error:
            raise ValueError(f"无效 InterVar {prefix} 证据数组") from error
        if (not isinstance(values, list) or len(values) != size or
                any(type(value) is not int or value not in (0, 1) for value in values) or any(values[standard:])):
            raise ValueError(f"InterVar {prefix} 证据数组不符合固定版本契约")
        evidence.update({prefix + str(i): value for i, value in enumerate(values[:standard], 1)})
    return label, evidence


def validate_annotation(path: Path) -> tuple[dict, dict[str, Path], dict, dict[str, Path]]:
    manifest = read_json(path)
    jsonschema.Draft7Validator(read_json(ROOT / "contracts/annotated_variants.schema.json")).validate(manifest)
    status = read_json(path.parent / "status.json")
    if manifest.get("stage") != "annotate_variants" or status.get("stage") != "annotate_variants" or status.get("status") != "complete":
        raise ValueError("第三步任务尚未成功完成")
    paths = {}
    for name, spec in manifest["files"].items():
        file = (path.parent / spec["path"]).resolve(strict=True)
        if file.stat().st_size != spec["bytes"] or checksum(file) != spec["sha256"]:
            raise ValueError(f"第三步产物校验失败: {name}")
        paths[name] = file
    for required in ("annotated_variants.jsonl", "database_snapshot.json"):
        if required not in paths:
            raise ValueError(f"第三步清单缺少 {required}")
    spec = manifest["prepared_manifest"]
    prepared_path = (path.parent / spec["path"]).resolve(strict=True)
    if checksum(prepared_path) != spec["sha256"]:
        raise ValueError("第三步引用的第二步清单校验失败")
    prepared, prepared_paths = validate_prepared(prepared_path)
    if manifest["sample_id"] != prepared["sample_id"] or manifest["frequency_policy"] != prepared["frequency_policy"]:
        raise ValueError("第二、三步的样本或频率权限不一致")
    if checksum(paths["database_snapshot.json"]) != manifest["database_snapshot_sha256"]:
        raise ValueError("第三步数据库快照校验失败")
    return manifest, paths, prepared, prepared_paths


def intervar_snapshot() -> tuple[dict, configparser.ConfigParser]:
    lock = read_json(ROOT / "config/dependencies.lock.json")
    checkout = ROOT / "vendor/InterVar"
    commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    clean = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if commit != lock["intervar"]["commit"] or clean:
        raise ValueError("InterVar 提交与锁文件不一致，或 vendor 中的上游源码/辅助表已修改")
    config_path = ROOT / "config/intervar.hg38.ini"
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path)
    if (config.get("InterVar", "buildver") != "hg38" or
            config.get("InterVar", "disorder_cutoff") != "0.005" or
            config.get("InterVar", "evidence_file") != "None"):
        raise ValueError("第四步要求固定 hg38、原始 0.005 兼容配置且不含隐式自定义证据")
    files = {}
    for key in sorted(AUX_KEYS):
        name = config.get("InterVar", key) + (".hg38" if key in BUILD_SUFFIX_KEYS else "")
        file = Path(name).resolve(strict=True)
        files[key] = {"path": str(file), "bytes": file.stat().st_size, "sha256": checksum(file)}
    files["script"] = {"path": str(checkout / "Intervar.py"), "sha256": checksum(checkout / "Intervar.py")}
    files["config"] = {"path": str(config_path), "sha256": checksum(config_path)}
    files["worker"] = {"path": str(ROOT / "egene/intervar_worker.py"), "sha256": checksum(ROOT / "egene/intervar_worker.py")}
    for name in ("intervar.py", "frequency_evidence.py"):
        file = ROOT / "egene" / name
        files["adapter_" + name] = {"path": str(file), "sha256": checksum(file)}
    return {**lock["intervar"], "files": files, "classifier": "InterVar ACMG-AMP 2015",
            "runtime_adapter": "cast BA1/PVS1 overrides to int at classfy boundary; no vendor edits"}, config


def load_annotation(db: sqlite3.Connection, paths: dict, prepared_paths: dict, prepared: dict,
                    manifest: dict, scope: str) -> tuple[list[str], list[str], int]:
    source_header, count = load_sources(db, prepared_paths, prepared)
    db.executescript("""
        ALTER TABLE variants ADD COLUMN selected INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE variants ADD COLUMN frequency TEXT;
        CREATE TABLE expected (annokey TEXT, gene TEXT, occurrence INTEGER,
                               PRIMARY KEY(annokey,gene,occurrence));
        CREATE TABLE results (mode TEXT, annokey TEXT, gene TEXT, occurrence INTEGER, data TEXT,
                              PRIMARY KEY(mode,annokey,gene,occurrence));
    """)
    raw_header = annotation_header(paths["raw/annovar.hg38_multianno.txt"])
    required = set(EXTERNAL_FREQUENCIES) | {"SIFT_score", "CADD_raw", "CADD_phred"}
    if not required <= set(raw_header) or raw_header[:7] != ["Chr", "Start", "End", "Ref", "Alt", "Func.refGene", "Gene.refGene"]:
        raise ValueError("ANNOVAR 表头顺序或固定 InterVar 所需字段不完整")
    loaded = 0
    with paths["annotated_variants.jsonl"].open() as handle:
        for line in handle:
            record = json.loads(line)
            source, annotation, triage = record["patient"], record["annotation"], record["triage"]
            key = annovar_key(*(annotation[name] for name in ("Chr", "Start", "End", "Ref", "Alt")))
            original = db.execute("SELECT * FROM variants WHERE annokey=?", (key,)).fetchone()
            if original is None or original["annotation"] is not None or json.loads(original["source"]) != source:
                raise ValueError("第三步记录与第二步患者侧表不能唯一对应")
            if record["normalized_id"] != original["normalized_id"] or set(annotation) != set(raw_header):
                raise ValueError("第三步标准化 ID 或注释字段不一致")
            if triage["triage_route"] not in {"candidate", "review", "background"}:
                raise ValueError("未知的第三步筛选路由")
            selected = scope == "all" or triage["triage_route"] != "background"
            db.execute("UPDATE variants SET annotation=?,triage=?,selected=? WHERE annokey=?",
                       (json.dumps(annotation, ensure_ascii=False), json.dumps(triage, ensure_ascii=False), int(selected), key))
            if selected:
                # ANNOVAR can name the same flanking gene twice (or NONE,NONE).
                # Preserve upstream multiplicity explicitly instead of merging it.
                occurrences = Counter()
                for gene in re.split(r"[,;]", annotation["Gene.refGene"]):
                    occurrences[gene] += 1
                    db.execute("INSERT INTO expected VALUES(?,?,?)", (key, gene, occurrences[gene]))
            loaded += 1
    if loaded != count or count != manifest["counts"]["annotated_variants"]:
        raise ValueError("第三步全量注释记录数与准备输入不一致")
    verified = set()
    with open_table(paths["raw/annovar.hg38_multianno.txt"]) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            key = annovar_key(*(row[name] for name in ("Chr", "Start", "End", "Ref", "Alt")))
            original = db.execute("SELECT annotation,avinput FROM variants WHERE annokey=?", (key,)).fetchone()
            if key in verified or original is None or json.loads(original["annotation"]) != row:
                raise ValueError("原始 ANNOVAR 表与结构化注释不一致")
            if [row["Otherinfo" + str(i)] for i in (1, 2, 3)] != original["avinput"].split("\t")[5:]:
                raise ValueError("ANNOVAR 基因型/质量信息与患者输入不一致")
            verified.add(key)
    if len(verified) != count:
        raise ValueError("原始 ANNOVAR 表变异集合不完整")
    candidates = db.execute("SELECT count(*) FROM variants WHERE json_extract(triage,'$.triage_route') != 'background'").fetchone()[0]
    if candidates != manifest["counts"]["candidate_variants"]:
        raise ValueError("候选数量与第三步清单不一致")
    db.commit()
    selected_count = db.execute("SELECT count(*) FROM variants WHERE selected=1").fetchone()[0]
    return source_header, raw_header, selected_count


def make_evidence(db: sqlite3.Connection, outdir: Path, policy: dict, permission: bool, exception_path: Path) -> Counter:
    unknown = set(policy["variants"]) - {row[0] for row in db.execute("SELECT normalized_id FROM variants")}
    if unknown:
        raise ValueError(f"频率策略引用了输入中不存在的变异: {sorted(unknown)[:5]}")
    exceptions = set()
    for line in exception_path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        chrom, pos, ref, alt = line.split()
        exceptions.add((canonical_contig(chrom), str(int(pos)), ref, alt))
    counts = Counter()
    with (outdir / "evidence_overrides.tsv").open("w") as evidence, (outdir / "frequency_evidence.jsonl").open("w") as audit:
        evidence.write("#Chr\tStart\tRef\tAlt\tEvidence\n")
        for row in db.execute("SELECT * FROM variants WHERE selected=1 ORDER BY ordinal"):
            source, annotation = json.loads(row["source"]), json.loads(row["annotation"])
            key = (canonical_contig(annotation["Chr"]), annotation["Start"], annotation["Ref"], annotation["Alt"])
            decision = adapt_frequency(source, annotation, policy, permission=permission, historical_exception=key in exceptions)
            db.execute("UPDATE variants SET frequency=? WHERE annokey=?", (json.dumps(decision, ensure_ascii=False), row["annokey"]))
            audit.write(json.dumps(decision, ensure_ascii=False, allow_nan=False) + "\n")
            if decision["overrides"]:
                fields = [annotation["Chr"].removeprefix("chr"), annotation["Start"], annotation["Ref"], annotation["Alt"],
                          ";".join(f"{code}={value}" for code, value in decision["overrides"].items())]
                evidence.write("\t".join(fields) + "\n")
                counts["variants_with_overrides"] += 1
            for item in decision["decisions"]:
                counts[item["code"] + ":" + item["status"]] += 1
    db.commit()
    return counts


def parse_results(db: sqlite3.Connection, path: Path, mode: str) -> int:
    count = 0
    occurrences = Counter()
    with open_table(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, [])
        if len(header) != 34 or header[:6] != ["#Chr", "Start", "End", "Ref", "Alt", "Ref.Gene"]:
            raise ValueError("InterVar 输出表头不符合固定版本契约")
        for count, fields in enumerate(reader, 1):
            if len(fields) != len(header):
                raise ValueError(f"InterVar 第 {count} 行列数异常")
            key, gene = annovar_key(*fields[:5]), fields[5]
            occurrences[(key, gene)] += 1
            occurrence = occurrences[(key, gene)]
            if db.execute("SELECT 1 FROM expected WHERE annokey=? AND gene=? AND occurrence=?", (key, gene, occurrence)).fetchone() is None:
                raise ValueError("InterVar 输出包含额外变异或错误的基因上下文")
            label, evidence = parse_evidence(fields[13])
            data = {"classification": label, "evidence": evidence, "legacy_evidence": fields[13].strip(),
                    "gene": gene, "gene_occurrence": occurrence, "annovar_key": json.loads(key)}
            try:
                db.execute("INSERT INTO results VALUES(?,?,?,?,?)", (mode, key, gene, occurrence, json.dumps(data, ensure_ascii=False)))
            except sqlite3.IntegrityError as error:
                raise ValueError("InterVar 输出包含重复变异—基因记录") from error
    expected = db.execute("SELECT count(*) FROM expected").fetchone()[0]
    if count != expected:
        raise ValueError(f"InterVar 输出不完整: 预期 {expected} 条变异—基因记录，实际 {count}")
    db.commit()
    return count


def run_engine(db: sqlite3.Connection, outdir: Path, snapshot: dict, config: configparser.ConfigParser,
               header: list[str], count: int, keep_work: bool) -> list[dict]:
    commands = []
    if not count:
        for mode in ("raw", "integrated"):
            (outdir / "logs" / (mode + ".log")).write_text("Empty variant selection; InterVar skipped.\n")
        write_json(outdir / "execution.json", {"status": "complete", "commands": []})
        return commands
    scratch = Path(tempfile.mkdtemp(prefix="egene_intervar_", dir="/tmp"))
    try:
        # --skip_annovar + AVinput prevents both conversion and annotation, so no
        # upstream shell command receives user-supplied paths and no DB is downloaded.
        for mode in ("raw", "integrated"):
            work = scratch / mode
            work.mkdir()
            with (work / "input.avinput").open("w") as av, (work / "patient.hg38_multianno.txt").open("w", newline="") as ann:
                writer = csv.DictWriter(ann, fieldnames=header, delimiter="\t", lineterminator="\n")
                writer.writeheader()
                for row in db.execute("SELECT avinput,annotation FROM variants WHERE selected=1 ORDER BY ordinal"):
                    av.write(row["avinput"] + "\n")
                    writer.writerow(json.loads(row["annotation"]))
            local = configparser.ConfigParser(interpolation=None)
            local.read_dict({section: dict(config[section]) for section in config.sections()})
            local["InterVar"].update({"inputfile": "input.avinput", "inputfile_type": "AVinput", "outfile": "patient",
                                      "evidence_file": "evidence.tsv" if mode == "integrated" else "None"})
            if mode == "integrated":
                shutil.copyfile(outdir / "evidence_overrides.tsv", work / "evidence.tsv")
            with (work / "config.ini").open("w") as handle:
                local.write(handle)
            args = [sys.executable, snapshot["files"]["worker"]["path"], "--script", snapshot["files"]["script"]["path"]]
            commands.append({"mode": mode, "argv": args, "cwd": str(work), "annotation_reused": True})
            write_json(outdir / "execution.json", {"status": "running", "commands": commands})
            print(f"运行 InterVar {mode}：{count:,} 个变异，复用第三步注释", flush=True)
            with (outdir / "logs" / (mode + ".log")).open("w") as log:
                result = subprocess.run(args, cwd=work, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise ValueError(f"InterVar {mode} 退出码 {result.returncode}；详见 logs/{mode}.log")
            result_path = work / "patient.hg38_multianno.txt.intervar"
            parse_results(db, result_path, mode)
            shutil.copyfile(result_path, outdir / "raw" / (mode + ".intervar"))
            shutil.copyfile(work / "config.ini", outdir / "raw" / (mode + ".ini"))
            shutil.copyfile(work / "worker_status.json", outdir / "raw" / (mode + "_worker.json"))
        write_json(outdir / "execution.json", {"status": "complete", "commands": commands,
                                              "scratch_directory": str(scratch) if keep_work else None})
    except BaseException:
        write_json(outdir / "execution.json", {"status": "failed", "commands": commands, "scratch_directory": str(scratch)})
        raise
    else:
        if not keep_work:
            shutil.rmtree(scratch)
    return commands


def export_results(db: sqlite3.Connection, outdir: Path, source_header: list[str]) -> dict:
    columns = source_header + ["intervar_gene", "gene_occurrence", "Func.refGene", "ExonicFunc.refGene", "CLNSIG", "CLNREVSTAT",
                               "triage_route", "raw_classification", "acmg_classification", "classification_changed",
                               "raw_evidence", "integrated_evidence", "evidence_changes", "frequency_decisions", "data_flags"]
    if len(columns) != len(set(columns)):
        raise ValueError("输出字段与患者侧表重名")
    raw_counts, final_counts, flags_count = Counter(), Counter(), Counter()
    changed_variants, changed_evidence_variants = set(), set()
    contexts = 0
    with (outdir / "acmg_results.tsv").open("w", newline="") as tab, (outdir / "acmg_results.jsonl").open("w") as structured:
        writer = csv.DictWriter(tab, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        query = """SELECT v.*, r.gene, r.occurrence, r.data raw_data, i.data final_data FROM variants v
                   JOIN results r ON v.annokey=r.annokey AND r.mode='raw'
                   JOIN results i ON r.annokey=i.annokey AND r.gene=i.gene
                     AND r.occurrence=i.occurrence AND i.mode='integrated'
                   ORDER BY v.ordinal,r.gene,r.occurrence"""
        for row in db.execute(query):
            source, annotation, triage = map(json.loads, (row["source"], row["annotation"], row["triage"]))
            raw, final, frequency = map(json.loads, (row["raw_data"], row["final_data"], row["frequency"]))
            changes = {code: {"before": raw["evidence"][code], "after": value}
                       for code, value in final["evidence"].items() if raw["evidence"][code] != value}
            if set(changes) - set(frequency["overrides"]):
                raise ValueError("整合运行意外改变了未授权的证据项")
            if any(final["evidence"][code] != value for code, value in frequency["overrides"].items()):
                raise ValueError("InterVar 未实际采用指定的频率证据覆盖")
            changed = raw["classification"] != final["classification"]
            if changed:
                changed_variants.add(row["normalized_id"])
            if changes:
                changed_evidence_variants.add(row["normalized_id"])
            flags = ["historical_intervar_2015_rules", "phenotype_and_inheritance_not_evaluated"]
            if source["quality_missing"] not in {"", "[]"}:
                flags.append("source_quality_incomplete")
            clinical = clinvar_summary(annotation)
            if clinical["conflict"]:
                flags.append("clinvar_conflict_requires_review")
            if clinical["special_context"]:
                flags.append("special_clinical_context_requires_review")
            if frequency["decisions"][-1]["status"] == "insufficient_coverage_evidence":
                flags.append("PM2_withheld_unknown_reference_coverage")
            if frequency["decisions"][-1]["status"] == "contradicted_by_supported_popgen_frequency":
                flags.append("PM2_withheld_supported_popgen_benign_frequency")
            flat = {**source, "intervar_gene": row["gene"], "gene_occurrence": row["occurrence"], "Func.refGene": annotation["Func.refGene"],
                    "ExonicFunc.refGene": annotation["ExonicFunc.refGene"], "CLNSIG": annotation["CLNSIG"],
                    "CLNREVSTAT": annotation["CLNREVSTAT"], "triage_route": triage["triage_route"],
                    "raw_classification": raw["classification"], "acmg_classification": final["classification"],
                    "classification_changed": changed, "raw_evidence": raw["evidence"], "integrated_evidence": final["evidence"],
                    "evidence_changes": changes, "frequency_decisions": frequency["decisions"], "data_flags": flags}
            writer.writerow({key: tsv_value(value) for key, value in flat.items()})
            structured.write(json.dumps({"normalized_id": row["normalized_id"], "gene": row["gene"], "gene_occurrence": row["occurrence"],
                                         "patient": source, "annotation": annotation, "triage": triage,
                                         "raw": raw, "integrated": final, "classification_changed": changed,
                                         "evidence_changes": changes, "frequency": frequency, "data_flags": flags},
                                        ensure_ascii=False, allow_nan=False) + "\n")
            raw_counts[raw["classification"]] += 1
            final_counts[final["classification"]] += 1
            flags_count.update(flags)
            contexts += 1
    if contexts != db.execute("SELECT count(*) FROM expected").fetchone()[0]:
        raise ValueError("原始/整合结果的变异—基因集合不一致")
    return {"gene_context_records": contexts, "classification_changed_variants": len(changed_variants),
            "evidence_changed_variants": len(changed_evidence_variants),
            "raw_classifications_by_gene_context": dict(raw_counts),
            "integrated_classifications_by_gene_context": dict(final_counts), "data_flags": dict(flags_count)}


def classify(args: argparse.Namespace) -> dict:
    manifest_path = args.annotation_manifest.expanduser().resolve(strict=True)
    manifest, paths, prepared, prepared_paths = validate_annotation(manifest_path)
    initial_manifest_hash = checksum(manifest_path)
    policy_path = args.frequency_policy.expanduser().resolve(strict=True)
    policy_hash, policy = checksum(policy_path), read_json(policy_path)
    jsonschema.Draft7Validator(read_json(ROOT / "contracts/acmg_frequency.schema.json")).validate(policy)
    for rule in policy["variants"].values():
        if not rule["context"].strip() or not rule["basis"].strip():
            raise ValueError("频率阈值需要明确的疾病背景和依据")
        if rule.get("bs1_threshold", 0) > rule.get("ba1_threshold", 1):
            raise ValueError("同一背景的 BS1 阈值不能高于 BA1 阈值")
    snapshot, config = intervar_snapshot()
    outdir = args.outdir.expanduser().absolute()
    if outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {outdir}")
    outdir.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "logs", "work"):
        (outdir / name).mkdir()
    write_json(outdir / "status.json", {"status": "running", "stage": "classify_variants", "started_at": now()})
    db = None
    try:
        write_json(outdir / "intervar_snapshot.json", snapshot)
        write_json(outdir / "frequency_policy.json", policy)
        shutil.copyfile(paths["database_snapshot.json"], outdir / "database_snapshot.json")
        db = sqlite3.connect(outdir / "work/intervar.sqlite")
        db.row_factory = sqlite3.Row
        source_header, header, count = load_annotation(db, paths, prepared_paths, prepared, manifest, args.scope)
        evidence_counts = make_evidence(db, outdir, policy, prepared["frequency_policy"]["use_for_acmg_ba1_bs1"],
                                        Path(snapshot["files"]["exclude_snps"]["path"]))
        commands = run_engine(db, outdir, snapshot, config, header, count, args.keep_work)
        summary = export_results(db, outdir, source_header)
        summary.update({"sample_id": prepared["sample_id"], "selected_variants": count,
                        "annotated_variants": manifest["counts"]["annotated_variants"], "scope": args.scope,
                        "classification_performed": count > 0, "classifier": "InterVar 2.2.2 / ACMG-AMP 2015",
                        "frequency_adaptation": dict(evidence_counts), "frequency_policy": prepared["frequency_policy"],
                        "upstream_input_qc": read_json(prepared_paths["input_qc.json"]),
                        "phenotype_and_inheritance_evaluated": False,
                        "limitations": [
                            "Historical InterVar rules and ANNOVAR snapshots, not all subsequent ClinGen specifications.",
                            "No disease-specific risk, penetrance, phenotype or family interpretation is performed in step 4.",
                            "PopGen benign evidence requires explicit context, threshold and adequacy/exception confirmation.",
                            "PM2 is withheld when every independent frequency annotation is missing; missing lookup is not absence.",
                            "Raw/integrated labels are variant interpretations, not patient diagnoses or disease probabilities.",
                            "One variant may produce multiple gene-context records; these counts are not variant counts.",
                        ]})
        write_json(outdir / "acmg_summary.json", summary)
        # Lock the inputs actually consumed, including all upstream output files
        # and InterVar auxiliary tables. Annotation DBs are reused, never rerun.
        if checksum(manifest_path) != initial_manifest_hash or checksum(policy_path) != policy_hash:
            raise ValueError("处理期间注释清单或频率策略发生变化")
        for group, specs in ((paths, manifest["files"]), (prepared_paths, prepared["files"])):
            for name, file in group.items():
                if checksum(file) != specs[name]["sha256"]:
                    raise ValueError(f"处理期间输入发生变化: {name}")
        for spec in snapshot["files"].values():
            if checksum(Path(spec["path"])) != spec["sha256"]:
                raise ValueError(f"处理期间 InterVar 依赖发生变化: {spec['path']}")
        db.close()
        db = None
        if not args.keep_work:
            shutil.rmtree(outdir / "work")
        output_names = ["acmg_results.tsv", "acmg_results.jsonl", "acmg_summary.json", "frequency_policy.json",
                        "frequency_evidence.jsonl", "evidence_overrides.tsv", "intervar_snapshot.json",
                        "database_snapshot.json", "execution.json", "logs/raw.log", "logs/integrated.log"]
        if count:
            output_names += ["raw/" + mode + suffix for mode in ("raw", "integrated")
                             for suffix in (".intervar", ".ini", "_worker.json")]
        result = {"schema_version": "1.0", "status": "complete", "stage": "classify_variants",
                  "producer": {"name": "egene.intervar", "version": __version__, "finished_at": now()},
                  "sample_id": prepared["sample_id"], "assembly": "GRCh38", "annovar_build": "hg38",
                  "annotation_manifest": {"path": str(manifest_path), "sha256": initial_manifest_hash},
                  "classifier": {"name": "InterVar", "version": snapshot["version"], "commit": snapshot["commit"],
                                 "guidelines": "ACMG-AMP 2015", "vendor_modified": False},
                  "scope": args.scope, "counts": {key: summary[key] for key in ("selected_variants", "gene_context_records",
                                   "classification_changed_variants", "evidence_changed_variants")},
                  "classification_performed": count > 0, "frequency_policy": prepared["frequency_policy"],
                  "phenotype_and_inheritance_evaluated": False,
                  "files": {name: {"path": name, "bytes": (outdir / name).stat().st_size,
                                   "sha256": checksum(outdir / name)} for name in output_names}, "commands": commands}
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/acmg_results.schema.json")).validate(result)
        write_json(outdir / "acmg_manifest.json", result)
        write_json(outdir / "status.json", {"status": "complete", "stage": "classify_variants", "finished_at": now(),
                                          "counts": result["counts"]})
        print(f"InterVar 完成：{count:,} 个变异，{summary['gene_context_records']:,} 条基因上下文记录；"
              f"分类变化 {summary['classification_changed_variants']:,} 个变异\n输出目录：{outdir}", flush=True)
        return result
    except BaseException as error:
        if db is not None:
            db.close()
        write_json(outdir / "status.json", {"status": "failed", "stage": "classify_variants", "failed_at": now(), "error": str(error)})
        raise


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotation-manifest", required=True, type=Path, help="Step-3 annotation_manifest.json")
    parser.add_argument("--outdir", required=True, type=Path, help="New output directory; existing results are never overwritten")
    parser.add_argument("--scope", choices=("all", "candidates"), default="all", help="Default all; candidates includes review records")
    parser.add_argument("--frequency-policy", type=Path, default=ROOT / "config/acmg_frequency.json")
    parser.add_argument("--keep-work", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    try:
        classify(args)
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError, jsonschema.ValidationError) as error:
        print(f"InterVar 判级失败：{error}", file=sys.stderr)
        return 2
    return 0
