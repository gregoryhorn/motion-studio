// Source UI + real scoped Python RPC/store; checker and tool-effect ports are fixtures.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),modules=path.join(os.homedir(),'.hermes/hermes-agent-official/apps/desktop/node_modules');
const esbuild=require(path.join(modules,'esbuild'));
const pw=process.env.PLAYWRIGHT_PACKAGE||path.join(os.homedir(),'projects/gregory-cv/projects/Exomorphic-Particle/node_modules/playwright');
const {chromium}=require(pw),{expect}=require(path.join(pw,'test.js'));
const temporary=fs.mkdtempSync(path.join(process.env.TMPDIR,'director-browser-'));
const output=path.resolve(process.env.DIRECTOR_EVIDENCE||'docs/evidence/director-v02');fs.mkdirSync(output,{recursive:true});
await esbuild.build({entryPoints:['tests/director-browser-fixture.js'],bundle:true,format:'iife',platform:'browser',
  alias:{react:path.join(modules,'react'),'react-dom':path.join(modules,'react-dom'),nanostores:path.join(modules,'nanostores'),
    '@hermes/plugin-sdk':path.resolve('tests/production-board-widgets.js')},outfile:path.join(temporary,'fixture.js'),logLevel:'error'});
const child=spawn(process.env.PYTHON||'python',['-m','tests.director_fixture'],{stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONPYCACHEPREFIX:path.join(temporary,'pycache')}});
const pending=new Map();let serial=0;const childErrors=[];
child.stderr.on('data',()=>childErrors.push('PYTHON_STDERR'));
const lines=readline.createInterface({input:child.stdout});lines.on('line',line=>{const message=JSON.parse(line),resolve=pending.get(message.id);pending.delete(message.id);resolve?.(message.result);});
const rpc=value=>new Promise((resolve,reject)=>{const id=++serial;pending.set(id,resolve);child.stdin.write(JSON.stringify({id,...value})+'\n');setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(Error('FIXTURE_TIMEOUT'));}},20000).unref();});
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||path.join(os.homedir(),'.cache/ms-playwright/chromium-1248/chrome-linux64/chrome'),headless:true,args:['--no-sandbox']});
const context=await browser.newContext({offline:true,serviceWorkers:'block',viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const page=await context.newPage(),errors=[],checks=[];
page.on('pageerror',error=>errors.push(error.message));
await page.exposeFunction('nativeRPC',rpc);
const button=name=>page.getByRole('button',{name,exact:true});
const check=async(name,fn)=>{await fn();checks.push(name);};
const count=async()=>rpc({op:'counts'});
const noOverflow=async()=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
try{
  const script=fs.readFileSync(path.join(temporary,'fixture.js'),'utf8').replaceAll('</script','<\\/script');
  await page.route('https://director.fixture.invalid/',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html></html>'}));
  await page.goto('https://director.fixture.invalid/');
  await page.setContent('<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;--ui-bg-primary:#151816;--ui-text-primary:#e8f0eb;--ui-bg-secondary:#26332c;--ui-text-secondary:#b9c8c0;--ui-accent:#96e7b2"><div id="root"></div><script>'+script+'</script></body></html>');
  await expect(button('Controlled tool · Untested')).toBeVisible();
  await check('Scoped inventory and Untested templates; zero discovery effects',async()=>{
    await expect(page.getByText('Profile-scoped inventory unavailable',{exact:true})).toBeVisible();
    assert.equal((await count()).effects,0);await noOverflow();
    await expect(page.getByText('No tested tools yet. Add a tool or rescan this profile.')).toBeVisible();
  });
  await check('Keyboard detail and Cancel perform zero effects and restore focus',async()=>{
    await button('Controlled tool · Untested').focus();await page.keyboard.press('Enter');
    await button('Review tiny test').focus();await page.keyboard.press('Enter');
    await expect(page.getByRole('dialog',{name:'Confirm tiny test'})).toContainText('One call:');
    await button('Cancel').click();await expect(button('Review tiny test')).toBeFocused();
    assert.equal((await count()).effects,0);
  });
  await check('Lost acknowledgement then unmount/reopen before result observation recovers one effect',async()=>{
    await page.evaluate(()=>{window.directorLoseTestAck=true;});
    await button('Review tiny test').click();await button('Test and enable').click();
    await expect(page.getByRole('status')).toContainText('Reply unconfirmed');
    assert.equal((await count()).effects,process.argv.includes('--negative-control')?2:1);
    await page.evaluate(()=>{window.directorUnmount();window.directorLoseTestAck=false;});
    await page.evaluate(()=>window.directorMount());
    await expect(button('Controlled tool · Tested')).toBeVisible();assert.equal((await count()).effects,1);
    await button('Controlled tool · Tested').click();await expect(page.getByText(/Enabled for this tested operation/)).toBeVisible();
  });
  await check('Quick and detailed help disclose costs, missing senses, reports and Undo',async()=>{
    await button('Help').click();await expect(page.getByRole('region',{name:'Detailed tools help'})).toContainText('Unknown cost is not free');
    await expect(page.getByRole('region',{name:'Detailed tools help'})).toContainText('Undo/Restore');
    await button('Close help').click();
  });
  await check('Actual Tools UI fits 1440 and 390, light/dark/custom and 200% CSS zoom',async()=>{
    for(const theme of ['dark','light','custom']){
      await page.evaluate(theme=>{document.body.style.setProperty('--ui-bg-primary',theme==='light'?'#fafafa':theme==='custom'?'#17233a':'#151816');
        document.body.style.setProperty('--ui-text-primary',theme==='light'?'#222':'#e8f0eb');
        document.body.style.setProperty('--ui-text-secondary',theme==='light'?'#505050':'#b9c8c0');
        document.body.style.setProperty('--ui-bg-secondary',theme==='light'?'#ecefec':theme==='custom'?'#233a60':'#26332c');},theme);
      for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await noOverflow();
        await page.screenshot({path:path.join(output,'tools-'+theme+'-'+width+'.png'),fullPage:true});}
    }
    await page.evaluate(()=>document.documentElement.style.zoom='2');await noOverflow();
    await page.screenshot({path:path.join(output,'tools-zoom.png'),fullPage:true});
    await page.evaluate(()=>document.documentElement.style.zoom='1');
  });
  const take=await rpc({op:'take'});
  await check('Open report is scoped retained text and does not dispatch checks',async()=>{
    await page.evaluate(take=>window.directorTake(take),take);
    await expect(page.getByText('Crystal Ball: WARN',{exact:true})).toBeVisible();
    await expect(page.getByText('Not checked: Hear is disabled',{exact:true})).toBeVisible();
    await button('Open report').click();await expect(page.locator('pre')).toContainText('Controlled report');
    assert.equal((await count()).effects,1);
  });
  await check('Remove/Undo and Recently removed Restore survive backend restart',async()=>{
    await button('Delete from Studio').click();await expect(button('Undo remove')).toBeVisible();
    await button('Undo remove').click();await expect(button('Delete from Studio')).toBeVisible();
    await button('Delete from Studio').click();await rpc({op:'restart'});
    await page.evaluate(()=>window.directorMount());await expect(button('Restore take 1')).toBeVisible();
    await button('Restore take 1').click();await expect(page.getByText('No removed takes.',{exact:true})).toBeVisible();
  });
  await check('Pending read away-and-back discards old continuation without new effects',async()=>{
    await page.evaluate(()=>{window.directorUnmount();window.fixtureHoldOperation='card.read';});
    await page.evaluate(()=>window.directorMount());
    await expect.poll(()=>page.evaluate(()=>typeof window.fixtureReleaseOperation)).toBe('function');
    await page.evaluate(()=>{window.directorHost.state.focusedSessionId.set('other');window.directorHost.state.focusedSessionId.set('session-a');window.fixtureHoldOperation=null;window.fixtureReleaseOperation();});
    await expect(page.getByRole('status')).toContainText('Selected chat or connection changed');
    await expect(button('Controlled tool · Tested')).toHaveCount(0);assert.equal((await count()).effects,1);
  });
  assert.deepEqual(errors,[]);assert.deepEqual(childErrors,[]);
  fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify({checks,passed:checks.length,pageErrors:errors,
    evidence:'Actual React source UI with real scoped RPC/SQLite; controlled tool/checker ports, not native install'},null,2)+'\n');
  console.log(JSON.stringify({passed:checks.length,pageErrors:errors.length,effects:(await count()).effects}));
}finally{await browser.close();child.stdin.end();await new Promise(resolve=>child.once('exit',resolve));fs.rmSync(temporary,{recursive:true,force:true});}
