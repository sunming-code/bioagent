#!/usr/bin/env python3
"""
GSE159677 post-Harmony annotation

Input:
  - <scdrs-work-dir>/merged/GSE159677_filtered_batch_corrected.h5ad
  - <scdrs-work-dir>/metadata/final_report_marker_manual.tsv

Main steps:
1. Load the Harmony-corrected object
2. Read paper-style 10 high-level marker panels from final_report_marker_manual.tsv
3. Score high-level cell types on acosh-normalized expression
4. Summarize scores by harmony_leiden cluster
5. Run cluster-vs-rest DGE for manual confirmation
6. Export an annotation review table for manual editing

This script does not hardcode final labels. It produces an auto suggestion table
that should be reviewed before finalizing annotation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import os

import numpy as np
import pandas as pd
import scanpy as sc
from matplotlib import pyplot as plt


sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, facecolor="white")


PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"
META_DIR = WORK_DIR / "metadata"

for p in [MERGED_DIR, PLOT_DIR, META_DIR]:
    p.mkdir(parents=True, exist_ok=True)


INPUT_H5AD = MERGED_DIR / "GSE159677_filtered_batch_corrected.h5ad"
MARKER_TSV = META_DIR / "final_report_marker_manual.tsv"

AUTO_H5AD = MERGED_DIR / "GSE159677_harmony_highlevel_auto_annotated.h5ad"
SUMMARY_CSV = MERGED_DIR / "GSE159677_harmony_cluster_score_summary.csv"
DGE_CSV = MERGED_DIR / "GSE159677_harmony_leiden_wilcoxon_dge.csv"
REVIEW_CSV = MERGED_DIR / "GSE159677_annotation_review_table.csv"
MARKER_JSON = META_DIR / "GSE159677_paper10_highlevel_markers.json"

UMAP_SCORE_PNG = PLOT_DIR / "GSE159677_harmony_highlevel_scores_umap.png"
UMAP_AUTO_PNG = PLOT_DIR / "GSE159677_harmony_highlevel_auto_umap.png"
DOTPLOT_PNG = PLOT_DIR / "GSE159677_harmony_highlevel_marker_dotplot.png"


PAPER_HIGHLEVEL_MAP = {
    "B cell": "B-cell",
    "Dendritic cell": "Dendritic-cell",
    "Endothelial": "Endothelial",
    "Fibroblast": "FB",
    "Macrophage": "Macrophage",
    "Mast cell": "Mast-cell",
    "NK cell": "NK-cell",
    "Plasma cell": "Plasma-cell",
    "T cell": "T-cell",
    "VSMC": "VSMC",
}

PAPER_HIGHLEVEL_ORDER = [
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
]

PAPER_HIGHLEVEL_COLORS = [
    "#8B5A46",  # B-cell
    "#8E6BBE",  # Dendritic-cell
    "#4DAA57",  # Endothelial
    "#CF78B8",  # FB
    "#F28E2B",  # Macrophage
    "#D43F3A",  # Mast-cell
    "#A7D989",  # NK-cell
    "#CBB6E5",  # Plasma-cell
    "#3D7DBB",  # T-cell
    "#B9CCE8",  # VSMC
]


def sanitize_obs_for_h5ad(adata):
    for col in adata.obs.columns:
        s = adata.obs[col]
        if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            adata.obs[col] = s.where(s.notna(), "").astype(str)
    return adata


def split_genes(text: str) -> list[str]:
    if pd.isna(text) or not str(text).strip():
        return []
    return [x.strip() for x in str(text).split(",") if x.strip()]


def build_varname_lookup(adata) -> pd.DataFrame:
    df = adata.var.reset_index()
    df = df.rename(columns={df.columns[0]: "var_name"})
    if "gene_name" not in df.columns:
        raise KeyError("adata.var['gene_name'] is required for marker lookup")
    df["gene_name"] = df["gene_name"].astype(str)
    return df


def symbols_to_varnames(adata, symbols: list[str]) -> list[str]:
    df = build_varname_lookup(adata)
    wanted = {x.upper() for x in symbols}
    out = (
        df[df["gene_name"].str.upper().isin(wanted)]
        .drop_duplicates(subset=["gene_name"], keep="first")["var_name"]
        .astype(str)
        .tolist()
    )
    return out


def marker_symbols_present(adata, symbols: list[str]) -> list[str]:
    present = set(adata.var["gene_name"].astype(str).str.upper())
    out = []
    for g in symbols:
        if g.upper() in present and g not in out:
            out.append(g)
    return out


def load_paper_highlevel_markers(adata, marker_tsv: Path):
    if not marker_tsv.exists():
        raise FileNotFoundError(
            f"Marker TSV not found: {marker_tsv}\n"
            "Please copy final_report_marker_manual.tsv into the metadata folder first."
        )

    df = pd.read_csv(marker_tsv, sep="\t")
    marker_symbols = {}
    marker_varnames = {}
    source_rows = []

    for report_name, paper_label in PAPER_HIGHLEVEL_MAP.items():
        sub = df[df["report_name"] == report_name]
        if sub.empty:
            raise ValueError(f"Marker row missing for report_name={report_name!r}")
        row = sub.iloc[0]
        symbols = split_genes(row["core_markers"])
        present_symbols = marker_symbols_present(adata, symbols)
        present_varnames = symbols_to_varnames(adata, symbols)
        if len(present_symbols) == 0:
            raise ValueError(f"No markers from {report_name!r} are present in adata.var['gene_name']")
        marker_symbols[paper_label] = present_symbols
        marker_varnames[paper_label] = present_varnames
        source_rows.append(
            {
                "paper_label": paper_label,
                "report_name": report_name,
                "core_markers_requested": ", ".join(symbols),
                "core_markers_present": ", ".join(present_symbols),
            }
        )

    with MARKER_JSON.open("w", encoding="utf-8") as f:
        json.dump(marker_symbols, f, ensure_ascii=False, indent=2)

    return marker_symbols, marker_varnames, pd.DataFrame(source_rows)


def save_fig(path: Path):
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close()


def main():
    adata = sc.read_h5ad(INPUT_H5AD)
    print("Loaded:", adata)

    if "acosh" not in adata.layers:
        raise KeyError("Expected adata.layers['acosh']")
    if "X_harmony" not in adata.obsm:
        raise KeyError("Expected adata.obsm['X_harmony']")
    if "harmony_leiden" not in adata.obs:
        raise KeyError("Expected adata.obs['harmony_leiden']")

    adata.obs["harmony_leiden"] = adata.obs["harmony_leiden"].astype(str)
    adata.uns["paper10_highlevel_colors"] = PAPER_HIGHLEVEL_COLORS

    marker_symbols, marker_varnames, marker_source_df = load_paper_highlevel_markers(adata, MARKER_TSV)
    marker_source_df.to_csv(META_DIR / "GSE159677_paper10_highlevel_marker_presence.csv", index=False)

    adata_score = adata.copy()
    adata_score.X = adata_score.layers["acosh"].copy()

    score_cols = []
    for celltype in PAPER_HIGHLEVEL_ORDER:
        genes_present = marker_varnames[celltype]
        score_name = f"{celltype}_score"
        sc.tl.score_genes(adata_score, gene_list=genes_present, score_name=score_name)
        adata.obs[score_name] = adata_score.obs[score_name].values
        score_cols.append(score_name)
        print(f"{celltype}: {len(genes_present)} genes used")

    plot_cols = ["patient", "condition", "sample_id", "harmony_leiden"] + score_cols
    ncols = 3
    nrows = math.ceil(len(plot_cols) / ncols)
    fig = plt.figure(figsize=(ncols * 5.0, nrows * 4.8))
    for i, col in enumerate(plot_cols, start=1):
        ax = fig.add_subplot(nrows, ncols, i)
        legend_loc = "right margin"
        kwargs = {}
        if col == "harmony_leiden":
            legend_loc = "on data"
        if col.endswith("_score"):
            kwargs.update({"vmin": "p1", "vmax": "p99", "color_map": "RdBu_r"})
        sc.pl.umap(
            adata,
            color=col,
            layer="acosh",
            size=6,
            legend_loc=legend_loc,
            show=False,
            ax=ax,
            **kwargs,
        )
        ax.set_title(col)
    save_fig(UMAP_SCORE_PNG)

    cluster_score_median = adata.obs.groupby("harmony_leiden", observed=True)[score_cols].median()
    cluster_score_median = cluster_score_median.rename(
        columns={f"{x}_score": x for x in PAPER_HIGHLEVEL_ORDER}
    )
    top_candidate = cluster_score_median.idxmax(axis=1).to_frame("suggested_label")
    second_candidate = (
        cluster_score_median.apply(lambda x: x.sort_values(ascending=False).index[1], axis=1)
        .to_frame("second_label")
    )
    top_margin = cluster_score_median.apply(
        lambda x: x.sort_values(ascending=False).iloc[0] - x.sort_values(ascending=False).iloc[1],
        axis=1,
    ).to_frame("top_minus_second")
    n_cells = (
        adata.obs["harmony_leiden"]
        .value_counts()
        .rename_axis("harmony_leiden")
        .to_frame("n_cells")
    )
    cluster_score_summary = pd.concat([n_cells, cluster_score_median, top_candidate, second_candidate, top_margin], axis=1)
    cluster_score_summary = cluster_score_summary.reset_index()
    cluster_score_summary["harmony_leiden_int"] = pd.to_numeric(cluster_score_summary["harmony_leiden"], errors="coerce")
    cluster_score_summary = cluster_score_summary.sort_values(["harmony_leiden_int", "harmony_leiden"]).drop(columns="harmony_leiden_int")
    cluster_score_summary.to_csv(SUMMARY_CSV, index=False)
    print("Saved:", SUMMARY_CSV)

    adata_dge = adata.copy()
    adata_dge.X = adata_dge.layers["acosh"].copy()
    adata_dge.obs["harmony_leiden"] = adata_dge.obs["harmony_leiden"].astype("category")

    sc.tl.rank_genes_groups(
        adata_dge,
        groupby="harmony_leiden",
        method="wilcoxon",
        key_added="GSE159677_harmony_leiden_dge",
    )

    gene_symbol_map = adata.var["gene_name"].astype(str).to_dict()
    cluster_list = sorted(adata.obs["harmony_leiden"].unique(), key=lambda x: int(x))
    all_dge = []
    top_marker_rows = []
    for cl in cluster_list:
        df = sc.get.rank_genes_groups_df(adata_dge, group=cl, key="GSE159677_harmony_leiden_dge")
        df["cluster"] = str(cl)
        df["gene_symbol"] = df["names"].astype(str).map(gene_symbol_map).fillna(df["names"].astype(str))
        all_dge.append(df)

        top = (
            df[(df["logfoldchanges"] > 0)]
            .sort_values(["pvals_adj", "logfoldchanges"], ascending=[True, False])
            .head(10)
        )
        top_marker_rows.append(
            {
                "harmony_leiden": str(cl),
                "top10_markers": ", ".join(top["gene_symbol"].astype(str).tolist()),
            }
        )

    dge_df = pd.concat(all_dge, ignore_index=True)
    dge_df = dge_df.rename(
        columns={
            "names": "ensembl_id",
            "logfoldchanges": "log2FC",
            "pvals": "pvalue",
            "pvals_adj": "padj",
        }
    )
    dge_df.to_csv(DGE_CSV, index=False)
    print("Saved:", DGE_CSV)

    review_df = cluster_score_summary.merge(pd.DataFrame(top_marker_rows), on="harmony_leiden", how="left")
    review_df["final_high_level_celltype_10"] = ""
    review_df.to_csv(REVIEW_CSV, index=False)
    print("Saved:", REVIEW_CSV)

    dotplot_markers = {celltype: marker_symbols[celltype] for celltype in PAPER_HIGHLEVEL_ORDER}
    sc.tl.dendrogram(adata_dge, groupby="harmony_leiden")
    dp = sc.pl.dotplot(
        adata_dge,
        var_names=dotplot_markers,
        groupby="harmony_leiden",
        gene_symbols="gene_name",
        dendrogram=True,
        standard_scale="var",
        show=False,
        return_fig=True,
    )
    dp.savefig(str(DOTPLOT_PNG), dpi=300)
    plt.close("all")

    auto_map = dict(zip(review_df["harmony_leiden"].astype(str), review_df["suggested_label"].astype(str)))
    adata.obs["high_level_celltype_auto"] = adata.obs["harmony_leiden"].astype(str).map(auto_map)
    adata.obs["high_level_celltype_auto"] = pd.Categorical(
        adata.obs["high_level_celltype_auto"],
        categories=PAPER_HIGHLEVEL_ORDER,
        ordered=True,
    )
    adata.uns["high_level_celltype_auto_colors"] = PAPER_HIGHLEVEL_COLORS

    fig = sc.pl.umap(
        adata,
        color=["harmony_leiden", "high_level_celltype_auto"],
        ncols=2,
        size=6,
        legend_loc="on data",
        show=False,
        return_fig=True,
    )
    fig.savefig(UMAP_AUTO_PNG, dpi=300, bbox_inches="tight")
    plt.close(fig)

    sanitize_obs_for_h5ad(adata)
    adata.write_h5ad(AUTO_H5AD, compression="gzip")

    print("\nNext step:")
    print(f"1. Review {REVIEW_CSV}")
    print(f"2. Review {DOTPLOT_PNG} and {DGE_CSV}")
    print("3. Fill final_high_level_celltype_10 manually in the review CSV")
    print("4. Run run_GSE159677_finalize_annotation.py")


if __name__ == "__main__":
    main()
