#!/usr/bin/env python3
"""
VSMC subtype marker dotplot for GSE159677.

Two-panel figure:
  Panel A – Dotplot: vsmc_leiden clusters × top DE markers (top 5 per cluster)
  Panel B – Dotplot: vsmc_leiden clusters × canonical reference markers
             (Contractile / Fibromyocyte / Modulated)

Cluster-to-subtype mapping is annotated on the y-axis.

Outputs:
  plots/GSE159677_vsmc_subtype_dotplot.png / .pdf
"""

from __future__ import annotations

from pathlib import Path
import os

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import scanpy as sc
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from scipy.sparse import issparse

PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR  = WORK_DIR / "merged"
PLOT_DIR    = WORK_DIR / "plots"

INPUT_H5AD  = MERGED_DIR / "GSE159677_vsmc_subtyped_final_z_score.h5ad"
DGE_CSV     = MERGED_DIR / "GSE159677_vsmc_intermediate_top_markers_z_score.csv"

OUT_PNG = PLOT_DIR / "GSE159677_vsmc_subtype_dotplot.png"
OUT_PDF = PLOT_DIR / "GSE159677_vsmc_subtype_dotplot.pdf"

# Canonical reference markers for Panel B
CANONICAL = {
    "Contractile": ["MYH11", "TAGLN", "ACTA2", "CNN1", "MYL9", "TPM2", "RGS5", "MYLK"],
    "Fibromyocyte": ["MGP", "BGN", "FN1", "VCAN", "DCN", "LUM", "ASPN", "COL1A1", "THBS2"],
    "Modulated":   ["DLX6-AS1", "SOST", "SUCNR1", "PTN", "ENPP2"],
}

# Final subtype assignment for each cluster (cluster 7 is removed)
CLUSTER_SUBTYPE = {
    "0": "Contractile",
    "1": "Modulated",
    "2": "Fibromyocyte",
    "3": "Fibromyocyte",
    "4": "Contractile",
    "5": "Fibromyocyte*",   # manual: ECM/secretory program
    "6": "Modulated*",      # manual: APOE/lipid-inflammatory
    "8": "Fibromyocyte",
    "9": "Modulated*",      # manual: IFN/MHC-like
}

SUBTYPE_COLORS = {
    "Contractile":   "#3D7DBB",
    "Fibromyocyte":  "#E07B54",
    "Fibromyocyte*": "#E0A07B",
    "Modulated":     "#6AAB6E",
    "Modulated*":    "#A0CBA3",
}

DOT_CMAP   = "Blues"
MAX_DOT    = 220
AXIS_FS    = 9
TOP_N      = 5   # top DE genes per cluster shown in Panel A


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_symbol_idx(adata: sc.AnnData) -> dict[str, int]:
    if "gene_name" in adata.var.columns:
        return {g: i for i, g in enumerate(adata.var["gene_name"].astype(str))}
    return {g: i for i, g in enumerate(adata.var.index.astype(str))}


def _compute_dot(adata, all_genes, sym_idx, groups, groupby, layer="acosh"):
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
            col = np.asarray(col.todense()).flatten()
        else:
            col = np.asarray(col).flatten()
        for gri, grp in enumerate(groups):
            mask = obs_grp == grp
            vals = col[mask]
            fracs[gri, gi] = (vals > 0).mean() if len(vals) else 0
            means[gri, gi] = vals.mean()        if len(vals) else 0
    return fracs, means


