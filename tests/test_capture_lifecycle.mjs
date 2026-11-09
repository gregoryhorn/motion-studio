import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {once} from 'node:events';
import * as captureModule from '../studio/filmmaking/capture.mjs';
import {stat, mkdtemp, readFile, writeFile, rm} from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
const {CaptureLifecycle}=captureModule;

// An actual owned process and RFC6455 peer: exercise native Node WebSocket,
// not source matching or a replacement Promise implementation. No Chromium,
// external connections, npm dependencies, or browser profiles are needed.
const peer=String.raw`
const {createServer}=require('node:http');
const {createHash}=require('node:crypto');
const mode=process.argv[1];
process.on('SIGTERM',()=>{}); // force the owned SIGKILL escalation path
const server=createServer();
server.on('upgrade',(req,socket)=>{
  if(mode==='noOpen')return;
  const accept=createHash('sha1').update(req.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n');
  let bytes=Buffer.alloc(0), calls=[];
  socket.on('error',()=>{});
  socket.on('data',b=>{
    bytes=Buffer.concat([bytes,b]);
    while(bytes.length>=2){
      const opcode=bytes[0]&15, masked=!!(bytes[1]&128);
      let n=bytes[1]&127, p=2;
      if(n===126){if(bytes.length<4)return;n=bytes.readUInt16BE(2);p=4;}
      if(n===127)throw Error('Unexpected oversized test frame');
      if(bytes.length<p+(masked?4:0)+n)return;
      const mask=masked?bytes.subarray(p,p+4):null;p+=masked?4:0;
      const payload=Buffer.from(bytes.subarray(p,p+n));bytes=bytes.subarray(p+n);
      if(mask)for(let i=0;i<n;i++)payload[i]^=mask[i%4];
      if(opcode===8){socket.end(Buffer.from([0x88,0]));return;}
      const m=JSON.parse(payload.toString());calls.push(m.method);
      if(m.method==='Silent')continue;
      if(m.method==='Disconnect'){socket.end(Buffer.from([0x88,0]));continue;}
      if(m.method==='Error'){socket.write(Buffer.from([0x83,0]));continue;}
      if(m.method==='Exit'){process.exit(7);}
      let result={method:m.method,params:m.params,sessionId:m.sessionId};
      if(m.method==='Test.history')result=calls.slice(0,-1);
      if(m.method==='Target.getTargets') {
        const blank={targetId:'owned-initial',type:'page',url:'about:blank',attached:false};
        const variants={
          initial:[{targetId:'worker',type:'service_worker',url:'about:blank'},blank],
          multiple:[blank,{...blank,targetId:'other'}],
          navigated:[{...blank,url:'https://example.invalid/'}],
          attached:[{...blank,attached:true}],
          context:[{...blank,browserContextId:'reported-context'}],
          mixed:[blank,{...blank,targetId:'other',url:'https://example.invalid/'}],
          noId:[{...blank,targetId:''}],
          opener:[{...blank,openerId:'other'}],
          missing:[],
        };
        result={targetInfos:variants[mode]};
      }
      if(m.method==='Target.createTarget')throw Error('Must not create a second page');
      if(m.method==='Target.attachToTarget') {
        if(m.params.targetId!=='owned-initial' || m.params.flatten!==true)throw Error('Wrong attachment');
        result={sessionId:'owned-session'};
      }
      const out=Buffer.from(JSON.stringify(m.method==='Reject'?{id:m.id,error:{message:'controlled refusal'}}:{id:m.id,result}));
      const header=out.length<126?Buffer.from([0x81,out.length]):Buffer.from([0x81,126,out.length>>8,out.length&255]);
      socket.write(Buffer.concat([header,out]));
    }
  });
});
server.listen(0,'127.0.0.1',()=>{
  if(mode!=='noEndpoint')process.stderr.write('DevTools listening on ws://127.0.0.1:'+server.address().port+'/fake\n');
});
`;

async function fixture(t,mode='normal',options={}) {
  const server=createServer();server.listen(0,'127.0.0.1');await once(server,'listening');
  const child=spawn(process.execPath,['-e',peer,mode],{stdio:['ignore','ignore','pipe']});
  const lifecycle=new CaptureLifecycle(child,server,{timeoutMs:500,shutdownMs:60,...options});
  t.after(async()=>{
    await lifecycle.cleanup();
    assert.equal(server.listening,false,'owned HTTP server closed');
    assert.ok(child.exitCode!==null || child.signalCode!==null || child.pid===undefined,'owned peer reaped');
    assert.equal(lifecycle.pending.size,0);
    assert.equal(lifecycle.waiters.size,0);
  });
  return lifecycle;
}
async function connected(t) {
  const lifecycle=await fixture(t);
  await lifecycle.connect(await lifecycle.endpoint());
  return lifecycle;
}

