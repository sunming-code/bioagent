from pathlib import Path
import os
from io import BytesIO
import gzip
import json

import h5py
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch

ROOT = Path(os.environ["ATHEROMAP_GSMAP_WORK_DIR"]).expanduser().resolve()
BASE = ROOT / "data/spatial/GSE241346"
RESULTS = ROOT / "results/gsmap_quick_mode/GSE241346"
OUT = ROOT / "results/carotid_gsmap_validation/GSE241346_triptych_atheromap"
OUT.mkdir(parents=True, exist_ok=True)
TRAIT = "GCST007435"
MISSING = "#bdbdbd"

SAMPLES = {
    "GSE241346_sample1": "GSM7727539_sample1",
    "GSE241346_sample2": "GSM7727540_sample2",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
    "legend.frameon": False,
    "savefig.facecolor": "white",
})


def decode(x):
    return x.decode("utf-8") if isinstance(x, bytes) else x


def vector(node):
    if isinstance(node, h5py.Dataset):
        return [decode(x) for x in node[()]]
    if "categories" in node and "codes" in node:
        categories = vector(node["categories"])
        codes = node["codes"][()]
        if np.any(codes < -1) or np.any(codes >= len(categories)):
            raise ValueError(f"分类编码异常：{node.name}")
        return [None if c == -1 else categories[int(c)] for c in codes]
    raise ValueError(f"不支持的字段格式：{node.name}")


def read_positions(path):
    # 兼容旧版无表头和新版有表头的 Space Ranger 坐标表。
    names = [
        "barcode", "in_tissue", "array_row", "array_col",
        "pxl_row_in_fullres", "pxl_col_in_fullres",
    ]
    table = pd.read_csv(path, header=None, dtype=str)
    if table.shape[1] != 6:
        raise ValueError(f"空间坐标表不是 6 列：{path}")
    if str(table.iloc[0, 0]).strip().lower() == "barcode":
        table = table.iloc[1:].copy()
    table.columns = names
    if table.barcode.isna().any() or table.barcode.duplicated().any():
        raise ValueError(f"原始坐标表 barcode 缺失或重复：{path}")
    for col in names[1:]:
        table[col] = pd.to_numeric(table[col], errors="raise")
    return table.set_index("barcode")


data, audit, sources = {}, [], []

