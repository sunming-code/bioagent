#!/usr/bin/env python3
"""
GSE159677 single-cell preprocessing before scDRS

Workflow:
1. Read GEO aggregated 10x filtered matrix (6 samples)
2. Recover patient / condition / sample_id from barcode suffix
3. Compute basic QC metrics
4. Inspect and remove RBC-like cells
5. Build pre-QC clusters for scDblFinder
6. Run scDblFinder in R
7. Apply formal QC filters
8. Run scran size-factor + acosh normalization in R
9. Run Harmony batch correction on patient
10. Save pre-scDRS objects and QC plots

This script follows the logic of ath_create_GSE159677_anndata.ipynb,
but keeps only the Harmony branch and stops before annotation.
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path

import anndata as ad
import harmonypy as hm
import numpy as np
import pandas as pd
import scanpy as sc
import seaborn as sns
from matplotlib import pyplot as plt
from scipy import io as spio
from scipy import sparse


sc.settings.verbosity = 2
sc.set_figure_params(dpi=120, facecolor="white")


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
PROJECT_DIR = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"]).expanduser().resolve()
INPUT_DIR = Path(os.environ["ATHEROMAP_SCDRS_INPUT_DIR"]).expanduser().resolve()
WORK_DIR = PROJECT_DIR
MERGED_DIR = WORK_DIR / "merged"
PLOT_DIR = WORK_DIR / "plots"

RSCRIPT_BIN = os.environ.get("ATHEROMAP_RSCRIPT", "Rscript")
SHOW_R_OUTPUT = True

RBC_GENES = ["HBB", "HBA1", "HBA2", "HEMGN"]
RBC_THR = 2.0

COUNTS_THR_MIN = 400
COUNTS_THR_MAX = 55000
GENES_THR_MIN = 350
GENES_THR_MAX = 4000
MT_THR = 0.10

PRECLUSTER_RES = 0.8
SCRAN_GROUP_RES = 0.5
HARMONY_LEIDEN_RES = 1.2

N_NEIGHBORS = 15
N_PCS_PRE = 15
N_PCS_HARMONY = 20
HARMONY_KEY = "patient"


RAW_H5AD = MERGED_DIR / "GSE159677_raw_aggregate.h5ad"
RBC_REMOVED_H5AD = MERGED_DIR / "GSE159677_rbc_removed.h5ad"
DOUBLET_H5AD = MERGED_DIR / "GSE159677_rbc_removed_with_doublets.h5ad"
DOUBLET_CSV = MERGED_DIR / "GSE159677_doublet_scores.csv.gz"
FILTERED_H5AD = MERGED_DIR / "GSE159677_filtered.h5ad"
FINAL_H5AD = MERGED_DIR / "GSE159677_filtered_batch_corrected.h5ad"


PATIENT_DICT = {1: "P1", 2: "P1", 3: "P2", 4: "P2", 5: "P3", 6: "P3"}
CONDITION_DICT = {1: "H", 2: "D", 3: "H", 4: "D", 5: "H", 6: "D"}


def ensure_dirs() -> None:
    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)


def flatten_sum(x) -> np.ndarray:
    return np.asarray(x).ravel()


def sanitize_obs_for_h5ad(adata: ad.AnnData) -> ad.AnnData:
    for col in adata.obs.columns:
        series = adata.obs[col]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            adata.obs[col] = series.where(series.notna(), "").astype(str)
    return adata


def calc_basic_qc(adata: ad.AnnData, layer: str = "raw_counts") -> ad.AnnData:
    X = adata.layers[layer] if layer in adata.layers else adata.X
    total_counts = flatten_sum(X.sum(axis=1))
    total_genes = flatten_sum((X > 0).sum(axis=1))
    gene_counts = flatten_sum(X.sum(axis=0))
    gene_cells = flatten_sum((X > 0).sum(axis=0))

    adata.obs["n_counts"] = total_counts
    adata.obs["n_genes"] = total_genes
    adata.var["n_counts"] = gene_counts
    adata.var["n_cells"] = gene_cells

    gene_symbols = adata.var["gene_name"].astype(str).str.upper()
    ribo_mask = gene_symbols.str.startswith(("RPS", "RPL")).to_numpy()
    mt_mask = gene_symbols.str.startswith(("MT-", "MT")).to_numpy()

    denom = np.clip(total_counts.astype(float), a_min=1, a_max=None)
    ribo_counts = flatten_sum(X[:, ribo_mask].sum(axis=1))
    mt_counts = flatten_sum(X[:, mt_mask].sum(axis=1))
    adata.obs["ribo_frac"] = ribo_counts / denom
    adata.obs["mt_frac"] = mt_counts / denom
    return adata


def build_varname_lookup(adata: ad.AnnData) -> pd.DataFrame:
    df = adata.var.reset_index()
    df = df.rename(columns={df.columns[0]: "var_name"})
    df["gene_name"] = df["gene_name"].astype(str)
    return df


def symbols_to_varnames(adata: ad.AnnData, symbols: list[str]) -> list[str]:
    df = build_varname_lookup(adata)
    wanted = {x.upper() for x in symbols}
    out = (
        df[df["gene_name"].str.upper().isin(wanted)]
        .drop_duplicates(subset=["gene_name"], keep="first")["var_name"]
        .astype(str)
        .tolist()
    )
    return out


def read_gse159677_aggregate(input_dir: Path) -> ad.AnnData:
    matrix_path = input_dir / "matrix.mtx.gz"
    barcodes_path = input_dir / "barcodes.tsv.gz"
    features_path = input_dir / "features.tsv.gz"

    if not matrix_path.exists():
        raise FileNotFoundError(f"Missing matrix file: {matrix_path}")
    if not barcodes_path.exists():
        raise FileNotFoundError(f"Missing barcode file: {barcodes_path}")
    if not features_path.exists():
        raise FileNotFoundError(f"Missing feature file: {features_path}")

    count_mat = sc.read_mtx(matrix_path)
    barcodes = pd.read_table(barcodes_path, header=None)
    features = pd.read_table(features_path, header=None)

    barcode_split = barcodes[0].str.rsplit("-", n=1, expand=True)
    suffix = barcode_split[1].astype(int)

    barcodes = barcodes.rename(columns={0: "cell_id"})
    barcodes["patient"] = suffix.map(PATIENT_DICT)
    barcodes["condition"] = suffix.map(CONDITION_DICT)
    barcodes["sample_id"] = barcodes["patient"] + "_" + barcodes["condition"]
    barcodes["method"] = "NextSeq500"
    barcodes["suffix_code"] = suffix.values
    barcodes = barcodes.set_index("cell_id", drop=True)

    features = features.iloc[:, :2].copy()
    features.columns = ["ensembl_gene_name", "gene_name"]
    features = features.set_index("ensembl_gene_name", drop=True)

    X = count_mat.X.T.tocsr() if hasattr(count_mat.X, "tocsr") else count_mat.X.T
    adata = ad.AnnData(X, obs=barcodes, var=features, dtype="float64")
    adata.layers["raw_counts"] = adata.X.copy()
    calc_basic_qc(adata)
    return adata


def plot_rbc_diagnostics(adata: ad.AnnData) -> ad.AnnData:
    ery_varnames = symbols_to_varnames(adata, RBC_GENES)
    if len(ery_varnames) == 0:
        raise ValueError("No RBC genes were found in adata.var['gene_name']")

    adata_pp = adata.copy()
    sc.pp.log1p(adata_pp)
    sc.pp.pca(adata_pp, n_comps=10, use_highly_variable=False, svd_solver="arpack")
    sc.pp.neighbors(adata_pp, n_neighbors=N_NEIGHBORS, n_pcs=10, metric="euclidean")
    sc.tl.umap(adata_pp, random_state=0)

    ncols = 2
    nrows = int(np.ceil(len(RBC_GENES) / ncols))
    fig = plt.figure(figsize=(ncols * 6, nrows * 5))
    for n, symbol in enumerate(RBC_GENES):
        ax = fig.add_subplot(nrows, ncols, n + 1)
        symbol_var = build_varname_lookup(adata).query("gene_name == @symbol")["var_name"].tolist()
        if len(symbol_var) == 0:
            ax.set_axis_off()
            ax.set_title(f"{symbol} not found")
            continue
        sc.pl.umap(adata_pp, color=symbol_var[0], show=False, size=15, ax=ax)
        ax.set_title(symbol)
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "GSE159677_rbc_gene_umap.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    sc.tl.score_genes(adata_pp, gene_list=ery_varnames, score_name="RBC_score")
    adata.obs["RBC_score"] = adata_pp.obs["RBC_score"].values
    adata.obs["RBC_score_high"] = np.where(adata.obs["RBC_score"] > RBC_THR, "yes", "no")
    adata_pp.obs["RBC_score_high"] = adata.obs["RBC_score_high"].values

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    sns.histplot(adata.obs["RBC_score"], ax=axes[0], bins=60)
    axes[0].axvline(RBC_THR, color="red")
    axes[0].set_title("RBC score", fontsize=15, fontweight="bold")

    sc.pl.umap(adata_pp, color="RBC_score", show=False, size=15, ax=axes[1])
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "GSE159677_rbc_score_hist_umap.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    sc.pl.umap(
        adata_pp,
        color="RBC_score_high",
        show=False,
        size=15,
        ax=axes[0],
        title="RBC score over threshold",
    )
    sc.tl.leiden(adata_pp, key_added="raw_leiden_cluster", resolution=0.1, random_state=0)
    sc.pl.umap(
        adata_pp,
        color="raw_leiden_cluster",
        show=False,
        size=15,
        ax=axes[1],
        legend_loc="on data",
    )
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "GSE159677_rbc_threshold_cluster.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    return adata


def make_preqc_clusters(adata: ad.AnnData) -> ad.AnnData:
    adata_pp = adata.copy()
    sc.pp.log1p(adata_pp)
    sc.pp.pca(adata_pp, n_comps=N_PCS_PRE, use_highly_variable=False, svd_solver="arpack")
    sc.pp.neighbors(adata_pp, n_neighbors=N_NEIGHBORS, n_pcs=N_PCS_PRE, metric="euclidean")
    sc.tl.umap(adata_pp, random_state=0)
    sc.tl.leiden(adata_pp, key_added="clusters", resolution=PRECLUSTER_RES, random_state=0)

    adata.obs["clusters"] = adata_pp.obs["clusters"].astype(str).values
    adata.obsm["X_umap_preqc"] = adata_pp.obsm["X_umap"].copy()

    cols_for_plotting = [
        "n_counts",
        "n_genes",
        "mt_frac",
        "ribo_frac",
        "patient",
        "condition",
        "sample_id",
        "clusters",
    ]

    ncols = 2
    nrows = math.ceil(len(cols_for_plotting) / ncols)
    fig = plt.figure(figsize=(ncols * 7, nrows * 5.5))
    for n, col in enumerate(cols_for_plotting):
        ax = fig.add_subplot(nrows, ncols, n + 1)
        legend_loc = "right margin"
        if col == "clusters":
            legend_loc = "on data"
        sc.pl.embedding(
            adata_pp,
            basis="umap",
            color=col,
            show=False,
            ax=ax,
            size=15,
            legend_loc=legend_loc,
        )
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "GSE159677_preqc_umap_panel.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    return adata


def run_r_script(script_text: str, script_path: Path) -> None:
    script_path.write_text(script_text)
    proc = subprocess.Popen(
        [RSCRIPT_BIN, str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is not None:
        for raw_line in proc.stdout:
            if SHOW_R_OUTPUT:
                print(raw_line.rstrip())
    ret = proc.wait()
    if ret != 0:
        raise RuntimeError(f"R script failed: {script_path}")


def run_scDblFinder(adata: ad.AnnData) -> ad.AnnData:
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmpdir = Path(tmpdirname)
        ifn = tmpdir / "in.h5ad"
        obs_csv = tmpdir / "doublet_obs.csv.gz"
        rfn = tmpdir / "run_scDblFinder.R"

        adata.write_h5ad(ifn, compression="gzip")

        r_script = f"""
