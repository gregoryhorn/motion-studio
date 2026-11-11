import {readRetained} from './retained-bytes.js';

const kinds=new Set(['Image','Video','Voice','Music','Sound effects']);
const formats={Image:['image/png','image/jpeg','image/webp','image/gif','image/avif','image/bmp'],
  Video:['video/mp4','video/webm','video/ogg'],
  audio:['audio/wav','audio/x-wav','audio/wave','audio/mpeg','audio/mp4','audio/ogg','audio/webm','audio/flac']};
const importMimes={png:'image/png',jpeg:'image/jpeg',wav:'audio/wav',mp4:'video/mp4'};
const identityKeys=['production','asset','request','requestRevision','take','artifact'];
const sameIdentity=(a,b)=>Boolean(a&&b&&identityKeys.every(key=>a[key]===b[key]));
const positive=value=>Number.isFinite(value)&&value>0?value:null;
const emptyState=()=>({slots:{A:null,B:null},active:null,position:'0',volume:1,status:'Choose an exact retained take. Nothing played.'});

export function normalizeMediaDescriptor(value){
  if(!value||!kinds.has(value.kind)||!value.identity)throw Error('MEDIA_DESCRIPTOR_INVALID');
  const identity={};
  for(const key of identityKeys){
    const field=value.identity[key];
    if(key==='requestRevision'){
      if(field!==null&&(!Number.isSafeInteger(field)||field<1))throw Error('MEDIA_DESCRIPTOR_INVALID');
    }else if((key==='production'||key==='asset')&&field===null){
      // Standalone imports have request/take provenance, without Production IDs.
    }else if(typeof field!=='string'||!field.trim())throw Error('MEDIA_DESCRIPTOR_INVALID');
    identity[key]=field;
  }
  if(typeof value.mime!=='string'||!Number.isSafeInteger(value.byteLength)||value.byteLength<1||value.byteLength>16777216||
    typeof value.reviewStatus!=='string'||!value.reviewStatus.trim())throw Error('MEDIA_DESCRIPTOR_INVALID');
  if(value.format!=null&&(importMimes[value.format]!==value.mime||
    (value.format==='wav'?!['Voice','Music','Sound effects'].includes(value.kind):
      value.kind!==(value.format==='mp4'?'Video':'Image'))))throw Error('MEDIA_DESCRIPTOR_INVALID');
  if(value.sha256!=null&&!/^[a-f0-9]{64}$/.test(value.sha256))throw Error('MEDIA_DESCRIPTOR_INVALID');
  return Object.freeze({identity:Object.freeze(identity),kind:value.kind,format:value.format??null,mime:value.mime,byteLength:value.byteLength,
    width:positive(value.width),height:positive(value.height),duration:positive(value.duration),
    reviewStatus:value.reviewStatus,qualityRole:typeof value.qualityRole==='string'?value.qualityRole:'Not recorded',
    sha256:value.sha256??null});
}

// Existing Production take_summary has no generic media MIME. The caller supplies a
// backend-validated MIME; this adapter must never infer it from a private filename.
export function descriptorFromProductionTake({production,asset,take,mime}){
  if(!production||!asset?.id)throw Error('MEDIA_DESCRIPTOR_INVALID');
  return normalizeMediaDescriptor({identity:{production,asset:asset.id,request:take.request,
    requestRevision:take.source_request_revision??null,take:take.id,artifact:take.artifact},kind:asset.kind,
    mime,byteLength:take.size,width:take.facts?.width,height:take.facts?.height,duration:take.facts?.duration,
    reviewStatus:take.review,qualityRole:take.quality_role,sha256:take.digest});
}

// Store.snapshot() take plus its owning request kind. No private name is used.
export function descriptorFromImportedTake({kind,take}){
  return normalizeMediaDescriptor({identity:{production:null,asset:null,request:take.request,
    requestRevision:take.revision,take:take.id,artifact:take.artifact},kind,
    format:take.facts?.format,mime:take.facts?.mime,byteLength:take.size,width:take.facts?.width,height:take.facts?.height,
    duration:take.facts?.duration,reviewStatus:take.review,qualityRole:'Imported original',sha256:take.digest});
}