for sample, prefix in SAMPLES.items():
    print(f"读取：{sample}", flush=True)
    h5ad = BASE / "h5ad" / f"{sample}_gsmap_spagcn.h5ad"
    ldsc_path = (
        RESULTS / sample / "spatial_ldsc"
        / f"{sample}_{TRAIT}.csv.gz"
    )
    raw = BASE / "raw"
    position_path = raw / f"{prefix}_tissue_positions_list.csv.gz"
    image_path = raw / f"{prefix}_tissue_hires_image.png.gz"
    scale_path = raw / f"{prefix}_scalefactors_json.json.gz"

    for kind, path in [
        ("h5ad", h5ad), ("ldsc", ldsc_path),
        ("positions", position_path), ("image", image_path),
        ("scalefactors", scale_path),
    ]:
        if not path.is_file():
            raise FileNotFoundError(path)
        sources.append({
            "sample": sample, "kind": kind, "path": str(path)
        })

    # 只读注释、barcode 和坐标，不加载表达矩阵。
    with h5py.File(h5ad, "r") as f:
        obs = f["obs"]
        index_key = decode(obs.attrs.get("_index", "_index"))
        ids = pd.Index(vector(obs[index_key]), name="spot")
        annotation = vector(obs["annotation"])
        original_xy = np.asarray(f["obsm/spatial"][()], dtype=float)

    if ids.has_duplicates or ids.isna().any():
        raise ValueError(f"{sample}：h5ad barcode 缺失或重复")
    if any(x is None or pd.isna(x) for x in annotation):
        raise ValueError(f"{sample}：存在缺失注释")
    if original_xy.shape != (len(ids), 2) or not np.isfinite(original_xy).all():
        raise ValueError(f"{sample}：h5ad 空间坐标异常")

    positions = read_positions(position_path)
    absent = ids.difference(positions.index)
    if len(absent):
        raise ValueError(f"{sample}：{len(absent)} 个 spot 缺少原始坐标")
    positions = positions.loc[ids]

    # 原始 Space Ranger 坐标中：x=像素列，y=像素行。
    xy = positions[
        ["pxl_col_in_fullres", "pxl_row_in_fullres"]
    ].to_numpy(dtype=float)
    if not np.isfinite(xy).all():
        raise ValueError(f"{sample}：原始坐标存在 NA/Inf")

    with gzip.open(scale_path, "rt") as f:
        scale = float(json.load(f)["tissue_hires_scalef"])
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError(f"{sample}：无效图像缩放参数")

    with gzip.open(image_path, "rb") as f:
        image = plt.imread(BytesIO(f.read()), format="png")

    if not np.isfinite(image).all():
        raise ValueError(f"{sample}：组织图像存在无效像素")
    height, width = image.shape[:2]
    scaled_xy = xy * scale
    outside = (
        (scaled_xy[:, 0] < -0.5)
        | (scaled_xy[:, 0] > width - 0.5)
        | (scaled_xy[:, 1] < -0.5)
        | (scaled_xy[:, 1] > height - 0.5)
    )
    if outside.any():
        raise ValueError(
            f"{sample}：{outside.sum()} 个 spot 圆心超出图像；"
            "请先核对坐标和图像，不自动调整方向。"
        )

    frame = pd.DataFrame({
        "x": xy[:, 0],
        "y": xy[:, 1],
        "annotation": [str(x) for x in annotation],
    }, index=ids)

    ldsc = pd.read_csv(ldsc_path, dtype={"spot": str})
    if not {"spot", "p"}.issubset(ldsc.columns):
        raise ValueError(f"{sample}：LDSC 缺少 spot/p 列")
    if ldsc.spot.isna().any() or ldsc.spot.duplicated().any():
        raise ValueError(f"{sample}：LDSC barcode 缺失或重复")
    ldsc = ldsc.set_index("spot")
    if len(ldsc.index.difference(ids)):
        raise ValueError(f"{sample}：LDSC 中存在 h5ad 没有的 spot")

    p = pd.to_numeric(ldsc["p"], errors="raise")
    bad = p.notna() & (~np.isfinite(p) | (p < 0) | (p > 1))
    if bad.any():
        raise ValueError(f"{sample}：存在非法 P 值")
    frame["p"] = p.reindex(ids)
    frame["neglog10p"] = -np.log10(frame["p"].clip(lower=1e-300))

    labels = sorted(
        frame.annotation.unique(),
        key=lambda x: (0, int(x)) if x.isdigit() else (1, x),
    )
    if len(labels) > 20:
        raise ValueError(f"{sample}：区域超过 20 个，需另选配色")
    palette = plt.get_cmap("tab10" if len(labels) <= 10 else "tab20")
    colors = {label: palette(i) for i, label in enumerate(labels)}

    # 仅诊断 h5ad 的坐标单位；绘图始终按原始 barcode 坐标对齐。
    candidates = {
        "matches_raw_fullres": xy,
        "matches_raw_hires": xy * scale,
        "matches_raw_fullres_xy_swapped": xy[:, ::-1],
        "matches_raw_hires_xy_swapped": (xy * scale)[:, ::-1],
    }
    matches = [
        name for name, candidate in candidates.items()
        if np.allclose(original_xy, candidate, atol=1.0, rtol=0)
    ]
    coordinate_note = ";".join(matches) if matches else "different_from_checked_forms"

    audit.append({
        "sample": sample,
        "n_spots": len(frame),
        "n_domains": len(labels),
        "n_ldsc_rows": len(ldsc),
        "n_valid_p": int(frame.p.notna().sum()),
        "n_missing_p": int(frame.p.isna().sum()),
        "n_zero_p": int(frame.p.eq(0).sum()),
        "n_not_in_tissue": int(positions.in_tissue.ne(1).sum()),
        "image_width": width,
        "image_height": height,
        "tissue_hires_scalef": scale,
        "n_centers_outside_image": int(outside.sum()),
        "h5ad_coordinate_check": coordinate_note,
        "plot_coordinates": "raw positions: x=column, y=row",
        "visual_registration": "pending_visual_review",
    })
    data[sample] = {
        "frame": frame, "image": image, "scale": scale,
        "labels": labels, "colors": colors,
    }
    print(
        f"  spot={len(frame)}, domains={len(labels)}, "
        f"有效P={frame.p.notna().sum()}, 坐标检查={coordinate_note}",
        flush=True,
    )

values = np.concatenate([
    item["frame"].neglog10p.to_numpy() for item in data.values()
])
values = values[np.isfinite(values)]
if not len(values):
    raise ValueError("两个样本均没有有效 P 值")
vmax = max(float(values.max()), 1e-6)
norm = Normalize(vmin=0, vmax=vmax)


def finish_axis(ax, frame):
    xmin, xmax = frame.x.min(), frame.x.max()
    ymin, ymax = frame.y.min(), frame.y.max()
    pad = 0.04 * max(xmax - xmin, ymax - ymin, 1.0)
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymax + pad, ymin - pad)
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()


def tissue(ax, item):
    image, scale = item["image"], item["scale"]
    h, w = image.shape[:2]
    ax.imshow(
        image, origin="upper", interpolation="nearest",
        cmap="gray" if image.ndim == 2 else None,
        extent=(
            -0.5 / scale, (w - 0.5) / scale,
            (h - 0.5) / scale, -0.5 / scale,
        ),
    )


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=300)
    plt.close(fig)


