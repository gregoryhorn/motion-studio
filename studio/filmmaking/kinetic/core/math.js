export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, u) => a + (b - a) * u;
export const E = {
  lin: u => u,
  inQuad: u => u * u,
  outQuad: u => 1 - (1 - u) * (1 - u),
  inCubic: u => u * u * u,
  outCubic: u => 1 - Math.pow(1 - u, 3),
  inOutCubic: u => u < .5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2,
  outQuint: u => 1 - Math.pow(1 - u, 5),
  inOutQuint: u => u < .5 ? 16 * u ** 5 : 1 - Math.pow(-2 * u + 2, 5) / 2,
  outExpo: u => u >= 1 ? 1 : 1 - Math.pow(2, -10 * u),
  inExpo: u => u <= 0 ? 0 : Math.pow(2, 10 * u - 10),
  inOutExpo: u => u <= 0 ? 0 : u >= 1 ? 1 : u < .5 ? Math.pow(2, 20 * u - 10) / 2 : (2 - Math.pow(2, -20 * u + 10)) / 2,
  outBack: (u, s = 1.70158) => 1 + (s + 1) * Math.pow(u - 1, 3) + s * Math.pow(u - 1, 2),
  outElastic: u => u <= 0 ? 0 : u >= 1 ? 1 : Math.pow(2, -10 * u) * Math.sin((u * 10 - .75) * (2 * Math.PI / 3)) + 1,
};
export const tw = (t, a, b, e = E.outCubic) => e(clamp((t - a) / (b - a)));
// 0 -> 1 -> 0 envelope: rise over [a, a+r], hold, fall over [b-f, b]
export const env = (t, a, b, r = .1, f = .1) => Math.min(tw(t, a, a + r, E.outCubic), 1 - tw(t, b - f, b, E.inCubic));

export function rng(seed) {
  let s = (seed * 2654435761) >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}
