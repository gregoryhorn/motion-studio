// Self-contained export lane. No registration, owner mutation or generator calls.
import {readRetained} from './retained-bytes.js';
const limit=16777216;
const safeCodes=new Set(['EXPORT_CANCELLED','EXPORT_CLOSED','EXPORT_SIZE_UNSUPPORTED','EXPORT_FORMAT_UNSUPPORTED',
  'EXPORT_SELECTION_STALE','EXPORT_SELECTED_TAKE_MISSING','EXPORT_REVISION_CONFLICT','EXPORT_SCOPE_CHANGED',
  'EXPORT_INTEGRITY_FAILED','EXPORT_LINEAGE_INVALID','EXPORT_IMPORT_UNAVAILABLE','MEDIA_SCOPE_DENIED',
  'CREATION_INTEGRITY_FAILED','RETAINED_SCOPE_CHANGED']);
const fileTypes={'audio/wav':'wav','image/png':'png','image/jpeg':'jpeg','video/mp4':'mp4'};
export class ProductionExportController{
  // hooks.prepare(spec, valid) -> {descriptor,client,operation,identity,
  //   reauthorize():Promise<void>,release():Promise<void>}.
  // hooks.chooseDestination({filename,mime,size},valid) -> null (cancel), or
  //   {write(bytes,valid):Promise<{status:'saved'|'cancelled'|'unknown'}>,close?()}.
  // The trusted host adapter MUST check valid immediately before its file write.
  constructor(owner,hooks,notify=()=>{}){
    this.owner=owner;this.hooks=hooks;this.notify=notify;this.serial=0;this.disposed=false;this.active=false;
    this.state={busy:false,status:'Export selected retained outputs. No generation or conversion.',phase:'idle'};
  }
  emit(values){if(!this.disposed){Object.assign(this.state,values);this.notify({...this.state});}}
  cancel(){this.serial++;this.emit({busy:this.active,phase:this.writing?'unknown':'cancelled',status:this.writing?
    'Save File was already dispatched. Destination outcome is unverified; cancellation cannot undo it.':
    'Export cancelled before any further write. Nothing further will be dispatched.'});}
  async save(assetIds,mode='zip'){
    if(this.disposed||this.active)return;
    const owner=this.owner,current=owner.state.current,client=owner.client,epoch=owner.epoch;
    if(!current||!owner.valid(epoch,client)||owner.state.busy)return;
    if(typeof this.hooks?.prepare!=='function'||typeof this.hooks?.chooseDestination!=='function'){
      this.emit({status:'Host Save File / export transport is unavailable. Nothing written.',phase:'unsupported'});return;
    }
    const ids=[...assetIds],serial=++this.serial,production=current.id,revision=current.revision;
    const selectedAsset=owner.state.selectedAsset,selectedTake=owner.state.selectedTake;
    const pointers=ids.map(id=>({id,take:current.assets.find(item=>item.id===id)?.selected_take}));
    const valid=()=>!this.disposed&&serial===this.serial&&owner.valid(epoch,client)&&
      owner.state.current?.id===production&&owner.state.current?.revision===revision&&
      owner.state.selectedAsset===selectedAsset&&owner.state.selectedTake===selectedTake&&
      pointers.every(pin=>{const asset=owner.state.current.assets.find(item=>item.id===pin.id);
        return asset?.selected_take===pin.take&&!asset?.stale;});
    let handle=null,destination=null,writing=false;
    this.active=true;
    this.emit({busy:true,phase:'checking',status:'Checking exact selected retained bytes and saved revision...'});
    try{
      if(!ids.length||new Set(ids).size!==ids.length||!['zip','file'].includes(mode)||(mode==='file'&&ids.length!==1))throw Error('EXPORT_SELECTION_STALE');
      for(const id of ids){const asset=current.assets.find(item=>item.id===id);
        if(!asset?.selected_take||asset.stale)throw Error('EXPORT_SELECTION_STALE');}
      handle=await this.hooks.prepare({production,expected:revision,assets:ids,mode},valid);
      if(!valid())return;
      const descriptor={...handle.descriptor};
      if(!Number.isInteger(descriptor.size)||descriptor.size<1||descriptor.size>limit)throw Error('EXPORT_SIZE_UNSUPPORTED');
      if((mode==='zip'&&(descriptor.mime!=='application/zip'||descriptor.filename!=='motion-studio-selected.zip'))||
        (mode==='file'&&(!fileTypes[descriptor.mime]||
          !new RegExp('^\\d{2}-[a-z-]+-take-\\d{2}\\.'+fileTypes[descriptor.mime]+'$').test(descriptor.filename))))throw Error('EXPORT_FORMAT_UNSUPPORTED');
      const identity={...handle.identity()};
      if(identity.take!==descriptor.take)throw Error('EXPORT_INTEGRITY_FAILED');
      const result=await readRetained(handle.client,handle.operation,()=>identity,valid);
      if(!valid())return;
      if(result.sha256!==descriptor.sha256||result.bytes.length!==descriptor.size)throw Error('EXPORT_INTEGRITY_FAILED');
      this.emit({phase:'destination',status:'Verified bytes ready. Choose Save File or cancel; delivery is not yet verified.'});
      destination=await this.hooks.chooseDestination({filename:descriptor.filename,mime:descriptor.mime,size:descriptor.size},valid);
      if(!valid())return;
      if(!destination){this.emit({phase:'cancelled',status:'Save File cancelled. Nothing written.'});return;}
      await handle.reauthorize();if(!valid())return;
      writing=true;this.writing=true;
      const receipt=await destination.write(result.bytes,valid);
      if(!valid()){
        // A write may have won a cancellation/navigation race. Never claim undo.
        if(!this.disposed&&serial===this.serial)this.emit({phase:'unknown',status:'Scope changed during Save File. Destination outcome is unverified; no retry.'});
        return;
      }
      if(receipt?.status==='cancelled')this.emit({phase:'cancelled',status:'Save File cancelled. Nothing written.'});
      else if(receipt?.status==='ready')this.emit({phase:'ready',status:'Download ready. Use the download link to save the verified original files.'});
      else if(receipt?.status==='saved')this.emit({phase:'saved',status:'Host reports file saved. Destination open/import/playback remains unverified.'});
      else this.emit({phase:'unknown',status:'Save File outcome unverified. Inspect the destination; no automatic retry.'});
    }catch(error){if(!this.disposed&&serial===this.serial){
      const code=safeCodes.has(error.code)?error.code:safeCodes.has(error.message)?error.message:null;
      this.emit({phase:writing?'unknown':'blocked',status:writing?'Save File outcome unverified. Inspect the destination; no automatic retry.':
        code?( /SCOPE/.test(code)?'The selected chat changed. Reopen the project before exporting.':
          /INTEGRITY/.test(code)?'The original bytes could not be verified. Reopen selected outputs.':
          'These outputs cannot be exported yet. Refresh and review their selections.'):
          'Export unavailable. No destination write dispatched; reopen selected outputs.'});
    }}finally{
      this.writing=false;
      try{await destination?.close?.();}catch{/* No raw host errors or paths. */}
      try{await handle?.release?.();}catch{/* Release is not a destination receipt. */}
      this.active=false;
      if(!this.disposed){if(serial===this.serial&&!valid()&&this.state.phase!=='unknown')this.emit({phase:'blocked',status:'Export scope or selection changed. No further work dispatched.'});
        this.emit({busy:false});}
    }
  }
  dispose(){this.serial++;this.disposed=true;}
}
