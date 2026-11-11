// Deterministic Production controller integrity/scope checks; fake primary only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
const url=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const transport=url(fs.readFileSync('studio/native/frontend/transport.js','utf8'));
const retained=url(fs.readFileSync('studio/native/frontend/retained-bytes.js','utf8'));
const {ProductionController}=await import(url(fs.readFileSync('studio/native/frontend/production-controller.js','utf8')
  .replace("'./transport.js'",JSON.stringify(transport)).replace("'./retained-bytes.js'",JSON.stringify(retained))));
const request='a'.repeat(32),take='d'.repeat(32),production='b'.repeat(32),asset='c'.repeat(32);
const linked={id:take,request,source_request_revision:1,artifact:'e'.repeat(32),origin:'test_fixture',review:'Not reviewed',selected:true};
const current={id:production,revision:2,brief_revision:1,title:'Synthetic',brief:{text:'',purpose:'',audience:'',usage:''},references:[],
  assets:[{id:asset,position:0,kind:'Sound effects',intent:'Synthetic intent',selected_take:take,stale:false,depends_on:[],references:[],takes:[linked]}]};
const checks=[];async function test(name,run){await run();checks.push(name);}
const storage=new Map();globalThis.localStorage={getItem:key=>storage.get(key)||null,
  setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
function setup(){
  storage.clear();const f=fixture();f.route.primary=true;f.route.mode=process.env.TEST_ROUTE_MODE||'local';const requests=[];let handler=async op=>op==='list'?{productions:[current],available:[linked],capabilities:{}}:
    op==='open'?{current,available:[linked],capabilities:{}}:{};
  f.host.request=async(method,payload)=>{const operation=method.split('.').at(-1);requests.push({operation,payload});return handler(operation,payload);};
  return {...f,requests,handle:value=>{handler=value;},controller:new ProductionController(f.host,()=>{})};
}
const bytes=Buffer.from('Synthetic Production retained bytes'),hash=b=>crypto.createHash('sha256').update(b).digest('hex');
await test('Production Connect reopens current focus after denial, then confirms connection',async()=>{
  const f=setup();f.handle(()=>({error:'PRODUCTION_WORKFLOW_REVIEW_REQUIRED'}));await f.controller.open();
  assert.equal(f.controller.state.needsConnection,true);f.set('focusedSessionId','new-chat');
  const gate=deferred();f.handle(op=>op==='admit'?gate.promise:{productions:[],available:[],capabilities:{}});
  const work=f.controller.admit();await flush();assert.equal(f.controller.state.connectionStatus,'Connecting…');
  await f.controller.admit();assert.deepEqual(f.requests.filter(r=>r.operation==='admit').map(r=>r.payload.session_id),['new-chat']);
  gate.resolve({});await work;assert.equal(f.controller.state.connectionStatus,'This chat is connected');
  assert.equal(f.controller.state.needsConnection,false);f.controller.dispose();
});
await test('Production Connect rejects focus transitions, disposal and stale replies without replay',async()=>{
  for(const mode of ['focus','away-back','dispose','reply']){
    const f=setup();await f.controller.open();const gate=deferred();
    if(mode==='reply')f.handle(()=>gate.promise);else f.host.profileRoutes=()=>gate.promise;
    const work=f.controller.admit();await flush();
    if(mode==='dispose')f.controller.dispose();else{f.set('focusedSessionId','away');if(mode==='away-back')f.set('focusedSessionId','s1');}
    gate.resolve(mode==='reply'?{}:[f.route]);await work;
    assert.equal(f.requests.filter(r=>r.operation==='admit').length,mode==='reply'?1:0);
    assert.notEqual(f.controller.state.connectionStatus,'This chat is connected');f.controller.dispose();
  }
});
await test('Production Connect keeps pending mutation guard and reports plain errors',async()=>{
  const f=setup();await f.controller.open();f.controller.pending={operation:'create'};
  await f.controller.admit();assert.equal(f.requests.filter(r=>r.operation==='admit').length,0);
  f.controller.pending=null;f.handle(()=>({error:'PRODUCTION_ACCESS_UNAVAILABLE'}));await f.controller.admit();
  assert.match(f.controller.state.connectionStatus,/Cannot connect/);f.controller.dispose();
});
await test('Production Connect refuses missing focus or mismatched owner and never retries a lost acknowledgement',async()=>{
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
const chunk={take,offset:0,total:bytes.length,bytes:bytes.toString('base64'),sha256:hash(bytes),chunk_sha256:hash(bytes)};
await test('Production controller rejects wrong-take first chunk with valid bytes and hashes',async()=>{
  const f=setup();await f.controller.open();f.handle(()=>({...chunk,take:'f'.repeat(32)}));await f.controller.load(linked);
  assert.equal(f.controller.state.url,null);assert.equal(f.controller.state.status,'The original bytes could not be verified. Reopen the take and try again.');f.controller.dispose();
});
await test('Production valid retained bytes publish one revocable original URL',async()=>{
  const f=setup();await f.controller.open();f.handle(()=>chunk);await f.controller.load(linked);
  assert.match(f.controller.state.url,/^blob:/);assert.equal(f.controller.state.urlTake,take);f.controller.dispose();
});
await test('Production disposal during chunk cannot publish bytes',async()=>{
  const f=setup();await f.controller.open();const gate=deferred();f.handle(()=>gate.promise);
  const work=f.controller.load(linked);await flush();f.controller.dispose();gate.resolve(chunk);await work;
  assert.equal(f.controller.state.url,null);
});
await test('Production away-and-back clears projection and never replays mutation',async()=>{
  const f=setup();await f.controller.open();f.set('focusedSessionId','away');f.set('focusedSessionId','s1');
  await f.controller.saveBrief({title:'Must not save',brief:{text:'',purpose:'',audience:'',usage:''}});
  assert.equal(f.requests.length,2);assert.equal(f.controller.state.current,null);f.controller.dispose();
});
await test('Production lost mutation reply preserves saved projection without automatic retry',async()=>{
  const f=setup();await f.controller.open();f.handle(op=>{if(op==='update_brief')throw Error('Lost reply');return {current,available:[linked]};});
  await f.controller.saveBrief({title:'Synthetic changed',brief:{text:'Changed',purpose:'',audience:'',usage:''}});
  assert.equal(f.requests.filter(item=>item.operation==='update_brief').length,1);assert.equal(f.controller.state.current.id,production);
  assert.match(f.controller.state.status,/unobserved/);f.controller.dispose();
});
await test('lost create locks replacement until exact saved command is reconciled',async()=>{
  const f=setup();f.handle(op=>op==='list'?{productions:[],available:[],capabilities:{}}:{});
  await f.controller.open();let saved=null;
  f.handle(op=>{if(op==='create'){saved={...current,command:f.controller.pending.payload.command};throw Error('Lost create');}return {};});
  const fields={title:'Synthetic lost create',brief:{text:'Synthetic'},kinds:['Image']};
  await f.controller.create(fields);await f.controller.create(fields);
  assert.equal(f.requests.filter(item=>item.operation==='create').length,1);assert.equal(f.controller.state.pending,true);
  await f.controller.open();await f.controller.create(fields);
  assert.equal(f.requests.filter(item=>item.operation==='create').length,1);assert.equal(f.controller.state.pending,true);
  f.handle(op=>op==='list'?{productions:[saved],available:[],capabilities:{}}:op==='open'?{current:saved,available:[]}:{});
  await f.controller.open();assert.equal(f.controller.state.pending,false);assert.equal(f.controller.state.current.id,production);
  assert.equal(f.requests.filter(item=>item.operation==='create').length,1);f.controller.dispose();
});
await test('reload before observed create ID reopens saved command without duplicate',async()=>{
  const f=setup();let saved=null;
  f.handle(op=>{if(op==='list')return {productions:saved?[saved]:[],available:[]};
    if(op==='open')return {current:saved,available:[]};if(op==='create'){saved={...current,command:f.controller.pending.payload.command};throw Error('Lost create');}});
  await f.controller.open();await f.controller.create({title:'Reload lost create',brief:{text:'Synthetic'},kinds:['Image']});
  const firstCount=f.requests.filter(item=>item.operation==='create').length;f.controller.dispose();
  f.controller=new ProductionController(f.host,()=>{});await f.controller.open();
  assert.equal(f.controller.state.current.command,saved.command);assert.equal(f.requests.filter(item=>item.operation==='create').length,firstCount);
  f.controller.dispose();
});
await test('postcommit coded projection failure does not release replacement Create',async()=>{
  const f=setup();await f.controller.open();let saved=null;
  f.handle(op=>{if(op==='create'){saved={...current,command:f.controller.pending.payload.command};
    const error=Error('Projection failed after commit');error.code='PRODUCTION_OPERATION_UNAVAILABLE';throw error;}});
  const fields={title:'Postcommit projection failure',brief:{text:'Synthetic'},kinds:['Image']};
  await f.controller.create(fields);assert.equal(f.controller.state.status,'The reply could not be confirmed. Reopen the project before trying again.');
  await f.controller.create(fields);
  assert.equal(f.requests.filter(item=>item.operation==='create').length,1);assert.equal(f.controller.state.pending,true);
  f.controller.dispose();f.controller=new ProductionController(f.host,()=>{});
  f.handle(op=>{if(op==='list')throw Error('Initial observation lost');});await f.controller.open();await f.controller.create(fields);
  assert.equal(f.requests.filter(item=>item.operation==='create').length,1);assert.equal(f.controller.state.pending,true);
  f.controller.dispose();assert.ok(saved);
});
await test('reload survives failed delayed empty and lost initial observation',async()=>{
  const f=setup();let saved=null;f.handle(()=>({productions:[],available:[]}));await f.controller.open();
  f.handle(op=>{if(op==='create'){saved={...current,command:f.controller.pending.payload.command};throw Error('Lost create');}});
  await f.controller.create({title:'Observation matrix',brief:{text:'Synthetic'},kinds:['Image']});
  const creates=()=>f.requests.filter(item=>item.operation==='create').length;f.controller.dispose();
  f.controller=new ProductionController(f.host,()=>{});f.handle(()=>{throw Error('List failed');});
  await f.controller.open();await f.controller.create({title:'Replacement',brief:{},kinds:['Image']});assert.equal(creates(),1);
  const gate=deferred();f.handle(()=>gate.promise);const delayed=f.controller.open();await flush();
  await f.controller.create({title:'Replacement',brief:{},kinds:['Image']});assert.equal(creates(),1);
  gate.resolve({productions:[],available:[]});await delayed;assert.equal(f.controller.state.pending,true);
  await f.controller.create({title:'Replacement',brief:{},kinds:['Image']});assert.equal(creates(),1);
  f.handle(op=>{if(op==='list')return {productions:[saved],available:[]};if(op==='open')throw Error('Open reply lost');});
  await f.controller.open();assert.equal(f.controller.state.pending,true);
  await f.controller.create({title:'Replacement',brief:{},kinds:['Image']});assert.equal(creates(),1);
  f.handle(op=>op==='list'?{productions:[saved],available:[]}:{current:saved,available:[]});
  await f.controller.open();assert.equal(f.controller.state.pending,false);assert.equal(creates(),1);f.controller.dispose();
});
await test('draft base revision is not rebased when refresh observes newer head',async()=>{
  const f=setup();await f.controller.open();const newer={...current,revision:3,title:'Agent intervening edit'};
  f.handle(op=>{if(op==='open')return {current:newer,available:[linked]};if(op==='update_brief')return {error:'PRODUCTION_STALE_REVISION'};});
  await f.controller.refresh();await f.controller.saveBrief({title:'Stale visual draft',brief:{text:'Draft'},expected:2});
  const sent=f.requests.find(item=>item.operation==='update_brief');assert.equal(sent.payload.expected,2);
  assert.equal(f.controller.state.status,'The project changed. Refresh before saving this edit.');assert.equal(f.controller.state.pending,false);
  assert.equal(f.controller.state.current.title,'Agent intervening edit');f.controller.dispose();
});
await test('old private-text closure cannot submit after A away-and-back transition',async()=>{
  const f=setup();await f.controller.open();const identity={epoch:f.controller.epoch,production,asset};
  f.set('focusedSessionId','away');f.set('focusedSessionId','s1');
  await f.controller.addAsset('Sound effects','Synthetic A private intent',identity);
  await f.controller.addReference(linked,'Synthetic A private reference',identity);
  assert.equal(f.requests.length,2);assert.equal(f.controller.state.current,null);f.controller.dispose();
});
for(const observation of ['failed','empty'])await test('away/back without reopen restores unresolved Create before '+observation+' observation',async()=>{
  const f=setup();f.handle(()=>({productions:[],available:[]}));await f.controller.open();
  f.handle(()=>{throw Error('Lost create');});
  const fields={title:'Synthetic uncertain A',brief:{text:'Synthetic'},kinds:['Image']};
  await f.controller.create(fields);const original=f.controller.pending.command;
  f.set('focusedSessionId','away');f.set('focusedSessionId','s1');
  f.handle(()=>{if(observation==='failed')throw Error('Observation failed');return {productions:[],available:[]};});
  await f.controller.open();await f.controller.create(fields);
  assert.equal(f.requests.filter(row=>row.operation==='create').length,1);
  assert.equal(f.controller.pending.command,original);assert.equal(f.controller.state.pending,true);f.controller.dispose();
});
await test('same-scope reopen retains exact pending payload for reconciliation',async()=>{
  const f=setup();f.handle(()=>({productions:[],available:[]}));await f.controller.open();
  f.handle(()=>{throw Error('Lost create');});await f.controller.create({title:'Synthetic',brief:{},kinds:['Image']});
  const pending=f.controller.pending;await f.controller.open();assert.equal(f.controller.pending,pending);f.controller.dispose();
});
await test('Create checks durable marker again immediately before dispatch',async()=>{
  const f=setup();f.handle(()=>({productions:[],available:[]}));await f.controller.open();
  const original='9'.repeat(32);storage.set('motion-studio.production.unresolved-create-v1',JSON.stringify({
    [f.controller.scope()]:{operation:'create',command:original}}));
  await f.controller.create({title:'Replacement',brief:{},kinds:['Image']});
  assert.equal(f.requests.filter(row=>row.operation==='create').length,0);assert.equal(f.controller.pending.command,original);f.controller.dispose();
});
for(const operation of ['refresh','mutation','load'])for(const code of ['PRODUCTION_ACCESS_UNAVAILABLE',
  'PRODUCTION_SCOPE_DENIED','PRODUCTION_WORKFLOW_REVIEW_REQUIRED','CREATION_STORE_REVIEW_REQUIRED',
  'MUSIC_SCOPE_REVIEW_REQUIRED','MUSIC_WORKFLOW_REVIEW_REQUIRED','MUSIC_POLICY_CHANGED','MUSIC_BINDING_DENIED',
  'MUSIC_EFFECT_REVIEW_REQUIRED'])
  await test('loaded audio cleared on explicit '+code+' during '+operation,async()=>{
    const f=setup();await f.controller.open();f.handle(()=>chunk);await f.controller.load(linked);
    const original=f.controller.state.url;assert.match(original,/^blob:/);
    f.handle(()=>({error:code}));
    if(operation==='refresh')await f.controller.refresh();
    else if(operation==='load')await f.controller.load(linked);
    else await f.controller.saveBrief({title:'Synthetic',brief:{}});
    assert.equal(f.controller.state.current,null);assert.deepEqual(f.controller.state.productions,[]);
    assert.deepEqual(f.controller.state.available,[]);assert.equal(f.controller.state.url,null);
    await assert.rejects(fetch(original));
    if(operation==='mutation'){
      assert.equal(f.controller.state.pending,true);assert.equal(f.controller.pending.payload,null);
      assert.match(f.controller.pending.command,/^[a-f0-9]{32}$/);
    }
    const count=f.requests.length;f.handle(()=>({current,productions:[current],available:[linked]}));
    await f.controller.refresh();assert.equal(f.requests.length,count);assert.equal(f.controller.state.current,null);
    await f.controller.open();assert.equal(f.controller.state.current.id,production);
    f.controller.dispose();
  });
await test('generic transient refresh error retains authorized projection and audio',async()=>{
  const f=setup();await f.controller.open();f.handle(()=>chunk);await f.controller.load(linked);const original=f.controller.state.url;
  f.handle(()=>{throw Error('Transient read');});await f.controller.refresh();
  assert.equal(f.controller.state.current.id,production);assert.equal(f.controller.state.url,original);f.controller.dispose();
});
const noChatMessage='Open or select a Motion Studio chat in the sidebar, then come back here.';
await test('missing focused chat opens once on selection, without sending or generating',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  assert.equal(f.controller.state.status,noChatMessage);assert.equal(f.requests.length,0);
  f.set('focusedSessionId','s1');f.set('focusedSessionId','s1');await flush();
  assert.deepEqual(f.requests.map(item=>item.operation),['list','open']);
  const count=f.requests.length;f.set('focusedSessionId','s1');await flush();
  assert.equal(f.requests.length,count);f.controller.dispose();
});
await test('rapid focus changes collapse to one open for the final chat',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  f.set('focusedSessionId','s1');f.set('focusedSessionId',null);
  f.set('focusedSessionId','s1');f.set('focusedSessionId','s2');await flush();
  assert.deepEqual(f.requests.map(item=>item.operation),['list','open']);
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
  assert.equal(f.controller.state.status,noChatMessage);const before=f.requests.length;
  f.set('focusedSessionId','s1');await flush();
  assert.deepEqual(f.requests.slice(before).map(item=>item.operation),['list','open']);f.controller.dispose();
});
await test('focused chat still requires matching owner before any RPC',async()=>{
  const f=setup();f.set('focusedSessionId',null);await f.controller.open();
  f.set('focusedSessionOwner',{connectionId:'other',profile:'other'});
  f.set('focusedSessionId','s1');await flush();assert.equal(f.requests.length,0);f.controller.dispose();
});
console.log(JSON.stringify({kind:'Production controller fake-primary integrity and lifecycle checks',checks},null,2));
