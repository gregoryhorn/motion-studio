// Production integration contracts with the actual scoped transport, no host effects.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import test from 'node:test';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
const url=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const retained=url(fs.readFileSync('studio/native/frontend/retained-bytes.js','utf8'));
const transport=url(fs.readFileSync('studio/native/frontend/transport.js','utf8'));
const {ProductionController}=await import(url(fs.readFileSync('studio/native/frontend/production-controller.js','utf8')
  .replace("'./transport.js'",JSON.stringify(transport)).replace("'./retained-bytes.js'",JSON.stringify(retained))));
const {ProductionExportController}=await import(url(fs.readFileSync('studio/native/frontend/production-export-controller.js','utf8')
  .replace("'./retained-bytes.js'",JSON.stringify(retained))));
const id=letter=>letter.repeat(32),request=id('a'),take=id('b'),assetId=id('c'),production=id('d'),importId=id('e'),exportId=id('f');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function setup(kind='Image'){
  const f=fixture();f.route.primary=true;f.route.mode=process.env.TEST_ROUTE_MODE||'local';
  const calls=[],drafts=[];let draft='';
  let current={id:production,title:'Controlled project',revision:3,assets:[{id:assetId,kind,intent:'Controlled intent',position:1,
    selected_take:null,stale:false,takes:[],depends_on:[],references:[]}],references:[]};
  const savedRequest={request,revision:7,kind,direction:'Controlled direction'};
  let handle=async(op,payload)=>{
    if(op==='production.list')return {productions:[current],available:[]};
    if(op==='production.open')return {current,available:[]};
    if(op==='creation.list')return {creations:[savedRequest]};
    if(op==='production.media_import.intent')return {...savedRequest,method:'import'};
    if(op==='production.media_import.begin')return {id:importId,take};
    if(op==='production.media_import.chunk')return {id:importId,received:payload.offset+Buffer.from(payload.data,'base64').length,status:'Media receiving'};
    if(op==='production.media_import.commit')return {id:importId,take,status:'Ready for review',error:null};
    if(op==='production.media_import.cancel')return {id:importId,take,status:'Cancelled',error:null};
    if(op==='production.link_take'){
      const linked={id:take,request,origin:'user_import',source_request_revision:7,artifact:importId,review:'Not reviewed'};
      current={...current,revision:4,assets:[{...current.assets[0],takes:[linked]}]};return {current,available:[linked]};
    }
    throw Error('Unexpected operation');
  };
  f.host.request=async(method,payload)=>{
    assert.equal(payload.session_id,'s1');const op=method.replace('plugin.motion-studio.','');calls.push({op,payload});return handle(op,payload);
  };
  f.host.composer={getDraft:async session=>{assert.equal(session,'s1');return draft;},
    insertText:async(session,text,options)=>{drafts.push({session,text,options});return true;}};
  const owner=new ProductionController(f.host),baseHandler=handle;
  return {...f,owner,calls,drafts,savedRequest,get current(){return current;},handle:value=>{handle=value;},
    setDraft:value=>{draft=value;},defaultHandler:baseHandler};
}
const file=(size=400000,type='image/png')=>({size,type,name:'controlled-original.png',arrayBuffer:async()=>new Uint8Array(size).fill(42).buffer});
const identity=f=>({epoch:f.owner.epoch,production,asset:assetId});

