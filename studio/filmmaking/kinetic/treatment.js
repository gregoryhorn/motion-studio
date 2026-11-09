// Presets affect implemented controls only; edit shot timing/copy for cadence/readability.
export const treatments = {
  kinetic: {camera:1, shake:1, flashes:1, effects:1, sfx:'all'},
  balanced: {camera:.65, shake:.45, flashes:.4, effects:.65, sfx:'sparse'},
  restrained: {camera:.15, shake:0, flashes:0, effects:.2, sfx:'manual'},
  custom: {camera:1, shake:1, flashes:1, effects:1, sfx:'manual'},
};
export function treatment(spec, scene={}) {
  const name=scene.treatment || spec.treatment || 'kinetic';
  if (!treatments[name]) throw Error('Unknown treatment: '+name);
  const out={...treatments[name], ...(spec.motion||{}), ...(scene.motion||{})};
  for (const k of ['camera','shake','flashes','effects']) if (!Number.isFinite(out[k]) || out[k]<0 || out[k]>1) throw Error('Motion '+k+' must be 0..1');
  if (!['none','manual','sparse','all'].includes(out.sfx)) throw Error('Invalid SFX density');
  return out;
}
