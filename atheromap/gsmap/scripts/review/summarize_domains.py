from pathlib import Path
import os
import json
import shutil

import h5py
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable

ROOT = Path(os.environ["ATHEROMAP_GSMAP_WORK_DIR"]).expanduser().resolve()
OUT = ROOT / "results/carotid_gsmap_validation/GSE241346_domain_results_atheromap"
OUT.mkdir(parents=True, exist_ok=True)
PARENT = OUT.parent
TRAIT = "GCST007435"
SAMPLES = ["GSE241346_sample1", "GSE241346_sample2"]

# 两个样本使用完全相同的细胞类型顺序和颜色。
CELLTYPES = [
    "SMC", "Fibromyocyte", "Fibroblast", "EC",
    "Macrophage_HMOX1", "Macrophage_Inflammatory",
    "Macrophage_Other", "Macrophage_PLIN2_TREM1",
    "Macrophage_TREM2_Foamy", "Monocyte", "DC",
    "Neutrophil", "Mast_cell", "B_cell", "Plasma_cell", "T_NK",
]
COLOR_VALUES = [
    "#31688e", "#74a9cf", "#a6bddb", "#41b6c4",
    "#a63603", "#d94801", "#f16913", "#fd8d3c",
    "#fdae6b", "#bdb76b", "#8c6bb1",
    "#c2a5cf", "#8c564b", "#238b45", "#74c476", "#b2df8a",
]
COLORS = dict(zip(CELLTYPES, COLOR_VALUES))

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
    "axes.spines.top": False,
    "axes.spines.right": False,
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
            raise ValueError(f"分类编码异常：{node.name}")
        return [None if c == -1 else cats[int(c)] for c in codes]
    raise ValueError(f"字段编码不支持：{node.name}")


def domain_key(value):
    value = str(value)
    return (0, int(value)) if value.isdigit() else (1, value)


