// Source component checks with a structural React facade; no host/store/media access.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const data=source=>'data:text/javascript;base64,'+Buffer.from(source).toString('base64');
const react=data('export const createElement=(type,props,...children)=>({type,props:props||{},children:children.flat(Infinity)});');
const sdk=data("export const Input='input',Textarea='textarea';");
const source=fs.readFileSync('studio/native/frontend/production-plan.js','utf8');
const {ProductionPlan,ProductionBoard,describeAssetPlan}=await import(data(source
  .replace("'react'",JSON.stringify(react)).replace("'@hermes/plugin-sdk'",JSON.stringify(sdk))));
const assets=[{id:'asset-a',position:0,kind:'Sound effects',intent:'Controlled impact',selected_take:'take-b',stale:true,
  depends_on:['asset-b'],references:[{id:'ref-a',revision:2}],takes:[{id:'take-a',review:'Approved'},{id:'take-b',review:'Not reviewed'}]},
  {id:'asset-b',position:1,kind:'Music',intent:'Controlled bed',selected_take:null,stale:false,depends_on:[],references:[],takes:[]}];
function nodes(tree){
  if(!tree||typeof tree!=='object')return [];
  if(typeof tree.type==='function')return nodes(tree.type(tree.props));
  return [tree,...tree.children.flatMap(nodes)];
}
function text(tree){
  if(tree==null||typeof tree==='boolean')return '';
  if(typeof tree!=='object')return String(tree);
  if(typeof tree.type==='function')return text(tree.type(tree.props));
  return tree.children.map(text).join(' ');
}
function setup(overrides={}){
  const calls=[],props={assets,asset:assets[0],current:{references:[]},busy:false,briefKey:'scope:production',
    identity:{epoch:1,production:'production-a',asset:'asset-a'},newKind:'Music',newIntent:'Controlled new asset',
    assetValues:{intent:'Draft impact',position:0,depends_on:[],references:[]},
    controller:{current:{chooseAsset:id=>calls.push(['choose',id]),addAsset:(...args)=>calls.push(['add',...args])}},
    setKindDraft:value=>calls.push(['kind',value]),setIntentDraft:value=>calls.push(['intent',value]),
    setAssetValues:value=>calls.push(['draft',value]),saveAsset:()=>calls.push(['save']),setAssetDraft:value=>calls.push(['discard',value]),
    button:(label,onClick,disabled=false)=>({type:'button',props:{onClick,disabled},children:[label]}),...overrides};
  const tree=ProductionPlan(props),all=nodes(tree);
  return {props,calls,tree,all,button:label=>all.find(node=>node.type==='button'&&text(node)===label)};
}
test('summary resolves exact selected pointer, review and staleness independently',()=>{
  const before=JSON.stringify(assets),summary=describeAssetPlan(assets[0],assets);
  assert.equal(summary.selection,'Selected take 2');assert.equal(summary.review,'QA: Not reviewed');
  assert.equal(summary.freshness,'Stale selection - earlier inputs');
  assert.deepEqual(summary.dependencies,['2. Music - Controlled bed']);assert.equal(JSON.stringify(assets),before);
});
test('no selection never claims current or approved output',()=>{
  const summary=describeAssetPlan({...assets[1],takes:[{id:'ignored',selected:true,review:'Approved'}]},assets);
  assert.equal(summary.selection,'No selected take');assert.equal(summary.freshness,'Not selected');
  assert.equal(summary.review,'QA: no selected take');
});
test('missing selected metadata and dependencies remain explicitly unknown',()=>{
  const summary=describeAssetPlan({...assets[0],selected_take:'missing',depends_on:['missing'],stale:false},assets);
  assert.equal(summary.selection,'Selected take unavailable');assert.equal(summary.review,'QA: Unknown');
  assert.equal(summary.freshness,'Selection freshness unknown');
  assert.deepEqual(summary.dependencies,['Unavailable asset']);
});
test('missing freshness stays unknown and explicit stale state remains visible',()=>{
  assert.equal(describeAssetPlan({...assets[0],stale:undefined},assets).freshness,'Selection freshness unknown');
  assert.equal(describeAssetPlan({...assets[0],selected_take:'missing'},assets).freshness,'Stale selection - earlier inputs');
});
test('progressive details expose every linked take without choosing or playing one',()=>{
  const tree=ProductionBoard({assets,selectedAsset:'asset-a'}),all=nodes(tree);
  const inventory=all.find(node=>node.props['aria-label']==='Linked takes for 1. Sound effects');
  assert.equal(inventory.children.length,2);
  assert.match(text(inventory.children[0]),/Take 1 \/ Approved \/ alternative.*take-a/);
  assert.match(text(inventory.children[1]),/Take 2 \/ Not reviewed \/ selected.*take-b/);
  assert.match(text(tree),/No takes yet/);
  assert.equal(all.filter(node=>['audio','video'].includes(node.type)).length,0);
});
test('board selects review context only and exposes semantic selected state',()=>{
  const chosen=[],tree=ProductionBoard({assets,selectedAsset:'asset-a',onChooseAsset:id=>chosen.push(id)});
  assert.equal(tree.type,'ol');assert.equal(tree.props['aria-label'],'Planned assets');
  const buttons=nodes(tree).filter(node=>node.type==='button');assert.equal(buttons.length,2);
  assert.equal(buttons[0].props['aria-pressed'],true);assert.equal(buttons[1].props['aria-pressed'],false);
  buttons[1].props.onClick();assert.deepEqual(chosen,['asset-b']);assert.equal(assets[0].selected_take,'take-b');
});
test('busy board blocks selection through disabled native buttons',()=>{
  const tree=ProductionBoard({assets,selectedAsset:'asset-a',busy:true});
  assert.ok(nodes(tree).filter(node=>node.type==='button').every(node=>node.props.disabled));
});
test('empty board offers real next steps without fake media or generation controls',()=>{
  const tree=ProductionBoard({assets:[]});assert.match(text(tree),/Add your first asset/);
  assert.equal(nodes(tree).filter(node=>node.type==='button'||node.type==='audio'||node.type==='video').length,0);
});
test('existing add callback receives exact kind, intent and scoped identity',()=>{
  const f=setup();f.button('Add asset').props.onClick();
  assert.deepEqual(f.calls,[['add',f.props.newKind,f.props.newIntent,f.props.identity]]);
});
test('reorder is draft only, clamps to available positions, and uses existing save callback',()=>{
  const f=setup();assert.equal(f.button('Move earlier').props.disabled,true);
  f.button('Move later').props.onClick();assert.deepEqual(f.calls,[['draft',{position:1}]]);
  f.button('Save asset').props.onClick();assert.deepEqual(f.calls.at(-1),['save']);
  const last=setup({assetValues:{intent:'Draft',position:1,depends_on:[],references:[]}});
  assert.equal(last.button('Move later').props.disabled,true);
  last.button('Move earlier').props.onClick();assert.deepEqual(last.calls,[['draft',{position:0}]]);
});
test('intent, dependencies, reference toggles and discard retain existing callback shapes',()=>{
  const f=setup({current:{references:[{id:'ref-a',revision:2,label:'Controlled reference'}]}});
  f.all.find(node=>node.props['aria-label']==='Asset intent').props.onChange({target:{value:'Changed'}});
  const checkboxes=f.all.filter(node=>node.type==='input'&&node.props.type==='checkbox');
  checkboxes[0].props.onChange({target:{checked:true}});checkboxes[1].props.onChange({target:{checked:true}});
  f.button('Discard changes').props.onClick();
  assert.deepEqual(f.calls,[['draft',{intent:'Changed'}],['draft',{depends_on:['asset-b']}],
    ['draft',{references:['ref-a']}],['discard',{key:null}]]);
});
test('all five existing kinds remain in add picker and busy fields are disabled',()=>{
  const f=setup({busy:true}),select=f.all.find(node=>node.props['aria-label']==='New asset media kind');
  assert.deepEqual(select.children.map(text),['Sound effects','Music','Voice','Image','Video']);
  assert.equal(select.props.disabled,true);
  assert.ok(f.all.filter(node=>['input','textarea'].includes(node.type)).every(node=>node.props.disabled));
});
