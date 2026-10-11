#!/usr/bin/env python3
"""
Plot final VSMC subtype UMAP and violin plot with significance tests.

Inputs:
  - merged/GSE159677_vsmc_subtyped_final_<trait>.h5ad

Outputs:
  - plots/GSE159677_vsmc_final_umap_<trait>.png
  - plots/GSE159677_vsmc_final_violin_<trait>.png
  - merged/GSE159677_vsmc_final_stats_<trait>.csv
"""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path
import os

import numpy as np
import pandas as pd
import scanpy as sc
import seaborn as sns
from matplotlib import pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from scipy.stats import kruskal, mannwhitneyu


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"

PLOT_DIR.mkdir(parents=True, exist_ok=True)

sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, dpi_save=200, frameon=False)

SUBTYPE_ORDER = ["Contractile", "Fibromyocyte", "Modulated"]
SUBTYPE_COLORS = {
    "Contractile": "#4F83C4",
    "Fibromyocyte": "#77AE6F",
    "Modulated": "#E9963A",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--input-h5ad",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_vsmc_subtyped_final_<trait>.h5ad",
    )
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


def bh_adjust(pvals: list[float]) -> list[float]:
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    adjusted = np.empty(n, dtype=float)
    prev = 1.0
    for i in range(n - 1, -1, -1):
        rank = i + 1
        value = ranked[i] * n / rank
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


def compute_stats(df: pd.DataFrame, value_col: str, group_col: str) -> pd.DataFrame:
    rows = []
    present_groups = [g for g in SUBTYPE_ORDER if g in df[group_col].unique()]
    group_values = [df.loc[df[group_col] == g, value_col].astype(float).values for g in present_groups]
    group_summary = {
        g: {
            "n": int(len(vals)),
            "mean": float(np.mean(vals)),
            "median": float(np.median(vals)),
        }
        for g, vals in zip(present_groups, group_values)
    }
    if len(group_values) >= 2:
        kw_stat, kw_p = kruskal(*group_values)
    else:
        kw_stat, kw_p = np.nan, np.nan
    rows.append(
        {
            "test": "kruskal",
            "group1": "ALL",
            "group2": "ALL",
            "statistic": kw_stat,
            "p_value": kw_p,
            "p_adj_bh": kw_p,
            "group1_n": np.nan,
            "group2_n": np.nan,
            "group1_mean": np.nan,
            "group2_mean": np.nan,
            "group1_median": np.nan,
            "group2_median": np.nan,
            "median_diff_group1_minus_group2": np.nan,
        }
    )

    pair_rows = []
    raw_pvals = []
    for g1, g2 in combinations(present_groups, 2):
        x = df.loc[df[group_col] == g1, value_col].astype(float).values
        y = df.loc[df[group_col] == g2, value_col].astype(float).values
        stat, p = mannwhitneyu(x, y, alternative="two-sided")
        pair_rows.append(
            {
                "test": "mannwhitneyu",
                "group1": g1,
                "group2": g2,
                "statistic": stat,
                "p_value": p,
                "group1_n": group_summary[g1]["n"],
                "group2_n": group_summary[g2]["n"],
                "group1_mean": group_summary[g1]["mean"],
                "group2_mean": group_summary[g2]["mean"],
                "group1_median": group_summary[g1]["median"],
                "group2_median": group_summary[g2]["median"],
                "median_diff_group1_minus_group2": group_summary[g1]["median"] - group_summary[g2]["median"],
            }
        )
        raw_pvals.append(p)

    if pair_rows:
        adj = bh_adjust(raw_pvals)
        for row, p_adj in zip(pair_rows, adj):
            row["p_adj_bh"] = p_adj
            rows.append(row)

    return pd.DataFrame(rows)


