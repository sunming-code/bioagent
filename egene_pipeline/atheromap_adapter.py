"""Prepare a checksum-verified GDgpt → AtheroMap handoff, without model calls."""
from __future__ import annotations

import argparse
from copy import deepcopy
import os
from pathlib import Path

from . import __version__
from .atheromap_reference import load_reference
from .common import ROOT, digest, file_spec, files_in, now, object_digest, read_json, validate_contract, verify_manifest, write_json

DEFAULT_REFERENCE = ROOT / "4_atheromap/config/GSE159677_scdrs.reference.json"
LIMITATIONS = [
    "单细胞表达和 scDRS 分数来自外部 GSE159677 参考队列，不是当前患者的组织测量。",
    "z_score 只是交付性状标签；来源未确认时只提供参考队列背景，不建立患者疾病匹配。",
    "GDgpt 提供结构化基因与疾病上下文；scDRS 权重来自独立基因集，不从模型回答推导。",
    "scDRS 分数、细胞级统计和基因表达不修改 ACMG 分类，不建立诊断或个体患病概率。",
]


def validate_gdgpt_content(payload, report, sample_id):
    validate_contract(payload, "gdgpt_input.schema.json")
    if (report.get("sample_id") != sample_id or payload["sample_id"] != sample_id
            or report.get("assembly") != "GRCh38" or payload["assembly"] != "GRCh38"):
        raise ValueError("GDgpt 清单、报告与输入的患者 ID 或参考版本不一致")
    for field in ("selection", "case", "phenotypes", "ancestry", "frequency_policy", "upstream_summary"):
        if report.get(field) != payload[field]:
            raise ValueError(f"GDgpt 报告与原始输入的 {field} 不一致")
    tasks = {t["id"]: t for t in payload["tasks"]}
    results = {r["task_id"]: r for r in report["task_results"]}
    if len(tasks) != len(payload["tasks"]) or len(results) != len(report["task_results"]) or set(tasks) != set(results):
        raise ValueError("GDgpt 任务和实际结果未一一对应")
    expected_status = "analyzed" if tasks else "no_eligible_candidates"
    if report.get("analysis_status") != expected_status:
        raise ValueError("GDgpt 分析状态与任务数量不符")
    for task_id, task in tasks.items():
        result = results[task_id]
        if (result.get("status") != "complete" or result.get("sample_id") != sample_id
                or result.get("task_id") != task_id
                or result.get("gene") != task["gene"] or result.get("kind") != task["kind"]
                or result.get("candidate_id") != task["candidate_id"]
                or result.get("task_sha256") != object_digest(task) or result.get("input_sha256") != object_digest(payload)):
            raise ValueError("GDgpt 结果的患者、基因、任务或输入校验值不一致")
        if not task["evidence"] or any(e["gene"] != task["gene"] for e in task["evidence"]):
            raise ValueError("GDgpt 任务缺少一致的原始变异证据")


def upstream(path):
    manifest, files = verify_manifest(path, "gdgpt_analysis")
    report, payload = (read_json(files[name]) for name in ("report.json", "gdgpt_input.json"))
    validate_gdgpt_content(payload, report, manifest["sample_id"])
    if manifest.get("analysis_status") != report["analysis_status"] or set(manifest["tasks"]) != {t["id"] for t in payload["tasks"]}:
        raise ValueError("GDgpt 清单状态或任务集合与报告不同")
    for result in report["task_results"]:
        record = manifest["tasks"][result["task_id"]]
        if record.get("status") != "complete" or read_json(files[record["file"]["path"]]) != result:
            raise ValueError("GDgpt 报告与逐任务结果文件不一致")
    return manifest, files, report, payload


def applicability(task, trait):
    candidate = task["candidate"]
    disease_id = candidate.get("disease_id") if candidate else None
    matched = (trait["provenance_status"] == "verified" and disease_id is not None
               and disease_id in trait["mapped_disease_ids"])
    reason = ("exact_curated_disease_id_match" if matched else
              "trait_provenance_unverified" if trait["provenance_status"] != "verified" else
              "no_disease_hypothesis" if disease_id is None else "no_curated_disease_id_match")
    return {"status": "trait_matched" if matched else "reference_context_only", "reason": reason,
            "disease_id": disease_id, "trait_id": trait["id"], "match_method": "exact_curated_identifier" if matched else None}


