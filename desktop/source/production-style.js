import {themeStyles} from './creation-style.js';
// Production-only rules live under .production-body so nothing reaches the shared .ms-top header.
export const productionStyles=themeStyles+`
.production-body{container-type:inline-size;container-name:production;min-width:0}
.production-notice{margin:12px 0;padding:12px 16px;border:1px solid var(--ms-accent);border-radius:8px;background:var(--ms-surface);color:var(--ms-text);font-weight:600;overflow-wrap:anywhere}
.production-body button{font:inherit;cursor:pointer;max-width:100%}
.production-body button:disabled{cursor:default}
.production-body .pd-btn{display:inline-flex;align-items:center;justify-content:center;min-height:36px;padding:6px 14px;border-radius:8px;border:1px solid var(--ms-line);background:var(--ms-surface);color:var(--ms-text);font-size:13px;font-weight:600;line-height:1.25;white-space:normal;overflow-wrap:anywhere;list-style:none}
.production-body .pd-btn:hover:not(:disabled){background:var(--ms-raised)}
.production-body .pd-btn:disabled{opacity:.5}
.production-body .pd-primary{background:color-mix(in srgb,var(--ms-accent) 30%,transparent);border-color:var(--ms-accent);font-weight:700}
.production-body .pd-primary:hover:not(:disabled){background:color-mix(in srgb,var(--ms-accent) 42%,transparent)}
.production-body .pd-accent{border-color:color-mix(in srgb,var(--ms-accent) 70%,transparent)}
.production-body .pd-ghost{border-color:transparent;background:transparent;color:var(--ms-muted);cursor:pointer}
.production-body .pd-wide{width:100%;min-height:42px;font-size:14px}
.production-body summary.pd-btn::-webkit-details-marker{display:none}
.production-linkish{appearance:none;border:0;background:transparent;padding:0;color:var(--ms-accent);font-weight:600;font-size:inherit;text-decoration:underline;text-underline-offset:2px}
.production-body label{display:flex;flex-direction:column;gap:6px;margin:14px 0 0;font-weight:650;font-size:13px;min-width:0}
.production-body select,.production-body input:not([type=checkbox]):not([type=range]):not([type=file]){font:inherit;font-weight:400;min-height:36px;width:100%;max-width:100%;min-width:0;padding:6px 10px;border:1px solid var(--ms-line);border-radius:8px;background:var(--ms-bg);color:var(--ms-text)}
.production-body select option{background:var(--ui-bg-secondary,#171c1b);color:var(--ms-text)}
.production-body textarea{font-weight:400}.production-body textarea.production-short{min-height:56px}
.production-body input[type=checkbox]{flex:0 0 18px;width:18px;height:18px;margin:2px 0 0;accent-color:var(--ms-accent)}
.production-body fieldset{min-width:0;margin:14px 0 0;padding:10px 14px 14px;border:1px solid var(--ms-line);border-radius:10px}
.production-body fieldset legend{padding:0 6px;font-weight:650;font-size:13px}
.production-body fieldset label{flex-direction:row;align-items:flex-start;gap:10px;font-weight:400;margin-top:8px;overflow-wrap:anywhere}
.production-body audio{width:100%}.production-body video{max-width:100%}.production-body a{color:var(--ms-accent)}
.production-body progress{max-width:100%;accent-color:var(--ms-accent)}
.production-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.production-muted{color:var(--ms-muted);font-size:13px;overflow-wrap:anywhere}
.production-stale{color:var(--ms-warn)}.production-center{text-align:center}.production-gap{margin-top:24px!important}
.production-rule{border:0;border-top:1px solid var(--ms-line);margin:16px 0;width:100%}

.production-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 12px;margin:0 0 16px}
.production-body .production-project{display:flex;flex-direction:row;align-items:center;gap:10px;margin:0;min-width:0;max-width:100%}
.production-project>span{font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ms-faint);font-weight:700}
.production-body .production-project select{width:auto;max-width:min(100%,360px);font-size:1.05rem;font-weight:650;background:var(--ms-surface)}
.production-project strong{font-size:1.05rem}
.production-howto{margin:0 0 16px;font-size:13px}
.production-howto>summary{cursor:pointer;color:var(--ms-muted);font-weight:600;width:max-content;max-width:100%}
.production-howto[open]>summary{margin-bottom:10px}.production-howto .ms-steps{margin-bottom:4px}

.production-layout{display:grid;grid-template-columns:minmax(210px,250px) minmax(0,1fr) minmax(290px,344px);gap:24px;align-items:start}
.production-layout[data-project=false]{grid-template-columns:minmax(0,760px)}
.production-left{display:flex;flex-direction:column;gap:20px;min-width:0}
.production-main{min-width:0}
.production-sections{display:flex;flex-direction:column;gap:4px;padding-bottom:16px;border-bottom:1px solid var(--ms-line)}
.production-sections button{appearance:none;text-align:left;min-height:38px;padding:8px 12px;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--ms-muted);font-weight:600}
.production-sections button:hover{color:var(--ms-text);background:var(--ms-raised)}
.production-sections button[aria-pressed=true]{color:var(--ms-text);background:color-mix(in srgb,var(--ms-accent) 18%,transparent);border-color:color-mix(in srgb,var(--ms-accent) 45%,transparent)}
.production-rail-plan{min-width:0}
.production-rail-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:10px}
.production-rail-head .ms-section-title{margin:0!important}.production-rail-head .production-linkish{font-size:12.5px}

.production-board{display:flex;flex-direction:column;gap:8px;list-style:none;padding:0;margin:0}
.production-board-card{min-width:0;border:1px solid var(--ms-line);border-radius:12px;background:var(--ms-surface);overflow-wrap:anywhere}
.production-board-card[data-on=true]{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent);background:color-mix(in srgb,var(--ms-accent) 9%,transparent)}
.production-board .production-asset{appearance:none;display:flex;flex-direction:column;gap:5px;width:100%;min-height:44px;margin:0;padding:10px 12px 8px;border:0;border-radius:11px;background:transparent;color:inherit;text-align:left;overflow:hidden}
.production-board .production-asset:disabled{opacity:.65}
.production-asset-head{display:flex;align-items:center;gap:8px;color:var(--ms-muted);font-size:12px;min-width:0}
.production-asset-head strong{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.production-icon{flex:none}
.production-asset-intent{display:block;max-width:100%;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.production-badges{display:flex;gap:5px;flex-wrap:wrap}
.production-badge{padding:1px 7px;border-radius:6px;font-size:11px;font-weight:600;background:var(--ms-raised);color:var(--ms-muted)}
.production-badge[data-tone=good]{color:var(--ms-accent);background:color-mix(in srgb,var(--ms-accent) 14%,transparent)}
.production-badge[data-tone=warn]{color:var(--ms-warn);background:color-mix(in srgb,var(--ms-warn) 14%,transparent)}
.production-plan-details{min-width:0;overflow-wrap:anywhere;font-size:12.5px;color:var(--ms-muted)}
.production-board .production-plan-details{padding:0 12px 6px}
.production-plan-details summary{cursor:pointer;min-height:28px;padding:4px 0;color:var(--ms-faint);font-weight:600}
.production-plan-details p{margin:6px 0!important}.production-plan-details ul{padding-inline-start:18px;margin:6px 0}.production-plan-details li{margin:6px 0}
.production-take-id{display:block;font-size:.9em;color:var(--ms-faint);overflow-wrap:anywhere}
.production-plan-empty{border:1px dashed var(--ms-line);border-radius:12px;padding:14px;color:var(--ms-muted);font-size:13px}

.production-panel h2{font-size:1.35rem;margin-bottom:6px}.production-panel>.production-row{margin-top:18px}.production-row+.production-muted,.production-row+.ms-help{margin-top:10px!important}.production-panel h3{font-size:1rem}
.production-plan-editor{margin-top:18px;padding:16px;border:1px solid var(--ms-line);border-radius:12px;background:var(--ms-bg)}
.production-plan-editor .production-plan-details{margin-top:12px;font-size:13px}
.production-plan-editor>.production-row{margin-top:16px}
.production-body .production-order{align-items:flex-end;margin-top:14px}.production-body .production-order label{margin:0;width:150px}
.production-add{margin-top:22px;padding-top:18px;border-top:1px solid var(--ms-line)}
.production-add-row{display:grid;grid-template-columns:minmax(140px,200px) minmax(0,1fr);gap:0 12px;margin-bottom:14px}
.production-ref-actions{display:grid;gap:4px;margin-top:6px}.production-ref-actions>div{margin-top:12px}
.production-ref{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px;border:1px solid var(--ms-line);border-radius:12px;padding:12px 14px;margin-top:8px}
.production-ref .ms-tech{flex-basis:100%;margin-top:4px!important;padding-top:8px!important}
.production-outputs{list-style:none;margin:16px 0 0;padding:0;border:1px solid var(--ms-line);border-radius:12px}
.production-outputs li{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;padding:10px 14px}
.production-outputs li+li{border-top:1px solid var(--ms-line)}
.production-out-name{display:inline-flex;align-items:center;gap:8px;font-weight:650}
.production-export{margin-top:24px;padding-top:20px;border-top:1px solid var(--ms-line)}
.production-export h3{font-size:1.1rem;margin-bottom:6px}.production-export .production-row{margin-top:16px}

.production-title{font-size:1.7rem;line-height:1.2;overflow-wrap:anywhere}
.production-title-n{color:var(--ms-muted);font-variant-numeric:tabular-nums}
.production-sub{margin:4px 0 14px!important}
.production-viewer{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;min-height:clamp(220px,46cqw,440px);padding:28px;border:1px solid var(--ms-line);border-radius:16px;text-align:center;overflow:hidden;
background:radial-gradient(120% 90% at 50% 0%,color-mix(in srgb,var(--ms-accent) 12%,transparent),transparent 70%),var(--ms-surface)}
.production-viewer-open{display:block;text-align:left;padding:0;border:0;background:none;min-height:0}
.production-viewer-title{font-size:1.15rem;font-weight:650}
.production-player{width:min(100%,520px);display:grid;gap:8px;justify-items:center}
.production-wave{display:flex;align-items:center;justify-content:center;gap:4px;width:min(100%,460px);height:110px}
.production-wave i{flex:1 1 0;max-width:6px;min-width:2px;border-radius:3px;background:color-mix(in srgb,var(--ms-accent) 65%,transparent)}
.production-frame{width:min(60%,300px);aspect-ratio:16/9;border:1.5px dashed color-mix(in srgb,var(--ms-accent) 55%,var(--ms-line));border-radius:12px;background:linear-gradient(135deg,color-mix(in srgb,var(--ms-accent) 14%,transparent),transparent)}
.production-statusline{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin-top:12px}
.production-take-state{font-weight:650;color:var(--ms-muted);padding-left:12px;border-left:1px solid var(--ms-line)}
.production-take-state[data-on=true]{color:var(--ms-accent)}
.production-takes-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px;margin:22px 0 12px;padding-top:18px;border-top:1px solid var(--ms-line)}
.production-takes-head .ms-section-title{margin:0!important;font-size:.85rem}
.production-takes{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,170px),1fr));gap:12px}
.production-body .production-take{appearance:none;display:flex;flex-direction:column;gap:8px;padding:8px 8px 10px;border:1px solid var(--ms-line);border-radius:12px;background:var(--ms-surface);color:inherit;text-align:left;min-width:0}
.production-take:hover:not(:disabled){border-color:color-mix(in srgb,var(--ms-accent) 40%,var(--ms-line))}
.production-take[aria-pressed=true]{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent)}
.production-take-thumb{display:flex;align-items:center;justify-content:center;height:72px;border-radius:8px;background:var(--ms-raised);padding:0 12px;overflow:hidden}
.production-take-thumb .production-wave{height:44px;gap:2px}.production-take-thumb .production-wave i{background:color-mix(in srgb,var(--ms-text) 30%,transparent)}
.production-take[data-selected=true] .production-take-thumb .production-wave i{background:color-mix(in srgb,var(--ms-accent) 75%,transparent)}
.production-take-name{font-weight:650;padding:0 4px}.production-take[data-selected=true] .production-take-name{color:var(--ms-accent)}
.production-take .ms-meta{margin:0;padding:0 4px}

.production-create{min-width:0;border:1px solid var(--ms-line);border-radius:16px;background:var(--ms-surface);padding:20px}
.production-create h2{font-size:1.35rem;margin-bottom:12px}
.production-kinds{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 2px;border-bottom:1px solid var(--ms-line);margin-bottom:4px}
.production-body .production-kind{appearance:none;border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;color:var(--ms-muted);font-size:12.5px;font-weight:600;padding:8px 3px;margin-bottom:-1px;white-space:nowrap}
.production-kind:hover:not(:disabled){color:var(--ms-text)}.production-kind:disabled{opacity:.45}
.production-kind[aria-pressed=true]{color:var(--ms-text);border-bottom-color:var(--ms-accent)}
.production-create-body{display:flex;flex-direction:column}
.production-create textarea{min-height:110px;margin-bottom:14px}
.production-label{display:block;font-weight:650;font-size:13px;margin-bottom:6px}
.production-refs{margin-bottom:16px}.production-refining{margin:0 0 12px!important}.production-kind-note{margin:0 0 12px!important;color:var(--ms-muted)}
.production-create .ms-method{padding:0 0 12px;border-top:0}.production-chip-add{border-style:dashed}
.production-create .pd-wide+.pd-wide{margin-top:8px}
.production-create .ms-notice{margin:0 0 12px!important;font-size:12.5px}
.production-import{display:flex;flex-direction:column}.production-import .production-row{margin-top:10px}

.production-comparison{border:1px solid var(--ms-line);border-radius:16px;background:var(--ms-surface);padding:20px;display:grid;gap:10px}
.production-comparison h3{font-size:1.15rem}.production-comparison h4{margin:0 0 4px;font-size:.95rem}
.production-comparison p{overflow-wrap:anywhere;color:var(--ms-muted);font-size:13px}
.production-comparison-slots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.production-comparison-slot{min-width:0;border:1px solid var(--ms-line);padding:14px;border-radius:12px;display:grid;gap:8px;align-content:start;background:var(--ms-bg)}
.production-comparison-slot label{margin:0}
.production-comparison-active{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent)}
.production-comparison button{min-height:36px;padding:6px 14px;border-radius:8px;border:1px solid var(--ms-line);background:var(--ms-surface);color:var(--ms-text);font-size:13px;font-weight:600}
.production-comparison button:hover:not(:disabled){background:var(--ms-raised)}
.production-comparison button:disabled{opacity:.5}.production-comparison button[aria-pressed=true]{background:color-mix(in srgb,var(--ms-accent) 18%,transparent);border-color:var(--ms-accent)}
.production-comparison-player{padding:12px;border:1px solid var(--ms-line);border-radius:10px;color:var(--ms-muted);font-size:13px}
.production-comparison-player:focus-visible{outline:2px solid var(--ms-accent);outline-offset:2px}
.production-comparison summary{cursor:pointer;min-height:28px;padding:4px 0;overflow-wrap:anywhere;color:var(--ms-faint);font-size:12.5px;font-weight:600}
.production-comparison input[type=range]{accent-color:var(--ms-accent)}

@container production (max-width:1060px){
.production-layout{grid-template-columns:minmax(0,1fr) minmax(250px,300px);gap:20px}
.production-left{display:contents}
.production-sections{grid-column:1/-1;flex-direction:row;flex-wrap:wrap;gap:6px;padding-bottom:12px}
.production-sections button{flex:1 1 auto;text-align:center;min-height:40px;border-color:var(--ms-line)}
.production-rail-plan{grid-column:1/-1;order:3}
.production-board{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),1fr));align-items:start}
.production-layout[data-project=false]{grid-template-columns:minmax(0,1fr)}
}
@container production (max-width:700px){
.production-layout{grid-template-columns:minmax(0,1fr)}
.production-main{order:1}.production-create{order:2}
.production-title{font-size:1.35rem}.production-viewer{padding:18px}
.production-comparison-slots,.production-add-row{grid-template-columns:minmax(0,1fr)}
.production-create,.production-comparison{padding:16px}
}
@media(prefers-reduced-motion:reduce){.production-body *{animation:none!important;transition:none!important}}
`;
