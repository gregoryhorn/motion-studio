// Focused non-private controller checks; no host, model, media store or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
const sourceURL=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const retained=sourceURL(fs.readFileSync('studio/native/frontend/retained-bytes.js','utf8'));
const module=await import(sourceURL(fs.readFileSync('studio/native/frontend/media-review-controller.js','utf8')
  .replace("'./retained-bytes.js'",JSON.stringify(retained))));
const {MediaReviewController,normalizeMediaDescriptor,descriptorFromProductionTake,descriptorFromImportedTake,
  createRetainedReviewReader,createImportedReviewReader,createPlaybackGroup}=module;
const bytes=Uint8Array.from([1,2,3,4]),sha=crypto.createHash('sha256').update(bytes).digest('hex');
const descriptor=(take='take-a',kind='Voice',mime='audio/wav')=>({identity:{production:'production-fixture',asset:'asset-fixture',
  request:'request-fixture',requestRevision:1,take,artifact:'artifact-'+take},kind,mime,byteLength:4,
  width:null,height:null,duration:2,reviewStatus:'Not reviewed',qualityRole:'Original',sha256:sha});
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {resolve,promise};};
class Player{
  constructor(){Object.assign(this,{src:'',currentTime:0,duration:2,paused:true,volume:1,plays:0});}
  pause(){this.paused=true;}
  load(){}
  removeAttribute(){this.src='';}
  async play(){this.plays++;this.paused=false;}
}
function setup(options={}){
  const urls=[],revoked=[],calls=[],states=[];
  const readBytes=async input=>{calls.push(input);return {scope:input.scope,identity:input.identity,bytes};};
  const controller=new MediaReviewController({scope:'fixture-epoch-1',readBytes,onChange:state=>states.push(state),
    urlAPI:{createObjectURL:blob=>{const url='blob:fixture-'+urls.length;urls.push({url,blob});return url;},
      revokeObjectURL:url=>revoked.push(url)},...options});
  return {controller,urls,revoked,calls,states};
}
async function loaded(options={}){
  const f=setup(options),player=new Player();f.controller.attach(player);f.controller.choose('A',descriptor());
  await f.controller.load('A');f.controller.activate('A');f.controller.metadata();return {...f,player};
}

test('normalization captures immutable opaque identity and keeps unknown measurements unknown',()=>{
  const input=descriptor(),normalized=normalizeMediaDescriptor(input);input.identity.take='changed';
  assert.equal(normalized.identity.take,'take-a');assert.equal(normalized.width,null);
  assert.ok(Object.isFrozen(normalized)&&Object.isFrozen(normalized.identity));
  assert.throws(()=>normalizeMediaDescriptor({...descriptor(),byteLength:0}));
  assert.throws(()=>normalizeMediaDescriptor({...descriptor(),identity:{...descriptor().identity,artifact:''}}));
});
test('existing Production shape maps without MIME or filename inference',()=>{
  const take={id:'t',request:'r',source_request_revision:7,artifact:'a',size:4,digest:sha,review:'Not reviewed',facts:{duration:3}};
  const result=descriptorFromProductionTake({production:'p',asset:{id:'asset',kind:'Music'},take,mime:'audio/wav'});
  assert.equal(result.identity.requestRevision,7);assert.equal(result.kind,'Music');assert.equal(result.duration,3);
  assert.throws(()=>descriptorFromProductionTake({production:'p',asset:{id:'asset',kind:'Music'},take}));
});
for(const kind of ['Voice','Music','Sound effects','Image','Video'])test(kind+' loads exact captured original, never autoplays',async()=>{
  const f=setup(),mime=kind==='Image'?'image/png':kind==='Video'?'video/webm':'audio/wav';
  const input=descriptor('take-'+kind,kind,mime);f.controller.choose('A',input);input.identity.take='mutated';
  await f.controller.load('A');assert.equal(f.calls.length,1);assert.equal(f.calls[0].identity.take,'take-'+kind);
  assert.equal(f.controller.state.active,null);assert.equal(f.urls.length,1);assert.equal(f.urls[0].blob.type,mime);
  assert.deepEqual(new Uint8Array(await f.urls[0].blob.arrayBuffer()),bytes);f.controller.dispose();assert.equal(f.revoked.length,1);
});
test('load coalesces and duplicate identity cannot occupy both slots',async()=>{
  const gate=deferred(),f=setup({readBytes:()=>gate.promise});f.controller.choose('A',descriptor());
  const work=f.controller.load('A');await f.controller.load('A');f.controller.choose('B',descriptor());
  assert.equal(f.controller.state.slots.B,null);gate.resolve({scope:'fixture-epoch-1',identity:descriptor().identity,bytes});await work;
  assert.equal(f.urls.length,1);await f.controller.load('A');assert.equal(f.urls.length,1);f.controller.dispose();
});
for(const field of ['production','asset','request','requestRevision','take','artifact','scope','size','digest'])
  test('rejects mismatched '+field+' without creating a Blob URL',async()=>{
    const input=descriptor(),reply={scope:'fixture-epoch-1',identity:{...input.identity},bytes};
    if(field==='scope')reply.scope='other';else if(field==='size')reply.bytes=bytes.slice(1);
    else if(field==='digest')reply.bytes=new Uint8Array(4);else reply.identity[field]=field==='requestRevision'?2:'wrong';
    const f=setup({readBytes:async()=>reply});f.controller.choose('A',input);await f.controller.load('A');
    assert.equal(f.urls.length,0);assert.match(f.controller.state.slots.A.error,/integrity/);f.controller.dispose();
  });
