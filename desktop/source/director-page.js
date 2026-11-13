import {createElement as h,useEffect,useRef,useState} from 'react';
import {creationStyles} from './creation-style.js';
import {TakeChecks} from './director-take.js';
const styles=`.director-page{background:var(--ui-bg-primary,#151816)!important}.director-page p{margin-bottom:12px}.director-page .ms-btn{background:var(--ui-bg-secondary,#26332c);color:var(--ms-text);border:1px solid var(--ms-line);font:inherit;cursor:pointer;margin:4px 8px 4px 0;padding:8px 12px}.director-page button:disabled{opacity:.55;cursor:not-allowed}.director-grid{display:grid;grid-template-columns:minmax(220px,1fr) minmax(0,2fr);gap:24px}.director-grid>*{min-width:0}.director-page p,.director-page button{overflow-wrap:anywhere}.director-page label{display:block;margin:12px 0}.director-page input,.director-page textarea{display:block;width:100%;box-sizing:border-box;background:var(--ui-bg-secondary,#26332c);color:inherit;border:1px solid var(--ms-line);padding:12px}.director-page dialog{max-width:min(480px,85vw);background:var(--ui-bg-secondary,#26332c);color:var(--ms-text);border:1px solid var(--ms-line);padding:24px}.director-page button:focus-visible{outline:2px solid var(--ui-focus-border,var(--ui-accent));outline-offset:4px}@media(max-width:650px){.director-grid{display:block}.director-detail{margin-top:24px}}`;
const HELP='Rescan reads cached metadata and fixed PATH presence only. Skills are instructions, not tested tools. Learn this tool drafts research into your selected chat; review costs under its budget and press Send. Research never authorizes generation. Test and enable runs one disclosed tiny local call and activates only its tested operation/version/shape/length after usable bytes and applicable Crystal Ball checks. Unknown cost is not free. Missing senses remain visible. Crystal Ball PASS is not your approval. Export assets is an originals ZIP with check coverage, not an assembled movie. Delete from Studio hides only inactive, unreferenced entries; Undo/Restore keep the same originals, history, reviews and reports across restart. In-use takes need a different selection or reference removal; unresolved runs need stop/reconciliation.';
function Confirmation({card,onCancel,onConfirm,busy}){
  const dialog=useRef(null),previous=useRef(null);
  useEffect(()=>{previous.current=document.activeElement;dialog.current?.showModal();return()=>previous.current?.focus?.();},[]);
  return h('dialog',{ref:dialog,'aria-label':'Confirm tiny test',onCancel:event=>{event.preventDefault();onCancel();}},
    h('h2',null,'Test and enable '+card.name+'?'),h('p',null,'One call: '+card.operation+'. Harmless test input: '+card.shape+'. Output: one tiny retained file.'),
    h('p',null,'Local process and output only; no install or authorized network use. '+card.price+'. '+card.wait+'. Crystal Ball checks may take up to 60 more seconds.'),
    h('p',null,'Enable only this operation, pinned version, tested shape and '+(card.seconds||0)+' second length. Your review stays Not reviewed. No second activation or automatic retry.'),
    h('div',{className:'ms-row'},h('button',{type:'button',className:'ms-btn',disabled:busy,onClick:onConfirm},'Test and enable'),
      h('button',{type:'button',className:'ms-btn',disabled:busy,onClick:onCancel,autoFocus:true},'Cancel')));
}
export function DirectorPage({createController,onBack}){
  const current=useRef(null),[state,setState]=useState(null),[selected,setSelected]=useState(null),[name,setName]=useState(''),[documentation,setDocs]=useState(''),[help,setHelp]=useState(''),[confirm,setConfirm]=useState(null),[showHelp,setShowHelp]=useState(false);
  useEffect(()=>{const controller=createController(setState);current.current=controller;setState({...controller.state});void controller.open();return()=>{controller.dispose();current.current=null;};},[createController]);
  useEffect(()=>{setConfirm(null);setSelected(null);setName('');setDocs('');setHelp('');},[state?.scopeEpoch]);
  if(!state)return h('p',null,'Opening tools…');
  const card=state.cards.find(item=>item.id===selected),busy=state.busy,c=current.current;
  const button=(label,action,disabled=false)=>h('button',{type:'button',className:'ms-btn',disabled:busy||disabled,onClick:action},label);
  return h('section',{className:'ms director-page'},h('style',null,creationStyles+styles),h('div',{className:'ms-inner'},
    h('header',{className:'ms-top'},h('h1',null,'Tools'),button('Back to workspace',onBack),button('Rescan',()=>c.open()),
      button(showHelp?'Close help':'Help',()=>setShowHelp(!showHelp))),
    h('p',{role:'status','aria-live':'polite'},state.status),
    h('p',null,'Profile: '+(state.inventory?.profile||'Unavailable')+' · Execution location: '+(state.inventory?.execution_location||'Unavailable')),
    h('p',null,state.inventory?.status),
    h('p',{className:'ms-help'},'Add a tool, learn its documented interface, then confirm one tiny test. No install or generation occurs during discovery.'),
    showHelp?h('section',{'aria-label':'Detailed tools help'},h('h2',null,'Tools, checks and recovery'),h('p',null,HELP)):null,
    h('div',{className:'director-grid'},h('aside',{'aria-label':'Tool list'},
      !state.cards.some(item=>item.status==='Tested')?h('p',null,'No tested tools yet. Add a tool or rescan this profile.'):null,
      ...state.cards.map(item=>h('button',{key:item.id,type:'button',className:'ms-card','aria-pressed':item.id===selected,disabled:busy,onClick:()=>setSelected(item.id)},item.name+' · '+item.status)),
      h('details',null,h('summary',null,'Discovered here'),...(state.inventory?.items||[]).map((item,index)=>h('div',{key:index},
        h('p',null,item.name+' · '+item.kind+' · '+item.status+' · '+item.price+' · '+item.wait),
        button('Learn '+item.name,()=>c.learn(item))))),
      h('details',null,h('summary',null,'Untested starter templates'),...state.templates.map(item=>h('p',{key:item.name},item.name+' · Untested')))),
      h('section',{className:'ms-panel director-detail','aria-label':'Tool detail'},card?h('div',null,
        button('Back to tools',()=>setSelected(null)),h('h2',null,card.name),h('p',null,card.status+' · '+card.operation),
        h('p',null,card.price+' · '+card.wait+' · Evidence date: '+new Date(card.source_date*1000).toLocaleDateString()),h('p',null,card.next_action),
        button('Learn this tool',()=>c.learn(card)),
        ['Untested','Needs re-test'].includes(card.status)?button('Review tiny test',()=>setConfirm(card),card.price!=='Zero local call cost'):null,
        button('Disable',()=>c.mutate('card.disable',{id:card.id,expected:card.revision})),
        button('Forget binding and notes',()=>c.mutate('card.forget',{id:card.id,expected:card.revision})),
        ...card.evidence.map((item,index)=>h('section',{key:index},
          h('p',null,'Tiny test: '+item.elapsed_seconds+' seconds · '+item.context),
          h(TakeChecks,{host:c.host,request:item.request,take:{id:item.take,review:item.user_verdict,
            check:{status:item.check,report:item.report,not_checked:item.not_checked||[]}},onChanged:()=>c.open()})))):
        h('form',{onSubmit:event=>{event.preventDefault();void c.mutate('card.prepare',{name,documentation,help,expected:0});}},
          h('h2',null,'Add a tool'),h('label',null,'Tool name',h('input',{value:name,maxLength:120,required:true,onChange:event=>setName(event.target.value)})),
          h('label',null,'Official documentation URL',h('input',{type:'url',value:documentation,maxLength:2000,onChange:event=>setDocs(event.target.value)})),
          h('label',null,'Or paste help / schema from the tool',h('textarea',{value:help,maxLength:12000,onChange:event=>setHelp(event.target.value)})),
          h('p',null,'No commands or workflow JSON to write. Do not paste keys, accounts, machine paths or private endpoints.'),
          h('button',{type:'submit',className:'ms-btn',disabled:busy||!name.trim()||!documentation.trim()&&!help.trim()},'Save untested draft')))),
    h('section',{className:'ms-panel','aria-label':'Recently removed'},h('h2',null,'Recently removed'),
      h('p',null,'Restore keeps the same take, review, report and original order. Nothing is purged.'),
      state.removed.length?button('Undo last remove',()=>{const item=state.removed[0];void c.mutate('take.restore',{request:item.request,take:item.take,expected:item.revision});}):null,
      state.removed.length?state.removed.map((item,index)=>h('div',{key:item.take},h('span',null,'Removed take '+(index+1)+' · Your review: '+item.review+' '),
        button('Restore take '+(index+1),()=>c.mutate('take.restore',{request:item.request,take:item.take,expected:item.revision})))):h('p',null,'No removed takes.')),
    confirm?h(Confirmation,{key:confirm.id,card:confirm,busy,onCancel:()=>setConfirm(null),onConfirm:()=>{const card=confirm;setConfirm(null);void c.mutate('card.test',{id:card.id,expected:card.revision,confirmed:true});}}):null));
}
