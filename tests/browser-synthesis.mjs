import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PACKAGE);
const {expect}=require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
const home=fs.mkdtempSync(path.join(os.tmpdir(),'motion-cs1-'));
const secret=crypto.randomBytes(32).toString('hex');fs.writeFileSync(path.join(home,'test-secret'),secret,{mode:0o600});
const origin='http://127.0.0.1:18773',out='docs/evidence/cs1';fs.mkdirSync(out,{recursive:true});
const server=spawn('python',['-m','tests.template_server','--home',home,'--port','18773','--synthesis-fixture'],{stdio:'ignore'});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const checks=[],pageErrors=[];let receipt={};
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
try {
  let ready=false;
  for(let i=0;i<100;i++) {try{if((await fetch(origin)).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,50));}
  assert.ok(ready,'fixture server ready');
  const context=await browser.newContext({viewport:{width:1365,height:1000}});
  await context.request.post(origin+'/api/login',{headers:{Origin:origin},data:{secret}});
  const page=await context.newPage();page.on('pageerror',()=>pageErrors.push('PAGE_ERROR'));
  await page.goto(origin);await page.locator('#workspace').waitFor({state:'visible'});
  await page.getByRole('button',{name:'Tools',exact:true}).click();
  await expect(page.locator('#connector-synthesis')).toContainText('Live synthesis unavailable');
  await expect(page.getByRole('button',{name:'Prepare proposed mapping',exact:true})).toBeDisabled();
  check('production is unavailable without invoking service',(await (await context.request.get(origin+'/api/cs1/receipt')).json()).facade_calls===0);
  await page.goto(origin+'/fixture/synthesis');
  async function fill(index) {
    await page.getByLabel('Public source 1',{exact:true}).fill('Fixture technical reference');
    await page.getByLabel('Documented version 1',{exact:true}).fill(index===0?'1.0':'2.4');
    await page.getByLabel('Technical excerpts 1',{exact:true}).fill(fs.readFileSync('tests/fixtures/synthesis/'+(index===0?'lumen-reference.txt':'ripple-reference.txt'),'utf8'));
  }
  async function submit() {
    const response=page.waitForResponse(r=>r.url().endsWith('/api/cs1/rpc')&&r.request().postDataJSON().method.endsWith('.prepare'));
    await page.getByRole('button',{name:'Prepare proposed mapping',exact:true}).click();
    const row=await (await response).json();await expect(page.getByRole('button',{name:'Check saved job',exact:true})).toBeEnabled();return row;
  }
  async function inspect() {
    await page.getByRole('button',{name:'Check saved job',exact:true}).click();
    await expect(page.getByRole('status')).toContainText('Proposal ready');
  }
  const proposals=[],savedJobs=[];
  for(const index of [0,1]) {
    await fill(index);const row=await submit();await inspect();
    savedJobs.push(row.id);
    const detail=page.locator('pre');proposals.push(JSON.parse(await detail.textContent()));
    check('disabled proposal '+index,proposals[index].disabled===true&&proposals[index].qualified===false);
    check('exact fixture mapping '+index,proposals[index].mapping.arguments[0].flag===(index===0?'--words':'--description'));
    check('exact selected evidence references '+index,proposals[index].evidence_map['arguments.0.flag'][0].quote.includes(index===0?'--words':'--description'));
    await expect(page.getByRole('status')).toContainText(row.id);
  }
  check('same trusted template interpreter',JSON.stringify(proposals[0].template_ref)===JSON.stringify(proposals[1].template_ref));
  await page.getByText('Proposal and evidence details',{exact:true}).click();await page.screenshot({path:out+'/proposals.png',fullPage:true});
  const before=await (await context.request.get(origin+'/api/cs1/receipt')).json();
  await page.getByRole('button',{name:'Check saved job',exact:true}).click();
  check('reopen/status never calls facade',(await (await context.request.get(origin+'/api/cs1/receipt')).json()).facade_calls===before.facade_calls);
  await page.goto(origin+'/fixture/synthesis');
  await page.getByText('Reopen a saved preparation',{exact:true}).click();
  await page.getByLabel('Saved job ID',{exact:true}).fill(savedJobs[0]);
  await page.getByRole('button',{name:'Open saved preparation',exact:true}).click();
  await expect(page.getByRole('status')).toContainText(savedJobs[0]);
  check('fresh-page reopen retains exact disabled proposal',JSON.parse(await page.locator('pre').textContent()).mapping.arguments[0].flag==='--words');
  check('fresh-page reopen causes no inference',(await (await context.request.get(origin+'/api/cs1/receipt')).json()).facade_calls===before.facade_calls);
  // Excluded first input retains editable fields; corrected retry is deliberate.
  await page.goto(origin+'/fixture/synthesis');await fill(0);
  await page.getByLabel('Technical excerpts 1',{exact:true}).fill('PRIVATE_SENTINEL');
  await page.getByRole('button',{name:'Prepare proposed mapping',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Inputs retained');
  await expect(page.getByLabel('Technical excerpts 1',{exact:true})).toBeEnabled();
  check('excluded data never reaches facade',(await (await context.request.get(origin+'/api/cs1/receipt')).json()).facade_calls===2);
  await fill(0);await submit();await inspect();
  check('deliberate corrected retry succeeds',true);
  await page.getByLabel('Technical excerpts 1',{exact:true}).fill(fs.readFileSync('tests/fixtures/synthesis/lumen-reference.txt','utf8').replace('Stop semantics is process-group-term-kill.','Stop behavior is not specified.'));
  await submit();await page.getByRole('button',{name:'Check saved job',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Needs information');
  await expect(page.getByRole('status')).toContainText('stopped');
  check('plain-language focused missing-information flow',await page.locator('pre').textContent()==='');
  await page.screenshot({path:out+'/unknowns.png',fullPage:true});
  // Keep an already processed Prepare reply held, then dispose on scope change.
  let release,arrive;
  const gate=new Promise(r=>release=r),arrived=new Promise(r=>arrive=r);
  await page.route('**/api/cs1/rpc',async route=>{
    if(!route.request().postDataJSON().method.endsWith('.prepare'))return route.continue();
    const response=await route.fetch();arrive();await gate;await route.fulfill({response});
  });
  await fill(1);await page.getByRole('button',{name:'Prepare proposed mapping',exact:true}).click();await arrived;
  await expect(page.getByLabel('Technical excerpts 1',{exact:true})).toBeDisabled();
  await page.locator('#fixture-switch').click();release();await page.unrouteAll({behavior:'wait'});
  await expect(page.getByRole('status')).toHaveText('Nothing prepared. Preparation never activates or runs a tool.');
  check('late reply cannot rebind changed session',await page.locator('pre').textContent()==='');
  receipt=await (await context.request.get(origin+'/api/cs1/receipt')).json();
  check('zero executable effects',receipt.effects.every(n=>n===0));check('zero page errors',pageErrors.length===0);
  await context.close();
} finally {
  await browser.close();server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve));
  fs.unlinkSync(path.join(home,'test-secret'));
  fs.writeFileSync(out+'/browser.json',JSON.stringify({kind:'offline fake SDK/host only',checks,pageErrors,receipt},null,2)+'\n');
}
console.log(JSON.stringify({checks:checks.length,pageErrors,receipt}));
