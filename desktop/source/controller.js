// Native public-record view state. Only opaque scoped commands use preferences.
import {openTechnical} from './transport.js';
const technicalEmpty=()=>Array.from({length:3},()=>({source:'',version:'',text:''}));
const technicalMessages={TECHNICAL_ACCESS_UNAVAILABLE:'Public technical access is unconfigured. Audience and plugin-store ownership require admission.',
  TECHNICAL_PRIMARY_UNAVAILABLE:'Select the supported already-open local primary session, then explicitly reopen.',
  TECHNICAL_EVIDENCE_EXCLUDED:'Evidence excluded by the technical/privacy gate. Correct selected public excerpts.',
  SYNTHESIS_PACKET_TOO_LARGE:'Technical packet too large. Shorten excerpts and deliberately prepare again.',
  SYNTHESIS_UNAVAILABLE:'Inference is unconfigured or its effective destination/fallback/data/cost policy is unverified.',
  TECHNICAL_PREPARATION_ACTIVE:'Another technical preparation is active. No queue or automatic retry.',
  TECHNICAL_EVIDENCE_STALE:'The selected evidence changed. Reopen its current revision before selecting again.',
  SYNTHESIS_STALE:'The selected evidence or template changed before preparation was admitted. Reopen the current evidence, review it and deliberately prepare again.',
  TECHNICAL_STORE_BUSY:'Another service owns the technical proposal store. Wait and explicitly reopen saved work.',
  TECHNICAL_STORE_REVIEW_REQUIRED:'Plugin store identity/ownership needs review. No automatic adoption.',
  TECHNICAL_RECOVERY_UNAVAILABLE:'Cannot retain the scoped recovery command. No preparation was dispatched.'};
