// Integrated existing workspace plus explicit, fail-closed emerging UI hooks.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {expect} = require(path.join(process.env.PLAYWRIGHT_PACKAGE, 'test.js'));
const command = () => crypto.randomUUID().replaceAll('-', '');
const checks = [], blocked = [], errors = [];
const check = (name, value) => {assert.ok(value, name); checks.push(name);};
const adapter = process.env.WORKSPACE_E2E_ADAPTER ?
  pathToFileURL(path.resolve(process.env.WORKSPACE_E2E_ADAPTER)).href : new URL('./packaged.mjs', import.meta.url).href;
const harness = await (await import(adapter)).createHarness();
const {page, rpc} = harness;
const {target, otherRoot, otherProfile} = harness;
assert.ok(target?.root && target?.profile && otherRoot && otherProfile, 'EXPLICIT_SCOPE_TARGETS_REQUIRED');
const button = name => page.getByRole('button', {name, exact:true});
// Reopen lives in the More menu of the project bar.
const reopen = async () => {await page.locator('details.ms-more').evaluate(node => {node.open = true;});
  await button('Reopen project').click();
  // The menu does not close itself; close it so it cannot cover narrow-layout controls.
  await page.locator('details.ms-more').evaluate(node => {node.open = false;});};
const call = async (method, payload = {}) => {
  const result = await rpc({op:'rpc', method:'production.' + method, payload:{session_id:target.root, ...payload}});
  assert.ok(!result.error, 'PRODUCTION_' + method.toUpperCase()); return result;
};
const mutate = async (operation, current, fields) => (await call(operation,
  {command:command(), production:current.id, expected:current.revision, ...fields})).current;
const counts = () => rpc({op:'counts'});
const protectedCounts = value => Object.fromEntries(['requests', 'takes', 'local_runs', 'media_files',
  'productions', 'production_revisions', 'imports', 'generator_calls'].map(key => [key, value[key]]));
