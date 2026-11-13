import {createElement as h,useEffect,useRef,useMemo,useState} from 'react';
import {Button} from '@hermes/plugin-sdk';
import {MediaReview} from './media-review.js';
import {createImportedReviewReader,createRetainedReviewReader} from './media-review-controller.js';
import {ProductionComparison} from './production-comparison.js';
import {TakeChecks} from './director-take.js';
import {MethodPicker,chosenMethod} from './methods-ui.js';

const NOTES={Video:'Cost depends on the selected method and account. Unknown cost is not free; review any spend before sending.',Music:'Local music generation is not qualified yet. You can import a track below.'};

const KINDS=['Sound effects','Music','Voice','Image','Video'];
const two=value=>String(value).padStart(2,'0');
const originLabel=origin=>origin==='user_import'?'Imported':origin==='test_fixture'?'Test file':'Generated';
const badge=(text,tone)=>text?h('span',{className:'ms-badge','data-tone':tone},text):null;
const isChosen=(asset,item)=>Boolean(item&&(item.selected||item.id===asset?.selected_take));
// Decorative level bars for audio stages; carries no information about the file.
const bars=()=>h('div',{className:'production-wave','aria-hidden':true},...Array.from({length:44},(_,index)=>
  h('i',{key:index,style:{height:(18+Math.round(70*Math.abs(Math.sin(index*1.7)*Math.cos(index*.45))))+'%'}})));

export function ProductionImport({controller,state,asset,identity}){
  const input=useRef(null),[chosen,setChosen]=useState('');
  useEffect(()=>{void controller?.loadImportRequests?.();},[controller,identity.epoch,asset?.id]);
  const requests=(state.importRequests||[]).filter(item=>item.kind===asset?.kind);
  const request=requests.find(item=>item.request===chosen)||requests[0];
  return h('section',{className:'production-import','aria-label':'Import a take'},
    h('input',{ref:input,type:'file',hidden:true,accept:'image/png,image/jpeg,audio/wav,video/mp4',
      'aria-label':'Original media file',onChange:event=>{const file=event.target.files?.[0];event.target.value='';
        if(file)void controller.importTake(file,request,identity);}}),
    h(Button,{className:'ms-btn pd-btn pd-wide',variant:'outline',disabled:state.busy||state.pending,onClick:()=>input.current?.click()},'Import a take'),
    h('p',{className:'ms-help production-center'},'Made in another tool? Bring it here. PNG, JPEG, WAV or MP4, up to 16 MB.'),
    requests.length>1?h('label',null,'Add it to this request',h('select',{'aria-label':'Import saved request',value:request?.request||'',disabled:state.busy,
      onChange:event=>setChosen(event.target.value)},
      ...requests.map(item=>h('option',{key:item.request,value:item.request},item.direction||item.kind+' request')))):null,
    !requests.length?h('p',{className:'ms-help production-center'},'Import directly into this asset. No sent request or generation is needed.'):null,
    state.importing?h('div',{className:'production-row'},h('progress',{max:100,value:state.importProgress||0,'aria-label':'Import progress'}),
      h('span',{role:'status'},' '+(state.importProgress||0)+'%'),
      h(Button,{className:'ms-btn pd-btn',variant:'outline',onClick:()=>controller.cancelImport()},'Cancel import')):null);
}

export function ProductionMediaReview({review,controller,asset,selectedTake,single=false}){
  const reader=useMemo(()=>{
    const options={client:review.client,valid:()=>review.valid()};
    const imported=createImportedReviewReader({...options,operation:'media_import.read_chunk'});
    const retained=createRetainedReviewReader({...options,operation:'chunk'});
    return args=>(asset.takes.find(take=>take.id===args.descriptor.identity.take)?.origin==='user_import'?imported:retained)(args);
  },[review,asset]);
  const register=useMemo(()=>value=>{controller.reviewCleanup=value?()=>value.dispose():null;
    const selected=review.descriptors.find(item=>item.identity.take===selectedTake)||review.descriptors[0];
    if(value&&selected)value.choose('A',selected);},[controller,review,selectedTake]);
  return h(MediaReview,{scope:review.scope,descriptors:review.descriptors,readBytes:reader,
    isScopeCurrent:review.valid,onController:register,single});
}

