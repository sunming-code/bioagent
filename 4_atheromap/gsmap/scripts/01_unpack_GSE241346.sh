#!/usr/bin/env bash
set -euo pipefail

: "${ATHEROMAP_GSMAP_WORK_DIR:?Set an explicit gsMap workspace}"
PROJECT_DIR="$ATHEROMAP_GSMAP_WORK_DIR"
TAR_FILE="${PROJECT_DIR}/data/spatial/GSE241346_RAW.tar"
OUT_DIR="${PROJECT_DIR}/data/spatial/GSE241346/raw"

mkdir -p "${OUT_DIR}"

if [ ! -f "${TAR_FILE}" ]; then
    echo "ERROR: cannot find ${TAR_FILE}"
    exit 1
fi

echo "[INFO] Extracting ${TAR_FILE}"
tar -xf "${TAR_FILE}" -C "${OUT_DIR}"

echo "[INFO] Extracted files:"
find "${OUT_DIR}" -maxdepth 3 -type f | sort
