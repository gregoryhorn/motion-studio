// Offline packaged Production vertical: real React/controller/RPC/store, fake producer/host.
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
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'motion-production-browser-'));
const evidence=process.env.PRODUCTION_EVIDENCE||'docs/evidence/production-reuse-r1';fs.mkdirSync(evidence,{recursive:true});
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
const checks=[],errors=[];const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
const command=()=>crypto.randomUUID().replaceAll('-','');
async function makeTake(direction,parent=null,root='session-a'){
  const context={root,session:root+'-physical'};
  const prepared=await rpc({op:'tool',...context,args:{operation:'prepare',direction,seconds:0.1,...(parent?{parent}:{})}});
  assert.ok(!prepared.error,prepared.error);
  const identity=Object.fromEntries(['request','revision','command','run'].map(key=>[key,prepared[key]]));
  const started=await rpc({op:'tool',...context,args:{operation:'start',...identity}});assert.ok(!started.error,started.error);
  await rpc({op:'settle-creation'});const status=await rpc({op:'tool',...context,args:{operation:'status'}});assert.ok(!status.error,status.error);return status;
}
try{
  const context=await browser.newContext({serviceWorkers:'block',offline:true,acceptDownloads:true});
  await context.exposeBinding('nativeRPC',(_source,message)=>rpc(message));
  await context.addInitScript(()=>{const mode=sessionStorage.getItem('production-observation');sessionStorage.removeItem('production-observation');
    if(mode==='fail')window.fixtureFailProductionList=true;
    if(mode==='delay-empty'){window.fixtureHoldOperation='list';window.fixtureHideProductionList=true;}});
  const html='<html><body><div id="root"></div><script>'+fs.readFileSync(path.join(temp,'fixture.js'),'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
  await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:html}):route.abort());
  const page=await context.newPage();page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  const more=async(target,name)=>{await target.locator('details.ms-more').evaluate(node=>{node.open=true;});await target.getByRole('button',{name,exact:true}).click();};
  const button=name=>page.getByRole('button',{name,exact:true}),section=name=>button(name).click();
  // With no project the Brief editor is the only panel; with one, Brief is a labeled switch. Wait for the open to settle.
  const briefSection=async()=>{await expect.poll(async()=>await button('Brief').count()>0||
    await page.getByLabel('Production title').isEnabled({timeout:250}).catch(()=>false),{timeout:15000}).toBe(true);if(await button('Brief').count())await section('Brief');};
  const productionList=()=>rpc({op:'production-tool',args:{operation:'list'}});
  await page.goto('https://motion.invalid/');await button('Production').click();await more(page,'Reopen project');
  await expect(page.getByRole('status')).toContainText('This chat cannot access');
  check('Production import/open is default denied with no store or effect',!(await rpc({op:'counts'})).state_created);
  await rpc({op:'admit-creation-fixture'});await rpc({op:'admit-production-fixture'});
  await page.reload();await button('Production').click();await more(page,'Reopen project');await briefSection();
  await expect(page.getByRole('region',{name:'Brief editor',exact:true})).toBeVisible();
  await expect(button('Create project')).toBeVisible();
  const first=await makeTake('Synthetic Production original'),second=await makeTake('Synthetic Production alternative',first.request);
  const before=await rpc({op:'counts'});
  await more(page,'Reopen project');await briefSection();await page.getByLabel('Production title').fill('Synthetic retained Production');
  await page.getByRole('textbox',{name:'Brief',exact:true}).fill('Synthetic brief for connected reuse');
  await button('Create project').click();await expect(page.getByRole('list',{name:'Planned assets',exact:true})).toBeVisible();
  let opened=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a'}});
  const production=opened.current.id,sfx=opened.current.assets[0];
  await section('Plan');
  check('native brief creates all five media metadata kinds without generation',await page.locator('.production-asset').count()===5&&
    opened.current.assets.length===5&&(await rpc({op:'counts'})).creation_effects===2);
  await section('References');await page.getByLabel('Retained Quick Create take').selectOption(first.candidate);
  await button('Add as a take for the selected asset').click();await section('Review');
  await expect(page.locator('.production-take-state')).toHaveText('Take 01 - Not selected');
  opened=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a',production}});
  const sourceChunk=await rpc({op:'rpc',method:'creation.chunk',payload:{session_id:'session-a',request:first.request,take:first.candidate,offset:0}});
  check('link adds immutable alternative without automatic selection',opened.current.assets[0].selected_take===null&&
    opened.current.assets[0].takes[0].digest===sourceChunk.sha256&&opened.current.assets[0].takes[0].id===first.candidate&&
    opened.current.assets[0].takes[0].request===first.request);
  await button('Use take').click();await expect(page.locator('.production-take-state')).toHaveText('Take 01 - Selected');
  await section('References');await page.getByLabel('Retained Quick Create take').selectOption(second.candidate);await button('Add as a take for the selected asset').click();
  opened=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a',production}});
  const sourceAfter=await rpc({op:'tool',args:{operation:'status'}}),afterLinks=await rpc({op:'counts'});
  check('alternatives preserve selected pointer and exact source provenance with no take/artifact/request/run copy',
    opened.current.assets[0].selected_take===first.candidate&&opened.current.assets[0].takes.length===2&&
    afterLinks.takes===before.takes&&afterLinks.media_files===before.media_files&&afterLinks.requests===before.requests&&
    afterLinks.runs===before.runs&&afterLinks.creation_effects===before.creation_effects&&
    sourceAfter.takes.every(take=>take.selected===second.takes.find(item=>item.id===take.id)?.selected));
  await page.getByLabel('Retained Quick Create take').selectOption(first.candidate);
  await page.getByLabel('Reference label').fill('Original retained reference');await button('Save as reference').click();
  await section('Plan');await page.getByText('Dependencies and references',{exact:true}).click();await page.getByRole('checkbox',{name:'Original retained reference',exact:true}).check();await button('Save asset').click();
  await section('Outputs');await expect(page.getByText('Out of date - review again',{exact:true})).toBeVisible();
  await section('Review');await page.locator('.production-take').first().click();
  await button('Keep this take').click();
  await section('Outputs');await expect(page.getByText(/^Take \d chosen$/)).toBeVisible();
  await section('References');await page.getByLabel('Retained Quick Create take').selectOption(second.candidate);await button('Replace with chosen take').click();
  await section('Outputs');await expect(page.getByText('Out of date - review again',{exact:true})).toBeVisible();
  opened=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a',production}});
  check('reference revision marks selection stale without replacing selected take or original dependency pin',
    opened.current.assets[0].stale&&opened.current.assets[0].selected_take===first.candidate&&
    opened.current.assets[0].references[0].revision===1&&opened.current.assets[0].selection_references[0].revision===1);
  const stale=await rpc({op:'rpc',method:'production.select_take',payload:{session_id:'session-a',command:command(),production,
    expected:1,asset:sfx.id,request:second.request,take:second.candidate}});
  check('stale expected revision rejects selection atomically',stale.error==='PRODUCTION_STALE_REVISION');
  await section('Review');await page.evaluate(()=>{window.fixtureWrongTake=true;});await button('Play').click();
  await expect(page.getByRole('status')).toContainText('could not be verified');
  check('packaged Production controller rejects wrong-take first chunk and publishes no audio',
    await page.getByLabel('Selected take audio').count()===0);
  await page.evaluate(()=>{window.fixtureWrongTake=false;});await button('Play').click();
  await expect(page.getByRole('status')).toContainText('Original ready');
  const audio=page.getByLabel('Selected take audio');await expect(audio).toHaveAttribute('src',/^blob:/);
  const playing=await audio.evaluate(async element=>{element.muted=true;await element.play();return !element.paused;});
  const downloadEvent=page.waitForEvent('download');await page.getByRole('link',{name:'Save / download original WAV',exact:true}).click();
  const download=await downloadEvent,bytes=fs.readFileSync(await download.path());
  const retained=await rpc({op:'rpc',method:'production.chunk',payload:{session_id:'session-a',production,asset:sfx.id,
    request:first.request,take:first.candidate,offset:0}});
  check('central player and download use exact linked original retained bytes',playing&&bytes.length===retained.total&&
    crypto.createHash('sha256').update(bytes).digest('hex')===retained.sha256);
  await section('Review');await page.locator('.production-take').first().click();await button('Play').click();
  await expect(page.getByRole('status')).toContainText('Original ready');
  check('changing central review leaves one paused audio element and no unintended simultaneous playback',
    await page.locator('audio').count()===1&&await page.locator('audio').evaluate(element=>element.paused));
  await page.setViewportSize({width:1280,height:900});await page.screenshot({path:path.join(evidence,'production-wide.png'),fullPage:true});
  await page.setViewportSize({width:760,height:900});
  const columns=await page.locator('.production-layout').evaluate(element=>getComputedStyle(element).gridTemplateColumns);
  check('narrow layout is one column and Review has no simultaneously rendered brief editor',
    !columns.includes(' ')&&await page.getByRole('textbox',{name:'Brief',exact:true}).count()===0&&
    await button('Plan').isVisible()&&await button('References').isVisible()&&await button('Outputs').isVisible());
  await section('Plan');await page.locator('.production-asset').nth(3).focus();await page.locator('.production-asset').nth(3).press('Enter');
  await expect(page.getByRole('heading',{name:'4. Image',exact:true})).toBeVisible();
  await page.locator('.production-asset').first().press('Enter');await section('Review');
  await page.screenshot({path:path.join(evidence,'production-narrow.png'),fullPage:true});
  check('narrow labeled switches and keyboard asset activation preserve central Review',true);
  const agent=await rpc({op:'production-tool',session:'compressed-physical',args:{operation:'open',production}});
  check('agent compressed physical session and native RPC reach same root projection',agent.current.id===production&&
    agent.current.revision===opened.current.revision&&agent.current.assets[0].selected_take===first.candidate);
  await briefSection();await page.getByLabel('Production title').fill('Successive brief one');await button('Save brief').click();
  await page.getByLabel('Production title').fill('Successive brief two');await button('Save brief').click();
  opened=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a',production}});
  check('two successive brief saves advance acknowledged draft base without discard',opened.current.title==='Successive brief two');
  await section('Plan');await page.getByLabel('Asset intent',{exact:true}).fill('Successive asset one');await button('Save asset').click();
  await page.getByLabel('Asset intent',{exact:true}).fill('Successive asset two');await button('Save asset').click();
  opened=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a',production}});
  check('two successive asset saves advance acknowledged draft base without discard',opened.current.assets[0].intent==='Successive asset two');
  await briefSection();await page.getByLabel('Production title').fill('Stale visual title must not overwrite');
  const agentBrief=await rpc({op:'production-tool',args:{operation:'update_brief',command:command(),production,
    expected:opened.current.revision,title:'Agent intervening saved title',brief:opened.current.brief}});
  await more(page,'Refresh');await expect(page.getByLabel('Production title')).toHaveValue('Stale visual title must not overwrite');
  await button('Save brief').click();await expect(page.getByRole('status')).toContainText('The project changed');
  const afterStaleBrief=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a',production}});
  check('stale brief draft keeps base revision and cannot overwrite intervening agent edit',
    afterStaleBrief.current.title==='Agent intervening saved title'&&afterStaleBrief.current.revision===agentBrief.current.revision&&
    await page.getByLabel('Production title').inputValue()==='Stale visual title must not overwrite');
  await button('Discard changes').click();await expect(page.getByLabel('Production title')).toHaveValue('Agent intervening saved title');
  await section('Plan');await page.getByLabel('Asset intent',{exact:true}).fill('Stale visual asset intent');
  const assetAgent=await rpc({op:'production-tool',args:{operation:'update_asset',command:command(),production,
    expected:afterStaleBrief.current.revision,asset:sfx.id,kind:'Sound effects',intent:'Agent intervening asset intent',
    position:0,depends_on:[],references:afterStaleBrief.current.assets[0].references.map(ref=>ref.id)}});
  await more(page,'Refresh');await button('Save asset').click();
  await expect(page.getByRole('status')).toContainText('The project changed');
  const afterStaleAsset=await rpc({op:'rpc',method:'production.open',payload:{session_id:'session-a',production}});
  check('stale asset draft cannot overwrite newer agent plan and remains for deliberate discard',
    afterStaleAsset.current.assets[0].intent==='Agent intervening asset intent'&&
    afterStaleAsset.current.revision===assetAgent.current.revision&&await page.getByLabel('Asset intent',{exact:true}).inputValue()==='Stale visual asset intent');
  await button('Discard changes').click();await expect(page.getByLabel('Asset intent',{exact:true})).toHaveValue('Agent intervening asset intent');
  await rpc({op:'rpc',method:'creation.admit',payload:{session_id:'session-b'}});
  await rpc({op:'rpc',method:'production.admit',payload:{session_id:'session-b'}});
  await makeTake('Synthetic B retained source',null,'session-b');const afterBSource=await rpc({op:'counts'});
  await page.getByLabel('New asset intent').fill('Synthetic A private new intent');
  await page.evaluate(()=>{const old=[...document.querySelectorAll('button')].find(element=>element.textContent==='Add asset');
    window.fixtureSession('session-b');old.click();});
  check('old A Add asset closure cannot submit A intent into B',
    await page.evaluate(()=>window.fixtureRequests.filter(item=>item.method.endsWith('.add_asset')).length)===0);
  await page.evaluate(()=>{window.fixtureSession('away-root');window.fixtureSession('session-a');});await more(page,'Reopen project');await section('References');
  await page.getByLabel('Reference label').fill('Synthetic A private reference label');
  await page.evaluate(()=>{const old=[...document.querySelectorAll('button')].find(element=>element.textContent==='Save as reference');
    window.fixtureSession('session-b');old.click();});
  check('old A Add reference closure cannot submit A label into B',
    await page.evaluate(()=>window.fixtureRequests.filter(item=>item.method.endsWith('.add_reference')).length)===1);
  await more(page,'Reopen project');await briefSection();
  await page.getByLabel('Production title').fill('Synthetic B production');
  await page.getByRole('textbox',{name:'Brief',exact:true}).fill('Synthetic B production brief');
  await button('Create project').click();await expect(button('Brief')).toBeVisible();
  await section('Plan');check('B New asset intent is empty after A to B reopen',await page.getByLabel('New asset intent').inputValue()==='');
  await section('References');
  check('B Reference label is empty and no A private draft text is rendered',await page.getByLabel('Reference label').inputValue()===''&&
    await page.getByText('Synthetic A private new intent',{exact:true}).count()===0&&
    await page.getByText('Synthetic A private reference label',{exact:true}).count()===0);
  await page.evaluate(()=>{window.fixtureSession('away-root');window.fixtureSession('session-a');});await more(page,'Reopen project');await briefSection();
  await expect(page.getByLabel('Production title')).toHaveValue('Agent intervening saved title');
  await page.getByRole('textbox',{name:'Brief',exact:true}).fill('Synthetic A delayed saved context');
  const delayedBefore=await page.evaluate(()=>window.fixtureRequests.filter(item=>item.method.endsWith('.update_brief')).length);
  await page.evaluate(()=>{window.fixtureHoldOperation='update_brief';});await button('Save brief').click();
  await expect.poll(()=>page.evaluate(()=>Boolean(window.fixtureReleaseOperation))).toBe(true);
  await page.evaluate(()=>{window.fixtureSession('session-b');window.fixtureReleaseOperation();});
  await expect(page.getByRole('status')).toContainText('The selected chat changed');
  check('scope switch during awaited save clears private projection and does not retry mutation',
    (await page.evaluate(()=>window.fixtureRequests.filter(item=>item.method.endsWith('.update_brief')).length))===delayedBefore+1);
  await more(page,'Reopen project');await briefSection();await expect(page.getByLabel('Production title')).toHaveValue('Synthetic B production');
  check('wrong root opens only B saved state and no delayed A text',
    await page.getByRole('textbox',{name:'Brief',exact:true}).inputValue()!=='Synthetic A delayed saved context');
  await page.evaluate(()=>{window.fixtureSession('away-root');window.fixtureSession('session-a');});await more(page,'Reopen project');await briefSection();
  await expect(page.getByLabel('Production title')).toHaveValue('Agent intervening saved title');
  await page.getByLabel('Purpose (optional)').fill('Synthetic same-scope typing');await more(page,'Refresh');
  await expect(page.getByLabel('Purpose (optional)')).toHaveValue('Synthetic same-scope typing');
  check('away-and-back requires reopen and same-scope refresh preserves text context',true);
  await button('New project').click();
  await expect(page.getByRole('region',{name:'Brief editor',exact:true})).toBeVisible();
  await expect(button('Create project')).toBeVisible();
  await expect(page.getByLabel('Production title')).toHaveValue('');
  await expect(page.getByRole('textbox',{name:'Brief',exact:true})).toHaveValue('');
  await page.getByLabel('Production title').fill('Synthetic visual lost create');
  await page.getByRole('textbox',{name:'Brief',exact:true}).fill('Synthetic visual lost brief');
  const createCount=()=>page.evaluate(()=>window.fixtureRequests.filter(item=>item.method.endsWith('.production.create')).length);
  const visualCreateBaseline=await createCount();
  await page.evaluate(()=>{window.fixtureLoseProductionCreate=true;});await button('Create project').click();
  await expect(page.getByRole('status')).toContainText('Reply unobserved');
  await expect(page.locator('.production-notice')).toHaveCount(0);
  const lostRequest=await page.evaluate(()=>window.fixtureRequests.find(item=>item.method.endsWith('.production.create')&&
    item.payload.title==='Synthetic visual lost create').payload);
  await button('Create project').evaluate(element=>element.click());
  check('second visual Create after unknown reply cannot mint another command',await createCount()===visualCreateBaseline+1);
  check('visual lost Create committed exactly one discoverable Production',
    (await productionList()).productions.filter(item=>item.title==='Synthetic visual lost create').length===1);
  for(const observation of ['failed','empty']){
    const marker=await page.evaluate(()=>localStorage.getItem('motion-studio.production.unresolved-create-v1'));
    await page.evaluate(mode=>{window.fixtureSession('session-b');window.fixtureSession('session-a');
      window.fixtureFailProductionList=mode==='failed';window.fixtureHideProductionList=mode==='empty';},observation);
    await more(page,'Reopen project');await briefSection();
    await expect(page.getByRole('status')).toContainText(observation==='failed'?'This chat cannot access':'Check interrupted save');
    await button('Create project').evaluate(element=>element.click());
    check('away/back without intermediate reopen plus '+observation+' observation preserves exact marker and dispatch count',
      await createCount()===visualCreateBaseline+1&&await page.evaluate(()=>localStorage.getItem('motion-studio.production.unresolved-create-v1'))===marker);
  }
  await page.evaluate(()=>sessionStorage.setItem('production-observation','fail'));await page.reload();await button('Production').click();
  await expect(page.getByRole('status')).toContainText('This chat cannot access');await briefSection();
  await button('Create project').evaluate(element=>element.click());
  check('actual reload followed by failed initial observation keeps replacement Create locked',
    (await productionList()).productions.filter(item=>item.title==='Synthetic visual lost create').length===1);
  await page.evaluate(()=>sessionStorage.setItem('production-observation','delay-empty'));await page.reload();await button('Production').click();
  await expect.poll(()=>page.evaluate(()=>Boolean(window.fixtureReleaseOperation))).toBe(true);
  // The Brief editor is already the only panel while the held list keeps the page busy.
  await button('Create project').evaluate(element=>element.click());
  await page.evaluate(()=>{window.fixtureReleaseOperation();window.fixtureHoldOperation=null;});
  await expect(page.getByRole('status')).toContainText('Check interrupted save');
  await page.evaluate(()=>{window.fixtureHideProductionList=false;});
  await button('Create project').evaluate(element=>element.click());
  check('delayed empty observation is not non-commit proof and cannot unlock replacement',
    (await productionList()).productions.filter(item=>item.title==='Synthetic visual lost create').length===1);
  await more(page,'Reopen project');await briefSection();await expect(page.getByLabel('Production title')).toHaveValue('Synthetic visual lost create');
  const {session_id:transportSession,...replayArgs}=lostRequest;
  const replay=await rpc({op:'production-tool',session:'new-compressed-segment',args:{operation:'create',...replayArgs}});
  assert.ok(replay.replayed&&replay.receipt?.revision===1,JSON.stringify(replay));
  check('exact saved command replay returns original receipt after visual recovery',true);
  await button('Quick Create').click();check('leaving Production disposes central audio and private projection',await page.locator('audio').count()===0);
  await button('Production').click();await more(page,'Reopen project');await briefSection();
  await expect(page.getByLabel('Production title')).toHaveValue('Synthetic visual lost create');
  // Real server policy revocation, with unchanged SDK atoms, after actual original-byte loading.
  // Separate pages isolate uncertain mutation memory while preserving the same backend records.
  for(const action of ['refresh','mutation']){
    const revokedPage=await context.newPage();revokedPage.on('pageerror',()=>errors.push('PAGE_ERROR'));
    await revokedPage.goto('https://motion.invalid/');
    const rb=name=>revokedPage.getByRole('button',{name,exact:true});
    await rb('Production').click();await more(revokedPage,'Reopen project');
    await revokedPage.getByLabel('Project').selectOption(production);
    await expect(revokedPage.locator('.production-take-state')).toHaveText(/- Selected$/);
    await rb('Play').click();
    const player=revokedPage.getByLabel('Selected take audio');await expect(player).toHaveAttribute('src',/^blob:/);
    const blob=await player.getAttribute('src');
    if(action==='mutation'){await rb('Brief').click();await revokedPage.getByLabel('Production title').fill('Rejected revoked edit');}
    const savedBefore=await rpc({op:'production-tool',args:{operation:'open',production}});
    const countBefore=await rpc({op:'counts'});await rpc({op:'revoke-production-fixture'});
    await (action==='refresh'?more(revokedPage,'Refresh'):rb('Save brief').click());
    await expect(revokedPage.getByRole('status')).toContainText('This chat cannot access');
    const revoked=await revokedPage.evaluate(async original=>({
      atomsUnchanged:window.fixtureRequests.at(-1).payload.session_id==='session-a',
      blobRevoked:await fetch(original).then(()=>false,()=>true),
      marker:document.querySelector('audio')===null
    }),blob);
    check('actual server revoke on '+action+' clears rows/player/Blob with unchanged host scope',revoked.atomsUnchanged&&revoked.blobRevoked&&revoked.marker&&
      await revokedPage.getByLabel('Project').count()===0&&
      await revokedPage.getByRole('option').count()===0);
    if(action==='mutation'){
      // No project is open after the denial, so the Brief editor is already the only panel.
      check('revoked mutation retains unresolved identity without private draft',
        await rb('Check interrupted save').count()===1&&await revokedPage.getByLabel('Production title').inputValue()==='');
    }
    await rpc({op:'admit-production-fixture'});
    const savedAfter=await rpc({op:'production-tool',args:{operation:'open',production}});
    check('authority return on '+action+' preserves committed records and does not auto-reopen',
      JSON.stringify(savedBefore)===JSON.stringify(savedAfter)&&
      (await rpc({op:'counts'})).production_revisions===countBefore.production_revisions&&
      await revokedPage.getByLabel('Project').count()===0);
    await more(revokedPage,'Reopen project');
    await revokedPage.getByLabel('Project').selectOption(production);await rb('Brief').click();
    await expect(revokedPage.getByLabel('Production title')).toHaveValue(savedBefore.current.title);
    check('explicit reopen after '+action+' revocation observes saved head without replay',
      (await rpc({op:'counts'})).production_revisions===countBefore.production_revisions);
    await revokedPage.close();
  }
  const final=await rpc({op:'counts'});
  check('whole visual/agent reuse flow adds no takes, media, requests, runs or generation beyond three fixture sources',
    final.takes===afterBSource.takes&&final.media_files===afterBSource.media_files&&final.requests===afterBSource.requests&&
    final.runs===afterBSource.runs&&final.creation_effects===afterBSource.creation_effects);
  check('no browser errors or persistent state beyond cleared opaque recovery marker',errors.length===0&&await page.evaluate(()=>localStorage.length===0));
  console.log(JSON.stringify({kind:'Offline packaged Production retained-take vertical; not installed/live/full Production',
    checks,creation_effects:final.creation_effects,page_errors:errors.length,evidence},null,2));
  await context.close();
}finally{
  await browser.close();bridge.stdin.end();const exit=await closed;fs.rmSync(temp,{recursive:true,force:true});
  assert.equal(exit,0);assert.equal(stderr,'');
}