// Right column: draft a request for the selected asset, or bring a finished file in.
export function CreatePanel({state,asset,assets,current,identity,controller,onSection,refineTake=null,onRefineDone=()=>{}}){
  const [,redraw]=useState(0),directions=controller.directionDrafts;
  useEffect(()=>{if(controller?.loadMethods&&!state.methods&&!state.methodsError)void controller.loadMethods();},[controller,state.methods,state.methodsError,identity.epoch]);
  const key=(current?.id||'')+':'+(asset?.id||''),draft=directions?.get(key),text=draft?.text??asset?.intent??'';
  const setDraft=value=>{if(!controller.identityValid(identity))return;directions?.set(key,{...directions.get(key),...value});redraw(count=>count+1);};
  const takes=asset?.takes||[],refining=takes.find(item=>item.id===refineTake)||null;
  const picked=state.methods?chosenMethod(state.methods,asset?.kind,draft?.method):null;
  const importing=picked?.id==='import'||picked?.engine==='import'||picked?.action==='import';
  const unavailable=Boolean(draft?.method&&(!picked||!picked.available));
  // The chat request names exactly what is on screen: the asset, the take being refined and the pinned references.
  const request=()=>[text.trim(),'[Motion Studio context: production '+current.id+', asset '+asset.id+
    (refining?'; refine take '+refining.id+' of request '+refining.request+' as a new take, keeping the earlier one':'')+
    ((asset.references||[]).length?'; references '+asset.references.map(ref=>ref.id+' revision '+ref.revision).join(', '):'')+
    (picked?'; preferred method '+picked.id:'')+']'].join('\n');
  const send=async append=>{
    if(importing||unavailable)return;
    const sent=directions?.get(key);
    const applied=await controller.createWithHermes(asset,request(),{...identity,revision:current.revision},append);
    if(applied&&controller.identityValid(identity)){
      if(directions?.get(key)===sent)directions?.delete(key);
      onRefineDone();redraw(count=>count+1);
    }
  };
  const blocked=state.busy||state.pending,references=(asset?.references||[]).map(ref=>
    (current?.references||[]).find(item=>item.id===ref.id)?.label||'Reference');
  return h('aside',{className:'production-create','aria-label':'Create with Hermes'},
    h('h2',null,'Create with Hermes'),
    h('div',{className:'production-kinds',role:'group','aria-label':'Media type'},...KINDS.map(kind=>{
      const target=assets.find(item=>item.kind===kind),on=asset?.kind===kind;
      return h('button',{key:kind,type:'button',className:'production-kind','aria-pressed':on,disabled:state.busy||!target,
        title:target?'Show the '+kind+' asset':'No '+kind+' asset in the plan yet',
        onClick:()=>{if(!on&&target)controller?.chooseAsset(target.id);}},kind);})),
    !asset?h('p',{className:'ms-empty'},current?'Add an asset to the plan, then describe what you want here.':'Create a project first.'):
    h('div',{className:'production-create-body'},
      h('label',{htmlFor:'production-direction'},'Direction for '+two(asset.position+1)+' '+asset.kind),
      h('textarea',{id:'production-direction',value:text,maxLength:2000,disabled:state.busy,
        placeholder:'Describe the take you want, e.g. a soft door close with a short room echo',
        onChange:event=>setDraft({text:event.target.value})}),
      h('div',{className:'production-refs'},h('span',{className:'production-label'},'References'),
        h('div',{className:'ms-row'},...references.map((label,index)=>h('span',{key:index,className:'ms-chip'},label)),
          h('button',{type:'button',className:'ms-chip production-chip-add',onClick:()=>onSection('References')},'+ Add'))),
      refining?h('p',{className:'ms-row production-refining'},h('span',{className:'ms-chip','data-on':'true'},'Refining take '+two(takes.indexOf(refining)+1)),
        h('button',{type:'button',className:'production-linkish',onClick:onRefineDone},'Start fresh instead')):null,
      state.methods?h(MethodPicker,{methods:state.methods,kind:asset.kind,choice:draft?.method,idPrefix:'production-method',
        onChoose:id=>setDraft({method:id})}):null,
      state.methodsError?h('p',{role:'status'},'Method information unavailable. ',h('button',{type:'button',disabled:state.methodsLoading,
        onClick:()=>controller.loadMethods()},'Retry methods')):null,
      state.methodsLoading?h('p',{role:'status'},'Checking methods. Nothing is started.'):null,
      NOTES[asset.kind]?h('p',{className:'ms-help production-kind-note',role:'note'},NOTES[asset.kind]):null,
      h(Button,{className:'ms-btn pd-btn pd-primary pd-wide',disabled:blocked||!text.trim()||importing||unavailable,
        onClick:()=>send(false)},'Create with Hermes'),
      importing?h('p',{className:'ms-help'},'Import is not generation. Use Import a take below to choose an existing file.'):null,
      state.draftAsset===asset.id?h(Button,{className:'ms-btn pd-btn pd-wide',variant:'outline',disabled:blocked||!text.trim()||importing||unavailable,
        onClick:()=>send(true)},'Add to existing draft'):null,
      h('p',{className:'ms-help production-center'},'Puts a request in your Hermes chat. You review it and press Send.'),
      h('hr',{className:'production-rule'}),
      h(ProductionImport,{controller,state,asset,identity}),
      h('hr',{className:'production-rule'}),
      h('p',{className:'ms-help production-center'},'References and original takes stay with the project.')));
}

