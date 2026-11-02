"""Render an offline PopGen report from delivered evidence, without rerunning analysis."""
from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
from html import escape
import json
import math
from pathlib import Path

POPS = ("AFR", "EUR", "EAS", "SAS", "AMR")
COLORS = dict(zip(POPS, ("#c85a35", "#3978ad", "#29977a", "#9b6fa9", "#d4a12d")))
MISSING = "未查到"
AF_EDGES = (0.001, 0.01, 0.05, 0.1, 0.25, 0.5)
AF_LABELS = ("[0, 0.1%)", "[0.1%, 1%)", "[1%, 5%)", "[5%, 10%)", "[10%, 25%)", "[25%, 50%)", "[50%, 100%]")


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def display(value):
    if value is None or not str(value).strip():
        return MISSING
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".8g") if math.isfinite(value) else MISSING
    return str(value)


def esc(value):
    return escape(display(value), quote=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}


def source_path(pack_path, pack, key, default):
    # A declared null means this analysis was skipped; never reuse a stale file.
    relative = pack.get("files", {}).get(key, default)
    return pack_path.parent / relative if relative else None


def tsv_rows(path):
    if path and path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle, delimiter="\t")


def supervised_q(path, sample_id):
    rows = list(tsv_rows(path))
    selected = [r for r in rows if r.get("Sample") in {"patient", "__POPGEN_PATIENT__", sample_id}]
    row = selected[0] if len(selected) == 1 else rows[0] if len(rows) == 1 else None
    if not row:
        return None
    q = {pop: number(row.get(pop)) for pop in POPS}
    if any(v is None or not 0 <= v <= 1 for v in q.values()) or not math.isclose(sum(q.values()), 1, abs_tol=0.001):
        raise ValueError("admixture_results_K5.tsv 的五个人群 Q 缺失、超出范围或总和不为 1")
    return q


def pca_data(path, sample_id):
    rows = list(tsv_rows(path))
    marked = [r for r in rows if r.get("SUPERPOP") == "PATIENT"
              or r.get("IID") in {"patient", "__POPGEN_PATIENT__"}]
    patients = marked or [r for r in rows if r.get("IID") == sample_id]
    points, groups = [], {pop: [] for pop in POPS}
    patient_ids = {id(r) for r in patients}
    for row in rows:
        coords = [number(row.get(f"PC{i}")) for i in (1, 2, 3)]
        patient = id(row) in patient_ids
        pop = "PATIENT" if patient else row.get("SUPERPOP")
        if coords[0] is not None and coords[1] is not None and (patient or pop in POPS):
            points.append({"iid": row.get("IID"), "pop": pop, "x": coords[0], "y": coords[1]})
        if not patient and pop in groups and all(v is not None for v in coords):
            groups[pop].append(coords)
    distances = {}
    if patients:
        patient_pc = [number(patients[0].get(f"PC{i}")) for i in (1, 2, 3)]
        if all(v is not None for v in patient_pc):
            for pop, values in groups.items():
                if values:
                    center = [sum(p[i] for p in values) / len(values) for i in range(3)]
                    distances[pop] = math.dist(patient_pc, center)
    return points, distances


def frequency_data(path, lookup):
    preview, bins, total, valid = [], [0] * len(AF_LABELS), 0, 0
    if not path or not path.is_file():
        return {"preview": [], "bins": bins, "total": None, "valid": 0}
    for row in tsv_rows(path):
        total += 1
        if row.get("matched_pop") != lookup:
            raise ValueError(f"allele_freq.tsv 第 {total} 行的 matched_pop 与查表人群不一致")
        if len(preview) < 25:
            preview.append([None if key.endswith("AF") and number(row.get(key)) is None else row.get(key)
                            for key in ("CHROM", "POS", "REF", "ALT", "matched_pop_AF", "global_AF")])
        value = number(row.get("matched_pop_AF"))
        if value is not None and 0 <= value <= 1:
            bins[bisect_right(AF_EDGES, value)] += 1
            valid += 1
    return {"preview": preview, "bins": bins, "total": total, "valid": valid}


