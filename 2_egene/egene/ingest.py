"""Prepare a PopGen delivery for ANNOVAR without performing ACMG classification."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import importlib.metadata
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys

import jsonschema
import pysam

from . import __version__
from .common import ROOT, GRCH38_LENGTHS, canonical_contig, checksum, find_bcftools, now, write_json

SCHEMA = ROOT / "contracts/popgen_evidence_pack.schema.json"
SOURCE_TAG = "EGENE_SOURCE"
ALT_TAG = "EGENE_ALT_INDEX"
AF_COLUMNS = ["CHROM", "POS", "REF", "ALT", "matched_pop", "matched_pop_AF", "global_AF"]
BASES = re.compile(r"^[ACGT]+$", re.I)


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"JSON 必须为对象: {path}")
    return value


def referenced(pack_path: Path, value: str | None, label: str) -> Path:
    if not value:
        raise ValueError(f"交付包缺少 {label} 文件引用")
    path = (pack_path.parent / value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"交付文件不存在 ({label}): {path}")
    return path


def load_pack(path: Path) -> tuple[dict, dict[str, Path]]:
    pack = read_json(path)
    jsonschema.Draft7Validator(json.loads(SCHEMA.read_text())).validate(pack)
    af = pack["allele_frequency"]
    ancestry = pack["ancestry"]["analysis_based"]
    if af["join_key"] != ["CHROM", "POS", "REF", "ALT"] or af["columns"] != AF_COLUMNS:
        raise ValueError("不支持的 PopGen 频率连接键或列定义")
    if af["matched_pop"] != ancestry["af_population"]:
        raise ValueError("频率表 matched_pop 与 analysis_based.af_population 不一致")
    if ancestry["use_for_acmg_ba1_bs1"] and (
        ancestry["assignment"] != "in_reference" or ancestry["af_population"] not in {"AFR", "EUR", "EAS", "SAS", "AMR"}
    ):
        raise ValueError("BA1/BS1 使用权限与祖源 assignment/af_population 矛盾")
    if ancestry["af_population"] and ancestry["af_source"] != f"AF_{ancestry['af_population']}":
        raise ValueError("af_source 与锁定的 af_population 不一致")
    files = pack["files"]
    paths = {
        "evidence_pack": path,
        "patient_vcf": referenced(path, files.get("patient_vcf"), "patient_vcf"),
        "allele_frequency": referenced(path, af["path"], "allele_frequency.path"),
    }
    if paths["allele_frequency"] != referenced(path, files["allele_frequency"], "files.allele_frequency"):
        raise ValueError("交付包中的两个频率表引用指向不同文件")
    for key in ("patient_vcf_index", "input_metadata", "af_coverage"):
        if files.get(key):
            paths[key] = referenced(path, files[key], key)
    if "input_metadata" in paths:
        metadata = read_json(paths["input_metadata"])
        for key in ("sample_id", "genome_build", "variant_count"):
            if key in metadata and key in pack["metadata"] and metadata[key] != pack["metadata"][key]:
                raise ValueError(f"input_metadata 与交付包的 {key} 不一致")
    if "af_coverage" in paths:
        coverage = read_json(paths["af_coverage"])
        if coverage.get("missing_AF_semantics", "unknown_not_zero") != "unknown_not_zero":
            raise ValueError("频率缺失语义不兼容：必须为 unknown_not_zero")
        if coverage.get("input_alleles", af["n_rows"]) != af["n_rows"]:
            raise ValueError("af_coverage.input_alleles 与频率表声明行数不一致")
    return pack, paths


def check_reference(path: Path) -> tuple[dict[str, int], str]:
    index = Path(str(path) + ".fai")
    if not path.is_file() or not index.is_file():
        raise ValueError(f"需要已建立 .fai 索引的 GRCh38 FASTA: {path}；可运行 scripts/prepare_reference.py")
    with pysam.FastaFile(str(path)) as reference:
        lengths = dict(zip(reference.references, reference.lengths))
    recognized = {name: length for name, length in lengths.items() if name in GRCH38_LENGTHS}
    if not recognized:
        raise ValueError("FASTA 缺少 chr1–chr22/chrX/chrY/chrM 命名的参考序列")
    for name, length in recognized.items():
        if length != GRCH38_LENGTHS[name]:
            raise ValueError(f"FASTA 的 {name} 长度不符合 GRCh38: {length}")
    return lengths, checksum(path)


def connection(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE frequencies (
            chrom TEXT, pos INTEGER, ref TEXT, alt TEXT, pop TEXT,
            matched REAL, global_af REAL, seen INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chrom, pos, ref, alt)
        ) WITHOUT ROWID;
        CREATE TABLE records (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE alleles (
            record_id INTEGER REFERENCES records(id), alt_index INTEGER,
            chrom TEXT, pos INTEGER, ref TEXT, alt TEXT,
            decision TEXT, reason TEXT, af_status TEXT, matched REAL, global_af REAL,
            normalized_id TEXT UNIQUE, norm_chrom TEXT, norm_pos INTEGER, norm_ref TEXT, norm_alt TEXT,
            norm_gt TEXT, norm_ad TEXT,
            annovar_chrom TEXT, annovar_start INTEGER, annovar_end INTEGER, annovar_ref TEXT, annovar_alt TEXT,
            PRIMARY KEY(record_id, alt_index)
        );
    """)
    return db


