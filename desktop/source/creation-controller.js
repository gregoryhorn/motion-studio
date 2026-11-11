// Insert a draft into a chat's composer. Desktop only accepts drafts into a composer
// that is on screen, so if the panel covers it we open that chat first, then retry.
// Never sends: the user reviews and presses Send.
async function insertDraft(host,session,text){
  const composer=host?.composer;if(!composer?.insertText)return false;
  if(await composer.insertText(session,text,{mode:'block'}))return true;
  if(typeof host.openSession!=='function')return false;
  try{await host.openSession(session);}catch{return false;}
  for(let i=0;i<10;i++){
    await new Promise(resolve=>setTimeout(resolve,250));
    if(await composer.insertText(session,text,{mode:'block'})){try{composer.focus?.(session);}catch{}return true;}
  }
  return false;
}
// AFC: observation and exact retained bytes only; generation stays in chat tools.
import {openTechnical} from './transport.js';
import {readRetained} from './retained-bytes.js';

const methods=new Set(['list','status','admit','admit_music','stop','chunk','review','select','methods']);
const denials=new Set(['MUSIC_SCOPE_REVIEW_REQUIRED','MUSIC_WORKFLOW_REVIEW_REQUIRED','MUSIC_POLICY_CHANGED',
  'MUSIC_BINDING_DENIED','CREATION_ACCESS_UNAVAILABLE','CREATION_SCOPE_DENIED',
  'CREATION_WORKFLOW_REVIEW_REQUIRED','CREATION_RETIRED','CREATION_STORE_REVIEW_REQUIRED']);
const command=()=>crypto.randomUUID().replaceAll('-','');
// Legacy local Errors carry only a message. Recognize exact fixed codes, never arbitrary text.
const legacyCodes=new Set(['CREATION_PRIMARY_UNAVAILABLE','TECHNICAL_PRIMARY_UNAVAILABLE','INVALID_METHODS_INPUT',
  'CREATION_INTEGRITY_FAILED','CREATION_CHUNK_INVALID','RETAINED_SCOPE_CHANGED','RETAINED_FILE_MISSING',
  'RETAINED_FILE_CORRUPT','STALE_REVISION','LOCAL_GPU_BUSY','CREATION_CONTEXT_REQUIRED','CREATION_EFFECT_REVIEW_REQUIRED',
  'CREATION_STORE_BUSY','INVALID_CREATION_INPUT','CREATION_OPERATION_UNAVAILABLE','CREATION_UNRESOLVED',
  'CREATION_PREPARATION_UNCERTAIN','CREATION_PREPARATION_CHANGED','CREATION_COMMAND_CONFLICT','CREATION_NO_EFFECT_UNPROVEN',
  'CREATION_CONTRACT_DRIFT','CREATION_TOOL_COLLISION','COMMAND_CONFLICT','REQUEST_NOT_FOUND','TAKE_NOT_FOUND',
  'RUN_NOT_FOUND','TAKE_SCOPE_MISMATCH','UNSAFE_STATE_HOME','UNSUPPORTED_OPERATION',...denials]);
const workspaceErrorCode=error=>typeof error?.code==='string'&&/^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$/.test(error.code)?error.code:
  legacyCodes.has(error?.message)?error.message:null;
