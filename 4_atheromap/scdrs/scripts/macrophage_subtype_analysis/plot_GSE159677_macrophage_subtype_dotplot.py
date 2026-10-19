#!/usr/bin/env python3
"""
Macrophage subtype marker dotplot for GSE159677.

Two-panel figure:
  Panel A - Dotplot: macrophage_leiden clusters x top DE markers
  Panel B - Dotplot: macrophage_leiden clusters x canonical reference markers

Outputs:
  plots/GSE159677_macrophage_subtype_dotplot.png / .pdf
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from scipy.sparse import issparse


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"

CANONICAL = {
    "Mac_C1Q": ["C1QA", "C1QB", "C1QC", "SELENOP", "FOLR2"],
    "Mac_HMOX1": ["HMOX1", "APOE", "APOC1", "CCL18", "GPNMB"],
    "Mac_IL10hi": ["IL10", "TNFAIP3", "CCL3", "CCL4", "CXCL3"],
    "Mac_PLIN2hi/TREM1hi": ["PLIN2", "TREM1", "ANGPTL4", "CCL2", "TIMP1"],
    "Mac_S100A8hi": ["S100A8", "S100A9", "IL1B", "FCN1", "VCAN"],
    "Mac_TREM2hi": ["TREM2", "SPP1", "APOE", "LPL", "GPNMB"],
}

SUBTYPE_COLORS = {
    "Mac_C1Q": "#C94232",
    "Mac_HMOX1": "#8C8C8C",
    "Mac_IL10hi": "#C5B3DE",
    "Mac_PLIN2hi/TREM1hi": "#49A2CF",
    "Mac_S100A8hi": "#C7C53B",
    "Mac_TREM2hi": "#E8B3CF",
}

MAX_DOT = 220
AXIS_FS = 9
TOP_N = 5


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--input-h5ad",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_macrophage_subtyped_final_<trait>.h5ad",
    )
    parser.add_argument(
        "--dge-csv",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_macrophage_leiden_wilcoxon_dge_<trait>.csv",
    )
    return parser.parse_args()


def build_cluster_subtype_map(adata: sc.AnnData) -> dict[str, str]:
    mapping = (
        adata.obs[["macrophage_leiden", "macrophage_subtype_final"]]
        .astype(str)
        .drop_duplicates()
        .sort_values(["macrophage_leiden", "macrophage_subtype_final"])
    )
    counts = mapping.groupby("macrophage_leiden")["macrophage_subtype_final"].nunique()
    multi = counts[counts > 1].index.tolist()
    if multi:
        print(
            f"WARNING: the following leiden cluster(s) map to more than one subtype; "
            f"only the last (alphabetically) will be used for y-axis coloring: {sorted(multi)}"
        )
    return dict(zip(mapping["macrophage_leiden"], mapping["macrophage_subtype_final"]))


def build_symbol_idx(adata: sc.AnnData) -> dict[str, int]:
    if "gene_name" in adata.var.columns:
        return {g: i for i, g in enumerate(adata.var["gene_name"].astype(str))}
    return {g: i for i, g in enumerate(adata.var.index.astype(str))}


def compute_dot(adata, all_genes, sym_idx, groups, groupby, layer="acosh"):
    mat = adata.layers[layer] if layer in adata.layers else adata.X
    obs_grp = adata.obs[groupby].astype(str).values
    n_g, n_gene = len(groups), len(all_genes)
    fracs = np.zeros((n_g, n_gene))
    means = np.zeros((n_g, n_gene))
    for gi, gene in enumerate(all_genes):
        if gene not in sym_idx:
            continue
        col = mat[:, sym_idx[gene]]
        if issparse(col):
            col = np.asarray(col.toarray()).flatten()
        else:
            col = np.asarray(col).flatten()
        for gri, grp in enumerate(groups):
            mask = obs_grp == grp
            vals = col[mask]
            fracs[gri, gi] = (vals > 0).mean() if len(vals) else 0
            means[gri, gi] = vals.mean() if len(vals) else 0
    return fracs, means


def draw_dotplot(ax, ax_cbar, ax_size, adata, all_genes, boundaries, groups, groupby, cluster_subtype, panel_label, title, cmap):
    sym_idx = build_symbol_idx(adata)
    fracs, means = compute_dot(adata, all_genes, sym_idx, groups, groupby)

    vmin = means.min(axis=0, keepdims=True)
    vmax = means.max(axis=0, keepdims=True)
    denom = np.where(vmax - vmin == 0, 1.0, vmax - vmin)
    means_s = (means - vmin) / denom
    n_gene, n_grp = len(all_genes), len(groups)

    ax.set_facecolor("#F7F7F7")
    for xi in range(n_gene):
        ax.axvline(xi, color="white", lw=0.4, zorder=1)
    for yi in range(n_grp):
        ax.axhline(yi, color="white", lw=0.4, zorder=1)

    norm = Normalize(vmin=0, vmax=1)
    cmap_fn = plt.colormaps[cmap]
    for gi in range(n_gene):
        for gri in range(n_grp):
            frac = fracs[gri, gi]
            if frac < 0.01:
                continue
            ax.scatter(
                gi,
                gri,
                s=frac * MAX_DOT,
                c=[cmap_fn(norm(means_s[gri, gi]))],
                edgecolors="none",
                zorder=3,
            )

    for ct, x0, x1 in boundaries:
        if x0 > 0:
            ax.axvline(x0 - 0.5, color="#555", lw=0.9, zorder=4)
        mid = (x0 + x1 - 1) / 2
        ax.text(mid, n_grp + 0.65, ct, ha="center", va="bottom", fontsize=7.5, fontweight="bold", rotation=30, rotation_mode="anchor")

    ytick_labels = []
    for grp in groups:
        subtype = cluster_subtype.get(grp, "")
        n_cells = adata.obs[adata.obs[groupby].astype(str) == grp].shape[0]
        ytick_labels.append(f"{grp}  [{subtype}]  n={n_cells}")

    ax.set_xticks(range(n_gene))
    ax.set_xticklabels(all_genes, rotation=90, ha="center", fontsize=7.5)
    ax.set_yticks(range(n_grp))
    ax.set_yticklabels(ytick_labels, fontsize=7.5)

    for gri, grp in enumerate(groups):
        subtype = cluster_subtype.get(grp, "")
        color = SUBTYPE_COLORS.get(subtype, "#333333")
        ax.get_yticklabels()[gri].set_color(color)
        ax.get_yticklabels()[gri].set_fontweight("bold")

    ax.set_xlim(-0.6, n_gene - 0.4)
    ax.set_ylim(-0.6, n_grp + 1.9)
    ax.invert_yaxis()
    ax.set_ylabel("Macrophage leiden cluster", fontsize=AXIS_FS)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(title, fontsize=AXIS_FS, pad=6)
    ax.text(-0.06, 1.06, panel_label, transform=ax.transAxes, fontsize=13, fontweight="bold", va="top", ha="left")

    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = plt.colorbar(sm, cax=ax_cbar, orientation="vertical")
    cb.set_label("Mean expr\n(scaled)", fontsize=7)
    cb.ax.tick_params(labelsize=6)

    ax_size.set_axis_off()
    for frac, label, yp in zip([0.25, 0.50, 0.75, 1.0], ["25%", "50%", "75%", "100%"], np.linspace(0.82, 0.10, 4)):
        ax_size.scatter(0.35, yp, s=frac * MAX_DOT, c="grey", edgecolors="none", transform=ax_size.transAxes, clip_on=False)
        ax_size.text(0.68, yp, label, ha="left", va="center", fontsize=6.5, transform=ax_size.transAxes)
    ax_size.text(0.35, 0.97, "Fraction\nexpressing", ha="center", va="bottom", fontsize=7, transform=ax_size.transAxes)


def _leiden_sort_key(val: str):
    try:
        return (0, int(val), val)
    except ValueError:
        return (1, 0, val)


def build_top_de_genes(dge_csv: Path, top_n: int = TOP_N):
    df = pd.read_csv(dge_csv)
    df["macrophage_leiden"] = df["macrophage_leiden"].astype(str)
    clusters = sorted(df["macrophage_leiden"].unique(), key=_leiden_sort_key)

    all_genes = []
    boundaries = []
    seen = set()
    for cl in clusters:
        sub = df[df["macrophage_leiden"] == cl].sort_values("scores", ascending=False)
        genes = [g for g in sub["gene_symbol"].tolist() if g not in seen][:top_n]
        seen.update(genes)
        if not genes:
            continue
        x0 = len(all_genes)
        all_genes.extend(genes)
        boundaries.append((f"cluster {cl}", x0, len(all_genes)))
    return all_genes, boundaries, clusters


def build_canonical_genes():
    all_genes = []
    boundaries = []
    for subtype, genes in CANONICAL.items():
        x0 = len(all_genes)
        all_genes.extend(genes)
        boundaries.append((subtype, x0, len(all_genes)))
    return all_genes, boundaries


def add_subtype_legend(fig):
    handles = [mpatches.Patch(color=SUBTYPE_COLORS[k], label=k) for k in CANONICAL]
    fig.legend(
        handles=handles,
        title="Subtype",
        title_fontsize=8,
        fontsize=7.5,
        loc="lower center",
        ncol=3,
        bbox_to_anchor=(0.5, -0.01),
        frameon=False,
        handlelength=1.2,
    )


def main():
    args = parse_args()
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    input_h5ad = args.input_h5ad or (MERGED_DIR / f"GSE159677_macrophage_subtyped_final_{args.trait}.h5ad")
    dge_csv = args.dge_csv or (MERGED_DIR / f"GSE159677_macrophage_leiden_wilcoxon_dge_{args.trait}.csv")
    out_png = PLOT_DIR / f"GSE159677_macrophage_subtype_dotplot_{args.trait}.png"
    out_pdf = PLOT_DIR / f"GSE159677_macrophage_subtype_dotplot_{args.trait}.pdf"

    if not dge_csv.exists():
        raise FileNotFoundError(
            f"DGE CSV not found: {dge_csv}\n"
            f"Run run_GSE159677_macrophage_subtype_formal.py first to generate it."
        )

    adata = sc.read_h5ad(input_h5ad)
    groups = sorted(adata.obs["macrophage_leiden"].astype(str).unique(), key=_leiden_sort_key)
    cluster_subtype = build_cluster_subtype_map(adata)

    top_genes, top_bounds, _ = build_top_de_genes(dge_csv, top_n=TOP_N)
    can_genes, can_bounds = build_canonical_genes()

    fig_h = max(14, len(groups) * 0.36 * 2 + 5)
    fig = plt.figure(figsize=(20, fig_h))
    fig.patch.set_facecolor("white")
    outer = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[len(top_genes), len(can_genes)], hspace=0.55)

    def make_row(spec, width_n):
        return gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=spec, width_ratios=[width_n, 0.32, 0.9], wspace=0.04)

    gs_a = make_row(outer[0], len(top_genes))
    ax_a = fig.add_subplot(gs_a[0])
    ax_a_cb = fig.add_subplot(gs_a[1])
    ax_a_sz = fig.add_subplot(gs_a[2])
    draw_dotplot(
        ax_a,
        ax_a_cb,
        ax_a_sz,
        adata,
        top_genes,
        top_bounds,
        groups,
        "macrophage_leiden",
        cluster_subtype,
        panel_label="A",
        title=f"Top {TOP_N} DE markers per macrophage leiden cluster",
        cmap="Blues",
    )

    gs_b = make_row(outer[1], len(can_genes))
    ax_b = fig.add_subplot(gs_b[0])
    ax_b_cb = fig.add_subplot(gs_b[1])
    ax_b_sz = fig.add_subplot(gs_b[2])
    draw_dotplot(
        ax_b,
        ax_b_cb,
        ax_b_sz,
        adata,
        can_genes,
        can_bounds,
        groups,
        "macrophage_leiden",
        cluster_subtype,
        panel_label="B",
        title="Canonical reference markers for final macrophage subtypes",
        cmap="Reds",
    )

    add_subtype_legend(fig)
    for out_path in [out_png, out_pdf]:
        fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
        print(f"saved: {out_path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