def frequency(value: str, location: str) -> float | None:
    if value.strip().lower() in {"", ".", "na", "nan", "none", "null"}:
        return None
    try:
        result = float(value)
    except ValueError as error:
        raise ValueError(f"无效频率 ({location}): {value}") from error
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"频率必须在 [0,1] 范围内 ({location}): {value}")
    return result


def load_frequencies(db: sqlite3.Connection, path: Path, pack: dict) -> int:
    expected = pack["allele_frequency"]
    count = 0
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != AF_COLUMNS:
            raise ValueError("allele_freq.tsv 表头与交付契约不一致")
        for count, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"频率表第 {count} 行列数不正确")
            if row["matched_pop"] != expected["matched_pop"]:
                raise ValueError(f"频率表第 {count} 行查表人群不一致")
            try:
                pos = int(row["POS"])
                if pos < 1 or not row["REF"] or not row["ALT"]:
                    raise ValueError()
            except ValueError as error:
                raise ValueError(f"频率表第 {count} 行变异键无效") from error
            values = (canonical_contig(row["CHROM"]), pos, row["REF"].upper(), row["ALT"].upper(),
                      row["matched_pop"], frequency(row["matched_pop_AF"], str(count)),
                      frequency(row["global_AF"], str(count)))
            try:
                db.execute("INSERT INTO frequencies(chrom,pos,ref,alt,pop,matched,global_af) VALUES(?,?,?,?,?,?,?)", values)
            except sqlite3.IntegrityError as error:
                raise ValueError(f"频率表有重复连接键: {values[:4]}") from error
    if count != expected["n_rows"]:
        raise ValueError(f"频率表实际 {count} 行，与交付包声明的 {expected['n_rows']} 行不一致")
    db.commit()
    return count


def number(value: str, field: str, *, integer: bool = False) -> float | int | None:
    if value == ".":
        return None
    try:
        result = int(value) if integer else float(value)
    except ValueError as error:
        raise ValueError(f"{field} 数值无效: {value}") from error
    if result < 0 or not math.isfinite(result):
        raise ValueError(f"{field} 必须为非负有限数值: {value}")
    return result


def genotype_record(fields: list[str], record_id: int) -> dict:
    chrom, pos, identifier, ref, alt, qual, site_filter, info, fmt, sample = fields
    keys = fmt.split(":")
    values = sample.split(":")
    if len(set(keys)) != len(keys) or len(values) > len(keys):
        raise ValueError(f"记录 {record_id} 的 FORMAT 不合法")
    formats = dict(zip(keys, values + ["."] * (len(keys) - len(values))))
    gt = formats.get("GT", ".")
    if not re.fullmatch(r"(?:\d+|\.)(?:[/|](?:\d+|\.))*", gt) or ("/" in gt and "|" in gt):
        raise ValueError(f"记录 {record_id} 的 GT 无效: {gt}")
    alleles = [int(value) if value != "." else None for value in re.split(r"[/|]", gt)]
    alts = alt.split(",")
    if any(value is not None and value > len(alts) for value in alleles):
        raise ValueError(f"记录 {record_id} 的 GT 等位基因编号超出 ALT 范围")
    dp = number(formats.get("DP", "."), "FORMAT/DP", integer=True)
    gq = number(formats.get("GQ", "."), "FORMAT/GQ")
    ad = formats.get("AD", ".")
    if ad != ".":
        depths = [number(value, "FORMAT/AD", integer=True) for value in ad.split(",")]
        if len(depths) != len(alts) + 1:
            raise ValueError(f"记录 {record_id} 的 AD 长度与 REF/ALT 数不匹配")
    quality = number(qual, "QUAL")
    missing = [name for name, value in (("DP", dp), ("GQ", gq), ("QUAL", quality)) if value is None]
    if ad == "." or "." in ad.split(","):
        missing.append("AD")
    if site_filter == ".":
        missing.append("FILTER")
    return {
        "record_id": record_id, "CHROM": chrom, "POS": int(pos), "ID": identifier, "REF": ref, "ALT": alt,
        "QUAL": qual, "FILTER": site_filter, "INFO": info, "FORMAT": fmt, "SAMPLE": sample,
        "GT": gt, "DP": dp, "GQ": gq, "AD": ad, "PS": formats.get("PS", "."),
        "phased": "|" in gt, "ploidy": len(alleles), "gt_alleles": alleles,
        "sample_filter": formats.get("FT", "."), "quality_missing": missing,
    }


