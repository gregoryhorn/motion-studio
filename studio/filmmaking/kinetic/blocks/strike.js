import { B, C, E, clamp, lerp, tw, rng, el, vis, set, at, type, styleType } from '../core.js';
import { cc, glowDot, isLight, qb, shake } from './helpers.js';
import { Scene } from './scene.js';

// ---------- Strike: "NO <thing>." over a mock of the thing, then the thing dies ----------
// items: [{ word, ui: { type: 'timeline', title, tag, tracks } | { type: 'tiles', tiles: [[label, icon], ...] } | { type: 'rack', rows: [...] },
//           ground, at, kill: 'slash' | 'topple' | 'power' }]   no: the word that slams beside each item ('NO')
// Each item: mock enters, NO slams at +1 beat, the word fills at +1.5, the mock dies at +2. tvOff: the last item ends in a TV switch-off point.
function timelinePanel(parent, ui) {
  const p = el('div', parent, 'panel');
  const hd = el('div', p, 'phead');
  for (let i = 0; i < 3; i++) el('span', hd, 'pdot');
  el('span', hd, 'mono ptitle').textContent = ui.title || 'sequence_final_v12_FINAL';
  el('span', hd, 'mono ptag').textContent = ui.tag || 'EXPORTING  3%  ·  14 H LEFT';
  const ru = el('div', p, 'ruler');
  for (let i = 0; i < 24; i++) {
    el('div', ru, 'tick', {
      left: 160 + i * 40 + 'px',
      height: i % 4 ? '7px' : '13px'
    });
    if (i % 4 === 0) el('div', ru, 'mono tlab', {
      left: 164 + i * 40 + 'px'
    }).textContent = `00:${String(i / 4 * 10).padStart(2, '0')}`;
  }
  const names = ui.tracks || ['V3', 'V2', 'V1', 'FX', 'CAM', 'A1', 'A2'],
    r = rng(21);
  p.clips = [];
  names.slice(0, 7).forEach((n, i) => {
    const row = el('div', p, 'trow', {
      top: 82 + i * 46 + 'px'
    });
    el('div', row, 'mono tname').textContent = n;
    let x = 160 + r() * 60;
    while (x < 1060) {
      const w = 70 + r() * 210;
      p.clips.push(el('div', row, 'clip' + (r() < .18 ? ' hot' : ''), {
        left: x + 'px',
        width: Math.min(w, 1090 - x) + 'px'
      }));
      x += w + 8 + r() * 50;
    }
  });
  p.ph = el('div', p, 'playhead');
  return p;
}
function noRow(no, w, t, tNo, tFill, y, o) {
  if (!no.__w) {
    no.__w = no.offsetWidth;
    w.__w = w.offsetWidth;
  }
  const nw = no.__w,
    ww = w.__w,
    gap = 54,
    tot = nw + gap + ww,
    sc = Math.min(1, 1680 / tot);
  const u = tw(t, tNo, tNo + .18, E.outExpo),
    xw = lerp(960, 960 + (tot / 2 - ww / 2) * sc, u),
    xn = 960 + (-tot / 2 + nw / 2) * sc;
  vis(no, t >= tNo - .01);
  const dr = Math.max(0, t - tNo) * 70;
  set(w, 'transform', at(xw + dr, y, `scale(${sc.toFixed(4)})`));
  set(no, 'transform', at(xn - 60 * (1 - u) + dr, y, `scale(${(sc * lerp(1.9, 1, u)).toFixed(4)}) rotate(${lerp(-12, -3, u).toFixed(2)}deg)`));
  set(no, 'opacity', clamp(u * 3).toFixed(3));
  const filled = t >= tFill;
  if (w.__filled !== filled) {
    styleType(w, {
      ...o,
      stroke: filled ? 0 : 3
    });
    w.__filled = filled;
  }
}
export class Strike extends Scene {
  build() {
    const f = this.f,
      r = this.root,
      o = this.o,
      n = o.items.length,
      span = (this.k1 - this.k0) / n;
    r.classList.add('persp');
    this.items = o.items.map((it, i) => {
      const k = it.at ?? this.k0 + i * span,
        kEnd = i < n - 1 ? o.items[i + 1].at ?? this.k0 + (i + 1) * span : this.k1;
      const ui = it.ui || {
          type: 'timeline'
        },
        kill = it.kill || {
          timeline: 'slash',
          tiles: 'topple',
          rack: 'power'
        }[ui.type] || 'slash';
      const g = cc(it.ground) || null,
        light = isLight(it.ground);
      const S = {
        it,
        ui,
        kill,
        k,
        kEnd,
        t: B(k),
        te: B(kEnd),
        light,
        tNo: B(k + 1),
        tFill: B(k + 1.5),
        tK: B(k + 2)
      };
      if (g) f.ground(S.t, S.te, g);
      if (i > 0) f.whip(S.t, i % 2 ? 1700 : 0, i % 2 ? 0 : 1150, .13, i % 2 ? -2 : 0);
      S.box = el('div', r, 'abs full p3d');
      S.wo = {
        size: 170,
        wdth: 110,
        color: light ? C.ink : C.paper
      };
      const mk = parent => {
        const no = type(parent, o.no || 'NO', {
          size: 170,
          wdth: 110,
          color: C.accent,
          glow: light ? 0 : 18,
          cls: 'abs'
        });
        const w = type(parent, it.word, {
          ...S.wo,
          stroke: 3,
          cls: 'abs'
        });
        return {
          no,
          w
        };
      };
      if (kill === 'slash') {
        const P1 = [250, 1010],
          P2 = [1700, 110],
          d = [P2[0] - P1[0], P2[1] - P1[1]],
          dl = Math.hypot(...d),
          dn = [d[0] / dl, d[1] / dl],
          nn = [-dn[1], dn[0]];
        S.n = nn;
        const E1 = [P1[0] - dn[0] * 3000, P1[1] - dn[1] * 3000],
          E2 = [P2[0] + dn[0] * 3000, P2[1] + dn[1] * 3000];
        const poly = sg => `polygon(${[E1, E2, [E2[0] + sg * nn[0] * 4000, E2[1] + sg * nn[1] * 4000], [E1[0] + sg * nn[0] * 4000, E1[1] + sg * nn[1] * 4000]].map(q => `${q[0].toFixed(0)}px ${q[1].toFixed(0)}px`).join(',')})`;
        S.halves = [1, -1].map(sg => {
          const h = el('div', S.box, 'abs full');
          h.style.clipPath = poly(sg);
          h.p = timelinePanel(h, ui);
          h.p.style.left = '400px';
          h.p.style.top = '430px';
          Object.assign(h, mk(h));
          return h;
        });
        f.comet({
          t0: S.tK - .03,
          t1: S.tK + .09,
          path: u => [lerp(P1[0], P2[0], u), lerp(P1[1], P2[1], u)],
          ease: E.lin,
          tail: .07,
          size: 11
        });
        f.slash({
          t0: S.tK - .03,
          x1: P1[0],
          y1: P1[1],
          x2: P2[0],
          y2: P2[1],
          dur: .12,
          hold: .1,
          fade: .1,
          w: 7
        });
        f.slash({
          t0: S.tK + .07,
          x1: 330,
          y1: 150,
          x2: 1620,
          y2: 980,
          dur: .08,
          hold: .06,
          fade: .1,
          w: 6
        });
        [.32, .5, .68].forEach((q, j) => f.burst({
          t0: S.tK + .02 + j * .02,
          x: lerp(P1[0], P2[0], q),
          y: lerp(P1[1], P2[1], q),
          n: 20,
          speed: 1000,
          life: .5,
          seed: 30 + j,
          w: 2.6
        }));
        f.flash({
          t0: S.tK,
          dur: .2,
          rise: .015,
          color: C.accent,
          peak: .22
        });
        f.shake(S.tK, 16);
        f.bump(S.tK, .04);
        f.cue(S.tK - .03, 'slash', 1);
        f.cue(S.tK, 'impact', .7);
        f.cue(S.tK + .07, 'slash', .6);
        f.fast(S.tK - .05, S.tK + .8, 10);
      } else {
        Object.assign(S, mk(S.box));
        if (ui.type === 'tiles') {
          S.tiles = el('div', S.box, 'abs p3d', {
            left: '441px',
            top: '480px',
            width: '1038px',
            height: '274px'
          });
          const rr = rng(17 + i);
          S.tl = (ui.tiles || []).slice(0, 8).map(([nm, ic, ver], j) => {
            const t = el('div', S.tiles, 'tile' + (light ? ' lt' : ''), {
              left: j % 4 * 266 + 'px',
              top: Math.floor(j / 4) * 150 + 'px'
            });
            el('div', t, 'ticon').textContent = ic || '◆';
            el('div', t, 'mono tlabel').textContent = nm;
            el('div', t, 'mono tver').textContent = ver || '';
            t.rz = (rr() - .5) * 50;
            t.z0 = -700 - rr() * 900;
            f.cue(S.t + .05 + j * .035, 'pop', .2);
            f.cue(S.tK + j * .045 + .25, 'thock', .4);
            return t;
          });
          f.slash({
            t0: S.tK + B(.55),
            x1: 380,
            y1: 900,
            x2: 1560,
            y2: 360,
            dur: .1,
            hold: .14,
            fade: .22,
            w: 6
          });
          f.cue(S.tK + B(.55), 'slash', .6);
          f.fast(S.t, S.t + .6, 8);
          f.fast(S.tK, S.tK + .9, 8);
        } else {
          S.rack = el('div', S.box, 'abs', {
            left: '510px',
            top: '440px',
            width: '900px',
            height: '378px'
          });
          S.units = (ui.rows || ['NODE 01', 'NODE 02', 'NODE 03']).slice(0, 3).map((nm, j) => {
            const u = el('div', S.rack, 'unit', {
              top: j * 134 + 'px'
            });
            el('div', u, 'mono uname').textContent = nm;
            const leds = el('div', u, 'leds');
            u.leds = Array.from({
              length: 14
            }, () => el('span', leds, 'led'));
            el('div', u, 'vents');
            f.cue(S.t + .05 + j * .1, 'thock', .5);
            return u;
          });
          S.tK = B(k + 2.5);
          f.comet({
            t0: S.tK - B(.6),
            t1: S.tK,
            path: u => qb([2050, 380], [1700, 420], [1410, 630], u),
            ease: E.inCubic,
            tail: .14,
            size: 9
          });
          f.burst({
            t0: S.tK,
            x: 1410,
            y: 630,
            n: 22,
            speed: 900,
            life: .45,
            seed: 44
          });
          f.cue(S.tK, 'power_down', .8);
        }
      }
      f.bump(S.tNo, .035);
      f.shake(S.tNo, 8);
      f.cue(S.tNo, 'thock', .8);
      f.cue(S.tNo, 'hit', .85);
      return S;
    });
    const L = this.items[n - 1];
    if (o.tvOff !== false) {
      this.tv = [B(this.k1 - .7), B(this.k1 - .4), this.t1];
      f.paint((x, t) => {
        const a = clamp((t - this.tv[1]) / .05) * (1 - clamp((t - this.t1 - .02) / .06));
        glowDot(x, 960, 629, 9, a, '#FFFFFF');
      });
      f.fast(this.tv[0], this.t1, 8);
      f.cue(this.tv[0], 'glitch', .4);
    }
  }
  update(t) {
    this.items.forEach((S, i) => {
      const on = t >= S.t - .01 && t < S.te;
      vis(S.box, on);
      if (!on) return;
      if (S.halves) {
        const e = tw(t, S.t, S.t + .42, E.outExpo),
          a = t - S.tK - .04,
          n = S.n;
        set(S.box, 'transform', `translateZ(${lerp(-1500, 0, e).toFixed(1)}px) rotateX(${lerp(28, 0, e).toFixed(2)}deg) rotateZ(${lerp(-5, 0, e).toFixed(2)}deg)`);
        set(S.box, 'opacity', clamp(e * 2).toFixed(3));
        S.halves.forEach((h, j) => {
          const sg = j ? -1 : 1,
            u = a > 0 ? E.outCubic(clamp(a / .5)) : 0,
            g = a > 0 ? a * a : 0;
          set(h, 'transform', `translate(${(sg * n[0] * 120 * u).toFixed(1)}px,${(sg * n[1] * 120 * u + (j ? 820 : 1050) * g).toFixed(1)}px) rotate(${(sg * 8 * u).toFixed(2)}deg)`);
          set(h, 'opacity', (1 - clamp((a - .35) / .4)).toFixed(3));
          set(h.p, 'transform', `rotateX(14deg) translateY(${(18 * Math.sin(t * 3)).toFixed(1)}px)`);
          set(h.p.ph, 'left', (240 + (t - S.t) * 900 % 900).toFixed(1) + 'px');
          h.p.clips.forEach((c, q) => set(c, 'opacity', (Math.floor(t * 14 + q * 1.7) % 5 === 0 ? .45 : 1).toString()));
          noRow(h.no, h.w, t, S.tNo, S.tFill, 260, S.wo);
        });
        return;
      }
      noRow(S.no, S.w, t, S.tNo, S.tFill, 260, S.wo);
      if (S.tl) {
        const sw = tw(t, S.t, S.tK, E.inOutCubic),
          hot = t >= S.tFill && t < S.tFill + .14;
        set(S.tiles, 'transform', `rotateX(${lerp(24, 8, sw).toFixed(2)}deg) rotateY(${lerp(-18, 12, sw).toFixed(2)}deg) translateZ(${lerp(-200, 60, sw).toFixed(1)}px)`);
        S.tl.forEach((tile, j) => {
          const p = tw(t, S.t + j * .035, S.t + j * .035 + .38, E.outBack);
          const d = tw(t, S.tK + j * .045, S.tK + j * .045 + .3, E.inCubic),
            fall = Math.max(0, t - S.tK - j * .045 - .3);
          set(tile, 'transform', `translateZ(${lerp(tile.z0, 0, p).toFixed(1)}px) rotateZ(${(tile.rz * (1 - p)).toFixed(2)}deg) translateY(${(d * 70 + 5 * Math.sin(t * 4 + j * 1.3) + 1400 * fall * fall).toFixed(1)}px) rotateX(${(-100 * d).toFixed(2)}deg)`);
          set(tile, 'opacity', (clamp(p * 1.6) * (1 - clamp((d - .8) / .2) * .5)).toFixed(3));
          set(tile, 'borderColor', hot ? C.accent : '');
        });
      }
      if (S.units) {
        const sw = tw(t, S.t, S.te, E.inOutCubic);
        set(S.rack, 'transform', `perspective(1400px) rotateY(${lerp(22, -14, sw).toFixed(2)}deg) rotateX(${lerp(8, -4, sw).toFixed(2)}deg) translateX(${lerp(-60, 60, sw).toFixed(1)}px)`);
        S.units.forEach((u, j) => {
          const p = tw(t, S.t + .05 + j * .1, S.t + .05 + j * .1 + .3, E.outBack),
            sh = t > S.tK ? shake(t - S.tK - j * .03, 6, 10, 70) : 0;
          set(u, 'transform', `translateX(${(-1100 * (1 - p) + sh).toFixed(1)}px) translateY(${(t < S.tK ? 2 * Math.sin(t * 47 + j * 2) : 0).toFixed(2)}px)`);
          set(u, 'opacity', clamp(p * 1.4).toFixed(3));
          u.leds.forEach((l, q) => {
            const dead = t > S.tK + (13 - q) * .018 + j * .03,
              blink = Math.floor(t * 12 + q * 3.7 + j * 5.1) % 4 !== 0;
            set(l, 'background', dead ? '#2A2D31' : q % 5 === 0 ? blink ? C.accent : C.sideP : blink ? C.paper : '#4A4C50');
          });
        });
      }
      if (this.tv && i === this.items.length - 1) {
        const o1 = tw(t, this.tv[0], this.tv[1], E.inCubic),
          o2 = tw(t, this.tv[1], this.tv[2], E.inExpo);
        set(S.box, 'transformOrigin', '960px 629px');
        set(S.box, 'transform', `scale(${lerp(1, .003, o2).toFixed(4)},${lerp(1, .006, o1).toFixed(4)})`);
        set(S.box, 'filter', o1 > 0 ? `brightness(${(1 + 3 * o1).toFixed(2)})` : 'none');
      }
    });
  }
}
