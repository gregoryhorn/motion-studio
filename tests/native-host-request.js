// Actual pinned Hermes v0.23.1 adapter; only its socket boundary is replaced.
import {HermesGateway} from 'hermes-host-client';
const wires=new WeakMap();
Object.getPrototypeOf(HermesGateway.prototype).request=function(method,payload){
  const dispatch=wires.get(this);if(!dispatch)throw Error('NO_TEST_WIRE');return dispatch(method,payload);
};
export function hostRequest(dispatch,profile='fixture',session='session-a'){
  const gateway=new HermesGateway();gateway.canonical=true;
  gateway.rememberSessionProfile(session,profile);wires.set(gateway,dispatch);
  return {request:gateway.request.bind(gateway),gateway};
}
