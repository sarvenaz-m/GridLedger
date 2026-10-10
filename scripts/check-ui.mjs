/* Chromium checks against the actual static application; no network services. */
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {chromium} from 'playwright';

const base=process.env.GRIDLEDGER_UI_URL || 'http://127.0.0.1:8027';
const server=process.env.GRIDLEDGER_UI_URL ? null : spawn(process.env.PYTHON || 'python3',['-m','http.server','8027','--bind','127.0.0.1'],{stdio:'ignore'});
let browser;
try {
  let ready=false;
  for(let i=0;i<80;i++){
    try {if((await fetch(base)).ok){ready=true;break;}} catch {}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.ok(ready,'Local static server did not become ready.');
  browser=await chromium.launch({headless:true,...(process.env.GRIDLEDGER_BROWSER_PATH?{executablePath:process.env.GRIDLEDGER_BROWSER_PATH}:{}),args:['--no-sandbox']});
  const errors=[],failedRequests=[],surfaces=[];
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
    const page=await browser.newPage({viewport,acceptDownloads:true});
    page.on('pageerror',error=>errors.push(error.message));
    page.on('requestfailed',request=>failedRequests.push(request.url()));
    page.on('response',response=>{if(response.status()>=400)failedRequests.push(response.url()+' '+response.status());});
    await page.goto(base,{waitUntil:'networkidle'});
    assert.equal(await page.locator('body').getAttribute('data-page'),'real');
    assert.equal(await page.locator('#realMeter option').count(),20);
    assert.equal(await page.locator('#realHorizon option').count(),3);
    assert.equal(await page.locator('#realComparison tbody tr').count(),5);
    await page.locator('#realChart').focus();
    const before=await page.evaluate(()=>GridLedgerRealUI.cursor);
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.evaluate(()=>GridLedgerRealUI.cursor),before+1);
    await page.locator('#realHorizon').selectOption('24');
    assert.equal(await page.evaluate(()=>GridLedgerRealUI.horizon),24);
    assert.match(await page.locator('#realCoverageNote').textContent(),/87\.1%/);
    const actual=await page.locator('#realActual').textContent();
    await page.locator('#realStressToggle').click();
    assert.equal(await page.locator('#realStressToggle').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#realActual').textContent(),actual);
    await page.locator('#realMeter').selectOption('11');
    assert.equal(await page.evaluate(()=>GridLedgerRealUI.meter),'MT_012');
    await page.locator('#realMeter').selectOption('19');
    assert.equal(await page.evaluate(()=>GridLedgerRealUI.meter),'MT_020');
    await page.locator('#realVerify').click();
    await page.waitForFunction(()=>document.getElementById('realIntegrity').textContent.startsWith('✓'));
    const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#realExport').click()]);
    assert.equal(download.suggestedFilename(),'gridledger-uci-replay.csv');
    for(const name of ['workbench','evaluation','provenance','method','real']){
      await page.locator(`.nav[data-tab="${name}"]`).click();
      assert.equal(await page.locator('body').getAttribute('data-page'),name);
      const dimensions=await page.evaluate(()=>({content:document.documentElement.scrollWidth,viewport:innerWidth}));
      assert.ok(dimensions.content<=dimensions.viewport,`${name} overflows at ${viewport.width}px`);
    }
    await page.locator('.nav[data-tab="provenance"]').click();
    await page.locator('#tamperBtn').click();
    await page.waitForFunction(()=>document.getElementById('integrityStatus').classList.contains('error'));
    await page.locator('#restoreBtn').click();
    await page.waitForFunction(()=>!document.getElementById('integrityStatus').classList.contains('error'));
    await page.locator('.nav[data-tab="workbench"]').click();
    await page.locator('[data-preset="ev"]').click();
    assert.equal(await page.locator('#evRange').inputValue(),'120');
    await page.locator('#tourStart').click();
    for(let i=0;i<5;i++)await page.locator('#tourNext').click();
    assert.equal(await page.locator('#tourBar').isVisible(),false);
    await page.locator('.nav[data-tab="real"]').click();
    await page.locator('#realMeter').selectOption('0');
    await page.locator('#realHorizon').selectOption('1');
    await page.locator('#realStressToggle').click();
    assert.equal(await page.locator('#realStressToggle').getAttribute('aria-pressed'),'false');
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:`assets/real-${viewport.width<500?'mobile':'workbench'}.png`,fullPage:true});
    surfaces.push({viewport,real_clients:20,horizons:3,five_workspaces:true,keyboard_replay:true,
                   controlled_loss:true,export_download:true,real_ledger_verification:true,
                   synthetic_presets:true,synthetic_tamper_and_restore:true,five_step_tour:true,no_horizontal_overflow:true});
    await page.close();
  }
  assert.deepEqual(errors,[]);
  assert.deepEqual(failedRequests,[]);
  const result={version:'2.0.0',browser:await browser.version(),surfaces,page_errors:errors,failed_requests:failedRequests};
  await writeFile('results/ui-validation.json',JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));
} finally {
  await browser?.close();
  server?.kill();
}
