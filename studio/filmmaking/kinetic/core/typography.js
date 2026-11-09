import { C } from './palette.js';
import { E, clamp, lerp, rng } from './math.js';
import { mixc, rgba } from './color.js';
import { el, set } from './dom.js';

// Display type. font-variation-settings drives Archivo's wght and wdth axes directly.
export function type(parent, text, o = {}) {
  const e = el('div', parent, 'type ' + (o.cls || ''));
  e.textContent = text;
  styleType(e, o);
  return e;
}
export function styleType(e, o = {}) {
  const s = e.style;
  s.fontFamily = o.font || 'Archivo';
  s.fontSize = (o.size || 150) + 'px';
  if (!o.font || o.font === 'Archivo') s.fontVariationSettings = `'wght' ${o.wght || 900}, 'wdth' ${o.wdth || 100}`;
  else s.fontWeight = o.weight || 700;
  s.color = o.color || C.paper;
  if (o.stroke) { s.color = 'transparent'; s.webkitTextStroke = `${o.stroke}px ${o.color || C.paper}`; }
  else if (s.webkitTextStroke) s.webkitTextStroke = '';
  s.letterSpacing = (o.ls || 0) + 'em';
  if (o.glow) s.textShadow = `0 0 ${o.glow}px ${rgba(C.accent, .55)}, 0 0 ${o.glow * 2.6}px ${rgba(C.accent, .28)}`;
}
// One span per letter, for per-letter animation.
export function letters(parent, text, o = {}) {
  const e = el('div', parent, 'type ' + (o.cls || ''));
  styleType(e, o);
  const spans = [...text].map(ch => { const s = el('span', e, 'ch'); s.textContent = ch === ' ' ? ' ' : ch; return s; });
  return { e, spans };
}
// Extruded 3D type: a stack of copies along -Z. The parent must preserve-3d.
export function extrude(parent, text, o = {}) {
  const g = el('div', parent, 'p3d xg');
  const n = o.layers || 32, depth = o.depth || 70;
  const s0 = o.side0 || C.side0, s1 = o.side1 || C.side1;
  const L = [];
  for (let i = n; i >= 0; i--) {
    const s = el('div', g, 'type xl');
    s.textContent = text;
    styleType(s, { ...o, glow: 0, color: i === 0 ? (o.face || C.paper) : mixc(s0, s1, i / n) });
    s.style.transform = `translateZ(${(-depth * i / n).toFixed(2)}px)`;
    if (i === 0 && o.glow) s.style.textShadow = `0 0 ${o.glow}px ${rgba(C.accent, .5)}`;
    L.push(s);
  }
  g.face = L[L.length - 1];
  return g;
}

// A type element cut into horizontal bands, so it can glitch (offset each band).
export function slices(parent, text, o = {}, k = 7) {
  const g = el('div', parent, 'abs');
  const parts = [];
  for (let i = 0; i < k; i++) {
    const e = type(g, text, { ...o, cls: (o.cls || '') + (i ? ' abs' : '') });
    e.style.clipPath = `inset(${(i / k * 100).toFixed(2)}% -10% ${(100 - (i + 1) / k * 100).toFixed(2)}% -10%)`;
    if (i) { e.style.left = '0'; e.style.top = '0'; }
    parts.push(e);
  }
  g.parts = parts; g.w = parts[0].offsetWidth; g.h = parts[0].offsetHeight;
  return g;
}
export function glitch(g, t, t0, dur, amp = 90, seed = 1) {
  const on = t >= t0 && t < t0 + dur, r = rng(seed + Math.floor(t * 30));
  g.parts.forEach((p, i) => set(p, 'transform', on ? `translateX(${((r() - .5) * 2 * amp * (r() < .55 ? 1 : .15)).toFixed(1)}px)` : 'none'));
}
// Per-letter tumble-in: each letter drops, spins and scales into place, staggered.
export function tumble(spans, t, t0, o = {}) {
  const { stagger = .03, dur = .32, rot = 70, dy = -140, seed = 4, from = .2 } = o;
  const r = rng(seed);
  spans.forEach((s, i) => {
    const rv = r() - .5, dv = .5 + r(), u = clamp((t - t0 - i * stagger) / dur), e = E.outBack(u, 2);
    set(s, 'display', 'inline-block');
    set(s, 'transform', `translateY(${((1 - e) * dy * dv).toFixed(1)}px) rotate(${((1 - e) * rot * rv * 2).toFixed(2)}deg) scale(${lerp(from, 1, e).toFixed(3)})`);
    set(s, 'opacity', clamp(u * 3).toFixed(3));
  });
}
