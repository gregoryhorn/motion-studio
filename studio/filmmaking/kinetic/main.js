// main.js: boot a film. Loads spec.js (the film), fonts, the logo and the film's own source, builds it,
// and exposes __seek / __samples / __shutter for the renderer and a scrubber for previewing.
import { configure, setPalette, W, H, DUR, FPS, BPM, B, beatAt } from './core.js';
import { Film } from './compositor.js';

const spec = (await import('./spec.js')).default;
configure(spec);
setPalette(spec.palette || {});
await Promise.all(['900 100px Archivo', '500 20px JBM', '700 30px Inst', '400 30px Inst'].map(f => document.fonts.load(f)));
const files = ['spec.js', 'blocks.js', 'core.js', 'compositor.js', 'main.js', 'index.html', 'treatment.js', 'hold.js'];
const texts = await Promise.all(files.map(async u => { const r = await fetch(['blocks.js', 'core.js'].includes(u) ? u.replace('.js', '-source.txt') : u); return r.ok ? r.text() : (['blocks.js', 'core.js'].includes(u) ? fetch(u).then(r => r.ok ? r.text() : '') : ''); }));
const src = { code: texts.slice(0, 2).join('\n'), lines: texts.reduce((n, s) => n + (s ? s.trimEnd().split('\n').length : 0), 0) };
// the logo is inlined as SVG markup, so anything active in the file is stripped first: scripts, embedded
// HTML, event handlers, and links or animations that point at javascript: (browsers ignore tabs, newlines
// and control characters in a URL, so "java&#9;script:" is checked without them)
const jsUrl = v => /^javascript:/i.test(v.replace(/[\s\u0000-\u001f]/g, ''));
function inertSvg(text) {
  const doc = new DOMParser().parseFromString(text, 'image/svg+xml'), svg = doc.documentElement;
  if (svg.nodeName.toLowerCase() !== 'svg' || doc.querySelector('parsererror')) return '';
  svg.querySelectorAll('script, foreignObject, iframe, object, embed').forEach(n => n.remove());
  svg.querySelectorAll('set, animate').forEach(n => { if (/href|^on/i.test(n.getAttribute('attributeName') || '')) n.remove(); });
  for (const n of [svg, ...svg.querySelectorAll('*')])
    for (const a of [...n.attributes]) if (/^on/i.test(a.name) || (/href$/i.test(a.name) && jsUrl(a.value))) n.removeAttribute(a.name);
  return new XMLSerializer().serializeToString(svg);
}
const logo = spec.logo ? await fetch(spec.logo).then(r => {if(!r.ok) throw Error('Missing logo: '+spec.logo); return r.text();}).then(inertSvg) : '';
if(spec.logo && !logo) throw Error('Invalid SVG logo');
await Promise.all(spec.scenes.map(([S,,,o]) => S.prepare?.(o || {})));
const images=spec.scenes.filter(([S,,,o])=>S.assetType!=='svg-draw' && o && o.src).map(([S,,,o])=>o.src);
await Promise.all(images.map(src=>new Promise((resolve,reject)=>{const im=new Image(); im.onload=resolve; im.onerror=()=>reject(Error('Missing/invalid picture: '+src)); im.src=src;})));

const film = new Film(document.getElementById('root'), { src, logo, spec });
window.__film = { title: spec.title || '', width: W, height: H, duration: DUR, dur: DUR, fps: FPS, bpm: BPM, cues: film.selectedCues(), lines: src.lines, cuts: film.cuts(), music: spec.music ? {...spec.music, stopTime:spec.music.stopBeat!=null ? B(spec.music.stopBeat):null}:null, sounds:spec.sounds||{}, treatment:spec.treatment||'kinetic', endCardStart:spec.endCardStart!=null ? B(spec.endCardStart):null, assets:spec.assets||[] };
window.__samples = (t, dt) => film.samples(t, dt);
window.__shutter = t => film.shutter(t);
window.__seek = t => film.render(t);
window.__beatToSeconds = B;
film.render(0);
window.__duration=DUR; window.__loaded=true; window.__resolveReady?.();

// preview: space plays, arrows step one beat, 0-9 jump to tenths of the film, ?t=12 starts at 12 s
if (!location.search.includes('render')) {
  let t = +(new URLSearchParams(location.search).get('t') || 0), playing = false, last = 0;
  const bar = document.createElement('input');
  Object.assign(bar, { type: 'range', min: 0, max: DUR, step: 1 / FPS, value: t });
  bar.className = 'scrub'; document.body.appendChild(bar);
  const label = document.createElement('div'); label.className = 'scrubt'; document.body.appendChild(label);
  const show = () => { film.render(t); bar.value = t; label.textContent = `${t.toFixed(2)} s  ·  beat ${beatAt(t).toFixed(1)}`; };
  bar.oninput = () => { t = +bar.value; show(); };
  addEventListener('keydown', e => {
    if (e.code === 'Space') { playing = !playing; last = performance.now(); e.preventDefault(); }
    if (e.code === 'ArrowRight') { t = Math.min(DUR, B(beatAt(t)+1)); show(); }
    if (e.code === 'ArrowLeft') { t = Math.max(0, B(beatAt(t)-1)); show(); }
    if (/^Digit\d$/.test(e.code)) { t = DUR * (+e.code.slice(5)) / 10; show(); }
  });
  const loop = now => { if (playing) { t += (now - last) / 1000; if (t > DUR) t = 0; show(); } last = now; requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  show();
}
