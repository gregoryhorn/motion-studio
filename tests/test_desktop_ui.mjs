/* Deferred unit/contract suite. AUTHORING ONLY until the parent completes
 * assembly and the user's commit-before-enable/test gate. This harness replaces
 * SDK/React imports ONLY in an in-memory test module. It is not a runtime UI,
 * test asset service, playback simulation, or evidence of host qualification.
 * After that gate: node --test tests/test_desktop_ui.mjs
 */
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { webcrypto, createHash } from 'node:crypto';

const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8');
if (!globalThis.crypto) globalThis.crypto = webcrypto;
function atom(initial) {
  let value = initial;
  const listeners = new Set();
  return { get: () => value, set: next => { value = next; for (const listener of listeners) listener(value); }, subscribe(listener) { listeners.add(listener); listener(value); return () => listeners.delete(listener); }, listeners };
}
const queries = [], cancelled = [], navigated = [];
const owner = atom({ connectionId: 'local', profile: 'default' });
const profile = atom('default'), connection = atom(null);
const host = {
  state: { focusedSessionOwner: owner, profile, connectionId: connection, focusedStoredSessionId: atom('test-session') },
  activeConnectionId: () => connection.get(),
  navigate: path => navigated.push(path),
  request: async (method, value) => { assert.equal(method, 'projects.list'); assert.deepEqual(value, { profile: 'default' }); return { projects: [], active_id: null }; },
  composer: {}
};
const sdk = { atom, host, useValue: a => a.get(), useQuery: spec => { queries.push(spec); return { data: undefined, isPending: false, refetch: async () => ({}) }; }, queryClient: { cancelQueries: spec => { cancelled.push(spec); return Promise.resolve(); }, invalidateQueries: async () => {} }, PANES_AREA: 'panes', ROUTES_AREA: 'routes', PALETTE_AREA: 'palette', KEYBINDS_AREA: 'keybinds' };
const react = { createElement: (type, props, ...children) => ({ type, props, children }), useEffect: () => {}, useRef: value => ({ current: value }), useState: value => [typeof value === 'function' ? value() : value, () => {}] };
globalThis.__motionDesktopUnitHarness = { sdk, react };
const instrumented = source
  .replace(/^import \{[^\n]+\} from '@hermes\/plugin-sdk';$/m, 'const { atom, host, useValue, useQuery, queryClient, PANES_AREA, ROUTES_AREA, PALETTE_AREA, KEYBINDS_AREA } = globalThis.__motionDesktopUnitHarness.sdk;')
  .replace(/^import \{[^\n]+\} from 'react';$/m, 'const { createElement: h, useEffect, useRef, useState } = globalThis.__motionDesktopUnitHarness.react;')
  + '\nexport const unitHarness = { command, reconcile, transmit, stage, saveDraft, read, capture, useRead, transitionOwner, ownerKey, scopeKey, compositionKey, recoveryIntention, recoveryOriginals, loadRecoveryReview, checkRecoveryFresh, finishRecovery, hasRecoveryJournal, RecoveryDialog };\n';
const ui = await import('data:text/javascript;base64,' + Buffer.from(instrumented).toString('base64'));
const scope = { backend_instance_id: 'test-backend', connection_id: 'local', profile_id: 'test-profile-id', native_project_id: 'test-native-id' };
const version = () => ({ schema_version: 'composition.v1', version_id: 'test-version', composition_revision: 1, format: { width: 1920, height: 1080, fps: { num: 24, den: 1 }, sample_rate: 48000, channels: 2, duration_frames: 96 }, tracks: [{ track_id: 'test-track', name: 'Picture', kind: 'video', order: 0, locked: false, visible: true, muted: false, clip_ids: ['test-clip'] }], clips: [{ clip_id: 'test-clip', track_id: 'test-track', start_frame: 0, end_frame: 96, source_mapping: { domain: 'frame', in_index: 0, out_index: 96, rate: { num: 24, den: 1 }, speed: { num: 1, den: 1 } }, subject: { kind: 'asset', id: 'test-source', version_id: 'test-source-version' }, linked_group_id: null, enabled: true }], scenes: [], layers: [], effects: [], audio_buses: [], captions: [], production_documents: [] });
let cleanup = null;
function setup(rest = async () => ({ api_version: 'ui.v1', scope, data: {}, command: { status: 'committed' } }), initial = null) {
  owner.set({ connectionId: 'local', profile: 'default' }); profile.set('default'); connection.set(null);
  const contributions = [], settings = [], timers = [], stored = new Map(initial ? [['motion-studio-ui.v1', initial]] : []), disposed = [];
  const ctx = { rest, storage: { get: (key, fallback) => stored.get(key) ?? fallback, set: (key, value) => stored.set(key, structuredClone(value)), remove: key => stored.delete(key) }, registerMany: cs => { contributions.push(...cs); return () => {}; }, registerSettingsPage: page => { settings.push(page); return () => {}; }, onDispose: f => disposed.push(f), setTimeout: (f, ms) => { const timer = { f, ms, cancelled: false }; timers.push(timer); return () => { timer.cancelled = true; }; }, os: { writeClipboard: async () => true } };
  ui.default.register(ctx);
  ui.studioState.set({ ...ui.studioState.get(), owner: owner.get(), project: 'test-native-id', composition: 'test-composition', storageError: null, offline: false });
  cleanup = () => disposed.forEach(f => f());
  return { ctx, contributions, settings, timers, stored, disposed };
}
afterEach(() => { cleanup?.(); cleanup = null; queries.length = 0; });