test('normal CDP response preserves params/session; duplicate cleanup reaps owned child',async t=>{
  const lifecycle=await connected(t);
  assert.deepEqual(await lifecycle.send('Normal',{n:4},'session'),{method:'Normal',params:{n:4},sessionId:'session'});
  assert.equal(lifecycle.pending.size,0);
  await assert.rejects(lifecycle.send('Reject'),/controlled refusal/);
  assert.equal((await lifecycle.send('Normal')).method,'Normal');
  const first=lifecycle.cleanup();assert.equal(lifecycle.cleanup(),first);await first;
  assert.equal(lifecycle.chrome.signalCode,'SIGKILL');
  await assert.rejects(lifecycle.send('Normal'),/cancelled/);
});

test('no response rejects every pending command with named bounded timeout',async t=>{
  const lifecycle=await connected(t);
  const results=await Promise.allSettled([lifecycle.send('Silent',{},undefined,40),lifecycle.send('Silent')]);
  assert.deepEqual(results.map(r=>r.status),['rejected','rejected']);
  assert.match(results[0].reason.message,/CDP Silent timed out after 40ms/);
  assert.equal(results[0].reason,results[1].reason);
  assert.equal(lifecycle.pending.size,0);
  await assert.rejects(lifecycle.send('Normal'),/timed out/);
});

for(const [method,pattern] of [['Disconnect',/disconnected/],['Error',/WebSocket error/],['Exit',/exited \(7\)|disconnected/]]) {
  test(`${method} rejects outstanding commands once and leaves no timers/waiters`,async t=>{
    const lifecycle=await connected(t);
    let rejections=0;
    const a=lifecycle.send('Silent').catch(e=>{rejections++;throw e;});
    const b=lifecycle.send(method).catch(e=>{rejections++;throw e;});
    const results=await Promise.allSettled([a,b]);
    assert.equal(rejections,2);assert.match(results[0].reason.message,pattern);
    assert.equal(results[0].reason,results[1].reason);
    lifecycle.fail(Error('second failure'));
    assert.equal(rejections,2);assert.equal(lifecycle.pending.size,0);
  });
}

test('WebSocket handshake never opens: bounded rejection and owned cleanup',async t=>{
  const lifecycle=await fixture(t,'noOpen');
  await assert.rejects(lifecycle.connect(await lifecycle.endpoint()),/connection timed out/);
});
test('DevTools never announced: bounded rejection and owned cleanup',async t=>{
  const lifecycle=await fixture(t,'noEndpoint',{timeoutMs:100});
  await assert.rejects(lifecycle.endpoint(),/DevTools timed out/);
});
// Hold transport events to force the child-exit path rather than depending on
// the OS race between SIGCHLD and WebSocket close/error delivery.
class HeldSocket extends EventTarget {
  send() {}
  close() {}
}
test('Chrome exit while waiting for connection rejects without waiting for deadline',async t=>{
  const lifecycle=await fixture(t,'noOpen',{WebSocketImpl:HeldSocket});
  const endpoint=await lifecycle.endpoint();
  const waiting=assert.rejects(lifecycle.connect(endpoint),/exited/);
  lifecycle.chrome.kill('SIGKILL');await waiting;
});
test('Chrome exit alone rejects all commands even without a socket close event',async t=>{
  const lifecycle=await fixture(t,'normal',{WebSocketImpl:HeldSocket});
  const connecting=lifecycle.connect(await lifecycle.endpoint());
  lifecycle.ws.dispatchEvent(new Event('open'));await connecting;
  const a=assert.rejects(lifecycle.send('Silent'),/exited/);
  const b=assert.rejects(lifecycle.send('Silent'),/exited/);
  lifecycle.chrome.kill('SIGKILL');await Promise.all([a,b]);
  assert.equal(lifecycle.pending.size,0);
});
test('cancellation rejects outstanding commands and reaps only owned process',async t=>{
  const lifecycle=await connected(t);
  const waiting=assert.rejects(lifecycle.send('Silent'),/cancelled/);
  await lifecycle.cleanup();await waiting;
});
for(const present of [true,false])test(`owned Chrome environment contains session bus only in child (parent present=${present})`,async()=>{
  // A separate parent process avoids mutating the test runner's real environment.
  const script=`
    const assert=require('node:assert/strict');
    const {spawn}=require('node:child_process');
    const {createServer}=require('node:net');
    (async()=>{
      const {ownedChromeEnvironment}=await import(${JSON.stringify(new URL('../studio/filmmaking/capture.mjs',import.meta.url).href)});
      const server=createServer(socket=>{throw Error('Child reached inherited desktop bus');});
      server.listen(0,'127.0.0.1');await new Promise(r=>server.once('listening',r));
      if(${present})process.env.DBUS_SESSION_BUS_ADDRESS='tcp:host=127.0.0.1,port='+server.address().port;
      else delete process.env.DBUS_SESSION_BUS_ADDRESS;
      const before={...process.env};
      const env=ownedChromeEnvironment();
      assert.ok(JSON.stringify({...process.env})===JSON.stringify(before),'parent environment unchanged');
      assert.deepEqual(env,{...before,DBUS_SESSION_BUS_ADDRESS:'unix:path=/dev/null'});
      const child=spawn(process.execPath,['-e',
        "const assert=require('node:assert/strict');const net=require('node:net');"+
        "assert.equal(process.env.DBUS_SESSION_BUS_ADDRESS,'unix:path=/dev/null');"+
        "const socket=net.createConnection({path:'/dev/null'});"+
        "socket.on('connect',()=>{throw Error('Unexpected D-Bus endpoint');});"+
        "socket.on('error',e=>{assert.ok(['ECONNREFUSED','ENOTSOCK'].includes(e.code),e.code);});"
      ],{env,stdio:['ignore','pipe','pipe']});
      let stderr='';child.stderr.on('data',b=>stderr+=b);
      const code=await new Promise(r=>child.once('exit',r));
      assert.equal(code,0,stderr);assert.ok(JSON.stringify({...process.env})===JSON.stringify(before),'parent environment unchanged');
      server.close();
    })().catch(e=>{console.error(e);process.exit(1);});
  `;
  assert.ok((await stat('/dev/null')).isCharacterDevice(),'/dev/null is a device, not a socket');
  const child=spawn(process.execPath,['-e',script],{env:{MOTION_ENV_SENTINEL:'preserved'},stdio:['ignore','pipe','pipe']});
  let stderr='';child.stderr.on('data',b=>stderr+=b);
  const timer=setTimeout(()=>child.kill('SIGKILL'),3000);
  try {assert.equal((await once(child,'exit'))[0],0,stderr);}
  finally {clearTimeout(timer);}
});

