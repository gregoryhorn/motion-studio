import {createElement as h,useEffect,useRef,useState} from 'react';
import {Button,Textarea} from '@hermes/plugin-sdk';
import {creationStyles} from './creation-style.js';
import {workspaceStatus} from './workspace-copy.js';
import {CREATE_HELP,QuickHelp,HelpPanel} from './help.js';
import {MethodPicker,chosenMethod} from './methods-ui.js';
import {TakeChecks} from './director-take.js';
import {kindIcon} from './production-plan.js';
const KIND_NOTES={Video:'Video cost and entitlement depend on the selected route. Unknown cost is not free; review before spending.',Music:'Local music engine not enabled yet \u2014 you can import a track.'};

const MEDIA=['Sound effects','Music','Voice','Image','Video'];
const DONE=['Ready for review','Stopped','Failed'];
// A short creator-facing title: the first clause of the saved request.
export function shortTitle(text){
  const value=String(text||'Untitled creation').trim(),first=value.split(/(?<=[.!?])\s|,\s/)[0]||value;
  return first.length>64?first.slice(0,61).trimEnd()+'…':first.replace(/[.]$/,'');
}
function tone(state){return state==='Ready for review'?'good':state==='Failed'?'warn':undefined;}
function badge(text,t){return text?h('span',{className:'ms-badge','data-tone':t},text):null;}

export function MotionHeader({active,onCreate,onProduction,status,helpOpen=false,onHelp,onTools}){
  const tab=(label,key,action)=>h('button',{type:'button',className:'ms-tab','aria-current':active===key?'page':undefined,onClick:action},label);
  return h('header',{className:'ms-top'},
    h('div',{className:'ms-brand'},h('span',{className:'ms-mark','aria-hidden':true}),'Motion Studio'),
    h('nav',{className:'ms-tabs','aria-label':'Workspace'},tab('Quick Create','create',onCreate),tab('Production','production',onProduction)),
    h('div',{className:'ms-spacer'}),
    h('p',{className:'ms-status',role:'status'},status),
    onTools?h('button',{type:'button',className:'ms-tab',onClick:onTools},'Tools'):null,
    onHelp?h('button',{type:'button',className:'ms-tab','aria-expanded':String(helpOpen),onClick:onHelp},helpOpen?'Close help':'Help'):null);
}

// Relative time for a saved creation, only when the row carries a usable timestamp.
export function relativeTime(value,now=Date.now()){
  const time=typeof value==='number'?(value<1e12?value*1000:value):Date.parse(value||'');
  if(!Number.isFinite(time))return null;
  const minutes=Math.max(0,Math.round((now-time)/60000));
  return minutes<1?'just now':minutes<60?minutes+' min ago':minutes<1440?Math.round(minutes/60)+' h ago':Math.round(minutes/1440)+' d ago';
}
const rowDuration=row=>{const value=row.takes?.[0]?.descriptor?.duration??row.takes?.[0]?.facts?.duration??row.defaults?.seconds;return Number.isFinite(value)&&value>0?Math.round(value*10)/10+' s':null;};
const reviewState=row=>row.state==='Ready for review'&&row.takes?.some(take=>{
  const qa=take.descriptor?.qa;return !qa||qa.perceptual!=='Matches request'||qa.useEligibility==='Not assessed'||
    qa.outstanding?.some(check=>!/user approval/i.test(check));
})?'Checking output':row.state;

const EXT={'audio/wav':'wav','audio/x-wav':'wav','audio/mpeg':'mp3','image/png':'png','image/jpeg':'jpeg','image/webp':'webp','video/mp4':'mp4','video/webm':'webm'};
const TOOLS={image_gen:'image generation',tts:'text to speech',video_gen:'video generation'};
// What a take is, from its recorded MIME when present and otherwise from the creation's media type.
export function takeMedia(kind,take){
  const mime=String(take?.descriptor?.mime||take?.facts?.mime||''),form=mime.startsWith('image/')||(!mime&&kind==='Image')?'image':
    mime.startsWith('video/')||(!mime&&kind==='Video')?'video':'audio';
  return {form,ext:EXT[mime]||{image:'png',video:'mp4',audio:'wav'}[form]};
}
export function originLabel(origin){
  const value=String(origin||''),tool=/^hermes_tool:(.+)$/.exec(value)?.[1];
  if(tool)return 'Made with Hermes '+(TOOLS[tool]||tool.replaceAll('_',' '))+'.';
  return value==='test_fixture'?'TEST ONLY - not generated.':/import/i.test(value)?'Imported file - structural validation only.':'Generated - see Crystal Ball report and your separate review.';
}