def bh_fdr(values):
    """BH校正；要求当前检验集合中的P值全部有效。"""
    p = np.asarray(values, dtype=float)
    if not len(p) or not np.isfinite(p).all():
        raise ValueError("BH 输入为空或含非有限值")
    if ((p < 0) | (p > 1)).any():
        raise ValueError("BH 输入含非法 P 值")
    order = np.argsort(p, kind="stable")
    ranked = p[order] * len(p) / np.arange(1, len(p) + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    result = np.empty(len(p))
    result[order] = np.clip(adjusted, 0, 1)
    return result


frames = {}
compositions = {}
rows = []
long_rows = []
audit = []
sources = []

for sample in SAMPLES:
    print(f"\n读取：{sample}", flush=True)

    h5ad = (
        ROOT / "data/spatial/GSE241346/h5ad"
        / f"{sample}_gsmap_spagcn.h5ad"
    )
    abundance_file = (
        ROOT / "results/cell2location/spatial_mapping" / sample
        / f"{sample}_means_cell_abundance_w_sf.csv"
    )
    cauchy_file = (
        ROOT / "results/gsmap_quick_mode/GSE241346" / sample
        / "cauchy_combination" / f"{sample}_{TRAIT}.Cauchy.csv.gz"
    )

    for kind, path in [
        ("annotation", h5ad),
        ("posterior_mean_abundance", abundance_file),
        ("cauchy", cauchy_file),
    ]:
        if not path.is_file():
            raise FileNotFoundError(path)
        sources.append({
            "sample": sample, "kind": kind, "path": str(path),
        })

    # 仅读取 h5ad 注释与 barcode，不加载表达矩阵。
    with h5py.File(h5ad, "r") as f:
        obs = f["obs"]
        ids = pd.Index(
            vector(obs[decode(obs.attrs.get("_index", "_index"))]),
            name="spot",
        )
        labels = vector(obs["annotation"])

    if ids.has_duplicates or ids.isna().any():
        raise ValueError(f"{sample}: h5ad barcode 缺失或重复")
    if any(pd.isna(x) for x in labels):
        raise ValueError(f"{sample}: domain 缺失")

    domains = pd.Series(
        [str(x) for x in labels], index=ids, name="domain"
    )
    order = sorted(domains.unique(), key=domain_key)

    abundance = pd.read_csv(abundance_file, index_col=0)
    abundance.index = abundance.index.astype(str)
    if abundance.index.has_duplicates or abundance.columns.duplicated().any():
        raise ValueError(f"{sample}: 丰度表行/列标签重复")

    missing = ids.difference(abundance.index)
    extra = abundance.index.difference(ids)
    if len(missing) or len(extra):
        raise ValueError(
            f"{sample}: barcode 不完全对应，"
            f"缺少={len(missing)}, 额外={len(extra)}"
        )
    if set(abundance.columns) != set(CELLTYPES):
        raise ValueError(
            f"{sample}: 细胞类型与已核实的16类不一致："
            f"{abundance.columns.tolist()}"
        )

    abundance = abundance.loc[ids, CELLTYPES].apply(
        pd.to_numeric, errors="raise"
    )
    values = abundance.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError(f"{sample}: 丰度有 NA/Inf 或负数")

    total = abundance.sum(axis=1)
    positive = total.gt(0)
    shares = abundance.div(total.where(positive), axis=0)
    composition = shares.groupby(domains).mean().loc[order, CELLTYPES]

    if composition.isna().any().any():
        raise ValueError(f"{sample}: 某个 domain 没有可归一化的丰度")
    if not np.allclose(composition.sum(axis=1), 1, atol=1e-6):
        raise ValueError(f"{sample}: domain 组成和不为1")

    cauchy = pd.read_csv(cauchy_file, dtype={"annotation": str})
    if not {"annotation", "p_cauchy"}.issubset(cauchy.columns):
        raise ValueError(f"{sample}: Cauchy 文件缺少必要列")
    if cauchy.annotation.isna().any() or cauchy.annotation.duplicated().any():
        raise ValueError(f"{sample}: Cauchy 区域标签缺失或重复")
    if set(cauchy.annotation) != set(order):
        raise ValueError(
            f"{sample}: Cauchy domain 与 h5ad 不一致；停止避免错配"
        )

    cauchy = cauchy.set_index("annotation").loc[order]
    p = pd.to_numeric(cauchy.p_cauchy, errors="raise").to_numpy()
    q_within = bh_fdr(p)

    for i, domain in enumerate(order):
        mask = domains.eq(domain)
        ranked = composition.loc[domain].sort_values(ascending=False)
        row = {
            "sample": sample,
            "domain": domain,
            "n_spots": int(mask.sum()),
            "n_composition_spots": int((mask & positive).sum()),
            "n_zero_total_abundance": int((mask & ~positive).sum()),
            "p_cauchy": float(p[i]),
            "q_BH_within_sample": float(q_within[i]),
            "top3_composition": "; ".join(
                f"{cell}: {value:.1%}"
                for cell, value in ranked.head(3).items()
            ),
        }
        for cell in CELLTYPES:
            row[f"composition__{cell}"] = float(composition.loc[domain, cell])
            long_rows.append({
                "sample": sample,
                "domain": domain,
                "celltype": cell,
                "mean_spot_normalized_posterior_mean": float(
                    composition.loc[domain, cell]
                ),
            })
        rows.append(row)

    spot_export = shares.copy()
    spot_export.insert(0, "domain", domains)
    spot_export.to_csv(
        OUT / f"{sample}_spot_normalized_composition.tsv.gz",
        sep="\t", compression="gzip", na_rep="NA",
    )
    composition.to_csv(
        OUT / f"{sample}_domain_composition.tsv", sep="\t"
    )
    compositions[sample] = composition
    audit.append({
        "sample": sample,
        "n_spots": len(ids),
        "n_domains": len(order),
        "n_zero_total_abundance": int((~positive).sum()),
        "n_zero_cauchy_p": int((p == 0).sum()),
        "barcode_match": "exact",
    })

summary = pd.DataFrame(rows)
summary["q_BH_all_domains"] = bh_fdr(summary.p_cauchy)
summary["neglog10_p_cauchy"] = -np.log10(
    summary.p_cauchy.clip(lower=1e-300)
)
summary["BH_within_lt_0p05"] = summary.q_BH_within_sample.lt(0.05)
summary["BH_all_lt_0p05"] = summary.q_BH_all_domains.lt(0.05)

summary.to_csv(OUT / "domain_summary.tsv", sep="\t", index=False)
pd.DataFrame(long_rows).to_csv(
    OUT / "domain_composition_long.tsv", sep="\t", index=False
)
pd.DataFrame(audit).to_csv(
    OUT / "data_audit.tsv", sep="\t", index=False
)

# 3行×2列；每一列为一个样本，domain顺序上下对应。
fig = plt.figure(figsize=(17, 15))
grid = fig.add_gridspec(
    3, 2,
    height_ratios=[1.2, 1.2, 2.4],
    left=0.19, right=0.89, bottom=0.19, top=0.89,
    hspace=0.39, wspace=0.26,
)

all_signal_max = max(
    1.0, float(summary.neglog10_p_cauchy.max())
)
heatmax = max(
    float(c.to_numpy().max()) * 100 for c in compositions.values()
)
heatnorm = Normalize(0, max(heatmax, 1e-6))

for col, sample in enumerate(SAMPLES):
    table = summary.loc[summary["sample"].eq(sample)].copy()
    order = table.domain.tolist()
    composition = compositions[sample].loc[order]
    x = np.arange(len(order))
    xticks = [f"D{d}" for d in order]

    # 上：原始 Cauchy P，标签同时报告两种 BH 校正范围。
    ax = fig.add_subplot(grid[0, col])
    ax.bar(x, table.neglog10_p_cauchy, color="#607d8b", width=0.7)
    ax.set_xlim(-0.6, len(order)-0.4)
    ax.set_ylim(0, all_signal_max * 1.55)
    ax.set_xticks(x)
    ax.set_xticklabels(xticks)
    ax.set_ylabel(r"$-\log_{10}(P_{\mathrm{Cauchy}})$")
    ax.set_title(
        f"{sample}\n{TRAIT}: domain association",
        fontsize=12, pad=12,
    )
    for j, row in enumerate(table.itertuples(index=False)):
        text = (
            f"n={row.n_spots}\n"
            f"qW={row.q_BH_within_sample:.3g}\n"
            f"qA={row.q_BH_all_domains:.3g}"
        )
        ax.text(
            j, row.neglog10_p_cauchy + all_signal_max*0.035,
            text, ha="center", va="bottom", fontsize=8,
        )
    ax.grid(axis="y", alpha=0.15)
    ax.set_axisbelow(True)

    # 中：每spot归一化后，按domain平均的组成。
    ax = fig.add_subplot(grid[1, col])
    bottom = np.zeros(len(order))
    for cell in CELLTYPES:
        heights = composition[cell].to_numpy() * 100
        ax.bar(
            x, heights, bottom=bottom, color=COLORS[cell],
            width=0.75, linewidth=0,
        )
        bottom += heights
    ax.set_xlim(-0.6, len(order)-0.4)
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(xticks)
    ax.set_ylabel("Normalized inferred composition (%)")
    ax.set_title("Cell2location composition", fontsize=11)

    # 下：同一组成数据的热图，便于读出较小成分。
    ax = fig.add_subplot(grid[2, col])
    ax.imshow(
        composition.T.to_numpy() * 100,
        cmap="Blues", norm=heatnorm, aspect="auto",
        interpolation="nearest",
        extent=(-0.5, len(order)-0.5, len(CELLTYPES)-0.5, -0.5),
    )
    ax.set_xlim(-0.6, len(order)-0.4)
    ax.set_xticks(x)
    ax.set_xticklabels(xticks)
    ax.set_yticks(np.arange(len(CELLTYPES)))
    ax.set_yticklabels(
        CELLTYPES if col == 0 else [""] * len(CELLTYPES),
        fontsize=9,
    )
    ax.set_xlabel("Sample-specific SpaGCN domain")
    ax.set_title("Composition detail: same values as stacked bars", fontsize=11)
    ax.tick_params(length=0)

cax = fig.add_axes([0.915, 0.22, 0.012, 0.29])
cb = fig.colorbar(
    ScalarMappable(norm=heatnorm, cmap="Blues"), cax=cax
)
cb.set_label("Normalized inferred composition (%)")

fig.legend(
    handles=[Patch(facecolor=COLORS[c], label=c) for c in CELLTYPES],
    loc="lower center", bbox_to_anchor=(0.54, 0.065),
    ncol=4, fontsize=9, frameon=False,
)

fig.suptitle(
    "Human carotid plaque | Spatial domains, composition and GWAS association",
    fontsize=16, y=0.965,
)
fig.text(
    0.54, 0.925,
    "qW: BH within each sample; qA: BH across all "
    f"{len(summary)} domains. n denotes spots, not biological replicates.",
    ha="center", fontsize=10,
)
fig.text(
    0.54, 0.025,
    "Domain IDs are sample-specific. Composition is inferred, not a measured cell fraction.\n"
    "Region-level association does not assign the signal to an individual cell type.",
    ha="center", fontsize=9, color="#555555",
)

for extension in ("png", "pdf"):
    fig.savefig(
        OUT / f"GSE241346_domain_association_composition.{extension}",
        dpi=300,
    )
plt.close(fig)

# 收集已有的完整三联图；不执行其他脚本。
triptych_stem = "GSE241346_two_samples_triptych"
candidates = []
for folder in PARENT.glob("GSE241346_triptych_*"):
    png = folder / f"{triptych_stem}.png"
    pdf = folder / f"{triptych_stem}.pdf"
    if (
        png.is_file() and pdf.is_file()
        and png.stat().st_size > 0 and pdf.stat().st_size > 0
    ):
        candidates.append(folder)

if candidates:
    chosen = max(
        candidates,
        key=lambda p: (p / f"{triptych_stem}.png").stat().st_mtime_ns,
    )
    for extension in ("png", "pdf"):
        source = chosen / f"{triptych_stem}.{extension}"
        shutil.copy2(source, OUT / source.name)
        sources.append({
            "sample": "both",
            "kind": "existing_triptych_copy",
            "path": str(source),
        })
    print(f"\n已复制已有三联图：{chosen}")
else:
    print("\n未找到完整三联图 PNG/PDF；联合图和汇总表仍已正常生成。")

pd.DataFrame(sources).to_csv(
    OUT / "input_files.tsv", sep="\t", index=False
)
pd.DataFrame([
    {"celltype": cell, "color": COLORS[cell]} for cell in CELLTYPES
]).to_csv(OUT / "celltype_colors.tsv", sep="\t", index=False)

(OUT / "analysis_settings.json").write_text(
    json.dumps({
        "trait": TRAIT,
        "abundance_statistic": "posterior mean",
        "composition": "normalize each spot, then average within domain",
        "domain_labels": "original H5AD annotation",
        "p_values": "existing Cauchy results; not recomputed",
        "BH_families": [
            "all domains within each sample",
            f"all {len(summary)} domains across both samples",
        ],
        "zero_p_display_floor": 1e-300,
        "heatmap_and_stacked_bars": "same data, complementary displays",
        "histological_annotation": "not assigned",
    }, indent=2),
    encoding="utf-8",
)

print("\n===== Domain 汇总 =====")
print(summary[[
    "sample", "domain", "n_spots", "p_cauchy",
    "q_BH_within_sample", "q_BH_all_domains", "top3_composition",
]].to_string(index=False))

print(f"\n完成，输出目录：{OUT}")
print("联合图：GSE241346_domain_association_composition.png / .pdf")
print("汇总表：domain_summary.tsv")
print("输入记录：input_files.tsv")
print("未重跑模型，未修改已有数据、domain 或结果。")
