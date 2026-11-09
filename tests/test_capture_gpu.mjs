import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm, readFile} from 'node:fs/promises';
import {EventEmitter} from 'node:events';
import {tmpdir} from 'node:os';
import path from 'node:path';
import * as capture from '../studio/filmmaking/capture.mjs';
const cfg={gpu_route:'chromium-native-nvidia-linux-v1',gpu_device:{vendor_id:4318,device_id:8708,driver_version:'595.99.02'},chrome_version:'Google Chrome 153.0.8010.52'};
const status=(pid,tgid,filters=1)=>`Pid:\t${pid}\nTgid:\t${tgid}\nNoNewPrivs:\t1\nSeccomp:\t2\nSeccomp_filters:\t${filters}\n`;
const stat=(pid,start='12')=>`${pid} (chrome (gpu)) S ${Array(18).fill('0').join(' ')} ${start} 0`;
function snapshot(){const s={stage:'before',chrome_version:'Chrome/153.0.8010.52',browser:{pid:100,start_time:'11',status:status(100,100,0)},gpu_process:{pid:200,start_time:'12',status:status(200,200),threads:[{tid:200,status:status(200,200)},{tid:201,status:status(201,200)}]},activation_log:'[200:200:1108/103423.842018:VERBOSE1:sandbox/policy/linux/sandbox_linux.cc:78] Activated seccomp-bpf sandbox for process type: gpu-process.',systemInfo:{gpu:{devices:[{vendorId:4318,deviceId:8708,driverVersion:'595.99.02'}],auxAttributes:{sandboxed:true,inProcessGpu:false,processCrashCount:0,glRenderer:'ANGLE (NVIDIA Corporation, NVIDIA RTX, OpenGL 4.5 NVIDIA 595.99.02)',glVendor:'Google Inc. (NVIDIA Corporation)',glImplementationParts:'(gl=egl-angle,angle=opengl)',glVersion:'OpenGL ES 3.0 (ANGLE)'},featureStatus:{opengl:'enabled_on',webgl:'enabled',gpu_compositing:'enabled'}}}};
  s.records=[s.browser,s.gpu_process];
  for(const [r,type] of [[s.browser,'browser'],[s.gpu_process,'GPU']]){r.processInfo={id:r.pid,type};r.stat=stat(r.pid,r.start_time);}
  s.processes={processInfo:s.records.map(r=>r.processInfo)};
  return s;
}
test('valid observations remain actual observations',()=>{const s=snapshot();assert.equal(capture.validateGpuSnapshot(s,cfg),s);});
const mutations={
  'unsandboxed':s=>{s.systemInfo.gpu.auxAttributes.sandboxed=false;},
  'in-process':s=>{s.systemInfo.gpu.auxAttributes.inProcessGpu=true;},
  'crashed':s=>{s.systemInfo.gpu.auxAttributes.processCrashCount=1;},
  'software renderer':s=>{s.systemInfo.gpu.auxAttributes.glRenderer='ANGLE SwiftShader NVIDIA';},
  'disabled GL':s=>{s.systemInfo.gpu.featureStatus.opengl='disabled_off';},
  'wrong vendor':s=>{s.systemInfo.gpu.devices[0].vendorId=123;},
  'wrong driver':s=>{s.systemInfo.gpu.devices[0].driverVersion='999.1';},
  'wrong device':s=>{s.systemInfo.gpu.devices[0].deviceId=1;},
  'wrong Chrome':s=>{s.chrome_version='Chrome/154.0.0.1';},
  'missing log':s=>{s.activation_log='';},
  'wrong PID log':s=>{s.activation_log=s.activation_log.replace('[200:','[201:');},
  'unsafe thread':s=>{s.gpu_process.threads[1].status=status(201,200).replace('Seccomp:\t2','Seccomp:\t0');},
  'unsafe main':s=>{s.gpu_process.status=status(200,200).replace('NoNewPrivs:\t1','NoNewPrivs:\t0');},
  'inherited filters only':s=>{s.browser.status=status(100,100,1);},
  'missing threads':s=>{s.gpu_process.threads=[];},
  'mismatched Tgid':s=>{s.gpu_process.threads[1].status=status(201,999);},
  'missing identity':s=>{delete s.gpu_process.stat;},
  'missing CDP processes':s=>{delete s.processes;},
  'main thread omitted':s=>{s.gpu_process.threads.shift();},
  'duplicate thread':s=>{s.gpu_process.threads.push(s.gpu_process.threads[0]);},
  'missing thread filters':s=>{s.gpu_process.threads[1].status=s.gpu_process.threads[1].status.replace(/Seccomp_filters:[^\n]*\n/,'');},
  'missing backend':s=>{delete s.systemInfo.gpu.auxAttributes.glImplementationParts;},
  'missing sandbox field':s=>{delete s.systemInfo.gpu.auxAttributes.sandboxed;},
  'crash count wrong type':s=>{s.systemInfo.gpu.auxAttributes.processCrashCount='0';},
};
for(const [name,mutate] of Object.entries(mutations))test(`fail closed: ${name}`,()=>{const s=snapshot();mutate(s);assert.throws(()=>capture.validateGpuSnapshot(s,cfg),/GPU qualification/);});
test('reject GPU restart and backend changes between observations',()=>{const before=snapshot(),after=snapshot();after.gpu_process.stat=stat(200,'13');assert.throws(()=>capture.validateGpuSnapshot(after,cfg,before),/GPU qualification/);after.gpu_process.stat=stat(200,'12');after.systemInfo.gpu.auxAttributes.glRenderer+=' changed';assert.throws(()=>capture.validateGpuSnapshot(after,cfg,before),/GPU qualification/);});

