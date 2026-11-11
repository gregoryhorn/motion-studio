import {createElement as h,useEffect,useRef,useState} from 'react';
import {Button,Input,Textarea} from '@hermes/plugin-sdk';
import {productionStyles} from './production-style.js';
import {ProductionBoard,ProductionPlan,kindIcon} from './production-plan.js';
import {ProductionExport} from './production-export.js';
import {CreatePanel,ProductionReview} from './production-review.js';
import {workspaceStatus} from './workspace-copy.js';
import {MotionHeader} from './creation-page.js';
import {PRODUCTION_HELP,QuickHelp,HelpPanel} from './help.js';
const KINDS=['Sound effects','Music','Voice','Image','Video'];
const SECTIONS=['Review','Brief','Plan','References','Outputs'];
const emptyBrief={text:'',purpose:'',audience:'',usage:''};
const sameBrief=(a,b)=>a.title===b.title&&Object.keys(emptyBrief).every(key=>a.brief[key]===b.brief[key]);
// Creator-facing wording for fixed controller messages; unknown text passes through unchanged.
const PLAIN=[[/^Saved Production reopened\..*/,'Project opened.'],[/^Saved Production observed\..*/,'Project is up to date.'],
  [/^Open a saved Production or create a brief\..*/,'Open a project or start a new one.'],[/^New Production brief\..*/,'New project. Write a brief to begin.'],
  [/^Checking exact retained original bytes.*/,'Checking the original file...'],[/^Original retained bytes verified\..*/,'Original ready. Press play on the player.'],
  [/^Unresolved Create.*|^Uncertain command locked\..*/,'A project was being saved when the connection dropped. Choose Check interrupted save.'],
  [/^Lost Create reconciled.*/,'The interrupted save was found. Nothing was duplicated.'],[/^Stale visual scope rejected\..*/,'The project changed. Reopen it and try again.'],
  [/^Reviewed Production management associated\..*/,'This chat is connected.'],[/^Selected chat\/profile\/connection changed\..*/,'The selected chat changed. Reopen the project.'],
  [/^Imported original linked\..*/,'Import finished. Review the take, then choose Use take.'],[/^Choose an existing same-kind request for this import\./,'Ready.'],
  [/^Durable Create recovery marker unavailable\..*/,'This window cannot save safely right now. Nothing was sent.'],
  [/^Choose an existing authorized request and file.*/,'Choose a file that matches this asset’s media type.'],
  [/^[A-Z0-9_-]{4,}$/,'Something went wrong. Refresh the project and try again.']];
export function plainStatus(status){
  const text=workspaceStatus(status),match=PLAIN.find(([pattern])=>pattern.test(text));
  return match?match[1]:text;
}