// The file's real type, read from its first bytes, so a JPEG is never offered as a PNG.
const SIGNATURES=[['png',[0x89,0x50,0x4e,0x47]],['jpeg',[0xff,0xd8,0xff]],['gif',[0x47,0x49,0x46,0x38]],['wav',[0x52,0x49,0x46,0x46]],['mp3',[0x49,0x44,0x33]],['webm',[0x1a,0x45,0xdf,0xa3]]];
function useFileType(url,fallback){
  const [found,setFound]=useState({url:null,ext:null});
  useEffect(()=>{let live=true;if(!url||typeof fetch!=='function')return()=>{};
    fetch(url).then(reply=>reply.blob()).then(blob=>blob.slice(0,12).arrayBuffer()).then(buffer=>{
      const bytes=new Uint8Array(buffer),match=SIGNATURES.find(([,magic])=>magic.every((value,index)=>bytes[index]===value));
      const ext=match?.[0]||(String.fromCharCode(...bytes.slice(4,8))==='ftyp'?'mp4':null);
      if(live&&ext)setFound({url,ext:ext==='wav'&&String.fromCharCode(...bytes.slice(8,12))==='WEBP'?'webp':ext});}).catch(()=>{});
    return()=>{live=false;};},[url]);
  return found.url===url&&found.ext?found.ext:fallback;
}
// Unsent text survives switching between Quick Create and Production (this window only, never stored).
const emptyDraft=()=>({text:'',kind:'Sound effects'});
const kept={draft:emptyDraft(),refinements:{},host:null,scope:null,stops:[],notify:null};
// Keep only a content-free authority guard while the page is unmounted. Away-and-back
// transitions still clear private drafts before another workspace can restore them.
function guardDrafts(host,notify){
  const keys=['focusedSessionId','focusedSessionOwner','connectionId','profile','gateway'];
  const snapshot=()=>JSON.stringify(keys.map(key=>{const value=host.state?.[key]?.get?.();
    return key==='focusedSessionOwner'&&value?{connectionId:value.connectionId,profile:value.profile}:value;}));
  const reset=()=>{kept.draft=emptyDraft();kept.refinements={};kept.notify?.();};
  kept.notify=notify;
  if(kept.host===host){if(kept.scope!==snapshot()){kept.scope=snapshot();reset();}return;}
  kept.stops.splice(0).forEach(stop=>stop());
  if(kept.host)reset();kept.host=host;kept.scope=snapshot();
  for(const key of keys){const stop=host.state?.[key]?.subscribe?.(()=>{
    const scope=snapshot();if(scope!==kept.scope){kept.scope=scope;reset();}
  });if(stop)kept.stops.push(stop);}
}

function ImageTake({url,ext,index}){
  const [open,setOpen]=useState(false),[zoom,setZoom]=useState('fit'),[width,setWidth]=useState(null);
  return h('div',{className:'ms-take-player'},
    h('button',{type:'button',className:'ms-thumb','aria-expanded':String(open),'aria-label':(open?'Close':'Open')+' zoom viewer for take '+(index+1),
      onClick:()=>setOpen(!open)},h('img',{src:url,alt:'Take '+(index+1)+' image',onLoad:event=>setWidth(event.target.naturalWidth)})),
    open?h('div',{className:'ms-zoom'},
      h('label',{className:'ms-zoom-bar'},'Zoom',h('select',{'aria-label':'Image zoom',value:zoom,onChange:event=>setZoom(event.target.value)},
        h('option',{value:'fit'},'Fit'),h('option',{value:'100'},'100%'),h('option',{value:'200'},'200%'))),
      h('div',{className:'ms-zoom-view',tabIndex:0,role:'region','aria-label':'Image viewer - arrow keys scroll when zoomed in'},
        h('img',{src:url,alt:'Take '+(index+1)+' image, enlarged',style:zoom==='fit'?{width:'100%',maxHeight:'70vh',objectFit:'contain'}:
          {width:width?width*Number(zoom)/100:undefined,maxWidth:'none'}}))):null,
    h('a',{className:'ms-link',href:url,download:'motion-studio-original.'+ext},'Save / download original '+ext.toUpperCase()));
}

