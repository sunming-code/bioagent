#!/usr/bin/env python3
"""
Characterise the Unknown leiden cluster (cluster 17) in GSE159677.

Four-panel figure:
  Panel A – QC metrics: mt_frac / n_genes / n_counts, cluster 17 highlighted
  Panel B – Dotplot: known lineage markers + activation genes across all clusters
  Panel C – Feature UMAPs: PTPRC, CD69, MT-CO1, NKG7
  Panel D – Cluster-17 internal scatter: mt_frac vs n_genes, coloured by condition

Outputs:
  plots/GSE159677_unknown_cluster_qc.png / .pdf
  plots/GSE159677_unknown_cluster_feature_umap.png / .pdf
"""

from __future__ import annotations

from pathlib import Path
import os

import matplotlib.gridspec as gridspec
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
PLOT_DIR    = WORK_DIR / "plots"

INPUT_H5AD  = MERGED_DIR / "GSE159677_harmony_highlevel_annotated_final.h5ad"
DGE_CSV     = MERGED_DIR / "GSE159677_harmony_leiden_wilcoxon_dge.csv"

UNKNOWN_CLUSTER = "17"

# Genes of interest for Panel B dotplot
LINEAGE_GENES = {
    "T-cell":    ["CD3D", "CD3E", "TRAC"],
    "NK-cell":   ["NKG7", "KLRD1", "GNLY"],
    "B-cell":    ["MS4A1", "CD79A"],
    "Mast-cell": ["KIT", "CPA3"],
    "Activation":["CD69", "PTPRC", "CXCR4", "CCL4"],
    "Mito":      ["MT-CO1", "MT-ND1"],
}

# Feature genes for Panel C
FEATURE_GENES = ["PTPRC", "CD69", "MT-CO1", "NKG7"]

AXIS_FS  = 9
DOT_CMAP = "Reds"
MAX_DOT  = 200


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_expr(adata: sc.AnnData, gene: str, layer: str = "acosh") -> np.ndarray:
    if "gene_name" in adata.var.columns:
        idx = adata.var[adata.var["gene_name"].astype(str) == gene].index
    else:
        idx = adata.var[adata.var.index.astype(str) == gene].index
    if len(idx) == 0:
        return np.zeros(adata.n_obs)
    col_pos = adata.var.index.get_loc(idx[0])
    mat = adata.layers[layer] if layer in adata.layers else adata.X
    col = mat[:, col_pos]
    if issparse(col):
        col = np.asarray(col.todense()).flatten()
    return np.asarray(col).flatten()


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
            means[gri, gi] = vals.mean() if len(vals) else 0
    return fracs, means


def _spine_off(ax, sides=("top", "right")):
    for s in sides:
        ax.spines[s].set_visible(False)


def _panel_label(ax, letter):
    ax.text(-0.08, 1.06, letter, transform=ax.transAxes,
            fontsize=13, fontweight="bold", va="top", ha="left")


# ─────────────────────────────────────────────────────────────────────────────
# Panel A – QC violin (mt_frac, n_genes, n_counts)
# ─────────────────────────────────────────────────────────────────────────────

def plot_qc_panel(axes, adata: sc.AnnData):
    groups = sorted(adata.obs["harmony_leiden"].astype(str).unique(), key=lambda x: int(x))
    metrics = [("mt_frac", "MT fraction"), ("n_genes", "# genes"), ("n_counts", "# UMIs")]

    for ax, (col, label) in zip(axes, metrics):
        data_list = []
        positions = []
        colors    = []
        for i, grp in enumerate(groups):
            mask = adata.obs["harmony_leiden"].astype(str) == grp
            data_list.append(adata.obs.loc[mask, col].values.astype(float))
            positions.append(i)
            colors.append("#E74C3C" if grp == UNKNOWN_CLUSTER else "#AABBCC")

        parts = ax.violinplot(data_list, positions=positions,
                              showmedians=True, showextrema=False,
                              widths=0.75)
        for pc, color in zip(parts["bodies"], colors):
            pc.set_facecolor(color)
            pc.set_alpha(0.75)
            pc.set_edgecolor("none")
        parts["cmedians"].set_color("black")
        parts["cmedians"].set_linewidth(1.0)

        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels(groups, fontsize=6.5, rotation=90)
        ax.set_ylabel(label, fontsize=AXIS_FS)
        ax.tick_params(axis="y", labelsize=AXIS_FS - 1)
        _spine_off(ax)

        # Annotate cluster 17
        unk_pos = groups.index(UNKNOWN_CLUSTER)
        ymax = ax.get_ylim()[1]
        ax.text(unk_pos, ymax * 0.97, "17", ha="center", va="top",
                fontsize=6.5, color="#E74C3C", fontweight="bold")

    axes[0].set_title("QC metrics by cluster  (red = Unknown cluster 17)",
                      fontsize=AXIS_FS, pad=5)
    _panel_label(axes[0], "A")