test('imports exact matching request/revision, bounded chunks, null-error commit, links and refreshes without selecting',async()=>{
  const f=setup();await f.owner.open();await f.owner.loadImportRequests();
  assert.deepEqual(f.owner.state.importRequests,[f.savedRequest]);await f.owner.importTake(file(),f.savedRequest,identity(f));
  const begin=f.calls.find(call=>call.op.endsWith('media_import.begin')).payload;
  assert.equal(begin.revision,7);assert.equal(begin.request,request);assert.equal(begin.size,400000);
  assert.equal(begin.digest,hash(new Uint8Array(400000).fill(42)));assert.equal(begin.format,'png');
  const chunks=f.calls.filter(call=>call.op.endsWith('media_import.chunk'));
  assert.deepEqual(chunks.map(call=>call.payload.offset),[0,196608,393216]);
  assert.ok(chunks.every(call=>Buffer.from(call.payload.data,'base64').length<=196608));
  const link=f.calls.find(call=>call.op==='production.link_take').payload;
  assert.equal(link.asset,assetId);assert.equal(link.expected,3);assert.equal(link.request,request);assert.equal(link.take,take);
  assert.equal(f.owner.state.current.assets[0].selected_take,null);assert.equal(f.owner.state.selectedTake,take);
  assert.equal(f.owner.state.busy,false);assert.equal(f.owner.state.importing,false);assert.equal(f.owner.state.importProgress,100);
  assert.ok(!f.calls.some(call=>/select_take|start|prepare$/.test(call.op)));f.owner.dispose();
});
for(const [kind,type] of [['Sound effects','audio/wav'],['Music','audio/wav'],['Voice','audio/wav'],['Video','video/mp4']]){
  test(kind+' imports through the same matching-kind seam',async()=>{
    const f=setup(kind);await f.owner.open();await f.owner.importTake(file(20,type),f.savedRequest,identity(f));
    assert.equal(f.owner.state.current.assets[0].takes[0].id,take);f.owner.dispose();
  });
}
for(const scenario of ['size','type','kind','stale visual'])test('invalid import '+scenario+' never dispatches begin',async()=>{
  const f=setup();await f.owner.open();let input=file(),saved=f.savedRequest,scope=identity(f);
  if(scenario==='size')input.size=16777217;if(scenario==='type')input.type='text/plain';
  if(scenario==='kind')saved={...saved,kind:'Voice'};
  if(scenario==='stale visual')scope.epoch--;
  await f.owner.importTake(input,saved,scope);assert.equal(f.calls.filter(call=>call.op.includes('media_import')).length,0);f.owner.dispose();
});
test('import without a prior request creates a non-generating scoped intent',async()=>{
  const f=setup();await f.owner.open();await f.owner.importTake(file(20),null,identity(f));
  const intent=f.calls.find(call=>call.op==='production.media_import.intent').payload;
  assert.equal(intent.production,production);assert.equal(intent.expected,3);assert.equal(intent.asset,assetId);
  assert.match(intent.command,/^[a-f0-9]{32}$/);
  assert.equal(f.owner.state.current.assets[0].takes[0].id,take);
  assert.ok(!f.calls.some(call=>/select_take|start|prepare$/.test(call.op)));f.owner.dispose();
});
for(const stage of ['begin','chunk'])test('cancel during '+stage+' stops commit and link',async()=>{
  const f=setup();await f.owner.open();const gate=deferred(),prior=f.defaultHandler;
  f.handle(async(op,payload)=>op.endsWith('media_import.'+stage)?gate.promise:prior(op,payload));
  const work=f.owner.importTake(file(20),f.savedRequest,identity(f));await flush();
  await f.owner.cancelImport();gate.resolve(stage==='begin'?{id:importId,take}:{id:importId,received:20});await work;
  assert.ok(f.calls.some(call=>call.op.endsWith('media_import.cancel')));
  assert.ok(!f.calls.some(call=>/commit|link_take/.test(call.op)));f.owner.dispose();
});

test('scope change while hashing/reading file prevents any import dispatch',async()=>{
  const f=setup();await f.owner.open();const gate=deferred();const input=file();input.arrayBuffer=()=>gate.promise;
  const work=f.owner.importTake(input,f.savedRequest,identity(f));f.set('focusedSessionId','away');
  gate.resolve(new Uint8Array(400000).buffer);await work;assert.equal(f.calls.length,2);assert.equal(f.owner.state.current,null);f.owner.dispose();
});

test('Hermes request targets current chat with exact production/asset wording, never sends',async()=>{
  const f=setup();await f.owner.open();await f.owner.createWithHermes(f.current.assets[0],'Controlled direction',identity(f));
  assert.deepEqual(f.drafts,[{session:'s1',text:'Motion Studio - create Image for production "Controlled project", asset 2 "Controlled intent": Controlled direction',options:{mode:'block'}}]);
  assert.equal(f.calls.length,2);f.owner.dispose();
});
test('existing Hermes draft is preserved until explicit append',async()=>{
  const f=setup();await f.owner.open();f.setDraft('Existing controlled draft');
  await f.owner.createWithHermes(f.current.assets[0],'Direction',identity(f));assert.equal(f.drafts.length,0);
  assert.equal(f.owner.state.draftAsset,assetId);
  await f.owner.createWithHermes(f.current.assets[0],'Direction',identity(f),true);assert.equal(f.drafts.length,1);f.owner.dispose();
});
test('Hermes composer scope change before insert never writes the draft',async()=>{
  const f=setup();await f.owner.open();const gate=deferred();f.host.composer.getDraft=()=>gate.promise;
  const work=f.owner.createWithHermes(f.current.assets[0],'Direction',identity(f));f.set('focusedSessionId','away');gate.resolve('');await work;
  assert.equal(f.drafts.length,0);f.owner.dispose();
});

