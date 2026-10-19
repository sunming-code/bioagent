#!/usr/bin/env python3
"""
Merge scDRS full-score back into the final annotated object and summarize results.

Default expectations:
  - merged/GSE159677_for_scdrs_rawcount.h5ad
  - scdrs_out/<trait>.full_score.gz
  - optionally, perform-downstream outputs:
      scdrs_out/<trait>.scdrs_group.final_high_level_celltype_10
      scdrs_out/<trait>.scdrs_group.patient
      scdrs_out/<trait>.scdrs_group.condition
      scdrs_out/<trait>.scdrs_group.harmony_leiden
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

import numpy as np
import pandas as pd
import scanpy as sc
from matplotlib import pyplot as plt


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"
SCDRS_DIR = WORK_DIR / "scdrs_out"

for p in [MERGED_DIR, PLOT_DIR, SCDRS_DIR]:
    p.mkdir(parents=True, exist_ok=True)


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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", required=True)
    parser.add_argument(
        "--h5ad-file",
        default=str(MERGED_DIR / "GSE159677_for_scdrs_rawcount.h5ad"),
    )
    parser.add_argument(
        "--score-file",
        default=None,
        help="Path to <trait>.full_score.gz. If omitted, use WORK_DIR/scdrs_out/<trait>.full_score.gz",
    )
    return parser.parse_args()


def pick_first(df: pd.DataFrame, candidates: list[str], required: bool = False):
    for col in candidates:
        if col in df.columns:
            return col
    if required:
        raise KeyError(f"None of these columns were found: {candidates}")
    return None


def read_score_file(score_file: Path) -> pd.DataFrame:
    df = pd.read_csv(score_file, sep="\t", compression="infer")
    if "cell" in df.columns:
        df = df.set_index("cell")
    elif df.columns[0].startswith("Unnamed"):
        df = df.set_index(df.columns[0])
    else:
        df = df.set_index(df.columns[0])
    df.index = df.index.astype(str)
    return df


def load_group_result(path: Path):
    if not path.exists():
        return None
    df = pd.read_csv(path, sep="\t", index_col=0)
    df.index = df.index.astype(str)
    return df


def save_assoc_barplot(group_df: pd.DataFrame, out_png: Path, title: str, order=None, colors=None):
    assoc_col = pick_first(group_df, ["assoc_mcz", "assoc_z", "assoc", "assoc_stat"], required=False)
    p_col = pick_first(group_df, ["assoc_mcp", "assoc_p", "assoc_pval"], required=False)
    if assoc_col is None:
        return

    plot_df = group_df.copy()
    plot_df["group_plot"] = plot_df.index.astype(str)
    if order is not None:
        present = [x for x in order if x in plot_df["group_plot"].tolist()]
        if present:
            plot_df = plot_df.set_index("group_plot").loc[present].reset_index()
        else:
            plot_df = plot_df.reset_index().rename(columns={"index": "group_plot"})
    else:
        plot_df = plot_df.reset_index().rename(columns={"index": "group_plot"})

    bar_colors = None
    if colors is not None and order is not None:
        color_map = {k: v for k, v in zip(order, colors)}
        bar_colors = [color_map.get(x, "#888888") for x in plot_df["group_plot"]]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].bar(plot_df["group_plot"], plot_df[assoc_col].astype(float), color=bar_colors)
    axes[0].set_ylabel(assoc_col)
    axes[0].set_title(f"{title}: association")
    axes[0].tick_params(axis="x", rotation=45)

    if p_col is not None:
        axes[1].bar(plot_df["group_plot"], plot_df[p_col].astype(float), color=bar_colors)
        axes[1].set_ylabel(p_col)
        axes[1].set_title(f"{title}: Monte Carlo p")
        axes[1].tick_params(axis="x", rotation=45)
    else:
        axes[1].axis("off")

    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    args = parse_args()
    trait = args.trait
    h5ad_file = Path(args.h5ad_file)
    score_file = Path(args.score_file) if args.score_file else SCDRS_DIR / f"{trait}.full_score.gz"

    adata = sc.read_h5ad(h5ad_file)
    if "final_high_level_celltype_10" not in adata.obs:
        raise KeyError("Expected final_high_level_celltype_10 in adata.obs")
    if "X_umap" not in adata.obsm:
        raise KeyError("Expected X_umap in adata.obsm")

    score_df = read_score_file(score_file)
    common = adata.obs_names.intersection(score_df.index)
    if len(common) == 0:
        raise ValueError("No overlapping cells between h5ad and scDRS full_score file")
    if len(common) != adata.n_obs:
        print(f"Warning: only {len(common)}/{adata.n_obs} cells matched between h5ad and score file")
    adata = adata[common].copy()
    score_df = score_df.loc[common].copy()

    norm_col = pick_first(score_df, ["norm_score", "score", "zscore"], required=True)
    raw_col = pick_first(score_df, ["raw_score"], required=False)
    pval_col = pick_first(score_df, ["mc_pval", "pval"], required=False)

    norm_key = f"{trait}_norm_score"
    raw_key = f"{trait}_raw_score"
    pval_key = f"{trait}_pval"
    high_key = f"{trait}_high_cell"

    adata.obs[norm_key] = score_df[norm_col].astype(float).values
    if raw_col is not None:
        adata.obs[raw_key] = score_df[raw_col].astype(float).values
    if pval_col is not None:
        adata.obs[pval_key] = score_df[pval_col].astype(float).values
        adata.obs[high_key] = adata.obs[pval_key] < 0.05
    else:
        thr = float(np.nanquantile(adata.obs[norm_key], 0.95))
        adata.obs[high_key] = adata.obs[norm_key] >= thr

    merged_h5ad = MERGED_DIR / f"GSE159677_scdrs_{trait}_merged.h5ad"
    adata.write_h5ad(merged_h5ad, compression="gzip")

    celltype_col = "final_high_level_celltype_10"
    present_order = [x for x in CELLTYPE_ORDER if x in adata.obs[celltype_col].astype(str).unique()]
    present_colors = adata.uns.get("final_high_level_celltype_10_colors", None)

    fig = sc.pl.umap(
        adata,
        color=[celltype_col, norm_key],
        ncols=2,
        frameon=False,
        size=6,
        color_map="RdBu_r",
        vmin="p1",
        vmax="p99",
        show=False,
        return_fig=True,
    )
    fig.savefig(PLOT_DIR / f"GSE159677_scdrs_umap_{trait}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    frac_df = (
        adata.obs.groupby(celltype_col, observed=True)[high_key]
        .mean()
        .reindex(present_order)
        .reset_index(name="fraction_high_score")
    )
    frac_df.to_csv(MERGED_DIR / f"GSE159677_scdrs_fraction_high_cells_{trait}.csv", index=False)

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    colors = present_colors if present_colors is not None and len(present_colors) == len(present_order) else None
    ax.bar(frac_df[celltype_col], frac_df["fraction_high_score"], color=colors)
    ax.set_ylabel("Fraction of high-scoring cells")
    ax.set_title(f"{trait}: fraction of high scDRS cells by cell type")
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    fig.savefig(PLOT_DIR / f"GSE159677_scdrs_fraction_high_cells_{trait}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    sc.pl.violin(
        adata,
        keys=[norm_key],
        groupby=celltype_col,
        rotation=45,
        stripplot=True,
        size=1,
        show=False,
        ax=ax,
    )
    ax.set_title(f"{trait}: scDRS score by cell type")
    plt.tight_layout()
    fig.savefig(PLOT_DIR / f"GSE159677_scdrs_violin_by_celltype_{trait}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    group_specs = {
        "final_high_level_celltype_10": PLOT_DIR / f"GSE159677_scdrs_group_assoc_celltype_{trait}.png",
        "patient": PLOT_DIR / f"GSE159677_scdrs_group_assoc_patient_{trait}.png",
        "condition": PLOT_DIR / f"GSE159677_scdrs_group_assoc_condition_{trait}.png",
        "harmony_leiden": PLOT_DIR / f"GSE159677_scdrs_group_assoc_harmony_leiden_{trait}.png",
    }

    for group_col, out_png in group_specs.items():
        group_path = SCDRS_DIR / f"{trait}.scdrs_group.{group_col}"
        group_df = load_group_result(group_path)
        if group_df is None:
            continue
        group_df.to_csv(MERGED_DIR / f"GSE159677_scdrs_group_{group_col}_{trait}.tsv", sep="\t")
        order = present_order if group_col == "final_high_level_celltype_10" else None
        colors = present_colors if group_col == "final_high_level_celltype_10" else None
        save_assoc_barplot(group_df, out_png, title=group_col, order=order, colors=colors)

    print("saved:", merged_h5ad)
    print("saved plots under:", PLOT_DIR)


if __name__ == "__main__":
    main()
