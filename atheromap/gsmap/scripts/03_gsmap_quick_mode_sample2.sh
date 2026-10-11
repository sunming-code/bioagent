#!/usr/bin/env bash
set -euo pipefail

: "${ATHEROMAP_GSMAP_WORK_DIR:?Set an explicit gsMap workspace}"
PROJECT_DIR="$ATHEROMAP_GSMAP_WORK_DIR"

SAMPLE_NAME="GSE241346_sample2"
TRAIT_NAME="GCST007435"

H5AD_FILE="${PROJECT_DIR}/data/spatial/GSE241346/h5ad/GSE241346_sample2_gsmap_spagcn.h5ad"
SUMSTATS_FILE="${PROJECT_DIR}/data/gwas/GCST007435_gsmap.sumstats.gz"
GSMAP_RESOURCE_DIR="${PROJECT_DIR}/resources/gsMap_resource"

WORKDIR="${PROJECT_DIR}/results/gsmap_quick_mode/GSE241346"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/03_gsmap_quick_mode_${SAMPLE_NAME}_${TRAIT_NAME}.log"

MAX_PROCESSES=10

mkdir -p "${WORKDIR}" "${LOG_DIR}"

echo "[INFO] PROJECT_DIR: ${PROJECT_DIR}"
echo "[INFO] SAMPLE_NAME: ${SAMPLE_NAME}"
echo "[INFO] TRAIT_NAME: ${TRAIT_NAME}"
echo "[INFO] H5AD_FILE: ${H5AD_FILE}"
echo "[INFO] SUMSTATS_FILE: ${SUMSTATS_FILE}"
echo "[INFO] GSMAP_RESOURCE_DIR: ${GSMAP_RESOURCE_DIR}"
echo "[INFO] WORKDIR: ${WORKDIR}"
echo "[INFO] LOG_FILE: ${LOG_FILE}"

if [ ! -f "${H5AD_FILE}" ]; then
    echo "ERROR: h5ad file not found: ${H5AD_FILE}"
    exit 1
fi

if [ ! -f "${SUMSTATS_FILE}" ]; then
    echo "ERROR: GWAS sumstats file not found: ${SUMSTATS_FILE}"
    exit 1
fi

if [ ! -d "${GSMAP_RESOURCE_DIR}" ]; then
    echo "ERROR: gsMap resource dir not found: ${GSMAP_RESOURCE_DIR}"
    exit 1
fi

for required_path in \
    "${GSMAP_RESOURCE_DIR}/quick_mode/snp_gene_weight_matrix.h5ad" \
    "${GSMAP_RESOURCE_DIR}/quick_mode/baseline" \
    "${GSMAP_RESOURCE_DIR}/quick_mode/SNP_gene_pair" \
    "${GSMAP_RESOURCE_DIR}/LDSC_resource/weights_hm3_no_hla" \
    "${GSMAP_RESOURCE_DIR}/LD_Reference_Panel/1000G_EUR_Phase3_plink" \
    "${GSMAP_RESOURCE_DIR}/genome_annotation/gtf/gencode.v46lift37.basic.annotation.gtf"
do
    if [ ! -e "${required_path}" ]; then
        echo "ERROR: required gsMap resource missing: ${required_path}"
        exit 1
    fi
done

echo "[INFO] Checking h5ad structure"

python - "$H5AD_FILE" <<'PY'
import sys
import scanpy as sc

h5ad = sys.argv[1]
adata = sc.read_h5ad(h5ad)

print("[CHECK] shape:", adata.shape)
print("[CHECK] layers:", list(adata.layers.keys()))
print("[CHECK] obsm:", list(adata.obsm.keys()))
print("[CHECK] annotation counts:")
print(adata.obs["annotation"].value_counts().sort_index())

assert "count" in adata.layers
assert "spatial" in adata.obsm
assert "annotation" in adata.obs.columns
assert adata.obs["annotation"].isna().sum() == 0
assert adata.var_names.is_unique
PY

echo "[INFO] Running gsMap quick_mode"

gsmap quick_mode \
    --workdir "${WORKDIR}" \
    --sample_name "${SAMPLE_NAME}" \
    --gsMap_resource_dir "${GSMAP_RESOURCE_DIR}" \
    --hdf5_path "${H5AD_FILE}" \
    --annotation "annotation" \
    --data_layer "count" \
    --sumstats_file "${SUMSTATS_FILE}" \
    --trait_name "${TRAIT_NAME}" \
    --max_processes "${MAX_PROCESSES}" \
    2>&1 | tee "${LOG_FILE}"

REPORT_FILE="${WORKDIR}/${SAMPLE_NAME}/report/${TRAIT_NAME}/${SAMPLE_NAME}_${TRAIT_NAME}_gsMap_Report.html"
LDSC_FILE="${WORKDIR}/${SAMPLE_NAME}/spatial_ldsc/${SAMPLE_NAME}_${TRAIT_NAME}.csv.gz"
CAUCHY_FILE="${WORKDIR}/${SAMPLE_NAME}/cauchy_combination/${SAMPLE_NAME}_${TRAIT_NAME}.Cauchy.csv.gz"

echo "[INFO] Checking expected outputs"

for output_file in \
    "${WORKDIR}/${SAMPLE_NAME}/find_latent_representations/${SAMPLE_NAME}_add_latent.h5ad" \
    "${WORKDIR}/${SAMPLE_NAME}/latent_to_gene/${SAMPLE_NAME}_gene_marker_score.feather" \
    "${LDSC_FILE}" \
    "${CAUCHY_FILE}" \
    "${REPORT_FILE}"
do
    if [ ! -e "${output_file}" ]; then
        echo "ERROR: expected output missing: ${output_file}"
        exit 1
    fi
    echo "[OK] ${output_file}"
done

echo "[INFO] gsMap quick_mode finished successfully."
echo "[INFO] Report: ${REPORT_FILE}"
echo "[INFO] Spatial LDSC result: ${LDSC_FILE}"
echo "[INFO] Cauchy result: ${CAUCHY_FILE}"