# ─────────────────────────────────────────────────────────────────────────────
# Panel B – Dotplot
# ─────────────────────────────────────────────────────────────────────────────

def plot_dotplot_panel(ax, ax_cbar, adata: sc.AnnData):
    groups = sorted(adata.obs["harmony_leiden"].astype(str).unique(), key=lambda x: int(x))
    sym_idx = _build_symbol_idx(adata)

    all_genes: list[str] = []
    boundaries: list[tuple[str, int, int]] = []
    for ct, genes in LINEAGE_GENES.items():
        valid = [g for g in genes if g in sym_idx]
        if not valid:
            continue
        x0 = len(all_genes)
        all_genes.extend(valid)
        boundaries.append((ct, x0, len(all_genes)))

    fracs, means = _compute_dot(adata, all_genes, sym_idx, groups, "harmony_leiden")

    # Scale means per gene 0–1
    vmin = means.min(axis=0, keepdims=True)
    vmax = means.max(axis=0, keepdims=True)
    denom = np.where(vmax - vmin == 0, 1.0, vmax - vmin)
    means_s = (means - vmin) / denom

    n_gene, n_grp = len(all_genes), len(groups)
    ax.set_facecolor("#f5f5f5")
    for xi in range(n_gene):
        ax.axvline(xi, color="white", lw=0.4, zorder=1)

    # Highlight row for cluster 17
    if UNKNOWN_CLUSTER in groups:
        unk_yi = groups.index(UNKNOWN_CLUSTER)
        ax.axhspan(unk_yi - 0.5, unk_yi + 0.5, color="#FFE0E0", zorder=0)

    for yi in range(n_grp):
        ax.axhline(yi, color="white", lw=0.4, zorder=1)

    cmap_fn = plt.cm.get_cmap(DOT_CMAP)
    norm    = Normalize(vmin=0, vmax=1)
    for gi in range(n_gene):
        for gri in range(n_grp):
            frac = fracs[gri, gi]
            if frac < 0.01:
                continue
            ax.scatter(gi, gri, s=frac * MAX_DOT,
                       c=[cmap_fn(norm(means_s[gri, gi]))],
                       edgecolors="none", zorder=3)

    # Group separators and labels
    for ct, x0, x1 in boundaries:
        if x0 > 0:
            ax.axvline(x0 - 0.5, color="#555", lw=0.8, zorder=4)
        mid = (x0 + x1 - 1) / 2
        ax.text(mid, n_grp + 0.6, ct, ha="center", va="bottom",
                fontsize=7.5, fontweight="bold", rotation=30, rotation_mode="anchor")

    ax.set_xticks(range(n_gene))
    ax.set_xticklabels(all_genes, rotation=90, fontsize=7.5)
    ax.set_yticks(range(n_grp))
    ax.set_yticklabels(
        [f"→ {g}" if g == UNKNOWN_CLUSTER else g for g in groups],
        fontsize=7,
    )
    # Red label for cluster 17
    if UNKNOWN_CLUSTER in groups:
        unk_yi = groups.index(UNKNOWN_CLUSTER)
        ax.get_yticklabels()[unk_yi].set_color("#E74C3C")
        ax.get_yticklabels()[unk_yi].set_fontweight("bold")

    ax.set_xlim(-0.6, n_gene - 0.4)
    ax.set_ylim(-0.6, n_grp + 1.8)
    ax.invert_yaxis()
    ax.set_ylabel("Leiden cluster", fontsize=AXIS_FS)
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title("Lineage & activation markers across clusters  (pink row = cluster 17)",
                 fontsize=AXIS_FS, pad=5)
    _panel_label(ax, "B")

    sm = ScalarMappable(cmap=DOT_CMAP, norm=norm)
    sm.set_array([])
    cb = plt.colorbar(sm, cax=ax_cbar)
    cb.set_label("Mean expr\n(scaled)", fontsize=7)
    cb.ax.tick_params(labelsize=6)


