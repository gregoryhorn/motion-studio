import { clamp, lerp } from './math.js';

const hex = h => h[0] === '#' ? [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)) : h.match(/[\d.]+/g).slice(0, 3).map(Number);
export function mixc(a, b, u) {
  const A = hex(a), Bc = hex(b);
  return '#' + A.map((v, i) => Math.round(lerp(v, Bc[i], clamp(u))).toString(16).padStart(2, '0')).join('');
}
export const rgba = (h, a) => `rgba(${hex(h).join(',')},${a})`;
