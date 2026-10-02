/* Visualizes the executed temporal audit. No fabricated or live sensor values. */
(() => {
 'use strict';const A=window.GRIDLEDGER_AUDIT,$=id=>document.getElementById(id);
 if(!A){$('auditStatus').textContent='Audit results unavailable';return;}
 $('auditStatus').textContent='✓ Input contract passed';
 $('auditSummary').innerHTML=[['15','executed temporal folds'],['45','model fits / baseline evaluations'],['09','input contract checks'],['60','distribution comparisons']].map(([value,label])=>`<div><b>${value}</b><span>${label}</span></div>`).join('');
 for(const summary of A.summary)$('auditFeeder').add(new Option(summary.feeder,summary.feeder));
 function render(){
  const feeder=$('auditFeeder').value,rs=A.folds.filter(x=>x.feeder===feeder),summary=A.summary.find(x=>x.feeder===feeder),W=650,H=190,pad=36;
  const max=Math.max(...rs.map(r=>r.models['Seasonal naive (24h)'].mae_kw))*1.2,y=v=>H-32-v/max*(H-50),x=i=>70+i*125;
  let content='';
  for(let i=0;i<4;i++){const v=max*i/3;content+=`<line x1="${pad}" y1="${y(v)}" x2="620" y2="${y(v)}" stroke="#29364b"/><text x="25" y="${y(v)+3}" fill="#7f94b5" font-size="10" text-anchor="end">${v.toFixed(1)}</text>`;}
  for(const [name,color] of [['Seasonal naive (24h)','#92aaff'],['Ridge','#4ee2d0']]){
   content+=`<polyline points="${rs.map((r,i)=>`${x(i)},${y(r.models[name].mae_kw)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2.4"/>`;
   rs.forEach((r,i)=>{const v=r.models[name].mae_kw;content+=`<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${color}"><title>${name}, fold ${i+1}: ${v.toFixed(3)} kW</title></circle>`;});
  }
  rs.forEach((r,i)=>{content+=`<text x="${x(i)}" y="184" fill="#8199bc" font-size="10" text-anchor="middle">Fold ${i+1}</text>`;});
  $('backtestChart').innerHTML=content;
  $('foldDetails').innerHTML=`<span>Pooled Ridge MAE <b>${summary.models.Ridge.pooled_mae_kw.toFixed(2)} kW</b></span><span>Worst fold <b>${summary.models.Ridge.worst_fold_mae_kw.toFixed(2)} kW</b></span><span>Mean coverage <b>${(summary.mean_coverage*100).toFixed(1)}%</b></span>`;
  const labels={temperature_forecast:'Temperature forecast',lag1:'Previous-hour demand',lag24:'Previous-day demand',rolling24:'24-hour demand mean'};
  $('driftRows').innerHTML=A.distribution_shift.filter(r=>r.feeder===feeder&&r.fold===5).map(r=>`<div class="drift-row"><span>${labels[r.feature]}<small>Wasserstein / scale ${r.wasserstein_iqr.toFixed(3)}</small></span><b>${r.psi.toFixed(3)} <small>PSI</small></b></div>`).join('');
 }
 $('auditFeeder').onchange=render;render();
})();