for(const mode of ['initial','context'])test(`reuse sole initial owned blank page (${mode}), ignoring non-page targets`,async t=>{
  const lifecycle=await fixture(t,mode);
  await lifecycle.connect(await lifecycle.endpoint());
  assert.deepEqual(await captureModule.attachOwnedInitialPage((...args)=>lifecycle.send(...args)),{sessionId:'owned-session'});
  assert.deepEqual(await lifecycle.send('Test.history'),['Target.getTargets','Target.attachToTarget']);
});
for(const mode of ['multiple','mixed','navigated','attached','opener','missing','noId']) {
  test(`refuse ${mode} targets instead of attaching arbitrarily or creating another page`,async t=>{
    const lifecycle=await fixture(t,mode);
    await lifecycle.connect(await lifecycle.endpoint());
    await assert.rejects(captureModule.attachOwnedInitialPage((...args)=>lifecycle.send(...args)),/initial owned about:blank page/);
    assert.deepEqual(await lifecycle.send('Test.history'),['Target.getTargets']);
  });
}

test('production Chrome spawn changes only child bus environment, not parent cwd or environment',async()=>{
  const cwdBefore=process.cwd(),envBefore={...process.env};
  const child=captureModule.spawnOwnedChrome(process.execPath,['-e',
    'process.stderr.write(JSON.stringify({cwd:process.cwd(),env:process.env}))']);
  let stderr='';child.stderr.on('data',b=>stderr+=b);
  const timer=setTimeout(()=>child.kill('SIGKILL'),3000);
  try {
    const [code,signal]=await once(child,'close');
    assert.equal(code,0,stderr);assert.equal(signal,null);
    const observed=JSON.parse(stderr);
    assert.equal(observed.cwd,cwdBefore);
    assert.deepEqual(observed.env,{...envBefore,DBUS_SESSION_BUS_ADDRESS:'unix:path=/dev/null'});
    assert.equal(process.cwd(),cwdBefore);
    assert.deepEqual({...process.env},envBefore);
  } finally {clearTimeout(timer);}
});

test('startup failure retains a bounded real child stderr tail and removes its observer',async()=>{
  const server=createServer();server.listen(0,'127.0.0.1');await once(server,'listening');
  const child=captureModule.spawnOwnedChrome(process.execPath,['-e',
    'process.stderr.write("x".repeat(20000)+"OWNED_FATAL_STARTUP");setTimeout(()=>process.exit(7),30)']);
  const lifecycle=new CaptureLifecycle(child,server,{timeoutMs:1000,shutdownMs:60});
  try {
    await assert.rejects(lifecycle.endpoint(),error=>{
      assert.match(error.message,/Chromium exited \(7\)/);
      assert.match(error.message,/OWNED_FATAL_STARTUP/);
      assert.ok(error.message.length<1900);
      return true;
    });
    assert.equal(lifecycle.stderrTail.length,16384);
  } finally {await lifecycle.cleanup();}
  assert.equal(child.stderr.listeners('data').includes(lifecycle.onStderr),false);
});

test('failed Chrome spawn rejects startup and closes owned server',async t=>{
  const server=createServer();server.listen(0,'127.0.0.1');await once(server,'listening');
  const child=spawn('/nonexistent/motion-capture-chrome',[],{stdio:['ignore','ignore','pipe']});
  const lifecycle=new CaptureLifecycle(child,server,{timeoutMs:500,shutdownMs:60});
  try {await assert.rejects(lifecycle.endpoint(),/process error.*ENOENT/);}
  finally {await lifecycle.cleanup();}
  assert.equal(server.listening,false);assert.equal(lifecycle.waiters.size,0);assert.equal(child.pid,undefined);
});
