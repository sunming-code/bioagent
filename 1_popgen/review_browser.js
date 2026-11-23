(() => {
  const get = id => document.getElementById(id);
  const data = JSON.parse(get('chromosome-data').textContent);
  const fields = JSON.parse(get('review-fields').textContent);
  const col = Object.fromEntries(fields.map((name, i) => [name, i]));
  const chrom = get('review-chrom'), mode = get('review-mode'), limit = get('review-limit');
  const canvas = get('review-plot'), ctx = canvas.getContext('2d');
  const baseline = get('review-baseline'), total = Number(baseline.dataset.total);
  const chromosomes = Object.keys(data).sort((a,b) => a.localeCompare(b, 'en', {numeric:true}));
  const groups = [], blocks = [], lineCache = new Map();
  // Keep only plot/filter columns in memory. Decode full rows by block for the table and TSV.
  const pos = new Float64Array(total), af = new Float64Array(total), score = new Float64Array(total);
  const dp = new Float64Array(total), gq = new Float64Array(total), blockId = new Uint32Array(total);
  const details = get('review-details'), body = get('review-body');
  let visible = new Uint32Array(0), selected = -1;
  let mean = NaN, maxScore = 0, cut = NaN, ready = false, exporting = false, project;
  const numeric = v => v == null || v.trim() === '' || !Number.isFinite(+v) || +v < 0 ? NaN : +v;
  const frequency = v => { const n = numeric(v); return n <= 1 ? n : NaN; };
  const percent = n => Number.isFinite(n) ? Number((n * 100).toPrecision(5)) + '%' : '未知';
  const fmtScore = n => Number.isFinite(n) ? n.toFixed(3) : '—';
  const field = v => v === '' || v === '.' ? '未提供' : v;
  // Roundoff at the mean must not flag ties when a sample has identical frequencies.
  const above = n => n - mean > 1e-13 * Math.max(1, Math.abs(mean));

  async function unpack(b64) {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    return (await new Response(stream).text()).slice(0,-1).split('\n');
  }
  function linesFor(b) {
    if (!lineCache.has(b)) {
      if (lineCache.size >= 4) lineCache.delete(lineCache.keys().next().value);
      lineCache.set(b, unpack(b.encoded));
    }
    return lineCache.get(b);
  }
  async function rowAt(i) {
    const b = blocks[blockId[i]];
    return (await linesFor(b))[i-b.start].split('\t');
  }
  async function indexRows() {
    let n = 0, positive = 0, zeros = 0, sum = 0, correction = 0, extent = 0;
    for (const [order,name] of chromosomes.entries()) {
      const g = {name, order, start:n, extent:1, offset:extent};
      for (const encoded of data[name]) {
        const id = blocks.length;
        blocks.push({encoded, group:g, start:n});
        for (const line of await unpack(encoded)) {
          const r = line.split('\t');
          pos[n] = Number(r[col.POS]); g.extent = Math.max(g.extent, pos[n]);
          blockId[n] = id; dp[n] = numeric(r[col.DP]); gq[n] = numeric(r[col.GQ]);
          af[n] = frequency(r[col.matched_pop_AF]);
          score[n] = af[n] > 0 ? -Math.log10(af[n]) : NaN;
          if (af[n] > 0) {
            const term = score[n] - correction, next = sum + term;
            correction = (next - sum) - term; sum = next;
            positive++; maxScore = Math.max(maxScore, score[n]);
          } else if (af[n] === 0) zeros++;
          n++;
        }
      }
      g.end = n; extent += g.extent; groups.push(g); chrom.add(new Option(name, name));
    }
    if (n !== total) throw new Error('位点行数与报告不一致');
    mean = positive ? sum/positive : NaN;
    const aboveCount = score.reduce((count, s) => count + Number(above(s)), 0);
    const number = n => n.toLocaleString('en-US');
    baseline.textContent = (positive
      ? '全样本均值 ' + fmtScore(mean) + '（对应 ALT 频率 ' + percent(10 ** -mean) + '）。' +
        number(positive) + ' 个有正频率的携带记录中，' + number(aboveCount) + ' 个高于均值。'
      : '本样本没有可计算稀有度的正频率，均值无法估计。') +
      '参考频率为零 ' + number(zeros) + ' 个，未知或无效 ' + number(total-positive-zeros) + ' 个。';
    ready = true; filter();
  }
  async function select(j) {
    const list = visible, i = list[j];
    selected = j;
    details.hidden = true;
    body.replaceChildren();
    draw();
    const r = await rowAt(i);
    if (visible !== list || selected !== j) return;
    const tr = body.insertRow();
    const values = [
      r[col.CHROM]+':'+r[col.POS]+' '+r[col.REF]+'>'+r[col.ALT], r[col.GT],
      percent(af[i])+' / '+percent(frequency(r[col.global_AF])), fmtScore(score[i]),
      ['DP '+field(r[col.DP]), 'GQ '+field(r[col.GQ]), 'AD '+field(r[col.AD]),
       'AB '+field(r[col.heterozygous_AB]), 'QUAL '+field(r[col.QUAL]),
       'FILTER '+field(r[col.FILTER]), 'FT '+field(r[col.FT])].join(' · '),
      r[col.frequency_context]+' · '+r[col.quality_context]
    ];
    if (details.dataset.integrated==='yes') values.push(r[col.egene_context]||'未连接到已判级记录');
    for (const v of values) tr.insertCell().textContent = v;
    details.hidden = false;
  }
  function draw() {
    if (!ready) return;
    const w = Math.max(1,Math.round(canvas.getBoundingClientRect().width)), h=300;
    const dpr = window.devicePixelRatio||1;
    canvas.width=w*dpr; canvas.height=h*dpr; ctx.setTransform(dpr,0,0,dpr,0,0);
    const left=64,right=Math.max(left+1,w-12),top=25,bottom=198;
    const active=groups.find(g=>g.name===chrom.value);
    const last=groups[groups.length-1];
    const extent=active ? active.extent : last ? last.offset+last.extent : 1;
    const xScale=(right-left)/extent;
    const cutScore=cut>0 ? -Math.log10(cut) : NaN;
    const ymax=Math.max(1,Math.ceil(maxScore),Math.ceil(cutScore)||0);
    const y=s=>bottom-s/ymax*(bottom-top);
    project=i=>{
      const g=blocks[blockId[i]].group;
      return [left+((active?0:g.offset)+pos[i])*xScale, af[i]===0?221:Number.isFinite(score[i])?y(score[i]):241];
    };
    ctx.font='12px system-ui'; ctx.fillStyle='#364f61';
    ctx.fillText('稀有度  −log₁₀(AF)',6,13);
    function line(py,color,dash=[]) {
      ctx.strokeStyle=color; ctx.setLineDash(dash); ctx.beginPath(); ctx.moveTo(left,py); ctx.lineTo(right,py); ctx.stroke(); ctx.setLineDash([]);
    }
    for(let k=0;k<=4;k++) {
      const s=ymax*k/4;
      ctx.fillText(String(Number(s.toFixed(2))),8,y(s)+4); line(y(s),'#d9e1e5');
    }
    for(const [label,py] of [['参考零',221],['未知',241]]) {
      ctx.fillText(label,8,py+4); line(py,'#e0e5e8');
    }
    let lastLabel=-Infinity;
    for(const g of active?[active]:groups) {
      const startX=left+(active?0:g.offset)*xScale, mid=startX+g.extent*xScale/2;
      ctx.fillStyle='#465b67';ctx.textAlign='center';
      const label=active ? g.name+' · 0–'+g.extent.toLocaleString()+' bp' : g.name.replace(/^chr/i,'');
      const half=ctx.measureText(label).width/2;
      if(mid-half>lastLabel+2) { ctx.fillText(label,mid,268);lastLabel=mid+half; }
      if(!active) {ctx.fillStyle='#d4dee3';ctx.fillRect(startX,249,1,6);}
    }
    ctx.fillStyle='#465b67';ctx.fillText(active?'染色体坐标（GRCh38）':'染色体（GRCh38）',(left+right)/2,290);ctx.textAlign='left';
    if(Number.isFinite(mean)) line(y(mean),'#28557c',[6,4]);
    if(Number.isFinite(cutScore)) line(y(cutScore),'#b24c16');
    for(const i of visible) {
      const [px,py]=project(i), rare=af[i]>0 && af[i]<cut;
      ctx.fillStyle=!Number.isFinite(af[i])?'#919ba2':af[i]===0?'#825886':rare?'#b24c16':
        blocks[blockId[i]].group.order%2?'#668eae':'#27677c';
      const radius=rare?2.8:1.45;
      ctx.fillRect(px-radius,py-radius,2*radius,2*radius);
    }
    if(selected>=0 && selected<visible.length) {
      ctx.strokeStyle='#162833';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...project(visible[selected]),6,0,2*Math.PI);ctx.stroke();
    }
  }
  function settings() {
    return {chrom:chrom.value, mode:mode.value, limit:limit.value, dp:get('review-dp').value,
            gq:get('review-gq').value, keepMissing:get('review-keep-missing').checked};
  }
  function filter() {
    if(!ready) return;
    const s=settings(), threshold=limit.valueAsNumber/100;
    cut=Number.isFinite(threshold) && limit.validity.valid ? threshold : NaN;
    const validQuality=get('review-dp').validity.valid && get('review-gq').validity.valid;
    const keepQ=(v,min)=>min==='' || (Number.isFinite(v)?v>=Number(min):s.keepMissing);
    const range=groups.find(g=>g.name===s.chrom), start=range?range.start:0, end=range?range.end:total;
    const matches=new Uint32Array(end-start);
    let n=0, low=0;
    for(let i=start;i<end;i++) {
      if(!validQuality || !keepQ(dp[i],s.dp) || !keepQ(gq[i],s.gq)) continue;
      if(af[i]<cut) low++;
      if(s.mode==='above' && !above(score[i])) continue;
      if(s.mode==='low' && !(af[i]<cut)) continue;
      if(s.mode==='zero' && af[i]!==0) continue;
      if(s.mode==='unknown' && Number.isFinite(af[i])) continue;
      matches[n++]=i;
    }
    visible=matches.subarray(0,n);selected=-1;
    body.replaceChildren();details.hidden=true;
    get('review-cut-label').textContent=Number.isFinite(cut)
      ? '当前范围和质量条件下，AF < '+percent(cut)+' 共 '+low+' 个。'
      : '请输入 0–100 的有效百分比。';
    get('review-count').textContent='当前显示 '+n+' 个携带等位基因';
    get('review-export').disabled=exporting || !n;
    draw();
  }
  canvas.onclick=e=>{
    if(!project) return;
    const box=canvas.getBoundingClientRect(),x=e.clientX-box.left,y=e.clientY-box.top;
    let best=-1, nextOverlap=-1, distance=64;
    visible.forEach((i,j)=>{
      const [px,py]=project(i), d=(x-px)**2+(y-py)**2;
      if(d<distance) {
        distance=d;best=j;nextOverlap=-1;
      } else if(d===distance && best!==-1 && best<=selected && j>selected && nextOverlap===-1) {
        nextOverlap=j;
      }
    });
    if(best>=0) select(nextOverlap>=0 ? nextOverlap : best);
  };
  canvas.onkeydown=e=>{
    if(!visible.length || !['ArrowLeft','ArrowRight'].includes(e.key)) return;
    e.preventDefault();
    const last=visible.length-1;
    const j=e.key==='ArrowRight' ? Math.min(selected+1,last) : selected<0 ? last : Math.max(0,selected-1);
    select(j);
  };
  chrom.onchange=filter; mode.onchange=filter; limit.oninput=filter;
  get('review-dp').oninput=filter;get('review-gq').oninput=filter;get('review-keep-missing').onchange=filter;
  function download(parts,type,name) {
    const url=URL.createObjectURL(new Blob(parts,{type}));
    const link=document.createElement('a');link.href=url;link.download=name;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  get('review-export').onclick=async()=>{
    const indices=visible, s=settings(), columns=['rarity_neg_log10_af','sample_mean_rarity','above_sample_mean',
      'view_chromosome','view_mode','af_cutoff_percent','min_dp','min_gq','keep_missing_quality'];
    const parts=[[...fields,...columns].join('\t')+'\n'];
    exporting=true;get('review-export').disabled=true;
    try {
      let j=0;
      while(j<indices.length) {
        const b=blocks[blockId[indices[j]]], lines=await linesFor(b), part=[];
        while(j<indices.length && blocks[blockId[indices[j]]]===b) {
          const i=indices[j++], value=score[i];
          part.push([lines[i-b.start],Number.isFinite(value)?value:'',Number.isFinite(mean)?mean:'',
            Number.isFinite(value)?above(value):'',s.chrom||'all',s.mode,s.limit,s.dp,s.gq,s.keepMissing].join('\t')+'\n');
        }
        parts.push(part.join(''));
      }
      download(parts,'text/tab-separated-values;charset=utf-8','variant_review_'+(s.chrom||'all')+'_'+s.mode+'.tsv');
    } finally {exporting=false;get('review-export').disabled=!visible.length;}
  };
  get('review-save-all').onclick=async e=>{
    if(!window.CompressionStream)return;
    e.preventDefault();
    const name=e.currentTarget.getAttribute('href').split('/').pop();
    const header=new Blob([fields.join('\t')+'\n']).stream().pipeThrough(new CompressionStream('gzip'));
    const parts=[await new Response(header).arrayBuffer()];
    for(const blocks of Object.values(data))for(const b64 of blocks)parts.push(Uint8Array.from(atob(b64),c=>c.charCodeAt(0)));
    download(parts,'application/gzip',name);
  };
  window.addEventListener('resize',draw);
  indexRows().catch(()=>{get('review-count').textContent='浏览器无法读取内嵌数据，请下载完整 TSV。';});
})();
