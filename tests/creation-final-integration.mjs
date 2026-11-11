import os from 'node:os';
// Scoped offline regressions: real controllers and React DOM, fake host only. No producers.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
const require=createRequire(import.meta.url);
const source=name=>fs.readFileSync('studio/native/frontend/'+name+'.js','utf8');
const moduleURL=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const transport=moduleURL(source('transport')),retained=moduleURL(source('retained-bytes'));
const {CreationController}=await import(moduleURL(source('creation-controller').replace("'./transport.js'",JSON.stringify(transport)).replace("'./retained-bytes.js'",JSON.stringify(retained))));
const {TechnicalController}=await import(moduleURL(source('controller').replace("'./transport.js'",JSON.stringify(transport))));
const {workspaceStatus}=await import(moduleURL(source('workspace-copy')));
const {readRetained}=await import(retained);
const checks=[];
async function check(name,run){await run();checks.push(name);}
function setup(){
  const f=fixture();f.route.primary=true;const calls=[];let handler=async()=>({creations:[]});
  f.host.request=async(method,payload)=>{calls.push({method,payload});return handler(method.split('.').at(-1),payload);};
  const drafts=[];f.host.composer={getDraft:async()=>'',insertText:async(...args)=>{drafts.push(args);return true;}};
  return {...f,calls,drafts,handle:value=>handler=value,controller:new CreationController(f.host)};
}
const inventory={kinds:{Image:{default:'image',options:[{id:'image',label:'Image route',available:true,cost:'unknown',engine:'cloud'},
  {id:'import',label:'Import existing file',available:true,cost:'free',engine:'import',action:'import'}]}}};
await check('failed inventory is not cached; explicit reload succeeds, single-flight and stale replies rejected',async()=>{
  const f=setup();await f.controller.open();f.handle(()=>({error:'INVALID_METHODS_INPUT'}));
  await f.controller.loadMethods(f.controller.client);assert.equal(f.controller.state.methods,null);assert.equal(f.controller.state.methodsError,'INVALID_METHODS_INPUT');
  const gate=deferred();f.handle(()=>gate.promise);const work=f.controller.loadMethods(f.controller.client);
  await f.controller.loadMethods(f.controller.client);assert.equal(f.calls.filter(c=>c.method.endsWith('.methods')).length,2);
  gate.resolve(inventory);await work;assert.deepEqual(f.controller.state.methods,inventory);
  f.set('profile','other');assert.equal(f.controller.state.methods,null);f.set('profile','p1');await f.controller.open();
  const pending=deferred();f.handle(()=>pending.promise);const stale=f.controller.loadMethods(f.controller.client);
  f.set('gateway','closed');pending.resolve(inventory);await stale;assert.equal(f.controller.state.methods,null);f.controller.dispose();
});
await check('import and unavailable explicit methods never create a chat draft',async()=>{
  const f=setup();await f.controller.open();
  for(const method of [{id:'import',available:true},{id:'gone',available:false}])await f.controller.request('Synthetic direction','Image',false,method);
  assert.equal(f.drafts.length,0);f.controller.dispose();
});
await check('method access denial clears private state and blocks follow-up until explicit reopen',async()=>{
  const f=setup();await f.controller.open();f.controller.emit({rows:[{request:'private-r'}],selected:'private-r'});
  f.handle(()=>({error:'CREATION_SCOPE_DENIED'}));await f.controller.loadMethods(f.controller.client);
  const count=f.calls.length;await f.controller.loadMethods(f.controller.client);await f.controller.refresh();
  assert.equal(f.calls.length,count);assert.deepEqual(f.controller.state.rows,[]);assert.equal(f.controller.state.draftsInvalidated,true);f.controller.dispose();
});
await check('safe errors distinguish retrieval failure, verified corruption, scope and unknown outcome',async()=>{
  const f=setup();await f.controller.open();f.controller.emit({rows:[{request:'r',takes:[],kind:'Image'}],selected:'r'});
  f.handle(()=>{throw Error('/private/secret-provider-response');});await f.controller.load('t');
  assert.match(f.controller.state.status,/retrieved/);assert.doesNotMatch(f.controller.state.status,/secret|INTEGRITY/);
  f.controller.failure(Error('CREATION_CHUNK_INVALID'));assert.equal(f.controller.state.status,'CREATION_CHUNK_INVALID');
  f.controller.failure({code:'/private/secret'});assert.match(f.controller.state.status,/may have reached/);
  assert.doesNotMatch(workspaceStatus('UNKNOWN_SERVER_CODE'),/Nothing was changed|try again/);
  assert.match(workspaceStatus('RETAINED_FILE_MISSING'),/rather than regenerating/);
  f.controller.dispose();
});
const bytes=Buffer.from([0xff,0xd8,0xff,0xd9]),hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const descriptor={mime:'image/jpeg',format:'jpeg',byteLength:bytes.length,width:32,height:24,qualityRole:'Not recorded',
  qa:{technical:'Validated retained format',perceptual:'Not reviewed',useEligibility:'Not assessed',userApproval:'Not recorded',outstanding:['Perceptual review against request','Intended-use eligibility and rights','Explicit user approval']}};
