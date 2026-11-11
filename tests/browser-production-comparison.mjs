// Packaged React/RPC/store comparison; synthetic distinct tones, no native/live effects.
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
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'motion-comparison-browser-'));
const evidence=process.env.COMPARISON_EVIDENCE||'docs/evidence/production-comparison-r1';fs.mkdirSync(evidence,{recursive:true});
execFileSync('python',['-m','zipfile','-e',process.env.NATIVE_BUNDLE,temp]);
execFileSync(process.env.ESBUILD,['tests/native-browser-fixture.js','--bundle','--format=iife','--platform=browser','--log-level=error',
  '--alias:motion-studio-package='+path.join(temp,'motion-studio/desktop/plugin.js'),
  '--alias:@hermes/plugin-sdk='+path.resolve('tests/native-sdk-browser.js'),'--outfile='+path.join(temp,'fixture.js')]);
const bridge=spawn('python',['-m','tests.native_package_fixture'],{stdio:['pipe','pipe','pipe']});
let sequence=0,stderr='';const waiting=new Map();bridge.stderr.on('data',chunk=>{stderr+=chunk;});
const closed=new Promise(resolve=>bridge.once('exit',code=>{for(const entry of waiting.values())entry.reject(Error('Fixture exited'));resolve(code);}));
createInterface({input:bridge.stdout}).on('line',line=>{const value=JSON.parse(line),entry=waiting.get(value.id);waiting.delete(value.id);
  value.error?entry.reject(Error('FIXTURE_OPERATION_FAILED: '+entry.operation)):entry.resolve(value.result);});
