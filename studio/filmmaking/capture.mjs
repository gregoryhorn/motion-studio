// Owned local capture. Node >=22 and an explicitly discovered Chromium executable.
// No npm dependencies, downloads, external requests or persistent server.
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile, mkdir, writeFile, realpath, readdir} from 'node:fs/promises';
import path from 'node:path';
import {once} from 'node:events';
import {pathToFileURL} from 'node:url';
import {cutsFor,shutterWindow,sampleTimes} from './timing.mjs';

// These are per-operation liveness bounds, not a render-duration limit. The
// WorkerContext caller owns the attempt deadline; long films may issue any
// number of commands. Match the existing 15s DevTools/film-readiness contract.
export class CaptureLifecycle {
  constructor(chrome, server, {timeoutMs=15000, shutdownMs=2000, WebSocketImpl=globalThis.WebSocket}={}) {
    this.chrome=chrome; this.server=server; this.timeoutMs=timeoutMs;
    this.shutdownMs=shutdownMs; this.WebSocketImpl=WebSocketImpl;
    this.pending=new Map(); this.seq=0; this.failure=null; this.waiters=new Set();
    this.stderrTail=''; this.gpuActivationLines=[]; this.logRemainder='';
    this.onStderr=b=>{
      const text=b.toString();this.stderrTail=(this.stderrTail+text).slice(-16384);
      const lines=(this.logRemainder+text).split('\n');
      this.logRemainder=lines.pop().slice(-4096);
      for(const line of lines)if(line.includes('Activated seccomp-bpf sandbox for process type: gpu-process.'))
        this.gpuActivationLines.push(line.slice(-4096));
      this.gpuActivationLines=this.gpuActivationLines.slice(-16);
    };
    chrome.stderr.on('data',this.onStderr);
    this.exited=chrome.exitCode!==null || chrome.signalCode!==null;
    this.onError=e=>{if(chrome.pid===undefined)this.exited=true; this.fail(Error('Chromium process error: '+e.message));};
    this.onExit=(code,signal)=>{this.exited=true; this.fail(this.diagnostic(`Chromium exited (${code ?? signal})`));};
    chrome.on('error',this.onError); chrome.on('exit',this.onExit);
  }
  diagnostic(message) {
    return Error(message+(this.stderrTail?'\n'+this.stderrTail.slice(-1800):''));
  }
  fail(error) {
    if(this.failure)return;
    this.failure=error;
    for(const reject of [...this.waiters])reject(error);
    for(const p of [...this.pending.values()])p.reject(error);
  }
  wait(register,label,timeoutMs=this.timeoutMs) {
    return new Promise((resolve,reject)=>{
      let dispose=()=>{}, settled=false;
      const finish=(fn,value)=>{
        if(settled)return;settled=true;
        clearTimeout(timer);this.waiters.delete(fail);dispose();fn(value);
      };
      const fail=e=>finish(reject,e);
      const timer=setTimeout(()=>fail(Error(`${label} timed out after ${timeoutMs}ms`)),timeoutMs);
      this.waiters.add(fail);
      if(this.failure){fail(this.failure);return;}
      dispose=register(value=>finish(resolve,value),fail) || (()=>{});
    });
  }
  async endpoint() {
    let output='';
    return this.wait(resolve=>{
      const data=b=>{
        output=(output+b.toString()).slice(-16384);
        const match=output.match(/DevTools listening on (ws:\/\/\S+)/);
        if(match)resolve(match[1]);
      };
      this.chrome.stderr.on('data',data);
      return ()=>this.chrome.stderr.off('data',data);
    },'Chromium DevTools');
  }
  async connect(endpoint,onEvent=()=>{}) {
    if(this.failure)throw this.failure;
    const ws=this.ws=new this.WebSocketImpl(endpoint);
    ws.addEventListener('close',()=>this.fail(this.diagnostic('Chromium disconnected')));
    ws.addEventListener('error',()=>this.fail(Error('Chromium WebSocket error')));
    ws.addEventListener('message',event=>{
      try {
        const m=JSON.parse(event.data);
        if(m.id){const p=this.pending.get(m.id);if(p)m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
        else onEvent(m);
      } catch(e){this.fail(e);}
    });
    await this.wait(resolve=>{
      const open=()=>resolve();ws.addEventListener('open',open);
      return ()=>ws.removeEventListener('open',open);
    },'Chromium WebSocket connection');
  }
  send(method,params={},sessionId,timeoutMs=this.timeoutMs) {
    if(this.failure)return Promise.reject(this.failure);
    return new Promise((resolve,reject)=>{
      const id=++this.seq;
      const finish=(fn,value)=>{
        if(!this.pending.has(id))return;
        this.pending.delete(id);clearTimeout(timer);fn(value);
      };
      const timer=setTimeout(()=>{
        // A timed-out command invalidates the session: later commands must not
        // race an unknown in-flight browser mutation.
        this.fail(this.diagnostic(`Chromium CDP ${method} timed out after ${timeoutMs}ms`));
      },timeoutMs);
      this.pending.set(id,{resolve:v=>finish(resolve,v),reject:e=>finish(reject,e)});
      try {this.ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));}
      catch(e){this.fail(e);}
    });
  }
  cleanup() {
    if(this.cleaning)return this.cleaning;
    this.cleaning=this.shutdown();return this.cleaning;
  }
  async shutdown() {
    this.fail(Error('Capture cancelled'));
    try {this.ws?.close();} catch {}
    this.server.close();this.server.closeAllConnections?.();
    if(!this.exited && this.chrome.pid!==undefined) {
      const waitExit=ms=>new Promise(resolve=>{
        const done=()=>{clearTimeout(timer);this.chrome.off('exit',done);resolve();};
        const timer=setTimeout(done,ms);this.chrome.once('exit',done);
        if(this.exited)done();
      });
      this.chrome.kill('SIGTERM');await waitExit(this.shutdownMs);
      if(!this.exited){this.chrome.kill('SIGKILL');await waitExit(this.shutdownMs);}
      if(!this.exited)throw Error('Owned Chromium did not exit after SIGKILL');
    }
    // Keep the error listener for a failed spawn's deferred error event, even
    // if cancellation happened before that event was delivered.
    this.chrome.off('exit',this.onExit);
    this.chrome.stderr.off('data',this.onStderr);
  }
}

