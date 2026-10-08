#!/usr/bin/env bash
# A2: 1000G 留一自测（PCA + 监督 ADMIXTURE vs 已知超群）
# 硬指标 4 人：YRI/CEU/CHB/ITU。AMR 不做硬门槛。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PANEL="${1:-$ROOT/data/reference/panel_1000g/ref_1000g_pruned}"
OUT="$ROOT/results/loo"
WORK="${LOO_TMP:-/scratch/wangy/RBM_popgen/loo}"
mkdir -p "$OUT" "$WORK"

# IID  label  superpop
SAMPLES=(
  "NA18486 YRI AFR"
  "NA06985 CEU EUR"
  "NA18526 CHB EAS"
  "HG03713 ITU SAS"
)

export CONDA_PKGS_DIRS=/home/wangy/miniconda3/pkgs
SUMMARY="$OUT/summary.tsv"
echo -e "IID\tSUBPOP\tTRUE\tPCA\tADMIXTURE\tQmax\tPASS" > "$SUMMARY"

for row in "${SAMPLES[@]}"; do
  set -- $row
  IID=$1; SUB=$2; TRUE=$3
  echo "======== LOO $IID $SUB $TRUE $(date -Is) ========"
  w="$WORK/$IID"
  rm -rf "$w"
  mkdir -p "$w" "$OUT/$IID"
  printf '0\t%s\n' "$IID" > "$w/keep.txt"

  conda run --no-capture-output -n popgen_analysis bash -c "
    set -e
    plink2 --bfile '$PANEL' --keep '$w/keep.txt' --output-chr chrM \
      --export vcf --out '$w/patient'
    plink2 --bfile '$PANEL' --remove '$w/keep.txt' --output-chr chrM \
      --make-bed --out '$w/panel_loo'
  "
  python3 - "$PANEL" "$IID" "$w/panel_loo" << 'PY'
from pathlib import Path
import sys
panel, iid, out = sys.argv[1], sys.argv[2], sys.argv[3]
fams = Path(panel + ".fam").read_text().splitlines()
pops = Path(panel + ".pop").read_text().splitlines()
keep_pop = [p for f, p in zip(fams, pops) if f.split()[1] != iid]
Path(out + ".pop").write_text("\n".join(keep_pop) + "\n")
src_map = Path(panel).parent / "sample_superpop.tsv"
if src_map.exists():
    rows = [src_map.read_text().splitlines()[0]]
    rows.extend(ln for ln in src_map.read_text().splitlines()[1:] if ln.split("\t")[0] != iid)
    Path(out).parent.joinpath("sample_superpop.tsv").write_text("\n".join(rows) + "\n")
print(f"[loo] panel_loo n={len(keep_pop)} dropped={iid}")
PY

  conda run --no-capture-output -n popgen_analysis \
    python "$ROOT/steps/02_analysis/popgen_agent.py" \
      --vcf "$w/patient.vcf" \
      --outdir "$OUT/$IID" \
      --panel-prefix "$w/panel_loo" \
      --skip-cv --skip-af
  if [[ ! -f "$OUT/$IID/partial_evidence.json" ]]; then
    echo "[loo] FAIL: no JSON for $IID" >&2
    exit 1
  fi

  python3 - "$OUT/$IID/partial_evidence.json" "$IID" "$SUB" "$TRUE" "$SUMMARY" << 'PY'
import json, sys
from pathlib import Path
js, iid, sub, true, summary = sys.argv[1:]
d = json.loads(Path(js).read_text())
pca = d["findings"]["pca"]["nearest_superpop"]
adm = d["findings"]["admixture"]["dominant"]
comps = d["findings"]["admixture_dominant"]
qmax = max(comps.values()) if comps else 0
passed = pca == true and adm == true and qmax >= 0.8
line = f"{iid}\t{sub}\t{true}\t{pca}\t{adm}\t{qmax:.4f}\t{int(passed)}"
Path(summary).write_text(Path(summary).read_text() + line + "\n")
print("[loo]", line, "PASS" if passed else "FAIL")
PY
done

echo "======== LOO done $(date -Is) ========"
cat "$SUMMARY"
