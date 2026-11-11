// Test-only SDK facade. Compiled only into a temporary browser harness, not package.
import {createElement} from 'react';
import {atom} from 'nanostores';
export const ROUTES_AREA='routes',SIDEBAR_NAV_AREA='sidebar.nav';
export const Button=props=>createElement('button',props),Input=props=>createElement('input',props),Textarea=props=>createElement('textarea',props);
export const host={state:{focusedSessionId:atom(window.fixtureInitialSession||'session-a'),focusedSessionOwner:atom({connectionId:'fixture-primary',profile:'fixture'}),
  connectionId:atom('fixture-primary'),profile:atom('fixture'),gateway:atom('open')},
  profileRoutes:async()=>[{primary:true,mode:'local',connectionId:'fixture-primary',profile:'fixture',targetProfile:'fixture'}],
  async request(method,payload){
    window.fixtureRequests.push({method,payload});
    if(window.fixtureFailProductionList&&method.includes('.production.')&&method.endsWith('.list')){
      throw new Error('CONTROLLED_PRODUCTION_LIST_FAILURE');
    }
    if(window.fixtureHoldOperation&&method.endsWith('.'+window.fixtureHoldOperation)){
      await new Promise(resolve=>{window.fixtureReleaseOperation=resolve;});
    }
    const result=await window.nativeRPC({op:'rpc',method:method.replace('plugin.motion-studio.technical.','').replace('plugin.motion-studio.',''),payload});
    if(window.fixtureLoseProductionCreate&&method.includes('.production.')&&method.endsWith('.create')){
      throw new Error('CONTROLLED_LOST_PRODUCTION_CREATE');
    }
    if(window.fixtureHideProductionList&&method.includes('.production.')&&method.endsWith('.list')){
      result.productions=[];
    }
    if(window.fixtureWrongTake&&method.includes('.production.')&&method.endsWith('.chunk')&&result?.take){
      result.take='f'.repeat(32);
    }
    const observed=result?.creations?.map(row=>row.request)||[];
    window.fixtureObservedCreationIds.push(...observed);
    if(method.endsWith('.prepare')&&window.fixtureLoseAck)throw new Error('CONTROLLED_LOST_ACK');
    return result;
  },composer:{getDraft:async session=>window.fixtureDrafts?.[session]??(session==='session-a'?window.fixtureDraft||'':''),
    insertText:async(session,text)=>{window.fixtureDrafts??={};const existing=window.fixtureDrafts[session]??(session==='session-a'?window.fixtureDraft||'':'');
      window.fixtureDrafts[session]=existing+'\n'+text;window.fixtureComposerCalls??=[];window.fixtureComposerCalls.push({session,text});
      if(session==='session-a')window.fixtureDraft=window.fixtureDrafts[session];window.fixtureDraftSession=session;return true;},
    submit:()=>{throw Error('No hidden Send');}}};
