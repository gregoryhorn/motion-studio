import { B, C, E, clamp, lerp, tw, rgba, el, vis, set, at, type } from '../core.js';
import { cb, cc, fitTo, isLight, meas, polyline, ptsAttr, svg, zoomThrough } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Graph: a comet draws a graph, it folds, a giant number lands, the camera flies through it ----------
// { number: '0', label: 'KEYFRAMES', sub: 'DRAGGED BY HAND', ground: 'paper', ticks: i => i * 4 + 'f', portal: true }
export class Graph extends Scene {
  static N = 6;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    this.s = svg('svg', r, {
      class: 'full abs',
      viewBox: '0 0 1920 1080',
      style: 'overflow:visible'
    });
    const X0 = 260,
      X1 = 1660,
      Y0 = 210,
      Y1 = 760,
      sp = o.from || [960, 629];
    this.pR = polyline([sp, [sp[0], Y1], [X1, Y1]]);
    this.pL = polyline([[sp[0], Y1], [X0, Y1], [X0, Y0]]);
    this.dropLen = Y1 - sp[1];
    this.axR = svg('polyline', this.s, {
      points: ptsAttr([[sp[0], Y1], [X1, Y1]]),
      fill: 'none',
      stroke: rgba(C.paper, .55),
      'stroke-width': 2
    });
    this.axL = svg('polyline', this.s, {
      points: ptsAttr([[sp[0], Y1], [X0, Y1], [X0, Y0]]),
      fill: 'none',
      stroke: rgba(C.paper, .55),
      'stroke-width': 2
    });
    this.lenL = this.pL.len;
    this.ticks = svg('g', this.s);
    const tl = o.ticks || (i => i * 4 + 'f');
    for (let i = 0; i <= 14; i++) {
      svg('line', this.ticks, {
        x1: X0 + i * 100,
        x2: X0 + i * 100,
        y1: Y1,
        y2: i % 2 ? Y1 + 10 : Y1 + 18,
        stroke: rgba(C.paper, .4),
        'stroke-width': 1.5
      });
      if (i % 2 === 0) {
        const tx = svg('text', this.ticks, {
          x: X0 + i * 100,
          y: Y1 + 46,
          class: 'svgmono',
          'text-anchor': 'middle'
        });
        tx.textContent = tl(i);
      }
    }
    const curve = u => cb([X0, Y1], [720, 770], [780, 190], [1110, 235], u),
      curve2 = u => cb([1110, 235], [1380, 272], [1460, 290], [X1, 280], u);
    const pts = [];
    for (let i = 0; i <= 120; i++) pts.push(curve(i / 120));
    for (let i = 1; i <= 60; i++) pts.push(curve2(i / 60));
    this.cpath = polyline(pts);
    this.cv = svg('path', this.s, {
      d: 'M' + pts.map(p => p.map(v => v.toFixed(1)).join(' ')).join(' L'),
      fill: 'none',
      stroke: C.accent,
      'stroke-width': 4,
      'stroke-linecap': 'round',
      class: 'glowline'
    });
    this.cvLen = this.cpath.len;
    this.kq = [0, .3, .56, .8, 1];
    this.kd = this.kq.map(q => {
      const [x, y] = this.cpath(q);
      return svg('rect', this.s, {
        x: -11,
        y: -11,
        width: 22,
        height: 22,
        fill: C.bg,
        stroke: C.accent,
        'stroke-width': 3,
        transform: `translate(${x} ${y}) rotate(45)`
      });
    });
    this.tA = this.k(0);
    this.tA1 = this.k(1);
    this.tC0 = this.k(1);
    this.tC1 = this.k(2.6);
    this.tPop = this.k(2.9);
    this.tF = [this.k(3.35), this.k(3.9)];
    this.tZ = this.k(4);
    this.tX = this.k(5.2);
    f.comet({
      t0: this.tA,
      t1: this.tA1,
      path: u => this.pR(u),
      ease: E.inOutCubic,
      tail: .14,
      size: 8
    });
    f.comet({
      t0: this.tA + .12,
      t1: this.tA1,
      path: u => this.pL(u),
      ease: E.inOutCubic,
      tail: .14,
      size: 8
    });
    f.comet({
      t0: this.tC0,
      t1: this.tC1,
      path: u => this.cpath(u),
      ease: E.inOutCubic,
      tail: .16,
      size: 10
    });
    this.kq.forEach((q, i) => {
      const [x, y] = this.cpath(q);
      f.burst({
        t0: this.tPop + i * .065,
        x,
        y,
        n: 12,
        speed: 620,
        life: .38,
        seed: 60 + i,
        w: 2.6
      });
      f.ring({
        t0: this.tPop + i * .065,
        dur: .35,
        cx: x,
        cy: y,
        r0: 8,
        r1: 70,
        w: 4
      });
    });
    const gr = o.ground ?? 'paper',
      light = isLight(gr),
      ink = light ? C.ink : C.paper;
    this.g = el('div', r, 'abs full');
    this.zEcho = [0, 1, 2].map(() => type(this.g, o.number ?? '0', {
      size: 780,
      stroke: 3,
      color: rgba(ink, .4),
      cls: 'abs'
    }));
    this.portal = el('div', this.g, 'abs', {
      background: C.bg,
      borderRadius: '50%'
    });
    vis(this.portal, o.portal !== false);
    this.zero = type(this.g, o.number ?? '0', {
      size: 780,
      color: ink,
      cls: 'abs'
    });
    this.kw = type(this.g, o.label || '', {
      size: 128,
      wdth: 100,
      color: ink,
      cls: 'abs'
    });
    this.kb = el('div', this.g, 'abs mono sub' + (light ? ' lt' : ''));
    this.kb.textContent = o.sub || '';
    [this.zW, this.zH] = meas(this.zero);
    this.zfit = fitTo(this.zW + 40 + this.kw.offsetWidth + 60, 1500);
    this.zX = 500;
    this.zY = 540;
    this.oPt = [this.zX, this.zY - this.zH / 2 * this.zfit + .485 * 780 * this.zfit];
    if (gr) f.ground(this.tZ, this.t1, cc(gr));
    f.ray({
      t0: this.tZ,
      dur: .5,
      color: ink,
      alpha: light ? .5 : .8,
      n: 70,
      r0: 280,
      r1: 1500,
      w: 3,
      screen: true,
      seed: 71,
      ...(light ? {
        blend: 'source-over'
      } : {})
    });
    f.shake(this.tZ, 18);
    f.bump(this.tZ, .06);
    f.bump(this.k(5), .03);
    f.fast(this.tZ - .03, this.tZ + .25, 12);
    f.fast(this.tF[0], this.tZ, 8);
    if (o.portal !== false) {
      f.smear(this.tX + .05, this.t1, 2.2);
      f.fast(this.tX, this.t1, 12);
      f.cue(this.tX, 'whoosh_big', .8);
    }
    f.cue(this.tA, 'draw', .55);
    f.cue(this.tC0, 'draw', .5);
    this.kq.forEach((q, i) => f.cue(this.tPop + i * .065, 'tick', .5));
    f.cue(this.tF[0], 'suck', .45, {
      end: this.tZ
    });
    f.cue(this.tZ, 'impact', 1);
  }
  head(t) {
    return this.cpath(E.inOutCubic(clamp((t - this.tC0) / (this.tC1 - this.tC0))));
  }
  cam(t) {
    const u = clamp((t - this.t0) / (this.t1 - this.t0));
    let s = 1 + .05 * u,
      x = 0,
      y = 0,
      r = lerp(.6, -.6, u);
    const fin = tw(t, this.tC0 - .25, this.tC0 + .2, E.inOutCubic) * (1 - tw(t, this.tC1, this.tC1 + .4, E.inOutCubic));
    if (fin > 0) {
      const [hx, hy] = this.head(t - .06);
      x = (hx - 960) * .8 * fin;
      y = (hy - 540) * .8 * fin;
      s *= lerp(1, 1.5, fin);
    }
    if (this.o.portal !== false) {
      const z = zoomThrough(t, this.tX, this.t1, this.oPt, {
        s,
        r
      });
      if (z) return z;
    }
    return {
      x,
      y,
      s,
      r
    };
  }
  update(t) {
    const a = tw(t, this.tA, this.tA1, E.inOutCubic),
      aL = tw(t, this.tA + .12, this.tA1, E.inOutCubic);
    this.axR.setAttribute('stroke-dasharray', `${Math.max(0, this.pR.len * a - this.dropLen).toFixed(1)} 9999`);
    this.axL.setAttribute('stroke-dasharray', `${(this.lenL * aL).toFixed(1)} 9999`);
    set(this.ticks, 'opacity', tw(t, this.k(.7), this.k(.7) + .2).toFixed(3));
    const c = tw(t, this.tC0, this.tC1, E.inOutCubic);
    this.cv.setAttribute('stroke-dasharray', `${(this.cvLen * c).toFixed(1)} 9999`);
    const fold = tw(t, this.tF[0], this.tF[1], E.inCubic);
    set(this.s, 'transformOrigin', '960px 760px');
    set(this.s, 'transform', `scaleY(${(1 - fold).toFixed(4)}) scaleX(${(1 - fold * .3).toFixed(4)})`);
    vis(this.s, t < this.tZ);
    this.kd.forEach((d, i) => {
      const show = c >= this.kq[i] - .001 ? tw(t, this.tC0 + (this.tC1 - this.tC0) * this.kq[i] * .9, this.tC0 + (this.tC1 - this.tC0) * this.kq[i] * .9 + .12, E.outBack) : 0;
      const pop = tw(t, this.tPop + i * .065, this.tPop + i * .065 + .16, E.outCubic),
        [x, y] = this.cpath(this.kq[i]);
      d.setAttribute('transform', `translate(${x} ${y}) rotate(45) scale(${(show * (1 + pop * 1.2)).toFixed(3)})`);
      d.setAttribute('opacity', (1 - pop).toFixed(3));
    });
    vis(this.g, t >= this.tZ - .02);
    if (t < this.tZ - .02) return;
    const z = tw(t, this.tZ, this.tZ + .22, E.outExpo),
      zf = this.zfit;
    set(this.zero, 'transform', at(this.zX, this.zY, `scale(${(lerp(2.8, 1, z) * zf).toFixed(3)})`));
    set(this.zero, 'opacity', tw(t, this.tZ - .02, this.tZ + .04).toFixed(3));
    set(this.portal, 'width', this.zW * .32 + 'px');
    set(this.portal, 'height', 780 * .5 + 'px');
    set(this.portal, 'transform', at(this.oPt[0], this.oPt[1], `scale(${(lerp(2.8, 1, z) * zf).toFixed(3)})`));
    this.zEcho.forEach((e, i) => {
      const p0 = this.tZ + i * B(.5),
        q = clamp((t - p0) / .5);
      set(e, 'transform', at(this.zX, this.zY, `scale(${(lerp(1, 1.7, E.outCubic(q)) * zf).toFixed(3)})`));
      set(e, 'opacity', (t >= p0 ? (1 - q) * .9 : 0).toFixed(3));
    });
    const k1 = tw(t, this.tZ + .05, this.tZ + .3, E.outExpo),
      k2 = tw(t, this.tZ + .12, this.tZ + .4, E.outExpo),
      lx = this.zX + this.zW * zf / 2 + 60;
    set(this.kw, 'transform', `translate(${(lx + 320 * (1 - k1)).toFixed(1)}px, 452px) scale(${zf})`);
    set(this.kw, 'transformOrigin', '0 0');
    set(this.kw, 'opacity', k1.toFixed(3));
    set(this.kb, 'transform', `translate(${(lx + 8 + 220 * (1 - k2)).toFixed(1)}px, 610px)`);
    set(this.kb, 'opacity', k2.toFixed(3));
  }
}