function Stage({state,asset,take,index,audio,controller,current,onUse,onClose,identity,single}){
  if(state.comparisonOpen)return h(ProductionComparison,{key:state.scopeEpoch+':'+asset.id+':'+current.revision,controller,asset,identity,onUse,onClose});
  if(state.mediaReview)return h('div',{className:'production-viewer production-viewer-open'},
    h(ProductionMediaReview,{review:state.mediaReview,controller,asset,selectedTake:state.selectedTake,single}));
  if(!take)return h('div',{className:'production-viewer'},h('p',{className:'production-viewer-title'},'No takes yet'),
    h('p',{className:'production-muted'},'Use Create with Hermes to ask for one, or import a file you already have.'));
  const loaded=state.url&&state.urlTake===take.id,sound=asset.kind!=='Image'&&asset.kind!=='Video';
  return h('div',{className:'production-viewer'},sound?bars():h('div',{className:'production-frame','aria-hidden':true}),
    h('p',{className:'production-viewer-title'},'Take '+two(index+1)+' / '+asset.kind),
    loaded?h('div',{className:'production-player'},h('audio',{ref:audio,controls:true,src:state.url,'aria-label':'Selected take audio'}),
      h('a',{className:'ms-link',href:state.url,download:'motion-studio-production-original.wav'},'Save / download original WAV')):
      h('p',{className:'production-muted'},'Nothing plays until you press Play.'));
}

