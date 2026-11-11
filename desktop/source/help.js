import {createElement as h,useEffect,useRef} from 'react';

// Shared help: a short always-visible "how it works" strip and a full guide panel.
export const CREATE_HELP={
  quick:[
    ['Describe it','Type what you want and pick a media type. Plain language is fine.'],
    ['Send from chat','Create in chat puts your request in the Hermes chat. You press Send.'],
    ['Review and compare','New takes appear in Recent creations. Play, view and compare each one.'],
    ['Keep the best','Choose a take, mark whether it is right, or ask for a variation.']],
  guide:[
    {title:'What Quick Create is for',body:['Request one sound, track, voice line, image or clip without setting up a project. Sent requests and retained takes are saved. Unsent text is kept only in this window and cleared when chat/profile/connection authority changes.']},
    {title:'Making something',body:['Describe the result in the box, for example "an 8-second loop of rain on a tin roof, no voices or music". Pick the media type, then choose Create in chat.',
      'The request is placed in your selected Hermes chat as a draft. Nothing starts until you press Send in the chat. Hermes uses sensible defaults and only asks a question if something important is missing.',
      'If the chat already has text, use Add to existing draft so nothing you typed is lost.']},
    {title:'Reviewing takes',body:['Select a creation on the left to see its takes. Play (or Show image) fetches the exact saved file and shows it in the take card; nothing plays until you ask.',
      'Choose marks the take you want to keep. Sounds right / Looks right and Needs work record your judgement; they do not change the file.',
      'Open Production opens the workspace only. To bring this take into a project, pick it under References there.',
      'Save / download retrieves the retained file. Derivatives are labeled separately from originals; source bytes remain separately retained. A click does not verify destination delivery.']},
    {title:'Asking for a variation',body:['Write the change under Ask for a variation, e.g. "shorter, with a softer ending". It is drafted into the chat as a new take of the same creation, so earlier takes are kept.']},
    {title:'Status badges',body:['Technical validation, listening/viewing review, intended-use eligibility and user approval are separate checks. Outstanding checks are shown on each take; a saved run state does not prove full quality approval. Selected means the take you chose, not commercial clearance.']},
    {title:'What each media type can do today',body:['Sound effects has the recorded local Stable Audio qualification. Consult the method picker for passive tool/model/key observations, restrictions and cost uncertainty; presence is not execution admission.',
      'Image, Voice and Video have collection support. That alone does not qualify generation, recovery or intended-use eligibility on your installed route.',
      'Music: the local music engine is not enabled yet; you can import a track and review, compare and export it like any other take.']},
    {title:'If something goes wrong',body:['Each action shows a busy label, then a green result or amber problem beside its button for about six seconds. The top right also shows the result. After Create in chat, follow the arrow to your chat and press Send there. Opening and refreshing show the number of saved creations; changed cards briefly highlight.',
      'If it says to open a chat, select your Motion Studio chat in Hermes and choose Open saved creations. Connections lets an administrator connect this chat to the Motion Studio workflow.']}]};

export const PRODUCTION_HELP={
  quick:[
    ['Write a brief','Give the project a title and say what it is for.'],
    ['Plan the assets','Add the sounds, images, voice, music and video the project needs.'],
    ['Create or import takes','Ask Hermes for a take, or import one you made elsewhere.'],
    ['Review and export','Compare takes, use the best one for each asset, then export.']],
  guide:[
    {title:'What Production is for',body:['Keep several related assets together: a brief, references, an asset plan, the takes for each asset and the files you finally choose.']},
    {title:'Brief',body:['Title and a short description are enough. Purpose, audience and usage are optional context. Saving a brief never starts generation.']},
    {title:'Plan',body:['Each asset is one thing you need, such as "door slam" or "opening title image". Set its media type, what it should be, its order and what it depends on.',
      'If you change something an asset depends on, its chosen take is marked out of date instead of being replaced.']},
    {title:'References',body:['Link earlier creations as references for an asset so the next takes stay consistent. References always point to the original saved file.']},
    {title:'Takes',body:['Create with Hermes drafts a request for the selected asset into your chat; you press Send. Import a take adds a file you made elsewhere (PNG, JPEG, WAV or MP4). Originals are never changed.',
      'Compare plays two takes from the same starting point at the same volume. Use take makes it the chosen take for that asset only.']},
    {title:'Outputs and export',body:['Outputs lists the chosen take for every asset. Export assets packages exactly those files into one ZIP with a short manifest, ready for your editor.']},
    {title:'If something goes wrong',body:['The message at the top right says what happened. Opening a project, editing the plan and reviewing never generate anything.',
      'Out of date means an input changed after the take was chosen; review it and choose again when ready.']}]};

export function QuickHelp({steps,label='How it works'}){
  return h('ol',{className:'ms-steps','aria-label':label},...steps.map(([title,text],index)=>
    h('li',{key:title,className:'ms-step'},h('span',{className:'ms-step-n','aria-hidden':true},index+1),
      h('span',null,h('strong',null,title),h('span',{className:'ms-step-text'},text)))));
}

export function HelpPanel({open,onClose,title,guide}){
  const heading=useRef(null);
  useEffect(()=>{if(!open)return;const invoker=document.activeElement;heading.current?.focus();
    return()=>{if(invoker?.isConnected)invoker.focus();};},[open]);
  if(!open)return null;
  // Closing removes this panel, so hand focus back to the Help control that opened it.
  const close=()=>onClose();
  return h('section',{className:'ms-help-panel',role:'region','aria-label':title+' help',
    onKeyDown:event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}}},
    h('div',{className:'ms-help-head'},h('h2',{ref:heading,tabIndex:-1},title+' guide'),
      h('button',{type:'button',className:'ms-tab',onClick:close},'Close help')),
    h('div',{className:'ms-help-grid'},...guide.map(section=>h('article',{key:section.title,className:'ms-help-section'},
      h('h3',null,section.title),...section.body.map((text,index)=>h('p',{key:index},text))))));
}

export const helpStyles=`
.ms-steps{list-style:none;margin:0 0 24px;padding:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.ms-step{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--ms-line);border-radius:12px;padding:12px;background:var(--ms-surface)}
.ms-step strong{display:block;font-size:13px}.ms-step-text{display:block;color:var(--ms-muted);font-size:12.5px;line-height:1.4;margin-top:2px}
.ms-step-n{flex:none;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:var(--ms-raised);color:var(--ms-text)}
.ms-help-panel{border:1px solid color-mix(in srgb,var(--ms-accent) 45%,var(--ms-line));border-radius:16px;background:var(--ms-surface);padding:20px 22px;margin:0 0 24px}
.ms-help-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}
.ms-help-head h2{font-size:1.2rem}.ms-help-head h2:focus{outline:none}
.ms-help-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px 24px}
.ms-help-section h3{font-size:.95rem;margin-bottom:6px}.ms-help-section p{color:var(--ms-muted);margin:0 0 8px!important;line-height:1.5}
@media(max-width:820px){.ms-steps{grid-template-columns:1fr 1fr}}@media(max-width:480px){.ms-steps{grid-template-columns:1fr}}
`;