def select_allele(payload: dict, alt_index: int, alt: str, args: argparse.Namespace) -> tuple[str, str]:
    gt = payload["gt_alleles"]
    if all(value is None for value in gt):
        return "missing_genotype", "GT 未判读"
    if any(value is None for value in gt):
        return "partial_genotype", "GT 不完整，不推断缺失的等位基因"
    if len(gt) not in (1, 2):
        return "unsupported_ploidy", "当前 ANNOVAR 输入仅处理单倍体和二倍体"
    if alt_index not in gt:
        return "not_carried", "GT 不携带此 ALT"
    if canonical_contig(payload["CHROM"]) not in GRCH38_LENGTHS:
        return "unsupported_contig", "当前解释范围为 chr1–chr22/chrX/chrY/chrM"
    if not BASES.fullmatch(payload["REF"]) or not BASES.fullmatch(alt) or payload["REF"].upper() == alt.upper():
        return "unsupported_variant", "仅准备有明确 A/C/G/T 序列的变异，符号等位基因另行处理"
    if not args.include_filtered:
        if payload["FILTER"] not in {".", "PASS"}:
            return "filtered", "位点 FILTER 未通过"
        if payload["sample_filter"] not in {".", "PASS"}:
            return "filtered", "样本 FORMAT/FT 未通过"
    for field, minimum in (("DP", args.min_dp), ("GQ", args.min_gq), ("QUAL", args.min_qual)):
        if minimum is not None:
            value = number(payload[field], field) if field == "QUAL" else payload[field]
            if value is None:
                return "quality_excluded", f"设定了 {field} 阈值，但该字段缺失"
            if value < minimum:
                return "quality_excluded", f"{field}={value} 低于阈值 {minimum}"
    return "retained", ""


def source_header(path: Path, sample_id: str, reference_lengths: dict[str, int]) -> str:
    with pysam.VariantFile(str(path)) as source:
        header = source.header
        if list(header.samples) != [sample_id]:
            raise ValueError(f"VCF 必须仅包含交付包样本 {sample_id}；实际为 {list(header.samples)}")
        if "GT" not in header.formats:
            raise ValueError("VCF 缺少 FORMAT/GT 定义")
        if SOURCE_TAG in header.info or ALT_TAG in header.info:
            raise ValueError("VCF 已含 e-Gene 内部追踪标签，拒绝重复准备")
        text = str(header)
        if re.search(r"GRCh37|hg19|hs37d5|human_g1k_v37", text, re.I):
            raise ValueError("检测到 GRCh37/hg19 标记；此步骤不执行 liftover")
        names = [canonical_contig(name) for name in header.contigs]
        if len(names) != len(set(names)):
            raise ValueError("VCF 同时包含规范化后重名的 contig")
        for name in header.contigs:
            canonical = canonical_contig(name)
            length = header.contigs[name].length
            if canonical in GRCH38_LENGTHS and length and length != GRCH38_LENGTHS[canonical]:
                raise ValueError(f"VCF 的 {name} 长度不符合 GRCh38")
    lines = []
    declared = set()
    for line in text.splitlines():
        if line.startswith("#CHROM"):
            continue
        match = re.match(r"##contig=<ID=([^,>]+)", line)
        if match:
            name = canonical_contig(match.group(1))
            line = line.replace("ID=" + match.group(1), "ID=" + name, 1)
            declared.add(name)
        lines.append(line)
    for name in GRCH38_LENGTHS:
        if name not in declared and name in reference_lengths:
            lines.append(f"##contig=<ID={name},length={reference_lengths[name]}>")
    lines += [
        f'##INFO=<ID={SOURCE_TAG},Number=1,Type=Integer,Description="Original PopGen record number">',
        f'##INFO=<ID={ALT_TAG},Number=A,Type=Integer,Description="Original ALT indices before splitting">',
        f"##egene_prepare_version={__version__}",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + sample_id,
    ]
    return "\n".join(lines) + "\n"


