"""Standalone interactive knowledge-graph page (pure HTML/JS/SVG, works offline)."""
import json
import re
from html import escape as esc

from pathlib import Path

from .gdgpt_report import _queries
from .report_theme import CSS

GRAPH_CSS = CSS + Path(__file__).with_suffix(".css").read_text(encoding="utf-8")


def graph_data(results):
    tasks = []
    for r in results:
        nodes, links = {}, {}

        def node(key, typ, label, **extra):
            n = nodes.setdefault(key, {"id": key, "type": typ, "label": label, "info": {}})
            for k, v in extra.items():
                if v:
                    n["info"].setdefault(k, set()).update(v if isinstance(v, (list, set)) else [v])
            return n

        def link(a, b, rel, src=None):
            k = tuple(sorted((a, b)))
            l = links.setdefault(k, {"s": a, "t": b, "rel": set(), "src": set()})
            if rel:
                l["rel"].add(rel)
            if src:
                l["src"].update(x.strip() for x in str(src).split(",") if x.strip())

        for c in _queries(r):
            for e in c["edges"]:
                d = e.get("disease")
                if not d:
                    continue
                dk = "D:" + d
                node(dk, "disease", d)
                if e.get("gene"):
                    gk = "G:" + e["gene"]
                    node(gk, "gene", e["gene"], 来源=e.get("source", "").split(","), 关系=[e.get("relation", "")])
                    link(dk, gk, e.get("relation"), e.get("source"))
                if e.get("pathway"):
                    pk = "P:" + e["pathway"]
                    gl = [x.strip() for x in str(e.get("genes", "")).split(",") if x.strip()]
                    node(pk, "pathway", e["pathway"], 通路来源=str(e.get("pathway_sources", "")).split(","),
                         关联基因数=[e.get("gene_count", "")])
                    link(dk, pk, e.get("disease_gene_relations"), e.get("disease_sources"))
                    for g in gl:
                        gk = "G:" + g
                        node(gk, "gene", g)
                        link(gk, pk, e.get("gene_pathway_relations"), e.get("pathway_sources"))
        focus = "G:" + str(r.get("gene"))
        if focus in nodes:
            nodes[focus]["focus"] = True
        elif r.get("gene"):
            nodes[focus] = {"id": focus, "type": "gene", "label": r["gene"], "focus": True, "info": {}}
            for dk in [k for k, v in nodes.items() if v["type"] == "disease"][:1]:
                links[tuple(sorted((dk, focus)))] = {"s": dk, "t": focus, "rel": {"本次分析"}, "src": set()}
        fix = lambda o: {k: (sorted(v) if isinstance(v, set) else v) for k, v in o.items()}
        tasks.append({"name": f"{r.get('gene', '-')} / {r.get('kind', '')}", "gene": r.get("gene"),
                      "coverage": r.get("kg_coverage_level"),
                      "nodes": [dict(fix(n), info=fix(n["info"])) for n in nodes.values()],
                      "links": [fix(l) for l in links.values()]})
    return tasks


PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>知识图谱 · __SAMPLE__</title><style>__CSS__</style></head><body>
<header class="atlas-head"><h1>知识图谱<small>GDGPT　/　EVIDENCE ATLAS</small></h1><div class="atlas-meta"><span>样本　__SAMPLE__</span><a href="report.html">← 专业报告</a></div></header>
<div class="bar"><div class="pill"><select aria-label="分析任务" id="task"></select></div>
<div class="pill"><input id="q" aria-label="搜索节点" type="search" placeholder="搜索节点…"></div>
<div class="pill" id="types"></div><div class="pill"><button id="fit">适应窗口</button><button id="pause">暂停布局</button></div></div>
<div class="atlas-work"><div id="stage"><svg id="svg" aria-label="交互式知识图谱"><g id="vp"><g id="el"></g><g id="nl"></g></g></svg></div><aside id="panel" aria-label="节点证据"></aside></div>
<div class="hint"><span class="focus-key">● 本次关注基因</span>拖拽空白处平移 · 滚轮缩放 · 点击节点查看证据 · 双击空白取消选择</div>
<script>
const DATA=__DATA__;const COL={disease:"var(--node-disease)",gene:"var(--node-gene)",pathway:"var(--node-pathway)"},TN={disease:"疾病",gene:"基因",pathway:"通路"};
const NS="http://www.w3.org/2000/svg",$=id=>document.getElementById(id);
const svg=$("svg"),vp=$("vp"),EL=$("el"),NL=$("nl"),panel=$("panel");
let nodes=[],links=[],byId={},nb={},sel=null,view={x:0,y:0,k:1},alpha=1,paused=false,hidden=new Set(),q="";
const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e};
DATA.forEach((t,i)=>{const o=document.createElement("option");o.value=i;o.textContent=t.name+(t.coverage?" · 覆盖"+t.coverage:"");$("task").appendChild(o)});
for(const t in TN){const l=document.createElement("label");l.innerHTML='<input type="checkbox" checked data-t="'+t+'"> <span style="color:'+COL[t]+'">●</span> '+TN[t];$("types").appendChild(l)}
function load(i){
 const T=DATA[i];sel=null;panel.style.display="none";EL.innerHTML="";NL.innerHTML="";byId={};nb={};
 nodes=T.nodes.map((n,j)=>{const a=j*2.4,r=40+Math.sqrt(j)*40;return Object.assign({},n,{x:Math.cos(a)*r,y:Math.sin(a)*r,vx:0,vy:0,fixed:n.type==="disease"})});
 nodes.forEach(n=>{byId[n.id]=n;nb[n.id]=new Set();n.r=n.type==="disease"?26:n.focus?14:n.type==="pathway"?10:8});
 // Disease nodes are anchors. One disease sits at the origin; several must be spread on a
 // ring, otherwise every one of them is pulled to (0,0) and their labels stack illegibly.
 const dz=nodes.filter(n=>n.type==="disease");
 if(dz.length>1){const dr=Math.max(150,30*dz.length+26*2);
  dz.forEach((n,j)=>{const a=-Math.PI/2+j*2*Math.PI/dz.length;n.ax=Math.cos(a)*dr;n.ay=Math.sin(a)*dr;n.x=n.ax;n.y=n.ay})}
 else dz.forEach(n=>{n.ax=0;n.ay=0});
 links=T.links.filter(l=>byId[l.s]&&byId[l.t]).map(l=>Object.assign({},l,{a:byId[l.s],b:byId[l.t]}));
 links.forEach(l=>{nb[l.s].add(l.t);nb[l.t].add(l.s);
  l.el=mk("line",{class:"edge flow","stroke":l.a.type==="gene"&&l.b.type==="pathway"||l.b.type==="gene"&&l.a.type==="pathway"?"var(--node-pathway)":"var(--node-gene)","stroke-width":1.3,"stroke-opacity":.6});
  const tt=mk("title",{});tt.textContent=(l.rel.join("、")||"关联")+(l.src.length?" · 来源："+l.src.join("、"):"");l.el.appendChild(tt);EL.appendChild(l.el)});
 nodes.forEach(n=>{const g=mk("g",{class:"node",role:"button",tabindex:0,"aria-label":TN[n.type]+" · "+n.label});
  const sh=n.type==="pathway"?mk("rect",{x:-n.r,y:-n.r,width:n.r*2,height:n.r*2,rx:4}):mk("circle",{r:n.r});
  sh.setAttribute("fill",n.focus?"var(--node-focus)":COL[n.type]);g.appendChild(sh);
  const tx=mk("text",{x:n.r+5,y:4,fill:"var(--ink)","font-size":n.type==="disease"?13:11.5});tx.textContent=n.label.length>34?n.label.slice(0,33)+"…":n.label;
  if(n.type==="disease"){tx.setAttribute("x",0);tx.setAttribute("y",n.r+16);tx.setAttribute("text-anchor","middle")}g.appendChild(tx);
  const ti=mk("title",{});ti.textContent=n.label;g.appendChild(ti);n.el=g;NL.appendChild(g);bind(g,n)});
 alpha=1;draw();setTimeout(fit,700)}