const rpc=message=>new Promise((resolve,reject)=>{const id=++sequence;waiting.set(id,{resolve,reject,operation:message.op});bridge.stdin.write(JSON.stringify({id,...message})+'\n');});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const checks=[],errors=[],fixtures=[];const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
const command=()=>crypto.randomUUID().replaceAll('-','');
async function makeTake(direction,seconds,seed,parent=null){
  const prepared=await rpc({op:'tool',args:{operation:'prepare',direction,seconds,seed,...(parent?{parent}:{})}});
  assert.ok(!prepared.error,prepared.error);const identity=Object.fromEntries(['request','revision','command','run'].map(key=>[key,prepared[key]]));
  const started=await rpc({op:'tool',args:{operation:'start',...identity}});assert.ok(!started.error,started.error);
  await rpc({op:'settle-creation'});const status=await rpc({op:'tool',args:{operation:'status'}});assert.ok(!status.error,status.error);return status;
}
try{
  await rpc({op:'admit-creation-fixture',fixture_mode:'comparison'});await rpc({op:'admit-production-fixture'});
  const first=await makeTake('Controlled A - low 220 Hz tone - 1.4 seconds',1.4,220);
  const second=await makeTake('Controlled B - high 660 Hz tone - 0.8 seconds',0.8,660,first.request);
  const created=await rpc({op:'production-tool',args:{operation:'create',command:command(),title:'Controlled SFX comparison',
    brief:{text:'Two nonprivate tone alternatives; listening not reviewed.'},kinds:['Sound effects','Music','Voice','Image','Video']}});
  const production=created.current.id,asset=created.current.assets[0].id;
  let revision=created.current.revision;
  for(const take of [first,second]){
    const linked=await rpc({op:'production-tool',args:{operation:'link_take',command:command(),production,expected:revision,
      asset,request:take.request,take:take.candidate}});assert.ok(!linked.error,linked.error);revision=linked.current.revision;
  }
  const selected=await rpc({op:'production-tool',args:{operation:'select_take',command:command(),production,expected:revision,
    asset,request:first.request,take:first.candidate}});revision=selected.current.revision;
  await rpc({op:'production-tool',args:{operation:'update_brief',command:command(),production,expected:revision,
    title:'Controlled SFX comparison',brief:{text:'Revised context; selected A stays stale until explicit Use take.'}}});
  const before=await rpc({op:'counts'});
  for(const [index,take] of [first,second].entries()){
    let offset=0,total=1,parts=[],sha;
    while(offset<total){const chunk=await rpc({op:'rpc',method:'production.chunk',payload:{session_id:'session-a',production,asset,
      request:take.request,take:take.candidate,offset}});const bytes=Buffer.from(chunk.bytes,'base64');parts.push(bytes);offset+=bytes.length;total=chunk.total;sha=chunk.sha256;}
    const bytes=Buffer.concat(parts);assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),sha);
    const file=index===0?'controlled-a-220hz-1.4s.wav':'controlled-b-660hz-0.8s.wav';fs.writeFileSync(path.join(evidence,file),bytes);
    fixtures.push({file,sha256:sha,bytes:bytes.length,frequency:index===0?220:660,seconds:index===0?1.4:0.8});
  }
  const context=await browser.newContext({serviceWorkers:'block',offline:true,reducedMotion:'reduce'});
  await context.exposeBinding('nativeRPC',(_source,message)=>rpc(message));
  const html='<html><body><div id="root"></div><script>'+fs.readFileSync(path.join(temp,'fixture.js'),'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
  await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:html}):route.abort());
  const page=await context.newPage();page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  const more=async(target,name)=>{await target.locator('details.ms-more').evaluate(node=>{node.open=true;});await target.getByRole('button',{name,exact:true}).click();};
  const button=name=>page.getByRole('button',{name,exact:true});
  const comparison=()=>page.getByRole('region',{name:'Compare two takes',exact:true});
  const status=()=>page.getByRole('status',{name:'Comparison status',exact:true});
  const audio=()=>page.getByLabel('Sound effects A/B comparison audio');
  const open=async()=>{await button('Compare').click();await expect(comparison()).toBeVisible();};
  const choose=async(slot,id)=>{await page.getByLabel('Comparison take '+slot,{exact:true}).selectOption(id);
    await expect(button('Listen to '+slot)).toBeEnabled();};
  const activate=async slot=>{await button('Listen to '+slot).click();await expect.poll(()=>audio().evaluate(el=>el.readyState)).toBeGreaterThan(0);};
  await page.goto('https://motion.invalid/');await button('Production').click();await expect(button('Compare')).toBeEnabled();await open();
  await choose('A',first.candidate);await choose('B',second.candidate);
  check('two clearly named exact takes show selected/stale and Not reviewed states',
    await comparison().getByText('Selected, but out of date: the brief or a dependency changed',{exact:true}).count()===1&&
    await comparison().getByText('Listening review: Not reviewed',{exact:true}).count()===2&&
    await comparison().locator('p').filter({hasText:'Take 1 - Controlled A - low 220 Hz tone - 1.4 seconds'}).count()===1);
  const detailsA=comparison().locator('summary').filter({hasText:'Technical details for A'});
  await expect(comparison().getByText('Take '+first.candidate+' / source request revision 1',{exact:true})).toBeHidden();
  await detailsA.focus();await detailsA.press('Enter');
  await expect(comparison().getByText('Take '+first.candidate+' / source request revision 1',{exact:true})).toBeVisible();
  await detailsA.press('Space');
  check('exact identity details are keyboard accessible while warnings stay visible',
    await comparison().getByText('Selected, but out of date: the brief or a dependency changed',{exact:true}).isVisible());
  check('primary take options use readable unique labels without full opaque IDs',await page.getByLabel('Comparison take A',{exact:true})
    .locator('option').evaluateAll(options=>options.every(option=>!/[a-f0-9]{32}/.test(option.textContent))));
  await activate('A');await page.getByLabel('Comparison position seconds').fill('0.25');
  await page.getByLabel('Shared monitoring volume').fill('0.37');
  check('loading verified source never plays automatically',await audio().evaluate(el=>el.paused&&Math.abs(el.currentTime-0.25)<0.01));
  await button('Play A').click();await expect.poll(()=>audio().evaluate(el=>el.paused)).toBe(false);
  await activate('B');
  check('one real audio element, A/B switch paused at common absolute position and identical gain',
    await page.locator('audio').count()===1&&await audio().evaluate(el=>el.paused&&Math.abs(el.currentTime-0.25)<0.01&&el.volume===0.37));
  await expect(comparison().getByText('Playback duration: 0.800 seconds',{exact:true})).toBeVisible();
  await page.getByLabel('Comparison position seconds').fill('1');await button('Play B').click();
  await expect(status()).toContainText('at or beyond the end');check('shorter B does not clamp or start at zero',await audio().evaluate(el=>el.paused));
  await page.getByLabel('Comparison position seconds').fill('');await button('Play B').click();await expect(status()).toContainText('finite position');
  check('blank position is not converted to zero',await audio().evaluate(el=>el.paused));
  await page.getByLabel('Comparison position seconds').fill('0.75');await button('Play B').click();await expect(status()).toContainText('Other take did not start');
  check('end has no loop or automatic A playback',await audio().evaluate(el=>el.paused&&!el.loop));
  await activate('A');await page.getByLabel('Comparison position seconds').fill('0.25');
  const keyboardPlayer=page.getByRole('group',{name:'Comparison keyboard player',exact:true});
  await keyboardPlayer.focus();await keyboardPlayer.press('Space');await expect.poll(()=>audio().evaluate(el=>el.paused)).toBe(false);
  await keyboardPlayer.press('Space');check('focused visible player Space controls explicit playback',await audio().evaluate(el=>el.paused));
  const afterCompare=await rpc({op:'counts'});check('comparison creates no new revision, take, artifact, request, run or effect',JSON.stringify(afterCompare)===JSON.stringify(before));
  check('no private drafts or audio persisted by comparison',await page.evaluate(()=>localStorage.length===0));
  await page.setViewportSize({width:1360,height:1000});await page.screenshot({path:path.join(evidence,'comparison-wide.png'),fullPage:true});
  await page.setViewportSize({width:390,height:900});
  check('narrow controls reflow without horizontal page overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(evidence,'comparison-narrow.png'),fullPage:true});
  await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});
  check('200 percent text reflow retains controls with no page overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)&&await button('Close comparison').isVisible());
  await page.screenshot({path:path.join(evidence,'comparison-reflow.png'),fullPage:true});await page.evaluate(()=>{document.documentElement.style.fontSize='';});
  await button('Close comparison').click();await expect(button('Compare')).toBeFocused();
  check('close restores invoking focus and removes audio',await page.locator('audio').count()===0);
  await open();await choose('A',first.candidate);await page.evaluate(()=>{window.fixtureHoldOperation='chunk';});
  await page.getByLabel('Comparison take B',{exact:true}).selectOption(second.candidate);
  await expect.poll(()=>page.evaluate(()=>Boolean(window.fixtureReleaseOperation))).toBe(true);
  await button('Close comparison').click();await page.evaluate(()=>{window.fixtureHoldOperation=null;window.fixtureReleaseOperation();window.fixtureReleaseOperation=null;});
  await expect(comparison()).toHaveCount(0);check('close during awaited chunk cannot resurrect comparison',await page.locator('audio').count()===0);
  await open();await page.evaluate(()=>{window.fixtureHoldOperation='chunk';});await page.getByLabel('Comparison take A',{exact:true}).selectOption(first.candidate);
  await expect.poll(()=>page.evaluate(()=>Boolean(window.fixtureReleaseOperation))).toBe(true);
  await page.getByLabel('Comparison take A',{exact:true}).selectOption('');
  await page.evaluate(()=>{window.fixtureHoldOperation=null;window.fixtureReleaseOperation();window.fixtureReleaseOperation=null;});
  await expect(button('Listen to A')).toBeDisabled();check('slot cleared during asynchronous read rejects stale bytes',true);
  await choose('A',first.candidate);await activate('A');await button('Play A').click();await button('Brief').click();
  check('section navigation disposes active comparison and sound',await page.locator('audio').count()===0);
  await button('Review').click();await open();await choose('A',first.candidate);await activate('A');
  await button('Use take A').click();await expect(comparison()).toHaveCount(0);
  await expect(button('Compare')).toBeFocused();
  const reused=await rpc({op:'production-tool',args:{operation:'open',production}});
  check('only explicit Use take accepts stale pins through existing revisioned selection',!reused.current.assets[0].stale&&reused.current.assets[0].selected_take===first.candidate);
  await open();await choose('A',first.candidate);await choose('B',second.candidate);
  await rpc({op:'production-tool',args:{operation:'select_take',command:command(),production,expected:reused.current.revision,
    asset,request:second.request,take:second.candidate}});await more(page,'Refresh');
  await expect(comparison()).toHaveCount(0);
  check('observed revision and selection change disposes previous comparison',await comparison().count()===0);
  await button('Play').click();await expect(page.getByLabel('Selected take audio')).toHaveAttribute('src',/^blob:/);
  check('single-take review still works after comparison disposal',true);
  await open();await choose('A',first.candidate);await activate('A');await button('Play A').click();
  await page.evaluate(()=>{window.fixtureSession('away-root');window.fixtureSession('session-a');});
  await expect(comparison()).toHaveCount(0);check('away-and-back scope loss clears private labels and player',await page.locator('audio').count()===0&&await page.getByText('Controlled A - low 220 Hz tone - 1.4 seconds',{exact:true}).count()===0);
  await more(page,'Reopen project');await open();await choose('A',first.candidate);await activate('A');await rpc({op:'revoke-production-fixture'});
  await page.getByLabel('Comparison take B',{exact:true}).selectOption(second.candidate);
  await expect(comparison()).toHaveCount(0);check('authority loss without host-atom changes clears all comparison labels and media',await page.locator('audio').count()===0);
  check('packaged browser has no uncaught page errors',errors.length===0);
  console.log(JSON.stringify({checks:checks.length,passed:checks,errors,fixtures,native:false,listening:'Not reviewed'},null,2));
  await context.close();
}finally{
  await browser.close();bridge.stdin.end();const code=await closed;fs.writeFileSync(path.join(evidence,'browser-stderr.txt'),stderr);
  fs.rmSync(temp,{recursive:true,force:true});assert.equal(code,0,stderr);
}