def gnn_data(ancestry, decision):
    gnn = ancestry.get("gnn_based") or {}
    # n_snps is the checkpoint's feature count, not the observed training-locus overlap.
    observed = gnn.get("n_snps_observed")
    if observed is None:
        observed = decision.get("n_snps_observed")
    observed = number(observed)
    observed = int(observed) if observed is not None else None
    status = decision.get("status")
    if observed is not None and observed < 200:
        reason = "交上的训练位点少于 200"
    elif not gnn or status not in {None, "OK", "ok"}:
        reason = decision.get("reason") or "本次未运行 GNN，或未产生有效结果"
    elif observed is None:
        reason = "未查到本次交上的训练位点数，无法确认达到 200 个位点"
    else:
        reason = None
    q = {pop: number((gnn.get("q") or {}).get(pop)) for pop in POPS}
    complete_q = (all(v is not None and 0 <= v <= 1 for v in q.values())
                  and math.isclose(sum(q.values()), 1, abs_tol=0.001))
    return {"result": gnn if reason is None else {}, "observed": observed, "reason": reason,
            "confidence": ancestry.get("confidence") if ancestry.get("confidence") is not None else gnn.get("qmax"),
            "q": q if reason is None and complete_q else None}


def collect_report(pack_path):
    pack_path = Path(pack_path).resolve(strict=True)
    pack = read_json(pack_path)
    meta = pack["metadata"]
    based = pack["ancestry"]["analysis_based"]
    lookup = based.get("pca_nearest")
    if lookup not in POPS or based.get("af_population") != lookup or pack["allele_frequency"].get("matched_pop") != lookup:
        raise ValueError("查表人群必须等于 PCA 最近档和 allele_frequency.matched_pop")
    partial = read_json(source_path(pack_path, pack, "partial_evidence", "../partial_evidence.json"))
    points, distances = pca_data(source_path(pack_path, pack, "pca", "../ancestry_pca.tsv"), meta["sample_id"])
    recorded = ((partial.get("findings") or {}).get("pca") or {}).get("pc_distance") or {}
    if recorded:
        distances = {k: number(v) for k, v in recorded.items() if k in POPS and number(v) is not None}
    second = next((pop for pop, _ in sorted(distances.items(), key=lambda item: item[1]) if pop != lookup), None)
    d1 = based.get("pca_d_nearest")
    d2 = based.get("pca_d_second")
    ratio = based.get("pca_d_second_over_nearest")
    d1 = d1 if d1 is not None else distances.get(lookup)
    d2 = d2 if d2 is not None else distances.get(second)
    if ratio is None and d1 is not None and d1 > 0 and d2 is not None:
        ratio = d2 / d1
    af_path = source_path(pack_path, pack, "allele_frequency", pack["allele_frequency"]["path"])
    return {"pack": pack, "based": based, "lookup": lookup,
            "q": supervised_q(source_path(pack_path, pack, "admixture_supervised", "../admixture_results_K5.tsv"), meta["sample_id"]),
            "points": points, "second": second, "d1": d1, "d2": d2, "ratio": ratio,
            "gnn": gnn_data(pack["ancestry"], read_json(source_path(pack_path, pack, "gnn_decision", None))),
            "frequency": frequency_data(af_path, lookup),
            "coverage": read_json(source_path(pack_path, pack, "af_coverage", "../af_coverage.json")),
            "downloads": {name: (pack_path.parent / name).is_file() for name in
                          ("evidence_pack.json", "allele_freq.tsv", "INTERFACE.md", "../patient.vcf.gz")}}


def table(headers, rows, table_id):
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in rows)
    return (f'<div class="table-wrap"><table id="{table_id}"><thead><tr>'
            + "".join(f'<th scope="col">{esc(v)}</th>' for v in headers)
            + f"</tr></thead><tbody>{body}</tbody></table></div>")