export function ownedChromeEnvironment() {
  // Chromium's desktop scope/portal clients use the session bus. Unsetting it
  // can autolaunch/recover the real desktop bus instead. Explicit unix:path has
  // no fallback address here; /dev/null is a character device, never a listening
  // Unix socket (connect fails). '/' is literal-safe in D-Bus address values.
  // Only this owned child's environment changes; no desktop configuration or
  // parent environment mutation, and no sandbox/isolation flags are needed.
  return {...process.env,DBUS_SESSION_BUS_ADDRESS:'unix:path=/dev/null'};
}

export function spawnOwnedChrome(chrome,args) {
  return spawn(chrome,args,{env:ownedChromeEnvironment(),stdio:['ignore','ignore','pipe']});
}

export async function attachOwnedInitialPage(send) {
  // Call only on the DevTools endpoint of the freshly spawned owned browser
  // with its attempt profile and explicit about:blank launch URL, never a shared
  // browser. Reuse its sole initial page rather than allocating another page.
  const {targetInfos}=await send('Target.getTargets');
  const pages=targetInfos.filter(t=>t.type==='page');
  const page=pages[0];
  if(pages.length!==1 || !page.targetId || page.url!=='about:blank' ||
     page.attached!==false || page.openerId)
    throw Error('Expected exactly one unattached initial owned about:blank page');
  return send('Target.attachToTarget',{targetId:page.targetId,flatten:true});
}

