import { C, E, clamp, lerp, tw, rgba, el, vis, set, at, type, styleType } from '../core.js';
import { cc, fitTo, fmt, hitFx, punch } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Stretch: a word on the variable width axis, ghost rows, a live ruler and the CSS that drives it ----------
// { word: 'ELASTIC.', grounds: [[0, 'accent'], [4, 'paper'], [5, 'accent']], code: true }
export class Stretch extends Scene {
  static N = 8;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    this.word = o.word || 'ELASTIC.';
    this.g = el('div', r, 'abs full');
    this.echo = [-2, -1, 1, 2].map(k => ({
      k,
      e: type(this.g, this.word, {
        size: 240,
        color: rgba(C.ink, Math.abs(k) === 1 ? .34 : .17),
        wdth: 62,
        stroke: 3,
        cls: 'abs'
      })
    }));
    this.w = type(this.g, this.word, {
      size: 240,
      color: C.ink,
      wdth: 62,
      cls: 'abs'
    });
    styleType(this.w, {
      size: 240,
      wdth: 125
    });
    this.fit = fitTo(this.w.offsetWidth * 1.08, 1780);
    this.rule = el('div', this.g, 'abs rule');
    this.px = el('div', this.g, 'abs mono pxl');
    this.code = el('div', this.g, 'abs mono codel');
    vis(this.code, o.code !== false);
    const gr = o.grounds || [[0, 'accent'], [4, 'paper'], [5, 'accent']];
    gr.forEach(([k, g], i) => {
      const kb = i < gr.length - 1 ? gr[i + 1][0] : 8;
      f.ground(this.k(k), this.k(kb), cc(g));
      if (i) {
        f.cut(this.k(k));
        f.bump(this.k(k), .05);
        f.shake(this.k(k), 10);
        f.cue(this.k(k), 'hit', .85);
      }
    });
    hitFx(f, this.t0, {
      hit: 2,
      ground: 'accent',
      at: [960, 500]
    });
    [1, 2, 3, 6, 7].forEach(k => f.bump(this.k(k), .03));
    f.fast(this.t0, this.k(.8), 10);
    f.fast(this.k(1), this.k(2), 8);
    f.fast(this.k(2.4), this.k(3.2), 8);
    f.fast(this.k(4), this.k(5.4), 10);
    f.fast(this.k(6), this.k(7), 8);
    f.cue(this.t0, 'drop', 1);
    f.cue(this.k(1), 'stretch', .8);
    f.cue(this.k(2.5), 'squeeze', .5);
    f.cue(this.k(4), 'squeeze', .7);
    f.cue(this.k(5), 'stretch', .8);
    f.cue(this.k(6), 'tick', .4);
  }
  wdthAt(t) {
    let v = 62;
    if (t >= this.k(1)) v = 62 + 63 * E.outElastic(clamp((t - this.k(1)) / (this.k(3) - this.k(1))));
    if (t >= this.k(4)) v = lerp(125, 66, E.inOutExpo(clamp((t - this.k(4)) / (this.k(4.8) - this.k(4)))));
    if (t >= this.k(5)) v = 66 + 59 * E.outElastic(clamp((t - this.k(5)) / (this.k(7) - this.k(5))));
    return v;
  }
  wghtAt(t) {
    return 900 - 680 * Math.sin(Math.PI * clamp((t - this.k(2.5)) / (this.k(3.5) - this.k(2.5))));
  }
  update(t) {
    const v = this.wdthAt(t),
      wd = Math.min(125, v),
      over = Math.max(0, v - 125) / 125;
    const ls = .07 * tw(t, this.k(6), this.k(7), E.outExpo) - .07 * tw(t, this.k(7), this.k(7.6), E.inCubic);
    styleType(this.w, {
      size: 240,
      color: C.ink,
      wdth: wd.toFixed(2),
      wght: Math.round(this.wghtAt(t)),
      ls: ls.toFixed(4)
    });
    const s = tw(t, this.t0, this.t0 + .2, E.outExpo),
      a = t - this.t0,
      sc = lerp(1.5, 1, s) * (1 + .025 * a) * this.fit;
    set(this.w, 'transform', at(960 + 26 * Math.sin(a * 2.4), 500 + 12 * Math.sin(a * 3.1), `scale(${(sc * (1 + over)).toFixed(4)},${sc.toFixed(4)}) rotate(${(-2.5 * (t >= this.k(5) ? punch(t, this.k(5), 6) : 0)).toFixed(2)}deg)`));
    this.echo.forEach(({
      k,
      e
    }) => {
      const vk = Math.min(125, this.wdthAt(t - Math.abs(k) * .08)),
        dir = k > 0 ? 1 : -1;
      styleType(e, {
        size: 240,
        color: rgba(C.ink, Math.abs(k) === 1 ? .34 : .17),
        wdth: vk.toFixed(2),
        stroke: 3
      });
      set(e, 'transform', at(960 + dir * a * 330, 500 + k * 235 * this.fit, `scale(${sc.toFixed(4)})`));
      set(e, 'opacity', tw(t, this.t0 + .04 * Math.abs(k), this.t0 + .14 + .04 * Math.abs(k)).toFixed(3));
    });
    const width = this.w.offsetWidth * (1 + over) * sc;
    set(this.rule, 'width', width.toFixed(1) + 'px');
    set(this.rule, 'transform', at(960, 690));
    this.px.textContent = `${fmt(Math.round(width))} PX`;
    set(this.px, 'transform', at(960, 722));
    this.code.textContent = `font-variation-settings: "wdth" ${Math.round(wd)}, "wght" ${Math.round(this.wghtAt(t))};`;
    set(this.code, 'transform', at(960, 815));
  }
}