// Center column: selected asset, large viewer, then the takes strip and its actions.
export function ProductionReview({state,asset,take,button,identity,audio,controller,onRefine}){
  const compareButton=useRef(null),restoreFocus=useRef(false),current=state.current,busy=state.busy,[single,setSingle]=useState(true);
  useEffect(()=>{if(restoreFocus.current&&!state.comparisonOpen&&!busy){restoreFocus.current=false;compareButton.current?.focus();}},
    [state.comparisonOpen,busy]);
  if(!asset)return h('section',{className:'production-review','aria-label':'Review'},h('div',{className:'production-viewer'},
    h('p',{className:'production-viewer-title'},current?'No assets yet':'No project open'),
    h('p',{className:'production-muted'},current?'Open Plan and add the first thing this project needs.':'Open a project or write a brief to start one.')));
  const takes=asset.takes||[],index=take?takes.findIndex(item=>item.id===take.id):-1,chosen=isChosen(asset,take);
  const stale=Boolean(asset.stale&&chosen),loaded=take&&state.url&&state.urlTake===take.id;
  const playable=take&&asset.kind==='Sound effects'&&take.origin!=='user_import';
  const play=()=>{if(!loaded)return controller.load(take);const node=audio.current;if(node)void(node.paused?node.play():node.pause());};
  const viewerOpen=Boolean(state.mediaReview||state.comparisonOpen);
  return h('section',{className:'production-review','aria-label':'Review'},
    h('h2',{className:'production-title'},h('span',{className:'production-title-n'},two(asset.position+1)+' /'),' '+(asset.intent||asset.kind)),
    h('p',{className:'production-muted production-sub'},asset.kind+' - '+(takes.length===1?'1 take':takes.length+' takes')),
    h(Stage,{state,asset,take,index,audio,controller,current,identity,single,onUse:()=>{restoreFocus.current=true;},
      onClose:()=>{restoreFocus.current=true;controller.clear();}}),
    take?h('div',{className:'production-statusline'},
      viewerOpen?button('Close viewer',()=>controller.clear()):playable?button(loaded?'Play / pause':'Play',play):button('Open viewer',()=>{setSingle(true);controller.prepareMediaReview();}),
      h('span',{className:'production-take-state','data-on':String(chosen)},'Take '+two(index+1)+(chosen?' - Selected':' - Not selected')),
      badge(take.review||'Not reviewed',take.review==='Approved'?'good':undefined),badge(originLabel(take.origin)),
      stale?badge('Out of date','warn'):null):null,
    take?h(TakeChecks,{key:take.id,host:controller.host,request:take.request,take,onChanged:()=>controller.refresh()}):null,
    h('div',{className:'production-takes-head'},h('h3',{className:'ms-section-title'},'Takes'),
      h('div',{className:'production-row'},
        h(Button,{className:'ms-btn pd-btn',variant:'outline',ref:compareButton,disabled:busy||state.pending||takes.length<2,
          onClick:()=>{setSingle(false);if(asset.kind==='Sound effects')controller.compare();else controller.prepareMediaReview();}},'Compare'),
        button(stale?'Keep this take':'Use take',()=>controller.select(take,identity),!take||(chosen&&!asset.stale)),
        button('Refine',onRefine,!take))),
    takes.length?h('div',{className:'production-takes',role:'group','aria-label':'Takes for this asset'},...takes.map((item,position)=>{
      const on=isChosen(asset,item);
      return h('button',{key:item.id,type:'button',className:'production-take','aria-pressed':item.id===take?.id,'data-selected':String(on),disabled:busy,
        onClick:()=>controller.chooseTake(item.id)},h('span',{className:'production-take-thumb','aria-hidden':true},bars()),
        h('span',{className:'production-take-name'},'Take '+two(position+1)+(on?' - Selected':'')),
        h('span',{className:'ms-meta'},badge(item.review||'Not reviewed',item.review==='Approved'?'good':undefined),badge(originLabel(item.origin)),
          on&&asset.stale?badge('Out of date','warn'):null));})):
      h('p',{className:'ms-empty'},'Takes for this asset appear here.'),
    h('p',{className:'ms-help'},'Compare puts two takes side by side without changing anything. Use take makes the open take the one this asset exports. Refine starts a follow-up request for the open take in Create with Hermes.'),
    take?h('details',{className:'ms-tech'},h('summary',null,'Technical details'),
      h('p',null,'Take '+take.id),take.artifact?h('p',null,'File '+take.artifact):null,
      h('p',null,'Source: '+(take.origin||'unknown')+(take.source_request_revision?' / request revision '+take.source_request_revision:''))):null);
}
