import { B, C, E, clamp, lerp, tw, rng, mixc, rgba, el, vis, set, at, type } from '../core.js';
import { fitTo, punch, svg } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Notes: notes typed in a panel, the preview answers each one (camera moves between them) ----------
// { preview: 'ELASTIC.', notes: [['hotter orange', 'recolor'], ['cut the intro in half', 'trim'], ['more punch', 'punch']],
//   segments: [['INTRO', 220], ['BRIEF', 190], ...], tag: 'PREVIEW  ·  00:18', panel: 'NOTES', file: 'film.js' }
export class Notes extends Scene {
  static N = 16;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    r.classList.add('persp');
    this.g = el('div', r, 'abs full p3d');
    this.pv = el('div', this.g, 'abs pvwin', {
      left: '130px',
      top: '250px',
      width: '1000px',
      height: '562px'
    });
    this.pvIn = el('div', this.pv, 'abs full');
    this.burstSvg = svg('svg', this.pvIn, {
      class: 'abs',
      width: 1000,
      height: 562,
      viewBox: '0 0 1000 562'
    });
    this.burstPoly = svg('polygon', this.burstSvg, {
      fill: C.paper
    });
    this.pvW = type(this.pvIn, o.preview || 'ELASTIC.', {
      size: 150,
      color: C.ink,
      wdth: 118,
      cls: 'abs'
    });
    this.pvFit = fitTo(this.pvW.offsetWidth, 900);
    this.scan = el('div', this.pv, 'abs scanl');
    el('div', this.pv, 'abs mono pvtag').textContent = o.tag || 'PREVIEW';
    this.strip = el('div', this.g, 'abs strip', {
      left: '130px',
      top: '836px',
      width: '1000px'
    });
    const segs = o.segments || [['INTRO', 220], ['BRIEF', 190], ['STRETCH', 120], ['FLY', 150], ['CUTS', 90], ['NOTES', 230]];
    let x = 0;
    this.segs = segs.map(([nm, w], i) => {
      const s = el('div', this.strip, 'seg' + (i === 0 ? ' hot' : ''), {
        left: x + 'px',
        width: w - 6 + 'px'
      });
      s.textContent = nm;
      s.w0 = w;
      x += w;
      return s;
    });
    this.ph = el('div', this.strip, 'sph');
    this.np = el('div', this.g, 'abs npanel', {
      left: '1190px',
      top: '250px',
      width: '600px',
      height: '650px'
    });
    const hd = el('div', this.np, 'nhead');
    el('div', hd, 'mono').textContent = o.panel || 'NOTES';
    el('div', hd, 'mono dimt').textContent = o.file || '';
    this.list = el('div', this.np, 'nlist');
    this.inp = el('div', this.np, 'ninput mono');
    this.inTxt = el('span', this.inp);
    this.inCar = el('span', this.inp, 'ncaret');
    this.send = el('div', this.np, 'nsend');
    this.send.textContent = '↑';
    this.bgw = type(r, ' ', {
      size: 300,
      wdth: 115,
      stroke: 3.5,
      color: rgba(C.paper, .24),
      cls: 'abs'
    });
    const slots = [[.7, 2.4], [4.5, 7.2], [9.6, 11.2]];
    this.notes = (o.notes || []).slice(0, 3).map(([s, fx], i) => {
      const bub = el('div', this.list, 'bub');
      el('div', bub, 'btxt').textContent = s;
      const rep = el('div', bub, 'mono rep');
      rep.textContent = o.done || '✓ re-rendered';
      return {
        s,
        fx,
        ta: this.k(slots[i][0]),
        tb: this.k(slots[i][1]),
        bub,
        rep
      };
    });
    const shotFor = fx => fx === 'trim' ? 'S' : fx === 'punch' ? 'F' : 'P';
    this.SH = {
      W: [960, 575, 1],
      I: [1420, 720, 1.42],
      P: [630, 531, 1.42],
      S: [630, 858, 1.75],
      F: [630, 531, 1.87]
    };
    this.shots = [[this.t0, 'W'], [this.k(.5), 'I']];
    this.notes.forEach((n, i) => {
      this.shots.push([n.tb + .1, shotFor(n.fx)]);
      if (i < this.notes.length - 1) this.shots.push([this.notes[i + 1].ta - B(.2), 'I']);
    });
    this.shots.push([this.k(15.4), 'W']);
    this.shots.slice(1).forEach(([k]) => {
      f.smear(k, k + .24, 2);
      f.fast(k, k + .26, 10);
    });
    this.notes.forEach(n => {
      const L = n.s.length;
      for (let i = 0; i < L; i++) f.cue(n.ta + (n.tb - .15 - n.ta) * (i + .5) / L, 'key', .2);
      f.cue(n.tb, 'send', 1.4);
      f.cue(n.tb, 'pop', .4);
      f.cue(n.tb + .5, 'tick', .4);
    });
    this.shots.slice(1, -1).forEach(([k]) => f.cue(k - .1, 'whoosh', .4));
    const tr = this.notes.find(n => n.fx === 'trim');
    if (tr) {
      f.slash({
        t0: tr.tb + .3,
        x1: 240,
        y1: 805,
        x2: 240,
        y2: 910,
        dur: .08,
        hold: .1,
        fade: .2,
        w: 5
      });
      f.cue(tr.tb + .3, 'slash', .85);
    }
    const pn = this.notes.find(n => n.fx === 'punch');
    this.punches = pn ? [0, 1, 2, 3].map(i => pn.tb + B(.8 + i)).filter(x => x < this.k(15.4)) : [];
    this.punches.forEach((k, i) => {
      f.shake(k, 12);
      f.bump(k, .04);
      f.cue(k, i === 3 ? 'impact_big' : 'impact', i === 3 ? .9 : .7);
      f.fast(k, k + .2, 8);
    });
    if (this.punches[2]) f.invert(this.punches[2] + 1 / 60, 2 / 60);
    f.fast(this.t0, this.k(.6), 8);
    f.fast(this.k(15.4), this.t1, 8);
    f.cue(this.t0, 'whoosh', .5);
  }
  cam(t) {
    let i = 0;
    while (i < this.shots.length - 1 && t >= this.shots[i + 1][0]) i++;
    const cur = this.SH[this.shots[i][1]],
      prev = i ? this.SH[this.shots[i - 1][1]] : cur;
    const st = t - this.shots[i][0],
      u = E.inOutCubic(clamp(st / .24)),
      drift = 1 + .06 * st;
    return {
      x: lerp(prev[0], cur[0], u) - 960 + 16 * Math.sin(t * 2.1) + 45 * st,
      y: lerp(prev[1], cur[1], u) - 540 + 10 * Math.sin(t * 1.7 + 1),
      s: lerp(prev[2], cur[2], u) * drift,
      r: .8 * Math.sin(t * 1.3)
    };
  }
  update(t) {
    const e = tw(t, this.t0, this.t0 + .45, E.outExpo),
      out = tw(t, this.k(15.4), this.t1, E.inExpo);
    set(this.g, 'transform', `translateZ(${lerp(-700, 0, e) - 500 * out}px) rotateY(${lerp(24, 0, e).toFixed(2)}deg) rotateX(${(50 * out).toFixed(2)}deg)`);
    set(this.g, 'opacity', (clamp(e * 2) * (1 - out)).toFixed(3));
    const rc = this.notes.find(n => n.fx === 'recolor'),
      tr = this.notes.find(n => n.fx === 'trim');
    const h = rc ? tw(t, rc.tb + .15, rc.tb + .55, E.inOutCubic) : 0;
    set(this.pvIn, 'background', mixc(C.accent, C.hot, h));
    let pk = 0,
      rot = 0;
    this.punches.forEach((k, i) => {
      if (t >= k) {
        pk = punch(t, k, 7);
        rot = (i % 2 ? 1 : -1) * 4;
      }
    });
    set(this.pvW, 'transform', at(500, 281, `scale(${((1 + .3 * pk) * this.pvFit).toFixed(4)}) rotate(${(rot * pk).toFixed(2)}deg)`));
    const bs = this.punches.length ? tw(t, this.punches[0], this.punches[0] + .2, E.outBack) : 0,
      R = 330 * bs * (1 + .12 * pk);
    if (bs > 0) {
      const rr = rng(5),
        a0 = (t - this.punches[0]) * .8,
        N = 32;
      this.burstPoly.setAttribute('points', Array.from({
        length: N
      }, (_, j) => {
        const v = rr(),
          rad = j % 2 ? R * (.55 - .12 * v) : R * (1 + .15 * v),
          a = a0 + j / N * Math.PI * 2;
        return `${(500 + Math.cos(a) * rad).toFixed(1)},${(281 + Math.sin(a) * rad * .78).toFixed(1)}`;
      }).join(' '));
    }
    vis(this.burstSvg, bs > 0);
    let sw = -1;
    for (const n of this.notes) {
      const q = (t - n.tb - .1) / .5;
      if (q >= 0 && q <= 1) sw = q;
    }
    vis(this.scan, sw >= 0);
    if (sw >= 0) set(this.scan, 'transform', `translateX(${(sw * 1000).toFixed(1)}px)`);
    const c = tr ? tw(t, tr.tb + .35, tr.tb + .65, E.outExpo) : 0;
    let x = 0;
    this.segs.forEach((s, i) => {
      const w = i === 0 ? lerp(s.w0, s.w0 / 2, c) : s.w0;
      set(s, 'left', x.toFixed(1) + 'px');
      set(s, 'width', (w - 6).toFixed(1) + 'px');
      x += w;
    });
    set(this.ph, 'left', ((t - this.t0) * 160 % x).toFixed(1) + 'px');
    let typed = '',
      caret = false,
      bt = '',
      b0 = 0;
    for (const n of this.notes) {
      if (t >= n.ta && t < n.tb) {
        typed = n.s.slice(0, Math.ceil(tw(t, n.ta, n.tb - .15, E.lin) * n.s.length));
        caret = true;
      }
      if (t >= n.ta - .05 && t < n.tb + 1.4) {
        bt = n.s.toUpperCase();
        b0 = n.ta;
      }
      const b = tw(t, n.tb, n.tb + .28, E.outBack),
        rp = tw(t, n.tb + .5, n.tb + .7, E.outCubic);
      vis(n.bub, t >= n.tb);
      set(n.bub, 'transform', `translateY(${(30 * (1 - b)).toFixed(1)}px) scale(${lerp(.9, 1, b).toFixed(3)})`);
      set(n.bub, 'opacity', clamp(b).toFixed(3));
      set(n.rep, 'opacity', rp.toFixed(3));
    }
    set(this.send, 'transform', `scale(${this.notes.some(n => t >= n.tb && t < n.tb + .12) ? .86 : 1})`);
    this.inTxt.textContent = typed || ' ';
    set(this.inCar, 'opacity', caret || Math.floor(t * 3.4) % 2 ? '1' : '0');
    if (this.bgw.textContent !== (bt || ' ')) this.bgw.textContent = bt || ' ';
    set(this.bgw, 'transform', `translate(${(1500 - (t - b0) * 520).toFixed(1)}px, 360px)`);
  }
}
