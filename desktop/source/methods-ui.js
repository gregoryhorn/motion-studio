import {createElement as h} from 'react';

// Per-media method picker with honest cost basis. `methods` is the methods.list
// response ({kinds:{Kind:{default,options:[...]}}}); missing data shows a clear fallback.
const COST={free:['Free','good'],subscription:['Included in subscription','good'],paid:['Paid per use','warn'],unknown:['Cost unknown','warn']};
export function costLabel(cost){return (COST[cost]||COST.unknown)[0];}

export function chosenMethod(methods,kind,choice){
  const entry=methods?.kinds?.[kind],options=entry?.options||[];
  // An explicit choice is never silently replaced: if it is not set up, nothing is chosen until the user picks again.
  if(choice)return options.find(item=>item.id===choice)||{id:choice,label:'Previously selected method',available:false,reason:'This method is no longer listed. Choose an alternative deliberately.'};
  // Import is a way to bring a file in, not a way to create one, so it is never the automatic pick.
  const creates=item=>item.available&&item.id!=='import'&&item.engine!=='import';
  return options.find(item=>item.id===entry?.default&&creates(item))||options.find(creates)||null;
}

export function MethodPicker({methods,kind,choice,onChoose,idPrefix='ms-method',loadingError=false}){
  const entry=methods?.kinds?.[kind];
  if(!entry)return h('p',{className:'ms-help ms-method-empty'},loadingError?'Method information could not be loaded. Retry loading deliberately.':methods?'No method information for '+kind+'.':'Checking which methods are available on this PC...');
  const current=chosenMethod(methods,kind,choice),listed=entry.options||[];
  const options=current&&!listed.some(item=>item.id===current.id)?[current,...listed]:listed;
  const importing=current?.action==='import'||current?.engine==='import'||current?.id==='import';
  const [label,tone]=current?.available?(importing?['Import existing file',undefined]:COST[current.cost]||COST.unknown):['Unavailable - choose another method','warn'];
  return h('div',{className:'ms-method'},
    h('label',{className:'ms-method-label',htmlFor:idPrefix},'Method'),
    h('select',{id:idPrefix,className:'ms-method-select',value:current?.id||choice||'',onChange:event=>onChoose(event.target.value)},
      ...(current||choice?[]:[h('option',{key:'',value:'',disabled:true},'Choose a method')]),...options.map(item=>h('option',{key:item.id,value:item.id,disabled:!item.available},
        item.label+(item.id===entry.default?' (default)':'')+' - '+(item.available?costLabel(item.cost):(item.reason||'Not available'))))),
    h('span',{className:'ms-badge','data-tone':tone},label),
    current?h('span',{className:'ms-badge'},importing?'Existing file':current.engine==='local'?'Runs on this PC':'Cloud'):null,
    current&&!current.available?h('span',{className:'ms-help ms-method-note'},current.reason||'Not available; choose an alternative deliberately.'):null,
    current?.note?h('span',{className:'ms-help ms-method-note'},current.note):null,
    current&&!importing?h('span',{className:'ms-help ms-method-note'},'Operation qualification: '+(current.operation_qualified||'unknown')+'. Intended-use permission: '+(current.permitted_for_use||'not assessed')+'. Presence is not admission.'):null,
    h('details',{className:'ms-method-all'},h('summary',null,'All '+kind+' options ('+options.filter(item=>item.available).length+' of '+options.length+' set up)'),
      h('p',{className:'ms-help'},'Set up means the tool, model or key was found on this PC. It has not been test-run for this request.'),
      h('ul',null,...options.map(item=>h('li',{key:item.id},h('strong',null,item.label),' - ',item.engine==='local'?'local':'cloud',', ',
        item.available?costLabel(item.cost):'unavailable: '+(item.reason||'not set up'),item.note?' - '+item.note:'')))));
}

export const methodStyles=`
.ms-method{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 12px;border-top:1px solid var(--ms-line)}
.ms-method-label{font-weight:650;font-size:12.5px;color:var(--ms-muted)}
.ms-method-select{background:var(--ms-bg);color:var(--ms-text);border:1px solid var(--ms-line);border-radius:8px;min-height:32px;padding:0 8px;font:inherit;max-width:100%}
.ms-method-note{margin:0!important}
.ms-method-all{flex-basis:100%;font-size:12.5px;color:var(--ms-muted)}.ms-method-all summary{cursor:pointer}
.ms-method-all ul{margin:6px 0 0;padding-left:18px;columns:2 260px}.ms-method-all li{margin:2px 0;break-inside:avoid}
.ms-method-empty{padding:10px 12px;margin:0!important;border-top:1px solid var(--ms-line)}
`;
