// Offline regression: actual scoped transport/controller and component callbacks.
// No producer, paid endpoint, native host or browser qualification is claimed.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
const url=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const source=name=>fs.readFileSync('studio/native/frontend/'+name+'.js','utf8');
const retained=url(source('retained-bytes')),transport=url(source('transport'));
const {ProductionController}=await import(url(source('production-controller').replace("'./transport.js'",JSON.stringify(transport))
  .replace("'./retained-bytes.js'",JSON.stringify(retained))));
const react=url(`export const createElement=(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity)});
export const useRef=value=>({current:value}),useMemo=fn=>fn(),useEffect=()=>{},useState=value=>[value,()=>{}];`);
const methods=url(source('methods-ui').replace("'react'",JSON.stringify(react)));
const reviewSource=source('production-review').replace("'react'",JSON.stringify(react))
  .replace("'@hermes/plugin-sdk'",JSON.stringify(url("export const Button='button'")))
  .replace("'./media-review.js'",JSON.stringify(url("export const MediaReview='review'")))
  .replace("'./media-review-controller.js'",JSON.stringify(url('export const createImportedReviewReader=()=>{},createRetainedReviewReader=()=>{};')))
  .replace("'./production-comparison.js'",JSON.stringify(url("export const ProductionComparison='comparison'")))
  .replace("'./methods-ui.js'",JSON.stringify(methods));
const {CreatePanel,ProductionImport}=await import(url(reviewSource));
const nodes=tree=>!tree||typeof tree!=='object'?[]:[tree,...tree.children.flatMap(nodes)];
const find=(tree,type,label)=>nodes(tree).find(n=>n.type===type&&(!label||n.children.includes(label)));
const production='d'.repeat(32),asset='c'.repeat(32),request='a'.repeat(32),take='b'.repeat(32),job='e'.repeat(32);
const inventory={kinds:{Image:{default:'image-route',options:[{id:'image-route',label:'Image route',engine:'cloud',available:true,cost:'unknown'},
  {id:'import',label:'Import',engine:'import',available:true,cost:'free'}]}}};
function setup(){
  const f=fixture();f.route.primary=true;
  const calls=[],inserted=[];
  const current={id:production,title:'Controlled project',revision:3,references:[{id:'ref',revision:2,label:'Controlled reference'}],
    assets:[{id:asset,position:0,kind:'Image',intent:'Controlled direction',references:[{id:'ref',revision:2}],takes:[{id:take,request}]}]};
  const original=async(op,payload)=>{
    if(op==='production.list')return {productions:[current],available:[]};
    if(op==='production.open')return {current,available:[]};
    if(op==='creation.methods')return inventory;
    if(op==='production.media_import.intent')return {request,revision:1,kind:'Image',method:'import'};
    if(op==='production.media_import.begin')return {id:job,take};
    if(op==='production.media_import.chunk')return {id:job,received:payload.offset+Buffer.from(payload.data,'base64').length};
    if(op==='production.media_import.commit')return {id:job,take,status:'Ready for review'};
    if(op==='production.link_take')return {current:{...current,revision:4},available:[]};
    throw Error('Unexpected controlled RPC '+op);
  };
  let handler=original;
  f.host.request=async(method,payload)=>{assert.equal(payload.session_id,'s1');const op=method.replace('plugin.motion-studio.','');calls.push({op,payload});return handler(op,payload);};
  f.host.composer={getDraft:async()=>'',insertText:async(session,text)=>{inserted.push({session,text});return true;}};
  const owner=new ProductionController(f.host);
  return {...f,owner,current,calls,inserted,original,handle:value=>{handler=value;}};
}
const identity=f=>({epoch:f.owner.epoch,production,asset});
const file=()=>({size:20,type:'image/png',name:'controlled.png',arrayBuffer:async()=>new Uint8Array(20).buffer});
const panel=f=>CreatePanel({state:f.owner.state,current:f.owner.state.current,asset:f.owner.state.current.assets[0],
  assets:f.owner.state.current.assets,identity:identity(f),controller:f.owner,onSection:()=>{},refineTake:take});
const key=production+':'+asset;

