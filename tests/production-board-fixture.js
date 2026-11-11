// Real ProductionPage and React DOM, synthetic projections and callback adapter only.
import {createElement as h} from 'react';
import {createRoot} from 'react-dom/client';
import {ProductionPage} from '../studio/native/frontend/production-page.js';
const kinds=['Sound effects','Music','Voice','Image','Video'];
const makeAssets=()=>kinds.map((kind,index)=>({id:'synthetic-asset-'+index,position:index,kind,
  intent:index===0?'Controlled impact':index===4?'Controlled '+('long-unbroken-label'.repeat(14)):'Controlled '+kind.toLowerCase(),
  selected_take:index===0?'synthetic-take-2':null,stale:index===0,revision:1,
  depends_on:index===0?['synthetic-asset-1']:[],references:index===0?[{id:'synthetic-reference',revision:1}]:[],
  takes:index===0?[{id:'synthetic-take-1',review:'Approved',origin:'test_fixture'},
    {id:'synthetic-take-2',review:'Not reviewed',origin:'test_fixture'}]:[]}));
window.boardCalls=[];
let controller;
function createController(onChange){
  const current={id:'synthetic-production',title:'Controlled Production board',revision:3,brief_revision:1,
    brief:{text:'Synthetic planning fixture',purpose:'',audience:'',usage:''},assets:makeAssets(),
    references:[{id:'synthetic-reference',label:'Controlled reference',revision:1,take:{id:'synthetic-take-1',review:'Approved'}}]};
  const state={current,productions:[current],scopeEpoch:1,selectedAsset:current.assets[0].id,selectedTake:'synthetic-take-2',
    busy:false,pending:false,status:'Synthetic saved projection. No generation.',available:[],capabilities:{},url:null};
  const emit=patch=>{Object.assign(state,patch);onChange({...state});};
  const record=(operation,...args)=>window.boardCalls.push({operation,args});
  controller={state,emit,open:async()=>emit({}),clear:()=>{},dispose:()=>{},
    chooseAsset:id=>{record('chooseAsset',id);emit({selectedAsset:id,selectedTake:state.current.assets.find(a=>a.id===id)?.selected_take||null});},
    addAsset:async(kind,intent,identity)=>{
      record('addAsset',kind,intent,identity);
      const added={...makeAssets()[1],id:'synthetic-added-'+state.current.assets.length,kind,intent,position:state.current.assets.length};
      state.current={...state.current,revision:state.current.revision+1,assets:[...state.current.assets,added]};emit({});
      return {receipt:{revision:state.current.revision}};
    },
    updateAsset:async(payload,identity)=>{
      record('updateAsset',payload,identity);
      const assets=state.current.assets.map(a=>a.id===payload.asset?{...a,intent:payload.intent,
        depends_on:payload.depends_on,references:payload.references.map(id=>({id,revision:1})),stale:Boolean(a.selected_take)}:a);
      const moving=assets.find(a=>a.id===payload.asset),others=assets.filter(a=>a!==moving);
      others.splice(payload.position,0,moving);
      state.current={...state.current,revision:state.current.revision+1,assets:others.map((a,position)=>({...a,position}))};
      emit({});return {receipt:{revision:state.current.revision}};
    },
  };
  window.boardFixture={busy:value=>emit({busy:value}),refresh:()=>emit({}),
    empty:()=>{state.current={...state.current,assets:[],references:[]};emit({selectedAsset:null,selectedTake:null});},
    single:()=>{state.current={...state.current,assets:[{...makeAssets()[1],position:0}],references:[]};
      emit({selectedAsset:state.current.assets[0].id,selectedTake:null});},
    stale:value=>{state.current={...state.current,assets:state.current.assets.map(a=>({...a,stale:value}))};emit({});}};
  return controller;
}
const root=createRoot(document.querySelector('#root'));
root.render(h(ProductionPage,{createController,onQuickCreate:()=>{}}));