suppressPackageStartupMessages(library(zellkonverter))
suppressPackageStartupMessages(library(scDblFinder))
suppressPackageStartupMessages(library(SingleCellExperiment))
suppressPackageStartupMessages(library(BiocParallel))

dat <- zellkonverter::readH5AD("{ifn}", reader="R")

if ("raw_counts" %in% assayNames(dat)) {{
    assayNames(dat)[assayNames(dat) == "raw_counts"] <- "counts"
}}

bp <- MulticoreParam(workers=4, progressbar=FALSE, RNGseed=1234)
sce <- scDblFinder(dat, samples="sample_id", cluster="clusters", BPPARAM=bp)

if ("counts" %in% assayNames(sce)) {{
    assayNames(sce)[assayNames(sce) == "counts"] <- "raw_counts"
}}

obs_df <- as.data.frame(colData(sce))
write.csv(obs_df, gzfile("{obs_csv}"), quote=TRUE)
"""
        run_r_script(r_script, rfn)

        obs_with_doublets = pd.read_csv(obs_csv, index_col=0)
        obs_with_doublets.to_csv(DOUBLET_CSV, compression="gzip")

        adata_with_doublets = adata.copy()
        common = adata_with_doublets.obs_names.intersection(obs_with_doublets.index)
        if len(common) != adata_with_doublets.n_obs:
            raise ValueError(
                f"Doublet output mismatch: {len(common)} / {adata_with_doublets.n_obs} cells matched"
            )
        obs_with_doublets = obs_with_doublets.loc[adata_with_doublets.obs_names]
        required_cols = ["scDblFinder.score", "scDblFinder.class"]
        missing_cols = [c for c in required_cols if c not in obs_with_doublets.columns]
        if missing_cols:
            raise ValueError(f"Missing expected scDblFinder columns: {missing_cols}")
        for col in obs_with_doublets.columns:
            adata_with_doublets.obs[col] = obs_with_doublets[col].values

    return adata_with_doublets


def plot_formal_qc(adata: ad.AnnData) -> None:
    cols_for_plotting = [
        "mt_frac",
        "ribo_frac",
        "scDblFinder.score",
        "scDblFinder.class",
        "patient",
        "condition",
    ]
    ax_titles = [
        "MT-fraction",
        "Ribosomal-fraction",
        "Doublet-score",
        "Doublet-class",
        "Patient",
        "Condition",
    ]

    ncols = 2
    nrows = math.ceil(len(cols_for_plotting) / ncols)
    fig = plt.figure(figsize=(ncols * 10, nrows * 8))

    for (n, color_by_col), ax_title in zip(enumerate(cols_for_plotting), ax_titles):
        ax = fig.add_subplot(nrows, ncols, n + 1)
        if pd.api.types.is_numeric_dtype(adata.obs[color_by_col]):
            im = ax.scatter(
                x=adata.obs["n_counts"],
                y=adata.obs["n_genes"],
                c=adata.obs[color_by_col],
                s=2,
                cmap="viridis",
            )
            fig.colorbar(im, ax=ax)
        else:
            categories = adata.obs[color_by_col].astype(str).sort_values().unique()
            palette = sns.color_palette("husl", len(categories))
            color_map = {cat: palette[i] for i, cat in enumerate(categories)}
            colors = adata.obs[color_by_col].astype(str).map(color_map).tolist()
            ax.scatter(x=adata.obs["n_counts"], y=adata.obs["n_genes"], c=colors, s=2)
            handles = [
                plt.matplotlib.patches.Patch(color=color_map[label], label=label)
                for label in categories
            ]
            ax.legend(handles=handles, loc="center right", fontsize=8)

        ax.set_xlabel("number of transcripts")
        ax.set_ylabel("number of genes")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(ax_title, fontweight="bold")
        ax.axhline(GENES_THR_MIN)
        ax.axhline(GENES_THR_MAX)
        ax.axvline(COUNTS_THR_MIN)
        ax.axvline(COUNTS_THR_MAX)

    fig.tight_layout()
    fig.savefig(PLOT_DIR / "GSE159677_formal_qc_scatter_panel.png", dpi=300, bbox_inches="tight")
    plt.close(fig)

    for groupby_col in ["patient", "condition", "sample_id"]:
        y_axis_vars = ["n_counts", "n_genes", "mt_frac", "ribo_frac", "scDblFinder.score"]
        log_bool_list = [True, True, False, False, False]
        max_thresholds = [COUNTS_THR_MAX, GENES_THR_MAX, MT_THR, 0, 0]
        min_thresholds = [COUNTS_THR_MIN, GENES_THR_MIN, 0, 0.05, 0]

        ncols = 2
        nrows = math.ceil(len(y_axis_vars) / ncols)
        fig = plt.figure(figsize=(ncols * 8, nrows * 7))

        for (n, y_axis), log_bool, thr_max, thr_min in zip(
            enumerate(y_axis_vars),
            log_bool_list,
            max_thresholds,
            min_thresholds,
        ):
            ax = fig.add_subplot(nrows, ncols, n + 1)
            sc.pl.violin(
                adata,
                [y_axis],
                groupby=groupby_col,
                size=1,
                log=log_bool,
                rotation=90,
                ax=ax,
                show=False,
            )
            ax.set_title(f"Grouped by {groupby_col}", fontweight="bold")
            ax.axhline(thr_max)
            ax.axhline(thr_min)

        fig.tight_layout()
        fig.savefig(
            PLOT_DIR / f"GSE159677_formal_qc_violin_by_{groupby_col}.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(fig)


def apply_formal_qc(adata: ad.AnnData) -> ad.AnnData:
    adata_filt = adata.copy()
    print(f"Total number of cells: {adata_filt.n_obs}")

    adata_filt = adata_filt[adata_filt.obs["n_counts"] >= COUNTS_THR_MIN].copy()
    print(f"Number of cells after min count filter: {adata_filt.n_obs}")

    sc.pp.filter_cells(adata_filt, max_counts=COUNTS_THR_MAX)
    print(f"Number of cells after max count filter: {adata_filt.n_obs}")

    adata_filt = adata_filt[adata_filt.obs["mt_frac"] <= MT_THR].copy()
    print(f"Number of cells after MT filter: {adata_filt.n_obs}")

    adata_filt = adata_filt[adata_filt.obs["n_genes"] >= GENES_THR_MIN].copy()
    print(f"Number of cells after min gene filter: {adata_filt.n_obs}")

    sc.pp.filter_cells(adata_filt, max_genes=GENES_THR_MAX)
    print(f"Number of cells after max gene filter: {adata_filt.n_obs}")

    adata_filt = adata_filt[adata_filt.obs["scDblFinder.class"].astype(str) != "doublet"].copy()
    print(f"Number of cells after Doublet filter: {adata_filt.n_obs}")
    return adata_filt


def run_acosh_norm(adata: ad.AnnData) -> ad.AnnData:
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmpdir = Path(tmpdirname)
        ifn = tmpdir / "in.h5ad"
        cells_fn = tmpdir / "cells.csv"
        sf_fn = tmpdir / "size_factors.csv"
        rfn = tmpdir / "run_acosh_norm.R"

        adata.write_h5ad(ifn, compression="gzip")

        r_script = f"""
