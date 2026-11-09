import { W, H } from './timing.js';
import { C } from './palette.js';
import { E, clamp, lerp, rng } from './math.js';
import { rgba } from './color.js';
import { el } from './dom.js';

// ---------- FX canvas: comet, sparks, glyph bursts, slashes, dot flashes ----------
export class FX {
  constructor(parent, dsf, cls) {
    this.c = el('canvas', parent, 'fx ' + (cls || ''));
    this.c.width = W * dsf; this.c.height = H * dsf; this.dsf = dsf;
    this.x = this.c.getContext('2d');
  }
  clear() { const x = this.x; x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, this.c.width, this.c.height); x.setTransform(this.dsf, 0, 0, this.dsf, 0, 0); }
}

export function drawComet(x, seg, t) {
  const { t0, t1, path, ease = E.inOutCubic, tail = .14, size = 9, color = C.accent, hold = 0, fade = .08 } = seg;
  if (t < t0 || t > Math.max(t1 + Math.max(tail, hold) + fade, seg.trail ? seg.trailEnd + .25 : 0)) return;
  const P = s => path(ease(clamp((s - t0) / (t1 - t0))), s);
  const head = Math.min(t, t1);
  const N = 28, pts = [];
  for (let i = 0; i <= N; i++) {
    const s = head - tail * (1 - i / N);
    if (s < t0) continue;
    pts.push(P(s));
  }
  // after arrival the tail drains into the head, and the head fades unless held
  const after = t - t1;
  const drain = after > 0 ? clamp(after / tail) : 0;
  const keep = pts.slice(Math.floor(drain * pts.length));
  const headA = after > hold ? 1 - clamp((after - hold) / fade) : 1;
  x.save(); x.globalCompositeOperation = 'lighter'; x.lineCap = 'round';
  if (seg.trail && t < seg.trailEnd + .25) {
    // a thin line stays behind along the path the comet has travelled
    const ta = .55 * (1 - clamp((t - seg.trailEnd) / .25));
    x.strokeStyle = rgba(color, ta); x.lineWidth = 2.4; x.beginPath();
    for (let i = 0; i <= 60; i++) { const s = t0 + (head - t0) * i / 60, p = P(s); i ? x.lineTo(...p) : x.moveTo(...p); }
    x.stroke();
  }
  if (seg.trail && t > t1 + Math.max(tail, hold) + fade) { x.restore(); return; }
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 1; i < keep.length; i++) {
      const u = i / keep.length;
      x.strokeStyle = pass ? rgba(C.tint, .9 * u * headA) : rgba(color, .35 * u * headA);
      x.lineWidth = pass ? size * .55 * u : size * 2.2 * u;
      x.beginPath(); x.moveTo(...keep[i - 1]); x.lineTo(...keep[i]); x.stroke();
    }
  }
  if (headA > 0 && keep.length) {
    const [hx, hy] = P(head);
    const g = x.createRadialGradient(hx, hy, 0, hx, hy, size * 3.4);
    g.addColorStop(0, rgba(C.tint, headA)); g.addColorStop(.22, rgba(C.tint2, .95 * headA));
    g.addColorStop(.45, rgba(color, .55 * headA)); g.addColorStop(1, rgba(color, 0));
    x.fillStyle = g; x.beginPath(); x.arc(hx, hy, size * 3.4, 0, 7); x.fill();
  }
  x.restore();
}

export function drawBurst(x, b, t) {
  const age = t - b.t0, life = b.life || .6;
  if (age < 0 || age > life) return;
  const r = rng(b.seed || 7), n = b.n || 26;
  x.save(); x.globalCompositeOperation = b.blend || 'lighter'; x.lineCap = 'round';
  for (let i = 0; i < n; i++) {
    const a = (b.angle ?? 0) + (r() - .5) * (b.spread ?? Math.PI * 2);
    const sp = (b.speed || 900) * (.35 + .65 * r()), l = life * (.45 + .55 * r());
    if (age > l) { r(); continue; }
    const k = age / l, drag = (1 - Math.exp(-3.2 * age)) / 3.2;
    const px = b.x + Math.cos(a) * sp * drag, py = b.y + Math.sin(a) * sp * drag + (b.g ?? 260) * age * age;
    const v = sp * Math.exp(-3.2 * age), len = (b.len || .035) * v + 2;
    const al = (1 - k) * (b.alpha ?? 1);
    if (b.glyphs) {
      const ch = b.glyphs[Math.floor(r() * b.glyphs.length)];
      x.save(); x.translate(px, py); x.rotate((r() - .5) * 2 * k * 2);
      x.font = `600 ${b.gsize || 30}px JBM`; x.fillStyle = rgba(b.color || C.accent, al);
      x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(ch, 0, 0); x.restore();
    } else {
      x.strokeStyle = rgba(b.color || C.accent, al); x.lineWidth = (b.w || 3) * (1 - k * .5);
      x.beginPath(); x.moveTo(px, py); x.lineTo(px - Math.cos(a) * len, py - Math.sin(a) * len); x.stroke();
    }
  }
  x.restore();
}

