import {createElement as h,useCallback,useEffect,useRef,useState} from 'react';
import {Button} from '@hermes/plugin-sdk';
import {MediaReviewController,normalizeMediaDescriptor} from './media-review-controller.js';
import {mediaReviewStyles} from './media-review-style.js';

const initialState={slots:{A:null,B:null},active:null,position:'0',volume:1,status:''};
const takeName=(descriptor,index)=>'Take '+(index+1);
const seconds=value=>value>=60?Math.floor(value/60)+' min '+Math.round(value%60)+' s':(value<10?Math.round(value*10)/10:Math.round(value))+' s';
const bytes=value=>value>=1048576?(value/1048576).toFixed(1)+' MB':Math.max(1,Math.round(value/1024))+' KB';
const mediaName=descriptor=>descriptor.kind+' take'+(descriptor.duration===null?'':', '+seconds(descriptor.duration));
// Creator-facing wording for fixed controller messages; unknown text passes through.
const PLAIN=[[/^Choose an exact retained take\..*|^Take context changed\..*/,''],[/^Choose two distinct.*/,'Pick two different takes.'],
  [/^Original bytes loaded\..*/,'Ready. Nothing plays until you press play.'],[/^Monitor (A|B) paused\..*/,'Take $1 is ready. Press Play.'],
  [/^Playing original (A|B)\..*/,'Playing take $1.'],[/^Paused\..*/,'Paused.'],[/^Original ended\..*/,'Finished.'],[/^Review closed.*/,'Viewer closed.'],
  [/^Position is at or beyond.*/,'That start time is past the end of this take.'],[/^Duration not decoded.*/,'Still loading the file. Try again in a moment.'],
  [/^Enter a finite position.*/,'Enter a start time of 0 or more.'],[/^Playback unavailable.*/,'Could not play. Press Play to try again.'],
  [/^This original cannot seek.*/,'This file cannot jump to that time.'],[/^Unsupported media format.*/,'This viewer cannot show this file type. The file is unchanged.'],
  [/^Original unavailable.*/,'Could not load the file. Try again.'],[/^Browser cannot decode.*/,'This browser cannot play this file. The file is unchanged.']];
const plain=text=>{const value=String(text||''),match=PLAIN.find(([pattern])=>pattern.test(value));return match?value.replace(match[0],match[1]):value;};
const EXTENSIONS={'audio/wav':'wav','audio/x-wav':'wav','audio/wave':'wav','image/png':'png','image/jpeg':'jpeg','video/mp4':'mp4'};
const badge=text=>text?h('span',{className:'ms-badge media-review-badge'},text):null;

function ImageOriginal({item,slot,controller}){
  const [zoom,setZoom]=useState('fit'),[dimensions,setDimensions]=useState(null);
  const width=dimensions?.width??item.descriptor.width;
  return h('div',{className:'media-review-image'},
    h('label',{className:'media-review-zoom'},'Zoom',h('select',{'aria-label':'Image zoom '+slot,value:zoom,
      onChange:event=>setZoom(event.target.value)},h('option',{value:'fit'},'Fit'),
      h('option',{value:'100'},'100%'),h('option',{value:'200'},'200%'))),
    h('div',{className:'media-review-image-viewport',tabIndex:0,role:'region',
      'aria-label':'Image '+slot+' - arrow keys scroll when zoomed in'},
      h('img',{src:item.url,alt:mediaName(item.descriptor),
        style:zoom==='fit'?{width:'100%',maxHeight:'70vh',objectFit:'contain'}:
          {width:width?width*Number(zoom)/100:undefined,maxWidth:'none'},
        onLoad:event=>setDimensions({width:event.target.naturalWidth,height:event.target.naturalHeight}),
        onError:()=>controller.mediaError(slot,item.url)})),
    dimensions?h('p',null,dimensions.width+' x '+dimensions.height+' pixels'):null);
}

