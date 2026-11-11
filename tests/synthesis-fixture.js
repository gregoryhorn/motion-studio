// ONLY served by explicit test harness. This is not a deployed SDK/auth claim.
import {mountSynthesis} from '/synthesis-ui.js';
import {api,session as loadSession} from '/api.js';
let session='fixture-session';
const atom=get=>{const listeners=new Set();return{get,subscribe:callback=>{listeners.add(callback);callback(get());return()=>listeners.delete(callback);},notify:()=>{for(const callback of listeners)callback(get());}};};
const route={connectionId:'fixture-local',mode:'local',profile:'fixture-profile',targetProfile:'fixture-profile'};
const host={state:{focusedSessionId:atom(()=>session),focusedSessionOwner:atom(()=>({connectionId:'fixture-local',profile:'fixture-profile'})),
  connectionId:atom(()=>'fixture-local'),profile:atom(()=>'fixture-profile'),gateway:atom(()=>'open')},
  profileRoutes:async()=>[route],requestProfile:async(route,method,params)=>api('/api/cs1/rpc',{route,method,params})};
// The existing cookie/CSRF login belongs ONLY to this fixture shim, never the
// production native adapter. Host/session admission is simulated separately.
await loadSession();
let dispose=mountSynthesis(document.getElementById('fixture-root'),{host,selectEvidence:value=>api('/api/cs1/selection',value)});
document.getElementById('fixture-switch').onclick=()=>{
  session='changed-fixture-session';host.state.focusedSessionId.notify();dispose();dispose=mountSynthesis(document.getElementById('fixture-root'));
};