export const GPU_ROUTE='chromium-native-nvidia-linux-v1';
export const QUALIFIED_CHROME_VERSION='153.0.8010.52';
const gpuError=message=>Error(`GPU qualification refused (${GPU_ROUTE}; Linux NVIDIA; qualified Chrome ${QUALIFIED_CHROME_VERSION} only): ${message}`);
export function validateGpuConfig(cfg,platform=process.platform) {
  if(platform!=='linux' || !cfg || typeof cfg!=='object' || Array.isArray(cfg) || cfg.gpu_route!==GPU_ROUTE ||
     !cfg.gpu_device || typeof cfg.gpu_device!=='object' || Array.isArray(cfg.gpu_device) ||
     cfg.gpu_device.vendor_id!==4318 ||
     typeof cfg.gpu_device.driver_version!=='string' || !/^\d+(?:\.\d+){1,3}$/.test(cfg.gpu_device.driver_version) ||
     (cfg.gpu_device.device_id!==undefined && (!Number.isInteger(cfg.gpu_device.device_id) || cfg.gpu_device.device_id<=0 || cfg.gpu_device.device_id>65535)) ||
     cfg.chrome_version!==`Google Chrome ${QUALIFIED_CHROME_VERSION}`)
    throw gpuError('missing, malformed or unqualified provider configuration');
  return cfg;
}
export function parseProcStatus(text) {
  if(typeof text!=='string')throw gpuError('unreadable procfs status');
  const result={};
  for(const key of ['Pid','Tgid','NoNewPrivs','Seccomp','Seccomp_filters']) {
    const m=text.match(new RegExp(`^${key}:\\s*(\\d+)\\s*$`,'m'));
    if(!m)throw gpuError(`missing procfs ${key}`);
    result[key]=Number(m[1]);
    if(!Number.isSafeInteger(result[key]))throw gpuError(`invalid procfs ${key}`);
  }
  return result;
}
export function procStartIdentity(stat,pid) {
  if(typeof stat!=='string' || !stat.startsWith(`${pid} (`))throw gpuError('mismatched procfs PID');
  const fields=stat.slice(stat.lastIndexOf(')')+2).trim().split(/\s+/);
  if(!/^\d+$/.test(fields[19]??'') || ['Z','X','x'].includes(fields[0]))throw gpuError('invalid or dead procfs identity');
  return fields[19];
}
const backend=s=>{
  const g=s.systemInfo.gpu,a=g.auxAttributes;
  return JSON.stringify([g.devices,a.glRenderer,a.glVendor,a.glVersion,a.glImplementationParts,a.displayType,g.featureStatus]);
};
export function validateGpuSnapshot(s,cfg,previous) {
  validateGpuConfig(cfg);
  const g=s?.systemInfo?.gpu,a=g?.auxAttributes;
  if(!a || a.sandboxed!==true || a.inProcessGpu!==false || a.processCrashCount!==0)
    throw gpuError('GPU must be sandboxed, out-of-process and never crashed');
  if(s.chrome_version!==`Chrome/${QUALIFIED_CHROME_VERSION}`)
    throw gpuError('observed browser version does not match qualification pin');
  if(!Array.isArray(g.devices) || g.devices.length!==1 || g.devices[0].vendorId!==4318 ||
     (g.devices[0].driverVersion!==undefined && g.devices[0].driverVersion!=='' && g.devices[0].driverVersion!==cfg.gpu_device.driver_version) ||
     (cfg.gpu_device.device_id!==undefined && g.devices[0].deviceId!==cfg.gpu_device.device_id))
    throw gpuError('observed NVIDIA device/driver differs from provider');
  if(typeof a.glRenderer!=='string' || !/^ANGLE \(NVIDIA /i.test(a.glRenderer) ||
     !/NVIDIA/i.test(a.glVendor??'') || a.glImplementationParts!=='(gl=egl-angle,angle=opengl)' ||
     !/ANGLE/.test(a.glVersion??'') || /swiftshader|software|llvmpipe|softpipe|disabled/i.test([a.glRenderer,a.glVendor,a.glVersion].join(' ')) ||
     !['opengl','webgl','gpu_compositing'].every(k=>/^enabled(?:_on)?$/.test(g.featureStatus?.[k]??'')))
    throw gpuError('native NVIDIA ANGLE OpenGL hardware backend required');
  const rendererDriver=a.glRenderer.match(/NVIDIA (\d+(?:\.\d+){1,3})\)$/)?.[1];
  if(rendererDriver!==cfg.gpu_device.driver_version)throw gpuError('ANGLE driver differs from provider');
  const identity=(snapshot,type)=>{
    const records=snapshot?.records?.filter(r=>r.processInfo?.type?.toLowerCase()===type);
    if(records?.length!==1)throw gpuError('missing or ambiguous process records');
    const record=records[0],pid=record.processInfo.id;
    return {...record,pid,start_time:procStartIdentity(record.stat,pid)};
  };
  const b=identity(s,'browser'),p=identity(s,'gpu');
  const infos=s.processes?.processInfo?.filter(info=>['browser','gpu'].includes(info.type?.toLowerCase()));
  if(infos?.length!==2 || !infos.some(info=>info.type.toLowerCase()==='browser'&&info.id===b.pid) ||
     !infos.some(info=>info.type.toLowerCase()==='gpu'&&info.id===p.pid))throw gpuError('CDP/procfs records do not match');
  for(const record of [b,p]) {
    if(!record || !Number.isSafeInteger(record.pid) || record.pid<=0 || !/^\d+$/.test(record.start_time??''))throw gpuError('missing process identity');
    const v=parseProcStatus(record.status);
    if(v.Pid!==record.pid || v.Tgid!==record.pid)throw gpuError('process identity/status mismatch');
  }
  if(b.pid===p.pid)throw gpuError('GPU is not a separate process');
  const baseline=parseProcStatus(b.status).Seccomp_filters;
  const check=(text,tid)=>{
    const v=parseProcStatus(text);
    if(v.Pid!==tid || v.Tgid!==p.pid || v.Seccomp!==2 || v.NoNewPrivs!==1 || v.Seccomp_filters<=baseline)
      throw gpuError('GPU main/thread lacks distinct seccomp policy or NoNewPrivs');
  };
  check(p.status,p.pid);
  if(!Array.isArray(p.threads) || !p.threads.length || !p.threads.some(t=>t.tid===p.pid) || new Set(p.threads.map(t=>t.tid)).size!==p.threads.length)
    throw gpuError('missing or duplicate GPU thread observations');
  for(const t of p.threads) {if(!Number.isSafeInteger(t.tid)||t.tid<=0)throw gpuError('invalid thread ID');check(t.status,t.tid);}
  const logPattern=new RegExp(`^\\[${p.pid}:\\d+:[^\\]\\n]+:VERBOSE1:sandbox/policy/linux/sandbox_linux\\.cc:\\d+\\] Activated seccomp-bpf sandbox for process type: gpu-process\\.$`,'m');
  if(typeof s.activation_log!=='string' || !logPattern.test(s.activation_log))throw gpuError('missing positive GPU policy activation log for observed PID');
  if(previous && (p.pid!==identity(previous,'gpu').pid || p.start_time!==identity(previous,'gpu').start_time ||
     b.pid!==identity(previous,'browser').pid || b.start_time!==identity(previous,'browser').start_time || backend(s)!==backend(previous)))
    throw gpuError('GPU/browser restarted or backend changed');
  return s;
}

