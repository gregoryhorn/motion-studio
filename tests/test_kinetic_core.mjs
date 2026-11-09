// Core component regressions. Synthetic DOM/canvas fixtures are not visual acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import * as core from '../studio/filmmaking/kinetic/core.js';
import * as timing from '../studio/filmmaking/kinetic/core/timing.js';
import * as palette from '../studio/filmmaking/kinetic/core/palette.js';
import * as effects from '../studio/filmmaking/kinetic/core/effects.js';

const colors = { bg: '#0C0E11', paper: '#F4F1EA', accent: '#FF5B2E', hot: '#FF3A0A', ink: '#141210' };
function element(tag) {
  const e = { tag, style: {}, children: [], className: '', textContent: '',
    appendChild(child) { this.children.push(child); child.parentElement = this; },
    get offsetLeft() { return this.parentElement ? this.parentElement.children.indexOf(this) * 24 : 0; },
    get offsetWidth() { return Math.max(20, this.textContent.length * 20); },
    get offsetHeight() { return 40; }
  };
  return e;
}
function documentFixture(api = core) {
  const properties = {};
  globalThis.document = {
    createElement: element,
    documentElement: { style: { setProperty: (key, value) => { properties[key] = value; } } }
  };
  api.configure();
  api.setPalette(colors);
  return properties;
}
function snapshot(e) {
  return { tag: e.tag, className: e.className, text: e.textContent,
    style: { ...e.style }, children: e.children.map(snapshot) };
}
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

function drawingFixture(api) {
  documentFixture(api);
  const calls = [];
  let gradients = 0;
  const x = new Proxy({}, {
    set(target, name, value) { calls.push(['set', name, value]); target[name] = value; return true; },
    get(target, name) {
      if (name === 'createRadialGradient') return (...args) => {
        const id = ++gradients;
        calls.push([name, id, ...args]);
        return { id, addColorStop: (...stops) => calls.push(['addColorStop', id, ...stops]) };
      };
      return (...args) => calls.push([name, ...args]);
    }
  });
  const fixtures = [
    ['drawComet', { t0: .1, t1: 1, path: u => [100 + u * 400, 500 - u * 100], trail: true, trailEnd: 1.4 }],
    ['drawBurst', { t0: .1, x: 900, y: 450, seed: 11 }],
    ['drawBurst', { t0: .1, x: 900, y: 450, seed: 11, glyphs: '{}ABC', gsize: 22 }],
    ['drawSlash', { t0: .1, x1: 0, y1: 80, x2: 800, y2: 400 }],
    ['drawDots', { t0: .1, dur: 1, cx: 960, cy: 540, rx: 60, ry: 50 }],
    ['drawRays', { t0: .1 }], ['drawRays', { t0: .1, inward: true }],
    ['drawRing', { t0: .1 }], ['drawBokeh', { t0: .1, t1: 2 }],
    ['drawStarburst', { t0: .1, t1: 2, morph: [.6, 1.2] }]
  ];
  for (const [name, options] of fixtures) for (const t of [-.01, 0, .1, .15, .3, .7, 1, 1.2, 1.8, 2.4]) {
    calls.push(['effect', name, t]);
    api[name](x, options, t);
  }
  return calls;
}
function typographyFixture(api) {
  documentFixture(api);
  const root = element('root');
  api.type(root, 'CODE', { size: 160, glow: 12 });
  const { spans } = api.letters(root, 'A B', { color: api.C.accent });
  const extruded = api.extrude(root, 'FILM', { layers: 4, depth: 20, glow: 6 });
  assert.equal(extruded.face, extruded.children.at(-1));
  const sliced = api.slices(root, 'GLITCH', { size: 180 }, 3);
  const states = [];
  for (const t of [0, .1, .4, 1.2, .1]) {
    api.glitch(sliced, t, .05, .4, 25, 3);
    api.tumble(spans, t, 0, { seed: 9 });
    states.push(snapshot(root));
  }
  return states;
}

// Recorded from the unchanged monolithic core before extraction.
const drawingDigest = 'bfc64beeeed804cc22af3b9aeec950e9c9b7e19c43395d944c6191f62ff88b1b';
const typographyDigest = '2372f5a743cdd61fb822e15fbcef2c31f30fcc6f6478a3bb2c041150a5d0b633';