// Only known facts are shown; ids live in the collapsed Technical details.
function DescriptorFacts({descriptor,slot}){
  const id=descriptor.identity,size=descriptor.width&&descriptor.height?descriptor.width+' x '+descriptor.height:null;
  return h('div',{className:'media-review-facts'},
    h('div',{className:'media-review-badges'},badge(descriptor.kind),descriptor.duration===null?null:badge(seconds(descriptor.duration)),
      badge(size),badge(bytes(descriptor.byteLength)),badge(descriptor.reviewStatus)),
    h('details',null,h('summary',null,'Technical details'+(slot?' '+slot:'')),h('p',null,descriptor.mime+' / '+descriptor.byteLength+' bytes'),
      ...Object.entries(id).filter(([,value])=>value!=null).map(([key,value])=>h('p',{key},key+': '+value))));
}

// Parent must advance scope on EVERY relevant owner/session/connection/revision
// transition (including away-and-back), and register onController with its cleanup.
export function MediaReview(props){
  let descriptors;
  try{descriptors=props.descriptors.map(normalizeMediaDescriptor);}catch{
    return h('section',{'aria-label':'Media viewer'},
      h('p',{role:'status'},'This take cannot be shown here. Nothing was opened.'));
  }
  return h(MediaReviewSession,{...props,descriptors,key:JSON.stringify([props.scope,descriptors,Boolean(props.single)])});
}

// One take in the big viewer: loads once (the Open viewer click is the request), never autoplays.
function SingleViewer({state,session,playerRef}){
  const item=state.slots.A,requested=useRef(null);
  useEffect(()=>{if(!item||requested.current===item)return;requested.current=item;void session.current?.load('A');},[item,session]);
  useEffect(()=>{if(item?.url&&item.descriptor.kind!=='Image'&&state.active!=='A')session.current?.activate('A');},[item?.url,state.active,session]);
  if(!item)return h('p',{className:'media-review-wait'},'Opening the take...');
  const kind=item.descriptor.kind,ready=item.url&&state.active==='A';
  return h('div',{className:'media-review-single'},
    item.loading||(!item.url&&!item.error)?h('p',{className:'media-review-wait'},'Loading the original file...'):null,
    item.error?h('div',{className:'media-review-wait'},h('p',{role:'status'},plain(item.error)),
      h(Button,{className:'ms-btn',variant:'outline',onClick:()=>void session.current?.load('A')},'Try again')):null,
    item.url&&kind==='Image'?h(ImageOriginal,{key:item.url,item,slot:'A',controller:session.current}):null,
    ready?h(kind==='Video'?'video':'audio',{key:kind==='Video'?'video':'audio',ref:playerRef,controls:true,
      preload:'metadata',playsInline:true,'aria-label':mediaName(item.descriptor),
      onLoadedMetadata:()=>session.current?.metadata(item.url),onPlay:()=>session.current?.playbackGroup.claim(session.current),
      onEnded:()=>session.current?.playbackGroup.release(session.current),onError:()=>session.current?.mediaError('A',item.url)}):null,
    item.url?h('a',{className:'ms-link',href:item.url,download:'motion-studio-original.'+(EXTENSIONS[item.descriptor.mime]||'bin')},
      'Save / download original '+(EXTENSIONS[item.descriptor.mime]||'file').toUpperCase()):null,
    h(DescriptorFacts,{descriptor:item.descriptor,slot:''}));
}

