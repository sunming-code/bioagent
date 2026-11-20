"""GDgpt report renderers: professional (full evidence) and plain-language HTML.

Pure standard library. Input is the dict written to report.json by gdgpt.write_report.
"""
import json
import re
from collections import Counter
from html import escape as esc

COV = {"high": ("高", "#0f9d6e", "图谱证据充分"), "partial": ("中", "#d98a00", "图谱证据部分覆盖"),
       "low": ("低", "#d64545", "图谱证据不足"), "disabled": ("未启用", "#8a94a6", "未使用图谱")}
EDGE = re.compile(r"-\s*(?P<kv>\w+=.*)")
TAGS = {"[KG-supported]": "kg", "[LLM-inferred]": "llm"}

CSS = """
:root{--ink:#1b2437;--mute:#667085;--line:#e4e8f0;--bg:#f5f7fb;--card:#fff;--brand:#1f4fd8;--brand2:#6a3df0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 -apple-system,"PingFang SC","Segoe UI",system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px 60px}
header.hero{background:linear-gradient(135deg,#14264f,#1f4fd8 60%,#6a3df0);color:#fff;padding:44px 0 70px}
header.hero h1{margin:6px 0 4px;font-size:30px;letter-spacing:.5px}header.hero .sub{opacity:.85}
.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;opacity:.75}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-top:-44px}
.kpi,.card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 4px 18px rgba(20,38,79,.06)}
.kpi{padding:16px 18px}.kpi b{display:block;font-size:28px;line-height:1.2}.kpi span{color:var(--mute);font-size:13px}
.card{padding:22px 24px;margin-top:20px}h2{margin:34px 0 4px;font-size:20px}h3{margin:0 0 10px;font-size:17px}
nav.toc{margin:18px 0 0;font-size:14px}nav.toc a{color:var(--brand);text-decoration:none;margin-right:16px}
table{width:100%;border-collapse:collapse;font-size:14px}th{background:#f0f3fa;text-align:left;font-weight:600}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}tr:hover td{background:#fafbff}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;color:#fff;font-size:12px;font-weight:600}
.chip{display:inline-block;padding:2px 10px;margin:2px 4px 2px 0;border-radius:8px;background:#eef2ff;color:#2a3d8f;font-size:13px}
.tag-kg{background:#e3f6ee;color:#0b7a55;border-radius:5px;padding:0 6px;font-size:12px;font-weight:600}
.tag-llm{background:#fff1d6;color:#9a5b00;border-radius:5px;padding:0 6px;font-size:12px;font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:760px){.grid2{grid-template-columns:1fr}}
.answer p{margin:.5em 0}.mute{color:var(--mute)}.note{border-left:4px solid #d98a00;background:#fff8e8;padding:10px 14px;border-radius:6px}
.bar{height:10px;border-radius:5px;background:#e8ecf5;overflow:hidden}.bar i{display:block;height:100%}
details{margin-top:12px}summary{cursor:pointer;color:var(--brand);font-weight:600}
.big{font-size:19px;line-height:1.8}.step{display:flex;gap:14px;margin:12px 0}.step em{flex:none;width:30px;height:30px;border-radius:50%;
background:var(--brand);color:#fff;text-align:center;line-height:30px;font-style:normal;font-weight:700}
footer{margin-top:40px;color:var(--mute);font-size:13px}
.kg .flow{stroke-dasharray:5 7;animation:dash 2.4s linear infinite}.kg .slow{animation-duration:4s}
@keyframes dash{to{stroke-dashoffset:-48}}.kg .pulse{transform-box:fill-box;transform-origin:center;animation:pulse 2.6s ease-in-out infinite}
@keyframes pulse{50%{transform:scale(1.12)}}.kgcard{padding:12px}.kgcap{color:var(--mute);font-size:13px;margin:8px 6px 0}
.open-graph{display:inline-block;padding:7px 16px;border-radius:999px;background:linear-gradient(135deg,#1f4fd8,#6a3df0);color:#fff;text-decoration:none;font-weight:600;font-size:14px;box-shadow:0 4px 14px rgba(31,79,216,.3)}
.open-graph small{opacity:.8;font-weight:400;margin-left:6px}.open-graph:hover{filter:brightness(1.1)}
@media(prefers-reduced-motion:reduce){.kg .flow,.kg .pulse{animation:none}}
@media print{body{background:#fff}.card,.kpi{box-shadow:none}header.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def _cov(level):
    return COV.get(str(level or "").lower(), (str(level or "-"), "#8a94a6", "未知"))


def _badge(level):
    label, color, _ = _cov(level)
    return f'<span class="badge" style="background:{color}">{esc(label)}</span>'


def _ratio(r):
    try:
        return max(0.0, min(1.0, float(r)))
    except (TypeError, ValueError):
        return 0.0


def _queries(result):
    """Yield (role, intent, count, edges[]) from tool_calls; tolerant of format drift."""
    out = []
    for call in result.get("tool_calls") or []:
        res = call.get("result")
        runs = res.get("runs", []) if isinstance(res, dict) else []
        text = res.get("text", "") if isinstance(res, dict) else ""
        edges, intent = [], None
        for line in text.splitlines():
            if line.startswith("[Neo4j_KG]"):
                m = re.search(r"intent=(\w+)", line)
                intent = m.group(1) if m else intent
            m = EDGE.match(line.strip())
            if m:
                kv = dict(p.split("=", 1) for p in re.split(r",\s*(?=\w+=)", m.group("kv")) if "=" in p)
                kv["_intent"] = intent or "-"
                edges.append(kv)
        out.append({"role": call.get("role", "-"), "runs": len(runs), "edges": edges})
    return out


def _donut(ratio, color, size=96):
    r, c = 38, 2 * 3.14159 * 38
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 100 100"><circle cx="50" cy="50" r="{r}" fill="none" stroke="#e8ecf5" stroke-width="12"/>'
            f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="{color}" stroke-width="12" stroke-linecap="round" '
            f'stroke-dasharray="{c * ratio:.1f} {c:.1f}" transform="rotate(-90 50 50)"/>'
            f'<text x="50" y="56" text-anchor="middle" font-size="20" font-weight="700" fill="#1b2437">{ratio * 100:.0f}%</text></svg>')


def _hbars(items, color="#1f4fd8", width=420):
    if not items:
        return '<p class="mute">无数据</p>'
    mx = max(v for _, v in items) or 1
    rows = "".join(
        f'<text x="0" y="{i * 26 + 16}" font-size="12" fill="#445">{esc(str(k))[:26]}</text>'
        f'<rect x="170" y="{i * 26 + 4}" width="{(width - 220) * v / mx:.0f}" height="14" rx="4" fill="{color}"/>'
        f'<text x="{176 + (width - 220) * v / mx:.0f}" y="{i * 26 + 16}" font-size="12" fill="#445">{v}</text>'
        for i, (k, v) in enumerate(items))
    return f'<svg width="100%" viewBox="0 0 {width} {len(items) * 26 + 6}">{rows}</svg>'


def _short(s, n=22):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


def _kg_graph(edges, focus=None, max_g=12, max_p=7, dark=True, labels=None):
    """Radial knowledge-graph SVG: disease (centre) -> genes (inner ring) -> pathways (outer ring)."""
    import math
    disease = next((e.get("disease") for e in edges if e.get("disease")), None)
    if not disease:
        return ""
    genes_direct = []
    for e in edges:
        g = e.get("gene")
        if g and g not in genes_direct:
            genes_direct.append(g)
    paths = []
    for e in edges:
        if e.get("pathway"):
            gl = [x.strip() for x in str(e.get("genes", "")).split(",") if x.strip()]
            try:
                n = int(e.get("gene_count", 0))
            except ValueError:
                n = len(gl)
            paths.append((e["pathway"], gl, n))
    paths = sorted(paths, key=lambda x: -x[2])[:max_p]
    linked = []
    for _, gl, _ in paths:
        for g in gl:
            if g not in linked:
                linked.append(g)
    genes = []
    for g in ([focus] if focus else []) + linked + genes_direct:
        if g and g not in genes:
            genes.append(g)
    genes = genes[:max_g]
    L = labels or {"d": "疾病", "g": "基因", "p": "通路", "f": "本次关注基因"}
    W, H, cx, cy, r1, r2 = 980, 560, 490, 280, 125, 230
    pos = {}
    for i, g in enumerate(genes):
        a = 2 * math.pi * i / max(len(genes), 1) - math.pi / 2
        pos[("g", g)] = (cx + r1 * math.cos(a), cy + r1 * math.sin(a), a)
    for i, (p, _, _) in enumerate(paths):
        a = 2 * math.pi * (i + 0.5) / max(len(paths), 1) - math.pi / 2
        pos[("p", p)] = (cx + r2 * 1.18 * math.cos(a), cy + r2 * 0.98 * math.sin(a), a)
    bg, ink, sub = ("#0c1630", "#e8eeff", "#9fb0d8") if dark else ("#f4f7ff", "#1b2437", "#667085")
    out = [f'<svg class="kg" width="100%" viewBox="0 0 {W} {H}" role="img" aria-label="知识图谱"><defs>'
           f'<radialGradient id="bgG{int(dark)}" cx="50%" cy="50%" r="70%"><stop offset="0" stop-color="{"#1b2f66" if dark else "#e6edff"}"/>'
           f'<stop offset="1" stop-color="{bg}"/></radialGradient>'
           '<filter id="glow"><feGaussianBlur stdDeviation="3.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
           f'<rect width="{W}" height="{H}" rx="16" fill="url(#bgG{int(dark)})"/>']
    for r in (r1, r2 * 1.1):
        out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{r * (1.18 if r > r1 else 1)}" ry="{r * (0.98 if r > r1 else 1)}" fill="none" stroke="{sub}" stroke-opacity=".18" stroke-dasharray="3 6"/>')
    for (kind, name), (x, y, _) in pos.items():
        if kind == "g":
            hot = name == focus
            out.append(f'<line class="flow" x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{"#ffc23d" if hot else "#27d3a2"}" stroke-width="{2.4 if hot else 1.3}" stroke-opacity=".75"/>')
    for p, gl, _ in paths:
        px, py, _ = pos[("p", p)]
        for g in gl:
            if ("g", g) in pos:
                gx, gy, _ = pos[("g", g)]
                out.append(f'<line class="flow slow" x1="{gx:.1f}" y1="{gy:.1f}" x2="{px:.1f}" y2="{py:.1f}" stroke="#9b7bff" stroke-width="1.2" stroke-opacity=".7"/>')
    for p, gl, n in paths:
        px, py, a = pos[("p", p)]
        anchor = "start" if math.cos(a) > 0.2 else ("end" if math.cos(a) < -0.2 else "middle")
        dx = 16 if anchor == "start" else (-16 if anchor == "end" else 0)
        dy = -16 if anchor == "middle" and math.sin(a) < 0 else (26 if anchor == "middle" else 4)
        out.append(f'<g><title>{esc(p)} · {n} 个相关基因</title><rect x="{px - 9:.1f}" y="{py - 9:.1f}" width="18" height="18" rx="5" fill="#9b7bff" filter="url(#glow)"/>'
                   f'<text x="{px + dx:.1f}" y="{py + dy:.1f}" text-anchor="{anchor}" font-size="11.5" fill="{ink}">{esc(_short(p, 26))}</text></g>')
    for g in genes:
        x, y, a = pos[("g", g)]
        hot = g == focus
        col = "#ffc23d" if hot else "#27d3a2"
        out.append(f'<g><title>{esc(g)}</title><circle cx="{x:.1f}" cy="{y:.1f}" r="{12 if hot else 8}" fill="{col}" filter="url(#glow)"/>'
                   f'<text x="{x + (14 if math.cos(a) >= 0 else -14):.1f}" y="{y + 4:.1f}" text-anchor="{"start" if math.cos(a) >= 0 else "end"}" '
                   f'font-size="{13 if hot else 11}" font-weight="{700 if hot else 500}" fill="{ink}">{esc(g)}</text></g>')
    out.append(f'<g><title>{esc(disease)}</title><circle class="pulse" cx="{cx}" cy="{cy}" r="34" fill="#ff5d73" filter="url(#glow)"/>'
               f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">{L["d"]}</text>'
               f'<rect x="{cx - 120}" y="{cy + 44}" width="240" height="20" rx="10" fill="{bg}" fill-opacity=".85"/>'
               f'<text x="{cx}" y="{cy + 58}" text-anchor="middle" font-size="12" fill="{ink}">{esc(_short(disease, 36))}</text></g>')
    ly = H - 22
    for i, (c, t) in enumerate([("#ff5d73", L["d"]), ("#27d3a2", L["g"]), ("#9b7bff", L["p"]), ("#ffc23d", L["f"])]):
        x = 24 + i * 130
        out.append(f'<circle cx="{x}" cy="{ly}" r="6" fill="{c}"/><text x="{x + 12}" y="{ly + 4}" font-size="12" fill="{sub}">{esc(t)}</text>')
    out.append("</svg>")
    return "".join(out)


def _answer_html(text):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    out = []
    for p in paras:
        p = esc(p)
        p = re.sub(r"^#+\s*(.+)$", r"<b>\1</b>", p, flags=re.M)
        p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p)
        for tag, cls in TAGS.items():
            p = p.replace(esc(tag), f'<span class="tag-{cls}">{esc(tag.strip("[]"))}</span>')
        out.append("<p>" + p.replace("\n", "<br>") + "</p>")
    return "".join(out) or '<p class="mute">无文本输出</p>'


def _shell(title, eyebrow, sub, body, plain=False):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{CSS}</style></head><body>'
            f'<header class="hero"><div class="wrap"><div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1>'
            f'<div class="sub">{esc(sub)}</div></div></header><div class="wrap">{body}'
            '<footer>本报告由 GDgpt 自动生成，为待复核的模型机制解释，不构成诊断或治疗建议。</footer></div></body></html>')


def render_professional(rep):
    results = rep.get("task_results") or []
    qs = [_queries(r) for r in results]
    n_edges = sum(len(c["edges"]) for q in qs for c in q)
    n_runs = sum(c["runs"] for q in qs for c in q)
    avg = sum(_ratio(r.get("kg_coverage_ratio")) for r in results) / len(results) if results else 0
    secs = sum(float(r.get("elapsed_seconds") or 0) for r in results)
    k = [(len(results), "完成分析任务"), (f"{avg * 100:.0f}%", "平均图谱覆盖率"), (n_edges, "检索到的图谱边"),
         (n_runs, "Cypher 查询次数"), (f"{secs / 60:.1f} 分", "总耗时")]
    body = '<div class="kpis">' + "".join(f'<div class="kpi"><b>{a}</b><span>{esc(b)}</span></div>' for a, b in k) + "</div>"
    body += '<nav class="toc"><a href="#sum">摘要</a><a href="#tasks">任务总览</a><a href="#detail">逐基因分析</a><a href="#bound">分析边界</a>' \
            '<a href="report_graph.html" target="_blank"><b>交互式图谱 ↗</b></a><a href="report.json">report.json</a><a href="gdgpt_input.json">上游证据</a></nav>'
    up = (rep.get("upstream_summary") or {}).get("conclusion") or {}
    body += f'<h2 id="sum">摘要</h2><div class="card"><p>{esc(rep.get("summary", ""))}</p>'
    if up.get("finding"):
        body += f'<p class="mute">上游结论：{esc(up["finding"])}</p>'
    body += f'<p class="mute">样本 {esc(rep.get("sample_id", ""))} · 基因组版本 {esc(rep.get("assembly", ""))} · 生成于 {esc(rep.get("generated_at", ""))}</p></div>'
    if not results:
        body += '<div class="card note">没有可自动进入机制分析的疾病候选，本次未调用大模型。</div>'
    else:
        dist = Counter(str(r.get("kg_coverage_level", "-")).lower() for r in results)
        body += '<h2 id="tasks">任务总览</h2><div class="grid2"><div class="card"><h3>图谱覆盖分布</h3>' + \
            _hbars([(_cov(l)[0], v) for l, v in dist.items()], "#1f4fd8") + '</div><div class="card"><h3>各任务覆盖率</h3>' + \
            _hbars([(f"{r.get('gene', '-')}/{r.get('kind', '')}", round(_ratio(r.get("kg_coverage_ratio")) * 100)) for r in results], "#6a3df0") + '</div></div>'
        body += '<div class="card"><table><tr><th>基因</th><th>类型</th><th>覆盖</th><th>覆盖率</th><th>边数</th><th>耗时(s)</th></tr>' + "".join(
            f'<tr><td><b>{esc(str(r.get("gene", "-")))}</b></td><td>{esc(str(r.get("kind", "-")))}</td><td>{_badge(r.get("kg_coverage_level"))}</td>'
            f'<td>{_ratio(r.get("kg_coverage_ratio")) * 100:.0f}%</td><td>{sum(len(c["edges"]) for c in q)}</td><td>{r.get("elapsed_seconds", "-")}</td></tr>'
            for r, q in zip(results, qs)) + "</table></div>"
        body += '<h2 id="detail">逐基因分析</h2>'
        for ti, (r, q) in enumerate(zip(results, qs)):
            lab, col, desc = _cov(r.get("kg_coverage_level"))
            edges = [e for c in q for e in c["edges"]]
            intents = Counter(e["_intent"] for e in edges).most_common()
            roles = Counter({c["role"]: len(c["edges"]) for c in q}).most_common()
            body += (f'<div class="card"><div style="display:flex;gap:20px;align-items:center">{_donut(_ratio(r.get("kg_coverage_ratio")), col)}'
                     f'<div><h3 style="margin:0">{esc(str(r.get("gene", "-")))} · {esc(str(r.get("kind", "")))}</h3>'
                     f'{_badge(r.get("kg_coverage_level"))} <span class="mute">{esc(desc)} · 候选 {esc(str(r.get("candidate_id", "-")))}</span></div></div>'
                     f'<div class="grid2" style="margin-top:14px"><div><b>按查询意图的边数</b>{_hbars(intents, "#0f9d6e")}</div>'
                     f'<div><b>按专家角色检索量</b>{_hbars(roles, "#d98a00")}</div></div>')
            kg = _kg_graph(edges, focus=r.get("gene"))
            if kg:
                body += ('<div style="display:flex;justify-content:space-between;align-items:center;margin-top:18px"><h3 style="margin:0">知识图谱子图</h3>'
                         f'<a class="open-graph" href="report_graph.html#t={ti}" target="_blank">打开交互式图谱 ↗ <small>拖拽 · 缩放 · 点击查看详情</small></a></div>'
                         '<div class="card kgcard" style="box-shadow:none;margin-top:8px">' + kg +
                         '<div class="kgcap">中心为疾病节点，内环为图谱中与其关联的基因，外环为 Reactome/NCBI 通路；连线表示被检索到的关联边，悬停节点可见完整名称。仅展示检索结果中的部分节点。</div></div>')
            if edges:
                body += '<details><summary>图谱证据表（前 40 条）</summary><table><tr><th>意图</th><th>实体</th><th>关系</th><th>来源</th></tr>' + "".join(
                    f'<tr><td>{esc(e["_intent"])}</td><td>{esc(e.get("gene") or e.get("pathway") or e.get("drug") or e.get("phenotype") or "-")}</td>'
                    f'<td>{esc(e.get("relation", "-"))}</td><td>{esc(e.get("source", "-"))}</td></tr>' for e in edges[:40]) + "</table></details>"
            body += f'<h3 style="margin-top:18px">机制解释</h3><div class="answer">{_answer_html(r.get("answer_text"))}</div></div>'
    lim = rep.get("limitations") or []
    body += '<h2 id="bound">分析边界</h2><div class="card note"><ul>' + "".join(f"<li>{esc(str(x))}</li>" for x in lim) + \
            "</ul><p>未建立诊断；未修改 ACMG 分类；不提供风险概率。</p></div>"
    return _shell(f"GDgpt 机制分析报告 · {rep.get('sample_id', '')}", "GDgpt · 专业版", "知识图谱约束的多专家机制解释，含证据表与查询追溯", body)


def _first_paras(text, n=2):
    ps = [re.sub(r"[#*]+", "", p).strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return [p for p in ps if len(p) > 20][:n]


def render_plain(rep):
    results = rep.get("task_results") or []
    body = '<div class="card big"><b>一句话结论</b><br>' + (
        f'本次对 {len(results)} 个基因做了进一步的“机制解读”，说明这些基因的变化<b>可能</b>如何与健康问题相关。这是辅助参考，<b>不是诊断</b>。'
        if results else "本次没有找到需要进一步解读的基因，因此没有生成机制解读。这<b>不等于</b>排除了任何问题。") + "</div>"
    if results:
        body += "<h2>涉及的基因</h2>"
        for r in results:
            lab, col, desc = _cov(r.get("kg_coverage_level"))
            conf = {"high": "较充分", "partial": "一般", "low": "较少"}.get(str(r.get("kg_coverage_level")).lower(), "未知")
            body += (f'<div class="card"><div style="display:flex;gap:18px;align-items:center">{_donut(_ratio(r.get("kg_coverage_ratio")), col, 80)}'
                     f'<div><h3 style="margin:0">{esc(str(r.get("gene", "-")))}</h3><span class="mute">可参考的医学资料：{conf}</span></div></div>')
            for p in _first_paras(r.get("answer_text")):
                body += f"<p>{esc(p)}</p>"
            kg = _kg_graph([e for c in _queries(r) for e in c["edges"]], focus=r.get("gene"), max_g=7, max_p=4, dark=False,
                           labels={"d": "疾病", "g": "相关基因", "p": "生物通路", "f": "本次关注"})
            if kg:
                body += '<div style="margin-top:10px">' + kg + '<div class="kgcap">这张图展示：疾病（中间）和哪些基因、生物通路在医学资料里被关联到一起。线越多，说明资料里联系越多。</div></div>'
            body += '<p class="mute">以上为 AI 根据知识库整理的说明，需由专业人员复核。</p></div>'
    body += ('<h2>接下来可以做什么</h2><div class="card">'
             '<div class="step"><em>1</em><div>把本报告和原始检测报告一起带给<b>遗传咨询师或相关专科医生</b>。</div></div>'
             '<div class="step"><em>2</em><div>询问这些基因与你的症状、家族史是否相关，是否需要进一步检查。</div></div>'
             '<div class="step"><em>3</em><div>不要仅凭本报告自行用药、停药或做出重大健康决定。</div></div></div>'
             '<h2>常见疑问</h2><div class="card"><details open><summary>这是诊断吗？</summary><p>不是。报告没有给出诊断，也没有改变原有的变异分类。</p></details>'
             '<details><summary>“资料较少”是什么意思？</summary><p>表示知识库中能找到的相关信息有限，解读的把握相应较低，并不代表没有风险。</p></details>'
             '<details><summary>专业人员想看细节怎么办？</summary><p>请查看同目录下的专业版报告 report.html。</p></details></div>')
    return _shell("基因分析结果 · 通俗版", "给普通用户", f"样本 {rep.get('sample_id', '')}", body, plain=True)


def write_html_reports(outdir, report):
    from .gdgpt_graph import render_graph
    (outdir / "report_graph.html").write_text(render_graph(report), encoding="utf-8")
    (outdir / "report.html").write_text(render_professional(report), encoding="utf-8")
    (outdir / "report_plain.html").write_text(render_plain(report), encoding="utf-8")
