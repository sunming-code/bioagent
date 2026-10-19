#!/usr/bin/env python

import gzip
import json
import random
from pathlib import Path
import os

import cv2
import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import scipy.sparse as sp
from scipy.io import mmread

import SpaGCN as spg
import torch


PROJECT_DIR = Path(os.environ["ATHEROMAP_GSMAP_WORK_DIR"]).expanduser().resolve()

RAW_DIR = PROJECT_DIR / "data" / "spatial" / "GSE241346" / "raw"
OUT_H5AD_DIR = PROJECT_DIR / "data" / "spatial" / "GSE241346" / "h5ad"
OUT_META_DIR = PROJECT_DIR / "data" / "spatial" / "GSE241346" / "metadata"
OUT_PLOT_DIR = PROJECT_DIR / "plots" / "GSE241346_spagcn"
OUT_LOG_DIR = PROJECT_DIR / "logs"

OUT_H5AD_DIR.mkdir(parents=True, exist_ok=True)
OUT_META_DIR.mkdir(parents=True, exist_ok=True)
OUT_PLOT_DIR.mkdir(parents=True, exist_ok=True)
OUT_LOG_DIR.mkdir(parents=True, exist_ok=True)


MIN_COUNTS_PER_SPOT = 100
MIN_GENES_PER_SPOT = 50
MIN_SPOTS_PER_GENE = 3

SPAGCN_P = 0.5
SPAGCN_LR = 0.05
SPAGCN_MAX_EPOCHS = 200
SPAGCN_TOL = 5e-3

R_SEED = 100
T_SEED = 100
N_SEED = 100

SAMPLES = {
    "sample1": {
        "geo_id": "GSM7727539",
        "out_prefix": "GSE241346_sample1",
        "histology": False,
        "alpha": None,
        "target_domains": 7,
    },
    "sample2": {
        "geo_id": "GSM7727540",
        "out_prefix": "GSE241346_sample2",
        "histology": False,
        "alpha": None,
        "target_domains": 7,
    },
}


def find_one(sample_id: str, suffix: str) -> Path:
    hits = sorted(RAW_DIR.rglob(f"*{sample_id}*{suffix}"))
    if len(hits) != 1:
        raise FileNotFoundError(
            f"Expected exactly one file for sample={sample_id}, suffix={suffix}, found {len(hits)}: {hits}"
        )
    return hits[0]


def read_tsv_maybe_gz(path: Path, **kwargs) -> pd.DataFrame:
    compression = "gzip" if path.name.endswith(".gz") else None
    return pd.read_csv(path, sep="\t", compression=compression, **kwargs)


def read_csv_maybe_gz(path: Path, **kwargs) -> pd.DataFrame:
    compression = "gzip" if path.name.endswith(".gz") else None
    return pd.read_csv(path, compression=compression, **kwargs)


def read_10x_from_geo_files(matrix_file: Path, features_file: Path, barcodes_file: Path) -> ad.AnnData:
    with gzip.open(matrix_file, "rb") if matrix_file.name.endswith(".gz") else open(matrix_file, "rb") as fh:
        matrix = mmread(fh).tocsr()

    features = read_tsv_maybe_gz(features_file, header=None)
    barcodes = read_tsv_maybe_gz(barcodes_file, header=None)

    if matrix.shape[0] != features.shape[0]:
        raise ValueError(f"Matrix feature dimension {matrix.shape[0]} != features rows {features.shape[0]}")
    if matrix.shape[1] != barcodes.shape[0]:
        raise ValueError(f"Matrix barcode dimension {matrix.shape[1]} != barcodes rows {barcodes.shape[0]}")

    gene_ids = features.iloc[:, 0].astype(str).to_numpy()
    gene_symbols = features.iloc[:, 1].astype(str).to_numpy() if features.shape[1] >= 2 else gene_ids
    feature_types = (
        features.iloc[:, 2].astype(str).to_numpy()
        if features.shape[1] >= 3
        else np.repeat("Gene Expression", len(gene_ids))
    )

    adata = ad.AnnData(X=matrix.T.tocsr())
    adata.obs_names = barcodes.iloc[:, 0].astype(str).to_numpy()
    adata.var_names = gene_symbols
    adata.var["gene_ids"] = gene_ids
    adata.var["feature_types"] = feature_types

    return adata


