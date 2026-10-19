from pathlib import Path
import os
from io import BytesIO
import gzip
import json

import h5py
import numpy as np
import pandas as pd
from scipy import sparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable

ROOT = Path(os.environ["ATHEROMAP_GSMAP_WORK_DIR"]).expanduser().resolve()
BASE = ROOT / "data/spatial/GSE241346"
OUT = ROOT / "results/carotid_gsmap_validation/GSE241346_QC_markers_atheromap"
OUT.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "GSE241346_sample1": "GSM7727539_sample1",
    "GSE241346_sample2": "GSM7727540_sample2",
}
PANELS = {
    "01_contractile_SMC": ["MYH11", "CNN1", "TAGLN", "ACTA2"],
    "02_ECM_stromal": ["COL1A1", "COL1A2", "COL3A1", "LUM", "DCN"],
    "03_macrophage": ["LST1", "TYROBP", "CD68", "HMOX1"],
    "04_foamy_state": ["TREM2", "APOE", "LPL", "PLIN2"],
    "05_B_plasma": ["MS4A1", "CD79A", "CD37", "MZB1", "JCHAIN", "SDC1"],
    "06_T_NK": ["CD3D", "CD3E", "NKG7", "GNLY"],
}
GENES = list(dict.fromkeys(g for genes in PANELS.values() for g in genes))

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "pdf.fonttype": 42,
    "savefig.facecolor": "white",
})

def decode(x):
    return x.decode("utf-8") if isinstance(x, (bytes, np.bytes_)) else x

def vector(node):
    if isinstance(node, h5py.Dataset):
        return [decode(x) for x in node[()]]
    if "categories" in node and "codes" in node:
        cats = vector(node["categories"])
        codes = node["codes"][()]
        if np.any(codes < -1) or np.any(codes >= len(cats)):
            raise ValueError("分类编码异常")
        return [None if c == -1 else cats[int(c)] for c in codes]
    raise ValueError(f"未知字段编码：{node.name}")

def read_counts(node):
    if isinstance(node, h5py.Dataset):
        return sparse.csr_matrix(node[()])
    encoding = decode(node.attrs.get("encoding-type", ""))
    shape = tuple(node.attrs["shape"])
    constructor = {
        "csr_matrix": sparse.csr_matrix,
        "csc_matrix": sparse.csc_matrix,
    }.get(encoding)
    if constructor is None:
        raise ValueError(f"不支持的 count 编码：{encoding}")
    return constructor(
        (node["data"][()], node["indices"][()], node["indptr"][()]),
        shape=shape,
    ).tocsr()

def positions(path):
    cols = [
        "spot", "in_tissue", "array_row", "array_col",
        "y", "x",
    ]
    t = pd.read_csv(path, header=None, dtype=str)
    if t.shape[1] != 6:
        raise ValueError(f"坐标表不是6列：{path}")
    if str(t.iloc[0, 0]).lower() == "barcode":
        t = t.iloc[1:].copy()
    t.columns = cols
    if t.spot.isna().any() or t.spot.duplicated().any():
        raise ValueError("原始坐标 barcode 缺失或重复")
    for col in cols[1:]:
        t[col] = pd.to_numeric(t[col], errors="raise")
    return t.set_index("spot")

def save(fig, stem):
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"{stem}.{ext}", dpi=250)
    plt.close(fig)

data = {}
gene_audit, coordinate_audit, source_files, domain_rows = [], [], [], []