// Keep result copy fixed and use the controller's confirmed outcome, never exceptions.
export function actionResult(status,{kind='status',rows=[],changed=[],confirmed}={}){
  const good=confirmed??/^(Saved creations opened|Saved progress observed|Request added to your chat|Draft added to selected chat|Original bytes verified|Retained derivative bytes verified|Reviewed server policy associated|This chat is connected)/.test(status||'');
  let text=workspaceStatus(status)||'The action could not be confirmed. Reopen saved progress.';
  if(good&&kind==='chat')text='Added to your chat — press Send there →';
  if(good&&kind==='list')text=rows.length+' creation'+(rows.length===1?'':'s')+' · '+text;
  return {text,tone:good?'good':'warn',changed:good?changed:[]};
}
function useActionFeedback(controller,scope){
  const [items,setItems]=useState({}),[latest,setLatest]=useState(null),timers=useRef(new Map()),live=useRef(true),lock=useRef(false),serial=useRef(0),allowedScope=useRef(scope);
  const activeRun=useRef(null);
  useEffect(()=>{live.current=true;return()=>{live.current=false;timers.current.forEach(clearTimeout);timers.current.clear();};},[]);
  useEffect(()=>{if(allowedScope.current===scope)return;allowedScope.current=scope;
    if(!/^[A-Z][A-Z0-9_]+$/.test(controller.current?.state.status||'')){activeRun.current=null;lock.current=false;}
    timers.current.forEach(clearTimeout);timers.current.clear();setItems({});setLatest(null);},[scope]);
  const run=async(id,action,options={})=>{
    if(controller.current?.state.scopeEpoch!==scope)return;
    if(lock.current)return;lock.current=true;
    const ticket={};activeRun.current=ticket;
    const current=controller.current,before=new Map((current?.state.rows||[]).map(row=>[row.request,JSON.stringify(row)]));
    clearTimeout(timers.current.get(id));timers.current.delete(id);
    setItems(items=>({...items,[id]:{pending:true,text:options.pendingMessage,tone:options.pendingMessage?'good':undefined}}));
    let failed=false,epoch=current?.state.scopeEpoch;
    try{const work=action();epoch=current?.state.scopeEpoch;allowedScope.current=epoch;await work;}catch{failed=true;}
    // Give even a synchronous method choice a visible busy frame.
    await new Promise(resolve=>setTimeout(resolve,180));
    if(activeRun.current!==ticket)return;
    lock.current=false;
    if(!live.current||controller.current!==current)return;
    const scopeChanged=current?.state.scopeEpoch!==epoch;
    // A coded refusal may clear the workspace itself; still show that refusal beside its action.
    if(scopeChanged&&!/^[A-Z][A-Z0-9_]+$/.test(current?.state.status||''))return;
    const rows=current?.state.rows||[],changed=rows.filter(row=>before.get(row.request)!==JSON.stringify(row)).map(row=>row.request);
    const confirmed=failed||scopeChanged?false:options.confirm?Boolean(options.confirm(current?.state)):undefined;
    const result={...actionResult(failed?'The action could not be confirmed. Reopen saved progress.':current?.state.status,
      {...options,rows,changed,confirmed}),stamp:++serial.current};
    if(options.success&&confirmed)result.text=typeof options.success==='function'?options.success():options.success;
    setItems(items=>({...items,[id]:result}));setLatest(result);
    clearTimeout(timers.current.get(id));
    timers.current.set(id,setTimeout(()=>{if(!live.current)return;setItems(items=>{const next={...items};delete next[id];return next;});
      setLatest(value=>value?.stamp===result.stamp?null:value);timers.current.delete(id);},6000));
  };
  return {items,latest,run,busy:Object.values(items).some(item=>item.pending)};
}
function InlineResult({result}){
  return h('span',{className:'ms-action-result','aria-live':'polite','aria-atomic':'true','data-tone':result?.tone},result?.text||null);
}
function FeedbackButton({feedback,id,label,working='Working…',action,options,disabled=false,primary=false,...props}){
  const result=feedback.items[id],pending=Boolean(result?.pending);
  return h('span',{className:'ms-action'},h(Button,{type:'button',className:'ms-btn'+(primary?' ms-btn-primary':''),variant:primary?'default':'outline',...props,
    disabled:disabled||feedback.busy,'aria-busy':pending,onClick:()=>feedback.run(id,action,options)},
    pending?h('span',{className:'ms-busy-dot','aria-hidden':true}):null,pending?working:label),h(InlineResult,{result}));
}

