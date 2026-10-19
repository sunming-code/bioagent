#!/usr/bin/env python3
"""WES variant-only → 在底库 AIM 上补参考纯合 0/0。

规则：覆盖 >= min_dp 且原 VCF 该坐标无记录 → 0/0；覆盖不足保持缺失，不写成 0/0。
已有 VCF 记录一律保留，不覆盖。
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run(cmd: str) -> None:
    print(f"[fill_refhom] RUN: {cmd}", flush=True)
    proc = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if proc.returncode != 0:
        err = (proc.stderr or "")[-4000:]
        raise RuntimeError(f"命令失败 ({proc.returncode}): {cmd}\n{err}")


def bim_to_intervals(bim: Path, bed: Path) -> int:
    n = 0
    with bim.open() as inf, bed.open("w") as out:
        for line in inf:
            chrom, _vid, _cm, pos, _a1, _a2 = line.split()
            p = int(pos)
            out.write(f"{chrom}\t{p - 1}\t{p}\n")
            n += 1
    return n


def load_called_positions(vcf: Path) -> set[tuple[str, int]]:
    called: set[tuple[str, int]] = set()
    cmd = f"bcftools query -f '%CHROM\\t%POS\\n' {vcf}"
    proc = subprocess.run(cmd, shell=True, text=True, capture_output=True, check=True)
    for line in proc.stdout.splitlines():
        chrom, pos = line.split("\t")
        called.add((chrom, int(pos)))
    return called


def vcf_header(vcf: Path, sample: str) -> str:
    proc = subprocess.run(
        f"bcftools view -h {vcf}",
        shell=True,
        text=True,
        capture_output=True,
        check=True,
    )
    lines = proc.stdout.splitlines()
    info_line = (
        '##INFO=<ID=RefHomFill,Number=0,Type=Flag,'
        'Description="Homozygous reference filled from BAM depth at panel AIM">'
    )
    if not any(line.startswith("##INFO=<ID=RefHomFill,") for line in lines):
        out = []
        inserted = False
        for line in lines:
            if not inserted and line.startswith("#CHROM"):
                out.append(info_line)
                inserted = True
            out.append(line)
        lines = out
    # 样本名保持与原 VCF 一致
    if lines and lines[-1].startswith("#CHROM"):
        cols = lines[-1].split("\t")
        cols[-1] = sample
        lines[-1] = "\t".join(cols)
    return "\n".join(lines) + "\n"


def sample_name(vcf: Path) -> str:
    proc = subprocess.run(
        f"bcftools query -l {vcf}",
        shell=True,
        text=True,
        capture_output=True,
        check=True,
    )
    names = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not names:
        raise RuntimeError(f"VCF 无样本名: {vcf}")
    return names[0]


def write_fill_vcf(
    bim: Path,
    depth: Path,
    called: set[tuple[str, int]],
    header: str,
    out_vcf: Path,
    min_dp: int,
) -> dict:
    dp_map: dict[tuple[str, int], int] = {}
    with depth.open() as fh:
        for line in fh:
            chrom, pos, dp = line.split()[:3]
            dp_map[(chrom, int(pos))] = int(dp)

    n_panel = n_called = n_fill = n_low = n_no_dp = 0
    out_vcf.parent.mkdir(parents=True, exist_ok=True)
    raw = Path(str(out_vcf)[:-3]) if str(out_vcf).endswith(".gz") else out_vcf
    with raw.open("w") as out:
        out.write(header)
        for line in bim.read_text().splitlines():
            chrom, vid, _cm, pos_s, a1, a2 = line.split()
            pos = int(pos_s)
            n_panel += 1
            # ID 为 chr:pos:REF:ALT；A2≈REF、A1≈ALT
            parts = vid.split(":")
            if len(parts) >= 4:
                ref, alt = parts[2], parts[3]
            else:
                ref, alt = a2, a1
            key = (chrom, pos)
            if key in called:
                n_called += 1
                continue
            dp = dp_map.get(key, 0)
            if dp < min_dp:
                if dp == 0 and key not in dp_map:
                    n_no_dp += 1
                else:
                    n_low += 1
                continue
            n_fill += 1
            out.write(
                f"{chrom}\t{pos}\t{vid}\t{ref}\t{alt}\t.\tPASS\t"
                f"RefHomFill;DP={dp}\tGT:DP\t0/0:{dp}\n"
            )
    if str(out_vcf).endswith(".gz"):
        run(f"bgzip -f {raw}")
    return {
        "panel_aim": n_panel,
        "already_in_vcf": n_called,
        "filled_0_0": n_fill,
        "low_coverage_skipped": n_low,
        "no_depth_record": n_no_dp,
        "min_dp": min_dp,
    }


def concat_sort(orig: Path, fill: Path, out: Path, tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    if not str(fill).endswith(".gz"):
        raise RuntimeError("fill VCF 需要 .vcf.gz")
    fill_sorted = tmp / "fill.sorted.vcf.gz"
    run(f"bcftools sort -Oz -o {fill_sorted} {fill} -T {tmp / 'fill_sort'}")
    run(f"bcftools index -f -t {fill_sorted}")
    fill_sorted.replace(fill)
    run(f"bcftools index -f -t {fill}")
    if not Path(str(orig) + ".tbi").exists() and not Path(str(orig) + ".csi").exists():
        run(f"bcftools index -f -t {orig}")
    merged = tmp / "merged.unsorted.vcf.gz"
    run(f"bcftools concat -a -Oz -o {merged} {orig} {fill}")
    run(f"bcftools sort -Oz -o {out} {merged} -T {tmp / 'sorttmp'}")
    run(f"bcftools index -f -t {out}")


def main() -> None:
    p = argparse.ArgumentParser(description="从 BAM 深度补 AIM 上的 0/0")
    p.add_argument("--bim", type=Path, required=True)
    p.add_argument("--vcf", type=Path, required=True)
    p.add_argument("--bam", type=Path, required=True)
    p.add_argument("--outdir", type=Path, required=True)
    p.add_argument("--min-dp", type=int, default=10)
    p.add_argument("--intervals", type=Path, help="写出 interval BED（避免覆盖 plink .bed）")
    p.add_argument("--complete-vcf", type=Path, required=True)
    p.add_argument("--stats", type=Path, required=True)
    args = p.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)
    intervals = args.intervals or (args.outdir / "panel.intervals.bed")
    n_int = bim_to_intervals(args.bim, intervals)
    print(f"[fill_refhom] intervals {n_int} → {intervals}", flush=True)

    depth = args.outdir / "panel.depth.tsv"
    run(
        f"samtools depth -b {intervals} --excl-flags UNMAP,SECONDARY,QCFAIL,DUP "
        f"-o {depth} {args.bam}"
    )

    sample = sample_name(args.vcf)
    called = load_called_positions(args.vcf)
    print(f"[fill_refhom] sample={sample} called_positions={len(called)}", flush=True)
    fill_vcf = args.outdir / "fill_0_0.vcf.gz"
    stats = write_fill_vcf(
        args.bim, depth, called, vcf_header(args.vcf, sample), fill_vcf, args.min_dp
    )
    concat_sort(args.vcf, fill_vcf, args.complete_vcf, args.outdir / "concat_tmp")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}\t{v}" for k, v in stats.items()]
    lines.append(f"complete_vcf\t{args.complete_vcf}")
    args.stats.write_text("\n".join(lines) + "\n")
    print("[fill_refhom] stats:", flush=True)
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
