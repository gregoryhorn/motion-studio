// R01/R02 real browser setup-only regressions; controlled holds/rejections, no Create.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_PACKAGE);
const {expect}=require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
const label=process.argv.includes('--red')?'red':'final';
const evidence='docs/evidence/tc1-ui';
fs.mkdirSync(evidence,{recursive:true});
const home=fs.mkdtempSync(path.join(os.tmpdir(),'motion-tool-identity-'));
const secret=crypto.randomBytes(32).toString('hex');
fs.writeFileSync(path.join(home,'test-secret'),secret,{mode:0o600});
const origin='http://127.0.0.1:18773';
const server=spawn('python',['-m','tests.template_server','--home',home,'--port','18773'],{stdio:'ignore'});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const checks=[],cases=[],errors=[];
const target=index=>path.join(home,'tools',['lumen-tone','ripple-forge'][index],'tool');
const document=index=>fs.readFileSync(path.join(home,`document-${index}.json`));
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
const same=(actual,expected)=>{assert.deepEqual(actual,expected);return true;};
const effectCount=()=>[0,1].map(index=>{
  const file=path.join(path.dirname(target(index)),'effects.jsonl');
  return fs.existsSync(file)?fs.readFileSync(file,'utf8').trim().split('\n').length:0;
});
async function open() {
  const context=await browser.newContext({viewport:{width:1365,height:1100}});
  assert.ok((await context.request.post(origin+'/api/login',{headers:{Origin:origin},data:{secret}})).ok());
  const page=await context.newPage();
  page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('dialog',dialog=>dialog.accept());
  await page.goto(origin);await page.locator('#workspace').waitFor({state:'visible'});
  await page.getByRole('button',{name:'Tools',exact:true}).click();await page.locator('#add-tool').click();
  await expect(page.locator('#connector-target option')).toHaveCount(3);
  return {context,page};
}
async function fill(page,name,index) {
  await page.locator('#connector-name').fill(name);
  await page.locator('#connector-target').selectOption(target(index));
  await page.locator('#connector-document').setInputFiles({name:`vendor-${index}.json`,mimeType:'application/json',buffer:document(index)});
}
async function submit(page) {
  const response=page.waitForResponse(value=>value.url()===origin+'/api/apps/connectors' && value.request().method()==='POST');
  await page.getByRole('button',{name:'Prepare disabled candidate',exact:true}).click();
  const result=await response;assert.ok(result.ok());
  const row=await result.json();await expect(page.locator('#connector-name')).toBeEnabled();
  return row;
}
async function perform(page,operation) {
  const response=page.waitForResponse(value=>value.url()===origin+'/api/apps/connectors/'+operation);
  await page.locator('#connector-'+operation).click();const result=await response;assert.ok(result.ok());
  await expect(page.locator('#connector-name')).toBeEnabled();return result.json();
}
const saved=(page,name)=>page.locator('#connector-list').getByRole('button',{name:new RegExp('^'+name+':')});
async function pair(page,prefix) {
  await fill(page,prefix+' A',0);const a=await submit(page);
  await page.locator('#connector-new').click();await fill(page,prefix+' B',1);const b=await submit(page);
  return {a,b};
}
async function rows(context) {return (await (await context.request.get(origin+'/api/apps/connectors')).json()).items;}
async function scenario(name,task) {
  const {context,page}=await open();
  try {await task(page,context);cases.push({name,status:'passed'});}
  catch(error) {cases.push({name,status:'failed',error:error.message});}
  finally {check(name+': zero setup executable effects',effectCount().every(value=>value===0));await context.close();}
}
async function held(page,pattern,task) {
  let release,arrive;
  const gate=new Promise(resolve=>{release=resolve;});const arrived=new Promise(resolve=>{arrive=resolve;});
  await page.route(pattern,async route=>{
    if(route.request().method()!=='POST')return route.continue();
    const response=await route.fetch();arrive();await gate;await route.fulfill({response});
  });
  try {await task(arrived,release);} finally {release();await page.unrouteAll({behavior:'wait'});}
}
try {
  let ready=false;
  for(let i=0;i<100;i++) {
    if(server.exitCode!==null) throw new Error('Owned identity server exited');
    try {if((await fetch(origin)).ok){ready=true;break;}}catch{}
    await new Promise(resolve=>setTimeout(resolve,50));
  }
  assert.ok(ready);
  await scenario('A-B-A exact form/evidence ownership',async(page,context)=>{
    const {a,b}=await pair(page,'Switch');
    await saved(page,b.name).click();await saved(page,a.name).click();
    await expect(page.locator('#connector-target')).toHaveValue(target(0),{timeout:1000});
    check('A selected restores exact name and target',(await page.locator('#connector-name').inputValue())===a.name);
    check('A selected clears foreign upload',await page.locator('#connector-document').evaluate(input=>input.files.length===0));
    await expect(page.locator('#connector-result')).toContainText('Select documentation');
    await fill(page,'Switch A revised',0);const revised=await submit(page);
    check('A preparation revises only A with exact chosen evidence',revised.id===a.id && revised.revision===a.revision+1 &&
      revised.candidate.target===target(0) && revised.candidate.evidence_digest===hash(document(0)));
    const stored=await rows(context);check('B unchanged after A revision',same(stored.find(row=>row.id===b.id),b));
    await page.screenshot({path:`${evidence}/${label}-identity.png`,fullPage:true});
  });
  await scenario('unprepared edits gate old reviewed identity',async(page,context)=>{
    await fill(page,'Dirty A',0);let a=await submit(page);a=await perform(page,'check');a=await perform(page,'review');
    let activations=0;page.on('request',request=>{if(request.url().endsWith('/connectors/activate'))activations++;});
    for(const field of ['name','target','document']) {
      await saved(page,a.name).click();
      if(field==='name')await page.locator('#connector-name').fill('Deliberate changed alias');
      if(field==='target')await page.locator('#connector-target').selectOption(target(1));
      if(field==='document')await page.locator('#connector-document').setInputFiles({name:'changed.json',mimeType:'application/json',buffer:document(1)});
      for(const operation of ['check','review','activate'])await expect(page.locator('#connector-'+operation)).toBeDisabled({timeout:1000});
      await page.locator('#connector-activate').evaluate(button=>button.click());
      check(field+' edit explains prepare-next action',(await page.locator('#connector-result').innerText()).includes('Unprepared changes'));
    }
    check('no stale activation submitted',activations===0);
    const stored=(await rows(context)).find(row=>row.id===a.id);
    check('edits preserve server revision/digest/review',stored.revision===a.revision && stored.digest===a.digest && stored.review===a.review);
    // Declining an explicit discard keeps the whole typed form/file intact.
    page.removeAllListeners('dialog');page.on('dialog',dialog=>dialog.dismiss());
    await page.locator('#connector-name').fill('Keep deliberate draft');await page.locator('#connector-new').click();
    check('declined draft discard preserves name and selected file',(await page.locator('#connector-name').inputValue())==='Keep deliberate draft' &&
      await page.locator('#connector-document').evaluate(input=>input.files[0]?.name==='changed.json'));
  });
  await scenario('immutable snapshot before asynchronous file read',async(page,context)=>{
    const {a,b}=await pair(page,'Read');await saved(page,a.name).click();await fill(page,a.name,0);
    await page.evaluate(()=>{const original=File.prototype.text;File.prototype.text=function(){const file=this;window.readEntered=true;
      return new Promise(resolve=>{window.releaseRead=()=>original.call(file).then(resolve);});};});
    const response=page.waitForResponse(value=>value.url()===origin+'/api/apps/connectors' && value.request().method()==='POST');
    await page.getByRole('button',{name:'Prepare disabled candidate',exact:true}).click();await page.waitForFunction(()=>window.readEntered);
    try {
      const blocked=await saved(page,b.name).isDisabled();await saved(page,b.name).evaluate(button=>button.click());
      await page.evaluate(()=>window.releaseRead());const result=await response;assert.ok(result.ok());const revised=await result.json();
      await expect(page.locator('#connector-name')).toBeEnabled();
      check('file read uses captured A ID/revision/target/evidence',revised.id===a.id && revised.revision===a.revision+1 &&
        revised.candidate.target===target(0) && revised.candidate.evidence_digest===hash(document(0)));
      check('saved switching blocked during file read',blocked);
      check('B not overwritten during read',same((await rows(context)).find(row=>row.id===b.id),b));
    } finally {await page.evaluate(()=>window.releaseRead?.());}
  });
  for(const operation of ['prepare','check','review','activate']) await scenario('held '+operation+' response owns selected draft',async(page,context)=>{
    const {a,b}=await pair(page,'Held '+operation);await saved(page,a.name).click();
    if(operation==='prepare')await fill(page,a.name,0);
    if(['review','activate'].includes(operation))await perform(page,'check');
    if(operation==='activate')await perform(page,'review');
    const endpoint=origin+'/api/apps/connectors'+(operation==='prepare'?'':'/'+operation);
    await held(page,endpoint,async(arrived,release)=>{
      const response=page.waitForResponse(value=>value.url()===endpoint && value.request().method()==='POST');
      await page.locator(operation==='prepare'?'#connector-form button[type=submit]':'#connector-'+operation).click();await arrived;
      const blocked=await saved(page,b.name).isDisabled();await saved(page,b.name).evaluate(button=>button.click());
      release();const acknowledged=await (await response).json();await expect(page.locator('#connector-name')).toBeEnabled();
      check(operation+': exact A response revision and evidence',acknowledged.id===a.id &&
        acknowledged.revision===a.revision+(operation==='prepare'?1:0) && acknowledged.candidate.target===target(0) &&
        acknowledged.candidate.evidence_digest===hash(document(0)));
      check(operation+': saved selection serialized',blocked);
      check(operation+': late response retains A form identity',(await page.locator('#connector-name').inputValue())===a.name &&
        (await page.locator('#connector-target').inputValue())===target(0));
      const stored=await rows(context);check(operation+': B exact revision unchanged',same(stored.find(row=>row.id===b.id),b));
    });
  });
  await scenario('first rejection releases controls and deliberate retry',async(page,context)=>{
    const before=(await rows(context)).length;await fill(page,'Rejected first',0);
    await page.route(origin+'/api/apps/connectors',route=>route.request().method()==='POST'
      ?route.fulfill({status:409,json:{error:'CONNECTOR_CONFLICT'}}):route.continue());
    await page.getByRole('button',{name:'Prepare disabled candidate',exact:true}).click();
    await expect(page.locator('#error')).toContainText('CONNECTOR_CONFLICT');
    await expect(page.locator('#connector-name')).toBeEnabled({timeout:1000});
    await page.screenshot({path:`${evidence}/${label}-first-failure.png`,fullPage:true});
    check('first failure retains complete name/target/file',(await page.locator('#connector-name').inputValue())==='Rejected first' &&
      (await page.locator('#connector-target').inputValue())===target(0) &&
      await page.locator('#connector-document').evaluate(input=>input.files[0]?.name==='vendor-0.json'));
    check('rejected first request creates no saved candidate',(await rows(context)).length===before);
    await page.unroute(origin+'/api/apps/connectors');await fill(page,'Corrected deliberate retry',1);const retry=await submit(page);
    check('corrected retry creates exactly one correct disabled revision',retry.revision===1 && retry.name==='Corrected deliberate retry' &&
      retry.candidate.target===target(1) && retry.candidate.evidence_digest===hash(document(1)) && (await rows(context)).length===before+1);
    check('retry is disabled, not activated',retry.state==='Disabled' && !retry.review);
    await expect(page.locator('#error')).toHaveText('');
    check('acknowledged retry clears the prior error',true);
  });
  check('no browser page errors',errors.length===0);
  const report={scope:'Setup-only R01/R02 controls; controlled async holds/rejection; no executable calls',cases,checks,pageErrors:errors,effects:effectCount()};
  fs.writeFileSync(`${evidence}/${label}-browser.json`,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
  if(cases.some(item=>item.status!=='passed'))process.exitCode=1;
} finally {
  await browser.close();if(server.exitCode===null){const done=new Promise(resolve=>server.once('exit',resolve));server.kill('SIGTERM');await done;}
  fs.rmSync(home,{recursive:true,force:true});
}
