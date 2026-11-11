import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {nativeFixture,openTechnical,ready,deferred,flush} from './native-technical-harness.mjs';

test('import/register/open observations do not prepare; unsupported SDK/secondary route deny',async()=>{
  const f=nativeFixture(),c=f.controller();assert.equal(f.requests.length,0);await c.open();assert.equal(f.prepares().length,0);c.dispose();assert.equal(f.subscriptions(),0);
  delete f.host.state.gateway.subscribe;await assert.rejects(openTechnical(f.host));assert.equal(f.subscriptions(),0);
  const secondary=nativeFixture();secondary.route.primary=false;await assert.rejects(openTechnical(secondary.host));assert.equal(secondary.requests.length,0);
});
for(const [key,away] of [['focusedSessionId','other'],['focusedSessionOwner',{connectionId:'other',profile:'p1'}],['connectionId','other'],['profile','other'],['gateway','closed']]){
  test(key+' away-and-back permanently invalidates idle and opening handles',async()=>{
    const f=nativeFixture(),client=await openTechnical(f.host),before=f.values[key];f.set(key,away);f.set(key,before);
    assert.equal(client.current(),false);await assert.rejects(client.request('prepare'));assert.equal(f.prepares().length,0);client.dispose();
    const held=deferred();f.host.profileRoutes=()=>held.promise;const opening=openTechnical(f.host);f.set(key,away);f.set(key,before);held.resolve([f.route]);
    await assert.rejects(opening);assert.equal(f.subscriptions(),0);
  });
}
test('dispose while opening causes no subsequent status/select/prepare',async()=>{
  const f=nativeFixture(),held=deferred();f.host.profileRoutes=()=>held.promise;const c=f.controller(),pending=c.open();c.dispose();held.resolve([f.route]);await pending;
  assert.equal(f.requests.length,0);assert.equal(f.subscriptions(),0);
});
for(const reason of ['dispose','scope'])test(reason+' while selecting fences mutation/Prepare',async()=>{
  const f=nativeFixture(),c=await ready(f),held=deferred();f.handle(()=>held.promise);c.edit(0,'text','controlled technical fact');const pending=c.select();
  if(reason==='dispose')c.dispose();else{f.set('gateway','closed');f.set('gateway','open');}
  held.resolve({...f.selected,revision:2});await pending;await c.prepare();assert.equal(f.prepares().length,0);assert.notEqual(c.state.selected?.revision,2);c.dispose();
});
test('selection changes and stale revision error retain draft without silently rebinding',async()=>{
  const f=nativeFixture(),c=await ready(f);c.edit(0,'text','controlled correction');f.handle(async()=>({error:'TECHNICAL_EVIDENCE_STALE'}));await c.select();
  assert.equal(c.state.forms[0].text,'controlled correction');assert.equal(c.state.dirty,true);await c.prepare();assert.equal(f.prepares().length,0);c.dispose();
});
for(const scenario of ['returned-proven','thrown-same','arbitrary-returned','null-thrown'])test('delivery classification '+scenario,async()=>{
  const f=nativeFixture(),c=await ready(f),draft=JSON.stringify(c.state.forms);
  f.handle(async()=>{if(scenario==='thrown-same')throw new Error('SYNTHESIS_PACKET_TOO_LARGE');if(scenario==='null-thrown')throw null;
    return {error:scenario==='arbitrary-returned'?'UNCLASSIFIED':'SYNTHESIS_PACKET_TOO_LARGE',pre_admission:true};});
  await c.prepare();assert.equal(JSON.stringify(c.state.forms),draft);assert.equal(Boolean(c.state.command),scenario!=='returned-proven');assert.equal(f.preferences.size,scenario==='returned-proven'?0:1);
  await c.prepare();assert.equal(f.prepares().length,scenario==='returned-proven'?2:1);c.dispose();
});
test('lost ack then remount recovers identical scoped command without another Prepare',async()=>{
  const f=nativeFixture(),c=await ready(f);let row,command;
  f.handle(async(operation,payload)=>{if(operation==='prepare'){command=payload.command;row={id:'b'.repeat(32),active:true,state:'Outcome unknown',evidence:f.selected.id};throw Error('controlled lost ack');}
    if(operation==='evidence.read')return f.selected;
    if(operation==='status'&&payload.command){assert.equal(payload.command,command);return row;}
    if(operation==='result')return row;
    return {inference:'admitted',audience:'fixture',current:{id:f.selected.id},latest:[row]};});
  await c.prepare();assert.equal(c.state.job,null);assert.equal(c.state.command,command);c.dispose();const reopened=f.controller();await reopened.open();
  assert.equal(reopened.state.job.id,row.id);assert.equal(reopened.state.command,command);await reopened.prepare();assert.equal(f.prepares().length,1);
  assert.deepEqual([...f.preferences.values()],[{command}]);reopened.dispose();
});
test('not-observed after remount remains uncertain; delayed admission found with no replay',async()=>{
  const f=nativeFixture(),c=await ready(f);let observed=false,command;
  f.handle(async(operation,payload)=>{if(operation==='prepare'){command=payload.command;throw Error('controlled unobserved delivery');}
    if(operation==='status'&&payload.command)return observed?{id:'b'.repeat(32),active:true,state:'In flight'}:{id:null,active:true,state:'Command not observed'};
    if(operation==='result')return {id:'b'.repeat(32),active:true,state:'In flight'};
    return {inference:'admitted',audience:'fixture',latest:[]};});
  await c.prepare();c.dispose();const next=f.controller();await next.open();assert.equal(next.state.command,command);assert.equal(next.state.job,null);
  await next.abandon();await next.prepare();assert.equal(f.prepares().length,1);observed=true;await next.check();assert.equal(next.state.job.id,'b'.repeat(32));assert.equal(f.prepares().length,1);next.dispose();
});
test('late prepare response after disposal or scope change never binds to new view',async()=>{
  for(const reason of ['dispose','scope']){const f=nativeFixture(),c=await ready(f),held=deferred();f.handle(()=>held.promise);const pending=c.prepare();await flush();
    if(reason==='dispose')c.dispose();else f.set('focusedSessionId','other');held.resolve({id:'b'.repeat(32),active:false,state:'Proposal ready'});await pending;
    assert.equal(c.state.job??null,null);assert.equal(f.preferences.size,1);assert.equal(f.prepares().length,1);c.dispose();}
});
test('preference storage silently failing prevents dispatch; another command is never overwritten',async()=>{
  const f=nativeFixture(),c=await ready(f);f.storage.set=()=>{};await c.prepare();assert.equal(f.prepares().length,0);assert.match(c.state.status,/No preparation was dispatched/);c.dispose();
  const g=nativeFixture(),other=await ready(g);g.preferences.set(other.key(),{command:'d'.repeat(32)});await other.prepare();assert.equal(g.prepares().length,0);assert.equal(other.state.command,'d'.repeat(32));other.dispose();
});
test('scope-specific recovery pointer is not sent from a different session',async()=>{
  const f=nativeFixture(),c=await ready(f);f.handle(async()=>{throw Error('controlled lost response');});await c.prepare();c.dispose();
  f.set('focusedSessionId','other');f.handle(async()=>({inference:'unavailable',latest:[]}));const next=f.controller();await next.open();
  assert.equal(next.state.command,null);assert.equal(f.requests.filter(r=>r.payload.session_id==='other'&&r.payload.command).length,0);next.dispose();
});
for(const operation of ['status','evidence.read','result'])test('dispose during saved opening '+operation+' stops obsolete continuation',async()=>{
  const f=nativeFixture(),held=deferred(),job={id:'b'.repeat(32),active:true,state:'In flight'};
  f.handle(async op=>{if(op===operation)return held.promise;if(op==='evidence.read')return f.selected;
    if(op==='result')return job;return {inference:'admitted',audience:'fixture',current:{id:f.selected.id},latest:[job]};});
  const c=f.controller(),pending=c.open();await flush();const before=f.requests.length;c.dispose();
  held.resolve(operation==='evidence.read'?f.selected:operation==='result'?job:{inference:'admitted',latest:[job]});await pending;
  assert.equal(f.requests.length,before);assert.equal(f.prepares().length,0);assert.equal(f.subscriptions(),0);
});
test('dashboard metadata uses its own registration API and never native transport',()=>{
  const registrations=[],window={__HERMES_PLUGIN_SDK__:{React:{createElement:(tag,props,text)=>({tag,text})}},
    __HERMES_PLUGINS__:{register:(name,render)=>registrations.push({name,render})}};
  vm.runInNewContext(fs.readFileSync('native-package/dashboard/dist/index.js','utf8'),{window});
  assert.equal(registrations.length,1);assert.equal(registrations[0].name,'motion-studio');
  assert.match(registrations[0].render().text,/separate native Desktop/);
  assert.match(registrations[0].render().text,/unavailable/);
});
