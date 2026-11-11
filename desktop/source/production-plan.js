import {createElement as h} from 'react';
import {Input,Textarea} from '@hermes/plugin-sdk';
const KINDS=['Sound effects','Music','Voice','Image','Video'];
const ICONS={'Sound effects':'M4 10v4h3l4 3V7l-4 3H4z M15 9.5a3.5 3.5 0 0 1 0 5 M17.5 7a7 7 0 0 1 0 10',
  Music:'M9 18V6l10-2v12 M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z M19 16a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z',
  Voice:'M12 4a2.5 2.5 0 0 0-2.5 2.5v5a2.5 2.5 0 0 0 5 0v-5A2.5 2.5 0 0 0 12 4z M6.5 11.5a5.5 5.5 0 0 0 11 0 M12 17v3',
  Image:'M4 5h16v14H4z M4 16l5-5 4 4 3-3 4 4',Video:'M4 6h12v12H4z M16 10l4-2.5v9L16 14'};
// Decorative media-kind glyph; always paired with a text label.
export const kindIcon=kind=>h('svg',{className:'production-icon',viewBox:'0 0 24 24',width:18,height:18,fill:'none',stroke:'currentColor',
  strokeWidth:1.7,strokeLinecap:'round',strokeLinejoin:'round','aria-hidden':true,focusable:'false'},h('path',{d:ICONS[kind]||ICONS.Image}));
const intentLabel=intent=>!intent?'No intent saved':intent.length>120?intent.slice(0,117)+'...':intent;

// Read-only projection: a selected pointer is not proof of QA or current inputs.
export function describeAssetPlan(item,assets){
  const takes=item.takes||[],index=takes.findIndex(take=>take.id===item.selected_take);
  return {
    title:(item.position+1)+'. '+item.kind,
    selection:!item.selected_take?'No selected take':index<0?'Selected take unavailable':'Selected take '+(index+1),
    review:!item.selected_take?'QA: no selected take':'QA: '+(takes[index]?.review||'Unknown'),
    freshness:!item.selected_take?'Not selected':item.stale?'Stale selection - earlier inputs':
      index<0||typeof item.stale!=='boolean'?'Selection freshness unknown':'Selection uses current pins',
    dependencies:(item.depends_on||[]).map(id=>{
      const dependency=assets.find(asset=>asset.id===id);
      return dependency?(dependency.position+1)+'. '+dependency.kind+' - '+(dependency.intent||'No intent saved'):'Unavailable asset';
    }),
  };
}

export function ProductionBoard({assets,selectedAsset,onChooseAsset,busy=false,references=[],onCreate}){
  if(!assets.length)return h('div',{className:'production-plan-empty'},
    h('p',null,'No assets in this plan.'),h('p',null,'Add your first asset in Plan. Adding an asset never generates anything.'));
  return h('ol',{className:'production-board',role:'list','aria-label':'Planned assets'},...assets.map(item=>{
    const summary=describeAssetPlan(item,assets),stale=Boolean(item.selected_take&&item.stale);
    return h('li',{key:item.id,className:'production-board-card','data-on':String(item.id===selectedAsset)},
      h('button',{type:'button',className:'production-asset '+(item.id===selectedAsset?'production-selected':''),
        disabled:busy,'aria-pressed':item.id===selectedAsset,
        onClick:()=>onChooseAsset?.(item.id)},h('span',{className:'production-asset-head'},kindIcon(item.kind),h('strong',null,summary.title)),
        h('span',{className:'production-asset-intent'},intentLabel(item.intent)),
        h('span',{className:'production-badges'},h('span',{className:'production-badge','data-tone':item.selected_take?'good':undefined},summary.selection),
          item.selected_take?h('span',{className:'production-badge'},summary.review):null,
          item.selected_take&&summary.freshness!=='Selection uses current pins'?h('span',{className:'production-badge '+(stale?'production-stale':''),'data-tone':stale?'warn':undefined},summary.freshness):null)),
      onCreate?h('button',{type:'button',className:'pd-btn',disabled:busy,onClick:()=>onCreate(item)},'Create with Hermes'):null,
      h('details',{className:'production-plan-details'},h('summary',null,'Details',h('span',{className:'ms-visually-hidden'},': '+summary.title)),
        h('p',null,(item.takes||[]).length+' takes / '+summary.dependencies.length+' dependencies / '+(item.references||[]).length+' references'),
        h('p',null,'Intent: '+(item.intent||'No intent saved')),
        h('p',null,summary.dependencies.length?'Depends on: '+summary.dependencies.join('; '):'No dependencies.'),
        h('p',null,(item.references||[]).length?'References: '+item.references.map(ref=>
          (references.find(reference=>reference.id===ref.id)?.label||'Reference')+' / revision '+ref.revision).join('; '):'No references.'),
        item.selected_take?h('p',null,'Selected take ID: '+item.selected_take):null,
        (item.takes||[]).length?h('ul',{'aria-label':'Linked takes for '+summary.title},...item.takes.map((take,index)=>
          h('li',{key:take.id},'Take '+(index+1)+' / '+(take.review||'Review unknown')+
            (take.id===item.selected_take?' / selected':' / alternative'),h('span',{className:'production-take-id'},take.id)))):
          h('p',null,'No takes yet. Create with Hermes or import a take.'),
        h('p',null,'Choosing an asset only changes what you are looking at. Use take is a separate step.')));
  }));
}

