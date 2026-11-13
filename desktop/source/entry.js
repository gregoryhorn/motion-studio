import {createElement,useState} from 'react';
import {host,ROUTES_AREA,SIDEBAR_NAV_AREA} from '@hermes/plugin-sdk';
import {TechnicalController} from './controller.js';
import {TechnicalPage} from './page.js';
import {CreationPage} from './creation-page.js';
import {CreationController} from './creation-controller.js';
import {ProductionPage} from './production-page.js';
import {ProductionController} from './production-controller.js';
import {DirectorController} from './director-controller.js';
import {DirectorPage} from './director-page.js';
function Workspace({createController,createCreation,createProduction,createDirector}){
  const [lane,setLane]=useState('creation');
  return createElement('div',null,createElement('button',{onClick:()=>setLane(lane==='technical'?'creation':'technical')},
      lane==='technical'?'Back to creations':'Technical proposals'),
    lane==='technical'?createElement(TechnicalPage,{createController}):lane==='tools'?
      createElement(DirectorPage,{createController:createDirector,onBack:()=>setLane('creation')}):lane==='production'?
      createElement(ProductionPage,{createController:createProduction,onQuickCreate:()=>setLane('creation'),onTools:()=>setLane('tools')}):
      createElement(CreationPage,{createController:createCreation,onProduction:()=>setLane('production'),onTools:()=>setLane('tools')}));
}
export default {id:'motion-studio',name:'Motion Studio',defaultEnabled:false,
  register(ctx){
    const controllers=new Set();
    const createController=notify=>{const value=new TechnicalController(host,ctx.storage,notify);
      const dispose=value.dispose.bind(value);value.dispose=()=>{dispose();controllers.delete(value);};controllers.add(value);return value;};
    const createCreation=notify=>{const value=new CreationController(host,notify);
      const dispose=value.dispose.bind(value);value.dispose=()=>{dispose();controllers.delete(value);};controllers.add(value);return value;};
    const createProduction=notify=>{const value=new ProductionController(host,notify);
      const dispose=value.dispose.bind(value);value.dispose=()=>{dispose();controllers.delete(value);};controllers.add(value);return value;};
    const createDirector=notify=>{const value=new DirectorController(host,notify);
      const dispose=value.dispose.bind(value);value.dispose=()=>{dispose();controllers.delete(value);};controllers.add(value);return value;};
    ctx.onDispose(()=>{for(const controller of controllers)controller.dispose();controllers.clear();});
    ctx.register({id:'route',area:ROUTES_AREA,data:{path:'/motion-studio'},render:()=>createElement(Workspace,{createController,createCreation,createProduction,createDirector})});
    ctx.register({id:'navigation',area:SIDEBAR_NAV_AREA,data:{path:'/motion-studio',label:'Motion Studio',codicon:'project'}});
  }
};
