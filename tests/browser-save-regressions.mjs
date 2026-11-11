// Controlled response timing around real HTTP commits; non-private fixtures only.
import assert from 'node:assert/strict';

async function fields(page, text, purpose, kind) {
  await page.locator('#text').fill(text);
  await page.locator('#purpose').fill(purpose);
  await page.getByRole('radio', {name: kind, exact: true}).check();
}
async function values(page) {
  return page.evaluate(() => ({text: document.querySelector('#text').value,
    purpose: document.querySelector('#purpose').value,
    kind: document.querySelector('[name=kind]:checked').value}));
}
async function saved(page) {
  await page.waitForFunction(() => document.querySelector('#save-state').textContent.startsWith('Saved'));
}
async function submit(page) {
  await page.locator('#status').evaluate(node => { node.textContent = ''; });
  await page.getByRole('button', {name: 'Save request', exact: true}).click();
  await page.getByText('Request saved. Nothing generated or started.', {exact: true}).waitFor();
  await saved(page);
}
async function holdSave(page) {
  let release, received;
  const gate = new Promise(resolve => { release = resolve; });
  const committed = new Promise(resolve => { received = resolve; });
  const payloads = [];
  const handler = async route => {
    payloads.push(route.request().postDataJSON());
    const response = await route.fetch();
    assert.equal(response.status(), 200);
    received();
    await gate;
    await route.fulfill({response});
  };
  await page.route('**/api/requests', handler);
  return {committed, payloads, release, remove: () => page.unroute('**/api/requests', handler)};
}
async function cleanRefresh(page, other, fixture, check) {
  await fields(page, 'F01 initial fixture', 'Initial usage', 'Sound effects');
  await submit(page);
  await page.locator('#file').setInputFiles(fixture);
  await page.locator('#takes .take').first().waitFor();
  await other.goto(page.url());
  await saved(other);
  const updated = {text: 'F01 other tab fixture', purpose: 'Other usage', kind: 'Voice'};
  await fields(other, updated.text, updated.purpose, updated.kind);
  await submit(other);
  // Review changes refresh state without changing the request revision themselves.
  await page.getByRole('combobox', {name: /Listening outcome/}).first().selectOption('Needs work');
  await page.getByText('Listening outcome saved. Usage rights remain unverified.', {exact: true}).waitFor();
  assert.deepEqual(await values(page), updated);
  check('F01 clean review refresh adopts text, purpose and kind atomically', true);
  await page.locator('#text').fill('F01 subsequent local fixture');
  await submit(page);
  await other.reload();
  await saved(other);
  assert.deepEqual(await values(other), {...updated, text: 'F01 subsequent local fixture'});
  check('F01 subsequent save does not revert other tab fields', true);
  await page.locator('#text').fill('F01 dirty local fixture');
  await fields(other, 'F01 newer external fixture', 'New external usage', 'Music');
  await submit(other);
  await page.getByRole('combobox', {name: /Listening outcome/}).first().selectOption('Matches request');
  await page.getByText('Listening outcome saved. Usage rights remain unverified.', {exact: true}).waitFor();
  assert.deepEqual(await values(page), {...updated, text: 'F01 dirty local fixture'});
  await page.getByRole('button', {name: 'Save request', exact: true}).click();
  await page.locator('#conflict').waitFor({state: 'visible'});
  check('F01 dirty review refresh retains old base and produces stale conflict', true);
  await page.getByRole('button', {name: 'Reload saved', exact: true}).click();
  await page.locator('#conflict').waitFor({state: 'hidden'});
}
async function delayedSave(page, check) {
  await fields(page, 'F02 submitted fixture', 'Submitted usage', 'Voice');
  await page.locator('#status').evaluate(node => { node.textContent = ''; });
  const held = await holdSave(page);
  await page.getByRole('button', {name: 'Save request', exact: true}).click();
  await held.committed;
  const newer = {text: 'F02 newer local fixture', purpose: 'Newer usage', kind: 'Music'};
  await fields(page, newer.text, newer.purpose, newer.kind);
  held.release();
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Request saved'));
  assert.deepEqual(await values(page), newer);
  assert.equal(await page.locator('#save-state').innerText(), 'Unsaved');
  check('F02 delayed Save preserves all later fields as Unsaved', true);
  await held.remove();
  const next = page.waitForRequest(request => request.url().endsWith('/api/requests'));
  await submit(page);
  const payload = (await next).postDataJSON();
  assert.notEqual(payload.command, held.payloads[0].command);
  assert.equal(payload.expected, held.payloads[0].expected + 1);
  check('F02 newer edits use new command against acknowledged revision', true);
  await page.reload();
  await saved(page);
  assert.deepEqual(await values(page), newer);
  check('F02 newer snapshot persists on reopen', true);
}
async function retrySave(page, check) {
  await page.locator('#text').fill('F02 uncertain receipt fixture');
  const payloads = [];
  const handler = async route => {
    payloads.push(route.request().postDataJSON());
    const response = await route.fetch();
    assert.equal(response.status(), 200);
    if (payloads.length === 1) await route.abort('failed');
    else await route.fulfill({response});
  };
  await page.route('**/api/requests', handler);
  await page.getByRole('button', {name: 'Save request', exact: true}).click();
  await page.locator('#error').filter({hasText: 'Failed to fetch'}).waitFor();
  await submit(page);
  assert.equal(payloads.length, 2);
  assert.deepEqual(payloads[1], payloads[0]);
  check('F02 lost receipt retry keeps original command and exact payload', true);
  await page.unroute('**/api/requests', handler);
}
async function refreshDuringSave(page, check) {
  await page.locator('#text').fill('F02 before state refresh fixture');
  let release, received;
  const gate = new Promise(resolve => { release = resolve; });
  const refreshing = new Promise(resolve => { received = resolve; });
  const handler = async route => {
    const response = await route.fetch();
    received();
    await gate;
    await route.fulfill({response});
  };
  await page.route('**/api/state', handler);
  await page.locator('#status').evaluate(node => { node.textContent = ''; });
  await page.getByRole('button', {name: 'Save request', exact: true}).click();
  await refreshing;
  const newer = {text: 'F02 edits during state refresh', purpose: 'State refresh usage', kind: 'Video'};
  await fields(page, newer.text, newer.purpose, newer.kind);
  release();
  await page.getByText('Request saved; newer edits remain Unsaved.', {exact: true}).waitFor();
  assert.deepEqual(await values(page), newer);
  assert.equal(await page.locator('#save-state').innerText(), 'Unsaved');
  check('F02 edits during post-save state refresh remain Unsaved', true);
  await page.unroute('**/api/state', handler);
  await submit(page);
}
async function newRequestSave(page, check) {
  await page.getByRole('button', {name: 'New request', exact: true}).click();
  await fields(page, 'F02 new submitted fixture', 'New request usage', 'Voice');
  const held = await holdSave(page);
  await page.getByRole('button', {name: 'Save request', exact: true}).click();
  await held.committed;
  await fields(page, 'F02 new later fixture', 'Later request usage', 'Music');
  // Repeated clicks while pending must not dispatch another mutable command.
  await page.getByRole('button', {name: 'Save request', exact: true}).click();
  held.release();
  await page.getByText('Request saved; newer edits remain Unsaved.', {exact: true}).waitFor();
  assert.equal(held.payloads.length, 1);
  assert.equal(held.payloads[0].id, null);
  assert.equal(await page.locator('#text').inputValue(), 'F02 new later fixture');
  await held.remove();
  const next = page.waitForRequest(request => request.url().endsWith('/api/requests'));
  await submit(page);
  const update = (await next).postDataJSON();
  assert.ok(update.id);
  assert.equal(update.expected, 1);
  assert.notEqual(update.command, held.payloads[0].command);
  check('F02 pending new-request save retains edits, deduplicates click and binds original new ID', true);
}
async function saveLeave(page, check) {
  await page.locator('#text').fill('F02 save-leave submitted fixture');
  await page.getByRole('button', {name: 'Productions', exact: true}).click();
  const held = await holdSave(page);
  await page.locator('#save-leave').click();
  await held.committed;
  // Stay is available while the bounded request is pending; then continue editing.
  await page.locator('#stay').click();
  await fields(page, 'F02 save-leave newer fixture', 'Retain before leaving', 'Image');
  await page.getByRole('button', {name: 'Productions', exact: true}).click();
  held.release();
  await page.getByText('Request saved; newer edits remain Unsaved.', {exact: true}).waitFor();
  assert.equal(await page.locator('#unsaved').isVisible(), true);
  assert.equal(await page.locator('#create').isVisible(), true);
  assert.equal(await page.locator('#save-state').innerText(), 'Unsaved');
  check('F02 pending Save-and-leave cannot navigate past later unsaved edits', true);
  await held.remove();
  await page.locator('#save-leave').click();
  await page.locator('#unsaved').waitFor({state: 'hidden'});
  assert.equal(await page.locator('#other-title').innerText(), 'Productions');
  check('F02 Save-and-leave navigates after latest snapshot acknowledged', true);
}
export async function saveRegressions(context, origin, fixture, check) {
  const page = await context.newPage();
  const other = await context.newPage();
  const errors = [];
  for (const tab of [page, other]) tab.on('pageerror', () => errors.push('PAGE_ERROR'));
  try {
    await page.goto(origin);
    await page.locator('#workspace').waitFor({state: 'visible'});
    await page.getByRole('button', {name: 'New request', exact: true}).click();
    await cleanRefresh(page, other, fixture, check);
    await delayedSave(page, check);
    await retrySave(page, check);
    await refreshDuringSave(page, check);
    await newRequestSave(page, check);
    await saveLeave(page, check);
    check('F01/F02 regression tabs have no browser runtime errors', errors.length === 0);
  } finally {
    // Avoid a beforeunload prompt when diagnosing a failed preservation assertion.
    await other.close({runBeforeUnload: false});
    await page.close({runBeforeUnload: false});
  }
}