suppressPackageStartupMessages(library(zellkonverter))
suppressPackageStartupMessages(library(SingleCellExperiment))
suppressPackageStartupMessages(library(BiocParallel))
suppressPackageStartupMessages(library(scran))
suppressPackageStartupMessages(library(MatrixGenerics))

sce <- zellkonverter::readH5AD("{ifn}", reader="R")

lib_sizes <- MatrixGenerics::colSums2(assay(sce, "raw_counts"))
keep_cells <- lib_sizes > 0
if (sum(!keep_cells) > 0) {{
    message("Dropping zero-count cells before scran: ", sum(!keep_cells))
    sce <- sce[, keep_cells]
}}

input_groups <- as.factor(colData(sce)[["leiden_filt"]])
register(MulticoreParam(workers=8))
size_factors <- calculateSumFactors(assay(sce, "raw_counts"), clusters=input_groups)
write.csv(data.frame(cell=colnames(sce)), file="{cells_fn}", row.names=FALSE, quote=TRUE)
write.csv(
    data.frame(cell=colnames(sce), size_factors=size_factors),
    file="{sf_fn}",
    row.names=FALSE,
    quote=TRUE
)
"""
        run_r_script(r_script, rfn)

        cell_df = pd.read_csv(cells_fn)
        sf_df = pd.read_csv(sf_fn)
        if cell_df.shape[0] != sf_df.shape[0]:
            raise ValueError("scran output mismatch between cell list and size factors")

        ordered_cells = cell_df["cell"].astype(str).tolist()
        adata_norm = adata[ordered_cells].copy()
        adata_norm.obs["size_factors"] = sf_df.set_index("cell").loc[ordered_cells, "size_factors"].values

        size_factors = adata_norm.obs["size_factors"].to_numpy(dtype=float)
        if np.any(~np.isfinite(size_factors)) or np.any(size_factors <= 0):
            raise ValueError("Invalid size factors returned by scran")

        raw_counts = adata_norm.layers["raw_counts"] if "raw_counts" in adata_norm.layers else adata_norm.X
        if sparse.issparse(raw_counts):
            norm_mat = raw_counts.tocsr().multiply((1.0 / size_factors)[:, None]).tocsr()
            acosh_mat = norm_mat.copy()
            acosh_mat.data = np.arccosh(acosh_mat.data + 1.0)
        else:
            norm_mat = np.asarray(raw_counts, dtype=float) / size_factors[:, None]
            acosh_mat = np.arccosh(norm_mat + 1.0)

        if acosh_mat.shape != adata_norm.shape:
            raise ValueError(f"acosh matrix shape mismatch: {acosh_mat.shape} vs {adata_norm.shape}")
        adata_norm.layers["acosh"] = acosh_mat

    return adata_norm


def plot_normalized_umap(adata: ad.AnnData) -> None:
    cols_for_plotting = [
        "n_counts",
        "n_genes",
        "mt_frac",
        "ribo_frac",
        "patient",
        "condition",
        "sample_id",
        "leiden_filt",
    ]
    ncols = 2
    nrows = int(np.ceil(len(cols_for_plotting) / ncols))
    fig = plt.figure(figsize=(ncols * 7, nrows * 5.5))
    for n, col in enumerate(cols_for_plotting):
        ax = fig.add_subplot(nrows, ncols, n + 1)
        leg_loc = "right margin"
        if col == "leiden_filt":
            leg_loc = "on data"
        sc.pl.umap(
            adata,
            color=col,
            show=False,
            ax=ax,
            size=15,
            legend_loc=leg_loc,
            layer="acosh",
        )
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "GSE159677_normalized_umap_panel.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def run_harmony(adata: ad.AnnData) -> ad.AnnData:
    adata_h = adata.copy()
    adata_h.X = adata_h.layers["acosh"].copy()

    sc.pp.pca(adata_h, n_comps=N_PCS_HARMONY, use_highly_variable=False, svd_solver="arpack")

    X_pca = np.asarray(adata_h.obsm["X_pca"], dtype=np.float64)
    ho = hm.run_harmony(X_pca, adata_h.obs, HARMONY_KEY, max_iter_harmony=20)
    Z = np.asarray(ho.Z_corr)

    if Z.shape[0] == adata_h.n_obs:
        X_harmony = Z
    elif Z.shape[1] == adata_h.n_obs:
        X_harmony = Z.T
    else:
        raise ValueError(f"Unexpected Harmony output shape: {Z.shape}")

    adata_h.obsm["X_harmony"] = X_harmony
    adata_h.obsm["harmony_pca"] = X_harmony
    sc.pp.neighbors(
        adata_h,
        use_rep="X_harmony",
        n_neighbors=N_NEIGHBORS,
        key_added="harmony_neighbors",
        metric="cosine",
    )
    sc.tl.leiden(
        adata_h,
        key_added="harmony_leiden",
        resolution=HARMONY_LEIDEN_RES,
        neighbors_key="harmony_neighbors",
        random_state=0,
    )
    sc.tl.umap(adata_h, neighbors_key="harmony_neighbors", random_state=0)
    return adata_h


def plot_harmony_umap(adata: ad.AnnData) -> None:
    cols_for_plotting = ["patient", "condition", "sample_id", "harmony_leiden", "n_counts", "n_genes"]
    ncols = 2
    nrows = int(np.ceil(len(cols_for_plotting) / ncols))
    fig = plt.figure(figsize=(ncols * 7, nrows * 5.5))
    for n, col in enumerate(cols_for_plotting):
        ax = fig.add_subplot(nrows, ncols, n + 1)
        leg_loc = "right margin"
        if col == "harmony_leiden":
            leg_loc = "on data"
        sc.pl.umap(
            adata,
            color=col,
            show=False,
            ax=ax,
            size=5,
            legend_loc=leg_loc,
            layer="acosh",
        )
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "GSE159677_harmony_umap_panel.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ensure_dirs()

    print("Step 1. Read aggregated GSE159677 matrix")
    adata = read_gse159677_aggregate(INPUT_DIR)
    print(adata)
    adata.write_h5ad(RAW_H5AD, compression="gzip")

    print("\nStep 2. RBC diagnostics and removal")
    adata = plot_rbc_diagnostics(adata)
    adata_rbc = adata[adata.obs["RBC_score_high"] == "no"].copy()
    print(f"Cells after RBC removal: {adata_rbc.n_obs}")
    adata_rbc.write_h5ad(RBC_REMOVED_H5AD, compression="gzip")

    print("\nStep 3. Pre-QC clustering for scDblFinder")
    adata_rbc = make_preqc_clusters(adata_rbc)

    print("\nStep 4. Run scDblFinder")
    adata_doublet = run_scDblFinder(adata_rbc)
    calc_basic_qc(adata_doublet)
    sanitize_obs_for_h5ad(adata_doublet)
    adata_doublet.write_h5ad(DOUBLET_H5AD, compression="gzip")

    print("\nStep 5. Formal QC plots and filtering")
    plot_formal_qc(adata_doublet)
    adata_filt = apply_formal_qc(adata_doublet)

    print("\nStep 6. Build groups for scran")
    adata_pp = adata_filt.copy()
    sc.pp.log1p(adata_pp)
    sc.pp.pca(adata_pp, n_comps=15, use_highly_variable=False, svd_solver="arpack")
    sc.pp.neighbors(adata_pp, n_neighbors=N_NEIGHBORS, n_pcs=10, metric="euclidean")
    sc.tl.leiden(adata_pp, key_added="leiden_filt", resolution=SCRAN_GROUP_RES, random_state=0)
    adata_filt.obs["leiden_filt"] = adata_pp.obs["leiden_filt"].astype(str).values

    print("\nStep 7. scran + acosh normalization")
    adata_norm = run_acosh_norm(adata_filt)
    adata_norm.X = adata_norm.layers["acosh"].copy()
    sanitize_obs_for_h5ad(adata_norm)
    adata_norm.write_h5ad(FILTERED_H5AD, compression="gzip")

    print("\nStep 8. Plot normalized UMAP")
    sc.pp.pca(adata_norm, n_comps=15, use_highly_variable=False, svd_solver="arpack")
    sc.pp.neighbors(adata_norm, n_neighbors=N_NEIGHBORS, n_pcs=15, metric="euclidean")
    sc.tl.umap(adata_norm, random_state=0)
    plot_normalized_umap(adata_norm)

    print("\nStep 9. Harmony batch correction")
    adata_harmony = run_harmony(adata_norm)
    plot_harmony_umap(adata_harmony)
    sanitize_obs_for_h5ad(adata_harmony)
    adata_harmony.write_h5ad(FINAL_H5AD, compression="gzip")

    print("\nDone.")
    print(f"saved: {RAW_H5AD}")
    print(f"saved: {RBC_REMOVED_H5AD}")
    print(f"saved: {DOUBLET_H5AD}")
    print(f"saved: {FILTERED_H5AD}")
    print(f"saved: {FINAL_H5AD}")
    print(f"plots: {PLOT_DIR}")


if __name__ == "__main__":
    main()