def collapse_duplicate_gene_symbols(adata: ad.AnnData) -> ad.AnnData:
    gene_names = pd.Index(adata.var_names.astype(str))

    if gene_names.is_unique:
        return adata

    X = adata.X.tocsc()
    gene_ids = (
        adata.var["gene_ids"].astype(str).to_numpy()
        if "gene_ids" in adata.var
        else gene_names.astype(str).to_numpy()
    )
    feature_types = (
        adata.var["feature_types"].astype(str).to_numpy()
        if "feature_types" in adata.var
        else np.repeat("Gene Expression", adata.n_vars)
    )

    unique_genes = pd.Index(pd.unique(gene_names))
    new_cols = []
    new_gene_ids = []
    new_feature_types = []
    merged_n = []

    for gene in unique_genes:
        idx = np.where(gene_names == gene)[0]
        col_sum = X[:, idx].sum(axis=1)
        new_cols.append(sp.csr_matrix(col_sum))
        new_gene_ids.append(";".join(pd.unique(gene_ids[idx])))
        new_feature_types.append(";".join(pd.unique(feature_types[idx])))
        merged_n.append(len(idx))

    new_X = sp.hstack(new_cols, format="csr")

    new_adata = ad.AnnData(X=new_X, obs=adata.obs.copy())
    new_adata.var_names = unique_genes.astype(str)
    new_adata.var["gene_ids"] = new_gene_ids
    new_adata.var["feature_types"] = new_feature_types
    new_adata.var["n_merged_features"] = merged_n

    return new_adata


def read_positions(position_file: Path) -> pd.DataFrame:
    pos = read_csv_maybe_gz(position_file, header=None)

    if str(pos.iloc[0, 0]).lower() in {"barcode", "barcodes"}:
        pos = read_csv_maybe_gz(position_file, header=0)
        rename_map = {
            "pxl_row_in_fullres": "pxl_row_in_fullres",
            "pxl_col_in_fullres": "pxl_col_in_fullres",
        }
        pos = pos.rename(columns=rename_map)
    else:
        pos.columns = [
            "barcode",
            "in_tissue",
            "array_row",
            "array_col",
            "pxl_row_in_fullres",
            "pxl_col_in_fullres",
        ]

    required = [
        "barcode",
        "in_tissue",
        "array_row",
        "array_col",
        "pxl_row_in_fullres",
        "pxl_col_in_fullres",
    ]
    missing = [x for x in required if x not in pos.columns]
    if missing:
        raise ValueError(f"Missing columns in tissue position file: {missing}")

    pos["barcode"] = pos["barcode"].astype(str)
    pos["in_tissue"] = pos["in_tissue"].astype(int)
    pos["array_row"] = pos["array_row"].astype(float)
    pos["array_col"] = pos["array_col"].astype(float)
    pos["pxl_row_in_fullres"] = pos["pxl_row_in_fullres"].astype(float)
    pos["pxl_col_in_fullres"] = pos["pxl_col_in_fullres"].astype(float)

    pos = pos.set_index("barcode")
    return pos


def read_json_maybe_gz(path: Path) -> dict:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt") as fh:
            return json.load(fh)
    with open(path, "rt") as fh:
        return json.load(fh)


def read_image_maybe_gz(path: Path) -> np.ndarray:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as fh:
            img_bytes = fh.read()
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        img_bgr = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    else:
        img_bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)

    if img_bgr is None:
        raise ValueError(f"Failed to read image: {path}")

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return img_rgb


def add_positions_and_filter_tissue(adata: ad.AnnData, positions: pd.DataFrame) -> ad.AnnData:
    common = adata.obs_names.intersection(positions.index)

    if len(common) == 0:
        raise ValueError("No common barcodes between expression matrix and tissue_positions_list")

    adata = adata[common, :].copy()
    adata.obs = adata.obs.join(positions.loc[adata.obs_names], how="left")

    adata = adata[adata.obs["in_tissue"].astype(int) == 1, :].copy()

    spatial = adata.obs[["pxl_col_in_fullres", "pxl_row_in_fullres"]].to_numpy(dtype=float)
    adata.obsm["spatial"] = spatial

    return adata


def add_qc_metrics(adata: ad.AnnData) -> ad.AnnData:
    adata.obs["total_counts"] = np.asarray(adata.X.sum(axis=1)).ravel()
    adata.obs["n_genes_by_counts"] = np.asarray((adata.X > 0).sum(axis=1)).ravel()
    adata.var["n_spots_by_counts"] = np.asarray((adata.X > 0).sum(axis=0)).ravel()
    return adata


