"""Run GDgpt on verified e-Gene tasks, isolating and checkpointing each model run."""
from __future__ import annotations

import argparse
from html import escape
import json
import os
from pathlib import Path
import shutil
import signal
import sys
from time import monotonic
from urllib.parse import urlsplit, urlunsplit

from . import __version__
from .common import ROOT, digest, file_spec, files_in, now, object_digest, read_json, run_command, validate_contract, verify_files, verify_manifest, write_json

GDGPT = ROOT / "3_GDgpt"


def load_input(path):
    manifest, files = verify_manifest(path, "prepare_gdgpt_input")
    payload = read_json(files["gdgpt_input.json"])
    validate_contract(payload, "gdgpt_input.schema.json")
    if payload["sample_id"] != manifest["sample_id"] or len(payload["tasks"]) != manifest["task_count"]:
        raise ValueError("GDgpt 输入的样本或任务数量不一致")
    if len({t["id"] for t in payload["tasks"]}) != len(payload["tasks"]):
        raise ValueError("GDgpt 任务 ID 重复")
    for task in payload["tasks"]:
        if any(e["gene"] != task["gene"] for e in task["evidence"]):
            raise ValueError("任务基因与变异证据不一致")
    return payload


def make_question(payload, task, prompt_variants=20):
    candidate = task["candidate"]
    disease = candidate["disease_name"] if candidate else "none; exploratory gene analysis only"
    labels = sorted({e["classification"] for e in task["evidence"]})
    # All KG/entity planners see the target even where legacy code slices to 600 chars.
    prefix = (f"Gene: {task['gene']}. Disease hypothesis: {disease}. "
              f"Upstream classifications: {', '.join(labels)}. "
              "Explain gene-level pathways using the Task KG. No variant-specific pathogenicity or treatment claim. ")
    prefix = prefix[:590]
    policy = (
        "\n请用中文完成机制解释，保留英文实体名。以下资料是上游观察，不是知识图谱事实。"
        "将上游事实标记为 [upstream:e-Gene]，图谱事实引用实际边，其他推断标记 [LLM-inferred]。"
        "不得修改 ACMG 分类、把 VUS 当成致病、把候选当成确诊，或把祖源置信分当成患病概率。"
        "图谱没有变异节点；不能用基因层面的关联证明该等位基因致病、可用药或药物敏感。"
        "未提供的病史/表型保持未知。引用肿瘤关系时说明当前病例没有据此确诊肿瘤。"
        "请说明图谱支持的基因功能/通路、与病例证据之间的缺口及需要核验的事项。"
        "每位专家控制在400字以内，最终报告控制在1000字以内。\n"
    )
    clinical = {"sample": payload["sample"], "clinical_description": payload["case"].get("clinical_description", "")[:4000],
        "clinical_description_omitted_characters": max(0, len(payload["case"].get("clinical_description", "")) - 4000),
        "positive_hpo_ids": payload["phenotypes"].get("positive_hpo_ids", [])[:50],
        "negative_hpo_ids": payload["phenotypes"].get("negative_hpo_ids", [])[:50],
        "phenotype_status": payload["phenotypes"].get("status"),
        "family": payload["case"].get("family", {})}
    brief_candidate = None if candidate is None else {key: candidate.get(key) for key in (
        "candidate_id", "disease_id", "disease_name", "rank", "priority_band", "inheritance_status", "inheritance_mode",
        "phenotype_status", "phenotype_score", "acmg_classifications", "review_flags", "diagnosis_established")}
    evidence = task["evidence"][:prompt_variants]
    upstream = {"sample_id": payload["sample_id"], "assembly": payload["assembly"], "task_kind": task["kind"],
        "clinical": clinical, "conclusion": payload["upstream_summary"]["conclusion"],
        "candidate": brief_candidate, "variant_evidence": evidence,
        "variant_evidence_total": len(task["evidence"]), "variant_evidence_omitted_from_prompt": len(task["evidence"]) - len(evidence),
        "omission_note": "完整证据保存在交付的 gdgpt_input.json；省略记录未被本次模型逐项审阅。",
        "frequency_policy": payload["frequency_policy"], "limitations": payload["limitations"]}
    return prefix + policy + "\n[Upstream observations]\n" + json.dumps(upstream, ensure_ascii=False)


