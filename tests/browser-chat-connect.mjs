// Packaged UI -> real admission/store; isolated SDK and disposable backend only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn,execFileSync} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PACKAGE);
const {expect}=require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'motion-connect-browser-'));
const evidence=process.env.CONNECT_EVIDENCE||temp;fs.mkdirSync(evidence,{recursive:true});
execFileSync('python',['-m','zipfile','-e',process.env.NATIVE_BUNDLE,temp]);
execFileSync(process.env.ESBUILD,['tests/native-browser-fixture.js','--bundle','--format=iife','--platform=browser','--log-level=error',
  '--alias:motion-studio-package='+path.join(temp,'motion-studio/desktop/plugin.js'),
  '--alias:@hermes/plugin-sdk='+path.resolve('tests/native-sdk-browser.js'),'--outfile='+path.join(temp,'fixture.js')]);
const bridge=spawn('python',['-m','tests.native_package_fixture'],{stdio:['pipe','pipe','pipe']});
let sequence=0,stderr='';const waiting=new Map();bridge.stderr.on('data',chunk=>{stderr+=chunk;});
const closed=new Promise(resolve=>bridge.once('exit',code=>{for(const item of waiting.values())item.reject(Error('Fixture exited'));resolve(code);}));
createInterface({input:bridge.stdout}).on('line',line=>{const value=JSON.parse(line),item=waiting.get(value.id);waiting.delete(value.id);
  value.error?item.reject(Error(value.error)):item.resolve(value.result);});
