/* Real UCI results, frozen Ridge inference and clock-aware replay. */
(() => {
  'use strict';
  const D=window.GRIDLEDGER_REAL,G=window.GridLedger,$=id=>document.getElementById(id);
  let meterIndex=0,horizon=1,stress=false,cursor=24;
  const num=(value,digits=3)=>value.toLocaleString('en-US',{maximumFractionDigits:digits,minimumFractionDigits:digits});
  const pct=value=>num(value*100,1)+'%';
  const entry=()=>D.meters[meterIndex].horizons[String(horizon)];
  const geometry=()=>window.innerWidth<=760?{width:360,left:37,right:346}:{width:900,left:52,right:878};
  const clock=value=>value.slice(8,10)+' '+['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+value.slice(5,7)-1]+' '+value.slice(0,4)+' · '+value.slice(11,16);
  function chart() {
    const e=entry(),rows=e.rows,q=e.metrics.intervals.Ridge.half_width_kw;
    const predictions=rows.map(r=>stress?r.stress_prediction:G.predict(e.model,r.features));
    const maximum=Math.max(...rows.map((r,i)=>Math.max(r.actual,r.seasonal,predictions[i]+q)))*1.06;
    const geom=geometry(),x=i=>geom.left+i/71*(geom.right-geom.left),y=value=>248-Math.max(0,value)/maximum*218;
    $('realChart').setAttribute('viewBox',`0 0 ${geom.width} 290`);
    let svg='';
    for(let i=0;i<5;i++){
      const value=maximum*i/4,yy=y(value);
      svg+=`<line x1="${geom.left}" x2="${geom.right}" y1="${yy}" y2="${yy}" stroke="#28394f"/><text x="${geom.left-10}" y="${yy+4}" text-anchor="end" fill="#8fa5c4" font-size="11">${num(value,maximum<20?1:0)}</text>`;
    }
    const upper=predictions.map((p,i)=>`${x(i)},${y(p+q)}`).join(' ');
    const lower=predictions.map((p,i)=>`${x(i)},${y(p-q)}`).reverse().join(' ');
    svg+=`<polygon points="${upper} ${lower}" fill="#4ee2d0" opacity=".10"/>`;
    const line=(values,color,dash='')=>`<polyline points="${values.map((p,i)=>`${x(i)},${y(p)}`).join(' ')}" stroke="${color}" stroke-width="2.4" fill="none" ${dash?`stroke-dasharray="${dash}"`:''}/>`;
    svg+=line(rows.map(r=>r.seasonal),'#ffae73','5 5')+line(rows.map(r=>r.actual),'#97b0ff')+line(predictions,'#4ee2d0');
    for(const i of (geom.width===360?[0,36,71]:[0,24,48,71]))svg+=`<text x="${x(i)}" y="278" text-anchor="${i===0?'start':i===71?'end':'middle'}" fill="#8fa5c4" font-size="11">${rows[i].target.slice(5,10)}${geom.width===360?'':' '+rows[i].target.slice(11,16)}</text>`;
    svg+=`<line id="realCursor" x1="${x(cursor)}" x2="${x(cursor)}" y1="20" y2="248" stroke="#dce5f9" stroke-dasharray="3 4" opacity=".6"/>`;
    $('realChart').innerHTML=svg;
    $('realChart').setAttribute('aria-label',`${D.meters[meterIndex].id}, ${horizon}-hour horizon. Observed power, frozen Ridge ${stress?'with controlled input loss':'forecast'}, weekly baseline and calibrated band.`);
  }
  function inspect(index) {
    cursor=Math.max(0,Math.min(71,index));
    const e=entry(),r=e.rows[cursor],prediction=stress?r.stress_prediction:G.predict(e.model,r.features);
    $('realRange').value=cursor;
    $('realReadingTime').textContent=clock(r.target);
    $('realOrigin').textContent=clock(r.origin);
    $('realTarget').textContent=clock(r.target);
    $('realActual').textContent=num(r.actual,2)+' kW';
    $('realPrediction').textContent=num(prediction,2)+' kW';
    $('realResidual').textContent=num(Math.abs(r.actual-prediction),2)+' kW';
    const marker=$('realCursor'),geom=geometry(),x=geom.left+cursor/71*(geom.right-geom.left);if(marker){marker.setAttribute('x1',x);marker.setAttribute('x2',x);}
  }
  function comparison() {
    const summary=D.summary.filter(r=>r.horizon_hours===horizon).sort((a,b)=>a.macro_mase-b.macro_mase);
    const body=$('realComparison').querySelector('tbody');body.textContent='';
    const baseline=summary.find(r=>r.model==='Seasonal 168h').macro_mase;
    for(const row of summary){
      const tr=document.createElement('tr');
      const improvement=(1-row.macro_mase/baseline)*100;
      tr.innerHTML=`<td>${row.model}</td><td>${num(row.macro_mase)}</td><td>${num(row.stress_macro_mase)}</td><td>${row.coverage===undefined?'—':pct(row.coverage)}</td><td>${row.model==='Seasonal 168h'?'Reference':num(improvement,1)+'%'}</td>`;
      body.append(tr);
    }
    const c=D.contrasts.find(r=>r.horizon_hours===horizon&&r.left==='Gradient boosting'&&r.right==='Seasonal 168h');
    $('realContrast').textContent=`Daily scaled error difference (boosting − weekly): ${num(c.mean_daily_scaled_error_difference)}. 95% block interval: [${num(c.bootstrap_95_low)}, ${num(c.bootstrap_95_high)}]. Negative values favor boosting.`;
    const boosting=summary.find(r=>r.model==='Gradient boosting');
    $('realCoverageNote').textContent=`Boosting's nominal 90% band covered ${pct(boosting.coverage)} of observed targets at this horizon; ${pct(boosting.stress_coverage)} under input loss. Calibration does not guarantee future coverage.`;
  }
  function render() {
    const e=entry(),m=e.metrics;
    $('realMae').textContent=num(m.models.Ridge.mae_kw,2);
    $('realBaselineMae').textContent=num(m.models['Seasonal 168h'].mae_kw,2);
    $('realCoverage').textContent=pct(m.intervals.Ridge.coverage);
    $('realStressMae').textContent=num(m.stress_models.Ridge.mae_kw,2);
    $('realSelection').textContent=`${D.meters[meterIndex].id} · ${horizon}-hour horizon · final fold test period`;
    $('realChartNote').textContent=stress?'Controlled input loss; original observed targets and frozen calibration band.':'Ridge inference runs locally from exported coefficients. Earlier observations become available at each new origin.';
    $('realStressToggle').setAttribute('aria-pressed',String(stress));
    $('realStressToggle').textContent=stress?'Input loss: on':'Input loss: off';
    $('realStressToggle').classList.toggle('selected',stress);
    $('realModelDigest').textContent=e.model_sha256;
    $('realValidTargets').textContent=m.n_test.toLocaleString('en-US');
    chart();inspect(cursor);comparison();
  }
  async function verifyRecords() {
    const result=await G.verify(D.chain,D.checkpoint);
    $('realIntegrity').textContent=(result.ok?'✓ ':'! ')+`${D.chain.length} real-data records · `+result.message;
    $('realIntegrity').classList.toggle('error',!result.ok);
    return result;
  }
  for(const [i,meter] of D.meters.entries())$('realMeter').add(new Option(meter.id,i));
  for(const h of D.horizons)$('realHorizon').add(new Option(h+(h===1?' hour':' hours'),h));
  $('realMeter').onchange=()=>{meterIndex=+$('realMeter').value;render();};
  $('realHorizon').onchange=()=>{horizon=+$('realHorizon').value;render();};
  $('realStressToggle').onclick=()=>{stress=!stress;render();};
  $('realRange').oninput=()=>inspect(+$('realRange').value);
  $('realChart').addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();inspect(cursor+(event.key==='ArrowRight'?1:-1));}});
  $('realChart').addEventListener('pointermove',event=>{const rect=$('realChart').getBoundingClientRect(),geom=geometry();const px=(event.clientX-rect.left)/rect.width*geom.width;inspect(Math.round((px-geom.left)/(geom.right-geom.left)*71));});
  $('realVerify').onclick=()=>verifyRecords().catch(error=>{$('realIntegrity').textContent=error.message;});
  $('realExport').onclick=()=>{
    const e=entry();const rows=['origin_provider_clock,target_provider_clock,meter,horizon_hours,actual_kw,ridge_kw,weekly_kw,input_loss'];
    for(const r of e.rows)rows.push([r.origin,r.target,D.meters[meterIndex].id,horizon,r.actual,stress?r.stress_prediction:G.predict(e.model,r.features),r.seasonal,stress].join(','));
    const blob=new Blob([rows.join('\n')+'\n'],{type:'text/csv'}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='gridledger-uci-replay.csv';a.click();URL.revokeObjectURL(url);
  };
  render();
  window.addEventListener('resize',()=>{chart();inspect(cursor);});
  window.GridLedgerRealUI={render,inspect,verifyRecords,get horizon(){return horizon;},get meter(){return D.meters[meterIndex].id;},get cursor(){return cursor;},get stress(){return stress;}};
})();
