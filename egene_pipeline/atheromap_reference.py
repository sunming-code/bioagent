"""Register and verify the existing, externally collected scDRS reference cohort."""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import re

from . import __version__
from .common import ROOT, file_spec, now, read_json, validate_contract, verify_files, write_json

MODULE = ROOT / "4_atheromap"
ROLES = {
    "auto_h5ad": "merged/overall_analysis/09_harmony_highlevel_auto_annotated.h5ad",
    "review": "merged/overall_analysis/10_annotation_review_table.csv",
    "cluster_mapping": "merged/overall_analysis/11_harmony_cluster_to_final_highlevel_mapping.csv",
    "annotated_h5ad": "merged/overall_analysis/12_harmony_highlevel_annotated_final.h5ad",
    "scdrs_h5ad": "merged/overall_analysis/14_for_scdrs_rawcount.h5ad",
    "covariates": "metadata/GSE159677_scdrs_covariates.tsv",
    "gene_set": "scdrs_input/trait_gene_sets.gs",
    "markers": "metadata/final_report_marker_manual.tsv",
    "marker_json": "metadata/GSE159677_paper10_highlevel_markers.json",
    "full_score": "scdrs_out/z_score.full_score.gz",
    "score": "scdrs_out/z_score.score.gz",
    **{f"group_{g}": f"scdrs_out/z_score.scdrs_group.{g}" for g in
       ("final_high_level_celltype_10", "patient", "condition", "harmony_leiden")},
    **{f"{kind}_{role}": f"merged/{kind}_subtype_analysis/{name}" for kind, entries in {
        "macrophage": {"base": "01_macrophage_subtyped.h5ad", "final": "11_macrophage_subtyped_final.h5ad",
                       "mapping": "08_macrophage_cluster_manual_relabel.csv", "celllevel": "14_macrophage_celllevel_scores.csv",
                       "dge": "03_macrophage_leiden_wilcoxon_dge.csv"},
        "vsmc": {"base": "01_vsmc_subtyped.h5ad", "final": "09_vsmc_subtyped_final.h5ad",
                 "mapping": "06_vsmc_cluster_manual_relabel.csv", "celllevel": "12_vsmc_celllevel_scores.csv",
                 "top_markers": "05_vsmc_intermediate_top_markers.csv"},
    }.items() for role, name in entries.items()},
}


def load_reference(path, *, verify=True):
    path = Path(path).resolve(strict=True)
    ref = read_json(path)
    validate_contract(ref, "atheromap_reference.schema.json")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", ref["trait"]["score_label"]):
        raise ValueError("scDRS trait 标签只能包含字母、数字、下划线、点或短横线")
    missing = set(ROLES) - ref["files"].keys()
    if missing:
        raise ValueError(f"参考清单缺少文件角色: {sorted(missing)}")
    if ref["trait"]["provenance_status"] == "verified":
        if not all(ref["trait"].get(k) for k in ("gwas_study_id", "disease_name", "source_records")):
            raise ValueError("已确认性状必须提供疾病名称、GWAS 标识和来源记录")
    data_root = (path.parent / ref["data_root"]).resolve(strict=True)
    files = verify_files(data_root, ref["files"]) if verify else {
        role: data_root / spec["path"] for role, spec in ref["files"].items()}
    return ref, data_root, files


def read_obs(path):
    import h5py
    from anndata._io.specs import read_elem
    with h5py.File(path, "r") as handle:
        obs = read_elem(handle["obs"])
    if not obs.index.is_unique:
        raise ValueError(f"H5AD barcode 重复: {path}")
    return obs


def script_constant(relative, name):
    for node in ast.parse((MODULE / relative).read_bytes()).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                return ast.literal_eval(node.value)
    raise ValueError(f"没有找到 {name}: {relative}")