function MediaReviewSession({scope,descriptors,readBytes,isScopeCurrent,onController,playbackGroup,single=false}){
  const [state,setState]=useState(initialState),session=useRef(null);
  useEffect(()=>{
    const current=new MediaReviewController({scope,readBytes,isScopeCurrent,playbackGroup,onChange:setState});
    session.current=current;setState({...initialState});onController?.(current);
    return()=>{current.onChange=()=>{};current.dispose();if(session.current===current)session.current=null;onController?.(null);};
  },[scope,readBytes,isScopeCurrent,onController,playbackGroup]);
  const playerRef=useCallback(node=>session.current?.attach(node),[]);
  const button=(label,action,disabled=false,extra={})=>h(Button,{className:'ms-btn',variant:'outline',onClick:action,disabled,...extra},label);
  if(state.closed)return h('section',{'aria-label':'Media viewer'},h('p',{role:'status'},plain(state.status)));
  if(single)return h('section',{'aria-label':'Media viewer',className:'media-review media-review-one'},
    h('style',null,mediaReviewStyles),h(SingleViewer,{state,session,playerRef}));
  const active=state.slots[state.active],timeBased=active&&active.descriptor.kind!=='Image';
  return h('section',{'aria-label':'Media viewer',className:'media-review'},
    h('style',null,mediaReviewStyles),h('h3',null,'Compare two takes'),
    h('p',null,'Comparing only looks and listens. It does not choose a take or change any file.'),
    h('div',{className:'media-review-slots'},...['A','B'].map(slot=>{
      const item=state.slots[slot],other=state.slots[slot==='A'?'B':'A'];
      const selected=item?descriptors.findIndex(value=>value.identity.take===item.descriptor.identity.take&&
        value.identity.artifact===item.descriptor.identity.artifact&&value.identity.asset===item.descriptor.identity.asset):-1;
      return h('article',{key:slot,className:'media-review-slot','data-on':String(state.active===slot)},h('h4',null,'Take '+slot+(state.active===slot?' - now playing from':'')),
        h('label',null,'Take '+slot,h('select',{'aria-label':'Take '+slot,value:selected<0?'':String(selected),
          onChange:event=>session.current?.choose(slot,event.target.value===''?null:descriptors[Number(event.target.value)])},
          h('option',{value:''},'Choose a take'),...descriptors.map((descriptor,index)=>
            h('option',{key:index,value:String(index),disabled:JSON.stringify(descriptor.identity)===JSON.stringify(other?.descriptor.identity)},
              takeName(descriptor,index))))),
        item?h('div',null,h(DescriptorFacts,{descriptor:item.descriptor,slot}),
          item.url?null:button(item.loading?'Loading '+slot+'...':'Load take '+slot,()=>void session.current?.load(slot),item.loading),
          item.error?h('p',{role:'status'},plain(item.error)):null,
          item.url?h('div',null,item.descriptor.kind==='Image'?
            h(ImageOriginal,{key:item.url,item,slot,controller:session.current}):
            button('Listen to '+slot,()=>session.current?.activate(slot),false,{'aria-pressed':state.active===slot})):null):null);
    })),
    timeBased?h('div',{className:'media-review-monitor'},
      h('div',{tabIndex:0,role:'group','aria-label':'Player - press Space to play or pause',onKeyDown:event=>{
        if(event.target===event.currentTarget&&event.code==='Space'){
          event.preventDefault();if(session.current?.player?.paused)void session.current.play();else session.current?.pause();
        }}},
        h(active.descriptor.kind==='Video'?'video':'audio',{key:active.descriptor.kind==='Video'?'video':'audio',ref:playerRef,
          preload:'metadata',playsInline:true,'aria-label':'Take '+state.active+': '+mediaName(active.descriptor),
          onLoadedMetadata:()=>session.current?.metadata(active.url),onTimeUpdate:()=>session.current?.position(),
          onEnded:()=>session.current?.ended(),onError:()=>session.current?.mediaError(state.active,active.url)})),
      h('div',{className:'media-review-controls'},
        h('label',null,'Start at (seconds)',h('input',{type:'number',min:0,step:'any',
          'aria-label':'Start at seconds',value:state.position,onChange:event=>session.current?.seek(event.target.value)})),
        h('label',null,'Same volume for both',h('input',{type:'range',min:0,max:1,step:0.01,
          'aria-label':'Same volume for both',value:state.volume,onChange:event=>session.current?.volume(event.target.value)}))),
      h('div',{className:'media-review-actions'},button('Play '+state.active,()=>void session.current?.play()),
        button('Play from start',()=>{session.current?.seek('0');void session.current?.play();}),
        button('Pause',()=>session.current?.pause())),
      h('p',null,'Both takes use the same start time and volume. Switching takes pauses playback; lengths and loudness are not matched.')):
      h('p',null,'Choose a take on each side and load it to compare.'),
    h('p',{role:'status','aria-label':'Viewer status'},plain(state.status)));
}
