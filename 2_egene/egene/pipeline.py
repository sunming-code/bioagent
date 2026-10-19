"""One command from a PopGen delivery or a verified completed stage to reports."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import jsonschema

from . import __version__
from .common import ROOT, checksum, now, write_json
from .ingest import load_pack, read_json
from .reporting import make_archive, previous, verified_manifest

STAGES = {
    2: ("prepare_input", "input_manifest.json", "02_input", "prepare_input.py"),
    3: ("annotate_variants", "annotation_manifest.json", "03_annotation", "annotate_variants.py"),
    4: ("classify_variants", "acmg_manifest.json", "04_acmg", "classify_variants.py"),
    5: ("prioritize_diseases", "disease_manifest.json", "05_diseases", "prioritize_diseases.py"),
    6: ("generate_report", "report_manifest.json", "delivery", "generate_report.py"),
}
SOURCE_OPTIONS = [("popgen_pack", 1), ("prepared_manifest", 2), ("annotation_manifest", 3), ("acmg_manifest", 4), ("disease_manifest", 5)]
PREVIOUS = {5: "acmg_manifest", 4: "annotation_manifest", 3: "prepared_manifest"}


def validate_options(args, level):
    if not 1 <= args.threads <= 64 or not 1 <= args.preview_limit <= 1000:
        raise ValueError("threads 必须在 1 到 64 之间，preview-limit 必须在 1 到 1000 之间")
    for name in ("min_dp", "min_gq", "min_qual"):
        value = getattr(args, name)
        if value is not None and (value < 0 or not math.isfinite(value)):
            raise ValueError("质量阈值必须是非负有限数值")
    if level >= 2 and (any(getattr(args, name) is not None for name in ("reference", "bcftools", "convert2annovar", "perl", "min_dp", "min_gq", "min_qual"))
            or args.include_filtered or args.ref_mismatch != "error"):
        raise ValueError("复用准备结果后不能改变输入质量或参考策略；请从 --popgen-pack 重新运行")
    if level >= 3 and (args.annotation_policy or args.verify_database_hashes):
        raise ValueError("复用注释后不能改变注释策略；请从 --prepared-manifest 重新运行")
    if level >= 4 and (args.frequency_policy or args.acmg_scope):
        raise ValueError("复用判级后不能改变频率策略或判级范围；请从 --annotation-manifest 重新运行")
    if level >= 5 and (args.case or args.disease_database or args.disease_policy or args.phenotype_aliases or args.include_background_vus):
        raise ValueError("复用疾病结果后不能改变病例或疾病策略；请从 --acmg-manifest 重新运行")


def input_context(args, level, path):
    if level == 1:
        pack, _ = load_pack(path)
        return pack["metadata"]["sample_id"], {}
    current = verified_manifest(path, STAGES[level][0])
    sample_id, result = current["manifest"]["sample_id"], {}
    for number in range(level, 1, -1):
        result[str(number)] = {"stage": STAGES[number][0], "manifest": str(current["path"]),
            "sha256": current["sha256"], "reused": True, "status": "complete"}
        if number > 2:
            current = previous(current, PREVIOUS[number], STAGES[number - 1][0])
    return sample_id, result


def command_for(number, current, destination, args):
    command = [sys.executable, str(ROOT / "scripts" / STAGES[number][3]), "--outdir", str(destination)]
    source_flag = {2: "--popgen-pack", 3: "--prepared-manifest", 4: "--annotation-manifest", 5: "--acmg-manifest", 6: "--disease-manifest"}[number]
    command += [source_flag, str(current)]
    options = []
    if number == 2:
        options = [("--reference", args.reference), ("--bcftools", args.bcftools), ("--convert2annovar", args.convert2annovar),
            ("--perl", args.perl), ("--min-dp", args.min_dp), ("--min-gq", args.min_gq), ("--min-qual", args.min_qual), ("--ref-mismatch", args.ref_mismatch)]
        if args.include_filtered:
            command.append("--include-filtered")
    elif number == 3:
        options = [("--threads", args.threads), ("--policy", args.annotation_policy)]
        if args.verify_database_hashes:
            command.append("--verify-database-hashes")
    elif number == 4:
        options = [("--scope", args.acmg_scope or "all"), ("--frequency-policy", args.frequency_policy)]
    elif number == 5:
        options = [("--case", args.case), ("--disease-database", args.disease_database), ("--policy", args.disease_policy), ("--phenotype-aliases", args.phenotype_aliases)]
        if args.include_background_vus:
            command.append("--include-background-vus")
    elif number == 6:
        options = [("--preview-limit", args.preview_limit)]
    for flag, value in options:
        if value is not None:
            command += [flag, str(value)]
    if args.keep_work and number in (2, 3, 4):
        command.append("--keep-work")
    return command


def resolve_paths(args):
    # Child processes run from ROOT, so all user-supplied paths must be resolved
    # against the caller's directory before scheduling any stage.
    for name in [key for key, _ in SOURCE_OPTIONS] + ["outdir", "case", "reference", "convert2annovar", "annotation_policy", "frequency_policy", "disease_database", "disease_policy", "phenotype_aliases"]:
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.expanduser().absolute())
    for name in ("bcftools", "perl"):
        value = getattr(args, name)
        if value and os.path.sep in value:
            setattr(args, name, str(Path(value).expanduser().absolute()))


def run(args):
    resolve_paths(args)
    source_name, level = next((name, number) for name, number in SOURCE_OPTIONS if getattr(args, name) is not None)
    validate_options(args, level)
    source_path = getattr(args, source_name).resolve(strict=True)
    source_hash = checksum(source_path)
    sample_id, stages = input_context(args, level, source_path)
    if args.case:
        case = read_json(args.case)
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/case.schema.json")).validate(case)
        if case["sample_id"] != sample_id:
            raise ValueError("病例与输入样本 ID 不一致")
    if args.outdir.exists():
        raise ValueError(f"输出目录已存在，拒绝覆盖: {args.outdir}")
    args.outdir.mkdir(parents=True, exist_ok=False)
    logs = args.outdir / "logs"
    logs.mkdir()
    configuration = {name: str(value) if isinstance(value, Path) else value for name, value in vars(args).items()}
    write_json(args.outdir / "pipeline_config.json", configuration)
    result = {"schema_version": "1.0", "stage": "run_pipeline", "status": "running", "sample_id": sample_id,
        "assembly": "GRCh38", "started_at": now(), "producer": {"name": "egene.pipeline", "version": __version__, "source_sha256": checksum(Path(__file__))},
        "input": {"kind": source_name, "path": str(source_path), "sha256": source_hash}, "stages": stages, "commands": [], "files": {}}
    active = None
    try:
        current = source_path
        for number in range(level + 1, 7):
            stage, name, folder, _ = STAGES[number]
            active = stage
            destination = args.outdir / folder
            command = command_for(number, current, destination, args)
            log_path = logs / (f"{number:02d}_" + stage + ".log")
            execution = {"stage": stage, "argv": command, "log": str(log_path.relative_to(args.outdir)), "started_at": now(), "status": "running"}
            result["commands"].append(execution)
            write_json(args.outdir / "pipeline_manifest.json", result)
            write_json(args.outdir / "status.json", {"stage": "run_pipeline", "status": "running", "active_stage": stage, "pid": os.getpid(), "updated_at": now()})
            print(f"[{number}/6] {stage}，日志：{log_path}", flush=True)
            with log_path.open("w") as log:
                process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            execution.update(finished_at=now(), returncode=process.returncode)
            if process.returncode != 0:
                execution["status"] = "failed"
                raise ValueError(f"{stage} 失败（退出码 {process.returncode}）；详情见 {log_path}")
            current = destination / name
            if number == 6:
                manifest = read_json(current)
                jsonschema.Draft7Validator(read_json(ROOT / "contracts/report_manifest.schema.json")).validate(manifest)
                if read_json(destination / "status.json").get("status") != "complete":
                    raise ValueError("报告没有完成状态")
                for spec in manifest["files"].values():
                    path = destination / spec["path"]
                    if path.stat().st_size != spec["bytes"] or checksum(path) != spec["sha256"]:
                        raise ValueError("报告产物校验失败")
            else:
                manifest = verified_manifest(current, stage)["manifest"]
            if manifest["sample_id"] != sample_id:
                raise ValueError("运行结果样本 ID 不一致")
            execution["status"] = "complete"
            result["stages"][str(number)] = {"stage": stage, "manifest": str(current), "sha256": checksum(current), "reused": False, "status": "complete"}
        if checksum(source_path) != source_hash:
            raise ValueError("运行期间入口文件发生变化")
        for record in result["stages"].values():
            if checksum(Path(record["manifest"])) != record["sha256"]:
                raise ValueError("运行期间步骤清单发生变化")
        archive = args.outdir / "delivery.zip"
        make_archive(args.outdir / "delivery", archive)
        result["status"] = "complete"
        result["finished_at"] = now()
        result["report"] = {"html": "delivery/report.html", "json": "delivery/report.json", "archive": "delivery.zip"}
        files = [args.outdir / "pipeline_config.json", archive, *(logs.glob("*.log")), *(args.outdir / "delivery").rglob("*")]
        result["files"] = {str(path.relative_to(args.outdir)): {"path": str(path.relative_to(args.outdir)), "bytes": path.stat().st_size, "sha256": checksum(path)} for path in files if path.is_file()}
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/pipeline.schema.json")).validate(result)
        write_json(args.outdir / "pipeline_manifest.json", result)
        write_json(args.outdir / "status.json", {"stage": "run_pipeline", "status": "complete", "finished_at": now(), "report": result["report"]})
        print(f"全流程完成：{args.outdir / result['report']['html']}\n报告包：{archive}", flush=True)
        return result
    except BaseException as error:
        result.update(status="failed", failed_at=now(), error=str(error), failed_stage=active)
        write_json(args.outdir / "pipeline_manifest.json", result)
        write_json(args.outdir / "status.json", {"stage": "run_pipeline", "status": "failed", "failed_stage": active, "error": str(error), "failed_at": now()})
        raise


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    for name, _ in SOURCE_OPTIONS:
        source.add_argument("--" + name.replace("_", "-"), type=Path)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--bcftools")
    parser.add_argument("--convert2annovar", type=Path)
    parser.add_argument("--perl")
    parser.add_argument("--min-dp", type=int)
    parser.add_argument("--min-gq", type=float)
    parser.add_argument("--min-qual", type=float)
    parser.add_argument("--include-filtered", action="store_true")
    parser.add_argument("--ref-mismatch", choices=("error", "exclude"), default="error")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--annotation-policy", type=Path)
    parser.add_argument("--verify-database-hashes", action="store_true")
    parser.add_argument("--acmg-scope", choices=("all", "candidates"))
    parser.add_argument("--frequency-policy", type=Path)
    parser.add_argument("--disease-database", type=Path)
    parser.add_argument("--disease-policy", type=Path)
    parser.add_argument("--phenotype-aliases", type=Path)
    parser.add_argument("--include-background-vus", action="store_true")
    parser.add_argument("--preview-limit", type=int, default=200)
    parser.add_argument("--keep-work", action="store_true")
    return parser


def main(argv=None):
    try:
        run(argument_parser().parse_args(argv))
    except (ValueError, OSError, KeyError, TypeError, jsonschema.ValidationError) as error:
        print(f"e-Gene 运行失败：{error}", file=sys.stderr)
        return 2
    return 0
