// SvgDraw: beat-timed vector tracing using the normal Scene and compositor clock.
import { Scene } from './blocks/scene.js';
import { B, C, clamp, el } from './core.js';
import { GEOMETRY, vectorSvg, namespaceSvg } from './svg-assets.js';

const prepared = new WeakMap();
let instance = 0;

export function traceProgress(progress, lengths, mode = 'sequential') {
  if (!['sequential', 'together'].includes(mode)) throw Error('Invalid SvgDraw mode');
  if (!lengths.length || !lengths.every(n => Number.isFinite(n) && n > 0))
    throw Error('SvgDraw needs positive finite path lengths');
  const p = Math.max(0, Math.min(1, progress));
  const total = lengths.reduce((a, b) => a + b, 0);
  let passed = 0;
  return lengths.map(length => {
    const local = mode === 'together' ? p : Math.max(0, Math.min(1, (p * total - passed) / length));
    passed += length;
    return local;
  });
}

function positive(value, name) {
  if (!Number.isFinite(value) || value <= 0) throw Error(`SvgDraw ${name} must be positive`);
  return value;
}

function appearance(svg, width, height) {
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '100%');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  Object.assign(svg.style, { position: 'absolute', left: '0', top: '0', width: `${width}px`, height: `${height}px` });
}

export class SvgDraw extends Scene {
  static assetType = 'svg-draw';

  // Main boot awaits this hook before building any scene or resolving readiness.
  static async prepare(options) {
    if (prepared.has(options)) return;
    if (Boolean(options.src) === Boolean(options.svg))
      throw Error('SvgDraw needs exactly one local src or inline svg string');
    let markup = options.svg;
    if (options.src) {
      const url = new URL(options.src, location.href);
      if (url.origin !== location.origin || !['http:', 'https:'].includes(url.protocol))
        throw Error('SvgDraw src must be a local same-origin SVG asset');
      const response = await fetch(url);
      if (!response.ok) throw Error(`Missing SvgDraw asset: ${options.src}`);
      markup = await response.text();
    }
    prepared.set(options, vectorSvg(markup));
  }

  build() {
    const o = this.o;
    const span = this.k1 - this.k0;
    this.delayBeats = o.delayBeats ?? 0;
    const drawBeats = positive(o.drawBeats ?? span * .65, 'drawBeats');
    const fillBeats = positive(o.fillBeats ?? span * .15, 'fillBeats');
    if (!Number.isFinite(this.delayBeats) || this.delayBeats < 0 ||
        this.delayBeats + drawBeats + (o.revealFill === false ? 0 : fillBeats) > span)
      throw Error('SvgDraw draw/fill timing must fit within the scene');
    this.drawStart = B(this.k0 + this.delayBeats);
    this.drawEnd = B(this.k0 + this.delayBeats + drawBeats);
    this.fillEnd = B(this.k0 + this.delayBeats + drawBeats + fillBeats);
    this.mode = o.mode ?? 'sequential';
    if (!['sequential', 'together'].includes(this.mode)) throw Error('Invalid SvgDraw mode');
    if (!['document', 'reverse'].includes(o.order ?? 'document')) throw Error('Invalid SvgDraw order');
    if (!['linear', 'smooth'].includes(o.easing ?? 'linear')) throw Error('Invalid SvgDraw easing');
    const width = positive(o.width ?? 1500, 'width');
    const height = positive(o.height ?? 800, 'height');
    const strokeWidth = positive(o.strokeWidth ?? 5, 'strokeWidth');
    const x = o.x ?? 960, y = o.y ?? 540;
    if (!Number.isFinite(x) || !Number.isFinite(y)) throw Error('Invalid SvgDraw position');
    const source = prepared.get(o);
    if (!source) throw Error('SvgDraw asset was not prepared by the project boot loader');
    this.wrapper = el('div', this.root, '', { position: 'absolute',
      left: `${x - width / 2}px`, top: `${y - height / 2}px`, width: `${width}px`, height: `${height}px` });
    this.wrapper.classList.add('svg-draw');
    const id = `svgdraw-${instance++}`;
    this.fillSvg = namespaceSvg(source.cloneNode(true), `${id}-fill`);
    this.traceSvg = namespaceSvg(source.cloneNode(true), `${id}-trace`);
    for (const svg of [this.fillSvg, this.traceSvg]) {
      appearance(svg, width, height);
      this.wrapper.appendChild(svg);
    }
    const shapes = [...this.traceSvg.querySelectorAll(GEOMETRY)].filter(node => !node.closest('defs'));
    if ((o.order ?? 'document') === 'reverse') shapes.reverse();
    this.paths = shapes.map(node => {
      const length = node.getTotalLength();
      positive(length, 'geometry length');
      // Ancestor paint styles must not leave the trace invisible or filled.
      for (let parent = node.parentElement; parent && parent !== this.wrapper; parent = parent.parentElement)
        parent.removeAttribute('opacity');
      node.setAttribute('fill', 'none');
      node.setAttribute('stroke', C[o.stroke] || o.stroke || C.accent);
      node.setAttribute('stroke-width', String(strokeWidth));
      node.setAttribute('stroke-opacity', '1');
      node.setAttribute('stroke-linecap', o.linecap ?? 'round');
      node.setAttribute('stroke-linejoin', 'round');
      node.setAttribute('stroke-dasharray', `${length} ${length}`);
      node.removeAttribute('pathLength');
      return { node, length };
    });
    if (!this.paths.length) throw Error('SvgDraw has no visible drawable paths');
    if (o.ground) this.f.ground(this.t0, this.t1, C[o.ground] || o.ground);
    // No automatic sounds or canvas effects; the regular spec cue system applies.
    this.update(this.t0);
  }

  update(t) {
    let progress = clamp((t - this.drawStart) / (this.drawEnd - this.drawStart));
    if (this.o.easing === 'smooth') progress = progress * progress * (3 - 2 * progress);
    const values = traceProgress(progress, this.paths.map(path => path.length), this.mode);
    this.paths.forEach(({ node, length }, i) => {
      node.setAttribute('stroke-dashoffset', String(length * (1 - values[i])));
      node.style.opacity = values[i] === 0 ? '0' : '1';
    });
    const fill = this.o.revealFill === false ? 0 : clamp((t - this.drawEnd) / (this.fillEnd - this.drawEnd));
    this.fillSvg.style.opacity = String(fill);
    this.traceSvg.style.opacity = String(1 - fill);
    this.wrapper.dataset.progress = String(progress);
    this.wrapper.dataset.fill = String(fill);
  }

  cam() { return { x: 0, y: 0, s: 1, r: 0 }; }
}
