// Isolated component contracts; synthetic fixtures are not real media acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';

const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8');
const prelude = `
const atom = initial => { let value = initial; return { get: () => value, set: next => { value = next; } }; };
const host = {}, useValue = a => a.get(), useQuery = () => ({}), queryClient = {};
const PANES_AREA = '', ROUTES_AREA = '', PALETTE_AREA = '', KEYBINDS_AREA = '';
const h = (type, props, ...children) => ({ type, props: props || {}, children });
const useEffect = () => {}, useRef = current => ({ current }), useState = value => [value, () => {}];
`;
const instrumented = prelude + source.replace(/^import .*$/gm, '') + '\nexport { CSS };';
const ui = await import('data:text/javascript;base64,' + Buffer.from(instrumented).toString('base64'));
const format = { duration_frames: 0, fps: { num: 60, den: 1 } };
const version = () => ({ format: structuredClone(format), clips: [], tracks: [
  { track_id: 'picture', name: 'V1', kind: 'video', order: 0, locked: false, visible: true, muted: false },
  { track_id: 'sound', name: 'A1', kind: 'audio', order: 1, locked: false, visible: true, muted: false }
] });
function model(v = version()) { return { s: ui.studioState.get(), version: v }; }
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...tree.children.flat(Infinity).flatMap(nodes)];
}

test('empty timeline has ten seconds of unique increasing timecode, without changing duration', () => {
  const before = structuredClone(format), scale = ui.timelineScale(format, 1000);
  assert.equal(scale.duration, 600);
  assert.equal(scale.ticks[0].label, '00:00:00:00');
  assert.equal(scale.ticks[1].label, '00:00:02:00');
  assert.ok(scale.ticks.length > 1);
  assert.equal(new Set(scale.ticks.map(t => t.label)).size, scale.ticks.length);
  assert.ok(scale.ticks.every((t, i) => !i || t.frame > scale.ticks[i - 1].frame));
  assert.deepEqual(format, before);
});
test('ruler density remains bounded at narrow, wide and zoomed widths and fractional fps', () => {
  for (const width of [120, 240, 1000, 8000]) for (const frames of [0, 1, 600, 1000000]) {
    const scale = ui.timelineScale({ duration_frames: frames, fps: { num: 30000, den: 1001 } }, width);
    assert.ok(scale.ticks.length <= Math.max(1, Math.floor(width / 120)) + 1);
    assert.ok(scale.duration >= frames);
    assert.ok(scale.ticks.every(t => Number.isSafeInteger(t.frame)));
    assert.ok(scale.step * scale.px >= Math.min(120, width));
  }
});
test('empty state retains real lanes, offers Assets, and shows no invented clips', () => {
  const tree = nodes(ui.TimelineContent({ model: model() }));
  assert.equal(tree.filter(n => n.props.className === 'track').length, 2);
  assert.equal(tree.filter(n => n.props.className === 'clip').length, 0);
  assert.equal(tree.filter(n => n.props.className === 'playhead').length, 3);
  const empty = tree.find(n => n.props.className === 'timeline-empty');
  assert.ok(empty);
  nodes(empty).find(n => n.children.includes('Open Assets')).props.onClick();
  assert.equal(ui.studioState.get().tab, 'Assets');
});
test('ruler seeking uses lane bounds, not nested label offset, and does not extend media', () => {
  const v = version(), tree = nodes(ui.TimelineContent({ model: model(v) }));
  const ruler = tree.find(n => n.props.className === 'ruler');
  const lane = nodes(ruler).find(n => n.props.className === 'lane');
  lane.props.onClick({ clientX: 660, currentTarget: { getBoundingClientRect: () => ({ left: 160 }) }, nativeEvent: { offsetX: 1 } });
  assert.equal(ui.studioState.get().frame, 300);
  assert.equal(v.format.duration_frames, 0);
});
test('populated clips keep proportional geometry and suppress empty-state copy', () => {
  const v = version();
  v.format.duration_frames = 1200;
  v.clips.push({ clip_id: 'unit-clip', track_id: 'picture', start_frame: 60, end_frame: 180, subject: { kind: 'asset', id: 'unit-source' } });
  const tree = nodes(ui.TimelineContent({ model: model(v) }));
  const clip = tree.find(n => n.props.className === 'clip');
  assert.equal(clip.props.style.left, 50);
  assert.equal(clip.props.style.width, 100);
  assert.ok(!tree.some(n => n.props.className === 'timeline-empty'));
});

// Optional visual fixture: actual component markup/CSS, no host/backend simulation.
if (process.env.MOTION_TIMELINE_PREVIEW) {
  const escape = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
  function html(node) {
    if (node == null || typeof node === 'boolean') return '';
    if (Array.isArray(node)) return node.map(html).join('');
    if (typeof node !== 'object') return escape(node);
    if (typeof node.type === 'function') return html(node.type({ ...node.props, children: node.children }));
    const attrs = Object.entries(node.props).filter(([key, value]) => !['key', 'ref', 'children'].includes(key) && !key.startsWith('on') && value != null).map(([key, value]) => {
      if (key === 'style') value = Object.entries(value).map(([k, v]) => `${k.replace(/[A-Z]/g, m => '-' + m.toLowerCase())}:${typeof v === 'number' && v !== 0 ? v + 'px' : v}`).join(';');
      return `${key === 'className' ? 'class' : key}="${escape(value)}"`;
    }).join(' ');
    const body = node.type === 'style' ? node.children.join('') : node.children.map(html).join('');
    return `<${node.type} ${attrs}>${body}</${node.type}>`;
  }
  ui.studioState.set({ ...ui.studioState.get(), frame: 0, tab: 'Preview' });
  const tree = ui.TimelineContent({ model: model() });
  await writeFile(process.env.MOTION_TIMELINE_PREVIEW, `<!doctype html><meta charset="utf-8"><title>Timeline component fixture - not a live project</title><style>:root{--background:#141619;--foreground:#e8e9eb;--muted-foreground:#a7acb4;--border:#3c4149;--primary:#e8c667}body{margin:0;padding:16px;background:#141619} ${ui.CSS}</style><main class="ms">${html(tree)}</main>`);
}
