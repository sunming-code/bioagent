#!/usr/bin/env python3
"""
Review Intermediate macrophage clusters from the formal macrophage subtyping result.

Outputs:
  - merged/GSE159677_macrophage_intermediate_review_<trait>.csv
  - merged/GSE159677_macrophage_intermediate_top_markers_<trait>.csv
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

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
        help="Default: merged/GSE159677_macrophage_subtyped_<trait>.h5ad",
    )
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument("--min-cells", type=int, default=5,
                        help="Skip DGE for Intermediate clusters with fewer than this many cells")
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


def pick_score_cols(adata: sc.AnnData) -> tuple[list[str], list[str]]:
    """Return (raw_score_cols, ranking_cols).

    ranking_cols prefers z-normalised columns (score_*_z) when available,
    keeping consistent with assign_subtypes() in run_GSE159677_macrophage_subtype_formal.py.
    Falls back to raw score columns if z columns are absent.
    """
    raw_cols = [
        "score_C1Q",
        "score_HMOX1",
        "score_IL10hi",
        "score_PLIN2_TREM1",
        "score_S100A8hi",
        "score_TREM2hi",
    ]
    missing = [c for c in raw_cols if c not in adata.obs.columns]
    if missing:
        raise KeyError(f"Missing expected primary score columns: {missing}")
    z_cols = [f"{c}_z" for c in raw_cols]
    if all(c in adata.obs.columns for c in z_cols):
        print("  Using z-normalised score columns for ranking (consistent with assign_subtypes).")
        return raw_cols, z_cols
    print("  z-score columns not found; falling back to raw score columns for ranking.")
    return raw_cols, raw_cols


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
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_macrophage_subtyped_{args.trait}.h5ad")

    adata = sc.read_h5ad(input_h5ad)
    trait_col = pick_trait_col(adata, args.trait)
    raw_score_cols, ranking_cols = pick_score_cols(adata)

    if "macrophage_subtype" not in adata.obs.columns or "macrophage_leiden" not in adata.obs.columns:
        raise KeyError("Expected columns 'macrophage_subtype' and 'macrophage_leiden' were not found")

    subtypes = adata.obs["macrophage_subtype"].astype(str)
    clusters = adata.obs["macrophage_leiden"].astype(str)

    # D: keep aux_cols in the same order as REFERENCE_SCORES in run_formal.py
    aux_key_order = [
        "aux_score_IFN_response",
        "aux_score_S100A8_low",
        "aux_score_M1_like",
        "aux_score_M2a_like",
        "aux_score_M2b_like",
        "aux_score_M2c_like",
        "aux_score_M2d_like",
        "aux_score_Classical_monocyte",
        "aux_score_Nonclassical_monocyte",
    ]
    present_aux = set(c for c in adata.obs.columns if c.startswith("aux_score_"))
    aux_cols = [c for c in aux_key_order if c in present_aux] + sorted(
        present_aux - set(aux_key_order)
    )

    # C: robust sort — try numeric, fall back to lexicographic
    def _sort_key(val: str):
        try:
            return (0, int(val), val)
        except ValueError:
            return (1, 0, val)

    intermediate_clusters = sorted(clusters[subtypes == "Intermediate"].unique(), key=_sort_key)
    if not intermediate_clusters:
        print("No Intermediate clusters found.")
        return

    # raw_label_map keys are always raw score col names (used for the mean_* columns)
    raw_label_map = {
        "score_C1Q": "Mac_C1Q",
        "score_HMOX1": "Mac_HMOX1",
        "score_IL10hi": "Mac_IL10hi",
        "score_PLIN2_TREM1": "Mac_PLIN2hi/TREM1hi",
        "score_S100A8hi": "Mac_S100A8hi",
        "score_TREM2hi": "Mac_TREM2hi",
    }
    # ranking_label_map maps ranking_cols -> display names (handles both raw and z variants)
    ranking_label_map = {
        rc: raw_label_map[rc.replace("_z", "")] for rc in ranking_cols
    }

    review_rows = []
    marker_rows = []

    # A: create tmp once outside the loop; only update the obs column inside
    tmp = adata.copy()

    for cluster in intermediate_clusters:
        mask = clusters == cluster
        n_cells = int(mask.sum())
        if n_cells < args.min_cells:
            print(f"  skip cluster {cluster} (n_cells={n_cells} < {args.min_cells}, DGE unreliable)")
            continue

        rank_means = adata.obs.loc[mask, ranking_cols].mean()
        rank_sorted = rank_means.sort_values(ascending=False)
        nearest_label = ranking_label_map[rank_sorted.index[0]]
        second_label = ranking_label_map[rank_sorted.index[1]]
        margin = float(rank_sorted.iloc[0] - rank_sorted.iloc[1])

        raw_means = adata.obs.loc[mask, raw_score_cols].mean()

        row = {
            "macrophage_leiden": cluster,
            "n_cells": n_cells,
            "suggested_label": nearest_label,
            "second_best_label": second_label,
            "score_margin": round(margin, 4),
            "scdrs_mean": round(float(adata.obs.loc[mask, trait_col].mean()), 4),
            "scdrs_median": round(float(adata.obs.loc[mask, trait_col].median()), 4),
            "scdrs_frac_gt_1p65": round(float((adata.obs.loc[mask, trait_col] > 1.65).mean()), 4),
        }
        for raw_col in raw_score_cols:
            row[f"mean_{raw_label_map[raw_col]}"] = round(float(raw_means[raw_col]), 4)
        for aux_col in aux_cols:
            row[aux_col] = round(float(adata.obs.loc[mask, aux_col].mean()), 4)
        review_rows.append(row)

        tmp.obs["intermediate_target"] = np.where(
            clusters == cluster, f"cluster_{cluster}", "other"
        )
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
        dge["macrophage_leiden"] = cluster
        dge["rank"] = np.arange(1, len(dge) + 1)
        marker_rows.append(dge.head(args.top_n).copy())

    if not review_rows:
        print(
            f"All Intermediate clusters were skipped "
            f"(all had fewer than {args.min_cells} cells). No output written."
        )
        return

    review_df = pd.DataFrame(review_rows).sort_values("macrophage_leiden", key=lambda s: s.map(_sort_key))
    markers_df = pd.concat(marker_rows, ignore_index=True)
    top_marker_summary = (
        markers_df.groupby("macrophage_leiden")["gene_symbol"]
        .apply(lambda x: ", ".join(x.astype(str).tolist()))
        .rename("top_markers")
        .reset_index()
    )
    review_df = review_df.merge(top_marker_summary, on="macrophage_leiden", how="left")

    out_review = MERGED_DIR / f"GSE159677_macrophage_intermediate_review_{args.trait}.csv"
    out_markers = MERGED_DIR / f"GSE159677_macrophage_intermediate_top_markers_{args.trait}.csv"
    review_df.to_csv(out_review, index=False)
    markers_df.to_csv(out_markers, index=False)

    print("\nIntermediate clusters:")
    print(review_df.to_string(index=False))
    print(f"\nsaved: {out_review}")
    print(f"saved: {out_markers}")


if __name__ == "__main__":
    main()
