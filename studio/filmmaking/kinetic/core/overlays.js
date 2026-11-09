import { C } from './palette.js';
import { E, lerp, tw } from './math.js';
import { rgba } from './color.js';
import { el, vis, set } from './dom.js';

// ---------- caption: spoken-style line, top left, current word in a highlight box ----------
export class Caption {
  constructor(film, phrases) {
    // own copies: the nested film in the rewind builds a second caption from the same phrase list
    this.f = film; this.ph = phrases.map(p => ({ ...p }));
    this.root = el('div', film.overlay, 'cap');
    for (const p of this.ph) {
      p.line = el('div', this.root, 'capline');
      p.box = el('div', p.line, 'capbox');
      p.spans = p.words.map(([w], i) => {
        const s = el('span', p.line, 'capw'); s.textContent = w;
        if (i < p.words.length - 1) el('span', p.line, 'capsp').textContent = ' ';
        return s;
      });
    }
  }
  measure() {
    for (const p of this.ph) p.geo = p.spans.map(s => [s.offsetLeft, s.offsetWidth]);
  }
  update(t, light) {
    const ink = light ? C.ink : C.paper, hi = light ? C.ink : C.accent, hiText = light ? C.accent : C.ink;
    for (const p of this.ph) {
      const on = t >= p.t0 - .05 && t < p.t1 + .15;
      vis(p.line, on);
      if (!on) continue;
      const out = tw(t, p.t1, p.t1 + .14, E.inCubic);
      set(p.line, 'opacity', (1 - out).toFixed(3));
      set(p.line, 'transform', `translateY(${(-10 * out).toFixed(2)}px)`);
      let cur = -1;
      p.words.forEach(([, wt], i) => {
        const s = p.spans[i], u = tw(t, wt - .03, wt + .1, E.outCubic);
        if (t >= wt - .01) cur = i;
        set(s, 'opacity', u.toFixed(3));
        set(s, 'transform', `translateY(${((1 - u) * 12).toFixed(2)}px)`);
      });
      p.spans.forEach((s, i) => set(s, 'color', i === cur ? hiText : ink));
      if (cur < 0) { set(p.box, 'opacity', '0'); continue; }
      // the box slides from the previous word to the current one
      const wt = p.words[cur][1], u = tw(t, wt - .01, wt + .08, E.outCubic);
      const [x1, w1] = p.geo[cur], [x0, w0] = cur > 0 ? p.geo[cur - 1] : [x1, 0];
      const x = lerp(x0, x1, u), w = lerp(w0, w1, u);
      set(p.box, 'opacity', '1');
      set(p.box, 'background', hi);
      set(p.box, 'transform', `translateX(${(x - 7).toFixed(2)}px)`);
      set(p.box, 'width', (w + 14).toFixed(2) + 'px');
    }
  }
}

// ---------- HUD: corner brackets, frame counter, label, REC, timecode ----------
export class HUD {
  constructor(film, label = '') {
    this.root = el('div', film.overlay, 'hud');
    this.br = ['tl', 'tr', 'bl', 'brr'].map(k => el('div', this.root, 'br ' + k));
    this.fr = el('div', this.root, 'hudt tl'); this.lb = el('div', this.root, 'hudt tr');
    this.rec = el('div', this.root, 'hudt bl'); this.tc = el('div', this.root, 'hudt brt');
    this.lb.textContent = label;
    this.dot = el('span', this.rec, 'recdot'); el('span', this.rec).textContent = 'REC';
  }
  update(t, light, alpha) {
    const f = Math.floor(t * 60 + 1e-6);
    this.fr.textContent = 'FRAME ' + String(f).padStart(4, '0');
    const s = Math.floor(t), ff = f % 60;
    this.tc.textContent = `00:${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}:${String(ff).padStart(2, '0')}`;
    set(this.root, 'opacity', alpha.toFixed(3));
    set(this.root, 'color', light ? rgba(C.ink, .55) : rgba(C.paper, .42));
    set(this.root, 'borderColor', light ? rgba(C.ink, .45) : rgba(C.paper, .32));
    set(this.dot, 'opacity', (t % 1 < .55 ? 1 : .25).toString());
    set(this.dot, 'background', light ? C.ink : C.accent);
  }
}