def _draw_dotplot(ax, ax_cbar, ax_size,
                  adata, all_genes, boundaries,
                  groups, groupby,
                  panel_label, title,
                  cmap=DOT_CMAP):
    sym_idx = _build_symbol_idx(adata)
    fracs, means = _compute_dot(adata, all_genes, sym_idx, groups, groupby)

    # Scale means per gene 0–1
    vmin = means.min(axis=0, keepdims=True)
    vmax = means.max(axis=0, keepdims=True)
    denom = np.where(vmax - vmin == 0, 1.0, vmax - vmin)
    means_s = (means - vmin) / denom

    n_gene, n_grp = len(all_genes), len(groups)

    ax.set_facecolor("#f7f7f7")
    for xi in range(n_gene):
        ax.axvline(xi, color="white", lw=0.4, zorder=1)
    for yi in range(n_grp):
        ax.axhline(yi, color="white", lw=0.4, zorder=1)

    # Alternating subtype background bands
    prev_st = None
    band_color = ["#EAF0FB", "#FBF3EA"]
    band_idx = 0
    for gri, grp in enumerate(groups):
        st = CLUSTER_SUBTYPE.get(grp, "")
        st_base = st.replace("*", "")
        if st_base != (prev_st or "").replace("*", ""):
            band_idx = 1 - band_idx
            prev_st = st
        ax.axhspan(gri - 0.5, gri + 0.5, color=band_color[band_idx], zorder=0)

    norm    = Normalize(vmin=0, vmax=1)
    cmap_fn = plt.colormaps[cmap]

    for gi in range(n_gene):
        for gri in range(n_grp):
            frac = fracs[gri, gi]
            if frac < 0.01:
                continue
            ax.scatter(gi, gri, s=frac * MAX_DOT,
                       c=[cmap_fn(norm(means_s[gri, gi]))],
                       edgecolors="none", zorder=3)

    # Group separators & top labels
    for ct, x0, x1 in boundaries:
        if x0 > 0:
            ax.axvline(x0 - 0.5, color="#555", lw=0.9, zorder=4)
        mid = (x0 + x1 - 1) / 2
        ax.text(mid, n_grp + 0.65, ct,
                ha="center", va="bottom", fontsize=7.5, fontweight="bold",
                rotation=30, rotation_mode="anchor")

    # Y-axis labels with subtype annotation
    ytick_labels = []
    for grp in groups:
        st = CLUSTER_SUBTYPE.get(grp, "")
        n  = adata.obs[adata.obs[groupby].astype(str) == grp].shape[0]
        ytick_labels.append(f"{grp}  [{st}]  n={n}")

    ax.set_xticks(range(n_gene))
    ax.set_xticklabels(all_genes, rotation=90, ha="center", fontsize=7.5)
    ax.set_yticks(range(n_grp))
    ax.set_yticklabels(ytick_labels, fontsize=7.5)

    # Colour the y tick labels by subtype
    for gri, grp in enumerate(groups):
        st = CLUSTER_SUBTYPE.get(grp, "")
        color = SUBTYPE_COLORS.get(st, "#333333")
        ax.get_yticklabels()[gri].set_color(color)
        ax.get_yticklabels()[gri].set_fontweight("bold")

    ax.set_xlim(-0.6, n_gene - 0.4)
    ax.set_ylim(-0.6, n_grp + 1.9)
    ax.invert_yaxis()
    ax.set_ylabel("VSMC leiden cluster", fontsize=AXIS_FS)
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(title, fontsize=AXIS_FS, pad=6)

    # Panel label
    ax.text(-0.06, 1.06, panel_label, transform=ax.transAxes,
            fontsize=13, fontweight="bold", va="top", ha="left")

    # Colorbar
    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = plt.colorbar(sm, cax=ax_cbar, orientation="vertical")
    cb.set_label("Mean expr\n(scaled)", fontsize=7)
    cb.ax.tick_params(labelsize=6)

    # Size legend
    ax_size.set_axis_off()
    for frac, label, yp in zip([0.25, 0.50, 0.75, 1.0],
                                ["25%", "50%", "75%", "100%"],
                                np.linspace(0.82, 0.10, 4)):
        ax_size.scatter(0.35, yp, s=frac * MAX_DOT, c="grey",
                        edgecolors="none", transform=ax_size.transAxes, clip_on=False)
        ax_size.text(0.68, yp, label, ha="left", va="center",
                     fontsize=6.5, transform=ax_size.transAxes)
    ax_size.text(0.35, 0.97, "Fraction\nexpressing",
                 ha="center", va="bottom", fontsize=7,
                 transform=ax_size.transAxes)


# ─────────────────────────────────────────────────────────────────────────────
# Build gene lists
# ─────────────────────────────────────────────────────────────────────────────

def build_top_de_genes(dge_csv: Path, top_n: int = TOP_N):
    df = pd.read_csv(dge_csv)
    df["vsmc_leiden"] = df["vsmc_leiden"].astype(str)
    clusters = sorted(df["vsmc_leiden"].unique(), key=lambda x: int(x))

    all_genes: list[str] = []
    boundaries: list[tuple[str, int, int]] = []
    seen: set[str] = set()

    for cl in clusters:
        sub = df[df["vsmc_leiden"] == cl].sort_values("scores", ascending=False)
        genes = [g for g in sub["gene_symbol"].tolist() if g not in seen][:top_n]
        seen.update(genes)
        if not genes:
            continue
        x0 = len(all_genes)
        all_genes.extend(genes)
        boundaries.append((f"cluster {cl}", x0, len(all_genes)))

    return all_genes, boundaries, clusters