export class CreationController {
  constructor(host,notify=()=>{},clock=globalThis){
    this.host=host;this.notify=notify;this.client=null;this.epoch=0;this.disposed=false;this.url=null;
    this.clock=clock;this.timer=null;this.watching=false;this.observing=false;this.delay=1000;
    this.state={rows:[],selected:null,busy:false,scopeEpoch:this.epoch,status:'Describe a sound in the selected Hermes chat. No work started.',url:null};
  }
  emit(values){if(this.disposed)return;Object.assign(this.state,values,{scopeEpoch:this.epoch});this.notify({...this.state});}
  clear(){if(this.url)URL.revokeObjectURL(this.url);this.url=null;this.emit({url:null});}
  failure(error,fallback='Reply unobserved. This action may have reached the server. Reopen saved state before another action; no automatic retry.'){
    const code=workspaceErrorCode(error);if(denials.has(code))this.invalidate();this.emit({busy:false,status:code||fallback,
      needsConnection:code==='CREATION_WORKFLOW_REVIEW_REQUIRED'||code==='MUSIC_WORKFLOW_REVIEW_REQUIRED'});}
  valid(epoch,client=this.client){return !this.disposed&&!this.state.draftsInvalidated&&epoch===this.epoch&&client?.current();}
  stopObservation(){this.observing=false;if(this.timer!==null)this.clock.clearTimeout(this.timer);this.timer=null;}
  invalidate(clearDrafts=true){this.waitingForChat=!this.host.state?.focusedSessionId?.get();this.stopObservation();this.epoch++;this.methodsLoading=null;this.clear();this.emit({rows:[],selected:null,busy:false,connecting:false,connectionStatus:null,needsConnection:clearDrafts&&!this.waitingForChat,methods:null,methodsError:null,draftsInvalidated:clearDrafts,status:this.waitingForChat?'CREATION_PRIMARY_UNAVAILABLE':'Selected chat/profile/connection changed. Reopen; no work replayed.'});}
  observe(){this.watching=true;return this.open();}
  schedule(){
    if(this.timer!==null)this.clock.clearTimeout(this.timer);this.timer=null;
    if(!this.observing||!this.valid(this.epoch))return;
    this.timer=this.clock.setTimeout(()=>{this.timer=null;void this.refresh(true);},this.delay);
  }
  publish(result,automatic=false){
    const rows=result.creations,selected=rows.some(row=>row.request===this.state.selected)?this.state.selected:rows[0]?.request||null;
    const changed=JSON.stringify(rows)!==JSON.stringify(this.state.rows);
    const active=rows.some(row=>['Prepared','Starting','Running','Cancelling','Collecting'].includes(row.state)||row.recovery?.state==='Applying');
    this.delay=changed||active?1000:Math.min(8000,this.delay*2);
    if(selected!==this.state.selected)this.clear();
    this.emit({rows,selected,busy:false,method:result.method,...(!automatic?{status:'Saved progress observed. No replay.'}:{})});
  }
  watchFocusedChat(){
    if(this.stopFocusedChat)return;
    const focused=this.host.state?.focusedSessionId;if(!focused?.subscribe)return;
    let previous=focused.get(),serial=0;
    this.stopFocusedChat=focused.subscribe(value=>{
      const changed=value!==previous;previous=value;if(changed)serial++;
      if(!value)this.waitingForChat=true;
      if(!changed||!value||!this.waitingForChat||this.disposed)return;
      const ticket=serial;
      queueMicrotask(()=>{
        if(this.disposed||ticket!==serial||focused.get()!==value)return;
        this.waitingForChat=false;void this.open();
      });
    });
  }
  async open(){
    this.watchFocusedChat();this.waitingForChat=!this.host.state?.focusedSessionId?.get();
    this.client?.dispose();this.invalidate(false);const epoch=this.epoch;this.emit({busy:true});
    try{
      const client=await openTechnical(this.host,()=>this.invalidate(),{namespace:'creation',methods});
      if(this.disposed||epoch!==this.epoch){client.dispose();return;}
      this.client=client;
      const result=await client.request('list');
      if(!this.valid(epoch,client))return;
      this.publish(result);this.delay=1000;this.observing=this.watching;
      this.emit({status:'Saved creations opened. No generation dispatched.'});this.schedule();
    }catch(error){if(!this.disposed&&epoch===this.epoch){this.stopObservation();this.failure(error);}}
  }
  async refresh(automatic=false){
    const client=this.client,epoch=this.epoch;if(!this.valid(epoch,client))return;
    if(this.state.busy){this.schedule();return;}
    this.emit({busy:true});
    try{const result=await client.request('list');if(!this.valid(epoch,client))return;
      this.publish(result,automatic);this.observing=this.watching;
    }catch(error){if(this.valid(epoch,client)){this.stopObservation();this.failure(error);}}
    finally{if(this.valid(epoch,client))this.schedule();}
  }
  choose(request){if(this.state.busy)return;this.clear();this.emit({selected:request});}
  async admit(operation='admit'){
    if(this.disposed||this.state.busy||!['admit','admit_music'].includes(operation))return;
    // Connect is an explicit reopen, never a request on the old latched transport.
    this.client?.dispose();this.invalidate(false);const epoch=this.epoch;
    this.emit({busy:true,connecting:true,connectionStatus:'Connecting…',status:'Connecting…'});
    try{
      const client=await openTechnical(this.host,()=>this.invalidate(),{namespace:'creation',methods});
      if(this.disposed||epoch!==this.epoch){client.dispose();return;}this.client=client;
      await client.request(operation);if(!this.valid(epoch,client))return;
      const result=await client.request('list');if(!this.valid(epoch,client))return;
      this.publish(result);this.observing=this.watching;this.schedule();
      this.emit({busy:false,connecting:false,needsConnection:false,connectionStatus:'This chat is connected',status:'This chat is connected'});
    }catch(error){if(!this.disposed&&epoch===this.epoch){this.failure(error);
      this.emit({connecting:false,connectionStatus:'Cannot connect this chat. Check the selected chat and its configured access, then try again.'});}}
  }
  selected(){return this.state.rows.find(row=>row.request===this.state.selected);}
  async action(operation,take,outcome){
    const row=this.selected(),client=this.client,epoch=this.epoch;
    if(!row||!this.valid(epoch,client)||this.state.busy)return;
    const payload=operation==='stop'?Object.fromEntries(['request','revision','command','run'].map(key=>[key,row[key]])):
      {request:row.request,take,command:command(),...(operation==='review'?{outcome}:{revision:row.revision})};
    this.emit({busy:true});
    try{await client.request(operation,payload);if(!this.valid(epoch,client))return;
      this.emit({busy:false});await this.refresh();
    }catch(error){if(this.valid(epoch,client))this.failure(error);}
  }
  async load(take){
    const row=this.selected(),client=this.client,epoch=this.epoch;
    if(!row||!this.valid(epoch,client)||this.state.busy)return;
    this.clear();this.emit({busy:true,status:'Loading the original file...'});
    try{
      const result=await readRetained(client,'chunk',()=>({request:row.request,take}),
        ()=>this.valid(epoch,client)&&this.state.selected===row.request);
      if(!this.valid(epoch,client)||this.state.selected!==row.request)return;
      const item=(row.takes||[]).find(item=>item.id===take),descriptor=result.descriptor||item?.descriptor;
      const mime=descriptor?.mime||result.mime||item?.facts?.mime||({Image:'image/png',Video:'video/mp4'})[row.kind]||'audio/wav';
      this.url=URL.createObjectURL(new Blob([result.bytes],{type:mime}));
      this.emit({url:this.url,take,mime,descriptor,busy:false,status:(row.kind==='Music'||item?.facts?.voice_lineage?'Retained derivative bytes verified. ':'Original bytes verified. ')+'Listening/viewing review and destination delivery remain separate.'});
    }catch(error){if(this.valid(epoch,client))this.failure(error,'The saved file could not be retrieved. Retry retrieval only; do not regenerate.');}
  }
  async refine(text,append=false,identity={epoch:this.epoch,request:this.state.selected}){
    const row=this.selected(),client=this.client,epoch=this.epoch;
    if(!row||identity.epoch!==epoch||identity.request!==row.request||!text.trim()||!this.valid(epoch,client)||this.state.busy||!this.host.composer?.getDraft||!this.host.composer?.insertText)return;
    this.emit({busy:true});
    try{
      const existing=await this.host.composer.getDraft(client.session);
      if(!this.valid(epoch,client)||this.state.selected!==row.request)return;
      if(existing&&!append){this.emit({busy:false,status:'Chat already has a draft. Choose Append to existing draft to preserve it.'});return;}
      const draft='Refine Motion Studio creation '+row.request+' as a deliberately new take (parent='+row.request+'): '+text;
      // Append only: never replace a draft that changed during the asynchronous read.
      const applied=await insertDraft(this.host,client.session,draft);
      if(!this.valid(epoch,client))return;
      this.emit({busy:false,status:applied?'Draft added to selected chat. Review it and press the visible Send; nothing sent.':'No matching visible composer. Nothing sent; no fallback.'});
    }catch{if(this.valid(epoch,client))this.emit({busy:false,status:'Composer unavailable. Nothing sent; no fallback.'});}
  }
  // Available methods + cost basis per media kind (read-only, cheap, no generation).
  async loadMethods(client){
    const epoch=this.epoch;if(!this.valid(epoch,client)||this.state.methods||this.methodsLoading)return;
    const token={};this.methodsLoading=token;this.emit({methodsError:null});
    try{const result=await client.request('methods');if(!this.valid(epoch,client))return;
      if(!result?.kinds||typeof result.kinds!=='object')throw Error('INVALID_METHODS_INPUT');
      this.emit({methods:result,methodsError:null});}
    catch(error){if(this.valid(epoch,client)){const code=workspaceErrorCode(error);
      if(denials.has(code))this.failure(error);else this.emit({methodsError:code||'INVALID_METHODS_INPUT'});}}
    finally{if(this.methodsLoading===token)this.methodsLoading=null;}
  }
  // New request: drafts a plain-language Motion Studio request into the selected chat.
  // The user reviews and presses Send; nothing is generated or sent from here.
  async request(text,kind='Sound effects',append=false,method=null){
    const client=this.client,epoch=this.epoch,value=String(text||'').trim();
    if(!value||this.state.busy)return;
    if(method&&(method.id==='import'||method.engine==='import'||method.action==='import')){
      this.emit({status:'Import uses an existing file. Open Production and choose Import a take; nothing sent.'});return;}
    if(method?.available===false){this.emit({status:'The selected method is unavailable. Choose an alternative deliberately; nothing sent.'});return;}
    const session=this.valid(epoch,client)?client.session:null;
    if(!session||!this.host.composer?.getDraft||!this.host.composer?.insertText){
      this.emit({status:'Click your Motion Studio chat in the sidebar once, then try again. Nothing sent.'});return;}
    this.emit({busy:true});
    try{
      const existing=await this.host.composer.getDraft(session);
      if(!this.valid(epoch,client))return;
      if(existing&&!append){this.emit({busy:false,status:'Chat already has a draft. Choose Add to existing draft to keep it.'});return;}
      const applied=await insertDraft(this.host,session,'Motion Studio - create '+kind+(method?' (method: '+method.label+' ['+method.id+'], cost: '+method.cost+')':'')+': '+value);
      if(!this.valid(epoch,client))return;
      this.emit({busy:false,status:applied?'Request added to your chat. Review it and press Send.':'No visible chat composer. Nothing sent.'});
    }catch{this.emit({busy:false,status:"Chat composer unavailable. Nothing sent."});}
  }
  dispose(){this.stopFocusedChat?.();this.stopObservation();this.disposed=true;this.epoch++;this.client?.dispose();if(this.url)URL.revokeObjectURL(this.url);this.url=null;}
}
