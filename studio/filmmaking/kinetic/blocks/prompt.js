import { C, E, clamp, lerp, tw, rng, rgba, el, set, at, type, styleType } from '../core.js';
import { chamferPts, polyline, ptsAttr, punch, relPos, svg } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Prompt: a brief types itself (camera on the caret), keywords punch, then a push into Enter = the drop ----------
// { label: 'BRIEF.md', text: [['plain text '], ['keyword', 1], ...], unit: 'CHARS', doodles: true }
// The Enter key fills the frame with the accent on the block's last beat: start the next block on an accent ground.
export class Prompt extends Scene {
  static N = 19;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    r.classList.add('persp');
    this.g = el('div', r, 'abs full p3d');
    const X = 340,
      Y = 395,
      Wd = 1240,
      Hd = 330;
    this.X = X;
    this.Y = Y;
    this.panel = el('div', this.g, 'abs briefbox', {
      left: X + 'px',
      top: Y + 'px',
      width: Wd + 'px',
      height: Hd + 'px'
    });
    this.s = svg('svg', this.g, {
      class: 'full abs',
      viewBox: '0 0 1920 1080'
    });
    const P = chamferPts(X, Y, Wd, Hd, 16);
    this.outline = svg('polyline', this.s, {
      points: ptsAttr(P),
      fill: 'none',
      stroke: rgba(C.paper, .75),
      'stroke-width': 2.2
    });
    this.oPath = polyline(P);
    this.oLen = this.oPath.len;
    const hd = el('div', this.panel, 'bhead');
    const l = el('div', hd, 'mono');
    el('span', l, 'bdot');
    el('span', l).textContent = o.label || 'BRIEF.md';
    this.count = el('div', hd, 'mono');
    this.text = el('div', this.panel, 'btext mono');
    this.chars = [];
    this.kws = [];
    for (const [s, kw] of o.text) {
      const host = kw ? el('span', this.text, 'kw') : this.text;
      const i0 = this.chars.length;
      for (const ch of s) {
        const c = el('span', host, 'bc');
        c.textContent = ch;
        this.chars.push(c);
      }
      if (kw) this.kws.push({
        host,
        i0,
        i1: this.chars.length - 1
      });
    }
    this.caret = el('div', this.text, 'caret');
    this.cpos = this.chars.map(c => [...relPos(c, this.text), c.offsetWidth]);
    // typing fills beats 1.3 to 11.4 of the block, whatever the length of the brief
    const rr = rng(11),
      raw = this.chars.map(c => .55 + .9 * rr() + (/[,:.]/.test(c.textContent) ? 3 : 0)),
      tot = raw.reduce((a, b) => a + b, 0);
    const ta = this.k(1.3),
      tb = this.k(11.4);
    let tt = ta;
    this.tc = raw.map(v => {
      const x = tt;
      tt += v / tot * (tb - ta);
      return x;
    });
    this.kws.forEach(k => {
      k.t = this.tc[k.i1] + .04;
    });
    this.enter = el('div', this.panel, 'enter');
    this.enter.textContent = '↵';
    this.tE = this.k(13.5);
    this.tP = this.k(16);
    this.tPush = this.k(14.6);
    this.kt = this.kws.map(k => k.t);
    this.doodles = o.doodles !== false;
    if (this.doodles) {
      const kt = this.kt;
      this.aa = type(this.g, 'Aa', {
        size: 150,
        cls: 'abs'
      });
      if (kt.length > 1) f.comet({
        t0: kt[1],
        t1: this.k(18),
        path: (u, s) => {
          const a = (s - kt[1]) * 4.2 - 1.2;
          return [1695 + Math.cos(a) * 120, 300 + Math.sin(a) * 52];
        },
        ease: E.lin,
        tail: .3,
        size: 7
      });
      this.orb = svg('ellipse', this.s, {
        cx: 1695,
        cy: 300,
        rx: 120,
        ry: 52,
        fill: 'none',
        stroke: rgba(C.paper, .25),
        'stroke-width': 1.5,
        'stroke-dasharray': '4 7'
      });
      this.cube = Array.from({
        length: 12
      }, () => svg('line', this.s, {
        stroke: C.accent,
        'stroke-width': 2.4,
        'stroke-linecap': 'round'
      }));
      this.tun = [0, 1, 2, 3].map(() => svg('polyline', this.s, {
        fill: 'none',
        stroke: rgba(C.paper, .6),
        'stroke-width': 1.8
      }));
      this.cutA = el('div', this.g, 'abs cutsq');
      this.cutB = el('div', this.g, 'abs cutsq');
      this.cutA.style.clipPath = 'polygon(0 0,100% 0,0 100%)';
      this.cutB.style.clipPath = 'polygon(100% 0,100% 100%,0 100%)';
    }
    f.comet({
      t0: this.k(.1),
      t1: this.k(1.3),
      path: u => this.oPath(u),
      ease: E.inOutCubic,
      tail: .16,
      size: 9
    });
    this.kws.forEach((k, i) => {
      const [l2, tp, w] = this.cpos[k.i1];
      f.burst({
        t0: k.t,
        x: X + 40 + l2 + w,
        y: Y + 74 + tp + 20,
        n: 14,
        speed: 700,
        life: .35,
        seed: 140 + i,
        w: 2.4
      });
      f.bump(k.t, .02);
      f.cue(k.t + .02, 'pop', .35);
      f.cue(k.t + .02, 'tick', .3);
    });
    this.pulses = this.kws.slice(0, 6).map((kw, i) => {
      const t = this.k(12.5 + i * .5),
        [l2, tp, w] = this.cpos[kw.i1],
        [l0] = this.cpos[kw.i0],
        cx = X + 40 + (l0 + l2 + w) / 2,
        cy = Y + 74 + tp + 20;
      f.cue(t, 'tick', .45);
      f.cue(t, 'pop', .3);
      f.bump(t, .025);
      f.burst({
        t0: t,
        x: cx,
        y: cy,
        n: 18,
        speed: 900,
        life: .4,
        seed: 170 + i,
        w: 2.6
      });
      f.ring({
        t0: t,
        dur: .4,
        cx,
        cy,
        r0: 30,
        r1: 260,
        w: 6,
        sy: .45
      });
      return t;
    });
    f.ray({
      t0: this.tPush,
      dur: this.t1 - this.tPush,
      inward: true,
      color: C.accent,
      n: 110,
      r0: 70,
      r1: 1300,
      w: 2.2,
      rate: 1.9,
      screen: true,
      seed: 151
    });
    [15, 16, 17, 17.5, 18, 18.25, 18.5].forEach(k => f.ring({
      t0: this.k(k),
      dur: .32,
      r0: 1100,
      r1: 60,
      w: 6,
      color: C.paper,
      alpha: .5,
      screen: true
    }));
    f.ring({
      t0: this.tP,
      dur: .45,
      r0: 40,
      r1: 900,
      w: 14,
      screen: true
    });
    f.flash({
      t0: this.tP,
      dur: .18,
      rise: .01,
      color: C.accent,
      peak: .25
    });
    f.shake(this.tP, 12);
    f.fast(this.t0, this.k(1.5), 8);
    f.fast(this.k(11.6), this.k(12.6), 8);
    f.fast(this.tPush, this.t1 + .05, 10);
    f.smear(this.k(17.5), this.t1, 1.8);
    f.light(this.k(18.3), this.t1);
    f.cue(this.k(.1), 'draw', .6);
    this.tc.forEach((v, i) => {
      if (this.chars[i].textContent !== ' ' || i % 2) f.cue(v, 'key', .18);
    });
    f.cue(this.tE, 'pop', .5);
    f.cue(this.tP, 'click', 1);
    f.cue(this.t1 - 1.5, 'riser', .9, {
      end: this.t1
    });
  }
  nAt(t) {
    let lo = 0,
      hi = this.tc.length;
    while (lo < hi) {
      const m = lo + hi >> 1;
      if (this.tc[m] <= t) lo = m + 1;else hi = m;
    }
    return lo;
  }
  caretAt(t) {
    const n = this.nAt(t),
      i = Math.min(n, this.chars.length - 1),
      [l, tp, w] = this.cpos[i];
    return [this.X + 40 + l + (n >= this.chars.length ? w : 0), this.Y + 74 + tp + 20];
  }
  cam(t) {
    let ax = 0,
      ay = 0;
    for (let q = 0; q < 10; q++) {
      const p = this.caretAt(t - q * .05);
      ax += p[0];
      ay += p[1];
    }
    ax /= 10;
    ay /= 10;
    const fin = tw(t, this.k(1.3) - .35, this.k(1.3) + .45, E.inOutCubic) * (1 - tw(t, this.k(11.6), this.k(12.5), E.inOutCubic));
    let x = (ax - 960) * .78 * fin,
      y = (ay - 540 + 30) * .9 * fin,
      s = lerp(1, 1.6, fin) * (1 - .1 * Math.sin(Math.PI * tw(t, this.k(11.6), this.k(13.6), E.lin)));
    const p1 = tw(t, this.tPush, this.tP, E.inOutCubic),
      p2 = tw(t, this.tP + .05, this.t1, E.inExpo);
    const kx = this.X + 1240 - 28 - 35,
      ky = this.Y + 330 - 24 - 24;
    x = lerp(x, kx - 960, p1);
    y = lerp(y, ky - 540, p1);
    s *= lerp(1, 2.6, p1) * Math.exp(Math.log(16) * p2);
    const dr = tw(t, this.t0, this.tPush, E.lin);
    return {
      x,
      y,
      s: s * (1 + .03 * dr * (1 - p1)),
      r: lerp(-1.4, .9, dr) * (1 - p1)
    };
  }
  update(t) {
    const o = tw(t, this.k(.1), this.k(1.3), E.inOutCubic);
    this.outline.setAttribute('stroke-dasharray', `${(this.oLen * o).toFixed(1)} 99999`);
    set(this.panel, 'opacity', tw(t, this.k(1), this.k(1.6), E.outCubic).toFixed(3));
    const n = this.nAt(t);
    this.chars.forEach((c, i) => set(c, 'visibility', i < n ? 'visible' : 'hidden'));
    this.count.textContent = `${String(n).padStart(3, '0')} / 2000 ${this.o.unit || 'CHARS'}`;
    this.kws.forEach((k, i) => {
      const h = tw(t, k.t, k.t + .13, E.outCubic),
        pt = this.pulses[i],
        pu = pt != null && t >= pt ? punch(t, pt, 10) : 0;
      set(k.host, 'backgroundSize', `${(h * 100).toFixed(1)}% 100%`);
      set(k.host, 'color', h > .5 ? C.ink : C.paper);
      set(k.host, 'display', 'inline-block');
      set(k.host, 'transform', `scale(${(1 + .32 * pu + .1 * (t >= k.t ? punch(t, k.t, 12) : 0)).toFixed(4)})`);
    });
    const typing = n > 0 && n < this.chars.length,
      ref = this.chars[Math.min(n, this.chars.length - 1)];
    const [rx, ry] = relPos(ref, this.text);
    set(this.caret, 'transform', `translate(${n < this.chars.length ? rx : rx + ref.offsetWidth}px,${ry + 4}px)`);
    set(this.caret, 'opacity', t < this.k(1.2) || t > this.tP ? '0' : typing || Math.floor(t * 3.4) % 2 === 0 ? '1' : '0');
    const e1 = tw(t, this.tE, this.tE + .25, E.outBack),
      pr = tw(t, this.tP, this.tP + .08, E.outCubic),
      rel = tw(t, this.tP + .08, this.tP + .25, E.outCubic);
    set(this.enter, 'transform', `scale(${(e1 * (1 - pr * .14 + rel * .14) * (1 + .06 * Math.sin(t * 18) * (t > this.tPush && t < this.tP ? 1 : 0))).toFixed(3)})`);
    set(this.enter, 'background', t >= this.tP ? C.accent : 'transparent');
    set(this.enter, 'color', t >= this.tP ? C.ink : C.paper);
    set(this.enter, 'borderColor', t >= this.tPush ? C.accent : rgba(C.paper, .5));
    set(this.enter, 'boxShadow', t > this.tPush ? `0 0 ${(20 + 30 * tw(t, this.tPush, this.tP)).toFixed(0)}px ${rgba(C.accent, .8)}` : 'none');
    if (this.doodles) {
      const kt = this.kt,
        dm = i => kt[i] == null ? 0 : tw(t, kt[i], kt[i] + .3, E.outBack);
      const d0 = dm(0),
        ph = (t - (kt[0] || 0)) * 3.1;
      styleType(this.aa, {
        size: 150,
        wght: Math.round(500 + 400 * Math.sin(ph)),
        wdth: Math.round(93 + 32 * Math.sin(ph * .73 + 1))
      });
      set(this.aa, 'transform', at(225, 560, `scale(${d0.toFixed(3)})`));
      set(this.aa, 'opacity', clamp(d0).toFixed(3));
      this.orb.setAttribute('opacity', clamp(dm(1)).toFixed(3));
      const d2 = dm(2),
        ca = (t - (kt[2] || 0)) * 1.6,
        cb2 = (t - (kt[2] || 0)) * 1.05 + .5;
      const V = [-1, 1].flatMap(x => [-1, 1].flatMap(y => [-1, 1].map(z => [x, y, z]))).map(([x, y, z]) => {
        let X = x * Math.cos(ca) - z * Math.sin(ca),
          Z = x * Math.sin(ca) + z * Math.cos(ca),
          Y = y * Math.cos(cb2) - Z * Math.sin(cb2);
        Z = y * Math.sin(cb2) + Z * Math.cos(cb2);
        const s = 62 * d2 * 4 / (4 + Z);
        return [1700 + X * s, 660 + Y * s];
      });
      [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]].forEach(([a, b], i) => {
        const l = this.cube[i];
        l.setAttribute('x1', V[a][0].toFixed(1));
        l.setAttribute('y1', V[a][1].toFixed(1));
        l.setAttribute('x2', V[b][0].toFixed(1));
        l.setAttribute('y2', V[b][1].toFixed(1));
        l.setAttribute('opacity', clamp(d2).toFixed(3));
      });
      const d3 = clamp(dm(3));
      this.tun.forEach((p, i) => {
        const q = ((t - (kt[3] || 0)) * .9 + i / 4) % 1,
          s = .2 + q * 1.1;
        p.setAttribute('points', ptsAttr(chamferPts(235 - 110 * s, 835 - 62 * s, 220 * s, 124 * s, 10 * s)));
        p.setAttribute('opacity', (d3 * Math.sin(Math.PI * q)).toFixed(3));
      });
      const d4 = clamp(dm(4)),
        cq = (t - (kt[4] || 0)) * 1.4 % 1,
        sep = E.outCubic(clamp((cq - .3) / .35)) * (1 - clamp((cq - .8) / .2));
      set(this.cutA, 'transform', at(228 - 16 * sep, 292 - 16 * sep, `rotate(45deg) scale(${d4.toFixed(3)})`));
      set(this.cutB, 'transform', at(228 + 16 * sep, 292 + 16 * sep, `rotate(45deg) scale(${d4.toFixed(3)})`));
    }
    const dr = tw(t, this.t0, this.k(14.4), E.inOutCubic);
    set(this.g, 'transform', `rotateY(${lerp(-7, 0, dr).toFixed(3)}deg) rotateX(${lerp(8, 0, dr).toFixed(3)}deg)`);
  }
}