def plot_umap(adata: sc.AnnData, trait_col: str, out_png: Path):
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.2))

    ax1 = axes[0]
    for subtype in [x for x in SUBTYPE_ORDER if x in adata.obs["vsmc_subtype_final"].astype(str).unique()]:
        mask = adata.obs["vsmc_subtype_final"].astype(str) == subtype
        coords = adata.obsm["X_umap_vsmc"][mask]
        ax1.scatter(
            coords[:, 0],
            coords[:, 1],
            s=6,
            c=SUBTYPE_COLORS[subtype],
            label=subtype,
            alpha=0.80,
            edgecolors="none",
            rasterized=True,
        )
    ax1.set_title("Final VSMC Labels")
    ax1.set_xlabel("UMAP1")
    ax1.set_ylabel("UMAP2")
    ax1.legend(frameon=False, fontsize=9, markerscale=2.5, loc="best")

    ax2 = axes[1]
    scores = adata.obs[trait_col].astype(float).values
    lo = float(np.nanpercentile(scores, 2))
    hi = float(np.nanpercentile(scores, 98))
    vabs = max(abs(lo), abs(hi))
    norm = TwoSlopeNorm(vmin=-vabs, vcenter=0.0, vmax=vabs)
    order = np.argsort(np.abs(scores))
    coords = adata.obsm["X_umap_vsmc"][order]
    vals = scores[order]
    sca = ax2.scatter(
        coords[:, 0],
        coords[:, 1],
        s=6,
        c=vals,
        cmap="RdBu_r",
        norm=norm,
        alpha=0.80,
        edgecolors="none",
        rasterized=True,
    )
    ax2.set_title(trait_col)
    ax2.set_xlabel("UMAP1")
    ax2.set_ylabel("UMAP2")
    fig.colorbar(sca, ax=ax2, fraction=0.046, pad=0.04)

    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def add_sig_bar(ax, x1: float, x2: float, y: float, h: float, text: str):
    ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=1.2, c="black")
    ax.text((x1 + x2) / 2, y + h, text, ha="center", va="bottom", fontsize=10)


def plot_violin(df: pd.DataFrame, value_col: str, group_col: str, stats_df: pd.DataFrame, out_png: Path):
    plt.figure(figsize=(8.8, 5.8))
    ax = plt.gca()

    order = [g for g in SUBTYPE_ORDER if g in df[group_col].unique()]
    palette = {k: v for k, v in SUBTYPE_COLORS.items() if k in order}

    sns.violinplot(
        data=df,
        x=group_col,
        y=value_col,
        order=order,
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
        order=order,
        width=0.20,
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
        order=order,
        color="black",
        size=1.8,
        jitter=0.22,
        alpha=0.45,
        ax=ax,
    )

    overall_row = stats_df[stats_df["test"] == "kruskal"].iloc[0]
    medians = df.groupby(group_col, observed=True)[value_col].median()
    median_text = ", ".join([f"{g}={medians[g]:.2f}" for g in order if g in medians.index])
    ax.set_title(
        f"scDRS score across final VSMC subtypes\n"
        f"Kruskal-Wallis p={overall_row['p_value']:.3g} | median: {median_text}",
        fontsize=14,
    )
    ax.set_xlabel("")
    ax.set_ylabel(value_col)

    y_max = float(df[value_col].max())
    y_min = float(df[value_col].min())
    span = y_max - y_min if y_max > y_min else 1.0
    base = y_max + 0.08 * span
    step = 0.08 * span
    h = 0.03 * span

    pair_rows = stats_df[stats_df["test"] == "mannwhitneyu"].copy()
    pair_rows = pair_rows.sort_values("p_adj_bh")
    xmap = {group: idx for idx, group in enumerate(order)}
    for i, row in enumerate(pair_rows.itertuples(index=False)):
        x1 = xmap[row.group1]
        x2 = xmap[row.group2]
        y = base + i * step
        add_sig_bar(ax, x1, x2, y, h, p_to_star(row.p_adj_bh))

    ax.set_ylim(y_min - 0.05 * span, base + max(len(pair_rows), 1) * step + 0.08 * span)
    plt.tight_layout()
    plt.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close()


def main():
    args = parse_args()
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_vsmc_subtyped_final_{args.trait}.h5ad")

    adata = sc.read_h5ad(input_h5ad)
    if "vsmc_subtype_final" not in adata.obs.columns or "X_umap_vsmc" not in adata.obsm:
        raise KeyError("Expected 'vsmc_subtype_final' in obs and 'X_umap_vsmc' in obsm")

    trait_col = pick_trait_col(adata, args.trait)
    df = adata.obs[[trait_col, "vsmc_subtype_final"]].copy()
    df["vsmc_subtype_final"] = df["vsmc_subtype_final"].astype(str)
    df = df[df["vsmc_subtype_final"].isin(SUBTYPE_ORDER)].copy()

    stats_df = compute_stats(df, value_col=trait_col, group_col="vsmc_subtype_final")
    out_stats = MERGED_DIR / f"GSE159677_vsmc_final_stats_{args.trait}.csv"
    stats_df.to_csv(out_stats, index=False)

    out_umap = PLOT_DIR / f"GSE159677_vsmc_final_umap_{args.trait}.png"
    plot_umap(adata, trait_col=trait_col, out_png=out_umap)

    out_violin = PLOT_DIR / f"GSE159677_vsmc_final_violin_{args.trait}.png"
    plot_violin(df, value_col=trait_col, group_col="vsmc_subtype_final", stats_df=stats_df, out_png=out_violin)

    print(stats_df.to_string(index=False))
    print(f"\nsaved: {out_stats}")
    print(f"saved: {out_umap}")
    print(f"saved: {out_violin}")


if __name__ == "__main__":
    main()