def prepare(args):
    output = Path(args.outdir).resolve()
    reference_path = Path(args.reference).resolve(strict=True)
    ref, data_root, _ = load_reference(reference_path)
    if output.exists() or output.is_relative_to(data_root):
        raise ValueError("输出目录必须是原始参考数据之外的新目录")
    source_path = Path(args.gdgpt_manifest).resolve(strict=True)
    manifest, source_files, report, payload = upstream(source_path)
    source_spec, reference_spec = file_spec(source_path), file_spec(reference_path)
    entries, excluded = [], []
    for task in payload["tasks"]:
        scope = applicability(task, ref["trait"])
        entry = {"source_task_id": task["id"], "kind": task["kind"], "gene": task["gene"],
                 "candidate_id": task["candidate_id"], "candidate": deepcopy(task["candidate"]),
                 "variant_evidence": deepcopy(task["evidence"]), "applicability": scope,
                 "gdgpt_result": deepcopy(next(r for r in report["task_results"] if r["task_id"] == task["id"]))}
        if args.scope == "matched-trait" and scope["status"] != "trait_matched":
            excluded.append({"source_task_id": task["id"], "gene": task["gene"], **scope})
        else:
            entries.append(entry)
    if args.scope == "matched-trait" and not entries:
        raise ValueError("没有来源已确认且疾病标识精确匹配的任务；当前数据可使用 --scope reference-context")
    result = {"schema_version": "1.0", "sample_id": manifest["sample_id"], "assembly": "GRCh38", "generated_at": now(),
              "producer": {"name": "egene_pipeline.atheromap_adapter", "version": __version__},
              "source_gdgpt_manifest": source_spec, "source_reference_manifest": reference_spec,
              "reference": {k: deepcopy(ref[k]) for k in ("reference_dataset_id", "reference_scope", "species", "tissue", "expression_genome_build", "trait")},
              "analysis_scope": "matched_trait_reference_context" if args.scope == "matched-trait" else "reference_context_only",
              "sample": deepcopy(payload["sample"]), "case": deepcopy(payload["case"]), "phenotypes": deepcopy(payload["phenotypes"]),
              "ancestry": deepcopy(payload["ancestry"]), "frequency_policy": deepcopy(payload["frequency_policy"]),
              "upstream_summary": deepcopy(payload["upstream_summary"]), "gdgpt_analysis_status": report["analysis_status"],
              "selection": {"requested_scope": args.scope, "source_task_count": len(payload["tasks"]),
                            "selected_task_count": len(entries), "excluded_tasks": excluded}, "tasks": entries,
              "classification_labels_modified": False, "diagnosis_established": False, "risk_probability": None,
              "limitations": list(dict.fromkeys(payload["limitations"] + LIMITATIONS))}
    validate_contract(result, "atheromap_input.schema.json")
    output.mkdir(parents=True)
    try:
        snapshot = deepcopy(ref)
        snapshot["data_root"] = os.path.relpath(data_root, output)
        write_json(output / "reference_snapshot.json", snapshot)
        write_json(output / "gdgpt_input_snapshot.json", payload)
        write_json(output / "gdgpt_report_snapshot.json", report)
        write_json(output / "atheromap_input.json", result)
        # Validate source artifacts again before publishing a successful handoff.
        upstream(source_path)
        if digest(source_path) != source_spec["sha256"] or digest(reference_path) != reference_spec["sha256"]:
            raise ValueError("生成接口期间上游或参考清单发生变化")
        handoff = {"schema_version": "1.0", "stage": "prepare_atheromap_input", "status": "complete",
                   "sample_id": result["sample_id"], "assembly": "GRCh38", "producer": result["producer"],
                   "created_at": now(), "analysis_scope": result["analysis_scope"], "task_count": len(entries),
                   "files": files_in(output), "sources": {"gdgpt": source_spec, "reference": reference_spec}}
        write_json(output / "input_manifest.json", handoff)
        write_json(output / "status.json", {"stage": handoff["stage"], "status": "complete"})
        load_input(output / "input_manifest.json")
        print(f"AtheroMap 输入完成：{output / 'input_manifest.json'}；{len(entries)} 个基因任务，scope={result['analysis_scope']}", flush=True)
        return handoff
    except BaseException as error:
        write_json(output / "status.json", {"stage": "prepare_atheromap_input", "status": "failed", "error": str(error)})
        raise


