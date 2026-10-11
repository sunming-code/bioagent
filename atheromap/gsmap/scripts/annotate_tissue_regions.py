#!/usr/bin/env python
"""
在组织图像上标注推测的解剖学区域。
基于 H&E/DAPI 形态学特征的推测性标注。
"""

import gzip
from pathlib import Path
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import FancyArrowPatch
import matplotlib.patches as mpatches

PROJECT_DIR = Path(os.environ["ATHEROMAP_GSMAP_WORK_DIR"]).expanduser().resolve()
RAW_DIR = PROJECT_DIR / "data/spatial/GSE241346/raw"
OUT_DIR = PROJECT_DIR / "results/presentation_slides"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_image(prefix):
    gz_path = RAW_DIR / f"{prefix}_tissue_hires_image.png.gz"
    tmp_path = Path(f"/tmp/{prefix}_tissue_hires_image.png")
    if not tmp_path.exists():
        with gzip.open(gz_path, "rb") as f_in:
            tmp_path.write_bytes(f_in.read())
    return mpimg.imread(str(tmp_path))


def annotate_sample2():
    """
    Sample2 是 H&E 明场染色，形态学特征更清晰。
    基于颈动脉粥样硬化斑块的典型组织学特征进行标注。
    """
    img = load_image("GSM7727540_sample2")
    h, w = img.shape[:2]

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(img)

    annotations = [
        {
            "label": "Fibrous cap / \nFibrous intima\n(纤维帽/纤维化内膜)",
            "xy": (w * 0.45, h * 0.15),
            "xytext": (w * 0.72, h * 0.05),
            "desc": "致密粉色, 富含SMC/胶原",
        },
        {
            "label": "Media\n(中膜)",
            "xy": (w * 0.15, h * 0.12),
            "xytext": (w * 0.01, h * 0.02),
            "desc": "外层, 有序平滑肌层",
        },
        {
            "label": "Lipid-rich /\nNecrotic core-like\n(脂质丰富/坏死核心样区域)",
            "xy": (w * 0.35, h * 0.42),
            "xytext": (w * 0.60, h * 0.55),
            "desc": "浅粉/疏松, 细胞少",
        },
        {
            "label": "Cellular intima\n(细胞性内膜)",
            "xy": (w * 0.25, h * 0.70),
            "xytext": (w * 0.01, h * 0.82),
            "desc": "深紫, 炎症细胞浸润",
        },
        {
            "label": "Shoulder region\n(肩部区域)",
            "xy": (w * 0.55, h * 0.30),
            "xytext": (w * 0.75, h * 0.30),
            "desc": "FC与脂核交界, 免疫细胞活跃",
        },
    ]

    for ann in annotations:
        ax.annotate(
            ann["label"],
            xy=ann["xy"],
            xytext=ann["xytext"],
            fontsize=9,
            fontweight="bold",
            color="white",
            ha="left",
            va="center",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="black", alpha=0.7),
            arrowprops=dict(
                arrowstyle="->",
                color="yellow",
                lw=2,
                connectionstyle="arc3,rad=0.2",
            ),
        )

    ax.set_title(
        "Sample 2 (H&E): Putative anatomical regions\n"
        "颈动脉斑块推测性解剖区域标注 (需病理确认)",
        fontsize=11, fontweight="bold", pad=10
    )
    ax.axis("off")

    legend_text = (
        "判断依据:\n"
        "• 纤维帽: 致密嗜酸性(粉色)纤维组织, 覆盖于斑块表面\n"
        "• 中膜: 外侧有序排列的平滑肌层\n"
        "• 坏死核心: 浅色/无细胞区域, 脂质/碎片沉积\n"
        "• 细胞性内膜: 深紫色高细胞密度, 炎症浸润\n"
        "• 肩部: FC边缘, 通常富含免疫细胞"
    )
    ax.text(
        0.02, 0.02, legend_text, transform=ax.transAxes,
        fontsize=7, verticalalignment="bottom",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
        fontfamily="sans-serif",
    )

    fig.savefig(OUT_DIR / "annotated_regions_sample2.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("[OK] annotated_regions_sample2.png")


def annotate_sample1():
    """
    Sample1 是 DAPI 荧光, 只能看到核密度。
    通过核密度分布和组织轮廓推测区域。
    """
    img = load_image("GSM7727539_sample1")
    h, w = img.shape[:2]

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(img)

    annotations = [
        {
            "label": "Lumen\n(血管腔)",
            "xy": (w * 0.38, h * 0.38),
            "xytext": (w * 0.15, h * 0.20),
            "desc": "中央空腔",
        },
        {
            "label": "Fibrous cap\n(纤维帽)",
            "xy": (w * 0.40, h * 0.22),
            "xytext": (w * 0.55, h * 0.08),
            "desc": "薄层细胞覆盖管腔表面",
        },
        {
            "label": "Media / Adventitia\n(中膜/外膜)",
            "xy": (w * 0.50, h * 0.15),
            "xytext": (w * 0.75, h * 0.10),
            "desc": "最外层, 较均匀荧光",
        },
        {
            "label": "High cellularity\n(Immune infiltration)\n(高细胞密度/免疫浸润)",
            "xy": (w * 0.70, h * 0.55),
            "xytext": (w * 0.80, h * 0.72),
            "desc": "DAPI亮信号=核密度高",
        },
        {
            "label": "Low cellularity\n(Necrotic core?)\n(低细胞密度/坏死核心?)",
            "xy": (w * 0.30, h * 0.50),
            "xytext": (w * 0.05, h * 0.65),
            "desc": "DAPI暗=细胞少, 可能是NC",
        },
        {
            "label": "Calcification?\n(钙化?)",
            "xy": (w * 0.65, h * 0.68),
            "xytext": (w * 0.80, h * 0.85),
            "desc": "亮绿/白色自发荧光",
        },
    ]

    for ann in annotations:
        ax.annotate(
            ann["label"],
            xy=ann["xy"],
            xytext=ann["xytext"],
            fontsize=9,
            fontweight="bold",
            color="white",
            ha="left",
            va="center",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="black", alpha=0.7),
            arrowprops=dict(
                arrowstyle="->",
                color="cyan",
                lw=2,
                connectionstyle="arc3,rad=0.2",
            ),
        )

    ax.set_title(
        "Sample 1 (DAPI): Putative anatomical regions\n"
        "颈动脉斑块推测性解剖区域标注 (仅基于核密度, 需病理确认)",
        fontsize=11, fontweight="bold", color="white", pad=10
    )
    ax.set_facecolor("black")
    fig.set_facecolor("black")
    ax.axis("off")

    legend_text = (
        "DAPI 判断依据:\n"
        "• 亮蓝 = 核密度高 (细胞多)\n"
        "• 暗蓝 = 核密度低 (细胞少/坏死/脂质)\n"
        "• 绿/白自发荧光 = 可能是钙化/脂质\n"
        "• 中央黑洞 = 血管腔\n"
        "⚠ DAPI 无法可靠区分 FC/NC, 仅供参考"
    )
    ax.text(
        0.02, 0.02, legend_text, transform=ax.transAxes,
        fontsize=7, verticalalignment="bottom", color="white",
        bbox=dict(boxstyle="round", facecolor="black", alpha=0.85, edgecolor="white"),
        fontfamily="sans-serif",
    )

    fig.savefig(OUT_DIR / "annotated_regions_sample1.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("[OK] annotated_regions_sample1.png")


if __name__ == "__main__":
    annotate_sample2()
    annotate_sample1()
    print("\n[DONE] Annotated region images saved.")
