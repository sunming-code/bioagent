#!/usr/bin/env python3
"""
Finalize VSMC subtype labels for GSE159677.

Manual decisions applied:
  - cluster 5 -> Fibromyocyte
  - cluster 6 -> Modulated
  - cluster 7 -> remove (Endothelial-like contamination)
  - cluster 9 -> Modulated

Outputs:
  - merged/GSE159677_vsmc_cluster_manual_relabel_<trait>.csv
  - merged/GSE159677_vsmc_final_counts_before_filter_<trait>.csv
  - merged/GSE159677_vsmc_final_counts_after_filter_<trait>.csv
  - merged/GSE159677_vsmc_subtyped_final_<trait>.h5ad
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

import pandas as pd
import scanpy as sc


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"


MANUAL_CLUSTER_MAP = {
    "5": "Fibromyocyte",
    "6": "Modulated",
    "7": "REMOVE_Endothelial_like",
    "9": "Modulated",
}

MANUAL_NOTES = {
    "5": "ECM/secretory program; closer to Fibromyocyte than Contractile",
    "6": "APOE/lipid-inflammatory switched state; assigned to Modulated",
    "7": "Endothelial-like contamination (PECAM1/VWF/EGFL7); removed from final VSMC object",
    "9": "IFN/MHC/APC-like inflammatory state; assigned to Modulated",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--input-h5ad",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_vsmc_subtyped_<trait>.h5ad",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_vsmc_subtyped_{args.trait}.h5ad")

    adata = sc.read_h5ad(input_h5ad)
    if "vsmc_leiden" not in adata.obs.columns or "vsmc_subtype" not in adata.obs.columns:
        raise KeyError("Expected obs columns 'vsmc_leiden' and 'vsmc_subtype' were not found")

    adata.obs["vsmc_leiden"] = adata.obs["vsmc_leiden"].astype(str)
    adata.obs["vsmc_subtype_raw"] = adata.obs["vsmc_subtype"].astype(str)
    adata.obs["vsmc_subtype_final"] = adata.obs["vsmc_subtype_raw"].copy()
    adata.obs["vsmc_manual_note"] = ""

    for cluster, label in MANUAL_CLUSTER_MAP.items():
        mask = adata.obs["vsmc_leiden"] == cluster
        adata.obs.loc[mask, "vsmc_subtype_final"] = label
        adata.obs.loc[mask, "vsmc_manual_note"] = MANUAL_NOTES[cluster]

    adata.obs["keep_in_final_vsmc"] = adata.obs["vsmc_subtype_final"] != "REMOVE_Endothelial_like"

    relabel_df = (
        adata.obs[["vsmc_leiden", "vsmc_subtype_raw", "vsmc_subtype_final", "vsmc_manual_note"]]
        .drop_duplicates()
        .sort_values(["vsmc_leiden", "vsmc_subtype_final"])
        .reset_index(drop=True)
    )

    counts_before = (
        adata.obs["vsmc_subtype_final"]
        .value_counts()
        .rename_axis("vsmc_subtype_final")
        .reset_index(name="n_cells")
    )

    adata_final = adata[adata.obs["keep_in_final_vsmc"]].copy()
    adata_final.obs["vsmc_subtype_final"] = pd.Categorical(
        adata_final.obs["vsmc_subtype_final"],
        categories=["Contractile", "Fibromyocyte", "Modulated"],
        ordered=True,
    )

    counts_after = (
        adata_final.obs["vsmc_subtype_final"]
        .value_counts()
        .rename_axis("vsmc_subtype_final")
        .reset_index(name="n_cells")
    )

    out_map = MERGED_DIR / f"GSE159677_vsmc_cluster_manual_relabel_{args.trait}.csv"
    out_before = MERGED_DIR / f"GSE159677_vsmc_final_counts_before_filter_{args.trait}.csv"
    out_after = MERGED_DIR / f"GSE159677_vsmc_final_counts_after_filter_{args.trait}.csv"
    out_h5ad = MERGED_DIR / f"GSE159677_vsmc_subtyped_final_{args.trait}.h5ad"

    relabel_df.to_csv(out_map, index=False)
    counts_before.to_csv(out_before, index=False)
    counts_after.to_csv(out_after, index=False)

    for col in adata_final.obs.columns:
        series = adata_final.obs[col]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            adata_final.obs[col] = series.where(series.notna(), "").astype(str)

    adata_final.write_h5ad(out_h5ad, compression="gzip")

    print("\nManual relabel table:")
    print(relabel_df.to_string(index=False))
    print("\nCounts before removing endothelial-like contamination:")
    print(counts_before.to_string(index=False))
    print("\nCounts after removing endothelial-like contamination:")
    print(counts_after.to_string(index=False))
    print(f"\nsaved: {out_map}")
    print(f"saved: {out_before}")
    print(f"saved: {out_after}")
    print(f"saved: {out_h5ad}")


if __name__ == "__main__":
    main()
