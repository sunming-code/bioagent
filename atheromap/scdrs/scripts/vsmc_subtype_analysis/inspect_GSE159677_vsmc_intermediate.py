#!/usr/bin/env python3
"""
Review Intermediate VSMC clusters from the formal VSMC subtyping result.

Outputs:
  - merged/GSE159677_vsmc_intermediate_review_<trait>.csv
  - merged/GSE159677_vsmc_intermediate_top_markers_<trait>.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

import numpy as np
import pandas as pd
import scanpy as sc


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--input-h5ad",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_vsmc_subtyped_<trait>.h5ad",
    )
    parser.add_argument("--top-n", type=int, default=15)
    return parser.parse_args()


def pick_trait_col(adata: sc.AnnData, trait: str) -> str:
    candidates = [
        f"{trait}_norm_score",
        "z_score_norm_score",
        "norm_score",
        "zscore",
        "score",
    ]
    for col in candidates:
        if col in adata.obs.columns:
            return col
    raise KeyError(f"Could not find scDRS score column. Available obs columns: {adata.obs.columns.tolist()}")


def pick_score_cols(adata: sc.AnnData) -> list[str]:
    required = ["score_Contractile", "score_Fibromyocyte", "score_Modulated"]
    missing = [c for c in required if c not in adata.obs.columns]
    if missing:
        raise KeyError(f"Missing expected primary score columns: {missing}")
    return required


def to_gene_symbol_df(adata: sc.AnnData, df: pd.DataFrame) -> pd.DataFrame:
    if "gene_name" not in adata.var.columns:
        df["gene_symbol"] = df["names"].astype(str)
        return df

    gene_map = adata.var["gene_name"].astype(str).replace({"nan": np.nan, "None": np.nan, "": np.nan})
    gene_map.index = adata.var_names.astype(str)
    df["gene_symbol"] = df["names"].astype(str).map(gene_map).fillna(df["names"].astype(str))
    return df


def main():
    args = parse_args()
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_vsmc_subtyped_{args.trait}.h5ad")

    adata = sc.read_h5ad(input_h5ad)
    trait_col = pick_trait_col(adata, args.trait)
    score_cols = pick_score_cols(adata)

    if "vsmc_subtype" not in adata.obs.columns or "vsmc_leiden" not in adata.obs.columns:
        raise KeyError("Expected columns 'vsmc_subtype' and 'vsmc_leiden' were not found in adata.obs")

    subtypes = adata.obs["vsmc_subtype"].astype(str)
    clusters = adata.obs["vsmc_leiden"].astype(str)

    intermediate_clusters = sorted(clusters[subtypes == "Intermediate"].unique(), key=int)
    if not intermediate_clusters:
        print("No Intermediate clusters found.")
        return

    review_rows = []
    marker_rows = []

    for cluster in intermediate_clusters:
        mask = clusters == cluster
        sub = adata[mask].copy()

        score_means = adata.obs.loc[mask, score_cols].mean()
        score_ranks = score_means.sort_values(ascending=False)
        nearest_label = score_ranks.index[0].replace("score_", "")
        second_label = score_ranks.index[1].replace("score_", "")
        margin = float(score_ranks.iloc[0] - score_ranks.iloc[1])

        review_rows.append(
            {
                "vsmc_leiden": cluster,
                "n_cells": int(mask.sum()),
                "suggested_label": nearest_label,
                "second_best_label": second_label,
                "score_margin": round(margin, 4),
                "mean_score_Contractile": round(float(score_means["score_Contractile"]), 4),
                "mean_score_Fibromyocyte": round(float(score_means["score_Fibromyocyte"]), 4),
                "mean_score_Modulated": round(float(score_means["score_Modulated"]), 4),
                "scdrs_mean": round(float(adata.obs.loc[mask, trait_col].mean()), 4),
                "scdrs_median": round(float(adata.obs.loc[mask, trait_col].median()), 4),
                "scdrs_frac_gt_1p65": round(float((adata.obs.loc[mask, trait_col] > 1.65).mean()), 4),
            }
        )

        tmp = adata.copy()
        tmp.obs["intermediate_target"] = np.where(clusters == cluster, f"cluster_{cluster}", "other")
        sc.tl.rank_genes_groups(
            tmp,
            groupby="intermediate_target",
            groups=[f"cluster_{cluster}"],
            reference="other",
            method="wilcoxon",
            key_added=f"cluster_{cluster}_wilcoxon",
            use_raw=False,
        )
        dge = sc.get.rank_genes_groups_df(
            tmp,
            group=f"cluster_{cluster}",
            key=f"cluster_{cluster}_wilcoxon",
        )
        dge = to_gene_symbol_df(tmp, dge)
        dge["vsmc_leiden"] = cluster
        dge["rank"] = np.arange(1, len(dge) + 1)
        marker_rows.append(dge.head(args.top_n).copy())

    review_df = pd.DataFrame(review_rows).sort_values("vsmc_leiden", key=lambda s: s.astype(int))
    markers_df = pd.concat(marker_rows, ignore_index=True)

    top_marker_summary = (
        markers_df.groupby("vsmc_leiden")["gene_symbol"]
        .apply(lambda x: ", ".join(x.astype(str).tolist()))
        .rename("top_markers")
        .reset_index()
    )
    review_df = review_df.merge(top_marker_summary, on="vsmc_leiden", how="left")

    out_review = MERGED_DIR / f"GSE159677_vsmc_intermediate_review_{args.trait}.csv"
    out_markers = MERGED_DIR / f"GSE159677_vsmc_intermediate_top_markers_{args.trait}.csv"
    review_df.to_csv(out_review, index=False)
    markers_df.to_csv(out_markers, index=False)

    print("\nIntermediate clusters:")
    print(review_df.to_string(index=False))
    print(f"\nsaved: {out_review}")
    print(f"saved: {out_markers}")


if __name__ == "__main__":
    main()
