"""PopGen Agent 结果可视化（只读已完成任务，不重跑步骤 1/2/3）。"""
from __future__ import annotations

import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
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


@lru_cache(maxsize=1)
def build_dashboard() -> dict:
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
    unsup_path = RESULTS / "admixture_unsupervised_K9.tsv"
    if unsup_path.exists():
        u = pd.read_csv(unsup_path, sep="\t")
        unsup = u.iloc[0].to_dict()
        unsup = {k: (float(v) if k.startswith("C") else v) for k, v in unsup.items()}

    based = (pack.get("ancestry") or {}).get("analysis_based") or {}
    gnn_based = (pack.get("ancestry") or {}).get("gnn_based") or gnn.get("ancestry")
    return {
        "sample": {
            "id": (pack.get("metadata") or {}).get("sample_id", "patient"),
            "alias": (pack.get("metadata") or {}).get("sample_alias", "HG002"),
            "genome_build": "GRCh38",
            "mode": (pack.get("metadata") or {}).get("mode"),
            "variant_count": (pack.get("metadata") or {}).get("variant_count"),
            "vcf": str(RESULTS / "patient.vcf.gz"),
        },
        "upload": _upload_state,
        "steps": {
            "1": {
                "title": "预处理 FASTQ → VCF",
                "env": "popgen",
                "status": "done",
                "stats": stats,
                "concordance": {
                    "precision_all": 0.890,
                    "precision_snp": 0.897,
                    "precision_indel": 0.822,
                    "recall_all": 0.181,
                    "tp": 705791,
                    "fp": 87146,
                    "fn": 3184708,
                    "note": "输入为外显子，truth 为全基因组，recall 会被撑低。主指标是 precision。",
                },
            },
            "2": {
                "title": "群体分析 PCA / ADMIXTURE / 频率",
                "env": "popgen_analysis",
                "status": "done",
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


@app.get("/api/dashboard")
def dashboard() -> dict:
    data = build_dashboard()
    data["upload"] = _upload_state
    return data


@app.post("/api/upload-vcf")
async def upload_vcf(file: UploadFile = File(...)) -> dict:
    name = file.filename or "patient.vcf"
    if not (name.endswith(".vcf") or name.endswith(".vcf.gz")):
        raise HTTPException(400, "只接受 .vcf 或 .vcf.gz")
    dest = UPLOADS / Path(name).name
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 800 * 1024 * 1024:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "VCF 超过 800MB")
            out.write(chunk)
    _upload_state.update({"filename": dest.name, "size": size, "bound": True})
    payload = dashboard()
    payload["message"] = (
        f"已接收 {dest.name}（{size/1e6:.1f} MB）。"
        "本界面绑定的是服务器上已完成的 HG002 步骤 1/2/3 结果，不会重跑分析。"
    )
    return payload


@app.get("/api/download/{key}")
def download(key: str):
    path = DOWNLOADS.get(key)
    if not path or not path.exists():
        raise HTTPException(404, f"没有文件: {key}")
    return FileResponse(path, filename=path.name)


@app.get("/api/download-zip")
def download_zip(kind: str = "delivery"):
    buf = io.BytesIO()
    if kind == "delivery":
        names = ["evidence_pack", "interface", "allele_freq"]
        zip_name = "popgen_e-gene_delivery.zip"
    else:
        names = list(DOWNLOADS)
        zip_name = "popgen_all_results.zip"
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for key in names:
            path = DOWNLOADS[key]
            if path.exists():
                zf.write(path, arcname=path.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
