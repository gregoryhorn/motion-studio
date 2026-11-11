// CF-F1 OFFLINE ONLY: visible catalog/method truth and actual two-adapter artifacts.
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
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'motion-flexibility-'));
const evidence = path.join(process.cwd(), 'docs/evidence');
const secret = crypto.randomBytes(32).toString('hex');
fs.writeFileSync(path.join(home, 'test-secret'), secret, {mode:0o600});
const origin = 'http://127.0.0.1:18767';
const checks = [], artifacts = [], pageErrors = [];
const check = (name, value) => { assert.ok(value, name); checks.push(name); };
const server = spawn('python', ['-m','tests.producer_server','--home',home,'--port','18767','--flexibility'], {stdio:'ignore'});
let browser;
try {
  let healthy = false;
  for (let n = 0; n < 100; n++) {
    if (server.exitCode !== null) throw new Error('Owned flexibility server exited');
    try { if ((await fetch(origin)).ok) { healthy = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.ok(healthy);
  browser = await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE, headless:true, args:['--no-sandbox']});
  const context = await browser.newContext({viewport:{width:1440,height:1080}, acceptDownloads:true});
  const page = await context.newPage();
  page.on('pageerror', () => pageErrors.push('PAGE_ERROR'));
  const login = await context.request.post(origin + '/api/login', {headers:{Origin:origin}, data:{secret}});
  assert.ok(login.ok());
  const {csrf} = await login.json();
  const headers = {Origin:origin,'X-CSRF-Token':csrf};
  const savedResponse = await context.request.post(origin + '/api/requests', {headers, data:{command:crypto.randomUUID().replaceAll('-',''), expected:0, kind:'Sound effects', text:'Non-private flexibility browser fixture'}});
  const saved = await savedResponse.json();
  await page.goto(origin);
  await page.locator('#workspace').waitFor({state:'visible'});
  await page.getByRole('button', {name:'Tools',exact:true}).click();
  const catalogText = await page.locator('#tools').innerText();
  for (const label of ['Setup needed', 'APP_MISSING', 'Restricted for this use', 'USE_RESTRICTED', 'RESOURCE_BUSY', 'RUNTIME_DRIFT', 'Offline tested only', 'Unsupported app/interface/version']) {
    check(`visible catalog explains ${label}`, catalogText.includes(label));
  }
  check('controlled passive setup and no user-authored code disclosed', (await page.locator('#other-info').innerText()).includes('passive setup') && (await page.locator('#other-info').innerText()).includes('No user-authored'));
  check('no fixture or real binding advertised Ready', !(await page.locator('#app-catalog').innerText()).includes('Ready'));
  check('Add existing app available without enabling generation', await page.getByRole('button',{name:'Add existing app',exact:true}).isEnabled() && await page.locator('#generate').isDisabled());
  await page.screenshot({path:path.join(evidence,'f1-catalog.png'),fullPage:true});
  for (const directory of ['portable-a','portable-b','resource','restricted','missing','stale']) {
    check(`open setup/status/selection did not execute ${directory}`, !fs.existsSync(path.join(home,directory,'effects.jsonl')));
  }
  await page.getByRole('button',{name:'Create',exact:true}).click();
  check('all five media choices remain', await page.locator('[name=kind]').count() === 5);
  check('BYO remains visible', await page.getByRole('heading',{name:'Import an existing WAV'}).isVisible());
  const snapshot = await (await context.request.get(origin + '/api/state')).json();
  const historical = await context.newPage();
  await historical.goto(origin);
  await historical.locator('#workspace').waitFor({state:'visible'});
  for (const adapter of ['test-render-cli', 'test-stable-cli']) {
    const record = snapshot.app_bindings.find(row => row.descriptor.id === adapter && row.reason === 'OFFLINE_ONLY');
    for (const reason of ['RESOURCE_BUSY', 'USE_RESTRICTED']) {
      const action = reason === 'RESOURCE_BUSY' ? 'Review current resource issue' : 'Resolve the named use restriction';
      await historical.evaluate(async ({record, saved, reason, action}) => {
        const {renderApps} = await import('/apps.js');
        const projected = {...record, current_revision:record.revision + 1, reason, action,
          availability:reason === 'RESOURCE_BUSY' ? 'Unavailable' : 'Restricted for this use'};
        renderApps({app_bindings:[projected], app_methods:[{request:saved.id, binding:record.binding,
          revision:record.revision, operation:record.descriptor.operations[0]}]}, saved, false, 'Sound effects', async()=>{});
      }, {record, saved, reason, action});
      check(`F1-R01 ${adapter} ${reason} selected original revision`,
        await historical.locator('#app-method').inputValue() === `${record.binding}:${record.revision}:${record.descriptor.operations[0]}`);
      const method = await historical.locator('#method-state').innerText();
      check(`F1-R01 ${adapter} ${reason} current reason/action and historical qualification`,
        method.includes(reason) && method.includes(action) && method.includes(record.qualification));
      check(`F1-R01 ${adapter} ${reason} catalog agrees`, (await historical.locator('#app-catalog').textContent()).includes(reason));
    }
  }
  await historical.close();
  check('F1-R01 method/catalog projections start nothing', ['portable-a','portable-b'].every(directory => !fs.existsSync(path.join(home,directory,'effects.jsonl'))));
  await page.getByRole('button',{name:'Tools',exact:true}).click();
  await page.getByRole('button',{name:'Add existing app',exact:true}).click();
  await expect(page.locator('#setup-checks')).toContainText('No process');
  check('setup declares passive bounded checks before submission', (await page.locator('#setup-checks').innerText()).includes('1 MiB'));
  check('setup shows complete interface, media, local destination and cost/use disclosure', /stable-audio-cli-v1/.test(await page.locator('#setup-description').innerText()) && /Sound effects/.test(await page.locator('#setup-description').innerText()) && /Free\/local/.test(await page.locator('#setup-description').innerText()));
  const allowedLocation = await page.locator('#setup-location').inputValue();
  await page.locator('#setup-location').fill('/not-approved');
  await page.getByRole('button',{name:'Save binding',exact:true}).click();
  await expect(page.locator('#setup-error')).toContainText('LOCATION_DENIED');
  check('setup error retains proposed location and useful action', await page.locator('#setup-location').inputValue() === '/not-approved' && (await page.locator('#setup-error').innerText()).includes('Choose a location'));
  await page.locator('#setup-location').fill(allowedLocation);
  await page.getByRole('button',{name:'Save binding',exact:true}).click();
  await expect(page.locator('#setup-result')).toContainText('Binding saved; not yet qualified');
  await page.getByRole('button',{name:'Check setup',exact:true}).click();
  await expect(page.locator('#setup-result')).toContainText('Passive setup check complete');
  check('setup success is disabled and not Ready', (await page.locator('#setup-result').innerText()).includes('generation remains disabled') && await page.locator('#generate').isDisabled());
  const setupState = await (await context.request.get(origin + '/api/state')).json();
  const setupBinding = setupState.app_bindings.find(item => item.descriptor.id === 'stable-audio-local' && item.qualification === 'Setup checked');
  check('save/check/open created zero run effects', setupState.runs.length === 0 && setupBinding.enabled === false);
  const concurrentSetup = await context.request.post(origin + '/api/apps/bindings',{headers,data:{adapter:'stable-audio-local',adapter_version:1,interface_version:'stable-audio-cli-v1',executable:allowedLocation,binding:setupBinding.binding,expected:setupBinding.revision}});
  assert.ok(concurrentSetup.ok());
  await page.getByRole('button',{name:'Save binding',exact:true}).click();
  await expect(page.locator('#setup-error')).toContainText('BINDING_CONFLICT');
  check('setup CAS conflict retains proposal and does not substitute method', await page.locator('#setup-location').inputValue() === allowedLocation && (await (await context.request.get(origin + '/api/state')).json()).app_methods.length === 0);
  await page.locator('#setup-location').fill('/not-approved'); // Controlled display value, not a private location in evidence.
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  check('setup stacks at narrow/text-scaled viewport', await page.locator('#setup-location').evaluate(node => node.getBoundingClientRect().right <= innerWidth));
  await page.screenshot({path:path.join(evidence,'setup-narrow.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1080});
  await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
  await page.getByRole('button',{name:'Return to request',exact:true}).click();
  check('setup returns to request without auto-selection', await page.locator('#app-method').inputValue() === '');
  for (const [adapter, options, directory] of [
    ['test-render-cli', {frame_count:4410,timbre:'soft'}, 'portable-b'],
    ['test-stable-cli', {seconds:0.1,seed:7}, 'portable-a']
  ]) {
    const record = snapshot.app_bindings.find(row => row.descriptor.id === adapter && row.reason === 'OFFLINE_ONLY');
    const operation = record.descriptor.operations[0];
    const value = `${record.binding}:${record.revision}:${operation}`;
    await page.locator('#app-method').selectOption(value);
    await expect(page.locator('#method-state')).toContainText(record.descriptor.name);
    await expect(page.locator('#status')).toContainText('Method saved');
    check(`${adapter} selection discloses offline scope and destination`, (await page.locator('#method-state').innerText()).includes('Offline tested only') && (await page.locator('#method-state').innerText()).includes('Local'));
    check(`${adapter} selection starts nothing`, !fs.existsSync(path.join(home,directory,'effects.jsonl')));
    const planResponse = await context.request.post(origin + '/api/apps/plans', {headers,data:{command:crypto.randomUUID().replaceAll('-',''),request:saved.id,revision:1,binding:record.binding,binding_revision:record.revision,operation,options}});
    assert.ok(planResponse.ok());
    const run = await planResponse.json();
    assert.ok((await context.request.post(`${origin}/api/sfx/runs/${run.id}/start`,{headers,data:{}})).ok());
    await expect.poll(async () => (await (await context.request.get(`${origin}/api/sfx/runs/${run.id}`)).json()).status,{timeout:10000}).toBe('Ready for review');
    await page.reload();
    await page.locator('#workspace').waitFor({state:'visible'});
    await expect(page.locator('#app-method')).toHaveValue(value);
    check(`${adapter} reopen retains explicit method`, await page.locator('#app-method').inputValue() === value);
    const card = page.locator('.take').filter({has:page.getByRole('heading',{name:'Test-only ' + record.descriptor.name,exact:true})});
    await card.waitFor();
    check(`${adapter} take has synthetic provenance`, (await card.locator('.tag').innerText()).includes('Test only - not generated'));
    const downloadEvent = page.waitForEvent('download');
    await card.getByRole('button',{name:'Download original',exact:true}).click();
    const download = await downloadEvent;
    const destination = path.join(home,directory + '.wav');
    await download.saveAs(destination);
    const bytes = fs.readFileSync(destination);
    const retained = await context.request.get(`${origin}/api/takes/${run.candidate}/media`);
    check(`${adapter} same scoped retrieval returns exact downloaded bytes`, bytes.equals(await retained.body()));
    const decoded = spawnSync('ffmpeg',['-v','error','-i',destination,'-f','null','-'],{encoding:'utf8'});
    check(`${adapter} independent decoder passes`, decoded.status === 0);
    check(`${adapter} actual child count exactly one`, fs.readFileSync(path.join(home,directory,'effects.jsonl'),'utf8').trim().split('\n').length === 1);
    artifacts.push({adapter,bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),fakeChildEffects:1});
  }
  check('Review and create remains disabled', await page.locator('#generate').isDisabled());
  await page.getByRole('button',{name:'Productions',exact:true}).click();
  check('Production scope remains explicit and unimplemented', (await page.locator('#other-info').innerText()).includes('Sound effects, Music, Voice, Image and Video') && (await page.locator('#other-info').innerText()).includes('Not implemented'));
  await page.getByRole('button',{name:'Create',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  check('method controls remain within narrow viewport', await page.locator('#app-method').evaluate(item => item.getBoundingClientRect().right <= window.innerWidth));
  await page.screenshot({path:path.join(evidence,'f1-method-narrow.png'),fullPage:true});
  check('no browser runtime errors', pageErrors.length === 0);
  const result = {qualification:'Two TEST interfaces only; no second real app or live generation qualified', checks, artifacts, pageErrors};
  fs.writeFileSync(path.join(evidence,'f1-browser-results.json'),JSON.stringify(result,null,2) + '\n');
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
