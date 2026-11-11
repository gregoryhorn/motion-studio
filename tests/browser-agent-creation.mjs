// Offline actual native ESM, packaged Python, shared fake child and retained WAV.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn,execFileSync} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PACKAGE);
const {expect}=require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'motion-afc-browser-'));
execFileSync('python',['-m','zipfile','-e',process.env.NATIVE_BUNDLE,temp]);
execFileSync(process.env.ESBUILD,['tests/native-browser-fixture.js','--bundle','--format=iife','--platform=browser','--log-level=error',
  '--alias:motion-studio-package='+path.join(temp,'motion-studio/desktop/plugin.js'),
  '--alias:@hermes/plugin-sdk='+path.resolve('tests/native-sdk-browser.js'),'--outfile='+path.join(temp,'fixture.js')]);
const bridge=spawn('python',['-m','tests.native_package_fixture'],{stdio:['pipe','pipe','pipe']});
let sequence=0,stderr='';const waiting=new Map();bridge.stderr.on('data',c=>{stderr+=c;});
const closed=new Promise(resolve=>bridge.once('exit',code=>{for(const e of waiting.values())e.reject(Error('Fixture exited'));resolve(code);}));
createInterface({input:bridge.stdout}).on('line',line=>{const v=JSON.parse(line),e=waiting.get(v.id);waiting.delete(v.id);v.error?e.reject(Error(v.error)):e.resolve(v.result);});
const rpc=message=>new Promise((resolve,reject)=>{const id=++sequence;waiting.set(id,{resolve,reject});bridge.stdin.write(JSON.stringify({id,...message})+'\n');});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const checks=[],errors=[];const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
try{
  const context=await browser.newContext({serviceWorkers:'block',offline:true,acceptDownloads:true});
  await context.exposeBinding('nativeRPC',(_source,message)=>rpc(message));
  const html='<html><body><div id="root"></div><script>'+fs.readFileSync(path.join(temp,'fixture.js'),'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
  await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:html}):route.abort());
  const page=await context.newPage();page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  const button=name=>page.getByRole('button',{name,exact:true});
  await page.goto('https://motion.invalid/');
  await expect(page.getByText('Motion Studio',{exact:true})).toBeVisible();
  check('import/register/render has no media access/effect',!(await rpc({op:'counts'})).state_created);
  await button('Open saved creations').click();
  await expect(page.getByRole('status')).toContainText('Creation access is not configured');
  check('default denied without creating state',!(await rpc({op:'counts'})).state_created);
  await rpc({op:'admit-creation-fixture'});
  await page.reload();await button('Open saved creations').click();
  await expect(page.getByRole('status')).toContainText('0 creations · Saved creations opened.');
  check('admitted workspace is open and empty before the agent request',await page.getByText('No saved creations opened for this chat.',{exact:true}).isVisible());
  // Selected ordinary sentence is mapped to tool args by a synthetic agent fixture,
  // not real inference. This delivered Prepare preserves automatic-observation coverage.
  const direction='Synthetic metallic door slam';
  await rpc({op:'tool',args:{operation:'prepare',direction}});
  await expect(page.getByRole('heading',{name:direction,exact:true})).toBeVisible({timeout:12000});
  const recovered=await rpc({op:'tool',args:{operation:'status'},session:'new-compressed-segment'});
  check('already-open page automatically discovers delivered Prepare with zero effects',Boolean(recovered.command)&&(await rpc({op:'counts'})).creation_effects===0);

  // Distinct interrupted-agent boundary: the loaded app has observed no creation
  // ID. Discard Prepare's delivered reply, reload, then use only root-scoped
  // observation/status. Identity evidence stays in the test bridge.
  const recoveryRoot='session-prepare-recovery',recoveryDirection='Synthetic lost Prepare recovery';
  await rpc({op:'rpc',method:'creation.admit',payload:{session_id:recoveryRoot}});
  const beforeLost=await rpc({op:'counts'});
  const recoveryPage=await context.newPage();recoveryPage.on('pageerror',()=>errors.push('PAGE_ERROR'));
  await recoveryPage.addInitScript(root=>{window.fixtureInitialSession=root;},recoveryRoot);
  await recoveryPage.goto('https://motion.invalid/');
  const discarded=await rpc({op:'tool',root:recoveryRoot,session:'physical-before-reload',
    discard_prepare_reply:true,args:{operation:'prepare',direction:recoveryDirection}});
  const beforeReload=await recoveryPage.evaluate(()=>({requests:window.fixtureRequests,ids:window.fixtureObservedCreationIds}));
  check('loaded app has no remembered request ID before lost-Prepare reload',discarded.delivered===false&&
    beforeReload.ids.length===0&&beforeReload.requests.every(r=>!r.payload?.request));
  const lostIdentity=await rpc({op:'lost-prepare-identity'});
  await recoveryPage.reload();
  await recoveryPage.getByRole('button',{name:'Open saved creations',exact:true}).click();
  await expect(recoveryPage.getByRole('heading',{name:recoveryDirection,exact:true})).toBeVisible();
  const recoveredLost=await rpc({op:'tool',root:recoveryRoot,session:'physical-after-reload',args:{operation:'status'}});
  const afterLost=await rpc({op:'counts'});
  const recoveryRequests=await recoveryPage.evaluate(()=>window.fixtureRequests);
  const afterReloadIds=await recoveryPage.evaluate(()=>window.fixtureObservedCreationIds);
  check('lost Prepare plus actual reload recovers identical root-scoped identity with one dispatch, zero effects and no replay',
    lostIdentity&&afterReloadIds.includes(lostIdentity.request)&&['request','revision','command','run'].every(key=>recoveredLost[key]===lostIdentity[key])&&
    afterLost.prepare_dispatches===beforeLost.prepare_dispatches+1&&afterLost.creation_effects===beforeLost.creation_effects&&
    afterLost.creation_effects===0&&recoveryRequests.every(r=>!r.method.endsWith('.prepare')&&!r.method.endsWith('.start')));
  await recoveryPage.close();

  const command=Object.fromEntries(['request','revision','command','run'].map(k=>[k,recovered[k]]));
  // Discard Start's delivered reply and reload without agent continuation. The
  // bridge retains identity only for test comparison; status remains root/no-ID.
  const beforeStart=await rpc({op:'counts'});
  const discardedStart=await rpc({op:'tool',discard_start_reply:true,args:{operation:'start',...command}});
  const lostStartIdentity=await rpc({op:'lost-start-identity'});
  await rpc({op:'settle-creation'});
  await page.reload();await button('Open saved creations').click();
  await expect(page.getByRole('status')).toContainText('1 creation · Saved creations opened.');
  await page.getByText('Technical details',{exact:true}).click();
  await expect(page.getByText('Progress: Ready for review; certainty: exited',{exact:true})).toBeVisible();
  const recoveredStart=await rpc({op:'tool',args:{operation:'status'},session:'after-lost-start-reload'});
  const afterStart=await rpc({op:'counts'});
  const startReloadRequests=await page.evaluate(()=>window.fixtureRequests);
  check('lost Start plus actual reload recovers identical root-scoped identity with one effect and no repeated dispatch',
    discardedStart.delivered===false&&lostStartIdentity&&
    ['request','revision','command','run'].every(key=>recoveredStart[key]===lostStartIdentity[key]&&recoveredStart[key]===recovered[key])&&
    afterStart.start_dispatches===beforeStart.start_dispatches+1&&beforeStart.creation_effects===0&&afterStart.creation_effects===1&&
    startReloadRequests.every(r=>!r.method.endsWith('.prepare')&&!r.method.endsWith('.start'))&&
    await page.getByText('Saved creation '+recovered.request,{exact:true}).isVisible());
  await expect(page.getByText(/TEST ONLY - not generated/)).toBeVisible();
  await button('Load original audio').click();
  await expect(page.getByRole('status')).toContainText('Player ready — use Play / pause.');
  const audio=page.getByLabel('Original audio',{exact:true});
  await expect(audio).toHaveAttribute('src',/^blob:/);
  await expect.poll(()=>audio.evaluate(el=>Number.isFinite(el.duration)?el.duration:null)).toBe(3);
  const playback=await audio.evaluate(async el=>{el.muted=true;await el.play();const active=!el.paused;el.pause();return active;});
  check('browser decodes original 3-second WAV and player starts without review assertion',playback);
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('link',{name:'Save / download original WAV',exact:true}).click();
  const download=await downloadEvent;const bytes=fs.readFileSync(await download.path());
  const first=await rpc({op:'rpc',method:'creation.chunk',payload:{session_id:'session-a',request:recovered.request,take:recovered.candidate,offset:0}});
  check('download is exact retained original, not another generated copy',crypto.createHash('sha256').update(bytes).digest('hex')===first.sha256&&bytes.length===first.total);
  await button('Choose this take').click();
  await expect(page.getByText('Selected',{exact:true})).toBeVisible();
  await button('Listened: needs work').click();
  await expect(button('Listened: needs work')).toHaveAttribute('aria-pressed','true');
  check('selection and explicit review are persisted separately from playback',true);
  await page.getByLabel('Change for another take').fill('Make the echo longer');
  await page.evaluate(()=>{window.fixtureDraft='Preserve existing draft';});
  await button('Put refinement in selected chat').click();
  await expect(page.getByRole('status')).toContainText('Chat already has a draft');
  check('refinement preserves existing draft before explicit append',(await page.evaluate(()=>window.fixtureDraft))==='Preserve existing draft');
  await button('Append to existing draft').click();
  await expect(page.getByRole('status')).toContainText('press Send there');
  check('refinement drafts into exact selected chat, no automatic send/fallback',await page.evaluate(()=>window.fixtureDraft.startsWith('Preserve existing draft')&&window.fixtureDraftSession==='session-a'));
  await page.reload();await button('Open saved creations').click();
  await expect(button('Listened: needs work')).toHaveAttribute('aria-pressed','true');
  await button('Load original audio').click();
  await expect(page.getByRole('status')).toContainText('Player ready — use Play / pause.');
  const requests=await page.evaluate(()=>window.fixtureRequests);
  check('reopen/player/review/download observations do not generate',requests.every(r=>!r.method.endsWith('.start')&&!r.method.endsWith('.prepare'))&&(await rpc({op:'counts'})).creation_effects===1);
  // Same mounted React page: ordinary polling preserves text, but a root change
  // synchronously masks it and rejects an event closed over the old identity.
  const refinement=page.getByLabel('Change for another take');
  await refinement.fill('Synthetic A text retained during polling');
  await button('Refresh progress').click();
  await expect(refinement).toHaveValue('Synthetic A text retained during polling');
  check('ordinary same-scope observation preserves refinement typing',true);
  await rpc({op:'rpc',method:'creation.admit',payload:{session_id:'session-b'}});
  const second=await rpc({op:'tool',root:'session-b',session:'session-b-physical',args:{operation:'prepare',direction:'Synthetic second root sound'}});
  check('second root has an independent saved creation',second.request!==recovered.request);
  const composerBefore=await page.evaluate(()=>window.fixtureComposerCalls?.length||0);
  await page.evaluate(()=>{const stale=[...document.querySelectorAll('button')].find(el=>el.textContent==='Put refinement in selected chat');
    window.fixtureSession('session-b');stale.click();});
  await expect(page.getByRole('status')).toContainText('Selected chat/profile/connection changed');
  await button('Open saved creations').click();
  await expect(page.getByRole('heading',{name:'Synthetic second root sound',exact:true})).toBeVisible();
  await expect(refinement).toHaveValue('');
  check('A text is absent and stale A action is rejected after same-profile switch to B without remount',
    (await page.evaluate(()=>window.fixtureComposerCalls?.length||0))===composerBefore);
  await refinement.fill('Fresh B refinement only');
  await button('Put refinement in selected chat').click();
  await expect(page.getByRole('status')).toContainText('press Send there');
  const composer=await page.evaluate(()=>window.fixtureComposerCalls);
  check('only fresh B text is appended to the exact B draft',composer.length===composerBefore+1&&
    composer.at(-1).session==='session-b'&&composer.at(-1).text.includes('Fresh B refinement only')&&
    !composer.at(-1).text.includes('Synthetic A text retained'));
  await refinement.fill('Unsent B text before away and back');
  const beforeAway=await page.evaluate(()=>window.fixtureComposerCalls.length);
  await page.evaluate(()=>{const stale=[...document.querySelectorAll('button')].find(el=>el.textContent==='Put refinement in selected chat');
    window.fixtureSession('away-root');window.fixtureSession('session-b');stale.click();});
  await expect(page.getByRole('status')).toContainText('Selected chat/profile/connection changed');
  await button('Open saved creations').click();
  await expect(page.getByRole('heading',{name:'Synthetic second root sound',exact:true})).toBeVisible();
  await expect(refinement).toHaveValue('');
  check('away-and-back remains invalidated, masks old text and rejects stale action',
    (await page.evaluate(()=>window.fixtureComposerCalls.length))===beforeAway);
  check('no private text or media in frontend persistent storage',await page.evaluate(()=>localStorage.length===0));
  check('no browser errors',errors.length===0);
  console.log(JSON.stringify({kind:'Offline built native UI + actual packaged shared engine + harmless argv child; not installed/live chat',checks,creation_effects:1,page_errors:errors.length},null,2));
  await context.close();
}finally{
  await browser.close();bridge.stdin.end();const exit=await closed;
  fs.rmSync(temp,{recursive:true,force:true});assert.equal(exit,0);assert.equal(stderr,'');
}