function tick(){
 if(!paused&&alpha>0.01){
  for(const a of nodes)for(const b of nodes){if(a===b)continue;let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy+.01;if(d2>90000)continue;const f=2600/d2*alpha,d=Math.sqrt(d2);a.vx+=dx/d*f;a.vy+=dy/d*f}
  for(const l of links){const dx=l.b.x-l.a.x,dy=l.b.y-l.a.y,d=Math.sqrt(dx*dx+dy*dy)||1,len=l.a.type==="disease"||l.b.type==="disease"?(l.a.type==="pathway"||l.b.type==="pathway"?230:120):90,f=(d-len)*.02*alpha;
   l.a.vx+=dx/d*f;l.a.vy+=dy/d*f;l.b.vx-=dx/d*f;l.b.vy-=dy/d*f}
  for(const n of nodes){if(n.fixed&&n.type==="disease"&&!n.dragging){n.x+=((n.ax||0)-n.x)*.1;n.y+=((n.ay||0)-n.y)*.1;continue}n.vx-=n.x*.002*alpha;n.vy-=n.y*.002*alpha;if(!n.dragging){n.x+=n.vx;n.y+=n.vy}n.vx*=.78;n.vy*=.78}
  alpha*=.992;draw()}
 requestAnimationFrame(tick)}
function draw(){for(const n of nodes)n.el.setAttribute("transform","translate("+n.x.toFixed(1)+","+n.y.toFixed(1)+")");
 for(const l of links){l.el.setAttribute("x1",l.a.x);l.el.setAttribute("y1",l.a.y);l.el.setAttribute("x2",l.b.x);l.el.setAttribute("y2",l.b.y)}}
function apply(){vp.setAttribute("transform","translate("+view.x+","+view.y+") scale("+view.k+")")}
function fit(){if(!nodes.length)return;const W=svg.clientWidth,H=svg.clientHeight;let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
 for(const n of nodes){x0=Math.min(x0,n.x-60);x1=Math.max(x1,n.x+160);y0=Math.min(y0,n.y-30);y1=Math.max(y1,n.y+40)}
 view.k=Math.min(2,Math.min(W/(x1-x0),H/(y1-y0))*.9);view.x=W/2-(x0+x1)/2*view.k;view.y=H/2-(y0+y1)/2*view.k;apply()}
function vis(n){return !hidden.has(n.type)}
function refresh(){const m=q?nodes.filter(n=>n.label.toLowerCase().includes(q)).map(n=>n.id):[];const hs=new Set(m);
 for(const n of nodes){const show=vis(n);n.el.style.display=show?"":"none";
  n.el.classList.toggle("dim",show&&sel&&n.id!==sel&&!nb[sel].has(n.id));n.el.classList.toggle("sel",n.id===sel);n.el.classList.toggle("hit",hs.has(n.id))}
 for(const l of links){const show=vis(l.a)&&vis(l.b);l.el.style.display=show?"":"none";
  l.el.classList.toggle("dim",!!sel&&l.s!==sel&&l.t!==sel);l.el.setAttribute("stroke-width",sel&&(l.s===sel||l.t===sel)?2.8:1.3)}}