# ─────────────────────────────────────────────────────────────────────────────
# Panel C – Feature UMAPs
# ─────────────────────────────────────────────────────────────────────────────

def plot_feature_umaps(axes, adata: sc.AnnData):
    coords = adata.obsm["X_umap"]
    # Background: all cells grey
    for ax, gene in zip(axes, FEATURE_GENES):
        expr = _get_expr(adata, gene)
        vmax = np.percentile(expr, 99)
        vmax = max(vmax, 1e-6)

        # Grey background first
        ax.scatter(coords[:, 0], coords[:, 1],
                   s=0.5, c="#DDDDDD", edgecolors="none",
                   rasterized=True, zorder=1)

        # Colour by expression (non-zero on top)
        order = np.argsort(expr)
        sc_plot = ax.scatter(
            coords[order, 0], coords[order, 1],
            s=0.8, c=expr[order], cmap="Reds",
            vmin=0, vmax=vmax,
            edgecolors="none", rasterized=True, zorder=2,
        )
        plt.colorbar(sc_plot, ax=ax, shrink=0.6, pad=0.02,
                     label="acosh expr", format="%.1f").ax.tick_params(labelsize=6)

        # Circle cluster 17 region
        unk_mask = adata.obs["harmony_leiden"].astype(str) == UNKNOWN_CLUSTER
        unk_coords = coords[unk_mask.values]
        if len(unk_coords):
            cx, cy = unk_coords[:, 0].mean(), unk_coords[:, 1].mean()
            ax.plot(cx, cy, "o", ms=12, mfc="none",
                    mec="#E74C3C", mew=1.2, zorder=5)
            ax.text(cx, cy - 1.2, "17", ha="center", va="top",
                    fontsize=7, color="#E74C3C", fontweight="bold")

        ax.set_title(gene, fontsize=AXIS_FS + 1, pad=3)
        ax.set_xlabel("UMAP1", fontsize=AXIS_FS - 1)
        ax.set_ylabel("UMAP2", fontsize=AXIS_FS - 1)
        ax.tick_params(labelsize=AXIS_FS - 2)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)

    axes[0].set_title(f"PTPRC (CD45)", fontsize=AXIS_FS + 1, pad=3)
    _panel_label(axes[0], "C")


# ─────────────────────────────────────────────────────────────────────────────
# Panel D – Cluster 17 internal scatter
# ─────────────────────────────────────────────────────────────────────────────

def plot_internal_scatter(ax, adata: sc.AnnData):
    mask = adata.obs["harmony_leiden"].astype(str) == UNKNOWN_CLUSTER
    sub  = adata.obs.loc[mask.values]

    cond_vals = sub["condition"].astype(str).values
    conds     = sorted(set(cond_vals))
    palette   = {"D": "#E74C3C", "H": "#3498DB"}

    for cond in conds:
        m = cond_vals == cond
        ax.scatter(
            sub.loc[m, "mt_frac"].values,
            sub.loc[m, "n_genes"].values,
            s=8, alpha=0.6,
            c=palette.get(cond, "#999999"),
            edgecolors="none",
            label=cond,
        )

    ax.set_xlabel("MT fraction", fontsize=AXIS_FS)
    ax.set_ylabel("# genes detected", fontsize=AXIS_FS)
    ax.set_title(f"Cluster 17 (Unknown) internal QC  (n={mask.sum()} cells)",
                 fontsize=AXIS_FS, pad=5)
    ax.legend(title="Condition", fontsize=8, title_fontsize=8,
              frameon=False)
    ax.tick_params(labelsize=AXIS_FS - 1)
    _spine_off(ax)

    # Add vertical threshold line at mt_frac = 0.25 (typical QC cutoff)
    ax.axvline(0.25, color="grey", lw=0.8, ls="--", alpha=0.7)
    ax.text(0.26, ax.get_ylim()[1] * 0.97, "mt=0.25",
            fontsize=6.5, color="grey", va="top")

    _panel_label(ax, "D")


