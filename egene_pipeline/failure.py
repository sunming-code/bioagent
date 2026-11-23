"""Publish a short offline report when an integrated run fails."""
from html import escape
import json
import re

from .common import now

REPORT = "error_report.html"
LABELS = {"startup": "启动与输入检查", "popgen": "PopGen", "egene": "e-Gene",
          "bridge": "e-Gene 到 GDgpt 的输入转换", "gdgpt": "GDgpt",
          "atheromap": "AtheroMap", "delivery": "统一交付"}


def _metadata(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def log_reason(path):
    if not path.is_file():
        return ""
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 12000))
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        if re.match(r"^(?:[\w.]+(?:Error|Exception)|Error|错误|统一流水线失败)[:：]", line):
            if "returned non-zero exit status" not in line and "步骤退出码" not in line:
                return line[:800]
    return ""


def publish_failure(outdir, stage, error, stages=None, sample_id=None):
    stage = stage or "startup"
    step = None
    cause = str(error).strip() or type(error).__name__
    rel_log = f"logs/{stage}.log" if stage in LABELS else None
    log = outdir / rel_log if rel_log else None
    if log and log.is_file():
        if "步骤退出码" in cause or "流水线退出码" in cause:
            cause = log_reason(log) or cause
    else:
        rel_log = None

    if stage == "popgen":
        records = _metadata(outdir / "01_popgen/timing.json").get("stages", [])
        failed = next((item for item in reversed(records) if item.get("status") == "failed"), {})
        step = failed.get("name")
    elif stage == "egene":
        folder = outdir / "02_egene"
        parent = _metadata(folder / "status.json")
        step = parent.get("failed_stage")
        for child in folder.glob("*/status.json"):
            data = _metadata(child)
            if data.get("status") == "failed" and data.get("stage") == step and data.get("error"):
                cause = data["error"]
                break
    elif stage in ("gdgpt", "atheromap"):
        folder = "04_gdgpt" if stage == "gdgpt" else "05_atheromap"
        status = _metadata(outdir / folder / "status.json")
        step = status.get("failed_task") or status.get("task") or status.get("active_step")
        if stage == "atheromap" and not step:
            steps = _metadata(outdir / folder / "atheromap_manifest.json").get("steps", [])
            step = next((s.get("name") for s in reversed(steps) if s.get("status") == "failed"), None)
        if status.get("status") == "failed" and status.get("error"):
            cause = status["error"]

    summary = {"stage": stage, "step": step, "sample_id": sample_id, "reason": str(cause)[:1000], "time": now(), "log": rel_log,
               "completed": [k for k,v in (stages or {}).items() if k != stage and v.get("status") == "complete"]}
    where = LABELS.get(stage, stage) + (f" / {step}" if step else "")
    completed = "、".join(LABELS.get(k,k) for k in summary["completed"]) or "无"
    sample = f'<p>样本　{escape(str(sample_id))}</p>' if sample_id else ""
    link = f'<p><a href="{rel_log}">查看本阶段完整日志</a></p>' if rel_log else ""
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>运行错误报告</title><main style="max-width:800px;margin:3em auto;padding:0 1em;font:16px/1.7 system-ui;overflow-wrap:anywhere">'
            f'<h1>运行错误报告</h1><h2>{escape(where)}</h2><p>{escape(summary["reason"])}</p>'
            f'{sample}<p>已完成阶段　{escape(completed)}</p><p>记录时间　{escape(summary["time"])}</p>{link}</main></html>')
    tmp = outdir / (REPORT + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(outdir / REPORT)
    return summary
