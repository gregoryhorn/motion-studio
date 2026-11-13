// PTP1 selected-primary transport. Metadata is a routing guard, not actor proof.
const technicalMethods=new Set(['evidence.select','evidence.read','prepare','status','result','abandon']);
const provenRejections=new Set(['SYNTHESIS_PACKET_TOO_LARGE','SYNTHESIS_UNAVAILABLE','SYNTHESIS_STALE',
  'TECHNICAL_PREPARATION_ACTIVE','TECHNICAL_ACCESS_UNAVAILABLE','TECHNICAL_STORE_BUSY','TECHNICAL_STORE_REVIEW_REQUIRED']);
const technicalUnavailable=()=>new Error('TECHNICAL_PRIMARY_UNAVAILABLE');
export async function openTechnical(host,onInvalidated=()=>{},options={}) {
  const methods=options.methods||technicalMethods,namespace=options.namespace||'technical';
  const workspace=['creation','production','director'].includes(namespace);
  const unavailable=()=>workspace?Object.assign(new Error('WORKSPACE_PRIMARY_UNAVAILABLE'),
    {code:namespace.toUpperCase()+'_PRIMARY_UNAVAILABLE'}):technicalUnavailable();
  const keys=['focusedSessionId','focusedSessionOwner','connectionId','profile','gateway'];
  if(!host?.request||!host?.profileRoutes||keys.some(key=>!host.state?.[key]?.subscribe))throw unavailable();
  const project=(key,value)=>key==='focusedSessionOwner'&&value?{connectionId:value.connectionId,profile:value.profile}:value;
  const capture=()=>Object.fromEntries(keys.map(key=>[key,project(key,host.state[key].get())]));
  let invalid=false,disposed=false;const subscriptions=[];
  const dispose=()=>{disposed=true;subscriptions.splice(0).forEach(stop=>stop());};
  try{
    for(const key of keys){let notified=false,previous;
      subscriptions.push(host.state[key].subscribe(value=>{
        const next=JSON.stringify(project(key,value));
        if(notified&&next!==previous&&!invalid){invalid=true;onInvalidated();}
        notified=true;previous=next;
      }));
    }
    const initial=capture(),owner=initial.focusedSessionOwner;
    const current=()=>!disposed&&!invalid&&JSON.stringify(capture())===JSON.stringify(initial);
    if(!initial.focusedSessionId||!owner||initial.gateway!=='open'||owner.connectionId!==initial.connectionId||owner.profile!==initial.profile)throw unavailable();
    const routes=await host.profileRoutes();
    if(!current()||routes.filter(r=>r.primary===true&&(r.mode==='local'||workspace&&r.mode==='remote')&&r.connectionId===owner.connectionId&&r.profile===owner.profile&&r.targetProfile===initial.profile).length!==1)throw unavailable();
    return Object.freeze({current,dispose,session:initial.focusedSessionId,scope:JSON.stringify([initial.connectionId,initial.profile,initial.focusedSessionId]),
      async request(operation,payload={}){
        if(!methods.has(operation)||!current())throw unavailable();
        const response=await host.request('plugin.motion-studio.'+namespace+'.'+operation,{...payload,session_id:initial.focusedSessionId},15000);
        if(!current())throw unavailable();
        if(response?.error){
          const error=new Error('TECHNICAL_REQUEST_REFUSED');
          error.code=typeof response.error==='string'?response.error:'TECHNICAL_OPERATION_UNAVAILABLE';
          error.preAdmissionRejected=operation==='prepare'&&response.pre_admission===true&&provenRejections.has(error.code);
          throw error;
        }
        return response;
      }
    });
  }catch(error){dispose();throw error;}
}
