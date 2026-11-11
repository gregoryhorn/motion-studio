// Offline packaged Production Music authority/privacy; synthetic child only.
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
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'motion-music-authority-'));
const evidence=process.env.MUSIC_EVIDENCE||'docs/evidence/music-authority-r2';
fs.mkdirSync(evidence,{recursive:true});
execFileSync('python',['-m','zipfile','-e',process.env.NATIVE_BUNDLE,temp]);
execFileSync(process.env.ESBUILD,['tests/native-browser-fixture.js','--bundle','--format=iife','--platform=browser','--log-level=error',
  '--alias:motion-studio-package='+path.join(temp,'motion-studio/desktop/plugin.js'),
  '--alias:@hermes/plugin-sdk='+path.resolve('tests/native-sdk-browser.js'),'--outfile='+path.join(temp,'fixture.js')]);
const bridge=spawn('python',['-m','tests.native_package_fixture'],{stdio:['pipe','pipe','pipe']});
let sequence=0,stderr='';const waiting=new Map();bridge.stderr.on('data',c=>{stderr+=c;});
const closed=new Promise(resolve=>bridge.once('exit',code=>{for(const entry of waiting.values())entry.reject(Error('Fixture exited'));resolve(code);}));
createInterface({input:bridge.stdout}).on('line',line=>{const row=JSON.parse(line),entry=waiting.get(row.id);waiting.delete(row.id);
  row.error?entry.reject(Error('FIXTURE_OPERATION_FAILED')):entry.resolve(row.result);});
const rpc=message=>new Promise((resolve,reject)=>{const id=++sequence;waiting.set(id,{resolve,reject});bridge.stdin.write(JSON.stringify({id,...message})+'\n');});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const command=()=>crypto.randomUUID().replaceAll('-','');
const checks=[],errors=[],check=(name,value)=>{assert.ok(value,name);checks.push(name);};
try{
  await rpc({op:'admit-creation-fixture'});await rpc({op:'admit-music-fixture'});await rpc({op:'admit-production-fixture'});
  const source=await rpc({op:'tool',args:{operation:'prepare',schema_version:2,kind:'Music',seconds:10,direction:'Synthetic private Music source'}});
  assert.ok(!source.error,source.error);
  await rpc({op:'tool',args:{operation:'start',...Object.fromEntries(['request','revision','command','run'].map(k=>[k,source[k]]))}});
  await rpc({op:'settle-creation'});
  let row=await rpc({op:'production-tool',args:{operation:'create',command:command(),title:'Synthetic Music privacy',
    kinds:['Sound effects','Music','Voice','Image','Video'],brief:{text:'Synthetic private brief'}}});
  const production=row.current.id,asset=row.current.assets.find(item=>item.kind==='Music').id;
  row=await rpc({op:'production-tool',args:{operation:'link_take',command:command(),production,expected:row.current.revision,
    asset,request:source.request,take:source.candidate}});
  assert.ok(!row.error,row.error);
  const context=await browser.newContext({serviceWorkers:'block',offline:true,acceptDownloads:true});
  await context.exposeBinding('nativeRPC',(_source,message)=>rpc(message));
  const html='<html><body><div id="root"></div><script>'+fs.readFileSync(path.join(temp,'fixture.js'),'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
  await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:html}):route.abort());
  const page=await context.newPage();page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  const button=name=>page.getByRole('button',{name,exact:true});
  await page.goto('https://motion.invalid/');await button('Production').click();await button('Open / reconcile').click();
  await page.getByLabel('Review asset',{exact:true}).selectOption(asset);await button('Takes').click();
  await page.getByRole('button',{name:/^Review .* take$/}).click();await button('Load original audio').click();
  const audio=page.getByLabel('Production original retained audio');await expect(audio).toHaveAttribute('src',/^blob:/);
  const blob=await audio.getAttribute('src');
  const playing=await audio.evaluate(async element=>{element.muted=true;await element.play();return !element.paused;});
  const downloadEvent=page.waitForEvent('download');await page.getByRole('link',{name:'Save / download original WAV',exact:true}).click();
  const download=await downloadEvent,bytes=fs.readFileSync(await download.path());
  const retained=await rpc({op:'rpc',method:'creation.chunk',payload:{session_id:'session-a',request:source.request,take:source.candidate,offset:0}});
  check('authorized Production Music playback/download is exact retained PCM16 derivative',playing&&bytes.length===retained.total&&
    crypto.createHash('sha256').update(bytes).digest('hex')===retained.sha256);
  await button('Brief').click();await page.getByLabel('Production title').fill('Synthetic unsaved private title');
  await button('Plan').click();await page.getByLabel('Asset intent',{exact:true}).fill('Synthetic unsaved private asset');
  await page.getByLabel('New asset intent').fill('Synthetic unsaved new asset');
  await button('References').click();await page.getByLabel('Reference label').fill('Synthetic unsaved private reference');
  await button('Review').click();await button('Load original audio').click();await expect(audio).toHaveAttribute('src',/^blob:/);
  const secondBlob=await audio.getAttribute('src');
  await rpc({op:'revoke-music-fixture'});await button('Refresh saved revision').click();
  await expect(page.getByRole('status')).toContainText('MUSIC_SCOPE_REVIEW_REQUIRED');
  check('server Music denial clears private rows, current selection and audio without host atom changes',
    await page.locator('audio').count()===0&&await page.getByLabel('Reopen saved Production').count()===0&&
    !(await page.locator('body').innerText()).includes(source.candidate));
  check('both previously published Blob URLs are revoked',await page.evaluate(async urls=>{
    const failed=await Promise.all(urls.map(url=>fetch(url).then(()=>false,()=>true)));return failed.every(Boolean);
  },[blob,secondBlob]));
  await button('Brief').click();await expect(page.getByLabel('Production title')).toHaveValue('');
  await expect(page.getByRole('textbox',{name:'Brief',exact:true})).toHaveValue('');
  await button('Plan').click();
  check('Music denial invalidates brief, asset and new-asset private drafts',
    await page.getByLabel('New asset intent').count()===0&&await page.getByLabel('Asset intent',{exact:true}).count()===0);
  await button('References').click();
  check('Music denial clears retained directions, reference labels and sources',await page.getByLabel('Reference label').count()===0&&
    await page.getByLabel('Retained Quick Create take').count()===0&&!(await page.locator('body').innerText()).includes('Synthetic private Music source'));
  const denied=await rpc({op:'rpc',method:'production.chunk',payload:{session_id:'session-a',production,asset,request:source.request,take:source.candidate,offset:0}});
  check('packaged backend denies bytes rather than trusting Production association',denied.error==='MUSIC_SCOPE_REVIEW_REQUIRED');
  check('native storage contains no private text or media',await page.evaluate(()=>!JSON.stringify(localStorage).includes('Synthetic')));
  await page.screenshot({path:path.join(evidence,'music-authority-denied.png'),fullPage:true});
  check('one synthetic Music execution, no model/provider call', (await rpc({op:'counts'})).music_effects===1&&(await rpc({op:'counts'})).model_calls===0);
  check('no browser page errors',errors.length===0);
  console.log(JSON.stringify({kind:'SOURCE/OFFLINE packaged Production Music authority; synthetic bytes, no ACE/live qualification',checks,page_errors:errors.length},null,2));
  await context.close();
}finally{
  await browser.close();bridge.stdin.end();const exit=await closed;fs.rmSync(temp,{recursive:true,force:true});assert.equal(exit,0);assert.equal(stderr,'');
}
