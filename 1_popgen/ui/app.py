"""Upload, run, inspect and download isolated PopGen analysis jobs."""
from __future__ import annotations

import json
import zipfile
import os
import uuid
import threading
import subprocess
import signal
from datetime import datetime, timezone

from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
JOBS = RESULTS / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
_JOB_LOCK = threading.Lock()
_CHILDREN: dict[str, subprocess.Popen] = {}
_CHILDREN_LOCK = threading.Lock()
from runtime import environment_prefix, command_env
DELIVERY = RESULTS / "delivery"
STATIC = Path(__file__).resolve().parent / "static"
UPLOADS = Path(__file__).resolve().parent / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

SUPERPOP_ORDER = ["AFR", "EUR", "EAS", "SAS", "AMR"]
DOWNLOADS = {
    "evidence_pack": DELIVERY / "evidence_pack.json",
    "interface": DELIVERY / "INTERFACE.md",
    "allele_freq": DELIVERY / "allele_freq.tsv",
    "gnn_decision": RESULTS / "gnn_decision.json",
    "partial_evidence": RESULTS / "partial_evidence.json",
    "ancestry_pca": RESULTS / "ancestry_pca.tsv",
    "admixture_k5": RESULTS / "admixture_results_K5.tsv",
    "admixture_cv": RESULTS / "admixture_cv.tsv",
    "admixture_unsupervised": RESULTS / "admixture_unsupervised_K9.tsv",
    "loo_summary": RESULTS / "loo/summary.tsv",
    "gnn_cv": RESULTS / "gnn/cv_metrics.json",
    "concordance": RESULTS / "concordance/summary.md",
    "patient_vcf": RESULTS / "patient.vcf.gz",
    "patient_stats": RESULTS / "patient.bcftools_stats.txt",
}

app = FastAPI(title="PopGen Agent UI", version="0.1")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_upload_state: dict = {"filename": None, "size": None, "bound": False}


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _file_info(path: Path) -> dict | None:
    if not path.exists():
        return None
    return {"name": path.name, "bytes": path.stat().st_size, "exists": True}


def _pca_scatter(path: Path, per_group: int = 70) -> dict:
    df = pd.read_csv(path, sep="\t")
    pts = []
    for sp in SUPERPOP_ORDER:
        sub = df[df["SUPERPOP"] == sp]
        if len(sub) > per_group:
            sub = sub.sample(per_group, random_state=42)
        for _, row in sub.iterrows():
            pts.append(
                {
                    "iid": str(row["IID"]),
                    "superpop": sp,
                    "pc1": float(row["PC1"]),
                    "pc2": float(row["PC2"]),
                    "kind": "ref",
                }
            )
    pat = df[df["SUPERPOP"] == "PATIENT"]
    if pat.empty:
        pat = df[df["IID"].astype(str).str.lower() == "patient"]
    for _, row in pat.iterrows():
        pts.append(
            {
                "iid": str(row["IID"]),
                "superpop": "PATIENT",
                "pc1": float(row["PC1"]),
                "pc2": float(row["PC2"]),
                "kind": "patient",
            }
        )
    return {"points": pts, "n_total": int(len(df))}


def _af_preview(path: Path, n_preview: int = 25, n_hist: int = 40000) -> dict:
    if not path.exists():
        return {"rows": [], "hist": [], "n_rows": 0}
    preview = pd.read_csv(path, sep="\t", nrows=n_preview)
    total = 0
    with path.open() as fh:
        next(fh, None)
        for total, _ in enumerate(fh, start=1):
            pass
    hist_src = pd.read_csv(path, sep="\t", usecols=["matched_pop_AF"], nrows=n_hist)
    vals = pd.to_numeric(hist_src["matched_pop_AF"], errors="coerce").dropna()
    bins = [0, 0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.01]
    labels = ["<0.1%", "0.1–1%", "1–5%", "5–10%", "10–25%", "25–50%", "≥50%"]
    cats = pd.cut(vals, bins=bins, labels=labels, right=False)
    hist = [{"bin": str(k), "n": int(v)} for k, v in cats.value_counts().sort_index().items()]
    rows = preview.fillna("").to_dict(orient="records")
    return {"rows": rows, "hist": hist, "n_rows": total, "hist_sample": int(len(vals))}


