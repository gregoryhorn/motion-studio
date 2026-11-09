import { DUR, E, clamp, lerp, tw, el, set } from '../core.js';
import { Scene } from './scene.js';

// ---------- Rewind: the film so far plays backwards inside a tilting playback window ----------
// { from: seconds to rewind from (default: this block's start) }
export class Rewind extends Scene {
  static noNest = true;
  static N = 8;
  build() {
    const f = this.f,
      r = this.root;
    r.classList.add('persp');
    this.w3 = el('div', r, 'abs full p3d');
    this.win = el('div', this.w3, 'abs pbwin', {
      left: '335px',
      top: '205px',
      width: '1250px',
      height: '703px'
    });
    this.inner = el('div', this.win, 'abs', {
      width: '1920px',
      height: '1080px',
      transformOrigin: '0 0',
      transform: `scale(${1250 / 1920})`
    });
    this.nested = new f.constructor(this.inner, {
      nested: true,
      dsf: 1,
      src: f.src,
      logo: f.logo,
      spec: f.spec
    });
    this.lines = [0, 1, 2].map(() => el('div', this.win, 'abs track'));
    this.hd = el('div', this.w3, 'abs mono pbhead');
    el('span', this.hd).textContent = this.o.label || 'PLAYBACK';
    this.spd = el('span', this.hd, 'pbspd');
    this.bar = el('div', this.w3, 'abs pbbar');
    this.bph = el('div', this.bar, 'pbph');
    this.tc = el('div', this.w3, 'abs mono pbtc');
    this.from = this.o.from ?? this.t0 - .05;
    this.endT = this.k(7.2);
    this.rate = (this.from - .45) / Math.pow(this.endT - this.t0, 1.1);
    f.fast(this.t0, this.t1, 8);
    f.fast(this.endT, this.t1, 12);
    f.cue(this.t0, 'rewind', .8, {
      dur: this.k(7.5) - this.t0
    });
    f.cue(this.endT, 'whoosh_big', .7);
    [2, 4, 6].forEach(k => f.bump(this.k(k), .025));
  }
  tn(t) {
    return clamp(this.from - Math.pow(Math.max(0, t - this.t0), 1.1) * this.rate, .45, this.from);
  }
  cam(t) {
    const u = tw(t, this.t0, this.t1, E.lin);
    return {
      s: 1 + .06 * u,
      r: lerp(1, -1, u)
    };
  }
  update(t) {
    const e = tw(t, this.t0, this.t0 + .25, E.outExpo),
      z = tw(t, this.endT, this.t1, E.inExpo),
      u = tw(t, this.t0, this.endT, E.inOutCubic);
    const tn = this.tn(t);
    this.nested.render(tn);
    set(this.w3, 'transform', `rotateY(${(lerp(-14, 10, u) * (1 - z)).toFixed(3)}deg) rotateX(${(lerp(8, 3, u) * (1 - z)).toFixed(3)}deg) translateZ(${lerp(-500, 0, e).toFixed(1)}px)`);
    set(this.win, 'transform', `scale(${lerp(1, 1.56, z).toFixed(4)})`);
    set(this.win, 'transformOrigin', '625px 351px');
    set(this.win, 'opacity', (clamp(e * 3) * (1 - clamp((z - .7) / .3))).toFixed(3));
    const ui = e * (1 - z);
    [this.hd, this.bar, this.tc].forEach(n => set(n, 'opacity', ui.toFixed(3)));
    set(this.hd, 'transform', 'translate(335px, 160px)');
    set(this.bar, 'transform', 'translate(335px, 932px)');
    this.spd.textContent = `◀◀  ${Math.round(18 * 1.1 * Math.pow(Math.max(.05, t - this.t0), .1))}×`;
    set(this.bph, 'width', (tn / DUR * 100).toFixed(2) + '%');
    const s = Math.floor(tn),
      ff = Math.floor(tn % 1 * 60);
    this.tc.textContent = `00:${String(s).padStart(2, '0')}:${String(ff).padStart(2, '0')}  /  00:${Math.floor(DUR)}:${String(Math.floor(DUR % 1 * 60)).padStart(2, '0')}`;
    set(this.tc, 'transform', `translate(${1585 - this.tc.offsetWidth}px, 952px)`);
    this.lines.forEach((l, i) => {
      set(l, 'transform', `translateY(${((t * (420 + i * 210) + i * 211) % 760 - 30).toFixed(1)}px)`);
      set(l, 'opacity', (.35 + .25 * Math.sin(t * 13 + i)).toFixed(3));
    });
  }
}