// Overflow menu: closes after an item is picked, on Escape (focus returns to More) and on outside press.
function MoreMenu({children}){
  const node=useRef(null);
  useEffect(()=>{const outside=event=>{if(node.current?.open&&!node.current.contains(event.target))node.current.open=false;};
    document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[]);
  return h('details',{ref:node,className:'ms-more',onKeyDown:event=>{if(event.key!=='Escape'||!node.current?.open)return;
      node.current.open=false;node.current.querySelector('summary')?.focus();}},
    h('summary',{className:'pd-btn pd-ghost'},'More'),
    h('div',{className:'ms-row ms-more-body',onClick:event=>{if(event.target.closest?.('button')&&node.current)node.current.open=false;}},children));
}

function ProjectBar({state,current,busy,section,button,controller,onNew,onSection}){
  return h('div',{className:'production-bar'},
    state.productions.length?h('label',{className:'production-project'},h('span',null,'Project'),h('select',{'aria-label':'Project',
      value:current?.id||'',disabled:busy,onChange:event=>void controller.current?.open(event.target.value)},
      current?null:h('option',{value:'',disabled:true},'New project'),
      ...state.productions.map(item=>h('option',{key:item.id,value:item.id},item.title||'Untitled project')))):
      h('p',{className:'production-project'},h('span',null,'Project'),h('strong',null,'New project')),
    current?button('New project',onNew):null,
    state.pending?button('Check interrupted save',()=>controller.current?.reconcilePending(),false,true):null,
    h('div',{className:'ms-spacer'}),
    h(MoreMenu,null,button('Refresh',()=>controller.current?.refresh(),false,true),
      button('Reopen project',()=>controller.current?.open(current?.id),false,true),button(state.connecting?'Connecting…':'Connect this chat',()=>controller.current?.admit())),
    current&&section!=='Outputs'?h(Button,{className:'ms-btn pd-btn pd-accent',variant:'outline',title:'Choose what to package and save it as one ZIP',
      onClick:()=>onSection('Outputs')},'Export assets'):null);
}

function BriefPanel({brief,current,busy,button,setBrief,setBriefField,saveBrief,createProduction,discard,focusRequest}){
  const panel=useRef(null),ready=Boolean(brief.title.trim()&&brief.brief.text.trim());
  useEffect(()=>{if(!focusRequest)return;const input=panel.current?.querySelector('[aria-label="Production title"]');
    input?.scrollIntoView({block:'center',behavior:'smooth'});input?.focus({preventScroll:true});},[focusRequest]);
  return h('section',{ref:panel,className:'ms-panel production-panel','aria-label':'Brief editor'},h('h2',null,current?'Brief':'Start a project'),
    h('p',{className:'production-muted'},'A title and a short brief are enough. The other fields are optional context. Saving never starts generation.'),
    h('label',null,'Project title',h(Input,{'aria-label':'Production title',value:brief.title,maxLength:200,disabled:busy,placeholder:'e.g. Morning ritual',
      onChange:event=>setBrief('title',event.target.value)})),
    ...[['text','Brief'],['purpose','Purpose (optional)'],['audience','Audience (optional)'],['usage','Usage (optional)']].map(([key,label])=>
      h('label',{key},label,h(Textarea,{'aria-label':label,value:brief.brief[key],maxLength:key==='text'?8000:2000,disabled:busy,
        className:key==='text'?'':'production-short',onChange:event=>setBriefField(key,event.target.value)}))),
    h('div',{className:'production-row'},current?button('Save brief',saveBrief,false,false,true):button('Create project',createProduction,!ready,false,true,{'aria-describedby':!ready?'production-create-hint':undefined}),
      button('Discard changes',discard)),
    !current&&!ready?h('p',{id:'production-create-hint',className:'ms-help'},'Enter a title and a brief to create your project.'):null,
    current?null:h('p',{className:'ms-help'},'A new project starts with one asset for each media type. You can add, edit or ignore them in Plan.'),
    current?h('details',{className:'ms-tech'},h('summary',null,'Technical details'),
      h('p',null,'Project revision '+current.revision+' / brief revision '+current.brief_revision)):null);
}

function ReferencesPanel({state,current,asset,source,referenceLabel,busy,button,controller,identity,setSource,setLabel}){
  return h('section',{className:'ms-panel production-panel','aria-label':'References'},h('h2',null,'References'),
    h('p',{className:'production-muted'},'Bring a take you saved in Quick Create into this project, as a take for the selected asset or as a reference that keeps later takes consistent.'),
    state.available.length?h('label',null,'Saved take from Quick Create',h('select',{'aria-label':'Retained Quick Create take',
      value:source?.id||'',disabled:busy,onChange:event=>setSource(event.target.value)},
      ...state.available.map(item=>h('option',{key:item.id,value:item.id},item.direction)))):
      h('p',{className:'ms-empty'},'No saved Quick Create takes in this chat yet.'),
    source?h('p',{className:'ms-meta'},h('span',{className:'ms-badge'},source.kind),h('span',{className:'ms-badge'},source.review)):null,
    current&&source?h('div',{className:'production-ref-actions'},
      h('div',null,button('Add as a take for the selected asset',()=>controller.current?.link(source,identity),!asset||source.kind!==asset.kind),
        asset&&source.kind!==asset.kind?h('p',{className:'ms-help'},'The selected asset is '+asset.kind+'; this take is '+source.kind+'.'):null),
      h('label',null,'Reference name',h(Input,{'aria-label':'Reference label',value:referenceLabel,maxLength:200,disabled:busy,placeholder:'e.g. Cafe ambience',
        onChange:event=>setLabel(event.target.value)})),
      h('div',null,button('Save as reference',()=>controller.current?.addReference(source,referenceLabel,identity)))):null,
    (current?.references||[]).length?h('h3',{className:'ms-section-title production-gap'},'Project references'):null,
    ...(current?.references||[]).map(reference=>h('article',{key:reference.id,className:'production-ref'},
      h('div',null,h('h3',null,reference.label||'Reference'),h('p',{className:'ms-meta'},h('span',{className:'ms-badge'},reference.take.review||'Not reviewed'))),
      source?button('Replace with chosen take',()=>controller.current?.updateReference(reference,source,
        referenceLabel||reference.label,identity)):null,
      h('details',{className:'ms-tech'},h('summary',null,'Technical details'),
        h('p',null,'Reference revision '+reference.revision+' / take '+reference.take.id)))));
}

function OutputsPanel({state,assets,controller}){
  return h('section',{className:'ms-panel production-panel','aria-label':'Outputs'},h('h2',null,'Outputs'),
    h('p',{className:'production-muted'},'The take you chose for each asset. Only chosen, up-to-date takes can be exported.'),
    assets.length?h('ul',{className:'production-outputs'},...assets.map(item=>{
      const index=(item.takes||[]).findIndex(take=>take.id===item.selected_take);
      return h('li',{key:item.id},h('span',{className:'production-out-name'},kindIcon(item.kind),(item.position+1)+'. '+item.kind),
        h('span',{className:'ms-badge','data-tone':!item.selected_take?undefined:item.stale?'warn':'good'},!item.selected_take?'No take chosen':
          item.stale?'Out of date - review again':index<0?'Take chosen':'Take '+(index+1)+' chosen'));})):
      h('p',{className:'ms-empty'},'Add assets in Plan to see them here.'),
    h(ProductionExport,{owner:controller.current,productionState:state,hooks:controller.current?.exportHooks?.()}));
}

function PlanRail({section,showSection,assets,asset,busy,current,controller}){
  return h('div',{className:'production-left'},
    h('nav',{className:'production-sections','aria-label':'Production sections'},
      ...SECTIONS.map(name=>h('button',{key:name,type:'button','aria-pressed':section===name,onClick:()=>showSection(name)},name))),
    current?h('div',{className:'production-rail-plan'},h('div',{className:'production-rail-head'},h('h2',{className:'ms-section-title'},'Asset plan'),
      h('button',{type:'button',className:'production-linkish',onClick:()=>showSection('Plan')},'Edit plan')),
      h(ProductionBoard,{assets,selectedAsset:asset?.id,busy,references:current.references||[],onChooseAsset:id=>controller.current?.chooseAsset(id)})):null);
}

function useDrafts(){
  const [briefDraft,setBriefDraft]=useState({key:null}),[assetDraft,setAssetDraft]=useState({key:null});
  const [sourceDraft,setSourceDraft]=useState({key:null,id:''}),[referenceDraft,setReferenceDraft]=useState({key:null,text:''});
  const [kindDraft,setKindDraft]=useState({key:null,kind:KINDS[0]}),[intentDraft,setIntentDraft]=useState({key:null,text:''});
  const [sectionDraft,setSectionDraft]=useState({key:null,name:'Review'}),[helpOpen,setHelpOpen]=useState(false),[refine,setRefine]=useState({key:null,take:null});
  return {refine,setRefine,briefDraft,setBriefDraft,assetDraft,setAssetDraft,sourceDraft,setSourceDraft,referenceDraft,setReferenceDraft,
    kindDraft,setKindDraft,intentDraft,setIntentDraft,sectionDraft,setSectionDraft,helpOpen,setHelpOpen};
}

export function ProductionPage({createController,onQuickCreate}){
  const controller=useRef(null),audio=useRef(null),[state,setState]=useState(null),[notice,setNotice]=useState(null),d=useDrafts();
  useEffect(()=>{const current=createController(setState);controller.current=current;setState({...current.state});
    void current.open();return()=>{audio.current?.pause();current.dispose();controller.current=null;};},[createController]);
  useEffect(()=>{if(!state?.url)audio.current?.pause();},[state?.url,state?.urlTake,state?.scopeEpoch]);
  if(!state)return h('p',null,'Production - no work started.');
  const current=state.current,busy=state.busy,assets=current?.assets||[];
  const asset=assets.find(item=>item.id===state.selectedAsset)||assets[0];
  const take=asset?.takes.find(item=>item.id===state.selectedTake)||null;
  const briefKey=state.scopeEpoch+':'+(current?.id||'new');
  const section=!current?'Brief':d.sectionDraft.key===briefKey?d.sectionDraft.name:'Review';
  const identity={epoch:state.scopeEpoch,production:current?.id||null,asset:asset?.id};
  const source=state.available.find(item=>item.id===(d.sourceDraft.key===briefKey?d.sourceDraft.id:''))||state.available[0];
  const referenceLabel=d.referenceDraft.key===briefKey?d.referenceDraft.text:'';
  const newKind=d.kindDraft.key===briefKey?d.kindDraft.kind:KINDS[0],newIntent=d.intentDraft.key===briefKey?d.intentDraft.text:'';
  const brief=d.briefDraft.key===briefKey?d.briefDraft:{key:briefKey,baseRevision:current?.revision||0,
    title:current?.title||'',brief:{...emptyBrief,...current?.brief}};
  const assetKey=briefKey+':'+(asset?.id||'none');
  const assetValues=d.assetDraft.key===assetKey?d.assetDraft:{key:assetKey,baseRevision:current?.revision||0,
    intent:asset?.intent||'',position:asset?.position||0,depends_on:asset?.depends_on||[],
    references:(asset?.references||[]).map(ref=>ref.id)};
  const setAssetValues=values=>d.setAssetDraft({...assetValues,...values});
  const button=(label,action,disabled=false,always=false,primary=false,props={})=>h(Button,{...props,className:'ms-btn pd-btn'+(primary?' pd-primary':''),
    variant:primary?'default':'outline',disabled:busy||(!always&&state.pending)||disabled,onClick:action},label);
  const showSection=name=>{setNotice(null);if(name!==section)controller.current?.clear();d.setSectionDraft({key:briefKey,name});};
  const saveBrief=async()=>{
    const submitted=brief,result=await controller.current?.saveBrief({title:submitted.title,brief:submitted.brief,
      expected:submitted.baseRevision},identity);
    if(!result?.receipt)return;
    d.setBriefDraft(draft=>{if(draft.key!==briefKey)return draft;
      return sameBrief(draft,submitted)?{key:null}:{...draft,baseRevision:result.receipt.revision};});
  };
  const saveAsset=async()=>{
    const submitted=assetValues,result=await controller.current?.updateAsset({asset:asset.id,kind:asset.kind,
      intent:submitted.intent,position:submitted.position,depends_on:submitted.depends_on,
      references:submitted.references,expected:submitted.baseRevision},identity);
    if(!result?.receipt)return;
    d.setAssetDraft(draft=>{if(draft.key!==assetKey)return draft;
      const unchanged=JSON.stringify(draft)===JSON.stringify(submitted);
      return unchanged?{key:null}:{...draft,baseRevision:result.receipt.revision};});
  };
  const createProduction=async()=>{
    if(!brief.title.trim()||!brief.brief.text.trim())return;
    setNotice(null);
    const owner=controller.current,result=await owner?.create({title:brief.title,brief:brief.brief,kinds:KINDS},identity);
    const saved=owner?.state.current;
    if(result?.receipt&&controller.current===owner&&owner.state.scopeEpoch===identity.epoch&&saved){
      const key=identity.epoch+':'+saved.id;
      d.setBriefDraft({key:null});d.setSectionDraft({key,name:'Plan'});setNotice({key,text:'Project created.'});
    }
  };
  const refine=()=>{d.setRefine({key:assetKey,take:take?.id||null});const box=document.getElementById('production-direction');box?.scrollIntoView({block:'nearest'});box?.focus();};
  const panel=section==='Brief'?h(BriefPanel,{brief,current,busy,button,saveBrief,createProduction,discard:()=>d.setBriefDraft({key:null}),focusRequest:notice?.key===briefKey?notice.focusRequest:null,
      setBrief:(key,value)=>d.setBriefDraft({...brief,[key]:value}),setBriefField:(key,value)=>d.setBriefDraft({...brief,brief:{...brief.brief,[key]:value}})}):
    section==='Plan'?h(ProductionPlan,{assets,asset,current,busy,controller,briefKey,newKind,newIntent,setKindDraft:d.setKindDraft,
      setIntentDraft:d.setIntentDraft,identity,assetValues,setAssetValues,saveAsset,setAssetDraft:d.setAssetDraft,button}):
    section==='References'?h(ReferencesPanel,{state,current,asset,source,referenceLabel,busy,button,controller,identity,
      setSource:id=>d.setSourceDraft({key:briefKey,id}),setLabel:text=>d.setReferenceDraft({key:briefKey,text})}):
    section==='Outputs'?h(OutputsPanel,{state,assets,controller}):
    h(ProductionReview,{state,asset,take,button,identity,audio,controller:controller.current,onRefine:refine});
  return h('section',{className:'ms production-shell','aria-label':'Production workspace'},h('style',null,productionStyles),
    h('div',{className:'ms-inner'},h(MotionHeader,{active:'production',onCreate:onQuickCreate,onProduction:()=>{},status:plainStatus(state.status),
        helpOpen:d.helpOpen,onHelp:()=>d.setHelpOpen(!d.helpOpen)}),
      h(HelpPanel,{open:d.helpOpen,onClose:()=>d.setHelpOpen(false),title:'Production',guide:PRODUCTION_HELP.guide}),
      state.needsConnection||state.connectionStatus?h('div',{className:'ms-notice','aria-label':'Chat connection'},
        h('p',{'aria-live':'polite'},state.connectionStatus||'Connect this chat to use its Production workflow.'),
        button(state.connecting?'Connecting…':'Connect this chat',()=>controller.current?.admit(),false,false,true)):null,
      h('div',{className:'production-body'},
        h(ProjectBar,{state,current,busy,section,button,controller,onSection:showSection,
          onNew:()=>{if(busy||state.pending)return;controller.current?.newBrief();
            const key=state.scopeEpoch+':new';d.setBriefDraft({key:null});d.setSectionDraft({key,name:'Brief'});
            setNotice({key,focusRequest:{},text:'New project — give it a title and a brief, then Create project.'});}}),
        notice?.key===briefKey?h('p',{className:'production-notice',role:'status'},notice.text):null,
        current?h('details',{className:'production-howto'},h('summary',null,'How Production works'),h(QuickHelp,{steps:PRODUCTION_HELP.quick})):
          h(QuickHelp,{steps:PRODUCTION_HELP.quick}),
        h('div',{className:'production-layout','data-project':String(Boolean(current))},
          current?h(PlanRail,{section,showSection,assets,asset,busy,current,controller}):null,
          h('main',{className:'production-main','aria-label':'Production '+section},panel),
          current?h(CreatePanel,{state,asset,assets,current,identity,controller:controller.current,onSection:showSection,
            refineTake:d.refine.key===assetKey?d.refine.take:null,onRefineDone:()=>d.setRefine({key:null,take:null})}):null))));
}