test('export hooks verify chunks and descriptor, expose a revocable download, then close the server handle',async()=>{
  const f=setup();await f.owner.open();f.owner.state.current.assets[0].selected_take=take;
  const bytes=Buffer.from('Controlled ZIP original bytes');const descriptor={take:exportId,filename:'motion-studio-selected.zip',mime:'application/zip',size:bytes.length,sha256:hash(bytes)};
  f.handle(async(op,payload)=>{
    if(op==='production.export.prepare'){assert.deepEqual(payload,{production,expected:3,assets:[assetId],mode:'zip',session_id:'s1'});return descriptor;}
    if(op==='production.export.descriptor')return descriptor;
    if(op==='production.export.chunk')return {take:exportId,offset:0,total:bytes.length,bytes:bytes.toString('base64'),sha256:hash(bytes),chunk_sha256:hash(bytes)};
    if(op==='production.export.close')return {take:exportId,closed:true};throw Error('Unexpected operation');
  });
  const exporter=new ProductionExportController(f.owner,f.owner.exportHooks());await exporter.save([assetId]);
  assert.equal(exporter.state.phase,'ready');assert.equal(f.owner.state.download.filename,descriptor.filename);
  const download=f.owner.state.download.url;assert.deepEqual(Buffer.from(await (await fetch(download)).arrayBuffer()),bytes);
  assert.equal(f.calls.at(-1).op,'production.export.close');f.owner.chooseAsset(assetId);
  assert.equal(f.owner.state.download,null);await assert.rejects(fetch(download));exporter.dispose();f.owner.dispose();
});
test('unknown RPC errors never expose codes or raw content',async()=>{
  const f=setup();await f.owner.open();f.handle(()=>({error:'PRIVATE_ERROR_SENTINEL'}));await f.owner.loadImportRequests();
  assert.ok(!f.owner.state.status.includes('SENTINEL'));f.owner.dispose();
});

function linkedTake(){return {id:take,request,artifact:importId,origin:'user_import',source_request_revision:7,review:'Not reviewed'};}
function linkedDescriptor(){return {identity:{production,asset:assetId,request,requestRevision:7,take,artifact:importId},
  kind:'Image',format:'png',mime:'image/png',byteLength:20,sha256:hash(new Uint8Array(20).fill(42)),
  width:1,height:1,duration:null,reviewStatus:'Not reviewed',qualityRole:'Imported original'};}
test('review describes linked exact takes and clears on visual scope change',async()=>{
  const f=setup();await f.owner.open();f.current.assets[0].takes=[linkedTake()];
  f.handle(async(op,payload)=>{assert.equal(op,'production.describe');assert.deepEqual(payload,{production,asset:assetId,request,take,session_id:'s1'});return linkedDescriptor();});
  await f.owner.prepareMediaReview();assert.deepEqual(f.owner.state.mediaReview.descriptors,[linkedDescriptor()]);
  assert.equal(f.owner.state.mediaReview.valid(),true);f.owner.chooseTake(take);assert.equal(f.owner.state.mediaReview,null);f.owner.dispose();
});
for(const field of ['production','asset','request','requestRevision','take','artifact'])test('review rejects descriptor '+field+' mismatch',async()=>{
  const f=setup();await f.owner.open();f.current.assets[0].takes=[linkedTake()];
  f.handle(async()=>{const value=linkedDescriptor();value.identity[field]=field==='requestRevision'?99:'wrong';return value;});
  await f.owner.prepareMediaReview();assert.equal(f.owner.state.mediaReview,null);assert.equal(f.owner.state.busy,false);f.owner.dispose();
});
test('closing review while describe is pending releases busy and rejects late descriptors',async()=>{
  const f=setup();await f.owner.open();f.current.assets[0].takes=[linkedTake()];const gate=deferred();f.handle(()=>gate.promise);
  const work=f.owner.prepareMediaReview();await flush();f.owner.clear();assert.equal(f.owner.state.busy,false);
  gate.resolve(linkedDescriptor());await work;assert.equal(f.owner.state.mediaReview,null);f.owner.dispose();
});
test('failed import link retains its friendly failure and never claims linked success',async()=>{
  const f=setup();await f.owner.open();const prior=f.defaultHandler;
  f.handle((op,payload)=>op==='production.link_take'?{error:'PRODUCTION_STALE_REVISION'}:prior(op,payload));
  await f.owner.importTake(file(20),f.savedRequest,identity(f));
  assert.match(f.owner.state.status,/project changed/);assert.equal(f.owner.state.pending,false);
  assert.equal(f.owner.state.current.assets[0].takes.length,0);f.owner.dispose();
});
test('cancelled commit reply cannot link a nonexistent take',async()=>{
  const f=setup();await f.owner.open();const prior=f.defaultHandler;
  f.handle((op,payload)=>op.endsWith('media_import.commit')?{id:importId,take,status:'Cancelled',error:null}:prior(op,payload));
  await f.owner.importTake(file(20),f.savedRequest,identity(f));
  assert.equal(f.calls.some(call=>call.op==='production.link_take'),false);assert.match(f.owner.state.status,/could not be completed/);f.owner.dispose();
});
test('export scope change during prepare still closes its handle when same-scope transport remains available',async()=>{
  const f=setup();await f.owner.open();f.current.assets[0].selected_take=take;const gate=deferred();
  f.handle((op)=>op==='production.export.prepare'?gate.promise:op==='production.export.close'?{closed:true}:Promise.reject(Error('Unexpected operation')));
  const exporter=new ProductionExportController(f.owner,f.owner.exportHooks());const work=exporter.save([assetId]);
  await flush();exporter.cancel();gate.resolve({take:exportId});await work;
  assert.equal(f.calls.at(-1).op,'production.export.close');assert.equal(f.owner.state.download,null);exporter.dispose();f.owner.dispose();
});