test('provider config is mandatory, Linux NVIDIA only, exact observed version pin',()=>{
  for(const value of [null,{}, {...cfg,gpu_route:'software'}, {...cfg,chrome_version:'Google Chrome 153.0.8010.53'}, {...cfg,chrome_version:'Google Chrome 153.0.8010.52 extra'}, {...cfg,gpu_device:{vendor_id:'4318',driver_version:'595.99.02'}}, {...cfg,gpu_device:{vendor_id:4318,driver_version:''}}, {...cfg,gpu_device:{...cfg.gpu_device,device_id:-1}}])
    assert.throws(()=>capture.validateGpuConfig(value),/GPU qualification.*153\.0\.8010\.52/);
  assert.throws(()=>capture.validateGpuConfig(cfg,'darwin'),/Linux NVIDIA/);
  assert.equal(capture.validateGpuConfig(cfg),cfg);
});
test('CDP missing/empty optional driver accepts renderer driver evidence, never mismatch',()=>{
  for(const missing of [undefined,'']){
    const s=snapshot();s.systemInfo.gpu.devices[0].driverVersion=missing;
    assert.equal(capture.validateGpuSnapshot(s,cfg),s);
    s.systemInfo.gpu.auxAttributes.glRenderer=s.systemInfo.gpu.auxAttributes.glRenderer.replace('595.99.02','595.99.03');
    assert.throws(()=>capture.validateGpuSnapshot(s,cfg),/driver differs/);
  }
});
function io(overrides={}){
  const s=snapshot(),calls=[],counts=new Map();
  const send=async method=>{
    calls.push(method);
    if(method==='SystemInfo.getInfo')return s.systemInfo;
    if(method==='SystemInfo.getProcessInfo')return s.processes;
    if(method==='Browser.getVersion')return {product:s.chrome_version};
    throw Error('unexpected '+method);
  };
  return {s,calls,options:{browserPid:100,activationLog:()=>s.activation_log,stage:'before',send,
    list:async()=>['200','201'],
    read:async file=>{
      counts.set(file,(counts.get(file)||0)+1);
      const parts=file.split('/'),pid=Number(parts[2]),tid=Number(parts[4]);
      if(parts.at(-1)==='stat')return stat(parts.includes('task')?tid:pid,pid===100?'11':'12');
      if(parts.at(-1)==='status')return status(parts.includes('task')?tid:pid,pid,pid===100?0:1);
      throw Error('unexpected proc read');
    },...overrides},counts};
}
test('fresh browser SystemInfo and all procfs threads are returned in shared raw shape',async()=>{
  const f=io(),s=await capture.observeGpu(f.options);
  assert.equal(capture.validateGpuSnapshot(s,cfg),s);
  assert.deepEqual(f.calls,['SystemInfo.getInfo','SystemInfo.getProcessInfo','Browser.getVersion','SystemInfo.getProcessInfo']);
  assert.equal(s.records.length,2);assert.equal(s.records[1].threads.length,2);
  assert.equal(f.counts.get('/proc/200/task/201/stat'),3);
});
for(const kind of ['missing process','identity changed','thread disappeared','thread set changed','CDP GPU restart','foreign browser'])test(`observation refuses ${kind}`,async()=>{
  const f=io();const originalRead=f.options.read,originalSend=f.options.send;let calls=0;
  if(kind==='missing process')f.options.read=async()=>{throw Error('ENOENT');};
  if(kind==='identity changed')f.options.read=async file=>{const v=await originalRead(file);return file==='/proc/200/stat'&&f.counts.get(file)>1?stat(200,'999'):v;};
  if(kind==='thread disappeared')f.options.read=async file=>{if(file==='/proc/200/task/201/status')throw Error('ENOENT');return originalRead(file);};
  if(kind==='thread set changed')f.options.list=async()=>++calls===1?['200','201']:['200'];
  if(kind==='CDP GPU restart')f.options.send=async method=>{const r=await originalSend(method);return method==='SystemInfo.getProcessInfo'&&++calls>1?{processInfo:[{type:'browser',id:100},{type:'GPU',id:999}]}:r;};
  if(kind==='foreign browser')f.options.browserPid=101;
  await assert.rejects(capture.observeGpu(f.options),/GPU qualification/);
});
test('only absent startup GPU is retried, bounded by deadline and attempt count',async()=>{
  let attempts=0,time=0;
  const absent=()=>{attempts++;const e=Error('starting');e.code='GPU_STARTUP_NOT_READY';throw e;};
  await assert.rejects(capture.qualifyGpu({},cfg,undefined,{startup:true,timeoutMs:100,now:()=>time,pause:async ms=>{time+=ms;},observe:absent}),/starting/);
  assert.equal(attempts,3);
  attempts=0;
  await assert.rejects(capture.qualifyGpu({},cfg,undefined,{startup:true,now:()=>0,pause:async()=>{},observe:absent}),/starting/);
  assert.equal(attempts,60);
  attempts=0;
  await assert.rejects(capture.qualifyGpu({},cfg,undefined,{observe:absent}),/starting/);assert.equal(attempts,1);
});
test('sandbox failures and missing activation evidence never retry',async()=>{
  for(const change of [s=>{s.systemInfo.gpu.auxAttributes.sandboxed=false;},s=>{s.activation_log='';}]){
    let attempts=0;
    await assert.rejects(capture.qualifyGpu({},cfg,undefined,{startup:true,observe:async()=>{attempts++;const s=snapshot();change(s);return s;}}),/GPU qualification/);
    assert.equal(attempts,1);
  }
  const f=io();f.s.processes.processInfo=f.s.processes.processInfo.filter(p=>p.type==='browser');f.s.systemInfo.gpu.auxAttributes.sandboxed=false;
  await assert.rejects(capture.observeGpu(f.options),e=>e.code!=='GPU_STARTUP_NOT_READY'&&/sandbox/.test(e.message));
});
test('startup absent GPU can become ready with fresh evidence',async()=>{
  let attempts=0;
  const observed=await capture.qualifyGpu({},cfg,undefined,{startup:true,pause:async()=>{},observe:async()=>{if(++attempts===1){const e=Error('starting');e.code='GPU_STARTUP_NOT_READY';throw e;}return snapshot();}});
  assert.equal(attempts,2);assert.equal(observed.chrome_version,'Chrome/153.0.8010.52');
});