// Adapts only the EXISTING retained chunk protocol, including its existing 16 MiB
// limit. This is not a new Image/Video backend route or a universal size promise.
export function createRetainedReviewReader({client,operation,valid,imported=false}){
  return async ({scope,descriptor,signal})=>{
    const current=()=>!signal.aborted&&valid(scope,descriptor.identity);
    if(!current())throw Error('MEDIA_SCOPE_CHANGED');
    const id=descriptor.identity;
    if(!imported&&(!id.production||!id.asset))throw Error('MEDIA_DESCRIPTOR_INVALID');
    const transport={request:async (name,payload)=>{
      if(!current())throw Error('MEDIA_SCOPE_CHANGED');
      const chunk=await client.request(name,payload);
      if(!current())throw Error('MEDIA_SCOPE_CHANGED');
      if(imported&&chunk.mime!==descriptor.mime)throw Error('MEDIA_ORIGINAL_UNAVAILABLE');
      return chunk;
    }};
    const result=await readRetained(transport,operation,()=>imported?{take:id.take}:
      {production:id.production,asset:id.asset,request:id.request,take:id.take},current);
    if(!current()||!descriptor.sha256||result.sha256!==descriptor.sha256||result.bytes.byteLength!==descriptor.byteLength)
      throw Error('MEDIA_ORIGINAL_UNAVAILABLE');
    return {scope,identity:id,bytes:result.bytes};
  };
}

// media_import.contracts.ReadChunk forbids extra fields: send ONLY take/offset.
export function createImportedReviewReader(options){
  return createRetainedReviewReader({...options,imported:true});
}

export function createPlaybackGroup(){
  let active=null;
  return {claim(owner){if(active!==owner)active?.pause();active=owner;},
    release(owner){if(active===owner)active=null;}};
}
export const mediaReviewPlaybackGroup=createPlaybackGroup();

