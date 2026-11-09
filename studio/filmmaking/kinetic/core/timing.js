export const W = 1920, H = 1080;
export let FPS = 60, BPM = 120, BEATS = 64, DUR = BEATS * 60 / BPM;
let tempoMap = [[0,0]];
export const B = k => {
  if (!Number.isFinite(k)) throw Error('Beat must be finite');
  let i=0;
  while (i+1<tempoMap.length && k>=tempoMap[i+1][0]) i++;
  const [beat,sec]=tempoMap[i], next=tempoMap[i+1];
  return sec+(k-beat)*(next ? (next[1]-sec)/(next[0]-beat) : 60/BPM);
};
export const beatAt = sec => {
  let i=0; while(i+1<tempoMap.length && sec>=tempoMap[i+1][1]) i++;
  const [beat,t]=tempoMap[i], next=tempoMap[i+1];
  return beat+(sec-t)/(next ? (next[1]-t)/(next[0]-beat) : 60/BPM);
};
export function configure(o = {}) {
  BPM=o.bpm ?? 120; BEATS=o.beats ?? 64; FPS=o.fps ?? 60;
  if (![BPM,BEATS,FPS].every(x=>Number.isFinite(x)&&x>0)) throw Error('bpm/beats/fps must be positive finite numbers');
  tempoMap=o.tempoMap ? o.tempoMap.map(p=>[...p]) : [[0,0]];
  if (!tempoMap.length || tempoMap[0][0]!==0 || tempoMap[0][1]!==0) throw Error('tempoMap must start at [0,0]');
  tempoMap.forEach((p,i)=>{if(p.length!==2 || !p.every(Number.isFinite) || (i && (p[0]<=tempoMap[i-1][0] || p[1]<=tempoMap[i-1][1]))) throw Error('tempoMap anchors must strictly increase');});
  DUR=B(BEATS);
}
