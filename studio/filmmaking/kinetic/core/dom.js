export function el(tag, parent, cls, style) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (style) Object.assign(e.style, style);
  if (parent) parent.appendChild(e);
  return e;
}
export function vis(e, on) { const d = on ? '' : 'none'; if (e.style.display !== d) e.style.display = d; }
export function set(e, k, v) { if (e.style[k] !== v) e.style[k] = v; }
// centre an element on (x, y), then apply extra transforms
export const at = (x, y, extra = '') => `translate(${x}px,${y}px) translate(-50%,-50%) ${extra}`;