def build_dashboard(results: Path = RESULTS, job_id: str | None = None) -> dict:
    RESULTS = results
    DELIVERY = results / "delivery"
    DOWNLOADS = download_paths(results)
    pack = _load_json(DELIVERY / "evidence_pack.json")
    gnn = _load_json(RESULTS / "gnn_decision.json")
    partial = _load_json(RESULTS / "partial_evidence.json")
    gnn_cv = _load_json(RESULTS / "gnn/cv_metrics.json")
    stats = {}
    stats_path = RESULTS / "patient.bcftools_stats.txt"
    if stats_path.exists():
        for line in stats_path.read_text().splitlines():
            if line.startswith("SN\t"):
                parts = line.split("\t")
                if len(parts) >= 4:
                    stats[parts[2].rstrip(":")] = parts[3]
            if line.startswith("TSTV\t"):
                parts = line.split("\t")
                if len(parts) >= 5:
                    stats["ts_tv"] = parts[4]

    cv_rows = []
    cv_path = RESULTS / "admixture_cv.tsv"
    if cv_path.exists():
        cv_rows = pd.read_csv(cv_path, sep="\t").to_dict(orient="records")
    loo = []
    loo_path = RESULTS / "loo/summary.tsv"
    if loo_path.exists():
        loo = pd.read_csv(loo_path, sep="\t").to_dict(orient="records")
    unsup = {}
    relative = (pack.get("files") or {}).get("admixture_unsupervised")
    unsup_path = DELIVERY / relative if relative else RESULTS / "missing_unsupervised.tsv"
    if unsup_path.exists():
        u = pd.read_csv(unsup_path, sep="\t")
        unsup = u.iloc[0].to_dict()
        unsup = {k: (float(v) if k.startswith("C") else v) for k, v in unsup.items()}

    based = (pack.get("ancestry") or {}).get("analysis_based") or {}
    gnn_based = (pack.get("ancestry") or {}).get("gnn_based") or gnn.get("ancestry")
    return {
        "job_id": job_id,
        "sample": {
            "id": (pack.get("metadata") or {}).get("sample_id", "patient"),
            "alias": (pack.get("metadata") or {}).get("sample_alias"),
            "genome_build": "GRCh38",
            "mode": (pack.get("metadata") or {}).get("mode"),
            "variant_count": (pack.get("metadata") or {}).get("variant_count"),
            "vcf": str(RESULTS / "patient.vcf.gz"),
        },
        "upload": {},
        "steps": {
            "1": {
                "title": "预处理 FASTQ → VCF",
                "env": "popgen",
                "status": "provided" if (RESULTS / "input_metadata.json").exists() else "missing",
                "stats": stats,
                "concordance": {},
            },
            "2": {
                "title": "群体分析 PCA / ADMIXTURE / 频率",
                "env": "popgen_analysis",
                "status": "done" if partial else "missing",
                "analysis_based": based,
                "admixture_q": based.get("q") or (partial.get("findings") or {}).get("admixture_dominant"),
                "pca_distance": ((partial.get("findings") or {}).get("pca") or {}).get("pc_distance"),
                "admixture_cv": cv_rows,
                "unsupervised": unsup,
                "loo": loo,
            },
            "3": {
                "title": "GNN 祖先决策",
                "env": "popgen_gnn",
                "status": "done" if gnn else "missing",
                "decision": gnn,
                "gnn_based": gnn_based,
                "confidence": (pack.get("ancestry") or {}).get("confidence"),
                "cv": gnn_cv,
            },
        },
        "pack": pack,
        "pca": _pca_scatter(RESULTS / "ancestry_pca.tsv") if (RESULTS / "ancestry_pca.tsv").exists() else {"points": []},
        "af": _af_preview(DELIVERY / "allele_freq.tsv"),
        "files": {k: _file_info(v) for k, v in DOWNLOADS.items()},
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = STATIC / "index.html"
    if not html.exists():
        raise HTTPException(500, "缺少 ui/static/index.html")
    return HTMLResponse(html.read_text(encoding="utf-8"))


def download_paths(results: Path) -> dict[str, Path]:
    delivery = results / "delivery"
    pack = _load_json(delivery / "evidence_pack.json")
    paths = {key: results / path.relative_to(RESULTS) for key, path in DOWNLOADS.items()}
    paths["patient_vcf_index"] = results / "patient.vcf.gz.tbi"
    paths["af_coverage"] = results / "af_coverage.json"
    relative = (pack.get("files") or {}).get("admixture_unsupervised")
    paths.pop("admixture_unsupervised", None)
    if relative:
        paths["admixture_unsupervised"] = delivery / relative
    return paths


def job_directory(job_id: str) -> Path:
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise HTTPException(404, "任务不存在")
    directory = JOBS / job_id
    if not (directory / "job.json").exists():
        raise HTTPException(404, "任务不存在")
    return directory


def write_job(directory: Path, state: dict) -> None:
    tmp = directory / "job.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(directory / "job.json")


def run_job(directory: Path, source: Path, state: dict) -> None:
    try:
        # One analysis at a time per service process; queued jobs remain visible.
        with _JOB_LOCK:
            state.update(status="running", started_at=datetime.now(timezone.utc).isoformat())
            write_job(directory, state)
            env = command_env("popgen_gnn")
            python = environment_prefix("popgen_gnn") / "bin" / "python"
            with (directory / "analysis.log").open("w") as log:
                process = subprocess.Popen([str(python), str(ROOT / "orchestrator.py"), "--vcf", str(source),
                                            "--outdir", str(directory / "output")], cwd=ROOT, env=env,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                with _CHILDREN_LOCK:
                    _CHILDREN[state["job_id"]] = process
                try:
                    code = process.wait()
                finally:
                    with _CHILDREN_LOCK:
                        _CHILDREN.pop(state["job_id"], None)
            if code:
                tail = (directory / "analysis.log").read_text(errors="replace")[-5000:]
                raise RuntimeError(tail)
            state.update(status="completed", finished_at=datetime.now(timezone.utc).isoformat())
            write_job(directory, state)
    except Exception as error:
        state.update(status="failed", error=str(error)[-5000:], finished_at=datetime.now(timezone.utc).isoformat())
        write_job(directory, state)


@app.get("/api/dashboard")
def dashboard(job_id: str | None = None) -> dict:
    if job_id:
        directory = job_directory(job_id)
        state = _load_json(directory / "job.json")
        if state["status"] != "completed":
            raise HTTPException(409, "任务尚未完成，请查看运行状态")
        return build_dashboard(directory / "output", job_id)
    return build_dashboard()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    directory = job_directory(job_id)
    state = _load_json(directory / "job.json")
    log = directory / "analysis.log"
    if log.exists():
        with log.open("rb") as f:
            f.seek(max(0, log.stat().st_size - 6000))
            state["log_tail"] = f.read().decode(errors="replace")
    return state


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return sorted([_load_json(p) for p in JOBS.glob("*/job.json")], key=lambda s: s["created_at"], reverse=True)


@app.post("/api/upload-vcf", status_code=202)
async def upload_vcf(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "patient.vcf").name
    if not (name.endswith(".vcf") or name.endswith(".vcf.gz")):
        raise HTTPException(400, "只接受 .vcf 或 .vcf.gz")
    try:
        environment_prefix("popgen_analysis")
        environment_prefix("popgen_gnn")
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    job_id = uuid.uuid4().hex
    directory = JOBS / job_id
    directory.mkdir()
    source = directory / ("input.vcf.gz" if name.endswith(".gz") else "input.vcf")
    size = 0
    try:
        with source.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > int(os.environ.get("POPGEN_MAX_UPLOAD_BYTES", str(4 * 1024**3))):
                    raise HTTPException(413, "VCF 超过上传大小限制")
                out.write(chunk)
        if not size:
            raise HTTPException(400, "VCF 文件为空")
    except BaseException:
        source.unlink(missing_ok=True)
        directory.rmdir()
        raise
    finally:
        await file.close()
    state = {"job_id": job_id, "filename": name, "bytes": size, "status": "queued",
             "created_at": datetime.now(timezone.utc).isoformat()}
    write_job(directory, state)
    threading.Thread(target=run_job, args=(directory, source, dict(state)), daemon=True).start()
    return state


@app.on_event("startup")
def recover_interrupted_jobs():
    for path in JOBS.glob("*/job.json"):
        state = _load_json(path)
        if state.get("status") in {"queued", "running"}:
            state.update(status="failed", error="服务在任务完成前退出，请重新提交 VCF")
            write_job(path.parent, state)


@app.on_event("shutdown")
def stop_running_jobs():
    with _CHILDREN_LOCK:
        children = list(_CHILDREN.values())
    for process in children:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


@app.get("/api/download/{key}")
def download(key: str, job_id: str | None = None):
    results = job_directory(job_id) / "output" if job_id else RESULTS
    if job_id and _load_json(results.parent / "job.json").get("status") != "completed":
        raise HTTPException(409, "任务尚未完成")
    path = download_paths(results).get(key)
    if not path or not path.is_file():
        raise HTTPException(404, f"没有文件: {key}")
    return FileResponse(path, filename=path.name)


@app.get("/api/download-zip")
def download_zip(kind: str = "delivery", job_id: str | None = None):
    results = job_directory(job_id) / "output" if job_id else RESULTS
    if job_id and _load_json(results.parent / "job.json").get("status") != "completed":
        raise HTTPException(409, "任务尚未完成")
    delivery = results / "delivery"
    pack = _load_json(delivery / "evidence_pack.json")
    if not pack:
        raise HTTPException(404, "尚无可交付的证据包")
    paths = {(delivery / "evidence_pack.json").resolve(), (delivery / "INTERFACE.md").resolve()}
    paths.update((delivery / rel).resolve() for rel in pack.get("files", {}).values() if rel)
    if kind == "all":
        paths.update(p.resolve() for p in download_paths(results).values() if p.is_file())
    archive = results / ("popgen_delivery.zip" if kind == "delivery" else "popgen_all_results.zip")
    temporary = results / (archive.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(paths):
                if not path.is_file():
                    raise HTTPException(409, f"交付文件缺失: {path.name}")
                zf.write(path, arcname=path.resolve().relative_to(results.resolve()))
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return FileResponse(archive, filename=archive.name, media_type="application/zip")
