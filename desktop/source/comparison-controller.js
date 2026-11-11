import {readRetained} from './retained-bytes.js';

// Ephemeral review only. The owner supplies the already scoped Production client.
export class ComparisonController{
  constructor(owner,audio,notify=()=>{}){
    this.owner=owner;this.audio=audio;this.notify=notify;this.closed=false;this.serial=0;
    this.epoch=owner.epoch;this.client=owner.client;this.production=owner.state.current.id;
    this.revision=owner.state.current.revision;this.asset=owner.state.selectedAsset;
    this.takes=owner.state.current.assets.find(item=>item.id===this.asset).takes;
    this.state={slots:{A:null,B:null},active:'A',position:'0',volume:1,status:'Choose two different retained SFX alternatives. Nothing plays automatically.'};
  }
  valid(){return !this.closed&&this.owner.valid(this.epoch,this.client)&&
    this.owner.state.current?.id===this.production&&this.owner.state.current?.revision===this.revision&&
    this.owner.state.selectedAsset===this.asset;}
  emit(values){if(this.closed)return;Object.assign(this.state,values);this.notify({...this.state});}
  stop(){this.serial++;this.audio.pause();}
  detach(){this.stop();this.audio.removeAttribute('src');this.audio.load();}
  drop(slot){const item=this.state.slots[slot];if(item?.url)URL.revokeObjectURL(item.url);}
  async choose(slot,id){
    if(!this.valid()||!['A','B'].includes(slot))return;
    const take=this.takes.find(item=>item.id===id),other=slot==='A'?'B':'A';
    if(id&&(!take||this.state.slots[other]?.take.id===id))return;
    this.detach();this.drop(slot);
    const item=take?{take,loading:true,url:null,duration:null}:null;
    this.emit({slots:{...this.state.slots,[slot]:item},status:take?'Checking exact retained bytes...':'Comparison slot cleared.'});
    if(!item)return;
    const current=()=>this.valid()&&this.state.slots[slot]===item;
    try{
      const result=await readRetained(this.client,'chunk',()=>({production:this.production,asset:this.asset,
        request:take.request,take:take.id}),current);
      if(!current())return;
      // Match the immutable linked projection too, not only the chunk's own digest.
      if(result.sha256!==take.digest||result.bytes.length!==take.size)throw Error('CREATION_INTEGRITY_FAILED');
      item.url=URL.createObjectURL(new Blob([result.bytes],{type:'audio/wav'}));item.loading=false;
      this.emit({status:'Original bytes verified. Load the active slot to measure playback duration; listening is not inferred.'});
    }catch(error){
      if(!current())return;
      this.drop(slot);this.emit({slots:{...this.state.slots,[slot]:{take,loading:false,url:null,duration:null}},
        status:['CREATION_INTEGRITY_FAILED','RETAINED_SCOPE_CHANGED'].includes(error.message)?error.message:'RETAINED_BYTES_UNAVAILABLE'});
      this.owner.failure(error,'RETAINED_BYTES_UNAVAILABLE');
    }
  }
  activate(slot){
    if(!this.valid()||!['A','B'].includes(slot))return;
    this.detach();this.emit({active:slot,status:'Slot '+slot+' paused. Press Play explicitly; position is seconds from each original start.'});
    const item=this.state.slots[slot];
    if(item?.url){this.audio.src=item.url;this.audio.volume=this.state.volume;this.audio.load();}
  }
  metadata(){
    if(!this.valid())return;const item=this.state.slots[this.state.active];
    if(!item?.url||this.audio.getAttribute('src')!==item.url)return;
    if(!Number.isFinite(this.audio.duration)||this.audio.duration<=0){this.detach();this.emit({status:'Audio duration unavailable. Playback unavailable.'});return;}
    item.duration=this.audio.duration;this.seek(this.state.position);
  }
  position(){const text=String(this.state.position).trim();return text===''?NaN:Number(text);}
  seek(value){
    if(!this.valid())return;this.stop();this.emit({position:String(value)});
    const position=this.position(),item=this.state.slots[this.state.active];
    if(!Number.isFinite(position)||position<0){this.emit({status:'Enter a finite position of zero seconds or later. Nothing played.'});return false;}
    if(!item?.duration){this.emit({status:'Load active slot to measure its duration. Nothing played.'});return false;}
    if(position>=item.duration){this.emit({status:'Position is at or beyond the end of '+this.state.active+'. No cropping, looping or fallback to zero.'});return false;}
    if(this.audio.getAttribute('src')!==item.url){this.emit({status:'Load active slot before playback. Nothing played.'});return false;}
    try{this.audio.currentTime=position;this.emit({status:'Paused at '+position+' seconds from original start. Press Play explicitly.'});return true;}
    catch{this.emit({status:'Position unavailable. Nothing played.'});return false;}
  }
  async play(){
    if(!this.valid()||!this.seek(this.state.position))return;
    const serial=this.serial;
    try{await this.audio.play();if(!this.valid()||serial!==this.serial){this.audio.pause();return;}
      this.emit({status:'Playing '+this.state.active+' from the stated position. No selection or listening approval recorded.'});}
    catch{if(this.valid()&&serial===this.serial)this.emit({status:'Playback unavailable. Press Play to retry deliberately.'});}
  }
  pause(){if(!this.valid())return;this.stop();this.emit({status:'Paused. Play starts at the entered comparison position.'});}
  mediaError(){if(!this.valid()||!this.audio.getAttribute('src'))return;
    const item=this.state.slots[this.state.active];if(item)item.duration=null;
    this.detach();this.emit({status:'Original audio could not be decoded for playback. Nothing played; load deliberately to retry.'});}
  ended(){if(this.valid()){this.stop();this.emit({status:'End of '+this.state.active+'. Other take did not start. Enter a valid position and press Play.'});}}
  volume(value){if(!this.valid())return;const volume=Number(value);if(!Number.isFinite(volume)||volume<0||volume>1)return;
    this.audio.volume=volume;this.emit({volume});}
  dispose(){if(this.closed)return;this.detach();this.closed=true;this.drop('A');this.drop('B');
    this.state={slots:{A:null,B:null},active:'A',position:'0',volume:1,status:''};this.takes=[];}
}
