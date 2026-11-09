// Stable entry point for the existing Kinetic engine and authored films.
// Re-exports retain shared live state; core-source.txt preserves existing line counters.
export { W, H, FPS, BPM, BEATS, DUR, B, beatAt, configure } from './core/timing.js';
export { C, setPalette } from './core/palette.js';
export { clamp, lerp, E, tw, env, rng } from './core/math.js';
export { mixc, rgba } from './core/color.js';
export { el, vis, set, at } from './core/dom.js';
export { type, styleType, letters, extrude, slices, glitch, tumble } from './core/typography.js';
export { Caption, HUD } from './core/overlays.js';
export { FX, drawComet, drawBurst, drawSlash, drawDots,
  drawRays, drawRing, drawBokeh, drawStarburst } from './core/effects.js';
