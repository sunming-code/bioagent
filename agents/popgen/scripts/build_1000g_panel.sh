#!/usr/bin/env bash
# 一次性：从 1000G GRCh38 面板建 LD 剪枝 plink 底库 + 超群 .pop
# 用法:
#   bash scripts/build_1000g_panel.sh 19          # 冒烟
#   bash scripts/build_1000g_panel.sh 1-22        # 正式
#
# 临时文件默认写 /scratch（家目录空间不够）。最终 bed/bim/fam/pop 仍落在
# popgen_agent/data/reference/panel_1000g/
set -euo pipefail

CHRS_ARG="${1:-19}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PANEL_VCF_DIR=/data/public/1000GP/20220422_3202_phased_SNV_INDEL_SV
SAMPLES_INFO=/data/public/1000GP/samples.info
OUT="$ROOT/data/reference/panel_1000g"
TMP="${PANEL_TMP:-/scratch/wangy/RBM_popgen/panel_1000g_tmp}"
mkdir -p "$OUT" "$TMP"

if [[ "$CHRS_ARG" == "1-22" ]]; then
  CHRS=($(seq 1 22))
else
  CHRS=($CHRS_ARG)
fi

export CONDA_PKGS_DIRS=/home/wangy/miniconda3/pkgs

rewrite_ids() {
  local prefix="$1"
  python3 - "$prefix" << 'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1] + ".bim")
rows = []
for line in p.read_text().splitlines():
    f = line.split("\t") if "\t" in line else line.split()
    # chr:pos:REF:ALT ；plink2 读 VCF 后 A2≈REF, A1≈ALT
    chrom, _iid, cm, pos, a1, a2 = f[0], f[1], f[2], f[3], f[4], f[5]
    if not chrom.startswith("chr"):
        chrom = "chr" + chrom
        f[0] = chrom
    f[1] = f"{chrom}:{pos}:{a2}:{a1}"
    rows.append("\t".join(f))
p.write_text("\n".join(rows) + "\n")
print(f"[panel] rewrote IDs {p} n={len(rows)}")
PY
}

echo "[panel] chromosomes: ${CHRS[*]}"
echo "[panel] TMP=$TMP"
echo "[panel] OUT=$OUT"
prune_list=()
for c in "${CHRS[@]}"; do
  vcf="$PANEL_VCF_DIR/1kGP_high_coverage_Illumina.chr${c}.filtered.SNV_INDEL_SV_phased_panel.vcf.gz"
  if [[ ! -f "$vcf" ]]; then
    echo "[panel] missing $vcf" >&2
    exit 1
  fi
  if [[ -f "$TMP/chr${c}.pruned.bed" && -f "$TMP/chr${c}.pruned.bim" ]]; then
    echo "[panel] chr${c}: resume, reuse existing pruned bed  $(date -Is)"
    prune_list+=("$TMP/chr${c}.pruned")
    continue
  fi
  echo "[panel] chr${c}: SNP + MAF>0.05 + LD prune  $(date -Is)"
  conda run --no-capture-output -n popgen_analysis \
    plink2 --vcf "$vcf" \
      --snps-only just-acgt --max-alleles 2 --maf 0.05 \
      --output-chr chrM \
      --make-bed --out "$TMP/chr${c}"
  rewrite_ids "$TMP/chr${c}"
  conda run --no-capture-output -n popgen_analysis bash -c "
    set -e
    plink2 --bfile '$TMP/chr${c}' --indep-pairwise 200 25 0.2 --out '$TMP/chr${c}'
    plink2 --bfile '$TMP/chr${c}' --extract '$TMP/chr${c}.prune.in' \
      --make-bed --out '$TMP/chr${c}.pruned'
  "
  rewrite_ids "$TMP/chr${c}.pruned"
  rm -f "$TMP/chr${c}.bed" "$TMP/chr${c}.bim" "$TMP/chr${c}.fam" \
        "$TMP/chr${c}.log" "$TMP/chr${c}.nosex" "$TMP/chr${c}.hh"
  n_pruned=$(wc -l < "$TMP/chr${c}.pruned.bim")
  echo "[panel] chr${c} pruned SNPs=$n_pruned  $(date -Is)"
  prune_list+=("$TMP/chr${c}.pruned")
