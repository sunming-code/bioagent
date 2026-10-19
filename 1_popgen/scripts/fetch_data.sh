#!/usr/bin/env bash
# =============================================================
# PopGen Agent - 数据下载脚本
# 下载步骤1所需的真实数据：HG002 外显子 FASTQ + GIAB truth 验证集
# 参考基因组(GRCh38)由本地复制，不在此脚本内(见 data/reference/)
#
# 用法: bash scripts/fetch_data.sh
# 支持断点续传(wget -c)，重复运行会跳过已校验完成的文件。
# =============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FASTQ_DIR="$ROOT/data/fastq"
TRUTH_DIR="$ROOT/data/truth"
mkdir -p "$FASTQ_DIR" "$TRUTH_DIR"

# ---- 下载 + md5 校验的通用函数 ----
# 用 aria2c 多连接下载(dl 环境)。国内直连 EBI 单线程仅 ~12KB/s，
# 16 连接可提速约 20 倍。ARIA="conda run -n dl aria2c ..."
ARIA=(conda run --no-capture-output -n dl aria2c -x16 -s16 -k1M \
      --file-allocation=none --max-tries=0 --retry-wait=5 -c --console-log-level=warn)

fetch() {
    local url="$1" out="$2" md5="${3:-}"
    local dir base
    dir="$(dirname "$out")"; base="$(basename "$out")"
    if [[ -f "$out" && -n "$md5" ]]; then
        if echo "$md5  $out" | md5sum -c - >/dev/null 2>&1; then
            echo "[SKIP] 已存在且校验通过: $base"; return 0
        fi
    fi
    echo "[GET ] $base"
    "${ARIA[@]}" -d "$dir" -o "$base" "$url"
    if [[ -n "$md5" ]]; then
        echo "$md5  $out" | md5sum -c - || { echo "[FAIL] md5 不匹配: $out"; return 1; }
    fi
}

echo "==================================================="
echo " 1/2  HG002 外显子 FASTQ (WXS, SRR2962669, ~12GB)"
echo "==================================================="
ENA=https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR296/009/SRR2962669
fetch "$ENA/SRR2962669_1.fastq.gz" "$FASTQ_DIR/HG002_exome_R1.fastq.gz" "fefddb5e031ee12a6719465acf84a72d"
fetch "$ENA/SRR2962669_2.fastq.gz" "$FASTQ_DIR/HG002_exome_R2.fastq.gz" "4a07904c52a6f78a8ef925144b562ac5"

echo "==================================================="
echo " 2/2  GIAB HG002 truth 验证集 (GRCh38 v4.2.1)"
echo "==================================================="
GIAB=https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38
fetch "$GIAB/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"           "$TRUTH_DIR/HG002_GRCh38_v4.2.1_benchmark.vcf.gz"
fetch "$GIAB/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz.tbi"       "$TRUTH_DIR/HG002_GRCh38_v4.2.1_benchmark.vcf.gz.tbi"
fetch "$GIAB/HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed" "$TRUTH_DIR/HG002_GRCh38_v4.2.1_benchmark.bed"

echo ; echo "==================================================="
echo " 完成。数据清单："
echo "==================================================="
ls -lah "$FASTQ_DIR"/*.fastq.gz "$TRUTH_DIR"/* 2>/dev/null | awk '{print $5"\t"$9}'
echo
echo "下一步：确认 truth VCF 的 contig 命名是否为 chr 前缀(需与 GRCh38.fa 一致)"
echo "  zcat $TRUTH_DIR/HG002_GRCh38_v4.2.1_benchmark.vcf.gz | grep -m1 -v '^#'"