export class MediaReviewController{
  constructor({scope,readBytes,onChange=()=>{},isScopeCurrent=()=>true,
    playbackGroup=mediaReviewPlaybackGroup,urlAPI=URL,BlobClass=Blob}){
    if(typeof scope!=='string'||!scope||typeof readBytes!=='function')throw Error('MEDIA_REVIEW_INPUT_INVALID');
    Object.assign(this,{scope,readBytes,onChange,isScopeCurrent,playbackGroup,urlAPI,BlobClass});
    this.state=emptyState();this.closed=false;this.player=null;this.playEpoch=0;
  }
  current(){
    if(this.closed)return false;
    if(!this.isScopeCurrent(this.scope)){this.dispose();return false;}
    return true;
  }
  emit(){if(!this.closed)this.onChange({...this.state,slots:{...this.state.slots}});}
  supported(descriptor){return (formats[descriptor.kind]||formats.audio).includes(descriptor.mime);}
  choose(slot,value){
    if(!this.current()||!['A','B'].includes(slot))return;
    const descriptor=value?normalizeMediaDescriptor(value):null;
    const other=this.state.slots[slot==='A'?'B':'A'];
    if(descriptor&&sameIdentity(descriptor.identity,other?.descriptor.identity)){
      this.state.status='Choose two distinct retained alternatives.';this.emit();return;
    }
    this.pause();this.releaseSlot(slot);
    if(descriptor)this.state.slots[slot]={descriptor,url:null,loading:false,abort:null,decodedDuration:null,error:null};
    this.state.status='Take context changed. Nothing played.';this.emit();
  }
  releaseSlot(slot){
    const item=this.state.slots[slot];if(!item)return;
    item.abort?.abort();
    if(this.state.active===slot){this.detach();this.state.active=null;}
    if(item.url)this.urlAPI.revokeObjectURL(item.url);
    this.state.slots[slot]=null;
  }
  async load(slot){
    if(!this.current())return;
    const item=this.state.slots[slot];if(!item||item.loading||item.url)return;
    if(!this.supported(item.descriptor)){
      item.error='Unsupported media format in this viewer. Original is unchanged.';this.emit();return;
    }
    item.abort=new AbortController();item.loading=true;item.error=null;this.emit();
    const valid=()=>this.current()&&this.state.slots[slot]===item&&!item.abort.signal.aborted;
    try{
      if(!valid())return;
      const result=await this.readBytes({scope:this.scope,descriptor:item.descriptor,
        identity:item.descriptor.identity,signal:item.abort.signal,valid});
      if(!valid())return;
      if(result?.scope!==this.scope||!sameIdentity(result.identity,item.descriptor.identity)||
        !(result.bytes instanceof Uint8Array)||result.bytes.byteLength!==item.descriptor.byteLength)throw Error('MEDIA_ORIGINAL_UNAVAILABLE');
      // Copy before any further await; an adapter cannot mutate the captured bytes.
      const bytes=new Uint8Array(result.bytes);
      if(item.descriptor.sha256){
        const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
        if(!valid())return;
        if(digest!==item.descriptor.sha256)throw Error('MEDIA_ORIGINAL_UNAVAILABLE');
      }
      if(!valid())return;
      item.url=this.urlAPI.createObjectURL(new this.BlobClass([bytes],{type:item.descriptor.mime}));
      item.loading=false;this.state.status='Original bytes loaded. Playback and review approval have not started.';
      this.emit();
    }catch{
      if(!valid())return;
      item.loading=false;item.error='Original unavailable or integrity check failed. Retry explicitly; no work was started.';this.emit();
    }
  }
  attach(player){
    if(this.player===player)return;
    this.detach();this.player=player;
    if(this.current())this.syncPlayer();
  }
  detach(){
    this.pause();
    if(this.player){this.player.removeAttribute('src');this.player.load();}
    this.player=null;
  }
  activate(slot){
    if(!this.current())return;
    const item=this.state.slots[slot];if(!item?.url||item.descriptor.kind==='Image'||item.error)return;
    this.pause();this.state.active=slot;this.state.status='Monitor '+slot+' paused. Press Play deliberately.';
    this.syncPlayer();this.emit();
  }
  syncPlayer(){
    const item=this.state.slots[this.state.active];
    if(!this.player||!item?.url||item.error)return;
    if(this.player.tagName&&this.player.tagName!==(item.descriptor.kind==='Video'?'VIDEO':'AUDIO'))return;
    this.player.autoplay=false;this.player.loop=false;this.player.volume=this.state.volume;
    this.player.src=item.url;this.player.load();
  }
  metadata(expectedURL){
    if(!this.current())return;
    const item=this.state.slots[this.state.active];if(!item||!this.player)return;
    if(expectedURL&&item.url!==expectedURL)return;
    item.decodedDuration=positive(this.player.duration);
    this.applyPosition();this.emit();
  }
  applyPosition(){
    const value=this.state.position.trim()===''?NaN:Number(this.state.position);
    const duration=this.state.slots[this.state.active]?.decodedDuration;
    if(!Number.isFinite(value)||value<0){this.state.status='Enter a finite position at or after zero.';return false;}
    if(!duration){this.state.status='Duration not decoded; playback unavailable until metadata is ready.';return false;}
    if(value>=duration){this.state.status='Position is at or beyond the end of this original. No retiming or automatic clamp.';return false;}
    try{this.player.currentTime=value;}catch{this.state.status='This original cannot seek to that position.';return false;}
    return true;
  }
  seek(value){
    if(!this.current())return;
    this.pause();this.state.position=String(value);this.applyPosition();this.emit();
  }
  volume(value){
    if(!this.current()||!Number.isFinite(Number(value)))return;
    this.state.volume=Math.max(0,Math.min(1,Number(value)));
    if(this.player)this.player.volume=this.state.volume;this.emit();
  }
  async play(){
    if(!this.current()||!this.player||!this.state.slots[this.state.active]?.url)return;
    const player=this.player,slot=this.state.active;
    if(this.state.slots[slot].error||!this.applyPosition()){this.emit();return;}
    this.playbackGroup.claim(this);
    const epoch=++this.playEpoch;
    try{
      await player.play();
      if(!this.current()||epoch!==this.playEpoch||player!==this.player||slot!==this.state.active){player.pause();return;}
      this.state.status='Playing original '+slot+'. Review status is unchanged.';this.emit();
    }catch{
      if(!this.current()||epoch!==this.playEpoch)return;
      player.pause();this.state.status='Playback unavailable or blocked. Original is unchanged; press Play to retry.';this.emit();
    }
  }
  pause(){
    this.playEpoch++;this.player?.pause();this.playbackGroup.release(this);
    if(!this.closed){this.state.status='Paused. Nothing else started.';this.emit();}
  }
  position(){
    if(!this.current()||!this.player||this.player.paused)return;
    this.state.position=String(this.player.currentTime);this.emit();
  }
  ended(){this.pause();if(this.current()){this.state.status='Original ended. Other take did not start.';this.emit();}}
  mediaError(slot=this.state.active,expectedURL){
    if(!this.current()||!this.state.slots[slot])return;
    const item=this.state.slots[slot];
    if(expectedURL&&item.url!==expectedURL)return;
    if(slot===this.state.active)this.detach();
    if(item.url)this.urlAPI.revokeObjectURL(item.url);
    item.url=null;item.error='Browser cannot decode this original format or codec. Original is unchanged.';this.emit();
  }
  dispose(){
    if(this.closed)return;
    this.closed=true;this.detach();
    for(const slot of ['A','B'])this.releaseSlot(slot);
    this.state=emptyState();this.state.closed=true;this.state.status='Review closed; scoped media cleared.';this.onChange({...this.state});
  }
}