def audit_reference(files, trait="z_score"):
    """Validate annotation decisions against cells, not numbered filenames."""
    import h5py
    import numpy as np
    import pandas as pd
    from anndata._io.specs import read_elem

    def need(ok, message):
        if not ok:
            raise ValueError(message)

    auto, final, raw = (read_obs(files[k]) for k in ("auto_h5ad", "annotated_h5ad", "scdrs_h5ad"))
    label, cluster = "final_high_level_celltype_10", "harmony_leiden"
    review = pd.read_csv(files["review"], dtype={cluster: str})
    mapping = pd.read_csv(files["cluster_mapping"], dtype={cluster: str})
    need({cluster, label, "suggested_label", "n_cells"}.issubset(review), "人工复核表缺少必需列")
    need(not review[cluster].duplicated().any() and review[label].notna().all() and review[label].str.strip().ne("").all(), "人工复核表包含重复 cluster 或空标签")
    allowed = script_constant("scdrs/scripts/overall_analysis/run_GSE159677_finalize_annotation.py", "CELLTYPE_ORDER")
    need(set(review[label]).issubset(allowed), "人工复核表含有不支持的最终标签")
    need(review.equals(mapping), "复核表与最终 cluster 映射不一致")
    need(set(review[cluster]) == set(auto[cluster].astype(str)), "复核表未完整覆盖参考 cluster")
    need(auto.index.equals(final.index) and final.index.equals(raw.index), "总体注释、自动注释与 scDRS 输入的细胞不一致")
    expected = auto[cluster].astype(str).map(review.set_index(cluster)[label])
    need(np.array_equal(expected.to_numpy(), final[label].astype(str).to_numpy()), "复核表没有正确应用到最终 H5AD")
    need(final[label].astype(str).equals(raw[label].astype(str)), "scDRS 输入未保留最终注释")
    need(np.array_equal(review.set_index(cluster)["n_cells"].sort_index(), auto[cluster].astype(str).value_counts().sort_index()), "复核表的细胞数量与 H5AD 不符")
    for role in ("annotated_h5ad", "scdrs_h5ad"):
        with h5py.File(files[role], "r") as f:
            need("raw_counts" in f["layers"] and {"X_harmony", "X_umap"}.issubset(f["obsm"]), "缺少 raw counts、Harmony 或 UMAP")
            var = read_elem(f["var"])
            need(var.index.is_unique and "gene_name" in var, "基因名称不唯一或缺少 gene_name")
    scores = pd.read_csv(files["score"], sep="\t", index_col=0)
    cov = pd.read_csv(files["covariates"], sep="\t", index_col=0)
    need(scores.index.is_unique and set(scores.index) == set(raw.index), "scDRS 分数未完整对应参考细胞")
    need(cov.index.equals(raw.index) and np.isfinite(cov.to_numpy(dtype=float)).all(), "协变量缺失、无效或细胞顺序不一致")
    need(np.allclose(cov["log_n_counts"], np.log1p(raw["n_counts"].astype(float))) and np.allclose(cov["mt_frac"], raw["mt_frac"].astype(float)), "协变量与 H5AD 内容不符")
    need(np.isfinite(scores["norm_score"]).all(), "scDRS norm_score 包含无效值")
    sets = pd.read_csv(files["gene_set"], sep="\t")
    need(list(sets.columns) == ["TRAIT", "GENESET"] and sets["TRAIT"].is_unique, "基因集格式无效")
    selected = sets.loc[sets["TRAIT"] == trait, "GENESET"]
    need(len(selected) == 1, "指定 trait 不在基因集中")
    genes = str(selected.iloc[0]).split(",")
    need(len(set(g.split(":")[0] for g in genes)) == len(genes), "基因集中存在重复基因")
    for gene in genes:
        symbol, sep, weight = gene.partition(":")
        need(bool(symbol) and (not sep or (np.isfinite(float(weight)) and float(weight) > 0)), "基因集包含无效权重")
    full_header = pd.read_csv(files["full_score"], sep="\t", nrows=0).columns
    need({"norm_score", "raw_score", "pval"}.issubset(full_header), "完整分数文件缺少必需列")
    summary = {"status": "passed", "cells": len(raw), "clusters": len(review),
               "celltype_counts": final[label].astype(str).value_counts().to_dict(),
               "gene_set_size": len(genes), "control_columns": sum(c.startswith("ctrl_norm_score_") for c in full_header),
               "condition_labels": sorted(raw["condition"].astype(str).unique()), "subtypes": {}}
    for kind, parent in (("macrophage", "Macrophage"), ("vsmc", "VSMC")):
        base, target = (read_obs(files[f"{kind}_{r}"]) for r in ("base", "final"))
        c, old, new = f"{kind}_leiden", f"{kind}_subtype", f"{kind}_subtype_final"
        table = pd.read_csv(files[f"{kind}_mapping"], dtype=str)
        need(not table[c].duplicated().any() and set(table[c]) == set(base[c].astype(str)), f"{kind} 映射未完整覆盖 cluster")
        need(set(base.index) == set(final.index[final[label].astype(str) == parent]), f"{kind} 与总体注释的细胞集合不同")
        expected = base[c].astype(str).map(table.set_index(c)[new])
        rules = script_constant(f"scdrs/scripts/{kind}_subtype_analysis/finalize_GSE159677_{kind}_labels.py", "MANUAL_CLUSTER_MAP")
        scripted = base[old].astype(str).copy()
        for key, value in rules.items():
            scripted.loc[base[c].astype(str) == key] = value
        need(np.array_equal(expected.to_numpy(), scripted.to_numpy()), f"{kind} 人工映射与当前代码不一致")
        keep = ~expected.str.startswith("REMOVE_")
        need(base.index[keep].equals(target.index), f"{kind} 最终删除名单不一致")
        need(np.array_equal(expected.loc[target.index].to_numpy(), target[new].astype(str).to_numpy()), f"{kind} 最终标签未落实")
        need(not target[new].astype(str).isin(["", "nan", "Intermediate"]).any(), f"{kind} 有未完成注释")
        need(np.allclose(target[f"{trait}_norm_score"], scores.loc[target.index, "norm_score"], atol=1e-6), f"{kind} 分数与全局分数不一致")
        celllevel = pd.read_csv(files[f"{kind}_celllevel"])
        need(len(celllevel) == len(target) and np.array_equal(celllevel["subtype"].astype(str), target[new].astype(str))
             and np.array_equal(celllevel["condition"].astype(str), target["condition"].astype(str))
             and np.allclose(celllevel["score"], target[f"{trait}_norm_score"], atol=1e-6), f"{kind} 细胞级 CSV 与最终 H5AD 不一致")
        summary["subtypes"][kind] = {"before": len(base), "removed": int((~keep).sum()), "after": len(target),
                                     "counts": target[new].astype(str).value_counts().to_dict(), "manual_rules": rules}
    return summary


