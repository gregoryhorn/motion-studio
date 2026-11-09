import { B, E, clamp, lerp, el } from '../core.js';

// ---------- base ----------
export class Scene {
  static N = 0;
  constructor(f, k0, k1, o = {}) {
    this.f = f;
    this.k0 = k0;
    this.k1 = k1;
    this.o = o;
    this.t0 = B(k0);
    this.t1 = B(k1);
    this.sc = this.constructor.N ? (k1 - k0) / this.constructor.N : 1;
    this.pre = o.pre || 0;
    this.post = o.post || 0;
    this.dir = o.dir || 1;
    this.root = el('div', f.scenesEl, 'scene');
    this.build();
    // transitions owned by the spec: whipIn: [dx, dy, dur, roll] lands this block, whipOut leaves it
    if (o.whipIn) f.whip(this.t0, ...o.whipIn);
    if (o.whipOut) f.whip(this.t1, ...o.whipOut);
  }
  // a beat offset inside the scene, scaled to its span, as seconds
  k(rel) {
    return B(this.k0 + rel * this.sc);
  }
  build() {}
  update() {}
  // default camera: a slow push with a little roll, so no shot is ever locked off
  cam(t) {
    const u = clamp((t - this.t0) / (this.t1 - this.t0));
    return {
      s: 1 + .06 * E.inOutCubic(u),
      r: this.dir * lerp(-.7, .7, u)
    };
  }
}
