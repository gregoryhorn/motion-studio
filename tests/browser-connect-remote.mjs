// Two focused sessions through real React, host request adapter and packaged RPC/store.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn,execFileSync} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PACKAGE);
const {expect}=require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'motion-connect-remote-'));
const evidence=path.resolve('var/staging/connect-remote');fs.mkdirSync(evidence,{recursive:true});
execFileSync('python',['-m','zipfile','-e',process.env.NATIVE_BUNDLE,temp]);
if(process.env.CONNECT_DESKTOP_BUNDLE)
  fs.copyFileSync(process.env.CONNECT_DESKTOP_BUNDLE,path.join(temp,'motion-studio/desktop/plugin.js'));
execFileSync(process.env.ESBUILD,['tests/native-browser-fixture.js','--bundle','--format=iife','--platform=browser','--log-level=error',
  '--alias:motion-studio-package='+path.join(temp,'motion-studio/desktop/plugin.js'),
  '--alias:@hermes/plugin-sdk='+path.resolve('tests/remote-sdk-browser.js'),
  '--alias:hermes-host-client='+process.env.HERMES_SOURCE+'/apps/desktop/src/api/client.ts',
  '--outfile='+path.join(temp,'fixture.js')]);
const bridge=spawn('python',['-m','tests.native_package_fixture'],{stdio:['pipe','pipe','pipe']});
let seq=0,stderr='';const waiting=new Map();bridge.stderr.on('data',c=>{stderr+=c;});
const closed=new Promise(resolve=>bridge.once('exit',code=>{for(const e of waiting.values())e.reject(Error('FIXTURE_CLOSED'));resolve(code);}));
createInterface({input:bridge.stdout}).on('line',line=>{const row=JSON.parse(line),e=waiting.get(row.id);waiting.delete(row.id);
  row.error?e.reject(Error(row.error)):e.resolve(row.result);});
const rpc=message=>new Promise((resolve,reject)=>{const id=++seq;waiting.set(id,{resolve,reject});bridge.stdin.write(JSON.stringify({id,...message})+'\n');});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const errors=[],checks=[];
let page;
try{
  await rpc({op:'admit-creation-fixture'});
  await rpc({op:'admit-production-fixture'});
  const denied=await rpc({op:'tool',root:'session-b',session:'physical-b',args:{operation:'status'}});
  assert.equal(denied.error,'CREATION_WORKFLOW_REVIEW_REQUIRED');
  const baseline=await rpc({op:'counts'});
  const context=await browser.newContext({serviceWorkers:'block',offline:true});
  await context.exposeBinding('nativeRPC',(_source,message)=>rpc(message));
  const html='<html><body><div id="root"></div><script>'+fs.readFileSync(path.join(temp,'fixture.js'),'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
  await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:html}):route.abort());
  page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto('https://motion.invalid/');
  await page.getByRole('button',{name:'Open saved creations',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('Saved creations opened');
  await page.evaluate(()=>{
    window.fixtureGateway.rememberSessionProfile('session-b','fixture');
    window.fixtureSession('session-b');
  });
  await page.locator('summary').filter({hasText:'Connections'}).click();
  const connect=page.locator('details').filter({has:page.locator('summary').filter({hasText:'Connections'})}).getByRole('button',{name:'Connect this chat',exact:true});
  await expect(connect).toBeEnabled();
  await connect.click();
  await expect.poll(async()=> (await rpc({op:'connection-roots'})).creation,{timeout:3000}).toEqual(['session-a','session-b']);
  checks.push('Connections button admits second focused root through remote-primary');
  await expect(page.getByText('This chat is connected',{exact:true}).first()).toBeVisible();
  await expect(connect).toHaveText('Connect this chat');
  const requests=await page.evaluate(()=>window.fixtureRequests.filter(row=>row.method.endsWith('creation.admit')));
  assert.deepEqual(requests.map(row=>row.payload.session_id),['session-b']);
  assert.equal(requests[0].payload.profile,'fixture');
  checks.push('actual host adapter sends second session and matching profile');
  const observed=await rpc({op:'tool',root:'session-b',session:'physical-b',args:{operation:'status'}});
  assert.notEqual(observed.error,'CREATION_WORKFLOW_REVIEW_REQUIRED');
  checks.push('agent no longer denied for second root');
  assert.deepEqual(await rpc({op:'counts'}),baseline);
  checks.push('admission creates no requests, runs, media or producer effects');
  await page.screenshot({path:path.join(evidence,'connected.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  await page.evaluate(()=>window.fixtureUnload());await context.close();
}catch(error){
  if(page){
    await page.screenshot({path:path.join(evidence,'failed.png'),fullPage:true});
    console.error(JSON.stringify({roots:await rpc({op:'connection-roots'}),admissions:await page.evaluate(()=>window.fixtureRequests.filter(row=>row.method.endsWith('creation.admit')))}));
  }
  throw error;
}finally{
  await browser.close();bridge.stdin.end();const code=await closed;
  fs.writeFileSync(path.join(evidence,'stderr.txt'),stderr);fs.rmSync(temp,{recursive:true,force:true});assert.equal(code,0);
}
console.log(JSON.stringify({checks,errors,boundary:'offline remote-primary browser, actual host request adapter and packaged Python; no Windows/live state'}));