function TakeCard({take,index,selected,busy,controller,state,feedback}){
  const kind=selected.kind||'Sound effects',music=kind==='Music',derivative=music||Boolean(take.facts?.voice_lineage||take.facts?.lineage)||/derivative/i.test(take.descriptor?.qualityRole||''),{form,ext:guess}=takeMedia(kind,take),player=useRef(null),wantPlay=useRef(false);
  const loaded=Boolean(state.url&&state.take===take.id),visual=form!=='audio',ext=useFileType(loaded&&!music?state.url:null,guess),playMessage=useRef('');
  // The Play click is the user action: start once the checked file has loaded. Never on mount.
  useEffect(()=>{if(loaded&&wantPlay.current){wantPlay.current=false;player.current?.play?.()?.catch?.(()=>{});}
    if(!loaded&&!busy)wantPlay.current=false;},[loaded,busy]);
  const play=async()=>{if(loaded){const node=player.current;if(node){const starting=node.paused;await(starting?node.play():node.pause());playMessage.current=starting?'Playing this take.':'Playback paused.';}return;}
    playMessage.current=form==='image'?'Image ready to view.':'Player ready — use Play / pause.';
    wantPlay.current=form!=='image';await controller().load(take.id);};
  const takeButton=(id,label,working,action,options={},props={})=>h(FeedbackButton,{feedback,id:take.id+':'+id,label,working,action,options,disabled:busy,...props});
  const verdict=(label,name,outcome)=>takeButton(outcome,label,'Saving…',()=>controller().action('review',take.id,outcome),
    {confirm:value=>/^Saved progress observed/.test(value.status)&&value.rows.find(row=>row.request===selected.request)?.takes?.find(item=>item.id===take.id)?.review===outcome,success:outcome==='Matches request'?'Review saved — matches request.':'Review saved — needs work.'},
    {className:'ms-seg-btn','aria-label':name,'aria-pressed':take.review===outcome});
  const pulse=Object.entries(feedback.items).filter(([id,result])=>id.startsWith(take.id+':')&&!id.endsWith(':play')&&result.tone==='good').at(-1)?.[1]?.stamp;
  const descriptor=take.descriptor,qa=descriptor?.qa;
  const loadName=derivative?'Load retained derivative '+form:'Load original '+form;
  return h('article',{className:'ms-take','data-selected':String(Boolean(take.selected)),'data-form':form,'aria-label':'Take '+(index+1)},
    h('div',{className:'ms-take-head'},h('span',null,'Take '+(index+1)),
      h('span',{key:pulse,className:'ms-row'+(pulse?' ms-feedback-pulse':'')},take.selected?badge('Selected','good'):null,badge(take.review||'Not reviewed',take.review==='Matches request'?'good':take.review==='Needs work'?'warn':undefined))),
    h('p',{className:'ms-help',style:{marginTop:0}},originLabel(take.origin)),
    descriptor?h('p',{className:'ms-help'},[descriptor.mime,descriptor.byteLength+' bytes',descriptor.width&&descriptor.height?descriptor.width+' × '+descriptor.height:null,
      descriptor.duration?descriptor.duration+' s':null,'Quality role: '+descriptor.qualityRole].filter(Boolean).join(' · ')):null,
    qa?h('p',{className:'ms-help'},'Technical: '+qa.technical+'. Perceptual: '+qa.perceptual+'. Use eligibility: '+qa.useEligibility+'. User approval: '+qa.userApproval+'. Outstanding: '+(qa.outstanding?.join('; ')||'none recorded')+'.'):null,
    h(TakeChecks,{host:controller().host,request:selected.request,take,onChanged:()=>controller().refresh()}),
    derivative?h('p',{className:'ms-notice'},'Retained derivative; source retained separately. Conversion is not an original-format download.'):null,
    take.facts?.voice_lineage?h('p',{className:'ms-help'},'Voice conversion: source '+String(take.facts.voice_lineage.native?.format||'format not recorded').toUpperCase()+' retained; review/download derivative is mono 44.1 kHz PCM16 WAV.'):null,
    h('div',{className:'ms-row'},
      takeButton('play',form==='image'?(loaded?'Image loaded':'Show image'):loaded?'Play / pause':'Play','Loading…',play,{confirm:value=>Boolean(value.url&&value.take===take.id),success:()=>playMessage.current},{primary:true,'aria-label':loadName,disabled:busy||(form==='image'&&loaded)}),
      takeButton('choose',take.selected?'Chosen':'Choose','Choosing…',()=>controller().action('select',take.id),{confirm:value=>/^Saved progress observed/.test(value.status)&&Boolean(value.rows.find(row=>row.request===selected.request)?.takes?.find(item=>item.id===take.id)?.selected),success:'Take chosen.'},{'aria-label':'Choose this take',disabled:busy||take.selected}),
      h('div',{className:'ms-seg',role:'group','aria-label':visual?'How does it look?':'How did it sound?'},verdict(visual?'Looks right':'Sounds right',(visual?'Reviewed':'Listened')+': matches request','Matches request'),
        verdict('Needs work',(visual?'Reviewed':'Listened')+': needs work','Needs work'))),
    !loaded?null:form==='image'?h(ImageTake,{url:state.url,ext,index}):h('div',{className:'ms-take-player'},
      h(form==='video'?'video':'audio',{ref:player,controls:true,playsInline:true,preload:'metadata',src:state.url,
        'aria-label':derivative?'Retained derivative '+form:'Original '+form}),
      h('a',{className:'ms-link',href:state.url,download:derivative?'motion-studio-derivative.'+ext:'motion-studio-original.'+ext},
        derivative?'Save / download derivative '+ext.toUpperCase():'Save / download original '+ext.toUpperCase())));
}

