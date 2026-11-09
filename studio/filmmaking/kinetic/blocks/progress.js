import { C, DUR, FPS, E, clamp, lerp, tw, rgba, el, vis, set, at, type, styleType } from '../core.js';
import { cc, fitTo, punch } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Progress: a two-line claim renders itself, frames of the film ride a conveyor past a render head ----------
// { lines: ['RENDERED', 'ON A LAPTOP.'], cards: [['EVERY', 'bg', 'paper'], ['FRAME', 'accent', 'ink'], ...], label: 'RENDER  4K · 60 FPS', doneLabel: 'RENDER  ✓ DONE', doneRight: 'ON A LAPTOP', ground: 'paper' }
export class Progress extends Scene {
  static N = 9;
  build() {
    const f = this.f,
      r = this.root,
      o = this.o,
      [l1, l2] = o.lines || ['RENDERED', 'ON A LAPTOP.'];
    this.R = el('div', r, 'abs full');
    this.r1o = type(this.R, l1, {
      size: 170,
      color: rgba(C.ink, .45),
      stroke: 2.5,
      cls: 'abs'
    });
    this.r1 = type(this.R, l1, {
      size: 170,
      color: C.ink,
      cls: 'abs'
    });
    this.r2 = type(this.R, l2, {
      size: 170,
      color: C.accent,
      cls: 'abs'
    });
    this.f1 = fitTo(this.r1.offsetWidth, 1700);
    this.f2 = fitTo(this.r2.offsetWidth, 1700);
    this.r1w = this.r1.offsetWidth * this.f1;
    this.r1s = el('div', this.R, 'abs rhead');
    this.bar = el('div', this.R, 'abs rbar lt');
    this.barFill = el('div', this.bar, 'rfill');
    this.big = el('div', this.R, 'abs mono bigc');
    this.barL = el('div', this.R, 'abs mono rlab lt');
    this.barR = el('div', this.R, 'abs mono rlab lt');
    this.belt = el('div', this.R, 'abs full');
    this.head = el('div', this.R, 'abs rhead');
    const FR = o.cards || [['FRAME', 'bg', 'paper'], ['BY', 'accent', 'ink'], ['FRAME', 'paper', 'ink'], ['IN', 'bg', 'accent'], ['CODE.', 'accent', 'ink']];
    this.cards = FR.map(([wd, bg, col], i) => {
      const c = el('div', this.belt, 'abs fcard');
      const tx = type(c, wd, {
        size: 50,
        wdth: 110,
        color: cc(col),
        cls: 'abs'
      });
      tx.style.left = '50%';
      tx.style.top = '50%';
      tx.style.transform = `translate(-50%,-50%) scale(${fitTo(tx.offsetWidth, 210)})`;
      return {
        c,
        tx,
        bg: cc(bg),
        col: cc(col),
        x0: i * 262
      };
    });
    this.beltW = Math.max(FR.length, 8) * 262;
    this.frames = Math.round(DUR * FPS);
    this.tR1 = this.t0 + .02;
    this.tR2 = this.k(1.7);
    f.ground(this.t0, this.t1, cc(o.ground || 'paper'));
    f.burst({
      t0: this.tR2,
      x: 1200,
      y: 520,
      n: 30,
      speed: 1300,
      life: .5,
      seed: 111,
      color: C.ink,
      blend: 'source-over'
    });
    f.shake(this.tR1, 10);
    f.shake(this.tR2, 16);
    f.bump(this.tR1, .035);
    f.bump(this.tR2, .05);
    f.bump(this.k(7), .05);
    f.fast(this.tR1 - .03, this.tR2 + .3, 10);
    f.fast(this.k(2), this.k(7), 6);
    f.cue(this.tR1, 'impact', .8);
    f.cue(this.tR2, 'impact_big', 1);
    f.cue(this.k(2), 'tick_run', .35, {
      dur: this.k(7) - this.k(2)
    });
    f.cue(this.k(7), 'ding', .7);
  }
  cam(t) {
    const u = tw(t, this.t0, this.t1, E.lin);
    return {
      s: 1 + .1 * E.inOutCubic(u),
      r: lerp(-1.2, 1.2, u),
      y: lerp(-10, 20, u)
    };
  }
  update(t) {
    const o = this.o,
      a1 = tw(t, this.tR1, this.tR1 + .2, E.outExpo),
      a2 = tw(t, this.tR2, this.tR2 + .2, E.outExpo);
    vis(this.r2, t >= this.tR2 - .01);
    const r1t = at(960, 262 - 300 * (1 - a1), `scale(${this.f1})`),
      wp = tw(t, this.tR1 + .1, this.tR2 - .05, E.inOutCubic);
    set(this.r1, 'transform', r1t);
    set(this.r1o, 'transform', r1t);
    set(this.r1, 'clipPath', `inset(-20% ${((1 - wp) * 100).toFixed(2)}% -20% 0)`);
    vis(this.r1s, wp > 0 && wp < 1);
    set(this.r1s, 'transform', `translate(${(960 - this.r1w / 2 + this.r1w * wp - 2).toFixed(1)}px, ${(262 - 300 * (1 - a1) - 92).toFixed(1)}px)`);
    set(this.r2, 'transform', at(960 + 800 * (1 - a2), 432, `scaleX(${lerp(1.45, 1, a2).toFixed(3)}) scale(${this.f2})`));
    set(this.r2, 'opacity', clamp(a2 * 2).toFixed(3));
    const b = tw(t, this.k(1.9), this.k(2.3), E.outCubic),
      prog = tw(t, this.k(2), this.k(7), E.inOutCubic),
      done = t >= this.k(7);
    [this.bar, this.barL, this.barR, this.big, this.belt, this.head].forEach(n => set(n, 'opacity', b.toFixed(3)));
    set(this.bar, 'transform', at(960, 768));
    const off = Math.max(0, t - this.k(1.9)) * 820;
    this.cards.forEach(cd => {
      const x = ((cd.x0 - off - 200) % this.beltW + this.beltW) % this.beltW - 300,
        ren = x + 120 < 960 || done;
      set(cd.c, 'transform', `translate(${x.toFixed(1)}px, 552px)`);
      if (cd.ren !== ren) {
        cd.ren = ren;
        set(cd.c, 'background', ren ? cd.bg : 'transparent');
        set(cd.c, 'borderStyle', ren ? 'solid' : 'dashed');
        styleType(cd.tx, {
          size: 50,
          wdth: 110,
          color: ren ? cd.col : rgba(C.ink, .35),
          stroke: ren ? 0 : 1.5
        });
      }
    });
    set(this.head, 'transform', 'translate(958px, 527px)');
    set(this.barFill, 'width', (prog * 100).toFixed(2) + '%');
    this.barL.textContent = done ? o.doneLabel || 'RENDER  ✓ DONE' : o.label || 'RENDER  4K · 60 FPS';
    this.barR.textContent = done ? o.doneRight || '' : `${Math.round(prog * 100)}%`;
    set(this.barL, 'transform', 'translate(210px, 798px)');
    set(this.barR, 'transform', `translate(${1710 - this.barR.offsetWidth}px, 798px)`);
    this.big.textContent = `${String(Math.round(prog * this.frames)).padStart(4, '0')} / ${this.frames}`;
    set(this.big, 'transform', at(960, 905, `scale(${(1 + .12 * (done ? punch(t, this.k(7), 8) : 0)).toFixed(4)})`));
    set(this.big, 'color', done ? C.accent : C.ink);
  }
}
