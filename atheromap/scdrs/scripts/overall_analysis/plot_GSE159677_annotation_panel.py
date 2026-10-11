#!/usr/bin/env python3
"""
Publication-quality annotation panel for GSE159677.

Three-in-one figure:
  Panel A – harmony_leiden UMAP (cluster numbers on data)
  Panel B – final_high_level_celltype_10 UMAP (legend on right)
  Panel C – Dotplot: leiden clusters × marker genes

Output:
  plots/GSE159677_annotation_panel.png
  plots/GSE159677_annotation_panel.pdf
"""

from __future__ import annotations

import json
from pathlib import Path
import os

import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from scipy.sparse import issparse


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR  = WORK_DIR / "merged"
META_DIR    = WORK_DIR / "metadata"
PLOT_DIR    = WORK_DIR / "plots"

INPUT_H5AD   = MERGED_DIR / "GSE159677_harmony_highlevel_annotated_final.h5ad"
MARKER_JSON  = META_DIR   / "GSE159677_paper10_highlevel_markers.json"
OUT_PNG      = PLOT_DIR   / "GSE159677_annotation_panel.png"
OUT_PDF      = PLOT_DIR   / "GSE159677_annotation_panel.pdf"

CELLTYPE_ORDER = [
    "B-cell", "Dendritic-cell", "Endothelial", "FB", "Macrophage",
    "Mast-cell", "NK-cell", "Plasma-cell", "T-cell", "VSMC", "Unknown",
]
CELLTYPE_COLORS = {
    "B-cell":        "#8B5A46",
    "Dendritic-cell":"#8E6BBE",
    "Endothelial":   "#4DAA57",
    "FB":            "#CF78B8",
    "Macrophage":    "#F28E2B",
    "Mast-cell":     "#D43F3A",
    "NK-cell":       "#A7D989",
    "Plasma-cell":   "#CBB6E5",
    "T-cell":        "#3D7DBB",
    "VSMC":          "#B9CCE8",
    "Unknown":       "#9E9E9E",
}

# Leiden cluster colour palette (tab20 extended)
_TAB20  = plt.cm.tab20.colors   # 20 colours
_TAB20B = plt.cm.tab20b.colors  # 20 more
LEIDEN_PALETTE = list(_TAB20) + list(_TAB20B)

DOT_CMAP    = "Reds"
MAX_DOT_PX  = 220       # scatter size units for 100 % fraction
PANEL_FS    = 11        # panel label font size
AXIS_FS     = 9


# ──────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────────────────

def _label(ax, letter: str):
    """Add bold panel letter (A / B / C) in upper-left corner."""
    ax.text(
        -0.06, 1.06, letter,
        transform=ax.transAxes,
        fontsize=14, fontweight="bold",
        va="top", ha="left",
    )


def _spine_off(ax):
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)


# ──────────────────────────────────────────────────────────────────────────────
# Panel A – leiden UMAP
# ──────────────────────────────────────────────────────────────────────────────

def plot_leiden_umap(ax, adata: sc.AnnData):
    coords   = adata.obsm["X_umap"]
    clusters = adata.obs["harmony_leiden"].astype(str).values
    uniq     = sorted(set(clusters), key=lambda x: int(x))

    if "harmony_leiden_colors" in adata.uns:
        raw_colors = adata.uns["harmony_leiden_colors"]
        color_map  = {cl: raw_colors[i % len(raw_colors)] for i, cl in enumerate(uniq)}
    else:
        color_map  = {cl: LEIDEN_PALETTE[i % len(LEIDEN_PALETTE)] for i, cl in enumerate(uniq)}

    for cl in uniq:
        mask = clusters == cl
        ax.scatter(
            coords[mask, 0], coords[mask, 1],
            s=2, c=[color_map[cl]], alpha=0.85,
            edgecolors="none", rasterized=True,
        )

    for cl in uniq:
        mask = clusters == cl
        cx = coords[mask, 0].mean()
        cy = coords[mask, 1].mean()
        ax.text(
            cx, cy, cl,
            fontsize=6.5, ha="center", va="center", fontweight="bold",
            color="black",
            bbox=dict(boxstyle="round,pad=0.12", facecolor="white",
                      alpha=0.72, edgecolor="none", linewidth=0),
        )

    ax.set_title("Leiden clusters", fontsize=AXIS_FS + 1, pad=4)
    ax.set_xlabel("UMAP1", fontsize=AXIS_FS)
    ax.set_ylabel("UMAP2", fontsize=AXIS_FS)
    ax.tick_params(labelsize=AXIS_FS - 1)
    _spine_off(ax)
    _label(ax, "A")


