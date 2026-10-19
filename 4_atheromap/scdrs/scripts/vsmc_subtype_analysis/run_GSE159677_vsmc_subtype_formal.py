#!/usr/bin/env python3
"""
Formal VSMC-specific subtyping + scDRS overlay for GSE159677.

This version differs from the exploratory script in three important ways:
1. VSMC-specific reclustering is done within the VSMC subset:
   HVG -> PCA -> Harmony -> neighbors -> UMAP -> Leiden
2. Marker genes are mapped to features through gene symbols with duplicate
   feature resolution, instead of silently taking the last duplicated symbol.
3. Automatic labeling only uses primary VSMC states from the manual marker
   table. Synthetic/Foamy are kept as auxiliary reference scores.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os

import harmonypy as hm
import numpy as np
import pandas as pd
import scanpy as sc
from matplotlib import pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from scipy import sparse


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"
SCDRS_DIR = WORK_DIR / "scdrs_out"
META_DIR = WORK_DIR / "metadata"

for folder in [MERGED_DIR, PLOT_DIR, META_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, dpi_save=200, frameon=False)


PRIMARY_REPORT_NAMES = {
    "Contractile": "Contractile VSMC",
    "Fibromyocyte": "Fibroblast-like VSMC",
    "Modulated": "Modulated VSMC",
}

AUXILIARY_REPORT_NAMES = {
    "Synthetic": "Synthetic VSMC",
    "Foamy": "Foamy VSMC",
}

FALLBACK_MARKERS = {
    "Contractile": {
        "positive": ["MYH11", "TAGLN", "ACTA2", "MYLK", "MYOCD", "CNN1", "MYL9", "TPM2", "RGS5"],
        "negative": [],
        "source": "fallback_manual",
    },
    "Fibromyocyte": {
        "positive": ["TCF21", "TNFRSF11B", "COL1A1", "DCN", "FN1", "MGP", "BGN", "LUM", "MMP2", "ASPN", "VCAN", "CCN3", "THBS2"],
        "negative": ["MYH11", "MYOCD"],
        "source": "fallback_manual",
    },
    "Modulated": {
        "positive": ["DLX6-AS1", "SOST", "SUCNR1", "PTN", "ENPP2"],
        "negative": [],
        "source": "fallback_manual",
    },
    "Synthetic": {
        "positive": ["MYH10", "ICAM1", "SPP1", "MMP3", "TIMP1", "MMP7", "MMP9"],
        "negative": ["MYH11", "TAGLN", "ACTA2", "CNN1"],
        "source": "fallback_manual",
    },
    "Foamy": {
        "positive": ["CD68", "CD36", "LGALS3", "ACTA2"],
        "negative": [],
        "source": "fallback_manual",
    },
}

SUBTYPE_COLORS = {
    "Contractile": "#4F83C4",
    "Fibromyocyte": "#77AE6F",
    "Modulated": "#E9963A",
    "Intermediate": "#A6A6A6",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", default="z_score")
    parser.add_argument("--resolution", type=float, default=0.6)
    parser.add_argument("--batch-key", default="patient")
    parser.add_argument("--n-top-genes", type=int, default=2000)
    parser.add_argument("--n-neighbors", type=int, default=15)
    parser.add_argument("--min-best-z", type=float, default=0.20)
    parser.add_argument("--min-margin-z", type=float, default=0.10)
    parser.add_argument("--neg-weight", type=float, default=0.30)
    parser.add_argument(
        "--h5ad-file",
        type=Path,
        default=MERGED_DIR / "GSE159677_harmony_highlevel_annotated_final.h5ad",
    )
    parser.add_argument(
        "--score-file",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--marker-tsv",
        type=Path,
        default=META_DIR / "final_report_marker_manual.tsv",
    )
    return parser.parse_args()


def split_markers(text: object) -> list[str]:
    if pd.isna(text):
        return []
    values = [x.strip() for x in str(text).split(",")]
    return [x for x in values if x and x.lower() not in {"nan", "none"}]


def load_marker_sets(marker_tsv: Path) -> dict[str, dict[str, object]]:
    marker_sets = {}
    if marker_tsv.exists():
        df = pd.read_csv(marker_tsv, sep="\t")
        report_map = {
            **PRIMARY_REPORT_NAMES,
            **AUXILIARY_REPORT_NAMES,
        }
        for subtype, report_name in report_map.items():
            hit = df[df["report_name"].astype(str) == report_name]
            if hit.empty:
                continue
            row = hit.iloc[0]
            pos = split_markers(row.get("core_markers")) + split_markers(row.get("supporting_markers"))
            neg = split_markers(row.get("negative_markers"))
            marker_sets[subtype] = {
                "positive": list(dict.fromkeys(pos)),
                "negative": list(dict.fromkeys(neg)),
                "source": report_name,
            }

    for subtype, fallback in FALLBACK_MARKERS.items():
        if subtype not in marker_sets:
            marker_sets[subtype] = fallback

    return marker_sets


def choose_expression_matrix(adata: sc.AnnData):
    if "acosh" in adata.layers:
        return adata.layers["acosh"], "acosh"
    return adata.X, "X"


def get_gene_symbol_series(adata: sc.AnnData) -> pd.Series:
    if "gene_name" in adata.var.columns:
        symbols = adata.var["gene_name"].astype(str).copy()
        symbols = symbols.replace({"": np.nan, "nan": np.nan, "None": np.nan})
        fallback = pd.Series(adata.var_names.astype(str), index=adata.var_names)
        symbols = symbols.fillna(fallback)
    else:
        symbols = pd.Series(adata.var_names.astype(str), index=adata.var_names)
    return symbols.astype(str)


def _to_1d(array_like) -> np.ndarray:
    if sparse.issparse(array_like):
        return np.asarray(array_like.toarray()).ravel()
    return np.asarray(array_like).ravel()


def build_feature_table(adata: sc.AnnData) -> pd.DataFrame:
    gene_symbols = get_gene_symbol_series(adata)
    count_layer = adata.layers["raw_counts"] if "raw_counts" in adata.layers else adata.X
    expr_layer, expr_layer_name = choose_expression_matrix(adata)

    detected = _to_1d((count_layer > 0).sum(axis=0))
    total_counts = _to_1d(count_layer.sum(axis=0))
    mean_expr = _to_1d(expr_layer.mean(axis=0))

    feature_df = pd.DataFrame(
        {
            "var_name": adata.var_names.astype(str),
            "gene_symbol": gene_symbols.values,
            "n_detected": detected,
            "total_counts": total_counts,
            f"mean_{expr_layer_name}": mean_expr,
        }
    )
    feature_df = feature_df.sort_values(
        ["gene_symbol", "n_detected", "total_counts", f"mean_{expr_layer_name}", "var_name"],
        ascending=[True, False, False, False, True],
    )
    return feature_df


def map_markers_to_features(
    adata: sc.AnnData, marker_sets: dict[str, dict[str, object]]
) -> tuple[dict[str, str], pd.DataFrame]:
    feature_df = build_feature_table(adata)
    top_feature = feature_df.drop_duplicates(subset=["gene_symbol"], keep="first").copy()
    symbol_to_var = dict(zip(top_feature["gene_symbol"], top_feature["var_name"]))

    rows = []
    for subtype, cfg in marker_sets.items():
        for role in ["positive", "negative"]:
            for gene in cfg[role]:
                var_name = symbol_to_var.get(gene)
                matched = var_name is not None
                row = {
                    "subtype": subtype,
                    "role": role,
                    "gene_symbol": gene,
                    "matched": matched,
                    "source": cfg["source"],
                    "var_name": var_name if matched else np.nan,
                }
                if matched:
                    meta_row = top_feature[top_feature["gene_symbol"] == gene].iloc[0]
                    row["n_detected"] = int(meta_row["n_detected"])
                    row["total_counts"] = float(meta_row["total_counts"])
                rows.append(row)
    mapping_df = pd.DataFrame(rows)
    return symbol_to_var, mapping_df


def score_gene_set(
    adata: sc.AnnData,
    genes: list[str],
    symbol_to_var: dict[str, str],
    score_name: str,
):
    var_ids = [symbol_to_var[g] for g in genes if g in symbol_to_var]
    if len(var_ids) >= 2:
        sc.tl.score_genes(
            adata,
            gene_list=var_ids,
            score_name=score_name,
            ctrl_size=min(50, len(var_ids) * 5),
            use_raw=False,
        )
    elif len(var_ids) == 1:
        X, _ = choose_expression_matrix(adata)
        idx = adata.var_names.get_loc(var_ids[0])
        if sparse.issparse(X):
            vals = np.asarray(X[:, idx].toarray()).ravel()
        else:
            vals = np.asarray(X[:, idx]).ravel()
        adata.obs[score_name] = vals - float(vals.mean())
    else:
        adata.obs[score_name] = 0.0
    return len(var_ids), len(genes)


def score_marker_sets(
    adata: sc.AnnData,
    marker_sets: dict[str, dict[str, object]],
    symbol_to_var: dict[str, str],
    neg_weight: float,
):
    primary_names = list(PRIMARY_REPORT_NAMES.keys())
    auxiliary_names = list(AUXILIARY_REPORT_NAMES.keys())

    for subtype in primary_names + auxiliary_names:
        cfg = marker_sets[subtype]
        prefix = "score" if subtype in primary_names else "aux_score"
        base_col = f"{prefix}_{subtype}"
        n_found, n_total = score_gene_set(adata, cfg["positive"], symbol_to_var, base_col)
        print(f"  {base_col}: {n_found}/{n_total} positive markers found")

        if cfg["negative"]:
            neg_col = f"{base_col}_neg"
            n_neg_found, n_neg_total = score_gene_set(adata, cfg["negative"], symbol_to_var, neg_col)
            print(f"  {neg_col}: {n_neg_found}/{n_neg_total} negative markers found")
            adata.obs[base_col] = adata.obs[base_col] - neg_weight * adata.obs[neg_col]


def run_subset_embedding(
    adata_vsmc: sc.AnnData,
    batch_key: str,
    n_top_genes: int,
    n_neighbors: int,
    resolution: float,
):
    adata_embed = adata_vsmc.copy()
    expr_layer, _ = choose_expression_matrix(adata_embed)
    adata_embed.X = expr_layer.copy() if hasattr(expr_layer, "copy") else expr_layer

    if "raw_counts" not in adata_embed.layers:
        raise ValueError(
            "run_subset_embedding requires adata.layers['raw_counts'] because "
            "flavor='seurat_v3' HVG selection must run on raw counts."
        )

    hvg_kwargs = {
        "n_top_genes": n_top_genes,
        "flavor": "seurat_v3",
        "layer": "raw_counts",
    }
    if batch_key in adata_embed.obs.columns and adata_embed.obs[batch_key].nunique() > 1:
        hvg_kwargs["batch_key"] = batch_key

    sc.pp.highly_variable_genes(adata_embed, **hvg_kwargs)
    adata_embed = adata_embed[:, adata_embed.var["highly_variable"]].copy()
    sc.pp.scale(adata_embed, max_value=10)
    sc.tl.pca(adata_embed, svd_solver="arpack")

    if batch_key in adata_embed.obs.columns and adata_embed.obs[batch_key].nunique() > 1:
        X_pca = np.asarray(adata_embed.obsm["X_pca"], dtype=np.float64)
        meta = adata_embed.obs[[batch_key]].copy()
        ho = hm.run_harmony(X_pca, meta, vars_use=[batch_key], max_iter_harmony=20)
        Z = np.asarray(ho.Z_corr)
        if Z.shape[0] == adata_embed.n_obs:
            X_harmony = Z
        elif Z.shape[1] == adata_embed.n_obs:
            X_harmony = Z.T
        else:
            raise ValueError(f"Unexpected Harmony output shape: {Z.shape}")
    else:
        X_harmony = np.asarray(adata_embed.obsm["X_pca"], dtype=np.float64)

    adata_embed.obsm["X_pca_harmony_vsmc"] = X_harmony
    sc.pp.neighbors(
        adata_embed,
        use_rep="X_pca_harmony_vsmc",
        n_neighbors=n_neighbors,
        metric="cosine",
        key_added="vsmc_neighbors",
    )
    sc.tl.umap(adata_embed, neighbors_key="vsmc_neighbors", random_state=0)
    sc.tl.leiden(
        adata_embed,
        resolution=resolution,
        key_added="vsmc_leiden",
        neighbors_key="vsmc_neighbors",
        random_state=0,
    )

    adata_vsmc.obs["vsmc_leiden"] = adata_embed.obs["vsmc_leiden"].astype(str).values
    adata_vsmc.obsm["X_umap_vsmc"] = adata_embed.obsm["X_umap"].copy()
    adata_vsmc.obsm["X_umap"] = adata_embed.obsm["X_umap"].copy()
    adata_vsmc.obsm["X_pca_harmony_vsmc"] = adata_embed.obsm["X_pca_harmony_vsmc"].copy()


def assign_subtypes(
    adata_vsmc: sc.AnnData,
    trait_key: str,
    min_best_z: float,
    min_margin_z: float,
) -> pd.DataFrame:
    primary_names = list(PRIMARY_REPORT_NAMES.keys())
    score_cols = [f"score_{name}" for name in primary_names]

    for col in score_cols:
        vals = adata_vsmc.obs[col].astype(float)
        std = float(vals.std(ddof=0))
        z_col = f"{col}_z"
        if std == 0 or np.isnan(std):
            adata_vsmc.obs[z_col] = 0.0
        else:
            adata_vsmc.obs[z_col] = (vals - float(vals.mean())) / std

    z_cols = [f"{col}_z" for col in score_cols]
    aux_cols = [f"aux_score_{name}" for name in AUXILIARY_REPORT_NAMES]

    cluster_labels = {}
    summary_rows = []
    clusters = sorted(adata_vsmc.obs["vsmc_leiden"].astype(str).unique(), key=int)
    for cluster in clusters:
        mask = adata_vsmc.obs["vsmc_leiden"].astype(str) == cluster
        z_means = adata_vsmc.obs.loc[mask, z_cols].mean().values
        raw_means = adata_vsmc.obs.loc[mask, score_cols].mean().values

        best_idx = int(np.argmax(z_means))
        order = np.argsort(z_means)
        second_idx = int(order[-2]) if len(order) > 1 else best_idx
        best_label = primary_names[best_idx]
        best_z = float(z_means[best_idx])
        margin_z = float(best_z - z_means[second_idx])

        if best_z < min_best_z or margin_z < min_margin_z:
            best_label = "Intermediate"

        cluster_labels[cluster] = best_label
        row = {
            "vsmc_leiden": cluster,
            "n_cells": int(mask.sum()),
            "assigned_label": best_label,
            "best_mean_z": round(best_z, 4),
            "margin_z": round(margin_z, 4),
            "scdrs_mean": round(float(adata_vsmc.obs.loc[mask, trait_key].mean()), 4),
            "scdrs_median": round(float(adata_vsmc.obs.loc[mask, trait_key].median()), 4),
            "scdrs_frac_gt_1p65": round(float((adata_vsmc.obs.loc[mask, trait_key] > 1.65).mean()), 4),
        }
        for i, subtype in enumerate(primary_names):
            row[f"mean_score_{subtype}"] = round(float(raw_means[i]), 4)
            row[f"mean_z_{subtype}"] = round(float(z_means[i]), 4)
        for aux_col in aux_cols:
            row[aux_col] = round(float(adata_vsmc.obs.loc[mask, aux_col].mean()), 4)
        summary_rows.append(row)

    adata_vsmc.obs["vsmc_subtype"] = (
        adata_vsmc.obs["vsmc_leiden"].astype(str).map(cluster_labels).astype("category")
    )
    return pd.DataFrame(summary_rows)


def sanitize_obs_for_h5ad(adata: sc.AnnData):
    for col in adata.obs.columns:
        series = adata.obs[col]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            adata.obs[col] = series.where(series.notna(), "").astype(str)


def load_scdrs_score_table(score_path: Path) -> pd.DataFrame:
    df = pd.read_csv(score_path, sep="\t")
    if "cell_id" in df.columns:
        df = df.set_index("cell_id")
    elif "cell" in df.columns:
        df = df.set_index("cell")
    else:
        df = df.set_index(df.columns[0])
    df.index = df.index.astype(str)
    return df


def choose_norm_score_column(score_df: pd.DataFrame) -> str:
    for col in ["norm_score", "z_score_norm", "z_score_norm_score", "zscore", "score"]:
        if col in score_df.columns:
            return col
    raise KeyError(f"Could not identify norm-score column from: {score_df.columns.tolist()}")


def plot_panels(adata_vsmc: sc.AnnData, trait_key: str, out_png: Path):
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.2))

    ax1 = axes[0]
    subtype_order = [x for x in ["Contractile", "Fibromyocyte", "Modulated", "Intermediate"] if x in adata_vsmc.obs["vsmc_subtype"].cat.categories]
    for subtype in subtype_order:
        mask = adata_vsmc.obs["vsmc_subtype"] == subtype
        coords = adata_vsmc.obsm["X_umap_vsmc"][mask]
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
    ax1.set_title("VSMC Specific Labels")
    ax1.set_xlabel("UMAP1")
    ax1.set_ylabel("UMAP2")
    ax1.legend(frameon=False, fontsize=9, markerscale=2.5, loc="best")

    ax2 = axes[1]
    scores = adata_vsmc.obs[trait_key].astype(float).values
    lo = float(np.nanpercentile(scores, 2))
    hi = float(np.nanpercentile(scores, 98))
    vabs = max(abs(lo), abs(hi))
    norm = TwoSlopeNorm(vmin=-vabs, vcenter=0.0, vmax=vabs)
    order = np.argsort(np.abs(scores))
    coords = adata_vsmc.obsm["X_umap_vsmc"][order]
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
    ax2.set_title(trait_key)
    ax2.set_xlabel("UMAP1")
    ax2.set_ylabel("UMAP2")
    fig.colorbar(sca, ax=ax2, fraction=0.046, pad=0.04)

    plt.tight_layout()
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main():
    args = parse_args()
    trait = args.trait
    score_path = args.score_file or (SCDRS_DIR / f"{trait}.full_score.gz")

    print("Loading annotated object ...")
    adata = sc.read_h5ad(args.h5ad_file)

    print("Subsetting VSMC cells ...")
    adata_vsmc = adata[adata.obs["final_high_level_celltype_10"].astype(str) == "VSMC"].copy()
    print(f"  VSMC cells: {adata_vsmc.n_obs}")

    expr_layer, expr_layer_name = choose_expression_matrix(adata_vsmc)
    adata_vsmc.X = expr_layer.copy() if hasattr(expr_layer, "copy") else expr_layer
    print(f"  Expression layer used for scoring/embedding: {expr_layer_name}")

    print("Loading scDRS score table ...")
    score_df = load_scdrs_score_table(score_path)
    common = adata_vsmc.obs_names.intersection(score_df.index)
    adata_vsmc = adata_vsmc[common].copy()
    score_df = score_df.loc[common]
    norm_col = choose_norm_score_column(score_df)
    trait_key = f"{trait}_norm_score"
    adata_vsmc.obs[trait_key] = score_df[norm_col].astype(float).values
    print(f"  Overlap with scDRS score table: {adata_vsmc.n_obs} cells")

    print("Loading marker sets ...")
    marker_sets = load_marker_sets(args.marker_tsv)
    symbol_to_var, mapping_df = map_markers_to_features(adata_vsmc, marker_sets)
    out_mapping = MERGED_DIR / f"GSE159677_vsmc_marker_feature_mapping_{trait}.csv"
    mapping_df.to_csv(out_mapping, index=False)
    print(f"  Marker mapping saved: {out_mapping}")

    print("Scoring VSMC subtype programs ...")
    score_marker_sets(adata_vsmc, marker_sets, symbol_to_var, neg_weight=args.neg_weight)

    print("Running VSMC-specific HVG/PCA/Harmony/UMAP/Leiden ...")
    run_subset_embedding(
        adata_vsmc,
        batch_key=args.batch_key,
        n_top_genes=args.n_top_genes,
        n_neighbors=args.n_neighbors,
        resolution=args.resolution,
    )

    print("Assigning cluster labels ...")
    summary_df = assign_subtypes(
        adata_vsmc,
        trait_key=trait_key,
        min_best_z=args.min_best_z,
        min_margin_z=args.min_margin_z,
    )
    out_summary = MERGED_DIR / f"GSE159677_vsmc_subtype_summary_{trait}.csv"
    summary_df.to_csv(out_summary, index=False)
    print(f"  Summary saved: {out_summary}")
    print(summary_df.to_string(index=False))

    print("\nSubtype distribution:")
    counts = adata_vsmc.obs["vsmc_subtype"].value_counts()
    for label, n in counts.items():
        frac = n / adata_vsmc.n_obs * 100
        print(f"  {label:<14s} {n:>5d}  ({frac:.1f}%)")

    print("\nscDRS score by subtype:")
    for label in adata_vsmc.obs["vsmc_subtype"].cat.categories:
        mask = adata_vsmc.obs["vsmc_subtype"] == label
        vals = adata_vsmc.obs.loc[mask, trait_key]
        print(
            f"  {label:<14s} mean={vals.mean():+.3f}  median={vals.median():+.3f}  "
            f"frac>1.65={(vals > 1.65).mean():.3f}"
        )

    out_png = PLOT_DIR / f"GSE159677_vsmc_subtype_scdrs_umap_{trait}.png"
    plot_panels(adata_vsmc, trait_key, out_png)
    print(f"  Plot saved: {out_png}")

    sanitize_obs_for_h5ad(adata_vsmc)
    out_h5ad = MERGED_DIR / f"GSE159677_vsmc_subtyped_{trait}.h5ad"
    adata_vsmc.write_h5ad(out_h5ad, compression="gzip")
    print(f"  H5AD saved: {out_h5ad}")


if __name__ == "__main__":
    main()