const chunk={take:'t',offset:0,total:bytes.length,bytes:bytes.toString('base64'),sha256:hash(bytes),chunk_sha256:hash(bytes),mime:'image/jpeg',descriptor};
await check('byte reader preserves JPEG descriptor and emits coded scope/integrity errors',async()=>{
  const result=await readRetained({request:async()=>chunk},'chunk',()=>({take:'t'}),()=>true);
  assert.equal(result.mime,'image/jpeg');assert.deepEqual(result.descriptor,descriptor);
  await assert.rejects(readRetained({request:async()=>chunk},'chunk',()=>({take:'t'}),()=>false),{code:'RETAINED_SCOPE_CHANGED'});
  await assert.rejects(readRetained({request:async()=>({...chunk,bytes:'!!!'})},'chunk',()=>({take:'t'}),()=>true),{code:'CREATION_INTEGRITY_FAILED'});
  const f=setup();await f.controller.open();f.controller.emit({rows:[{request:'r',kind:'Image',takes:[{id:'t',descriptor}]}],selected:'r'});
  f.handle(()=>chunk);await f.controller.load('t');assert.equal((await fetch(f.controller.state.url)).headers.get('content-type'),'image/jpeg');f.controller.dispose();
});
await check('technical refusal clears only the matching Prepare pointer and copy retains proof boundary',async()=>{
  for(const code of ['SYNTHESIS_STALE','TECHNICAL_STORE_BUSY'])for(const proof of [false,true])for(const newer of [false,true]){
    const data=new Map(),storage={get:(key,fallback)=>data.get(key)??fallback,set:(key,value)=>data.set(key,value),remove:key=>data.delete(key)};
    const c=new TechnicalController({},storage);c.client={scope:'scope',current:()=>true,request:async()=>{
      if(newer)storage.set(c.key(),{command:'newer'});throw {code,preAdmissionRejected:proof};}};
    c.emit({connected:true,inference:true,selected:{id:'e',revision:1,template:{}}});await c.prepare();
    assert.match(c.state.status,code==='SYNTHESIS_STALE'?/selected evidence or template/:/Another service owns/);
    assert.equal(c.state.status.includes('This Prepare was not admitted.'),proof);
    assert.equal(storage.get(c.key(),null)?.command??null,newer?'newer':proof?null:c.state.command);
  }
});

