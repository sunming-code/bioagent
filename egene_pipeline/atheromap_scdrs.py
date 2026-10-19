"""Run existing scDRS data in an isolated workspace from an AtheroMap handoff."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import gc
from html import escape
import importlib.metadata
import os
from pathlib import Path
import runpy
import shutil
import signal
import sys
import time

from . import __version__
from .atheromap_adapter import load_input
from .atheromap_reference import MODULE, audit_reference, read_obs
from .common import ROOT, digest, file_spec, files_in, now, read_json, run_command, write_json


def normalize_h5ad_metadata(path):
    """Represent newer AnnData null metadata as omitted keys in 0.10 copies.

    AnnData 0.10 cannot read encoding-type=null. Its writer omits None values.
    Restrict conversion to uns metadata; retain the original None in the audit.
    """
    import h5py
    changes = []
    with h5py.File(path, "r+") as handle:
        nulls = []
        handle.visititems(lambda name, node: nulls.append(name) if node.attrs.get("encoding-type") == "null" else None)
        if any(not name.startswith("uns/") for name in nulls):
            raise ValueError(f"H5AD 在 uns 之外包含不支持的 null 数据，拒绝转换: {path}")
        for name in nulls:
            changes.append({"hdf5_path": name, "original_value": None,
                            "action": "omit_null_uns_key_for_anndata_0_10"})
            del handle[name]
    return changes


def stage_inputs(files, work, trait, mode):
    aliases = {
        "annotated_h5ad": "merged/GSE159677_harmony_highlevel_annotated_final.h5ad",
        "scdrs_h5ad": "merged/GSE159677_for_scdrs_rawcount.h5ad",
        "review": "merged/GSE159677_annotation_review_table.csv",
        "cluster_mapping": "merged/GSE159677_harmony_cluster_to_final_highlevel_mapping.csv",
        "covariates": "metadata/GSE159677_scdrs_covariates.tsv",
        "gene_set": "scdrs_input/trait_gene_sets.gs",
        "markers": "metadata/final_report_marker_manual.tsv",
        "marker_json": "metadata/GSE159677_paper10_highlevel_markers.json",
        "macrophage_dge": f"merged/GSE159677_macrophage_leiden_wilcoxon_dge_{trait}.csv",
        "vsmc_top_markers": f"merged/GSE159677_vsmc_intermediate_top_markers_{trait}.csv",
        **{f"{kind}_final": f"merged/GSE159677_{kind}_subtyped_final_{trait}.h5ad" for kind in ("macrophage", "vsmc")},
    }
    if mode == "reuse":
        aliases.update({"full_score": f"scdrs_out/{trait}.full_score.gz", "score": f"scdrs_out/{trait}.score.gz"})
        aliases.update({role: f"scdrs_out/{trait}.scdrs_group.{role[6:]}" for role in files if role.startswith("group_")})
    records = {}
    for role, name in aliases.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Independent copies prevent the original scripts from writing through a symlink.
        shutil.copyfile(files[role], target)
        changes = normalize_h5ad_metadata(target) if target.suffix == ".h5ad" else []
        records[role] = {"source": str(files[role]), "workspace_path": str(name), "metadata_compatibility": changes}
    for name in ("plots", "scdrs_out", "metadata", "merged"):
        (work / name).mkdir(exist_ok=True)
    return records


def python_script(relative, argv, log):
    previous = sys.argv
    sys.argv = [str(MODULE / relative)] + list(map(str, argv))
    try:
        with Path(log).open("w") as handle, redirect_stdout(handle), redirect_stderr(handle):
            runpy.run_path(str(MODULE / relative), run_name="__main__")
    finally:
        sys.argv = previous
        import matplotlib.pyplot as plt
        plt.close("all")
        gc.collect()


def score_table(work, trait, reference_files, mode):
    import numpy as np
    import pandas as pd
    short = pd.read_csv(work / f"scdrs_out/{trait}.score.gz", sep="\t", index_col=0)
    full_path = work / f"scdrs_out/{trait}.full_score.gz"
    header = pd.read_csv(full_path, sep="\t", nrows=0).columns
    full = pd.read_csv(full_path, sep="\t", usecols=[header[0], "norm_score"], index_col=0)
    obs = read_obs(work / "merged/GSE159677_for_scdrs_rawcount.h5ad")
    if (not short.index.is_unique or not full.index.is_unique or set(short.index) != set(obs.index)
            or set(full.index) != set(obs.index) or not np.isfinite(short["norm_score"]).all()
            or not np.allclose(short.loc[obs.index, "norm_score"], full.loc[obs.index, "norm_score"], atol=1e-6)):
        raise ValueError("scDRS 分数文件未完整对应参考细胞，或完整/简版分数不一致")
    short = short.loc[obs.index]
    if mode == "recompute":
        import scanpy as sc
        for kind in ("macrophage", "vsmc"):
            path = work / f"merged/GSE159677_{kind}_subtyped_final_{trait}.h5ad"
            data = sc.read_h5ad(path)
            data.obs[f"{trait}_norm_score"] = short.loc[data.obs_names, "norm_score"].to_numpy()
            data.write_h5ad(path, compression="gzip")
            del data
            gc.collect()
    obs["norm_score"] = short["norm_score"].to_numpy()
    p_column = "mc_pval" if "mc_pval" in short else "pval"
    obs["high_score"] = short[p_column].to_numpy() < 0.05
    obs["score_pval"] = short[p_column].to_numpy()
    return obs, p_column


def summaries(obs, work, delivery, trait):
    import pandas as pd
    overall = obs.groupby(["final_high_level_celltype_10", "condition"], observed=True).agg(
        n_cells=("norm_score", "size"), mean_score=("norm_score", "mean"), median_score=("norm_score", "median"),
        fraction_high_score=("high_score", "mean")).reset_index()
    overall.to_csv(delivery / "celltype_condition_summary.tsv", sep="\t", index=False)
    obs.groupby(["patient", "condition", "final_high_level_celltype_10"], observed=True).agg(
        n_cells=("norm_score", "size"), mean_score=("norm_score", "mean")).reset_index().rename(
        columns={"patient": "reference_donor"}).to_csv(delivery / "reference_donor_summary.tsv", sep="\t", index=False)
    counts = {}
    for kind in ("macrophage", "vsmc"):
        data = read_obs(work / f"merged/GSE159677_{kind}_subtyped_final_{trait}.h5ad")
        data[f"{trait}_norm_score"] = obs.loc[data.index, "norm_score"].to_numpy()
        table = data[[f"{kind}_subtype_final", "condition", f"{trait}_norm_score"]].copy()
        table.columns = ["subtype", "condition", "score"]
        folder = work / f"merged/{kind}_subtype_analysis"
        folder.mkdir(exist_ok=True)
        table.to_csv(folder / f"GSE159677_{kind}_celllevel_scores.csv", index=False)
        # Keep an ID-bearing export alongside the exact legacy R input format.
        table.rename_axis("reference_cell_id").to_csv(delivery / f"{kind}_celllevel_scores.tsv", sep="\t")
        table.groupby(["subtype", "condition"], observed=True).agg(n_cells=("score", "size"),
            mean_score=("score", "mean"), median_score=("score", "median")).reset_index().to_csv(
                delivery / f"{kind}_condition_summary.tsv", sep="\t", index=False)
        counts[kind] = {"cells": len(data), "subtype_counts": table["subtype"].astype(str).value_counts().to_dict()}
    return counts


def gene_context(payload, files, delivery):
    import h5py
    import numpy as np
    import pandas as pd
    from anndata._io.specs import read_elem
    from anndata.experimental import sparse_dataset
    genes = sorted({t["gene"] for t in payload["tasks"]})
    fields = ["gene", "mapping_status", "feature_id", "compartment", "reference_group", "n_cells", "mean_acosh", "fraction_expressing"]
    rows, mapping = [], {}
    with h5py.File(files["annotated_h5ad"], "r") as handle:
        var, obs = (read_elem(handle[k]) for k in ("var", "obs"))
        symbols = var["gene_name"].astype(str).str.upper()
        matrix = handle["layers/acosh"]
        matrix = sparse_dataset(matrix) if isinstance(matrix, h5py.Group) else matrix
        strata = {"overall": obs["final_high_level_celltype_10"].astype(str)}
        for kind in ("macrophage", "vsmc"):
            sub = read_obs(files[f"{kind}_final"])
            strata[kind] = sub[f"{kind}_subtype_final"].astype(str)
        for gene in genes:
            hits = np.flatnonzero(symbols.to_numpy() == gene.upper())
            status = "matched_unique_symbol" if len(hits) == 1 else "not_found" if len(hits) == 0 else "ambiguous_multiple_features"
            mapping[gene] = {"status": status, "feature_ids": var.index[hits].astype(str).tolist()}
            if len(hits) != 1:
                rows.append({"gene": gene, "mapping_status": status})
                continue
            column = matrix[:, int(hits[0])]
            values = np.asarray(column.toarray() if hasattr(column, "toarray") else column).ravel()
            if not np.isfinite(values).all():
                raise ValueError(f"目标基因表达包含非有限值: {gene}")
            expression = pd.Series(values, index=obs.index)
            for compartment, labels in strata.items():
                for group, ids in labels.groupby(labels, observed=True).groups.items():
                    v = expression.loc[ids].to_numpy()
                    rows.append({"gene": gene, "mapping_status": status, "feature_id": str(var.index[hits[0]]),
                                 "compartment": compartment, "reference_group": group, "n_cells": len(v),
                                 "mean_acosh": float(v.mean()), "fraction_expressing": float((v > 0).mean())})
    pd.DataFrame(rows, columns=fields).to_csv(delivery / "target_gene_expression.tsv", sep="\t", index=False)
    context = [{"source_task_id": task["source_task_id"], "gene": task["gene"], "kind": task["kind"],
                "candidate": task["candidate"], "applicability": task["applicability"],
                "variant_evidence": task["variant_evidence"], "expression_mapping": mapping[task["gene"]]} for task in payload["tasks"]]
    write_json(delivery / "target_gene_context.json", context)
    return mapping


def run(args):
    output = Path(args.outdir).resolve()
    input_path = Path(args.input_manifest).resolve(strict=True)
    payload, ref, data_root, files = load_input(input_path)
    if output.exists() or output.is_relative_to(data_root):
        raise ValueError("输出目录必须是原始参考数据之外的新目录")
    if args.plots != "none" and ref["trait"]["score_label"] != "z_score":
        raise ValueError("现有 VSMC dotplot 和 R 绘图脚本仅接受 z_score；其他 trait 需先适配这些脚本")
    output.mkdir(parents=True)
    work, delivery = output / "work", output / "delivery"
    work.mkdir(); delivery.mkdir(); (output / "logs").mkdir()
    manifest = {"schema_version": "1.0", "stage": "atheromap_scdrs", "status": "running", "started_at": now(),
                "sample_id": payload["sample_id"], "assembly": "GRCh38", "producer": {"name": "egene_pipeline.atheromap_scdrs", "version": __version__},
                "input_manifest": file_spec(input_path), "reference_dataset_id": ref["reference_dataset_id"],
                "analysis_scope": payload["analysis_scope"], "mode": args.mode, "plots": args.plots, "steps": [], "files": {}}
    previous_work = os.environ.get("ATHEROMAP_SCDRS_WORK_DIR")
    os.environ["ATHEROMAP_SCDRS_WORK_DIR"] = str(work)

    def save(status="running", active=None, error=None):
        manifest["status"] = status
        write_json(output / "atheromap_manifest.json", manifest)
        write_json(output / "status.json", {"stage": manifest["stage"], "status": status, "active_step": active,
                                           "sample_id": payload["sample_id"], "error": error, "updated_at": now()})

    def step(name, action):
        record = {"name": name, "status": "running", "started_at": now(), "log": f"logs/{name}.log"}
        manifest["steps"].append(record); save(active=name)
        print(f"[{name}] 开始", flush=True)
        start = time.monotonic()
        action(output / record["log"])
        record.update(status="complete", elapsed_seconds=round(time.monotonic() - start, 3), finished_at=now())
        save(); print(f"[{name}] 完成 ({record['elapsed_seconds']}s)", flush=True)

    try:
        save()
        audit = audit_reference(files, ref["trait"]["score_label"])
        if audit != ref["annotation_validation"]:
            raise ValueError("参考队列内容与注册时的注释验收记录不一致")
        write_json(output / "annotation_validation.json", audit)
        trait = ref["trait"]["score_label"]
        manifest["input_aliases"] = stage_inputs(files, work, trait, args.mode)
        write_json(output / "input_compatibility.json", manifest["input_aliases"])
        if args.mode == "recompute":
            step("compute_score", lambda log: run_command(["bash", MODULE / "scdrs/scripts/overall_analysis/run_GSE159677_scdrs_cli.sh", trait], ROOT, log, timeout=args.timeout))
        obs, p_column = score_table(work, trait, files, args.mode)
        step("merge", lambda log: python_script("scdrs/scripts/overall_analysis/run_GSE159677_merge_scdrs_and_downstream.py", ["--trait", trait], log))
        counts = summaries(obs, work, delivery, trait)
        mappings = gene_context(payload, files, delivery)
        if args.plots != "none":
            scripts = [
                "overall_analysis/plot_GSE159677_annotation_panel.py",
                "overall_analysis/plot_GSE159677_celltype_violin_with_stats.py",
                "overall_analysis/plot_GSE159677_celltype_condition_violin.py",
                "overall_analysis/plot_GSE159677_condition_scdrs_umap.py",
                *[f"{kind}_subtype_analysis/plot_GSE159677_{kind}_{name}.py" for kind in ("macrophage", "vsmc")
                  for name in ("final_panels", "subtype_condition_violin", "subtype_dotplot")],
            ]
            for relative in scripts:
                options = [] if "annotation_panel" in relative or "vsmc_subtype_dotplot" in relative else ["--trait", trait]
                step(Path(relative).stem, lambda log, p=relative, argv=options: python_script("scdrs/scripts/" + p, argv, log))
            for kind in ("macrophage", "vsmc"):
                for filename in (f"GSE159677_{kind}_final_stats_{trait}.csv", f"GSE159677_{kind}_subtype_condition_stats_{trait}.csv"):
                    shutil.copyfile(work / "merged" / filename, work / f"merged/{kind}_subtype_analysis" / filename)
                if args.plots == "all":
                    (work / f"plots/{kind}_subtype_analysis").mkdir(exist_ok=True)
                    rscript = os.environ.get("ATHEROMAP_RSCRIPT", "Rscript")
                    script = MODULE / f"scdrs/scripts/{kind}_subtype_analysis/plot_GSE159677_{kind}_violin_ggplot2.R"
                    step(f"{kind}_R_violin", lambda log, p=script: run_command([rscript, "--vanilla", p], ROOT, log, timeout=args.timeout))
        for name in ("plots", "statistics"):
            (delivery / name).mkdir()
        for image in (work / "plots").rglob("*"):
            if image.is_file():
                target = delivery / "plots" / image.relative_to(work / "plots")
                target.parent.mkdir(exist_ok=True, parents=True); shutil.copyfile(image, target)
        for table in (work / "merged").glob("*"):
            if table.suffix in (".csv", ".tsv"):
                shutil.copyfile(table, delivery / "statistics" / table.name)
        for group_file in (work / "scdrs_out").glob("*.scdrs_group.*"):
            shutil.copyfile(group_file, delivery / "statistics" / group_file.name)
        report = {"schema_version": "1.0", "sample_id": payload["sample_id"], "assembly": "GRCh38", "generated_at": now(),
                  "reference_dataset_id": ref["reference_dataset_id"], "reference_scope": "external_cohort", "trait": ref["trait"],
                  "analysis_scope": payload["analysis_scope"], "mode": args.mode, "score_source": "existing_reference_scores" if args.mode == "reuse" else "recomputed_reference_scores",
                  "reference_cells": len(obs), "reference_celltype_counts": obs["final_high_level_celltype_10"].astype(str).value_counts().to_dict(),
                  "subtypes": counts, "target_gene_mapping": mappings, "selection": payload["selection"],
                  "high_score_rule": f"{p_column}<0.05", "classification_labels_modified": False, "diagnosis_established": False,
                  "risk_probability": None, "limitations": payload["limitations"],
                  "files": {"expression": "target_gene_expression.tsv", "target_context": "target_gene_context.json", "celltype_summary": "celltype_condition_summary.tsv"}}
        write_json(delivery / "report.json", report)
        write_json(delivery / "atheromap_input.json", payload)
        links = [f'<li><a href="{escape(str(p.relative_to(delivery)), quote=True)}">{escape(str(p.relative_to(delivery)))}</a></li>'
                 for p in sorted(delivery.rglob("*")) if p.is_file() and p.suffix in (".png", ".pdf", ".tsv", ".csv", ".json")]
        (delivery / "report.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AtheroMap scDRS</title>'
            '<style>body{max-width:1100px;margin:32px auto;font:16px/1.8 system-ui}pre{white-space:pre-wrap}</style>'
            f'<h1>AtheroMap scDRS：{escape(payload["sample_id"])}</h1><p>外部参考队列：GSE159677；性状标签：{escape(trait)}；范围：{escape(payload["analysis_scope"])}</p>'
            f'<p>已处理参考队列 {len(obs):,} 个细胞；巨噬细胞 {counts["macrophage"]["cells"]:,} 个；VSMC {counts["vsmc"]["cells"]:,} 个。</p>'
            '<p>参考表达与细胞关联结果不代表患者的组织测量，不改变原始变异分类。</p>'
            '<ul>' + ''.join(links) + '</ul><pre>' + escape('\n'.join(payload["limitations"])) + '</pre></html>', encoding="utf-8")
        # Re-read both the handoff and original reference hashes after the scripts finish.
        load_input(input_path)
        if digest(input_path) != manifest["input_manifest"]["sha256"]:
            raise ValueError("运行期间输入清单发生变化")
        manifest["runtime"] = {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scanpy", "anndata", "scdrs", "jsonschema")}
        manifest["code_sha256"] = {str(p.relative_to(ROOT)): digest(p) for p in sorted((MODULE / "scdrs/scripts").rglob("*")) if p.suffix in (".py", ".R", ".sh")}
        manifest["files"] = files_in(output, ("atheromap_manifest.json", "status.json"))
        manifest["finished_at"] = now()
        save("complete")
        print(f"scDRS 接入完成：{delivery / 'report.html'}", flush=True)
        return manifest
    except BaseException as error:
        manifest.update(error=str(error), failed_at=now())
        save("failed", error=str(error))
        raise
    finally:
        if previous_work is None:
            os.environ.pop("ATHEROMAP_SCDRS_WORK_DIR", None)
        else:
            os.environ["ATHEROMAP_SCDRS_WORK_DIR"] = previous_work


def main():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--mode", choices=("reuse", "recompute"), default="reuse")
    parser.add_argument("--plots", choices=("all", "python", "none"), default="all")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("timeout 必须为正数")
    run(args)


if __name__ == "__main__":
    main()