for sample, prefix in SAMPLES.items():
    print(f"读取 {sample}", flush=True)
    h5ad = BASE / "h5ad" / f"{sample}_gsmap_spagcn.h5ad"
    raw = BASE / "raw"
    posfile = raw / f"{prefix}_tissue_positions_list.csv.gz"
    imgfile = raw / f"{prefix}_tissue_hires_image.png.gz"
    scalefile = raw / f"{prefix}_scalefactors_json.json.gz"

    for p in (h5ad, posfile, imgfile, scalefile):
        if not p.is_file():
            raise FileNotFoundError(p)
        source_files.append({"sample": sample, "path": str(p)})

    with h5py.File(h5ad, "r") as f:
        obs, var = f["obs"], f["var"]
        ids = pd.Index(vector(obs[decode(obs.attrs["_index"])]), name="spot")
        names = np.asarray(
            vector(var[decode(var.attrs["_index"])]), dtype=str
        )
        domain = vector(obs["annotation"])
        h5xy = np.asarray(f["obsm/spatial"][()], dtype=float)
        if "layers/count" not in f:
            raise ValueError(f"{sample} 缺少 layers/count")
        X = read_counts(f["layers/count"])

    if ids.has_duplicates or ids.isna().any():
        raise ValueError(f"{sample} spot ID 异常")
    if any(pd.isna(x) for x in domain):
        raise ValueError(f"{sample} annotation 缺失")
    if X.shape != (len(ids), len(names)):
        raise ValueError(f"{sample} 表达矩阵维度不匹配")

    X.sum_duplicates()
    X.eliminate_zeros()
    if (
        not np.isfinite(X.data).all()
        or (X.data < 0).any()
        or not np.allclose(X.data, np.rint(X.data), atol=1e-6, rtol=0)
    ):
        raise ValueError(f"{sample} count 层不是有限、非负的整数计数")

    total = np.asarray(X.sum(axis=1)).ravel().astype(float)
    detected = np.diff(X.indptr)
    pos = positions(posfile)

    if len(ids.difference(pos.index)):
        raise ValueError(f"{sample} 有 barcode 在原始坐标表中不存在")
    retained = pos.loc[ids].copy()
    xy = retained[["x", "y"]].to_numpy(dtype=float)
    if not np.isfinite(xy).all():
        raise ValueError("原始坐标存在 NA/Inf")

    with gzip.open(scalefile, "rt") as f:
        scale = float(json.load(f)["tissue_hires_scalef"])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("图像缩放参数异常")
    with gzip.open(imgfile, "rb") as f:
        image = plt.imread(BytesIO(f.read()), format="png")
    if not np.isfinite(image).all():
        raise ValueError("图像含异常像素")

    h, w = image.shape[:2]
    px = xy * scale
    outside = (
        (px[:, 0] < -0.5) | (px[:, 0] > w - 0.5)
        | (px[:, 1] < -0.5) | (px[:, 1] > h - 0.5)
    )
    if outside.any():
        raise ValueError(f"{sample} 保留 spot 圆心超出图像范围")

    # 仅报告坐标差异；不改变用于既有分析的坐标。
    candidates = {
        "fullres_xy": xy,
        "hires_xy": xy * scale,
        "fullres_yx": xy[:, ::-1],
        "hires_yx": (xy * scale)[:, ::-1],
    }
    matches = [
        key for key, value in candidates.items()
        if h5xy.shape == value.shape
        and np.allclose(h5xy, value, atol=1, rtol=0)
    ]
    coordinate_audit.append({
        "sample": sample,
        "n_retained": len(ids),
        "n_raw_in_tissue": int(pos.in_tissue.eq(1).sum()),
        "n_raw_in_tissue_not_retained": int(
            (pos.in_tissue.eq(1) & ~pos.index.isin(ids)).sum()
        ),
        "n_retained_outside_raw_tissue_mask": int(
            retained.in_tissue.ne(1).sum()
        ),
        "n_zero_count_spots": int((total == 0).sum()),
        "h5ad_coordinate_match": ";".join(matches) or "not_matched",
        "visual_registration": "pending_visual_review",
    })

    frame = pd.DataFrame({
        "x": xy[:, 0], "y": xy[:, 1],
        "domain": [str(x) for x in domain],
        "counts_retained_genes": total,
        "genes_detected_retained_genes": detected,
    }, index=ids)

    # 使用 count 层全部保留基因作为归一化分母。
    # 不修改原始矩阵。零总量 spot 表达记 NA。
    expr, raw_gene = {}, {}
    for gene in GENES:
        columns = np.flatnonzero(names == gene)
        gene_audit.append({
            "sample": sample, "gene": gene,
            "matched_var_columns": len(columns),
        })
        if not len(columns):
            continue
        counts = np.asarray(X[:, columns].sum(axis=1)).ravel()
        values = np.full(len(ids), np.nan)
        ok = total > 0
        values[ok] = np.log1p(1e4 * counts[ok] / total[ok])
        expr[gene] = values
        raw_gene[gene] = counts

        for label in sorted(frame.domain.unique()):
            mask = frame.domain.eq(label).to_numpy()
            valid = mask & ok
            domain_rows.append({
                "sample": sample, "domain": label, "gene": gene,
                "n_spots": int(mask.sum()),
                "n_positive_total_spots": int(valid.sum()),
                "mean_log1p_per_10k": (
                    float(values[valid].mean()) if valid.any() else np.nan
                ),
                "fraction_detected_positive_total": (
                    float((counts[valid] > 0).mean()) if valid.any() else np.nan
                ),
            })

    if not expr:
        raise ValueError(
            f"{sample} 未匹配到任何标志基因；需先检查 var 的基因标识"
        )

    data[sample] = dict(
        frame=frame, pos=pos, image=image, scale=scale, expr=expr
    )
    export = frame.join(pd.DataFrame(expr, index=ids))
    export.to_csv(
        OUT / f"{sample}_spot_QC_marker_values.tsv.gz",
        sep="\t", compression="gzip", na_rep="NA",
    )
    print(
        f"  spots={len(ids)}, genes={X.shape[1]}, "
        f"markers={len(expr)}/{len(GENES)}, coordinate_match={matches}",
        flush=True,
    )
    del X

