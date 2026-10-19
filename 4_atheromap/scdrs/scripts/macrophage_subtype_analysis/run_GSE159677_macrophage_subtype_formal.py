#!/usr/bin/env python3
"""
Formal macrophage-specific subtyping + scDRS overlay for GSE159677.

Workflow:
1. Subset high-level Macrophage cells
2. Macrophage-specific reclustering:
   HVG -> PCA -> Harmony -> neighbors -> UMAP -> Leiden
3. Score primary macrophage subtype markers from the manual marker table
4. Assign an automatic subtype label per macrophage Leiden cluster
5. Export summary tables, one-vs-rest DGE, UMAP panel, and a subtype h5ad
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

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

sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, frameon=False)


PRIMARY_SUBTYPES = {
    "C1Q": {
        "report_name": "C1Q macrophage",
        "display_name": "Mac_C1Q",
        "color": "#C94232",
    },
    "HMOX1": {
        "report_name": "HMOX1 macrophage",
        "display_name": "Mac_HMOX1",
        "color": "#8C8C8C",
    },
    "IL10hi": {
        "report_name": "IL10/TNFAIP3 macrophage",
        "display_name": "Mac_IL10hi",
        "color": "#C5B3DE",
    },
    "PLIN2_TREM1": {
        "report_name": "PLIN2hi/TREM1hi macrophage",
        "display_name": "Mac_PLIN2hi/TREM1hi",
        "color": "#49A2CF",
    },
    "S100A8hi": {
        "report_name": "S100A8/IL1B macrophage",
        "display_name": "Mac_S100A8hi",
        "color": "#C7C53B",
    },
    "TREM2hi": {
        "report_name": "TREM2hi macrophage",
        "display_name": "Mac_TREM2hi",
        "color": "#E8B3CF",
    },
}

REFERENCE_SCORES = {
    "IFN_response": {
        "report_name": "IFN-response myeloid",
    },
    "S100A8_low": {
        "report_name": "S100A8/IL1B-low myeloid",
    },
    "M1_like": {
        "report_name": "M1-like macrophage",
    },
    "M2a_like": {
        "report_name": "M2a-like macrophage",
    },
    "M2b_like": {
        "report_name": "M2b-like macrophage",
    },
    "M2c_like": {
        "report_name": "M2c-like macrophage",
    },
    "M2d_like": {
        "report_name": "M2d-like macrophage",
    },
    "Classical_monocyte": {
        "report_name": "Classical monocyte",
    },
    "Nonclassical_monocyte": {
        "report_name": "Nonclassical monocyte",
    },
}

FALLBACK_MARKERS = {
    "C1Q": {
        "positive": ["C1QA", "C1QB", "C1QC", "SELENOP", "FOLR2", "AIF1", "PLTP", "GPR34"],
        "negative": [],
        "source": "fallback_manual",
    },
    "HMOX1": {
        "positive": ["HMOX1", "APOE", "APOC1", "CCL18", "GPNMB", "ACP5", "NUPR1"],
        "negative": [],
        "source": "fallback_manual",
    },
    "IL10hi": {
        "positive": ["IL10", "TNFAIP3", "CCL3", "CCL4", "CXCL3", "GPR183", "IER3", "NFKBIA"],
        "negative": [],
        "source": "fallback_manual",
    },
    "PLIN2_TREM1": {
        "positive": ["PLIN2", "TREM1", "ANGPTL4", "CCL2", "TIMP1", "MIF", "CCL7", "MARCO"],
        "negative": [],
        "source": "fallback_manual",
    },
    "S100A8hi": {
        "positive": ["S100A8", "S100A9", "IL1B", "FCN1", "VCAN", "S100A12", "NAMPT", "LYZ"],
        "negative": [],
        "source": "fallback_manual",
    },
    "TREM2hi": {
        "positive": ["TREM2", "SPP1", "APOE", "LPL", "GPNMB", "MARCO", "FABP5", "APOC1"],
        "negative": [],
        "source": "fallback_manual",
    },
    "IFN_response": {
        "positive": ["RSAD2", "CXCL10", "IFIT3", "ISG15", "MX1", "IFIT1", "IFI44L", "USP18"],
        "negative": [],
        "source": "fallback_manual",
    },
    "S100A8_low": {
        "positive": ["FCN1", "LST1", "S100A8", "S100A9", "PLAC8", "CTSS", "AIF1"],
        "negative": [],
        "source": "fallback_manual",
    },
    "M1_like": {
        "positive": ["IL1B", "IL6", "TNF", "CXCL10", "MARCO"],
        "negative": [],
        "source": "fallback_manual",
    },
    "M2a_like": {
        "positive": ["MRC1", "IL10", "TGFB1", "CCL18", "PPARG"],
        "negative": [],
        "source": "fallback_manual",
    },
    "M2b_like": {
        "positive": ["MRC1", "CD86", "IL1B", "TNF", "IL10"],
        "negative": [],
        "source": "fallback_manual",
    },
    "M2c_like": {
        "positive": ["MRC1", "CD163", "IL10", "TGFB1", "CXCL13"],
        "negative": [],
        "source": "fallback_manual",
    },
    "M2d_like": {
        "positive": ["VEGFA", "IL10"],
        "negative": [],
        "source": "fallback_manual",
    },
    "Classical_monocyte": {
        "positive": ["CD14", "FCGR1A", "SELL", "CCR2", "TNFRSF1A"],
        "negative": ["FCGR3A"],
        "source": "fallback_manual",
    },
    "Nonclassical_monocyte": {
        "positive": ["FCGR3A", "CX3CR1", "IL1RN", "TNFRSF1B", "FCGR2A"],
        "negative": ["CD14"],
        "source": "fallback_manual",
    },
}


def _leiden_sort_key(val: str):
    try:
        return (0, int(val), val)
    except ValueError:
        return (1, 0, val)


def default_marker_tsv() -> Path:
    candidates = [
        META_DIR / "final_report_marker_manual-v2.tsv",
        Path(__file__).resolve().parent / "ath9_manual_annotation_full_markers" / "final_report_marker_manual-v2.tsv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


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
        default=default_marker_tsv(),
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
            **{k: v["report_name"] for k, v in PRIMARY_SUBTYPES.items()},
            **{k: v["report_name"] for k, v in REFERENCE_SCORES.items()},
        }
        for subtype_key, report_name in report_map.items():
            hit = df[df["report_name"].astype(str) == report_name]
            if hit.empty:
                continue
            row = hit.iloc[0]
            pos = split_markers(row.get("core_markers")) + split_markers(row.get("supporting_markers"))
            neg = split_markers(row.get("negative_markers"))
            marker_sets[subtype_key] = {
                "positive": list(dict.fromkeys(pos)),
                "negative": list(dict.fromkeys(neg)),
                "source": report_name,
            }

    for subtype_key, fallback in FALLBACK_MARKERS.items():
        if subtype_key not in marker_sets:
            marker_sets[subtype_key] = fallback
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
    for subtype_key, cfg in marker_sets.items():
        for role in ["positive", "negative"]:
            for gene in cfg[role]:
                var_name = symbol_to_var.get(gene)
                matched = var_name is not None
                row = {
                    "subtype_key": subtype_key,
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
    primary_keys = list(PRIMARY_SUBTYPES.keys())
    aux_keys = list(REFERENCE_SCORES.keys())

    for subtype_key in primary_keys + aux_keys:
        cfg = marker_sets[subtype_key]
        prefix = "score" if subtype_key in primary_keys else "aux_score"
        base_col = f"{prefix}_{subtype_key}"
        n_found, n_total = score_gene_set(adata, cfg["positive"], symbol_to_var, base_col)
        print(f"  {base_col}: {n_found}/{n_total} positive markers found")
        if cfg["negative"]:
            neg_col = f"{base_col}_neg"
            n_neg_found, n_neg_total = score_gene_set(adata, cfg["negative"], symbol_to_var, neg_col)
            print(f"  {neg_col}: {n_neg_found}/{n_neg_total} negative markers found")
            adata.obs[base_col] = adata.obs[base_col] - neg_weight * adata.obs[neg_col]


def run_subset_embedding(
    adata_mac: sc.AnnData,
    batch_key: str,
    n_top_genes: int,
    n_neighbors: int,
    resolution: float,
):
    adata_embed = adata_mac.copy()
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

    adata_embed.obsm["X_pca_harmony_mac"] = X_harmony
    sc.pp.neighbors(
        adata_embed,
        use_rep="X_pca_harmony_mac",
        n_neighbors=n_neighbors,
        metric="cosine",
        key_added="mac_neighbors",
    )
    sc.tl.umap(adata_embed, neighbors_key="mac_neighbors", random_state=0)
    sc.tl.leiden(
        adata_embed,
        resolution=resolution,
        key_added="macrophage_leiden",
        neighbors_key="mac_neighbors",
        random_state=0,
    )

    adata_mac.obs["macrophage_leiden"] = adata_embed.obs["macrophage_leiden"].astype(str).values
    adata_mac.obsm["X_umap_macrophage"] = adata_embed.obsm["X_umap"].copy()
    adata_mac.obsm["X_umap"] = adata_embed.obsm["X_umap"].copy()
    adata_mac.obsm["X_pca_harmony_mac"] = adata_embed.obsm["X_pca_harmony_mac"].copy()


def assign_subtypes(
    adata_mac: sc.AnnData,
    trait_key: str,
    min_best_z: float,
    min_margin_z: float,
) -> pd.DataFrame:
    primary_keys = list(PRIMARY_SUBTYPES.keys())
    score_cols = [f"score_{key}" for key in primary_keys]

    for col in score_cols:
        vals = adata_mac.obs[col].astype(float)
        std = float(vals.std(ddof=0))
        z_col = f"{col}_z"
        if std == 0 or np.isnan(std):
            adata_mac.obs[z_col] = 0.0
        else:
            adata_mac.obs[z_col] = (vals - float(vals.mean())) / std

    z_cols = [f"{col}_z" for col in score_cols]
    aux_cols = [f"aux_score_{key}" for key in REFERENCE_SCORES]

    cluster_labels = {}
    summary_rows = []
    clusters = sorted(adata_mac.obs["macrophage_leiden"].astype(str).unique(), key=_leiden_sort_key)
    for cluster in clusters:
        mask = adata_mac.obs["macrophage_leiden"].astype(str) == cluster
        z_means = adata_mac.obs.loc[mask, z_cols].mean().values
        raw_means = adata_mac.obs.loc[mask, score_cols].mean().values

        best_idx = int(np.argmax(z_means))
        order = np.argsort(z_means)
        second_idx = int(order[-2]) if len(order) > 1 else best_idx
        best_key = primary_keys[best_idx]
        best_label = PRIMARY_SUBTYPES[best_key]["display_name"]
        best_z = float(z_means[best_idx])
        margin_z = float(best_z - z_means[second_idx])

        if best_z < min_best_z or margin_z < min_margin_z:
            best_label = "Intermediate"

        cluster_labels[cluster] = best_label
        row = {
            "macrophage_leiden": cluster,
            "n_cells": int(mask.sum()),
            "assigned_label": best_label,
            "best_mean_z": round(best_z, 4),
            "margin_z": round(margin_z, 4),
            "scdrs_mean": round(float(adata_mac.obs.loc[mask, trait_key].mean()), 4),
            "scdrs_median": round(float(adata_mac.obs.loc[mask, trait_key].median()), 4),
            "scdrs_frac_gt_1p65": round(float((adata_mac.obs.loc[mask, trait_key] > 1.65).mean()), 4),
        }
        for i, subtype_key in enumerate(primary_keys):
            display_name = PRIMARY_SUBTYPES[subtype_key]["display_name"]
            row[f"mean_score_{display_name}"] = round(float(raw_means[i]), 4)
            row[f"mean_z_{display_name}"] = round(float(z_means[i]), 4)
        for aux_col in aux_cols:
            row[aux_col] = round(float(adata_mac.obs.loc[mask, aux_col].mean()), 4)
        summary_rows.append(row)

    adata_mac.obs["macrophage_subtype"] = (
        adata_mac.obs["macrophage_leiden"].astype(str).map(cluster_labels).astype("category")
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


def export_cluster_dge(adata_mac: sc.AnnData, out_csv: Path):
    tmp = adata_mac.copy()
    sc.tl.rank_genes_groups(
        tmp,
        groupby="macrophage_leiden",
        method="wilcoxon",
        key_added="macrophage_leiden_wilcoxon",
        use_raw=False,
    )
    rows = []
    clusters = sorted(tmp.obs["macrophage_leiden"].astype(str).unique(), key=_leiden_sort_key)
    gene_map = get_gene_symbol_series(tmp)
    gene_map.index = tmp.var_names.astype(str)
    for cluster in clusters:
        df = sc.get.rank_genes_groups_df(
            tmp,
            group=cluster,
            key="macrophage_leiden_wilcoxon",
        )
        df["gene_symbol"] = df["names"].astype(str).map(gene_map).fillna(df["names"].astype(str))
        df["macrophage_leiden"] = cluster
        rows.append(df)
    dge_df = pd.concat(rows, ignore_index=True)
    dge_df.to_csv(out_csv, index=False)


def plot_panels(adata_mac: sc.AnnData, trait_key: str, out_png: Path):
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 5.4))

    ax1 = axes[0]
    subtype_order = [
        cfg["display_name"]
        for cfg in PRIMARY_SUBTYPES.values()
        if cfg["display_name"] in adata_mac.obs["macrophage_subtype"].cat.categories
    ] + [
        x
        for x in ["Intermediate"]
        if x in adata_mac.obs["macrophage_subtype"].cat.categories
    ]
    for subtype in subtype_order:
        mask = adata_mac.obs["macrophage_subtype"] == subtype
        coords = adata_mac.obsm["X_umap_macrophage"][mask]
        if subtype == "Intermediate":
            color = "#A6A6A6"
        else:
            color = next(
                cfg["color"] for cfg in PRIMARY_SUBTYPES.values() if cfg["display_name"] == subtype
            )
        ax1.scatter(
            coords[:, 0],
            coords[:, 1],
            s=6,
            c=color,
            label=subtype,
            alpha=0.80,
            edgecolors="none",
            rasterized=True,
        )
    ax1.set_title("Macrophage Specific Labels")
    ax1.set_xlabel("UMAP1")
    ax1.set_ylabel("UMAP2")
    ax1.legend(frameon=False, fontsize=9, markerscale=2.5, loc="best")

    ax2 = axes[1]
    scores = adata_mac.obs[trait_key].astype(float).values
    lo = float(np.nanpercentile(scores, 2))
    hi = float(np.nanpercentile(scores, 98))
    vabs = max(abs(lo), abs(hi), 1e-6)
    norm = TwoSlopeNorm(vmin=-vabs, vcenter=0.0, vmax=vabs)
    order = np.argsort(np.abs(scores))
    coords = adata_mac.obsm["X_umap_macrophage"][order]
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
    for folder in [MERGED_DIR, PLOT_DIR, META_DIR, SCDRS_DIR]:
        folder.mkdir(parents=True, exist_ok=True)

    args = parse_args()
    trait = args.trait
    score_path = args.score_file or (SCDRS_DIR / f"{trait}.full_score.gz")

    print("Loading annotated object ...")
    adata = sc.read_h5ad(args.h5ad_file)

    print("Subsetting macrophage cells ...")
    adata_mac = adata[adata.obs["final_high_level_celltype_10"].astype(str) == "Macrophage"].copy()
    print(f"  Macrophage cells: {adata_mac.n_obs}")
    if adata_mac.n_obs == 0:
        available = sorted(adata.obs["final_high_level_celltype_10"].astype(str).unique().tolist())
        raise ValueError(
            "No cells labeled 'Macrophage' found in 'final_high_level_celltype_10'. "
            f"Available labels: {available}"
        )

    expr_layer, expr_layer_name = choose_expression_matrix(adata_mac)
    adata_mac.X = expr_layer.copy() if hasattr(expr_layer, "copy") else expr_layer
    print(f"  Expression layer used for scoring/embedding: {expr_layer_name}")

    print("Loading scDRS score table ...")
    score_df = load_scdrs_score_table(score_path)
    common = adata_mac.obs_names.intersection(score_df.index)
    adata_mac = adata_mac[common].copy()
    score_df = score_df.loc[common]
    norm_col = choose_norm_score_column(score_df)
    trait_key = f"{trait}_norm_score"
    adata_mac.obs[trait_key] = score_df[norm_col].astype(float).values
    print(f"  Overlap with scDRS score table: {adata_mac.n_obs} cells")

    print("Loading marker sets ...")
    marker_sets = load_marker_sets(args.marker_tsv)
    symbol_to_var, mapping_df = map_markers_to_features(adata_mac, marker_sets)
    out_mapping = MERGED_DIR / f"GSE159677_macrophage_marker_feature_mapping_{trait}.csv"
    mapping_df.to_csv(out_mapping, index=False)
    print(f"  saved: {out_mapping}")

    print("Scoring marker sets ...")
    score_marker_sets(adata_mac, marker_sets, symbol_to_var, args.neg_weight)

    print("Running macrophage-specific embedding ...")
    run_subset_embedding(
        adata_mac,
        batch_key=args.batch_key,
        n_top_genes=args.n_top_genes,
        n_neighbors=args.n_neighbors,
        resolution=args.resolution,
    )

    print("Assigning subtype labels ...")
    summary_df = assign_subtypes(
        adata_mac,
        trait_key=trait_key,
        min_best_z=args.min_best_z,
        min_margin_z=args.min_margin_z,
    )
    out_summary = MERGED_DIR / f"GSE159677_macrophage_subtype_summary_{trait}.csv"
    summary_df.to_csv(out_summary, index=False)

    counts_df = (
        adata_mac.obs["macrophage_subtype"]
        .astype(str)
        .value_counts()
        .rename_axis("macrophage_subtype")
        .reset_index(name="n_cells")
    )
    out_counts = MERGED_DIR / f"GSE159677_macrophage_subtype_counts_{trait}.csv"
    counts_df.to_csv(out_counts, index=False)

    out_dge = MERGED_DIR / f"GSE159677_macrophage_leiden_wilcoxon_dge_{trait}.csv"
    print("Computing one-vs-rest DGE across macrophage Leiden clusters ...")
    export_cluster_dge(adata_mac, out_dge)

    out_plot = PLOT_DIR / f"GSE159677_macrophage_subtype_scdrs_umap_{trait}.png"
    plot_panels(adata_mac, trait_key, out_plot)

    sanitize_obs_for_h5ad(adata_mac)
    out_h5ad = MERGED_DIR / f"GSE159677_macrophage_subtyped_{trait}.h5ad"
    adata_mac.write_h5ad(out_h5ad, compression="gzip")

    print("\nSubtype summary:")
    print(summary_df.to_string(index=False))
    print("\nSubtype counts:")
    print(counts_df.to_string(index=False))
    print(f"\nsaved: {out_summary}")
    print(f"saved: {out_counts}")
    print(f"saved: {out_dge}")
    print(f"saved: {out_plot}")
    print(f"saved: {out_h5ad}")


if __name__ == "__main__":
    main()
