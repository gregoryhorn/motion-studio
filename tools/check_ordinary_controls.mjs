// Explicit one-time authorized REAL normal UI check; never run by aggregate tests.
// No qualification scope/intents; the normal app APIs alone own admission and dispatch.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE);
const {expect} = require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
assert.equal(process.argv[2],'--run-one-real','Explicit one-real-control invocation required');
const journal = 'var/state/qs1-normal-browser-receipt.json';
assert.ok(!fs.existsSync(journal),'Existing ordinary receipt must not be replayed');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(),'motion-real-control-'));
const secret = crypto.randomBytes(32).toString('hex');
const secretFile = path.join(scratch,'temporary-owner');
fs.writeFileSync(secretFile,secret,{mode:0o600});
const historical = '6c3c47e1b5464d7e83254097c6b33f8e';
const historicalFile = `var/media/${historical}.wav`;
const beforeBytes = fs.readFileSync(historicalFile);
const port = await new Promise(resolve=>{
  const listener=net.createServer(); listener.listen(0,'127.0.0.1',()=>{
    const chosen=listener.address().port;listener.close(()=>resolve(chosen));
  });
});
const origin=`http://127.0.0.1:${port}`;
const log = fs.openSync('var/state/qs1-normal-server.log','wx',0o600);
const server=spawn('python',['-m','tools.ordinary_control_server','--state','var','--secret-file',secretFile,'--port',String(port)],{stdio:['ignore',log,log]});
let browser, context;
const checks=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
try {
  let ready=false;
  for(let n=0;n<600;n++) {
    if(server.exitCode!==null) throw new Error('Ordinary server blocked/exited; inspect private readiness receipt, never rerun blindly');
    try{if((await fetch(origin)).ok){ready=true;break;}}catch{}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.ok(ready,'Owned ordinary app did not become ready');
  const readiness=fs.readFileSync('var/state/qs1-normal-server.log','utf8').split('\n').filter(Boolean).map(line=>{try{return JSON.parse(line);}catch{return null;}}).find(value=>value?.readiness==='passed');
  assert.ok(readiness,'Fresh pin/resource/use readiness must precede controls');
  browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
  context=await browser.newContext({viewport:{width:1400,height:1100},acceptDownloads:true});
  const auth=await context.request.post(origin+'/api/login',{headers:{Origin:origin},data:{secret}});
  assert.ok(auth.ok());
  const initial=await(await context.request.get(origin+'/api/state')).json();
  const previous=initial.runs.find(run=>run.candidate===historical && run.status==='Ready for review');
  assert.ok(previous,'Known successful historical candidate must remain retained');
  // Obtain only the established controlled description through the owner's normal plan view.
  // No qualification operation/intent file is opened, copied or used as runtime authority.
  const original=await(await context.request.get(`${origin}/api/apps/plans/${previous.id}`)).json();
  assert.equal(original.parameters.seconds,3);assert.equal(original.parameters.seed,42);
  const page=await context.newPage();
  let pageErrors=0;
  page.on('pageerror',()=>pageErrors++);
  await page.goto(origin);
  await page.locator('#workspace').waitFor({state:'visible'});
  await page.getByRole('button',{name:'New request',exact:true}).click();
  await page.locator('#text').fill(original.direction);
  await page.locator('#purpose').fill('Noncommercial local technical evaluation; no publication or commercial clearance');
  await page.getByRole('button',{name:'Save request',exact:true}).click();
  await expect(page.locator('#save-state')).toContainText('Saved');
  const request=await page.evaluate(()=>localStorage.getItem('motion-active-request'));
  await page.locator('#app-method').selectOption(`${readiness.binding}:${readiness.binding_revision}:sfx`);
  await expect(page.locator('#generate')).toBeEnabled();
  check('normal UI exact 3s seed42 defaults',await page.locator('#sfx-seconds').inputValue()==='3' && await page.locator('#sfx-seed').inputValue()==='42');
  await page.locator('#generate').click();
  await expect(page.locator('#create-sfx')).toBeEnabled();
  const prepared=await(await context.request.get(origin+'/api/state')).json();
  const run=prepared.runs.find(run=>run.request===request);
  assert.ok(run && run.status==='Prepared');
  check('save select review cause no producer effect',!prepared.runs.some(value=>value.request===request && value.certainty!=='not attempted'));
  const receipt={version:1,request,run:run.id,candidate:run.candidate,historical_candidate:historical,
    source_manifest:readiness.source_manifest,binding:readiness.binding,binding_revision:readiness.binding_revision,
    stage:'Prepared',listening:'Not reviewed'};
  fs.writeFileSync(journal,JSON.stringify(receipt,null,2)+'\n',{mode:0o600,flag:'wx'});
  await page.locator('#create-sfx').click(); // The sole ordinary explicit Create action.
  let result, recovery, stable=0;
  for(let n=0;n<660;n++) {
    const state=await(await context.request.get(origin+'/api/state')).json();
    recovery=state.recovery.find(value=>value.request===request);
    result=state.runs.find(value=>value.id===(recovery?.successor||run.id));
    if(result && ['Ready for review','Failed','Blocked','Cancelled','Outcome unknown','Collection blocked'].includes(result.status) && !['Reserved','Applying'].includes(recovery?.state)) {
      stable++;
      if(stable>=3) break;
    } else stable=0;
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  assert.ok(result,'Ordinary result unavailable');
  receipt.result_run=result.id;receipt.result_candidate=result.candidate;receipt.status=result.status;
  receipt.recovery=recovery||null;receipt.stage='Observed';
  fs.writeFileSync(journal,JSON.stringify(receipt,null,2)+'\n',{mode:0o600});
  if(result.status!=='Ready for review') {
    console.log(JSON.stringify({scope:'One real ordinary-control check',status:result.status,reason:result.error,recovery_state:recovery?.state||null,checks,listening:'Not reviewed'},null,2));
    process.exitCode=1;
  } else {
    const originalBytes=await context.request.get(`${origin}/api/takes/${result.candidate}/media`);
    assert.ok(originalBytes.ok());
    const retained=fs.readFileSync(`var/media/${result.candidate}.wav`);
    check('authenticated scoped retrieval equals original WAV',retained.equals(await originalBytes.body()));
    await page.reload();
    await page.locator('#workspace').waitFor({state:'visible'});
    await expect(page.locator('#takes .take')).toHaveCount(initial.takes.length+1);
    const card=page.locator('#takes .take').filter({has:page.locator('audio[aria-label^="Candidate '+result.candidate+'"]')});
    await expect(card).toBeVisible();
    check('same-artifact browser reopen does not start another run',(await(await context.request.get(origin+'/api/state')).json()).runs.filter(value=>value.request===request).length===(recovery?.successor?2:1));
    check('generated technical and unreviewed labels',(await card.innerText()).includes('Generated - technical checks passed') && await card.locator('select').inputValue()==='Not reviewed');
    const downloadEvent=page.waitForEvent('download');
    await card.getByRole('button',{name:'Download original',exact:true}).click();
    const download=await downloadEvent;
    const destination='var/state/qs1-normal-downloaded.wav';
    assert.ok(!fs.existsSync(destination));
    await download.saveAs(destination);
    check('normal control download exact original bytes',fs.readFileSync(destination).equals(retained));
    const anonymous=await browser.newContext();
    const denied=await anonymous.request.get(`${origin}/api/takes/${result.candidate}/media`);
    check('unauthenticated retrieval refused',denied.status()===401);await anonymous.close();
    check('historical successful WAV unchanged',fs.readFileSync(historicalFile).equals(beforeBytes));
    check('ordinary real browser has no page errors',pageErrors===0);
    receipt.stage='Downloaded and reopened';receipt.checks=checks;receipt.bytes=retained.length;
    fs.writeFileSync(journal,JSON.stringify(receipt,null,2)+'\n',{mode:0o600});
    console.log(JSON.stringify({scope:'One real ordinary-control check',status:result.status,run:result.id,candidate:result.candidate,source_manifest:readiness.source_manifest,
      bytes:retained.length,checks,pageErrors,listening:'Not reviewed',recovery_state:recovery?.state||null},null,2));
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
  }
} finally {
  await context?.close();await browser?.close();
  if(server.exitCode===null){const done=new Promise(resolve=>server.once('exit',resolve));server.kill('SIGTERM');await done;}
  fs.closeSync(log);fs.rmSync(scratch,{recursive:true,force:true});
}
