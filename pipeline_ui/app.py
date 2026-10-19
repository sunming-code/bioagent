"""Small local web UI for running and observing the unified pipeline.

The pipeline itself remains the source of truth.  This service only starts the
existing ``run_pipeline.py`` entry point and turns its atomic manifest/status
files into a browser friendly snapshot and an SSE stream.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
RUNS.mkdir(parents=True, exist_ok=True)
STATIC = Path(__file__).resolve().parent / "static"
RUN_ID_RE = re.compile(r"^ui_[0-9A-Za-z_-]{8,80}$")
STAGE_ORDER = ("popgen", "egene", "bridge", "gdgpt", "atheromap", "delivery")
SELECTABLE_STAGES = ("popgen", "egene", "gdgpt", "atheromap")
START_STAGE_FOR_INPUT = {
    "popgen": ("fastq_dir", "vcf"),
    "egene": ("popgen_pack",),
    "gdgpt": ("egene_report",),
    "atheromap": ("gdgpt_manifest",),
}
STAGE_LABELS = {
    "popgen": "PopGen：FASTQ → VCF",
    "egene": "e-Gene：注释、ACMG 与疾病候选",
    "bridge": "结果适配：生成 GDgpt 输入",
    "gdgpt": "GDgpt：机制分析",
    "atheromap": "AtheroMap：参考分析",
    "delivery": "统一交付：报告与 ZIP",
}
_processes: dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _tail(path: Path, limit: int = 6000) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _run_dir(run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(404, "任务不存在")
    path = RUNS / run_id
    if not path.is_dir():
        raise HTTPException(404, "任务不存在")
    return path


def _first_json(outdir: Path, *relative: str) -> dict:
    for name in relative:
        value = _read_json(outdir / name)
        if value:
            return value
    return {}


def _result_previews(outdir: Path) -> dict:
    """Return small, stable previews while large result files are still writing."""
    pack = _first_json(outdir, "01_popgen/delivery/evidence_pack.json")
    report = _first_json(outdir, "02_egene/delivery/report.json")
    gdgpt = _first_json(outdir, "04_gdgpt/report.json")
    gdgpt_manifest = _first_json(outdir, "04_gdgpt/gdgpt_manifest.json")
    gdgpt_input = _first_json(outdir, "04_gdgpt/gdgpt_input.json")
    bridge = _first_json(outdir, "03_gdgpt_input/input_manifest.json")
    atheromap = _first_json(outdir, "05_atheromap/report.json")
    unified = _first_json(outdir, "delivery/pipeline_report.json")
    popgen = {}
    if pack:
        meta = pack.get("metadata") or {}
        ancestry = pack.get("ancestry") or {}
        popgen = {
            "sample_id": meta.get("sample_id"),
            "variant_count": meta.get("variant_count"),
            "ancestry": ancestry.get("analysis_based") or ancestry.get("gnn_based") or ancestry,
        }
    egene = {}
    if report:
        conclusion = report.get("conclusion") or {}
        stats = report.get("variant_statistics") or {}
        diseases = report.get("disease_statistics") or {}
        egene = {
            "finding": conclusion.get("finding"),
            "counts": stats.get("counts"),
            "candidate_diseases": diseases.get("distinct_candidate_diseases"),
            "candidate_pairs": diseases.get("candidate_disease_gene_pairs"),
        }
    gdgpt_preview = {}
    if gdgpt:
        gdgpt_preview = {
            "analysis_status": gdgpt.get("analysis_status"),
            "summary": gdgpt.get("summary"),
            "task_count": len(gdgpt.get("task_results") or []),
            "task_total": len(gdgpt_input.get("tasks") or []),
        }
    elif gdgpt_manifest:
        completed = sum(1 for item in (gdgpt_manifest.get("tasks") or {}).values()
                        if item.get("status") == "complete")
        gdgpt_preview = {"analysis_status": gdgpt_manifest.get("status"),
                         "task_count": completed,
                         "task_total": len(gdgpt_input.get("tasks") or []) or len(gdgpt_manifest.get("tasks") or {})}
    return {"popgen": popgen, "egene": egene, "bridge": {
        "sample_id": bridge.get("sample_id"), "task_count": bridge.get("task_count"),
    }, "gdgpt": gdgpt_preview, "atheromap": {
        "status": atheromap.get("status"), "sample_id": atheromap.get("sample_id"),
        "scdrs": atheromap.get("scdrs", {}).get("status"),
        "gsmap_samples": len(atheromap.get("gsmap", {}).get("samples", [])),
    }, "unified": {
        "status": unified.get("gdgpt_analysis_status"),
        "sample_id": unified.get("sample_id"),
        "report": "delivery/index.html" if unified else None,
    }}


def _stage_artifacts(run_id: str, outdir: Path, recorded: dict, status_by_stage: dict[str, str] | None = None) -> list[dict]:
    """Expose only files inside this run so completed stages are immediately usable."""
    result = []
    status_by_stage = status_by_stage or {}
    items = dict(recorded)
    # A stage writes into a stable directory before its final manifest is
    # published. Include that directory so task-level files are visible while
    # the stage is still running.
    roots = {"popgen": "01_popgen", "egene": "02_egene", "bridge": "03_gdgpt_input",
             "gdgpt": "04_gdgpt", "atheromap": "05_atheromap", "delivery": "delivery"}
    for stage, relative_root in roots.items():
        if stage not in items and (outdir / relative_root).is_dir():
            items[stage] = {"status": status_by_stage.get(stage, "running"),
                            "artifact": {"path": str(outdir / relative_root)}}
    for stage, item in items.items():
        artifact = item.get("artifact") or {}
        raw_path = artifact.get("path")
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        entry = {"stage": stage, "status": item.get("status") or status_by_stage.get(stage, "pending"), "path": str(path),
                 "bytes": artifact.get("bytes"), "sha256": artifact.get("sha256"), "files": []}
        try:
            relative = path.relative_to(outdir.resolve())
        except ValueError:
            result.append(entry)
            continue
        if path.is_file():
            entry["artifact_url"] = f"/api/runs/{run_id}/artifacts?path={relative.as_posix()}"
        # A manifest is often completed before its report index; list the current
        # directory so the browser can show each newly written artifact on SSE.
        root = path if path.is_dir() else path.parent
        if root.is_dir():
            for current_root, _directories, filenames in os.walk(root):
                for filename in sorted(filenames):
                    child = Path(current_root) / filename
                    rel = child.relative_to(outdir).as_posix()
                    entry["files"].append({"path": rel,
                                           "url": f"/api/runs/{run_id}/artifacts?path={rel}"})
                    if len(entry["files"]) >= 80:
                        break
                if len(entry["files"]) >= 80:
                    break
        result.append(entry)
    return result


def snapshot(run_id: str) -> dict:
    directory = _run_dir(run_id)
    request_state = _read_json(directory / "ui_state.json")
    outdir = Path(request_state.get("output_dir") or directory)
    manifest = _read_json(outdir / "pipeline_manifest.json")
    status_file = _read_json(outdir / "status.json")
    # Keep compatibility with an early UI run that used one directory for both.
    if not manifest and not status_file:
        manifest = _read_json(directory / "pipeline_manifest.json")
        status_file = _read_json(directory / "status.json")
        outdir = directory
    commands = {item.get("stage"): item for item in manifest.get("commands", [])}
    recorded = manifest.get("stages") or {}
    failed = manifest.get("failed_stage")
    stages = []
    for name in STAGE_ORDER:
        if name == "delivery":
            state = "complete" if (outdir / "delivery/index.html").is_file() else ("running" if status_file.get("active_stage") == name else "pending")
        elif name in recorded and recorded[name].get("status") == "complete":
            state = "complete"
        else:
            state = (commands.get(name) or {}).get("status", "pending")
        if failed == name or (status_file.get("status") == "failed" and status_file.get("active_stage") == name):
            state = "failed"
        stages.append({
            "name": name,
            "label": STAGE_LABELS[name],
            "status": state,
            "started_at": (commands.get(name) or {}).get("started_at"),
            "finished_at": (commands.get(name) or {}).get("finished_at"),
        })
    status = status_file.get("status") or manifest.get("status") or request_state.get("status", "queued")
    if status == "running" and not manifest and request_state.get("status") == "failed":
        status = "failed"
    ui_log_tail = _tail(directory / "ui.log")
    active = status_file.get("active_stage")
    stage_log_tail = _tail(outdir / "logs" / f"{active}.log") if active else ""
    log_tail = stage_log_tail or ui_log_tail
    return {
        "run_id": run_id,
        "status": status,
        "active_stage": status_file.get("active_stage") or manifest.get("failed_stage"),
        "sample_id": status_file.get("sample_id") or manifest.get("sample_id"),
        "error": status_file.get("error") or manifest.get("error") or request_state.get("error"),
        "started_at": manifest.get("started_at") or request_state.get("started_at"),
        "finished_at": manifest.get("finished_at") or request_state.get("finished_at"),
        "stages": stages,
        "results": _result_previews(outdir),
        "artifacts": _stage_artifacts(run_id, outdir, recorded,
                                       {item["name"]: item["status"] for item in stages}),
        "requested_end_stage": manifest.get("requested_end_stage") or request_state.get("request", {}).get("end_stage"),
        "log_tail": log_tail,
        "report_url": f"/api/runs/{run_id}/report" if (outdir / "delivery/index.html").is_file() else None,
        "request": request_state.get("request", {}),
    }


def _run_job(run_id: str, command: list[str], directory: Path, state: dict) -> None:
    log_path = directory / "ui.log"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                       env=dict(os.environ, PYTHONUNBUFFERED="1"), start_new_session=True)
            with _process_lock:
                _processes[run_id] = process
            code = process.wait()
        state.update(status="complete" if code == 0 else "failed", returncode=code,
                     finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if code:
            state["error"] = f"统一流水线退出码 {code}"
    except Exception as error:  # pragma: no cover - defensive worker boundary
        state.update(status="failed", error=str(error))
    finally:
        with _process_lock:
            _processes.pop(run_id, None)
        _write_json(directory / "ui_state.json", state)


def _path_value(payload: dict, key: str, label: str, *, directory: bool = False) -> Path:
    path = Path(str(payload.get(key, ""))).expanduser().resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        raise HTTPException(400, f"{label}不存在: {path}")
    return path


def _validate_request(payload: dict) -> dict:
    start_stage = str(payload.get("start_stage", "popgen"))
    # Keep API callers that predate range selection on the former three-stage
    # behavior; the browser always sends an explicit end_stage.
    requested_end = payload.get("end_stage")
    end_stage = str(requested_end if requested_end is not None else ("atheromap" if payload.get("with_atheromap") else "gdgpt"))
    if start_stage not in SELECTABLE_STAGES or end_stage not in SELECTABLE_STAGES:
        raise HTTPException(400, "开始和结束步骤必须是 popgen、egene、gdgpt 或 atheromap")
    if SELECTABLE_STAGES.index(start_stage) > SELECTABLE_STAGES.index(end_stage):
        raise HTTPException(400, "结束步骤不能早于开始步骤")
    input_type = str(payload.get("input_type") or START_STAGE_FOR_INPUT[start_stage][0])
    if input_type not in START_STAGE_FOR_INPUT[start_stage]:
        raise HTTPException(400, f"{start_stage} 不支持输入类型 {input_type}")

    source = None
    reference_default = ROOT / "1_popgen/data/reference/GRCh38.fa"
    reference = Path(str(payload.get("reference") or reference_default)).expanduser().resolve()
    if start_stage == "popgen":
        if input_type == "fastq_dir":
            source = _path_value(payload, "fastq_dir", "FASTQ 目录", directory=True)
            reads = sorted(source.glob("*_R[12].fastq.gz")) + sorted(source.glob("*_R[12].fq.gz"))
            if not reads:
                raise HTTPException(400, "FASTQ 目录中没有 *_R1/_R2.fastq.gz 配对文件")
        else:
            source = _path_value(payload, "vcf", "VCF 文件")
        if not reference.is_file():
            raise HTTPException(400, f"参考 FASTA不存在: {reference}")
    else:
        source = _path_value(payload, "input_path", {
            "egene": "PopGen evidence pack", "gdgpt": "e-Gene report manifest",
            "atheromap": "GDgpt manifest",
        }[start_stage])

    def positive_int(key: str, default: int, maximum: int | None = None) -> int:
        try:
            value = int(payload.get(key, default))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{key} 必须是整数")
        if value < 1 or (maximum is not None and value > maximum):
            raise HTTPException(400, f"{key} 超出有效范围")
        return value

    threads = positive_int("threads", 4, 64)
    max_rounds = positive_int("max_rounds", 6, 6)
    task_timeout = positive_int("task_timeout", 3600)
    prompt_variants = positive_int("prompt_variants", 20)
    atheromap_timeout = positive_int("atheromap_timeout", 7200)
    ref_mismatch = str(payload.get("ref_mismatch", "error"))
    if ref_mismatch not in ("error", "exclude"):
        raise HTTPException(400, "REF 不一致处理方式必须是 error 或 exclude")
    atheromap_reference = Path(str(payload.get("atheromap_reference") or ROOT / "4_atheromap/config/GSE159677_scdrs.reference.json")).expanduser().resolve()
    atheromap_gsmap_root = Path(str(payload.get("atheromap_gsmap_root") or ROOT / "4_atheromap_data/GSE241346_gsMap")).expanduser().resolve()
    if end_stage == "atheromap":
        if not atheromap_reference.is_file():
            raise HTTPException(400, f"AtheroMap 参考清单不存在: {atheromap_reference}")
        if not atheromap_gsmap_root.is_dir():
            raise HTTPException(400, f"AtheroMap gsMap 目录不存在: {atheromap_gsmap_root}")
    scope = str(payload.get("atheromap_scope", "reference-context"))
    mode = str(payload.get("atheromap_mode", "reuse"))
    plots = str(payload.get("atheromap_plots", "all"))
    if scope not in ("reference-context", "matched-trait") or mode not in ("reuse", "recompute") or plots not in ("all", "python", "none"):
        raise HTTPException(400, "AtheroMap 参数无效")
    return {"start_stage": start_stage, "end_stage": end_stage, "input_type": input_type,
            "source": source, "reference": reference, "threads": threads,
            "skip_cv": bool(payload.get("skip_cv")), "skip_gnn": bool(payload.get("skip_gnn")),
            "max_rounds": max_rounds, "task_timeout": task_timeout, "prompt_variants": prompt_variants,
            "ref_mismatch": ref_mismatch,
            "gene": [str(g).strip() for g in (payload.get("gene") or []) if str(g).strip()],
            "max_candidates": payload.get("max_candidates"), "atheromap_reference": atheromap_reference,
            "atheromap_gsmap_root": atheromap_gsmap_root, "atheromap_scope": scope,
            "atheromap_mode": mode, "atheromap_plots": plots, "atheromap_timeout": atheromap_timeout}


def _command_for(request: dict, output_dir: Path) -> list[str]:
    command = [sys.executable, str(ROOT / "run_pipeline.py")]
    if request["start_stage"] == "popgen":
        command += ["--" + request["input_type"].replace("_", "-"), str(request["source"]), "--reference", str(request["reference"])]
    else:
        command += ["--" + request["input_type"].replace("_", "-"), str(request["source"])]
    command += ["--outdir", str(output_dir), "--threads", str(request["threads"]), "--end-stage", request["end_stage"]]
    if (SELECTABLE_STAGES.index(request["start_stage"]) <= SELECTABLE_STAGES.index("egene")
            and SELECTABLE_STAGES.index(request["end_stage"]) >= SELECTABLE_STAGES.index("egene")):
        command += ["--ref-mismatch", request["ref_mismatch"]]
    if request["skip_cv"]:
        command.append("--skip-cv")
    if request["skip_gnn"]:
        command.append("--skip-gnn")
    for gene in request["gene"]:
        command += ["--gene", gene]
    if request["max_candidates"] not in (None, ""):
        try:
            if int(request["max_candidates"]) < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(400, "max_candidates 必须是正整数")
        command += ["--max-candidates", str(int(request["max_candidates"]))]
    if request["start_stage"] in ("gdgpt", "atheromap") or SELECTABLE_STAGES.index(request["end_stage"]) >= SELECTABLE_STAGES.index("gdgpt"):
        command += ["--max-rounds", str(request["max_rounds"]), "--task-timeout", str(request["task_timeout"]),
                    "--prompt-variants", str(request["prompt_variants"])]
    if request["end_stage"] == "atheromap":
        command += ["--with-atheromap", "--atheromap-reference", str(request["atheromap_reference"]),
                    "--atheromap-gsmap-root", str(request["atheromap_gsmap_root"]),
                    "--atheromap-scope", request["atheromap_scope"], "--atheromap-mode", request["atheromap_mode"],
                    "--atheromap-plots", request["atheromap_plots"], "--atheromap-timeout", str(request["atheromap_timeout"])]
    return command


async def index(request: Request) -> FileResponse:
    return FileResponse(STATIC / "index.html")


async def create_run(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "请求必须是 JSON 对象")
    if not isinstance(payload, dict):
        raise HTTPException(400, "请求必须是 JSON 对象")
    validated = _validate_request(payload)
    run_id = "ui_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:8]
    directory = RUNS / run_id
    directory.mkdir()
    output_dir = directory / "output"
    command = _command_for(validated, output_dir)
    request_record = {key: (str(value) if isinstance(value, Path) else value)
                      for key, value in validated.items() if key not in {"source"}}
    request_record["input_path"] = str(validated["source"])
    state = {"run_id": run_id, "status": "queued", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "output_dir": str(output_dir), "request": request_record, "command": command}
    _write_json(directory / "ui_state.json", state)
    thread = threading.Thread(target=_run_job, args=(run_id, command, directory, state), daemon=True)
    thread.start()
    return JSONResponse({"run_id": run_id, "status": "queued"}, status_code=202)


async def list_runs(request: Request) -> JSONResponse:
    result = []
    for path in sorted(RUNS.glob("ui_*/ui_state.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            result.append(snapshot(path.parent.name))
        except HTTPException:
            continue
    return JSONResponse(result)


async def get_run(request: Request) -> JSONResponse:
    return JSONResponse(snapshot(request.path_params["run_id"]))


async def events(request: Request) -> StreamingResponse:
    run_id = request.path_params["run_id"]
    _run_dir(run_id)

    def stream():
        last = ""
        while True:
            current = snapshot(run_id)
            encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
            if encoded != last:
                yield f"event: progress\ndata: {encoded}\n\n"
                last = encoded
            if current["status"] in {"complete", "failed"}:
                yield "event: end\ndata: {}\n\n"
                break
            time.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def stop_run(request: Request) -> JSONResponse:
    run_id = request.path_params["run_id"]
    _run_dir(run_id)
    with _process_lock:
        process = _processes.get(run_id)
    if process is None or process.poll() is not None:
        return JSONResponse(snapshot(run_id))
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    return JSONResponse({"run_id": run_id, "status": "stopping"})


async def report(request: Request) -> FileResponse:
    run_id = request.path_params["run_id"]
    directory = _run_dir(run_id)
    state = _read_json(directory / "ui_state.json")
    path = Path(state.get("output_dir") or directory) / "delivery/index.html"
    if not path.is_file():
        raise HTTPException(404, "报告尚未生成")
    return FileResponse(path)


async def artifact(request: Request) -> FileResponse:
    """Serve a run-local artifact after validating it cannot escape output_dir."""
    run_id = request.path_params["run_id"]
    directory = _run_dir(run_id)
    state = _read_json(directory / "ui_state.json")
    outdir = Path(state.get("output_dir") or directory).resolve()
    relative = request.query_params.get("path", "")
    if not relative or Path(relative).is_absolute():
        raise HTTPException(404, "产物不存在")
    path = (outdir / relative).resolve()
    if not path.is_relative_to(outdir) or not path.is_file():
        raise HTTPException(404, "产物不存在")
    return FileResponse(path)


app = Starlette(routes=[
    Route("/", index, methods=["GET"]),
    Mount("/static", app=StaticFiles(directory=STATIC), name="static"),
    Route("/api/runs", create_run, methods=["POST"]),
    Route("/api/runs", list_runs, methods=["GET"]),
    Route("/api/runs/{run_id}", get_run, methods=["GET"]),
    Route("/api/runs/{run_id}/events", events, methods=["GET"]),
    Route("/api/runs/{run_id}/stop", stop_run, methods=["POST"]),
    Route("/api/runs/{run_id}/report", report, methods=["GET"]),
    Route("/api/runs/{run_id}/artifacts", artifact, methods=["GET"]),
])