def facts(rows):
    return '<dl class="facts">' + "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in rows) + "</dl>"


def svg_start(title, chart_id, height=300):
    return (f'<svg id="{chart_id}" viewBox="0 0 760 {height}" role="img" '
            f'aria-labelledby="{chart_id}-title"><title id="{chart_id}-title">{esc(title)}</title>')


def legend():
    return '<div class="legend">' + "".join(f'<span><i style="background:{COLORS[p]}"></i>{p}</span>' for p in POPS) + "</div>"


def stacked_q(q):
    chart = svg_start("监督 ADMIXTURE K=5 祖源比例", "admixture-chart", 105)
    x = 20
    for pop in POPS:
        width = q[pop] / sum(q.values()) * 720
        chart += (f'<rect x="{x:.4f}" y="15" width="{width:.4f}" height="48" fill="{COLORS[pop]}">'
                  f'<title>{pop}: Q={q[pop]:.8g}</title></rect>')
        if width >= 58:
            chart += f'<text x="{x + width / 2:.3f}" y="44" text-anchor="middle" fill="white">{pop} {q[pop]:.1%}</text>'
        x += width
    return chart + '<text x="20" y="92">0%</text><text x="740" y="92" text-anchor="end">100%</text></svg>'


def scatter(points):
    if not points or not any(p["pop"] == "PATIENT" for p in points):
        return '<p class="empty">未查到可标出本次样本的 PCA 数据。</p>'
    chart = svg_start("PC1–PC2：参考面板与本次样本", "pca-chart", 350)
    xmin, xmax = min(p["x"] for p in points), max(p["x"] for p in points)
    ymin, ymax = min(p["y"] for p in points), max(p["y"] for p in points)
    dx, dy = (xmax - xmin) or 0.01, (ymax - ymin) or 0.01
    xmin, xmax, ymin, ymax = xmin - dx * .08, xmax + dx * .08, ymin - dy * .08, ymax + dy * .08
    sx = lambda x: 85 + (x - xmin) / (xmax - xmin) * 635
    sy = lambda y: 285 - (y - ymin) / (ymax - ymin) * 255
    for i in range(5):
        x, y = xmin + (xmax - xmin) * i / 4, ymin + (ymax - ymin) * i / 4
        chart += (f'<path d="M {sx(x):.2f} 30 V 285 M 85 {sy(y):.2f} H 720" stroke="#e4e9ee"/>'
                  f'<text x="{sx(x):.2f}" y="307" text-anchor="middle">{x:.3g}</text>'
                  f'<text x="76" y="{sy(y)+4:.2f}" text-anchor="end">{y:.3g}</text>')
    for point in sorted(points, key=lambda p: p["pop"] == "PATIENT"):
        x, y = sx(point["x"]), sy(point["y"])
        title = f'<title>{esc(point["iid"])} · {esc(point["pop"])} · PC1={point["x"]:.8g}, PC2={point["y"]:.8g}</title>'
        if point["pop"] == "PATIENT":
            chart += (f'<path class="patient-point" d="M {x:.2f} {y-9:.2f} L {x+9:.2f} {y:.2f} L {x:.2f} {y+9:.2f} L {x-9:.2f} {y:.2f} Z" '
                      f'fill="#122a43" stroke="white" stroke-width="2">{title}</path>'
                      f'<text x="{x:.2f}" y="{y-14:.2f}" text-anchor="middle" font-weight="bold">本次样本</text>')
        else:
            chart += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{COLORS[point["pop"]]}" opacity=".6">{title}</circle>'
    return chart + '<text x="402" y="339" text-anchor="middle">PC1</text><text transform="translate(22,160) rotate(-90)" text-anchor="middle">PC2</text></svg>'


