import {createElement as h,useEffect,useRef,useState} from 'react';
import {Button,Input,Textarea} from '@hermes/plugin-sdk';
export function TechnicalPage({createController}){
  const controller=useRef(null),[state,setState]=useState(null);
  useEffect(()=>{const current=createController(setState);controller.current=current;setState({...current.state});
    return()=>{current.dispose();controller.current=null;};},[createController]);
  if(!state)return h('p',null,'Motion Studio public technical lane. No work started.');
  const busy=state.pending,uncertain=Boolean(state.command&&!state.job?.id),active=state.job?.active;
  const button=(label,action,disabled=false)=>h(Button,{onClick:()=>controller.current?.[action](),disabled:busy||disabled},label);
  const fields=state.forms.map((form,index)=>h('fieldset',{key:index,disabled:busy||uncertain||active},
    h('legend',null,'Selected public technical source '+(index+1)+(index?' (optional)':'')),
    ...[['source','Public provenance'],['version','Documented version'],['text','Technical excerpts']].map(([key,label])=>
      h('label',{key},label,h(key==='text'?Textarea:Input,{'aria-label':label+' '+(index+1),value:form[key],maxLength:key==='text'?24576:200,
        onChange:event=>controller.current?.edit(index,key,event.target.value)})))));
  return h('section',{'aria-label':'Motion Studio'},
    h('h1',null,'Motion Studio'),h('h2',null,'Quick Create / Production'),
    h('p',null,'This is the separate public technical lane, not media generation. Back to creations opens the source-only native SFX workspace; live media/generation remains unqualified. Music, Voice, Image, Video and Production remain incomplete.'),
    h('h2',null,'Prepare technical proposal'),
    h('p',null,'Public/non-personal technical excerpts only. No private creative prompts, chat, files, configuration, credentials or media. Provenance is not fetched. Finite technical-sentence recognition is not arbitrary-document intelligence; a privacy filter cannot prove prose safe.'),
    h('p',null,'Audience: clients authorized by the gateway to control this session, including operators and multiple controlling clients. This is not exclusive-owner, LOCAL-only or private-workspace proof. Host session restoration/bookkeeping may occur.'),
    h('p',null,'Inference is unavailable until effective primary/fallback destinations, retries, data/cost policy and audience/store ownership are admitted. One app invocation is not one provider attempt or a hard spending cap.'),
    h('p',{role:'status'},state.status),
    button('Open / reconcile saved technical work','open'),
    h('p',null,state.connected?'Public record access observed. Inference '+(state.inference?'admitted for this status observation.':'unconfigured/unverified.'):'No admitted public record access observed. Nothing is inferred.'),
    ...fields,button('Save selected technical evidence','select',!state.connected||uncertain||active),
    button('Prepare disabled proposal','prepare',!state.connected||!state.inference||state.dirty||!state.selected||uncertain||active),
    button('Check saved work','check'),button('Abandon proposal','abandon',!state.connected||!state.job?.id||!active),
    state.job?h('p',null,'Saved job '+state.job.id+(state.selected&&state.job.evidence!==state.selected.id?' is historical, not preparation of the current evidence.':'')):null,
    ...(state.job?.result?.questions||[]).map((question,index)=>h('p',{key:index},question+' Add the documented fact to a new evidence revision; no schema/command authoring.')),
    h('details',null,h('summary',null,'Disabled proposal and evidence details'),
      h('pre',null,state.job?.result?JSON.stringify(state.job.result,null,2):'No validated result observed.')));
}