function RequestText({text}){
  const [open,setOpen]=useState(false),long=String(text||'').length>150;
  return h('div',{className:'ms-request-wrap'},h('p',{className:'ms-request','data-clamp':String(long&&!open)},text),
    long?h('button',{type:'button',className:'ms-linkish','aria-expanded':String(open),onClick:()=>setOpen(!open)},open?'Show less':'Show full request'):null);
}

function Review({state,selected,controller,refinement,setRefinement,onProduction,feedback}){
  const busy=state.busy,music=selected.kind==='Music',d=selected.defaults;
  const key=state.selected,text=refinement[key]||'';
  const identity={epoch:state.scopeEpoch,request:state.selected};
  const button=(id,label,working,action,options={},disabled=false)=>h(FeedbackButton,{feedback,id:selected.request+':'+id,label,working,action,options,disabled:busy||disabled});
  const running=selected.run&&!DONE.includes(selected.state);
  return h('section',{className:'ms-panel','aria-label':'Selected creation'},
    h('div',{className:'ms-meta',style:{marginTop:0,marginBottom:10}},badge(selected.kind||'Sound effects'),badge(reviewState(selected),tone(reviewState(selected))),badge(rowDuration(selected))),
    h('h2',null,shortTitle(selected.direction)),
    h(RequestText,{key:selected.request,text:selected.direction}),
    selected.next_action?h('p',{className:'ms-notice'},selected.next_action):null,
    selected.effect_review?h('p',{className:'ms-notice'},'Local effect review is missing. Draft retained; no generation authorized.'):null,
    selected.recovery?h('p',{className:'ms-notice'},selected.recovery.state+': '+selected.recovery.next_action):null,
    running?h('div',{className:'ms-row',style:{marginTop:14}},button('stop','Stop requested work','Stopping…',()=>controller().action('stop'))):null,
    h('div',{className:'ms-block'},h('h3',{className:'ms-section-title'},'Takes'),
      (selected.takes||[]).length?h('div',{className:'ms-takes'},...selected.takes.map((take,index)=>h(TakeCard,{key:take.id,take,index,selected,busy,controller,state,feedback}))):
        h('p',{className:'ms-empty'},'No takes yet. Progress updates here while Hermes works.'),
      ),
    h('div',{className:'ms-row',style:{marginTop:12}},button('production','Open Production →','Opening…',async()=>{
      await new Promise(resolve=>setTimeout(resolve,220));if(controller()?.state.scopeEpoch===identity.epoch)onProduction();
    },{confirm:()=>true,pendingMessage:'Opening Production → link this take under References.',success:'Opening Production — link this take under References.'})),
    h('p',{className:'ms-help'},'Then link this saved take under References; opening Production does not copy or select it.'),
    h('div',{className:'ms-block'},h('label',{className:'ms-label',htmlFor:'ms-refine'},'Ask for a variation'),
      h(Textarea,{id:'ms-refine','aria-label':'Change for another take',placeholder:'e.g. Make it shorter with a softer ending',value:text,maxLength:2000,
        onChange:event=>setRefinement({...refinement,[key]:event.target.value})}),
      h('div',{className:'ms-row',style:{marginTop:10}},
        button('refine','Put refinement in selected chat','Adding to chat…',()=>controller().refine(text,false,identity),{kind:'chat'},!text.trim()),
        button('append','Append to existing draft','Adding to chat…',()=>controller().refine(text,true,identity),{kind:'chat'},!text.trim())),
      h('p',{className:'ms-help'},'Adds a draft to the selected chat. You review it and press Send.')),
    h('details',{className:'ms-tech'},h('summary',null,'Technical details'),
      h('p',null,'Saved creation '+selected.request),
      h('p',null,(selected.method||state.method||'Saved request')+' - local fixed tool; no provider fallback. Saved parameters: '+(d?d.seconds+' seconds / seed '+d.seed+' / '+d.steps+' steps':'no qualified method prepared')),
      h('p',null,music?'Music rights/use and listening unqualified. Only same-output collection recovery; no generation retry.':'Noncommercial local technical evaluation only. No commercial clearance. One supported bounded recovery may occur; no blind retries.'),
      selected.disclosure?h('p',null,selected.disclosure):null,
      h('p',null,'Progress: '+selected.state+'; certainty: '+selected.certainty+(selected.failure?'; '+selected.failure:''))));
}

