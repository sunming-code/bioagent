"""Run the verified GDgpt → AtheroMap fourth stage.

This stage prepares the checksum-verified handoff, runs the existing scDRS
reference workflow, and attaches the already validated GSE241346 gsMap
spatial/GWAS results.  It never treats the external reference cohorts as
patient tissue or patient-specific genetic measurements.
"""
from __future__ import annotations

import argparse
from html import escape
import shutil
from pathlib import Path

from . import __version__
from .atheromap_adapter import prepare as prepare_handoff
from .common import ROOT, digest, file_spec, files_in, now, read_json, run_command, verify_manifest, write_json

DEFAULT_REFERENCE = ROOT / "4_atheromap/config/GSE159677_scdrs.reference.json"
DEFAULT_GSMAP_ROOT = ROOT / "4_atheromap_data/GSE241346_gsMap"


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"AtheroMap 已验收结果目录不存在: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)


def validate_gsmap_source(root: Path) -> dict:
    validation = root / "validation/gsmap_real_samples"
    manifest_path = validation / "validation_manifest.json"
    result_path = validation / "result_validation.json"
    browser_path = validation / "browser_validation.json"
    files_index_path = validation / "output_files.json"
    for path in (manifest_path, result_path, browser_path, files_index_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"gsMap 验收证据缺失: {path}")
    manifest = read_json(manifest_path)
    result = read_json(result_path)
    browser = read_json(browser_path)
    index = read_json(files_index_path)
    if manifest.get("status") != "complete" or result.get("status") != "passed" or browser.get("status") != "passed":
        raise ValueError("gsMap 真实样本验收状态不是 complete/passed")
    if not {sample["sample"] for sample in result.get("samples", [])} >= {"GSE241346_sample1", "GSE241346_sample2"}:
        raise ValueError("gsMap 验收没有同时包含两个真实样本")
    for item in index.get("files", []):
        path = root / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError(f"gsMap 已验收输出完整性失败: {path}")
    return {"manifest": manifest, "result": result, "browser": browser, "files": index,
            "validation_root": str(validation)}


