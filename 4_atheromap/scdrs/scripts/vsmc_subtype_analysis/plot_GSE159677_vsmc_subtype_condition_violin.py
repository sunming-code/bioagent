#!/usr/bin/env python3
"""
Plot VSMC final subtype x condition scDRS violin plot with per-subtype statistics.

Outputs:
  - plots/GSE159677_vsmc_subtype_condition_violin_<trait>.png
  - merged/GSE159677_vsmc_subtype_condition_stats_<trait>.csv
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
from scipy.stats import mannwhitneyu


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"

SUBTYPE_ORDER = ["Contractile", "Fibromyocyte", "Modulated"]
COND_ORDER = ["D", "H"]
COND_PALETTE = {
    "D": "#D55E00",
    "H": "#4C78A8",
}

sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, frameon=False)


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
        "norm_score",
        "zscore",
        "score",
    ]
    for col in candidates:
        if col in adata.obs.columns:
            return col
    raise KeyError(f"Could not find scDRS score column. Available obs columns: {adata.obs.columns.tolist()}")


def bh_adjust(pvals: list[float]) -> list[float]:
    if not pvals:
        return []
    arr = np.asarray(pvals, dtype=float)
    n = len(arr)
    order = np.argsort(arr)
    ranked = arr[order]
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


def compute_stats(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    rows = []
    raw_pvals = []

    for subtype in SUBTYPE_ORDER:
        sub = df[df["vsmc_subtype_final"] == subtype].copy()
        if sub.empty:
            continue
        d_vals = sub.loc[sub["condition"] == "D", value_col].astype(float).values
        h_vals = sub.loc[sub["condition"] == "H", value_col].astype(float).values

        if len(d_vals) == 0 or len(h_vals) == 0:
            stat, p = np.nan, np.nan
        else:
            stat, p = mannwhitneyu(d_vals, h_vals, alternative="two-sided")
            raw_pvals.append(p)

        rows.append(
            {
                "subtype": subtype,
                "n_D": int(len(d_vals)),
                "n_H": int(len(h_vals)),
                "mean_D": float(np.mean(d_vals)) if len(d_vals) else np.nan,
                "mean_H": float(np.mean(h_vals)) if len(h_vals) else np.nan,
                "median_D": float(np.median(d_vals)) if len(d_vals) else np.nan,
                "median_H": float(np.median(h_vals)) if len(h_vals) else np.nan,
                "median_diff_D_minus_H": (
                    float(np.median(d_vals) - np.median(h_vals))
                    if len(d_vals) and len(h_vals)
                    else np.nan
                ),
                "statistic": stat,
                "p_value": p,
            }
        )

    valid_idx = [i for i, row in enumerate(rows) if pd.notna(row["p_value"])]
    adj = bh_adjust([rows[i]["p_value"] for i in valid_idx])
    for idx, p_adj in zip(valid_idx, adj):
        rows[idx]["p_adj_bh"] = p_adj
    for i, row in enumerate(rows):
        if "p_adj_bh" not in row:
            rows[i]["p_adj_bh"] = np.nan

    return pd.DataFrame(rows)


def add_sig_bar(ax, x1: float, x2: float, y: float, h: float, text: str):
    ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=1.2, c="black")
    ax.text((x1 + x2) / 2, y + h, text, ha="center", va="bottom", fontsize=10)


def plot_violin(df: pd.DataFrame, value_col: str, stats_df: pd.DataFrame, out_png: Path):
    fig, ax = plt.subplots(figsize=(9.2, 5.8))

    sns.violinplot(
        data=df,
        x="vsmc_subtype_final",
        y=value_col,
        hue="condition",
        order=[x for x in SUBTYPE_ORDER if x in df["vsmc_subtype_final"].unique()],
        hue_order=[x for x in COND_ORDER if x in df["condition"].unique()],
        palette=COND_PALETTE,
        inner=None,
        cut=0,
        linewidth=1.1,
        dodge=True,
        ax=ax,
    )
    sns.boxplot(
        data=df,
        x="vsmc_subtype_final",
        y=value_col,
        hue="condition",
        order=[x for x in SUBTYPE_ORDER if x in df["vsmc_subtype_final"].unique()],
        hue_order=[x for x in COND_ORDER if x in df["condition"].unique()],
        palette=COND_PALETTE,
        width=0.18,
        dodge=True,
        showcaps=True,
        showfliers=False,
        boxprops={"facecolor": "white", "alpha": 0.8, "zorder": 3},
        whiskerprops={"linewidth": 1.0},
        medianprops={"color": "black", "linewidth": 1.3},
        ax=ax,
    )

    handles, labels = ax.get_legend_handles_labels()
    legend_map = {}
    for handle, label in zip(handles, labels):
        if label not in legend_map:
            legend_map[label] = handle
    keep_labels = [x for x in COND_ORDER if x in legend_map]
    ax.legend(
        [legend_map[x] for x in keep_labels],
        keep_labels,
        frameon=False,
        title="Condition",
        loc="upper right",
    )
    ax.set_xlabel("")
    ax.set_ylabel(value_col)

    medians = (
        df.groupby(["vsmc_subtype_final", "condition"], observed=True)[value_col]
        .median()
        .reset_index()
    )
    med_txt_parts = []
    for subtype in SUBTYPE_ORDER:
        sub = medians[medians["vsmc_subtype_final"] == subtype]
        if sub.empty:
            continue
        vals = []
        for cond in COND_ORDER:
            hit = sub[sub["condition"] == cond]
            if not hit.empty:
                vals.append(f"{cond}={hit.iloc[0][value_col]:.2f}")
        med_txt_parts.append(f"{subtype}: " + ", ".join(vals))
    ax.set_title("VSMC subtype x condition scDRS score\n" + " | ".join(med_txt_parts), fontsize=13)

    y_max = float(df[value_col].max())
    y_min = float(df[value_col].min())
    span = y_max - y_min if y_max > y_min else 1.0
    h = 0.03 * span
    base = y_max + 0.08 * span

    present_order = [x for x in SUBTYPE_ORDER if x in df["vsmc_subtype_final"].unique()]
    for i, subtype in enumerate(present_order):
        row = stats_df[stats_df["subtype"] == subtype]
        if row.empty or pd.isna(row.iloc[0]["p_adj_bh"]):
            continue
        add_sig_bar(ax, i - 0.20, i + 0.20, base, h, p_to_star(float(row.iloc[0]["p_adj_bh"])))

    ax.set_ylim(y_min - 0.05 * span, base + h + 0.12 * span)
    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    args = parse_args()
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_vsmc_subtyped_final_{args.trait}.h5ad")

    adata = sc.read_h5ad(input_h5ad)
    if "vsmc_subtype_final" not in adata.obs.columns or "condition" not in adata.obs.columns:
        raise KeyError("Expected obs columns 'vsmc_subtype_final' and 'condition' were not found")

    trait_col = pick_trait_col(adata, args.trait)
    df = adata.obs[[trait_col, "vsmc_subtype_final", "condition"]].copy()
    df["vsmc_subtype_final"] = df["vsmc_subtype_final"].astype(str)
    df["condition"] = df["condition"].astype(str)
    df = df[df["vsmc_subtype_final"].isin(SUBTYPE_ORDER)].copy()
    df = df[df["condition"].isin(COND_ORDER)].copy()

    stats_df = compute_stats(df, trait_col)
    out_stats = MERGED_DIR / f"GSE159677_vsmc_subtype_condition_stats_{args.trait}.csv"
    stats_df.to_csv(out_stats, index=False)

    out_plot = PLOT_DIR / f"GSE159677_vsmc_subtype_condition_violin_{args.trait}.png"
    plot_violin(df, trait_col, stats_df, out_plot)

    print(stats_df.to_string(index=False))
    print(f"\nsaved: {out_stats}")
    print(f"saved: {out_plot}")


if __name__ == "__main__":
    main()
