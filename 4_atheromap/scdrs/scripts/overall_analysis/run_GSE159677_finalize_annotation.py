#!/usr/bin/env python3
"""
Finalize GSE159677 high-level annotation from the edited review CSV.

Before running:
1. Open GSE159677_annotation_review_table.csv
2. Fill final_high_level_celltype_10 for every harmony_leiden cluster
3. Save the CSV
"""

from __future__ import annotations

from pathlib import Path
import os

import pandas as pd
import scanpy as sc
from matplotlib import pyplot as plt


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"
PLOT_DIR.mkdir(parents=True, exist_ok=True)

INPUT_H5AD = MERGED_DIR / "GSE159677_harmony_highlevel_auto_annotated.h5ad"
REVIEW_CSV = MERGED_DIR / "GSE159677_annotation_review_table.csv"

OUTPUT_H5AD = MERGED_DIR / "GSE159677_harmony_highlevel_annotated_final.h5ad"
OUTPUT_COUNTS_CSV = MERGED_DIR / "GSE159677_final_high_level_celltype_counts.csv"
OUTPUT_MAP_CSV = MERGED_DIR / "GSE159677_harmony_cluster_to_final_highlevel_mapping.csv"
OUTPUT_PNG = PLOT_DIR / "GSE159677_final_high_level_celltypes_panelD.png"

USE_SUGGESTED_IF_FINAL_EMPTY = False

CELLTYPE_ORDER = [
    "B-cell",
    "Dendritic-cell",
    "Endothelial",
    "FB",
    "Macrophage",
    "Mast-cell",
    "NK-cell",
    "Plasma-cell",
    "T-cell",
    "VSMC",
    "Unknown",
]

CELLTYPE_COLORS = [
    "#8B5A46",  # B-cell
    "#8E6BBE",  # Dendritic-cell
    "#4DAA57",  # Endothelial
    "#CF78B8",  # FB
    "#F28E2B",  # Macrophage
    "#D43F3A",  # Mast-cell
    "#A7D989",  # NK-cell
    "#CBB6E5",  # Plasma-cell
    "#3D7DBB",  # T-cell
    "#B9CCE8",  # VSMC
    "#9E9E9E",  # Unknown
]


def sanitize_obs_for_h5ad(adata):
    for col in adata.obs.columns:
        s = adata.obs[col]
        if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            adata.obs[col] = s.where(s.notna(), "").astype(str)
    return adata


def main():
    adata = sc.read_h5ad(INPUT_H5AD)
    review_df = pd.read_csv(REVIEW_CSV, dtype=str)

    required_cols = {"harmony_leiden", "suggested_label", "final_high_level_celltype_10"}
    missing = required_cols - set(review_df.columns)
    if missing:
        raise ValueError(f"Review CSV missing required columns: {sorted(missing)}")

    review_df["harmony_leiden"] = review_df["harmony_leiden"].astype(str)
    review_df["final_high_level_celltype_10"] = review_df["final_high_level_celltype_10"].fillna("").astype(str).str.strip()

    if USE_SUGGESTED_IF_FINAL_EMPTY:
        mask = review_df["final_high_level_celltype_10"] == ""
        review_df.loc[mask, "final_high_level_celltype_10"] = review_df.loc[mask, "suggested_label"].astype(str)

    if (review_df["final_high_level_celltype_10"] == "").any():
        missing_clusters = review_df.loc[
            review_df["final_high_level_celltype_10"] == "", "harmony_leiden"
        ].tolist()
        raise ValueError(
            "Please fill final_high_level_celltype_10 for all clusters before finalizing. "
            f"Missing clusters: {missing_clusters}"
        )

    invalid = sorted(set(review_df["final_high_level_celltype_10"]) - set(CELLTYPE_ORDER))
    if invalid:
        raise ValueError(f"Invalid final labels in review CSV: {invalid}")

    cluster_to_highlevel = dict(
        zip(review_df["harmony_leiden"].astype(str), review_df["final_high_level_celltype_10"].astype(str))
    )

    adata.obs["harmony_leiden"] = adata.obs["harmony_leiden"].astype(str)
    unmapped = sorted(set(adata.obs["harmony_leiden"]) - set(cluster_to_highlevel.keys()), key=lambda x: int(x))
    if unmapped:
        raise ValueError(f"These harmony_leiden clusters are missing from the review CSV: {unmapped}")

    adata.obs["final_high_level_celltype_10"] = adata.obs["harmony_leiden"].map(cluster_to_highlevel)
    present_order = [x for x in CELLTYPE_ORDER if x in set(adata.obs["final_high_level_celltype_10"])]
    present_colors = [CELLTYPE_COLORS[CELLTYPE_ORDER.index(x)] for x in present_order]

    adata.obs["final_high_level_celltype_10"] = pd.Categorical(
        adata.obs["final_high_level_celltype_10"],
        categories=present_order,
        ordered=True,
    )
    adata.uns["final_high_level_celltype_10_colors"] = present_colors

    counts = (
        adata.obs["final_high_level_celltype_10"]
        .value_counts(dropna=False)
        .reindex(present_order, fill_value=0)
        .rename_axis("final_high_level_celltype_10")
        .reset_index(name="n_cells")
    )
    counts.to_csv(OUTPUT_COUNTS_CSV, index=False)

    mapping_df = review_df.copy()
    mapping_df = mapping_df.sort_values("harmony_leiden", key=lambda s: s.astype(int))
    mapping_df.to_csv(OUTPUT_MAP_CSV, index=False)

    fig = sc.pl.umap(
        adata,
        color="final_high_level_celltype_10",
        size=6,
        frameon=False,
        legend_loc="right margin",
        title="High level cell types",
        show=False,
        return_fig=True,
    )
    fig.savefig(OUTPUT_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)

    sanitize_obs_for_h5ad(adata)
    adata.write_h5ad(OUTPUT_H5AD, compression="gzip")

    print("saved:", OUTPUT_H5AD)
    print("saved:", OUTPUT_COUNTS_CSV)
    print("saved:", OUTPUT_MAP_CSV)
    print("saved:", OUTPUT_PNG)


if __name__ == "__main__":
    main()
