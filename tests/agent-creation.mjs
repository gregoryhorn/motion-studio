import os from 'node:os';
// Deterministic AFC async/latching/integrity cases; reuses the existing SDK fixture.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
const url=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const transport=url(fs.readFileSync('studio/native/frontend/transport.js','utf8'));
const retained=url(fs.readFileSync('studio/native/frontend/retained-bytes.js','utf8'));
const {readRetained}=await import(retained);
const {CreationController}=await import(url(fs.readFileSync('studio/native/frontend/creation-controller.js','utf8')
  .replace("'./transport.js'",JSON.stringify(transport)).replace("'./retained-bytes.js'",JSON.stringify(retained))));
const row={request:'a'.repeat(32),revision:1,command:'b'.repeat(32),run:'c'.repeat(32),direction:'Synthetic direction',state:'Prepared',takes:[]};
const checks=[];
async function test(name,run){await run();checks.push(name);}
function setup(clock=globalThis){
  const f=fixture();f.route.primary=true;f.route.mode=process.env.TEST_ROUTE_MODE||'local';const requests=[];
  let handler=async()=>({creations:[row]});
  f.host.request=async(method,payload)=>{const operation=method.split('.').at(-1);requests.push({operation,payload});return handler(operation,payload);};
  const composerCalls=[];f.host.composer={getDraft:async()=>'',insertText:async(...args)=>{composerCalls.push(args);return true;},submit:()=>{throw Error('No send');}};
  return {...f,requests,composerCalls,handle:value=>{handler=value;},controller:new CreationController(f.host,()=>{},clock)};
}
function fakeClock(){
  let sequence=0;const timers=new Map();
  return {timers,setTimeout:(fn,delay)=>{const id=++sequence;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),
    delay:()=>[...timers.values()][0]?.delay??null,fire:()=>{const next=timers.entries().next().value;if(!next)return false;timers.delete(next[0]);next[1].fn();return true;}};
}
await test('dispose while opening routes prevents RPC',async()=>{
  const f=setup(),gate=deferred();f.host.profileRoutes=()=>gate.promise;
  const work=f.controller.open();f.controller.dispose();gate.resolve([f.route]);await work;
  assert.equal(f.requests.length,0);assert.equal(f.subscriptions(),0);
});
await test('dispose after list reply prevents publication',async()=>{
  const f=setup(),gate=deferred();f.handle(()=>gate.promise);
  const work=f.controller.open();await flush();f.controller.dispose();gate.resolve({creations:[row]});await work;
  assert.equal(f.controller.state.rows.length,0);
});
await test('automatic observation is bounded, single-flight and preserves a valid selection',async()=>{
  const clock=fakeClock(),f=setup(clock),settled={...row,state:'Ready for review'},other={...settled,request:'e'.repeat(32),direction:'Other synthetic direction'};
  f.handle(()=>({creations:[settled,other]}));await f.controller.observe();assert.equal(clock.delay(),1000);
  f.controller.choose(other.request);f.handle(()=>({creations:[settled,other]}));clock.fire();await flush();
  assert.equal(f.controller.state.selected,other.request);assert.equal(clock.delay(),2000);
  const gate=deferred();f.handle(()=>gate.promise);clock.fire();await flush();const count=f.requests.length;
  assert.equal(clock.fire(),false);gate.resolve({creations:[settled,other]});await flush();
  assert.equal(f.requests.length,count);assert.equal(clock.delay(),4000);
  f.handle(()=>({creations:[settled]}));clock.fire();await flush();assert.equal(f.controller.state.selected,settled.request);
  assert.equal(clock.delay(),1000);f.handle(()=>({creations:[settled]}));clock.fire();await flush();assert.equal(clock.delay(),2000);
  clock.fire();await flush();assert.equal(clock.delay(),4000);clock.fire();await flush();assert.equal(clock.delay(),8000);
  clock.fire();await flush();assert.equal(clock.delay(),8000);f.controller.dispose();
});
await test('polling stops permanently on error, scope transition and disposal',async()=>{
  for(const mode of ['error','scope','dispose']){
    const clock=fakeClock(),f=setup(clock);await f.controller.observe();assert.equal(clock.timers.size,1);
    if(mode==='error'){f.handle(()=>({error:'CREATION_ACCESS_UNAVAILABLE'}));clock.fire();await flush();}
    if(mode==='scope'){f.set('focusedSessionId','foreign');f.set('focusedSessionId','s1');}
    if(mode==='dispose')f.controller.dispose();
    assert.equal(clock.timers.size,0);assert.equal(clock.fire(),false);assert.equal(f.subscriptions(),mode==='dispose'?0:6);
    f.controller.dispose();
  }
});
for(const [key,away,back] of [['focusedSessionId','foreign','s1'],['profile','foreign','p1'],['gateway','closed','open']]){
  await test(key+' away-and-back latches before next action',async()=>{
    const f=setup();await f.controller.open();f.set(key,away);f.set(key,back);
    await f.controller.action('stop');await f.controller.refresh();
    assert.equal(f.requests.length,1);assert.equal(f.controller.state.rows.length,0);f.controller.dispose();
  });
}
await test('scope change during saved read rejects result',async()=>{
  const f=setup(),gate=deferred();f.handle(()=>gate.promise);const work=f.controller.open();await flush();
  f.set('focusedSessionId','foreign');gate.resolve({creations:[row]});await work;
  assert.equal(f.controller.state.rows.length,0);f.controller.dispose();
});
await test('lost stop acknowledgement only observes, never retries effect',async()=>{
  const f=setup();await f.controller.open();f.handle(op=>{if(op==='stop')throw Error('Lost reply');return {creations:[row]};});
  await f.controller.action('stop');assert.match(f.controller.state.status,/unobserved/);await f.controller.refresh();
  assert.equal(f.requests.filter(r=>r.operation==='stop').length,1);f.controller.dispose();
});
await test('proven denial is retained without fallback or dispatch',async()=>{
  const f=setup();f.handle(()=>({error:'CREATION_ACCESS_UNAVAILABLE'}));await f.controller.open();
  assert.equal(f.controller.state.status,'CREATION_ACCESS_UNAVAILABLE');assert.equal(f.requests.length,1);f.controller.dispose();
});
await test('disposed or changed composer read cannot mutate draft',async()=>{
  for(const dispose of [true,false]){
    const f=setup();await f.controller.open();const gate=deferred();f.host.composer.getDraft=()=>gate.promise;
    const work=f.controller.refine('Synthetic change');await flush();
    if(dispose)f.controller.dispose();else f.set('focusedSessionId','foreign');
    gate.resolve('');await work;assert.equal(f.composerCalls.length,0);f.controller.dispose();
  }
});
await test('existing draft requires explicit append and exact chat; never send',async()=>{
  const f=setup();await f.controller.open();f.host.composer.getDraft=async()=>'Existing private draft';
  await f.controller.refine('Synthetic change');assert.equal(f.composerCalls.length,0);
  await f.controller.refine('Synthetic change',true);assert.equal(f.composerCalls[0][0],'s1');f.controller.dispose();
});
const bytes=Buffer.from('Synthetic retained bytes'),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
await test('Connect reopens the focused chat after workflow denial and shows a confirmed result',async()=>{
  const f=setup();f.handle(()=>({error:'CREATION_WORKFLOW_REVIEW_REQUIRED'}));await f.controller.open();
  assert.equal(f.controller.state.needsConnection,true);
  f.set('focusedSessionId','new-chat');const gate=deferred();
  f.handle(op=>op==='admit'?gate.promise:{creations:[]});
  const work=f.controller.admit();await flush();assert.equal(f.controller.state.connectionStatus,'Connecting…');
  assert.deepEqual(f.requests.filter(r=>r.operation==='admit').map(r=>r.payload.session_id),['new-chat']);
  gate.resolve({});await work;assert.equal(f.controller.state.connectionStatus,'This chat is connected');
  assert.equal(f.controller.state.needsConnection,false);f.controller.dispose();
});
await test('Connect never dispatches after focus changes during route lookup or disposal',async()=>{
  for(const transition of ['focus','dispose','away-back']){
    const f=setup();await f.controller.open();const gate=deferred();f.host.profileRoutes=()=>gate.promise;
    const work=f.controller.admit();await flush();
    if(transition==='dispose')f.controller.dispose();else{f.set('focusedSessionId','away');if(transition==='away-back')f.set('focusedSessionId','s1');}
    gate.resolve([f.route]);await work;assert.equal(f.requests.filter(r=>r.operation==='admit').length,0);f.controller.dispose();
  }
});
await test('Connect failures are plain, repeated clicks single-flight, and stale acknowledgements are rejected',async()=>{
  const f=setup();await f.controller.open();const gate=deferred();f.handle(()=>gate.promise);
  const work=f.controller.admit();await flush();await f.controller.admit();
  assert.equal(f.requests.filter(r=>r.operation==='admit').length,1);
  f.set('focusedSessionId','away');gate.resolve({});await work;
  assert.notEqual(f.controller.state.connectionStatus,'This chat is connected');
  f.handle(()=>({error:'CREATION_ACCESS_UNAVAILABLE'}));await f.controller.admit();
  assert.match(f.controller.state.connectionStatus,/Cannot connect/);f.controller.dispose();
});
await test('new-request draft never uses the old session fallback',async()=>{
  const f=setup();await f.controller.open();f.set('focusedSessionId','new-chat');
  await f.controller.request('Synthetic request');assert.equal(f.composerCalls.length,0);f.controller.dispose();
});
await test('Connect refuses missing focus or mismatched owner and never retries a lost acknowledgement',async()=>{
  for(const mode of ['no-focus','owner','lost-ack']){
    const f=setup();await f.controller.open();
    if(mode==='no-focus')f.set('focusedSessionId',null);
    if(mode==='owner')f.set('focusedSessionOwner',{connectionId:'foreign',profile:'p1'});
    if(mode==='lost-ack')f.handle(()=>{throw Error('Lost acknowledgement');});
    await f.controller.admit();await f.controller.refresh();
    assert.equal(f.requests.filter(r=>r.operation==='admit').length,mode==='lost-ack'?1:0);
    assert.match(f.controller.state.connectionStatus,/Cannot connect/);f.controller.dispose();
  }
});
const chunk={take:'d'.repeat(32),offset:0,total:bytes.length,bytes:bytes.toString('base64'),sha256:hash(bytes),chunk_sha256:hash(bytes)};
await test('valid original bytes yield revocable Blob, not autoplay/review',async()=>{
  const f=setup();await f.controller.open();f.handle(()=>chunk);await f.controller.load(chunk.take);
  assert.match(f.controller.state.url,/^blob:/);assert.equal(f.requests.filter(r=>r.operation==='review').length,0);
  f.controller.choose(row.request);assert.equal(f.controller.state.url,null);f.controller.dispose();
});
await test('shared loader rejects wrong take even with valid bytes and digests',async()=>{
  const wrong={...chunk,take:'f'.repeat(32)};let requests=0;
  await assert.rejects(()=>readRetained({request:async()=>{requests++;return wrong;}},'chunk',
    ()=>({request:row.request,take:chunk.take}),()=>true),/CREATION_INTEGRITY_FAILED/);
  assert.equal(requests,1);
});
for(const mutation of [{take:'f'.repeat(32)},{offset:1},{chunk_sha256:'0'.repeat(64)},{sha256:'0'.repeat(64)},{total:16777217},{bytes:''}]){
  await test('reject corrupt chunk '+Object.keys(mutation)[0]+JSON.stringify(mutation).slice(0,10),async()=>{
    const f=setup();await f.controller.open();f.handle(()=>({...chunk,...mutation}));await f.controller.load(chunk.take);
    assert.equal(f.controller.state.url,null);assert.equal(f.controller.state.status,'CREATION_INTEGRITY_FAILED');f.controller.dispose();
  });
}
await test('disposed chunk continuation cannot publish private Blob',async()=>{
  const f=setup();await f.controller.open();const gate=deferred();f.handle(()=>gate.promise);
  const work=f.controller.load(chunk.take);await flush();f.controller.dispose();gate.resolve(chunk);await work;
  assert.equal(f.controller.state.url,null);
});
for(const code of ['MUSIC_SCOPE_REVIEW_REQUIRED','MUSIC_WORKFLOW_REVIEW_REQUIRED','MUSIC_POLICY_CHANGED','MUSIC_BINDING_DENIED']){
  await test(code+' clears private Music rows and player on server denial without host transition',async()=>{
    const f=setup();f.handle(()=>({creations:[{...row,kind:'Music'}]}));await f.controller.open();
    f.handle(()=>chunk);await f.controller.load(chunk.take);assert.match(f.controller.state.url,/^blob:/);
    f.handle(()=>({error:code}));await f.controller.refresh();
    assert.equal(f.controller.state.rows.length,0);assert.equal(f.controller.state.url,null);assert.equal(f.controller.state.selected,null);
    f.controller.dispose();
  });
}
for(const interruption of ['scope','denial']){
  await test('explicit saved-creations reopen recovers after '+interruption+' without replay',async()=>{
    const f=setup();await f.controller.open();
    if(interruption==='scope'){f.set('focusedSessionId','away');f.set('focusedSessionId','s1');}
    else {f.handle(()=>({error:'CREATION_SCOPE_DENIED'}));await f.controller.refresh();}
    assert.equal(f.controller.state.draftsInvalidated,true);
    assert.deepEqual(f.controller.state.rows,[]);
    const before=f.requests.length;
    f.handle(()=>({creations:[row]}));await f.controller.open();
    assert.equal(f.controller.state.draftsInvalidated,false);
    assert.equal(f.controller.state.busy,false);
    assert.deepEqual(f.controller.state.rows,[row]);
    assert.equal(f.controller.state.selected,row.request);
    assert.deepEqual(f.requests.slice(before).map(r=>r.operation),['list']);
    assert.equal(f.composerCalls.length,0);f.controller.dispose();
  });
}
await test('unavailable methods cannot blank saved creations or prevent explicit reopen',async()=>{
  const f=setup();await f.controller.open();
  f.handle(op=>op==='methods'?{error:'METHODS_UNAVAILABLE'}:{creations:[row]});
  await f.controller.loadMethods(f.controller.client);
  assert.equal(f.controller.state.methodsError,'METHODS_UNAVAILABLE');
  assert.equal(f.controller.state.busy,false);assert.deepEqual(f.controller.state.rows,[row]);
  await f.controller.open();assert.deepEqual(f.controller.state.rows,[row]);
  assert.equal(f.controller.state.busy,false);
  assert.deepEqual(f.requests.map(r=>r.operation),['list','methods','list']);f.controller.dispose();
});
const {workspaceStatus}=await import(url(fs.readFileSync('studio/native/frontend/workspace-copy.js','utf8')));
const noChatMessage='Open or select a Motion Studio chat in the sidebar, then come back here.';
await test('missing focused chat opens once on selection, without sending or generating',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  assert.equal(workspaceStatus(f.controller.state.status),noChatMessage);assert.equal(f.requests.length,0);
  f.set('focusedSessionId','s1');f.set('focusedSessionId','s1');await flush();
  assert.deepEqual(f.requests.map(item=>item.operation),['list']);
  const count=f.requests.length;f.set('focusedSessionId','s1');await flush();
  assert.equal(f.requests.length,count);f.controller.dispose();
});
await test('rapid focus changes collapse to one open for the final chat',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  f.set('focusedSessionId','s1');f.set('focusedSessionId',null);
  f.set('focusedSessionId','s1');f.set('focusedSessionId','s2');await flush();
  assert.deepEqual(f.requests.map(item=>item.operation),['list']);
  assert.ok(f.requests.every(item=>item.payload.session_id==='s2'));f.controller.dispose();
});
await test('failed automatic chat open is not retried by repeated notifications',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  f.handle(()=>{throw Error('Synthetic unavailable');});f.set('focusedSessionId','s1');await flush();
  assert.equal(f.requests.length,1);f.set('focusedSessionId','s1');await flush();
  assert.equal(f.requests.length,1);f.controller.dispose();
});
await test('queued focused-chat open is cancelled by disposal',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  f.set('focusedSessionId','s1');f.controller.dispose();await flush();
  assert.equal(f.requests.length,0);
});
await test('returning from no focused chat reopens read-only saved state once',async()=>{
  const f=setup();await f.controller.open();f.set('focusedSessionId',null);
  assert.equal(workspaceStatus(f.controller.state.status),noChatMessage);const before=f.requests.length;
  f.set('focusedSessionId','s1');await flush();
  assert.deepEqual(f.requests.slice(before).map(item=>item.operation),['list']);f.controller.dispose();
});
await test('focused chat still requires matching owner before any RPC',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  f.set('focusedSessionOwner',{connectionId:'other',profile:'other'});
  f.set('focusedSessionId','s1');await flush();assert.equal(f.requests.length,0);f.controller.dispose();
});
console.log(JSON.stringify({kind:'Deterministic fake primary SDK; no host/media effects',checks},null,2));
// Real React + real CreationController in the existing jsdom dependency. No producers.
{
  const {createRequire}=await import('node:module'),path=await import('node:path');
  const require=createRequire(import.meta.url),desktop=path.join(process.env.HERMES_SOURCE||path.join(os.homedir(),'.hermes/hermes-agent-official'),'apps/desktop/node_modules');
  const {JSDOM}=require(path.join(desktop,'jsdom'));
  const {build}=require(process.env.ESBUILD_PACKAGE||'esbuild');
  const source=`
    import {createElement as h,act} from 'react';
    import {createRoot} from 'react-dom/client';
    import {CreationPage,actionResult} from './studio/native/frontend/creation-page.js';
    import {CreationController} from './studio/native/frontend/creation-controller.js';
    window.act=act;window.actionResult=actionResult;
    const values={focusedSessionId:'s1',focusedSessionOwner:{connectionId:'c1',profile:'p1'},connectionId:'c1',profile:'p1',gateway:'open'};
    const listeners=Object.fromEntries(Object.keys(values).map(key=>[key,new Set()]));
    window.change=(key,value)=>{values[key]=value;for(const fn of listeners[key])fn(value);};
    const state=Object.fromEntries(Object.keys(values).map(key=>[key,{get:()=>values[key],subscribe:fn=>{listeners[key].add(fn);fn(values[key]);return()=>listeners[key].delete(fn);}}]));
    window.rows=[{request:'r1',revision:1,kind:'Sound effects',direction:'Synthetic sound',state:'Ready for review',takes:[{id:'t1',review:'Not reviewed'}]}];
    window.calls=[];window.draft='';window.inserted=[];
    window.inventory={kinds:{'Sound effects':{default:'local',options:[{id:'local',label:'Local method',available:true,cost:'free',engine:'local'},{id:'other',label:'Other method',available:true,cost:'unknown',engine:'cloud'}]}}};
    const host={state,profileRoutes:async()=>[{primary:true,mode:'local',connectionId:'c1',profile:'p1',targetProfile:'p1'}],request:async(method,payload)=>{
      const op=method.split('.').at(-1);window.calls.push({op,payload});if(window.gate)await window.gate;
      if(window.problem)return {error:window.problem};
      if(op==='list')return {creations:structuredClone(window.rows)};
      if(op==='methods')return window.inventory;
      if(op==='select'){window.rows[0].takes[0].selected=true;return {};}
      if(op==='review'){window.rows[0].takes[0].review=payload.outcome;return {};}
      if(op==='admit'||op==='admit_music')return {};
      if(op==='chunk')return window.chunk;
      throw Error('Unexpected action');},composer:{getDraft:async()=>{if(window.gate)await window.gate;return window.draft;},insertText:async(session,text)=>{window.inserted.push({session,text});return true;}}};
    window.root=createRoot(document.querySelector('#root'));
    window.mount=()=>window.root.render(h(CreationPage,{createController:notify=>{const c=new CreationController(host,notify,{setTimeout:()=>1,clearTimeout:()=>{}});window.controller=c;return c;},onProduction:()=>{window.productionOpened=true;}}));
  `;
  const bundle=await build({stdin:{contents:source,resolveDir:process.cwd(),sourcefile:'lane-q-feedback.js'},bundle:true,write:false,format:'iife',platform:'browser',nodePaths:[desktop],plugins:[{
    name:'sdk',setup(build){build.onResolve({filter:/^@hermes\/plugin-sdk$/},()=>({path:'sdk',namespace:'fixture'}));build.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:"import {createElement as h} from 'react';export const Button=props=>h('button',props),Textarea=props=>h('textarea',props),Input=props=>h('input',props);",resolveDir:desktop}));}
  }]});
  const dom=new JSDOM('<div id="root"></div>',{url:'https://motion.invalid/',runScripts:'dangerously'}),w=dom.window;
  w.IS_REACT_ACT_ENVIRONMENT=true;w.structuredClone=structuredClone;
  w.MessageChannel=class {constructor(){this.port1={onmessage:null};this.port2={postMessage:()=>setImmediate(()=>this.port1.onmessage?.())};}};
  Object.defineProperty(w,'crypto',{value:crypto.webcrypto});w.URL.createObjectURL=()=> 'blob:synthetic';w.URL.revokeObjectURL=()=>{};
  const timers=new Map();let timerId=0;
  w.setTimeout=(fn,delay)=>{const id=++timerId;if(delay===6000)timers.set(id,fn);else setTimeout(fn,delay);return id;};w.clearTimeout=id=>timers.delete(id);
  w.eval(bundle.outputFiles[0].text);
  const settle=()=>new Promise(resolve=>setTimeout(resolve,210));
  const act=fn=>w.act(async()=>{await fn();await flush();});
  const button=name=>[...w.document.querySelectorAll('button')].find(el=>(el.getAttribute('aria-label')||el.textContent)===name);
  const click=async name=>{const el=button(name);assert.ok(el,name);await act(()=>el.click());return el;};
  const result=el=>el.closest('.ms-action').querySelector('.ms-action-result');
  const finish=()=>act(settle);
  const fill=async(selector,value)=>act(()=>{const el=w.document.querySelector(selector);Object.getOwnPropertyDescriptor(w.HTMLTextAreaElement.prototype,'value').set.call(el,value);el.dispatchEvent(new w.Event('input',{bubbles:true}));});
  try{
    await act(()=>w.mount());
    await test('Open shows busy on its button, count inline/header, changed cards, and expires',async()=>{
      w.gate=new Promise(resolve=>{w.release=resolve;});
      const el=await click('Open saved creations');assert.equal(el.textContent,'Opening…');assert.equal(el.disabled,true);assert.ok(el.querySelector('.ms-busy-dot'));
      assert.equal(button('Refresh progress').textContent,'Refresh progress');
      await act(()=>{w.release();w.gate=null;});await finish();
      assert.match(result(el).textContent,/1 creation/);assert.equal(result(el).dataset.tone,'good');assert.equal(result(el).getAttribute('aria-live'),'polite');
      assert.match(w.document.querySelector('.ms-status').textContent,/1 creation/);
      w.rows.push({request:'r2',revision:1,kind:'Image',direction:'Synthetic image',state:'Prepared',takes:[]});
      const refresh=await click('Refresh progress');assert.equal(refresh.textContent,'Refreshing…');await finish();
      assert.match(result(refresh).textContent,/2 creations/);assert.ok(w.document.querySelector('.ms-card-changed'));
      await act(()=>{for(const fn of [...timers.values()])fn();});assert.equal(result(refresh).textContent,'');
    });
    await test('chat success points to Send; draft conflict is amber; append preserves exact controller call',async()=>{
      await fill('#ms-request','Synthetic direction');w.gate=new Promise(resolve=>{w.release=resolve;});
      const create=await click('Create in chat');assert.equal(create.textContent,'Adding to chat…');assert.equal(create.disabled,true);
      await act(()=>{w.release();w.gate=null;});await finish();
      assert.equal(result(create).textContent,'Added to your chat — press Send there →');assert.equal(w.inserted.length,1);assert.equal(w.inserted[0].session,'s1');
      w.draft='Existing draft';await click('Create in chat');await finish();assert.equal(result(create).dataset.tone,'warn');assert.match(result(create).textContent,/already has a draft/);assert.equal(w.inserted.length,1);
      const append=await click('Add to existing draft');await finish();assert.equal(result(append).dataset.tone,'good');assert.equal(w.inserted.length,2);
    });
    await test('Choose and verdict persist controller outcomes and pulse updated badges',async()=>{
      const choose=await click('Choose this take');assert.equal(choose.textContent,'Choosing…');await finish();
      assert.equal(choose.textContent,'Chosen');assert.equal(result(choose).textContent,'Take chosen.');assert.ok(w.document.querySelector('.ms-feedback-pulse'));
      for(const [label,outcome] of [['Listened: matches request','Matches request'],['Listened: needs work','Needs work']]){
        const verdict=await click(label);assert.equal(verdict.textContent,'Saving…');await finish();
        assert.equal(verdict.getAttribute('aria-pressed'),'true');assert.equal(w.rows[0].takes[0].review,outcome);assert.equal(result(verdict).dataset.tone,'good');
      }
    });
    await test('refinement, append, connections, and method selection each show their own result',async()=>{
      await fill('#ms-refine','Synthetic shorter ending');
      const refine=await click('Put refinement in selected chat');await finish();assert.equal(result(refine).dataset.tone,'warn');
      const append=await click('Append to existing draft');await finish();assert.match(result(append).textContent,/press Send there/);
      for(const name of ['Connect this chat','Connect Music workflow']){const el=await click(name);assert.equal(el.textContent,'Connecting…');await finish();assert.equal(result(el).dataset.tone,'good');}
      await act(()=>{const select=w.document.querySelector('#ms-method');select.value='other';select.dispatchEvent(new w.Event('change',{bubbles:true}));});
      assert.equal(w.document.querySelector('.ms-method-feedback').disabled,true);assert.match(w.document.querySelector('.ms-method-feedback').textContent,/Selecting…/);await finish();
      assert.match(w.document.querySelector('.ms-method-feedback>.ms-action-result').textContent,/Other method/);
    });
    await test('Play retrieval busy state and confirmed inline outcome use real retained-byte verification',async()=>{
      const bytes=Buffer.from('synthetic audio bytes'),digest=crypto.createHash('sha256').update(bytes).digest('hex');
      w.chunk={take:'t1',offset:0,total:bytes.length,bytes:bytes.toString('base64'),sha256:digest,chunk_sha256:digest,mime:'audio/wav'};
      w.HTMLMediaElement.prototype.play=async()=>{};
      const play=await click('Load original audio');assert.equal(play.textContent,'Loading…');await finish();
      assert.equal(result(play).dataset.tone,'good');assert.match(result(play).textContent,/Player ready/);assert.ok(w.document.querySelector('audio[src="blob:synthetic"]'));
    });
    await test('saved-card and Production navigation show feedback on the initiating control',async()=>{
      const card=w.document.querySelector('.ms-card');await act(()=>card.click());assert.equal(card.getAttribute('aria-busy'),'true');assert.match(card.textContent,/Opening…/);await finish();
      assert.match(card.closest('.ms-card-action').textContent,/Creation opened/);
      const nav=await click('Open Production →');assert.equal(nav.textContent,'Opening…');assert.match(result(nav).textContent,/link this take/);assert.equal(w.productionOpened,undefined);
      await act(()=>new Promise(resolve=>setTimeout(resolve,440)));assert.equal(w.productionOpened,true);
    });
    await test('a repeated review failure cannot reuse an already-saved verdict as success',async()=>{
      w.problem='STALE_REVISION';const verdict=await click('Listened: needs work');await finish();assert.equal(result(verdict).dataset.tone,'warn');assert.match(result(verdict).textContent,/creation changed/);w.problem=null;
    });
    await test('problems remain amber and scope changes clear old success',async()=>{
      w.problem='STALE_REVISION';const refresh=await click('Refresh progress');await finish();assert.equal(result(refresh).dataset.tone,'warn');assert.match(result(refresh).textContent,/creation changed/);w.problem=null;
      await act(()=>w.change('gateway','closed'));assert.equal(w.document.querySelectorAll('.ms-action-result[data-tone="good"]').length,0);
      assert.match(w.document.querySelector('.ms-status').textContent,/changed/);
    });
    await test('an access refusal during Open is still visible next to Open',async()=>{
      await act(()=>w.change('gateway','open'));w.problem='CREATION_ACCESS_UNAVAILABLE';const el=await click('Open saved creations');await finish();
      assert.equal(result(el).dataset.tone,'warn');assert.match(result(el).textContent,/access is not configured/);w.problem=null;
    });
    await test('reduced-motion styles suppress spinner/pulse animations',async()=>{
      const css=w.document.querySelector('style').textContent;assert.match(css,/@media\(prefers-reduced-motion:reduce\)[\s\S]*animation:none!important/);
      assert.equal(w.actionResult('CREATION_ACCESS_UNAVAILABLE').tone,'warn');assert.equal(w.actionResult('Draft added to selected chat.',{kind:'chat'}).tone,'good');
    });
  }finally{await act(()=>w.root.unmount());w.close();}
}
console.log(JSON.stringify({kind:'Quick Create feedback: real React/controller + jsdom; no producers',passed:checks.length,checks},null,2));
