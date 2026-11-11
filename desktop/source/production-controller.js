import {openTechnical} from './transport.js';
import {readRetained} from './retained-bytes.js';
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
const methods=new Set(['list','open','admit','create','update_brief','add_asset','update_asset',
  'add_reference','update_reference','link_take','select_take','chunk','describe',
  ...['intent','begin','chunk','status','commit','cancel','describe','read_chunk'].map(name=>'media_import.'+name),
  ...['prepare','descriptor','chunk','close'].map(name=>'export.'+name)]);
const safeRejections=new Set(['PRODUCTION_STALE_REVISION','PRODUCTION_ASSET_NOT_FOUND',
  'PRODUCTION_REFERENCE_NOT_FOUND','PRODUCTION_MEDIA_KIND_MISMATCH','PRODUCTION_DEPENDENCY_INVALID',
  'PRODUCTION_DEPENDENCY_CYCLE','PRODUCTION_TAKE_NOT_LINKED']);
const recoveryKey='motion-studio.production.unresolved-create-v1';
const authorityDenials=new Set(['PRODUCTION_ACCESS_UNAVAILABLE','PRODUCTION_SCOPE_DENIED',
  'PRODUCTION_WORKFLOW_REVIEW_REQUIRED','PRODUCTION_TAKE_SCOPE_MISMATCH',
  'CREATION_ACCESS_UNAVAILABLE','CREATION_CONTEXT_REQUIRED','CREATION_SCOPE_DENIED',
  'CREATION_WORKFLOW_REVIEW_REQUIRED','CREATION_STORE_REVIEW_REQUIRED','CREATION_RETIRED',
  'MUSIC_SCOPE_REVIEW_REQUIRED','MUSIC_WORKFLOW_REVIEW_REQUIRED','MUSIC_POLICY_CHANGED',
  'MUSIC_BINDING_DENIED','MUSIC_EFFECT_REVIEW_REQUIRED']);
export function productionMessage(code,fallback='This action is unavailable. Refresh the saved project and try again.'){
  code=code||fallback;
  const messages={PRODUCTION_PRIMARY_UNAVAILABLE:'Open or select a Motion Studio chat in the sidebar, then come back here.',
    PRODUCTION_STALE_REVISION:'The project changed. Refresh before saving this edit.',
    PRODUCTION_OPERATION_UNAVAILABLE:'The reply could not be confirmed. Reopen the project before trying again.',
    CREATION_INTEGRITY_FAILED:'The original bytes could not be verified. Reopen the take and try again.',
    RETAINED_SCOPE_CHANGED:'The selected chat or take changed. Reopen the original.'};
  if(messages[code])return messages[code];
  if(authorityDenials.has(code)||/SCOPE|ACCESS|PRIMARY|POLICY|BINDING/.test(code||''))return 'This chat cannot access that media. Reopen the matching profile and chat.';
  if(/REVISION|STALE/.test(code||''))return 'Saved inputs changed. Refresh and review the current selection.';
  return /^[A-Z][A-Z0-9_]+$/.test(fallback)?'This action is unavailable. Reopen the matching chat and project.':fallback;
}
const command=()=>crypto.randomUUID().replaceAll('-','');
// Window-only drafts survive workspace unmount, but not any authority transition,
// including an away-and-back transition while Production is unmounted.
const draftOwners=new WeakMap();
function draftsFor(host){
  if(draftOwners.has(host))return draftOwners.get(host);
  const drafts=new Map();draftOwners.set(host,drafts);
  for(const key of ['focusedSessionId','focusedSessionOwner','connectionId','profile','gateway']){
    let prior=JSON.stringify(host.state[key]?.get());
    host.state[key]?.subscribe(value=>{const next=JSON.stringify(value);if(next!==prior)drafts.clear();prior=next;});
  }
  return drafts;
}
function records(){try{return JSON.parse(globalThis.localStorage?.getItem(recoveryKey)||'{}');}catch{return {};}}
function stored(scope){const value=records()[scope];return value?.operation==='create'&&/^[a-f0-9]{32}$/.test(value.command)?value:null;}
function retain(scope,pending){try{const all=records();all[scope]={operation:'create',command:pending.command};
  globalThis.localStorage.setItem(recoveryKey,JSON.stringify(all));return stored(scope)?.command===pending.command;}catch{return false;}}
