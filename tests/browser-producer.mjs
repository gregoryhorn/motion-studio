// OFFLINE TEST ONLY: real ASGI process + explicit argv-native fake child, no model.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn, spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE);
const {expect} = require(path.join(process.env.PLAYWRIGHT_PACKAGE, 'test.js'));
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'motion-offline-producer-'));
const evidence = path.join(process.cwd(), 'docs/evidence');
const secret = crypto.randomBytes(32).toString('hex');
fs.writeFileSync(path.join(home, 'test-secret'), secret, {mode: 0o600});
const origin = 'http://127.0.0.1:18766';
const server = spawn('python', ['-m', 'tests.producer_server', '--home', home, '--port', '18766'], {stdio: 'ignore'});
let browser;
const checks = [];
const check = (name, value) => { assert.ok(value, name); checks.push(name); };
try {
  let healthy = false;
  for (let n = 0; n < 100; n++) {
    if (server.exitCode !== null) throw new Error('Owned offline test server exited');
    try { if ((await fetch(origin)).ok) { healthy = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.ok(healthy);
  browser = await chromium.launch({executablePath: process.env.CHROME_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const context = await browser.newContext({viewport:{width:1440,height:1080}, acceptDownloads:true});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', () => pageErrors.push('PAGE_ERROR'));
  const login = await context.request.post(origin + '/api/login', {headers:{Origin:origin}, data:{secret}});
  assert.ok(login.ok());
  const {csrf} = await login.json();
  const headers = {Origin:origin, 'X-CSRF-Token':csrf};
  const request = await context.request.post(origin + '/api/requests', {headers,
    data:{command:crypto.randomUUID().replaceAll('-',''), expected:0, text:'Non-private offline SFX browser fixture', kind:'Sound effects', purpose:'Offline test only'}});
  const saved = await request.json();
  const plan = await context.request.post(origin + '/api/sfx/plans', {headers,
    data:{command:crypto.randomUUID().replaceAll('-',''), request:saved.id, revision:1, seconds:0.1, seed:42}});
  assert.ok(plan.ok());
  const run = await plan.json();
  check('prepared immutable plan says Nothing started', run.message === 'Nothing started');
  await page.goto(origin);
  await page.locator('#workspace').waitFor({state:'visible'});
  check('local-tool method and no-agent disclosure visible', (await page.locator('.capability').innerText()).includes('Local Stable Audio - existing video producer tool') && (await page.locator('.capability').innerText()).includes('Direct local tool route; no Hermes agent conversation'));
  check('normal Review and create stays disabled even in offline harness', await page.locator('#generate').isDisabled());
  check('prepared plan is not a fake queued/generated result', (await page.locator('#runs').innerText()).includes('Prepared') && await page.locator('#takes .take').count() === 0);
  const start = await context.request.post(`${origin}/api/sfx/runs/${run.id}/start`, {headers,data:{}});
  assert.ok(start.ok());
  await expect.poll(async () => {
    const response = await context.request.get(`${origin}/api/sfx/runs/${run.id}`);
    return (await response.json()).status;
  }, {timeout:10000}).toBe('Ready for review');
  await page.reload();
  await page.locator('#workspace').waitFor({state:'visible'});
  const snapshot = await context.request.get(origin + '/api/state');
  check('offline state read succeeds after retention', snapshot.ok());
  const state = await snapshot.json();

  check('offline state contains original retained candidate', state.takes.some(take => take.id === run.candidate));
  await page.locator('#takes .take').waitFor();
  check('fixture run and take explicitly labeled Test only - not generated', (await page.locator('#runs').innerText()).includes('Test only - not generated') && (await page.locator('#takes .tag').innerText()).includes('Test only - not generated'));
  check('fixture output is not advertised as Imported or native agent generation', !(await page.locator('#takes .tag').innerText()).includes('Imported') && !(await page.locator('#takes .tag').innerText()).includes('Hermes agent'));
  await page.getByRole('button', {name:'Load player',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('audio').src.startsWith('blob:'));
  const duration = await page.locator('audio').evaluate(async audio => {
    await audio.play();
    await new Promise((resolve,reject) => { audio.onended = resolve; audio.onerror = reject; });
    return audio.duration;
  });
  check('actual offline retained fixture decodes and plays in browser', duration === 0.1);
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', {name:'Download original',exact:true}).click();
  const download = await downloadEvent;
  const destination = path.join(home, 'destination.wav');
  await download.saveAs(destination);
  const retained = await context.request.get(`${origin}/api/takes/${run.candidate}/media`);
  const data = fs.readFileSync(destination);
  check('actual fixture download equals owner-scoped retained bytes', data.equals(await retained.body()));
  const decoded = spawnSync('ffmpeg', ['-v','error','-i',destination,'-f','null','-'], {encoding:'utf8'});
  check('independent ffmpeg decoder accepts downloaded offline fixture', decoded.status === 0);
  const effects = fs.readFileSync(path.join(home, 'offline-tool/effects.jsonl'), 'utf8').trim().split('\n');
  check('one actual fake-child effect only', effects.length === 1);
  check('recorded effect uses only the test executable', effects.every(line => JSON.parse(line).argv[0] === path.join(home,'offline-tool/fixture-worker')));
  check('offline browser has no runtime errors', pageErrors.length === 0);
  await page.screenshot({path:path.join(evidence,'offline-producer.png'),fullPage:true});
  const result = {qualification:'Offline argv-native fixture only; NOT live generation', checks, pageErrors,
    destinationBytes:data.length, destinationHash:crypto.createHash('sha256').update(data).digest('hex'),
    fakeChildEffects:effects.length};
  fs.writeFileSync(path.join(evidence,'offline-browser-results.json'), JSON.stringify(result,null,2) + '\n');
  console.log(JSON.stringify(result,null,2));
} finally {
  await browser?.close();
  if (server.exitCode === null) {
    const exited = new Promise(resolve => server.once('exit',resolve));
    server.kill('SIGTERM');
    await exited;
  }
  fs.rmSync(home,{recursive:true,force:true});
}
