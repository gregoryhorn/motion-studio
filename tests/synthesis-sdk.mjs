import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync('studio/views/synthesis-transport.js','utf8');
const {openSynthesis}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const checks=[];
function fixture() {
  const values={focusedSessionId:'s1',focusedSessionOwner:{connectionId:'c1',profile:'p1'},connectionId:'c1',profile:'p1',gateway:'open'};
  const route={connectionId:'c1',profile:'p1',targetProfile:'p1',mode:'local'},calls=[];
  const host={state:Object.fromEntries(Object.keys(values).map(k=>[k,{get:()=>values[k],subscribe:callback=>{callback(values[k]);return()=>{};}}])),
    profileRoutes:async()=>[route],requestProfile:async(...args)=>{calls.push(args);return{id:'job',state:'Prepared'};}};
  return {values,route,calls,host};
}
async function rejects(name,edit) {
  const f=fixture();edit(f);await assert.rejects(openSynthesis(f.host));assert.equal(f.calls.length,0);checks.push(name);
}
await rejects('missing authorized session',f=>f.values.focusedSessionId=null);
await rejects('focused owner mismatch',f=>f.values.focusedSessionOwner.profile='other');
await rejects('closed route never dials',f=>f.values.gateway='idle');
await rejects('remote route refused',f=>f.route.mode='remote');
await rejects('target profile mismatch',f=>f.route.targetProfile='other');
await rejects('ambiguous duplicate route',f=>f.host.profileRoutes=async()=>[f.route,{...f.route}]);
await rejects('old SDK unavailable',f=>f.host.requestProfile=null);
await rejects('session changes during route read',f=>f.host.profileRoutes=async()=>{f.values.focusedSessionId='changed';return[f.route];});
const f=fixture(),client=await openSynthesis(f.host);
assert.equal(f.calls.length,0);checks.push('open registers no inference');
await client.request('prepare',{command:'fixed'});
assert.deepEqual(f.calls[0],[f.route,'plugin.motion-studio.connector.prepare',{command:'fixed',session_id:'s1'},15000]);
checks.push('exact descriptor/session/finite supported requestProfile');
await assert.rejects(client.request('run',{command:'other'}));assert.equal(f.calls.length,1);checks.push('foreign method refused');
let release;const held=new Promise(r=>release=r);f.host.requestProfile=async()=>held;
const pending=client.request('result',{job:'job'});f.values.focusedSessionId='changed';release({id:'old'});
await assert.rejects(pending);checks.push('late response fenced');
client.dispose();await assert.rejects(client.request('status',{job:'job'}));checks.push('disposed scope cannot request');
fs.mkdirSync('docs/evidence/cs1',{recursive:true});
fs.writeFileSync('docs/evidence/cs1/sdk.json',JSON.stringify({kind:'offline SDK simulation, not deployed auth',checks},null,2)+'\n');
console.log(JSON.stringify({checks:checks.length}));
