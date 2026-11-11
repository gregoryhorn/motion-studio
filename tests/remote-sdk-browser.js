// Fake SDK and socket wire around the ACTUAL pinned host request adapter.
export * from './native-sdk-browser.js';
import {host} from './native-sdk-browser.js';
import {hostRequest} from './native-host-request.js';
const dispatch=host.request.bind(host),adapter=hostRequest(dispatch);
host.request=adapter.request;
host.requestProfile=()=>{throw Error('NO_SECONDARY_PROFILE_ROUTE');};
host.profileRoutes=async()=>[{primary:true,mode:window.fixtureRouteMode||'remote',
  connectionId:'fixture-primary',profile:'fixture',targetProfile:'fixture'}];
window.fixtureGateway=adapter.gateway;
window.fixtureSetScope=(key,value)=>host.state[key].set(value);
