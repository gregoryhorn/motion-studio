// Mount in actual Production Outputs with its existing owner and state projection.
import {createElement as h,useEffect,useRef,useState} from 'react';
import {Button} from '@hermes/plugin-sdk';
import {ProductionExportController} from './production-export-controller.js';
export function ProductionExport({owner,productionState,hooks}){
  const controller=useRef(null),[state,setState]=useState(null),[choice,setChoice]=useState({key:'',ids:[]});
  const current=productionState?.current;
  const key=(productionState?.scopeEpoch??'')+':'+(current?.id||'')+':'+(current?.revision||'');
  const previousKey=useRef(key);
  useEffect(()=>{
    const value=new ProductionExportController(owner,hooks,setState);controller.current=value;setState({...value.state});
    return()=>{value.dispose();controller.current=null;};
  },[owner,hooks]);
  useEffect(()=>{if(previousKey.current!==key){previousKey.current=key;controller.current?.cancel();}},[key]);
  const assets=current?.assets||[],selected=choice.key===key?choice.ids:assets.filter(asset=>asset.selected_take&&!asset.stale).map(asset=>asset.id);
  const busy=Boolean(state?.busy),unsupported=!hooks?.prepare||!hooks?.chooseDestination;
  const toggle=id=>{controller.current?.cancel();owner.clearDownload?.();setChoice({key,ids:selected.includes(id)?selected.filter(value=>value!==id):[...selected,id]});};
  const takeLabel=asset=>{const index=(asset.takes||[]).findIndex(take=>take.id===asset.selected_take);
    return !asset.selected_take?'no take chosen':asset.stale?'out of date':index<0?'take chosen':'Take '+(index+1);};
  return h('section',{className:'production-export','aria-label':'Export selected Production outputs'},
    h('h3',null,'Export'),
    h('p',{className:'production-muted'},'Saves the original file of each chosen take (WAV, PNG, JPEG or MP4). The ZIP also holds a short list of what is inside. Up to 16 MB in total.'),
    h('fieldset',{disabled:busy||!current||productionState?.busy},h('legend',null,'Assets to export'),
      ...assets.map(asset=>h('label',{key:asset.id},h('input',{type:'checkbox',
        checked:selected.includes(asset.id),disabled:!asset.selected_take||asset.stale,
        onChange:()=>toggle(asset.id)}),(asset.position+1)+'. '+asset.kind+(asset.intent?' - '+asset.intent:'')+' ('+takeLabel(asset)+')'))),
    h('div',{className:'production-row'},
      h(Button,{className:'ms-btn pd-btn pd-primary',disabled:busy||!selected.length||unsupported||productionState?.busy,
        onClick:()=>controller.current?.save(selected,'zip')},'Export assets'),
      h(Button,{className:'ms-btn pd-btn',variant:'outline',disabled:busy||selected.length!==1||unsupported||productionState?.busy,
        onClick:()=>controller.current?.save(selected,'file')},'Save selected file'),
      h(Button,{className:'ms-btn pd-btn',variant:'outline',disabled:!busy,onClick:()=>{controller.current?.cancel();owner.clearDownload?.();}},'Cancel export')),
    h('p',{className:'ms-help'},!selected.length?'Nothing to export yet: open Review, pick a take for an asset and choose Use take.':
      'Export assets saves one ZIP of everything ticked. Save selected file saves a single original when exactly one is ticked.'),
    productionState?.download?h('a',{className:'ms-link',href:productionState.download.url,download:productionState.download.filename},
      'Download '+productionState.download.filename):null,
    h('p',{role:'status','aria-live':'polite',className:'production-muted'},unsupported?'Saving files is not available in this window. Nothing was written.':state?.status));
}
