import {helpStyles} from './help.js';
import {methodStyles} from './methods-ui.js';
// Motion Studio design system. Colors come from the active Hermes theme (--ui-*),
// with the design-concept graphite/cream/mint palette only as a fallback.
export const themeStyles=helpStyles+methodStyles+`
.ms{--ms-bg:color-mix(in srgb,var(--ms-text) 2%,transparent);--ms-surface:color-mix(in srgb,var(--ms-text) 4%,transparent);--ms-raised:color-mix(in srgb,var(--ms-text) 8%,transparent);
--ms-text:var(--ui-text-primary,#f2ecdf);--ms-muted:var(--ui-text-secondary,#a7afab);--ms-faint:var(--ui-text-tertiary,#7d8581);
--ms-line:color-mix(in srgb,var(--ms-text) 14%,transparent);--ms-accent:var(--ui-accent-primary,var(--ui-accent,#8fe3c0));--ms-warn:var(--ui-warning-primary,#e8b45a);
box-sizing:border-box;color:var(--ms-text);background:transparent;min-height:100%;padding:28px 32px 40px!important;max-width:none!important;margin:0!important;font-size:14px;line-height:1.5}
.ms *{box-sizing:border-box}
.ms-inner{max-width:1440px;margin:0 auto}
.ms h1,.ms h2,.ms h3{margin:0;font-weight:650;letter-spacing:-.01em}
.ms p{margin:0;overflow-wrap:anywhere}
.ms-top{display:flex;align-items:center;gap:20px;flex-wrap:wrap;min-height:56px;padding:0 0 18px;margin:0 0 28px;border-bottom:1px solid var(--ms-line)}
.ms.ms .ms-top .ms-tab{min-height:0;height:36px;padding:0 14px;margin:0;border:0;line-height:36px;font-size:14px}
.ms.ms .ms-top h1,.ms.ms .ms-top .ms-brand{margin:0;font-size:1.25rem;line-height:36px}
.ms-brand{display:flex;align-items:center;gap:10px;font-size:1.25rem;font-weight:700}
.ms-mark{width:26px;height:18px;border-radius:4px;background:linear-gradient(90deg,var(--ms-accent) 0 30%,transparent 30% 35%,var(--ms-accent) 35% 65%,transparent 65% 70%,var(--ms-accent) 70%);transform:skewX(-14deg)}
.ms-tabs{display:flex;gap:4px;flex-wrap:wrap}
.ms-tab{appearance:none;border:0;background:transparent;color:var(--ms-muted);font:inherit;font-weight:600;padding:8px 14px;border-radius:8px;cursor:pointer}
.ms-tab:hover{color:var(--ms-text);background:var(--ms-raised)}
.ms-tab[aria-current="page"]{color:var(--ms-text);background:color-mix(in srgb,var(--ms-accent) 18%,transparent);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ms-accent) 45%,transparent)}
.ms-spacer{flex:1}
.ms-status{font-size:12.5px;color:var(--ms-muted);display:flex;align-items:center;gap:8px;min-height:20px}
.ms-status::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--ms-accent);flex:none}
.ms-hero{margin-bottom:18px}
.ms-composer{border:1px solid color-mix(in srgb,var(--ms-accent) 55%,var(--ms-line));border-radius:16px;background:var(--ms-surface);overflow:hidden}
.ms-composer:focus-within{box-shadow:0 0 0 3px color-mix(in srgb,var(--ms-accent) 25%,transparent)}
.ms .ms-composer textarea{border:0;border-radius:0;background:transparent;min-height:96px;font-size:1.05rem;padding:16px 18px;resize:vertical}
.ms .ms-composer textarea:focus-visible{outline:none}
.ms-composer-bar{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:center;padding:10px 12px;border-top:1px solid var(--ms-line)}
.ms-composer-bar .ms-chips{margin-top:0}
button.ms-chip{appearance:none;background:transparent;font:inherit;font-size:12.5px;font-weight:600;cursor:pointer}
button.ms-chip:hover{color:var(--ms-text)}
.ms-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:14px}
.ms-more{position:relative}.ms-more>summary{list-style:none}.ms-more>summary::-webkit-details-marker{display:none}
.ms-more-body{position:absolute;right:0;top:calc(100% + 6px);z-index:5;background:var(--ui-bg-secondary,#171c1b);border:1px solid var(--ms-line);border-radius:10px;padding:10px;box-shadow:0 8px 24px rgba(0,0,0,.35);width:max-content;max-width:80vw}
.ms-visually-hidden{position:absolute!important;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.ms-hero h1{font-size:2rem;line-height:1.15}
.ms-sub{color:var(--ms-muted);font-size:1rem;margin-top:6px!important;max-width:62ch}
.ms-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.ms-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:999px;border:1px solid var(--ms-line);color:var(--ms-muted);font-size:12.5px;font-weight:600}
.ms-chip[data-on="true"]{color:var(--ms-text);border-color:color-mix(in srgb,var(--ms-accent) 55%,transparent);background:color-mix(in srgb,var(--ms-accent) 12%,transparent)}
.ms-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.ms .ms-btn{min-height:34px;padding:0 14px;font-size:13px;border-radius:8px}
.ms-grid{display:grid;grid-template-columns:minmax(260px,340px) minmax(0,1fr);gap:24px;align-items:start}
.ms-section-title{font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ms-faint);font-weight:700;margin-bottom:10px!important}
.ms-list{display:flex;flex-direction:column;gap:8px}
.ms-card{display:block;width:100%;text-align:left;font:inherit;color:inherit;cursor:pointer;background:var(--ms-surface);border:1px solid var(--ms-line);border-radius:12px;padding:12px 14px}
.ms-card:hover{border-color:color-mix(in srgb,var(--ms-accent) 40%,var(--ms-line))}
.ms-card[aria-pressed="true"]{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent)}
.ms-card-title{font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ms-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.ms-badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:6px;font-size:11.5px;font-weight:650;background:var(--ms-raised);color:var(--ms-muted)}
.ms-badge[data-tone="good"]{color:var(--ms-accent);background:color-mix(in srgb,var(--ms-accent) 14%,transparent)}
.ms-badge[data-tone="warn"]{color:var(--ms-warn);background:color-mix(in srgb,var(--ms-warn) 14%,transparent)}
.ms-panel{background:var(--ms-surface);border:1px solid var(--ms-line);border-radius:16px;padding:24px;min-width:0}
.ms-panel h2{font-size:1.45rem;line-height:1.25}
.ms-request{color:var(--ms-muted);margin-top:8px!important;max-width:90ch}
.ms-request[data-clamp="true"]{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ms-linkish{appearance:none;border:0;background:transparent;padding:0;margin-top:4px;color:var(--ms-accent);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.ms-seg{display:inline-flex;border:1px solid var(--ms-line);border-radius:8px;overflow:hidden}
.ms-seg-btn{appearance:none;border:0;background:transparent;color:var(--ms-muted);font:inherit;font-size:12.5px;font-weight:600;min-height:34px;padding:0 12px;cursor:pointer}
.ms-seg-btn+.ms-seg-btn{border-left:1px solid var(--ms-line)}
.ms-seg-btn:hover:not(:disabled){color:var(--ms-text);background:var(--ms-raised)}.ms-seg-btn:disabled{opacity:.5;cursor:default}
.ms-seg-btn[aria-pressed="true"]{color:var(--ms-text);background:color-mix(in srgb,var(--ms-accent) 22%,transparent)}
.ms-take-player{display:grid;gap:6px}.ms-take-player video{width:100%;max-height:60vh;border-radius:8px;background:color-mix(in srgb,var(--ms-text) 6%,transparent)}
.ms-thumb{appearance:none;display:block;width:100%;padding:0;border:1px solid var(--ms-line);border-radius:10px;overflow:hidden;cursor:zoom-in;background:color-mix(in srgb,var(--ms-text) 4%,transparent)}
.ms-thumb[aria-expanded="true"]{cursor:zoom-out;border-color:var(--ms-accent)}
.ms-thumb img{display:block;width:100%;height:180px;object-fit:contain}
.ms-take[data-form="image"]:has(.ms-zoom){grid-column:1/-1}
.ms-zoom{display:grid;gap:8px}.ms-zoom-bar{display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;color:var(--ms-muted)}
.ms-zoom-bar select{font:inherit;min-height:32px;padding:4px 8px;border:1px solid var(--ms-line);border-radius:8px;background:var(--ms-bg);color:var(--ms-text)}
.ms-zoom-view{max-height:72vh;overflow:auto;border:1px solid var(--ms-line);border-radius:10px;padding:2px}.ms-zoom-view img{display:block;height:auto}
.ms-card-title{display:flex;align-items:center;gap:8px}.ms-card-text{min-width:0;overflow:hidden;text-overflow:ellipsis}.ms-card-icon{flex:none;display:inline-flex;color:var(--ms-muted)}
.ms-kind-note{color:var(--ms-muted)}
.ms-card-time{margin-left:auto;font-size:11.5px;color:var(--ms-faint);align-self:center}
.ms-block{margin-top:24px;padding-top:20px;border-top:1px solid var(--ms-line)}
.ms-takes{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:12px}
.ms-take{border:1px solid var(--ms-line);border-radius:12px;padding:14px;background:var(--ms-bg);display:flex;flex-direction:column;gap:10px}
.ms-take[data-selected="true"]{border-color:var(--ms-accent)}
.ms-take-head{display:flex;justify-content:space-between;align-items:center;gap:8px;font-weight:650}
.ms audio{width:100%;height:40px}
.ms a.ms-link{color:var(--ms-accent);font-weight:600;text-decoration:none}.ms a.ms-link:hover{text-decoration:underline}
.ms label.ms-label{display:block;font-weight:650;margin-bottom:6px}
.ms textarea{width:100%;min-height:84px;background:var(--ms-bg);border:1px solid var(--ms-line);border-radius:10px;color:var(--ms-text);padding:10px 12px;font:inherit;resize:vertical}
.ms-help{color:var(--ms-faint);font-size:12.5px;margin-top:8px!important}
.ms-empty{border:1px dashed var(--ms-line);border-radius:12px;padding:22px;color:var(--ms-muted);text-align:center}
.ms details.ms-tech{margin-top:24px;border-top:1px solid var(--ms-line);padding-top:14px;color:var(--ms-faint);font-size:12.5px}
.ms details.ms-tech summary{cursor:pointer;font-weight:600;color:var(--ms-muted)}
.ms details.ms-tech p{margin-top:6px!important}
.ms-notice{border:1px solid color-mix(in srgb,var(--ms-warn) 45%,transparent);background:color-mix(in srgb,var(--ms-warn) 10%,transparent);border-radius:10px;padding:10px 12px;margin-top:14px!important}
.ms button:focus-visible,.ms textarea:focus-visible,.ms a:focus-visible,.ms summary:focus-visible,.ms select:focus-visible,.ms input:focus-visible{outline:2px solid var(--ms-accent);outline-offset:2px}
@media(max-width:820px){.ms{padding:18px 16px 28px}.ms-hero{grid-template-columns:1fr}.ms-grid{grid-template-columns:1fr}.ms-hero h1{font-size:1.6rem}.ms-panel{padding:16px}}

.ms-action{display:inline-flex;flex-direction:column;align-items:flex-start;gap:5px;max-width:100%;min-width:0}
.ms-action-result{font-size:12.5px;line-height:1.4;max-width:38ch;overflow-wrap:anywhere}
.ms-action-result:empty{display:none}.ms-action-result[data-tone="good"]{color:var(--ui-success-primary,#8fe3c0)}.ms-action-result[data-tone="warn"]{color:var(--ms-warn)}
.ms-busy-dot{display:inline-block;width:7px;height:7px;margin-right:7px;border-radius:50%;background:currentColor;animation:ms-busy 800ms ease-in-out infinite alternate}
.ms-method-feedback{border:0;padding:0;margin:0;min-width:0}.ms-method-feedback>.ms-action-result{display:block;padding:0 12px 8px}
.ms-feedback-pulse{animation:ms-feedback-pulse 700ms ease-out 1}.ms-card-changed{animation:ms-card-highlight 3s ease-out 1}
@keyframes ms-busy{to{opacity:.3}}@keyframes ms-feedback-pulse{50%{background:color-mix(in srgb,var(--ms-accent) 28%,transparent);box-shadow:0 0 0 4px color-mix(in srgb,var(--ms-accent) 18%,transparent)}}
@keyframes ms-card-highlight{from{background:color-mix(in srgb,var(--ms-accent) 22%,var(--ms-surface))}to{background:var(--ms-surface)}}
@media(prefers-reduced-motion:reduce){.ms *{transition:none!important;animation:none!important}.ms-card-changed{outline:2px solid var(--ms-accent);outline-offset:2px}.ms-feedback-pulse{background:color-mix(in srgb,var(--ms-accent) 18%,transparent)}}
`;
export const creationStyles=themeStyles;
