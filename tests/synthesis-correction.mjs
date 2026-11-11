import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture,view,deferred,flush,openSynthesis} from './synthesis-correction-harness.mjs';

test('returned pre-admission rejection permits deliberate correction only',async()=>{
  const f=fixture(),v=view(f);let attempts=0;
  f.host.requestProfile=async(...args)=>{f.calls.push(args);return ++attempts===1?{error:'SYNTHESIS_PACKET_TOO_LARGE'}:{id:'a'.repeat(32),state:'Prepared',active:true};};
  try{
    v.send();await flush();assert.equal(v.submit().disabled,false);
    assert.equal(v.fields().disabled,false);assert.equal(v.find('Check saved job').disabled,true);
    assert.equal(f.calls.length,1);v.send();await flush();assert.equal(f.calls.length,2);
    assert.notEqual(f.calls[0][2].command,f.calls[1][2].command);
  }finally{v.dispose();}
});

test('uncertain error and not-observed read retain exact command and cannot abandon null',async()=>{
  const f=fixture(),v=view(f);
  f.host.requestProfile=async(...args)=>{f.calls.push(args);if(args[1].endsWith('.prepare'))throw new Error('SYNTHESIS_PACKET_TOO_LARGE');return{state:'Command not observed',active:true,id:null};};
  try{
    v.send();await flush();assert.equal(v.submit().disabled,true);
    await v.find('Check saved job').onclick();await flush();
    assert.equal(f.calls[0][2].command,f.calls[1][2].command);
    assert.equal(v.submit().disabled,true);assert.equal(v.find('Abandon proposal').disabled,true);
    v.send();v.find('Abandon proposal').onclick();v.find('Open saved preparation').onclick();await flush();
    assert.equal(f.calls.length,2);
    await v.find('Check saved job').onclick();await flush();assert.equal(f.calls[2][2].command,f.calls[0][2].command);
    assert.equal(f.calls.filter(c=>c[1].endsWith('.prepare')).length,1);
    f.set('gateway','closed');f.set('gateway','open');
    f.host.requestProfile=async(...args)=>{f.calls.push(args);return{id:'a'.repeat(32),state:'Prepared',active:true};};
    await v.find('Check saved job').onclick();await flush();
    assert.equal(f.calls[3][2].command,f.calls[0][2].command);assert.equal(v.find('Abandon proposal').disabled,false);
    assert.equal(f.calls.filter(c=>c[1].endsWith('.prepare')).length,1);
  }finally{v.dispose();}
});

for(const stage of ['opening','selection','saved opening'])test('disposal during '+stage+' prevents subsequent work',async()=>{
  const f=fixture(),held=deferred();
  if(stage==='selection')f.ports.selectEvidence=async value=>{f.selections.push(value);return held.promise;};
  else f.host.profileRoutes=()=>held.promise;
  const v=view(f);
  if(stage==='saved opening'){
    v.all().find(n=>n.attributes['aria-label']==='Saved job ID').value='a'.repeat(32);
    v.find('Open saved preparation').onclick();
  }else v.send();
  await flush();v.dispose();held.resolve(stage==='selection'?{id:'e'.repeat(32),revision:1,template:{}}:[f.route]);await flush();
  assert.equal(f.calls.length,0);assert.equal(f.selections.length,stage==='selection'?1:0);
  assert.equal(f.subscriptions(),0);
});

test('saved preparation read survives remount without prepare',async()=>{
  const f=fixture(),v=view(f);
  v.all().find(n=>n.attributes['aria-label']==='Saved job ID').value='a'.repeat(32);
  try{await v.find('Open saved preparation').onclick();await flush();assert.equal(f.calls.length,1);assert.match(f.calls[0][1],/\.result$/);assert.equal(f.selections.length,0);}
  finally{v.dispose();assert.equal(f.subscriptions(),0);}
});

for(const [key,away,back] of [['focusedSessionId','s2','s1'],['connectionId','c2','c1'],['profile','p2','p1'],['focusedSessionOwner',{connectionId:'c2',profile:'p1'},{connectionId:'c1',profile:'p1'}],['gateway','closed','open']]) {
  for(const stage of ['idle','opening','response'])test(key+' away-and-back latches during '+stage,async()=>{
    const f=fixture(),held=deferred();let client;
    if(stage==='opening')f.host.profileRoutes=()=>held.promise;
    if(stage==='response')f.host.requestProfile=async(...args)=>{f.calls.push(args);return held.promise;};
    const opening=openSynthesis(f.host);
    if(stage==='opening'){
      f.set(key,away);f.set(key,back);held.resolve([f.route]);await assert.rejects(opening);assert.equal(f.calls.length,0);assert.equal(f.subscriptions(),0);return;
    }
    client=await opening;
    try{
      const pending=stage==='response'?client.request('status',{command:'fixed'}):null;
      f.set(key,away);f.set(key,back);if(pending){held.resolve({id:'old'});await assert.rejects(pending);}
      await assert.rejects(client.request('prepare',{command:'new'}));assert.equal(f.calls.length,stage==='response'?1:0);
    }finally{client.dispose();assert.equal(f.subscriptions(),0);}
    f.host.requestProfile=async(...args)=>{f.calls.push(args);return{id:'saved'};};
    const reopened=await openSynthesis(f.host);await reopened.request('result',{job:'saved'});reopened.dispose();assert.equal(f.subscriptions(),0);
  });
}
test('same projected owner notification does not invalidate; absent subscription refuses',async()=>{
  const f=fixture(),client=await openSynthesis(f.host);
  f.set('focusedSessionOwner',{connectionId:'c1',profile:'p1'});await client.request('status',{command:'fixed'});client.dispose();
  delete f.host.state.gateway.subscribe;await assert.rejects(openSynthesis(f.host));assert.equal(f.subscriptions(),0);
});
test('other returned refusals and null exceptions do not clear uncertain command',async()=>{
  for(const kind of ['returned','thrown']){
    const f=fixture(),v=view(f);
    f.host.requestProfile=async(...args)=>{f.calls.push(args);if(kind==='thrown')throw null;return{error:'INVALID_SYNTHESIS_INPUT'};};
    try{v.send();await flush();assert.equal(v.submit().disabled,true);assert.equal(v.find('Check saved job').disabled,false);assert.equal(v.find('Abandon proposal').disabled,true);assert.equal(f.calls.length,1);}
    finally{v.dispose();assert.equal(f.subscriptions(),0);}
  }
});
test('scope invalidation during evidence selection causes no Prepare',async()=>{
  const f=fixture(),held=deferred();f.ports.selectEvidence=async value=>{f.selections.push(value);return held.promise;};
  const v=view(f);try{
    v.send();await flush();f.set('focusedSessionId','s2');f.set('focusedSessionId','s1');
    held.resolve({id:'e'.repeat(32),revision:1,template:{}});await flush();assert.equal(f.calls.length,0);
    assert.equal(v.submit().disabled,false);
  }finally{v.dispose();assert.equal(f.subscriptions(),0);}
});
