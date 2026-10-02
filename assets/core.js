(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GridLedger = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function predict(model, features) {
    if (features.length !== model.coef.length || features.some(x => !Number.isFinite(x))) throw Error('Invalid feature vector');
    return features.reduce((y,x,i) => y + (x-model.mean[i])/model.scale[i]*model.coef[i], model.intercept);
  }
  function scenario(feeder, {extraEV=0, solar=1, threshold=1, spike=false}={}) {
    return feeder.rows.map((r,i) => {
      const h=new Date(r.timestamp).getUTCHours();
      const extra=extraEV*Math.exp(-.5*((h-19)/2.2)**2);
      const forecast=predict(feeder.model,r.features);
      const measured=r.actual+(spike && i===feeder.rows.length-17 ? 45 : 0);
      const net=forecast+extra-r.pv*solar;
      return {...r,forecast,measured,net,extra,residual:Math.abs(measured-forecast),alert:Math.abs(measured-forecast)>feeder.metrics.anomaly_threshold_kw*threshold,overload:net>feeder.capacity};
    });
  }
  function canonical(value) {
    if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
    if (value!==null && typeof value==='object') return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
    return JSON.stringify(value);
  }
  async function digest(value) {
    if (!globalThis.crypto?.subtle) throw Error('SHA-256 requires HTTPS or localhost.');
    const data=new TextEncoder().encode(canonical(value));
    return Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',data))).map(x=>x.toString(16).padStart(2,'0')).join('');
  }
  async function append(chain,payload) {
    const body={index:chain.length,previous:chain.length?chain[chain.length-1].hash:'0'.repeat(64),payload};
    const record={...body,hash:await digest(body)};chain.push(record);return record;
  }
  async function verify(chain, checkpoint) {
    let previous='0'.repeat(64);
    if (!Array.isArray(chain)) return {ok:false,message:'Invalid record list'};
    for(let i=0;i<chain.length;i++) {
      const r=chain[i];
      if (!r || Object.keys(r).sort().join(',')!=='hash,index,payload,previous') return {ok:false,message:'Invalid record schema at '+i};
      if (r.index!==i || r.previous!==previous) return {ok:false,message:'Broken link at record '+i};
      if (r.hash!==await digest({index:r.index,previous:r.previous,payload:r.payload})) return {ok:false,message:'Payload changed at record '+i};
      previous=r.hash;
    }
    if(checkpoint && previous!==checkpoint) return {ok:false,message:'Checkpoint mismatch: chain rewritten or truncated'};
    return {ok:true,message:checkpoint?'Records match the saved checkpoint':'Internally consistent; external checkpoint not supplied'};
  }
  return {predict,scenario,canonical,digest,append,verify};
});
