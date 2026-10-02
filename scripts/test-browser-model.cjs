const assert=require('node:assert/strict');
const fs=require('node:fs');
const G=require('../assets/core.js');
const D=JSON.parse(fs.readFileSync('assets/demo-data.json','utf8'));
async function main(){
 let max=0;for(const f of D.feeders)for(const r of f.rows){const error=Math.abs(G.predict(f.model,r.features)-r.prediction);max=Math.max(error,max);assert.ok(error<1e-8);}
 assert.equal((await G.verify(D.chain,D.checkpoint)).ok,true);
 const tampered=structuredClone(D.chain);tampered[0].payload.prediction_watts++;
 assert.equal((await G.verify(tampered,D.checkpoint)).ok,false);
 const f=D.feeders[0],normal=G.scenario(f),shift=G.scenario(f,{extraEV:120,solar:0});
 assert.ok(Math.max(...shift.map(r=>r.net))>Math.max(...normal.map(r=>r.net)));
 assert.ok(shift.some(r=>r.overload));
 const spike=G.scenario(f,{spike:true});assert.ok(spike[55].residual>normal[55].residual);
 console.log(JSON.stringify({predictions_checked:216,max_absolute_error:max,python_js_ledger_parity:true,tamper_detected:true,scenario_response:true}));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