function releaseStored(scope,pending){try{const all=records();if(all[scope]?.command===pending?.command){delete all[scope];
  if(Object.keys(all).length)globalThis.localStorage.setItem(recoveryKey,JSON.stringify(all));
  else globalThis.localStorage.removeItem(recoveryKey);}}catch{/* Memory lock remains fail-closed. */}}
export class ProductionController{
  constructor(host,notify=()=>{}){
    this.host=host;this.directionDrafts=draftsFor(host);this.notify=notify;this.client=null;this.epoch=0;this.disposed=false;this.url=null;
    this.pendingScope=this.scope();this.pending=this.restore();this.state={productions:[],current:null,available:[],capabilities:{},selectedAsset:null,
      selectedTake:null,busy:false,pending:Boolean(this.pending),scopeEpoch:0,methods:null,methodsLoading:false,methodsError:false,
      status:this.pending?'Unresolved Create restored. Reconcile exactly; replacement Create is locked.':
        'Open a saved Production or create a brief. No work started.',url:null,urlTake:null};
  }
  scope(){return JSON.stringify({root:this.host.state.focusedSessionId?.get()||'',
    connection:this.host.state.connectionId?.get()||'',profile:this.host.state.profile?.get()||''});}
  restore(){const value=stored(this.scope());return value?{operation:'create',command:value.command,payload:null}:null;}
  bindRecovery(){
    const scope=this.scope(),restored=this.restore();
    if(scope!==this.pendingScope)this.pending=restored;
    else if(restored&&restored.command!==this.pending?.command)this.pending=restored;
    this.pendingScope=scope;
  }
  release(pending){if(this.pending===pending)this.pending=null;releaseStored(this.scope(),pending);}
  emit(values){if(this.disposed)return;Object.assign(this.state,values,{scopeEpoch:this.epoch});this.notify({...this.state});}
  clear(){const cleanup=this.reviewCleanup;this.reviewCleanup=null;cleanup?.();
    this.loadSerial=(this.loadSerial||0)+1;
    this.clearDownload();this.emit({mediaReview:null});
    if(this.loading){this.loading=false;this.emit({busy:false});}
    if(this.url)URL.revokeObjectURL(this.url);this.url=null;this.emit({url:null,urlTake:null,comparisonOpen:false});}
  compare(){
    const asset=this.state.current?.assets.find(item=>item.id===this.state.selectedAsset);
    if(!this.valid(this.epoch)||this.state.busy||this.state.comparisonOpen||asset?.kind!=='Sound effects'||asset.takes.length<2)return;
    if(asset.takes.some(take=>take.origin==='user_import'))return this.prepareMediaReview();
    this.clear();this.emit({comparisonOpen:true});
  }
  valid(epoch,client=this.client){return !this.disposed&&epoch===this.epoch&&client?.current();}
  identityValid(identity){return !identity||(identity.epoch===this.epoch&&
    identity.production===(this.state.current?.id||null)&&(identity.asset===undefined||identity.asset===this.state.selectedAsset)&&
    (identity.revision===undefined||identity.revision===this.state.current?.revision));}
  invalidate(){this.waitingForChat=!this.host.state?.focusedSessionId?.get();this.directionDrafts.clear();this.bindRecovery();this.epoch++;this.clear();this.emit({methods:null,methodsLoading:false,methodsError:false,productions:[],current:null,available:[],capabilities:{},selectedAsset:null,
    selectedTake:null,draftAsset:null,importRequests:[],importing:false,importProgress:null,busy:false,connecting:false,connectionStatus:null,needsConnection:!this.waitingForChat,pending:Boolean(this.pending),status:this.waitingForChat?'Open or select a Motion Studio chat in the sidebar, then come back here.':'Selected chat/profile/connection changed. Reopen; no command replayed.'});}
  resetForOpen(){this.importJob=null;this.emit({connecting:false,connectionStatus:null,needsConnection:false,methods:null,methodsLoading:false,methodsError:false,importRequests:[],draftAsset:null,importing:false,importProgress:null});this.client?.dispose();this.epoch++;this.clear();this.emit({current:null,available:[],selectedAsset:null,
    selectedTake:null,busy:false,pending:Boolean(this.pending)});}
  failure(error,fallback){
    if(authorityDenials.has(error.code)){
      // A server denial invalidates private view/draft ownership even if host atoms did not change.
      this.directionDrafts.clear();this.epoch++;this.client?.dispose();this.clear();
      this.emit({connectionStatus:null,methods:null,methodsLoading:false,methodsError:false,productions:[],current:null,available:[],capabilities:{},selectedAsset:null,selectedTake:null,
        importRequests:[],draftAsset:null,importing:false,importProgress:null});
      // Keep only the opaque recovery command across revoked authority; never replay private payload.
      if(this.pending)this.pending={...this.pending,payload:null};
    }
    this.emit({busy:false,pending:Boolean(this.pending),needsConnection:['PRODUCTION_WORKFLOW_REVIEW_REQUIRED','CREATION_WORKFLOW_REVIEW_REQUIRED'].includes(error.code),status:productionMessage(error.code,fallback)});
  }
  publish(result,status='Saved Production observed. Nothing generated.'){
    const current=result.current,assets=current?.assets||[];
    const selectedAsset=assets.some(a=>a.id===this.state.selectedAsset)?this.state.selectedAsset:assets[0]?.id||null;
    const asset=assets.find(a=>a.id===selectedAsset),takes=asset?.takes||[];
    const selectedTake=takes.some(t=>t.id===this.state.selectedTake)?this.state.selectedTake:asset?.selected_take||takes[0]?.id||null;
    if(this.state.comparisonOpen||selectedAsset!==this.state.selectedAsset||selectedTake!==this.state.selectedTake||
      current?.revision!==this.state.current?.revision)this.clear();
    this.emit({current,productions:result.productions||this.state.productions,available:result.available||[],
      capabilities:result.capabilities||{},selectedAsset,selectedTake,busy:false,pending:Boolean(this.pending),status});
  }
  observePending(result,productions=[]){
    const pending=this.pending;if(!pending)return;
    const match=pending.operation==='create'&&(result.current?.command===pending.command||
      productions.some(item=>item.command===pending.command));
    if(match){this.release(pending);this.emit({pending:false,status:'Lost Create reconciled from saved command. No duplicate dispatched.'});}
    else this.emit({pending:true,status:'Unresolved Create remains locked. An absent or failed list is not non-commit proof; reconcile again.'});
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
  async open(production=null){
    this.watchFocusedChat();this.waitingForChat=!this.host.state?.focusedSessionId?.get();
    this.resetForOpen();const epoch=this.epoch;this.emit({busy:true});let client;
    try{
      client=await openTechnical(this.host,()=>this.invalidate(),{namespace:'production',methods});
      if(this.disposed||epoch!==this.epoch){client.dispose();return;}this.client=client;
      this.bindRecovery();this.emit({pending:Boolean(this.pending)});
      const listed=await client.request('list');if(!this.valid(epoch,client))return;
      this.emit({productions:listed.productions,available:listed.available,capabilities:listed.capabilities});
      const pendingId=this.pending?.operation==='create'?
        listed.productions.find(item=>item.command===this.pending.command)?.id:null;
      if(this.pending?.operation==='create'&&!pendingId){
        this.publish({...listed,current:null},'Unresolved Create remains locked. Retry exact observation; no replacement is allowed.');return;
      }
      const id=pendingId||production||listed.productions[0]?.id;
      const result=id?await client.request('open',{production:id}):listed;
      if(!this.valid(epoch,client))return;
      this.publish({...result,productions:listed.productions},'Saved Production reopened. No mutation or generation dispatched.');
      this.observePending({...result,productions:listed.productions},listed.productions);
    }catch(error){if(!this.disposed&&epoch===this.epoch)this.failure(error,'PRODUCTION_ACCESS_UNAVAILABLE');}
  }
  async refresh(){
    const client=this.client,epoch=this.epoch,id=this.state.current?.id;
    if(!this.valid(epoch,client)||this.state.busy)return;this.emit({busy:true});
    try{const result=await client.request(id?'open':'list',id?{production:id}:{});if(!this.valid(epoch,client))return;
      this.publish(result,'Saved state observed. No command replayed.');this.observePending(result,result.productions||[]);
    }catch(error){if(this.valid(epoch,client))this.failure(error,'Reply unobserved. Reopen to reconcile; do not resubmit.');}
  }
  async admit(){
    if(this.disposed||this.state.busy||this.pending)return;
    this.resetForOpen();this.invalidate();const epoch=this.epoch;
    this.emit({busy:true,connecting:true,connectionStatus:'Connecting…',status:'Connecting…'});
    try{
      const client=await openTechnical(this.host,()=>this.invalidate(),{namespace:'production',methods});
      if(this.disposed||epoch!==this.epoch){client.dispose();return;}this.client=client;
      this.bindRecovery();
      if(this.pending){this.emit({busy:false,connecting:false,connectionStatus:'Check the interrupted save before connecting this chat.'});return;}
      await client.request('admit');if(!this.valid(epoch,client))return;
      const result=await client.request('list');if(!this.valid(epoch,client))return;
      this.publish({...result,current:null},'This chat is connected');
      this.emit({connecting:false,needsConnection:false,connectionStatus:'This chat is connected'});
    }catch(error){if(!this.disposed&&epoch===this.epoch){this.failure(error,'PRODUCTION_ACCESS_UNAVAILABLE');
      this.emit({connecting:false,connectionStatus:error.code==='CREATION_WORKFLOW_REVIEW_REQUIRED'?
        'Connect this chat in Quick Create first, then connect it to Production.':
        'Cannot connect this chat. Check the selected chat and its configured access, then try again.'});}}
  }
  newBrief(){if(this.state.busy||this.pending)return;this.clear();this.emit({draftAsset:null});this.emit({current:null,selectedAsset:null,selectedTake:null,
    status:'New Production brief. No saved head or command assumed.'});}
  chooseAsset(asset){if(this.state.busy)return;this.clear();this.emit({selectedAsset:asset,selectedTake:
    this.state.current?.assets.find(a=>a.id===asset)?.selected_take||null});}
  chooseTake(take){if(this.state.busy)return;this.clear();this.emit({selectedTake:take});}
  async mutate(operation,payload={},identity=null){
    const client=this.client,epoch=this.epoch,current=this.state.current;
    if(!this.identityValid(identity)){this.emit({status:'Stale visual scope rejected. Reopen and review current saved state.'});return;}
    if(operation==='create')this.bindRecovery();
    if(this.pending){this.emit({pending:true,status:'Uncertain command locked. Reconcile it before any replacement mutation.'});return;}
    if(!this.valid(epoch,client)||this.state.busy)return;
    const revisioned=operation!=='create';if(revisioned&&!current)return;
    const full={...payload,command:command(),...(revisioned?{production:current.id,expected:payload.expected??current.revision}:{})};
    const pending={operation,command:full.command,payload:full};
    if(operation==='create'&&!retain(this.scope(),pending)){
      this.emit({busy:false,pending:false,status:'Durable Create recovery marker unavailable. No command dispatched.'});return;
    }
    this.clear();this.pending=pending;this.emit({busy:true,pending:true});
    try{const result=await client.request(operation,full);if(!this.valid(epoch,client))return;
      this.release(pending);this.publish(result,result.replayed?'Original receipt returned; current head shown separately. No duplicate mutation.':
        'Saved Production revision '+result.current.revision+'. No media generated or copied.');return result;
    }catch(error){if(this.valid(epoch,client)){
      if(error.code&&safeRejections.has(error.code))this.release(pending);
      this.failure(error,'Reply unobserved. Command locked; open or reconcile exactly before acting. No automatic retry.');
    }}
  }
  async reconcilePending(){
    const pending=this.pending,client=this.client,epoch=this.epoch;
    if(!pending||this.state.busy)return;if(!pending.payload){await this.open();return;}
    if(!this.valid(epoch,client))return;this.emit({busy:true,pending:true});
    try{const result=await client.request(pending.operation,pending.payload);if(!this.valid(epoch,client))return;
      this.release(pending);this.publish(result,'Original pending receipt reconciled exactly. Current head shown; no replacement mutation.');return result;
    }catch(error){if(this.valid(epoch,client))this.failure(error,
      'Pending reply still unobserved. Command remains locked; no replacement or automatic retry.');}
  }
  create(fields,identity){return this.mutate('create',fields,identity);}
  saveBrief(fields,identity){return this.mutate('update_brief',fields,identity);}
  addAsset(kind,intent,identity){return this.mutate('add_asset',{kind,intent,depends_on:[],references:[]},identity);}
  updateAsset(fields,identity){return this.mutate('update_asset',fields,identity);}
  addReference(source,label,identity){return this.mutate('add_reference',{request:source.request,take:source.id,label},identity);}
  updateReference(reference,source,label,identity){return this.mutate('update_reference',{reference:reference.id,
    request:source.request,take:source.id,label},identity);}
  async link(source,identity){
    const result=await this.mutate('link_take',{asset:this.state.selectedAsset,request:source.request,take:source.id},identity);
    if(result&&!result.error&&this.state.current)this.emit({selectedTake:source.id});return result;
  }
  select(take,identity){return this.mutate('select_take',{asset:this.state.selectedAsset,request:take.request,take:take.id},identity);}
  async loadMethods(){
    const epoch=this.epoch,client=this.client;
    if(!this.valid(epoch,client)||this.state.methodsLoading)return;
    this.emit({methodsLoading:true,methodsError:false});let reader;
    try{
      reader=await openTechnical(this.host,()=>this.invalidate(),{namespace:'creation',methods:new Set(['methods'])});
      if(!this.valid(epoch,client))return;
      const result=await reader.request('methods');if(!this.valid(epoch,client))return;
      if(!result?.kinds)throw Error('Invalid methods envelope');
      this.emit({methods:result,methodsLoading:false});
    }catch(error){if(this.valid(epoch,client)){
      this.emit({methodsLoading:false,methodsError:true});
      if(authorityDenials.has(error.code))this.failure(error);
    }}finally{reader?.dispose();}
  }
  async loadImportRequests(){
    const epoch=this.epoch,client=this.client;if(!this.valid(epoch,client)||this.state.busy)return;
    this.emit({busy:true});let reader;
    try{
      reader=await openTechnical(this.host,()=>this.invalidate(),{namespace:'creation',methods:new Set(['list'])});
      if(!this.valid(epoch,client))return;
      const result=await reader.request('list');if(!this.valid(epoch,client))return;
      this.emit({importRequests:result.creations||[],busy:false,status:'Choose an existing same-kind request for this import.'});
    }catch(error){if(this.valid(epoch,client))this.failure(error,'Saved requests unavailable. Open the matching chat and refresh requests.');}
    finally{reader?.dispose();}
  }
  async createWithHermes(asset,direction=asset?.intent,identity=null,append=false){
    const client=this.client,epoch=this.epoch,current=this.state.current;
    if(!asset||!current||!this.identityValid(identity)||this.state.busy||this.pending)return;
    if(!this.valid(epoch,client)||!this.host.composer?.getDraft||!this.host.composer?.insertText){
      this.emit({status:'Open a Hermes chat for this profile, then try again. Nothing sent.'});return;
    }
    const valid=()=>this.valid(epoch,client)&&this.state.current?.id===current.id&&this.state.current?.revision===current.revision&&this.state.selectedAsset===asset.id;
    this.emit({busy:true});
    try{
      const existing=await this.host.composer.getDraft(client.session);if(!valid())return;
      if(existing&&!append){this.emit({busy:false,draftAsset:asset.id,status:'Your chat has an unsent draft. Choose Add to existing draft to keep it.'});return;}
      const text='Motion Studio - create '+asset.kind+' for production "'+current.title+'", asset '+(asset.position+1)+
        ' "'+asset.intent+'": '+(direction||asset.intent||'Use the production brief.');
      const applied=await insertDraft(this.host,client.session,text);if(!valid())return;
      this.emit({busy:false,draftAsset:applied?null:this.state.draftAsset,status:applied?'Request added to your chat. Review it and press Send.':'No visible chat composer. Nothing sent.'});
      return Boolean(applied);
    }catch{if(valid())this.emit({busy:false,status:'Chat composer unavailable. Nothing sent.'});}
  }
  async importTake(file,request,identity=null){
    const client=this.client,epoch=this.epoch,current=this.state.current;
    const asset=current?.assets.find(item=>item.id===this.state.selectedAsset);
    if(!asset||!this.identityValid(identity)||!this.valid(epoch,client)||this.state.busy||this.pending)return;
    const formats={'image/png':'png','image/jpeg':'jpeg','audio/wav':'wav','audio/x-wav':'wav','video/mp4':'mp4'};
    const format=formats[file?.type],kind=format==='png'||format==='jpeg'?'Image':format==='mp4'?'Video':null;
    if(!format||!file.size||file.size>16777216){this.emit({status:'Choose a PNG, JPEG, WAV or MP4 file up to 16 MiB.'});return;}
    if((request&&request.kind!==asset.kind)||(kind?kind!==asset.kind:!['Sound effects','Music','Voice'].includes(asset.kind))){
      this.emit({status:'Choose a file and, if used, an authorized request matching this asset’s media type.'});return;}
    const job={cancelled:false,id:null,client};this.importJob=job;
    const valid=()=>this.valid(epoch,client)&&this.state.current?.id===current.id&&this.state.current?.revision===current.revision&&
      this.state.selectedAsset===asset.id&&!job.cancelled;
    this.clear();this.emit({busy:true,importing:true,importProgress:0,status:'Checking the original file…'});
    try{
      const bytes=new Uint8Array(await file.arrayBuffer());if(!valid())return;
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
      if(!valid())return;
      if(!request){
        request=await client.request('media_import.intent',{production:current.id,expected:current.revision,asset:asset.id,command:command()});
        if(!valid())return;
        if(!request?.request||!Number.isInteger(request.revision)||request.kind!==asset.kind||request.method!=='import')throw Error('Import intent could not be confirmed.');
      }
      const begun=await client.request('media_import.begin',{command:command(),request:request.request,revision:request.revision,
        digest,size:bytes.length,name:file.name,format});job.id=begun.id;
      if(!valid()){if(this.valid(epoch,client))await client.request('media_import.cancel',{id:job.id});return;}
      for(let offset=0;offset<bytes.length;offset+=196608){
        const part=bytes.subarray(offset,offset+196608);let binary='';for(const value of part)binary+=String.fromCharCode(value);
        const receipt=await client.request('media_import.chunk',{id:job.id,offset,data:btoa(binary)});
        if(!valid())return;
        if(receipt.id!==job.id||receipt.received!==offset+part.length)throw Error('Import progress could not be confirmed.');
        this.emit({importProgress:Math.round(receipt.received/bytes.length*100),status:'Importing original… '+Math.round(receipt.received/bytes.length*100)+'%'});
      }
      if(!valid())return;
      const committed=await client.request('media_import.commit',{id:job.id});if(!valid())return;
      if(committed.take!==begun.take||committed.id!==job.id||committed.status!=='Ready for review')throw Error('Import was not completed.');
      this.emit({busy:false,importing:false});
      const linked=await this.link({request:request.request,id:committed.take},identity);
      if(linked&&this.valid(epoch,client)&&!this.pending){await this.refresh();this.emit({status:'Imported original linked. Review it, then select it as an output.'});}
    }catch(error){if(this.valid(epoch,client)&&!job.cancelled)this.failure(error,'Import could not be completed. Refresh saved takes before trying again.');}
    finally{if(this.importJob===job){this.importJob=null;if(this.valid(epoch,client))this.emit({busy:false,importing:false});}}
  }
  async cancelImport(){
    const job=this.importJob;if(!job)return;job.cancelled=true;
    this.emit({status:'Cancelling import…'});
    try{if(job.id&&job.client.current())await job.client.request('media_import.cancel',{id:job.id});
      if(this.importJob===job)this.emit({status:'Import cancelled. Refresh saved takes if commit was already in progress.'});
    }catch{if(this.importJob===job)this.emit({status:'Cancellation could not be confirmed. Refresh saved takes before retrying.'});}
  }
  async prepareMediaReview(){
    const current=this.state.current,asset=current?.assets.find(item=>item.id===this.state.selectedAsset),epoch=this.epoch,client=this.client;
    if(!asset||!this.valid(epoch,client)||this.state.busy)return;
    this.clear();const serial=this.loadSerial;this.loading=true;
    const valid=()=>this.valid(epoch,client)&&serial===this.loadSerial&&this.state.current?.revision===current.revision&&this.state.selectedAsset===asset.id;
    this.emit({busy:true,status:'Checking linked originals…'});
    try{
      const descriptors=[];
      for(const take of asset.takes){const descriptor=await client.request('describe',{production:current.id,asset:asset.id,request:take.request,take:take.id});
        if(!valid())return;
        const id=descriptor.identity;
        if(!id||id.production!==current.id||id.asset!==asset.id||id.request!==take.request||id.take!==take.id||
          id.artifact!==take.artifact||id.requestRevision!==take.source_request_revision)throw Error('Media identity could not be verified.');
        descriptors.push(descriptor);}
      this.loading=false;this.emit({busy:false,mediaReview:{scope:JSON.stringify([epoch,current.id,current.revision,asset.id,serial]),descriptors,valid,client},
        status:'Originals ready for review. Choose and load a take; nothing plays automatically.'});
    }catch(error){if(valid()){this.loading=false;this.failure(error,'Original media could not be opened. Refresh the linked takes.');}}
  }
  clearDownload(){if(this.downloadURL)URL.revokeObjectURL(this.downloadURL);this.downloadURL=null;this.emit({download:null});}
  exportHooks(){
    if(this.boundExportHooks)return this.boundExportHooks;
    this.boundExportHooks={prepare:async(spec,valid)=>{
      const client=this.client,descriptor=await client.request('export.prepare',spec);
      const release=()=>client.current()?client.request('export.close',{take:descriptor.take}):Promise.resolve();
      return {descriptor,client,operation:'export.chunk',identity:()=>({take:descriptor.take}),release,
        reauthorize:async()=>{if(!valid())throw Error('EXPORT_SCOPE_CHANGED');
          const observed=await client.request('export.descriptor',{take:descriptor.take});
          if(JSON.stringify(observed)!==JSON.stringify(descriptor))throw Error('EXPORT_INTEGRITY_FAILED');}};
    },chooseDestination:async(spec,valid)=>({write:async(bytes)=>{
      if(!valid())return {status:'cancelled'};
      if(this.downloadURL)URL.revokeObjectURL(this.downloadURL);
      this.downloadURL=URL.createObjectURL(new Blob([bytes],{type:spec.mime}));
      this.emit({download:{url:this.downloadURL,filename:spec.filename}});return {status:'ready'};
    }})};return this.boundExportHooks;
  }
  async load(take){
    const current=this.state.current,asset=this.state.selectedAsset,client=this.client,epoch=this.epoch;
    if(!current||!asset||!this.valid(epoch,client)||this.state.busy)return;
    this.clear();const serial=this.loadSerial;this.loading=true;
    this.emit({selectedTake:take.id,busy:true,status:'Checking exact retained original bytes...'});
    try{const result=await readRetained(client,'chunk',()=>({production:current.id,asset,
        request:take.request,take:take.id}),()=>this.valid(epoch,client)&&this.state.selectedAsset===asset&&
        serial===this.loadSerial&&this.state.selectedTake===take.id&&this.state.current?.id===current.id&&
        this.state.current?.revision===current.revision);
      if(!this.valid(epoch,client)||serial!==this.loadSerial||this.state.selectedAsset!==asset||this.state.selectedTake!==take.id||
        this.state.current?.id!==current.id||this.state.current?.revision!==current.revision)return;
      this.loading=false;
      this.url=URL.createObjectURL(new Blob([result.bytes],{type:'audio/wav'}));
      this.emit({url:this.url,urlTake:take.id,busy:false,status:'Original retained bytes verified. Listening/download is not delivery proof.'});
    }catch(error){if(this.valid(epoch,client)&&serial===this.loadSerial){this.loading=false;this.failure(error,
      ['CREATION_INTEGRITY_FAILED','RETAINED_SCOPE_CHANGED'].includes(error.message)?error.message:'RETAINED_BYTES_UNAVAILABLE');}}
  }
  dispose(){this.stopFocusedChat?.();this.clear();this.disposed=true;this.pending=null;this.epoch++;this.client?.dispose();}
}