test('core facade preserves every existing named export', () => {
  assert.deepEqual(Object.keys(core).sort(), (`B BEATS BPM C Caption DUR E FPS FX H HUD W at beatAt clamp configure
    drawBokeh drawBurst drawComet drawDots drawRays drawRing drawSlash drawStarburst el env extrude glitch
    lerp letters mixc rgba rng set setPalette slices styleType tumble tw type vis`).split(/\s+/).sort());
  assert.equal(core.configure, timing.configure);
  assert.equal(core.C, palette.C);
  assert.equal(core.drawComet, effects.drawComet);
});
test('timing re-exports are live and tempo anchors remain copied and reversible', () => {
  const anchors = [[0, 0], [4, 3], [8, 5]];
  core.configure({ bpm: 90, beats: 12, fps: 30, tempoMap: anchors });
  assert.equal(core.BPM, 90); assert.equal(core.FPS, 30); assert.equal(core.BEATS, 12);
  assert.equal(core.DUR, timing.DUR); assert.equal(core.DUR, 5 + 4 * 60 / 90);
  anchors[1][1] = 50;
  for (const beat of [-2, 0, 1, 4, 5, 8, 9, 12]) assert.ok(Math.abs(core.beatAt(core.B(beat)) - beat) < 1e-10);
  timing.configure({ bpm: 60, beats: 10, fps: 24 });
  assert.equal(core.DUR, 10); assert.equal(core.B(3), 3); assert.equal(core.FPS, 24);
  core.configure();
});
test('timing validation rejects invalid configuration and non-finite beats', () => {
  for (const options of [{ bpm: 0 }, { fps: NaN }, { beats: -1 }, { tempoMap: [] },
    { tempoMap: [[1, 0]] }, { tempoMap: [[0, 0], [2, 1], [1, 2]] }, { tempoMap: [[0, 0], [2, Infinity]] }])
    assert.throws(() => core.configure(options));
  assert.throws(() => core.B(Infinity), /Beat must be finite/);
  core.configure();
});
test('palette mutations remain shared by typography and CSS variables', () => {
  const properties = documentFixture();
  const identity = core.C;
  palette.setPalette({ accent: '#112233', paper: '#abcdef' });
  assert.equal(core.C, identity); assert.equal(core.C.tint, core.mixc('#112233', '#FFFFFF', .72));
  assert.equal(properties['--accent'], '#112233'); assert.equal(properties['--paper'], '#abcdef');
  assert.equal(core.type(null, 'Shared palette').style.color, '#abcdef');
  documentFixture();
});
test('easing, colors and seeded randomness preserve numerical behavior', () => {
  assert.equal(core.clamp(-1), 0); assert.equal(core.clamp(2), 1);
  assert.equal(core.lerp(10, 20, .25), 12.5); assert.equal(core.tw(-2, 0, 1), 0);
  assert.equal(core.tw(2, 0, 1), 1); assert.equal(core.mixc('#000000', '#FFFFFF', .5), '#808080');
  assert.equal(core.rgba('#112233', .4), 'rgba(17,34,51,0.4)');
  const a = core.rng(7), b = core.rng(7), c = core.rng(8);
  const sequence = next => Array.from({ length: 12 }, next);
  const values = sequence(a);
  assert.deepEqual(values, sequence(b)); assert.notDeepEqual(values, sequence(c));
  assert.ok(values.every(v => v >= 0 && v < 1));
});
test('typography and canvas command snapshots match the pre-refactor engine', () => {
  assert.equal(digest(drawingFixture(core)), drawingDigest);
  assert.equal(digest(typographyFixture(core)), typographyDigest);
});
test('caption measurement, active word and HUD formatting remain unchanged', () => {
  documentFixture();
  const phrases = [{ t0: 0, t1: 1, words: [['HELLO', 0], ['WORLD', .5]] }];
  const film = { overlay: element('overlay') }, cap = new core.Caption(film, phrases);
  cap.measure(); cap.update(.7, false);
  assert.equal(phrases[0].line, undefined);
  assert.equal(cap.ph[0].spans[1].style.color, core.C.ink);
  assert.equal(cap.ph[0].box.style.opacity, '1');
  cap.update(2, false); assert.equal(cap.ph[0].line.style.display, 'none');
  cap.update(.2, true); assert.equal(cap.ph[0].spans[0].style.color, core.C.accent);
  const hud = new core.HUD(film, 'TEST'); hud.update(61.5, false, .5);
  assert.equal(hud.fr.textContent, 'FRAME 3690'); assert.equal(hud.tc.textContent, '00:01:01:30');
  assert.equal(hud.root.style.opacity, '0.500'); assert.equal(hud.lb.textContent, 'TEST');
});
test('every retained block imports through the compatibility facade', async () => {
  const blocks = await import('../studio/filmmaking/kinetic/blocks.js');
  for (const name of ['Scene', 'Words', 'Strike', 'Graph', 'Hero', 'Prompt', 'Stretch', 'Fly',
    'Notes', 'Counters', 'Progress', 'Chain', 'Rewind', 'Logo', 'Picture']) assert.equal(typeof blocks[name], 'function');
  assert.ok(blocks.Words && blocks.Prompt && blocks.Strike && blocks.Counters);
  const { Film } = await import('../studio/filmmaking/kinetic/compositor.js');
  assert.equal(typeof Film, 'function');
});

// Local one-time parity check against a pre-refactor copy, never an engine fallback.
if (process.env.KINETIC_BASELINE) {
  const source = await readFile(process.env.KINETIC_BASELINE, 'utf8');
  const baseline = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const drawing = drawingFixture(baseline), typography = typographyFixture(baseline);
  assert.equal(digest(drawingFixture(core)), digest(drawing));
  assert.deepEqual(typographyFixture(core), typography);
  assert.deepEqual(Object.keys(core), Object.keys(baseline));
  for (const [name, value] of Object.entries(baseline)) if (typeof value === 'function')
    assert.equal(core[name].toString(), value.toString(), name + ' implementation changed');
  console.log('Pre-refactor parity:', JSON.stringify({ drawing: digest(drawing), typography: digest(typography) }));
}