def runtime_signature():
    sys.path.insert(0, str(GDGPT))
    from utils import load_config
    cfg = load_config()
    endpoint = urlsplit(cfg["base_url"])
    public_url = urlunsplit((endpoint.scheme, endpoint.hostname or "", endpoint.path, "", ""))
    sources = ["agents.py", "workflow.py", "tools.py", "knowledge_base.py", "parallel_execution.py", "utils.py",
               "kg_build/task_kg_output/task_kg_nodes.csv", "kg_build/task_kg_output/task_kg_edges.csv"]
    signature = {"model": cfg["text_model"], "base_url": public_url,
        "embedding_provider": cfg.get("embedding_provider", "openai"), "embedding_model": cfg.get("embedding_model"),
        "neo4j_uri": cfg.get("neo4j_uri"), "neo4j_database": cfg.get("neo4j_database"),
        "max_parallel_experts": cfg.get("max_parallel_experts", 7), "max_parallel_queries": cfg.get("max_parallel_queries", 3),
        "source_sha256": {name: digest(GDGPT / name) for name in sources},
        "integration_sha256": {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")}}
    return cfg, signature


def run_task(args):
    payload = load_input(args.input_manifest)
    task = next(t for t in payload["tasks"] if t["id"] == args.task_id)
    cfg, runtime = runtime_signature()
    if not cfg.get("api_key"):
        raise ValueError("GDgpt 未配置 API Key；请在 3_GDgpt/config.json 或 GDGPT_API_KEY 中配置")
    from agents import MDTAgents
    from workflow import create_workflow, is_placeholder_final_answer
    from evaluation.run_batch_eval_template import run_one_question
    conf = {key: cfg.get("neo4j_" + key, "") for key in ("uri", "user", "password", "database")}
    agents = MDTAgents(cfg["api_key"], cfg["base_url"], cfg["text_model"], True, neo4j_conf=conf)
    status = agents.tools.neo4j_kg.test_connection()
    if status.get("ok") != "true":
        raise RuntimeError(f"GDgpt 图谱不可用: {status.get('message')}")
    question = make_question(payload, task, args.prompt_variants)
    started = monotonic()
    compiled = create_workflow(agents)

    class ProgressWorkflow:
        def stream(self, state):
            for event in compiled.stream(state):
                for stage, data in event.items():
                    print(f"{task['id']} {stage}: {data.get('stage_elapsed_seconds', 0):.2f}s", flush=True)
                yield event

    try:
        result = run_one_question(ProgressWorkflow(), agents, question, args.max_rounds)
        if is_placeholder_final_answer(result.get("answer_text")):
            raise RuntimeError("GDgpt 未生成实质性答案")
        if any(not item["ok"] for item in result.get("execution_timings", [])):
            raise RuntimeError("本次 GDgpt 分析中存在失败的模型请求或专家调用")
        runs = [r for call in result["tool_calls"] if isinstance(call.get("result"), dict)
                for r in call["result"].get("runs", [])]
        if any(r.get("error") for r in runs):
            raise RuntimeError("GDgpt 图谱查询失败；不将工具故障记为正常的低覆盖")
        result.update(schema_version="1.0", status="complete", task_id=task["id"], sample_id=payload["sample_id"],
            task_sha256=object_digest(task), input_sha256=object_digest(payload), runtime=runtime,
            parameters={"max_rounds": args.max_rounds, "prompt_variants": args.prompt_variants},
            question=question, gene=task["gene"], kind=task["kind"], candidate_id=task["candidate_id"],
            elapsed_seconds=round(monotonic() - started, 3), completed_at=now(),
            diagnosis_established=False, classification_labels_modified=False, risk_probability=None)
        write_json(args.task_output, result)
    finally:
        tool = agents.tools.neo4j_kg
        if getattr(tool, "_driver", None):
            tool._driver.close()


def write_report(outdir, payload, results, runtime):
    status = "analyzed" if results else "no_eligible_candidates"
    summary = (f"已完成 {len(results)} 项基因机制分析。" if results else
               "上游没有可自动进入机制分析的疾病候选，本次未调用大模型。未自动提升 background VUS，也未生成疾病诊断。")
    report = {"schema_version": "1.0", "sample_id": payload["sample_id"], "assembly": "GRCh38",
        "generated_at": now(), "analysis_status": status, "summary": summary,
        "upstream_summary": payload["upstream_summary"], "selection": payload["selection"],
        "case": payload["case"], "phenotypes": payload["phenotypes"], "ancestry": payload["ancestry"],
        "frequency_policy": payload["frequency_policy"], "runtime": runtime,
        "task_results": results, "limitations": payload["limitations"],
        "diagnosis_established": False, "risk_probability": None, "classification_labels_modified": False}
    write_json(outdir / "report.json", report)
    sections = [f"# GDgpt 机制分析：{payload['sample_id']}", summary,
        "## 上游结论", payload["upstream_summary"]["conclusion"]["finding"],
        "完整逐变异证据见 gdgpt_input.json；ACMG 分类以 e-Gene 原始交付为准。"]
    for result in results:
        sections += [f"## {result['gene']} / {result['kind']}",
            f"图谱查询覆盖：{result['kg_coverage_level']}；结果为待复核的模型机制解释。", result["answer_text"]]
    sections += ["## 分析边界"] + [f"- {line}" for line in payload["limitations"]]
    content = "\n\n".join(sections) + "\n"
    (outdir / "report.md").write_text(content, encoding="utf-8")
    (outdir / "report.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>GDgpt 机制分析</title>'
        '<style>body{max-width:1100px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
        '<nav><a href="report.json">结构化结果与工具记录</a> · <a href="gdgpt_input.json">完整上游任务证据</a></nav>'
        '<pre>' + escape(content) + '</pre></html>', encoding="utf-8")
    return report


def run(args):
    if not 1 <= args.max_rounds <= 6 or args.prompt_variants < 1 or args.task_timeout < 1:
        raise ValueError("max-rounds 范围为 1–6；prompt-variants 和 task-timeout 必须为正数")
    payload = load_input(args.input_manifest)
    if args.outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {args.outdir}")
    args.outdir.mkdir(parents=True)
    (args.outdir / "tasks").mkdir()
    (args.outdir / "questions").mkdir()
    manifest = {"schema_version": "1.0", "stage": "gdgpt_analysis", "status": "running",
        "sample_id": payload["sample_id"], "assembly": "GRCh38", "started_at": now(),
        "producer": {"name": "egene_pipeline.gdgpt", "version": __version__},
        "input_manifest": file_spec(args.input_manifest), "tasks": {}, "files": {}}
    manifest_path = args.outdir / "gdgpt_manifest.json"
    current_task = None
    try:
        runtime = runtime_signature()[1] if payload["tasks"] else None
        parameters = {"max_rounds": args.max_rounds, "prompt_variants": args.prompt_variants}
        previous = None
        if args.resume_results:
            previous = read_json(args.resume_results / "gdgpt_manifest.json")
            if previous["sample_id"] != payload["sample_id"] or previous["input_manifest"]["sha256"] != digest(args.input_manifest):
                raise ValueError("续接 GDgpt 结果的样本或输入清单不一致")
        results = []
        write_json(args.outdir / "gdgpt_input.json", payload)
        shutil.copyfile(args.input_manifest, args.outdir / "input_manifest.source.json")
        for task in payload["tasks"]:
            current_task = task["id"]
            target = args.outdir / "tasks" / (current_task + ".json")
            (args.outdir / "questions" / (current_task + ".txt")).write_text(make_question(payload, task, args.prompt_variants), encoding="utf-8")
            old = (previous or {}).get("tasks", {}).get(current_task)
            if old and old.get("status") == "complete":
                old_path = verify_files(args.resume_results, {current_task: old["file"]})[current_task]
                result = read_json(old_path)
                if (result["runtime"] != runtime or result["parameters"] != parameters
                        or result["task_sha256"] != object_digest(task) or result["input_sha256"] != object_digest(payload)):
                    raise ValueError("已完成任务的模型、代码、参数或输入变化；请从输入清单开始新分析")
                shutil.copyfile(old_path, target)
                print(f"复用已完成任务 {current_task}", flush=True)
            else:
                manifest["tasks"][current_task] = {"status": "running", "started_at": now()}
                write_json(manifest_path, manifest)
                write_json(args.outdir / "status.json", {"stage": manifest["stage"], "status": "running", "task": current_task})
                run_command([sys.executable, "-m", "egene_pipeline.gdgpt", "--input-manifest", args.input_manifest,
                    "--task-id", current_task, "--task-output", target, "--max-rounds", args.max_rounds,
                    "--prompt-variants", args.prompt_variants], ROOT, args.outdir / "logs" / (current_task + ".log"),
                    timeout=args.task_timeout)
                result = read_json(target)
            if (result.get("status") != "complete" or result.get("sample_id") != payload["sample_id"]
                    or result.get("task_id") != current_task or result.get("task_sha256") != object_digest(task)
                    or result.get("runtime") != runtime or result.get("input_sha256") != object_digest(payload)
                    or result.get("parameters") != parameters):
                raise ValueError("模型运行产物的任务、输入、模型或完成状态不一致")
            results.append(result)
            manifest["tasks"][current_task] = {"status": "complete", "file": file_spec(target, args.outdir)}
            write_json(manifest_path, manifest)
        # Upstream input must still be intact after all model calls.
        load_input(args.input_manifest)
        if digest(args.input_manifest) != manifest["input_manifest"]["sha256"]:
            raise ValueError("模型分析期间输入清单发生变化")
        report = write_report(args.outdir, payload, results, runtime)
        manifest.update(status="complete", finished_at=now(), analysis_status=report["analysis_status"],
            runtime=runtime, parameters=parameters, files=files_in(args.outdir, ("gdgpt_manifest.json", "status.json")))
        write_json(manifest_path, manifest)
        write_json(args.outdir / "status.json", {"stage": manifest["stage"], "status": "complete", "analysis_status": report["analysis_status"]})
        print(f"GDgpt 完成：{args.outdir / 'report.html'}", flush=True)
        return manifest
    except BaseException as error:
        manifest.update(status="failed", failed_at=now(), failed_task=current_task, error=str(error))
        write_json(manifest_path, manifest)
        write_json(args.outdir / "status.json", {"stage": manifest["stage"], "status": "failed", "task": current_task, "error": str(error)})
        raise


def main():
    # Allow the orchestrator to stop us while a task subprocess is in flight.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--outdir", type=Path)
    parser.add_argument("--resume-results", type=Path)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--task-timeout", type=int, default=3600)
    parser.add_argument("--prompt-variants", type=int, default=20)
    parser.add_argument("--task-id", help=argparse.SUPPRESS)
    parser.add_argument("--task-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.task_id:
        if not args.task_output:
            parser.error("内部任务必须指定输出文件")
        run_task(args)
    else:
        if not args.outdir:
            parser.error("必须指定 --outdir")
        run(args)


if __name__ == "__main__":
    main()