def bar_chart(series, labels, chart_id, title, probability=False):
    chart = svg_start(title, chart_id, 330)
    maximum = 1 if probability else max(1, max(v for _, values, _ in series for v in values))
    for i in range(5):
        value, y = maximum * i / 4, 260 - 220 * i / 4
        label = f"{value:.0%}" if probability else f"{value:,.0f}"
        chart += f'<path d="M 70 {y} H 740" stroke="#e4e9ee"/><text x="60" y="{y+4}" text-anchor="end">{label}</text>'
    step = 670 / len(labels)
    width = min(45, step * .72 / len(series))
    for i, label in enumerate(labels):
        center = 70 + step * (i + .5)
        chart += f'<text x="{center:.2f}" y="286" text-anchor="middle" font-size="12">{esc(label)}</text>'
        for j, (name, values, opacity) in enumerate(series):
            value = values[i]
            height = value / maximum * 220
            x = center + (j - len(series) / 2) * width
            color = COLORS.get(label, "#3978ad")
            chart += (f'<rect x="{x:.2f}" y="{260-height:.2f}" width="{width-2:.2f}" height="{height:.2f}" '
                      f'fill="{color}" fill-opacity="{opacity}"><title>{esc(label)} · {esc(name)}: {value:.8g}</title></rect>')
    return chart + '<text x="70" y="318">' + ("纵轴：比例" if probability else "纵轴：等位基因条数") + '</text></svg>'


STYLE = """
:root{color-scheme:light;--ink:#193047;--muted:#627386;--line:#dce5ec;--paper:#fff}
*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:var(--ink);font:15px/1.65 system-ui,-apple-system,'Noto Sans CJK SC',sans-serif}
main{max-width:1180px;margin:auto;padding:36px 28px 56px}header{border-top:5px solid #29977a;padding:24px 0}h1{font-size:32px;margin:4px 0 12px}h2{font-size:21px;margin:0 0 16px}p{margin:10px 0}.eyebrow{color:#247b67;font-weight:650;letter-spacing:2px;font-size:12px}
section{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:24px;margin:20px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.grid section{margin:0}.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin:14px 0}.facts div{min-width:0}.facts dt{color:var(--muted);font-size:13px}.facts dd{margin:4px 0;overflow-wrap:anywhere;font-weight:600}
.badge{display:inline-block;padding:4px 12px;border-radius:20px;background:#e5f3ec;color:#22624b}.blocked{background:#fff0dd;color:#845518}.note,.empty,figcaption{color:var(--muted);font-size:13px}.empty{padding:24px;background:#f5f7f9}.callout{border-left:3px solid #29977a;padding:4px 16px;background:#f5faf8}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{background:#f4f7f9;white-space:nowrap}td:nth-child(n+5){min-width:130px}svg{display:block;width:100%;height:auto;font:13px system-ui,sans-serif}svg text{fill:var(--ink)}svg text[fill="white"]{fill:white}.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;margin:8px 0 16px}.legend span{display:flex;align-items:center;gap:6px}.legend i{display:inline-block;width:10px;height:10px;border-radius:3px}a{color:#246797;text-underline-offset:3px}.downloads{display:flex;flex-wrap:wrap;gap:12px 24px}ol{padding-left:24px}ol li{padding:7px 0}footer{color:var(--muted);border-top:1px solid var(--line);padding-top:20px}figure{margin:0}.counts dd{font-size:26px}nav{display:flex;gap:20px;flex-wrap:wrap}
th,td{white-space:nowrap;overflow-wrap:normal}
@media(max-width:760px){main{padding:20px 14px}section{padding:18px}.grid{grid-template-columns:1fr}h1{font-size:26px}.facts{grid-template-columns:repeat(2,minmax(0,1fr))}}@media print{body{background:white}main{padding:0}section{break-inside:avoid}.grid{display:block}.grid section{margin:18px 0}}
"""