// IO seams are for deterministic tests; capture() always uses the real defaults.
export async function observeGpu({send,browserPid,activationLog,stage,read=readFile,list=readdir}) {
  const systemInfo=await send('SystemInfo.getInfo');
  const processes=await send('SystemInfo.getProcessInfo');
  const version=await send('Browser.getVersion');
  const all=processes.processInfo;
  const browsers=all.filter(p=>p.type.toLowerCase()==='browser');
  const gpus=all.filter(p=>p.type.toLowerCase()==='gpu');
  if(browsers.length!==1 || browsers[0].id!==browserPid)throw gpuError('CDP browser differs from owned process');
  const aux=systemInfo.gpu?.auxAttributes;
  if(aux && (aux.sandboxed===false || aux.inProcessGpu===true || (aux.processCrashCount!==undefined && aux.processCrashCount!==0)))
    throw gpuError('positive sandbox/in-process/crash failure during startup');
  if(gpus.length===0){const e=gpuError('GPU startup not ready');e.code='GPU_STARTUP_NOT_READY';throw e;}
  if(gpus.length!==1 || !Number.isSafeInteger(gpus[0].id) || gpus[0].id<=0)throw gpuError('ambiguous GPU process');
  const record=async pid=>{
    const root=`/proc/${pid}`;
    const stat=await read(root+'/stat','utf8');
    const start_time=procStartIdentity(stat,pid);
    const status=await read(root+'/status','utf8');
    return {pid,start_time,status,stat};
  };
  try {
    const browser=await record(browserPid),gpu_process=await record(gpus[0].id);
    const root=`/proc/${gpu_process.pid}`;
    const tids=(await list(root+'/task')).sort();
    gpu_process.threads=[];
    for(const tid of tids) {
      if(!/^\d+$/.test(tid))throw gpuError('invalid procfs task');
      const base=root+'/task/'+tid;
      const stat=await read(base+'/stat','utf8');
      const start_time=procStartIdentity(stat,Number(tid));
      const status=await read(base+'/status','utf8');
      if(procStartIdentity(await read(base+'/stat','utf8'),Number(tid))!==start_time)throw gpuError('GPU thread identity changed');
      gpu_process.threads.push({tid:Number(tid),start_time,status});
    }
    if(JSON.stringify(tids)!==JSON.stringify((await list(root+'/task')).sort()))throw gpuError('GPU threads changed during observation');
    for(const t of gpu_process.threads)if(procStartIdentity(await read(`${root}/task/${t.tid}/stat`,'utf8'),t.tid)!==t.start_time)throw gpuError('GPU thread disappeared or changed identity');
    for(const r of [browser,gpu_process])if(procStartIdentity(await read(`/proc/${r.pid}/stat`,'utf8'),r.pid)!==r.start_time)throw gpuError('process identity changed during observation');
    const verify=await send('SystemInfo.getProcessInfo');
    const current=verify.processInfo.filter(p=>['gpu','browser'].includes(p.type.toLowerCase()));
    if(current.length!==2 || !current.some(p=>p.type.toLowerCase()==='gpu'&&p.id===gpu_process.pid) || !current.some(p=>p.type.toLowerCase()==='browser'&&p.id===browserPid))throw gpuError('process disappeared or restarted during observation');
    const records=[{...browser,processInfo:browsers[0]},{...gpu_process,processInfo:gpus[0]}];
    return {stage,chrome_version:version.product,browser_version:version,systemInfo,processes,records,activation_log:activationLog()};
  } catch(e) {throw gpuError('procfs/process observation failed: '+e.message);}
}
export async function qualifyGpu(options,cfg,previous,{startup=false,timeoutMs=15000,now=Date.now,pause=ms=>new Promise(r=>setTimeout(r,ms)),observe=observeGpu}={}) {
  const deadline=now()+timeoutMs;
  for(let attempt=0;;attempt++) {
    try {return validateGpuSnapshot(await observe(options),cfg,previous);}
    catch(e) {
      // Never retry reported sandbox/backend/kernel failures, missing evidence,
      // disappeared processes or restarts. Only an as-yet absent startup GPU.
      if(!startup || e.code!=='GPU_STARTUP_NOT_READY' || attempt>=59 || now()>=deadline)throw e;
      await pause(Math.min(50,Math.max(1,deadline-now())));
    }
  }
}

