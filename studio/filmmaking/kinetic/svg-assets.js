// Safe vector-only SVG intake for draw-on scenes. No scripts, fonts or external assets.
const NS = 'http://www.w3.org/2000/svg';
const TAGS = new Set(['svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line',
  'polyline', 'polygon', 'defs', 'linearGradient', 'radialGradient', 'stop', 'title', 'desc']);
const ATTRS = new Set(['id', 'viewBox', 'preserveAspectRatio', 'width', 'height',
  'x', 'y', 'x1', 'x2', 'y1', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'd', 'points',
  'transform', 'fill', 'fill-rule', 'fill-opacity', 'stroke', 'stroke-width',
  'stroke-opacity', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit', 'stroke-dasharray', 'stroke-dashoffset',
  'opacity', 'vector-effect', 'gradientUnits', 'gradientTransform', 'spreadMethod',
  'offset', 'stop-color', 'stop-opacity', 'fx', 'fy', 'fr']);
const STYLE_ATTRS = new Set(['fill', 'fill-rule', 'fill-opacity', 'stroke',
  'stroke-width', 'stroke-opacity', 'stroke-linecap', 'stroke-linejoin',
  'stroke-miterlimit', 'stroke-dasharray', 'stroke-dashoffset', 'opacity', 'stop-color', 'stop-opacity']);
export const GEOMETRY = 'path,rect,circle,ellipse,line,polyline,polygon';

function safeValue(value) {
  // Only local paint-server references are allowed. Reject URL escapes/control chars.
  const clean = value.replace(/url\(\s*['"]?#[A-Za-z_][\w:.-]*['"]?\s*\)/gi, '');
  return !/url\s*\(|javascript:|data:|@import|[\\\u0000-\u001f]/i.test(clean);
}

export function vectorSvg(markup) {
  if (typeof markup !== 'string' || markup.length > 2_000_000)
    throw Error('SvgDraw requires SVG markup smaller than 2 MB');
  if (/<!DOCTYPE|<!ENTITY/i.test(markup)) throw Error('SVG declarations/entities are not supported');
  const doc = new DOMParser().parseFromString(markup, 'image/svg+xml');
  const root = doc.documentElement;
  if (root.localName !== 'svg' || doc.querySelector('parsererror')) throw Error('Invalid SVG document');
  const nodes = [root, ...root.querySelectorAll('*')];
  if (nodes.length > 5000) throw Error('SVG is too complex: maximum 5000 elements');
  for (const node of nodes) {
    if (node.namespaceURI !== NS || !TAGS.has(node.localName))
      throw Error(`Unsupported SVG element: ${node.localName}. Convert text/use/CSS to plain vector paths first.`);
    if (node.hasAttribute('style')) {
      for (const name of [...node.style]) {
        if (!STYLE_ATTRS.has(name)) throw Error(`Unsupported SVG style: ${name}`);
        const value = node.style.getPropertyValue(name);
        if (!safeValue(value)) throw Error('External or active SVG styling is not supported');
        node.setAttribute(name, value);
      }
      node.removeAttribute('style');
    }
    for (const attribute of [...node.attributes]) {
      if (attribute.name === 'xmlns') continue;
      if (/^on/i.test(attribute.name) || !safeValue(attribute.value))
        throw Error('Active or external SVG content is not supported');
      if (!ATTRS.has(attribute.name)) node.removeAttribute(attribute.name);
    }
  }
  if (!root.hasAttribute('viewBox')) {
    const width = Number(root.getAttribute('width'));
    const height = Number(root.getAttribute('height'));
    if (!(width > 0 && height > 0)) throw Error('SVG needs a valid viewBox or numeric width/height');
    root.setAttribute('viewBox', `0 0 ${width} ${height}`);
  }
  const box = root.getAttribute('viewBox').trim().split(/[\s,]+/).map(Number);
  if (box.length !== 4 || !box.every(Number.isFinite) || box[2] <= 0 || box[3] <= 0)
    throw Error('SVG viewBox must have positive width and height');
  if (!root.querySelector(GEOMETRY)) throw Error('SVG has no drawable vector geometry');
  return root;
}

export function namespaceSvg(svg, prefix) {
  const ids = new Map();
  for (const node of [svg, ...svg.querySelectorAll('[id]')]) {
    if (node.id) {
      if (ids.has(node.id)) throw Error('SVG has duplicate IDs');
      ids.set(node.id, `${prefix}-${node.id}`);
    }
  }
  for (const node of [svg, ...svg.querySelectorAll('*')]) {
    if (node.id) node.id = ids.get(node.id);
    for (const attribute of [...node.attributes]) {
      if (/url\(/i.test(attribute.value)) node.setAttribute(attribute.name,
        attribute.value.replace(/url\(\s*['"]?#([\w:.-]+)['"]?\s*\)/gi, (_, id) => {
          if (!ids.has(id)) throw Error(`Unresolved SVG paint reference: ${id}`);
          return `url(#${ids.get(id)})`;
        }));
    }
  }
  return svg;
}
