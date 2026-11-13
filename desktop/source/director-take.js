import {createElement as h,useEffect,useRef,useState} from 'react';
import {openTechnical} from './transport.js';
import {directorMethods,directorCommand} from './director-controller.js';
export function TakeChecks({host,request,take,onChanged=()=>{},removable=true}){
  const transport=useRef(null),live=useRef(false),[check,setCheck]=useState(take.check||{status:'Not checked',reason:'No matching retained report'}),[message,setMessage]=useState(''),[report,setReport]=useState(null),[busy,setBusy]=useState(false),[removed,setRemoved]=useState(null),[removalRevision,setRemovalRevision]=useState(take.removal_revision??0);
  useEffect(()=>{live.current=true;let obsolete=false;
    const invalidate=()=>{obsolete=true;transport.current?.dispose();transport.current=null;if(live.current){setReport(null);setCheck({status:'Not checked',reason:'Selected chat changed'});setMessage('Reopen this workspace. Nothing is replayed.');}};
    void openTechnical(host,invalidate,{namespace:'director',methods:directorMethods}).then(client=>{
      if(obsolete||!live.current){client.dispose();return;}transport.current=client;
      return client.request('status',{request,take:take.id}).then(value=>{if(live.current&&!obsolete&&client.current())setCheck(value);});
    }).catch(()=>{});
    return()=>{obsolete=true;live.current=false;transport.current?.dispose();transport.current=null;};
  },[host,request,take.id]);
  const run=async action=>{const client=transport.current;if(!client?.current()||busy)return;setBusy(true);
    try{await action(client);}
    catch(error){if(live.current&&client.current())setMessage(error?.code==='DIRECTOR_TAKE_IN_USE'?'Choose another take or remove its reference first.':error?.code==='DIRECTOR_RUN_UNRESOLVED'?'Stop or reconcile unresolved work before removing this take.':'Reply unconfirmed. Reopen saved state; nothing is replayed.');}
    finally{if(live.current&&client.current())setBusy(false);}};
  const open=()=>run(async client=>{
    const value=await client.request('report',{request,take:take.id,report:check.report});if(!live.current||!client.current())return;
    const asset=value.assets.find(name=>name.endsWith('/report.md'));
    let text='Full report assets are unavailable. '+(check.reason||'');
    if(asset){let parts=[],offset=0,total=1;
      while(offset<total){const chunk=await client.request('report',{request,take:take.id,report:check.report,asset,offset});if(!live.current||!client.current())return;
        const bytes=Uint8Array.from(atob(chunk.bytes),char=>char.charCodeAt(0));if(!bytes.length||chunk.offset!==offset||chunk.total>2*1024*1024)throw Error('REPORT_INVALID');
        parts.push(bytes);offset+=bytes.length;total=chunk.total;}
      text=new TextDecoder().decode(new Uint8Array(parts.flatMap(part=>Array.from(part))));}
    if(live.current&&client.current())setReport(text);
  });
  const remove=()=>run(async client=>{
    const result=await client.request(removed?'take.restore':'take.remove',{request,take:take.id,command:directorCommand(),expected:removalRevision});
    if(!live.current||!client.current())return;
    setRemovalRevision(result.revision);setRemoved(result.removed?result:null);setMessage(result.removed?'Removed from Studio. Original and history retained.':'Take restored.');onChanged();
  });
  return h('section',{'aria-label':'Take checks and removal'},
    h('p',{role:'region','aria-label':'Crystal Ball checks','aria-live':'polite'},'Crystal Ball: '+check.status+(check.reason?' - '+check.reason:'')),
    check.not_checked_details?.length?h('ul',{'aria-label':'Checks not performed'},
      ...check.not_checked_details.map((item,index)=>h('li',{key:index},item.summary))):
      check.not_checked?.length?h('p',null,'Missing checks: '+check.not_checked.join(', ')):null,
    check.not_checked_omitted_count?h('p',null,check.not_checked_omitted_count+' omitted check details are retained in the full report.'):null,
    h('p',null,'Your review: '+(take.review||'Not reviewed')+'. Automated checks do not approve delivery.'),
    h('div',{className:'ms-row'},check.report?h('button',{type:'button',className:'ms-btn',disabled:busy,onClick:open},'Open report'):null,
      removable?h('button',{type:'button',className:'ms-btn',disabled:busy||take.selected,onClick:remove},removed?'Undo remove':'Delete from Studio'):null),
    message?h('p',{role:'status'},message):null,
    report!==null?h('details',{open:true},h('summary',null,'Crystal Ball report'),h('pre',{style:{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}},report)):null);
}