// Asset-plan editor only; drafts and scoped command closures remain owned by the page.
export function ProductionPlan({assets,asset,current,busy,controller,briefKey,newKind,newIntent,
  setKindDraft,setIntentDraft,identity,assetValues,setAssetValues,saveAsset,setAssetDraft,button}){
  return h('section',{className:'ms-panel production-panel production-plan','aria-label':'Asset plan'},h('h2',null,'Asset plan'),
    h('p',{className:'production-muted'},'Each asset is one thing the project needs. Pick one in the list to edit it here.'),
    asset?h('article',{className:'production-plan-editor','aria-label':'Selected asset plan'},h('h3',null,(asset.position+1)+'. '+asset.kind),
      asset.selected_take&&asset.stale?h('p',{className:'ms-notice production-stale'},'The chosen take is out of date: something it depends on changed. Review it before using it again.'):null,
      h('label',null,'What it should be',h(Textarea,{'aria-label':'Asset intent',value:assetValues.intent,maxLength:2000,disabled:busy,
        placeholder:'e.g. A soft door close with a short room echo',onChange:event=>setAssetValues({intent:event.target.value})})),
      h('div',{className:'production-row production-order'},
        h('label',null,'Order (0 is first)',h(Input,{'aria-label':'Plan position',type:'number',min:0,max:Math.max(0,assets.length-1),step:1,
          value:assetValues.position,disabled:busy,onChange:event=>setAssetValues({position:Number(event.target.value)})})),
        button('Move earlier',()=>setAssetValues({position:Math.max(0,assetValues.position-1)}),assetValues.position<=0),
        button('Move later',()=>setAssetValues({position:Math.min(assets.length-1,assetValues.position+1)}),assetValues.position>=assets.length-1)),
      h('details',{className:'production-plan-details'},h('summary',null,'Dependencies and references'),
      h('fieldset',null,h('legend',null,'Depends on'),...assets.filter(item=>item.id!==asset.id).map(item=>
        h('label',{key:item.id},h('input',{type:'checkbox',checked:assetValues.depends_on.includes(item.id),disabled:busy,
          onChange:event=>setAssetValues({depends_on:event.target.checked?[...assetValues.depends_on,item.id]:
            assetValues.depends_on.filter(id=>id!==item.id)})}),(item.position+1)+'. '+item.kind+' / '+intentLabel(item.intent))),
        assets.length===1?h('p',null,'No other assets. Add an asset before defining a dependency.'):null),
      h('fieldset',null,h('legend',null,'Uses references'),...(current.references.length?current.references.map(reference=>
        h('label',{key:reference.id},h('input',{type:'checkbox',checked:assetValues.references.includes(reference.id),disabled:busy,
          onChange:event=>setAssetValues({references:event.target.checked?[...assetValues.references,reference.id]:
            assetValues.references.filter(id=>id!==reference.id)})}),reference.label||'Reference '+reference.revision)):
        [h('p',{key:'none'},'No references yet. Add one in References.')]))),
      h('div',{className:'production-row'},button('Save asset',saveAsset),button('Discard changes',()=>setAssetDraft({key:null}))),
      h('p',{className:'production-muted'},'Changes apply when you save. If another asset depends on this one, its chosen take is marked out of date rather than replaced.')):null,
    current?h('div',{className:'production-add'},h('h3',null,'Add an asset'),
      h('div',{className:'production-add-row'},h('label',null,'Media type',h('select',{'aria-label':'New asset media kind',
        value:newKind,disabled:busy,onChange:event=>setKindDraft({key:briefKey,kind:event.target.value})},...KINDS.map(kind=>h('option',{key:kind},kind)))),
      h('label',null,'What it should be',h(Input,{'aria-label':'New asset intent',value:newIntent,maxLength:2000,disabled:busy,
        placeholder:'e.g. Opening title image',onChange:event=>setIntentDraft({key:briefKey,text:event.target.value})}))),
      button('Add asset',()=>controller.current?.addAsset(newKind,newIntent,identity))):null);
}
