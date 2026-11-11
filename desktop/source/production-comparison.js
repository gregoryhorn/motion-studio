import {createElement as h,useEffect,useRef,useState} from 'react';
import {Button} from '@hermes/plugin-sdk';
import {productionMessage} from './production-controller.js';
import {ComparisonController} from './comparison-controller.js';

// Creator-facing wording for fixed comparison messages.
const plain=text=>String(text).replace(/^Choose two different retained SFX alternatives\..*/,'Choose two different takes. Nothing plays until you press Play.')
  .replace(/^Original bytes verified\..*/,'Take loaded. Choose Listen to hear it.').replace(/active slot/g,'take').replace(/Slot /g,'Take ')
  .replace(/ deliberately/g,'').replace(/Original audio/g,'This take').replace(/entered comparison position/g,'start time you entered');
export function ProductionComparison({controller,asset,identity,onClose,onUse}){
  const audio=useRef(null),session=useRef(null),[state,setState]=useState(null);
  useEffect(()=>{
    const current=new ComparisonController(controller,audio.current,setState);session.current=current;
    const cleanup=()=>current.dispose();controller.reviewCleanup=cleanup;setState({...current.state});
    return()=>{cleanup();if(controller.reviewCleanup===cleanup)controller.reviewCleanup=null;session.current=null;};
  },[controller]);
  const slots=state?.slots||{A:null,B:null},active=state?.active||'A';
  const label=take=>controller.state.available.find(item=>item.id===take.id)?.direction||'Sound effect';
  const takeLabel=take=>'Take '+(asset.takes.findIndex(item=>item.id===take.id)+1)+' - '+label(take);
  const button=(label,action,disabled=false,extra={})=>h(Button,{className:'ms-btn',variant:'outline',onClick:action,disabled,...extra},label);
  return h('section',{'aria-label':'Compare two takes',className:'production-comparison'},
    h('h3',null,'Compare two takes'),
    h('p',null,'Comparing only listens. Use take A or B makes that take the one this asset exports.'),
    h('p',null,'Both takes start from 0 seconds at the same volume. Switching pauses playback, and nothing plays until you press Play. The original files are never changed.'),
    h('div',{className:'production-comparison-slots'},...['A','B'].map(slot=>{
      const item=slots[slot],other=slots[slot==='A'?'B':'A'];
      return h('article',{key:slot,className:'production-comparison-slot'+(active===slot?' production-comparison-active':'')},
        h('h4',null,'Take '+slot+(active===slot?' - now listening':'')),
        h('label',null,'Take '+slot,h('select',{'aria-label':'Comparison take '+slot,value:item?.take.id||'',
          onChange:event=>void session.current?.choose(slot,event.target.value)},
          h('option',{value:''},'Choose a take'),
          ...asset.takes.map(take=>h('option',{key:take.id,value:take.id,disabled:take.id===other?.take.id},
            takeLabel(take))))),
        item?h('div',null,h('p',null,takeLabel(item.take)),
          h('p',{className:item.take.selected&&asset.stale?'production-stale':''},item.take.selected?
            (asset.stale?'Selected, but out of date: the brief or a dependency changed':'Selected for this asset'):'Not selected'),
          h('p',null,'Listening review: '+item.take.review),
          h('p',null,'Audio: '+(item.take.facts?.duration??'unknown')+' seconds / '+
            (item.take.facts?.channels??'unknown')+' channels / '+(item.take.facts?.rate??'unknown')+' Hz'),
          h('p',null,item.loading?'Loading the original...':item.url?'Original WAV ready':'Could not load this take. Choose it again to retry.'),
          h('p',null,'Playback duration: '+(item.duration===null?'not measured yet':item.duration.toFixed(3)+' seconds')),
          h('details',null,h('summary',null,'Technical details for '+slot),
            h('p',null,'Take '+item.take.id+' / source request revision '+item.take.source_request_revision),
            h('p',null,'Source request '+item.take.request+' / source '+item.take.origin),
            h('p',null,'Artifact '+item.take.artifact+' / SHA256 '+item.take.digest))):null,
        h('div',{className:'production-row'},button('Listen to '+slot,()=>session.current?.activate(slot),!item?.url,{'aria-pressed':active===slot}),
          item?button('Use take '+slot,()=>{void controller.select(item.take,identity);onUse();},controller.state.busy||controller.state.pending||
            (item.take.selected&&!asset.stale)):null));
    })),
    h('label',null,'Position (seconds from the start)',h('input',{type:'number',min:0,step:'any',
      'aria-label':'Comparison position seconds',value:state?.position??'0',onChange:event=>session.current?.seek(event.target.value)})),
    h('label',null,'Same volume for both (loudness is not matched)',h('input',{type:'range',min:0,max:1,step:0.01,
      'aria-label':'Shared monitoring volume',value:state?.volume??1,onChange:event=>session.current?.volume(event.target.value)})),
    h('p',null,'Volume '+Math.round((state?.volume??1)*100)+'% / listening to '+active),
    h('div',{tabIndex:0,role:'group',className:'production-comparison-player',
      'aria-label':'Comparison keyboard player',onKeyDown:event=>{if(event.code==='Space'){event.preventDefault();
        if(audio.current.paused)void session.current?.play();else session.current?.pause();}}},
      'Listening to take '+active+'. Focus here and press Space to play or pause.',
      h('audio',{ref:audio,preload:'metadata','aria-label':'Sound effects A/B comparison audio',
        onLoadedMetadata:()=>session.current?.metadata(),onEnded:()=>session.current?.ended(),onError:()=>session.current?.mediaError()})),
    h('div',{className:'production-row'},button('Play '+active,()=>void session.current?.play()),button('Play from start',()=>{session.current?.seek('0');void session.current?.play();}),
      button('Pause',()=>session.current?.pause()),button('Close comparison',onClose)),
    h('p',{role:'status','aria-label':'Comparison status'},state?.status?plain(productionMessage(null,state.status)):'Opening comparison. Nothing played.'),
    h('details',null,h('summary',null,'How comparison works'),
      h('p',null,'Position is counted in seconds from the start of each take. Nothing is stretched, trimmed or loudness-matched, so real differences in length and level stay audible. Comparing does not mark a take as reviewed.')));
}