# ──────────────────────────────────────────────────────────────────────────────
# Panel B – cell-type UMAP
# ──────────────────────────────────────────────────────────────────────────────

def _build_celltype_colors(adata: sc.AnnData) -> dict[str, str]:
    """Read cell type colours from adata.uns; fall back to CELLTYPE_COLORS."""
    key = "final_high_level_celltype_10_colors"
    if key in adata.uns:
        cats = adata.obs["final_high_level_celltype_10"].cat.categories.tolist()
        raw  = adata.uns[key]
        return {ct: raw[i] for i, ct in enumerate(cats) if i < len(raw)}
    return dict(CELLTYPE_COLORS)


def plot_celltype_umap(ax, adata: sc.AnnData, ax_legend):
    coords    = adata.obsm["X_umap"]
    celltypes = adata.obs["final_high_level_celltype_10"].astype(str).values
    present   = [c for c in CELLTYPE_ORDER if c in set(celltypes)]
    ct_colors = _build_celltype_colors(adata)

    for ct in present:
        mask = celltypes == ct
        color = ct_colors.get(ct, CELLTYPE_COLORS.get(ct, "#999999"))
        ax.scatter(
            coords[mask, 0], coords[mask, 1],
            s=2, c=[color], alpha=0.85,
            edgecolors="none", rasterized=True, label=ct,
        )

    ax.set_title("Cell type annotation", fontsize=AXIS_FS + 1, pad=4)
    ax.set_xlabel("UMAP1", fontsize=AXIS_FS)
    ax.set_ylabel("UMAP2", fontsize=AXIS_FS)
    ax.tick_params(labelsize=AXIS_FS - 1)
    _spine_off(ax)
    _label(ax, "B")

    # Legend in a separate axes (ax_legend)
    ax_legend.set_axis_off()
    handles = [
        mpatches.Patch(facecolor=ct_colors.get(ct, CELLTYPE_COLORS.get(ct, "#999999")),
                       edgecolor="none", label=ct)
        for ct in present
    ]
    ax_legend.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.0, 1.0),
        frameon=False,
        fontsize=8,
        title="Cell type",
        title_fontsize=8.5,
        handlelength=1.2,
        handleheight=1.2,
        borderpad=0.3,
        labelspacing=0.4,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Panel C – Dotplot
# ──────────────────────────────────────────────────────────────────────────────

def _get_expr_matrix(adata: sc.AnnData, layer: str | None):
    if layer and layer in adata.layers:
        return adata.layers[layer]
    return adata.X


def _build_symbol_index(adata: sc.AnnData) -> dict[str, int]:
    if "gene_name" in adata.var.columns:
        return {g: i for i, g in enumerate(adata.var["gene_name"].astype(str))}
    return {g: i for i, g in enumerate(adata.var.index.astype(str))}


