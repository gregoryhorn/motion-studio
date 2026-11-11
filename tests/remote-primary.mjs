// Remote/local transport guards and actual host profile injection, no live socket.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fixture,deferred,flush} from './synthesis-correction-harness.mjs';
import {hostRequest} from './native-host-request.js';
const url=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
const transport=url(fs.readFileSync('studio/native/frontend/transport.js','utf8'));
const retained=url(fs.readFileSync('studio/native/frontend/retained-bytes.js','utf8'));
const {openTechnical}=await import(transport);
const controllers={};
for(const [name,file,symbol] of [['creation','creation-controller','CreationController'],['production','production-controller','ProductionController']])
  controllers[name]=(await import(url(fs.readFileSync('studio/native/frontend/'+file+'.js','utf8')
    .replace("'./transport.js'",JSON.stringify(transport)).replace("'./retained-bytes.js'",JSON.stringify(retained)))))[symbol];
const checks=[];async function test(name,run){await run();checks.push(name);}
function setup(namespace,mode='remote'){
  const f=fixture();f.route.primary=true;f.route.mode=mode;const calls=[];
  const adapter=hostRequest(async(method,payload)=>{calls.push({method,payload});return namespace==='creation'?{creations:[]}:{productions:[],available:[],capabilities:{}};},'p1','s1');
  f.host.request=adapter.request;f.host.requestProfile=()=>{throw Error('NO_SECONDARY');};
  const options={namespace,methods:new Set(['list','chunk'])};
  return {...f,calls,adapter,options};
}
for(const namespace of ['creation','production']){
  for(const mode of ['local','remote'])await test(namespace+' '+mode+' actual host injected profile',async()=>{
    const f=setup(namespace,mode),client=await openTechnical(f.host,()=>{},f.options);
    await client.request('list',{session_id:'forged'});
    assert.deepEqual(f.calls,[{method:'plugin.motion-studio.'+namespace+'.list',payload:{session_id:'s1',profile:'p1'}}]);
    await assert.rejects(client.request('prepare'));assert.equal(f.calls.length,1);client.dispose();assert.equal(f.subscriptions(),0);
  });
  const rejected={missingPrimary:f=>{delete f.route.primary;},secondary:f=>{f.route.primary=false;},
    duplicate:f=>{f.host.profileRoutes=async()=>[f.route,{...f.route}];},noRoutes:f=>{f.host.profileRoutes=async()=>[];},
    wrongConnection:f=>{f.route.connectionId='other';},wrongProfile:f=>{f.route.profile='other';},wrongTarget:f=>{f.route.targetProfile='other';},
    wrongOwner:f=>{f.set('focusedSessionOwner',{connectionId:'other',profile:'p1'});},
    selectedProfile:f=>{f.set('profile','other');},missingSession:f=>{f.set('focusedSessionId','');},
    disconnected:f=>{f.set('gateway','closed');},unknownMode:f=>{f.route.mode='pool';}};
  for(const [name,change] of Object.entries(rejected))await test(namespace+' denies '+name+' without RPC/effect',async()=>{
    const f=setup(namespace);change(f);await assert.rejects(openTechnical(f.host,()=>{},f.options),{code:namespace.toUpperCase()+'_PRIMARY_UNAVAILABLE'});
    assert.equal(f.calls.length,0);assert.equal(f.subscriptions(),0);
  });
  for(const [key,away] of [['focusedSessionId','away'],['connectionId','away'],['profile','away'],
    ['focusedSessionOwner',{connectionId:'away',profile:'p1'}],['gateway','closed']])
    for(const stage of ['routes','response','ready'])await test(namespace+' '+key+' away/back '+stage,async()=>{
      const f=setup(namespace),held=deferred(),before=f.values[key];let client,pending,invalidations=0;
      if(stage==='routes'){
        f.host.profileRoutes=()=>held.promise;pending=openTechnical(f.host,()=>invalidations++,f.options);
      }else{
        client=await openTechnical(f.host,()=>invalidations++,f.options);
        if(stage==='response'){f.host.request=()=>held.promise;pending=client.request('list');}
      }
      f.set(key,away);f.set(key,before);
      if(stage==='routes'){held.resolve([f.route]);await assert.rejects(pending);assert.equal(f.calls.length,0);}
      else if(stage==='response'){held.resolve({});await assert.rejects(pending);await assert.rejects(client.request('list'));client.dispose();}
      else {await assert.rejects(client.request('list'));client.dispose();}
      assert.equal(invalidations,1);assert.equal(f.subscriptions(),0);
    });
  await test(namespace+' disposal discards response',async()=>{
    const f=setup(namespace),client=await openTechnical(f.host,()=>{},f.options),held=deferred();
    f.host.request=()=>held.promise;const pending=client.request('list');client.dispose();held.resolve({});await assert.rejects(pending);
    assert.equal(f.subscriptions(),0);
  });
  await test(namespace+' transport refusal distinct from server admission',async()=>{
    const f=setup(namespace),controller=new controllers[namespace](f.host);f.route.primary=false;await controller.open();
    assert.equal(controller.state.status,namespace.toUpperCase()+'_PRIMARY_UNAVAILABLE');assert.equal(f.calls.length,0);
    f.route.primary=true;f.host.request=async()=>({error:namespace.toUpperCase()+'_ACCESS_UNAVAILABLE'});await controller.open();
    assert.equal(controller.state.status,namespace.toUpperCase()+'_ACCESS_UNAVAILABLE');controller.dispose();
  });
  await test(namespace+' ambiguous attached host profile never reaches wire',async()=>{
    const f=setup(namespace);f.adapter.gateway.rememberSessionProfile('s1','other');
    const client=await openTechnical(f.host,()=>{},f.options);await assert.rejects(client.request('list'));assert.equal(f.calls.length,0);client.dispose();
  });
}
for(const namespace of [undefined,'technical','unknown'])await test(String(namespace)+' remote stays denied',async()=>{
  const f=setup('creation');await assert.rejects(openTechnical(f.host,()=>{},{namespace,methods:new Set(['list'])}));assert.equal(f.calls.length,0);
});
console.log(JSON.stringify({checks,errors:[],boundary:'actual pinned host adapter with fake wire; no live gateway'}));
