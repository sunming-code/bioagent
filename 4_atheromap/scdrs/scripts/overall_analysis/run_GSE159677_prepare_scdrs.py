#!/usr/bin/env python3
"""
Prepare final annotated GSE159677 object for scDRS.

Outputs:
  - merged/GSE159677_for_scdrs_rawcount.h5ad
  - metadata/GSE159677_scdrs_covariates.tsv
  - metadata/GSE159677_duplicate_gene_symbols.tsv
"""

from __future__ import annotations

from pathlib import Path
import os

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
from scipy import sparse


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
META_DIR = WORK_DIR / "metadata"
for p in [MERGED_DIR, META_DIR]:
    p.mkdir(parents=True, exist_ok=True)

INPUT_H5AD = MERGED_DIR / "GSE159677_harmony_highlevel_annotated_final.h5ad"
OUT_H5AD = MERGED_DIR / "GSE159677_for_scdrs_rawcount.h5ad"
OUT_COV = META_DIR / "GSE159677_scdrs_covariates.tsv"
OUT_DUP = META_DIR / "GSE159677_duplicate_gene_symbols.tsv"


def sanitize_obs_for_h5ad(adata):
    for col in adata.obs.columns:
        s = adata.obs[col]
        if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            adata.obs[col] = s.where(s.notna(), "").astype(str)
    return adata


def collapse_to_gene_symbols(adata: ad.AnnData, gene_col: str = "gene_name") -> ad.AnnData:
    if gene_col not in adata.var.columns:
        raise KeyError(f"adata.var['{gene_col}'] is required")
    if "raw_counts" not in adata.layers:
        raise KeyError("adata.layers['raw_counts'] is required")

    raw_counts = adata.layers["raw_counts"]
    if not sparse.issparse(raw_counts):
        raw_counts = sparse.csr_matrix(np.asarray(raw_counts))
    else:
        raw_counts = raw_counts.tocsr()

    gene_symbols = adata.var[gene_col].astype(str).replace({"": np.nan, "nan": np.nan, "None": np.nan})
    gene_symbols = gene_symbols.fillna(pd.Series(adata.var_names.astype(str), index=gene_symbols.index)).astype(str)

    dup_report = gene_symbols.value_counts().rename_axis("gene_symbol").reset_index(name="n_features")
    dup_report = dup_report[dup_report["n_features"] > 1].sort_values(["n_features", "gene_symbol"], ascending=[False, True])
    dup_report.to_csv(OUT_DUP, sep="\t", index=False)

    uniq_symbols, inverse = np.unique(gene_symbols.to_numpy(), return_inverse=True)
    gene_to_symbol = sparse.csr_matrix(
        (np.ones(len(inverse), dtype=np.float64), (np.arange(len(inverse)), inverse)),
        shape=(len(inverse), len(uniq_symbols)),
    )
    collapsed = raw_counts @ gene_to_symbol
    collapsed = collapsed.tocsr()

    new_var = pd.DataFrame(index=pd.Index(uniq_symbols, name="gene_name"))
    new_var["gene_name"] = uniq_symbols

    adata_out = ad.AnnData(X=collapsed, obs=adata.obs.copy(), var=new_var, dtype="float64")
    adata_out.var_names = adata_out.var["gene_name"].astype(str)
    adata_out.var_names_make_unique()
    adata_out.layers["raw_counts"] = collapsed.copy()

    for key in ["X_harmony", "X_umap"]:
        if key in adata.obsm:
            adata_out.obsm[key] = adata.obsm[key].copy()

    keep_obs = [
        "patient",
        "condition",
        "sample_id",
        "n_counts",
        "n_genes",
        "mt_frac",
        "ribo_frac",
        "harmony_leiden",
        "final_high_level_celltype_10",
    ]
    keep_obs = [x for x in keep_obs if x in adata_out.obs.columns]
    adata_out.obs = adata_out.obs[keep_obs].copy()
    return adata_out


def main():
    adata = sc.read_h5ad(INPUT_H5AD)
    if "final_high_level_celltype_10" not in adata.obs:
        raise KeyError("Please finalize annotation first: final_high_level_celltype_10 not found")
    if "X_harmony" not in adata.obsm:
        raise KeyError("Expected adata.obsm['X_harmony']")

    adata_scdrs = collapse_to_gene_symbols(adata, gene_col="gene_name")
    adata_scdrs.X = adata_scdrs.layers["raw_counts"].copy()

    sc.pp.neighbors(
        adata_scdrs,
        use_rep="X_harmony",
        n_neighbors=15,
        metric="cosine",
    )

    cov_df = pd.DataFrame(index=adata_scdrs.obs_names)
    cov_df["const"] = 1.0
    cov_df["log_n_counts"] = np.log1p(adata_scdrs.obs["n_counts"].astype(float))
    cov_df["mt_frac"] = adata_scdrs.obs["mt_frac"].astype(float)
    cov_df.to_csv(OUT_COV, sep="\t")

    sanitize_obs_for_h5ad(adata_scdrs)
    adata_scdrs.write_h5ad(OUT_H5AD, compression="gzip")

    print("saved:", OUT_H5AD)
    print("saved:", OUT_COV)
    print("saved:", OUT_DUP)
    print("shape:", adata_scdrs.shape)


if __name__ == "__main__":
    main()
