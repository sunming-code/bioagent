#!/usr/bin/env python3
"""
Violin plot of scDRS norm_score across all high-level cell types,
with one-vs-rest statistical tests and pairwise significance bars
for the top enriched cell types.

Inputs:
  - merged/GSE159677_scdrs_z_score_merged.h5ad

Outputs:
  - plots/GSE159677_scdrs_celltype_violin_stats_<trait>.png
  - merged/GSE159677_scdrs_celltype_one_vs_rest_<trait>.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

import numpy as np
import pandas as pd
import scanpy as sc
import seaborn as sns
from matplotlib import pyplot as plt
from scipy.stats import kruskal, mannwhitneyu


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"

PLOT_DIR.mkdir(parents=True, exist_ok=True)

sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, dpi_save=200, frameon=False)

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

CELLTYPE_COLORS = {
    "B-cell": "#8B5A46",
    "Dendritic-cell": "#8E6BBE",
    "Endothelial": "#4DAA57",
    "FB": "#CF78B8",
    "Macrophage": "#F28E2B",
    "Mast-cell": "#D43F3A",
    "NK-cell": "#A7D989",
    "Plasma-cell": "#CBB6E5",
    "T-cell": "#3D7DBB",
    "VSMC": "#B9CCE8",
    "Unknown": "#999999",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--input-h5ad",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_scdrs_<trait>_merged.h5ad",
    )
    parser.add_argument(
        "--celltype-col",
        default="final_high_level_celltype_10",
    )
    return parser.parse_args()


def pick_trait_col(adata: sc.AnnData, trait: str) -> str:
    for col in [f"{trait}_norm_score", "norm_score", "zscore", "score"]:
        if col in adata.obs.columns:
            return col
    raise KeyError(f"No scDRS score column found. Available: {adata.obs.columns.tolist()}")


def bh_adjust(pvals: list[float]) -> list[float]:
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    if n == 0:
        return []
    order = np.argsort(pvals)
    ranked = pvals[order]
    adjusted = np.empty(n, dtype=float)
    prev = 1.0
    for i in range(n - 1, -1, -1):
        value = ranked[i] * n / (i + 1)
        prev = min(prev, value)
        adjusted[i] = min(prev, 1.0)
    out = np.empty(n, dtype=float)
    out[order] = adjusted
    return out.tolist()


def p_to_star(p: float) -> str:
    if p < 1e-4:
        return "****"
    if p < 1e-3:
        return "***"
    if p < 1e-2:
        return "**"
    if p < 5e-2:
        return "*"
    return "ns"


def compute_one_vs_rest(
    df: pd.DataFrame, value_col: str, group_col: str, present_groups: list[str]
) -> pd.DataFrame:
    rows = []
    raw_pvals = []

    for group in present_groups:
        in_vals = df.loc[df[group_col] == group, value_col].astype(float).values
        out_vals = df.loc[df[group_col] != group, value_col].astype(float).values
        stat, p = mannwhitneyu(in_vals, out_vals, alternative="two-sided")
        rows.append(
            {
                "celltype": group,
                "n_cells": len(in_vals),
                "mean_score": round(float(in_vals.mean()), 4),
                "median_score": round(float(np.median(in_vals)), 4),
                "frac_gt_1p65": round(float((in_vals > 1.65).mean()), 4),
                "test": "mannwhitneyu_one_vs_rest",
                "statistic": round(float(stat), 2),
                "p_value": p,
            }
        )
        raw_pvals.append(p)

    adj = bh_adjust(raw_pvals)
    for row, p_adj in zip(rows, adj):
        row["p_adj_bh"] = p_adj
        row["sig"] = p_to_star(p_adj)

    all_values = [df.loc[df[group_col] == g, value_col].astype(float).values for g in present_groups]
    if len(all_values) >= 2:
        kw_stat, kw_p = kruskal(*all_values)
    else:
        kw_stat, kw_p = np.nan, np.nan
    rows.insert(
        0,
        {
            "celltype": "ALL (Kruskal-Wallis)",
            "n_cells": len(df),
            "mean_score": round(float(df[value_col].mean()), 4),
            "median_score": round(float(df[value_col].median()), 4),
            "frac_gt_1p65": round(float((df[value_col] > 1.65).mean()), 4),
            "test": "kruskal",
            "statistic": round(float(kw_stat), 2),
            "p_value": kw_p,
            "p_adj_bh": kw_p,
            "sig": p_to_star(kw_p),
        },
    )

    return pd.DataFrame(rows)


def add_sig_bar(ax, x1: float, x2: float, y: float, h: float, text: str):
    ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=1.2, c="black")
    ax.text((x1 + x2) / 2, y + h, text, ha="center", va="bottom", fontsize=9)


def plot_violin_with_stats(
    df: pd.DataFrame,
    value_col: str,
    group_col: str,
    stats_df: pd.DataFrame,
    out_png: Path,
):
    present_order = [g for g in CELLTYPE_ORDER if g in df[group_col].unique()]
    palette = {k: v for k, v in CELLTYPE_COLORS.items() if k in present_order}

    fig, ax = plt.subplots(figsize=(14, 6.5))

    sns.violinplot(
        data=df,
        x=group_col,
        y=value_col,
        order=present_order,
        palette=palette,
        inner=None,
        cut=0,
        linewidth=1.2,
        ax=ax,
    )
    sns.boxplot(
        data=df,
        x=group_col,
        y=value_col,
        order=present_order,
        width=0.18,
        showcaps=True,
        boxprops={"facecolor": "white", "zorder": 3, "alpha": 0.85},
        whiskerprops={"linewidth": 1.1},
        medianprops={"color": "black", "linewidth": 1.4},
        flierprops={"marker": ""},
        ax=ax,
    )
    sns.stripplot(
        data=df,
        x=group_col,
        y=value_col,
        order=present_order,
        color="black",
        size=1.2,
        jitter=0.22,
        alpha=0.35,
        ax=ax,
    )

    kw_row = stats_df[stats_df["test"] == "kruskal"].iloc[0]
    ax.set_title(
        f"scDRS score by cell type (Kruskal-Wallis p={kw_row['p_value']:.3g})\n"
        f"* marks: mean>0 & frac>1.65 >8% (one-vs-rest MWU, BH-adjusted)",
        fontsize=12,
    )
    ax.set_xlabel("")
    ax.set_ylabel(value_col)
    ax.tick_params(axis="x", rotation=35)
    for label in ax.get_xticklabels():
        label.set_ha("right")

    ovr = stats_df[stats_df["test"] == "mannwhitneyu_one_vs_rest"].copy()
    xmap = {g: i for i, g in enumerate(present_order)}
    y_max = float(df[value_col].max())
    y_min = float(df[value_col].min())
    span = y_max - y_min if y_max > y_min else 1.0

    # Method C: only annotate cell types with mean_score > 0 AND frac_gt_1p65 > 0.08
    # This focuses on true positive enrichment rather than large-sample bilateral differences
    enrich_mask = (ovr["mean_score"] > 0) & (ovr["frac_gt_1p65"] > 0.08)
    for _, row in ovr[enrich_mask].iterrows():
        ct = row["celltype"]
        if ct not in xmap:
            continue
        xi = xmap[ct]
        star = row["sig"]
        ax.text(
            xi,
            y_max + 0.06 * span,
            star,
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="bold",
            color="black",
        )

    ax.set_ylim(y_min - 0.05 * span, y_max + 0.18 * span)

    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    args = parse_args()
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_scdrs_{args.trait}_merged.h5ad")

    print(f"Loading {input_h5ad} ...")
    adata = sc.read_h5ad(input_h5ad)

    trait_col = pick_trait_col(adata, args.trait)
    group_col = args.celltype_col
    if group_col not in adata.obs.columns:
        raise KeyError(f"Column '{group_col}' not found in adata.obs")

    df = adata.obs[[trait_col, group_col]].copy()
    df[group_col] = df[group_col].astype(str)
    present_groups = [g for g in CELLTYPE_ORDER if g in df[group_col].unique()]
    df = df[df[group_col].isin(present_groups)].copy()
    print(f"  {len(df)} cells across {len(present_groups)} cell types")

    print("Computing one-vs-rest statistics ...")
    stats_df = compute_one_vs_rest(df, value_col=trait_col, group_col=group_col, present_groups=present_groups)

    out_stats = MERGED_DIR / f"GSE159677_scdrs_celltype_one_vs_rest_{args.trait}.csv"
    stats_df.to_csv(out_stats, index=False)

    out_png = PLOT_DIR / f"GSE159677_scdrs_celltype_violin_stats_{args.trait}.png"
    plot_violin_with_stats(df, value_col=trait_col, group_col=group_col, stats_df=stats_df, out_png=out_png)

    print("\nOne-vs-rest statistics:")
    print(stats_df.to_string(index=False))
    print(f"\nsaved: {out_stats}")
    print(f"saved: {out_png}")


if __name__ == "__main__":
    main()
