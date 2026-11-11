// Real browser controls + harmless actual child; no model/qualification intent.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn, spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE);
const {expect} = require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
const checks = [], errors = [];
const check = (name,value) => { assert.ok(value,name); checks.push(name); };
const browser = await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
async function scenario(legacy,port) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(),'motion-ordinary-fixture-'));
  const secret = crypto.randomBytes(32).toString('hex');
  fs.writeFileSync(path.join(home,'test-secret'),secret,{mode:0o600});
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn('python',['-m','tests.ordinary_server','--home',home,'--port',String(port),...(legacy?['--legacy']:[])],{stdio:'ignore'});
  let context;
  const effectCount = () => {
    const file = path.join(home,'offline-tool/effects.jsonl');
    return fs.existsSync(file) ? fs.readFileSync(file,'utf8').trim().split('\n').length : 0;
  };
  try {
    let healthy = false;
    for (let n=0;n<100;n++) {
      if (server.exitCode !== null) throw new Error('Owned ordinary fixture server exited');
      try { if ((await fetch(origin)).ok) {healthy=true;break;} } catch {}
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    assert.ok(healthy);
    context = await browser.newContext({viewport:{width:1365,height:1000},acceptDownloads:true});
    const auth = await context.request.post(origin+'/api/login',{headers:{Origin:origin},data:{secret}});
    assert.ok(auth.ok());
    const page = await context.newPage();
    page.on('pageerror',()=>errors.push('PAGE_ERROR'));
    page.on('dialog',dialog=>dialog.accept());
    await page.goto(origin);
    await page.locator('#workspace').waitFor({state:'visible'});
    await page.locator('#text').fill('Non-private English synthetic whoosh fixture');
    await page.locator('#purpose').fill('Noncommercial local technical evaluation fixture');
    await page.getByRole('button',{name:'Save request',exact:true}).click();
    await expect(page.locator('#save-state')).toContainText('Saved');
    const selected = await page.locator('#app-method option').evaluateAll(items=>items.find(item=>item.textContent.includes('Available for evaluation')).value);
    await page.locator('#app-method').selectOption(selected);
    await expect(page.locator('#generate')).toBeEnabled();
    check(`${legacy?'recovery':'ordinary'} save/select/status produce no effect`,effectCount()===0);
    check('normal defaults are three seconds and seed42',(await page.locator('#sfx-seconds').inputValue())==='3' && (await page.locator('#sfx-seed').inputValue())==='42');
    check('scope and bounded recovery beside start',(await page.locator('#unavailable').innerText()).includes('Noncommercial local technical evaluation only') && (await page.locator('#unavailable').innerText()).includes('one supported local recovery'));
    if (!legacy) {
      let release, received;
      const held = new Promise(resolve=>{release=resolve;});
      const arrived = new Promise(resolve=>{received=resolve;});
      await page.route('**/api/apps/plans',async route=>{
        const response = await route.fetch(); received(); await held; await route.fulfill({response});
      });
      await page.locator('#generate').click();
      await arrived;
      await page.locator('#text').fill('Non-private changed English synthetic whoosh fixture');
      check('editing while review pending invalidates Create',await page.locator('#create-sfx').isDisabled());
      release();
      await expect(page.locator('#sfx-options')).toBeEnabled();
      check('late review response cannot restore dirty Create',await page.locator('#create-sfx').isDisabled() && effectCount()===0);
      await page.unroute('**/api/apps/plans');
      await page.getByRole('button',{name:'Save request',exact:true}).click();
      await expect(page.locator('#save-state')).toContainText('revision 2');
    }
    await page.locator('#generate').click();
    await expect(page.locator('#create-sfx')).toBeEnabled();
    check('review is immutable local model/parameters/one candidate',(await page.locator('#sfx-review').innerText()).includes('100 steps; one candidate') && effectCount()===0);
    await page.locator('#create-sfx').evaluate(button=>{button.click();button.click();});
    await expect.poll(async()=>{
      const state = await (await context.request.get(origin+'/api/state')).json();
      return legacy ? state.recovery[0]?.state : state.takes.length===1 ? 'Completed' : 'Waiting';
    },{timeout:12000}).toBe('Completed');
    const state = await (await context.request.get(origin+'/api/state')).json();
    const take = state.takes[0];
    check(`${legacy?'recovery':'ordinary'} repeated Create has bounded effect count`,effectCount()===(legacy?2:1));
    check('fixture remains labelled and never auto-reviewed',take.origin==='test_fixture' && take.review==='Not reviewed');
    if (legacy) {
      await expect(page.locator('#runs')).toContainText('Recovery: Completed');
      check('browser reports completed linked recovery',(await page.locator('#runs').innerText()).includes('Recovery: Completed'));
      check('original failed identity remains with distinct successor',state.runs.some(run=>run.status==='Failed') && state.recovery[0].successor!==state.recovery[0].failed_run && state.recovery[0].reserved===true);
      check('technical lessons advisory without request identifiers',state.technical_knowledge.authority==='none' && !JSON.stringify(state.technical_knowledge).includes(take.request));
    }
    await page.reload();
    await page.locator('#workspace').waitFor({state:'visible'});
    await page.locator('#takes .take').waitFor();
    check('reopen observes original run without launch',effectCount()===(legacy?2:1) && await page.locator('#create-sfx').isDisabled());
    check('no autoplay before explicit player load',await page.locator('audio').evaluate(audio=>!audio.src && audio.paused));
    const original = await context.request.get(`${origin}/api/takes/${take.id}/media`);
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('button',{name:'Download original',exact:true}).click();
    const download = await downloadEvent;
    const file = path.join(home,'download.wav');
    await download.saveAs(file);
    check('normal UI download equals scoped original bytes',fs.readFileSync(file).equals(await original.body()));
    const decoded = spawnSync('/usr/bin/ffmpeg',['-v','error','-i',file,'-f','null','-'],{encoding:'utf8'});
    check('independent decode of ordinary-control fixture',decoded.status===0);
    await page.getByRole('button',{name:'Load player',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('audio').src.startsWith('blob:'));
    const duration = await page.locator('audio').evaluate(async audio=>{
      await audio.play(); await new Promise((resolve,reject)=>{audio.onended=resolve;audio.onerror=reject;}); return audio.duration;
    });
    check('three-second playback survives observation polling',duration===3);
    const observed = await (await context.request.get(origin+'/api/state')).json();
    check('playback/download never claim listening review',observed.takes[0].review==='Not reviewed');
    if (!legacy) {
      await page.getByRole('button',{name:'New request',exact:true}).click();
      await page.locator('#text').fill('Non-private stop fixture');
      await page.getByRole('button',{name:'Save request',exact:true}).click();
      await expect(page.locator('#save-state')).toContainText('Saved');
      await page.locator('#app-method').selectOption(selected);
      await expect(page.locator('#generate')).toBeEnabled();
      await page.locator('#sfx-seconds').fill('0.1');
      fs.writeFileSync(path.join(home,'offline-tool/mode'),'sleep');
      await page.locator('#generate').click();
      await expect(page.locator('#create-sfx')).toBeEnabled();
      await page.locator('#create-sfx').click();
      await expect.poll(effectCount).toBe(2);
      const active = (await (await context.request.get(origin+'/api/state')).json()).runs.find(run=>run.status==='Running');
      const applyingNotice = 'Controlled collection already applying; observe its outcome.';
      await page.route('**/api/sfx/runs/*/stop',async route=>{
        const response = await route.fetch();
        await route.fulfill({response,json:{...await response.json(),recovery_action:'already-applying',recovery_notice:applyingNotice}});
      });
      await page.locator(`[data-run="${active.id}"]`).getByRole('button',{name:'Stop request'}).click();
      await expect(page.locator('#status')).toHaveText(applyingNotice);
      check('stop handler renders already-applying notice (controlled response)',true);
      await expect.poll(async()=>{
        const value = await (await context.request.get(`${origin}/api/sfx/runs/${active.id}`)).json();return value.status;
      }).toBe('Cancelled');
      await page.reload();
      await page.locator('#workspace').waitFor({state:'visible'});
      await expect(page.locator('#runs')).toContainText('Cancelled');
      check('stopped flow reopens without recovery or new effect',effectCount()===2 && (await page.locator('#runs').innerText()).includes('Cancelled'));
      const completedNotice = 'Controlled collection completion won; edit cannot undo it.';
      await page.route('**/api/sfx/runs/*/suppress-recovery',route=>route.fulfill({json:{
        recovery_suppressed:false,recovery_action:'completion-won',recovery_notice:completedNotice}}));
      await page.locator('#text').fill('Changed controlled notice fixture');
      await expect(page.locator('#status')).toHaveText(completedNotice);
      check('edit handler renders completion-won notice (controlled response)',true);
    }
    await page.screenshot({path:`docs/evidence/qs1-${legacy?'recovery':'ordinary'}.png`,fullPage:true});
  } finally {
    await context?.close();
    if (server.exitCode===null) {const done=new Promise(resolve=>server.once('exit',resolve));server.kill('SIGTERM');await done;}
    fs.rmSync(home,{recursive:true,force:true});
  }
}
try {
  await scenario(false,18770);
  await scenario(true,18771);
  check('ordinary browsers have no page errors',errors.length===0);
  const result={scope:'Synthetic ordinary UI and actual harmless child only; no model',checks,pageErrors:errors};
  fs.writeFileSync('docs/evidence/qs1-browser-results.json',JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result,null,2));
} finally {await browser.close();}
