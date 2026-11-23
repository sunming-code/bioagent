"""Build a per-carried-allele review table and bounded, offline chromosome views."""
from __future__ import annotations

import base64
from bisect import bisect_right
from collections import Counter
from contextlib import closing
import csv
import gzip
import io
import math
import os
from pathlib import Path
import sqlite3
import tempfile

FIELDS = ("record_id", "alt_index", "CHROM", "POS", "REF", "ALT", "GT", "DP", "GQ", "AD",
          "heterozygous_AB", "QUAL", "FILTER", "FT", "matched_pop_AF", "global_AF",
          "frequency_context", "egene_context", "sample_id", "assembly", "matched_pop",
          "use_for_acmg_ba1_bs1", "quality_context")
QC_EDGES = {"DP": (5, 10, 20, 30, 50, 100), "GQ": (10, 20, 30, 60, 90),
            "AB": tuple(i / 10 for i in range(1, 10))}
TABLE = "variant_review.tsv.gz"
INTEGRATED_TABLE = "variant_review_egene.tsv.gz"
SHORTLIST = "review_shortlist.tsv.gz"


def numeric(value):
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


def index_inputs(db, af_path, acmg_path, sample_id):
    db.execute("CREATE TABLE af (chr,pos,ref,alt,af,global_af, PRIMARY KEY(chr,pos,ref,alt)) WITHOUT ROWID")
    with af_path.open(encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f, delimiter="\t")
        db.executemany("INSERT INTO af VALUES (?,?,?,?,?,?)",
                       ((r["CHROM"], r["POS"], r["REF"], r["ALT"], r["matched_pop_AF"], r["global_AF"]) for r in rows))
    if acmg_path:
        db.execute("CREATE TABLE interpretations (rec,idx,chr,pos,ref,alt,gt,context)")
        with acmg_path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r.get("sample_id") != sample_id:
                    raise ValueError("e-Gene 判级表的样本与 PopGen 不一致")
                if r.get("source_CHROM") and r.get("record_id"):
                    context = " / ".join(r.get(k, "") for k in ("intervar_gene", "triage_route", "acmg_classification"))
                    db.execute("INSERT INTO interpretations VALUES (?,?,?,?,?,?,?,?)", (r["record_id"], r["alt_index"],
                               r["source_CHROM"], r["source_POS"], r["source_REF"], r["source_ALT"], r["source_GT"], context))
        db.execute("CREATE INDEX by_record ON interpretations(rec,idx)")


