"""Render an offline PopGen report from delivered evidence, without rerunning analysis."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import csv
from html import escape
import json
import math
from pathlib import Path

if __package__:
    from . import review
else:
    import review

POPS = ("AFR", "EUR", "EAS", "SAS", "AMR")
COLORS = dict(zip(POPS, ("#905c4f", "#765766", "#665e57", "#925e72", "#82653e")))
POP_NAMES = {"AFR": "非洲", "EUR": "欧洲", "EAS": "东亚", "SAS": "南亚", "AMR": "美洲混合祖源"}
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


def population_label(pop):
    return f"{POP_NAMES[pop]}（{pop}）" if pop in POP_NAMES else esc(pop)


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
    bins, total, valid = [0] * len(AF_LABELS), 0, 0
    if not path or not path.is_file():
        return {"bins": bins, "total": None, "valid": 0}
    for row in tsv_rows(path):
        total += 1
        if row.get("matched_pop") != lookup:
            raise ValueError(f"allele_freq.tsv 第 {total} 行的 matched_pop 与查表人群不一致")
        value = number(row.get("matched_pop_AF"))
        if value is not None and 0 <= value <= 1:
            bins[bisect_right(AF_EDGES, value)] += 1
            valid += 1
    return {"bins": bins, "total": total, "valid": valid}


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
            "q": q if reason is None and complete_q else None,
            "neighbors": decision.get("patient_neighbors") if reason is None else None,
            "total": gnn.get("n_snps") or decision.get("n_snps")}


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
    af_name = pack.get("files", {}).get("allele_frequency", pack["allele_frequency"]["path"])
    af_path = pack_path.parent / af_name if af_name else None
    return {"pack": pack, "based": based, "lookup": lookup,
            "q": supervised_q(source_path(pack_path, pack, "admixture_supervised", "../admixture_results_K5.tsv"), meta["sample_id"]),
            "points": points, "second": second, "d1": d1, "d2": d2, "ratio": ratio,
            "gnn": gnn_data(pack["ancestry"], read_json(source_path(pack_path, pack, "gnn_decision", None))),
            "frequency": frequency_data(af_path, lookup), "af_name": af_name,
            "coverage": read_json(source_path(pack_path, pack, "af_coverage", "../af_coverage.json")),
            "downloads": {name: (pack_path.parent / name).is_file() for name in
                          ("evidence_pack.json", af_name, "INTERFACE.md", "../patient.vcf.gz") if name}}


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
        chart += (f'<path d="M {sx(x):.2f} 30 V 285 M 85 {sy(y):.2f} H 720" stroke="var(--line)"/>'
                  f'<text x="{sx(x):.2f}" y="307" text-anchor="middle">{x:.3g}</text>'
                  f'<text x="76" y="{sy(y)+4:.2f}" text-anchor="end">{y:.3g}</text>')
    for point in sorted(points, key=lambda p: p["pop"] == "PATIENT"):
        x, y = sx(point["x"]), sy(point["y"])
        title = f'<title>{esc(point["iid"])} · {esc(point["pop"])} · PC1={point["x"]:.8g}, PC2={point["y"]:.8g}</title>'
        if point["pop"] == "PATIENT":
            chart += (f'<path class="patient-point" d="M {x:.2f} {y-9:.2f} L {x+9:.2f} {y:.2f} L {x:.2f} {y+9:.2f} L {x-9:.2f} {y:.2f} Z" '
                      f'fill="var(--ink)" stroke="white" stroke-width="2">{title}</path>'
                      f'<text x="{x:.2f}" y="{y-14:.2f}" text-anchor="middle" font-weight="bold">本次样本</text>')
        else:
            chart += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{COLORS[point["pop"]]}" opacity=".6">{title}</circle>'
    return chart + '<text x="402" y="339" text-anchor="middle">PC1</text><text transform="translate(22,160) rotate(-90)" text-anchor="middle">PC2</text></svg>'


def bar_chart(series, labels, chart_id, title, probability=False, count_label="等位基因条数"):
    chart = svg_start(title, chart_id, 330)
    maximum = 1 if probability else max(1, max(v for _, values, _ in series for v in values))
    for i in range(5):
        value, y = maximum * i / 4, 260 - 220 * i / 4
        label = f"{value:.0%}" if probability else f"{value:,.0f}"
        chart += f'<path d="M 70 {y} H 740" stroke="var(--line)"/><text x="60" y="{y+4}" text-anchor="end">{label}</text>'
    step = 670 / len(labels)
    width = min(45, step * .72 / len(series))
    for i, label in enumerate(labels):
        center = 70 + step * (i + .5)
        chart += f'<text x="{center:.2f}" y="286" text-anchor="middle" font-size="12">{esc(label)}</text>'
        for j, (name, values, opacity) in enumerate(series):
            value = values[i]
            height = value / maximum * 220
            x = center + (j - len(series) / 2) * width
            color = COLORS.get(label, "#765766")
            chart += (f'<rect x="{x:.2f}" y="{260-height:.2f}" width="{width-2:.2f}" height="{height:.2f}" '
                      f'fill="{color}" fill-opacity="{opacity}"><title>{esc(label)} · {esc(name)}: {value:.8g}</title></rect>')
    return chart + '<text x="70" y="318">' + ("纵轴：比例" if probability else "纵轴："+count_label) + '</text></svg>'


STYLE = (Path(__file__).resolve().parents[1] / "egene_pipeline/report_theme.css").read_text(encoding="utf-8") + """
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.grid section{margin:0}.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(142px,1fr));gap:10px 18px}.facts dt,.note,figcaption{font-size:13px;color:var(--muted)}.facts dd{margin:3px 0;font-weight:600}.facts div{min-width:0}.counts dd{font:24px var(--serif)}
.badge{display:inline-block;background:var(--lilac);color:var(--plum);padding:2px 10px;border-radius:3px}.blocked{background:var(--rose);color:var(--accent)}.callout{border-left:3px solid var(--ochre);padding:8px 12px;background:var(--wash)}
svg{display:block;width:100%;height:auto;font:13px var(--sans)}svg text{fill:var(--ink)}svg text[fill="white"]{fill:white}.legend,nav,.downloads{display:flex;flex-wrap:wrap;gap:8px 18px}.legend{font-size:13px}.legend i{display:inline-block;width:11px;height:11px;margin-right:5px;border-radius:2px}.table-wrap th,.table-wrap td{white-space:nowrap}figure{margin:0}ol{padding-left:22px}ol li{padding:5px 0}
@media(max-width:760px){.grid{grid-template-columns:1fr}.facts{grid-template-columns:repeat(2,minmax(0,1fr))}}@media print{.grid{display:block}.legend i,svg{print-color-adjust:exact}}
#gnn{margin-top:20px}#rules{border-top:1px solid var(--line);padding-top:14px;margin-top:18px}#rules summary{cursor:pointer;font-weight:600}
"""


def ancestry_summary(data):
    based, gnn = data["based"], data["gnn"]
    predicted = gnn["result"].get("predicted")
    pca, dominant = based.get("pca_nearest"), based.get("admixture_dominant")
    summary = f"PCA 最近参考人群为 {esc(pca)}，监督 ADMIXTURE 最大成分为 {esc(dominant)}。"
    if not predicted:
        return summary + f"本次没有 GNN 结论，原因是{esc(gnn['reason'])}。"
    observed, total = gnn["observed"], gnn["total"]
    coverage = f"{observed:,} / {total:,}（{observed / total:.2%}）" if observed is not None and total else esc(observed)
    agreement = (f"三种方法一致支持在本面板内用 {esc(pca)} 作人群频率比较。"
                 if predicted == pca == dominant else
                 f"各方法的结果有分歧，频率比较仍使用 PCA 对应的 {esc(pca)}，使用权限见下方。")
    return (summary + f"GNN 对 {esc(predicted)} 的分类分数为 {esc(gnn['confidence'])}；"
            f"实际观测到的模型位点为 {coverage}。{agreement}分数衡量模型在五个参考组之间的选择，覆盖比例衡量此次实际可用的信息量。")


def neighbor_graph(neighbors):
    if not neighbors:
        return '<p class="note">本次没有保存推理图的样本邻边。</p>'
    chart = svg_start("本次样本在 GNN 输入图中的直接参考邻居", "gnn-neighbors", 380)
    for i, node in enumerate(neighbors):
        angle = 2 * math.pi * i / len(neighbors)
        x, y = 380 + 262 * math.cos(angle), 190 + 148 * math.sin(angle)
        pop = node["superpop"]
        chart += (f'<path d="M380 190 L{x:.1f} {y:.1f}" stroke="#a4b9c3"/>'
                  f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{COLORS.get(pop, "#777")}">'
                  f'<title>{esc(node["iid"])} · {esc(pop)}</title></circle>'
                  f'<text x="{x:.1f}" y="{y-11:.1f}" text-anchor="middle">{esc(node["iid"])}</text>')
    groups = Counter(node["superpop"] for node in neighbors)
    group_counts = "、".join(f"{population_label(pop)} {n} 人" for pop, n in groups.most_common())
    return (chart + '<circle cx="380" cy="190" r="12" fill="#183546"/><text x="400" y="188">本次样本</text></svg>'
            + f'<p>每条线连接一位与样本直接相邻的参考个体，本次共 {len(neighbors)} 人，其中{group_counts}。</p>'
            + legend() + '<p class="note">颜色表示参考人群，节点位置仅用于排布。</p>')


def review_section(data):
    result = data.get("review")
    if result is None:
        return '<section id="review"><h2>位点复核</h2><p>缺少样本 VCF 或频率表。</p></section>'
    counts = result["counts"]
    charts = []
    metrics = {"DP": "变异记录的样本深度 DP", "GQ": "样本基因型质量 GQ", "AB": "杂合等位基因平衡 AB"}
    captions = {"DP": "越靠右的区间，每个位点被测序读段覆盖的次数越多。",
                "GQ": "越靠右的区间，变异检测软件对样本基因型的判断越有把握。",
                "AB": "越接近 0.5，支持参考和替代等位基因的读段数越接近。"}
    for key, title in metrics.items():
        bins = result["hist"][key]
        n = sum(bins)
        total = counts["ab_eligible" if key == "AB" else "carried_records"]
        edges = review.QC_EDGES[key]
        labels = [f"<{edges[0]}"] + [f"{a}–<{b}" for a,b in zip(edges,edges[1:])] + [f"≥{edges[-1]}"]
        chart = bar_chart([(title, bins, 1)], labels, "quality-"+key.lower(), title, count_label="VCF 记录数") if n else '<p class="empty">没有可绘制的有效观测。</p>'
        caption = f'<p>{captions[key]}</p>' if n else ""
        charts.append(f'<div><h3>{title}</h3><p>有效 {n:,} / 适用 {total:,} · 缺失或无效 {total-n:,}</p>{chart}{caption}</div>')
    payload = json.dumps(result["chunks"], separators=(",", ":")).replace("<", r"\u003c")
    policy = data["pack"].get("review_policy") or {}
    integrated = "yes" if result["integrated"] else "no"
    columns = ["位点（GRCh38）", "基因型", "匹配频率 / 全球频率", "稀有度", "测序与基因型质量", "复核说明"]
    if result["integrated"]:
        columns.append("e-Gene 判级记录")
    table_name = review.INTEGRATED_TABLE if result["integrated"] else review.TABLE
    js = Path(__file__).with_name("review_browser.js").read_text(encoding="utf-8")
    return f"""<section id="quality"><h2>测序与基因型质量</h2>
