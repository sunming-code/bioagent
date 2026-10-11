#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash run_GSE159677_scdrs_cli.sh <trait_name> <gs_file>
#
# Example:
#   bash run_GSE159677_scdrs_cli.sh z_score <scdrs-work-dir>/scdrs_input/trait_gene_sets.gs

# Activate the original scDRS environment before running this script.
command -v scdrs >/dev/null || { echo "scdrs is not on PATH" >&2; exit 1; }

: "${ATHEROMAP_SCDRS_WORK_DIR:?Set an explicit scDRS workspace}"
WORK_DIR="$ATHEROMAP_SCDRS_WORK_DIR"
MERGED_DIR="$WORK_DIR/merged"
META_DIR="$WORK_DIR/metadata"
SCDRS_DIR="$WORK_DIR/scdrs_out"

TRAIT_NAME="${1:-z_score}"
GS_FILE="${2:-$WORK_DIR/scdrs_input/trait_gene_sets.gs}"

H5AD_FILE="$MERGED_DIR/GSE159677_for_scdrs_rawcount.h5ad"
COV_FILE="$META_DIR/GSE159677_scdrs_covariates.tsv"

for input_file in "$H5AD_FILE" "$COV_FILE" "$GS_FILE"; do
  [ -f "$input_file" ] || { echo "Missing input: $input_file" >&2; exit 1; }
done
mkdir -p "$SCDRS_DIR"

echo "Trait: $TRAIT_NAME"
echo "Gene set: $GS_FILE"
echo "H5AD: $H5AD_FILE"
echo "Covariate: $COV_FILE"

# If your local scDRS version expects hsapiens/mmusculus instead of human/mouse,
# replace --h5ad-species and --gs-species below accordingly.
scdrs compute-score \
  --h5ad-file "$H5AD_FILE" \
  --h5ad-species human \
  --cov-file "$COV_FILE" \
  --gs-file "$GS_FILE" \
  --gs-species human \
  --flag-filter-data False \
  --flag-raw-count True \
  --n-ctrl 1000 \
  --flag-return-ctrl-raw-score False \
  --flag-return-ctrl-norm-score True \
  --out-folder "$SCDRS_DIR"

scdrs perform-downstream \
  --h5ad-file "$H5AD_FILE" \
  --score-file "$SCDRS_DIR/${TRAIT_NAME}.full_score.gz" \
  --out-folder "$SCDRS_DIR" \
  --group-analysis final_high_level_celltype_10,patient,condition,harmony_leiden

echo "scDRS finished: $SCDRS_DIR"