def load_input(path):
    path = Path(path).resolve(strict=True)
    manifest, files = verify_manifest(path, "prepare_atheromap_input")
    value = read_json(files["atheromap_input.json"])
    validate_contract(value, "atheromap_input.schema.json")
    source = read_json(files["gdgpt_input_snapshot.json"])
    report = read_json(files["gdgpt_report_snapshot.json"])
    validate_gdgpt_content(source, report, manifest["sample_id"])
    ref, data_root, reference_files = load_reference(files["reference_snapshot.json"])
    if value["sample_id"] != manifest["sample_id"] or source["sample_id"] != value["sample_id"] or report["sample_id"] != value["sample_id"]:
        raise ValueError("AtheroMap 接口包含其他患者")
    if manifest["task_count"] != len(value["tasks"]) or len({t["source_task_id"] for t in value["tasks"]}) != len(value["tasks"]):
        raise ValueError("AtheroMap 任务数量或 ID 不一致")
    if manifest["sources"] != {"gdgpt": value["source_gdgpt_manifest"], "reference": value["source_reference_manifest"]}:
        raise ValueError("AtheroMap 来源清单记录不一致")
    scope = value["selection"]["requested_scope"]
    selected, excluded = [], []
    for task in source["tasks"]:
        match = applicability(task, ref["trait"])
        if scope == "matched-trait" and match["status"] != "trait_matched":
            excluded.append({"source_task_id": task["id"], "gene": task["gene"], **match})
        else:
            selected.append(task["id"])
    expected_selection = {"requested_scope": scope, "source_task_count": len(source["tasks"]),
                          "selected_task_count": len(selected), "excluded_tasks": excluded}
    expected_scope = "matched_trait_reference_context" if scope == "matched-trait" else "reference_context_only"
    if (value["selection"] != expected_selection or [t["source_task_id"] for t in value["tasks"]] != selected
            or value["analysis_scope"] != expected_scope or manifest["analysis_scope"] != expected_scope
            or value["gdgpt_analysis_status"] != report["analysis_status"] or (scope == "matched-trait" and not selected)):
        raise ValueError("AtheroMap 分析范围、任务选择或上游状态不一致")
    if any(value["reference"][key] != ref[key] for key in value["reference"]):
        raise ValueError("参考快照与接口不一致")
    for key in ("sample", "case", "phenotypes", "ancestry", "frequency_policy", "upstream_summary"):
        if value[key] != source[key]:
            raise ValueError(f"上游 {key} 被修改")
    original = {t["id"]: t for t in source["tasks"]}
    for item in value["tasks"]:
        task = original.get(item["source_task_id"])
        if task is None or any(item[k] != task[k] for k in ("gene", "kind", "candidate_id", "candidate")) or item["variant_evidence"] != task["evidence"]:
            raise ValueError("AtheroMap 任务改变了原始基因、疾病或变异证据")
        if item["applicability"] != applicability(task, ref["trait"]):
            raise ValueError("疾病与 GWAS 性状的匹配状态不一致")
        result = next(r for r in report["task_results"] if r["task_id"] == task["id"])
        if item["gdgpt_result"] != result:
            raise ValueError("GDgpt 机制结果与快照不同")
    return value, ref, data_root, reference_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gdgpt-manifest", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--scope", choices=("reference-context", "matched-trait"), default="reference-context")
    parser.add_argument("--outdir", type=Path, required=True)
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
