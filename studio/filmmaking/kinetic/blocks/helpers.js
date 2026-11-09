import { C, DUR, FPS, E, clamp, lerp, tw, rgba, el, set, styleType } from '../core.js';

// ---------- helpers (exported for custom blocks) ----------
const NS = 'http://www.w3.org/2000/svg';
export function svg(tag, parent, attrs = {}) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
export const qb = (a, b, c, u) => {
  const v = 1 - u;
  return [v * v * a[0] + 2 * v * u * b[0] + u * u * c[0], v * v * a[1] + 2 * v * u * b[1] + u * u * c[1]];
};
export const cb = (a, b, c, d, u) => {
  const v = 1 - u;
  return [v * v * v * a[0] + 3 * v * v * u * b[0] + 3 * v * u * u * c[0] + u * u * u * d[0], v * v * v * a[1] + 3 * v * v * u * b[1] + 3 * v * u * u * c[1] + u * u * u * d[1]];
};
// Reparametrise any curve by arc length, so a comet moves at the speed its easing says.
export function arcLen(fn, n = 400) {
  const P = [],
    L = [0];
  for (let i = 0; i <= n; i++) {
    P.push(fn(i / n));
    if (i) L.push(L[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
  }
  const tot = L[n];
  const f = u => {
    const d = clamp(u) * tot;
    let lo = 0,
      hi = n;
    while (hi - lo > 1) {
      const m = lo + hi >> 1;
      if (L[m] < d) lo = m;else hi = m;
    }
    const s = (d - L[lo]) / (L[hi] - L[lo] || 1);
    return [lerp(P[lo][0], P[hi][0], s), lerp(P[lo][1], P[hi][1], s)];
  };
  f.len = tot;
  return f;
}
export const polyline = pts => arcLen(u => {
  const n = pts.length - 1,
    x = clamp(u) * n,
    i = Math.min(n - 1, Math.floor(x)),
    s = x - i;
  return [lerp(pts[i][0], pts[i + 1][0], s), lerp(pts[i][1], pts[i + 1][1], s)];
}, pts.length * 60);
export const chamferPts = (x, y, w, h, c) => [[x + c, y], [x + w - c, y], [x + w, y + c], [x + w, y + h - c], [x + w - c, y + h], [x + c, y + h], [x, y + h - c], [x, y + c], [x + c, y]];
export const ptsAttr = P => P.map(p => p.map(v => v.toFixed(1)).join(',')).join(' ');
export const shake = (a, amp = 10, k = 16, w = 64) => a < 0 ? 0 : amp * Math.exp(-k * a) * Math.sin(w * a);
export const GLYPHS = '{}<>/;=()[]*+'.split('');
export const fmt = n => n.toLocaleString('en-US');
export const meas = e => [e.offsetWidth, e.offsetHeight];
// position of an element relative to an ancestor (offsetLeft alone is relative to the nearest transformed parent)
export function relPos(e, root) {
  let x = 0,
    y = 0;
  for (let n = e; n && n !== root; n = n.offsetParent) {
    x += n.offsetLeft;
    y += n.offsetTop;
    if (n.offsetParent === null) break;
  }
  return [x, y];
}
// {lines}, {frames} and {seconds} in on-screen text are filled from the film itself, so the numbers stay true
export const fillVars = (f, v) => String(v).replace('{lines}', fmt(f.src.lines || 0)).replace('{frames}', fmt(Math.round(DUR * FPS))).replace('{seconds}', String(Math.round(DUR)));
export const punch = (t, t0, k = 9) => t < t0 ? 0 : Math.exp(-k * (t - t0));
// palette names ('bg', 'paper', 'accent', 'hot', 'ink') or any CSS colour
export const cc = c => c && C[c] || c;
const isLight = g => !!g && g !== 'bg' && g !== C.bg;
const typeOn = g => isLight(g) ? C.ink : C.paper;
export function glowDot(x, cx, cy, r, a = 1, color = C.accent) {
  if (a <= 0) return;
  const g = x.createRadialGradient(cx, cy, 0, cx, cy, r * 3.4);
  g.addColorStop(0, rgba(C.tint, a));
  g.addColorStop(.22, rgba(C.tint2, .95 * a));
  g.addColorStop(.45, rgba(color, .55 * a));
  g.addColorStop(1, rgba(color, 0));
  x.save();
  x.globalCompositeOperation = 'lighter';
  x.fillStyle = g;
  x.beginPath();
  x.arc(cx, cy, r * 3.4, 0, 7);
  x.fill();
  x.restore();
}
// slot-reel number: every digit is a column of 0-9 that spins down and settles on its target
export function reel(parent, text, o) {
  const row = el('div', parent, 'abs reel');
  styleType(row, o);
  row.cols = [];
  for (const ch of String(text)) {
    if (!/\d/.test(ch)) {
      el('span', row, 'rch').textContent = ch;
      continue;
    }
    const c = el('span', row, 'rcol'),
      inner = el('span', c, 'rin');
    inner.textContent = Array.from({
      length: 30
    }, (_, i) => i % 10).join('\n');
    const probe = el('span', row, 'rch');
    probe.textContent = ch;
    c.style.width = probe.offsetWidth + 'px';
    probe.remove();
    row.cols.push({
      inner,
      d: +ch
    });
  }
  return row;
}
export function spinReel(row, t, t0, dur = .7, stagger = .07) {
  row.cols.forEach((c, i) => {
    const u = E.outCubic(clamp((t - t0 - i * stagger) / dur)),
      pos = (20 + c.d) * u;
    set(c.inner, 'transform', `translateY(${(-pos).toFixed(4)}em)`);
  });
}
// a bright band that sweeps across a face (background-clip text)
export function sheen(face, base) {
  Object.assign(face.style, {
    backgroundImage: `linear-gradient(100deg, ${base} 40%, #FFFFFF 47%, ${C.tint} 50%, ${base} 57%)`,
    backgroundSize: '320% 100%',
    webkitBackgroundClip: 'text',
    backgroundClip: 'text',
    color: 'transparent',
    backgroundPosition: '100% 0'
  });
}
// camera that flies through the counter of a glyph: P = the glyph's centre in stage coordinates
function zoomThrough(t, ta, tb, P, base) {
  const z = tw(t, ta, tb, E.inExpo);
  if (z <= 0) return null;
  const s0 = base.s || 1,
    S = s0 * Math.exp(Math.log(70) * z),
    m = E.inOutCubic(clamp(z * 1.5));
  const tx = lerp(960 + s0 * (P[0] - 960), 960, m),
    ty = lerp(540 + s0 * (P[1] - 540), 540, m);
  return {
    x: P[0] - 960 - (tx - 960) / S,
    y: P[1] - 540 - (ty - 540) / S,
    s: S,
    r: (base.r || 0) * (1 - clamp(z * 3))
  };
}
// the centre of a glyph's counter (the hole of an O, 0, D...) inside a letters() element placed at (cx, cy)
function counterOf(L, i, cx, cy, size) {
  const sp = L.spans[i],
    [w, h] = meas(L.e);
  return [cx - w / 2 + sp.offsetLeft + sp.offsetWidth / 2, cy - h / 2 + .48 * size];
}
// punch effects on an entrance: hit 1 = flash and shake, hit 2 = rays, ring and sparks too
function hitFx(f, t0, o = {}) {
  const hit = o.hit ?? 1,
    g = o.ground,
    light = isLight(g);
  if (!hit) return;
  f.shake(t0, 9 + 5 * hit);
  f.bump(t0, .025 + .02 * hit);
  f.fast(t0 - .03, t0 + .28, hit > 1 ? 12 : 8);
  if (hit > 1) {
    const rc = light ? C.ink : o.rayColor ? cc(o.rayColor) : C.paper;
    f.ray({
      t0,
      dur: .55,
      color: rc,
      n: 90,
      r0: 120,
      r1: 1600,
      w: 2.6,
      screen: true,
      seed: Math.round(t0 * 97),
      ...(light ? {
        blend: 'source-over',
        alpha: .5
      } : {})
    });
    f.ring({
      t0,
      dur: .5,
      r0: 40,
      r1: 1100,
      w: 16,
      color: light ? C.ink : C.accent,
      screen: true,
      ...(light ? {
        blend: 'source-over',
        alpha: .45
      } : {})
    });
    if (o.at) f.burst({
      t0,
      x: o.at[0],
      y: o.at[1],
      n: 44,
      speed: 1700,
      life: .55,
      w: 3.3,
      seed: Math.round(t0 * 13),
      ...(light ? {
        color: C.ink,
        blend: 'source-over'
      } : {})
    });
    f.flash({
      t0,
      dur: .24,
      rise: .015,
      color: C.accent,
      peak: light ? .12 : .24
    });
  } else f.flash({
    t0,
    dur: .12,
    rise: .01,
    color: '#FFFFFF',
    peak: light ? .2 : .3
  });
}
export { counterOf, hitFx, isLight, typeOn, zoomThrough };

// Shared type sizing used by several scene families.
export const fitTo = (w, max = 1760) => Math.min(1, max / Math.max(1, w));
