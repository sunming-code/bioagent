"""Validate and publish a single-sample GRCh38 VCF and tabix index."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import pysam


def prepare(source: Path, outdir: Path) -> dict:
    source = source.resolve(strict=True)
    outdir.mkdir(parents=True, exist_ok=True)
    destination = outdir / "patient.vcf.gz"
    if source == destination.resolve():
        raise ValueError("输入 VCF 必须位于新的任务输出目录之外")
    with pysam.VariantFile(str(source)) as vcf:
        samples = list(vcf.header.samples)
        if len(samples) != 1:
            raise ValueError(f"需要单样本 VCF，当前包含 {len(samples)} 个样本")
        if "GT" not in vcf.header.formats:
            raise ValueError("VCF 缺少 FORMAT/GT 基因型")
        header = str(vcf.header)
        if re.search(r"(?:GRCh37|hg19|human_g1k_v37|hs37d5)", header, re.I):
            raise ValueError("检测到 GRCh37/hg19；请先转换为 GRCh38")
        for name, expected in (("1", 248956422), ("2", 242193529), ("X", 156040895)):
            for contig in (name, "chr" + name):
                if contig in vcf.header.contigs:
                    length = vcf.header.contigs[contig].length
                    if length and length != expected:
                        raise ValueError(f"{contig} 长度不符合 GRCh38: {length}")
        contigs = list(vcf.header.contigs)
    renames = outdir / "contig_rename.tsv"
    mapping = {str(c): f"chr{c}" for c in range(1, 23)} | {"X": "chrX", "Y": "chrY", "MT": "chrM", "M": "chrM"}
    targets = [mapping.get(c, c) for c in contigs]
    if len(targets) != len(set(targets)):
        raise ValueError("VCF 同时含有会重名的 contig，例如 1 和 chr1")
    renames.write_text("".join(f"{c}\t{mapping[c]}\n" for c in contigs if c in mapping))
    annotated = outdir / "input.renamed.bcf"
    normalized = outdir / "input.split.bcf"
    first = ["bcftools", "annotate", "-Ob", "-o", str(annotated)]
    if renames.stat().st_size:
        first += ["--rename-chrs", str(renames)]
    subprocess.run(first + [str(source)], check=True)
    subprocess.run(["bcftools", "norm", "-m", "-any", "-Ob", "-o", str(normalized), str(annotated)], check=True)
    subprocess.run(["bcftools", "sort", "-Oz", "-o", str(destination), str(normalized)], check=True)
    subprocess.run(["bcftools", "index", "-t", str(destination)], check=True)
    n = 0
    unsupported = set()
    autosomes = {f"chr{i}" for i in range(1, 23)}
    with pysam.VariantFile(str(destination)) as vcf:
        for record in vcf:
            n += 1
            if record.chrom not in autosomes:
                unsupported.add(record.chrom)
    if n < 10000:
        raise ValueError(f"变异记录不足 10000 条（当前 {n} 条），不适合当前祖先分析流程")
    meta = {"sample_id": samples[0], "sample_alias": samples[0], "source_vcf": str(source),
            "sample_vcf": destination.name, "genome_build": "GRCh38", "variant_count": n,
            "genome_build_basis": "caller_declared_GRCh38_and_header_checks",
            "af_reference_coverage": "chr1-chr22", "unsupported_af_contigs": sorted(unsupported)}
    (outdir / "input_metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    for p in (annotated, normalized):
        p.unlink()
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vcf", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.vcf, args.outdir)