def render_html(data):
    pack, based, q = data["pack"], data["based"], data["q"]
    meta, gnn, af, coverage = pack["metadata"], data["gnn"], data["frequency"], data["coverage"]
    sample = meta.get("sample_alias") or meta["sample_id"]
    allowed = based.get("use_for_acmg_ba1_bs1") is True
    header = facts([("样本名", sample), ("样本 ID", meta["sample_id"]), ("基因组", meta.get("genome_build")),
                    ("变异条数", meta.get("variant_count")), ("参考面板", meta.get("reference_panel")),
                    ("打包时间", pack.get("producer", {}).get("pack_built_at"))])
    policy = facts([("查表人群（PCA 最近档）", data["lookup"]), ("assignment", based.get("assignment")), ("原因", based.get("reason"))])
    pca_note = facts([("最近档", data["lookup"]), ("次近档", data["second"]), ("最近档距离", data["d1"]),
                      ("次近档距离", data["d2"]), ("距离比（次近 / 最近）", data["ratio"])])
    if q:
        maximum = max(q.values())
        admixture = stacked_q(q) + legend() + table(["超群", "Q", "是否最大档"],
            [(pop, q[pop], "是" if q[pop] == maximum else "否") for pop in POPS], "admixture-table")
    else:
        admixture = '<p class="empty">未查到 admixture_results_K5.tsv 中的本次样本，无法绘制监督 ADMIXTURE。</p>'
    result = gnn["result"]
    if gnn["reason"]:
        gnn_html = f'<p class="callout">本次没有 GNN 结论：{esc(gnn["reason"])}。</p>'
        gnn_html += facts([("交上的训练位点数", gnn["observed"]), ("最低要求", 200),
                           ("预测档", "无结论"), ("置信度", None), ("与 PCA3 是否一致", "无结论"),
                           ("usable_for_lookup", False), ("未产生结论的原因", gnn["reason"])])
    else:
        concordant = result.get("concordant_with_pca3")
        discordance = result.get("discordance_reason") or ("无不一致" if concordant is True else None)
        gnn_html = facts([("预测档", result.get("predicted")), ("置信度", gnn["confidence"]),
                          ("PCA3 最近档", result.get("pca3_nearest")), ("与 PCA3 是否一致", concordant),
                          ("usable_for_lookup", result.get("usable_for_lookup")), ("交上的训练位点数", gnn["observed"]),
                          ("不一致原因", discordance)])
        if result.get("note"):
            gnn_html += f'<p class="note">{esc(result["note"])}</p>'
        if q and gnn["q"]:
            gnn_html += bar_chart([("ADMIXTURE Q", [q[p] for p in POPS], 1),
                                   ("GNN 概率", [gnn["q"][p] for p in POPS], .35)], list(POPS),
                                  "gnn-chart", "监督 ADMIXTURE Q 与 GNN 概率", True)
            gnn_html += '<p class="note">每个超群左边为 ADMIXTURE Q，右边浅色为 GNN 概率。</p>'
        else:
            gnn_html += '<p class="empty">未查到完整的五超群 ADMIXTURE Q 或 GNN 概率，无法绘制比较图。</p>'
    unsupported = coverage.get("unsupported_contigs")
    unsupported_count = len(unsupported) if isinstance(unsupported, list) else None
    counts = facts([("输入等位基因", coverage.get("input_alleles", af["total"])),
                    ("精确匹配", coverage.get("matched_reference_alleles")),
                    ("未查到", coverage.get("unmatched_reference_alleles")),
                    ("无法查询的 contig 数", unsupported_count)])
    contigs = "、".join(unsupported) if unsupported else "无" if unsupported == [] else MISSING
    histogram = (bar_chart([("matched_pop_AF", af["bins"], 1)], list(AF_LABELS), "frequency-chart", "已匹配人群频率分布")
                 if af["valid"] else '<p class="empty">未查到可绘图的 matched_pop_AF；空白不进入图。</p>')
    preview = table(["染色体", "位置", "REF", "ALT", "匹配人群频率", "全球频率"], af["preview"], "frequency-preview")
    if not af["preview"]:
        preview += '<p class="empty">未查到可预览的频率记录。</p>'
    links = "".join(f'<a href="{escape(name)}" download>{escape(Path(name).name)}</a>' if exists else
                    f'<span>{escape(Path(name).name)}（未提供）</span>' for name, exists in data["downloads"].items())
    rules = ["只用查表人群对应的 matched_pop_AF；连接键为 CHROM + POS + REF + ALT（GRCh38）。",
             "仅当 analysis_based.use_for_acmg_ba1_bs1 = true 时，才允许用 matched_pop_AF 按下游 SOP 评估 BA1/BS1；false 时频率仅供参考。",
             "assignment=admixed 不等于改去最大 Q 人群；查表人群仍取 PCA 最近档，GNN 也不得更改它。",
             f'无监督最佳 K（本次 {display(pack.get("structure", {}).get("unsupervised_best_k"))}）只描述面板细结构，没有对应的 AF 列。',
             "频率空白表示未查到，不是 0；参考库实际记录的 0 保留为 0。",
             "这一页不是致病变异清单，也不进行患者诊断。"]
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PopGen 报告 · {esc(sample)}</title><style>{STYLE}</style></head><body><main>
<header><div class="eyebrow">POPGEN · POPULATION GENETICS</div><h1>祖源与人群频率报告</h1>{header}
<nav aria-label="报告导航"><a href="#ancestry">祖源与查表策略</a><a href="#frequency">频率结果</a><a href="#rules">六条使用规则</a><a href="#downloads">下载文件</a></nav></header>
<section id="ancestry"><h2>查表人群与 BA1/BS1 权限</h2><span class="badge {'' if allowed else 'blocked'}">BA1/BS1：{'允许' if allowed else '不允许'}</span>{policy}
<p class="note">查表人群以 PCA 最近档为准。GNN 是补充祖源证据，不修改查表人群或 BA1/BS1 开关。</p></section>
<div class="grid"><section><h2>监督 ADMIXTURE · K=5</h2>{admixture}<p class="note">数据：admixture_results_K5.tsv；五段按 AFR、EUR、EAS、SAS、AMR 排列。</p></section>
<section><h2>PCA · PC1–PC2</h2>{scatter(data['points'])}{legend()}{pca_note}<p class="note">深色菱形为本次样本。距离与查表分档基于 PC1–PC3；散点展示 PC1–PC2。数据：ancestry_pca.tsv。</p></section></div>
<section id="gnn"><h2>GNN 补充祖源证据</h2>{gnn_html}</section>
<section id="frequency"><h2>人群频率覆盖</h2><div class="counts">{counts}</div><p class="note">无法查询的 contig：{esc(contigs)}。精确匹配按 CHROM + POS + REF + ALT 统计，来自 af_coverage.json；未查到数包含无法查询的 contig 上的等位基因。</p>
{histogram}<p class="note">全表统计：{esc(af['total'])} 条；有效 matched_pop_AF：{af['valid']} 条。空白不进入图，实际频率 0 进入首个区间。</p>
<h2>频率预览 · 前 25 行</h2>{preview}<p class="note">数据：allele_freq.tsv，保持原始顺序。空白显示为「未查到」。频率为 0–1 的比例。</p></section>
<section id="rules"><h2>六条使用规则</h2><ol>{''.join(f'<li>{esc(rule)}</li>' for rule in rules)}</ol></section>
<section id="downloads"><h2>下载文件</h2><div class="downloads">{links}</div></section>
<footer>本次 PopGen 没有 snpEff、VQSR、捕获区间和 ACMG 分级。ACMG 分级由下游 e-Gene 完成。</footer>
</main></body></html>'''


def generate_report(pack_path, output=None):
    pack_path = Path(pack_path).resolve(strict=True)
    output = Path(output).resolve() if output else pack_path.parent / "popgen_report.html"
    if output.parent != pack_path.parent:
        raise ValueError("报告必须与 evidence_pack.json 位于同一目录，以保持下载链接有效")
    html = render_html(collect_report(pack_path))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="默认为证据包同目录的 popgen_report.html；下载链接相对于该目录")
    args = parser.parse_args()
    print(generate_report(args.evidence_pack, args.output))


if __name__ == "__main__":
    main()
