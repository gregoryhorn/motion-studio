import { B, C, E, lerp, tw, rng, rgba, el, vis, set, at, letters, tumble } from '../core.js';
import { cc, chamferPts, fitTo, polyline, ptsAttr, punch, svg } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Picture: an image (key art, a product, a screenshot) cut in with a slash, pushed, with words slammed over it ----------
// { src: 'art/key.png', words: [[beat, 'TEXT', 'paper'|'accent'], ...], reveal: 'slash' | 'zoom', focus: [x, y] (0-1, where to push in), x, y (word position),
//   tint: 0.35 (darken for type), frame: true (a chamfered frame grows round it), weather: 'rain' | 'snow' | 'dust' | null,
//   cutIns: [[beat, scale, [fx, fy], cue]] (hard punch-in cuts to a detail of the same image, on the beat) }
// A still image parks the frame: the block keeps it moving with a fast push and pan, a slight 3D tilt,
// a punch-in on every word, and a weather layer drawn over it.
// Scenario MCP is the natural source: generate the image to the brief, upscale it, drop it in the film folder.
export class Picture extends Scene {
  static N = 8;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    r.classList.add('persp');
    this.g = el('div', r, 'abs full');
    this.img = el('div', this.g, 'abs pic', {
      backgroundImage: `url("${o.src}")`,
      backgroundPosition: `${(o.focus || [.5, .5])[0] * 100}% ${(o.focus || [.5, .5])[1] * 100}%`
    });
    this.shade = el('div', this.g, 'abs full', {
      background: `linear-gradient(180deg, ${rgba(C.bg, .1)}, ${rgba(C.bg, o.tint ?? .35)} 70%, ${rgba(C.bg, (o.tint ?? .35) + .25)})`
    });
    this.halves = null;
    this.s = svg('svg', this.g, {
      class: 'full abs',
      viewBox: '0 0 1920 1080',
      style: 'overflow:visible'
    });
    this.frame = svg('polyline', this.s, {
      points: ptsAttr(chamferPts(70, 70, 1780, 940, 36)),
      fill: 'none',
      stroke: C.accent,
      'stroke-width': 4
    });
    this.fLen = polyline(chamferPts(70, 70, 1780, 940, 36)).len;
    vis(this.frame, o.frame !== false);
    this.words = (o.words || []).map(([k, text, c], i) => {
      const L = letters(this.g, text, {
        size: o.size || 260,
        wdth: 112,
        color: cc(c) || C.paper,
        glow: cc(c) === C.accent ? 22 : 0,
        cls: 'abs'
      });
      L.e.style.textShadow = `0 8px 40px ${rgba(C.bg, .6)}`;
      const t = B(this.k0 + k * this.sc),
        fit = fitTo(L.e.offsetWidth, o.x ? 2 * Math.min(o.x, 1920 - o.x) - 120 : 1600);
      f.shake(t, 10);
      f.bump(t, .035);
      f.cue(t, 'hit', .85);
      f.fast(t, t + .2, 8);
      return {
        L,
        t,
        fit,
        i
      };
    });
    this.tR = this.t0;
    if ((o.reveal || 'slash') === 'slash') {
      f.slash({
        t0: this.t0 - .02,
        x1: 1800,
        y1: -60,
        x2: 120,
        y2: 1140,
        dur: .12,
        hold: .08,
        fade: .2,
        w: 8
      });
      f.cue(this.t0 - .02, 'slash', 1);
      f.flash({
        t0: this.t0,
        dur: .2,
        rise: .01,
        color: '#FFFFFF',
        peak: .35
      });
    } else {
      f.cue(this.t0, 'whoosh_big', .7);
    }
    f.cue(this.t0, 'impact', .9);
    f.shake(this.t0, 14);
    f.bump(this.t0, .05);
    f.fast(this.t0, this.t0 + .45, 10);
    this.words.forEach(w => f.fast(w.t, w.t + .2, 8));
    this.cutIns = (o.cutIns || []).map(([k, sc, fp, cue]) => {
      const t = B(this.k0 + k * this.sc);
      f.cut(t);
      f.shake(t, 12);
      f.bump(t, .04);
      f.fast(t, t + .2, 8);
      f.cue(t, cue || 'hit', .9);
      f.flash({
        t0: t,
        dur: .1,
        rise: .005,
        color: '#FFFFFF',
        peak: .25
      });
      return {
        t,
        sc,
        fp
      };
    });
    const wx = o.weather === undefined ? 'dust' : o.weather;
    if (wx) {
      const rr = rng(193),
        P = Array.from({
          length: wx === 'rain' ? 420 : 160
        }, () => [rr(), rr(), .4 + rr(), rr()]);
      f.paint((x, t) => {
        if (t < this.t0 || t >= this.t1) return;
        const a = Math.min(1, (t - this.t0) / .15, (this.t1 - t) / .1),
          age = t - this.t0;
        x.save();
        x.globalCompositeOperation = 'lighter';
        x.lineCap = 'round';
        for (const [px, py, sp, ph] of P) {
          if (wx === 'rain') {
            // fast diagonal streaks, longer and brighter when near the lens
            const vy = 2600 * sp,
              y = (py * 1300 + age * vy) % 1300 - 110,
              xx = (px * 2100 + age * vy * .18) % 2100 - 90,
              L = 40 + 70 * sp;
            x.strokeStyle = rgba(C.paper, (.14 + .26 * sp) * a);
            x.lineWidth = .9 + 1.8 * sp * sp;
            x.beginPath();
            x.moveTo(xx, y);
            x.lineTo(xx - L * .18, y - L);
            x.stroke();
          } else {
            const vy = wx === 'snow' ? 90 * sp : -35 * sp,
              y = ((py * 1180 + age * vy) % 1180 + 1180) % 1180 - 50,
              xx = px * 1920 + Math.sin(age * (1 + sp) + ph * 7) * 30;
            x.fillStyle = rgba(wx === 'snow' ? '#FFFFFF' : C.paper, (wx === 'snow' ? .5 : .28) * sp * a);
            x.beginPath();
            x.arc(xx, y, (wx === 'snow' ? 2.6 : 1.8) * sp + .6, 0, 7);
            x.fill();
          }
        }
        x.restore();
      }, true);
    }
  }
  cam(t) {
    const u = tw(t, this.t0, this.t1, E.lin);
    return {
      s: 1 + .1 * E.inOutCubic(u),
      r: lerp(-1, 1, u),
      x: lerp(-25, 25, u)
    };
  }
  update(t) {
    const o = this.o,
      u = tw(t, this.t0, this.t1, E.lin),
      rv = tw(t, this.t0, this.t0 + .45, E.outExpo);
    const z = (o.reveal || 'slash') === 'zoom' ? lerp(2.4, 1, rv) : lerp(1.18, 1, rv);
    let pk = 0;
    this.words.forEach(w => {
      if (t >= w.t) pk = punch(t, w.t, 8);
    });
    const f0 = o.focus || [.5, .5],
      pan = (u - .5) * 70;
    let ci = null;
    this.cutIns.forEach(c => {
      if (t >= c.t) ci = c;
    });
    set(this.img, 'transformOrigin', ci ? `${(ci.fp[0] * 100).toFixed(1)}% ${(ci.fp[1] * 100).toFixed(1)}%` : '50% 50%');
    const cz = ci ? ci.sc * (1 + .14 * (t - ci.t)) : 1;
    set(this.img, 'transform', `scale(${cz.toFixed(4)}) perspective(1600px) rotateY(${lerp(-3, 3, u).toFixed(3)}deg) translate(${(-pan - (f0[0] - .5) * 60 * u).toFixed(1)}px, ${(-(f0[1] - .5) * 40 * u).toFixed(1)}px) scale(${(z * (1.06 + .24 * E.inOutCubic(u)) * (1 + .07 * pk)).toFixed(4)})`);
    // slash reveal: the image opens along the diagonal the slash drew
    if ((o.reveal || 'slash') === 'slash') {
      const p = (1 - rv) * 50;
      set(this.g, 'clipPath', `polygon(${50 + p}% ${-p}%, 100% 0, 100% 100%, ${50 - p}% ${100 + p}%, 0 100%, 0 0)`);
    } else set(this.g, 'opacity', rv.toFixed(3));
    this.frame.setAttribute('stroke-dasharray', `${(this.fLen * tw(t, this.t0 + .2, this.t0 + .9, E.inOutCubic)).toFixed(1)} 99999`);
    this.words.forEach(({
      L,
      t: tw0,
      fit,
      i
    }) => {
      const nx = this.words[i + 1]?.t ?? this.t1,
        on = t >= tw0 - .01 && t < nx;
      vis(L.e, on);
      if (!on) return;
      const sl = tw(t, tw0, tw0 + .16, E.outExpo);
      set(L.e, 'transform', at(o.x || 960, o.y || 600, `scale(${(lerp(1.4, 1, sl) * (1 + .05 * (t - tw0)) * fit).toFixed(4)})`));
      tumble(L.spans, t, tw0, {
        stagger: .02,
        dur: .22,
        rot: 30,
        dy: -90,
        seed: 200 + i,
        from: .6
      });
    });
  }
}
