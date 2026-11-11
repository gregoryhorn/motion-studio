// Real React DOM + exact built native ESM; all host/model ports remain fake.
import {createRoot} from 'react-dom/client';
import plugin from 'motion-studio-package';
import {host} from '@hermes/plugin-sdk';
window.fixtureRequests=[];window.fixtureObservedCreationIds=[];window.fixtureLoseAck=false;
window.fixtureSession=session=>host.state.focusedSessionId.set(session);
const contributions=[],disposers=[];
const scope=key=>'hermes.plugin.motion-studio.'+key;
const storage={get:(key,fallback)=>JSON.parse(localStorage.getItem(scope(key))||'null')??fallback,
  set:(key,value)=>localStorage.setItem(scope(key),JSON.stringify(value)),remove:key=>localStorage.removeItem(scope(key))};
plugin.register({storage,register:entry=>{contributions.push(entry);return()=>{};},onDispose:callback=>disposers.push(callback)});
const root=createRoot(document.querySelector('#root'));
root.render(contributions.find(c=>c.data.path==='/motion-studio'&&c.render).render());
window.fixtureContributions=contributions.map(c=>({area:c.area,path:c.data.path,label:c.data.label}));
window.fixtureUnload=()=>{root.unmount();disposers.forEach(callback=>callback());};
