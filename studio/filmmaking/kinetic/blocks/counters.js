import { C, E, lerp, tw, el, vis, set, at, type } from '../core.js';
import { fillVars, fitTo, reel, spinReel } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Counters: the source as a plane the camera flies over, giant numbers on slot reels ----------
// { counters: [['1', 'WEB PAGE'], ['{lines}', 'LINES OF CODE'], ['{frames}', 'FRAMES. ALL CODE.']], title: 'film / spec.js' }
// '{lines}' and '{frames}' are filled from the film itself.
export class Counters extends Scene {
  static N = 11;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o;
    r.classList.add('persp');
    this.plane = el('div', r, 'abs codewin', {
      left: '180px',
      top: '-560px',
      width: '1560px',
      height: '1740px',
      transformOrigin: '50% 100%'
    });
    const hd = el('div', this.plane, 'phead');
    for (let i = 0; i < 3; i++) el('span', hd, 'pdot');
    el('span', hd, 'mono ptitle').textContent = o.title || 'film / spec.js';
    this.body = el('div', this.plane, 'cbody');
    this.inner = el('div', this.body, 'cinner big');
    this.hlRow = el('div', this.body, 'abs hlrow');
    const lines = (o.source || f.src.code || '').split('\n');
    this.nl = lines.length;
    this.html = lines.map((l, i) => `<span class="ln">${i + 1}</span>${hl(l) || ' '}`);
    this.LH = 30;
    this.vrows = Array.from({
      length: 62
    }, () => {
      const d = el('div', this.inner, 'cl abs');
      d.style.width = '100%';
      return d;
    });
    const fill = v => fillVars(f, v);
    const cs = o.counters || [],
      step = 3;
    this.cnt = cs.map(([v, l], i) => {
      const g = el('div', r, 'abs full'),
        k = 2 + i * step,
        k1 = i < cs.length - 1 ? 2 + (i + 1) * step : 11;
      const num = reel(g, fill(v), {
        size: 360,
        color: C.accent,
        glow: 22
      });
      const lab = type(g, l, {
        size: 120,
        wdth: 122,
        cls: 'abs'
      });
      num.fit = fitTo(num.offsetWidth, 1700);
      lab.fit = fitTo(lab.offsetWidth, 1700);
      const t0 = this.k(k);
      f.cue(t0, 'impact', .8);
      f.cue(t0 + .05, 'tick_run', .3, {
        dur: .7
      });
      f.fast(t0, t0 + 1, 10);
      f.bump(t0, .05);
      f.shake(t0, 12);
      f.flash({
        t0,
        dur: .2,
        rise: .01,
        color: C.accent,
        peak: .18
      });
      f.burst({
        t0,
        x: 960,
        y: 450,
        n: 30,
        speed: 1300,
        life: .5,
        seed: 160 + i
      });
      return {
        g,
        num,
        lab,
        t: t0,
        t1: this.k(k1)
      };
    });
    f.fast(this.t0, this.k(2), 10);
    f.cue(this.t0, 'scroll', .55, {
      dur: this.t1 - this.t0
    });
  }
  update(t) {
    const e = tw(t, this.t0, this.t0 + .5, E.outExpo),
      dim = this.cnt.some(c => t >= c.t && t < c.t1) ? .32 : 1;
    set(this.plane, 'transform', `translateY(${(500 * (1 - e)).toFixed(1)}px) rotateX(${lerp(70, 56, e).toFixed(2)}deg) rotateZ(${(-4 + 3 * Math.sin((t - this.t0) * .9)).toFixed(2)}deg)`);
    set(this.plane, 'opacity', (e * dim).toFixed(3));
    const y = Math.pow(Math.max(0, t - this.t0), 1.15) * 3900,
      first = Math.floor(y / this.LH);
    this.vrows.forEach((d, i) => {
      const li = (first + i) % this.nl;
      if (d.__li !== li) {
        d.innerHTML = this.html[li];
        d.__li = li;
      }
      set(d, 'transform', `translateY(${((first + i) * this.LH - y).toFixed(1)}px)`);
    });
    set(this.hlRow, 'transform', `translateY(${(1080 - y % this.LH).toFixed(1)}px)`);
    this.cnt.forEach(c => {
      const on = t >= c.t - .01 && t < c.t1;
      vis(c.g, on);
      if (!on) return;
      const p = tw(t, c.t, c.t + .2, E.outExpo),
        x = tw(t, c.t1 - .12, c.t1, E.inCubic),
        a = t - c.t;
      set(c.num, 'transform', at(960, 450 - 300 * x, `scale(${(lerp(1.5, 1, p) * (1 + .05 * a) * c.num.fit).toFixed(4)})`));
      set(c.lab, 'transform', at(960 + 300 * (1 - tw(t, c.t + .08, c.t + .35, E.outExpo)), 720 + 300 * x, `scale(${c.lab.fit})`));
      set(c.lab, 'opacity', tw(t, c.t + .08, c.t + .2).toFixed(3));
      set(c.g, 'opacity', (1 - x).toFixed(3));
      spinReel(c.num, t, c.t, .75);
    });
  }
}
const KW = new Set('const let var class extends return if else for while new this function import export from of await async super static'.split(' '));
export function hl(line) {
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const re = /(\/\/.*$)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`)|\b([A-Za-z_]\w*)\b|\b(\d+(?:\.\d+)?)\b/g;
  let out = '',
    last = 0,
    m;
  while (m = re.exec(line)) {
    out += esc(line.slice(last, m.index));
    if (m[1]) out += `<i class="cm">${esc(m[1])}</i>`;else if (m[2]) out += `<i class="st">${esc(m[2])}</i>`;else if (m[3]) out += KW.has(m[3]) ? `<i class="kw">${m[3]}</i>` : /^[A-Z]/.test(m[3]) ? `<i class="ty">${m[3]}</i>` : m[3];else if (m[4]) out += `<i class="nu">${m[4]}</i>`;
    last = re.lastIndex;
  }
  return out + esc(line.slice(last));
}
