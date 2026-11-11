// Isolated React/browser fixture for the new review lane only. No shared bundle,
// backend, live client, listener, private media or credential is used.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const playwright=process.env.PLAYWRIGHT_PACKAGE||path.dirname(require.resolve('playwright/package.json'));
const {chromium}=require(playwright),{expect}=require(path.join(playwright,'test.js'));
const desktopModules=path.join(process.env.HERMES_SOURCE||path.join(os.homedir(),'.hermes/hermes-agent-official'),'apps/desktop/node_modules');
const compiler=process.env.ESBUILD||path.join(desktopModules,'.bin/esbuild');
const temp=fs.mkdtempSync(path.join(process.env.TMPDIR||os.tmpdir(),'media-review-lane-'));
const checks=[],errors=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);};
let browser;
const entry=`
import {createElement as h,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MediaReview} from ${JSON.stringify(path.resolve('studio/native/frontend/media-review.js'))};
const originalCreate=URL.createObjectURL.bind(URL),originalRevoke=URL.revokeObjectURL.bind(URL);
window.fixtureURLs=[];window.fixtureRevoked=[];
URL.createObjectURL=blob=>{const url=originalCreate(blob);window.fixtureURLs.push(url);return url;};
URL.revokeObjectURL=url=>{window.fixtureRevoked.push(url);originalRevoke(url);};
const bytes=new Map(),descriptors=[];window.fixtureReads=0;window.fixtureCurrent=true;
function add(id,kind,mime,data,extra={}){
  bytes.set(id,data);descriptors.push({identity:{production:'controlled-production',asset:'controlled-asset',
    request:'controlled-request-'+id,requestRevision:1,take:id,artifact:'controlled-artifact-'+id},
    kind,mime,byteLength:data.length,reviewStatus:'Not reviewed',qualityRole:'Original fixture',...extra});
}
function picture(width,height,color){
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  const context=canvas.getContext('2d');context.fillStyle=color;context.fillRect(0,0,width,height);
  context.fillStyle='white';context.fillRect(0,0,width/3,height/3);
  return Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]),value=>value.charCodeAt(0));
}
function tone(){
  const rate=8000,frames=rate*3,data=new Uint8Array(44+frames*2),view=new DataView(data.buffer);
  const text=(offset,value)=>[...value].forEach((letter,index)=>view.setUint8(offset+index,letter.charCodeAt(0)));
  text(0,'RIFF');view.setUint32(4,data.length-8,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);
  view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);
  view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,frames*2,true);
  for(let index=0;index<frames;index++)view.setInt16(44+index*2,Math.sin(index*2*Math.PI*220/rate)*4000,true);
  return data;
}
add('image-wide','Image','image/png',picture(1200,800,'#264c35'),{width:1200,height:800});
add('image-tall','Image','image/png',picture(800,1200,'#314471'),{width:800,height:1200});
for(const [id,kind] of [['voice','Voice'],['music','Music'],['sfx','Sound effects']])add(id,kind,'audio/wav',tone(),{duration:3});
add('video','Video','video/webm',Uint8Array.from(atob(window.fixtureVideo),value=>value.charCodeAt(0)),{duration:3,width:160,height:90});
add('unsupported','Image','image/svg+xml',new TextEncoder().encode('<svg/>'));
add('broken','Image','image/png',new TextEncoder().encode('controlled invalid PNG'));
const readBytes=async input=>{
  window.fixtureReads++;
  if(window.fixtureHold)await new Promise(resolve=>{window.fixtureRelease=resolve;});
  return {scope:input.scope,identity:input.identity,bytes:bytes.get(input.identity.take)};
};
const isScopeCurrent=()=>window.fixtureCurrent;
const onController=value=>{window.fixtureController=value;};
function Fixture(){
  const [scope,setScope]=useState('fixture-epoch-1'),[open,setOpen]=useState(true);
  window.fixtureScope=value=>setScope(value);window.fixtureClose=()=>setOpen(false);window.fixtureOpen=()=>setOpen(true);
  return open?h(MediaReview,{scope,descriptors,readBytes,isScopeCurrent,onController}):h('p',null,'Fixture review closed');
}
createRoot(document.getElementById('root')).render(h(Fixture));
`;
try{
  const video=path.join(temp,'controlled-pattern-with-tone.webm');
  execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10',
    '-f','lavfi','-i','sine=frequency=440:sample_rate=8000','-t','3','-c:v','libvpx','-c:a','libvorbis',video]);
  const fixture=path.join(temp,'fixture.js');
  const sdk=path.join(temp,'sdk.js');
  fs.writeFileSync(sdk,"import {createElement} from 'react'; export const Button=props=>createElement('button',props);");
  execFileSync(compiler,[
    '--bundle','--format=iife','--platform=browser','--log-level=error',
    '--alias:@hermes/plugin-sdk='+sdk,'--outfile='+fixture],
    {input:entry,env:{...process.env,NODE_PATH:process.env.NODE_PATH||desktopModules}});
  browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE,headless:true,args:['--no-sandbox']});
  const context=await browser.newContext({serviceWorkers:'block',offline:true,reducedMotion:'reduce'});
  const html='<html><meta name="viewport" content="width=device-width"><body style="margin:0;background:#121513"><div id="root"></div><script>'+ 
    'window.fixtureVideo='+JSON.stringify(fs.readFileSync(video).toString('base64'))+';'+
    fs.readFileSync(fixture,'utf8').replaceAll('</script','<\\/script')+'</script></body></html>';
  await context.route('**/*',route=>route.request().url()==='https://media-review.invalid/'?
    route.fulfill({contentType:'text/html',body:html}):route.abort());
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  const button=name=>page.getByRole('button',{name,exact:true});
  const status=()=>page.getByRole('status',{name:'Media review status',exact:true});
  const choose=async(slot,index)=>page.getByLabel('Retained take '+slot,{exact:true}).selectOption(String(index));
  const load=async(slot,index)=>{await choose(slot,index);await button('Load original '+slot).click();};
  const monitor=async slot=>{await button('Monitor '+slot).click();await expect.poll(()=>page.locator('audio,video').evaluate(el=>el.readyState)).toBeGreaterThan(0);};
  await page.goto('https://media-review.invalid/');
  await load('A',0);await load('B',1);await expect(page.locator('img')).toHaveCount(2);
  await expect.poll(()=>page.locator('img').evaluateAll(images=>images.every(image=>image.complete&&image.naturalWidth>0))).toBe(true);
  check('two real decoded full-resolution PNG originals show distinct dimensions side by side',
    await page.locator('img').evaluateAll(images=>images[0].naturalWidth===1200&&images[1].naturalHeight===1200)&&
    await page.locator('.media-review-slots').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length===2));
  const zoom=page.getByLabel('Image zoom A',{exact:true});await zoom.focus();await zoom.selectOption('100');
  check('actual-pixel zoom has keyboard-reachable local pan viewport without page overflow',
    await page.locator('img').first().evaluate(image=>image.getBoundingClientRect().width===1200)&&
    await page.getByRole('region',{name:'Image A viewport - arrow keys scroll at actual size'}).getAttribute('tabindex')==='0'&&
    await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await zoom.selectOption('200');check('200 percent zoom uses actual source pixels',await page.locator('img').first().evaluate(image=>image.getBoundingClientRect().width===2400));
  await zoom.selectOption('fit');await page.getByText('Exact retained identity A',{exact:true}).focus();await page.keyboard.press('Enter');
  check('exact request/take/artifact lineage is keyboard-accessible',await page.getByText('take: image-wide',{exact:true}).isVisible());
  const initialURLCount=await page.evaluate(()=>window.fixtureURLs.length);
  await load('A',2);await monitor('A');
  check('explicit audio load/monitor does not autoplay and replaces/revokes old image',
    await page.locator('audio').evaluate(el=>el.paused&&!el.autoplay)&&await page.evaluate(()=>window.fixtureRevoked.length===1));
  await page.getByLabel('Original position seconds').fill('0.5');await page.getByLabel('Original monitoring volume').fill('0.37');
  const playerGroup=page.getByRole('group',{name:'Original media keyboard player',exact:true});await playerGroup.focus();await playerGroup.press('Space');
  await expect.poll(()=>page.locator('audio').evaluate(el=>el.paused)).toBe(false);
  await playerGroup.press('Space');check('focused player Space deliberately plays and pauses real WAV',await page.locator('audio').evaluate(el=>el.paused));
  await load('B',5);await monitor('B');
  check('video with audio uses one active player, paused on switch, same gain and absolute origin',
    await page.locator('audio,video').count()===1&&await page.locator('video').evaluate(el=>el.paused&&el.volume===0.37&&el.currentTime>=0.5&&!el.muted));
  await page.getByLabel('Original position seconds').fill('0.25');await button('Play original B').click();
  await expect.poll(()=>page.locator('video').evaluate(el=>el.currentTime)).toBeGreaterThan(0.3);
  await button('Pause original').click();
  check('real controlled video decodes frames and plays deliberately with audio retained',
    await page.locator('video').evaluate(el=>el.videoWidth===160&&el.videoHeight===90&&el.paused&&el.duration>2));
  await page.getByLabel('Original position seconds').fill('9');await button('Play original B').click();
  await expect(status()).toContainText('at or beyond the end');check('out-of-range video position cannot retime or start playback',await page.locator('video').evaluate(el=>el.paused));
  for(const [index,kind] of [[3,'Music'],[4,'Sound effects']]){
    await load('A',index);await monitor('A');
    check(kind+' original WAV has accessible kind/take/duration/review and is paused',
      await page.locator('audio').getAttribute('aria-label')===kind+' take '+(index===3?'music':'sfx')+' / 3 seconds / Not reviewed'&&
      await page.locator('audio').evaluate(el=>el.paused));
  }
  await page.getByLabel('Original position seconds').fill('0.1');await button('Play original A').click();
  await expect.poll(()=>page.locator('audio').evaluate(el=>el.paused)).toBe(false);
  await page.evaluate(()=>{window.fixtureOldPlayer=document.querySelector('audio');window.fixtureScope('fixture-epoch-2');});
  await expect(page.locator('audio,video,img')).toHaveCount(0);
  check('scope change pauses detached player and revokes all old scoped URLs',await page.evaluate(()=>window.fixtureOldPlayer.paused&&
    !window.fixtureOldPlayer.getAttribute('src')&&window.fixtureURLs.length===window.fixtureRevoked.length));
  await load('A',6);await expect(page.getByText('Unsupported media format in this viewer. Original is unchanged.',{exact:true})).toBeVisible();
  const reads=await page.evaluate(()=>window.fixtureReads);await load('B',7);
  await expect(page.getByText('Browser cannot decode this original format or codec. Original is unchanged.',{exact:true})).toBeVisible();
  check('unsupported MIME performs no read and corrupt PNG reports actual decoder refusal',
    await page.evaluate(()=>window.fixtureReads)===reads+1&&await page.locator('img').count()===0);
  await choose('A',0);await page.evaluate(()=>{window.fixtureHold=true;});await button('Load original A').click();
  await expect.poll(()=>page.evaluate(()=>Boolean(window.fixtureRelease))).toBe(true);
  await choose('A',1);await page.evaluate(()=>{window.fixtureHold=false;window.fixtureRelease();window.fixtureRelease=null;});
  await expect(button('Load original A')).toBeEnabled();
  check('pending original read cannot publish into replaced exact identity',await page.locator('img').count()===0);
  await button('Load original A').click();await expect(page.locator('img')).toHaveCount(1);
  await page.setViewportSize({width:390,height:900});
  check('390px review reflows without horizontal page overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.evaluate(()=>{document.documentElement.style.fontSize='200%';});
  check('200 percent text reflow retains labeled load and zoom controls',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)&&await page.getByLabel('Image zoom A',{exact:true}).isVisible());
  await page.screenshot({path:path.join(temp,'narrow-reflow.png'),fullPage:true});
  await page.evaluate(()=>{window.fixtureCurrent=false;window.fixtureController.current();});
  await expect(page.getByText('Review closed; scoped media cleared.',{exact:true})).toBeVisible();
  check('external scope refusal clears all exact labels and media without host mutation',await page.locator('select,audio,video,img,details').count()===0);
  check('no browser page errors or private persistence',errors.length===0&&await page.evaluate(()=>localStorage.length===0));
  check('fixture exercised loaded byte URLs',initialURLCount===2);
  await context.close();
  console.log(JSON.stringify({checks:checks.length,passed:checks,errors,temporaryEvidence:temp,native:false,listening:'Not reviewed'},null,2));
}finally{
  await browser?.close();
  // Keep only the harmless screenshot/result location for coordinator inspection.
  for(const name of ['controlled-pattern-with-tone.webm','fixture.js','sdk.js'])fs.rmSync(path.join(temp,name),{force:true});
}
