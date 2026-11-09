import { C, E, lerp, tw, el, vis, set, at, type } from '../core.js';
import { Scene } from './scene.js';

// ---------- Logo: a line, a slash, the logo builds, the end line; then it holds with a slow push and a sheen ----------
// { mark: ['id', ...] (SVG ids that drop in one by one), word: ['id', ...] (SVG ids wiped in after), tagline, small, width: 840 }
// Without mark/word ids the whole logo wipes in. The logo comes from spec.logo (inline SVG text).
export class Logo extends Scene {
  static N = 11;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    this.line = el('div', r, 'abs lline');
    const svgEl = (() => {
      const d = document.createElement('div');
      d.innerHTML = f.logo;
      return d.querySelector('svg');
    })();
    const vb = (svgEl?.getAttribute('viewBox') || '0 0 840 207').split(/[\s,]+/).map(Number),
      lw = o.width || 840,
      lh = lw * vb[3] / vb[2];
    this.lw0 = lw;
    this.lh0 = lh;
    this.lw = el('div', r, 'abs', {
      left: '960px',
      top: (o.y || 505) + 'px'
    });
    this.d = el('div', this.lw, 'abs logo');
    this.d.innerHTML = f.logo;
    this.wm = el('div', this.lw, 'abs logo');
    this.wm.innerHTML = f.logo;
    this.sh = el('div', this.lw, 'abs logo sheen');
    this.sh.innerHTML = f.logo;
    const mark = o.mark || [],
      word = o.word || [];
    this.dia = mark.map(id => this.d.querySelector('#' + id)).filter(Boolean);
    if (mark.length) {
      word.forEach(id => {
        const p = this.d.querySelector('#' + id);
        if (p) p.style.display = 'none';
      });
      mark.forEach(id => {
        const p = this.wm.querySelector('#' + id);
        if (p) p.style.display = 'none';
      });
    } else vis(this.d, false);
    for (const host of [this.d, this.wm, this.sh]) {
      const s = host.querySelector('svg');
      if (s) {
        s.setAttribute('width', lw);
        s.setAttribute('height', lh);
        s.style.overflow = 'visible';
      }
    }
    if (!svgEl) {
      // no logo file: a type wordmark wipes in instead
      [this.wm, this.sh].forEach((h, i) => {
        h.innerHTML = '';
        const t = type(h, o.wordmark || f.spec.title || '', {
          size: 150,
          wdth: 104,
          color: i ? '#FFFFFF' : C.paper
        });
        t.style.whiteSpace = 'nowrap';
      });
      this.lw0 = this.wm.firstChild.offsetWidth;
      this.lh0 = this.wm.firstChild.offsetHeight;
    }
    this.sub = el('div', r, 'abs endline');
    this.sub.textContent = o.tagline || '';
    this.made = el('div', r, 'abs mono made');
    this.made.textContent = o.small || '';
    this.tS = this.k(1);
    f.slash({
      t0: this.tS,
      x1: 420,
      y1: 545,
      x2: 1500,
      y2: 535,
      dur: .1,
      hold: .1,
      fade: .3,
      w: 5
    });
    f.burst({
      t0: this.tS + .04,
      x: 960,
      y: 540,
      n: 30,
      speed: 1100,
      life: .55,
      seed: 141
    });
    f.flash({
      t0: this.tS,
      dur: .3,
      rise: .02,
      color: '#FFFFFF',
      peak: .12
    });
    f.bokeh({
      t0: this.k(1.5),
      t1: this.t1 + 1,
      n: 70,
      color: C.paper,
      size: 2.4,
      vy: -26,
      alpha: .3,
      seed: 142
    });
    f.fast(this.tS - .02, this.tS + .6, 10);
    f.cue(this.tS, 'logo_hit', 1.1);
    this.dia.forEach((_, i) => f.cue(this.tS + .1 + i * .075, 'tick', .3));
    f.cue(this.k(5.6), 'sparkle', .3);
  }
  cam(t) {
    return {
      s: 1 + .09 * E.outCubic(tw(t, this.tS, this.t1, E.lin))
    };
  }
  update(t) {
    const l = tw(t, this.tS - .02, this.tS + .16, E.outExpo),
      lo = tw(t, this.tS + .14, this.tS + .45, E.inCubic);
    vis(this.line, t >= this.tS - .02);
    set(this.line, 'width', (lerp(4, 1100, l) * (1 - lo * .6)).toFixed(1) + 'px');
    set(this.line, 'transform', at(960, 540));
    set(this.line, 'opacity', (1 - lo).toFixed(3));
    set(this.lw, 'transform', `translate(${-this.lw0 / 2}px,${-this.lh0 / 2}px)`);
    this.dia.forEach((p, i) => {
      const u = tw(t, this.tS + .08 + i * .075, this.tS + .08 + i * .075 + .4, E.outBack);
      set(p, 'transform', `translateY(${(-70 * (1 - u)).toFixed(1)}px)`);
      set(p, 'visibility', u > 0 ? 'visible' : 'hidden');
      p.style.transformBox = 'fill-box';
    });
    const w = tw(t, this.tS + (this.dia.length ? .3 : .05), this.tS + .95, E.inOutCubic);
    set(this.wm, 'clipPath', `inset(-20% ${((1 - w) * 100).toFixed(2)}% -20% 0)`);
    set(this.wm, 'transform', `translateX(${(26 * (1 - w)).toFixed(1)}px)`);
    const sw = tw(t, this.k(5.6), this.k(5.6) + .9, E.inOutCubic);
    vis(this.sh, sw > 0 && sw < 1);
    set(this.sh, 'webkitMaskPosition', `${lerp(130, -30, sw).toFixed(2)}% 0`);
    const s1 = tw(t, this.k(3.5), this.k(3.5) + .4, E.outCubic),
      s2 = tw(t, this.k(4.6), this.k(4.6) + .4, E.outCubic),
      ly = (this.o.y || 505) + this.lh0 / 2;
    set(this.sub, 'transform', at(960, ly + 60 + 14 * (1 - s1)));
    set(this.sub, 'opacity', s1.toFixed(3));
    set(this.made, 'transform', at(960, ly + 118 + 10 * (1 - s2)));
    set(this.made, 'opacity', (s2 * .8).toFixed(3));
  }
}