test('activation log retention survives chunking and bounded stderr eviction',async()=>{
  const child=new EventEmitter();Object.assign(child,{pid:100,exitCode:0,signalCode:null,stderr:new EventEmitter()});
  const lifecycle=new capture.CaptureLifecycle(child,{close(){},closeAllConnections(){}});
  const line=snapshot().activation_log;
  child.stderr.emit('data',Buffer.from(line.slice(0,31)));
  child.stderr.emit('data',Buffer.from(line.slice(31)+'\n'));
  child.stderr.emit('data',Buffer.from('x'.repeat(20000)+'\n'));
  assert.deepEqual(lifecycle.gpuActivationLines,[line]);assert.equal(lifecycle.stderrTail.length,16384);
  for(let i=0;i<20;i++)child.stderr.emit('data',Buffer.from(line+'\n'));
  assert.equal(lifecycle.gpuActivationLines.length,16);
  await lifecycle.cleanup();assert.equal(child.stderr.listenerCount('data'),0);
});
test('production source keeps native flags, no bypass, and all gates before report',async()=>{
  const source=await readFile(new URL('../studio/filmmaking/capture.mjs',import.meta.url),'utf8');
  for(const flag of ['--enable-gpu','--disable-component-extensions-with-background-pages','--disable-features=WebUIOmniboxPopup,WebUIOmniboxAimPopup,SpareRendererForSitePerProcess','--enable-logging=stderr','--vmodule=sandbox_linux=1'])assert.ok(source.includes(flag),flag);
  for(const flag of ['--disable-gpu','--no-sandbox','--disable-gpu-sandbox','--in-process-gpu'])assert.ok(!source.includes(flag),flag);
  const before=source.indexOf("await qualify('before-authored-navigation'"),graphics=source.indexOf("await qualify('after-graphics-before-authored-navigation'"),navigate=source.indexOf("cmd('Page.navigate'"),after=source.indexOf("await qualify('after-capture'"),report=source.indexOf('await writeFile(cfg.report');
  assert.ok(before>0&&before<graphics&&graphics<navigate&&navigate<after&&after<report);
});

test('missing GPU evidence fails closed before source access or browser spawn',async()=>{
  const dir=await mkdtemp(path.join(tmpdir(),'capture-gpu-'));
  try {
    const file=path.join(dir,'config.json');
    await writeFile(file,JSON.stringify({width:8,height:8,duration_frames:1,start:0,end:1,samples:1,rate:{num:24,den:1}}));
    await assert.rejects(capture.capture(file),/GPU qualification.*153\.0\.8010\.52/);
  } finally {await rm(dir,{recursive:true,force:true});}
});
