// Deterministic in-memory DOM/SDK fixture, not deployed DOM/auth qualification.
import fs from 'node:fs';
const moduleURL=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const transport=moduleURL(fs.readFileSync('studio/views/synthesis-transport.js','utf8'));
export const {openSynthesis}=await import(transport);
export const {mountSynthesis}=await import(moduleURL(fs.readFileSync('studio/views/synthesis-ui.js','utf8').replace("'./synthesis-transport.js'",JSON.stringify(transport))));
export const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
export const flush=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate);};
export function fixture() {
  const values={focusedSessionId:'s1',focusedSessionOwner:{connectionId:'c1',profile:'p1'},connectionId:'c1',profile:'p1',gateway:'open'};
  const listeners=Object.fromEntries(Object.keys(values).map(k=>[k,new Set()]));
  const state=Object.fromEntries(Object.keys(values).map(k=>[k,{get:()=>values[k],subscribe:callback=>{
    listeners[k].add(callback);callback(values[k]);return()=>listeners[k].delete(callback);
  }}]));
  const calls=[],selections=[],route={connectionId:'c1',profile:'p1',targetProfile:'p1',mode:'local'};
  const host={state,profileRoutes:async()=>[route],requestProfile:async(...args)=>{calls.push(args);return{id:'a'.repeat(32),state:'Prepared',active:true};}};
  const ports={host,selectEvidence:async value=>{selections.push(value);return{id:'e'.repeat(32),revision:1,template:{}};}};
  return{values,listeners,host,ports,calls,selections,route,set:(key,value)=>{values[key]=value;for(const notify of listeners[key])notify(value);},subscriptions:()=>Object.values(listeners).reduce((n,s)=>n+s.size,0)};
}
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.value='';this.disabled=false;this.hidden=false;this.attributes={};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(key,handler){this['on'+key]=handler;}
}
export function view(f) {
  globalThis.document={createElement:tag=>new Element(tag)};
  const root=new Element('root'),dispose=mountSynthesis(root,f.ports);
  const all=()=>{const out=[];function walk(n){out.push(n);n.children.forEach(walk);}walk(root);return out;};
  const find=text=>all().find(n=>n.textContent===text);
  return{root,dispose,all,find,submit:()=>find('Prepare proposed mapping'),fields:()=>all().find(n=>n.tag==='fieldset'),
    send:()=>all().find(n=>n.tag==='form').onsubmit({preventDefault(){}}),
    status:()=>all().find(n=>n.attributes.role==='status')?.textContent};
}