function show(n){sel=n.id;const p=panel;p.innerHTML="";p.style.display="block";
 const add=(tag,txt,cls)=>{const e=document.createElement(tag);e.textContent=txt;if(cls)e.className=cls;p.appendChild(e);return e};
 const x=add("button","×");x.id="x";x.setAttribute("aria-label","关闭节点证据");x.onclick=()=>{sel=null;p.style.display="none";refresh()};
 add("h2",n.label);const t=add("span",TN[n.type]+(n.focus?" · 本次关注":""),"tag");t.style.color=n.focus?"var(--ochre)":COL[n.type];
 add("div","直接关联节点："+nb[n.id].size+" 个");
 for(const k in n.info){add("h4",k);add("div",n.info[k].filter(Boolean).join("、")||"-")}
 const ls=links.filter(l=>l.s===n.id||l.t===n.id);const rel=[...new Set(ls.flatMap(l=>l.rel))];if(rel.length){add("h4","关系类型");add("div",rel.join("、"))}
 const src=[...new Set(ls.flatMap(l=>l.src))];if(src.length){add("h4","证据来源");add("div",src.join("、"))}
 for(const ty of ["disease","gene","pathway"]){const xs=[...nb[n.id]].map(i=>byId[i]).filter(o=>o.type===ty);if(!xs.length)continue;
  add("h4","关联"+TN[ty]+"（"+xs.length+"）");const box=document.createElement("div");xs.forEach(o=>{const s=document.createElement("button");s.className="nb";s.textContent=o.label.length>28?o.label.slice(0,27)+"…":o.label;s.onclick=()=>{show(o);center(o)};box.appendChild(s)});p.appendChild(box)}
 refresh()}
function center(n){view.x=(svg.clientWidth-(innerWidth>650?panel.offsetWidth:0))/2-n.x*view.k;view.y=(svg.clientHeight-(innerWidth<=650?panel.offsetHeight:0))/2-n.y*view.k;apply()}
function bind(g,n){g.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();show(n)}};let sx,sy,moved;g.addEventListener("pointerdown",e=>{e.stopPropagation();g.setPointerCapture(e.pointerId);n.dragging=true;n.fixed=true;moved=false;sx=e.clientX;sy=e.clientY;alpha=Math.max(alpha,.3)});
 g.addEventListener("pointermove",e=>{if(!n.dragging)return;if(Math.abs(e.clientX-sx)+Math.abs(e.clientY-sy)>3)moved=true;n.x+=e.movementX/view.k;n.y+=e.movementY/view.k;draw()});
 g.addEventListener("pointerup",e=>{n.dragging=false;if(n.type!=="disease")n.fixed=false;if(!moved)show(n)});}
let pan=null;$("stage").addEventListener("pointerdown",e=>{pan={x:e.clientX,y:e.clientY};$("stage").classList.add("drag")});
addEventListener("pointermove",e=>{if(!pan)return;view.x+=e.clientX-pan.x;view.y+=e.clientY-pan.y;pan={x:e.clientX,y:e.clientY};apply()});
addEventListener("pointerup",()=>{pan=null;$("stage").classList.remove("drag")});
$("stage").addEventListener("dblclick",e=>{if(e.target.closest(".node"))return;sel=null;panel.style.display="none";refresh()});
$("stage").addEventListener("wheel",e=>{e.preventDefault();const f=Math.exp(-e.deltaY*.0015),k=Math.max(.15,Math.min(5,view.k*f));
 const rect=svg.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;view.x=x-(x-view.x)*(k/view.k);view.y=y-(y-view.y)*(k/view.k);view.k=k;apply()},{passive:false});
$("task").onchange=e=>load(+e.target.value);$("q").oninput=e=>{q=e.target.value.trim().toLowerCase();refresh()};
$("fit").onclick=fit;$("pause").onclick=e=>{paused=!paused;e.target.textContent=paused?"继续布局":"暂停布局"};
$("types").onchange=e=>{const t=e.target.dataset.t;e.target.checked?hidden.delete(t):hidden.add(t);refresh()};
addEventListener("resize",fit);
if(DATA.length){load(+((location.hash.match(/t=(\d+)/)||[0,0])[1])<DATA.length?+((location.hash.match(/t=(\d+)/)||[0,0])[1]):0);$("task").value=String(+((location.hash.match(/t=(\d+)/)||[0,0])[1])<DATA.length?+((location.hash.match(/t=(\d+)/)||[0,0])[1]):0);tick()}else{$("stage").insertAdjacentHTML("afterend",'<div class="empty-graph">没有可展示的图谱数据</div>')}
</script></body></html>"""


def render_graph(rep):
    data = json.dumps(graph_data(rep.get("task_results") or []), ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__CSS__", GRAPH_CSS).replace("__SAMPLE__", esc(str(rep.get("sample_id", "")))).replace("__DATA__", data)