def qc_filter(adata: ad.AnnData) -> tuple[ad.AnnData, pd.DataFrame]:
    adata = add_qc_metrics(adata)

    spot_keep = (
        (adata.obs["total_counts"] >= MIN_COUNTS_PER_SPOT)
        & (adata.obs["n_genes_by_counts"] >= MIN_GENES_PER_SPOT)
    )

    removed_obs = adata.obs.loc[~spot_keep].copy()
    adata = adata[spot_keep, :].copy()

    adata = add_qc_metrics(adata)
    gene_keep = adata.var["n_spots_by_counts"] >= MIN_SPOTS_PER_GENE
    adata = adata[:, gene_keep].copy()
    adata = add_qc_metrics(adata)

    return adata, removed_obs


def plot_removed_spots(before: ad.AnnData, removed_obs: pd.DataFrame, out_file: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(6, 5), dpi=160)

    ax.scatter(
        before.obs["pxl_col_in_fullres"],
        -before.obs["pxl_row_in_fullres"],
        s=8,
        c="lightgrey",
        linewidths=0,
        label="kept candidate",
    )

    if removed_obs.shape[0] > 0:
        ax.scatter(
            removed_obs["pxl_col_in_fullres"],
            -removed_obs["pxl_row_in_fullres"],
            s=12,
            c="#d62728",
            linewidths=0,
            label="removed by QC",
        )

    ax.set_title(title)
    ax.set_xlabel("fullres pixel column")
    ax.set_ylabel("-fullres pixel row")
    ax.set_aspect("equal")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(out_file)
    plt.close(fig)


def plot_annotation(adata: ad.AnnData, out_file: Path, title: str) -> None:
    annot = adata.obs["annotation"].astype(str)
    categories = sorted(annot.unique(), key=lambda x: int(x) if x.isdigit() else x)
    color_map = {cat: plt.cm.tab20(i % 20) for i, cat in enumerate(categories)}
    colors = annot.map(color_map)

    fig, ax = plt.subplots(figsize=(6, 5), dpi=160)
    ax.scatter(
        adata.obs["pxl_col_in_fullres"],
        -adata.obs["pxl_row_in_fullres"],
        s=10,
        c=list(colors),
        linewidths=0,
    )

    handles = [
        plt.Line2D([0], [0], marker="o", linestyle="", color=color_map[cat], markersize=5, label=str(cat))
        for cat in categories
    ]
    ax.legend(handles=handles, title="annotation", frameon=False, fontsize=7, title_fontsize=8)
    ax.set_title(title)
    ax.set_xlabel("fullres pixel column")
    ax.set_ylabel("-fullres pixel row")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(out_file)
    plt.close(fig)


def prepare_spagcn_input(adata: ad.AnnData) -> ad.AnnData:
    spg_adata = adata.copy()
    spg_adata.X = spg_adata.X.astype(np.float32)

    spg.prefilter_genes(spg_adata, min_cells=MIN_SPOTS_PER_GENE)
    spg.prefilter_specialgenes(spg_adata)

    sc.pp.normalize_per_cell(spg_adata)
    sc.pp.log1p(spg_adata)

    return spg_adata