<p>DP 和 GQ 按至少携带一个 ALT 的已判读 VCF 记录统计。DP 为这些位点的测序深度。AB 取双等位二倍体杂合调用的 ALT 深度 / (REF 深度 + ALT 深度)，要求 AD 完整、总数大于零。已标记的多等位拆分记录排除在 AB 之外；历史 VCF 按交付时的等位基因表示统计。</p>
<div class="quality-grid">{''.join(charts)}</div></section>
<section id="review"><h2>携带变异的全基因组稀有度图</h2>
<p>输入 {counts["input_alt"]:,} 个 ALT 记录，其中携带 {counts["carried_alt"]:,}，未携带 {counts["not_carried_alt"]:,}，基因型缺失或不完整 {counts["unknown_gt_alt"]:,}。清单保留所有已判读的携带记录，包括待下游参考序列核验的位点。</p>
<p>每个点对应一个携带的 ALT。纵轴为 −log₁₀(匹配祖源 ALT 频率)，点越高，该 ALT 在 {esc(data["lookup"])} 参考人群中越少见。横轴按染色体排列，各段从 0 延伸到本次最远的携带位点，坐标使用 GRCh38。</p>
<p id="review-baseline" data-total="{counts["carried_alt"]}"></p>
<div class="review-controls"><label>染色体 <select id="review-chrom"><option value="">全部染色体</option></select></label>
<label>显示 <select id="review-mode"><option value="all">全部携带位点</option><option value="above">稀有度高于样本均值</option><option value="low">匹配频率低于阈值</option><option value="zero">参考频率为零</option><option value="unknown">频率未知或无效</option></select></label>
<label>探索阈值（%） <input id="review-limit" type="number" min="0" max="100" step="any" value="{esc(policy.get('af_percent', 1))}"></label>
<label>最低 DP <input id="review-dp" value="{escape(str(policy["min_dp"])) if policy.get("min_dp") is not None else ''}" type="number" min="0" step="1" placeholder="不限"></label>
<label>最低 GQ <input id="review-gq" value="{escape(str(policy["min_gq"])) if policy.get("min_gq") is not None else ''}" type="number" min="0" step="1" placeholder="不限"></label>
<label><input type="checkbox" id="review-keep-missing" {'checked' if policy.get('keep_missing_quality') else ''}>设置质量阈值时保留缺失值</label></div>
<p class="review-legend"><span class="mean-line">全样本稀有度均值</span><span class="cut-line">低频复核阈值</span><span id="review-cut-label"></span></p>
<canvas id="review-plot" tabindex="0" aria-label="携带变异的全基因组稀有度图" aria-describedby="review-hint"></canvas>
<p id="review-hint">点击一个点，下方会显示这个位点的证据。键盘聚焦图后，可用左右方向键选点。</p>
<div id="review-details" class="table-wrap" data-integrated="{integrated}" aria-live="polite" hidden><table><thead><tr>{''.join('<th scope="col">'+t+'</th>' for t in columns)}</tr></thead><tbody id="review-body"></tbody></table></div>
<p class="note">橙色点的正频率低于所选阈值。参考频率为零和频率未知各占一行，两者都不计算稀有度。正阈值的低频筛选包含参考频率明确为零的记录。样本均值在切换染色体或筛选时保持固定。两条线用于描述频率和安排复核，致病性由下游结合其他证据评估。</p>
<div class="review-controls"><span id="review-count" aria-live="polite">正在读取携带位点…</span><button id="review-export" type="button" disabled>导出当前筛选表</button><a id="review-save-all" download href="{table_name}">下载全部位点 TSV.gz</a></div>
<script type="application/json" id="review-fields">{json.dumps(review.FIELDS)}</script><script type="application/json" id="chromosome-data">{payload}</script><script>{js}</script></section>"""


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
    pca_caption = (f'<p>深色菱形代表本次样本。按前三个主成分比较，它与{population_label(data["lookup"])}参考人群的中心最近。</p>'
                   if any(p["pop"] == "PATIENT" for p in data["points"]) else "")
    if q:
        maximum = max(q.values())
        largest = "、".join(population_label(p) for p in POPS if q[p] == maximum)
        admixture = stacked_q(q) + f'<p>色段越长，估计的祖源成分占比越高。本次占比最高的是{largest}（{maximum:.1%}）。</p>' + legend() + table(["超群", "Q", "是否最大档"],
            [(pop, q[pop], "是" if q[pop] == maximum else "否") for pop in POPS], "admixture-table")
    else:
        admixture = '<p class="empty">未查到 admixture_results_K5.tsv 中的本次样本，无法绘制监督 ADMIXTURE。</p>'
    result = gnn["result"]
    gnn_plot = ""
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
            gnn_plot = bar_chart([("ADMIXTURE Q", [q[p] for p in POPS], 1),
                                   ("GNN 概率", [gnn["q"][p] for p in POPS], .35)], list(POPS),
                                  "gnn-chart", "监督 ADMIXTURE Q 与 GNN 概率", True)
            top_score = max(gnn["q"].values())
            top_groups = "、".join(population_label(p) for p in POPS if gnn["q"][p] == top_score)
            gnn_plot += (f'<p>深色柱表示估计的祖源比例，浅色柱表示 GNN 的分类分数，本次模型得分最高的是{top_groups}。</p>')
        else:
            gnn_plot = '<p class="empty">未查到完整的五超群 ADMIXTURE Q 或 GNN 概率，无法绘制比较图。</p>'
    unsupported = coverage.get("unsupported_contigs")
    unsupported_count = len(unsupported) if isinstance(unsupported, list) else None
    counts = facts([("输入等位基因", coverage.get("input_alleles", af["total"])),
                    ("精确匹配", coverage.get("matched_reference_alleles")),
                    ("未查到", coverage.get("unmatched_reference_alleles")),
                    ("无法查询的 contig 数", unsupported_count)])
    contigs = "、".join(unsupported) if unsupported else "无" if unsupported == [] else MISSING
    histogram = (bar_chart([("matched_pop_AF", af["bins"], 1)], list(AF_LABELS), "frequency-chart", "已匹配人群频率分布")
                 if af["valid"] else '<p class="empty">未查到可绘图的 matched_pop_AF；空白不进入图。</p>')
    if af["valid"]:
        histogram += '<p>柱子越高，表示全量频率表中落在该频率区间的等位基因记录越多。</p>'
    links = []
    for name, exists in data["downloads"].items():
        label = escape(Path(name).name)
        if name == data["af_name"]:
            label = f'全量逐位点频率表（{label}）'
        links.append(f'<a href="{escape(name)}" download>{label}</a>' if exists else f'<span>{label}（未提供）</span>')
    shortlist = pack.get("files", {}).get("review_shortlist")
    if shortlist and pack.get("review_policy"):
        n = pack["review_policy"]["selected_alleles"]
        links.append(f'<a href="{escape(shortlist)}" download>运行时复核清单（{esc(n)} 个等位基因）</a>')
    rules = ["只用查表人群对应的 matched_pop_AF；连接键为 CHROM + POS + REF + ALT（GRCh38）。",
             "仅当 analysis_based.use_for_acmg_ba1_bs1 = true 时，才允许用 matched_pop_AF 按下游 SOP 评估 BA1/BS1；false 时频率仅供参考。",
             "assignment=admixed 不等于改去最大 Q 人群；查表人群仍取 PCA 最近档，GNN 也不得更改它。",
             f'无监督最佳 K（本次 {display(pack.get("structure", {}).get("unsupervised_best_k"))}）只描述面板细结构，没有对应的 AF 列。',
             "频率空白表示未查到，不是 0；参考库实际记录的 0 保留为 0。",
             "这一页不是致病变异清单，也不进行患者诊断。"]
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PopGen 报告 · {esc(sample)}</title><style>{STYLE}
.quality-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr));gap:16px}} .review-controls,.review-legend{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}} .review-controls input{{width:6em}} #review-plot{{display:block;width:100%;height:300px;cursor:crosshair}} .mean-line::before,.cut-line::before{{content:"";display:inline-block;width:28px;vertical-align:middle;margin-right:6px;border-top:2px dashed #28557c}} .cut-line::before{{border-color:#b24c16;border-top-style:solid}} #review-details td{{white-space:normal;overflow-wrap:anywhere;vertical-align:top}} #review-details td:first-child{{white-space:nowrap}} #review-details td:nth-child(5){{min-width:220px}} button,select,input{{font:inherit}}</style></head><body><main><div class="folio"><span class="imprint">BioAgent</span><span>POPGEN　/　RESEARCH EDITION</span></div>
<header><div class="eyebrow">POPGEN · POPULATION GENETICS</div><h1>祖源与人群频率报告</h1>{header}</header>
<p class="callout">{ancestry_summary(data)}</p>
<section id="ancestry" class="conclusion"><h2>查表人群与 BA1/BS1 权限</h2><span class="badge {'' if allowed else 'blocked'}">BA1/BS1：{'允许' if allowed else '不允许'}</span>{policy}
<p class="note">查表人群以 PCA 最近档为准。GNN 是补充祖源证据，不修改查表人群或 BA1/BS1 开关。</p></section>
<div class="grid"><section><h2>监督 ADMIXTURE · K=5</h2>{admixture}<p class="note">数据：admixture_results_K5.tsv；五段按 AFR、EUR、EAS、SAS、AMR 排列。</p></section>
<section><h2>PCA · PC1–PC2</h2>{scatter(data['points'])}{pca_caption}{legend()}{pca_note}<p class="note">图中展示前两个主成分，坐标来自 ancestry_pca.tsv。</p></section></div>
<div class="grid" id="gnn"><section><h2>GNN 补充祖源证据</h2>{gnn_plot}{gnn_html}</section><section><h2>样本与参考个体的直接邻边</h2>{neighbor_graph(gnn["neighbors"])}</section></div>
{review_section(data)}
<section id="frequency"><h2>人群频率覆盖</h2><div class="counts">{counts}</div><p class="note">无法查询的 contig：{esc(contigs)}。精确匹配按 CHROM + POS + REF + ALT 统计，来自 af_coverage.json；未查到数包含无法查询的 contig 上的等位基因。</p>
{histogram}<p class="note">全表共 {esc(af['total'])} 条，有效频率 {af['valid']} 条。空白不进入图，实际频率 0 进入首个区间。</p></section>
<section id="downloads"><h2>下载文件</h2><div class="downloads">{''.join(links)}</div>
<details id="rules"><summary>六条使用规则</summary><ol>{''.join(f'<li>{esc(rule)}</li>' for rule in rules)}</ol></details></section>
<footer>本次 PopGen 没有 snpEff、VQSR、捕获区间和 ACMG 分级。ACMG 分级由下游 e-Gene 完成。</footer>
</main></body></html>'''


def generate_report(pack_path, output=None, *, acmg_path=None, review_data=None):
    pack_path = Path(pack_path).resolve(strict=True)
    output = Path(output).resolve() if output else pack_path.parent / "popgen_report.html"
    if output.parent != pack_path.parent:
        raise ValueError("报告必须与 evidence_pack.json 位于同一目录，以保持下载链接有效")
    data = collect_report(pack_path)
    pack = data["pack"]
    vcf = source_path(pack_path, pack, "patient_vcf", "../patient.vcf.gz")
    af = source_path(pack_path, pack, "allele_frequency", pack["allele_frequency"]["path"])
    if review_data is not None:
        data["review"] = review_data
    elif vcf and vcf.is_file() and af and af.is_file():
        data["review"] = review.collect(vcf, pack["metadata"]["sample_id"], af, output.parent, data["lookup"],
                                        data["based"].get("use_for_acmg_ba1_bs1") is True, acmg_path,
                                        af_percent=(pack.get("review_policy") or {}).get("af_percent", 1.0))
    html = render_html(data)
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
