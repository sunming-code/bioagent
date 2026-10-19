"""Step 6: verified, portable JSON/TSV and standalone Chinese HTML reports."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import heapq
from html import escape
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile
from zoneinfo import ZoneInfo

import jsonschema

from . import __version__
from .annotation import validate_prepared
from .common import ROOT, checksum, now, write_json
from .disease import validate_acmg
from .ingest import read_json, tsv_value

LABELS = {"Pathogenic": "致病", "Likely pathogenic": "可能致病", "Uncertain significance": "意义未明（VUS）",
          "Likely benign": "可能良性", "Benign": "良性", "not_evaluated": "未判级"}
ORDER = {label: index for index, label in enumerate(LABELS)}
EXPORT_FIELDS = ["sample_id", "normalized_id", "CHROM", "POS", "REF", "ALT", "source_GT", "normalized_GT",
    "alt_dosage", "original_DP", "original_GQ", "original_AD", "original_QUAL", "original_FILTER", "quality_missing",
    "matched_pop", "matched_pop_AF", "global_AF", "af_status", "use_for_acmg_ba1_bs1", "genes_refGene", "genes_ensGene",
    "genes_knownGene", "Func.refGene", "ExonicFunc.refGene", "AAChange.refGene", "CLNSIG", "CLNREVSTAT", "CLNDN",
    "triage_route", "triage_reasons", "acmg_evaluated", "display_priority_classification", "acmg_gene_contexts"]
KNOWN_SCHEMAS = {"prepare_input": "prepared_input.schema.json", "annotate_variants": "annotated_variants.schema.json",
                 "classify_variants": "acmg_results.schema.json", "prioritize_diseases": "disease_results.schema.json"}


def verified_manifest(path: Path, stage: str):
    path = path.expanduser().resolve(strict=True)
    manifest = read_json(path)
    jsonschema.Draft7Validator(read_json(ROOT / "contracts" / KNOWN_SCHEMAS[stage])).validate(manifest)
    status = read_json(path.parent / "status.json")
    if manifest.get("stage") != stage or status.get("stage") != stage or status.get("status") != "complete":
        raise ValueError(f"分析步骤未成功完成: {stage}")
    files = {}
    for name, spec in manifest["files"].items():
        file = (path.parent / spec["path"]).resolve(strict=True)
        if file.stat().st_size != spec["bytes"] or checksum(file) != spec["sha256"]:
            raise ValueError(f"报告输入校验失败: {stage}/{name}")
        files[name] = file
    return {"path": path, "sha256": checksum(path), "manifest": manifest, "files": files}


def previous(current, key, stage):
    spec = current["manifest"][key]
    path = (current["path"].parent / spec["path"]).resolve(strict=True)
    if checksum(path) != spec["sha256"]:
        raise ValueError(f"步骤间清单校验失败: {stage}")
    result = verified_manifest(path, stage)
    if result["manifest"]["sample_id"] != current["manifest"]["sample_id"]:
        raise ValueError("报告链包含其他样本")
    return result


def load_chain(path: Path):
    disease = verified_manifest(path, "prioritize_diseases")
    acmg = previous(disease, "acmg_manifest", "classify_variants")
    annotation = previous(acmg, "annotation_manifest", "annotate_variants")
    prepared = previous(annotation, "prepared_manifest", "prepare_input")
    if acmg["manifest"]["frequency_policy"] != prepared["manifest"]["frequency_policy"]:
        raise ValueError("报告链的频率使用权限不一致")
    if disease["manifest"]["counts"]["input_variants"] != acmg["manifest"]["counts"]["selected_variants"]:
        raise ValueError("疾病分析与 ACMG 判级的变异集合数量不一致")
    return {"prepared": prepared, "annotation": annotation, "acmg": acmg, "disease": disease}


def verify_chain_unchanged(chain):
    for group in chain.values():
        if checksum(group["path"]) != group["sha256"]:
            raise ValueError("生成报告期间上游清单发生变化")
        for name, spec in group["manifest"]["files"].items():
            if checksum(group["files"][name]) != spec["sha256"]:
                raise ValueError(f"生成报告期间上游产物发生变化: {name}")


def create_variant_export(chain, outdir, preview_limit):
    """Stream large upstream tables through a disk index, retaining every variant."""
    work = outdir / "work"
    work.mkdir()
    db = sqlite3.connect(work / "report.sqlite")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE variants (id TEXT PRIMARY KEY, ordinal INTEGER, source TEXT, annotation TEXT, triage TEXT);
        CREATE TABLE contexts (id TEXT, gene TEXT, occurrence INTEGER, classification TEXT, data TEXT,
                               PRIMARY KEY(id,gene,occurrence));
        CREATE INDEX contexts_variant ON contexts(id);
    """)
    prepared, annotation, acmg = (chain[key] for key in ("prepared", "annotation", "acmg"))
    counts = Counter({key: 0 for key in ("retained_variants", "annotated_variants", "acmg_gene_contexts", "acmg_selected_variants")})
    context_counts, variant_counts = Counter(), Counter()
    try:
        with prepared["files"]["patient_variants.tsv"].open(newline="") as handle:
            csv.field_size_limit(64 * 1024 * 1024)
            for ordinal, row in enumerate(csv.DictReader(handle, delimiter="\t"), 1):
                if row["sample_id"] != prepared["manifest"]["sample_id"] or None in row:
                    raise ValueError("患者变异表样本或列数不一致")
                db.execute("INSERT INTO variants(id,ordinal,source) VALUES (?,?,?)", (row["normalized_id"], ordinal, json.dumps(row)))
                counts["retained_variants"] += 1
        with annotation["files"]["annotated_variants.jsonl"].open() as handle:
            for line in handle:
                record = json.loads(line)
                stored = db.execute("SELECT source,annotation FROM variants WHERE id=?", (record["normalized_id"],)).fetchone()
                if stored is None or stored["annotation"] is not None or json.loads(stored["source"]) != record["patient"]:
                    raise ValueError("注释结果不能唯一连接到患者侧表")
                db.execute("UPDATE variants SET annotation=?,triage=? WHERE id=?", (
                    json.dumps(record["annotation"]), json.dumps(record["triage"]), record["normalized_id"]))
                counts["annotated_variants"] += 1
        if counts["retained_variants"] != prepared["manifest"]["counts"]["retained_variants"] or counts["annotated_variants"] != counts["retained_variants"]:
            raise ValueError("报告全量变异/注释数量不一致")
        with acmg["files"]["acmg_results.jsonl"].open() as handle:
            for line in handle:
                record = json.loads(line)
                stored = db.execute("SELECT source FROM variants WHERE id=?", (record["normalized_id"],)).fetchone()
                label = record["integrated"]["classification"]
                if stored is None or json.loads(stored["source"]) != record["patient"] or label not in LABELS or label == "not_evaluated":
                    raise ValueError("ACMG 上下文与患者变异或分类不一致")
                item = {"gene": record["gene"], "occurrence": record["gene_occurrence"], "classification": label,
                        "raw_classification": record["raw"]["classification"], "evidence": record["integrated"]["evidence"],
                        "evidence_changes": record["evidence_changes"], "data_flags": record["data_flags"]}
                db.execute("INSERT INTO contexts VALUES (?,?,?,?,?)", (record["normalized_id"], record["gene"], record["gene_occurrence"], label, json.dumps(item)))
                context_counts[label] += 1
        if sum(context_counts.values()) != acmg["manifest"]["counts"]["gene_context_records"]:
            raise ValueError("报告 ACMG 基因上下文数量不一致")
        counts["acmg_gene_contexts"] = sum(context_counts.values())
        counts["acmg_selected_variants"] = db.execute("SELECT count(DISTINCT id) FROM contexts").fetchone()[0]
        if counts["acmg_selected_variants"] != acmg["manifest"]["counts"]["selected_variants"]:
            raise ValueError("报告 ACMG 判级变异数不一致")
        counts["variants_with_plp_context"] = 0
        counts["variants_with_vus_context"] = 0
        with (outdir / "variants.tsv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()

            def rows():
                for stored in db.execute("SELECT * FROM variants ORDER BY ordinal"):
                    source, anno, triage = (json.loads(stored[key]) for key in ("source", "annotation", "triage"))
                    contexts = [json.loads(row[0]) for row in db.execute("SELECT data FROM contexts WHERE id=? ORDER BY gene,occurrence", (stored["id"],))]
                    labels = {item["classification"] for item in contexts}
                    display = min(labels, key=ORDER.get) if labels else "not_evaluated"
                    variant_counts[display] += 1
                    counts["variants_with_plp_context"] += bool(labels & {"Pathogenic", "Likely pathogenic"})
                    counts["variants_with_vus_context"] += "Uncertain significance" in labels
                    result = {key: source.get(key, "") for key in EXPORT_FIELDS}
                    result.update({key: anno.get(key, ".") for key in ("Func.refGene", "ExonicFunc.refGene", "AAChange.refGene", "CLNSIG", "CLNREVSTAT", "CLNDN")})
                    result.update(genes_refGene=anno.get("Gene.refGene", "."), genes_ensGene=anno.get("Gene.ensGene", "."),
                        genes_knownGene=anno.get("Gene.knownGene", "."), triage_route=triage["triage_route"],
                        triage_reasons=triage.get("triage_reasons", []), acmg_evaluated=bool(contexts),
                        display_priority_classification=display, acmg_gene_contexts=contexts)
                    writer.writerow({key: tsv_value(result[key]) for key in EXPORT_FIELDS})
                    yield {**result, "ordinal": stored["ordinal"]}

            preview = heapq.nsmallest(preview_limit, rows(), key=lambda row: (ORDER[row["display_priority_classification"]],
                row["triage_route"] == "background", row["ordinal"]))
        counts["variants_not_classified"] = counts["retained_variants"] - counts["acmg_selected_variants"]
        return {"counts": dict(counts), "gene_context_classifications": dict(context_counts),
                "variant_display_priority_classifications": dict(variant_counts), "preview": preview,
                "display_priority_semantics": "One display-priority label per variant; every gene-context label and evidence is retained in the TSV. This display label is not a new classification."}
    finally:
        db.close()
        shutil.rmtree(work)


def report_conclusion(stats, disease_count):
    counts = stats["counts"]
    if counts["acmg_selected_variants"] == 0:
        finding = "本次没有变异完成 ACMG 判级。"
    elif counts["variants_with_plp_context"]:
        finding = f"本次有 {counts['variants_with_plp_context']:,} 个变异至少包含一个致病/可能致病的基因上下文，需核对疾病机制及病例背景。"
    else:
        finding = "本次已判级集合中未见致病/可能致病的基因上下文。"
    finding += f" 当前策略形成 {disease_count:,} 个基因—疾病候选。"
    return {"finding": finding, "interpretation": "候选和相容基因型用于复核，不能单独确立患者诊断；空候选也不能排除遗传病。",
            "risk_probability": None, "risk_probability_status": "not_estimated", "diagnosis_established": False}


def write_provenance(chain, outdir):
    directory = outdir / "provenance"
    directory.mkdir()
    for label, group in chain.items():
        shutil.copyfile(group["path"], directory / (label + "_manifest.source.json"))
    mapping = {"input_qc.json": ("prepared", "input_qc.json"),
        "popgen_evidence_pack.source.json": ("prepared", "popgen_evidence_pack.json"),
        "annotation_databases.json": ("annotation", "database_snapshot.json"),
        "annotation_policy.json": ("annotation", "triage_policy.json"),
        "intervar_snapshot.json": ("acmg", "intervar_snapshot.json"),
        "acmg_frequency_policy.json": ("acmg", "frequency_policy.json"),
        "disease_databases.json": ("disease", "disease_database_snapshot.json"),
        "disease_policy.json": ("disease", "disease_policy.json")}
    for target, (stage, name) in mapping.items():
        shutil.copyfile(chain[stage]["files"][name], directory / target)


def html_table(headers, rows, table_id=None):
    attribute = f' id="{escape(table_id)}"' if table_id else ""
    head = "".join(f"<th>{escape(str(value))}</th>" for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>" for row in rows)
    return f'<div class="table-scroll"><table{attribute}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render_html(report):
    sample, stats = report["sample"], report["variant_statistics"]
    counts = stats["counts"]
    candidates, preview = report["disease_candidates"], stats["preview"]
    def e(value):
        return escape(str(value))
    def metric(label, value):
        return f'<div class="metric"><span>{e(label)}</span><strong>{e(value)}</strong></div>'
    context_rows = [[LABELS[label], stats["gene_context_classifications"].get(label, 0)] for label in LABELS if label != "not_evaluated"]
    phenotype = report["phenotypes"]
    phenotype_rows = [["阳性" if item["input"]["observed"] else "明确否定", item["resolved"]["id"], item["resolved"]["label"], item["input"].get("source_text", "")]
                      for item in phenotype.get("resolved_entries", [])]
    candidate_rows = [[row["rank"], row["disease_name"], row["disease_id"], row["gene"], row["inheritance_status"],
        "未评估" if row["phenotype_score"] is None else row["phenotype_score"], "；".join(row["supporting_variant_ids"])] for row in candidates[:100]]
    variant_rows = [[row["normalized_id"], row["genes_refGene"], row["source_GT"], LABELS[row["display_priority_classification"]],
        row["triage_route"], row["Func.refGene"], row["AAChange.refGene"], row["matched_pop_AF"] or "未知"] for row in preview]
    quality = report["input_quality"]
    issues = "".join(f"<li>{e(value)}</li>" for value in report["limitations"])
    qc = "".join(f"<li>{e(value)}</li>" for value in quality.get("warnings", [])) or "<li>上游未记录额外质量提示。</li>"
    ancestry = report["ancestry"].get("analysis_based", {})
    ancestry_rows = [["查表人群", ancestry.get("af_population", "未知")], ["祖源归属状态", ancestry.get("assignment", "未知")],
        ["PopGen 频率可参与 BA1/BS1 评估", "是；仍需背景与阈值" if report["frequency_policy"].get("use_for_acmg_ba1_bs1") else "否；仅作信息展示"],
        ["GNN 用途", "祖源辅助信息；不作为疾病概率或判级分数"]]
    phenotype_text = ("已使用结构化阳性 HPO 条目进行匹配。" if phenotype["positive_hpo_ids"] else "没有可解析的阳性表型，表型匹配未评估。")
    resolved = html_table(["观察", "HPO", "名称", "原始记录"], phenotype_rows) if phenotype_rows else "<p>没有结构化表型记录。</p>"
    unresolved = "".join(f"<li>{e(item['input'].get('label', item['input'].get('id', '')))}：{e(item['reason'])}</li>" for item in phenotype.get("unresolved_entries", []))
    details = []
    for row in candidates[:100]:
        evidence_rows = [[variant["normalized_id"], LABELS.get(variant["classification"], variant["classification"]),
            variant["patient"]["source_GT"], variant["consequence"].get("AAChange.refGene", ".")] for variant in row["variants"]]
        detail_json = json.dumps({"inheritance": row["inheritance"], "phenotype": row["phenotype"],
            "association_sources": row["association_sources"], "review_flags": row["review_flags"]}, ensure_ascii=False, indent=2)
        details.append(f'<details><summary>#{row["rank"]} {e(row["gene"])} · {e(row["disease_name"])}</summary>'
            + html_table(["支持变异", "原始分类", "GT", "转录本/蛋白改变"], evidence_rows)
            + f'<pre>{e(detail_json)}</pre></details>')
    versions = report["versions"]
    version_rows = [["报告模块", report["producer"]["version"]], ["参考版本", "GRCh38 / hg38"],
        ["分类器", f"InterVar {versions['classifier']['version']} / {versions['classifier']['guidelines']}"],
        ["HPO", versions["disease_databases"].get("hpo_release", "未知")], ["HGNC", versions["disease_databases"].get("hgnc_release", "未知")]]
    downloads = "".join(f'<a download href="{name}">{title}</a>' for name, title in [
        ("report.json", "结构化报告"), ("variants.tsv", "全量变异"), ("acmg_results.tsv", "ACMG 证据"),
        ("disease_candidates.tsv", "疾病候选"), ("carrier_findings.tsv", "携带者可能性"),
        ("variant_disease_links.tsv", "全部疾病关联"), ("report_manifest.json", "文件校验清单")])
    metrics = "".join([metric("保留的变异", f"{counts['retained_variants']:,}"), metric("已判级变异", f"{counts['acmg_selected_variants']:,}"),
        metric("ACMG 基因上下文", f"{counts['acmg_gene_contexts']:,}"), metric("疾病—基因候选", f"{len(candidates):,}")])
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{e(sample['sample_id'])} · e-Gene 分析报告</title>
<style>
:root{{--ink:#182638;--muted:#53657a;--line:#dce5ee;--accent:#006c76;--bg:#f2f6f8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 system-ui,-apple-system,"Noto Sans SC",sans-serif}}
main{{max-width:1240px;margin:auto;padding:30px 24px 60px}}header{{border-top:5px solid var(--accent);padding:24px 0}}h1{{font-size:30px;margin:4px 0 12px}}h2{{font-size:21px;margin:0 0 16px}}h3{{font-size:17px}}
.eyebrow{{font-size:12px;color:var(--accent);letter-spacing:2px}}.sub,.muted{{color:var(--muted)}}section{{background:white;border:1px solid var(--line);border-radius:12px;padding:24px;margin:20px 0}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.metric{{border:1px solid var(--line);border-radius:10px;padding:18px;background:white}}.metric span{{display:block;color:var(--muted);font-size:13px}}.metric strong{{font-size:30px;color:var(--accent)}}
.conclusion{{border-left:4px solid var(--accent)}}.table-scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}}th{{background:#eef5f7;font-weight:600;white-space:nowrap}}
input{{padding:9px 12px;border:1px solid var(--line);border-radius:6px;width:min(100%,460px);margin:0 0 14px}}button,.downloads a{{display:inline-block;border:1px solid var(--line);background:white;color:var(--accent);padding:8px 12px;border-radius:6px;text-decoration:none;margin:4px;cursor:pointer}}details{{border-top:1px solid var(--line);padding:12px 0}}summary{{cursor:pointer;font-weight:600}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f5f7fa;padding:14px}}.empty{{color:var(--muted);padding:18px;background:#f7f9fb}}footer{{font-size:12px;color:var(--muted)}}
@media(max-width:700px){{.metrics{{grid-template-columns:repeat(2,1fr)}}main{{padding:16px}}section{{padding:16px}}h1{{font-size:24px}}}}
@media print{{body{{background:white}}main{{max-width:none;padding:0}}section{{break-inside:avoid;border-radius:0}}.downloads,button,input{{display:none}}.table-scroll{{overflow:visible}}a{{color:inherit}}}}
</style></head><body><main>
<header><div class="eyebrow">E-GENE · VARIANT INTERPRETATION</div><h1>遗传变异与疾病关联分析报告</h1>
<div class="sub">样本 {e(sample['sample_id'])} · GRCh38 · {e(report['generated_at_local'])}</div><button type="button" onclick="window.print()">打印 / 保存 PDF</button></header>
<div class="metrics">{metrics}</div>
<section class="conclusion"><h2>本次结果</h2><p>{e(report['conclusion']['finding'])}</p><p>{e(report['conclusion']['interpretation'])}</p>
<p class="muted">个体患病概率：未估计。ACMG 判级范围：{e(report['analysis_scope']['acmg_scope'])}；未判级变异 {counts['variants_not_classified']:,} 个。</p></section>
<section><h2>病例与表型</h2><p>性别：{e({'male':'男','female':'女','unknown':'未知'}.get(sample.get('sex'),'未知'))}；年龄：{e(sample.get('age_years') if sample.get('age_years') is not None else '未提供')}；发病年龄：{e(sample.get('onset_age_years') if sample.get('onset_age_years') is not None else '未提供')}。</p>
<p>{e(phenotype_text)}</p>{resolved}<ul>{unresolved}</ul><details><summary>原始临床描述</summary><p>{e(report['case'].get('clinical_description') or '未提供')}</p></details></section>
<section><h2>疾病候选与遗传解释</h2><p class="muted">按基因—疾病背景展示；表型分数用于复核排序。携带者可能性是候选表的一个子集。预览最多 100 项，完整结果见下载文件。</p>
{html_table(['排序','疾病','标识','基因','遗传相容性','表型相似度','支持变异'],candidate_rows) if candidate_rows else '<p class="empty">当前筛选策略没有形成疾病候选；全部已知基因—疾病映射仍保留在关联表。</p>'}
{''.join(details)}</section>
<section><h2>ACMG 分类分布</h2><p class="muted">以下按基因上下文计数，一个变异可有多个上下文，不能与变异数直接相加。</p>{html_table(['分类','基因上下文数'],context_rows)}</section>
<section><h2>变异预览</h2><p class="muted">显示 {len(preview):,} / {counts['retained_variants']:,} 个变异，按复核优先级排序。多基因记录的展示分类仅用于排序，完整逐上下文分类与证据见 ACMG 表。</p>
<input type="search" id="variant-filter" aria-label="筛选变异预览" placeholder="在预览中搜索基因、变异或分类">{html_table(['变异','注释基因','原始 GT','展示分类','筛选路由','功能区域','转录本/蛋白改变','匹配人群 AF'],variant_rows,'variant-preview')}</section>
<section><h2>祖源与频率使用</h2>{html_table(['项目','结果'],ancestry_rows)}<p class="muted">频率缺失保持未知；全局 AF 不绕过 PopGen 使用权限。</p></section>
<section><h2>输入质量与分析范围</h2><p>原始 VCF 记录 {quality.get('input_records',0):,} 条；保留变异 {counts['retained_variants']:,} 个。原始记录和 ALT 数的统计口径不同。</p><ul>{qc}</ul>
{html_table(['处理结果','ALT 数'],sorted(quality.get('allele_decisions',{}).items()))}<details><summary>质量字段缺失统计</summary>{html_table(['字段','缺失记录数'],sorted(quality.get('records_missing_quality',{}).items()))}</details></section>
<section><h2>版本、依据与限制</h2>{html_table(['项目','版本'],version_rows)}<ul>{issues}</ul><p>使用 HPO 和 HGNC，具体来源、许可、版本及校验值见 provenance 目录。source 清单是原始运行快照，其内部路径供追溯；报告包中的下载文件采用相对路径。</p></section>
<section class="downloads"><h2>完整结果下载</h2>{downloads}</section>
<footer>报告标识 {e(report['report_id'])} · {e(report['producer']['name'])} {e(report['producer']['version'])} · 全部内容由已验证的分析结果生成。</footer>
</main><script>document.getElementById('variant-filter').addEventListener('input',function(){{const q=this.value.toLocaleLowerCase();document.querySelectorAll('#variant-preview tbody tr').forEach(function(row){{row.hidden=!row.textContent.toLocaleLowerCase().includes(q)}})}});</script></body></html>'''


def generate(args):
    chain = load_chain(args.disease_manifest)
    outdir = args.outdir.expanduser().absolute()
    if outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {outdir}")
    if not 1 <= args.preview_limit <= 1000:
        raise ValueError("报告变异预览数量必须为 1 到 1000")
    outdir.mkdir(parents=True, exist_ok=False)
    write_json(outdir / "status.json", {"stage": "generate_report", "status": "running", "started_at": now()})
    try:
        stats = create_variant_export(chain, outdir, args.preview_limit)
        disease = chain["disease"]
        case = read_json(disease["files"]["case.json"])
        phenotypes = read_json(disease["files"]["phenotypes.normalized.json"])
        candidates = json.loads(disease["files"]["disease_candidates.json"].read_text())
        if not isinstance(candidates, list):
            raise ValueError("疾病候选文件必须为数组")
        disease_summary = read_json(disease["files"]["disease_summary.json"])
        if len(candidates) != disease["manifest"]["counts"]["candidate_disease_gene_pairs"]:
            raise ValueError("报告疾病候选数量不一致")
        sample_id = disease["manifest"]["sample_id"]
        if case["sample_id"] != sample_id or phenotypes["sample_id"] != sample_id:
            raise ValueError("病例/表型快照与报告样本不一致")
        created = now()
        snapshot = read_json(chain["annotation"]["files"]["database_snapshot.json"])
        report = {"schema_version": "1.0", "report_id": "egene-" + chain["disease"]["sha256"][:16],
            "generated_at": created, "generated_at_local": datetime.fromisoformat(created).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S Asia/Shanghai"),
            "producer": {"name": "egene.reporting", "version": __version__},
            "sample": {"sample_id": sample_id, "sex": case.get("sex", "unknown"), "age_years": case.get("age_years"), "onset_age_years": case.get("onset_age_years")},
            "assembly": "GRCh38", "conclusion": report_conclusion(stats, len(candidates)),
            "analysis_scope": {"acmg_scope": chain["acmg"]["manifest"]["scope"], "case_provided": disease["manifest"]["case_input"]["provided"],
                "phenotype_status": disease["manifest"]["phenotype_status"], "classification_labels_modified": False},
            "variant_statistics": stats, "disease_statistics": disease["manifest"]["counts"],
            "case": case, "phenotypes": phenotypes, "disease_candidates": candidates,
            "ancestry": chain["prepared"]["manifest"].get("ancestry", {}), "frequency_policy": chain["prepared"]["manifest"]["frequency_policy"],
            "input_quality": read_json(chain["prepared"]["files"]["input_qc.json"]),
            "versions": {"classifier": chain["acmg"]["manifest"]["classifier"], "annotation_databases": snapshot,
                         "disease_databases": read_json(disease["files"]["disease_database_snapshot.json"])},
            "limitations": ["候选疾病、相容基因型和 VUS 均不能单独建立患者诊断，空候选不排除遗传疾病。",
                "InterVar 使用固定的 ACMG-AMP 2015 规则和历史兼容数据库；疾病特异机制、外显率及后续全部专家规范未自动核验。",
                "HPO 基因—疾病关联不等同于 ClinGen 临床有效性审定；OMIM 与 ORPHA 条目可能描述同一种疾病。",
                "缺失的质量、频率、表型、父母调用及相位均保留未知；报告不新增 ACMG 证据或个体患病概率。",
                "当前仅解释前序流程保留的变异及明确的基因—疾病关联，不涵盖所有遗传机制或所有变异类型。",
                "显示预览有数量上限，完整变异、ACMG 证据和全部疾病关联保存在随附 TSV 中。"],
            "upstream_limitations": disease_summary.get("limitations", []),
            "files": {"variants": "variants.tsv", "acmg": "acmg_results.tsv", "diseases": "disease_candidates.tsv",
                "carriers": "carrier_findings.tsv", "associations": "variant_disease_links.tsv", "manifest": "report_manifest.json"}}
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/report.schema.json")).validate(report)
        write_json(outdir / "report.json", report)
        (outdir / "report.html").write_text(render_html(report))
        for target, stage, name in [("acmg_results.tsv", "acmg", "acmg_results.tsv"), ("disease_candidates.tsv", "disease", "disease_candidates.tsv"),
                ("carrier_findings.tsv", "disease", "carrier_findings.tsv"), ("variant_disease_links.tsv", "disease", "variant_disease_links.tsv"),
                ("case.json", "disease", "case.json"), ("phenotypes.normalized.json", "disease", "phenotypes.normalized.json")]:
            shutil.copyfile(chain[stage]["files"][name], outdir / target)
        write_provenance(chain, outdir)
        verify_chain_unchanged(chain)
        files = [path for path in outdir.rglob("*") if path.is_file() and path.name != "status.json"]
        manifest = {"schema_version": "1.0", "status": "complete", "stage": "generate_report", "sample_id": sample_id, "assembly": "GRCh38",
            "producer": {"name": "egene.reporting", "version": __version__, "finished_at": now(), "source_sha256": checksum(Path(__file__))},
            "disease_manifest": {"path": str(chain["disease"]["path"]), "sha256": chain["disease"]["sha256"]},
            "counts": {**stats["counts"], "disease_candidates": len(candidates)}, "classification_labels_modified": False,
            "files": {str(path.relative_to(outdir)): {"path": str(path.relative_to(outdir)), "bytes": path.stat().st_size, "sha256": checksum(path)} for path in sorted(files)}}
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/report_manifest.schema.json")).validate(manifest)
        write_json(outdir / "report_manifest.json", manifest)
        write_json(outdir / "status.json", {"stage": "generate_report", "status": "complete", "finished_at": now(), "counts": manifest["counts"]})
        print(f"报告完成：{outdir / 'report.html'}", flush=True)
        return manifest
    except BaseException as error:
        write_json(outdir / "status.json", {"stage": "generate_report", "status": "failed", "failed_at": now(), "error": str(error)})
        raise


def make_archive(directory, target):
    if target.exists():
        raise ValueError(f"报告压缩包已存在，拒绝覆盖: {target}")
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(directory)))


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disease-manifest", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--preview-limit", type=int, default=200)
    return parser


def main(argv=None):
    try:
        generate(argument_parser().parse_args(argv))
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, jsonschema.ValidationError) as error:
        print(f"报告生成失败：{error}", file=sys.stderr)
        return 2
    return 0
