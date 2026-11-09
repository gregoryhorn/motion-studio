import { C, E, clamp, lerp, tw, rgba, el, vis, set, at, type, letters, extrude, tumble } from '../core.js';
import { fitTo, hitFx, meas, sheen } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Hero: a kicker line, then an extruded 3D title flies in, orbits, flips and shines ----------
// { kicker: 'WRITTEN BY', title: 'OPUS 5.5', sub: 'in Claude Code', chevron: '> ' }
export class Hero extends Scene {
  static N = 8;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    r.classList.add('persp');
    this.by = letters(r, o.kicker || '', {
      size: 120,
      wdth: 125,
      cls: 'abs'
    });
    this.byFit = fitTo(this.by.e.offsetWidth, 1500);
    this.w = el('div', r, 'abs p3d', {
      left: '960px',
      top: '590px'
    });
    this.ghost = [3, 2, 1].map(i => type(this.w, o.title, {
      size: 250,
      wdth: 108,
      stroke: 2,
      color: rgba(C.accent, .16 * (4 - i)),
      cls: 'abs'
    }));
    this.title = extrude(this.w, o.title, {
      size: 250,
      wdth: 108,
      layers: 44,
      depth: 96,
      face: C.paper
    });
    this.title.classList.add('abs');
    sheen(this.title.face, C.paper);
    [this.tw0, this.th0] = meas(this.title.face);
    this.tfit = fitTo(this.tw0, 1500);
    this.sub = el('div', r, 'abs mono chev');
    el('span', this.sub, 'chv').textContent = o.chevron ?? '> ';
    this.subT = el('span', this.sub);
    this.subC = el('span', this.sub, 'blk');
    this.tL = this.k(2);
    const cx = 960,
      cy = 590;
    f.comet({
      t0: this.k(.4),
      t1: this.tL,
      path: u => {
        const ang = -2.2 + u * Math.PI * 2.4,
          rr = 360 * (1 - u * u * u) + 4;
        return [cx + Math.cos(ang) * rr * 1.3, cy + Math.sin(ang) * rr * .62];
      },
      ease: E.inCubic,
      tail: .22,
      size: 10
    });
    f.slash({
      t0: this.tL + .03,
      x1: 480,
      y1: 840,
      x2: 1460,
      y2: 330,
      dur: .11,
      hold: .16,
      fade: .25,
      w: 6
    });
    hitFx(f, this.tL, {
      hit: 2,
      at: [960, 590]
    });
    f.bump(this.k(4), .03);
    f.bump(this.k(6), .03);
    f.bokeh({
      t0: this.t0,
      t1: this.t1,
      n: 46,
      color: C.accent,
      size: 2.4,
      vx: 24,
      vy: -30,
      alpha: .45,
      seed: 84
    });
    f.fast(this.t0, this.t0 + .5, 8);
    f.fast(this.k(4), this.k(4.5), 10);
    f.fast(this.k(6), this.k(6.6), 8);
    this.by.spans.forEach((_, i) => f.cue(this.t0 + .06 + i * .025, 'key', .2));
    f.cue(this.k(.4), 'whoosh', .6);
    f.cue(this.tL, 'impact_big', 1);
    f.cue(this.tL + .03, 'slash', .8);
    f.cue(this.k(3.3), 'sparkle', .35);
    f.cue(this.k(6.2), 'sparkle', .35);
    f.cue(this.k(4) + .05, 'whoosh_big', .55);
    f.slash({
      t0: this.k(5.5),
      x1: -100,
      y1: 700,
      x2: 2020,
      y2: 480,
      dur: .1,
      hold: .05,
      fade: .2,
      w: 4
    });
    f.cue(this.k(5.5), 'slash', .75);
    const sub = o.sub || '';
    for (let i = 0; i < Math.min(16, sub.length); i++) f.cue(this.k(5) + .4 * i / Math.min(16, sub.length), 'key', .16);
  }
  cam(t) {
    const u = clamp((t - this.t0) / (this.t1 - this.t0)),
      land = tw(t, this.t0, this.t0 + .6, E.outExpo);
    return {
      s: lerp(this.o.landZoom ?? 1.7, 1, land) * (1 + .08 * E.inOutCubic(u)),
      r: lerp(-1, 1, u) + 4 * (1 - land),
      x: lerp(-30, 30, u)
    };
  }
  update(t) {
    const d = t - this.t0,
      ent = tw(t, this.t0, this.t0 + .35, E.outExpo);
    tumble(this.by.spans, t, this.t0, {
      stagger: .025,
      dur: .3,
      rot: 60,
      dy: -120,
      seed: 25
    });
    set(this.by.e, 'transform', at(960 + 700 * (1 - ent) - d * 90, 270, `scale(${this.byFit})`));
    const u = tw(t, this.tL, this.tL + .45, E.outExpo),
      orb = E.inOutCubic(tw(t, this.tL, this.t1, E.lin)),
      flip = 360 * E.inOutCubic(tw(t, this.k(4), this.k(4) + .3, E.lin));
    vis(this.w, t >= this.tL - .01);
    const z = lerp(-2400, 0, u) + 60 * orb;
    set(this.w, 'transform', `translateZ(${z.toFixed(1)}px) rotateX(${(lerp(18, 9, u) - 6 * orb + flip).toFixed(2)}deg) rotateY(${(lerp(-140, -18, u) + 48 * orb).toFixed(2)}deg) scale(${this.tfit})`);
    set(this.w, 'opacity', tw(t, this.tL - .01, this.tL + .05).toFixed(3));
    set(this.title, 'transform', `translate(${-this.tw0 / 2}px,${-this.th0 / 2}px)`);
    const sw = Math.max(tw(t, this.k(3.3), this.k(3.3) + .5, E.inOutCubic) * (t < this.k(6.2) ? 1 : 0), tw(t, this.k(6.2), this.k(6.2) + .5, E.inOutCubic));
    set(this.title.face, 'backgroundPosition', `${lerp(100, 0, sw).toFixed(2)}% 0`);
    const gh = tw(t, this.k(6), this.k(6.6), E.outCubic);
    this.ghost.forEach((g, i) => {
      set(g, 'transform', `translate(${-this.tw0 / 2}px,${-this.th0 / 2}px) translateZ(${(-(3 - i) * 190 * gh - 100).toFixed(1)}px)`);
      set(g, 'opacity', gh.toFixed(3));
    });
    const txt = this.o.sub || '',
      n = Math.floor(tw(t, this.k(5), this.k(5) + .4, E.lin) * txt.length);
    this.subT.textContent = txt.slice(0, n);
    set(this.subC, 'opacity', t < this.k(5) ? '0' : n < txt.length || Math.floor(t * 3.4) % 2 === 0 ? '1' : '0');
    set(this.sub, 'transform', at(960, 885));
    set(this.sub, 'opacity', (txt ? tw(t, this.k(4.8), this.k(5)) : 0).toFixed(3));
  }
}