// Existing dependencies only. Bundle virtual fixture in memory; no writes outside this test.
const packageRoot=path.dirname(process.env.PLAYWRIGHT_PACKAGE||path.dirname(require.resolve('playwright/package.json')));
const {build}=require(path.join(packageRoot,'esbuild'));
const {chromium}=require(path.join(packageRoot,'playwright'));
const {expect}=require(path.join(packageRoot,'playwright/test.js'));
const browserSource=`
import {createElement as h,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {CreationController} from './studio/native/frontend/creation-controller.js';
import {CreationPage} from './studio/native/frontend/creation-page.js';
const values={focusedSessionId:'s1',focusedSessionOwner:{connectionId:'c1',profile:'p1'},connectionId:'c1',profile:'p1',gateway:'open'};
const listeners=Object.fromEntries(Object.keys(values).map(key=>[key,new Set()]));
window.change=(key,value)=>{values[key]=value;for(const fn of listeners[key])fn(value);};
const state=Object.fromEntries(Object.keys(values).map(key=>[key,{get:()=>values[key],subscribe:fn=>{listeners[key].add(fn);fn(values[key]);return()=>listeners[key].delete(fn);}}]));
const descriptor=${JSON.stringify(descriptor)},chunk=${JSON.stringify(chunk)},inventory=${JSON.stringify(inventory)};
window.inventory=inventory;window.failMethods=true;window.calls=[];
const rows=[{request:'image-r',kind:'Image',direction:'Synthetic image',state:'Ready for review',takes:[{id:'t',descriptor,review:'Not reviewed'}]},
 {request:'voice-r',kind:'Voice',direction:'Synthetic voice',state:'Ready for review',takes:[{id:'v',review:'Not reviewed',descriptor:{...descriptor,mime:'audio/wav',format:'wav',qualityRole:'Retained derivative; source retained'},facts:{voice_lineage:{native:{format:'mp3'}}}}]}];
const host={state,profileRoutes:async()=>[{primary:true,mode:'local',connectionId:'c1',profile:'p1',targetProfile:'p1'}],
 request:async(method,payload)=>{window.calls.push(method);const op=method.split('.').at(-1);
  if(op==='list')return {creations:rows};if(op==='methods')return window.failMethods?{error:'INVALID_METHODS_INPUT'}:window.inventory;
  if(op==='chunk')return {...chunk,take:payload.take};throw Error('Unexpected action');},
 composer:{getDraft:async()=>'',insertText:async()=>{throw Error('Unexpected composer mutation');}}};
const createController=notify=>{const c=new CreationController(host,notify);window.controller=c;return c;};
function App(){const [open,setOpen]=useState(true);window.show=setOpen;return open?h(CreationPage,{createController,onProduction:()=>setOpen(false)}):h('button',{onClick:()=>setOpen(true)},'Return to Quick Create');}
createRoot(document.querySelector('#root')).render(h(App));`;
const nodePaths=[packageRoot,...(process.env.NODE_PATH||path.join(process.env.HERMES_SOURCE||path.join(os.homedir(),'.hermes/hermes-agent-official'),'apps/desktop/node_modules')).split(path.delimiter)];
const bundle=await build({stdin:{contents:browserSource,resolveDir:process.cwd(),sourcefile:'creation-final-fixture.js'},bundle:true,write:false,format:'iife',platform:'browser',nodePaths,plugins:[{
  name:'sdk-fixture',setup(build){build.onResolve({filter:/^@hermes\/plugin-sdk$/},()=>({path:'sdk',namespace:'fixture'}));
    build.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:"import {createElement as h} from 'react';export const Button=props=>h('button',props),Textarea=props=>h('textarea',props),Input=props=>h('input',props);",resolveDir:packageRoot}));}
}]});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||undefined,args:['--no-sandbox']});
try{
  const context=await browser.newContext({serviceWorkers:'block',offline:true});
  const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await context.route('**/*',route=>route.request().url()==='https://motion.invalid/'?route.fulfill({contentType:'text/html',body:'<div id="root"></div><script>'+bundle.outputFiles[0].text.replaceAll('</script','<\\/script')+'</script>'}):route.abort());
  await page.goto('https://motion.invalid/');
  const button=name=>page.getByRole('button',{name,exact:true}),request=page.getByRole('textbox',{name:'Describe what you want to make'});
  await check('UI inventory failure exposes deliberate working retry with no poll loop',async()=>{
    await expect(button('Retry method loading')).toBeVisible();
    assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.endsWith('.methods')).length),1);
    await page.evaluate(()=>{window.failMethods=false;});await button('Retry method loading').click();
    await expect(button('Retry method loading')).toHaveCount(0);
  });
  await check('media radio keyboard preserves text, wraps and moves focus',async()=>{
    await request.fill('Synthetic unsent direction');const radio=page.getByRole('radio',{name:'Sound effects',exact:true});await radio.focus();await radio.press('ArrowLeft');
    await expect(page.getByRole('radio',{name:'Video',exact:true})).toBeFocused();await expect(page.getByRole('radio',{name:'Video',exact:true})).toHaveAttribute('aria-checked','true');
    await expect(request).toHaveValue('Synthetic unsent direction');await page.getByRole('radio',{name:'Image',exact:true}).click();
  });
  await check('import is explicit, unavailable choice persists and blocks Create without fallback',async()=>{
    const picker=page.getByLabel('Method',{exact:true});await picker.selectOption('import');await expect(button('Create in chat')).toBeDisabled();
    await expect(page.getByText('Import existing file',{exact:true}).first()).toBeAttached();
    await picker.selectOption('image');await page.evaluate(()=>{window.inventory.kinds.Image.options[0].available=false;window.inventory.kinds.Image.options[0].reason='Route unavailable';window.controller.emit({methods:structuredClone(window.inventory)});});
    await expect(picker).toHaveValue('image');await expect(button('Create in chat')).toBeDisabled();await expect(page.getByText('Route unavailable',{exact:true})).toBeVisible();
  });
  await check('JPEG MIME/dimensions/QA and visual review names are real; save extension matches bytes',async()=>{
    await expect(page.getByText(/image\/jpeg · 4 bytes · 32 × 24/)).toBeVisible();
    await expect(page.getByText(/Technical: Validated retained format\. Perceptual: Not reviewed/)).toBeVisible();
    await expect(page.getByRole('button',{name:'Reviewed: matches request',exact:true})).toBeVisible();
    await expect(page.getByText('Checking output',{exact:true}).first()).toBeVisible();
    await button('Load original image').click();const link=page.getByRole('link',{name:'Save / download original JPEG'});await expect(link).toHaveAttribute('download','motion-studio-original.jpeg');
    assert.equal(await page.evaluate(async()=>{const blob=await (await fetch(document.querySelector('a[download]').href)).blob();return blob.type;}),'image/jpeg');
  });
  await check('per-request refinement and composer survive workspace remount; Voice derivative is labeled',async()=>{
    const refine=page.getByRole('textbox',{name:'Change for another take'});await refine.fill('Image variation');
    await page.getByRole('button',{name:/Synthetic voice/}).click();await refine.fill('Voice variation');
    await expect(page.getByText(/Voice conversion: source MP3 retained/)).toBeVisible();await expect(button('Load retained derivative audio')).toBeVisible();
    await page.getByRole('button',{name:/Synthetic image/}).click();await expect(refine).toHaveValue('Image variation');
    await button('Open Production →').click();await button('Return to Quick Create').click();await expect(request).toHaveValue('Synthetic unsent direction');await expect(refine).toHaveValue('Image variation');
  });
  await check('Help Escape and Close restore the exact invoker and match visible labels',async()=>{
    const help=button('Help');await help.click();await expect(page.getByRole('heading',{name:'Quick Create guide'})).toBeFocused();
    await page.getByRole('heading',{name:'Quick Create guide'}).press('Escape');await expect(help).toBeFocused();
    await help.click();await page.getByRole('region',{name:'Quick Create help'}).getByRole('button',{name:'Close help',exact:true}).click();await expect(help).toBeFocused();
  });
  await check('authority away-and-back while unmounted clears private composer/refinement',async()=>{
    await button('Open Production →').click();await page.evaluate(()=>{window.change('gateway','closed');window.change('gateway','open');});
    await button('Return to Quick Create').click();await expect(request).toHaveValue('');await expect(page.getByRole('textbox',{name:'Change for another take'})).toHaveValue('');
  });
  assert.deepEqual(errors,[]);await context.close();
}finally{await browser.close();}
console.log(JSON.stringify({kind:'Offline real controllers/React/isolated Chromium; synthetic host, no producers',passed:checks.length,checks},null,2));