test('methods uses passive creation RPC, failed load remains retryable and successful inventory is shown',async()=>{
  const f=setup();await f.owner.open();f.handle(op=>op==='creation.methods'?Promise.reject(Error('controlled outage')):f.original(op));
  await f.owner.loadMethods();assert.equal(f.owner.state.methods,null);assert.equal(f.owner.state.methodsError,true);
  f.handle(f.original);await f.owner.loadMethods();assert.deepEqual(f.owner.state.methods,inventory);assert.equal(f.owner.state.methodsError,false);
  assert.deepEqual(f.calls.map(c=>c.op),['production.list','production.open','creation.methods','creation.methods']);f.owner.dispose();
});
for(const stage of ['routes','reply'])test('methods rejects obsolete '+stage+' continuation after away-and-back',async()=>{
  const f=setup();await f.owner.open();const gate=deferred();
  if(stage==='routes')f.host.profileRoutes=()=>gate.promise;
  else f.handle(op=>op==='creation.methods'?gate.promise:f.original(op));
  const work=f.owner.loadMethods();await flush();f.set('focusedSessionId','away');f.set('focusedSessionId','s1');
  gate.resolve(stage==='routes'?[f.route]:inventory);await work;
  assert.equal(f.owner.state.methods,null);assert.equal(f.owner.state.methodsLoading,false);
  assert.equal(f.calls.filter(c=>c.op==='creation.methods').length,stage==='routes'?0:1);f.owner.dispose();
});
for(const existing of [false,true])test('import '+(existing?'preserves existing request':'creates non-generating intent first'),async()=>{
  const f=setup();await f.owner.open();await f.owner.importTake(file(),existing?{request,revision:7,kind:'Image'}:null,identity(f));
  const intent=f.calls.find(c=>c.op.endsWith('.intent'));
  if(existing)assert.equal(intent,undefined);
  else {assert.deepEqual(Object.keys(intent.payload).sort(),['asset','command','expected','production','session_id']);
    assert.equal(intent.payload.production,production);assert.equal(intent.payload.asset,asset);assert.equal(intent.payload.expected,3);assert.match(intent.payload.command,/^[a-f0-9]{32}$/);}
  const begin=f.calls.find(c=>c.op.endsWith('.begin'));assert.equal(begin.payload.request,request);assert.equal(begin.payload.revision,existing?7:1);
  assert.ok(f.calls.some(c=>c.op==='production.link_take'));assert.equal(f.inserted.length,0);
  assert.ok(!f.calls.some(c=>/prepare|start|select_take/.test(c.op)));f.owner.dispose();
});
for(const mode of ['scope','cancel','dispose'])test('import intent '+mode+' interruption prevents begin',async()=>{
  const f=setup();await f.owner.open();const gate=deferred();f.handle((op,p)=>op.endsWith('.intent')?gate.promise:f.original(op,p));
  const work=f.owner.importTake(file(),null,identity(f));await flush();
  if(mode==='scope')f.set('focusedSessionId','away');else if(mode==='cancel')await f.owner.cancelImport();else f.owner.dispose();
  gate.resolve({request,revision:1,kind:'Image',method:'import'});await work;
  assert.ok(!f.calls.some(c=>c.op.endsWith('.begin')));f.owner.dispose();
});
test('empty-request UI permits import and routes selected file with no creation request',()=>{
  const calls=[],scope={epoch:1,production,asset};
  const tree=ProductionImport({controller:{importTake:(...args)=>calls.push(args)},state:{busy:false,pending:false},asset:{id:asset,kind:'Image'},identity:scope});
  assert.equal(find(tree,'button','Import a take').props.disabled,false);
  const input=find(tree,'input'),original=file();input.props.onChange({target:{files:[original],value:'controlled'}});
  assert.deepEqual(calls,[[original,undefined,scope]]);
});
test('draft retains method/text on existing chat draft or failed insertion; clears only on successful insert with exact pins',async()=>{
  const f=setup();await f.owner.open();await f.owner.loadMethods();
  find(panel(f),'textarea').props.onChange({target:{value:'Unsent controlled text'}});
  f.host.composer.getDraft=async()=>'Existing draft';
  await find(panel(f),'button','Create with Hermes').props.onClick();assert.equal(f.owner.directionDrafts.get(key).text,'Unsent controlled text');
  f.host.composer.insertText=async()=>false;
  await find(panel(f),'button','Add to existing draft').props.onClick();assert.ok(f.owner.directionDrafts.has(key));
  f.host.composer.insertText=async(session,text)=>{f.inserted.push({session,text});return true;};
  await find(panel(f),'button','Add to existing draft').props.onClick();assert.equal(f.owner.directionDrafts.has(key),false);
  assert.match(f.inserted[0].text,/preferred method image-route/);assert.match(f.inserted[0].text,/refine take b{32} of request a{32}/);
  assert.match(f.inserted[0].text,/references ref revision 2/);assert.match(f.inserted[0].text,/Unsent controlled text/);f.owner.dispose();
});
test('explicit import method cannot draft generation; unavailable explicit method cannot silently fall back',async()=>{
  const f=setup();await f.owner.open();await f.owner.loadMethods();
  f.owner.directionDrafts.set(key,{text:'Keep this direction',method:'import'});
  const tree=panel(f);assert.equal(find(tree,'button','Create with Hermes').props.disabled,true);
  await find(tree,'button','Create with Hermes').props.onClick();assert.equal(f.inserted.length,0);
  f.owner.directionDrafts.set(key,{text:'Keep this direction',method:'missing-method'});
  assert.equal(find(panel(f),'button','Create with Hermes').props.disabled,true);f.owner.dispose();
});
test('drafts survive same-host controller remount but clear on scope transition while unmounted and server denial',async()=>{
  const f=setup();await f.owner.open();const old=panel(f);find(old,'textarea').props.onChange({target:{value:'Private controlled draft'}});
  f.owner.dispose();const next=new ProductionController(f.host);assert.equal(next.directionDrafts.get(key).text,'Private controlled draft');next.dispose();
  f.set('focusedSessionId','away');f.set('focusedSessionId','s1');const reopened=new ProductionController(f.host);await reopened.open();
  assert.equal(reopened.directionDrafts.size,0);find(old,'textarea').props.onChange({target:{value:'Stale closure'}});assert.equal(reopened.directionDrafts.size,0);
  reopened.directionDrafts.set(key,{text:'Private controlled draft'});reopened.failure({code:'PRODUCTION_SCOPE_DENIED'});assert.equal(reopened.directionDrafts.size,0);reopened.dispose();
});
test('scope change during composer read prevents insert and does not resurrect drafts',async()=>{
  const f=setup();await f.owner.open();const gate=deferred();f.host.composer.getDraft=()=>gate.promise;
  find(panel(f),'textarea').props.onChange({target:{value:'Controlled draft'}});const work=find(panel(f),'button','Create with Hermes').props.onClick();
  f.set('focusedSessionId','away');f.set('focusedSessionId','s1');gate.resolve('');await work;
  assert.equal(f.inserted.length,0);assert.equal(f.owner.directionDrafts.size,0);f.owner.dispose();
});
test('method picker persists explicit ID with direction, and stale revision callback cannot insert',async()=>{
  const f=setup();await f.owner.open();await f.owner.loadMethods();
  find(panel(f),'textarea').props.onChange({target:{value:'Preserved direction'}});
  const picker=nodes(panel(f)).find(node=>node.props.idPrefix==='production-method');picker.props.onChoose('image-route');
  assert.deepEqual(f.owner.directionDrafts.get(key),{text:'Preserved direction',method:'image-route'});
  const old=panel(f);f.owner.state.current={...f.owner.state.current,revision:4};
  await find(old,'button','Create with Hermes').props.onClick();assert.equal(f.inserted.length,0);assert.ok(f.owner.directionDrafts.has(key));f.owner.dispose();
});
test('late successful composer reply cannot delete a newer draft',async()=>{
  const f=setup();await f.owner.open();const gate=deferred();f.host.composer.insertText=()=>gate.promise;
  find(panel(f),'textarea').props.onChange({target:{value:'First direction'}});
  const work=find(panel(f),'button','Create with Hermes').props.onClick();await flush();
  f.owner.directionDrafts.set(key,{text:'Newer direction'});gate.resolve(true);await work;
  assert.equal(f.owner.directionDrafts.get(key).text,'Newer direction');f.owner.dispose();
});