const rpc=message=>new Promise((resolve,reject)=>{const id=++sequence;waiting.set(id,{resolve,reject});bridge.stdin.write(JSON.stringify({id,...message})+'\n');});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const checks=[],errors=[];const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
try{
  await rpc({op:'admit-creation-fixture'});await rpc({op:'admit-production-fixture'});
  const context=await browser.newContext({serviceWorkers:'block',offline:true,viewport:{width:1280,height:900}});
  await context.exposeBinding('nativeRPC',(_source,message)=>rpc(message));
  const html='<html><body><div id="root"></div><script>'+fs.readFileSync(path.join(temp,'fixture.js'),'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
  await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:html}):route.abort());
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  const button=name=>page.getByRole('button',{name,exact:true});
  const banner=page.locator('[aria-label="Chat connection"]');
  const roots=()=>rpc({op:'connection-roots'});
  const more=async(label,name)=>{await page.getByText(label,{exact:true}).click();await page.locator('details.ms-more').getByRole('button',{name,exact:true}).click();};
  const hold=()=>page.evaluate(()=>{window.fixtureHoldOperation='admit';});
  const release=()=>page.evaluate(()=>{window.fixtureHoldOperation=null;window.fixtureReleaseOperation();});
  await page.goto('https://motion.invalid/');await expect(page.getByRole('status')).toContainText('Saved creations opened');
  await page.evaluate(()=>window.fixtureSession('connect-b'));
  const denied=await rpc({op:'tool',root:'connect-b',args:{operation:'prepare',direction:'Synthetic connect regression'}});
  check('new focused agent root is denied before explicit Connect',denied.error==='CREATION_WORKFLOW_REVIEW_REQUIRED');
  await expect(banner.getByRole('button',{name:'Connect this chat',exact:true})).toBeVisible();
  // Exercise the exact original Connections path while its old transport is invalid.
  await hold();await more('Connections','Connect this chat');
  await expect(banner).toContainText('Connecting…');
  await expect.poll(()=>page.evaluate(()=>Boolean(window.fixtureReleaseOperation))).toBe(true);
  check('pending UI has not yet written a new root',!(await roots()).creation.includes('connect-b'));
  await release();await expect(banner).toContainText('This chat is connected');
  check('Connections admitted exactly the currently focused root, preserving the old one',
    JSON.stringify((await roots()).creation)===JSON.stringify(['connect-b','session-a']));
  const prepared=await rpc({op:'tool',root:'connect-b',args:{operation:'prepare',direction:'Synthetic connect regression'}});
  check('agent Prepare succeeds after native Connect without generation',Boolean(prepared.request)&&!prepared.error);
  await expect(page.locator('details.ms-more').getByRole('button',{name:'Connect this chat',exact:true})).toBeVisible();
  await page.screenshot({path:path.join(evidence,'quick-create-connected.png'),fullPage:true});
  // Initial denied list must expose the CTA outside the closed Connections menu.
  await page.evaluate(()=>window.fixtureSession('connect-c'));await button('Open saved creations').click();
  await expect(page.getByRole('status')).toContainText('This chat needs review');
  await expect(banner.getByRole('button',{name:'Connect this chat',exact:true})).toBeVisible();
  await page.screenshot({path:path.join(evidence,'quick-create-review-required.png'),fullPage:true});
  await banner.getByRole('button',{name:'Connect this chat',exact:true}).click();await expect(banner).toContainText('This chat is connected');
  check('workflow-review denial is recoverable directly from the prominent CTA',(await roots()).creation.includes('connect-c'));
  await button('Production').click();
  await expect(banner.getByRole('button',{name:'Connect this chat',exact:true})).toBeVisible();
  // Production still requires the separately admitted Creation scope; no implicit grant.
  await page.evaluate(()=>window.fixtureSession('production-unreviewed'));
  await banner.getByRole('button',{name:'Connect this chat',exact:true}).click();
  await expect(banner).toContainText('Connect this chat in Quick Create first');
  check('Production cannot bypass the Creation association prerequisite',
    !(await roots()).creation.includes('production-unreviewed')&&!(await roots()).production.includes('production-unreviewed'));
  await rpc({op:'rpc',method:'creation.admit',payload:{session_id:'production-d'}});
  await page.evaluate(()=>window.fixtureSession('production-d'));await hold();await more('More','Connect this chat');
  await expect(banner).toContainText('Connecting…');await release();await expect(banner).toContainText('This chat is connected');
  check('Production Connect targets its current focus with separate authority',
    JSON.stringify((await roots()).production)===JSON.stringify(['production-d','session-a']));
  await page.screenshot({path:path.join(evidence,'production-connected.png'),fullPage:true});
  // The old admission acknowledgement cannot claim a new chat is connected.
  await rpc({op:'rpc',method:'creation.admit',payload:{session_id:'production-pending'}});
  await page.evaluate(()=>window.fixtureSession('production-pending'));await hold();
  await banner.getByRole('button',{name:'Connect this chat',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.fixtureRequests.some(r=>r.method.endsWith('.production.admit')&&r.payload.session_id==='production-pending'))).toBe(true);
  await page.evaluate(()=>window.fixtureSession('production-after'));await release();
  await expect(banner).not.toContainText('This chat is connected');
  await expect.poll(async()=>Boolean((await roots()).production.includes('production-pending'))).toBe(true);
  check('scope change rejects late acknowledgement and never admits the replacement chat',!(await roots()).production.includes('production-after'));
  await rpc({op:'revoke-production-fixture'});
  await banner.getByRole('button',{name:'Connect this chat',exact:true}).click();
  await expect(banner).toContainText('Cannot connect this chat');
  check('server access guard still denies admission and shows a plain error',!(await roots()).production.includes('production-after'));
  await page.screenshot({path:path.join(evidence,'production-connect-error.png'),fullPage:true});
  const counts=await rpc({op:'counts'});
  check('connection flows generated nothing',counts.creation_effects===0&&counts.music_effects===0&&counts.model_calls===0);
  check('no browser errors',errors.length===0);
  console.log(JSON.stringify({kind:'Packaged chat Connect, real disposable store; not installed Hermes Desktop',passed:checks.length,checks,page_errors:errors,evidence},null,2));
  await context.close();
}finally{
  await browser.close();bridge.stdin.end();const exit=await closed;
  fs.rmSync(temp,{recursive:true,force:true});assert.equal(exit,0);assert.equal(stderr,'');
}
