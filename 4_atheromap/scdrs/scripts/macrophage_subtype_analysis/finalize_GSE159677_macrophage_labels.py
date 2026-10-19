#!/usr/bin/env python3
"""
Finalize macrophage subtype labels for GSE159677.

Default behavior:
  - keep all automatic labels from the formal macrophage subtyping step
  - allow optional cluster-level manual relabeling by editing MANUAL_CLUSTER_MAP

Outputs:
  - merged/GSE159677_macrophage_cluster_manual_relabel_<trait>.csv
  - merged/GSE159677_macrophage_final_counts_before_filter_<trait>.csv
  - merged/GSE159677_macrophage_final_counts_after_filter_<trait>.csv
  - merged/GSE159677_macrophage_subtyped_final_<trait>.h5ad
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
import scanpy as sc


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"

# Edit after running inspect_GSE159677_macrophage_intermediate.py
MANUAL_CLUSTER_MAP: dict[str, str] = {
    "7": "REMOVE_DC_contamination",
}

MANUAL_NOTES: dict[str, str] = {
    "7": "FCER1A 46%+, CD1C 22.6%+, CLEC10A+, HLA-II hi — confirmed cDC2 contamination",
}

FINAL_ORDER = [
    "Mac_C1Q",
    "Mac_HMOX1",
    "Mac_IL10hi",
    "Mac_PLIN2hi/TREM1hi",
    "Mac_S100A8hi",
    "Mac_TREM2hi",
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--input-h5ad",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_macrophage_subtyped_<trait>.h5ad",
    )
    return parser.parse_args()


def sanitize_obs_for_h5ad(adata: sc.AnnData):
    for col in adata.obs.columns:
        series = adata.obs[col]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            adata.obs[col] = series.where(series.notna(), "").astype(str)


def main():
    args = parse_args()
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_macrophage_subtyped_{args.trait}.h5ad")

    adata = sc.read_h5ad(input_h5ad)
    if "macrophage_leiden" not in adata.obs.columns or "macrophage_subtype" not in adata.obs.columns:
        raise KeyError("Expected obs columns 'macrophage_leiden' and 'macrophage_subtype' were not found")

    adata.obs["macrophage_leiden"] = adata.obs["macrophage_leiden"].astype(str)
    adata.obs["macrophage_subtype_raw"] = adata.obs["macrophage_subtype"].astype(str)
    adata.obs["macrophage_subtype_final"] = adata.obs["macrophage_subtype_raw"].copy()
    adata.obs["macrophage_manual_note"] = ""

    if not MANUAL_CLUSTER_MAP:
        print("MANUAL_CLUSTER_MAP is empty. Keeping automatic macrophage subtype labels.")

    existing_clusters = set(adata.obs["macrophage_leiden"].astype(str).unique())
    unknown_clusters = set(MANUAL_CLUSTER_MAP.keys()) - existing_clusters
    if unknown_clusters:
        print(
            f"WARNING: the following cluster(s) in MANUAL_CLUSTER_MAP do not exist in "
            f"'macrophage_leiden' and will be ignored: {sorted(unknown_clusters)}\n"
            f"  Available clusters: {sorted(existing_clusters)}"
        )

    for cluster, label in MANUAL_CLUSTER_MAP.items():
        mask = adata.obs["macrophage_leiden"] == cluster
        adata.obs.loc[mask, "macrophage_subtype_final"] = label
        adata.obs.loc[mask, "macrophage_manual_note"] = MANUAL_NOTES.get(cluster, "")

    adata.obs["keep_in_final_macrophage"] = ~adata.obs["macrophage_subtype_final"].astype(str).str.startswith("REMOVE_")

    relabel_df = (
        adata.obs[
            ["macrophage_leiden", "macrophage_subtype_raw", "macrophage_subtype_final", "macrophage_manual_note"]
        ]
        .drop_duplicates()
        .sort_values(["macrophage_leiden", "macrophage_subtype_final"])
        .reset_index(drop=True)
    )

    counts_before = (
        adata.obs["macrophage_subtype_final"]
        .value_counts()
        .rename_axis("macrophage_subtype_final")
        .reset_index(name="n_cells")
    )

    n_removed = (~adata.obs["keep_in_final_macrophage"]).sum()
    if n_removed > 0:
        removed_labels = (
            adata.obs.loc[~adata.obs["keep_in_final_macrophage"], "macrophage_subtype_final"]
            .value_counts()
            .to_dict()
        )
        print(f"Removing {n_removed} cells with REMOVE_* labels: {removed_labels}")

    adata_final = adata[adata.obs["keep_in_final_macrophage"]].copy()
    if adata_final.n_obs == 0:
        raise ValueError(
            "adata_final is empty after filtering REMOVE_* labels. "
            "All clusters appear to have been marked for removal. "
            "Please review MANUAL_CLUSTER_MAP."
        )
    present = [x for x in FINAL_ORDER if x in adata_final.obs["macrophage_subtype_final"].astype(str).unique()]
    extras = [
        x
        for x in sorted(adata_final.obs["macrophage_subtype_final"].astype(str).unique())
        if x not in present
    ]
    adata_final.obs["macrophage_subtype_final"] = pd.Categorical(
        adata_final.obs["macrophage_subtype_final"].astype(str),
        categories=present + extras,
        ordered=True,
    )

    counts_after = (
        adata_final.obs["macrophage_subtype_final"]
        .value_counts()
        .rename_axis("macrophage_subtype_final")
        .reset_index(name="n_cells")
    )

    out_map = MERGED_DIR / f"GSE159677_macrophage_cluster_manual_relabel_{args.trait}.csv"
    out_before = MERGED_DIR / f"GSE159677_macrophage_final_counts_before_filter_{args.trait}.csv"
    out_after = MERGED_DIR / f"GSE159677_macrophage_final_counts_after_filter_{args.trait}.csv"
    out_h5ad = MERGED_DIR / f"GSE159677_macrophage_subtyped_final_{args.trait}.h5ad"

    relabel_df.to_csv(out_map, index=False)
    counts_before.to_csv(out_before, index=False)
    counts_after.to_csv(out_after, index=False)
    sanitize_obs_for_h5ad(adata_final)
    adata_final.write_h5ad(out_h5ad, compression="gzip")

    print("\nManual relabel table:")
    print(relabel_df.to_string(index=False))
    print("\nCounts before filtering:")
    print(counts_before.to_string(index=False))
    print("\nCounts after filtering:")
    print(counts_after.to_string(index=False))
    print(f"\nsaved: {out_map}")
    print(f"saved: {out_before}")
    print(f"saved: {out_after}")
    print(f"saved: {out_h5ad}")


if __name__ == "__main__":
    main()
