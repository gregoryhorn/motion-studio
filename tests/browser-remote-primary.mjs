// Packaged React + actual pinned host injection + Python RPC/store, offline only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn,execFileSync} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_PACKAGE);
const {expect}=require(path.join(process.env.PLAYWRIGHT_PACKAGE,'test.js'));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'motion-remote-browser-'));
const evidence='docs/evidence/native-remote-primary-r1';fs.mkdirSync(evidence,{recursive:true});
execFileSync('python',['-m','zipfile','-e',process.env.NATIVE_BUNDLE,temp]);
for(const name of ['studio/native/creation/registration.py','desktop/source/transport.js','desktop/plugin.js'])
  fs.copyFileSync(path.join(process.env.SFX_REPAIR_DELTA,'after',name),path.join(temp,'motion-studio',name));
execFileSync(process.env.ESBUILD,['tests/native-browser-fixture.js','--bundle','--format=iife','--platform=browser','--log-level=error',
  '--alias:motion-studio-package='+path.join(temp,'motion-studio/desktop/plugin.js'),
  '--alias:@hermes/plugin-sdk='+path.resolve('tests/remote-sdk-browser.js'),
  '--alias:hermes-host-client='+path.join(process.env.HERMES_SOURCE||path.join(os.homedir(),'.hermes/hermes-agent-official'),'apps/desktop/src/api/client.ts'),
  '--outfile='+path.join(temp,'fixture.js')]);
const bridge=spawn('python',['-m','tests.native_package_fixture'],{stdio:['pipe','pipe','pipe']});
let seq=0,stderr='';const waiting=new Map();bridge.stderr.on('data',c=>{stderr+=c;});
const closed=new Promise(resolve=>bridge.once('exit',code=>{for(const e of waiting.values())e.reject(Error('FIXTURE_CLOSED'));resolve(code);}));
createInterface({input:bridge.stdout}).on('line',line=>{const row=JSON.parse(line),e=waiting.get(row.id);waiting.delete(row.id);
  row.error?e.reject(Error('FIXTURE_OPERATION_FAILED')):e.resolve(row.result);});
const rpc=message=>new Promise((resolve,reject)=>{const id=++seq;waiting.set(id,{resolve,reject});bridge.stdin.write(JSON.stringify({id,...message})+'\n');});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
const checks=[],errors=[],check=(name,value)=>{assert.ok(value,name);checks.push(name);};
try{
  // Controlled fixture setup only. All later page work is retained observation.
  await rpc({op:'admit-creation-fixture'});
  const source=await rpc({op:'tool',args:{operation:'prepare',direction:'Synthetic retained remote UI fixture',seconds:0.1}});
  assert.ok(!source.error);
  await rpc({op:'tool',args:{operation:'start',...Object.fromEntries(['request','revision','command','run'].map(k=>[k,source[k]]))}});
  await rpc({op:'settle-creation'});
  const saved=await rpc({op:'tool',args:{operation:'status'}});
  check('controlled retained SFX ready before review',Boolean(saved.candidate));
  const baseline=await rpc({op:'counts'});
  for(const mode of ['remote','local']){
    const context=await browser.newContext({serviceWorkers:'block',offline:true});
    await context.exposeBinding('nativeRPC',(_s,message)=>rpc(message));
    await context.addInitScript(value=>{window.fixtureRouteMode=value;},mode);
    const html='<html><body><div id="root"></div><script>'+fs.readFileSync(path.join(temp,'fixture.js'),'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
    await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:html}):route.abort());
    const page=await context.newPage();page.on('pageerror',()=>errors.push('PAGE_ERROR'));
    const button=name=>page.getByRole('button',{name,exact:true});
    await page.goto('https://motion.invalid/');await button('Open saved creations').click();
    await expect(page.getByRole('status')).toContainText('Saved creations opened');
    check(mode+' Creation actual profile envelope accepted',await page.evaluate(()=>window.fixtureRequests.some(r=>r.method.endsWith('creation.list')&&r.payload.profile==='fixture')));
    await button('Load original audio').click();await expect(page.getByRole('status')).toContainText('Original bytes verified');
    check(mode+' retained bytes loaded',await page.locator('audio').getAttribute('src'));
    await page.evaluate(()=>{window.fixtureSetScope('gateway','closed');window.fixtureSetScope('gateway','open');});
    await expect(page.getByRole('status')).toContainText('Reopen');
    check(mode+' disconnect clears retained Blob',await page.locator('audio').evaluateAll(nodes=>nodes.every(node=>!node.getAttribute('src'))));
    await button('Open saved creations').click();await expect(page.getByRole('status')).toContainText('Saved creations opened');
    check(mode+' no Production or Music controls added',await page.getByRole('button',{name:'Production',exact:true}).count()===0);
    await page.screenshot({path:path.join(evidence,mode+'-creation-open.png'),fullPage:true});
    check(mode+' no forbidden generation RPC',await page.evaluate(()=>!window.fixtureRequests.some(r=>/\.(prepare|start|admit_music|create)$/.test(r.method))));
    await page.evaluate(()=>window.fixtureUnload());await context.close();
  }
  check('native review made no source/generator/mutation effects',JSON.stringify(await rpc({op:'counts'}))===JSON.stringify(baseline));
  check('zero browser page errors',errors.length===0);
}finally{
  await browser.close();bridge.stdin.end();const code=await closed;
  fs.writeFileSync(path.join(evidence,'packaged-browser-stderr.txt'),stderr);
  fs.rmSync(temp,{recursive:true,force:true});assert.equal(code,0);
}
console.log(JSON.stringify({checks,errors,boundary:'packaged offline React/actual host adapter/fake socket; not Windows native qualification'}));
