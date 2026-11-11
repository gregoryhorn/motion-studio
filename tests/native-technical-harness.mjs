// Fake primary SDK for native UI tests; no host connection/provider/tool.
import fs from 'node:fs';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
export {deferred,flush};
const url=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const transport=url(fs.readFileSync('studio/native/frontend/transport.js','utf8'));
export const {openTechnical}=await import(transport);
export const {TechnicalController}=await import(url(fs.readFileSync('studio/native/frontend/controller.js','utf8').replace("'./transport.js'",JSON.stringify(transport))));
export function nativeFixture(){
  const f=fixture();f.route.primary=true;
  const preferences=new Map(),requests=[];
  const storage={get:(key,fallback)=>preferences.get(key)??fallback,set:(key,value)=>preferences.set(key,value),remove:key=>preferences.delete(key)};
  const selected={id:'e'.repeat(32),revision:1,template:{id:'documented-cli-wav',revision:1},body:{sources:[]}};
  let handler=async(operation,payload)=>{
    if(operation==='status')return {inference:'admitted',audience:'controlled fixture audience',latest:[],current:null};
    if(operation==='evidence.select'||operation==='evidence.read')return selected;
    return {id:'a'.repeat(32),state:'Prepared',active:true,evidence:selected.id};
  };
  f.host.request=async(method,payload)=>{const operation=method.replace('plugin.motion-studio.technical.','');requests.push({operation,payload});return handler(operation,payload);};
  const controller=()=>new TechnicalController(f.host,storage);
  return {...f,storage,preferences,requests,selected,controller,handle:value=>{handler=value;},prepares:()=>requests.filter(r=>r.operation==='prepare')};
}
export async function ready(f){const controller=f.controller();await controller.open();controller.edit(0,'source','Controlled public reference');await controller.select();return controller;}
