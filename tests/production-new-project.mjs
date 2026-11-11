// Source-component flow with hook/DOM facades; no browser/native qualification.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const url=s=>'data:text/javascript;base64,'+Buffer.from(s).toString('base64');
let frame,cursor,effects,dirty,tree,mode,calls,owner,focuses,scrolls;
const frames=new Map();
globalThis.document={addEventListener:()=>{},removeEventListener:()=>{}};
const slot=initial=>{const i=cursor++;if(!(i in frame))frame[i]=initial;return i;};
globalThis.productionFlowHooks={
  useState(initial){const f=frame,i=slot(initial);return [f[i],value=>{f[i]=typeof value==='function'?value(f[i]):value;dirty=true;}];},
  useRef(initial){return frame[slot({current:initial})];},
  useEffect(fn,deps){const i=cursor++,old=frame[i];if(!old||deps.some((v,j)=>v!==old[j]))effects.push(fn);frame[i]=deps;},
};
const react=url(`export const createElement=(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity)});
export const {useState,useRef,useEffect}=globalThis.productionFlowHooks;`);
let source=fs.readFileSync('studio/native/frontend/production-page.js','utf8');
const stubs={
  '@hermes/plugin-sdk':"export const Button='button',Input='input',Textarea='textarea';",
  './production-style.js':"export const productionStyles='';",
  './production-plan.js':"export const ProductionBoard='board',ProductionPlan='plan',kindIcon=()=>'';",
  './production-export.js':"export const ProductionExport='export';",
  './production-review.js':"export const CreatePanel='create-panel',ProductionReview='review';",
  './workspace-copy.js':"export const workspaceStatus=s=>s;",
  './creation-page.js':"export const MotionHeader='header';",
  './help.js':"export const PRODUCTION_HELP={quick:[],guide:[]},QuickHelp='quick-help',HelpPanel='help';",
};
source=source.replace("'react'",JSON.stringify(react));
for(const [name,stub] of Object.entries(stubs))source=source.replace(JSON.stringify(name).replaceAll('"',"'"),JSON.stringify(url(stub)));
const {ProductionPage}=await import(url(source));
const current={id:'existing',title:'Existing',revision:1,brief_revision:1,brief:{text:'Existing brief'},assets:[],references:[]};
function createController(onChange){
  const state={current,productions:[current],scopeEpoch:1,busy:false,pending:false,status:'Ready.',available:[],capabilities:{}};
  const emit=patch=>{Object.assign(state,patch);onChange({...state});};
  owner={state,open:async()=>emit({}),dispose:()=>{},clear:()=>{},
    newBrief:()=>emit({current:null,selectedAsset:null,selectedTake:null}),
    create:async(payload,identity)=>{calls.push({payload,identity});if(mode==='failure')return;
      if(mode==='scope'){emit({scopeEpoch:2,current:null});return {receipt:{revision:1}};}
      const saved={...current,...payload,id:'created'};emit({current:saved});return {receipt:{revision:1},current:saved};}};
  return owner;
}
function expand(node){
  if(!node||typeof node!=='object')return node;
  if(typeof node.type==='function'){
    frame=frames.get(node.type)||[];frames.set(node.type,frame);cursor=0;
    return expand(node.type({...node.props,children:node.children}));
  }
  if(node.props.ref)node.props.ref.current={querySelector:()=>({scrollIntoView:()=>scrolls++,focus:()=>focuses++})};
  return {...node,children:node.children.map(expand)};
}
function render(){
  do{dirty=false;effects=[];tree=expand({type:ProductionPage,props:{createController,onQuickCreate:()=>{}},children:[]});
    for(const effect of effects)effect();}while(dirty);
  return tree;
}
const nodes=n=>!n||typeof n!=='object'?[]:[n,...n.children.flatMap(nodes)];
const text=n=>!n||typeof n==='boolean'?'':typeof n==='object'?n.children.map(text).join(''):String(n);
const find=label=>nodes(tree).find(n=>n.props['aria-label']===label);
const button=label=>nodes(tree).find(n=>n.type==='button'&&text(n)===label);
const status=()=>nodes(tree).find(n=>n.props.className==='production-notice');
function setup(){frames.clear();calls=[];focuses=scrolls=0;mode='success';render();button('New project').props.onClick();render();}
function fill(label,value){find(label).props.onChange({target:{value}});render();}
test('New project opens Brief, scrolls/focuses title, clears old title and shows banner',()=>{
  setup();assert.ok(find('Production Brief'));assert.equal(find('Production title').props.value,'');
  assert.equal(focuses,1);assert.equal(scrolls,1);
  assert.equal(text(status()),'New project — give it a title and a brief, then Create project.');
});
test('Create project is primary, disabled with a described hint until title and brief are nonblank',()=>{
  setup();assert.match(button('Create project').props.className,/pd-primary/);
  assert.equal(button('Create project').props.disabled,true);
  assert.equal(button('Create project').props['aria-describedby'],'production-create-hint');
  fill('Production title','   ');fill('Brief','Brief');assert.equal(button('Create project').props.disabled,true);
  fill('Production title','Title');fill('Brief','   ');assert.equal(button('Create project').props.disabled,true);
  fill('Brief','Brief');assert.equal(button('Create project').props.disabled,false);assert.equal(focuses,1);
});
test('even direct invalid Create invocation cannot dispatch',async()=>{
  setup();await button('Create project').props.onClick();assert.equal(calls.length,0);
});
test('success preserves five-media payload, switches to new project Plan and announces creation',async()=>{
  setup();fill('Production title','Title');fill('Brief','Brief');await button('Create project').props.onClick();render();
  assert.ok(find('Production Plan'));assert.equal(text(status()),'Project created.');assert.equal(calls.length,1);
  assert.deepEqual(calls[0],{payload:{title:'Title',brief:{text:'Brief',purpose:'',audience:'',usage:''},
    kinds:['Sound effects','Music','Voice','Image','Video']},identity:{epoch:1,production:null,asset:undefined}});
  button('New project').props.onClick();render();assert.equal(focuses,2);assert.equal(find('Production title').props.value,'');
});
for(const outcome of ['failure','scope'])test(outcome+' does not announce success or navigate to Plan',async()=>{
  setup();mode=outcome;fill('Production title','Title');fill('Brief','Brief');await button('Create project').props.onClick();render();
  assert.ok(find('Production Brief'));assert.notEqual(text(status()),'Project created.');
  if(outcome==='failure')assert.equal(find('Production title').props.value,'Title');
});
test('busy/pending Create stays disabled',()=>{
  setup();fill('Production title','Title');fill('Brief','Brief');
  owner.state.pending=true;owner.newBrief();render();assert.equal(button('Create project').props.disabled,true);
});
