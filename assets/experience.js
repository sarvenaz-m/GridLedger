/* Guided exploration and hourly replay; all displayed values come from the model. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id),UI=window.GridLedgerUI;
 let timer=null,step=0;
 const setPreset=name=>{UI.preset(name);document.querySelectorAll('.preset').forEach(b=>{b.classList.toggle('active',b.dataset.preset===name);b.setAttribute('aria-pressed',String(b.dataset.preset===name));});};
 const clearPreset=()=>document.querySelectorAll('.preset').forEach(b=>{b.classList.remove('active');b.setAttribute('aria-pressed','false');});
 document.querySelectorAll('.preset').forEach(b=>b.onclick=()=>setPreset(b.dataset.preset));
 ['evRange','solarRange','thresholdRange','spikeBtn'].forEach(id=>$(id).addEventListener(id==='spikeBtn'?'click':'input',clearPreset));
 $('resetBtn').addEventListener('click',()=>setPreset('baseline'));
 function stop(){clearInterval(timer);timer=null;$('replayPlay').textContent='▶';$('replayPlay').setAttribute('aria-label','Play hourly replay');}
 function play(){if(timer){stop();return;}if(UI.cursor>=71)UI.inspect(0);$('replayPlay').textContent='Ⅱ';$('replayPlay').setAttribute('aria-label','Pause hourly replay');timer=setInterval(()=>{if(UI.cursor>=71){stop();return;}UI.inspect(UI.cursor+1);},+$('replaySpeed').value);}
 $('replayPlay').onclick=play;
 $('replayRange').oninput=()=>{stop();UI.inspect(+$('replayRange').value);};
 $('replaySpeed').onchange=()=>{if(timer){stop();play();}};
 $('forecastChart').addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();stop();UI.inspect(UI.cursor+(e.key==='ArrowRight'?1:-1));}});
 document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',stop));
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
 const steps=[
  {title:'Read the forecast',text:'Move across the chart, drag the time control or press play. Each point is a rolling one-hour forecast.',run:()=>{UI.tab('workbench');setPreset('baseline');UI.inspect(30);}},
  {title:'Stress the evening peak',text:'The EV preset adds 120 kW at the evening peak. Compare the net-load estimate with feeder capacity.',run:()=>{UI.tab('workbench');setPreset('ev');UI.inspect(43);}},
  {title:'Find a measurement anomaly',text:'A 45 kW meter spike is added at hour 55. Inspect the selected residual and orange alert marker.',run:()=>{UI.tab('workbench');setPreset('meter');}},
  {title:'Compare the models',text:'Review the held-out errors, chronological split and detector scores across all three feeders.',run:()=>UI.tab('evaluation')},
  {title:'Verify the prediction record',text:'Choose Test tampering to change a record, then Restore original to recover the valid chain.',run:()=>UI.tab('provenance')}
 ];
 function showStep(){stop();const s=steps[step];s.run();$('tourBar').hidden=false;$('tourStep').textContent=String(step+1).padStart(2,'0')+' / 05';$('tourTitle').textContent=s.title;$('tourText').textContent=s.text;$('tourBack').disabled=step===0;$('tourNext').textContent=step===4?'Finish tour ✓':'Next step →';$('tourNext').focus({preventScroll:true});$('tourBar').scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
 function close(){stop();$('tourBar').hidden=true;UI.tab('workbench');setPreset('baseline');$('tourStart').focus({preventScroll:true});}
 $('tourStart').onclick=()=>{step=0;showStep();};
 $('tourNext').onclick=()=>{if(step===4)close();else{step++;showStep();}};
 $('tourBack').onclick=()=>{if(step>0){step--;showStep();}};
 $('tourClose').onclick=close;
 $('exploreBtn').onclick=()=>{UI.tab('workbench');$('workbench').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});};
})();