export class TechnicalController {
  constructor(host,storage,notify=()=>{}){
    this.host=host;this.storage=storage;this.notify=notify;this.client=null;this.generation=0;this.disposed=false;
    this.state={forms:technicalEmpty(),pending:false,connected:false,inference:false,selected:null,job:null,command:null,dirty:false,
      status:'Public technical lane not opened. Inference unconfigured/unverified; private media and native generation unavailable.'};
  }
  emit(value){Object.assign(this.state,value);if(!this.disposed)this.notify({...this.state});}
  key(){return 'technical-command:'+this.client.scope;}
  pointer(command){if(command){this.storage.set(this.key(),{command});
    if(this.storage.get(this.key(),null)?.command!==command)throw Object.assign(new Error('TECHNICAL_RECOVERY_UNAVAILABLE'),{code:'TECHNICAL_RECOVERY_UNAVAILABLE'});
  }else if(this.storage.get(this.key(),null)?.command===this.state.command)this.storage.remove(this.key());}
  invalidate(){this.generation++;this.emit({connected:false,pending:false,forms:technicalEmpty(),selected:null,job:null,
    status:'Session/connection changed. This view is invalid. Explicitly reopen to reconcile saved work; no resubmission.'});}
  edit(index,key,value){if(this.state.pending||this.state.command&&!this.state.job?.id)return;
    const forms=this.state.forms.map((item,i)=>i===index?{...item,[key]:value}:item);this.emit({forms,dirty:true});}
  async transaction(task){
    if(this.disposed||this.state.pending)return;
    const generation=++this.generation,owned=()=>!this.disposed&&generation===this.generation;
    this.emit({pending:true});
    try{await task(owned);}
    catch(error){if(owned()){

      if(error?.code==='SYNTHESIS_UNAVAILABLE')this.emit({inference:false});
      if(error?.code==='TECHNICAL_ACCESS_UNAVAILABLE')this.emit({connected:false});
      this.emit({status:(technicalMessages[error?.code]||technicalMessages[error?.message]||'Technical operation unavailable or response unobserved. Reopen/check the same command; no automatic retry.')+
        (error?.prepareNotAdmitted===true?' This Prepare was not admitted.':'')});
    }}finally{if(owned())this.emit({pending:false});}
  }
  usable(owned){return owned()&&this.client?.current();}
  open(){return this.transaction(async owned=>{
    this.client?.dispose();this.emit({connected:false,selected:null,job:null,command:null,forms:technicalEmpty()});
    const client=await openTechnical(this.host,()=>this.invalidate());
    if(!owned()){client.dispose();return;}this.client=client;
    const status=await client.request('status');if(!this.usable(owned))return;
    this.emit({connected:true,inference:status.inference==='admitted',status:'Public technical records opened. '+status.audience});
    const pointer=this.storage.get(this.key(),null);
    if(status.current){const selected=await client.request('evidence.read',{evidence:status.current.id});if(!this.usable(owned))return;
      this.emit({selected,dirty:false,forms:[...selected.body.sources.map(s=>({source:s.source,version:s.version,text:s.excerpts.map(e=>e.text).join('\n')})),...technicalEmpty()].slice(0,3)});}
    let job;
    if(pointer?.command){this.emit({command:pointer.command});job=await client.request('status',{command:pointer.command});if(!this.usable(owned))return;}
    else job=status.latest?.[0];
    if(job?.id){job=await client.request('result',{job:job.id});if(!this.usable(owned))return;this.show(job);}
    else if(pointer?.command)this.emit({job:null,status:'Command not yet observed. Delivery is uncertain; check the same command, never infer cancellation or resubmit.'});
  });}
  show(job){
    if(!job.id){this.emit({job:null,status:'Command not yet observed. Outcome uncertain; check again without resubmitting.'});return;}
    if(!job.active&&this.state.command){this.pointer(null);this.emit({command:null});}
    this.emit({job,status:job.state+'. Disabled/unqualified proposal only. Abandon after dispatch discards outcome, not provider cancellation or zero cost.'});
  }
  select(){
    if(!this.state.connected||this.state.command&&!this.state.job?.id||this.state.job?.active)return;
    const sources=this.state.forms.filter(s=>s.source||s.version||s.text).map((s,i)=>({id:'source-'+i,source:s.source,version:s.version,
      kind:'selected-technical-excerpt',excerpts:s.text.split(/\n+/).filter(t=>t.trim()).map((text,j)=>({id:'part-'+j,section:'Selected technical reference',text:text.trim()}))}));
    const expected=this.state.selected?.revision||0;
    return this.transaction(async owned=>{if(!this.usable(owned))return;
      const selected=await this.client.request('evidence.select',{expected,selection:{sources}});if(!this.usable(owned))return;
      this.emit({selected,dirty:false,status:'Technical evidence revision saved. No inference or tool operation occurred.'});});
  }
  prepare(){
    if(!this.state.connected||!this.state.inference||this.state.dirty||!this.state.selected||this.state.command&&!this.state.job?.id||this.state.job?.active)return;
    const selected=this.state.selected;
    return this.transaction(async owned=>{if(!this.usable(owned))return;
      const previous=this.storage.get(this.key(),null)?.command;
      if(previous){this.emit({command:previous,status:'A scoped command already needs reconciliation. Check saved work; no new preparation dispatched.'});return;}
      const command=crypto.randomUUID().replaceAll('-','');this.pointer(command);this.emit({command,job:null});
      if(!this.usable(owned))return;
      let job;
      try{job=await this.client.request('prepare',{command,evidence:selected.id,revision:selected.revision,template:selected.template});}
      catch(error){
        if(this.usable(owned)&&error?.preAdmissionRejected===true&&
          ['SYNTHESIS_PACKET_TOO_LARGE','SYNTHESIS_UNAVAILABLE','SYNTHESIS_STALE','TECHNICAL_PREPARATION_ACTIVE',
            'TECHNICAL_ACCESS_UNAVAILABLE','TECHNICAL_STORE_BUSY','TECHNICAL_STORE_REVIEW_REQUIRED'].includes(error.code)){
          error.prepareNotAdmitted=true;
          if(this.state.command===command&&this.storage.get(this.key(),null)?.command===command){this.pointer(null);this.emit({command:null,job:null});}
        }
        throw error;
      }
      if(this.usable(owned))this.show(job);
    });
  }
  check(){return this.open();} // Explicit observation/recovery, never Prepare.
  abandon(){if(!this.state.connected||!this.state.job?.id||!this.state.job.active)return;
    const id=this.state.job.id;return this.transaction(async owned=>{if(!this.usable(owned))return;
      const job=await this.client.request('abandon',{job:id});if(this.usable(owned))this.show(job);});}
  dispose(){if(this.disposed)return;this.disposed=true;this.generation++;this.client?.dispose();this.state={forms:technicalEmpty(),pending:false,connected:false};}
}
