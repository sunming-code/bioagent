"""Standalone interactive knowledge-graph page (pure HTML/JS/SVG, works offline)."""
import json
import re
from html import escape as esc

from .gdgpt_report import _queries


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
<title>知识图谱 · __SAMPLE__</title><style>
*{box-sizing:border-box}html,body{margin:0;height:100%;background:#070d1f;color:#e8eeff;font:14px/1.5 -apple-system,"PingFang SC",system-ui,sans-serif;overflow:hidden}
#stage{position:fixed;inset:0;cursor:grab}#stage.drag{cursor:grabbing}svg{width:100%;height:100%;display:block}
.bar{position:fixed;top:14px;left:14px;right:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;pointer-events:none}
.bar>*{pointer-events:auto}.pill{background:rgba(18,30,64,.85);border:1px solid #2a3c75;border-radius:12px;padding:6px 10px;backdrop-filter:blur(8px)}
button,select,input{font:inherit;color:#e8eeff;background:#16244f;border:1px solid #2f4390;border-radius:8px;padding:5px 10px}button{cursor:pointer}button:hover{background:#21357a}
input[type=search]{width:190px}label{margin-right:8px;white-space:nowrap}h1{font-size:15px;margin:0 6px 0 0}
#panel{position:fixed;top:70px;right:14px;bottom:14px;width:320px;overflow:auto;background:rgba(14,24,54,.92);border:1px solid #2a3c75;border-radius:14px;padding:16px;display:none}
#panel h2{margin:0 0 4px;font-size:17px;word-break:break-word}.tag{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;color:#fff;margin-bottom:8px}
#panel h4{margin:14px 0 4px;color:#9fb0d8;font-size:12px;letter-spacing:1px}.nb{display:inline-block;margin:2px 4px 2px 0;padding:2px 9px;border-radius:8px;background:#1d2d63;cursor:pointer;font-size:13px}.nb:hover{background:#2c449a}
#x{float:right;padding:0 8px}.hint{position:fixed;left:14px;bottom:14px;color:#8fa0cc;font-size:12px}
.node{cursor:pointer}.node text{pointer-events:none;paint-order:stroke;stroke:#070d1f;stroke-width:3px}.dim{opacity:.12}.edge{stroke-linecap:round}
.flow{stroke-dasharray:5 7;animation:dash 2.4s linear infinite}@keyframes dash{to{stroke-dashoffset:-48}}
.sel circle,.sel rect{stroke:#fff;stroke-width:3}.hit circle,.hit rect{stroke:#ffe27a;stroke-width:3}
@media(prefers-reduced-motion:reduce){.flow{animation:none}}</style></head><body>
<div id="stage"><svg id="svg"><g id="vp"><g id="el"></g><g id="nl"></g></g></svg></div>
<div class="bar"><div class="pill"><h1>知识图谱</h1><select id="task"></select></div>
<div class="pill"><input id="q" type="search" placeholder="搜索节点…"></div>
<div class="pill" id="types"></div><div class="pill"><button id="fit">适应窗口</button> <button id="pause">暂停布局</button></div></div>
<div id="panel"></div>
<div class="hint">拖拽空白处平移 · 滚轮缩放 · 拖动节点 · 点击节点查看详情 · 双击空白取消选择</div>
<script>
const DATA=__DATA__;const COL={disease:"#ff5d73",gene:"#27d3a2",pathway:"#9b7bff"},TN={disease:"疾病",gene:"基因",pathway:"通路"};
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
  l.el=mk("line",{class:"edge flow","stroke":l.a.type==="gene"&&l.b.type==="pathway"||l.b.type==="gene"&&l.a.type==="pathway"?"#9b7bff":"#27d3a2","stroke-width":1.3,"stroke-opacity":.6});
  const tt=mk("title",{});tt.textContent=(l.rel.join("、")||"关联")+(l.src.length?" · 来源："+l.src.join("、"):"");l.el.appendChild(tt);EL.appendChild(l.el)});
 nodes.forEach(n=>{const g=mk("g",{class:"node"});
  const sh=n.type==="pathway"?mk("rect",{x:-n.r,y:-n.r,width:n.r*2,height:n.r*2,rx:4}):mk("circle",{r:n.r});
  sh.setAttribute("fill",n.focus?"#ffc23d":COL[n.type]);g.appendChild(sh);
  const tx=mk("text",{x:n.r+5,y:4,fill:"#e8eeff","font-size":n.type==="disease"?13:11.5});tx.textContent=n.label.length>34?n.label.slice(0,33)+"…":n.label;
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
function fit(){if(!nodes.length)return;const W=innerWidth,H=innerHeight;let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
 for(const n of nodes){x0=Math.min(x0,n.x-60);x1=Math.max(x1,n.x+160);y0=Math.min(y0,n.y-30);y1=Math.max(y1,n.y+40)}
 view.k=Math.min(2,Math.min(W/(x1-x0),H/(y1-y0))*.9);view.x=W/2-(x0+x1)/2*view.k;view.y=H/2-(y0+y1)/2*view.k+20;apply()}
function vis(n){return !hidden.has(n.type)}
function refresh(){const m=q?nodes.filter(n=>n.label.toLowerCase().includes(q)).map(n=>n.id):[];const hs=new Set(m);
 for(const n of nodes){const show=vis(n);n.el.style.display=show?"":"none";
  n.el.classList.toggle("dim",show&&sel&&n.id!==sel&&!nb[sel].has(n.id));n.el.classList.toggle("sel",n.id===sel);n.el.classList.toggle("hit",hs.has(n.id))}
 for(const l of links){const show=vis(l.a)&&vis(l.b);l.el.style.display=show?"":"none";
  l.el.classList.toggle("dim",!!sel&&l.s!==sel&&l.t!==sel);l.el.setAttribute("stroke-width",sel&&(l.s===sel||l.t===sel)?2.8:1.3)}}
function show(n){sel=n.id;const p=panel;p.innerHTML="";p.style.display="block";
 const add=(tag,txt,cls)=>{const e=document.createElement(tag);e.textContent=txt;if(cls)e.className=cls;p.appendChild(e);return e};
 const x=add("button","×");x.id="x";x.onclick=()=>{sel=null;p.style.display="none";refresh()};
 add("h2",n.label);const t=add("span",TN[n.type]+(n.focus?" · 本次关注":""),"tag");t.style.background=n.focus?"#d99a00":COL[n.type];
 add("div","直接关联节点："+nb[n.id].size+" 个");
 for(const k in n.info){add("h4",k);add("div",n.info[k].filter(Boolean).join("、")||"-")}
 const ls=links.filter(l=>l.s===n.id||l.t===n.id);const rel=[...new Set(ls.flatMap(l=>l.rel))];if(rel.length){add("h4","关系类型");add("div",rel.join("、"))}
 const src=[...new Set(ls.flatMap(l=>l.src))];if(src.length){add("h4","证据来源");add("div",src.join("、"))}
 for(const ty of ["disease","gene","pathway"]){const xs=[...nb[n.id]].map(i=>byId[i]).filter(o=>o.type===ty);if(!xs.length)continue;
  add("h4","关联"+TN[ty]+"（"+xs.length+"）");const box=document.createElement("div");xs.forEach(o=>{const s=document.createElement("span");s.className="nb";s.textContent=o.label.length>28?o.label.slice(0,27)+"…":o.label;s.onclick=()=>{show(o);center(o)};box.appendChild(s)});p.appendChild(box)}
 refresh()}
function center(n){view.x=innerWidth/2-n.x*view.k-150;view.y=innerHeight/2-n.y*view.k;apply()}
function bind(g,n){let sx,sy,moved;g.addEventListener("pointerdown",e=>{e.stopPropagation();g.setPointerCapture(e.pointerId);n.dragging=true;n.fixed=true;moved=false;sx=e.clientX;sy=e.clientY;alpha=Math.max(alpha,.3)});
 g.addEventListener("pointermove",e=>{if(!n.dragging)return;if(Math.abs(e.clientX-sx)+Math.abs(e.clientY-sy)>3)moved=true;n.x+=e.movementX/view.k;n.y+=e.movementY/view.k;draw()});
 g.addEventListener("pointerup",e=>{n.dragging=false;if(n.type!=="disease")n.fixed=false;if(!moved)show(n)});}
let pan=null;$("stage").addEventListener("pointerdown",e=>{pan={x:e.clientX,y:e.clientY};$("stage").classList.add("drag")});
addEventListener("pointermove",e=>{if(!pan)return;view.x+=e.clientX-pan.x;view.y+=e.clientY-pan.y;pan={x:e.clientX,y:e.clientY};apply()});
addEventListener("pointerup",()=>{pan=null;$("stage").classList.remove("drag")});
$("stage").addEventListener("dblclick",e=>{if(e.target.closest(".node"))return;sel=null;panel.style.display="none";refresh()});
$("stage").addEventListener("wheel",e=>{e.preventDefault();const f=Math.exp(-e.deltaY*.0015),k=Math.max(.15,Math.min(5,view.k*f));
 view.x=e.clientX-(e.clientX-view.x)*(k/view.k);view.y=e.clientY-(e.clientY-view.y)*(k/view.k);view.k=k;apply()},{passive:false});
$("task").onchange=e=>load(+e.target.value);$("q").oninput=e=>{q=e.target.value.trim().toLowerCase();refresh()};
$("fit").onclick=fit;$("pause").onclick=e=>{paused=!paused;e.target.textContent=paused?"继续布局":"暂停布局"};
$("types").onchange=e=>{const t=e.target.dataset.t;e.target.checked?hidden.delete(t):hidden.add(t);refresh()};
addEventListener("resize",fit);
if(DATA.length){load(+((location.hash.match(/t=(\d+)/)||[0,0])[1])<DATA.length?+((location.hash.match(/t=(\d+)/)||[0,0])[1]):0);$("task").value=String(+((location.hash.match(/t=(\d+)/)||[0,0])[1])<DATA.length?+((location.hash.match(/t=(\d+)/)||[0,0])[1]):0);tick()}else{document.body.insertAdjacentHTML("beforeend",'<div style="position:fixed;inset:0;display:grid;place-items:center;color:#9fb0d8">没有可展示的图谱数据</div>')}
</script></body></html>"""


def render_graph(rep):
    data = json.dumps(graph_data(rep.get("task_results") or []), ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__SAMPLE__", esc(str(rep.get("sample_id", "")))).replace("__DATA__", data)