def image_on(ax, item):
    image, scale = item["image"], item["scale"]
    h, w = image.shape[:2]
    ax.imshow(
        image, origin="upper", interpolation="nearest",
        cmap="gray" if image.ndim == 2 else None,
        extent=(-0.5/scale, (w-0.5)/scale, (h-0.5)/scale, -0.5/scale),
    )

def finish(ax, item, full=False):
    if full:
        h, w = item["image"].shape[:2]
        ax.set_xlim(-0.5/item["scale"], (w-0.5)/item["scale"])
        ax.set_ylim((h-0.5)/item["scale"], -0.5/item["scale"])
    else:
        frame = item["frame"]
        xmin, xmax = frame.x.min(), frame.x.max()
        ymin, ymax = frame.y.min(), frame.y.max()
        pad = 0.04 * max(xmax-xmin, ymax-ymin, 1)
        ax.set_xlim(xmin-pad, xmax+pad)
        ax.set_ylim(ymax+pad, ymin-pad)
    ax.set_aspect("equal")
    ax.set_axis_off()

# 每个样本一张 2×3 的 QC 图。
for sample, item in data.items():
    fig, axes = plt.subplots(2, 3, figsize=(15, 10), constrained_layout=True)
    ax = axes.ravel()
    frame, pos = item["frame"], item["pos"]
    for a in ax:
        image_on(a, item)

    ax[0].set_title("Tissue image")

    mask = pos.in_tissue.eq(1)
    ax[1].scatter(
        pos.loc[mask, "x"], pos.loc[mask, "y"],
        s=8, facecolors="none", edgecolors="#00bfff", linewidths=0.4,
    )
    ax[1].set_title(f"Original in_tissue=1: {mask.sum()} spots")

    excluded = mask & ~pos.index.isin(frame.index)
    ax[2].scatter(
        frame.x, frame.y, s=8, facecolors="none",
        edgecolors="#00bfff", linewidths=0.4, label="Retained",
    )
    ax[2].scatter(
        pos.loc[excluded, "x"], pos.loc[excluded, "y"],
        s=12, c="#ff9900", marker="x", linewidths=0.7,
        label="In tissue, not retained",
    )
    ax[2].legend(loc="upper right", fontsize=8)
    ax[2].set_title("Retained / not retained")

    for a, values, title, cmap in [
        (ax[3], np.log1p(frame.counts_retained_genes),
         "log1p(total counts); retained genes", "viridis"),
        (ax[4], frame.genes_detected_retained_genes,
         "Detected genes; retained genes", "viridis"),
    ]:
        sc = a.scatter(
            frame.x, frame.y, s=9, c=values, cmap=cmap, linewidths=0
        )
        a.set_title(title)
        fig.colorbar(sc, ax=a, shrink=0.65)

    labels = sorted(frame.domain.unique())
    cmap = plt.get_cmap("tab10")
    for i, label in enumerate(labels):
        sub = frame.loc[frame.domain.eq(label)]
        ax[5].scatter(
            sub.x, sub.y, s=9, color=cmap(i), linewidths=0,
            alpha=0.65, label=f"D{label}",
        )
    ax[5].legend(loc="upper right", ncol=2, fontsize=8)
    ax[5].set_title("Domains on tissue")

    for a in ax:
        finish(a, item, full=True)
    fig.suptitle(
        f"{sample} | Spatial QC\n"
        "Original mask is not independent histological validation",
        fontsize=14,
    )
    save(fig, f"{sample}_QC")