// Minimal React facade exercises actual component callbacks and scoped readers.
const react=url(`export const createElement=(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity)});
export const useRef=value=>({current:value}),useMemo=fn=>fn(),useEffect=()=>{},useState=value=>[value,()=>{}];`);
const sdk=url("export const Button='button';");
const media=url("export const MediaReview='media-review';");
const comparison=url("export const ProductionComparison='comparison';");
const mediaController=url(fs.readFileSync('studio/native/frontend/media-review-controller.js','utf8')
  .replace("'./retained-bytes.js'",JSON.stringify(retained)));
const {ProductionImport,ProductionMediaReview}=await import(url(fs.readFileSync('studio/native/frontend/production-review.js','utf8')
  .replace("'react'",JSON.stringify(react)).replace("'@hermes/plugin-sdk'",JSON.stringify(sdk))
  .replace("'./media-review.js'",JSON.stringify(media)).replace("'./media-review-controller.js'",JSON.stringify(mediaController))
  .replace("'./production-comparison.js'",JSON.stringify(comparison))
  .replace("'./methods-ui.js'",JSON.stringify(url(fs.readFileSync('studio/native/frontend/methods-ui.js','utf8').replace("'react'",JSON.stringify(react)))))));
const nodes=tree=>!tree||typeof tree!=='object'?[]:[tree,...tree.children.flatMap(nodes)];
test('mounted import enables import-first and exposes native file accept and exact scoped callback',async()=>{
  const calls=[],asset={id:assetId,kind:'Image'},scope={epoch:1,production,asset:assetId};
  const controller={importTake:(...args)=>calls.push(args)};
  const empty=ProductionImport({controller,state:{},asset,identity:scope});
  assert.ok(!nodes(empty).find(node=>node.type==='button'&&node.children.includes('Import a take')).props.disabled);
  const view=ProductionImport({controller,state:{importRequests:[{request,revision:7,kind:'Image'}]},asset,identity:scope});
  const input=nodes(view).find(node=>node.type==='input');assert.equal(input.props.accept,'image/png,image/jpeg,audio/wav,video/mp4');
  const original=file(20),target={files:[original],value:'nonprivate fixture'};input.props.onChange({target});
  assert.equal(target.value,'');assert.deepEqual(calls,[[original,{request,revision:7,kind:'Image'},scope]]);
});
for(const imported of [true,false])test('mounted '+(imported?'imported':'legacy')+' review uses strict scoped byte-reader payload and selects current take',async()=>{
  const descriptor=linkedDescriptor(),bytes=new Uint8Array(20).fill(42),calls=[];
  let valid=true;
  const review={scope:'controlled-review-scope',descriptors:[descriptor],valid:()=>valid,
    client:{request:async(op,payload)=>{calls.push({op,payload});return {take,offset:0,total:20,
      bytes:Buffer.from(bytes).toString('base64'),sha256:hash(bytes),chunk_sha256:hash(bytes),mime:'image/png'};}}};
  const controller={},asset={takes:[{id:take,origin:imported?'user_import':'test_fixture'}]};
  const view=ProductionMediaReview({review,controller,asset,selectedTake:take});
  assert.equal(view.type,'media-review');const chosen=[];
  view.props.onController({choose:(...args)=>chosen.push(args),dispose:()=>{}});
  assert.deepEqual(chosen,[['A',descriptor]]);assert.equal(typeof controller.reviewCleanup,'function');
  const result=await view.props.readBytes({scope:review.scope,descriptor,signal:new AbortController().signal});
  assert.deepEqual(result.bytes,bytes);
  assert.deepEqual(calls,[{op:imported?'media_import.read_chunk':'chunk',payload:imported?{take,offset:0}:{production,asset:assetId,request,take,offset:0}}]);
  valid=false;await assert.rejects(view.props.readBytes({scope:review.scope,descriptor,signal:new AbortController().signal}));assert.equal(calls.length,1);
});
