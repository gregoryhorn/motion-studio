import { C, E, clamp, lerp, tw, el, vis, set, at, type } from '../core.js';
import { arcLen, cc, fillVars, fitTo, qb } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Chain: A to B to C as one long world; the camera rides the comet from node to node, then pulls back ----------
// { nodes: [['BRIEF', 'brief.md'], ['CODE', 'film.js'], ['FILM.', '4K · 60 FPS', 'accent']] }
export class Chain extends Scene {
  static N = 12;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    this.g = el('div', r, 'abs full');
    this.nodes = o.nodes.slice(0, 3).map(([s, tag, c], i) => {
      const col = cc(c) || (i === o.nodes.length - 1 ? C.accent : C.paper);
      const w = type(this.g, s, {
        size: 300,
        wdth: 110,
        color: col,
        glow: col === C.accent ? 26 : 0,
        cls: 'abs'
      });
      const tg = el('div', this.g, 'abs mono ctag big');
      tg.textContent = fillVars(f, tag || '');
      const fit = fitTo(w.offsetWidth, 1500);
      return {
        w,
        tg,
        x: 960 + i * 2000,
        y: 520,
        ww: w.offsetWidth * fit,
        fit
      };
    });
    const [a, b, c] = this.nodes;
    const s1 = arcLen(u => qb([-200, 160], [300, 140], [a.x - a.ww / 2 - 40, a.y], u));
    const s2 = arcLen(u => qb([a.x + a.ww / 2 + 40, a.y], [1960, 120], [b.x - b.ww / 2 - 40, b.y], u));
    const s3 = arcLen(u => qb([b.x + b.ww / 2 + 40, b.y], [3960, 940], [c.x - c.ww / 2 - 40, c.y], u));
    this.s2 = s2;
    this.s3 = s3;
    this.tn = [this.k(.6), this.k(4), this.k(7)];
    this.c2 = [this.k(2.6), this.tn[1]];
    this.c3 = [this.k(5.6), this.tn[2]];
    f.comet({
      t0: this.t0 - .05,
      t1: this.tn[0],
      path: s1,
      ease: E.inCubic,
      tail: .18,
      size: 10
    });
    f.comet({
      t0: this.c2[0],
      t1: this.c2[1],
      path: s2,
      ease: E.inOutCubic,
      tail: .2,
      size: 10,
      trail: true,
      trailEnd: this.t1
    });
    f.comet({
      t0: this.c3[0],
      t1: this.c3[1],
      path: s3,
      ease: E.inOutCubic,
      tail: .2,
      size: 10,
      trail: true,
      trailEnd: this.t1
    });
    f.burst({
      t0: this.tn[2],
      x: c.x,
      y: c.y,
      n: 40,
      speed: 1500,
      life: .55,
      seed: 121
    });
    this.nodes.forEach((nd, i) => f.ring({
      t0: this.tn[i],
      dur: i === 2 ? .5 : .45,
      cx: nd.x,
      cy: nd.y,
      r0: 40,
      r1: i === 2 ? 900 : 700,
      w: i === 2 ? 16 : 12
    }));
    f.flash({
      t0: this.tn[2],
      dur: .25,
      rise: .015,
      color: C.accent,
      peak: .2
    });
    f.bokeh({
      t0: this.t0,
      t1: this.t1,
      n: 120,
      x0: -600,
      x1: 5600,
      y0: -300,
      y1: 1400,
      color: C.accent,
      size: 2.4,
      vx: 30,
      vy: -20,
      alpha: .45,
      seed: 122
    });
    this.tn.forEach((k, i) => {
      f.cue(k, i === 2 ? 'impact_big' : 'impact', i === 2 ? 1 : .75);
      f.fast(k - .03, k + .25, 10);
      f.shake(k, i === 2 ? 18 : 10);
      f.bump(k, i === 2 ? .06 : .035);
    });
    f.smear(this.c2[0] + .1, this.c2[1] - .2, 2);
    f.smear(this.c3[0] + .1, this.c3[1] - .2, 2);
    f.fast(this.c2[0], this.c2[1], 10);
    f.fast(this.c3[0], this.c3[1], 10);
    f.fast(this.k(8), this.k(11.5), 6);
    f.cue(this.t0, 'whoosh', .5);
    f.cue(this.c2[0] + .2, 'whoosh_big', .6);
    f.cue(this.c3[0] + .2, 'whoosh_big', .7);
  }
  cam(t) {
    const follow = (seg, path) => path(E.inOutCubic(clamp((t - seg[0]) / (seg[1] - seg[0]))));
    const st = tw(t, this.t0, this.c2[0] + .1, E.inOutCubic);
    let x = lerp(-90, 60, st),
      y = 0,
      s = 1 + .14 * st,
      r = lerp(-1.5, .5, st);
    if (t >= this.c2[0]) {
      const [hx, hy] = follow(this.c2, this.s2),
        m = tw(t, this.c2[0], this.c2[0] + .25, E.inOutCubic);
      s = lerp(s, 1, m);
      r = lerp(r, 0, m);
      x = lerp(x, hx - 960 + (2000 - (hx - 960)) * tw(t, this.c2[1] - .2, this.c2[1], E.outCubic), m);
      y = (hy - 520) * .5 * m * (1 - tw(t, this.c2[1] - .2, this.c2[1]));
    }
    if (t >= this.c2[1]) {
      const q = tw(t, this.c2[1], this.c3[0] + .25, E.inOutCubic);
      x = 2000 + lerp(-50, 70, q);
      y = 0;
      s = 1 + .12 * q;
      r = lerp(0, 1, q);
    }
    if (t >= this.c3[0]) {
      const [hx, hy] = follow(this.c3, this.s3),
        m = tw(t, this.c3[0], this.c3[0] + .25, E.inOutCubic);
      s = lerp(s, 1, m);
      r = lerp(r, 0, m);
      x = lerp(x, hx - 960 + (4000 - (hx - 960)) * tw(t, this.c3[1] - .2, this.c3[1], E.outCubic), m);
      y = (hy - 520) * .5 * m * (1 - tw(t, this.c3[1] - .2, this.c3[1]));
    }
    if (t >= this.c3[1]) {
      const p = tw(t, this.k(8), this.k(11.4), E.inOutCubic);
      x = lerp(4000, 2000, p);
      y = lerp(0, -20, p);
      s = lerp(1.04, .34, p);
      r = lerp(0, -2.5, p);
    }
    return {
      x,
      y,
      s,
      r
    };
  }
  update(t) {
    this.nodes.forEach((n, i) => {
      const k = this.tn[i],
        u = tw(t, k, k + .22, E.outExpo);
      vis(n.w, t >= k - .01);
      set(n.w, 'transform', at(n.x + 500 * (1 - u) * (i === 2 ? 1 : 0), n.y, (i === 2 ? `scaleX(${lerp(1.45, 1, u).toFixed(3)})` : `scale(${lerp(1.35, 1, u).toFixed(3)})`) + ` scale(${n.fit})`));
      set(n.w, 'opacity', clamp(u * 2).toFixed(3));
      if (i < 2) set(n.w, 'clipPath', `inset(-30% ${((1 - tw(t, k - .02, k + .2, E.outCubic)) * 100).toFixed(1)}% -30% 0)`);
      const g = tw(t, k + .25, k + .5, E.outCubic);
      set(n.tg, 'transform', at(n.x, n.y + 200 + 12 * (1 - g)));
      set(n.tg, 'opacity', g.toFixed(3));
    });
  }
}
