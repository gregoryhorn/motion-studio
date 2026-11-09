// Pure capture timing. Kept in step with shutter_window/sample_times in the adapter.
export function cutsFor(cuts, duration) {
  if (!Number.isFinite(duration) || duration <= 0 || !Array.isArray(cuts) ||
      cuts.some((t,i) => !Number.isFinite(t) || t <= 0 || t >= duration || (i && t <= cuts[i-1])))
    throw Error('Cuts must be unique ascending interior seconds');
  return cuts;
}
export function previousFloat(x) {
  if (x === 0) return -Number.MIN_VALUE;
  const a = new DataView(new ArrayBuffer(8));
  a.setFloat64(0,x);
  a.setBigUint64(0,a.getBigUint64(0)+(x>0?-1n:1n));
  return a.getFloat64(0);
}
export function shutterWindow(t,fps,cuts,shutter,duration) {
  cutsFor(cuts,duration);
  if (!Number.isFinite(t) || t<0 || t>=duration || !Number.isFinite(fps) || fps<=0 ||
      !Number.isFinite(shutter) || shutter<0 || shutter>8) throw Error('Invalid exposure');
  const left = cuts.filter(c=>c<=t).at(-1) ?? 0;
  const right = cuts.find(c=>c>t) ?? duration;
  const length = 0.5*shutter/fps;
  let a=t,b=Math.min(t+length,right);
  if (b<t+length) a=Math.max(left,b-length);
  if (b===right) b=Math.max(t,previousFloat(right));
  return {a:Math.min(a,b),b,left,right};
}
export function sampleTimes(t,window,requested,cap) {
  if (!Number.isInteger(requested) || requested<1 || requested>64 ||
      !Number.isInteger(cap) || cap<1 || cap>64) throw Error('Invalid subframe samples');
  const n=window.a===window.b?1:Math.min(requested,cap);
  return Array.from({length:n},(_,j)=>n===1?t:Math.min(window.b,window.a+(window.b-window.a)*j/(n-1)));
}