export function drawSlash(x, s, t) {
  const { t0, x1, y1, x2, y2, dur = .12, hold = .22, fade = .2, w = 7, color = C.accent } = s;
  const age = t - t0;
  if (age < 0 || age > dur + hold + fade) return;
  const u = E.outCubic(clamp(age / dur));
  const tailU = E.inCubic(clamp((age - dur * .6) / (hold + fade)));
  const a = age > dur + hold ? 1 - (age - dur - hold) / fade : 1;
  const hx = lerp(x1, x2, u), hy = lerp(y1, y2, u), tx = lerp(x1, x2, tailU * u), ty = lerp(y1, y2, tailU * u);
  x.save(); x.globalCompositeOperation = 'lighter'; x.lineCap = 'round';
  [[w * 5, .18], [w * 2.2, .45], [w, .95], [w * .35, 1]].forEach(([lw, al], i) => {
    x.strokeStyle = i === 3 ? rgba(C.tint, al * a) : rgba(color, al * a);
    x.lineWidth = lw; x.beginPath(); x.moveTo(tx, ty); x.lineTo(hx, hy); x.stroke();
  });
  x.restore();
}

export function drawDots(x, d, t) {
  const age = t - d.t0;
  if (age < 0 || age > d.dur) return;
  const a = Math.sin(Math.PI * age / d.dur) * (d.alpha || .55);
  const sp = d.sp || 18;
  x.save();
  for (let gx = d.cx - d.rx; gx <= d.cx + d.rx; gx += sp) for (let gy = d.cy - d.ry; gy <= d.cy + d.ry; gy += sp) {
    const q = ((gx - d.cx) / d.rx) ** 2 + ((gy - d.cy) / d.ry) ** 2;
    if (q > 1) continue;
    // a ring that expands outward from the centre over the flash
    const ring = 1 - Math.abs(Math.sqrt(q) - age / d.dur * 1.1) * 2.2;
    const al = a * clamp(.25 + ring) * (1 - q * .6);
    if (al <= .01) continue;
    x.fillStyle = rgba(d.color || C.paper, al);
    x.fillRect(gx - 1.6, gy - 1.6, 3.2, 3.2);
  }
  x.restore();
}