def build_canonical_genes():
    all_genes: list[str] = []
    boundaries: list[tuple[str, int, int]] = []
    for ct, genes in CANONICAL.items():
        x0 = len(all_genes)
        all_genes.extend(genes)
        boundaries.append((ct, x0, len(all_genes)))
    return all_genes, boundaries


# ─────────────────────────────────────────────────────────────────────────────
# Legend for subtype colours
# ─────────────────────────────────────────────────────────────────────────────

def _add_subtype_legend(fig, ax_ref):
    handles = [
        mpatches.Patch(color=SUBTYPE_COLORS[k], label=k)
        for k in ["Contractile", "Fibromyocyte", "Fibromyocyte*",
                  "Modulated", "Modulated*"]
    ]
    fig.legend(handles=handles,
               title="Subtype  (* = manual)",
               title_fontsize=8,
               fontsize=7.5,
               loc="lower center",
               ncol=5,
               bbox_to_anchor=(0.5, -0.01),
               frameon=False,
               handlelength=1.2)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {INPUT_H5AD} ...")
    adata = sc.read_h5ad(INPUT_H5AD)
    print(adata)

    groups = sorted(adata.obs["vsmc_leiden"].astype(str).unique(), key=lambda x: int(x))
    print(f"VSMC leiden clusters: {groups}")

    # ── Gene lists ────────────────────────────────────────────────────────────
    top_genes, top_bounds, _ = build_top_de_genes(DGE_CSV, top_n=TOP_N)
    can_genes, can_bounds     = build_canonical_genes()

    print(f"Panel A: {len(top_genes)} genes (top {TOP_N} DE per cluster)")
    print(f"Panel B: {len(can_genes)} canonical reference genes")

    # ── Figure ────────────────────────────────────────────────────────────────
    n_grp = len(groups)
    h_per_row = 0.38          # inch per cluster row
    fig_h = max(14, n_grp * h_per_row * 2 + 5)

    fig = plt.figure(figsize=(20, fig_h))
    fig.patch.set_facecolor("white")

    outer = gridspec.GridSpec(2, 1, figure=fig,
                              height_ratios=[len(top_genes), len(can_genes)],
                              hspace=0.55)

    def _make_row(spec):
        return gridspec.GridSpecFromSubplotSpec(
            1, 3, subplot_spec=spec,
            width_ratios=[len(top_genes if spec == outer[0] else can_genes),
                          0.32, 0.9],
            wspace=0.04,
        )

    # Panel A
    gs_a = _make_row(outer[0])
    ax_a     = fig.add_subplot(gs_a[0])
    ax_a_cb  = fig.add_subplot(gs_a[1])
    ax_a_sz  = fig.add_subplot(gs_a[2])

    print("Drawing Panel A (top DE markers dotplot) ...")
    _draw_dotplot(
        ax_a, ax_a_cb, ax_a_sz,
        adata, top_genes, top_bounds, groups, "vsmc_leiden",
        panel_label="A",
        title=f"Top {TOP_N} DE markers per VSMC leiden cluster (Wilcoxon, one-vs-rest)",
        cmap="Blues",
    )

    # Panel B – override width ratio based on canonical gene count
    gs_b_inner = gridspec.GridSpecFromSubplotSpec(
        1, 3, subplot_spec=outer[1],
        width_ratios=[len(can_genes), 0.32, 0.9],
        wspace=0.04,
    )
    ax_b     = fig.add_subplot(gs_b_inner[0])
    ax_b_cb  = fig.add_subplot(gs_b_inner[1])
    ax_b_sz  = fig.add_subplot(gs_b_inner[2])

    print("Drawing Panel B (canonical reference markers dotplot) ...")
    _draw_dotplot(
        ax_b, ax_b_cb, ax_b_sz,
        adata, can_genes, can_bounds, groups, "vsmc_leiden",
        panel_label="B",
        title="Canonical Contractile / Fibromyocyte / Modulated reference markers",
        cmap="Reds",
    )

    _add_subtype_legend(fig, ax_b)

    for out in [OUT_PNG, OUT_PDF]:
        fig.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
        print(f"saved: {out}")
    plt.close(fig)


if __name__ == "__main__":
    main()
