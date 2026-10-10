const assert = require('node:assert/strict');
const fs = require('node:fs');
const G = require('../assets/core.js');
const D = JSON.parse(fs.readFileSync('assets/real-data.json', 'utf8'));

async function main() {
  let checked = 0, max = 0;
  for (const meter of D.meters) {
    for (const [horizon, entry] of Object.entries(meter.horizons)) {
      assert.equal(entry.rows.length, 72);
      for (const row of entry.rows) {
        const difference = Math.abs(G.predict(entry.model, row.features) - row.prediction);
        assert.ok(difference < 1e-8, `${meter.id}: Python/JS mismatch`);
        max = Math.max(max, difference);
        // Treat clock labels as arithmetic strings here, without claiming a UTC timezone.
        const delta = Date.parse(row.target + 'Z') - Date.parse(row.origin + 'Z');
        assert.equal(delta, (+horizon - 1) * 3600000);
        checked++;
      }
    }
  }
  assert.equal(checked, 4320);
  assert.equal((await G.verify(D.chain, D.checkpoint)).ok, true);
  assert.equal(D.chain.length, 60);
  const changed = structuredClone(D.chain);
  changed[0].payload.horizon_hours++;
  assert.equal((await G.verify(changed, D.checkpoint)).ok, false);
  assert.equal((await G.verify(D.chain.slice(1), D.checkpoint)).ok, false);
  const m = D.meters[0].horizons['1'].model;
  assert.throws(() => G.predict(m, []));
  assert.throws(() => G.predict({...m, scale: m.scale.map(()=>0)}, D.meters[0].horizons['1'].rows[0].features));
  assert.equal(G.predict({coef:[1],mean:[0],scale:[1],intercept:-5,clip_min:0},[1]),0);
  const result = {status:'passed', predictions_checked:checked, max_absolute_error_kw:max,
                  real_ledger_records:60, tampering_detected:true, horizon_alignment:true,
                  nonnegative_python_js_clipping:true, invalid_inputs_rejected:true};
  fs.writeFileSync('results/real-browser-validation.json',JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
