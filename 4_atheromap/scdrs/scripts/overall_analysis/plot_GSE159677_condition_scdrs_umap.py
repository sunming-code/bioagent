#!/usr/bin/env python3
"""
Plot D vs H scDRS UMAP comparison for GSE159677.

Outputs:
  - plots/GSE159677_condition_scdrs_global_umap_<trait>.png
  - plots/GSE159677_condition_scdrs_vsmc_umap_<trait>.png
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

import numpy as np
import scanpy as sc
from matplotlib import pyplot as plt
from matplotlib.colors import TwoSlopeNorm


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"

sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, frameon=False)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument(
        "--global-h5ad",
        type=Path,
        default=None,
        help="Default: merged/GSE159677_scdrs_<trait>_merged.h5ad",
    )
    parser.add_argument(
        "--vsmc-h5ad",
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


def build_norm(values: np.ndarray) -> TwoSlopeNorm:
    lo = float(np.nanpercentile(values, 2))
    hi = float(np.nanpercentile(values, 98))
    vabs = max(abs(lo), abs(hi), 1e-6)
    return TwoSlopeNorm(vmin=-vabs, vcenter=0.0, vmax=vabs)


def _plot_condition_panel(
    ax,
    coords: np.ndarray,
    scores: np.ndarray,
    condition: np.ndarray,
    target: str,
    norm: TwoSlopeNorm,
    title: str,
):
    mask = condition == target
    ax.scatter(
        coords[:, 0],
        coords[:, 1],
        s=5,
        c="#D9D9D9",
        alpha=0.35,
        edgecolors="none",
        rasterized=True,
    )
    order = np.argsort(np.abs(scores[mask]))
    sub_coords = coords[mask][order]
    sub_scores = scores[mask][order]
    sca = ax.scatter(
        sub_coords[:, 0],
        sub_coords[:, 1],
        s=6,
        c=sub_scores,
        cmap="RdBu_r",
        norm=norm,
        alpha=0.85,
        edgecolors="none",
        rasterized=True,
    )
    ax.set_title(f"{title}\n{target} (n={mask.sum()})")
    ax.set_xlabel("UMAP1")
    ax.set_ylabel("UMAP2")
    return sca


def plot_global_condition_umap(adata: sc.AnnData, trait_col: str, out_png: Path):
    if "X_umap" not in adata.obsm:
        raise KeyError("Global object is missing obsm['X_umap']")
    if "condition" not in adata.obs.columns:
        raise KeyError("Global object is missing obs['condition']")

    coords = adata.obsm["X_umap"]
    scores = adata.obs[trait_col].astype(float).values
    condition = adata.obs["condition"].astype(str).values
    norm = build_norm(scores)

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.4))
    sca = _plot_condition_panel(
        axes[0], coords, scores, condition, "D", norm, "Global scDRS UMAP"
    )
    _plot_condition_panel(
        axes[1], coords, scores, condition, "H", norm, "Global scDRS UMAP"
    )
    fig.colorbar(sca, ax=axes, fraction=0.025, pad=0.02)
    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def get_vsmc_object(global_adata: sc.AnnData, vsmc_h5ad: Path) -> sc.AnnData:
    if vsmc_h5ad.exists():
        adata_vsmc = sc.read_h5ad(vsmc_h5ad)
        if "condition" not in adata_vsmc.obs.columns:
            common = adata_vsmc.obs_names.intersection(global_adata.obs_names)
            adata_vsmc = adata_vsmc[common].copy()
            cond = global_adata.obs.loc[common, "condition"]
            assert len(cond) == len(adata_vsmc), "Duplicate obs_names in global object"
            adata_vsmc.obs["condition"] = cond.astype(str).values
        return adata_vsmc

    mask = global_adata.obs["final_high_level_celltype_10"].astype(str) == "VSMC"
    adata_vsmc = global_adata[mask].copy()
    if "X_umap_vsmc" not in adata_vsmc.obsm:
        if "X_umap" in adata_vsmc.obsm:
            adata_vsmc.obsm["X_umap_vsmc"] = adata_vsmc.obsm["X_umap"].copy()
        else:
            raise KeyError("No VSMC-specific embedding found: neither X_umap_vsmc nor X_umap available")
    return adata_vsmc


def plot_vsmc_condition_umap(adata_vsmc: sc.AnnData, trait_col: str, out_png: Path):
    if "X_umap_vsmc" not in adata_vsmc.obsm:
        raise KeyError("VSMC object is missing obsm['X_umap_vsmc']")
    if "condition" not in adata_vsmc.obs.columns:
        raise KeyError("VSMC object is missing obs['condition']")

    coords = adata_vsmc.obsm["X_umap_vsmc"]
    scores = adata_vsmc.obs[trait_col].astype(float).values
    condition = adata_vsmc.obs["condition"].astype(str).values
    norm = build_norm(scores)

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.4))
    sca = _plot_condition_panel(
        axes[0], coords, scores, condition, "D", norm, "VSMC-specific scDRS UMAP"
    )
    _plot_condition_panel(
        axes[1], coords, scores, condition, "H", norm, "VSMC-specific scDRS UMAP"
    )
    fig.colorbar(sca, ax=axes, fraction=0.025, pad=0.02)
    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    args = parse_args()
    global_h5ad = args.global_h5ad or (MERGED_DIR / f"GSE159677_scdrs_{args.trait}_merged.h5ad")
    vsmc_h5ad = args.vsmc_h5ad or (MERGED_DIR / f"GSE159677_vsmc_subtyped_final_{args.trait}.h5ad")

    global_adata = sc.read_h5ad(global_h5ad)
    trait_col = pick_trait_col(global_adata, args.trait)

    out_global = PLOT_DIR / f"GSE159677_condition_scdrs_global_umap_{args.trait}.png"
    plot_global_condition_umap(global_adata, trait_col, out_global)
    print(f"saved: {out_global}")

    adata_vsmc = get_vsmc_object(global_adata, vsmc_h5ad)
    trait_col_vsmc = pick_trait_col(adata_vsmc, args.trait)
    out_vsmc = PLOT_DIR / f"GSE159677_condition_scdrs_vsmc_umap_{args.trait}.png"
    plot_vsmc_condition_umap(adata_vsmc, trait_col_vsmc, out_vsmc)
    print(f"saved: {out_vsmc}")


if __name__ == "__main__":
    main()
