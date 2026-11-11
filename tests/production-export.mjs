// Focused no-network export boundary tests using the shipped retained-byte verifier.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
const moduleUrl=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const retained=moduleUrl(fs.readFileSync('studio/native/frontend/retained-bytes.js','utf8'));
const {ProductionExportController}=await import(moduleUrl(fs.readFileSync('studio/native/frontend/production-export-controller.js','utf8')
  .replace("'./retained-bytes.js'",JSON.stringify(retained))));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const production='a'.repeat(32),asset='b'.repeat(32),take='c'.repeat(32),artifact='d'.repeat(32);
const payload=Buffer.from('controlled nonprivate retained export bytes');
const checks=[];
async function test(name,body){await body();checks.push(name);}
function fixture(mode='zip',format='wav'){
  const calls=[],writes=[];
  const owner={epoch:1,disposed:false,client:{current:()=>true},state:{busy:false,selectedAsset:asset,selectedTake:take,
    current:{id:production,revision:7,assets:[{id:asset,selected_take:take,stale:false}]}},
    valid(epoch,client){return !this.disposed&&this.epoch===epoch&&client===this.client&&client.current();}};
  const descriptor={take:artifact,filename:mode==='zip'?'motion-studio-selected.zip':'01-image-take-01.'+format,
    mime:mode==='zip'?'application/zip':({wav:'audio/wav',png:'image/png',jpeg:'image/jpeg',mp4:'video/mp4'})[format],
    size:payload.length,sha256:hash(payload)};
  const handle={descriptor,operation:'export_chunk',identity:()=>({take:artifact}),
    client:{request:async(operation,identity)=>{calls.push(operation);assert.equal(identity.take,artifact);
      return {take:artifact,offset:0,total:payload.length,bytes:payload.toString('base64'),
        sha256:hash(payload),chunk_sha256:hash(payload)};}},
    reauthorize:async()=>{calls.push('reauthorize');},release:async()=>{calls.push('release');}};
  const destination={write:async(bytes,valid)=>{assert.ok(valid());calls.push('write');writes.push(Buffer.from(bytes));return {status:'saved'};},
    close:async()=>{calls.push('close');}};
  const hooks={prepare:async(spec,valid)=>{calls.push('prepare');assert.ok(valid());
      assert.deepEqual(spec,{production,expected:7,assets:[asset],mode});return handle;},
    chooseDestination:async(spec,valid)=>{calls.push('choose');assert.ok(valid());
      assert.deepEqual(spec,{filename:descriptor.filename,mime:descriptor.mime,size:descriptor.size});return destination;}};
  const controller=new ProductionExportController(owner,hooks);
  return {owner,descriptor,handle,destination,hooks,controller,calls,writes};
}
await test('exact verified ZIP delivered once through explicit host Save File hooks; selection untouched',async()=>{
  const f=fixture(),before=structuredClone(f.owner.state);await f.controller.save([asset]);
  assert.deepEqual(f.calls,['prepare','export_chunk','choose','reauthorize','write','close','release']);
  assert.deepEqual(f.writes,[payload]);assert.deepEqual(f.owner.state,before);assert.equal(f.controller.state.phase,'saved');
  assert.match(f.controller.state.status,/remains unverified/);
});
await test('single-file MIME and exact name passed to host without conversion',async()=>{
  const f=fixture('file');await f.controller.save([asset],'file');assert.deepEqual(f.writes,[payload]);assert.equal(f.controller.state.phase,'saved');
});
for(const format of ['png','jpeg','mp4'])await test(format+' single-file original MIME and extension accepted',async()=>{
  const f=fixture('file',format);await f.controller.save([asset],'file');
  assert.deepEqual(f.writes,[payload]);assert.equal(f.controller.state.phase,'saved');
});
for(const change of ['asset','take','extension','mime','path'])await test('rejects single-file '+change+' mismatch before destination',async()=>{
  const f=fixture('file','png');
  if(change==='asset')f.descriptor.filename='x1-image-take-01.png';
  if(change==='take')f.descriptor.filename='01-image-take-xx.png';
  if(change==='extension')f.descriptor.filename='01-image-take-01.jpeg';
  if(change==='mime')f.descriptor.mime='image/jpeg';
  if(change==='path')f.descriptor.filename='../'+f.descriptor.filename;
  await f.controller.save([asset],'file');assert.equal(f.calls.includes('choose'),false);assert.deepEqual(f.writes,[]);
});
await test('host cancel never dispatches write; release always runs',async()=>{
  const f=fixture();f.hooks.chooseDestination=async()=>null;await f.controller.save([asset]);
  assert.deepEqual(f.writes,[]);assert.equal(f.controller.state.phase,'cancelled');assert.equal(f.calls.at(-1),'release');
});
for(const stage of ['prepare','read','choose','reauthorize'])for(const change of ['cancel','dispose','scope','revision','selection','pointer','stale','away-and-back']){
  await test(change+' while awaiting '+stage+' prevents further dispatch',async()=>{
    const f=fixture(),gate=deferred(),entered=deferred();
    if(stage==='prepare')f.hooks.prepare=async()=>{entered.resolve();return gate.promise;};
    if(stage==='read')f.handle.client.request=async()=>{entered.resolve();return gate.promise;};
    if(stage==='choose')f.hooks.chooseDestination=async()=>{entered.resolve();return gate.promise;};
    if(stage==='reauthorize')f.handle.reauthorize=async()=>{entered.resolve();return gate.promise;};
    const work=f.controller.save([asset]);await entered.promise;
    if(change==='cancel')f.controller.cancel();
    if(change==='dispose')f.controller.dispose();
    if(change==='scope')f.owner.epoch++;
    if(change==='revision')f.owner.state.current.revision++;
    if(change==='selection')f.owner.state.selectedTake='other';
    if(change==='pointer')f.owner.state.current.assets[0].selected_take='other';
    if(change==='stale')f.owner.state.current.assets[0].stale=true;
    if(change==='away-and-back'){f.owner.epoch+=2;f.owner.state.selectedTake=take;}
    gate.resolve(stage==='prepare'?f.handle:stage==='choose'?f.destination:stage==='read'?
      {take:artifact,offset:0,total:payload.length,bytes:payload.toString('base64'),sha256:hash(payload),chunk_sha256:hash(payload)}:undefined);
    await work;assert.deepEqual(f.writes,[]);assert.equal(f.calls.at(-1),'release');
    assert.equal(f.calls.includes('write'),false);
  });
}
await test('repeated clicks during pending preparation do not create duplicate operations',async()=>{
  const f=fixture(),gate=deferred();let prepares=0;f.hooks.prepare=async()=>{prepares++;return gate.promise;};
  const work=f.controller.save([asset]);await f.controller.save([asset]);gate.resolve(f.handle);await work;
  assert.equal(prepares,1);assert.equal(f.writes.length,1);
});
await test('cancellation waits for handle cleanup before accepting a new export',async()=>{
  const f=fixture(),gate=deferred(),entered=deferred();let prepares=0;
  f.hooks.prepare=async()=>{prepares++;entered.resolve();return gate.promise;};
  const work=f.controller.save([asset]);await entered.promise;f.controller.cancel();
  await f.controller.save([asset]);assert.equal(prepares,1);assert.ok(f.controller.state.busy);
  gate.resolve(f.handle);await work;assert.equal(f.controller.state.busy,false);assert.equal(f.calls.at(-1),'release');
  await f.controller.save([asset]);assert.equal(prepares,2);assert.deepEqual(f.writes,[payload]);
});
await test('descriptor is pinned before awaiting retained reads',async()=>{
  const f=fixture(),request=f.handle.client.request;
  f.hooks.chooseDestination=async spec=>{assert.equal(spec.filename,'motion-studio-selected.zip');return f.destination;};
  f.handle.client.request=async(...args)=>{f.descriptor.filename='/PRIVATE_PATH_SENTINEL';return request(...args);};
  await f.controller.save([asset]);assert.deepEqual(f.writes,[payload]);assert.equal(f.controller.state.phase,'saved');
});
for(const field of ['sha256','size','mime','filename','take'])await test('rejects mismatched descriptor '+field+' before save',async()=>{
  const f=fixture();f.descriptor[field]=({sha256:'0'.repeat(64),size:payload.length+1,mime:'text/plain',filename:'/private/output.zip',take:'wrong'})[field];
  await f.controller.save([asset]);assert.deepEqual(f.writes,[]);assert.equal(f.calls.includes('choose'),false);assert.equal(f.controller.state.phase,'blocked');
});
await test('chunk corruption is rejected by shared byte verifier',async()=>{
  const f=fixture(),request=f.handle.client.request;f.handle.client.request=async(...args)=>({...await request(...args),chunk_sha256:'0'.repeat(64)});
  await f.controller.save([asset]);assert.deepEqual(f.writes,[]);assert.equal(f.controller.state.status,'The original bytes could not be verified. Reopen selected outputs.');
});
await test('scope denial during final server reauthorization blocks destination write',async()=>{
  const f=fixture();f.handle.reauthorize=async()=>{throw {code:'EXPORT_SCOPE_CHANGED'};};await f.controller.save([asset]);
  assert.deepEqual(f.writes,[]);assert.equal(f.controller.state.status,'The selected chat changed. Reopen the project before exporting.');
});
await test('unknown host errors/paths/credentials are never exposed or automatically retried',async()=>{
  const f=fixture();f.destination.write=async()=>{throw Error('PRIVATE_CREDENTIAL_PATH_SENTINEL');};await f.controller.save([asset]);
  assert.equal(f.controller.state.phase,'unknown');assert.ok(!JSON.stringify(f.controller.state).includes('SENTINEL'));
  assert.equal(f.calls.filter(value=>value==='prepare').length,1);
});
await test('scope drift during dispatched write never claims delivery verified or undo',async()=>{
  const f=fixture();f.destination.write=async()=>{f.owner.epoch++;return {status:'saved'};};await f.controller.save([asset]);
  assert.notEqual(f.controller.state.phase,'saved');assert.match(f.controller.state.status,/changed|unverified/);
});
await test('explicit host unknown receipt remains unknown, not saved',async()=>{
  const f=fixture();f.destination.write=async()=>({status:'unknown'});await f.controller.save([asset]);
  assert.equal(f.controller.state.phase,'unknown');assert.match(f.controller.state.status,/no automatic retry/);
});
await test('missing host Save File support is truthful and has zero effects',async()=>{
  const f=fixture();f.controller.hooks={};await f.controller.save([asset]);assert.equal(f.controller.state.phase,'unsupported');assert.deepEqual(f.calls,[]);
});
for(const choice of ['missing','stale','empty','duplicate'])await test(choice+' selection rejected without backend or file effect',async()=>{
  const f=fixture();let ids=[asset];if(choice==='missing')f.owner.state.current.assets[0].selected_take=null;
  if(choice==='stale')f.owner.state.current.assets[0].stale=true;if(choice==='empty')ids=[];if(choice==='duplicate')ids=[asset,asset];
  await f.controller.save(ids);assert.deepEqual(f.calls,[]);assert.deepEqual(f.writes,[]);
});
console.log(JSON.stringify({checks:checks.length,passed:checks},null,2));