def _compute_dot_stats(
    adata: sc.AnnData,
    all_genes: list[str],
    symbol_idx: dict[str, int],
    groups: list[str],
    groupby: str,
    X,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (fractions, means) arrays of shape (n_groups, n_genes)."""
    n_g, n_gene = len(groups), len(all_genes)
    fracs = np.zeros((n_g, n_gene))
    means = np.zeros((n_g, n_gene))
    obs_group = adata.obs[groupby].astype(str).values

    for gi, gene in enumerate(all_genes):
        if gene not in symbol_idx:
            continue
        col_idx = symbol_idx[gene]
        col = X[:, col_idx]
        if issparse(col):
            col = np.asarray(col.todense()).flatten()
        else:
            col = np.asarray(col).flatten()

        for gri, grp in enumerate(groups):
            mask = obs_group == grp
            vals = col[mask]
            fracs[gri, gi] = (vals > 0).mean() if len(vals) else 0.0
            means[gri, gi] = vals.mean()        if len(vals) else 0.0

    return fracs, means


def plot_dotplot(
    ax_dot, ax_cbar, ax_size,
    adata: sc.AnnData,
    marker_dict: dict[str, list[str]],
    groupby: str = "harmony_leiden",
    layer: str | None = "acosh",
):
    symbol_idx = _build_symbol_index(adata)
    X          = _get_expr_matrix(adata, layer)
    groups     = sorted(adata.obs[groupby].astype(str).unique(), key=lambda x: int(x))
    n_groups   = len(groups)

    # Build ordered gene list and group boundary positions
    all_genes:  list[str]        = []
    boundaries: list[tuple[str, int, int]] = []   # (celltype, x_start, x_end)
    for ct, genes in marker_dict.items():
        valid = [g for g in genes if g in symbol_idx]
        if not valid:
            continue
        x_start = len(all_genes)
        all_genes.extend(valid)
        boundaries.append((ct, x_start, len(all_genes)))

    n_genes = len(all_genes)
    fracs, means = _compute_dot_stats(adata, all_genes, symbol_idx, groups, groupby, X)

    # Standard-scale mean expression per gene (0–1)
    vmin_gene = means.min(axis=0, keepdims=True)
    vmax_gene = means.max(axis=0, keepdims=True)
    denom     = np.where(vmax_gene - vmin_gene == 0, 1.0, vmax_gene - vmin_gene)
    means_s   = (means - vmin_gene) / denom

    # ── Draw background grid ────────────────────────────────────────────────
    ax_dot.set_facecolor("#f7f7f7")
    for xi in range(n_genes):
        ax_dot.axvline(xi, color="white", lw=0.45, zorder=1)
    for yi in range(n_groups):
        ax_dot.axhline(yi, color="white", lw=0.45, zorder=1)

    # ── Draw dots ───────────────────────────────────────────────────────────
    cmap_fn = plt.cm.get_cmap(DOT_CMAP)
    norm    = Normalize(vmin=0, vmax=1)

    for gi in range(n_genes):
        for gri in range(n_groups):
            frac = fracs[gri, gi]
            if frac < 0.005:
                continue
            size  = frac * MAX_DOT_PX
            color = cmap_fn(norm(means_s[gri, gi]))
            ax_dot.scatter(gi, gri, s=size, c=[color],
                           edgecolors="none", zorder=3)

    # ── Cell-type group separators & top labels ──────────────────────────────
    for ct, x_start, x_end in boundaries:
        if x_start > 0:
            ax_dot.axvline(x_start - 0.5, color="#555555", lw=0.9, zorder=4)
        mid = (x_start + x_end - 1) / 2
        ax_dot.text(
            mid, n_groups + 0.55, ct,
            ha="center", va="bottom", fontsize=7.5, fontweight="bold",
            rotation=35, rotation_mode="anchor",
        )

    # ── Axis formatting ──────────────────────────────────────────────────────
    ax_dot.set_xticks(range(n_genes))
    ax_dot.set_xticklabels(all_genes, rotation=90, ha="center", fontsize=7)
    ax_dot.set_yticks(range(n_groups))
    ax_dot.set_yticklabels(groups, fontsize=7.5)
    ax_dot.set_xlim(-0.6, n_genes - 0.4)
    ax_dot.set_ylim(-0.6, n_groups + 1.8)
    ax_dot.invert_yaxis()
    ax_dot.set_xlabel("")
    ax_dot.set_ylabel("Leiden cluster", fontsize=AXIS_FS)
    ax_dot.tick_params(axis="x", which="both", length=0)
    ax_dot.tick_params(axis="y", which="both", length=0)
    ax_dot.spines["top"].set_visible(False)
    ax_dot.spines["right"].set_visible(False)
    ax_dot.spines["left"].set_visible(False)
    ax_dot.spines["bottom"].set_visible(False)
    _label(ax_dot, "C")

    # ── Colorbar ─────────────────────────────────────────────────────────────
    sm = ScalarMappable(cmap=DOT_CMAP, norm=norm)
    sm.set_array([])
    cb = plt.colorbar(sm, cax=ax_cbar)
    cb.set_label("Mean expression\n(scaled per gene)", fontsize=7)
    cb.ax.tick_params(labelsize=6.5)

    # ── Size legend ───────────────────────────────────────────────────────────
    ax_size.set_axis_off()
    frac_levels = [0.20, 0.50, 0.80, 1.00]
    labels      = ["20%", "50%", "80%", "100%"]
    y_pos       = np.linspace(0.82, 0.08, len(frac_levels))
    for frac, label, yp in zip(frac_levels, labels, y_pos):
        ax_size.scatter(
            0.35, yp, s=frac * MAX_DOT_PX,
            c="grey", edgecolors="none",
            transform=ax_size.transAxes,
            clip_on=False,
        )
        ax_size.text(
            0.72, yp, label,
            ha="left", va="center", fontsize=6.5,
            transform=ax_size.transAxes,
        )
    ax_size.text(
        0.35, 0.96, "Fraction\nexpressing",
        ha="center", va="bottom", fontsize=7,
        transform=ax_size.transAxes,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {INPUT_H5AD} ...")
    adata = sc.read_h5ad(INPUT_H5AD)
    print(adata)

    if "X_umap" not in adata.obsm:
        raise KeyError("adata.obsm['X_umap'] not found")
    if "harmony_leiden" not in adata.obs.columns:
        raise KeyError("adata.obs['harmony_leiden'] not found")
    if "final_high_level_celltype_10" not in adata.obs.columns:
        raise KeyError("adata.obs['final_high_level_celltype_10'] not found")

    print(f"Loading markers from {MARKER_JSON} ...")
    with open(MARKER_JSON, encoding="utf-8") as f:
        marker_dict: dict[str, list[str]] = json.load(f)
    # Preserve CELLTYPE_ORDER (exclude Unknown which has no markers)
    ordered_marker_dict = {
        ct: marker_dict[ct]
        for ct in CELLTYPE_ORDER
        if ct in marker_dict
    }

    # ── Figure layout ─────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(18, 15))
    fig.patch.set_facecolor("white")

    outer = gridspec.GridSpec(
        2, 1,
        height_ratios=[4.8, 8.8],
        hspace=0.38,
        figure=fig,
    )

    # Top row: A (leiden) | B (celltype) | B_legend
    top_gs = gridspec.GridSpecFromSubplotSpec(
        1, 3,
        subplot_spec=outer[0],
        width_ratios=[5, 5, 1.2],
        wspace=0.12,
    )
    ax_leiden   = fig.add_subplot(top_gs[0])
    ax_celltype = fig.add_subplot(top_gs[1])
    ax_legend   = fig.add_subplot(top_gs[2])

    # Bottom row: C (dotplot) | cbar | size legend
    bot_gs = gridspec.GridSpecFromSubplotSpec(
        1, 3,
        subplot_spec=outer[1],
        width_ratios=[15.5, 0.35, 1.0],
        wspace=0.04,
    )
    ax_dot  = fig.add_subplot(bot_gs[0])
    ax_cbar = fig.add_subplot(bot_gs[1])
    ax_size = fig.add_subplot(bot_gs[2])

    # ── Draw panels ───────────────────────────────────────────────────────────
    print("Drawing Panel A (leiden UMAP) ...")
    plot_leiden_umap(ax_leiden, adata)

    print("Drawing Panel B (celltype UMAP) ...")
    plot_celltype_umap(ax_celltype, adata, ax_legend)

    print("Drawing Panel C (dotplot) ...")
    plot_dotplot(ax_dot, ax_cbar, ax_size, adata, ordered_marker_dict)

    # ── Save ──────────────────────────────────────────────────────────────────
    for out_path in [OUT_PNG, OUT_PDF]:
        fig.savefig(out_path, dpi=300, bbox_inches="tight", facecolor="white")
        print(f"saved: {out_path}")

    plt.close(fig)


if __name__ == "__main__":
    main()
