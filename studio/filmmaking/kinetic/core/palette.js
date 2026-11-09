import { mixc } from './color.js';

// palette: bg (dark ground), paper (light ground and light type), accent (the brand colour), hot (a hotter accent),
// ink (type on light grounds). Everything else is derived.
export const C = { bg: '#0C0E11', paper: '#F4F1EA', accent: '#FF5B2E', hot: '#FF3A0A', ink: '#141210' };
export function setPalette(p = {}) {
  Object.assign(C, p);
  C.tint = mixc(C.accent, '#FFFFFF', .72);      // the white-hot core of the comet and slashes
  C.tint2 = mixc(C.accent, '#FFFFFF', .5);
  C.side0 = mixc(C.accent, '#000000', .45);     // extrusion side colours
  C.side1 = mixc(C.bg, '#000000', .25);
  C.sideP = mixc(C.accent, '#000000', .62);
  C.panel = mixc(C.bg, C.paper, .035);
  const r = document.documentElement.style;
  for (const k of ['bg', 'paper', 'accent', 'hot', 'ink', 'panel']) r.setProperty('--' + k, C[k]);
}