let failure = false;
try {
  page.on('pageerror', () => errors.push('PAGE_ERROR'));
  const source = await rpc({op:'seed'}), alternative = await rpc({op:'seed', sample:1400});
  const expected = Buffer.from(source.bytes, 'base64');
  let current = (await call('create', {command:command(), title:'Controlled browser production',
    brief:{text:'Controlled workspace lifecycle'}, kinds:['Sound effects','Music','Voice','Image','Video']})).current;
  const asset = current.assets[0].id;
  for (const row of [source, alternative]) current = await mutate('link_take', current,
    {asset, request:row.request, take:row.take});
  current = await mutate('select_take', current, {asset, request:source.request, take:source.take});
  const before = await counts();
  await harness.navigate();
  await button('Production').click();
  await reopen();
  await expect(page.getByRole('region', {name:'Review'})).toBeVisible();
  const selectedIdentity = await harness.identity();
  check('selected chat root and profile match explicit fixture target',
    selectedIdentity.root === target.root && selectedIdentity.profile === target.profile);
  await button('Plan').click();
  check('five media asset inventory remains visible', await page.locator('.production-asset').count() === 5);
  await button('Review').click();
  // The seeded take is an imported file, so it opens in the single-take viewer.
  await button('Open viewer').click();
  const audio = page.locator('.media-review audio');
  await expect(audio).toBeVisible();
  await expect.poll(() => audio.evaluate(element => element.readyState)).toBeGreaterThanOrEqual(2);
  const facts = await audio.evaluate(element => ({duration:element.duration, paused:element.paused,
    width:element.getBoundingClientRect().width}));
  check('visible actual decoded media has finite duration and no autoplay',
    facts.duration > 0 && Number.isFinite(facts.duration) && facts.paused && facts.width > 0);
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link', {name:'Save / download original WAV', exact:true}).click();
  const download = await downloaded;
  check('existing reviewed selected WAV download is exact original bytes',
    fs.readFileSync(await download.path()).equals(expected));
  await page.reload(); await button('Production').click(); await reopen();
  await expect(page.getByRole('region', {name:'Review'})).toBeVisible();
  assert.deepEqual(protectedCounts(await counts()), protectedCounts(before));
  check('page reload and native reopen observe without duplicate work', true);
  await rpc({op:'reopen'});
  await reopen();
  check('cold service reopen retains exact selected take',
    (await call('open', {production:current.id})).current.assets[0].selected_take === source.take);
  await button('Brief').click();
  await page.getByRole('textbox', {name:'Brief', exact:true}).fill('Controlled revised browser brief');
  await button('Save brief').click();
  await expect(page.getByRole('textbox', {name:'Brief', exact:true})).toHaveValue('Controlled revised browser brief');
  await expect.poll(async () => (await call('open', {production:current.id})).current.brief.text)
    .toBe('Controlled revised browser brief');
  current = (await call('open', {production:current.id})).current;
  check('native brief edit retains approved output but marks it stale',
    current.assets[0].stale && current.assets[0].selected_take === source.take);
  await button('References').click();
  await page.getByLabel('Retained Quick Create take').selectOption(source.take);
  await page.getByLabel('Reference label').fill('Controlled linked reference');
  await button('Save as reference').click();
  await expect(page.getByRole('heading', {name:'Controlled linked reference', exact:true})).toBeVisible();
  await button('Plan').click();
  await page.getByText('Dependencies and references', {exact:true}).click();
  await page.getByRole('checkbox', {name:'Controlled linked reference', exact:true}).check();
  await button('Save asset').click();
  await expect.poll(async () => (await call('open', {production:current.id})).current.assets[0].references.length).toBe(1);
  await button('Review').click();
  await button('Keep this take').click();
  await expect.poll(async () => (await call('open', {production:current.id})).current.assets[0].stale).toBe(false);
  current = (await call('open', {production:current.id})).current;
  check('native reusable reference and asset plan pins accepted with same retained take',
    current.assets[0].selected_take === source.take && current.assets[0].selection_references.length === 1);
  const rejected = await rpc({op:'rpc', method:'production.select_take', payload:{session_id:target.root,
    command:command(), production:current.id, expected:1, asset, request:alternative.request, take:alternative.take}});
  check('integrated stale write cannot replace selected output', rejected.error === 'PRODUCTION_STALE_REVISION' &&
    (await call('open', {production:current.id})).current.assets[0].selected_take === source.take);
  await page.setViewportSize({width:760, height:900});
  await button('Plan').click();
  const image = page.locator('.production-asset').nth(3);
  await image.focus(); await image.press('Enter');
  await expect(page.getByRole('heading', {name:'4. Image', exact:true})).toBeVisible();
  check('narrow keyboard asset selection works without drag', await image.evaluate(element =>
    document.activeElement === element && element.getBoundingClientRect().width > 0));
  await page.setViewportSize({width:380, height:900});
  await button('Review').click();
  check('reflow keeps named review and asset selection visible',
    await page.getByRole('list', {name:'Planned assets'}).isVisible() && await button('Plan').isVisible());
  check('reflow page has no horizontal overflow', await page.evaluate(() =>
    document.documentElement.scrollWidth <= window.innerWidth));
  await harness.selectScope({root:otherRoot, profile:target.profile});
  await expect(page.locator('audio[src^="blob:"]')).toHaveCount(0);
  await expect(page.getByText('Controlled browser production', {exact:true})).toHaveCount(0);
  check('switching selected chat clears private projection and media', true);
  await harness.selectScope({root:target.root, profile:otherProfile});
  await expect(page.locator('audio[src^="blob:"]')).toHaveCount(0);
  check('profile change cannot retain private playable media', true);
  await harness.selectScope(target);
  await reopen();
  await expect(page.getByRole('region', {name:'Review'})).toBeVisible();
  const file = {name:'controlled.wav', mimeType:'audio/wav', buffer:expected};
  if (harness.cancelInput) {
    const prior = await counts();
    await harness.cancelInput({page, file, production:current.id, asset});
    assert.deepEqual(protectedCounts(await counts()), protectedCounts(prior));
    check('input chooser cancellation has no mutation or producer effect', true);
  } else blocked.push('cancelInput');
  if (harness.importTake) {
    const previous = (await call('open', {production:current.id})).current;
    const imported = await harness.importTake({page, file, production:current.id, asset});
    current = (await call('open', {production:current.id})).current;
    check('UI import adds an alternative without replacing selected output',
      current.assets[0].selected_take === previous.assets[0].selected_take &&
      current.assets[0].takes.some(take => take.id === imported.take && take.request === imported.request));
    const chunk = await call('chunk', {production:current.id, asset, request:imported.request,
      take:imported.take, offset:0});
    check('UI imported alternative retains actual controlled bytes', Buffer.from(chunk.bytes, 'base64').equals(expected));
  } else blocked.push('importTake');
  if (harness.exportSelected) {
    const exported = await harness.exportSelected({page, production:current.id, asset,
      reviewAlternative:alternative.take});
    check('selected export ignores alternative review and retains exact bytes', Buffer.isBuffer(exported) && exported.equals(expected));
  } else blocked.push('exportSelected');
  if (harness.pendingInputScopeChange) {
    const prior = await counts();
    await harness.pendingInputScopeChange({page, file, production:current.id, asset,
      selectScope:harness.selectScope});
    assert.deepEqual(protectedCounts(await counts()), protectedCounts(prior));
    check('obsolete input continuation cannot mutate after scope away-and-back', true);
  } else blocked.push('pendingInputScopeChange');
  if (harness.reviewImageVideo) {
    const media = await harness.reviewImageVideo({page});
    await expect(media.image).toBeVisible();
    check('actual imported Image is decoded and visible', await media.image.evaluate(element =>
      element instanceof HTMLImageElement && element.complete && element.naturalWidth > 0 && element.naturalHeight > 0));
    await expect(media.video).toBeVisible();
    await expect.poll(() => media.video.evaluate(element => element.readyState)).toBeGreaterThanOrEqual(2);
    check('actual imported Video has decoded frames and finite duration without autoplay',
      await media.video.evaluate(element => element instanceof HTMLVideoElement && element.videoWidth > 0 &&
        element.videoHeight > 0 && Number.isFinite(element.duration) && element.duration > 0 && element.paused));
  } else blocked.push('reviewImageVideo');
  check('all workspace actions performed zero producer calls', (await counts()).generator_calls === 0);
  check('no uncaught page errors', errors.length === 0);
} catch (error) {
  failure = true;
  // Assertion labels contain only controlled fixture data. Do not serialize raw errors.
  errors.push('WORKSPACE_ASSERTION_FAILED');
  console.error('Workspace check failed after: ' + (checks.at(-1) || 'setup'));
} finally {
  if(process.env.WORKSPACE_SCREENSHOTS){
    fs.mkdirSync(process.env.WORKSPACE_SCREENSHOTS,{recursive:true});
    await page.screenshot({path:path.join(process.env.WORKSPACE_SCREENSHOTS,'workspace-e2e.png'),fullPage:true});
  }
  await harness.close();
  const receipt = {mode:harness.mode, realWindowsQualified:false, checks, blocked, errors,
    status:failure||blocked.length ? 'failed' : 'passed',
    limitations:['No real host/Windows, perceptual review or assistive-technology qualification.']};
  if (process.env.WORKSPACE_E2E_RECEIPT) fs.writeFileSync(process.env.WORKSPACE_E2E_RECEIPT,
    JSON.stringify(receipt, null, 2) + '\n', {flag:'wx'});
  console.log(JSON.stringify(receipt));
}
process.exitCode = failure ? 1 : blocked.length ? 2 : 0;
