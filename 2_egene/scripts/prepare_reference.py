#!/usr/bin/env python3
"""Download, verify and index the official UCSC hg38 genomic FASTA."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from egene.common import GRCH38_LENGTHS, checksum, now, write_json

URL = "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/hg38.fa.gz"
MD5_URL = "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/md5sum.txt"
# UCSC's published digest for this fixed GRCh38 assembly file.
EXPECTED_MD5 = "1c9dcaddfa41027f17cd8f7a82c7293b"


def main() -> None:
    import pysam

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an already downloaded official hg38.fa.gz")
    args = parser.parse_args()
    directory = ROOT / "data/reference"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "GRCh38.fa"
    manifest_path = directory / "reference_manifest.json"
    if target.exists():
        if not manifest_path.is_file():
            raise ValueError("已有 FASTA 缺少来源清单；不会覆盖，请将它作为 prepare_input.py 的 --reference 输入")
        manifest = json.loads(manifest_path.read_text())
        if checksum(target) != manifest.get("fasta_sha256"):
            raise ValueError("已有参考 FASTA 与来源清单的 SHA-256 不符")
    else:
        archive = (args.archive or ROOT / ".runtime/downloads/hg38.fa.gz").resolve()
        if not args.archive:
            archive.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(MD5_URL, timeout=60) as response:
                published = response.read().decode()
            if f"{EXPECTED_MD5}  hg38.fa.gz" not in published:
                raise ValueError("UCSC 公布的参考校验值已变化，请核对来源")
            if shutil.which("aria2c"):
                environment = dict(os.environ)
                for protocol, proxy in urllib.request.getproxies().items():
                    if protocol in {"http", "https", "all", "no"}:
                        environment[protocol + "_proxy"] = proxy
                subprocess.run([
                    "aria2c", "--continue=true", "--allow-overwrite=false", "--auto-file-renaming=false",
                    "--max-connection-per-server=8", "--split=8", "--min-split-size=16M",
                    "--file-allocation=none", "--console-log-level=warn", "--summary-interval=30",
                    "--show-console-readout=false", "--enable-color=false",
                    f"--checksum=md5={EXPECTED_MD5}", f"--dir={archive.parent}", f"--out={archive.name}", URL,
                ], check=True, env=environment)
            elif not archive.exists():
                partial = archive.with_suffix(archive.suffix + ".part")
                with urllib.request.urlopen(URL, timeout=60) as response, partial.open("wb") as output:
                    shutil.copyfileobj(response, output, 8 * 1024 * 1024)
                partial.replace(archive)
        if checksum(archive, "md5") != EXPECTED_MD5:
            raise ValueError("参考压缩包的 MD5 与 UCSC 公布值不符")
        partial = target.with_suffix(".fa.part")
        digest = hashlib.sha256()
        with gzip.open(archive, "rb") as source, partial.open("wb") as output:
            for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
                output.write(block)
                digest.update(block)
        partial.replace(target)
        manifest = {
            "assembly": "GRCh38", "source": URL, "checksum_source": MD5_URL,
            "archive_md5": EXPECTED_MD5, "fasta_sha256": digest.hexdigest(),
            "fasta_bytes": target.stat().st_size, "prepared_at": now(),
        }
    pysam.faidx(str(target))
    with pysam.FastaFile(str(target)) as reference:
        for contig, length in GRCH38_LENGTHS.items():
            if reference.get_reference_length(contig) != length:
                raise ValueError(f"参考序列长度不符合 GRCh38: {contig}")
        manifest["contigs"] = dict(zip(reference.references, reference.lengths))
    manifest["fai_sha256"] = checksum(Path(str(target) + ".fai"))
    write_json(manifest_path, manifest)
    print(f"GRCh38 参考已就绪: {target}")


if __name__ == "__main__":
    main()