for(const action of ['replace','clear','dispose','scope-loss'])test(action+' while reading aborts and rejects stale completion',async()=>{
  const gate=deferred();let current=true,input;
  const f=setup({isScopeCurrent:()=>current,readBytes:value=>{input=value;return gate.promise;}});
  f.controller.choose('A',descriptor());const work=f.controller.load('A');
  if(action==='replace')f.controller.choose('A',descriptor('new-take'));
  if(action==='clear')f.controller.choose('A',null);
  if(action==='dispose')f.controller.dispose();
  if(action==='scope-loss'){current=false;f.controller.current();current=true;}
  assert.equal(input.signal.aborted,true);
  gate.resolve({scope:input.scope,identity:input.identity,bytes});await work;assert.equal(f.urls.length,0);
  assert.notEqual(f.controller.state.slots.A?.descriptor.identity.take,'take-a');f.controller.dispose();
});
test('scope refusal before dispatch clears descriptors and pauses/revokes both originals',async()=>{
  let current=true;const f=await loaded({isScopeCurrent:()=>current});
  f.controller.choose('B',descriptor('take-b'));await f.controller.load('B');await f.controller.play();
  current=false;f.controller.load('B');assert.equal(f.player.paused,true);assert.equal(f.player.src,'');
  assert.equal(f.controller.state.closed,true);assert.deepEqual(f.controller.state.slots,{A:null,B:null});assert.equal(f.revoked.length,2);
  assert.equal(f.calls.length,2);
});
test('switching pauses and preserves original absolute position and shared gain; deliberate replay only',async()=>{
  const f=await loaded();f.controller.choose('B',descriptor('take-b'));await f.controller.load('B');
  f.controller.seek('0.4');f.controller.volume(0.37);await f.controller.play();assert.equal(f.player.paused,false);
  f.controller.activate('B');f.controller.metadata();assert.equal(f.player.paused,true);assert.equal(f.player.currentTime,0.4);
  assert.equal(f.player.volume,0.37);assert.equal(f.player.plays,1);assert.equal(f.player.loop,false);assert.equal(f.player.autoplay,false);
  f.controller.dispose();assert.equal(f.player.src,'');assert.equal(f.revoked.length,2);
});
test('invalid/out-of-range position never clamps or plays; end never starts another original',async()=>{
  const f=await loaded();
  for(const value of ['',-1,'NaN','Infinity',2,3]){f.controller.seek(value);await f.controller.play();assert.equal(f.player.plays,0);}
  f.controller.seek('0.25');await f.controller.play();f.controller.ended();assert.equal(f.player.paused,true);
  assert.match(f.controller.state.status,/Other take did not start/);f.controller.dispose();
});
test('one active player across controller instances using a shared monitoring group',async()=>{
  const playbackGroup=createPlaybackGroup(),a=await loaded({playbackGroup}),b=await loaded({playbackGroup});
  await a.controller.play();await b.controller.play();assert.equal(a.player.paused,true);assert.equal(b.player.paused,false);
  a.controller.dispose();b.controller.dispose();
});
for(const action of ['dispose','switch','pause'])test('late play promise after '+action+' cannot revive playback',async()=>{
  const f=await loaded(),gate=deferred();f.player.play=async()=>{await gate.promise;f.player.paused=false;};
  const work=f.controller.play();
  if(action==='dispose')f.controller.dispose();
  else if(action==='switch'){f.controller.choose('B',descriptor('b'));await f.controller.load('B');f.controller.activate('B');}
  else f.controller.pause();gate.resolve();await work;assert.equal(f.player.paused,true);f.controller.dispose();
});
test('unsupported MIME performs no read, and decoder error revokes exact URL without changing originals',async()=>{
  const f=setup();f.controller.choose('A',descriptor('svg','Image','image/svg+xml'));await f.controller.load('A');
  assert.equal(f.calls.length,0);assert.match(f.controller.state.slots.A.error,/Unsupported/);
  f.controller.choose('A',descriptor());await f.controller.load('A');const url=f.controller.state.slots.A.url;
  f.controller.mediaError('A','blob:stale');assert.equal(f.revoked.length,0);f.controller.mediaError('A',url);
  assert.deepEqual(f.revoked,[url]);assert.equal(f.controller.state.slots.A.url,null);f.controller.dispose();
});
test('sanitized read/playback failures preserve alternative, approval and explicit retry',async()=>{
  let reads=0;const f=setup({readBytes:async input=>{reads++;if(reads===1)throw Error('PRIVATE raw filename');
    return {scope:input.scope,identity:input.identity,bytes};}});
  f.controller.choose('A',descriptor());await f.controller.load('A');assert.doesNotMatch(JSON.stringify(f.states),/PRIVATE/);
  assert.equal(reads,1);await f.controller.load('A');assert.equal(reads,2);assert.equal(f.controller.state.slots.A.descriptor.reviewStatus,'Not reviewed');
  const player=new Player();f.controller.attach(player);f.controller.activate('A');f.controller.metadata();
  player.play=()=>Promise.reject(Error('PRIVATE'));await f.controller.play();assert.equal(player.paused,true);
  assert.doesNotMatch(f.controller.state.status,/PRIVATE/);f.controller.dispose();
});
test('existing chunk adapter pins requested take, original digest/size and external scope validity',async()=>{
  let allowed=true,calls=0;
  const reader=createRetainedReviewReader({client:{request:async(_operation,payload)=>{calls++;assert.equal(payload.take,'take-a');
    return {take:payload.take,offset:0,total:4,bytes:Buffer.from(bytes).toString('base64'),sha256:sha,chunk_sha256:sha};}},
    operation:'production.chunk',valid:()=>allowed});
  const input={scope:'fixture',descriptor:normalizeMediaDescriptor(descriptor()),signal:new AbortController().signal};
  const result=await reader(input);assert.deepEqual(result.bytes,bytes);assert.equal(result.identity.take,'take-a');
  allowed=false;await assert.rejects(reader(input),/SCOPE_CHANGED/);assert.equal(calls,1);
});