def write_shortlist(outdir, policy):
    """Persist run-time selection separately from the complete evidence table."""
    cutoff = policy["af_percent"] / 100
    limits = [(key, policy["min_" + key.lower()]) for key in ("DP", "GQ") if policy["min_" + key.lower()] is not None]
    selected = 0
    tmp = tempfile.NamedTemporaryFile(dir=outdir, delete=False)
    path = Path(tmp.name)
    try:
        with (tmp, gzip.open(outdir / TABLE, "rt", encoding="utf-8", newline="") as source,
              gzip.GzipFile(filename="", mode="wb", fileobj=tmp, mtime=0) as gz,
              io.TextIOWrapper(gz, encoding="utf-8", newline="") as dest):
            rows = csv.DictReader(source, delimiter="\t")
            writer = csv.DictWriter(dest, fieldnames=rows.fieldnames, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                af = numeric(row["matched_pop_AF"])
                if af is None or af >= cutoff:
                    continue
                for key, minimum in limits:
                    value = numeric(row[key])
                    if (value is None and not policy["keep_missing_quality"]) or (value is not None and value < minimum):
                        break
                else:
                    writer.writerow(row)
                    selected += 1
        path.replace(outdir / SHORTLIST)
    finally:
        path.unlink(missing_ok=True)
    return selected


def collect(vcf_path, sample_id, af_path, outdir, lookup, allowed, acmg_path=None, af_percent=1.0):
    """One row per complete genotype carrying the ALT, in original VCF order."""
    counts = Counter()
    hist = {k: [0] * (len(bins) + 1) for k, bins in QC_EDGES.items()}
    chunks = {}
    block = []
    last_chrom = None

    def flush():
        if block:
            compressed = gzip.compress("".join(block).encode(), compresslevel=4, mtime=0)
            chunks[last_chrom].append(base64.b64encode(compressed).decode("ascii"))
            block.clear()

    with vcf_path.open("rb") as source:
        open_vcf = gzip.open if source.read(2) == b"\x1f\x8b" else open
    tmp = tempfile.NamedTemporaryFile(dir=outdir, delete=False)
    temp_path = Path(tmp.name)
    try:
        with (tmp, closing(sqlite3.connect("")) as db, open_vcf(vcf_path, "rt", encoding="utf-8") as vcf,
              gzip.GzipFile(filename="", mode="wb", fileobj=tmp, mtime=0) as gz,
              io.TextIOWrapper(gz, encoding="utf-8") as out):
            index_inputs(db, af_path, acmg_path, sample_id)
            out.write("\t".join(FIELDS) + "\n")
            for line in vcf:
                if line.startswith("#CHROM"):
                    if line.rstrip("\r\n").split("\t")[9:] != [sample_id]:
                        raise ValueError("PopGen 位点复核的 VCF 样本与证据包不一致")
                    break
            else:
                raise ValueError("PopGen 位点复核缺少 VCF 样本表头")
            for record_id, line in enumerate(vcf, 1):
                chrom, pos, _, ref, alt_text, qual, site_filter, info, fmt, sample = line.rstrip("\r\n").split("\t")
                counts["records"] += 1
                fields = dict(zip(fmt.split(":"), sample.split(":")))
                gt = fields.get("GT", ".")
                calls = gt.replace("|", "/").split("/")
                alts = alt_text.split(",")
                counts["input_alt"] += len(alts)
                if not all(c.isdigit() for c in calls):
                    counts["unknown_gt_alt"] += len(alts)
                    continue
                if any(int(c) > len(alts) for c in calls):
                    raise ValueError(f"VCF 记录 {record_id} 的 GT 超出 ALT 范围")
                carried = {int(c) for c in calls} - {0}
                counts["not_carried_alt"] += len(alts) - len(carried)
                if not carried:
                    continue
                counts["carried_records"] += 1
                for k in ("DP", "GQ"):
                    value = numeric(fields.get(k))
                    if value is not None:
                        hist[k][bisect_right(QC_EDGES[k], value)] += 1
                ab = ""
                if len(alts) == 1 and sorted(calls) == ["0", "1"] and ";POPGEN_ORIG=" not in (";" + info):
                    counts["ab_eligible"] += 1
                    ad = [numeric(x) for x in fields.get("AD", ".").split(",")]
                    if len(ad) == 2 and None not in ad and sum(ad) > 0:
                        balance = ad[1] / sum(ad)
                        hist["AB"][bisect_right(QC_EDGES["AB"], balance)] += 1
                        ab = format(balance, ".8g")
                missing = [tag for tag in ("DP", "GQ") if numeric(fields.get(tag)) is None]
                ad_values = fields.get("AD", ".").split(",")
                if len(ad_values) != len(alts) + 1 or any(numeric(x) is None for x in ad_values):
                    missing.append("AD")
                quality = ["缺少 " + "/".join(missing)] if missing else ["DP/GQ/AD 已提供"]
                filter_values = {site_filter, fields.get("FT", ".")} - {".", "PASS"}
                if filter_values:
                    quality.append("原始过滤标记 " + "/".join(sorted(filter_values)))
                if chrom != last_chrom:
                    flush()
                    chunks.setdefault(chrom, [])
                    last_chrom = chrom
                for idx in sorted(carried):
                    alt = alts[idx-1]
                    key = (chrom, pos, ref, alt)
                    freq = db.execute("SELECT af, global_af FROM af WHERE chr=? AND pos=? AND ref=? AND alt=?", key).fetchone()
                    af, global_af = freq or ("", "")
                    value = numeric(af)
                    if value is None or value > 1:
                        reason = "频率未知"
                    elif value == 0:
                        reason = "参考频率记录为零"
                    elif value < af_percent / 100:
                        reason = f"匹配人群频率低于{af_percent:g}%"
                    else:
                        reason = f"匹配人群频率达到{af_percent:g}%"
                    if not allowed:
                        reason += "（仅供参考）"
                    interpretation = ""
                    if acmg_path:
                        hits = db.execute("SELECT DISTINCT context FROM interpretations WHERE rec=? AND idx=? "
                                          "AND chr=? AND pos=? AND ref=? AND alt=? AND gt=? ORDER BY context",
                                          (str(record_id), str(idx), *key, gt))
                        interpretation = " | ".join(h[0] for h in hits)
                    row = (str(record_id), str(idx), *key, gt, fields.get("DP", "."), fields.get("GQ", "."),
                           fields.get("AD", "."), ab, qual, site_filter, fields.get("FT", "."), af, global_af,
                           reason, interpretation, sample_id, "GRCh38", lookup, str(allowed).lower(), "；".join(quality))
                    record = "\t".join(row) + "\n"
                    out.write(record)
                    block.append(record)
                    counts["carried_alt"] += 1
                    if len(block) == 12000:
                        flush()
            flush()
        os.replace(temp_path, outdir / (INTEGRATED_TABLE if acmg_path else TABLE))
    finally:
        temp_path.unlink(missing_ok=True)
    return {"counts": counts, "hist": hist, "chunks": chunks, "integrated": bool(acmg_path)}