def run_spagcn(adata: ad.AnnData, cfg: dict, scalefactors: dict, image: np.ndarray | None) -> pd.Series:
    random.seed(R_SEED)
    np.random.seed(N_SEED)
    torch.manual_seed(T_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(T_SEED)

    spg_adata = prepare_spagcn_input(adata)

    x_array = spg_adata.obs["array_row"].astype(float).to_numpy()
    y_array = spg_adata.obs["array_col"].astype(float).to_numpy()

    if cfg["histology"]:
        if image is None:
            raise ValueError(f"{cfg['out_prefix']} requested histology=True but image is missing")

        hires_scale = float(scalefactors["tissue_hires_scalef"])
        spot_diameter_fullres = float(scalefactors["spot_diameter_fullres"])
        beta = max(5, int(round(spot_diameter_fullres * hires_scale)))

        x_pixel = np.rint(spg_adata.obs["pxl_row_in_fullres"].to_numpy(dtype=float) * hires_scale).astype(int)
        y_pixel = np.rint(spg_adata.obs["pxl_col_in_fullres"].to_numpy(dtype=float) * hires_scale).astype(int)

        x_pixel = np.clip(x_pixel, 0, image.shape[0] - 1)
        y_pixel = np.clip(y_pixel, 0, image.shape[1] - 1)

        print(
            f"[INFO] {cfg['out_prefix']}: SpaGCN adjacency histology=True, "
            f"alpha={cfg['alpha']}, beta={beta}, hires_scale={hires_scale}"
        )

        adj = spg.calculate_adj_matrix(
            x=x_pixel.tolist(),
            y=y_pixel.tolist(),
            x_pixel=x_pixel.tolist(),
            y_pixel=y_pixel.tolist(),
            image=image,
            beta=beta,
            alpha=cfg["alpha"],
            histology=True,
        )
    else:
        print(f"[INFO] {cfg['out_prefix']}: SpaGCN adjacency histology=False")
        adj = spg.calculate_adj_matrix(
            x=x_array.tolist(),
            y=y_array.tolist(),
            histology=False,
        )

    l_value = spg.search_l(
        SPAGCN_P,
        adj,
        start=0.01,
        end=1000,
        tol=0.01,
        max_run=100,
    )

    print(f"[INFO] {cfg['out_prefix']}: searched l={l_value}")

    res = spg.search_res(
        spg_adata,
        adj,
        l_value,
        cfg["target_domains"],
        start=0.7,
        step=0.1,
        tol=SPAGCN_TOL,
        lr=SPAGCN_LR,
        max_epochs=50,
        r_seed=R_SEED,
        t_seed=T_SEED,
        n_seed=N_SEED,
    )

    print(f"[INFO] {cfg['out_prefix']}: searched louvain resolution={res}")

    clf = spg.SpaGCN()
    clf.set_l(l_value)

    clf.train(
        spg_adata,
        adj,
        init_spa=True,
        init="louvain",
        res=res,
        tol=SPAGCN_TOL,
        lr=SPAGCN_LR,
        max_epochs=SPAGCN_MAX_EPOCHS,
    )

    pred, prob = clf.predict()
    pred = pd.Series(pred, index=spg_adata.obs_names, name="spagcn_pred").astype(str)

    adj_2d = spg.calculate_adj_matrix(
        x=spg_adata.obs["array_row"].astype(float).tolist(),
        y=spg_adata.obs["array_col"].astype(float).tolist(),
        histology=False,
    )

    refined = spg.refine(
        sample_id=spg_adata.obs_names.tolist(),
        pred=pred.tolist(),
        dis=adj_2d,
        shape="hexagon",
    )

    refined = pd.Series(refined, index=spg_adata.obs_names, name="spagcn_refined").astype(str)

    return refined


def process_one_sample(sample_name: str, cfg: dict) -> dict:
    geo_id = cfg["geo_id"]
    out_prefix = cfg["out_prefix"]

    print(f"\n[INFO] Processing {sample_name}: {geo_id}")

    matrix_file = find_one(geo_id, "matrix.mtx.gz")
    features_file = find_one(geo_id, "features.tsv.gz")
    barcodes_file = find_one(geo_id, "barcodes.tsv.gz")
    position_file = find_one(geo_id, "tissue_positions_list.csv.gz")

    scalefactor_file = find_one(geo_id, "scalefactors_json.json.gz")
    hires_image_file = find_one(geo_id, "tissue_hires_image.png.gz")

    print(f"[INFO] matrix:     {matrix_file}")
    print(f"[INFO] features:   {features_file}")
    print(f"[INFO] barcodes:   {barcodes_file}")
    print(f"[INFO] positions:  {position_file}")
    print(f"[INFO] scalefacts: {scalefactor_file}")
    print(f"[INFO] hires img:  {hires_image_file}")

    adata = read_10x_from_geo_files(matrix_file, features_file, barcodes_file)
    n_spots_raw, n_genes_raw = adata.n_obs, adata.n_vars

    duplicated_gene_symbols = int(pd.Index(adata.var_names).duplicated().sum())
    adata = collapse_duplicate_gene_symbols(adata)
    n_genes_after_collapse = adata.n_vars

    positions = read_positions(position_file)
    adata = add_positions_and_filter_tissue(adata, positions)
    n_spots_tissue = adata.n_obs

    before_qc = add_qc_metrics(adata.copy())
    adata, removed_obs = qc_filter(adata)

    n_spots_after_qc, n_genes_after_qc = adata.n_obs, adata.n_vars

    adata.layers["count"] = adata.X.copy()

    scalefactors = read_json_maybe_gz(scalefactor_file)
    image = read_image_maybe_gz(hires_image_file) if cfg["histology"] else None

    refined = run_spagcn(adata, cfg, scalefactors, image)

    adata.obs["spagcn_refined"] = refined.loc[adata.obs_names].astype(str).to_numpy()
    adata.obs["annotation"] = adata.obs["spagcn_refined"].astype(str)

    adata.uns["GSE241346_processing"] = {
        "geo_id": geo_id,
        "sample_name": sample_name,
        "histology": cfg["histology"],
        "alpha": cfg["alpha"],
        "target_domains": cfg["target_domains"],
        "min_counts_per_spot": MIN_COUNTS_PER_SPOT,
        "min_genes_per_spot": MIN_GENES_PER_SPOT,
        "min_spots_per_gene": MIN_SPOTS_PER_GENE,
        "spagcn_p": SPAGCN_P,
        "spagcn_lr": SPAGCN_LR,
        "spagcn_max_epochs": SPAGCN_MAX_EPOCHS,
        "spagcn_tol": SPAGCN_TOL,
        "r_seed": R_SEED,
        "t_seed": T_SEED,
        "n_seed": N_SEED,
    }

    assert adata.var_names.is_unique
    assert "count" in adata.layers
    assert "spatial" in adata.obsm
    assert "annotation" in adata.obs
    assert adata.obs["annotation"].isna().sum() == 0

    h5ad_file = OUT_H5AD_DIR / f"{out_prefix}_gsmap_spagcn.h5ad"
    adata.write_h5ad(h5ad_file)

    annotation_file = OUT_META_DIR / f"{out_prefix}_spagcn_annotation.tsv"
    adata.obs[
        [
            "annotation",
            "spagcn_refined",
            "total_counts",
            "n_genes_by_counts",
            "in_tissue",
            "array_row",
            "array_col",
            "pxl_row_in_fullres",
            "pxl_col_in_fullres",
        ]
    ].to_csv(annotation_file, sep="\t")

    annotation_counts_file = OUT_META_DIR / f"{out_prefix}_spagcn_annotation_counts.tsv"
    adata.obs["annotation"].value_counts().sort_index().to_csv(
        annotation_counts_file,
        sep="\t",
        header=["n_spots"],
    )

    removed_file = OUT_META_DIR / f"{out_prefix}_removed_spots_qc.tsv"
    removed_obs.to_csv(removed_file, sep="\t")

    plot_removed_spots(
        before_qc,
        removed_obs,
        OUT_PLOT_DIR / f"{out_prefix}_removed_spots_qc.png",
        f"{out_prefix}: removed spots by QC",
    )

    plot_annotation(
        adata,
        OUT_PLOT_DIR / f"{out_prefix}_spagcn_annotation.png",
        f"{out_prefix}: SpaGCN annotation",
    )

    return {
        "sample": sample_name,
        "geo_id": geo_id,
        "histology": cfg["histology"],
        "alpha": cfg["alpha"],
        "target_domains": cfg["target_domains"],
        "raw_spots": n_spots_raw,
        "raw_genes": n_genes_raw,
        "duplicated_gene_symbols": duplicated_gene_symbols,
        "genes_after_duplicate_collapse": n_genes_after_collapse,
        "tissue_spots": n_spots_tissue,
        "removed_spots_qc": removed_obs.shape[0],
        "spots_after_qc": n_spots_after_qc,
        "genes_after_qc": n_genes_after_qc,
        "n_annotations": adata.obs["annotation"].nunique(),
        "h5ad": str(h5ad_file),
    }


def main() -> None:
    all_summary = []

    for sample_name, cfg in SAMPLES.items():
        summary = process_one_sample(sample_name, cfg)
        all_summary.append(summary)

    summary_df = pd.DataFrame(all_summary)
    summary_file = OUT_LOG_DIR / "GSE241346_h5ad_spagcn_summary.tsv"
    summary_df.to_csv(summary_file, sep="\t", index=False)

    print("\n[INFO] Finished.")
    print(summary_df.to_string(index=False))
    print(f"[INFO] Summary written to: {summary_file}")


if __name__ == "__main__":
    main()