// ---------- v2 effects ----------
// Speed lines on a spoke pattern. Outward: a burst that stretches and drains. Inward: lines that keep converging.
export function drawRays(x, o, t) {
  const { t0, dur = .5, cx = 960, cy = 540, n = 64, inward = false, color = C.paper, w = 2.4, r0 = 60, r1 = 1400, seed = 3, alpha = 1, rate = 2.2 } = o;
  const age = t - t0;
  if (age < 0 || age > dur) return;
  const r = rng(seed), k = age / dur;
  x.save(); x.globalCompositeOperation = o.blend || 'lighter'; x.lineCap = 'round';
  for (let i = 0; i < n; i++) {
    const a = r() * Math.PI * 2, sp = .55 + .9 * r(), off = r(), ww = w * (.45 + 1.1 * r()), jit = r();
    let h, tl, al;
    if (inward) {
      const q = (age * rate * sp + off) % 1, rad = u => r0 + (r1 - r0) * Math.pow(1 - clamp(u), 1.7);
      h = rad(q); tl = rad(q - .16 - .1 * jit); al = Math.sin(Math.PI * q) * Math.pow(k, .6) * Math.min(1, (1 - k) * 12);
    } else {
      const q = clamp(age / (dur * (.45 + .55 * sp)));
      h = lerp(r0, r1, E.outCubic(q)); tl = lerp(r0, r1, E.inCubic(q)); al = 1 - q;
    }
    if (al <= .01 || h <= tl - 1e-3 && !inward) continue;
    x.strokeStyle = rgba(color, clamp(al * alpha)); x.lineWidth = ww;
    x.beginPath(); x.moveTo(cx + Math.cos(a) * tl, cy + Math.sin(a) * tl); x.lineTo(cx + Math.cos(a) * h, cy + Math.sin(a) * h); x.stroke();
  }
  x.restore();
}
// Expanding shockwave ring.
export function drawRing(x, o, t) {
  const { t0, dur = .45, cx = 960, cy = 540, r0 = 20, r1 = 700, w = 10, color = C.accent, alpha = 1, sy = 1 } = o;
  const k = (t - t0) / dur;
  if (k < 0 || k > 1) return;
  x.save(); x.globalCompositeOperation = o.blend || 'lighter';
  x.strokeStyle = rgba(color, (1 - k) * alpha); x.lineWidth = w * (1 - k * .8);
  x.beginPath(); x.ellipse(cx, cy, lerp(r0, r1, E.outCubic(k)), lerp(r0, r1, E.outCubic(k)) * sy, 0, 0, 7); x.stroke();
  x.restore();
}
// Drifting points of light that wrap inside a region: keeps a quiet frame alive.
export function drawBokeh(x, o, t) {
  const { t0, t1, n = 40, x0 = 0, y0 = 0, x1 = W, y1 = H, color = C.accent, size = 3, vx = 0, vy = -30, seed = 5, alpha = .6 } = o;
  if (t < t0 || t > t1) return;
  const r = rng(seed), fade = Math.min(1, (t - t0) / .25, (t1 - t) / .25), age = t - t0;
  x.save(); x.globalCompositeOperation = 'lighter';
  for (let i = 0; i < n; i++) {
    const px0 = r(), py0 = r(), sp = .5 + r(), sz = size * (.4 + 1.3 * r() * r()), ph = r() * 7, wob = 6 + 18 * r();
    const px = x0 + (((px0 * (x1 - x0) + vx * sp * age + Math.sin(age * 1.3 + ph) * wob) % (x1 - x0)) + (x1 - x0)) % (x1 - x0);
    const py = y0 + (((py0 * (y1 - y0) + vy * sp * age + Math.cos(age * 1.1 + ph) * wob) % (y1 - y0)) + (y1 - y0)) % (y1 - y0);
    const a = fade * alpha * (.35 + .65 * Math.abs(Math.sin(age * (1.5 + sp) + ph)));
    x.fillStyle = rgba(color, a * .35); x.beginPath(); x.arc(px, py, sz * 2.6, 0, 7); x.fill();
    x.fillStyle = rgba(color, a); x.beginPath(); x.arc(px, py, sz, 0, 7); x.fill();
  }
  x.restore();
}
// Comic starburst that pops in, spins, and can melt into a circle (morph 0 -> 1).
export function drawStarburst(x, o, t) {
  const { t0, t1, cx = 960, cy = 540, r = 300, spikes = 16, jag = .42, spin = .5, color = C.accent, seed = 9, pop = .18, morph } = o;
  if (t < t0 || t > t1) return;
  const rr = rng(seed), age = t - t0;
  const s = E.outBack(clamp(age / pop), 2.4) * (1 - E.inCubic(clamp((t - (t1 - .12)) / .12)));
  const m = morph ? E.inOutCubic(clamp((t - morph[0]) / (morph[1] - morph[0]))) : 0;
  const N = spikes * 2, rot = age * spin + (o.rot || 0);
  x.save(); x.fillStyle = color; x.beginPath();
  for (let i = 0; i <= N; i++) {
    const j = i % N, out = j % 2 === 0, v = rr();
    const rad = r * s * lerp(out ? (1 + .18 * v) : (1 - jag * (.7 + .5 * v)), .82, m);
    const a = rot + j / N * Math.PI * 2 + (out ? 0 : (v - .5) * .12);
    const px = cx + Math.cos(a) * rad, py = cy + Math.sin(a) * rad * (o.sy || 1);
    i ? x.lineTo(px, py) : x.moveTo(px, py);
  }
  x.closePath(); x.fill(); x.restore();
}
