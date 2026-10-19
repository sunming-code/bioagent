"""Validate a portable e-Gene delivery and build evidence-preserving GDgpt tasks."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from pathlib import Path
import re
import shutil

from . import __version__
from .common import ROOT, digest, file_spec, files_in, now, object_digest, read_json, validate_contract, verify_manifest, write_json

LABELS = {"Pathogenic", "Likely pathogenic", "Uncertain significance", "Likely benign", "Benign", "not_evaluated"}
LIMITATIONS = [
    "上游疾病候选是待复核假设，不是确诊；空候选不能排除遗传病。",
    "GDgpt 的知识图谱支持基因层面的机制关系，不能证明具体变异致病、药物敏感或个体患病概率。",
    "原始 ACMG 分类、筛选路由和频率使用权限保持不变；VUS 不升级为致病。",
    "e-Gene 的孟德尔疾病候选不等于肿瘤驱动变异或肿瘤用药证据。",
]


def rows(path):
    csv.field_size_limit(64 * 1024 * 1024)
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"TSV 列数不一致: {path}")
            yield row


def parse_field(row, name, default):
    import json
    value = row.get(name, "")
    return json.loads(value) if value else default


def build(report_path, genes=(), max_candidates=None):
    manifest, files = verify_manifest(report_path, "generate_report")
    import jsonschema
    jsonschema.Draft7Validator(read_json(ROOT / "2_egene/contracts/report_manifest.schema.json")).validate(manifest)
    report = read_json(files["report.json"])
    jsonschema.Draft7Validator(read_json(ROOT / "2_egene/contracts/report.schema.json")).validate(report)
    sample_id = manifest["sample_id"]
    if report["sample"]["sample_id"] != sample_id or report["assembly"] != "GRCh38":
        raise ValueError("e-Gene 报告与清单的样本/参考版本不一致")
    case, phenotypes = (read_json(files[name]) for name in ("case.json", "phenotypes.normalized.json"))
    if case.get("sample_id") != sample_id or phenotypes.get("sample_id") != sample_id:
        raise ValueError("病例、表型与报告的样本不一致")
    if report.get("case") != case or report.get("phenotypes") != phenotypes:
        raise ValueError("病例/表型快照与结构化报告不一致")
    candidates = report["disease_candidates"]
    if len(candidates) != manifest["counts"]["disease_candidates"]:
        raise ValueError("候选数量与报告清单不一致")
    if max_candidates is not None and max_candidates < 1:
        raise ValueError("max-candidates 必须为正整数")
    requested = list(dict.fromkeys(g.upper() for g in genes))
    if any(not re.fullmatch(r"[A-Z0-9_.-]+", g) for g in requested):
        raise ValueError("--gene 必须为基因符号")
    selected = candidates if max_candidates is None else candidates[:max_candidates]
    candidate_pairs = {(vid, c["gene"]) for c in selected for vid in c["all_variant_ids"]}
    # Stream the complete association table; nearby genes never become variant targets.
    selected_links, gene_aliases = {}, {}
    for row in rows(files["variant_disease_links.tsv"]):
        gene = row["resolved_gene"]
        matches = [g for g in requested if g in {gene.upper(), row["original_gene"].upper()}]
        if not matches and (row["normalized_id"], gene) not in candidate_pairs:
            continue
        if row["gene_relation"] != "overlapping_gene_feature" or not gene:
            continue
        for alias in matches:
            gene_aliases.setdefault(alias, set()).add(gene)
        key = (row["normalized_id"], row["original_gene"], int(row["gene_occurrence"]))
        if key in selected_links:
            raise ValueError("重复的变异—基因上下文")
        selected_links[key] = {"gene": gene, "classification": row["classification"],
            "gene_relation": row["gene_relation"], "gene_mapping_status": row["gene_mapping_status"],
            "eligible_for_candidates": row["eligible_for_candidates"] == "true",
            "exclusion_reasons": parse_field(row, "exclusion_reasons", [])}
    for gene in requested:
        if len(gene_aliases.get(gene, ())) != 1:
            raise ValueError(f"指定基因 {gene} 没有唯一的、与患者变异重叠的已解析基因上下文")
    evidence = {}
    total_contexts = 0
    classifications = Counter()
    for row in rows(files["acmg_results.tsv"]):
        total_contexts += 1
        if row["sample_id"] != sample_id or row["acmg_classification"] not in LABELS:
            raise ValueError("ACMG 表的样本或分类不一致")
        classifications[row["acmg_classification"]] += 1
        key = (row["normalized_id"], row["intervar_gene"], int(row["gene_occurrence"]))
        if key not in selected_links:
            continue
        link = selected_links[key]
        if row["acmg_classification"] != link["classification"] or key in evidence:
            raise ValueError("ACMG 与基因关联表的分类或上下文不一致")
        evidence[key] = {**link, "normalized_id": row["normalized_id"], "original_gene": row["intervar_gene"],
            "gene_occurrence": int(row["gene_occurrence"]), "classification": row["acmg_classification"],
            "raw_classification": row["raw_classification"], "source_GT": row["source_GT"],
            "triage_route": row["triage_route"], "integrated_evidence": parse_field(row, "integrated_evidence", {}),
            "data_flags": parse_field(row, "data_flags", []), "evidence_changes": parse_field(row, "evidence_changes", {})}
    if set(evidence) != set(selected_links):
        raise ValueError("基因关联记录无法连接到原始 ACMG 证据")
    if (total_contexts != report["variant_statistics"]["counts"]["acmg_gene_contexts"]
            or dict(classifications) != report["variant_statistics"]["gene_context_classifications"]):
        raise ValueError("全量 ACMG 表与报告统计不一致")
    wanted_ids = {key[0] for key in evidence}
    variants, total_variants = {}, 0
    for row in rows(files["variants.tsv"]):
        total_variants += 1
        if row["sample_id"] != sample_id:
            raise ValueError("变异表含有其他样本")
        if row["normalized_id"] in wanted_ids:
            if row["normalized_id"] in variants:
                raise ValueError("变异表存在重复标准化 ID")
            variants[row["normalized_id"]] = row
    if total_variants != report["variant_statistics"]["counts"]["retained_variants"] or set(variants) != wanted_ids:
        raise ValueError("完整变异表的数量或证据连接不一致")
    for item in evidence.values():
        row = variants[item["normalized_id"]]
        item["annotation"] = {key: row[key] for key in ("Func.refGene", "ExonicFunc.refGene", "AAChange.refGene", "CLNSIG", "CLNREVSTAT", "CLNDN")}
        item["frequency"] = {key: row[key] for key in ("matched_pop", "matched_pop_AF", "global_AF", "af_status", "use_for_acmg_ba1_bs1")}
        item["quality"] = {key: row[key] for key in ("original_DP", "original_GQ", "original_QUAL", "original_FILTER", "quality_missing")}
        contexts = parse_field(row, "acmg_gene_contexts", [])
        if not any(c["gene"] == item["original_gene"] and c["occurrence"] == item["gene_occurrence"]
                   and c["classification"] == item["classification"] for c in contexts):
            raise ValueError("变异导出与逐基因 ACMG 分类不一致")
    with (ROOT / "3_GDgpt/kg_build/task_kg_output/task_kg_nodes.csv").open(newline="") as handle:
        graph_nodes = list(csv.DictReader(handle))
    graph_genes = {n["name"] for n in graph_nodes if n["type"] == "Gene"}
    graph_diseases = {n["name"].casefold() for n in graph_nodes if n["type"] == "Disease"}
    tasks = []

    def task(kind, gene, candidate=None):
        items = [e for e in evidence.values() if e["gene"] == gene
                 and (candidate is None or e["normalized_id"] in candidate["all_variant_ids"])]
        items.sort(key=lambda e: (e["normalized_id"], e["original_gene"], e["gene_occurrence"]))
        if not items:
            raise ValueError(f"任务没有可追溯的变异证据: {gene}")
        if candidate is not None:
            observed = {e["normalized_id"] for e in items}
            if observed != set(candidate["all_variant_ids"]) or not all(e["eligible_for_candidates"] for e in items):
                raise ValueError("候选所需等位基因缺失或不具备上游候选资格")
            for e in items:
                if candidate["acmg_classifications"].get(e["normalized_id"]) != e["classification"]:
                    raise ValueError("候选与原始变异分类不一致")
        identity = {"kind": kind, "gene": gene, "candidate_id": candidate["candidate_id"] if candidate else None}
        return {"id": "task-" + object_digest(identity)[:16], **identity, "candidate": candidate,
            "evidence": items, "knowledge_scope": "gene_level_only",
            "kg_snapshot_presence": {"gene": gene in graph_genes,
                "disease_name_exact": bool(candidate and candidate["disease_name"].casefold() in graph_diseases)}}

    for candidate in selected:
        tasks.append(task("disease_candidate", candidate["gene"], candidate))
    for gene in dict.fromkeys(next(iter(gene_aliases[g])) for g in requested):
        tasks.append(task("explicit_gene_exploration", gene))
    if len({t["id"] for t in tasks}) != len(tasks):
        raise ValueError("重复的候选或指定基因任务")
    result = {"schema_version": "1.0", "sample_id": sample_id, "assembly": "GRCh38", "generated_at": now(),
        "producer": {"name": "egene_pipeline.adapter", "version": __version__},
        "source_report_manifest": file_spec(report_path), "source_report": file_spec(files["report.json"]),
        "sample": report["sample"], "case": case, "phenotypes": phenotypes,
        "upstream_summary": {"conclusion": report["conclusion"], "variant_counts": report["variant_statistics"]["counts"],
            "gene_context_classifications": report["variant_statistics"]["gene_context_classifications"],
            "disease_statistics": report["disease_statistics"], "analysis_scope": report["analysis_scope"],
            "input_quality": report["input_quality"]},
        "ancestry": report.get("ancestry", {}), "frequency_policy": report.get("frequency_policy", {}),
        "selection": {"candidate_count": len(candidates), "selected_candidate_count": len(selected),
            "omitted_candidate_count": len(candidates) - len(selected), "requested_genes": requested,
            "automatic_background_vus_inclusion": False}, "tasks": tasks,
        "limitations": list(dict.fromkeys(LIMITATIONS + report.get("limitations", []) + report.get("upstream_limitations", [])))}
    validate_contract(result, "gdgpt_input.schema.json")
    # Detect changed source files before publishing a successful handoff.
    verified, _ = verify_manifest(report_path, "generate_report")
    if verified != manifest or digest(report_path) != result["source_report_manifest"]["sha256"]:
        raise ValueError("生成输入期间上游清单发生变化")
    return result


def prepare(args):
    outdir = args.outdir.resolve()
    if outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {outdir}")
    outdir.mkdir(parents=True)
    try:
        payload = build(args.egene_report.resolve(), args.gene, args.max_candidates)
        write_json(outdir / "gdgpt_input.json", payload)
        shutil.copyfile(args.egene_report, outdir / "egene_report_manifest.source.json")
        manifest = {"schema_version": "1.0", "status": "complete", "stage": "prepare_gdgpt_input",
            "sample_id": payload["sample_id"], "assembly": "GRCh38", "producer": payload["producer"],
            "created_at": now(), "task_count": len(payload["tasks"]), "selection": payload["selection"],
            "source_report_manifest": payload["source_report_manifest"], "files": files_in(outdir)}
        write_json(outdir / "input_manifest.json", manifest)
        write_json(outdir / "status.json", {"stage": manifest["stage"], "status": "complete"})
        print(f"已生成 {len(payload['tasks'])} 个 GDgpt 任务：{outdir / 'input_manifest.json'}", flush=True)
        return manifest
    except BaseException as error:
        write_json(outdir / "status.json", {"stage": "prepare_gdgpt_input", "status": "failed", "error": str(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--egene-report", type=Path, required=True, help="e-Gene delivery/report_manifest.json")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--gene", action="append", default=[])
    parser.add_argument("--max-candidates", type=int)
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