# ─────────────────────────────────────────────────────────────────────────────
# Numerical summary
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(adata: sc.AnnData, dge_csv: Path):
    sym_idx = _build_symbol_idx(adata)
    mat     = adata.layers["acosh"] if "acosh" in adata.layers else adata.X
    obs_grp = adata.obs["harmony_leiden"].astype(str).values

    unk_mask = obs_grp == UNKNOWN_CLUSTER
    all_mask = ~unk_mask

    print("\n" + "=" * 60)
    print(f"  Unknown cluster {UNKNOWN_CLUSTER} summary")
    print("=" * 60)
    print(f"  n_cells:  {unk_mask.sum()}")
    print(f"  mt_frac:  median={adata.obs.loc[unk_mask,'mt_frac'].median():.3f}  "
          f"(global median={adata.obs['mt_frac'].median():.3f})")
    print(f"  n_genes:  median={adata.obs.loc[unk_mask,'n_genes'].median():.0f}  "
          f"(global={adata.obs['n_genes'].median():.0f})")

    print("\n  Lineage marker mean expression (acosh):")
    check = {"CD3D": "T-cell", "NKG7": "NK-cell",
             "CD69": "Activation", "PTPRC": "Leukocyte", "MT-CO1": "Mito"}
    for gene, cat in check.items():
        if gene not in sym_idx:
            print(f"    {gene:8s}  NOT FOUND in var")
            continue
        col = mat[:, sym_idx[gene]]
        if issparse(col):
            col = np.asarray(col.todense()).flatten()
        else:
            col = np.asarray(col).flatten()
        mean_unk  = col[unk_mask].mean()
        mean_rest = col[all_mask].mean()
        print(f"    {gene:8s} [{cat:10s}]  cluster17={mean_unk:.3f}  rest={mean_rest:.3f}")

    print("\n  Condition breakdown in cluster 17:")
    for cond, cnt in adata.obs.loc[unk_mask, "condition"].value_counts().items():
        print(f"    {cond}: {cnt} cells")

    print("\n  Interpretation:")
    mt_med = adata.obs.loc[unk_mask, "mt_frac"].median()
    global_mt = adata.obs["mt_frac"].median()
    if mt_med > global_mt * 1.5:
        print("  -> HIGH mt_frac: likely stressed / low-quality cells")
    else:
        print("  -> mt_frac not markedly elevated; may be a real (activated) immune subset")
    print("=" * 60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    PLOT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {INPUT_H5AD} ...")
    adata = sc.read_h5ad(INPUT_H5AD)
    print(adata)

    # ── Figure 1: QC + Dotplot ────────────────────────────────────────────────
    fig1 = plt.figure(figsize=(18, 14))
    fig1.patch.set_facecolor("white")

    outer = gridspec.GridSpec(2, 1, height_ratios=[4, 7], hspace=0.42, figure=fig1)

    # Panel A – three QC violins side by side
    qc_gs  = gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=outer[0], wspace=0.35)
    ax_mt  = fig1.add_subplot(qc_gs[0])
    ax_ng  = fig1.add_subplot(qc_gs[1])
    ax_nc  = fig1.add_subplot(qc_gs[2])
    print("Drawing Panel A (QC violins) ...")
    plot_qc_panel([ax_mt, ax_ng, ax_nc], adata)

    # Panel B – dotplot
    bot_gs  = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=outer[1],
                                               width_ratios=[14, 0.35], wspace=0.04)
    ax_dot  = fig1.add_subplot(bot_gs[0])
    ax_cbar = fig1.add_subplot(bot_gs[1])
    print("Drawing Panel B (dotplot) ...")
    plot_dotplot_panel(ax_dot, ax_cbar, adata)

    for ext in ["png", "pdf"]:
        out = PLOT_DIR / f"GSE159677_unknown_cluster_qc.{ext}"
        fig1.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
        print(f"saved: {out}")
    plt.close(fig1)

    # ── Figure 2: Feature UMAPs + internal scatter ────────────────────────────
    fig2 = plt.figure(figsize=(18, 9))
    fig2.patch.set_facecolor("white")

    gs2 = gridspec.GridSpec(1, 5, figure=fig2, wspace=0.35,
                            width_ratios=[4, 4, 4, 4, 4])
    ax_feats = [fig2.add_subplot(gs2[i]) for i in range(4)]
    ax_int   = fig2.add_subplot(gs2[4])

    print("Drawing Panel C (feature UMAPs) ...")
    plot_feature_umaps(ax_feats, adata)

    print("Drawing Panel D (internal scatter) ...")
    plot_internal_scatter(ax_int, adata)
    _panel_label(ax_int, "D")

    for ext in ["png", "pdf"]:
        out = PLOT_DIR / f"GSE159677_unknown_cluster_feature_umap.{ext}"
        fig2.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
        print(f"saved: {out}")
    plt.close(fig2)

    # ── Numerical summary ─────────────────────────────────────────────────────
    print_summary(adata, DGE_CSV)


if __name__ == "__main__":
    main()