def run(args):
    output = Path(args.outdir).resolve()
    source_manifest = Path(args.gdgpt_manifest).resolve(strict=True)
    reference = Path(args.reference).resolve(strict=True)
    gsmap_root = Path(args.gsmap_root).resolve(strict=True)
    if output.exists():
        raise ValueError(f"AtheroMap 输出目录已存在，拒绝覆盖: {output}")
    gsmap = validate_gsmap_source(gsmap_root)
    output.mkdir(parents=True)
    input_dir = output / "input"
    scdrs_dir = output / "scdrs"
    gsmap_dir = output / "gsmap"
    manifest = {
        "schema_version": "1.0", "stage": "atheromap", "status": "running", "started_at": now(),
        "sample_id": None, "assembly": "GRCh38",
        "producer": {"name": "egene_pipeline.atheromap", "version": __version__},
        "gdgpt_manifest": file_spec(source_manifest), "reference_manifest": file_spec(reference),
        "gsmap_root": str(gsmap_root), "scope": args.scope, "mode": args.mode, "plots": args.plots,
        "steps": [], "files": {},
    }
    write_json(output / "atheromap_manifest.json", manifest)
    write_json(output / "status.json", {"stage": "atheromap", "status": "running", "active_step": None})

    def step(name, action):
        record = {"name": name, "status": "running", "started_at": now()}
        manifest["steps"].append(record)
        write_json(output / "atheromap_manifest.json", manifest)
        write_json(output / "status.json", {"stage": "atheromap", "status": "running", "active_step": name})
        try:
            action()
            record.update(status="complete", finished_at=now())
        except BaseException:
            record.update(status="failed", finished_at=now())
            raise
        write_json(output / "atheromap_manifest.json", manifest)

    try:
        step("prepare_input", lambda: prepare_handoff(argparse.Namespace(
            gdgpt_manifest=source_manifest, reference=reference, scope=args.scope, outdir=input_dir)))
        input_manifest = input_dir / "input_manifest.json"
        handoff, _ = verify_manifest(input_manifest, "prepare_atheromap_input")
        manifest["sample_id"] = handoff["sample_id"]

        step("scdrs", lambda: run_command([
            "bash", ROOT / "4_atheromap/tools/run_scdrs.sh",
            "--input-manifest", input_manifest,
            "--mode", args.mode,
            "--plots", args.plots,
            "--timeout", args.timeout,
            "--outdir", scdrs_dir,
        ], ROOT, output / "logs/scdrs.log", timeout=args.timeout + 120))
        scdrs_manifest_path = scdrs_dir / "atheromap_manifest.json"
        scdrs_manifest, _ = verify_manifest(scdrs_manifest_path, "atheromap_scdrs")
        if scdrs_manifest["sample_id"] != handoff["sample_id"]:
            raise ValueError("scDRS 输出样本与 GDgpt 输入不一致")

        def attach_gsmap():
            _copy_tree(gsmap_root / "results/gsmap_quick_mode", gsmap_dir / "results/gsmap_quick_mode")
            _copy_tree(gsmap_root / "validation/gsmap_real_samples", gsmap_dir / "validation/gsmap_real_samples")
            write_json(gsmap_dir / "source.json", {
                "source_root": str(gsmap_root),
                "source_validation_manifest": file_spec(gsmap_root / "validation/gsmap_real_samples/validation_manifest.json"),
                "source_result_validation": file_spec(gsmap_root / "validation/gsmap_real_samples/result_validation.json"),
                "source_browser_validation": file_spec(gsmap_root / "validation/gsmap_real_samples/browser_validation.json"),
                "attached_without_recomputation": True,
            })
        step("gsmap_validated_results", attach_gsmap)

        scdrs_report = read_json(scdrs_dir / "delivery/report.json")
        gsmap_report = gsmap["result"]
        report = {
            "schema_version": "1.0", "stage": "atheromap", "status": "complete",
            "sample_id": handoff["sample_id"], "assembly": "GRCh38", "generated_at": now(),
            "analysis_scope": handoff.get("analysis_scope"),
            "scdrs": {
                "status": scdrs_manifest["status"], "mode": scdrs_manifest.get("mode"),
                "report": "scdrs/delivery/report.json", "html": "scdrs/delivery/report.html",
                "reference_dataset_id": scdrs_report.get("reference_dataset_id"),
                "reference_cells": scdrs_report.get("reference_cells"),
            },
            "gsmap": {
                "status": gsmap["result"]["status"], "validation": "gsmap/validation/gsmap_real_samples/validation_manifest.json",
                "result_validation": "gsmap/validation/gsmap_real_samples/result_validation.json",
                "browser_validation": "gsmap/validation/gsmap_real_samples/browser_validation.json",
                "samples": [{"sample": s["sample"], "report": "gsmap/" + s["report"],
                             "n_spots": s["n_spots"], "n_groups": s["n_groups"],
                             "bh_significant_spots": s["bh_significant_spots"],
                             "bh_significant_groups": s["bh_significant_groups"]}
                            for s in gsmap_report["samples"]],
            },
            "classification_labels_modified": False, "diagnosis_established": False, "risk_probability": None,
            "limitations": list(dict.fromkeys(scdrs_report.get("limitations", []) + [
                "gsMap spatial results are the validated external GSE241346 reference analysis, not patient tissue.",
                "Spatial domain numbers are SpaGCN IDs and are not reviewed histopathology labels.",
                "scDRS uses the external GSE159677 reference cohort and does not calculate a patient-specific risk probability.",
            ])),
        }
        write_json(output / "report.json", report)
        links = [
            '<li><a href="scdrs/delivery/report.html">AtheroMap scDRS 报告</a></li>',
            '<li><a href="gsmap/validation/gsmap_real_samples/README.md">gsMap 两个真实样本验收记录</a></li>',
        ]
        for sample in gsmap_report["samples"]:
            links.append(f'<li><a href="gsmap/{escape(sample["report"], quote=True)}">{escape(sample["sample"])} gsMap HTML 报告</a></li>')
        (output / "report.html").write_text(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>AtheroMap 第四阶段报告</title>'
            '<style>body{max-width:1100px;margin:32px auto;padding:0 20px;font:16px/1.8 system-ui}a{color:#0759aa}</style>'
            f'<h1>AtheroMap 第四阶段：{escape(handoff["sample_id"])}</h1>'
            '<p>本阶段同时保留 scDRS 外部参考队列分析和已验收 gsMap 空间结果。</p><ul>' + ''.join(links) +
            '</ul><p>这些结果不改变 ACMG 分类，不建立患者诊断或个体患病概率。</p></html>', encoding="utf-8")
        manifest["files"] = files_in(output, ("atheromap_manifest.json", "status.json"))
        manifest.update(status="complete", finished_at=now(), report={"json": "report.json", "html": "report.html"},
                        scdrs_manifest="scdrs/atheromap_manifest.json",
                        gsmap_validation="gsmap/validation/gsmap_real_samples/validation_manifest.json")
        write_json(output / "atheromap_manifest.json", manifest)
        write_json(output / "status.json", {"stage": "atheromap", "status": "complete", "sample_id": handoff["sample_id"], "report": "report.html"})
        # Verify the published manifest and all copied artifacts after final writes.
        verify_manifest(output / "atheromap_manifest.json", "atheromap")
        print(f"AtheroMap 第四阶段完成：{output / 'report.html'}", flush=True)
        return manifest
    except BaseException as error:
        manifest.update(status="failed", failed_at=now(), error=str(error))
        write_json(output / "atheromap_manifest.json", manifest)
        write_json(output / "status.json", {"stage": "atheromap", "status": "failed", "error": str(error)})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gdgpt-manifest", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--gsmap-root", type=Path, default=DEFAULT_GSMAP_ROOT)
    parser.add_argument("--scope", choices=("reference-context", "matched-trait"), default="reference-context")
    parser.add_argument("--mode", choices=("reuse", "recompute"), default="reuse")
    parser.add_argument("--plots", choices=("all", "python", "none"), default="all")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("timeout 必须为正数")
    run(args)


if __name__ == "__main__":
    main()