// These fixtures are explicitly unit data. Production plugin.js has none.
// Deferred recovery fixtures only: these are not observed backend/media receipts.
function recoveryFixture() {
  const sourceVersion = { ...version(), composition_id: 'test-composition', sha256: 'a'.repeat(64), asset_refs: [], settings: {} };
  const headVersion = { ...structuredClone(sourceVersion), version_id: 'unit-current-head', composition_revision: 2, sha256: 'b'.repeat(64) };
  const intention = { base: { version_id: sourceVersion.version_id, composition_revision: 1 }, operations: [{ op: 'clip.move', clip_id: 'test-clip', start_frame: 1 }], acknowledged_dependency_ids: ['unit-dependent'] };
  return { sourceVersion, headVersion, intention, schemas: { 'unit.schema': { schema_ref: 'unit-only-schema', revision: 1 } }, documentRebindIds: [] };
}
function recoveryModel() {
  return { s: ui.studioState.get(), scope, key: ui.unitHarness.compositionKey(scope), ppath: '/projects/test-native-id', cpath: '/projects/test-native-id/compositions/test-composition', can: op => ['OP-RECOVERY-REVIEW', 'OP-RECOVER-AS-NEW'].includes(op) };
}
test('recovery review hashes exact immutable source graph and schema bytes, not current head graph', async () => {
  const f = recoveryFixture(), before = structuredClone(f);
  f.headVersion.clips = [];
  const review = await ui.makeRecoveryReview(f);
  const graph = Object.fromEntries(['schema_version', 'format', 'tracks', 'clips', 'scenes', 'layers', 'effects', 'audio_buses', 'captions', 'asset_refs', 'settings', 'production_documents'].map(k => [k, f.sourceVersion[k]]));
  assert.equal(review.base_graph_sha256, await ui.publicHash(graph));
  assert.equal(review.schema_catalog_sha256, await ui.publicHash(f.schemas));
  assert.equal(review.source.sha256, 'a'.repeat(64));
  assert.equal(review.current_head.sha256, 'b'.repeat(64));
  assert.deepEqual(Object.keys(review).sort(), ['base_graph_sha256', 'current_head', 'schema_catalog_sha256', 'source', 'transaction']);
  assert.deepEqual(review.transaction, { operations: f.intention.operations, dependency_policy: 'reject_unlisted', acknowledged_dependency_ids: ['unit-dependent'], document_rebind_ids: [] });
  review.transaction.operations[0].start_frame = 9;
  assert.deepEqual(f.sourceVersion, before.sourceVersion); assert.deepEqual(f.intention, before.intention);
});
test('recovery refuses incomplete source/schema/document values and mismatched retained base', async () => {
  for (const mutate of [f => { delete f.sourceVersion.settings; }, f => { f.schemas = null; }, f => { f.intention.base.version_id = 'wrong-base'; }, f => { f.sourceVersion.production_documents = [{ document_id: 'unit-doc' }]; }, f => { f.documentRebindIds = ['unit-doc', 'unit-doc']; }]) {
    const f = recoveryFixture(); mutate(f); await assert.rejects(() => ui.makeRecoveryReview(f), /Recovery blocked/);
  }
});
test('recovery token binds source, head, hash, catalog, expiry and explicit affected/blocker facts', async () => {
  const review = await ui.makeRecoveryReview(recoveryFixture());
  const prepared = { review, review_sha256: await ui.publicHash(review), preconditions: { catalog_revision: 7 } };
  const token = { review_token: 'unit-token', review_sha256: prepared.review_sha256, source: review.source, current_head: review.current_head, catalog_revision: 7, affected_entities: ['test-clip'], blockers: [], expires_at: '2030-01-01T00:00:00Z' };
  const now = Date.parse('2029-01-01T00:00:00Z');
  assert.doesNotThrow(() => ui.validateRecoveryToken(prepared, token, now));
  for (const patch of [{ review_sha256: 'c'.repeat(64) }, { source: { ...review.source, version_id: 'other' } }, { current_head: { ...review.current_head, version_id: 'other' } }, { catalog_revision: 8 }, { expires_at: '2028-01-01T00:00:00Z' }, { expires_at: 'invalid' }, { blockers: ['unit-blocker'] }, { review_token: '' }]) assert.throws(() => ui.validateRecoveryToken(prepared, { ...token, ...patch }, now), /expired, mismatched or blocked/);
  const absent = { ...token }; delete absent.affected_entities;
  assert.throws(() => ui.validateRecoveryToken(prepared, absent, now), /blocked/);
});
test('ambiguous original is status-queried only and never replayed', async () => {
  const calls = [], key = JSON.stringify(Object.values(scope)) + ':unused';
  const journal = { operation: 'OP-TRANSACTION', owner: { connectionId: 'local', profile: 'default' }, state: 'unknown', body: { command_id: 'unit-original-command', scope, input: {}, preconditions: {} }, request_sha256: 'a'.repeat(64) };
  setup(async (path, options) => { calls.push({ path, options }); return { api_version: 'ui.v1', scope, data: { command_id: journal.body.command_id, request_sha256: journal.request_sha256, status: 'pending', effect_state: 'pending' } }; }, { drafts: {}, journals: { [key]: journal }, scopes: {} });
  const model = recoveryModel();
  await assert.rejects(() => ui.unitHarness.recoveryOriginals(model, ui.unitHarness.capture()), /remains ambiguous/);
  assert.equal(calls.length, 1); assert.match(calls[0].path, /\/commands\/unit-original-command/);
  assert.notEqual(calls[0].options?.method, 'POST');
});
test('recovery capability gate and disconnected owner block before source loading', async () => {
  const calls = []; setup(async (...args) => { calls.push(args); throw new Error('must not read'); });
  const model = recoveryModel();
  await assert.rejects(() => ui.unitHarness.loadRecoveryReview({ ...model, can: op => op === 'OP-RECOVERY-REVIEW' }, []), /both recovery operations/);
  connection.set('other-connection');
  await assert.rejects(() => ui.unitHarness.loadRecoveryReview(model, []), /context changed/);
  assert.equal(calls.length, 0);
});
test('new recovery selects only after committed receipt plus exact version and retains original journal', async () => {
  const originalKey = JSON.stringify([scope.backend_instance_id, scope.connection_id, scope.profile_id, scope.native_project_id]) + ':test-composition';
  const recoveryKey = originalKey + ':recover-as-new:unit', receiptId = 'unit-new-receipt';
  const original = { operation: 'OP-TRANSACTION', owner: { connectionId: 'local', profile: 'default' }, state: 'failed', body: { command_id: 'unit-original', scope }, request_sha256: 'a'.repeat(64) };
  const recoveredVersion = { ...recoveryFixture().sourceVersion, composition_id: 'unit-new-composition', version_id: 'unit-new-version', transaction_receipt_id: receiptId };
  const recovery = { operation: 'OP-RECOVER-AS-NEW', owner: original.owner, state: 'unknown', recovery_original_key: originalKey, body: { command_id: 'unit-recovery', scope }, request_sha256: 'b'.repeat(64), result: null };
  const calls = [], env = setup(async (path) => {
    calls.push(path);
    const data = path.includes('/commands/') ? { command_id: recovery.body.command_id, request_sha256: recovery.request_sha256, status: 'committed', effect_state: 'committed', receipt_id: receiptId } : path.includes('/receipts/') ? { receipt_id: receiptId, kind: recovery.operation, command_id: recovery.body.command_id, request_sha256: recovery.request_sha256, scope, effect_state: 'committed', subject_refs: [{ kind: 'composition', id: recoveredVersion.composition_id }, { kind: 'version', id: recoveredVersion.version_id }] } : { version: recoveredVersion };
    assert.equal(ui.studioState.get().composition, 'test-composition');
    return { api_version: 'ui.v1', scope, data };
  }, { drafts: {}, journals: { [originalKey]: original, [recoveryKey]: recovery }, scopes: {} });
  await ui.unitHarness.finishRecovery(recoveryModel(), recoveryKey);
  assert.equal(ui.studioState.get().composition, 'unit-new-composition');
  assert.deepEqual(env.stored.get('motion-studio-ui.v1').journals[originalKey], original);
  assert.equal(calls.length, 3); assert.match(calls[1], /\/projects\/test-native-id\/receipts\//);
  assert.match(ui.studioState.get().message, /Original local draft\/journal retained, unreplayed/);
});

test('recovery loads original version and full immutable documents instead of projecting current graph', async () => {
  const f = recoveryFixture(), document = { document_id: 'unit-document', document_version_id: 'unit-document-version', kind: 'unit-only', value: { original: 'retained Unicode Ω' } };
  document.sha256 = await ui.publicHash(document.value);
  const { value, ...pin } = document; f.sourceVersion.production_documents = [pin];
  const key = JSON.stringify([scope.backend_instance_id, scope.connection_id, scope.profile_id, scope.native_project_id]) + ':test-composition';
  const original = { operation: 'OP-TRANSACTION', owner: { connectionId: 'local', profile: 'default' }, state: 'failed', body: { scope, command_id: 'unit-original', preconditions: f.intention.base, input: { operations: f.intention.operations, dependency_policy: 'reject_unlisted', acknowledged_dependency_ids: f.intention.acknowledged_dependency_ids } }, request_sha256: 'a'.repeat(64) };
  const calls = [];
  setup(async path => {
    calls.push(path); const url = new URL(path, 'https://unit.invalid');
    const data = url.pathname.endsWith('/bootstrap') ? { schemas: f.schemas } : url.pathname.includes('/documents/') ? document : url.pathname.endsWith('/compositions') ? { catalog_revision: 7 } : { version: url.searchParams.get('version_id') === f.sourceVersion.version_id ? f.sourceVersion : f.headVersion };
    return { api_version: 'ui.v1', scope, data };
  }, { drafts: {}, journals: { [key]: original }, scopes: {} });
  const prepared = await ui.unitHarness.loadRecoveryReview(recoveryModel(), ['unit-document']);
  assert.equal(prepared.review.source.version_id, f.sourceVersion.version_id);
  assert.equal(prepared.review.current_head.version_id, f.headVersion.version_id);
  assert.deepEqual(prepared.review.transaction.document_rebind_ids, ['unit-document']);
  assert.ok(calls.some(path => path.includes('/documents/unit-document?version_id=test-version')));
  assert.equal(prepared.review.base_graph_sha256, (await ui.makeRecoveryReview({ ...f, sourceVersion: { ...f.sourceVersion, production_documents: [document] }, documentRebindIds: ['unit-document'] })).base_graph_sha256);
  ui.studioState.set({ ...ui.studioState.get(), composition: 'other' });
  await assert.rejects(() => ui.unitHarness.checkRecoveryFresh(recoveryModel(), prepared), /context changed/);
});
test('unconfirmed recovery status never switches composition or launches a second POST', async () => {
  for (const status of ['pending', 'unknown', 'failed']) {
    const key = JSON.stringify([scope.backend_instance_id, scope.connection_id, scope.profile_id, scope.native_project_id]) + ':test-composition', recoveryKey = key + ':recover-as-new:unit';
    const j = { operation: 'OP-RECOVER-AS-NEW', owner: { connectionId: 'local', profile: 'default' }, state: 'unknown', recovery_original_key: key, body: { command_id: 'unit-recovery', scope }, request_sha256: 'b'.repeat(64) };
    const calls = [];
    setup(async path => { calls.push(path); return { api_version: 'ui.v1', scope, data: { status, command_id: j.body.command_id, request_sha256: j.request_sha256, effect_state: 'unknown' } }; }, { drafts: {}, journals: { [recoveryKey]: j }, scopes: {} });
    await assert.rejects(() => ui.unitHarness.finishRecovery(recoveryModel(), recoveryKey), /original remains unreplayed/);
    assert.equal(ui.studioState.get().composition, 'test-composition'); assert.equal(calls.length, 1);
    cleanup(); cleanup = null;
  }
});

test('public ESM only, no private DOM/store access or synthetic media clock', () => {
  const imports = [...source.matchAll(/^import .* from '([^']+)';$/gm)].map(m => m[1]);
  assert.deepEqual(imports, ['@hermes/plugin-sdk', 'react']);
  assert.doesNotMatch(source, /window\.hermesDesktop|document\.querySelector|innerHTML|createRoot|setInterval\(/);
  // Self-fingerprinting reads only the evaluated native-loader blob. Backend
  // and media IO must still use the supported authenticated context REST seam.
  assert.match(source, /if \(import\.meta\.url\.startsWith\('blob:'\)\) \{\s+fetch\(import\.meta\.url\)/);
  assert.equal([...source.matchAll(/\bfetch\(/g)].length, 1);
  assert.doesNotMatch(source.replace('fetch(import.meta.url)', ''), /host\.media|sendTrustedHandoff|\bfetch\(/);
  assert.match(source, /onTimeUpdate/); assert.match(source, /e\.currentTarget\.currentTime/);
});
test('six exact dock tabs; Settings is not a seventh tab', () => assert.deepEqual(ui.TABS, ['Preview', 'Assets', 'Layers', 'Inspector', 'Production', 'Jobs']));
test('separate native right and bottom pane contributions, shared Focus route', () => {
  const { contributions, settings } = setup();
  assert.equal(contributions.find(c => c.id === 'studio').data.placement, 'right');
  const bottom = contributions.find(c => c.id === 'timeline');
  assert.equal(bottom.data.placement, 'bottom');
  assert.equal(bottom.data.height, 'clamp(160px, 24vh, 280px)');
  assert.equal(bottom.data.minHeight, 'min(120px, 24vh)');
  assert.equal(bottom.data.maxHeight, '40vh');
  assert.equal(contributions.find(c => c.id === 'focus').data.path, '/motion-studio');
  assert.equal(settings.length, 1); assert.ok(contributions.every(c => typeof c.id === 'string'));
});
test('keybind uses the actual SDK defaults array contract', () => {
  const { contributions } = setup(); const bind = contributions.find(c => c.area === 'keybinds').data;
  assert.deepEqual(bind.defaults, ['mod+alt+m']); assert.equal(typeof bind.run, 'function'); assert.equal(bind.defaultCombo, undefined);
});
test('scope rejects another backend, profile, connection or native ID', () => {
  for (const key of Object.keys(scope)) assert.throws(() => ui.assertScope(scope, { ...scope, [key]: 'other' }), e => e.code === 'SCOPE_MISMATCH');
  ui.assertScope(scope, { ...scope });
});
test('unversioned facade rejected; unscoped authentication error remains meaningful', () => {
  assert.throws(() => ui.unwrap({ data: {} }, scope), e => e.code === 'CONTRACT_INCOMPATIBLE');
  assert.throws(() => ui.unwrap({ api_version: 'ui.v1', scope: {}, error: { code: 'AUTH_REQUIRED', message: 'Authenticate', effect_state: 'none' } }, scope), e => e.code === 'AUTH_REQUIRED');
});
test('frozen command deep copies all user input and uses independent UUIDs', () => {
  const input = { operations: [{ op: 'clip.enable', enabled: false }] }, pre = { composition_revision: 1, version_id: 'test-version' };
  const c = ui.frozenCommand(scope, pre, input); input.operations[0].enabled = true; pre.composition_revision = 9;
  assert.equal(c.input.operations[0].enabled, false); assert.equal(c.preconditions.composition_revision, 1);
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  assert.match(c.command_id, uuid); assert.match(c.idempotency_key, uuid); assert.notEqual(c.command_id, c.idempotency_key);
});
test('canonical request hash matches exact Node SHA-256 and does not include retry UUIDs', async () => {
  const pre = { version_id: 'test-version', composition_revision: 1 }, input = { name: 'literal Unicode Ω' }, route = '/projects/test-native-id/compositions';
  const expected = createHash('sha256').update(ui.canonical({ operation_id: 'OP-COMPOSITION-CREATE', route, scope, preconditions: pre, input })).digest('hex');
  assert.equal(await ui.requestHash('OP-COMPOSITION-CREATE', route, scope, pre, input), expected);
  assert.equal(ui.canonical({ z: 1, a: [true, null, 'x'] }), '{"a":[true,null,"x"],"z":1}');
});
test('integer fields reject fractional, infinite and out-of-range edits', () => {
  for (const bad of ['1.5', 'NaN', 'Infinity', '1e3', '', '9007199254740992', -1]) assert.throws(() => ui.safeInteger(bad));
  assert.equal(ui.safeInteger('24'), 24); assert.equal(ui.safeInteger('-8', -10, 10), -8);
});
test('rational nearest-even ties are deterministic', () => {
  assert.equal(ui.roundEven(5n, 2n), 2); assert.equal(ui.roundEven(7n, 2n), 4); assert.equal(ui.roundEven(9n, 2n), 4); assert.throws(() => ui.roundEven(1n, 0n));
});
test('display timecode labels nominal NDF frame count', () => {
  assert.equal(ui.timecode(24, { num: 24, den: 1 }), '00:00:01:00');
  assert.equal(ui.timecode(30, { num: 30000, den: 1001 }), '00:00:01:00');
});
test('linked selection expands only through explicit link IDs', () => {
  const v = version(); v.clips[0].linked_group_id = 'test-link'; v.clips.push({ ...structuredClone(v.clips[0]), clip_id: 'test-audio' });
  assert.deepEqual(ui.linkedSelection(v, ['test-clip']), ['test-clip', 'test-audio']); assert.deepEqual(ui.linkedSelection(v, ['test-clip'], true), ['test-clip']);
});
test('move preserves duration/source; locked participants block the whole move', () => {
  const v = version(), move = ui.buildMove(v, ['test-clip'], 8);
  assert.equal(move.placements[0].start_frame, 8); const result = ui.projectDraft(v, [move]);
  assert.equal(result.clips[0].end_frame, 104); assert.deepEqual(result.clips[0].source_mapping, v.clips[0].source_mapping); assert.equal(v.clips[0].start_frame, 0);
  v.tracks[0].locked = true; assert.throws(() => ui.buildMove(v, ['test-clip'], 8), /locked/);
});
test('trim uses source rate/speed, not output-frame arithmetic', () => {
  const clip = version().clips[0]; clip.source_mapping.rate = { num: 48, den: 1 }; clip.source_mapping.out_index = 192;
  const op = ui.buildTrim(clip, 4, 92, { num: 24, den: 1 }); assert.equal(op.source_mapping.in_index, 8); assert.equal(op.source_mapping.out_index, 184);
  clip.source_mapping.rate = { num: 25, den: 1 }; assert.throws(() => ui.buildTrim(clip, 1, 96, { num: 24, den: 1 }), /conform/);
});
test('split rejects boundaries and unsupported fractional source cuts', () => {
  const v = version(); assert.throws(() => ui.buildSplit(v, ['test-clip'], 0)); assert.throws(() => ui.buildSplit(v, ['test-clip'], 96));
  const ops = ui.buildSplit(v, ['test-clip'], 48); assert.equal(ops.length, 1); assert.equal(ops[0].op, 'clip.split');
  const local = ui.projectDraft(v, ops); assert.equal(local.clips.length, 2); assert.equal(local.clips[0].end_frame, 48); assert.equal(local.clips[1].source_mapping.in_index, 48);
  v.clips[0].source_mapping.rate = { num: 25, den: 1 }; assert.throws(() => ui.buildSplit(v, ['test-clip'], 1), /conform/);
});
test('insertion planner splits residuals for overwrite and pins ripple affected IDs', () => {
  const v = version(); v.tracks[0].overlap_policy = 'exclusive';
  const insert = { op: 'clip.insert', create_ref: crypto.randomUUID(), track_id: 'test-track', start_frame: 24, end_frame: 48, subject: { kind: 'asset', id: 'test-source', version_id: 'test-source-version' }, source_mapping: { domain: 'frame', in_index: 0, out_index: 24, rate: { num: 24, den: 1 }, speed: { num: 1, den: 1 } }, linked_group_id: null, enabled: true };
  assert.throws(() => ui.buildInsertion(v, insert, 'place'), /occupied/);
  const overwrite = ui.buildInsertion(v, insert, 'overwrite'); assert.equal(overwrite.filter(o => o.op === 'clip.split').length, 2); assert.equal(overwrite.at(-1).op, 'clip.insert');
  const graph = ui.projectDraft(v, overwrite); assert.deepEqual(graph.clips.map(c => [c.start_frame, c.end_frame]).sort((a, b) => a[0] - b[0]), [[0, 24], [24, 48], [48, 96]]);
  const ripple = ui.buildInsertion(v, insert, 'insert'); const op = ripple.find(o => o.op === 'timeline.ripple'); assert.equal(op.delta_frames, 24); assert.equal(op.expected_affected_ids.length, 1);
  v.tracks.push({ ...v.tracks[0], track_id: 'audio-track', kind: 'audio', order: 1 });
  v.clips[0].linked_group_id = 'test-link';
  v.clips.push({ ...structuredClone(v.clips[0]), clip_id: 'audio-clip', track_id: 'audio-track' });
  const linked = ui.buildInsertion(v, insert, 'overwrite');
  const result = ui.projectDraft(v, linked);
  assert.equal(result.clips.filter(c => c.track_id === 'audio-track').length, 2);
  const left = result.clips.filter(c => c.start_frame === 0), right = result.clips.filter(c => c.start_frame === 48);
  assert.equal(left[0].linked_group_id, left[1].linked_group_id);
  assert.equal(right[0].linked_group_id, right[1].linked_group_id);
  assert.notEqual(left[0].linked_group_id, right[0].linked_group_id);
  const multi = ui.buildInsertion(v, insert, 'insert').find(o => o.op === 'timeline.ripple');
  assert.deepEqual(new Set(multi.track_ids), new Set(['test-track', 'audio-track']));
  assert.equal(multi.expected_affected_ids.length, 2);
  v.tracks[1].locked = true;
  assert.throws(() => ui.buildInsertion(v, insert, 'insert'), /locked/);
  assert.throws(() => ui.buildInsertion(v, insert, 'overwrite'), /locked/);
});
test('exact insertion rejects guessed frame durations and links atomic new tracks', () => {
  const v = version(), asset = { asset_id: 'a', asset_version_id: 'av', duration_frames: 100, rate: { num: 25, den: 1 } };
  assert.throws(() => ui.exactAssetPlacement(v, asset, 'test-track', 0, 1, 0), /conform/);
  assert.throws(() => ui.exactAssetPlacement(v, { ...asset, duration_frames: undefined }, 'test-track', 0, 25, 0), /unknown/);
  const picture = ui.exactAssetPlacement(v, asset, 'new-video', 0, 25, 96);
  assert.equal(picture.end_frame, 120);
  const audio = { ...ui.exactAssetPlacement(v, asset, 'new-audio', 0, 25, 96), subject: { kind: 'asset', id: 'audio', version_id: 'audio-version' } };
  const tracks = ['video', 'audio'].map((kind, i) => ({ op: 'track.create', create_ref: 'new-' + kind, kind, name: kind, order: i + 1, overlap_policy: kind === 'audio' ? 'mix' : 'exclusive' }));
  const ops = ui.buildInsertion(v, [picture, audio], 'place', tracks);
  assert.deepEqual(ops.slice(0, 2), tracks); assert.equal(ops.at(-1).op, 'link.set');
  assert.deepEqual(ops.at(-1).clip_ids, [picture.create_ref, audio.create_ref]);
  const graph = ui.projectDraft(v, ops);
  assert.equal(graph.clips.at(-1).linked_group_id, graph.clips.at(-2).linked_group_id);
  assert.throws(() => ui.buildInsertion(v, [picture, { ...audio, end_frame: 121 }], 'place', tracks), /conform/);
  v.asset_refs = [{ asset_id: 'audio', asset_version_id: 'audio-version', kind: 'audio', sample_rate: 44100 }];
  assert.throws(() => ui.buildInsertion(v, audio, 'place', tracks), /sample rate/);
});
test('source-tick split uses exact PTS and refuses fractional cuts', () => {
  const v = version();
  v.clips[0].source_mapping = { domain: 'source_tick', in_pts: 10, out_pts: 9610, start_pts: 10, time_base: { num: 1, den: 2400 }, conform_ref: null };
  const local = ui.projectDraft(v, ui.buildSplit(v, ['test-clip'], 24));
  assert.equal(local.clips[0].source_mapping.out_pts, 2410); assert.equal(local.clips[1].source_mapping.in_pts, 2410);
  v.clips[0].source_mapping.time_base.den = 25;
  assert.throws(() => ui.buildSplit(v, ['test-clip'], 1), /conform/);
});
test('plain delete leaves a gap and never mutates source version', () => {
  const v = version(); const result = ui.projectDraft(v, [{ op: 'entity.delete', targets: [{ kind: 'clip', id: 'test-clip' }], expected_dependency_ids: [] }]);
  assert.equal(result.clips.length, 0); assert.equal(v.clips.length, 1); assert.equal(result.tracks.length, 1);
});
test('caption import preserves literal Unicode and rounds outward', () => {
  const cues = ui.parseTimedCaptions('1\n00:00:00,020 --> 00:00:00,040\n日本語 Ω\n', { num: 24, den: 1 });
  assert.deepEqual(cues, [{ start_frame: 0, end_frame: 1, text: '日本語 Ω' }]);
  const web = ui.parseTimedCaptions('WEBVTT\n\n00:01.000 --> 00:02.000\nCaption', { num: 24, den: 1 }); assert.equal(web[0].start_frame, 24); assert.equal(web[0].end_frame, 48);
});
test('source captions retain exact times and preview clipped, excluded and repeated rows', () => {
  const v = version(); v.format.duration_frames = 120;
  v.clips[0] = { ...v.clips[0], start_frame: 24, end_frame: 72, source_mapping: { domain: 'frame', in_index: 24, out_index: 72, rate: { num: 24, den: 1 }, speed: { num: 1, den: 1 } } };
  v.clips.push({ ...structuredClone(v.clips[0]), clip_id: 'repeat', start_frame: 72, end_frame: 120 });
  const cues = ui.parseTimedCaptions('1\n00:00:00,500 --> 00:00:01,020\nclipped\n\n2\n00:00:01,020 --> 00:00:02,000\ninside\n\n3\n00:00:04,000 --> 00:00:05,000\nexcluded', v.format.fps, true);
  const preview = ui.mapCaptionImport(v, cues, ['test-clip', 'repeat']);
  assert.match(preview.blocked, /explicitly/);
  assert.equal(preview.rows.filter(r => r.status === 'excluded').length, 2);
  assert.equal(preview.rows.filter(r => r.status === 'clipped').length, 2);
  assert.ok(preview.rows.filter(r => r.status !== 'excluded').every(r => r.repeated));
  const accepted = ui.mapCaptionImport(v, cues, ['test-clip', 'repeat'], true);
  assert.equal(accepted.blocked, null); assert.equal(accepted.cues.length, 4);
  assert.deepEqual(accepted.cues[0], { start_frame: 24, end_frame: 25, text: 'clipped' });
  assert.deepEqual(accepted.cues[2], { start_frame: 24, end_frame: 48, text: 'inside' });
  v.clips[0].source_mapping.conform_ref = { id: 'unknown' };
  assert.throws(() => ui.mapCaptionImport(v, cues, ['test-clip'], true), /Unknown source conform/);
});
test('source-tick captions subtract observed start_pts instead of assuming zero', () => {
  const v = version();
  v.clips[0].source_mapping = { domain: 'source_tick', in_pts: 2500, out_pts: 6500, start_pts: 1500, time_base: { num: 1, den: 1000 }, conform_ref: null };
  const cues = ui.parseTimedCaptions('1\n00:00:01,020 --> 00:00:02,000\nexact', v.format.fps, true);
  assert.deepEqual(ui.mapCaptionImport(v, cues, ['test-clip'], true).cues, [{ start_frame: 0, end_frame: 24, text: 'exact' }]);
});
test('malformed or executable caption markup is not silently stripped', () => {
  for (const text of ['1\n00:00:01,000 --> 00:00:00,000\nbackwards', '1\n00:00:00,000 --> 00:00:01,000\n<b>markup</b>', '1\ninvalid --> other\ntext']) assert.throws(() => ui.parseTimedCaptions(text, { num: 24, den: 1 }));
});
test('prepared composer insertion preserves draft, reads back exact text and never submits', async () => {
  const previous = host.composer, calls = []; let draft = 'Existing human draft';
  host.composer = { getDraft: async id => { calls.push(['get', id]); return draft; }, insertText: async (id, text, options) => { calls.push(['insert', id, text, options]); draft += '\n\n' + text; return true; }, submit: () => { throw new Error('Must not auto-submit'); } };
  try {
    const target = { owner_key: ui.unitHarness.ownerKey(owner.get()), session_id: 'test-session' };
    const result = await ui.insertPreparedRequest(target, 'Frozen pinned request');
    assert.equal(result.state, 'inserted_not_submitted');
    assert.ok(draft.startsWith('Existing human draft'));
    assert.deepEqual(calls.find(c => c[0] === 'insert').slice(1), ['test-session', 'Frozen pinned request', { mode: 'block' }]);
    assert.equal(calls.filter(c => c[0] === 'get').length, 2);
    await assert.rejects(ui.insertPreparedRequest({ ...target, session_id: 'other' }, 'wrong'), /changed/);
  } finally { host.composer = previous; }
});
test('production values require exact immutable document reference identity and bare hashes', () => {
  const ref = { kind: 'storyboard', document_id: 'doc', document_version_id: 'dv', schema_ref: { id: 'schema', version: 'v1', sha256: 'a'.repeat(64) }, sha256: 'b'.repeat(64) };
  const value = { ...ref, value: { panels: [] } };
  assert.equal(ui.documentMatchesReference(ref, value), true);
  for (const changed of [{ document_version_id: 'other' }, { sha256: 'c'.repeat(64) }, { kind: 'creative_plan' }, { schema_ref: { ...ref.schema_ref, sha256: 'd'.repeat(64) } }, { value: null }]) assert.equal(ui.documentMatchesReference(ref, { ...value, ...changed }), false);
  assert.equal(ui.documentMatchesReference({ ...ref, sha256: 'sha256:' + ref.sha256 }, value), false);
  assert.equal(ui.documentMatchesReference(ref, { ...ref }), false);
  assert.match(source, /\/documents\/\$\{enc\(ref.document_id\)\}/);
  assert.match(source, /version_id: model.saved\?\.version_id/);
});
test('schema form follows local advertised pins only, with no remote ref resolution', () => {
  const schema = { type: 'object', required: ['name', 'panels'], properties: { name: { type: 'string' }, panels: { type: 'array', items: { $ref: '#/$defs/Panel' } } }, $defs: { Panel: { type: 'object', required: ['duration'], properties: { duration: { type: 'integer', minimum: 1 } } } } };
  assert.deepEqual(ui.schemaSeed(schema), { name: '', panels: [] }); assert.deepEqual(ui.schemaSeed(schema.properties.panels.items, schema), { duration: 1 });
  assert.equal(ui.resolveSchema({ $ref: 'https://untrusted/schema' }, schema), null);
});
test('media requires exact same-origin authenticated Project route and range qualification', () => {
  const media = { transport: 'same_origin_cookie', range_supported: true, relative_stream_route: '/ui/v1/projects/test-native-id/media-access/test-access/bytes' };
  assert.equal(ui.qualifiedMediaRoute(media, scope), '/api/plugins/motion-studio/ui/v1/projects/test-native-id/media-access/test-access/bytes');
  for (const route of ['https://example.invalid/video', '//example.invalid/video', '/ui/v1/projects/other/media-access/a/bytes', '/ui/v1/projects/test-native-id/media-access/../bytes', '/ui/v1/projects/test-native-id/media-access/a/bytes?token=secret']) assert.throws(() => ui.qualifiedMediaRoute({ ...media, relative_stream_route: route }, scope));
  assert.throws(() => ui.qualifiedMediaRoute({ ...media, range_supported: false }, scope));
});
// Deferred authenticated-Blob unit fixtures; not real media/runtime qualification.
const blobFixture = (size = 17) => {
  const bytes = Uint8Array.from({ length: size }, (_, i) => i % 251);
  const hash = value => createHash('sha256').update(value).digest('hex');
  const media = { media_id: 'unit-media', sha256: hash(bytes) };
  const lease = { ...media, access_id: 'unit-lease', transport: 'authenticated_blob', byte_length: size, mime: 'video/mp4', expires_at: new Date(Date.now() + 60000).toISOString() };
  const chunk = (offset, length) => {
    const body = bytes.slice(offset, offset + length);
    return { ...media, mime: lease.mime, byte_length: size, display_name: 'unit-only.mp4', offset, bytes_base64: Buffer.from(body).toString('base64'), chunk_sha256: hash(body), eof: offset + body.length === size };
  };
  return { bytes, media, lease, chunk };
};
test('authenticated Blob serially validates bounded chunks and complete bytes with real WebCrypto', async () => {
  const f = blobFixture(262151), calls = []; let active = 0;
  const blob = await ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES, async (id, offset, length) => {
    assert.equal(id, 'unit-lease'); assert.equal(active++, 0); calls.push([offset, length]);
    await Promise.resolve(); active--; return f.chunk(offset, length);
  }, () => true, () => true);
  assert.deepEqual(calls, [[0, 262144], [262144, 7]]);
  assert.equal(blob.type, 'video/mp4'); assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), f.bytes);
});
test('authenticated Blob rejects unknown/unsupported MIME, invalid limits and unsafe leases before fetching', async () => {
  const f = blobFixture();
  for (const altered of [{ mime: 'text/html' }, { mime: 'image/svg+xml' }, { mime: 'application/octet-stream' }, { byte_length: 0 }, { byte_length: ui.MEDIA_BLOB_BYTES + 1 }, { byte_length: 1.5 }, { media_id: 'other' }, { sha256: '0'.repeat(64) }, { access_id: '../foreign' }, { expires_at: 'unknown' }, { expires_at: new Date(0).toISOString() }, { transport: 'unknown' }]) {
    await assert.rejects(ui.verifiedMediaBlob({ ...f.lease, ...altered }, f.media, ui.MEDIA_BLOB_BYTES, () => assert.fail('must not fetch'), () => true, () => true));
  }
  await assert.rejects(ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES + 1, () => assert.fail('must not fetch'), () => true, () => true));
  await assert.rejects(ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES, () => assert.fail('must not fetch'), () => true, () => false));
});
test('authenticated Blob rejects chunk identity/offset/bounds/base64/hash/EOF defects', async () => {
  const f = blobFixture();
  for (const altered of [{ media_id: 'other' }, { sha256: '0'.repeat(64) }, { offset: 1 }, { byte_length: 18 }, { mime: 'text/html' }, { bytes_base64: '!!!' }, { bytes_base64: Buffer.from([1]).toString('base64') }, { chunk_sha256: '0'.repeat(64) }, { eof: false }]) {
    await assert.rejects(ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES, async (_, o, n) => ({ ...f.chunk(o, n), ...altered }), () => true, () => true));
  }
  // Per-chunk integrity is not a substitute for the exact complete-byte pin.
  const wrongPin = { ...f.media, sha256: '0'.repeat(64) };
  await assert.rejects(ui.verifiedMediaBlob({ ...f.lease, ...wrongPin }, wrongPin, ui.MEDIA_BLOB_BYTES, async (_, o, n) => ({ ...f.chunk(o, n), ...wrongPin }), () => true, () => true), /Complete media SHA-256/);
});
test('authenticated Blob drops changed owner/Project after awaited fetch and WebCrypto; disconnect is not success', async () => {
  const f = blobFixture(262151); let current = true, calls = 0;
  await assert.rejects(ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES, async (_, o, n) => { calls++; current = false; return f.chunk(o, n); }, () => current, () => true), /context changed/);
  assert.equal(calls, 1);
  let checks = 0;
  await assert.rejects(ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES, async (_, o, n) => f.chunk(o, n), () => ++checks < 4, () => true), /context changed/);
  await assert.rejects(ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES, async () => { throw new Error('Disconnected'); }, () => true, () => true), /Disconnected/);
});
test('authenticated Blob refuses lease expiry during an awaited chunk', async () => {
  const f = blobFixture(), originalNow = Date.now;
  let now = originalNow(); f.lease.expires_at = new Date(now + 1000).toISOString();
  Date.now = () => now;
  try {
    await assert.rejects(ui.verifiedMediaBlob(f.lease, f.media, ui.MEDIA_BLOB_BYTES, async (_, o, n) => { now += 2000; return f.chunk(o, n); }, () => true, () => true), /expired/);
  } finally { Date.now = originalNow; }
});
test('Blob integration is explicit scoped REST, revocable, expiry-bound and never an invented binary SDK', () => {
  assert.match(source, /transport_capabilities \|\|/);
  assert.match(source, /transports\.authenticated_blob === true/);
  assert.match(source, /boot\.limits\?\.media_blob_bytes/);
  assert.match(source, /await read\(`\$\{path\}\/media-access\/\$\{enc\(id\)\}\/chunks`, \{ offset, length \}, scope, cap\)/);
  assert.match(source, /URL\.revokeObjectURL/); assert.match(source, /cancelExpiry/);
  assert.match(source, /Load verified Blob fallback/); assert.match(source, /onError: media\.fail/);
  assert.doesNotMatch(source.replace('fetch(import.meta.url)', ''), /autoPlay: true|host\.media|\bfetch\(/);
});
test('GET includes connection assertion and late prior-context data is rejected', async () => {
  let reply, called; const submitted = new Promise(resolve => { called = resolve; });
  setup(async path => { called(path); return new Promise(resolve => { reply = resolve; }); });
  const pending = ui.unitHarness.read('/bootstrap', { client_contract: 'ui.v1', client_kind: 'desktop' });
  const path = await submitted; assert.match(path, /connection_id=local/);
  owner.set({ connectionId: 'other', profile: 'default' }); reply({ api_version: 'ui.v1', scope, data: { original: true } });
  await assert.rejects(pending, /Late response|Context changed/);
});
test('verified stale frontend cannot submit a command or discard retained drafts', async () => {
  const calls = [];
  setup(async path => { calls.push(path); return { api_version: 'ui.v1', scope, data: { runtime_identity: { frontend_hash_algorithm: 'motion/import-normalized-sha256/v1', frontend_source_sha256: 'a'.repeat(64) } } }; });
  await ui.unitHarness.read('/bootstrap', { client_contract: 'ui.v1', client_kind: 'desktop' });
  ui.frontendIdentity.set({ status: 'ready', sha256: 'b'.repeat(64) });
  const before = structuredClone(ui.studioState.get().drafts);
  try {
    await assert.rejects(ui.unitHarness.command('/settings', 'OP-SETTINGS-UPDATE', scope, {}, {}), /update pending/);
    assert.equal(calls.length, 1);
    assert.deepEqual(ui.studioState.get().drafts, before);
  } finally { ui.frontendIdentity.set({ status: 'unavailable', sha256: null }); }
});
test('query polling is cache-owned, disabled when focused/ambient transport differs', () => {
  setup(); ui.unitHarness.useRead('/settings', {}, scope, true, true);
  assert.equal(queries.at(-1).refetchInterval, 5000); assert.equal(queries.at(-1).retry, false);
  owner.set({ connectionId: 'other', profile: 'default' }); ui.unitHarness.useRead('/settings', {}, scope, true, true); assert.equal(queries.at(-1).enabled, false);
});
test('unknown command outcome retains frozen request; status check does not resubmit', async () => {
  const sent = []; let storedRequest;
  setup(async (path, options) => { sent.push({ path, options }); if (options?.method === 'POST') { storedRequest = structuredClone(options.body); throw new Error('Simulated test-only lost reply'); } return { api_version: 'ui.v1', scope, data: { status: 'unknown', effect_state: 'unknown', recovery_actions: [] } }; });
  await assert.rejects(ui.unitHarness.command('/projects/test-native-id/compositions/test-composition/transactions', 'OP-TRANSACTION', scope, { version_id: 'test-version', composition_revision: 1 }, { operations: [], gesture_id: crypto.randomUUID(), summary: 'Unit request only', dependency_policy: 'reject_unlisted', acknowledged_dependency_ids: [] }, 'unit-command'), /lost reply/);
  await ui.unitHarness.reconcile('unit-command', scope);
  assert.equal(sent.filter(x => x.options?.method === 'POST').length, 1); assert.match(sent[1].path, new RegExp('/commands/' + storedRequest.command_id));
  await assert.rejects(ui.unitHarness.command('/projects/test-native-id/compositions/test-composition/transactions', 'OP-TRANSACTION', scope, {}, {}, 'unit-command'), /reconciliation/);
});
test('local multi-edit batch survives persistence; no autosave while local mode is chosen', () => {
  const env = setup(); const v = version(); ui.studioState.set({ ...ui.studioState.get(), offline: true });
  const key = ui.unitHarness.compositionKey(scope), model = { version: v, saved: v, scope, key, readOnly: false, draft: null };
  for (const offset of [1, 2, 3]) ui.unitHarness.stage(model, [ui.buildMove(v, ['test-clip'], offset)], 'Unit local edit');
  const stored = env.stored.get('motion-studio-ui.v1'); assert.equal(stored.drafts[key].operations.length, 3); assert.equal(stored.drafts[key].manual, true);
  assert.equal(env.timers.filter(t => !t.cancelled).length, 1); // timer callback itself must skip manual batches
});
test('probe preparation is inert exact context for acknowledged user-submitted composer insertion, never direct REST execution', () => {
  setup(); const a = sourceAsset(), model = sourceModel();
  const text = ui.preparedSourceProbeText(model, a, true);
  assert.match(text, /PREPARED ONLY/); assert.match(text, /not approval, execution/);
  assert.ok(text.includes(a.sha256)); assert.ok(text.includes(model.saved.version_id));
  assert.match(text, /OP-ASSET-PROBE/); assert.match(text, /full_decode/);
  const component = source.slice(source.indexOf('function SourcePreparation('), source.indexOf('function InsertDialog('));
  assert.match(component, /Direct REST probing is blocked/);
  assert.match(component, /insertPreparedRequest\(prepared.target, prepared.text\)/);
  assert.match(component, /not submitted, approved or executed/);
  assert.match(component, /sourcePreparationRequest\(model, asset, receipt, fullDecode\)/);
  assert.doesNotMatch(component, /submit\(false\)|composer\.submit|session_id\s*:\s*.*command/);
});
// Source preparation fixtures are unit-only data, not observed probe results.
const sourceAsset = () => ({ asset_id: 'unit-asset', asset_version_id: 'unit-asset-v1', sha256: 'c'.repeat(64), entity_revision: 3 });
const sourceReceipt = () => ({ receipt_id: 'unit-receipt', asset_id: 'unit-asset', asset_version_id: 'unit-asset-v1', full_decode: 'not_tested', vfr: 'no', streams: [{ index: 0, type: 'video', rate: { num: 24, den: 1 }, frame_count: 96 }] });
function sourceModel(operations = ['OP-ASSET-PROBE', 'OP-ASSET-BIND', 'OP-JOB-GET']) {
  return { scope, s: ui.studioState.get(), cpath: '/projects/test-native-id/compositions/test-composition', saved: version(), readOnly: false, can: op => operations.includes(op) };
}
test('source probe and bind use finite routes, explicit effects policy and exact CAS/pins', () => {
  setup(); const model = sourceModel(), asset = sourceAsset();
  const probe = ui.sourcePreparationRequest(model, asset, null, true);
  assert.equal(probe.operation, 'OP-ASSET-PROBE'); assert.equal(probe.route, model.cpath + '/assets/unit-asset/probe');
  assert.deepEqual(probe.input, { asset_version_id: asset.asset_version_id, sha256: asset.sha256, full_decode: true });
  assert.deepEqual(probe.preconditions, { entity_revision: 3, composition_revision: 1, version_id: 'test-version' });
  const bind = ui.sourcePreparationRequest(model, asset, sourceReceipt());
  assert.equal(bind.operation, 'OP-ASSET-BIND'); assert.equal(bind.route, model.cpath + '/assets/unit-asset/bind');
  assert.deepEqual(bind.input, { asset_version_id: asset.asset_version_id, sha256: asset.sha256, receipt_id: 'unit-receipt', stream_index: 0 });
  assert.deepEqual(bind.preconditions, probe.preconditions);
  for (const input of [probe.input, bind.input]) { assert.equal(input.approval_refs, undefined); assert.equal(input.session_id, undefined); assert.equal(input.artifact, undefined); }
});
test('source actions fail closed without supported operations, exact admitted identity or saved revision', () => {
  setup(); const a = sourceAsset();
  for (const operations of [[], ['OP-ASSET-PROBE'], ['OP-JOB-GET']]) assert.throws(() => ui.sourcePreparationRequest(sourceModel(operations), a), /advertise/);
  assert.throws(() => ui.sourcePreparationRequest(sourceModel(['OP-ASSET-PROBE', 'OP-JOB-GET']), a, sourceReceipt()), /advertise/);
  for (const asset of [null, { ...a, sha256: 'sha256:' + a.sha256 }, { ...a, entity_revision: null }]) assert.throws(() => ui.sourcePreparationRequest(sourceModel(), asset), /identity\/revision/);
  assert.throws(() => ui.sourcePreparationRequest({ ...sourceModel(), saved: null }, a), /identity\/revision/);
  assert.throws(() => ui.sourcePreparationRequest(sourceModel(), a, null, 'true'), /full-decode/);
});
test('binding requires succeeded matching owned job, committed receipt and observed supported stream zero', () => {
  setup(); const a = sourceAsset(), receipt = sourceReceipt(), job = { job_id: 'unit-job', state: 'succeeded', source_probe: receipt };
  assert.equal(ui.committedSourceReceipt(job, 'unit-job', a), receipt);
  for (const state of ['queued', 'waiting_for_approval', 'running', 'failed', 'interrupted', 'reconciliation_required']) assert.equal(ui.committedSourceReceipt({ ...job, state }, 'unit-job', a), null);
  assert.equal(ui.committedSourceReceipt(job, 'different-job', a), null);
  assert.equal(ui.committedSourceReceipt({ ...job, source_probe: { ...receipt, asset_version_id: 'other' } }, 'unit-job', a), null);
  for (const r of [{ ...receipt, receipt_id: null }, { ...receipt, asset_id: 'other' }, { ...receipt, full_decode: 'fail' }, { ...receipt, streams: [{ ...receipt.streams[0], index: 1 }] }, { ...receipt, vfr: 'unknown', streams: [{ index: 0, type: 'video' }] }]) assert.throws(() => ui.sourcePreparationRequest(sourceModel(), a, r), /receipt|timing\/sample/);
});
test('metadata binding never stands in for exact saved graph pin or silently follows changed source', () => {
  setup(); const a = sourceAsset(), v = version();
  assert.equal(ui.exactSourcePin(v, a), null);
  v.asset_refs = [{ ...a, kind: 'video' }]; assert.equal(ui.exactSourcePin(v, a), v.asset_refs[0]);
  for (const key of ['asset_id', 'asset_version_id', 'sha256']) {
    assert.equal(ui.exactSourcePin(v, { ...a, [key]: 'other' }), null);
    assert.equal(ui.selectedRegisteredAsset(a, { ...a, [key]: 'other' }), null);
  }
  assert.equal(ui.selectedRegisteredAsset(a, { ...a, entity_revision: 4 }).entity_revision, 4);
  assert.equal(ui.exactSourcePin(v, null), null);
  assert.notEqual(ui.sourcePreparationIdentity(sourceModel(), a), ui.sourcePreparationIdentity(sourceModel(), { ...a, sha256: 'd'.repeat(64) }));
  assert.notEqual(ui.sourcePreparationIdentity(sourceModel(), a), ui.sourcePreparationIdentity({ ...sourceModel(), s: { ...sourceModel().s, composition: 'other' } }, a));
});
test('source preparation uses owned polling and exact readbacks without private receipt download or invented graph op', () => {
  const preparation = source.slice(source.indexOf('function SourcePreparation('), source.indexOf('function InsertDialog('));
  assert.match(preparation, /useRead\(jobId/); assert.match(preparation, /OP-JOB-GET/);
  assert.match(preparation, /cancelAutosave\?\.\(\)/);
  assert.match(preparation, /read\(model\.cpath/); assert.match(preparation, /exactSourcePin\(saved, asset\)/);
  assert.match(preparation, /\/context/); assert.match(preparation, /\/assets/);
  assert.doesNotMatch(preparation, /stage\(|OP-TRANSACTION|asset\.pin|fetch\(|approval_refs\s*:/);
  assert.match(preparation, /trusted host session/); assert.match(preparation, /binding service publishes a version/);
});
test('probe and metadata binding preserve original local unsaved draft and exact source selection', async () => {
  const env = setup(async (path, options) => ({ api_version: 'ui.v1', scope, command: { status: 'committed' }, data: path.endsWith('/probe') ? { asset_id: 'unit-asset', asset_version_id: 'unit-asset-v1', job: { job_id: 'unit-job' } } : { asset_id: 'unit-asset', asset_version_id: 'unit-asset-v1', readiness: 'bound' } }));
  const v = version(), key = ui.unitHarness.compositionKey(scope), a = sourceAsset();
  ui.studioState.set({ ...ui.studioState.get(), asset: a, offline: true });
  ui.unitHarness.stage({ version: v, saved: v, scope, key, readOnly: false, draft: null }, [ui.buildMove(v, ['test-clip'], 1)], 'Keep original unit draft');
  const original = structuredClone(env.stored.get('motion-studio-ui.v1').drafts[key]);
  for (const receipt of [sourceReceipt()]) {
    const r = ui.sourcePreparationRequest(sourceModel(), a, receipt);
    await ui.unitHarness.command(r.route, r.operation, scope, r.preconditions, r.input, key);
    assert.deepEqual(env.stored.get('motion-studio-ui.v1').drafts[key], original);
    assert.deepEqual(ui.studioState.get().asset, a);
  }
});
test('late insertion save never reads the old route through a new owner or composition', async () => {
  for (const switchContext of [() => owner.set({ connectionId: 'other', profile: 'default' }), () => ui.studioState.set({ ...ui.studioState.get(), composition: 'other', epoch: ui.studioState.get().epoch + 1 })]) {
    let release, started; const ready = new Promise(resolve => started = resolve), calls = [];
    const env = setup(async (path, options) => { calls.push({ path, options }); started(); return new Promise(resolve => release = resolve); });
    const v = version(), key = ui.unitHarness.compositionKey(scope), model = { version: v, saved: v, scope, key, cpath: '/projects/test-native-id/compositions/test-composition', readOnly: false };
    ui.studioState.set({ ...ui.studioState.get(), offline: true });
    ui.unitHarness.stage(model, [ui.buildMove(v, ['test-clip'], 1)], 'Exact old scope');
    const saving = ui.unitHarness.saveDraft(model); await ready; switchContext();
    release({ api_version: 'ui.v1', scope, command: { status: 'committed' }, data: { version: { ...v, version_id: 'old-saved' } } });
    await saving;
    assert.equal(calls.length, 1, 'no readback in the new context');
    assert.equal(env.stored.get('motion-studio-ui.v1').journals[key].state, 'committed');
    cleanup(); cleanup = null;
  }
});
test('disposal releases subscriptions and cancels cache-owned requests', () => {
  const env = setup(); const before = owner.listeners.size; cleanup(); cleanup = null;
  assert.equal(owner.listeners.size, before - 1); assert.ok(cancelled.length > 0); assert.equal(env.disposed.length, 1);
});
