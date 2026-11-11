// Colors follow the host theme through the shared --ms-* tokens (see creation-style.js).
export const mediaReviewStyles=`
.media-review{color:var(--ms-text,var(--ui-text-primary,#f2efe6));background:var(--ms-surface,transparent);padding:18px;border:1px solid var(--ms-line,var(--ui-stroke-secondary,#343b36));border-radius:16px;min-width:0;display:grid;gap:10px}
.media-review *{box-sizing:border-box}.media-review p,.media-review summary{overflow-wrap:anywhere;font-size:13px;color:var(--ms-muted,inherit)}
.media-review h3{font-size:1.15rem}.media-review h4{margin:0 0 4px;font-size:.95rem}
.media-review-slots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:start}
.media-review-slot{min-width:0;border:1px solid var(--ms-line,#343b36);padding:14px;border-radius:12px;background:var(--ms-bg,transparent)}
.media-review label{display:flex;flex-direction:column;gap:6px;margin:10px 0;min-width:0}
.media-review input,.media-review select,.media-review button{font:inherit;max-width:100%;min-width:0;min-height:36px}
.media-review input:not([type=range]),.media-review select{color:inherit;background:var(--ms-bg,transparent);border:1px solid var(--ms-line,#64756a);border-radius:8px;padding:6px 10px}
.media-review input[type=range]{accent-color:var(--ms-accent,#9be7c4)}
.media-review button{color:inherit;background:var(--ms-surface,transparent);border:1px solid var(--ms-line,#64756a);border-radius:8px;padding:6px 14px;font-size:13px;font-weight:600;white-space:normal;overflow-wrap:anywhere;cursor:pointer}
.media-review button:hover:not(:disabled){background:var(--ms-raised,transparent)}
.media-review button:disabled{opacity:.5;cursor:default}.media-review button[aria-pressed=true]{background:color-mix(in srgb,var(--ms-accent,#9be7c4) 18%,transparent);border-color:var(--ms-accent,#9be7c4)}
.media-review summary{cursor:pointer;min-height:32px;padding:6px 0;font-weight:600}
.media-review :is(button,input,select,summary,[tabindex]):focus-visible{outline:2px solid var(--ms-accent,#9be7c4);outline-offset:2px}
.media-review-image-viewport{max-width:100%;max-height:70vh;overflow:auto;background:color-mix(in srgb,var(--ms-text,#fff) 3%,transparent);border:1px solid var(--ms-line,#64756a);border-radius:10px;padding:2px}
.media-review-image-viewport img{display:block;height:auto}.media-review-monitor{min-width:0;margin-top:8px}
.media-review-monitor [role=group]{border:1px solid var(--ms-line,#64756a);border-radius:10px;padding:12px}
.media-review video,.media-review audio{display:block;width:100%;max-width:100%;max-height:70vh;object-fit:contain;border-radius:8px}
.media-review-actions{display:flex;flex-wrap:wrap;gap:8px}
.media-review-one{padding:20px}.media-review-single{display:grid;gap:14px;justify-items:stretch}
.media-review-wait{min-height:160px;display:grid;place-content:center;justify-items:center;gap:10px;text-align:center}
.media-review-badges{display:flex;flex-wrap:wrap;gap:6px}.media-review-badge{display:inline-flex;padding:2px 8px;border-radius:6px;font-size:11.5px;font-weight:650;background:var(--ms-raised,rgba(128,128,128,.2));color:var(--ms-muted,inherit)}
.media-review-facts{display:grid;gap:4px}.media-review-facts summary{color:var(--ms-faint,inherit);font-size:12.5px}
.media-review label.media-review-zoom{flex-direction:row;align-items:center;gap:8px;margin:0 0 8px;font-size:13px}.media-review-zoom select{width:auto}
.media-review-slot[data-on=true]{border-color:var(--ms-accent,#9be7c4)}
.media-review-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0 16px}
@media(max-width:600px){.media-review-slots{grid-template-columns:minmax(0,1fr)}.media-review{padding:12px}.media-review-slot{padding:10px}}
@media(prefers-reduced-motion:reduce){.media-review *{animation:none!important;transition:none!important}}
`;