# 每个基因：两个样本共享色标。
# 用合并非零表达的 99% 分位数作显示上限；只影响颜色。
scale_rows = []
for panel, genes in PANELS.items():
    fig, axes = plt.subplots(
        2, len(genes), figsize=(3.4*len(genes), 7.4),
        squeeze=False, constrained_layout=True,
    )
    for col, gene in enumerate(genes):
        arrays = [
            item["expr"][gene] for item in data.values()
            if gene in item["expr"]
        ]
        joined = np.concatenate(arrays) if arrays else np.array([])
        positive = joined[np.isfinite(joined) & (joined > 0)]
        vmax = float(np.quantile(positive, 0.99)) if len(positive) else 1.0
        norm = Normalize(0, max(vmax, 1e-6))
        scale_rows.append({
            "gene": gene, "vmin": 0, "vmax": vmax,
            "n_values_above_display_max": int((joined > vmax).sum()),
        })

        for row, (sample, item) in enumerate(data.items()):
            a = axes[row, col]
            frame = item["frame"]
            a.scatter(frame.x, frame.y, s=9, c="#dddddd", linewidths=0)

            if gene in item["expr"]:
                values = item["expr"][gene]
                valid = np.isfinite(values)
                a.scatter(
                    frame.x.to_numpy()[valid], frame.y.to_numpy()[valid],
                    s=9, c=values[valid], cmap="Reds", norm=norm,
                    linewidths=0,
                )
                status = "" if np.any(values[valid] > 0) else "\nNot detected"
            else:
                status = "\nNot in retained gene matrix"

            a.set_title(f"{sample.replace('GSE241346_', '')} | {gene}{status}")
            finish(a, item)

        cb = fig.colorbar(
            ScalarMappable(norm=norm, cmap="Reds"),
            ax=axes[:, col].tolist(), shrink=0.55,
            extend="max" if np.any(joined > vmax) else "neither",
        )
        cb.set_label("log1p(count / total × 10,000)", fontsize=8)

    fig.suptitle(
        panel + "\nSame-gene scale shared across samples; "
        "display capped at pooled positive-expression P99",
        fontsize=12,
    )
    save(fig, panel)

pd.DataFrame(domain_rows).to_csv(
    OUT / "domain_marker_summary.tsv", sep="\t", index=False
)
pd.DataFrame(gene_audit).to_csv(
    OUT / "marker_availability.tsv", sep="\t", index=False
)
pd.DataFrame(coordinate_audit).to_csv(
    OUT / "coordinate_QC_audit.tsv", sep="\t", index=False
)
pd.DataFrame(scale_rows).to_csv(
    OUT / "marker_display_scales.tsv", sep="\t", index=False
)
pd.DataFrame(source_files).to_csv(
    OUT / "input_files.tsv", sep="\t", index=False
)

(OUT / "README.txt").write_text(
    "QC uses the existing count layer and retained genes only.\n"
    "It does not reconstruct QC before gene filtering.\n"
    "In-tissue spots absent from the H5AD are labelled not retained; "
    "their exclusion reason is not inferred here.\n"
    "Marker expression is log1p(count / retained-gene total * 10000).\n"
    "Marker colors share a scale across samples for the same gene only.\n"
    "Upper display limits are pooled positive-expression P99; "
    "saved numeric values are not clipped.\n"
    "Missing genes are not interpreted as absent cell types.\n"
    "No spatial registration is certified automatically.\n"
    "No GWAS values, statistical tests, new filtering or annotation changes.\n",
    encoding="utf-8",
)

print("\n坐标/QC摘要：")
print(pd.DataFrame(coordinate_audit).to_string(index=False))
print("\n缺失的标志基因：")
missing = pd.DataFrame(gene_audit)
missing = missing.loc[missing.matched_var_columns.eq(0)]
print(missing.to_string(index=False) if len(missing) else "无")

print("\n完成，输出目录：", OUT)
print("先查看 *_QC.png，再查看 01 至 06 标志基因图。")
print("图像配准尚需人工查看；未修改原数据或已有结果。")