def register(data_root, output):
    data_root, output = Path(data_root).resolve(strict=True), Path(output).resolve()
    if output.exists() or output.is_relative_to(data_root):
        raise ValueError("参考清单必须写入新的、位于原始数据目录之外的文件")
    files = {role: data_root / rel for role, rel in ROLES.items()}
    audit = audit_reference(files)
    records = {role: file_spec(path, data_root) for role, path in files.items()}
    value = {"schema_version": "1.0", "stage": "scdrs_reference", "created_at": now(),
             "producer": {"name": "egene_pipeline.atheromap_reference", "version": __version__},
             "reference_dataset_id": "GSE159677", "reference_scope": "external_cohort", "species": "human",
             "tissue": "carotid plaque", "expression_genome_build": None,
             "data_root": os.path.relpath(data_root, output.parent), "files": records, "annotation_validation": audit,
             "trait": {"id": "local:z_score", "score_label": "z_score", "provenance_status": "unverified",
                       "disease_name": None, "gwas_study_id": None, "gwas_genome_build": None,
                       "mapped_disease_ids": [], "source_records": [],
                       "note": "z_score 是交付文件中的标签；真实疾病、GWAS 来源和权重生成方法尚未确认。"}}
    validate_contract(value, "atheromap_reference.schema.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, value)
    load_reference(output)
    print(f"参考队列注册完成：{output}；{audit['cells']} 个细胞，{len(records)} 个输入文件", flush=True)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    register(args.data_root, args.out)


if __name__ == "__main__":
    main()