done

echo "[panel] merge ${#prune_list[@]} chromosomes  $(date -Is)"
if [[ ${#prune_list[@]} -eq 1 ]]; then
  conda run --no-capture-output -n popgen_analysis \
    plink2 --bfile "${prune_list[0]}" --make-bed --out "$OUT/ref_1000g_pruned"
else
  printf '%s\n' "${prune_list[@]:1}" > "$TMP/merge.list"
  conda run --no-capture-output -n popgen_analysis \
    plink --bfile "${prune_list[0]}" --merge-list "$TMP/merge.list" \
      --allow-extra-chr --make-bed --out "$OUT/ref_1000g_pruned"
  conda run --no-capture-output -n popgen_analysis \
    plink2 --bfile "$OUT/ref_1000g_pruned" --output-chr chrM --make-bed \
      --out "$OUT/ref_1000g_pruned.chr"
  mv "$OUT/ref_1000g_pruned.chr.bed" "$OUT/ref_1000g_pruned.bed"
  mv "$OUT/ref_1000g_pruned.chr.bim" "$OUT/ref_1000g_pruned.bim"
  mv "$OUT/ref_1000g_pruned.chr.fam" "$OUT/ref_1000g_pruned.fam"
fi
rewrite_ids "$OUT/ref_1000g_pruned"

echo "[panel] write superpop .pop (FAM 顺序)"
python3 - << PY
from pathlib import Path
from collections import Counter
fam = Path("$OUT/ref_1000g_pruned.fam")
info = Path("$SAMPLES_INFO")
out_pop = Path("$OUT/ref_1000g_pruned.pop")
out_map = Path("$OUT/sample_superpop.tsv")
sub_to_super = {
    "YRI":"AFR","LWK":"AFR","GWD":"AFR","MSL":"AFR","ESN":"AFR","ASW":"AFR","ACB":"AFR",
    "CEU":"EUR","TSI":"EUR","FIN":"EUR","GBR":"EUR","IBS":"EUR",
    "CHB":"EAS","JPT":"EAS","CHS":"EAS","CDX":"EAS","KHV":"EAS",
    "GIH":"SAS","PJL":"SAS","BEB":"SAS","STU":"SAS","ITU":"SAS",
    "MXL":"AMR","PUR":"AMR","CLM":"AMR","PEL":"AMR",
}
iid_to_sub = {}
for line in info.read_text().splitlines():
    if not line.strip():
        continue
    parts = line.split()
    iid_to_sub[parts[0]] = parts[1]
pops, rows = [], []
missing = 0
for line in fam.read_text().splitlines():
    iid = line.split()[1]
    sub = iid_to_sub.get(iid)
    superpop = sub_to_super.get(sub, "-")
    if superpop == "-":
        missing += 1
    pops.append(superpop)
    rows.append(f"{iid}\t{sub or 'NA'}\t{superpop}")
out_pop.write_text("\n".join(pops) + "\n")
out_map.write_text("IID\tSUBPOP\tSUPERPOP\n" + "\n".join(rows) + "\n")
n_fam = sum(1 for _ in fam.open())
n_bim = sum(1 for _ in open("$OUT/ref_1000g_pruned.bim"))
print(f"[panel] fam={n_fam} snps={n_bim} pop_missing={missing}")
print("[panel] superpop", dict(Counter(pops)))
if n_fam != 3202:
    raise SystemExit(f"expected 3202 samples, got {n_fam}")
if missing:
    raise SystemExit(f"unmapped samples: {missing}")
if not (30000 <= n_bim <= 400000):
    print(f"[panel] WARNING: SNP count {n_bim} outside expected 30k-400k")
PY

echo "[panel] done: $OUT/ref_1000g_pruned.{bed,bim,fam,pop}  $(date -Is)"
ls -lh "$OUT"/ref_1000g_pruned.*
