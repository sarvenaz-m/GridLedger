/* UI for the exported, executed experiment. No external services or API keys. */
(() => {
'use strict';
const D=window.GRIDLEDGER_DATA, G=window.GridLedger;
const $=id=>document.getElementById(id);
let selected=0,spike=false,chain=structuredClone(D.chain),checkpoint=D.checkpoint,rows=[],cursor=54,chartScales={};
let originalChain=structuredClone(chain),originalHead=checkpoint;
const fnum=(x,d=1)=>Number(x).toFixed(d);
const pct=x=>fnum(x*100,1)+'%';
const short=x=>x.slice(0,10)+'…'+x.slice(-6);
const state=()=>({extraEV:+$('evRange').value,solar:+$('solarRange').value/100,threshold:+$('thresholdRange').value/100,spike});
function save(name,text,mime='application/json') {
  const url=URL.createObjectURL(new Blob([text],{type:mime}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function chart(id,rs,kind) {
  const svg=$(id),W=Math.max(300,Math.round(svg.getBoundingClientRect().width)||820),H=kind==='forecast'?270:180,pad={l:43,r:14,t:18,b:34};
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const m=D.feeders[selected].metrics,cap=D.feeders[selected].capacity;
  let max=kind==='forecast'?Math.max(...rs.map(r=>Math.max(r.measured,r.forecast+m.interval_half_width_kw)))*1.13:Math.max(cap*1.08,...rs.map(r=>r.net*1.14));
  const min=kind==='forecast'?Math.max(0,Math.min(...rs.map(r=>Math.min(r.measured,r.forecast-m.interval_half_width_kw)))-10):Math.min(0,...rs.map(r=>r.net));
  const x=i=>pad.l+i/(rs.length-1)*(W-pad.l-pad.r),y=v=>H-pad.b-(v-min)/(max-min)*(H-pad.t-pad.b);
  const points=fn=>rs.map((r,i)=>`${x(i).toFixed(2)},${y(fn(r)).toFixed(2)}`).join(' ');
  chartScales[id]={x,y,W,H,pad};
  let html='';
  for(let j=0;j<=4;j++){const v=min+(max-min)*j/4;html+=`<line x1="${pad.l}" y1="${y(v)}" x2="${W-pad.r}" y2="${y(v)}" stroke="#253044" stroke-width="1"/><text x="${pad.l-9}" y="${y(v)+3}" text-anchor="end" fill="#7e91ad" font-size="10">${Math.round(v)}</text>`;}
  for(let i=0;i<rs.length;i+=12){const t=new Date(rs[i].timestamp);const label=t.getUTCHours()===0?`${t.getUTCDate()} Jun`:`${String(t.getUTCHours()).padStart(2,'0')}:00`;html+=`<text x="${x(i)}" y="${H-11}" text-anchor="middle" fill="#7e91ad" font-size="10">${label}</text>`;}
  if(kind==='forecast'){
    const band=points(r=>r.forecast+m.interval_half_width_kw)+' '+rs.map((r,i)=>`${x(i)},${y(r.forecast-m.interval_half_width_kw)}`).reverse().join(' ');
    html+=`<polygon points="${band}" fill="#17464f" opacity=".8"/><polyline points="${points(r=>r.measured)}" fill="none" stroke="#92aaff" stroke-width="1.6"/><polyline points="${points(r=>r.forecast)}" fill="none" stroke="#4ee2d0" stroke-width="2.1"/>`;
    rs.forEach((r,i)=>{if(r.alert)html+=`<circle cx="${x(i)}" cy="${y(r.measured)}" r="3.6" fill="#ffae73" stroke="#101724" stroke-width="1.2"><title>${r.timestamp}: residual ${fnum(r.residual)} kW</title></circle>`;});
  } else {
    html+=`<polygon points="${x(0)},${y(0)} ${points(r=>r.net)} ${x(rs.length-1)},${y(0)}" fill="#123942"/><polyline points="${points(r=>r.net)}" fill="none" stroke="#4ee2d0" stroke-width="2"/><line x1="${pad.l}" x2="${W-pad.r}" y1="${y(cap)}" y2="${y(cap)}" stroke="#ffae73" stroke-width="1.2" stroke-dasharray="5 5"/><text x="${W-pad.r-1}" y="${y(cap)-7}" text-anchor="end" fill="#ffae73" font-size="10">${cap} kW capacity</text>`;
  }
  svg.innerHTML=html;
  if(kind==='forecast'){
    svg.insertAdjacentHTML('beforeend','<g id="chartCursor"><line stroke="#8ea7ff" stroke-dasharray="4 5"/><circle r="4.5" fill="#4ee2d0" stroke="#101724" stroke-width="2"/></g>');
    svg.onpointermove=e=>{const box=svg.getBoundingClientRect();const px=(e.clientX-box.left)*W/box.width;inspect(Math.max(0,Math.min(71,Math.round((px-pad.l)/(W-pad.l-pad.r)*71))));};
  }
}
function inspect(index){
  cursor=Math.max(0,Math.min(71,index));const r=rows[cursor];if(!r)return;
  const scale=chartScales.forecastChart,node=$('chartCursor');
  if(node&&scale){const {x,y,H,pad}=scale;const line=node.querySelector('line');line.setAttribute('x1',x(cursor));line.setAttribute('x2',x(cursor));line.setAttribute('y1',pad.t);line.setAttribute('y2',H-pad.b);const dot=node.querySelector('circle');dot.setAttribute('cx',x(cursor));dot.setAttribute('cy',y(r.forecast));}
  if($('replayRange')){$('replayRange').value=cursor;$('replayTime').textContent=new Date(r.timestamp).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'UTC'})+' UTC';$('readingForecast').textContent=fnum(r.forecast,1)+' kW';$('readingMeasured').textContent=fnum(r.measured,1)+' kW';$('readingResidual').textContent=fnum(r.residual,1)+' kW';$('readingState').textContent=r.alert?'Residual alert':'Within threshold';$('readingState').classList.toggle('alert',r.alert);}
}
function render(){
  const f=D.feeders[selected],s=state();rows=G.scenario(f,s);
  $('evValue').textContent=s.extraEV+' kW';$('solarValue').textContent=Math.round(s.solar*100)+'%';$('thresholdValue').textContent=fnum(s.threshold)+'×';
  $('mae').textContent=fnum(f.metrics.forecast_clean_hours.Ridge.mae_kw,2);
  $('coverage').textContent=pct(f.metrics.coverage_clean);
  $('alerts').textContent=rows.filter(r=>r.alert).length.toString().padStart(2,'0');
  const headroom=f.capacity-Math.max(...rows.map(r=>r.net));$('headroom').textContent=fnum(headroom)+' kW';
  $('headroom').style.color=headroom<0?'#ffae73':'';
  const violations=rows.filter(r=>r.overload).length;
  $('scenarioResult').textContent=violations?`${violations} of 72 hours exceed the aggregate capacity.`:'All 72 hours remain within the aggregate capacity.';
  $('scenarioResult').classList.toggle('warn',violations>0);
  $('spikeBtn').classList.toggle('selected',spike);$('spikeBtn').textContent=spike?'− Remove meter spike':'+ Inject a meter spike';
  $('modelHash').textContent=short(f.model_sha256);$('datasetHash').textContent=short(D.dataset_sha256);
  $('chartNote').textContent=spike?'A +45 kW meter spike is applied at replay hour 55.':'Forecast recalculated from exported model weights in your browser.';
  chart('forecastChart',rows,'forecast');chart('netChart',rows,'net');
  inspect(cursor);
}
function evaluation(){
  const body=$('metricsTable').querySelector('tbody');body.textContent='';
  for(const f of D.feeders){for(const [name,m] of Object.entries(f.metrics.forecast_clean_hours)){
    const tr=document.createElement('tr');const baseline=f.metrics.forecast_clean_hours['Seasonal naive (24h)'].mae_kw;
    tr.innerHTML=`<td><span class="model-name">${name}</span><br><span class="subtle">${f.id} · ${f.name}</span></td><td>${fnum(m.mae_kw,2)}</td><td>${fnum(m.rmse_kw,2)}</td><td class="gain">${name.startsWith('Seasonal')?'Reference':fnum((1-m.mae_kw/baseline)*100,1)+'% lower MAE'}</td>`;body.append(tr);
  }}
  $('detectorScores').innerHTML=D.feeders.map(f=>`<div class="score-row"><span>${f.name}<br><span class="subtle">${f.metrics.injected_hours} injected hours · ${f.metrics.alert_hours} alerts</span></span><span>Precision <b>${pct(f.metrics.anomaly_precision)}</b><br>Recall <b>${pct(f.metrics.anomaly_recall)}</b></span></div>`).join('');
}
function ledger(){
  $('ledgerCards').innerHTML=chain.map((r,i)=>`<article class="ledger-card"><span class="record-no">${i+1}</span><div><h3>${r.payload.feeder} · ${fnum(r.payload.prediction_watts/1000,2)} kW · ${r.payload.timestamp}</h3><p>Record ${r.hash}</p><p>Previous ${r.previous}</p><p>Model ${r.payload.model_sha256}</p></div></article>`).join('');
}
async function verify(){
  try {const result=await G.verify(chain,checkpoint);$('integrityStatus').textContent=(result.ok?'✓ ':'! ')+result.message;$('integrityStatus').classList.toggle('error',!result.ok);return result;}catch(e){$('integrityStatus').textContent=e.message;$('integrityStatus').classList.add('error');return {ok:false};}
}
function tab(name){document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===name));document.querySelectorAll('.nav').forEach(x=>{x.classList.toggle('active',x.dataset.tab===name);x.setAttribute('aria-current',x.dataset.tab===name?'page':'false');});$('pageName').textContent={workbench:'WORKBENCH',evaluation:'MODEL EVALUATION',provenance:'PROVENANCE',method:'METHOD & EVIDENCE'}[name];document.body.dataset.page=name;if(name==='provenance'){ledger();void verify();}if(name==='workbench')render();}
for(const [i,f] of D.feeders.entries()){$('feederSelect').add(new Option(f.id+' / '+f.name,i));}
$('feederSelect').onchange=()=>{selected=+$('feederSelect').value;render();};
for(const id of ['evRange','solarRange','thresholdRange'])$(id).oninput=render;
$('spikeBtn').onclick=()=>{spike=!spike;render();};
$('resetBtn').onclick=()=>{$('evRange').value=0;$('solarRange').value=100;$('thresholdRange').value=100;spike=false;render();};
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
$('exportBtn').onclick=()=>{const header='timestamp,feeder,measured_kw,forecast_kw,pv_kw,additional_ev_kw,scenario_net_kw,alert,over_capacity';const text=header+'\n'+rows.map(r=>[r.timestamp,D.feeders[selected].id,r.measured,r.forecast,r.pv*state().solar,r.extra,r.net,r.alert,r.overload].join(',')).join('\n');save('gridledger-scenario.csv',text,'text/csv');};
$('recordBtn').onclick=async()=>{
  const b=$('recordBtn');b.disabled=true;
  try {
    const valid=await G.verify(chain,checkpoint);if(!valid.ok)throw Error('Restore the original ledger before appending.');
    const f=D.feeders[selected],r=rows[rows.length-1];
    await G.append(chain,{schema:'gridledger.prediction.v1',feeder:f.id,timestamp:r.timestamp,prediction_watts:Math.round(r.forecast*1000),model_sha256:f.model_sha256,dataset_sha256:D.dataset_sha256,anomaly:r.alert});
    checkpoint=chain[chain.length-1].hash;originalChain=structuredClone(chain);originalHead=checkpoint;
    $('recordStatus').textContent='Recorded. The Provenance tab now contains '+chain.length+' verifiable records. Export to keep this session.';ledger();
  }catch(e){$('recordStatus').textContent=e.message;}finally{b.disabled=false;}
};
$('verifyBtn').onclick=verify;
$('tamperBtn').onclick=async()=>{chain[0].payload.prediction_watts+=1000;ledger();await verify();};
$('restoreBtn').onclick=async()=>{chain=structuredClone(originalChain);checkpoint=originalHead;ledger();await verify();};
$('exportLedger').onclick=()=>save('gridledger-ledger.json',JSON.stringify({records:chain,checkpoint},null,2));
render();evaluation();ledger();
window.GridLedgerUI={inspect,tab,get cursor(){return cursor;},get rows(){return rows;},preset(name){const values={baseline:[0,100,false],ev:[120,70,false],solar:[30,20,false],meter:[0,100,true]}[name];if(!values)return;$('evRange').value=values[0];$('solarRange').value=values[1];$('thresholdRange').value=100;spike=values[2];render();if(spike)inspect(55);}};
window.addEventListener('resize',()=>{if($('workbench').classList.contains('active'))render();});
})();