export function CreationPage({createController,onProduction=()=>{},onTools}){
  const controller=useRef(null),[state,setState]=useState(null),[refinement,keepRefinement]=useState(kept.refinements);
  const [draft,keepDraft]=useState(kept.draft),[helpOpen,setHelpOpen]=useState(false);
  const setDraft=value=>{kept.draft=value;keepDraft(value);},setRefinement=value=>{kept.refinements=value;keepRefinement(value);};
  const pickKind=(event,index)=>{const step={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[event.key];if(!step)return;
    event.preventDefault();const next=MEDIA[(index+step+MEDIA.length)%MEDIA.length];setDraft({...draft,kind:next,method:undefined});
    event.currentTarget.parentElement?.children[(index+step+MEDIA.length)%MEDIA.length]?.focus();};
  useEffect(()=>{const reset=()=>{keepDraft(kept.draft);keepRefinement(kept.refinements);};
    const current=createController(value=>{if(value.draftsInvalidated){kept.draft=emptyDraft();kept.refinements={};reset();}setState(value);});
    controller.current=current;guardDrafts(current.host,reset);setState({...current.state});
    void current.observe();
    return()=>{kept.notify=null;current.dispose();controller.current=null;};},[createController]);
  useEffect(()=>{const current=controller.current;if(current?.client&&!state?.methods&&!state?.methodsError)void current.loadMethods(current.client);},[state?.rows,state?.methods,state?.methodsError]);
  const feedback=useActionFeedback(controller,state?.scopeEpoch);
  if(!state)return h('p',null,'Motion Studio - no work started.');
  const selected=state.rows.find(row=>row.request===state.selected),busy=state.busy,c=()=>controller.current;
  const btn=(text,action,primary)=>h(FeedbackButton,{feedback,id:text,label:text,working:text.startsWith('Open')?'Opening…':text.startsWith('Connect')?'Connecting…':'Refreshing…',action,primary,disabled:busy,options:{kind:/Open|Refresh/.test(text)?'list':'status'}});
  const picked=chosenMethod(state.methods,draft.kind,draft.method),importing=picked?.id==='import'||picked?.engine==='import';
  const kinds=new Set(state.rows.map(row=>row.kind||'Sound effects'));
  return h('section',{className:'ms creation-shell'},h('style',null,creationStyles),h('div',{className:'ms-inner'},
    h(MotionHeader,{active:'create',onCreate:()=>{},onProduction,onTools,status:feedback.latest?.text||workspaceStatus(state.status),helpOpen,onHelp:()=>setHelpOpen(!helpOpen)}),
    h(HelpPanel,{open:helpOpen,onClose:()=>setHelpOpen(false),title:'Quick Create',guide:CREATE_HELP.guide}),
    h('div',{className:'ms-hero'},
      h('div',null,h('h1',null,'What would you like to make?'),
        h('p',{className:'ms-sub'},'Describe the result. Hermes handles the production steps, and your takes appear below to play, view, compare and keep.'))),
    h(QuickHelp,{steps:CREATE_HELP.quick}),
    state.needsConnection||state.connectionStatus?h('div',{className:'ms-notice','aria-label':'Chat connection'},
      h('p',{'aria-live':'polite'},state.connectionStatus||'Connect this chat to use its creation workflow.'),
      h(Button,{className:'ms-btn ms-btn-primary',disabled:busy,onClick:()=>c().admit()},state.connecting?'Connecting…':'Connect this chat')):null,
    h('div',{className:'ms-composer'},
      h('label',{className:'ms-visually-hidden',htmlFor:'ms-request'},'Describe what you want to make'),
      h(Textarea,{id:'ms-request',value:draft.text,maxLength:4000,placeholder:'e.g. An 8-second loop of rain on a tin roof. No voices or music.',
        onChange:event=>setDraft({...draft,text:event.target.value})}),
      h('div',{className:'ms-composer-bar'},
        h('div',{className:'ms-chips',role:'radiogroup','aria-label':'Media type'},...MEDIA.map((kind,index)=>h('button',{key:kind,type:'button',role:'radio',
          className:'ms-chip','data-on':String(draft.kind===kind),'aria-checked':String(draft.kind===kind),tabIndex:draft.kind===kind?0:-1,
          onKeyDown:event=>pickKind(event,index),onClick:()=>setDraft({...draft,kind,method:undefined})},kind))),
        h('div',{className:'ms-row'},
          h(FeedbackButton,{feedback,id:'Create in chat',label:'Create in chat',working:'Adding to chat…',disabled:busy||importing||picked?.available===false||!draft.text.trim(),action:()=>c().request(draft.text,draft.kind,false,chosenMethod(state.methods,draft.kind,draft.method)),options:{kind:'chat'}}),
          h(FeedbackButton,{feedback,id:'Add to existing draft',label:'Add to existing draft',working:'Adding to chat…',disabled:busy||importing||picked?.available===false||!draft.text.trim(),action:()=>c().request(draft.text,draft.kind,true,chosenMethod(state.methods,draft.kind,draft.method)),options:{kind:'chat'}}))),
      h('fieldset',{className:'ms-method-feedback',disabled:busy||feedback.busy,'aria-busy':Boolean(feedback.items.method?.pending)},
        h(MethodPicker,{methods:state.methods,loadingError:Boolean(state.methodsError),kind:draft.kind,choice:draft.method,
          onChoose:method=>feedback.run('method',()=>setDraft({...draft,method}),{confirm:()=>true,success:'Method selected — '+(chosenMethod(state.methods,draft.kind,method)?.label||'selected option')+'.'})}),
        feedback.items.method?.pending?h('span',{className:'ms-help'},h('span',{className:'ms-busy-dot','aria-hidden':true}),'Selecting…'):null,h(InlineResult,{result:feedback.items.method}))),
    state.methodsError?h('div',{className:'ms-notice',role:'status'},workspaceStatus(state.methodsError),' ',
      h(FeedbackButton,{feedback,id:'retry-methods',label:'Retry method loading',working:'Loading…',action:()=>c().loadMethods(c().client),options:{confirm:value=>Boolean(value.methods),success:'Methods loaded.'}})):null,
    importing?h('p',{className:'ms-help ms-kind-note',role:'note',style:{marginBottom:4}},'Import brings in a file you already have, so there is nothing to create here. Open Production and use Import a take.'):null,
    h('p',{className:'ms-help',style:{marginBottom:KIND_NOTES[draft.kind]?4:28}},'Puts your request in the selected Hermes chat. You press Send; Hermes asks only if something important is missing. '),
    KIND_NOTES[draft.kind]?h('p',{className:'ms-help ms-kind-note',role:'note',style:{marginBottom:28}},KIND_NOTES[draft.kind]):null,
    h('div',{className:'ms-toolbar'},h('h2',{className:'ms-section-title',style:{margin:0}},'Recent creations'),h('div',{className:'ms-spacer'}),
      btn('Open saved creations',()=>c().open()),btn('Refresh progress',()=>c().refresh()),
      h('details',{className:'ms-more'},h('summary',{className:'ms-tab'},'Connections'),
        h('div',{className:'ms-row ms-more-body'},btn('Connect this chat',()=>c().admit()),btn('Connect Music workflow',()=>c().admit('admit_music'))))),
    h('div',{className:'ms-grid'},
      h('aside',{'aria-label':'Saved creations'},
        state.rows.length?h('div',{className:'ms-list'},...state.rows.map(row=>h('div',{key:row.request,className:'ms-card-action'},h('button',{key:feedback.latest?.changed?.includes(row.request)?feedback.latest.stamp:0,type:'button',className:'ms-card'+(feedback.latest?.changed?.includes(row.request)?' ms-card-changed':''),'aria-pressed':String(row.request===state.selected),
          disabled:busy||feedback.busy,'aria-busy':Boolean(feedback.items['card:'+row.request]?.pending),title:row.direction,
          onClick:()=>feedback.run('card:'+row.request,()=>c().choose(row.request),{confirm:value=>value.selected===row.request,success:'Creation opened — review its takes.'})},
          h('div',{className:'ms-card-title'},h('span',{className:'ms-card-icon',title:row.kind||'Sound effects'},kindIcon(row.kind||'Sound effects')),h('span',{className:'ms-card-text'},shortTitle(row.direction))),
          feedback.items['card:'+row.request]?.pending?h('span',null,h('span',{className:'ms-busy-dot','aria-hidden':true}),'Opening…'):null,
          h('div',{className:'ms-meta'},badge(row.kind||'Sound effects'),badge(reviewState(row),tone(reviewState(row))),badge(rowDuration(row)),
            h('span',{className:'ms-card-time'},relativeTime(row.updated_at??row.created_at??row.updated??row.created)))),h(InlineResult,{result:feedback.items['card:'+row.request]})))):
          h('p',{className:'ms-empty'},'No saved creations opened for this chat.')),
      selected?h(Review,{state,selected,controller:c,refinement,setRefinement,onProduction,feedback}):
        h('section',{className:'ms-panel ms-empty'},'Select a saved creation to play or view its takes, review them and choose one. Opening and viewing never generate.'))));
}
