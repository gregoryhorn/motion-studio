// Deterministic no-model comparison adverse paths with the real scoped owner.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
const url=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const retained=url(fs.readFileSync('studio/native/frontend/retained-bytes.js','utf8'));
const transport=url(fs.readFileSync('studio/native/frontend/transport.js','utf8'));
const {ComparisonController}=await import(url(fs.readFileSync('studio/native/frontend/comparison-controller.js','utf8').replace("'./retained-bytes.js'",JSON.stringify(retained))));
const {ProductionController}=await import(url(fs.readFileSync('studio/native/frontend/production-controller.js','utf8')
  .replace("'./transport.js'",JSON.stringify(transport)).replace("'./retained-bytes.js'",JSON.stringify(retained))));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const bytes=Buffer.from('Nonprivate exact comparison bytes'),digest=hash(bytes);
const takes=['a','b','c'].map((letter,index)=>({id:letter.repeat(32),request:'d'.repeat(32),digest,size:bytes.length,
  review:'Not reviewed',origin:'test_fixture',source_request_revision:index+1,selected:index===0}));
const current={id:'e'.repeat(32),revision:3,assets:[{id:'f'.repeat(32),kind:'Sound effects',takes,selected_take:takes[0].id,stale:true}]};
const chunk=take=>({take,offset:0,total:bytes.length,bytes:bytes.toString('base64'),sha256:digest,chunk_sha256:digest});
class AudioFixture{
  constructor(){this.src='';this.paused=true;this.currentTime=0;this.duration=2;this.volume=1;this.plays=0;}
  pause(){this.paused=true;}
  load(){}
  removeAttribute(){this.src='';}
  getAttribute(){return this.src;}
  async play(){this.plays++;this.paused=false;}
}
async function setup(){
  const f=fixture();f.route.primary=true;const calls=[];let handler=(operation,payload)=>operation==='list'?{productions:[current]}:
    operation==='open'?{current:structuredClone(current),available:[]}:chunk(payload.take);
  f.host.request=async(method,payload)=>{const operation=method.split('.').at(-1);calls.push({operation,payload});return handler(operation,payload);};
  const owner=new ProductionController(f.host);await owner.open();owner.compare();
  const audio=new AudioFixture(),comparison=new ComparisonController(owner,audio);owner.reviewCleanup=()=>comparison.dispose();
  return {...f,owner,audio,comparison,calls,handle:value=>{handler=value;}};
}
const checks=[];async function test(name,body){await body();checks.push(name);}
await test('two exact linked alternatives read only original chunks; no autoplay or selection',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);await f.comparison.choose('B',takes[1].id);
  assert.ok(f.comparison.state.slots.A.url);assert.ok(f.comparison.state.slots.B.url);assert.equal(f.audio.plays,0);
  assert.deepEqual(f.calls.map(call=>call.operation),['list','open','chunk','chunk']);
  assert.equal(f.owner.state.current.assets[0].selected_take,takes[0].id);f.owner.dispose();
});
await test('switch pauses, preserves absolute position and gain, and requires explicit Play',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);await f.comparison.choose('B',takes[1].id);
  f.comparison.activate('A');f.comparison.metadata();f.comparison.volume(0.37);f.comparison.seek('1.25');await f.comparison.play();
  assert.equal(f.audio.paused,false);f.comparison.activate('B');assert.equal(f.audio.paused,true);
  f.comparison.metadata();assert.equal(f.audio.currentTime,1.25);assert.equal(f.audio.volume,0.37);assert.equal(f.audio.plays,1);
  await f.comparison.play();assert.equal(f.audio.plays,2);f.owner.dispose();
});
await test('shorter end, invalid positions and ended never clamp, loop or start other slot',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);f.comparison.activate('A');f.audio.duration=0.5;f.comparison.metadata();
  for(const value of ['',-1,'Infinity','NaN',0.5,1]){f.comparison.seek(value);await f.comparison.play();assert.equal(f.audio.plays,0);}
  f.comparison.seek('0.25');await f.comparison.play();f.comparison.ended();assert.equal(f.audio.paused,true);
  assert.match(f.comparison.state.status,/Other take did not start/);f.owner.dispose();
});
for(const change of ['focusedSessionId','profile','connectionId','gateway'])await test(change+' loss during read clears private bytes and ignores response',async()=>{
  const f=await setup(),gate=deferred();f.handle(()=>gate.promise);const work=f.comparison.choose('A',takes[0].id);await flush();
  f.set(change,'changed');gate.resolve(chunk(takes[0].id));await work;
  assert.equal(f.owner.state.current,null);assert.equal(f.comparison.state.slots.A,null);assert.equal(f.audio.src,'');f.owner.dispose();
});
for(const action of ['clear','dispose','chooseAsset','publish'])await test(action+' during read cannot publish stale bytes',async()=>{
  const f=await setup(),gate=deferred();f.handle(()=>gate.promise);const work=f.comparison.choose('A',takes[0].id);await flush();
  if(action==='chooseAsset')f.owner.chooseAsset('other');else if(action==='publish')f.owner.publish({current:{...current,revision:4}});else f.owner[action]();
  gate.resolve(chunk(takes[0].id));await work;assert.equal(f.comparison.state.slots.A,null);assert.equal(f.audio.src,'');f.owner.dispose();
});
await test('slot replacement rejects delayed response and does not affect replacement',async()=>{
  const f=await setup(),gate=deferred();f.handle((_op,payload)=>payload.take===takes[0].id?gate.promise:chunk(payload.take));
  const work=f.comparison.choose('A',takes[0].id);await flush();await f.comparison.choose('A',takes[2].id);
  const replacement=f.comparison.state.slots.A.url;gate.resolve(chunk(takes[0].id));await work;
  assert.equal(f.comparison.state.slots.A.take.id,takes[2].id);assert.equal(f.comparison.state.slots.A.url,replacement);f.owner.dispose();
});
for(const malformed of ['take','offset','total','bytes','sha256','chunk_sha256','projection_digest','projection_size'])await test('rejects malformed '+malformed,async()=>{
  const f=await setup();f.handle(()=>{const value=chunk(takes[0].id);
    if(malformed==='projection_digest')value.sha256='0'.repeat(64);
    else if(malformed==='projection_size')f.comparison.takes[0]={...f.comparison.takes[0],size:99};
    else value[malformed]=({take:'wrong',offset:1,total:1,bytes:'!',sha256:'0'.repeat(64),chunk_sha256:'0'.repeat(64)})[malformed];
    return value;});
  // Projection size mismatch needs to exist before the captured immutable take is chosen.
  if(malformed==='projection_size')f.comparison.takes=f.comparison.takes.map(t=>({...t,size:99}));
  await f.comparison.choose('A',takes[0].id);assert.equal(f.comparison.state.slots.A.url,null);f.owner.dispose();
});
await test('self-consistent chunk digest still must match linked immutable digest',async()=>{
  const f=await setup(),other=Buffer.from('Other bytes');f.handle(()=>({...chunk(takes[0].id),bytes:other.toString('base64'),
    total:other.length,sha256:hash(other),chunk_sha256:hash(other)}));
  await f.comparison.choose('A',takes[0].id);assert.equal(f.comparison.state.status,'CREATION_INTEGRITY_FAILED');f.owner.dispose();
});
await test('unknown read is truthful, preserves other slot, and only explicit retry reads again',async()=>{
  const f=await setup();await f.comparison.choose('B',takes[1].id);f.handle(()=>{throw Error('Sensitive raw error must not surface');});
  await f.comparison.choose('A',takes[0].id);assert.equal(f.comparison.state.status,'RETAINED_BYTES_UNAVAILABLE');
  assert.ok(f.comparison.state.slots.B.url);assert.equal(f.calls.length,4);f.owner.dispose();
});
await test('server authority denial clears both slots and projection without host atom change',async()=>{
  const f=await setup();await f.comparison.choose('B',takes[1].id);f.handle(()=>({error:'PRODUCTION_SCOPE_DENIED'}));
  await f.comparison.choose('A',takes[0].id);assert.equal(f.owner.state.current,null);assert.equal(f.comparison.state.slots.B,null);f.owner.dispose();
});
await test('repeat compare is inert, duplicate slots and unlinked take refused',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);f.owner.compare();assert.equal(f.comparison.closed,false);
  await f.comparison.choose('B',takes[0].id);await f.comparison.choose('B','unknown');assert.equal(f.calls.length,3);f.owner.dispose();
});
await test('late playback promise after disposal cannot revive or retain media',async()=>{
  const f=await setup(),gate=deferred();await f.comparison.choose('A',takes[0].id);f.comparison.activate('A');f.comparison.metadata();
  f.audio.play=async()=>{await gate.promise;f.audio.paused=false;};const work=f.comparison.play();f.owner.dispose();gate.resolve();await work;
  assert.equal(f.audio.paused,true);assert.equal(f.audio.src,'');assert.deepEqual(f.comparison.state.slots,{A:null,B:null});
});
for(const change of ['focusedSessionId','profile','connectionId','gateway'])await test(change+' loss during playback pauses and releases media',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);f.comparison.activate('A');f.comparison.metadata();await f.comparison.play();
  f.set(change,'changed');assert.equal(f.audio.paused,true);assert.equal(f.audio.src,'');assert.equal(f.comparison.state.slots.A,null);f.owner.dispose();
});
await test('same revision refresh discards cached source review metadata and bytes',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);f.owner.publish({current:structuredClone(current)});
  assert.equal(f.comparison.state.slots.A,null);assert.equal(f.owner.state.comparisonOpen,false);f.owner.dispose();
});
await test('single-take read closed during navigation cannot reappear or leave busy lock',async()=>{
  const f=await setup(),gate=deferred();f.owner.clear();f.handle(()=>gate.promise);const work=f.owner.load(takes[0]);await flush();
  f.owner.clear();gate.resolve(chunk(takes[0].id));await work;assert.equal(f.owner.state.url,null);assert.equal(f.owner.state.busy,false);f.owner.dispose();
});
await test('rejected Play promise leaves a deliberate retry, never automatic retry',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);f.comparison.activate('A');f.comparison.metadata();
  f.audio.play=async()=>{throw Error('Denied');};await f.comparison.play();assert.match(f.comparison.state.status,/Press Play to retry/);f.owner.dispose();
});
await test('decode failure discloses unavailable audio and removes playback source',async()=>{
  const f=await setup();await f.comparison.choose('A',takes[0].id);f.comparison.activate('A');f.comparison.metadata();f.comparison.mediaError();
  assert.match(f.comparison.state.status,/could not be decoded/);assert.equal(f.audio.src,'');assert.equal(f.audio.paused,true);f.owner.dispose();
});
console.log(JSON.stringify({checks:checks.length,passed:checks},null,2));
