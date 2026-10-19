#!/usr/bin/env python3
"""
Top scDRS-correlated genes for GSE159677 and cross-celltype dotplot.

Inputs:
  - merged/GSE159677_harmony_highlevel_annotated_final.h5ad
  - scdrs_out/<trait>.full_score.gz

Outputs:
  - merged/GSE159677_scdrs_gene_corr_<trait>.csv
  - merged/GSE159677_scdrs_top20_positive_genes_<trait>.csv
  - plots/GSE159677_scdrs_gene_top20_corr_<trait>.png
  - plots/GSE159677_scdrs_top10_positive_genes_dotplot_<trait>.png
  - plots/GSE159677_scdrs_top20_plus_dotplot_<trait>.png
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

import numpy as np
import pandas as pd
import scanpy as sc
from matplotlib import pyplot as plt
from matplotlib.colors import Normalize
from scipy import sparse


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
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--h5ad-file",
        default=str(MERGED_DIR / "GSE159677_harmony_highlevel_annotated_final.h5ad"),
    )
    parser.add_argument(
        "--score-file",
        default=None,
        help="Path to <trait>.full_score.gz. Defaults to WORK_DIR/scdrs_out/<trait>.full_score.gz",
    )
    parser.add_argument(
        "--celltype-col",
        default="final_high_level_celltype_10",
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
    else:
        df = df.set_index(df.columns[0])
    df.index = df.index.astype(str)
    return df


def get_expr_matrix(adata: sc.AnnData):
    if "acosh" in adata.layers:
        X = adata.layers["acosh"]
        layer_name = "acosh"
    else:
        X = adata.X
        layer_name = "X"
    if sparse.issparse(X):
        X = X.tocsr()
    else:
        X = np.asarray(X, dtype=np.float64)
    return X, layer_name


def get_gene_symbols(adata: sc.AnnData) -> pd.Series:
    if "gene_name" in adata.var.columns:
        symbols = adata.var["gene_name"].astype(str).replace({"": np.nan, "nan": np.nan, "None": np.nan})
    else:
        symbols = pd.Series(index=adata.var_names, dtype=object)
    fallback = pd.Series(adata.var_names.astype(str), index=adata.var_names)
    symbols = symbols.fillna(fallback).astype(str)
    return symbols.reset_index(drop=True)


def compute_gene_correlations(X, y: np.ndarray, gene_symbols: pd.Series) -> pd.DataFrame:
    n_cells = X.shape[0]
    y = np.asarray(y, dtype=np.float64)
    valid = np.isfinite(y)
    X = X[valid]
    y = y[valid]
    n_cells = X.shape[0]

    y_centered = y - y.mean()
    y_std = y_centered.std(ddof=0)
    if y_std == 0:
        raise ValueError("scDRS score vector has zero variance")

    if sparse.issparse(X):
        x_mean = np.asarray(X.mean(axis=0)).ravel()
        x_sq_mean = np.asarray(X.power(2).mean(axis=0)).ravel()
        x_std = np.sqrt(np.clip(x_sq_mean - x_mean**2, 0, None))
        cov = np.asarray((X.T @ y_centered) / n_cells).ravel()
        nnz_frac = np.asarray(X.getnnz(axis=0) / n_cells).ravel()
    else:
        x_mean = X.mean(axis=0)
        x_std = X.std(axis=0, ddof=0)
        cov = (X * y_centered[:, None]).mean(axis=0)
        nnz_frac = (X > 0).mean(axis=0)

    corr = np.full(X.shape[1], np.nan, dtype=np.float64)
    keep = x_std > 0
    corr[keep] = cov[keep] / (x_std[keep] * y_std)

    corr_df = pd.DataFrame(
        {
            "feature_index": np.arange(X.shape[1], dtype=int),
            "gene_symbol": gene_symbols.astype(str).values,
            "corr": corr,
            "mean_expr": x_mean,
            "nonzero_fraction": nnz_frac,
        }
    )
    corr_df = corr_df.replace([np.inf, -np.inf], np.nan).dropna(subset=["corr"]).copy()
    corr_df = corr_df.sort_values(["gene_symbol", "corr"], ascending=[True, False])
    corr_df = corr_df.drop_duplicates(subset=["gene_symbol"], keep="first")
    corr_df = corr_df.sort_values("corr", ascending=False).reset_index(drop=True)
    return corr_df


def build_dotplot_df(adata: sc.AnnData, X, celltype_col: str, top_df: pd.DataFrame) -> pd.DataFrame:
    plot_types = [x for x in CELLTYPE_ORDER if x in adata.obs[celltype_col].astype(str).unique() and x != "Unknown"]
    top10 = top_df.head(10).copy()
    idxs = top10["feature_index"].astype(int).tolist()
    genes = top10["gene_symbol"].astype(str).tolist()

    rows = []
    for celltype in plot_types:
        mask = adata.obs[celltype_col].astype(str).values == celltype
        if mask.sum() == 0:
            continue
        sub = X[mask][:, idxs]
        if sparse.issparse(sub):
            mean_expr = np.asarray(sub.mean(axis=0)).ravel()
            frac_expr = np.asarray(sub.getnnz(axis=0) / sub.shape[0]).ravel() * 100.0
        else:
            mean_expr = sub.mean(axis=0)
            frac_expr = (sub > 0).mean(axis=0) * 100.0
        for gene, mean_val, frac_val in zip(genes, mean_expr, frac_expr):
            rows.append(
                {
                    "celltype": celltype,
                    "gene_symbol": gene,
                    "mean_expr": float(mean_val),
                    "fraction_pct": float(frac_val),
                }
            )

    dot_df = pd.DataFrame(rows)
    dot_df["mean_expr_scaled"] = 0.0
    for gene in genes:
        mask = dot_df["gene_symbol"] == gene
        vals = dot_df.loc[mask, "mean_expr"].to_numpy(dtype=float)
        if len(vals) == 0:
            continue
        vmin = vals.min()
        vmax = vals.max()
        if vmax > vmin:
            dot_df.loc[mask, "mean_expr_scaled"] = (vals - vmin) / (vmax - vmin)
        else:
            dot_df.loc[mask, "mean_expr_scaled"] = 0.0
    return dot_df, plot_types, genes


def draw_dotplot(ax, dot_df: pd.DataFrame, plot_types: list[str], genes: list[str]):
    x_map = {g: i for i, g in enumerate(genes)}
    y_map = {ct: i for i, ct in enumerate(plot_types)}

    x = dot_df["gene_symbol"].map(x_map).to_numpy()
    y = dot_df["celltype"].map(y_map).to_numpy()
    sizes = 8 + (dot_df["fraction_pct"].to_numpy() * 2.8)
    colors = dot_df["mean_expr_scaled"].to_numpy()

    sca = ax.scatter(
        x,
        y,
        s=sizes,
        c=colors,
        cmap="Reds",
        norm=Normalize(vmin=0, vmax=1),
        edgecolors="none",
    )

    ax.set_xticks(range(len(genes)))
    ax.set_xticklabels(genes, rotation=90)
    ax.set_yticks(range(len(plot_types)))
    ax.set_yticklabels(plot_types)
    ax.set_xlim(-0.5, len(genes) - 0.5)
    ax.set_ylim(-0.5, len(plot_types) - 0.5)
    ax.invert_yaxis()
    ax.grid(True, color="#d0d0d0", linewidth=0.8, alpha=0.7)
    ax.set_title("Top 10 positively correlated genes across cell types")
    return sca


def add_size_legend(ax):
    levels = [20, 40, 60, 80, 100]
    handles = [
        ax.scatter([], [], s=8 + level * 2.8, color="#7f7f7f", edgecolors="none")
        for level in levels
    ]
    ax.legend(
        handles,
        [str(x) for x in levels],
        title="Fraction of cells\nin group (%)",
        frameon=False,
        loc="center left",
        bbox_to_anchor=(1.02, 0.72),
        borderaxespad=0,
    )


def save_barplot(top20_df: pd.DataFrame, out_png: Path, title: str):
    plot_df = top20_df.sort_values("corr", ascending=True)
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    ax.barh(plot_df["gene_symbol"], plot_df["corr"], color="#E59A2E", edgecolor="none")
    ax.set_xlabel("Gene-score correlation (CORR)")
    ax.set_ylabel("Gene")
    ax.set_title(title)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    args = parse_args()
    trait = args.trait
    h5ad_file = Path(args.h5ad_file)
    score_file = Path(args.score_file) if args.score_file else SCDRS_DIR / f"{trait}.full_score.gz"
    celltype_col = args.celltype_col

    adata = sc.read_h5ad(h5ad_file)
    if celltype_col not in adata.obs:
        raise KeyError(f"Expected {celltype_col!r} in adata.obs")

    score_df = read_score_file(score_file)
    common = adata.obs_names.intersection(score_df.index)
    if len(common) == 0:
        raise ValueError("No overlapping cells between h5ad and score file")
    adata = adata[common].copy()
    score_df = score_df.loc[common].copy()

    norm_col = pick_first(score_df, ["norm_score", "score", "zscore"], required=True)
    norm_key = f"{trait}_norm_score"
    adata.obs[norm_key] = score_df[norm_col].astype(float).values

    X, expr_layer = get_expr_matrix(adata)
    gene_symbols = get_gene_symbols(adata)
    corr_df = compute_gene_correlations(X, adata.obs[norm_key].to_numpy(), gene_symbols)

    out_corr_csv = MERGED_DIR / f"GSE159677_scdrs_gene_corr_{trait}.csv"
    out_top20_csv = MERGED_DIR / f"GSE159677_scdrs_top20_positive_genes_{trait}.csv"
    out_bar_png = PLOT_DIR / f"GSE159677_scdrs_gene_top20_corr_{trait}.png"
    out_dot_png = PLOT_DIR / f"GSE159677_scdrs_top10_positive_genes_dotplot_{trait}.png"
    out_combo_png = PLOT_DIR / f"GSE159677_scdrs_top20_plus_dotplot_{trait}.png"

    corr_df.to_csv(out_corr_csv, index=False)
    top20_df = corr_df.head(20).copy()
    top20_df.to_csv(out_top20_csv, index=False)

    save_barplot(top20_df, out_bar_png, "Top 20 scDRS-correlated genes")

    dot_df, plot_types, genes = build_dotplot_df(adata, X, celltype_col, corr_df)
    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    sca = draw_dotplot(ax, dot_df, plot_types, genes)
    add_size_legend(ax)
    cbar = fig.colorbar(sca, ax=ax, fraction=0.05, pad=0.18)
    cbar.set_label("Mean expression\nin group")
    plt.tight_layout()
    fig.savefig(out_dot_png, dpi=300, bbox_inches="tight")
    plt.close(fig)

    fig = plt.figure(figsize=(14, 6.6), layout="constrained")
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.28)

    ax1 = fig.add_subplot(gs[0, 0])
    plot_df = top20_df.sort_values("corr", ascending=True)
    ax1.barh(plot_df["gene_symbol"], plot_df["corr"], color="#E59A2E", edgecolor="none")
    ax1.set_xlabel("Gene-score correlation (CORR)")
    ax1.set_ylabel("Gene")
    ax1.set_title("Top 20 scDRS-correlated genes")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    ax2 = fig.add_subplot(gs[0, 1])
    sca = draw_dotplot(ax2, dot_df, plot_types, genes)
    add_size_legend(ax2)
    cbar = fig.colorbar(sca, ax=ax2, fraction=0.05, pad=0.18)
    cbar.set_label("Mean expression\nin group")
    fig.savefig(out_combo_png, dpi=300, bbox_inches="tight")
    plt.close(fig)

    print("Expression layer used:", expr_layer)
    print("saved:", out_corr_csv)
    print("saved:", out_top20_csv)
    print("saved:", out_bar_png)
    print("saved:", out_dot_png)
    print("saved:", out_combo_png)
    print("\nTop 20 positive genes:")
    print(top20_df[["gene_symbol", "corr"]].to_string(index=False))


if __name__ == "__main__":
    main()
