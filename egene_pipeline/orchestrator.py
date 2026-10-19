"""One command from VCF/FASTQ or verified upstream results to GDgpt delivery."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import os
from pathlib import Path
import shutil
import sys
import uuid
import zipfile

from . import __version__
from .common import ROOT, digest, file_spec, files_in, now, read_json, run_command, verify_files, verify_manifest, write_json

SOURCE_FLAGS = ("vcf", "fastq_dir", "popgen_pack", "prepared_manifest", "annotation_manifest",
                "acmg_manifest", "disease_manifest", "egene_report", "gdgpt_input", "gdgpt_manifest", "resume_from")
PIPELINE_STAGES = ("popgen", "egene", "gdgpt", "atheromap")
EGENE_PATHS = ("reference", "annotation_policy", "frequency_policy", "disease_database", "disease_policy", "phenotype_aliases", "case", "convert2annovar")
EGENE_VALUES = EGENE_PATHS + ("bcftools", "perl", "min_dp", "min_gq", "min_qual", "ref_mismatch", "acmg_scope", "preview_limit")
EGENE_BOOLS = ("include_filtered", "verify_database_hashes", "include_background_vus", "keep_work")
ATHEROMAP_PATHS = ("atheromap_reference", "atheromap_gsmap_root")
ATHEROMAP_VALUES = ATHEROMAP_PATHS + ("atheromap_scope", "atheromap_mode", "atheromap_plots", "atheromap_timeout")
DEFAULTS = {"threads": 4, "skip_cv": False, "skip_gnn": False, "ref_mismatch": "error", "preview_limit": 200,
            "gene": [], "max_candidates": None, "max_rounds": 6, "task_timeout": 3600, "prompt_variants": 20,
            "with_atheromap": False, "atheromap_scope": "reference-context", "atheromap_mode": "reuse",
            "atheromap_plots": "all", "atheromap_timeout": 7200,
            **{name: False for name in EGENE_BOOLS}}


def argument_parser():
    p = argparse.ArgumentParser(description="PopGen → e-Gene → GDgpt 统一流水线，默认保留全部疾病候选，逐任务保存证据。")
    sources = p.add_mutually_exclusive_group(required=True)
    for name in SOURCE_FLAGS:
        sources.add_argument("--" + name.replace("_", "-"), type=Path)
    p.add_argument("--outdir", type=Path, help="必须是新目录；默认 runs/<时间_任务ID>")
    p.add_argument("--end-stage", choices=PIPELINE_STAGES,
                   help="完成指定阶段后停止并保留该阶段产物；省略则执行完整交付")
    p.add_argument("--threads", type=int)
    p.add_argument("--skip-cv", action="store_true", default=None)
    p.add_argument("--skip-gnn", action="store_true", default=None)
    p.add_argument("--gene", action="append", help="显式探索患者已有变异的指定基因，可重复；不改变疾病候选或 ACMG 分类")
    p.add_argument("--max-candidates", type=int, help="可选限制疾病候选任务数量；默认全部，省略数量记入报告")
    p.add_argument("--max-rounds", type=int, help="GDgpt 每任务最大轮数，默认 6")
    p.add_argument("--task-timeout", type=int, help="每任务硬超时秒数，默认 3600；超时终止子进程后可续接")
    p.add_argument("--prompt-variants", type=int, help="每任务模型上下文最多展示的变异上下文数，默认20；完整证据始终交付")
    p.add_argument("--with-atheromap", "--atheromap", dest="with_atheromap", action="store_true", default=None,
                   help="在 GDgpt 完成后接入第四阶段 AtheroMap：scDRS 参考分析及已验收 gsMap 空间结果")
    p.add_argument("--atheromap-reference", type=Path, help="AtheroMap scDRS 参考数据清单")
    p.add_argument("--atheromap-gsmap-root", type=Path, help="已验收 GSE241346 gsMap 工作目录")
    p.add_argument("--atheromap-scope", choices=("reference-context", "matched-trait"))
    p.add_argument("--atheromap-mode", choices=("reuse", "recompute"))
    p.add_argument("--atheromap-plots", choices=("all", "python", "none"))
    p.add_argument("--atheromap-timeout", type=int, help="AtheroMap 单阶段超时秒数，默认7200")
    for name in EGENE_PATHS:
        p.add_argument("--" + name.replace("_", "-"), type=Path)
    for name in ("bcftools", "perl"):
        p.add_argument("--" + name)
    for name in ("min_dp", "min_gq", "min_qual"):
        p.add_argument("--" + name.replace("_", "-"), type=float)
    p.add_argument("--ref-mismatch", choices=("error", "exclude"))
    p.add_argument("--acmg-scope", choices=("all", "candidates"))
    p.add_argument("--preview-limit", type=int)
    for name in EGENE_BOOLS:
        p.add_argument("--" + name.replace("_", "-"), action="store_true", default=None)
    for name in ("popgen_python", "egene_python", "gdgpt_python"):
        p.add_argument("--" + name.replace("_", "-"), type=Path)
    return p


def configuration(args, previous=None):
    values = {key: str(value.expanduser().absolute()) if isinstance(value, Path) else value
              for key, value in vars(args).items() if key not in SOURCE_FLAGS + ("outdir", "end_stage")}
    config = dict((previous or {}).get("configuration", {}))
    for key, value in values.items():
        if previous and value is not None and value != config.get(key) and key not in {
            "threads", "task_timeout", "popgen_python", "egene_python", "gdgpt_python",
            "with_atheromap", "atheromap_reference", "atheromap_gsmap_root",
            "atheromap_scope", "atheromap_mode", "atheromap_plots", "atheromap_timeout",
        }:
            raise ValueError(f"--resume-from 不允许改变已记录的 {key}；请从相应上游清单开始新运行")
        if value is not None:
            config[key] = value
    for key, value in DEFAULTS.items():
        config.setdefault(key, value)
    for name in EGENE_VALUES:
        config.setdefault(name, None)
    config.setdefault("egene_python", str(ROOT / "2_egene/.runtime/venv/bin/python"))
    config.setdefault("gdgpt_python", str(ROOT / "3_GDgpt/.venv/bin/python"))
    config.setdefault("popgen_python", config["egene_python"])
    config.setdefault("atheromap_reference", str(ROOT / "4_atheromap/config/GSE159677_scdrs.reference.json"))
    config.setdefault("atheromap_gsmap_root", str(ROOT / "4_atheromap_data/GSE241346_gsMap"))
    for name in ATHEROMAP_VALUES:
        config.setdefault(name, None)
    if not 1 <= config["threads"] <= 64 or not 1 <= config["max_rounds"] <= 6 or config["task_timeout"] < 1 or config["prompt_variants"] < 1 or config["atheromap_timeout"] < 1:
        raise ValueError("threads 范围为1–64，max-rounds 为1–6，超时及上下文数量必须为正数")
    if config["max_candidates"] is not None and config["max_candidates"] < 1:
        raise ValueError("max-candidates 必须为正整数")
    for name in ("popgen_python", "egene_python", "gdgpt_python"):
        if not Path(config[name]).is_file() or not os.access(config[name], os.X_OK):
            raise ValueError(f"缺少可执行环境 {name}: {config[name]}")
    if config["with_atheromap"]:
        for name in ("atheromap_reference", "atheromap_gsmap_root"):
            if not Path(config[name]).exists():
                raise ValueError(f"缺少 AtheroMap 输入: {name}={config[name]}")
    return config


def validate_reuse(record, name):
    path = Path(record["artifact"]["path"])
    if digest(path) != record["artifact"]["sha256"] or path.stat().st_size != record["artifact"]["bytes"]:
        raise ValueError(f"复用步骤清单被修改: {name}")
    if name != "popgen":
        stage = {"egene": "generate_report", "bridge": "prepare_gdgpt_input", "gdgpt": "gdgpt_analysis",
                 "atheromap": "atheromap"}[name]
        return verify_manifest(path, stage)[0]["sample_id"]
    pack = read_json(path)
    if pack.get("schema_version") != "1.0" or pack["metadata"].get("genome_build") != "GRCh38":
        raise ValueError("PopGen 交付包版本或参考版本不兼容")
    return pack["metadata"]["sample_id"]


def deliver(outdir, stages):
    egene_path = Path(stages["egene"]["artifact"]["path"])
    gdgpt_path = Path(stages["gdgpt"]["artifact"]["path"])
    egene, egene_files = verify_manifest(egene_path, "generate_report")
    gdgpt, gdgpt_files = verify_manifest(gdgpt_path, "gdgpt_analysis")
    if egene["sample_id"] != gdgpt["sample_id"]:
        raise ValueError("最终交付的两个报告不属于同一样本")
    atheromap_path = Path(stages["atheromap"]["artifact"]["path"]) if "atheromap" in stages else None
    atheromap_manifest = atheromap_files = None
    if atheromap_path is not None:
        atheromap_manifest, atheromap_files = verify_manifest(atheromap_path, "atheromap")
        if atheromap_manifest["sample_id"] != egene["sample_id"]:
            raise ValueError("AtheroMap 与 e-Gene/GDgpt 不属于同一样本")
    delivery = outdir / "delivery"
    delivery.mkdir()
    packages = [("egene", egene_path, egene_files), ("gdgpt", gdgpt_path, gdgpt_files)]
    if atheromap_path is not None:
        packages.append(("atheromap", atheromap_path, atheromap_files))
    for label, manifest_path, files in packages:
        folder = delivery / label
        folder.mkdir()
        for name, src in files.items():
            # Preserve nested relative paths, including offline provenance links.
            rel = src.relative_to(manifest_path.parent.resolve())
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
        shutil.copyfile(manifest_path, folder / manifest_path.name)
        shutil.copyfile(manifest_path.parent / "status.json", folder / "status.json")
    er = read_json(egene_files["report.json"])
    gr = read_json(gdgpt_files["report.json"])
    am = read_json(atheromap_files["report.json"]) if atheromap_files else None
    summary = {"schema_version": "1.0", "sample_id": egene["sample_id"], "assembly": "GRCh38", "generated_at": now(),
        "producer": {"name": "egene_pipeline", "version": __version__},
        "upstream_conclusion": er["conclusion"], "variant_counts": er["variant_statistics"]["counts"],
        "gene_context_classifications": er["variant_statistics"]["gene_context_classifications"],
        "disease_statistics": er["disease_statistics"], "ancestry": er.get("ancestry", {}),
        "frequency_policy": er.get("frequency_policy", {}), "gdgpt_analysis_status": gr["analysis_status"],
        "gdgpt_summary": gr["summary"], "gdgpt_selection": gr["selection"], "gdgpt_task_count": len(gr["task_results"]),
        "classification_labels_modified": False, "diagnosis_established": False, "risk_probability": None,
        "stages": stages, "limitations": list(dict.fromkeys(gr["limitations"] + (am.get("limitations", []) if am else []))),
        "atheromap_analysis_status": (am["status"] if am else None),
        "files": {"egene_report": "egene/report.html", "gdgpt_report": "gdgpt/report.html", "gdgpt_input": "gdgpt/gdgpt_input.json",
                  "atheromap_report": "atheromap/report.html" if atheromap_files else None}}
    write_json(delivery / "pipeline_report.json", summary)
    sample = escape(egene["sample_id"])
    (delivery / "index.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>e-Gene 统一分析报告</title>'
        '<style>body{max-width:1000px;margin:40px auto;padding:0 20px;font:17px/1.8 system-ui}a{color:#0759aa}li{margin:12px 0}</style>'
        f'<h1>统一分析报告：{sample}</h1><p>PopGen → e-Gene → GDgpt' + (' → AtheroMap' if atheromap_files else '') + '</p>'
        f'<p>{escape(er["conclusion"]["finding"])}</p><p>{escape(gr["summary"])}</p>'
        '<ul><li><a href="egene/report.html">e-Gene：完整变异、ACMG 分类与疾病候选</a></li>'
        '<li><a href="gdgpt/report.html">GDgpt：机制分析、图谱证据和分析边界</a></li>'
        + ('<li><a href="atheromap/report.html">AtheroMap：scDRS 参考分析与 gsMap 空间结果</a></li>' if atheromap_files else '') +
        '<li><a href="gdgpt/gdgpt_input.json">GDgpt 完整输入证据</a></li>'
        '<li><a href="pipeline_report.json">统一结构化结果和溯源</a></li></ul>'
        '<p>分类与上游保持一致；疾病候选和模型机制解释均不等于患者确诊。</p></html>', encoding="utf-8")
    write_json(delivery / "delivery_manifest.json", {"schema_version": "1.0", "status": "complete", "sample_id": egene["sample_id"],
        "producer": summary["producer"], "files": files_in(delivery)})
    archive = outdir / "delivery.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(delivery.rglob("*")):
            if path.is_file():
                bundle.write(path, Path("delivery") / path.relative_to(delivery))
    verify_files(delivery, read_json(delivery / "delivery_manifest.json")["files"])
    return summary


def run(args):
    source_name = next(name for name in SOURCE_FLAGS if getattr(args, name) is not None)
    source_path = getattr(args, source_name).expanduser().resolve(strict=True)
    previous = read_json(source_path) if source_name == "resume_from" else None
    if previous and (previous.get("stage") != "integrated_pipeline" or previous.get("schema_version") != "1.0"):
        raise ValueError("--resume-from 必须指向统一流水线的 pipeline_manifest.json")
    config = configuration(args, previous)
    source_stage = {"fastq_dir": "popgen", "vcf": "popgen", "popgen_pack": "egene",
                    "prepared_manifest": "egene", "annotation_manifest": "egene", "acmg_manifest": "egene",
                    "disease_manifest": "egene", "egene_report": "gdgpt", "gdgpt_input": "gdgpt",
                    "gdgpt_manifest": "atheromap"}.get(source_name)
    if args.end_stage and source_stage and PIPELINE_STAGES.index(source_stage) > PIPELINE_STAGES.index(args.end_stage):
        raise ValueError(f"输入已经来自 {source_stage}，不能结束在更早的 {args.end_stage} 阶段")
    outdir = (args.outdir or ROOT / "runs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])).expanduser().resolve()
    if outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {outdir}")
    if previous:
        entry = previous["input"]
        stages = {name: {**record, "reused": True} for name, record in previous["stages"].items() if record["status"] == "complete"}
    else:
        entry = {"kind": source_name, **file_spec(source_path)} if source_path.is_file() else {"kind": source_name, "path": str(source_path)}
        stages = {}
    outdir.mkdir(parents=True)
    result = {"schema_version": "1.0", "stage": "integrated_pipeline", "status": "running", "started_at": now(),
        "producer": {"name": "egene_pipeline", "version": __version__}, "input": entry,
        "configuration": config, "stages": stages, "commands": [], "sample_id": None, "files": {},
        "requested_end_stage": args.end_stage}
    active = None
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        env[key] = str(config["threads"])
    env.setdefault("HF_HUB_OFFLINE", "1")

    def save(status="running", error=None):
        result["status"] = status
        write_json(outdir / "pipeline_manifest.json", result)
        write_json(outdir / "status.json", {"stage": "integrated_pipeline", "status": status,
            "active_stage": active, "sample_id": result["sample_id"], "updated_at": now(), "error": error,
            "report": (result.get("report") or {}).get("html") if status == "complete" else None,
            "end_stage": result.get("end_stage")})

    def finish_partial(name):
        """Publish a successful stage-bounded run without requiring downstream reports."""
        nonlocal active
        active = name
        result.update(status="complete", end_stage=name, finished_at=now(),
                      report={"stage": name, "artifact": stages[name]["artifact"]})
        save("complete")
        print(f"阶段 {name} 完成，产物：{stages[name]['artifact']['path']}", flush=True)
        return result

    def record(name, path, reused=False):
        item = {"status": "complete", "artifact": file_spec(path), "reused": reused}
        sample_id = validate_reuse(item, name)
        if result["sample_id"] is not None and result["sample_id"] != sample_id:
            raise ValueError("步骤之间混入其他样本")
        result["sample_id"] = sample_id
        stages[name] = item
        save()

    def execute(name, command, cwd):
        nonlocal active
        active = name
        log = outdir / "logs" / (name + ".log")
        execution = {"stage": name, "argv": [str(x) for x in command], "log": str(log.relative_to(outdir)), "started_at": now(), "status": "running"}
        result["commands"].append(execution)
        save()
        print(f"[{name}] 开始，日志：{log}", flush=True)
        try:
            run_command(command, cwd, log, env=env)
            execution.update(status="complete", finished_at=now())
        except BaseException:
            execution.update(status="failed", finished_at=now())
            raise

    try:
        save()
        for name, stage_record in list(stages.items()):
            validate_reuse(stage_record, name)
            record(name, Path(stage_record["artifact"]["path"]), True)
        kind, path = entry["kind"], Path(entry["path"])
        if kind in {"vcf", "fastq_dir"} and "popgen" not in stages and "egene" not in stages:
            destination = outdir / "01_popgen"
            command = [config["popgen_python"], ROOT / "1_popgen/orchestrator.py", "--" + kind.replace("_", "-"), path,
                "--outdir", destination, "--threads", config["threads"]]
            if config["reference"]:
                command += ["--ref", config["reference"]]
            for flag in ("skip_cv", "skip_gnn"):
                if config[flag]:
                    command += ["--" + flag.replace("_", "-")]
            execute("popgen", command, ROOT / "1_popgen")
            record("popgen", destination / "delivery/evidence_pack.json")
        elif kind == "popgen_pack" and "popgen" not in stages:
            record("popgen", path, True)
        elif kind == "egene_report" and "egene" not in stages:
            record("egene", path, True)
        elif kind == "gdgpt_manifest" and "gdgpt" not in stages:
            record("gdgpt", path, True)
        if args.end_stage == "popgen" and "popgen" in stages:
            return finish_partial("popgen")
        elif kind == "gdgpt_input" and "bridge" not in stages:
            if args.gene is not None or args.max_candidates is not None:
                raise ValueError("复用 GDgpt 输入后不能改变任务选择；请从 --egene-report 开始")
            record("bridge", path, True)
            payload = read_json(path.parent / "gdgpt_input.json")
            source = payload["source_report_manifest"]
            if digest(source["path"]) != source["sha256"]:
                raise ValueError("GDgpt 输入对应的 e-Gene 原始报告已改变")
            record("egene", Path(source["path"]), True)
        if kind != "gdgpt_manifest" and "egene" not in stages:
            active = "egene"
            source_flag = "popgen_pack" if "popgen" in stages else kind
            upstream = stages["popgen"]["artifact"]["path"] if "popgen" in stages else path
            destination = outdir / "02_egene"
            command = [config["egene_python"], ROOT / "2_egene/run.py", "--" + source_flag.replace("_", "-"), upstream,
                       "--outdir", destination, "--threads", config["threads"]]
            # Continue the last verified e-Gene substage after an interrupted run.
            resumed_level = None
            if previous:
                internal_path = source_path.parent / "02_egene/pipeline_manifest.json"
                if internal_path.is_file():
                    internal = read_json(internal_path)
                    for level in (5, 4, 3, 2):
                        item = internal.get("stages", {}).get(str(level), {})
                        if item.get("status") == "complete":
                            upstream = Path(item["manifest"])
                            if digest(upstream) != item["sha256"]:
                                raise ValueError("e-Gene 续接清单发生变化")
                            source_flag = {2: "prepared_manifest", 3: "annotation_manifest", 4: "acmg_manifest", 5: "disease_manifest"}[level]
                            command = [config["egene_python"], ROOT / "2_egene/run.py", "--" + source_flag.replace("_", "-"), upstream,
                                       "--outdir", destination, "--threads", config["threads"]]
                            resumed_level = level
                            break
            completed_options = set()
            if resumed_level is not None:
                if resumed_level >= 2:
                    completed_options.update(("reference", "bcftools", "convert2annovar", "perl", "min_dp", "min_gq", "min_qual", "include_filtered", "ref_mismatch"))
                if resumed_level >= 3:
                    completed_options.update(("annotation_policy", "verify_database_hashes"))
                if resumed_level >= 4:
                    completed_options.update(("frequency_policy", "acmg_scope"))
                if resumed_level >= 5:
                    completed_options.update(("case", "disease_database", "disease_policy", "phenotype_aliases", "include_background_vus"))
            for name in EGENE_VALUES:
                if config.get(name) is not None and name not in completed_options:
                    command += ["--" + name.replace("_", "-"), config[name]]
            for name in EGENE_BOOLS:
                if config[name] and name not in completed_options:
                    command += ["--" + name.replace("_", "-")]
            execute("egene", command, ROOT)
            record("egene", destination / "delivery/report_manifest.json")
        elif not previous:
            changed = [name for name in EGENE_VALUES + EGENE_BOOLS if getattr(args, name) is not None and getattr(args, name) is not False]
            if changed:
                raise ValueError("复用完整报告后不能更改 e-Gene 策略或病例：" + ", ".join(changed))
        if args.end_stage == "egene" and "egene" in stages:
            return finish_partial("egene")
        if kind != "gdgpt_manifest" and "bridge" not in stages:
            destination = outdir / "03_gdgpt_input"
            command = [config["egene_python"], "-m", "egene_pipeline.adapter", "--egene-report", stages["egene"]["artifact"]["path"], "--outdir", destination]
            for gene in config["gene"]:
                command += ["--gene", gene]
            if config["max_candidates"] is not None:
                command += ["--max-candidates", config["max_candidates"]]
            execute("bridge", command, ROOT)
            record("bridge", destination / "input_manifest.json")
        if args.end_stage == "gdgpt" and "gdgpt" in stages:
            return finish_partial("gdgpt")
        if kind != "gdgpt_manifest" and "gdgpt" not in stages:
            destination = outdir / "04_gdgpt"
            command = [config["gdgpt_python"], "-m", "egene_pipeline.gdgpt", "--input-manifest", stages["bridge"]["artifact"]["path"],
                "--outdir", destination, "--max-rounds", config["max_rounds"], "--task-timeout", config["task_timeout"],
                "--prompt-variants", config["prompt_variants"]]
            if previous:
                partial = source_path.parent / "04_gdgpt"
                if (partial / "gdgpt_manifest.json").is_file():
                    command += ["--resume-results", partial]
            execute("gdgpt", command, ROOT)
            record("gdgpt", destination / "gdgpt_manifest.json")
        if args.end_stage == "gdgpt" and "gdgpt" in stages:
            return finish_partial("gdgpt")
        if config["with_atheromap"] and "atheromap" not in stages:
            destination = outdir / "05_atheromap"
            command = [config["egene_python"], "-m", "egene_pipeline.atheromap",
                       "--gdgpt-manifest", stages["gdgpt"]["artifact"]["path"],
                       "--outdir", destination,
                       "--reference", config["atheromap_reference"],
                       "--gsmap-root", config["atheromap_gsmap_root"],
                       "--scope", config["atheromap_scope"],
                       "--mode", config["atheromap_mode"],
                       "--plots", config["atheromap_plots"],
                       "--timeout", config["atheromap_timeout"]]
            execute("atheromap", command, ROOT)
            record("atheromap", destination / "atheromap_manifest.json")
        if args.end_stage == "atheromap" and "atheromap" in stages:
            return finish_partial("atheromap")
        active = "delivery"
        save()
        for name, item in stages.items():
            validate_reuse(item, name)
        if entry.get("sha256") and (not path.is_file() or digest(path) != entry["sha256"]):
            raise ValueError("运行期间原始入口文件发生变化")
        summary = deliver(outdir, stages)
        delivered_files = {"delivery/" + name: {**spec, "path": "delivery/" + spec["path"]}
                           for name, spec in files_in(outdir / "delivery").items()}
        result.update(finished_at=now(), gdgpt_analysis_status=summary["gdgpt_analysis_status"],
            report={"html": "delivery/index.html", "json": "delivery/pipeline_report.json", "archive": "delivery.zip"},
            files=delivered_files)
        result["archive"] = file_spec(outdir / "delivery.zip", outdir)
        result["files"]["delivery.zip"] = result["archive"]
        save("complete")
        print(f"完整流水线交付：{outdir / 'delivery/index.html'}\n报告包：{outdir / 'delivery.zip'}", flush=True)
        return result
    except BaseException as error:
        result.update(failed_at=now(), failed_stage=active, error=str(error))
        save("failed", str(error))
        raise


def main(argv=None):
    try:
        run(argument_parser().parse_args(argv))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"统一流水线失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