test('import descriptor maps the existing Store take without invented Production identity',()=>{
  const result=descriptorFromImportedTake({kind:'Image',take:{id:'t',artifact:'a',request:'r',revision:2,
    size:4,digest:sha,review:'Not reviewed',facts:{mime:'image/png',width:1200,height:800}}});
  assert.deepEqual(result.identity,{production:null,asset:null,request:'r',requestRevision:2,take:'t',artifact:'a'});
  assert.equal(result.width,1200);assert.equal(result.mime,'image/png');assert.equal(result.duration,null);
});

test('canonical media_import MediaDescriptor v1 is accepted directly with its format intact',()=>{
  const canonical={...descriptor('take-image','Image','image/png'),format:'png',
    identity:{...descriptor().identity,production:null,asset:null},width:1200,height:800,duration:null};
  assert.deepEqual(normalizeMediaDescriptor(canonical),canonical);
  assert.throws(()=>normalizeMediaDescriptor({...canonical,mime:'image/jpeg'}));
  assert.throws(()=>normalizeMediaDescriptor({...canonical,kind:'Voice'}));
  assert.throws(()=>normalizeMediaDescriptor({...canonical,byteLength:16777217}));
});

test('import reader sends strict ReadChunk shape and verifies MIME, original bytes and scope',async()=>{
  const input={scope:'fixture',descriptor:normalizeMediaDescriptor({...descriptor(),
    identity:{...descriptor().identity,production:null,asset:null}}),signal:new AbortController().signal};
  let allowed=true,calls=0,mime='audio/wav';
  const reader=createImportedReviewReader({operation:'media.read_chunk',valid:()=>allowed,
    client:{request:async(operation,payload)=>{
      calls++;assert.equal(operation,'media.read_chunk');assert.deepEqual(payload,{take:'take-a',offset:0});
      return {take:payload.take,offset:0,total:4,bytes:Buffer.from(bytes).toString('base64'),
        sha256:sha,chunk_sha256:sha,mime};
    }}});
  assert.deepEqual((await reader(input)).bytes,bytes);
  mime='image/png';await assert.rejects(reader(input),/ORIGINAL_UNAVAILABLE/);
  allowed=false;await assert.rejects(reader(input),/SCOPE_CHANGED/);assert.equal(calls,2);
});

test('import reader stops between chunks when its epoch changes',async()=>{
  const data=new Uint8Array(49153),digest=crypto.createHash('sha256').update(data).digest('hex');
  let allowed=true,calls=0;
  const reader=createImportedReviewReader({operation:'read_chunk',valid:()=>allowed,
    client:{request:async()=>{calls++;allowed=false;const part=data.slice(0,49152);
      return {take:'take-a',offset:0,total:data.length,bytes:Buffer.from(part).toString('base64'),
        sha256:digest,chunk_sha256:crypto.createHash('sha256').update(part).digest('hex'),mime:'audio/wav'};}}});
  await assert.rejects(reader({scope:'fixture',descriptor:normalizeMediaDescriptor({...descriptor(),
    byteLength:data.length,sha256:digest}),signal:new AbortController().signal}),/SCOPE_CHANGED/);
  assert.equal(calls,1);
});

test('changing the other comparison slot also pauses the active original',async()=>{
  const f=await loaded();await f.controller.play();assert.equal(f.player.paused,false);
  f.controller.choose('B',descriptor('take-b'));assert.equal(f.player.paused,true);
  assert.equal(f.controller.state.active,'A');f.controller.dispose();
});
