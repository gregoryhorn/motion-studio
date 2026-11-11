// Real browser + real owned loopback process; only non-private fixtures.
// Set PLAYWRIGHT_PACKAGE and CHROME_EXECUTABLE to existing installed paths.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn, spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {saveRegressions} from './browser-save-regressions.mjs';
import {originNames} from './browser-origin-names.mjs';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE);
const root = process.cwd();
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'motion-browser-'));
const evidence = path.join(root, 'docs/evidence');
fs.mkdirSync(evidence, {recursive: true});
const port = 18765;
const origin = `http://127.0.0.1:${port}`;
const secret = crypto.randomBytes(32).toString('hex');
const secretFile = path.join(home, 'test-secret');
fs.writeFileSync(secretFile, secret, {mode: 0o600});
const fixture = path.join(home, 'non-private-tone.wav');
const make = spawnSync('python', ['-c', 'from tests.fixtures import wav; import sys; from pathlib import Path; Path(sys.argv[1]).write_bytes(wav(seconds=1))', fixture], {cwd: root});
assert.equal(make.status, 0);
let server, browser;
async function start() {
  server = spawn('python', ['-m', 'studio', '--test-only', '--port', String(port), '--state', path.join(home, 'var'), '--secret-file', secretFile], {cwd: root, stdio: 'ignore'});
  for (let attempt = 0; attempt < 100; attempt++) {
    if (server.exitCode !== null) throw new Error('Owned test server exited');
    try { if ((await fetch(origin)).ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error('Test server did not become healthy');
}
async function stop() {
  if (!server || server.exitCode !== null) return;
  const exited = new Promise(resolve => server.once('exit', resolve));
  server.kill('SIGTERM');
  await exited;
}
const checks = [];
const check = (name, value) => { assert.ok(value, name); checks.push(name); };
try {
  await start();
  browser = await chromium.launch({executablePath: process.env.CHROME_EXECUTABLE, headless: true, args: ['--no-sandbox']});
  const context = await browser.newContext({viewport: {width: 1440, height: 1080}, acceptDownloads: true});
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const login = await context.request.post(`${origin}/api/login`, {headers: {Origin: origin}, data: {secret}});
  check('test owner session accepted', login.ok());
  const cookie = (await context.cookies()).find(x => x.name === 'studio_session');
  check('session HttpOnly and Strict', cookie.httpOnly && cookie.sameSite === 'Strict');
  await page.goto(origin);
  await page.locator('#workspace').waitFor({state: 'visible'});
  check('generation button disabled', await page.locator('#generate').isDisabled());
  check('local tool route disclosed without agent conversation claim', (await page.locator('.capability').innerText()).includes('Local Stable Audio - existing video producer tool') && (await page.locator('.capability').innerText()).includes('Direct local tool route; no Hermes agent conversation'));
  check('five media types', await page.locator('[name=kind]').count() === 5);
  check('real empty state', (await page.locator('#takes').innerText()).includes('No creations yet'));
  await page.screenshot({path: path.join(evidence, 'desktop-empty.png'), fullPage: true});
  const kinds = ['Sound effects', 'Music', 'Voice', 'Image', 'Video'];
  for (const kind of kinds) {
    await page.getByRole('button', {name: 'New request', exact: true}).click();
    await page.locator('#text').fill(`Non-private browser fixture: ${kind}`);
    await page.getByRole('radio', {name: kind, exact: true}).check();
    await page.getByRole('button', {name: 'Save request', exact: true}).click();
    await page.getByText('Request saved. Nothing generated or started.', {exact:true}).waitFor();
    await page.waitForFunction(() => document.querySelector('#save-state').textContent.includes('revision'));
    if (kind === 'Image' || kind === 'Video') check(`${kind} import disabled`, await page.locator('#file').isDisabled());
  }
  // Reopen the actual audio request, then import non-private fixture bytes.
  await page.getByText('Saved requests', {exact:true}).click();
  await page.locator('#requests button').filter({hasText: 'Sound effects'}).click();
  await page.locator('#file').setInputFiles(fixture);
  await page.locator('#takes .take').waitFor();
  check('one imported take only', await page.locator('#takes .take').count() === 1);
  check('import, technical/listening/rights distinct', /Imported/.test(await page.locator('#takes').innerText()) && /Listening review not recorded/.test(await page.locator('#takes').innerText()) && /Usage rights not verified/.test(await page.locator('#takes').innerText()));
  const provenance = page.locator('#takes .take details').first();
  check('F04 exact provenance is secondary and collapsed', !(await provenance.evaluate(node => node.open)));
  await provenance.locator('summary').click();
  check('F04 full take and request identity remains discoverable', /Take [a-f0-9]{32} · Request [a-f0-9]{32}, revision/.test(await provenance.innerText()));
  await provenance.locator('summary').click();
  await page.getByRole('button', {name: 'Load player', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('audio').src.startsWith('blob:'));
  check('no autoplay', await page.locator('audio').evaluate(audio => audio.paused));
  const playback = await page.locator('audio').evaluate(async audio => {
    await audio.play();
    await new Promise((resolve, reject) => { audio.onended = resolve; audio.onerror = reject; });
    return {duration: audio.duration, position: audio.currentTime};
  });
  check('browser decodes and plays actual retained WAV', playback.duration === 1 && playback.position === 1);
  await page.getByRole('combobox', {name: /Listening outcome/}).selectOption('Needs work');
  await page.getByText('Listening outcome saved. Usage rights remain unverified.', {exact:true}).waitFor();
  await page.getByRole('button', {name: 'Use take', exact:true}).click();
  await page.locator('.take.selected').waitFor();
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', {name: 'Download original', exact:true}).click();
  const download = await downloadEvent;
  const destination = path.join(home, 'retrieved.wav');
  await download.saveAs(destination);
  check('actual destination bytes equal selected original', fs.readFileSync(destination).equals(fs.readFileSync(fixture)));
  check('click reports offered, not verified receipt', (await page.locator('#status').innerText()).startsWith('Download offered.'));
  const fixtureHash = crypto.createHash('sha256').update(fs.readFileSync(destination)).digest('hex');
  fs.copyFileSync(destination, path.join(evidence, 'retrieved-non-private-tone.wav'));
  // A second intentional import must not steal selection; hostile display names stay text.
  const originalState = await (await context.request.get(`${origin}/api/state`)).json();
  const originalTake = originalState.takes[0].id;
  const secondBytes = Buffer.from(fs.readFileSync(fixture));
  secondBytes[44] ^= 16;
  await page.locator('#file').setInputFiles({name:'<img src=x onerror=alert(1)>.wav', mimeType:'audio/wav', buffer:secondBytes});
  await page.waitForFunction(() => document.querySelectorAll('#takes .take').length === 2);
  const secondState = await (await context.request.get(`${origin}/api/state`)).json();
  check('second import retains old selected take', secondState.requests.find(x => x.selected)?.selected === originalTake && secondState.takes.length === 2);
  check('hostile display filename is text, not HTML', await page.locator('#takes img').count() === 0 && (await page.locator('#takes').innerText()).includes('<img src=x'));
  const secondDownloadEvent = page.waitForEvent('download');
  await page.locator('#takes .take').first().getByRole('button', {name:'Download original',exact:true}).click();
  const secondDownload = await secondDownloadEvent;
  const secondDestination = path.join(home, 'second-retrieved.wav');
  await secondDownload.saveAs(secondDestination);
  check('download names exact unselected candidate independently', fs.readFileSync(secondDestination).equals(secondBytes));
  // A real server stop/start must retain IDs and review, no import or generation on reopen.
  const before = await (await context.request.get(`${origin}/api/state`)).json();
  await stop();
  await start();
  await page.reload();
  await page.locator('.take.selected').waitFor();
  const after = await (await context.request.get(`${origin}/api/state`)).json();
  check('cold process restart keeps original request/take/review/selection', JSON.stringify(before.requests) === JSON.stringify(after.requests) && JSON.stringify(before.takes) === JSON.stringify(after.takes) && after.takes.find(x => x.id === originalTake).review === 'Needs work');
  check('cold process restart restores exact active saved request', await page.locator('#text').inputValue() === 'Non-private browser fixture: Sound effects');
  await page.screenshot({path: path.join(evidence, 'desktop-imported.png'), fullPage: true});
  // Unsaved navigation has Save / Discard / Stay and retains exact edits.
  await page.locator('#text').fill('Unsaved non-private fixture');
  await page.getByRole('button', {name: 'Productions', exact:true}).click();
  await page.locator('#unsaved').waitFor({state: 'visible'});
  await page.getByRole('button', {name:'Stay', exact:true}).click();
  check('Stay retains unsaved edits', await page.locator('#text').inputValue() === 'Unsaved non-private fixture');
  await page.getByRole('button', {name: 'Productions', exact:true}).click();
  await page.getByRole('button', {name:'Discard', exact:true}).click();
  check('Production honest partial scope', (await page.locator('#other-info').innerText()).includes('Not implemented in this slice'));
  await page.getByRole('button', {name: 'Create', exact:true}).click();
  // A real concurrent revision must reject UI save while retaining the unsaved copy.
  const active = after.requests.find(x => x.id === after.takes.find(t => t.id === originalTake).request);
  const sessionData = await (await context.request.get(`${origin}/api/session`)).json();
  const concurrent = await context.request.post(`${origin}/api/requests`, {headers:{Origin:origin,'X-CSRF-Token':sessionData.csrf}, data:{command:crypto.randomUUID().replaceAll('-',''),id:active.id,expected:active.revision,text:'Concurrent non-private edit',kind:'Sound effects'}});
  check('concurrent request edit succeeds independently', concurrent.ok());
  await page.locator('#text').fill('Keep my non-private copy');
  await page.getByRole('button', {name:'Save request',exact:true}).click();
  await page.locator('#conflict').waitFor({state:'visible'});
  check('stale UI save preserves user text', await page.locator('#text').inputValue() === 'Keep my non-private copy');
  await page.getByRole('button', {name:'Keep copy',exact:true}).click();
  await page.locator('#conflict').waitFor({state:'hidden'});
  check('Keep copy saves separately without overwriting concurrent request', (await (await context.request.get(`${origin}/api/state`)).json()).requests.some(x => x.id === active.id && x.text === 'Concurrent non-private edit'));
  await page.setViewportSize({width:390, height:844});
  check('390px no horizontal overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path: path.join(evidence, 'narrow-imported.png'), fullPage:true});
  await page.setViewportSize({width:1440, height:1080});
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  check('200 percent root text scale no horizontal overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  check('F04 plan stacks at 200 percent root text scale', await page.evaluate(() => {
    const composer = document.querySelector('.columns > div').getBoundingClientRect();
    const plan = document.querySelector('aside').getBoundingClientRect();
    return plan.top >= composer.bottom && plan.width >= composer.width - 1;
  }));
  await page.screenshot({path:path.join(evidence, 'text-200.png'), fullPage:true});
  await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
  // Tab-based keyboard traversal visibly reaches composer without mouse.
  await page.locator('[data-nav="Create"]').focus();
  for (let n=0;n<5;n++) await page.keyboard.press('Tab');
  check('keyboard reaches request composer', await page.locator('#text').evaluate(x => x === document.activeElement));
  await saveRegressions(context, origin, fixture, check);
  await originNames(context, origin, fs.readFileSync(fixture).toString('base64'), check);
  check('no browser runtime errors', pageErrors.length === 0);
  fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify({checks, fixtureOrigin:'Locally synthesized 440 Hz test fixture; not producer generation; not human listening', destinationHash:fixtureHash, destinationBytes:fs.statSync(destination).size, pageErrors, limitations:['Loopback test only; P01 private preview not delivered','Automated media playback is not actual human listening','200% root text scale is not full browser/accessibility conformance']}, null, 2));
  console.log(JSON.stringify({passed:checks.length, checks, destinationBytes:fs.statSync(destination).size, pageErrors}, null, 2));
} finally {
  await browser?.close();
  await stop();
  fs.rmSync(home, {recursive:true, force:true});
}
