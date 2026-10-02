/* Compile and exercise the real Solidity contract on an ephemeral local EVM. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const solc = require('solc');
const ganache = require('ganache');
const { ethers } = require('ethers');
async function main() {
  const root = path.resolve(__dirname, '..');
  const src = fs.readFileSync(path.join(root,'contracts/PredictionRegistry.sol'),'utf8');
  const input = { language:'Solidity', sources:{'PredictionRegistry.sol':{content:src}}, settings:{evmVersion:'shanghai', optimizer:{enabled:true,runs:200}, outputSelection:{'*':{'*':['abi','evm.bytecode.object']}}}};
  const output = JSON.parse(solc.compile(JSON.stringify(input)));
  for (const e of output.errors || []) if(e.severity==='error') throw Error(e.formattedMessage);
  const compiled = output.contracts['PredictionRegistry.sol'].PredictionRegistry;
  const engine = ganache.provider({logging:{quiet:true},wallet:{deterministic:true},chain:{chainId:1337,hardfork:'shanghai'}});
  const provider = new ethers.BrowserProvider(engine);
  const owner = await provider.getSigner(0), outsider = await provider.getSigner(1);
  const registry = await new ethers.ContractFactory(compiled.abi, compiled.evm.bytecode.object,owner).deploy();
  await registry.waitForDeployment();
  const ledger=JSON.parse(fs.readFileSync(path.join(root,'results/ledger.json'),'utf8'));
  const manifest=crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'results/manifest.json'))).digest('hex');
  const id=ethers.id('gridledger:run-42:checkpoint');
  const d='0x'+ledger.checkpoint, m='0x'+manifest;
  const checks=[];
  async function check(name, fn){await fn();checks.push({name,passed:true});console.log('PASS '+name);}
  await check('Owner starts as an authorized writer',async()=>assert.equal(await registry.writers(await owner.getAddress()),true));
  await check('Unauthorized writer cannot anchor',async()=>{await assert.rejects(registry.connect(outsider).anchor.staticCall(id,d,m));});
  await check('Zero digest is rejected',async()=>{await assert.rejects(registry.anchor.staticCall(id,ethers.ZeroHash,m));});
  await check('Prediction checkpoint and manifest are anchored',async()=>{await(await registry.anchor(id,d,m)).wait();const a=await registry.anchors(id);assert.equal(a.digest,d);assert.equal(a.manifest,m);assert.equal(a.writer,await owner.getAddress());assert.equal(await registry.count(),1n);});
  await check('Duplicate identifiers cannot overwrite history',async()=>{await assert.rejects(registry.anchor.staticCall(id,ethers.id('changed'),m));assert.equal((await registry.anchors(id)).digest,d);});
  await check('Only the owner may change writers',async()=>{await assert.rejects(registry.connect(outsider).setWriter.staticCall(await outsider.getAddress(),true));});
  await check('Granted writer may anchor a new prediction',async()=>{await(await registry.setWriter(await outsider.getAddress(),true)).wait();await(await registry.connect(outsider).anchor(ethers.id('second'),d,m)).wait();assert.equal(await registry.count(),2n);});
  await check('Revocation blocks further writes',async()=>{await(await registry.setWriter(await outsider.getAddress(),false)).wait();await assert.rejects(registry.connect(outsider).anchor.staticCall(ethers.id('third'),d,m));});
  fs.writeFileSync(path.join(root,'results/evm-test.json'),JSON.stringify({environment:'ephemeral local Ganache EVM',compiler:solc.version(),chain_id:1337,contract_sha256:crypto.createHash('sha256').update(src).digest('hex'),anchored_checkpoint:ledger.checkpoint,manifest_sha256:manifest,checks},null,2)+'\n');
  await engine.disconnect();
}
main().catch(e=>{console.error(e);process.exitCode=1;});