def triptych(samples, name):
    height = 1.8 + 3.8 * len(samples)
    fig, axes = plt.subplots(
        len(samples), 3, figsize=(14.5, height), squeeze=False
    )
    fig.subplots_adjust(
        left=0.025, right=0.90, bottom=0.14, top=0.87,
        wspace=0.16, hspace=0.65,
    )

    for row, sample in enumerate(samples):
        item = data[sample]
        frame = item["frame"]
        axs = axes[row]
        tissue(axs[0], item)

        for label in item["labels"]:
            part = frame.loc[frame.annotation.eq(label)]
            axs[1].scatter(
                part.x, part.y, s=9,
                color=item["colors"][label], linewidths=0,
            )

        axs[2].scatter(frame.x, frame.y, s=9, c=MISSING, linewidths=0)
        valid = frame.neglog10p.notna()
        axs[2].scatter(
            frame.loc[valid, "x"], frame.loc[valid, "y"],
            s=9, c=frame.loc[valid, "neglog10p"],
            cmap="Reds", norm=norm, linewidths=0,
        )

        for ax in axs:
            finish_axis(ax, frame)

        axs[0].set_title(f"{sample}\nTissue image", fontsize=11)
        axs[1].set_title("SpaGCN spatial domains", fontsize=11)
        axs[2].set_title(
            TRAIT + r": spatial LDSC $-\log_{10}(P)$", fontsize=11
        )

        # 每个样本使用自己的区域图例，不暗示跨样本区域对应。
        axs[1].legend(
            handles=[
                Patch(facecolor=item["colors"][x], label=f"Domain {x}")
                for x in item["labels"]
            ],
            loc="upper center", bbox_to_anchor=(0.5, -0.04),
            ncol=3, fontsize=8, borderaxespad=0,
        )

    cax = fig.add_axes([0.928, 0.34, 0.013, 0.32])
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap="Reds"), cax=cax)
    cb.set_label(r"$-\log_{10}(P)$")
    fig.suptitle(
        "Human carotid plaque | GSE241346",
        y=0.97, fontsize=15,
    )
    fig.text(
        0.5, 0.025,
        "Domain IDs are sample-specific. Shared association scale across both samples.\n"
        "Grey spots: missing P values. Tissue staining type has not been verified.",
        ha="center", fontsize=9, color="#555555",
    )
    save(fig, name)


triptych(list(SAMPLES), "GSE241346_two_samples_triptych")
for sample in SAMPLES:
    triptych([sample], f"{sample}_triptych")

# 单独输出对齐检查图，不把 spot 覆盖在主图的组织面板上。
fig, axes = plt.subplots(1, 2, figsize=(12, 6))
fig.subplots_adjust(left=0.03, right=0.97, bottom=0.08, top=0.88)
for ax, sample in zip(axes, SAMPLES):
    item = data[sample]
    frame = item["frame"]
    tissue(ax, item)
    ax.scatter(
        frame.x, frame.y, s=9, facecolors="none",
        edgecolors="#00bfff", linewidths=0.4,
    )
    finish_axis(ax, frame)
    ax.set_title(sample, fontsize=11)
fig.suptitle("Registration check: retained spot centres on tissue")
save(fig, "QA_tissue_spot_alignment")

pd.DataFrame(audit).to_csv(OUT / "plot_audit.tsv", sep="\t", index=False)
pd.DataFrame(sources).to_csv(OUT / "input_files.tsv", sep="\t", index=False)

pd.concat([
    item["frame"].assign(sample=sample).reset_index()
    for sample, item in data.items()
], ignore_index=True).to_csv(
    OUT / "plot_source_data.tsv.gz",
    sep="\t", index=False, na_rep="NA", compression="gzip",
)

pd.DataFrame([
    {
        "sample": sample,
        "domain": label,
        "color": matplotlib.colors.to_hex(item["colors"][label]),
    }
    for sample, item in data.items()
    for label in item["labels"]
]).to_csv(OUT / "domain_colors.tsv", sep="\t", index=False)

(OUT / "plot_settings.json").write_text(
    json.dumps({
        "trait": TRAIT,
        "point_size": 9,
        "association_cmap": "Reds",
        "vmin": 0,
        "vmax": vmax,
        "zero_p_display_floor": 1e-300,
        "coordinate_source": "raw Space Ranger positions aligned by barcode",
        "cross_sample_domain_equivalence": "not_assumed",
        "expression_matrix_loaded": False,
    }, indent=2),
    encoding="utf-8",
)

print("\n完成。输出目录：", OUT)
print("合并图：GSE241346_two_samples_triptych.png / .pdf")
print("对齐检查：QA_tissue_spot_alignment.png / .pdf")
print("请先查看对齐检查图，再查看两个样本的三联图。")
print("仅重绘已有结果；未重跑 gsMap，未修改原始数据。")