export async function capture(configPath) {
const cfg = JSON.parse(await readFile(configPath, 'utf8'));
validateGpuConfig(cfg);
// Keep the frozen JSON exact; floating point is only a browser timing value.
cfg.fps = cfg.rate?.num / cfg.rate?.den;
if(![cfg.width,cfg.height,cfg.duration_frames,cfg.start,cfg.end,cfg.samples].every(Number.isInteger) ||
   cfg.width<=0 || cfg.height<=0 || !Number.isFinite(cfg.fps) || cfg.fps<23 || cfg.fps>60 ||
   !cfg.rate || !Number.isInteger(cfg.rate.num) || !Number.isInteger(cfg.rate.den) || cfg.rate.den<=0 ||
   cfg.fps!==cfg.rate.num/cfg.rate.den || cfg.start<0 || cfg.start>=cfg.end || cfg.end>cfg.duration_frames || cfg.samples<1 || cfg.samples>64)
  throw Error('Invalid frozen capture configuration');
const duration = cfg.duration_frames / cfg.fps;
const root = await realpath(cfg.root);
const allowed = new Set(cfg.members);
const errors = [];
const server = createServer(async (req,res) => {
  try {
    const name = decodeURIComponent(new URL(req.url,'http://local').pathname).slice(1);
    if (!allowed.has(name)) {res.writeHead(404); return res.end();}
    const file = await realpath(path.join(root,name));
    if (!file.startsWith(root+path.sep)) throw Error('Escaped source closure');
    const mime = {'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.json':'application/json','.png':'image/png','.svg':'image/svg+xml','.ttf':'font/ttf','.otf':'font/otf','.woff2':'font/woff2','.mp4':'video/mp4','.jpg':'image/jpeg','.jpeg':'image/jpeg','.css':'text/css'}[path.extname(file).toLowerCase()] || 'application/octet-stream';
    res.writeHead(200,{'Content-Type':mime, 'Content-Security-Policy':"default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-src 'none'; worker-src 'none'"});
    res.end(await readFile(file));
  } catch(e) {res.writeHead(400); res.end(); errors.push(String(e));}
});
await mkdir(cfg.profile,{recursive:true});
server.listen(0,'127.0.0.1'); await once(server,'listening');
const origin = `http://127.0.0.1:${server.address().port}`;
let chrome;
try {
  chrome = spawnOwnedChrome(cfg.chrome,['--headless=new','--enable-gpu','--disable-background-networking','--no-first-run','--no-default-browser-check','--disable-component-extensions-with-background-pages','--disable-features=WebUIOmniboxPopup,WebUIOmniboxAimPopup,SpareRendererForSitePerProcess','--enable-logging=stderr','--vmodule=sandbox_linux=1','--remote-debugging-port=0',`--user-data-dir=${cfg.profile}`,'about:blank']);
} catch(e) {server.close();server.closeAllConnections?.();throw e;}
const lifecycle=new CaptureLifecycle(chrome,server);
const send=(...args)=>lifecycle.send(...args);
const onSignal=()=>{lifecycle.cleanup().then(()=>process.exit(130),e=>{console.error(e);process.exit(1);});};
for(const s of ['SIGTERM','SIGINT'])process.on(s,onSignal);
try {
  const endpoint=await lifecycle.endpoint();
  await lifecycle.connect(endpoint,m=>{
    if(m.method==='Runtime.exceptionThrown') errors.push(JSON.stringify(m.params.exceptionDetails));
    if(m.method==='Fetch.requestPaused') {
      const u=new URL(m.params.request.url);
      const okay=u.origin===origin || ['data:','blob:','about:'].includes(u.protocol);
      if(!okay)errors.push('External request refused: '+u.origin);
      send(okay?'Fetch.continueRequest':'Fetch.failRequest',{requestId:m.params.requestId,...(okay?{}:{errorReason:'BlockedByClient'})},m.sessionId).catch(e=>errors.push(String(e)));
    }
  });
  const gpuOptions={send,browserPid:chrome.pid,activationLog:()=>lifecycle.gpuActivationLines.join('\n')};
  const qualify=(stage,previous,startup=false)=>lifecycle.wait((resolve,reject)=>{
    qualifyGpu({...gpuOptions,stage},cfg,previous,{startup,timeoutMs:lifecycle.timeoutMs}).then(resolve,reject);
  },'GPU qualification');
  // No authored navigation occurs until the fresh owned browser is attested.
  const before=await qualify('before-authored-navigation',undefined,true);
  const {sessionId}=await attachOwnedInitialPage(send);
  const cmd=(m,p={})=>send(m,p,sessionId);
  const evaluate=async expression=>{
    const r=await cmd('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails)); return r.result.value;
  };
  await cmd('Runtime.enable'); await cmd('Page.enable');
  await cmd('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
  await cmd('Emulation.setDeviceMetricsOverride',{width:cfg.width,height:cfg.height,deviceScaleFactor:1,mobile:false});
  const graphics_probe=await evaluate(`(()=>{
    const c=document.createElement('canvas');c.width=1;c.height=1;
    const gl=c.getContext('webgl2')||c.getContext('webgl');
    if(!gl)throw Error('GPU qualification requires WebGL');
    gl.clearColor(0,1,0,1);gl.clear(gl.COLOR_BUFFER_BIT);gl.finish();
    const pixel=new Uint8Array(4);gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
    return {version:gl.getParameter(gl.VERSION),renderer:gl.getParameter(gl.RENDERER),pixel:[...pixel],error:gl.getError()};
  })()`);
  if(graphics_probe.error!==0 || JSON.stringify(graphics_probe.pixel)!=='[0,255,0,255]')throw gpuError('graphics probe failed');
  const after_graphics=await qualify('after-graphics-before-authored-navigation',before);
  await cmd('Page.navigate',{url:origin+'/'+cfg.entry+'?render=1'});
  const readyUntil=Date.now()+15000;
  while(!await evaluate('!!(window.__film && typeof window.__seek === "function")')){
    if(errors.length || Date.now()>readyUntil)throw Error('Missing seekable film contract: '+errors.join('\n'));
    await new Promise(r=>setTimeout(r,25));
  }
  await evaluate('(async()=>{await window.__ready;await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));return true})()');
  const film=await evaluate('window.__film');
  if(!Number.isFinite(film.duration)||film.fps!==cfg.fps || film.width!==cfg.width || film.height!==cfg.height || Math.abs(film.duration-duration)>1e-7)throw Error('Authored canvas/rate/duration differs from frozen scene');
  film.cuts=cutsFor(film.cuts??[],duration);
  let cues=await evaluate('window.__film.cues||[]');
  if(!Array.isArray(cues)||cues.some(c=>!Number.isFinite(c.t??c.time)||(c.t??c.time)<0||(c.t??c.time)>=duration||typeof(c.name??c.event)!=='string'))throw Error('Invalid sound cue list');
  cues=cues.map(c=>({...c,t:c.t??c.time,name:c.name??c.event}));
  const exposures=[];
  await mkdir(cfg.frames,{recursive:true});
  for(let k=cfg.start;k<cfg.end;k++){
    const t=k/cfg.fps, shutter=await evaluate(`window.__shutter?window.__shutter(${t}):1`);
    if(!Number.isFinite(shutter)||shutter<0||shutter>8)throw Error('Invalid shutter');
    const window=shutterWindow(t,cfg.fps,film.cuts,shutter,duration);
    const requested=await evaluate(`window.__samples?window.__samples(${window.a},${window.b-window.a}):1`);
    const times=sampleTimes(t,window,requested,cfg.samples),n=times.length;
    for(let j=0;j<n;j++){
      const ts=times[j];
      if(ts<window.left || ts>=window.right)throw Error('Sample escaped shot');
      await evaluate(`(async()=>{window.__frameT=${t};await window.__seek(${ts});await new Promise(r=>requestAnimationFrame(r));return true})()`);
      const {data}=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,clip:{x:0,y:0,width:cfg.width,height:cfg.height,scale:1}});
      await writeFile(path.join(cfg.frames,`${k-cfg.start}-${j}.png`),Buffer.from(data,'base64'));
    }
    const exposure={frame:k,t,shutter,...window,samples:n,times};
    exposures.push(exposure);
    await writeFile(path.join(cfg.frames,`${k-cfg.start}.json`),JSON.stringify(exposure));
    if(errors.length)throw Error(errors.join('\n'));
  }
  const after=await qualify('after-capture',before);
  const gpu_qualification={route:GPU_ROUTE,status:'passed',before,after,after_graphics,graphics_probe};
  await writeFile(cfg.report,JSON.stringify({film,cues,frames:cfg.end-cfg.start,sample_cap:cfg.samples,exposures,errors,gpu_qualification}));
} finally {
  try {await lifecycle.cleanup();}
  finally {for(const s of ['SIGTERM','SIGINT'])process.off(s,onSignal);}
}
}
if(process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)
  await capture(process.argv[2]);