def load_vcf(db: sqlite3.Connection, source: Path, selected: Path, pack: dict,
             reference_lengths: dict[str, int], reference_path: Path, args: argparse.Namespace) -> dict:
    header = source_header(source, pack["metadata"]["sample_id"], reference_lengths)
    with source.open("rb") as probe:
        compressed = probe.read(2) == b"\x1f\x8b"
    opener = gzip.open if compressed else open
    count = 0
    decisions = Counter()
    missing = Counter()
    gt_counts = Counter()
    mismatches = 0
    mismatch_path = selected.parent.parent / "reference_mismatches.tsv"
    with opener(source, "rt") as handle, selected.open("w") as output, \
            pysam.FastaFile(str(reference_path)) as reference, mismatch_path.open("w", newline="") as mismatch_output:
        mismatch_writer = csv.writer(mismatch_output, delimiter="\t", lineterminator="\n")
        mismatch_writer.writerow(["record_id", "CHROM", "POS", "VCF_REF", "FASTA_REF"])
        output.write(header)
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            count += 1
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 10:
                raise ValueError(f"VCF 记录 {count} 应有 10 列")
            payload = genotype_record(fields, count)
            if payload["POS"] < 1:
                raise ValueError(f"VCF 记录 {count} 的 POS 无效")
            db.execute("INSERT INTO records VALUES(?,?)", (count, json.dumps(payload, ensure_ascii=False)))
            gt_counts[payload["GT"]] += 1
            missing.update(payload["quality_missing"])
            retained = False
            for alt_index, alt in enumerate(fields[4].split(","), 1):
                decision, reason = select_allele(payload, alt_index, alt, args)
                decisions[decision] += 1
                key = (canonical_contig(fields[0]), int(fields[1]), fields[3].upper(), alt.upper())
                af = db.execute("SELECT matched,global_af FROM frequencies WHERE chrom=? AND pos=? AND ref=? AND alt=?", key).fetchone()
                if af:
                    db.execute("UPDATE frequencies SET seen=1 WHERE chrom=? AND pos=? AND ref=? AND alt=?", key)
                status = "no_row" if af is None else ("missing" if af["matched"] is None else "available")
                db.execute("""INSERT INTO alleles(
                    record_id,alt_index,chrom,pos,ref,alt,decision,reason,af_status,matched,global_af
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                           (count, alt_index, *key, decision, reason, status,
                            af["matched"] if af else None, af["global_af"] if af else None))
                retained |= decision == "retained"
            if retained:
                canonical = canonical_contig(fields[0])
                if canonical not in reference_lengths:
                    raise ValueError(f"FASTA 缺少需要核验的 contig: {canonical}")
                expected_ref = reference.fetch(canonical, int(fields[1]) - 1,
                                               int(fields[1]) - 1 + len(fields[3])).upper()
                if expected_ref != fields[3].upper():
                    mismatches += 1
                    mismatch_writer.writerow([count, canonical, fields[1], fields[3], expected_ref])
                    n_excluded = db.execute(
                        "SELECT count(*) FROM alleles WHERE record_id=? AND decision='retained'", (count,)
                    ).fetchone()[0]
                    db.execute(
                        "UPDATE alleles SET decision='reference_mismatch',reason=? WHERE record_id=? AND decision='retained'",
                        (f"GRCh38 REF={expected_ref}, VCF REF={fields[3]}; no allele swapping", count),
                    )
                    decisions["retained"] -= n_excluded
                    decisions["reference_mismatch"] += n_excluded
                    continue
                fields[0] = canonical
                fields[3] = fields[3].upper()
                fields[4] = fields[4].upper()
                tags = f"{SOURCE_TAG}={count};{ALT_TAG}=" + ",".join(map(str, range(1, len(fields[4].split(",")) + 1)))
                fields[7] = tags if fields[7] == "." else fields[7] + ";" + tags
                output.write("\t".join(fields) + "\n")
            if count % 10000 == 0:
                db.commit()
                print(f"已读取 {count:,} 条 VCF 记录", flush=True)
    expected = pack["metadata"].get("variant_count")
    if expected is not None and count != expected:
        raise ValueError(f"VCF 实际 {count} 条记录，与交付包声明的 {expected} 不一致")
    orphan = db.execute("SELECT chrom,pos,ref,alt FROM frequencies WHERE seen=0 LIMIT 1").fetchone()
    if orphan:
        raise ValueError(f"频率表含不属于输入 VCF 的变异，可能混用了任务: {tuple(orphan)}")
    db.commit()
    if mismatches and args.ref_mismatch == "error":
        raise ValueError(
            f"Reference allele mismatch: {mismatches} 条携带记录的 REF 与 GRCh38 不符；"
            f"详见 {mismatch_path}。请修正上游输入，或显式使用 --ref-mismatch exclude 排除这些记录"
        )
    return {"input_records": count, "input_alleles": sum(decisions.values()),
            "allele_decisions": dict(decisions), "original_genotypes": dict(gt_counts),
            "records_missing_quality": dict(missing), "reference_mismatch_records": mismatches}


def command(arguments: list[str], log: Path, commands: list, *, stdout=None) -> None:
    commands.append(arguments)
    with log.open("w") as errors:
        result = subprocess.run(arguments, stdout=stdout if stdout is not None else errors, stderr=errors)
    if result.returncode:
        detail = log.read_text(errors="replace")[-3000:]
        raise ValueError(f"命令失败，退出码 {result.returncode}；日志 {log.name}\n{detail}")


def normalize(db: sqlite3.Connection, selected: Path, reference: Path, outdir: Path,
              bcftools: Path, commands: list) -> int:
    unsorted = selected.parent / "normalized.all.vcf"
    command([str(bcftools), "norm", "-f", str(reference), "--check-ref", "e",
             "-m", "-any", "--multi-overlaps", "0", "-Ov", "-o", str(unsorted), str(selected)],
            outdir / "logs/normalize.log", commands)
    ready = selected.parent / "normalized.carried.vcf"
    count = 0
    with pysam.VariantFile(str(unsorted)) as source, pysam.VariantFile(str(ready), "w", header=source.header) as output:
        for record in source:
            source_id = record.info[SOURCE_TAG]
            alt_index = record.info[ALT_TAG][0]
            original = db.execute("SELECT * FROM alleles WHERE record_id=? AND alt_index=?", (source_id, alt_index)).fetchone()
            if original is None:
                raise ValueError("标准化后丢失原始记录映射")
            if original["decision"] != "retained":
                continue
            if len(record.alts or ()) != 1:
                raise ValueError("标准化后仍存在多等位记录")
            key = f"GRCh38:{record.chrom}:{record.pos}:{record.ref}:{record.alts[0]}"
            if not BASES.fullmatch(record.ref) or not BASES.fullmatch(record.alts[0]):
                raise ValueError(f"标准化后出现不支持的等位基因: {key}")
            sample = next(iter(record.samples.values()))
            gt = sample.get("GT")
            if not gt or any(value is None for value in gt) or 1 not in gt:
                raise ValueError(f"标准化后基因型不符合保留的原始 ALT: {key}")
            raw = str(record).rstrip().split("\t")
            formats = dict(zip(raw[8].split(":"), raw[9].split(":")))
            try:
                db.execute("""UPDATE alleles SET normalized_id=?,norm_chrom=?,norm_pos=?,norm_ref=?,norm_alt=?,
                    norm_gt=?,norm_ad=? WHERE record_id=? AND alt_index=?""",
                           (key, record.chrom, record.pos, record.ref, record.alts[0],
                            formats["GT"], formats.get("AD", "."), source_id, alt_index))
            except sqlite3.IntegrityError as error:
                raise ValueError(f"多个原始等位基因标准化到同一变异 {key}；请先处理重复记录，避免任意合并基因型或频率") from error
            output.write(record)
            count += 1
    expected = db.execute("SELECT count(*) FROM alleles WHERE decision='retained'").fetchone()[0]
    if count != expected:
        raise ValueError(f"标准化映射不完整: 预期 {expected}，实际 {count}")
    command([str(bcftools), "sort", "-Oz", "-o", str(outdir / "normalized.vcf.gz"),
             "-T", str(selected.parent / "sort"), str(ready)], outdir / "logs/sort.log", commands)
    command([str(bcftools), "index", "-t", str(outdir / "normalized.vcf.gz")],
            outdir / "logs/index.log", commands)
    db.commit()
    return count


def convert_annovar(db: sqlite3.Connection, outdir: Path, converter: Path,
                    perl: Path, commands: list, count: int) -> None:
    converted = outdir / "work/converted.withinfo.tsv"
    if count:
        # The upstream Perl script interpolates .gz paths into a shell pipeline.
        # Feed a plain VCF so spaces and shell metacharacters remain literal.
        converter_input = outdir / "work/annovar_input.vcf"
        with gzip.open(outdir / "normalized.vcf.gz", "rb") as source, converter_input.open("wb") as target:
            shutil.copyfileobj(source, target)
        with converted.open("w") as handle:
            command([str(perl), str(converter), "-format", "vcf4", "-includeinfo", "-withzyg",
                     str(converter_input)], outdir / "logs/convert2annovar.log", commands, stdout=handle)
    else:
        converted.touch()
        (outdir / "logs/convert2annovar.log").write_text("No retained variants; conversion skipped.\n")
    seen = set()
    with converted.open() as handle, (outdir / "patient.avinput").open("w") as output:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 18:
                raise ValueError(f"不支持的 convert2annovar 输出格式：预期 18 列，实际 {len(fields)}")
            key = f"GRCh38:{canonical_contig(fields[8])}:{fields[9]}:{fields[11]}:{fields[12]}"
            original = db.execute("SELECT normalized_id FROM alleles WHERE normalized_id=?", (key,)).fetchone()
            if original is None or key in seen:
                raise ValueError(f"ANNOVAR 转换结果存在丢失映射或重复: {key}")
            seen.add(key)
            db.execute("""UPDATE alleles SET annovar_chrom=?,annovar_start=?,annovar_end=?,annovar_ref=?,annovar_alt=?
                WHERE normalized_id=?""", (*fields[:5], key))
            output.write("\t".join(fields[:8]) + "\n")
    if len(seen) != count:
        raise ValueError(f"ANNOVAR 转换丢失变异: 预期 {count}，实际 {len(seen)}")
    db.commit()


def tsv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return value


def export_tables(db: sqlite3.Connection, outdir: Path, pack: dict) -> dict:
    ancestry = pack["ancestry"]["analysis_based"]
    pop = ancestry["af_population"]
    permission = ancestry["use_for_acmg_ba1_bs1"]
    sample_id = pack["metadata"]["sample_id"]
    source_columns = ["sample_id", "record_id", "CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER",
                      "INFO", "FORMAT", "SAMPLE", "GT", "DP", "GQ", "AD", "PS", "phased", "ploidy", "quality_missing"]
    mapping_columns = ["record_id", "alt_index", "source_CHROM", "source_POS", "source_REF", "source_ALT",
                       "source_GT", "alt_dosage", "decision", "reason", "normalized_id", "CHROM", "POS", "REF", "ALT",
                       "normalized_GT", "ANNOVAR_CHROM", "ANNOVAR_START", "ANNOVAR_END", "ANNOVAR_REF", "ANNOVAR_ALT",
                       "matched_pop", "matched_pop_AF", "global_AF", "af_status", "use_for_acmg_ba1_bs1"]
    patient_columns = ["sample_id", *mapping_columns, "original_QUAL", "original_FILTER", "original_DP", "original_GQ",
                       "original_AD", "normalized_AD", "original_PS", "original_phased", "original_ploidy", "quality_missing"]
    af_columns = ["CHROM", "POS", "REF", "ALT", "matched_pop", "matched_pop_AF", "global_AF",
                  "af_status", "use_for_acmg_ba1_bs1"]
    stats = Counter()
    with (outdir / "source_records.tsv").open("w", newline="") as raw_out, \
            (outdir / "variant_mapping.tsv").open("w", newline="") as map_out, \
            (outdir / "patient_variants.tsv").open("w", newline="") as patient_out, \
            (outdir / "allele_freq.tsv").open("w", newline="") as af_out:
        writers = []
        for handle, columns in ((raw_out, source_columns), (map_out, mapping_columns),
                                (patient_out, patient_columns), (af_out, af_columns)):
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            writers.append(writer)
        source_writer, map_writer, patient_writer, af_writer = writers
        for row in db.execute("SELECT payload FROM records ORDER BY id"):
            payload = json.loads(row["payload"])
            source_writer.writerow({key: tsv_value(value) for key, value in {"sample_id": sample_id, **payload}.items()})
        query = """SELECT a.*,r.payload FROM alleles a JOIN records r ON a.record_id=r.id ORDER BY a.record_id,a.alt_index"""
        for allele in db.execute(query):
            payload = json.loads(allele["payload"])
            row = dict(zip(mapping_columns, [
                allele["record_id"], allele["alt_index"], payload["CHROM"], payload["POS"], payload["REF"],
                payload["ALT"].split(",")[allele["alt_index"] - 1], payload["GT"],
                payload["gt_alleles"].count(allele["alt_index"]), allele["decision"], allele["reason"],
                allele["normalized_id"], allele["norm_chrom"], allele["norm_pos"], allele["norm_ref"], allele["norm_alt"],
                allele["norm_gt"], allele["annovar_chrom"], allele["annovar_start"], allele["annovar_end"],
                allele["annovar_ref"], allele["annovar_alt"], pop, allele["matched"], allele["global_af"],
                allele["af_status"], permission,
            ]))
            map_writer.writerow({key: tsv_value(value) for key, value in row.items()})
            if allele["decision"] != "retained":
                continue
            stats[allele["af_status"]] += 1
            patient_row = {"sample_id": sample_id, **row,
                           **{"original_" + key: payload[key] for key in ("QUAL", "FILTER", "DP", "GQ", "AD", "PS", "phased", "ploidy")},
                           "normalized_AD": allele["norm_ad"], "quality_missing": payload["quality_missing"]}
            patient_writer.writerow({key: tsv_value(value) for key, value in patient_row.items()})
            af_writer.writerow({key: tsv_value(value) for key, value in row.items()})
    return dict(stats)


def prepare(args: argparse.Namespace) -> dict:
    pack_path = args.popgen_pack.expanduser().resolve(strict=True)
    reference = args.reference.expanduser().resolve(strict=True)
    outdir = args.outdir.expanduser().absolute()
    if outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {outdir}")
    pack, paths = load_pack(pack_path)
    reference_lengths, reference_hash = check_reference(reference)
    bcftools = find_bcftools(args.bcftools)
    converter = args.convert2annovar.expanduser().resolve(strict=True)
    perl_path = shutil.which(args.perl)
    if not perl_path:
        raise ValueError(f"找不到 Perl: {args.perl}")
    outdir.mkdir(parents=True, exist_ok=False)
    (outdir / "work").mkdir()
    (outdir / "logs").mkdir()
    write_json(outdir / "status.json", {"status": "running", "started_at": now(), "stage": "prepare_input"})
    db = None
    try:
        source_stats = {name: (path.stat().st_size, path.stat().st_mtime_ns) for name, path in paths.items()}
        sources = {name: {"path": str(path), "bytes": path.stat().st_size, "sha256": checksum(path)} for name, path in paths.items()}
        db = connection(outdir / "work/ingest.sqlite")
        rows = load_frequencies(db, paths["allele_frequency"], pack)
        print(f"已读取 {rows:,} 行 PopGen 频率", flush=True)
        qc = load_vcf(db, paths["patient_vcf"], outdir / "work/selected.vcf", pack, reference_lengths, reference, args)
        commands = []
        count = normalize(db, outdir / "work/selected.vcf", reference, outdir, bcftools, commands)
        convert_annovar(db, outdir, converter, Path(perl_path), commands, count)
        af_stats = export_tables(db, outdir, pack)
        qc.update({
            "retained_variants": count, "ready_for_annotation": count > 0,
            "retained_frequency_status": af_stats,
            "missing_AF_semantics": "unknown_not_zero",
            "reference_check": "REF checked with --check-ref e on retained source records; no allele swapping",
            "normalized_GT_semantics": "ALT dosage only; other original ALT alleles become 0 after splitting. Use source_GT/source_records.tsv for inheritance and phase.",
            "quality_policy": {"include_filtered": args.include_filtered, "min_dp": args.min_dp,
                               "min_gq": args.min_gq, "min_qual": args.min_qual,
                               "ref_mismatch": args.ref_mismatch,
                               "missing_quality_without_threshold": "retained_and_flagged",
                               "partial_genotype": "excluded_without_imputation"},
            "warnings": [],
        })
        if qc["records_missing_quality"]:
            qc["warnings"].append("存在缺少质量字段或 FILTER 未评估的记录；缺失值未被解释为质控通过")
        if qc["reference_mismatch_records"]:
            qc["warnings"].append(f"按显式选项排除了 {qc['reference_mismatch_records']} 条 REF 不匹配记录，未改写原始基因型")
        if af_stats.get("missing", 0) + af_stats.get("no_row", 0):
            qc["warnings"].append("部分保留变异的 PopGen 频率未知，未填充为零")
        if not pack["ancestry"]["analysis_based"]["use_for_acmg_ba1_bs1"]:
            qc["warnings"].append("本包 PopGen 频率仅供信息展示，不得用于 BA1/BS1")
        if "input_metadata" in paths:
            metadata = read_json(paths["input_metadata"])
            if "holdout" in metadata.get("source_vcf", "").lower():
                qc["warnings"].append("上游来源标记为 holdout；本次运行仅证明输入准备执行成功")
        for name, path in paths.items():
            if source_stats[name] != (path.stat().st_size, path.stat().st_mtime_ns):
                raise ValueError(f"处理期间输入文件发生变化: {name}")
        write_json(outdir / "input_qc.json", qc)
        shutil.copyfile(pack_path, outdir / "popgen_evidence_pack.json")
        version = subprocess.check_output([str(bcftools), "--version"], text=True).splitlines()[:2]
        output_names = ["normalized.vcf.gz", "normalized.vcf.gz.tbi", "patient.avinput", "source_records.tsv",
                        "variant_mapping.tsv", "patient_variants.tsv", "allele_freq.tsv", "input_qc.json",
                        "popgen_evidence_pack.json", "reference_mismatches.tsv"]
        manifest = {
            "schema_version": "1.0", "status": "complete", "stage": "prepare_input",
            "producer": {"name": "egene.popgen_input", "version": __version__, "finished_at": now()},
            "sample_id": pack["metadata"]["sample_id"], "assembly": "GRCh38", "annovar_build": "hg38",
            "inputs": sources,
            "reference": {"path": str(reference), "sha256": reference_hash,
                          "fai_sha256": checksum(Path(str(reference) + ".fai")),
                          "assembly_check": "declared GRCh38, canonical contig lengths and selected-record REF checks"},
            "tools": {"python": sys.version.split()[0], "bcftools": str(bcftools), "bcftools_version": version,
                      "convert2annovar": str(converter), "convert2annovar_sha256": checksum(converter),
                      "pysam": pysam.__version__, "jsonschema": importlib.metadata.version("jsonschema")},
            "input_schema_sha256": checksum(SCHEMA),
            "ancestry": pack["ancestry"],
            "frequency_policy": {"lookup_population": pack["ancestry"]["analysis_based"]["af_population"],
                                 "use_for_acmg_ba1_bs1": pack["ancestry"]["analysis_based"]["use_for_acmg_ba1_bs1"],
                                 "gnn_usage": "supplementary_ancestry_only",
                                 "missing_AF_semantics": "unknown_not_zero",
                                 "join": "original CHROM+POS+REF+ALT before normalization; coordinates transported via variant_mapping.tsv",
                                 "classification_performed": False},
            "counts": {"input_records": qc["input_records"], "input_alleles": qc["input_alleles"],
                       "frequency_rows": rows, "retained_variants": count},
            "files": {name: {"path": name, "bytes": (outdir / name).stat().st_size,
                             "sha256": checksum(outdir / name)} for name in output_names},
            "commands": commands,
        }
        manifest["files"]["popgen_evidence_pack.json"]["role"] = "source snapshot only; resolve inputs from this manifest"
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/prepared_input.schema.json")).validate(manifest)
        db.close()
        db = None
        if not args.keep_work:
            shutil.rmtree(outdir / "work")
        write_json(outdir / "input_manifest.json", manifest)
        write_json(outdir / "status.json", {"status": "complete", "finished_at": now(),
                                          "stage": "prepare_input", "retained_variants": count})
        print(f"输入准备完成：{qc['input_records']:,} 条原始记录 → {count:,} 个携带变异\n输出目录：{outdir}", flush=True)
        return manifest
    except Exception as error:
        if db is not None:
            db.close()
        write_json(outdir / "status.json", {"status": "failed", "failed_at": now(),
                                          "stage": "prepare_input", "error": str(error)})
        raise


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--popgen-pack", type=Path, required=True, help="PopGen delivery/evidence_pack.json")
    parser.add_argument("--reference", type=Path, default=ROOT / "data/reference/GRCh38.fa", help="Indexed GRCh38 genomic FASTA")
    parser.add_argument("--outdir", type=Path, required=True, help="New output directory; existing paths are never overwritten")
    parser.add_argument("--bcftools", help="Explicit bcftools executable")
    parser.add_argument("--convert2annovar", type=Path, default=ROOT / "vendor/annovar/convert2annovar.pl")
    parser.add_argument("--perl", default="perl")
    parser.add_argument("--min-dp", type=int, help="Optional explicit FORMAT/DP minimum; missing DP then excludes")
    parser.add_argument("--min-gq", type=float, help="Optional explicit FORMAT/GQ minimum; missing GQ then excludes")
    parser.add_argument("--min-qual", type=float, help="Optional explicit site QUAL minimum; missing QUAL then excludes")
    parser.add_argument("--include-filtered", action="store_true", help="Explicitly retain failed FILTER/FT calls with their original flags")
    parser.add_argument("--ref-mismatch", choices=("error", "exclude"), default="error",
                        help="REF mismatch policy: stop by default, or explicitly exclude and audit; never swap alleles")
    parser.add_argument("--keep-work", action="store_true", help="Keep intermediate VCF and SQLite files on success")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = argument_parser()
    args = parser.parse_args(argv)
    for name in ("min_dp", "min_gq", "min_qual"):
        value = getattr(args, name)
        if value is not None and (value < 0 or not math.isfinite(value)):
            parser.error(f"--{name.replace('_', '-')} 必须为非负有限数值")
    try:
        prepare(args)
    except (ValueError, OSError, sqlite3.Error, jsonschema.ValidationError) as error:
        print(f"输入准备失败：{error}", file=sys.stderr)
        return 2
    return 0
