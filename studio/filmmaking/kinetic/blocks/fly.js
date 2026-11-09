import { C, E, clamp, lerp, tw, rng, rgba, el, vis, set, extrude } from '../core.js';
import { cc, chamferPts, fitTo, ptsAttr, svg } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Fly: the camera flies through extruded words in depth, then orbits the last one ----------
// { words: [['CAMERA', 'paper'], ['FLIES', 'accent'], ['THROUGH', 'paper'], ['THE TYPE.', 'accent']] }
export class Fly extends Scene {
  static N = 11;
  constructor(f, k0, k1, o) {
    super(f, k0, k1, o);
    this.noGrid = true;
  }
  camZ(t) {
    return lerp(this.cz0, this.cz1, this.ease(tw(t, this.t0, this.k(8), E.lin)));
  }
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    r.classList.add('persp', 'fly');
    this.world = el('div', r, 'abs p3d', {
      left: '960px',
      top: '540px'
    });
    const ws = o.words,
      n = ws.length,
      gap = 6100 / Math.max(1, n - 1),
      off = [[0, 0], [160, -30], [-120, 30], [0, 0], [140, 20], [-140, -20]];
    this.items = ws.map(([s, c], i) => {
      const col = cc(c) || C.paper,
        isA = col === C.accent,
        z = -i * gap,
        [dx, dy] = i === n - 1 ? [0, 0] : off[i % off.length];
      const w = el('div', this.world, 'abs p3d');
      const x = extrude(w, s, {
        size: 250,
        wdth: 104,
        layers: 36,
        depth: 90,
        face: col,
        side0: isA ? C.side0 : C.sideP,
        side1: C.side1,
        glow: isA ? 20 : 0
      });
      x.classList.add('abs');
      const fw = x.face.offsetWidth,
        fh = x.face.offsetHeight,
        fit = fitTo(fw, 1500);
      x.style.transform = `translate(${-fw / 2}px,${-fh / 2}px)`;
      w.fit = fit;
      const pw = el('div', this.world, 'abs p3d');
      const ps = svg('svg', pw, {
        width: 1560,
        height: 760,
        viewBox: '0 0 1560 760',
        class: 'abs',
        style: 'left:-780px;top:-380px;overflow:visible'
      });
      svg('polyline', ps, {
        points: ptsAttr(chamferPts(6, 6, 1548, 748, 40)),
        fill: 'none',
        stroke: rgba(C.accent, .25),
        'stroke-width': 12
      });
      svg('polyline', ps, {
        points: ptsAttr(chamferPts(6, 6, 1548, 748, 40)),
        fill: 'none',
        stroke: C.accent,
        'stroke-width': 3.5
      });
      svg('polyline', ps, {
        points: ptsAttr(chamferPts(330, 220, 900, 320, 24)),
        fill: 'none',
        stroke: rgba(C.paper, .18),
        'stroke-width': 2
      });
      return {
        w,
        pw,
        z,
        dx,
        dy,
        rot: [-3, 4, -5, 2, -4, 3][i % 6]
      };
    });
    this.cz0 = -700;
    this.cz1 = (n - 1) * gap - 140;
    this.ease = u => .4 * u + .6 * E.inOutCubic(u);
    this.passes = this.items.slice(0, -1).map(it => {
      let k = 0;
      while (k < 8 && this.camZ(this.k(k)) + it.z < 950) k += .05;
      return k;
    });
    const rr = rng(77);
    this.dust = Array.from({
      length: 460
    }, () => {
      const a = rr() * Math.PI * 2,
        rad = 380 + rr() * 1300;
      return [Math.cos(a) * rad, Math.sin(a) * rad * .7, -(n - 1) * gap - 1300 + rr() * ((n - 1) * gap + 2100), .6 + rr()];
    });
    f.paint((x, t) => {
      if (t < this.t0 || t >= this.t1) return;
      const c = this.view(t),
        c2 = this.view(t - .03);
      x.save();
      x.globalCompositeOperation = 'lighter';
      x.lineCap = 'round';
      for (const [dx, dy, dz, sz] of this.dust) {
        const p = this.project(dx, dy, dz, c),
          q = this.project(dx, dy, dz, c2);
        if (!p || !q) continue;
        const al = clamp(p[2] * .55) * (1 - clamp((t - this.k(10.6)) / .3));
        x.strokeStyle = rgba(sz > 1.3 ? C.accent : C.paper, al);
        x.lineWidth = Math.min(8, 2 * sz * p[2]);
        x.beginPath();
        x.moveTo(q[0], q[1]);
        x.lineTo(p[0], p[1]);
        x.stroke();
      }
      x.restore();
    }, true);
    f.fast(this.t0, this.k(8.5), 10);
    f.fast(this.k(8.5), this.t1, 8);
    f.burst({
      t0: this.k(8),
      x: 960,
      y: 560,
      n: 30,
      speed: 1200,
      life: .5,
      seed: 91
    });
    f.shake(this.k(8), 14);
    f.bump(this.k(8), .04);
    this.passes.forEach((k, i) => {
      f.cue(this.k(k) - .14, 'whoosh_big', .65 + i * .1);
      f.slash({
        t0: this.k(k) - .02,
        x1: -100,
        y1: 620 - i * 60,
        x2: 2020,
        y2: 470 + i * 60,
        dur: .09,
        hold: .06,
        fade: .18,
        w: 4
      });
    });
    f.cue(this.k(8), 'impact', .9);
    f.cue(this.k(10.4), 'whoosh', .5);
  }
  view(t) {
    const u = tw(t, this.t0, this.k(8), E.lin),
      e = this.ease(u),
      orb = E.inOutCubic(tw(t, this.k(8), this.k(10.8), E.lin));
    return {
      cz: this.camZ(t),
      roll: lerp(2, -5, e) + 8 * Math.sin(u * Math.PI * 2.2) * (1 - orb),
      yaw: lerp(7, -3, e) + 50 * orb
    };
  }
  project(x, y, z, c) {
    const rel = z + c.cz,
      d = 1100 - rel;
    if (d < 60) return null;
    const k = 1100 / d,
      a = c.roll * Math.PI / 180,
      ca = Math.cos(a),
      sa = Math.sin(a);
    return [960 + (x * ca - y * sa) * k, 540 + (x * sa + y * ca) * k, k];
  }
  update(t) {
    const c = this.view(t),
      land = t - this.k(8),
      zp = -140 * clamp(land / .2);
    set(this.world, 'transform', `rotateZ(${c.roll.toFixed(3)}deg) translateZ(${zp.toFixed(1)}px) rotateY(${c.yaw.toFixed(3)}deg) translateZ(${(c.cz - zp).toFixed(1)}px)`);
    for (const it of this.items) {
      const rel = it.z + c.cz,
        near = 1 - clamp((rel - 650) / 380),
        far = clamp(1 - (-rel - 900) / 1300);
      vis(it.w, rel < 1080);
      vis(it.pw, rel - 260 < 1080);
      set(it.w, 'transform', `translate3d(${it.dx}px,${it.dy}px,${it.z}px) scale(${it.w.fit})`);
      set(it.w, 'opacity', Math.min(near, far).toFixed(3));
      const pn = 1 - clamp((rel - 260 - 600) / 420);
      set(it.pw, 'transform', `translate3d(${it.dx * .6}px,${it.dy * .6}px,${it.z - 260}px) rotateZ(${it.rot}deg)`);
      set(it.pw, 'opacity', Math.min(pn, .15 + .85 * clamp(1 - (-(rel - 260) - 900) / 1600)).toFixed(3));
    }
    set(this.root, 'opacity', (1 - tw(t, this.k(10.7), this.t1, E.inExpo)).toFixed(3));
  }
  cam(t) {
    return {
      s: 1 + .5 * tw(t, this.k(10.5), this.t1, E.inExpo)
    };
  }
}
