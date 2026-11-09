/* Motion Studio native Desktop surfaces. Uncompiled ESM; no private host APIs.
 * The host owns layout, identity, credentials and approval. No production is
 * launched by rendering a component. See README for integration and limits. */
import { atom, host, useValue, useQuery, queryClient, PANES_AREA, ROUTES_AREA, PALETTE_AREA, KEYBINDS_AREA } from '@hermes/plugin-sdk';
import { createElement as h, useEffect, useRef, useState } from 'react';

export const TABS = ['Preview', 'Assets', 'Layers', 'Inspector', 'Production', 'Jobs'];
export const API = '/ui/v1';
export const COMPOSITION_PRESETS = Object.freeze([
  { id: 'landscape-hd', label: 'Landscape HD', width: 1920, height: 1080, fps: 30 },
  { id: 'portrait-hd', label: 'Portrait HD', width: 1080, height: 1920, fps: 30 },
  { id: 'square', label: 'Square', width: 1080, height: 1080, fps: 30 },
  { id: 'landscape-4k', label: 'Landscape 4K', width: 3840, height: 2160, fps: 30 },
  { id: 'cinema-hd', label: 'Cinema HD', width: 1920, height: 1080, fps: 24 }
].map(Object.freeze));
const ROOT_KEY = 'motion-studio-ui.v1';
const enc = encodeURIComponent;
const clone = value => JSON.parse(JSON.stringify(value));
const uid = () => crypto.randomUUID();
const errorText = e => e?.message || 'The request could not be completed.';
const fmt = n => Number.isSafeInteger(n) ? String(n) : 'Unknown';
const empty = () => ({ owner: null, epoch: 0, project: null, composition: null, tab: 'Preview', frame: 0, sourceFrame: 0, monitor: 'program', selected: [], selectedTrack: null, range: null, tool: 'select', snap: true, zoom: 1, table: false, dialog: null, message: '', storageError: null, drafts: {}, journals: {}, undo: null, redo: null, solo: null, returnPath: '/', focus: false });
export const studioState = atom(empty());
export const frontendIdentity = atom({ status: 'pending', sha256: null });
let backendBuildIdentity = null;
export async function frontendSourceFingerprint(source) {
  const normalized = source.replaceAll('\r\n', '\n').replace(/^import (.+) from ['"][^'"\r\n]+['"];[ \t]*$/gm, 'import $1 from "<host-import>";');
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(normalized)))).map(value => value.toString(16).padStart(2, '0')).join('');
}
export function buildParity(backend, frontend) {
  if (frontend?.status === 'pending') return { status: 'checking', message: 'Checking loaded Studio build…' };
  if (backend?.frontend_hash_algorithm !== 'motion/import-normalized-sha256/v1' || !/^[0-9a-f]{64}$/.test(backend?.frontend_source_sha256 || '') || frontend?.status !== 'ready') return { status: 'unverified', message: 'Studio build identity is unverified. Disk installation is not proof of loaded code.' };
  return backend.frontend_source_sha256 === frontend.sha256
    ? { status: 'current', message: 'Loaded Studio frontend matches backend build.' }
    : { status: 'stale', message: 'Studio update pending: loaded frontend differs from backend. Edits are preserved; refresh the Desktop plugin before saving.' };
}
// Read this evaluated blob while its URL is still live. The native loader revokes
// it after import; reading the on-disk file later would misidentify old code.
if (import.meta.url.startsWith('blob:')) {
  fetch(import.meta.url).then(response => { if (!response.ok) throw new Error('Loaded module is unreadable'); return response.text(); })
    .then(frontendSourceFingerprint).then(sha256 => frontendIdentity.set({ status: 'ready', sha256 }))
    .catch(() => frontendIdentity.set({ status: 'unavailable', sha256: null }));
} else frontendIdentity.set({ status: 'unavailable', sha256: null });
let context = null;
let alive = false;
let storage = { drafts: {}, journals: {}, scopes: {} };
let cancelAutosave = null;
const inflight = new Set();
const change = patch => studioState.set({ ...studioState.get(), ...patch });
const scopeKey = s => JSON.stringify([s?.backend_instance_id, s?.connection_id, s?.profile_id, s?.native_project_id]);
const ownerKey = o => JSON.stringify([o?.connectionId, o?.profile]);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const ownerNow = () => host.state.focusedSessionOwner.get();
const transportOwner = () => ({ connectionId: host.activeConnectionId() || 'local', profile: host.state.profile.get() });
const transportReady = owner => Boolean(owner && ownerKey(owner) === ownerKey(transportOwner()));
const isCurrent = cap => alive && transportReady(cap.owner) && cap.epoch === studioState.get().epoch && ownerKey(cap.owner) === ownerKey(ownerNow()) && (cap.project === undefined || cap.project === studioState.get().project) && (cap.composition === undefined || cap.composition === studioState.get().composition);
const capture = () => { const s = studioState.get(); return { owner: s.owner ? clone(s.owner) : null, epoch: s.epoch, project: s.project, composition: s.composition }; };
const projectPath = id => `/projects/${enc(id)}`;
const compositionPath = (p, c) => `${projectPath(p)}/compositions/${enc(c)}`;
const compositionKey = s => `${scopeKey(s)}:${studioState.get().composition || ''}`;
function persist() {
  if (!context) return false;
  try { context.storage.set(ROOT_KEY, storage); return true; }
  catch (e) { change({ storageError: 'Cannot safely save edits on this device. Export recovery before continuing.' }); return false; }
}
function updateLocal(patch) {
  const before = studioState.get();
  if (('project' in patch && patch.project !== before.project) || ('composition' in patch && patch.composition !== before.composition)) {
    cancelAutosave?.(); cancelAutosave = null;
    queryClient.cancelQueries({ queryKey: ['motion-studio'] });
    patch = { ...patch, epoch: before.epoch + 1 };
  }
  change(patch);
  const s = studioState.get();
  if (s.owner) {
    const saved = { project: s.project, composition: s.composition, tab: s.tab, frame: s.frame, sourceFrame: s.sourceFrame, selected: s.selected, selectedTrack: s.selectedTrack, range: s.range, zoom: s.zoom, table: s.table, monitor: s.monitor, largeControls: s.largeControls || false };
    storage.scopes[ownerKey(s.owner)] = saved;
    if (s.project) storage.scopes[`${ownerKey(s.owner)}:${s.project}`] = saved;
    if (s.project && s.composition) storage.scopes[`${ownerKey(s.owner)}:${s.project}:${s.composition}`] = saved;
    persist();
  }
}
function transitionOwner() {
  const next = ownerNow();
  const s = studioState.get();
  if (ownerKey(next) === ownerKey(s.owner)) return;
  backendBuildIdentity = null;
  cancelAutosave?.(); cancelAutosave = null;
  queryClient.cancelQueries({ queryKey: ['motion-studio'] });
  const saved = storage.scopes[ownerKey(next)] || {};
  studioState.set({ ...empty(), ...saved, storageError: s.storageError, owner: next ? clone(next) : null, epoch: s.epoch + 1, drafts: storage.drafts, journals: storage.journals, message: 'Connection context changed. Previous drafts are frozen in their original scope.' });
}
export function assertScope(expected, received) {
  if (!received || ['backend_instance_id', 'connection_id', 'profile_id', 'native_project_id'].some(k => expected[k] !== undefined && received[k] !== expected[k])) throw Object.assign(new Error('Response belongs to another context; it was ignored.'), { code: 'SCOPE_MISMATCH', effect_state: 'unknown' });
}
export function unwrap(envelope, expected) {
  if (!envelope || envelope.api_version !== 'ui.v1') throw Object.assign(new Error('This backend does not provide the Motion Studio ui.v1 contract.'), { code: 'CONTRACT_INCOMPATIBLE' });
  if (expected && (!envelope.error || envelope.scope?.backend_instance_id)) assertScope(expected, envelope.scope);
  if (envelope.error) throw Object.assign(new Error(envelope.error.message), envelope.error);
  return envelope.data;
}
function params(values = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined) q.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
  return q.size ? `?${q}` : '';
}
async function read(path, values = {}, scope = null, cap = capture()) {
  if (!isCurrent(cap)) throw new Error('Context changed. Request cancelled.');
  const envelope = await context.rest(`${API}${path}${params({ ...values, connection_id: cap.owner.connectionId })}`);
  if (!isCurrent(cap)) throw new Error('Context changed. Late response discarded.');
  if (path === '/bootstrap' && !envelope.error) backendBuildIdentity = envelope.data?.runtime_identity || null;
  return { data: unwrap(envelope, scope), scope: envelope.scope, meta: envelope.meta };
}
function invalidate() { return queryClient.invalidateQueries({ queryKey: ['motion-studio'] }); }
function useRead(path, values, scope, enabled = true, poll = false) {
  const s = useValue(studioState);
  const cap = { owner: s.owner, epoch: s.epoch, project: s.project, composition: s.composition };
  return useQuery({ queryKey: ['motion-studio', ownerKey(s.owner), s.epoch, scopeKey(scope), path, values], queryFn: () => read(path, values, scope, cap), enabled: Boolean(alive && transportReady(s.owner) && path && enabled), retry: false, staleTime: 1000, refetchInterval: poll ? 5000 : false });
}
export function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
}
export async function publicHash(value) {
  const bytes = new TextEncoder().encode(canonical(value));
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2, '0')).join('');
}
export async function requestHash(operation_id, route, scope, preconditions, input) {
  return publicHash({ operation_id, route, scope, preconditions, input });
}
export function frozenCommand(scope, preconditions, input) {
  return { scope: clone(scope), command_id: uid(), idempotency_key: uid(), preconditions: clone(preconditions), input: clone(input) };
}
async function command(route, operation, scope, preconditions, input, journalKey = compositionKey(scope)) {
  const parity = buildParity(backendBuildIdentity, frontendIdentity.get());
  if (parity.status === 'stale') throw new Error(parity.message);
  const cap = capture();
  if (!isCurrent(cap) || studioState.get().storageError) throw new Error('Local journal or connection is unavailable. No command was sent.');
  assertScope({ connection_id: cap.owner.connectionId }, scope);
  const existing = storage.journals[journalKey];
  if (existing && !['committed', 'failed'].includes(existing.state)) throw new Error('A previous request needs reconciliation before another command can be sent.');
  const body = frozenCommand(scope, preconditions, input);
  const request_sha256 = await requestHash(operation, route, scope, preconditions, input);
  if (!isCurrent(cap)) throw new Error('Context changed before request submission.');
  const journal = { route, operation, body, request_sha256, state: 'prepared', owner: clone(cap.owner), result: null };
  storage.journals[journalKey] = journal;
  if (!persist()) throw new Error(studioState.get().storageError);
  return transmit(journalKey, cap);
}
async function transmit(key, cap = capture()) {
  const j = storage.journals[key];
  if (!j || inflight.has(key) || !isCurrent(cap) || ownerKey(j.owner) !== ownerKey(cap.owner)) throw new Error('This request is frozen or already being checked.');
  inflight.add(key);
  j.state = 'sending';
  if (!persist()) { inflight.delete(key); throw new Error('Cannot persist request journal.'); }
  try {
    const response = await context.rest(`${API}${j.route}`, { method: 'POST', body: clone(j.body) });
    const result = unwrap(response, j.body.scope);
    j.state = response.command?.status === 'committed' ? 'committed' : 'pending';
    j.result = result;
    if (response.command?.receipt_id) j.receipt_id = response.command.receipt_id;
    persist();
    if (isCurrent(cap)) {
      if (j.state === 'committed' && j.operation === 'OP-TRANSACTION') {
        delete storage.drafts[key]; persist();
        change({ drafts: { ...storage.drafts }, undo: result.undo_token || null, redo: null });
      }
      change({ journals: { ...storage.journals }, message: j.state === 'committed' ? 'Saved on backend. Refreshing exact saved version…' : 'Request accepted; completion is not yet confirmed.' });
      await invalidate();
    }
    return result;
  } catch (e) {
    j.state = e.effect_state === 'none' ? 'failed' : 'unknown';
    j.error = { message: errorText(e), code: e.code, effect_state: e.effect_state || 'unknown', details: e.details || null };
    persist();
    if (isCurrent(cap)) change({ journals: { ...storage.journals }, message: e.code === 'REVISION_CONFLICT' ? 'Other changes need review before these edits can sync.' : `${errorText(e)}${j.state === 'unknown' ? ' Check request status before retrying.' : ''}`, dialog: ['REVISION_CONFLICT', 'UNDO_CONFLICT', 'PROPOSAL_STALE'].includes(e.code) ? 'conflict' : studioState.get().dialog });
    throw e;
  } finally { inflight.delete(key); }
}
async function reconcile(key, scope) {
  const j = storage.journals[key];
  if (!j) return;
  const cap = capture();
  if (ownerKey(j.owner) !== ownerKey(cap.owner)) throw new Error('Return to the original connection/profile to reconcile this request.');
  const r = await read(`/commands/${enc(j.body.command_id)}`, { scope: j.body.scope, request_sha256: j.request_sha256 }, scope, cap);
  j.state = r.data.status; j.status = r.data; persist();
  if (j.state === 'failed' && r.data.effect_state === 'unknown') j.state = 'unknown';
  if (j.state === 'committed') {
    if (j.operation === 'OP-TRANSACTION') delete storage.drafts[key];
    persist(); change({ drafts: { ...storage.drafts }, journals: { ...storage.journals }, message: 'Backend receipt confirmed. Refreshing saved version.' }); await invalidate();
  } else { change({ journals: { ...storage.journals }, message: `Request status: ${j.state}. No duplicate request was launched.` }); }
  return r.data;
}
const guard = fn => async (...args) => { try { return await fn(...args); } catch (e) { change({ message: errorText(e) }); return null; } };
export function safeInteger(value, min = 0, max = Number.MAX_SAFE_INTEGER) {
  if (!/^-?\d+$/.test(String(value))) throw new Error('Enter a whole number of frames.');
  const n = Number(value);
  if (!Number.isSafeInteger(n) || n < min || n > max) throw new Error(`Value must be an integer from ${min} to ${max}.`);
  return n;
}
export function roundEven(num, den) {
  const n = BigInt(num), d = BigInt(den);
  if (d <= 0n || n < 0n) throw new Error('Timing must be nonnegative with a positive rate.');
  const q = n / d, r = n % d;
  return Number(q + (r * 2n > d || (r * 2n === d && q % 2n) ? 1n : 0n));
}
export function timecode(frame, fps) {
  const nominal = Math.ceil(fps.num / fps.den);
  const f = safeInteger(frame), seconds = Math.floor(f / nominal);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60, f % nominal].map(n => String(n).padStart(2, '0')).join(':');
}
export function linkedSelection(version, ids, isolate = false) {
  const selected = new Set(ids);
  if (!isolate) {
    const links = new Set(version.clips.filter(c => selected.has(c.clip_id) && c.linked_group_id).map(c => c.linked_group_id));
    for (const c of version.clips) if (links.has(c.linked_group_id)) selected.add(c.clip_id);
  }
  return [...selected];
}
export function buildMove(version, ids, delta, targetTrack = null) {
  const clips = version.clips.filter(c => ids.includes(c.clip_id));
  if (!clips.length) throw new Error('Select a placement first.');
  if (clips.some(c => version.tracks.find(t => t.track_id === c.track_id)?.locked)) throw new Error('A selected track is locked. Unlock explicitly before editing.');
  return { op: 'clip.move', placements: clips.map(c => ({ clip_id: c.clip_id, target_track_id: targetTrack || c.track_id, start_frame: safeInteger(c.start_frame + delta) })), link_policy: 'preserve' };
}
export function buildTrim(clip, start, end, fps) {
  start = safeInteger(start); end = safeInteger(end, start + 1);
  const m = clone(clip.source_mapping);
  if (!['frame', 'source_tick'].includes(m?.domain) || m.conform_ref) throw new Error('Precise trimming needs a known source-time conform mapping.');
  const factorNum = m.domain === 'frame' ? BigInt(m.rate.num) * BigInt(fps.den) * BigInt(m.speed.num) : BigInt(m.time_base.den) * BigInt(fps.den);
  const factorDen = m.domain === 'frame' ? BigInt(m.rate.den) * BigInt(fps.num) * BigInt(m.speed.den) : BigInt(m.time_base.num) * BigInt(fps.num);
  const sourceDelta = frames => {
    const value = BigInt(frames) * factorNum;
    if (value % factorDen !== 0n) throw new Error('This trim needs a supported rational source conform; no source rounding was applied.');
    return Number(value / factorDen);
  };
  const input = m.domain === 'frame' ? 'in_index' : 'in_pts', output = m.domain === 'frame' ? 'out_index' : 'out_pts';
  m[input] += sourceDelta(start - clip.start_frame);
  m[output] += sourceDelta(end - clip.end_frame);
  if ((m.domain === 'frame' && m[input] < 0) || m[output] <= m[input]) throw new Error('Trim is outside source handles.');
  return { op: 'clip.trim', clip_id: clip.clip_id, start_frame: start, end_frame: end, source_mapping: m, link_policy: 'preserve' };
}
export function buildSplit(version, ids, frame) {
  const clips = version.clips.filter(c => ids.includes(c.clip_id));
  if (!clips.length || clips.some(c => frame <= c.start_frame || frame >= c.end_frame)) throw new Error('Split must be strictly inside every selected placement.');
  const closure = linkedSelection(version, ids);
  if (closure.some(id => !ids.includes(id))) throw new Error('Split requires every linked companion explicitly.');
  for (const c of clips) {
    if (version.tracks.find(t => t.track_id === c.track_id)?.locked) throw new Error('A linked split participant is locked.');
    buildTrim(c, c.start_frame, frame, version.format.fps);
  }
  const groups = new Set();
  return clips.filter(c => { if (!c.linked_group_id) return true; if (groups.has(c.linked_group_id)) return false; groups.add(c.linked_group_id); return true; }).map(c => ({ op: 'clip.split', clip_id: c.clip_id, at_frame: frame, right_create_ref: uid(), link_policy: 'preserve' }));
}
export function projectDraft(version, operations) {
  const v = clone(version);
  for (const o of operations) {
    if (o.op === 'track.create') v.tracks.push({ track_id: o.create_ref, kind: o.kind, name: o.name, order: o.order, overlap_policy: o.overlap_policy, locked: false, visible: true, muted: false, clip_ids: [] });
    if (o.op === 'clip.insert') v.clips.push({ ...clone(o), clip_id: o.create_ref, effect_ids: [] });
    if (o.op === 'clip.split') {
      const first = v.clips.find(c => c.clip_id === o.clip_id);
      const clips = first ? v.clips.filter(c => c.clip_id === first.clip_id || (first.linked_group_id && c.linked_group_id === first.linked_group_id)) : [];
      for (const c of clips) {
        if (o.at_frame <= c.start_frame || o.at_frame >= c.end_frame) throw new Error('Linked split is not interior to every companion.');
        const right = clone(c), original = clone(c);
        right.clip_id = c.clip_id === o.clip_id ? o.right_create_ref : `${o.right_create_ref}:${c.clip_id}`;
        right.start_frame = o.at_frame;
        c.source_mapping = buildTrim(original, original.start_frame, o.at_frame, v.format.fps).source_mapping;
        right.source_mapping = buildTrim(original, o.at_frame, original.end_frame, v.format.fps).source_mapping;
        if (clips.length > 1) right.linked_group_id = `${o.right_create_ref}:group`;
        c.end_frame = o.at_frame; v.clips.push(right);
      }
    }
    if (o.op === 'clip.move') for (const p of o.placements) { const c = v.clips.find(x => x.clip_id === p.clip_id); if (c) { c.end_frame += p.start_frame - c.start_frame; c.start_frame = p.start_frame; c.track_id = p.target_track_id; } }
    if (o.op === 'clip.trim') { const c = v.clips.find(x => x.clip_id === o.clip_id); if (c) Object.assign(c, { start_frame: o.start_frame, end_frame: o.end_frame, source_mapping: o.source_mapping }); }
    if (o.op === 'clip.enable') { const c = v.clips.find(x => x.clip_id === o.clip_id); if (c) c.enabled = o.enabled; }
    if (o.op === 'track.update') { const t = v.tracks.find(x => x.track_id === o.track_id); if (t) Object.assign(t, o); }
    if (o.op === 'entity.delete') { const ids = new Set(o.targets.map(t => t.id)); v.clips = v.clips.filter(c => !ids.has(c.clip_id) && !ids.has(c.track_id)); v.tracks = v.tracks.filter(t => !ids.has(t.track_id)); }
    if (o.op === 'caption.upsert') { const i = v.captions.findIndex(c => c.cue_id === o.cue_id); const c = { ...o, cue_id: o.cue_id || o.create_ref }; if (i >= 0) v.captions[i] = c; else v.captions.push(c); }
    if (o.op === 'timeline.ripple') for (const family of ['clips', 'captions']) { v[family] = v[family].filter(c => !(o.track_ids.includes(c.track_id) && o.action === 'delete' && c.start_frame >= o.range.start_frame && c.end_frame <= o.range.end_frame)); for (const c of v[family]) if (o.track_ids.includes(c.track_id) && c.start_frame >= o.range.end_frame) { c.start_frame += o.delta_frames; c.end_frame += o.delta_frames; } }
    if (o.op === 'document.put') { const document = { ...clone(o), document_id: o.document_id || o.create_ref }; const i = v.production_documents.findIndex(d => d.document_id === o.document_id); if (i >= 0) v.production_documents[i] = document; else v.production_documents.push(document); }
    if (o.op === 'link.set') for (const c of v.clips) if (o.clip_ids.includes(c.clip_id)) c.linked_group_id = o.group_id;
    if (o.op === 'audio.set') { const target = o.target.kind === 'clip' ? v.clips.find(c => c.clip_id === o.target.id) : v.audio_buses.find(b => b.bus_id === o.target.id); if (target) target.audio = { gain_db_milli: o.gain_db_milli, pan_milli: o.pan_milli, muted: o.muted, fades: o.fades, envelope: o.envelope }; }
  }
  v.format.duration_frames = Math.max(0, ...v.clips.map(c => c.end_frame), ...v.captions.map(c => c.end_frame));
  return v;
}
export function insertionAffected(version, placements, mode) {
  const list = Array.isArray(placements) ? placements : [placements];
  const start = list[0].start_frame, end = list[0].end_frame;
  const tracks = new Set(list.map(p => p.track_id));
  const participates = c => tracks.has(c.track_id) && c.end_frame > start && (mode === 'insert' || c.start_frame < end);
  if (mode !== 'place') {
    let previous;
    do {
      previous = tracks.size;
      const closure = linkedSelection(version, version.clips.filter(participates).map(c => c.clip_id));
      for (const c of version.clips) if (closure.includes(c.clip_id)) tracks.add(c.track_id);
    } while (tracks.size !== previous);
  }
  const clips = version.clips.filter(participates);
  const cues = (version.captions || []).filter(participates);
  return { track_ids: [...tracks], clips, cues };
}
export function buildInsertion(version, placement, mode = 'place', newTracks = []) {
  if (!['place', 'insert', 'overwrite'].includes(mode)) throw new Error('Unknown insertion behavior.');
  const list = (Array.isArray(placement) ? placement : [placement]).map(clone);
  if (!list.length) throw new Error('Choose a placement.');
  let graph = projectDraft(version, newTracks);
  const operations = [...newTracks];
  const start = safeInteger(list[0].start_frame), end = safeInteger(list[0].end_frame, start + 1), duration = end - start;
  for (const p of list) {
    if (p.start_frame !== start || p.end_frame !== end) throw new Error('Linked insertion requires exact matching output intervals; prepare conform externally.');
    const t = graph.tracks.find(t => t.track_id === p.track_id);
    if (!t || t.locked) throw new Error('Choose an existing unlocked compatible target track.');
    const ref = graph.asset_refs?.find(a => a.asset_id === p.subject.id && a.asset_version_id === p.subject.version_id);
    if (ref && !((t.kind === 'audio' && ref.kind === 'audio') || (['video', 'overlay'].includes(t.kind) && ['video', 'image'].includes(ref.kind)))) throw new Error('Source is incompatible with the chosen track.');
    if (ref?.kind === 'audio' && ref.sample_rate !== graph.format.sample_rate) throw new Error('Audio sample rate needs an observed compatible conform derivative.');
    if (mode === 'place' && t.overlap_policy === 'exclusive' && graph.clips.some(c => c.track_id === t.track_id && c.start_frame < end && c.end_frame > start)) throw new Error('This range is occupied. Choose reviewed overwrite or ripple insert.');
  }
  if (mode !== 'place') {
    const review = insertionAffected(graph, list, mode), tracks = new Set(review.track_ids);
    if (graph.tracks.some(t => tracks.has(t.track_id) && t.locked)) throw new Error('An affected linked companion track is locked.');
    if (review.cues.length) throw new Error('Affected caption cues require a separate explicit timing plan.');
    for (const boundary of mode === 'overwrite' ? [start, end] : [start]) {
      while (true) {
        const c = graph.clips.find(c => tracks.has(c.track_id) && c.start_frame < boundary && c.end_frame > boundary);
        if (!c) break;
        const split = buildSplit(graph, linkedSelection(graph, [c.clip_id]), boundary);
        operations.push(...split); graph = projectDraft(graph, split);
      }
    }
    if (mode === 'overwrite') {
      const removed = graph.clips.filter(c => tracks.has(c.track_id) && c.start_frame >= start && c.end_frame <= end);
      const ids = removed.map(c => c.clip_id);
      if (linkedSelection(graph, ids).some(id => !ids.includes(id))) throw new Error('Overwrite cannot preserve these offset linked companions; review their boundaries first.');
      if (removed.some(c => c.effect_ids?.length || graph.layers?.some(l => l.clip_id === c.clip_id))) throw new Error('Overwrite has dependent effects/layers; review dependency removal separately.');
      if (removed.length) operations.push({ op: 'entity.delete', targets: removed.map(c => ({ kind: 'clip', id: c.clip_id })), expected_dependency_ids: [] });
    } else {
      const affected = graph.clips.filter(c => tracks.has(c.track_id) && c.end_frame > start);
      const ids = affected.map(c => c.clip_id);
      if (linkedSelection(graph, ids).some(id => !ids.includes(id))) throw new Error('Ripple cannot preserve these offset linked companions; review their boundaries first.');
      operations.push({ op: 'timeline.ripple', track_ids: [...tracks], range: { start_frame: start, end_frame: start }, action: 'insert_gap', delta_frames: duration, link_policy: 'preserve', expected_affected_ids: ids });
    }
  }
  operations.push(...list);
  if (list.length > 1) operations.push({ op: 'link.set', clip_ids: list.map(p => p.create_ref), group_id: uid() });
  return operations;
}
function draftFor(model) { return storage.drafts[model.key]; }
function hasRecoveryJournal(key) { return Object.values(storage.journals).some(j => j.recovery_original_key === key && j.operation === 'OP-RECOVER-AS-NEW'); }
function stage(model, operations, summary, dependencies = []) {
  if (hasRecoveryJournal(model.key)) throw new Error('Original local recovery is retained, unreplayed. Reconcile the separate recovery command before editing elsewhere.');
  if (!model.version || !model.scope || model.readOnly || studioState.get().storageError) throw new Error('Editing is unavailable until exact Project and Composition scope is ready.');
  if (operations.length + (model.draft?.operations.length || 0) > 1000) throw new Error('Save this batch before adding more than 1000 operations.');
  const j = storage.journals[model.key];
  if (j && !['committed', 'failed'].includes(j.state)) throw new Error('Wait for the pending save or reconcile its outcome before editing.');
  const old = draftFor(model);
  if (old?.recovered) throw new Error('Review recovered local edits before adding changes.');
  const base = old?.base || { composition_revision: model.saved.composition_revision, version_id: model.saved.version_id };
  if (base.version_id !== model.saved.version_id) { change({ dialog: 'conflict' }); throw new Error('The saved version changed. Local edits are preserved for review.'); }
  const next = { base, operations: [...(old?.operations || []), ...clone(operations)], summary, dependencies: [...new Set([...(old?.dependencies || []), ...dependencies])], owner: clone(studioState.get().owner), recovered: false, manual: old?.manual || studioState.get().offline || globalThis.navigator?.onLine === false };
  storage.drafts[model.key] = next;
  if (!persist()) return;
  change({ drafts: { ...storage.drafts }, message: `${next.operations.length} changes saved on this device; waiting to sync.` });
  cancelAutosave?.();
  cancelAutosave = context.setTimeout(() => { cancelAutosave = null; if (!next.manual && !next.recovered) guard(() => saveDraft(model))(); }, 300);
}
async function saveDraft(model) {
  if (hasRecoveryJournal(model.key)) throw new Error('Original local journal is retained and unreplayed; use the separate recovery command.');
  const d = draftFor(model);
  if (!d || d.recovered || !same(d.owner, ownerNow())) return;
  const result = await command(model.cpath + '/transactions', 'OP-TRANSACTION', model.scope, d.base, { operations: d.operations, gesture_id: uid(), summary: d.summary, dependency_policy: 'reject_unlisted', acknowledged_dependency_ids: d.dependencies }, model.key);
  return result;
}
function useModel() {
  const s = useValue(studioState);
  const native = useQuery({ queryKey: ['motion-studio', ownerKey(s.owner), s.epoch, 'native-projects'], queryFn: async () => { const cap = capture(); if (!isCurrent(cap)) throw new Error('The focused owner is not the active request transport; switch the native connection/profile back to resume.'); const value = await host.request('projects.list', { profile: cap.owner.profile }); if (!isCurrent(cap)) throw new Error('Project context changed.'); if (!Array.isArray(value.projects) || !('active_id' in value)) throw new Error('Native Project registry did not return projects and active_id.'); return value; }, enabled: Boolean(transportReady(s.owner)), retry: false, refetchInterval: 5000 });
  useEffect(() => {
    if (!native.data) return;
    const id = native.data.active_id;
    const valid = id != null && native.data.projects.some(p => p.id === id);
    if (s.project !== (valid ? id : null)) {
      cancelAutosave?.();
      const previous = valid ? storage.scopes[`${ownerKey(s.owner)}:${id}`] || {} : {};
      updateLocal({ project: valid ? id : null, composition: previous.composition || null, selected: previous.selected || [], selectedTrack: previous.selectedTrack || null, range: previous.range || null, frame: previous.frame || 0, dialog: null, undo: null, redo: null });
    }
  }, [native.data, s.project]);
  const boot = useRead('/bootstrap', { client_contract: 'ui.v1', client_kind: 'desktop' }, null, Boolean(s.owner), true);
  const baseScope = boot.data?.scope;
  const scope = baseScope && s.project ? { ...baseScope, native_project_id: s.project } : null;
  const ppath = s.project ? projectPath(s.project) : null;
  const pcontext = useRead(ppath && ppath + '/context', {}, scope, Boolean(scope));
  const catalogPages = useCollection(ppath && ppath + '/compositions', { include_archived: false }, { s, scope }, true);
  const catalog = catalogPages.query;
  const cpath = s.composition && ppath ? compositionPath(s.project, s.composition) : null;
  const head = useRead(cpath, {}, scope, Boolean(scope && cpath), true);
  const capabilities = useRead('/capabilities', { mode: 'cached', ...(scope ? { native_project_id: s.project, ...(s.composition ? { composition_id: s.composition } : {}) } : {}) }, scope || baseScope, Boolean(baseScope));
  const saved = head.data?.data?.version || head.data?.data?.head || (head.data?.data?.schema_version === 'composition.v1' ? head.data.data : null);
  const summary = head.data?.data?.composition || head.data?.data?.summary || catalogPages.items.find(c => c.composition_id === s.composition);
  const key = scope ? `${scopeKey(scope)}:${s.composition || ''}` : '';
  const draft = storage.drafts[key];
  const version = saved && draft && draft.base.version_id === saved.version_id ? projectDraft(saved, draft.operations) : saved;
  const supported = pcontext.data?.data?.supported_operations || boot.data?.data?.supported_operations || [];
  const can = op => supported.includes(op) || supported.some(x => x.operation_id === op && x.available !== false);
  const journal = storage.journals[key];
  const status = useRead(journal && !['committed', 'failed', 'prepared'].includes(journal.state) ? `/commands/${enc(journal.body.command_id)}` : null, journal ? { scope: journal.body.scope, request_sha256: journal.request_sha256 } : {}, scope, Boolean(journal && scope), true);
  useEffect(() => {
    const observed = status.data?.data;
    if (!journal || !observed || journal.state === observed.status) return;
    journal.state = observed.status === 'failed' && observed.effect_state === 'unknown' ? 'unknown' : observed.status;
    journal.status = observed;
    if (journal.state === 'committed' && journal.operation === 'OP-TRANSACTION') delete storage.drafts[key];
    persist(); change({ drafts: { ...storage.drafts }, journals: { ...storage.journals } });
    if (journal.state === 'committed') invalidate();
  }, [status.data, key]);
  return { s, native, boot, scope, baseScope, ppath, pcontext, catalog, compositions: catalogPages.items, catalogMore: catalogPages.more, cpath, head, capabilities, saved, summary, key, draft, version, can, readOnly: !transportReady(s.owner) || !scope || !saved || Boolean(head.data?.data?.constraints?.read_only || head.data?.data?.read_only || summary?.archived), cas: saved ? { composition_revision: saved.composition_revision, version_id: saved.version_id } : null };
}

// Scoped visual language; all colors are semantic host theme values. No host DOM is queried.
const CSS = `
.ms{--ms-bg:var(--ui-bg-editor,var(--background));--ms-panel:var(--ui-bg-elevated,var(--ui-bg-editor,var(--background)));--ms-line:var(--ui-stroke-primary,var(--border));--ms-text:var(--ui-text-primary,var(--foreground));--ms-muted:var(--ui-text-secondary,var(--muted-foreground));--ms-accent:var(--ui-accent,var(--primary));--ms-field:color-mix(in srgb,var(--ms-panel) 88%,var(--ms-text) 12%);color:var(--ms-text);background:var(--ms-bg);font:12px/1.45 var(--font-sans,system-ui);height:100%;min-height:0;min-width:0;display:flex;flex-direction:column;isolation:isolate;container-type:inline-size;overflow:hidden}
.ms input:not([type=checkbox]):not([type=range]),.ms select,.ms textarea{color:var(--ms-text);background:var(--ms-field);border-color:color-mix(in srgb,var(--ms-panel) 56%,var(--ms-text) 44%)}.ms input::placeholder,.ms textarea::placeholder{color:var(--ms-muted)}.ms select option{color:var(--ms-text);background:var(--ms-panel)}.ms details>summary{cursor:pointer;padding:6px 0;color:var(--ms-text)}.ms .workflow{margin:10px 12px;border-left:3px solid var(--ms-accent)}.ms .workflow ol{margin:0;padding-left:20px}.ms .workflow li{padding:3px 0}.ms .workflow [aria-current=step]{font-weight:650;color:var(--ms-text)}
.ms *{box-sizing:border-box}.ms button,.ms input,.ms select,.ms textarea{font:inherit;color:inherit}.ms button{border:1px solid var(--ms-line);background:var(--ms-panel);border-radius:5px;min-height:32px;padding:5px 9px;cursor:pointer}.ms button:not(.clip):not(.item):not([role=tab]){background:color-mix(in srgb,var(--ms-panel) 85%,var(--ms-text) 15%);border-color:color-mix(in srgb,var(--ms-line) 65%,var(--ms-text) 35%);box-shadow:inset 0 1px 0 color-mix(in srgb,var(--ms-text) 12%,transparent),0 1px 2px #0003;font-weight:600}.ms button[aria-pressed=true]:not(.clip){background:color-mix(in srgb,var(--ms-accent) 20%,var(--ms-panel));border-color:var(--ms-accent);color:var(--ms-text)}.ms button:active:not(:disabled){box-shadow:inset 0 1px 3px #0004}.ms button:hover:not(:disabled){background:var(--chrome-action-hover,var(--accent))}.ms button:disabled{opacity:.55;cursor:not-allowed}.ms :focus-visible{outline:2px solid var(--ms-accent);outline-offset:2px}.ms input,.ms select,.ms textarea{min-width:0;min-height:32px;padding:5px 7px;border:1px solid var(--ms-line);border-radius:4px;background:var(--ms-bg)}.ms input[type=checkbox]{min-height:20px;width:20px}.ms input[type=range]{padding:0;accent-color:var(--ms-accent)}.ms textarea{width:100%;min-height:88px;resize:vertical}.ms label{display:flex;flex-direction:column;gap:5px;color:var(--ms-muted);min-width:0}.ms h2,.ms h3,.ms h4,.ms p{margin:0}.ms h2{font-size:14px;letter-spacing:.02em}.ms h3{font-size:12px;font-weight:650}.ms small,.ms .muted{color:var(--ms-muted)}.ms .bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:9px 12px;border-bottom:1px solid var(--ms-line)}.ms .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ms .spread{justify-content:space-between}.ms .grow{flex:1;min-width:0}.ms .scroll{overflow:auto;min-height:0;flex:1}.ms .body{padding:12px;display:flex;flex-direction:column;gap:12px}.ms .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.ms .card{border:1px solid var(--ms-line);background:var(--ms-panel);border-radius:6px;padding:12px;display:flex;flex-direction:column;gap:10px}.ms .badge{border:1px solid var(--ms-line);border-radius:4px;padding:2px 6px;font-size:10px;letter-spacing:.025em;color:var(--ms-muted)}.ms .primary{border-color:var(--ms-accent);color:var(--ms-accent)}.ms.studio-dock> :not(.scroll){flex-shrink:0}.ms.studio-dock>.scroll{min-width:0;overscroll-behavior:contain}.ms .tabs{display:flex;overflow:auto;border-bottom:1px solid var(--ms-line);flex-shrink:0}.ms .tabs button{flex:1;border:0;border-radius:0;white-space:nowrap;padding:10px 9px;background:var(--ms-bg);border-bottom:2px solid var(--ms-line)}.ms .tabs button[aria-selected=true]{color:var(--ms-accent);border-bottom-color:var(--ms-accent);background:var(--ms-panel)}.ms .notice{padding:8px 12px;border-bottom:1px solid var(--ms-line);background:var(--ms-panel);overflow-wrap:anywhere}.ms .monitor{position:relative;aspect-ratio:16/9;min-height:120px;background:var(--ui-bg-sunken,var(--ms-bg));display:grid;place-items:center;border:1px solid var(--ms-line);overflow:hidden}.ms video,.ms audio{width:100%;max-height:100%}.ms .monitor video{height:100%;object-fit:contain}.ms .guides{position:absolute;inset:10%;border:1px dashed var(--ms-muted);pointer-events:none}.ms .empty{padding:28px 15px;text-align:center;display:flex;flex-direction:column;gap:10px;align-items:center;color:var(--ms-muted)}.ms .list{display:flex;flex-direction:column;gap:6px}.ms .item{width:100%;text-align:start;padding:9px;border:1px solid var(--ms-line);border-radius:5px;display:flex;gap:9px;align-items:center;background:var(--ms-panel)}.ms .item[aria-selected=true]{border-color:var(--ms-accent)}.ms .item img{width:64px;height:40px;object-fit:contain}.ms .mono{font-family:var(--font-mono,monospace);font-variant-numeric:tabular-nums}.ms .timeline{overflow:auto;min-height:100px;flex:1;position:relative}.ms .ruler{height:30px;position:sticky;top:0;background:var(--ms-panel);z-index:3;display:flex}.ms .track{display:flex;min-height:52px;border-bottom:1px solid var(--ms-line)}.ms .trackhead{position:sticky;left:0;width:160px;min-width:160px;padding:6px;background:var(--ms-panel);z-index:2;border-right:1px solid var(--ms-line)}.ms .trackhead button{padding:2px 5px;min-width:32px}.ms .lane{position:relative;min-height:52px;background:var(--ms-bg)}.ms .clip{position:absolute;top:5px;height:41px;overflow:hidden;white-space:nowrap;border-color:var(--ms-muted);background:var(--ms-panel);touch-action:none;user-select:none;text-align:start}.ms .clip[aria-pressed=true]{border:2px solid var(--ms-accent)}.ms .playhead{position:absolute;top:0;bottom:0;width:1px;background:var(--ms-accent);pointer-events:none;z-index:1}.ms .handle{position:absolute;top:0;bottom:0;width:8px;background:var(--ms-line)}.ms .handle.start{left:0;cursor:w-resize}.ms .handle.end{right:0;cursor:e-resize}.ms .tracktitle{max-width:132px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ms table{width:100%;border-collapse:collapse;text-align:start}.ms td,.ms th{padding:7px;border-bottom:1px solid var(--ms-line)}.ms progress{width:100%;accent-color:var(--ms-accent)}.ms dialog{color:var(--ms-text);background:var(--ms-bg);border:1px solid var(--ms-line);border-radius:8px;padding:0;width:min(700px,94vw);max-height:88vh}.ms dialog::backdrop{background:var(--overlay-backdrop, var(--ms-line))}.ms .dialogbody{overflow:auto;max-height:70vh;padding:16px;display:flex;flex-direction:column;gap:12px}.ms .dialogfoot{padding:12px;display:flex;justify-content:flex-end;gap:8px;border-top:1px solid var(--ms-line)}.ms .error{color:var(--ui-danger,var(--destructive))}.ms .focusgrid{display:grid;grid-template-rows:minmax(0,1fr) minmax(220px,35%);height:100%;min-height:0;gap:1px;background:var(--ms-line)}.ms .focusgrid>section{min-height:0}.ms .dragreadout{position:sticky;left:170px;z-index:4;color:var(--ms-accent);background:var(--ms-panel);padding:3px}.ms.large button,.ms .large button{min-height:44px}@media(pointer:coarse){.ms button,.ms input,.ms select{min-height:44px}.ms .handle{width:12px}}.ms [dir=auto]{unicode-bidi:plaintext}@container(max-width:420px){.ms .composition-bar>span{flex-basis:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ms .composition-bar>.grow{flex-basis:70%}.ms.studio-dock>.tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));overflow:visible}.ms.studio-dock>.tabs button{min-width:0;padding:5px}.ms.studio-dock .bar{gap:6px;padding:6px 8px}.ms .grid{grid-template-columns:1fr}.ms .bar{padding:8px}.ms .tabs button{padding:10px 7px}.ms .body{padding:9px}.ms .trackhead{width:130px;min-width:130px}}@media(prefers-reduced-motion:reduce){.ms *{scroll-behavior:auto!important;animation:none!important;transition:none!important}}`;
function B({ children, title, onClick, disabled, primary, ...props }) { return h('button', { type: 'button', title: title || props['aria-label'] || (typeof children === 'string' ? children : undefined), onClick: guard(onClick || (() => {})), disabled, className: primary ? 'primary' : '', ...props }, children); }
function Badge({ children }) { return h('span', { className: 'badge' }, children); }
function Notice({ children, error = false }) { return h('div', { className: `notice ${error ? 'error' : ''}`, role: error ? 'alert' : 'status' }, children); }
function Unavailable({ title, reason, action }) { return h('div', { className: 'empty' }, h('h3', {}, title), h('p', {}, reason), action || null); }
function QueryState({ query, children, emptyText = 'No items yet.' }) {
  if (query.isPending && !query.data) return h(Unavailable, { title: 'Loading…', reason: 'Reading the current authorized context.' });
  if (query.error) return h(Unavailable, { title: 'This view is unavailable', reason: errorText(query.error), action: h(B, { onClick: () => query.refetch() }, 'Retry') });
  return children || h(Unavailable, { title: emptyText, reason: 'No media or completed work has been invented for this view.' });
}
function NumberField({ label, value, onChange, min = 0, max = Number.MAX_SAFE_INTEGER, step = 1, unit = 'frames', disabled = false }) {
  return h('label', {}, `${label} · ${unit}`, h('input', { type: 'number', inputMode: 'numeric', value, min, max, step, disabled, onChange: e => onChange(e.target.value), onKeyDown: e => { if (e.shiftKey && ['ArrowUp', 'ArrowDown'].includes(e.key)) { e.preventDefault(); onChange(String(Number(value || 0) + (e.key === 'ArrowUp' ? 10 : -10) * step)); } } }));
}
function Modal({ title, children, close = () => change({ dialog: null }) }) {
  const ref = useRef(null), previous = useRef(null);
  useEffect(() => { previous.current = ref.current?.ownerDocument.activeElement; ref.current?.showModal(); return () => { ref.current?.close(); previous.current?.focus?.(); }; }, []);
  return h('dialog', { ref, 'aria-label': title, onCancel: e => { e.preventDefault(); close(); } }, h('div', { className: 'bar spread' }, h('h2', {}, title), h(B, { onClick: close, 'aria-label': 'Close dialog' }, 'Close')), h('div', { className: 'dialogbody' }, children));
}
function Icon({ name }) {
  const paths = { play: 'm9 5 11 7-11 7z', pause: 'M8 5v14M16 5v14', settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2', film: 'M3 4h18v16H3zM7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4', split: 'M4 4l16 16M4 20 20 4M12 2v20' };
  return h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, 'aria-hidden': true }, h('path', { d: paths[name] || paths.film }));
}
function Header(props) {
  const frontend = useValue(frontendIdentity);
  const backend = props.model.boot?.data?.data?.runtime_identity;
  const parity = buildParity(backend, frontend);
  return h('div', {}, h('div', { role: 'status', 'aria-label': 'Studio build status', 'data-motion-build-status': parity.status, className: parity.status === 'stale' ? 'error' : 'muted', title: backend ? `Backend ${backend.manifest_sha256}; loaded frontend ${frontend.sha256 || 'unverified'}` : 'No backend identity received' }, parity.message), h(HeaderContent, props));
}
function HeaderContent({ model, focus = false }) {
  const { s } = model;
  const nativeProject = model.native.data?.projects.find(p => p.id === s.project);
  const j = storage.journals[model.key];
  const save = s.storageError || (model.draft?.recovered ? 'Recovered local edits · review required' : j && !['committed', 'failed'].includes(j.state) ? `Save ${j.state} · check receipt` : model.draft ? `${model.draft.operations.length} changes saved on this device` : model.saved ? `Saved r${model.saved.composition_revision}` : 'No Composition selected');
  return h('header', {}, h('div', { className: 'bar spread' }, h('div', { className: 'row' }, h(Icon, { name: 'film' }), h('h2', {}, 'STUDIO'), h(Badge, {}, s.owner?.profile || 'No profile')), h('div', { className: 'row' }, h(B, { onClick: () => change({ dialog: 'settings' }), 'aria-label': 'Studio Settings' }, 'Settings'), h(B, { onClick: () => focus ? leaveFocus() : enterFocus() }, focus ? 'Return to chat' : 'Focus Studio'))), h('div', { className: 'bar composition-bar' }, h('span', { className: 'muted', title: s.project || '' }, `Project · ${nativeProject?.name || 'Choose in native Project selector'}`), h('label', { className: 'grow' }, 'Composition', h('select', { value: s.composition || '', disabled: !model.scope, onChange: e => { cancelAutosave?.(); const id = e.target.value || null; const previous = storage.scopes[`${ownerKey(s.owner)}:${s.project}:${id}`] || {}; updateLocal({ composition: id, selected: previous.selected || [], selectedTrack: previous.selectedTrack || null, range: previous.range || null, frame: previous.frame || 0, undo: null, redo: null }); } }, h('option', { value: '' }, 'Choose Composition'), ...(model.compositions || []).map(c => h('option', { key: c.composition_id, value: c.composition_id }, `${c.name} · ${c.composition_id}`)))), h(B, { onClick: () => change({ dialog: 'new' }), disabled: !model.scope }, 'New')), h('div', { className: 'bar spread' }, h('span', { className: 'muted', 'aria-live': 'polite' }, save), model.saved && h(B, { onClick: () => change({ dialog: 'export' }), disabled: Boolean(model.draft || (j && !['committed', 'failed'].includes(j.state))) }, 'Export…')), s.message && h(Notice, {}, s.message), model.draft?.recovered && h('div', { className: 'bar' }, h(B, { onClick: () => change({ dialog: 'conflict' }) }, 'Review recovery')), j && ['unknown', 'pending', 'accepted', 'sending'].includes(j.state) && h('div', { className: 'bar' }, h(B, { onClick: () => reconcile(model.key, model.scope) }, 'Check request status')));
}
function SaveControls({ model }) {
  const j = storage.journals[model.key], d = model.draft;
  const retries = j?.status?.recovery_actions || [];
  const retryAllowed = retries.some(a => (typeof a === 'string' ? a : a.action || '').startsWith('retry_identical'));
  return h('div', { className: 'bar' }, !transportReady(model.s.owner) && h(Notice, { error: true }, 'Focused chat owner differs from the active transport. Drafts are frozen; restore that native connection/profile to resume.'), h(B, { 'aria-pressed': Boolean(model.s.offline), onClick: () => { cancelAutosave?.(); if (d) d.manual = !model.s.offline; persist(); change({ offline: !model.s.offline, message: model.s.offline ? 'Online mode. Review and sync the local batch explicitly.' : 'Local edit mode. Changes stay on this device until you choose Sync.' }); } }, model.s.offline ? 'Local edit mode' : 'Keep edits local'), h(B, { disabled: !d || d.recovered || (j && !['committed', 'failed'].includes(j.state)), onClick: () => { d.manual = false; persist(); return saveDraft(model); } }, 'Sync local changes'), j && !['committed', 'failed'].includes(j.state) && h(B, { disabled: !retryAllowed, title: retryAllowed ? 'Retry exact original UUID, key, CAS and body' : 'The backend must explicitly authorize identical-request retry after reconciliation', onClick: () => transmit(model.key) }, 'Retry identical request'), h(B, { disabled: !model.version, onClick: () => change({ dialog: 'production-action', productionIntent: 'diagnose', productionSelection: model.s.selected }) }, 'Ask Hermes about selection…'), model.catalogMore && h(B, { onClick: model.catalogMore }, 'Load more compositions'));
}
function enterFocus() { persist(); const hash = globalThis.location?.hash?.slice(1); change({ focus: true, returnPath: hash?.startsWith('/') && hash !== '/motion-studio' ? hash : `/${enc(host.state.focusedStoredSessionId.get() || '')}` }); host.navigate('/motion-studio'); }
function leaveFocus() { const path = studioState.get().returnPath; change({ focus: false }); host.navigate(path && path !== '/motion-studio' ? path : '/'); }
function choose(model, clip, event = {}) {
  let ids = event.shiftKey ? model.s.selected.includes(clip.clip_id) ? model.s.selected.filter(id => id !== clip.clip_id) : [...model.s.selected, clip.clip_id] : [clip.clip_id];
  ids = linkedSelection(model.version, ids, event.altKey);
  updateLocal({ selected: ids, selectedTrack: clip.track_id });
}
function CompositionEmpty({ model }) {
  const problem = model.native.error || model.boot.error || model.pcontext.error || model.catalog.error || model.head.error;
  return h(Unavailable, { title: problem ? 'Studio context unavailable' : !model.s.project ? 'Select a native Hermes Project' : 'No Composition selected', reason: problem ? errorText(problem) : !model.s.project ? 'Use Hermes’ native Project selector. Studio never infers identity from a folder, title or name.' : 'Create or choose an independent Composition in this Project. Project files remain available in Assets.', action: model.scope && h(B, { primary: true, onClick: () => change({ dialog: 'new' }) }, 'New composition') });
}
export function qualifiedMediaRoute(result, scope) {
  if (result.transport !== 'same_origin_cookie' || typeof result.relative_stream_route !== 'string' || !result.range_supported) throw new Error('The server did not qualify same-origin authenticated range playback.');
  const route = result.relative_stream_route;
  if (!route.startsWith('/') || route.startsWith('//') || /[\\\\?#\u0000-\u0020]/.test(route) || decodeURIComponent(route).split('/').some(x => x === '..' || x === '.')) throw new Error('Unsafe media route was refused.');
  const prefix = `/api/plugins/motion-studio${API}${projectPath(scope.native_project_id)}/media-access/`;
  const full = route.startsWith(API + '/') ? '/api/plugins/motion-studio' + route : route;
  if (!full.startsWith(prefix) || !full.endsWith('/bytes')) throw new Error('Media route is outside this exact native Project scope.');
  return full;
}
export const MEDIA_BLOB_BYTES = 64 * 1024 * 1024;
const MEDIA_CHUNK_BYTES = 262144;
const MEDIA_MIMES = new Set(['video/mp4', 'video/webm', 'video/quicktime', 'video/x-matroska', 'audio/mp4', 'audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/webm', 'audio/ogg', 'audio/flac']);
const mediaHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export function playableMediaMime(mime) {
  // Never navigate to, embed, or execute arbitrary content (including HTML/SVG).
  if (!MEDIA_MIMES.has(mime) || !globalThis.document?.createElement) return false;
  const support = document.createElement(mime.startsWith('audio/') ? 'audio' : 'video').canPlayType(mime);
  return support === 'maybe' || support === 'probably';
}
export async function verifiedMediaBlob(result, media, limit, fetchChunk, current, supports = playableMediaMime) {
  const check = () => { if (!current()) throw new Error('Media context changed. Bytes discarded; load again explicitly.'); };
  check();
  if (result.transport !== 'authenticated_blob' || typeof result.access_id !== 'string' || !/^[A-Za-z0-9_-]{1,160}$/.test(result.access_id)) throw new Error('Invalid authenticated Blob lease.');
  if (!mediaHash(media.sha256) || result.media_id !== media.media_id || result.sha256 !== media.sha256) throw new Error('Media lease does not match the exact selected pin.');
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MEDIA_BLOB_BYTES || !Number.isSafeInteger(result.byte_length) || result.byte_length < 1 || result.byte_length > limit) throw new Error('Media exceeds the advertised bounded full-Blob memory limit.');
  if (!MEDIA_MIMES.has(result.mime) || !supports(result.mime)) throw new Error('Unknown or browser-unsupported media MIME. No conform or executable fallback is attempted.');
  if (!globalThis.crypto?.subtle?.digest || typeof globalThis.Blob !== 'function') throw new Error('Real WebCrypto and browser Blob support are required.');
  const expires = Date.parse(result.expires_at);
  if (!Number.isFinite(expires) || expires <= Date.now()) throw new Error('Media lease expired. Load again explicitly.');
  const valid = () => { check(); if (Date.now() >= expires) throw new Error('Media lease expired. Load again explicitly.'); };
  const digest = async bytes => {
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    valid();
    return [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, '0')).join('');
  };
  const bytes = new Uint8Array(result.byte_length);
  let offset = 0;
  while (offset < bytes.length) {
    valid();
    const length = Math.min(MEDIA_CHUNK_BYTES, bytes.length - offset);
    const part = await fetchChunk(result.access_id, offset, length);
    valid();
    if (!part || part.media_id !== media.media_id || part.sha256 !== media.sha256 || part.byte_length !== bytes.length || part.mime !== result.mime || part.offset !== offset || !mediaHash(part.chunk_sha256)) throw new Error('Media chunk identity, offset or bounds changed.');
    if (typeof part.bytes_base64 !== 'string' || part.bytes_base64.length !== 4 * Math.ceil(length / 3) || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(part.bytes_base64)) throw new Error('Invalid or oversized base64 media chunk.');
    const decoded = atob(part.bytes_base64);
    if (decoded.length !== length || part.eof !== (offset + length === bytes.length)) throw new Error('Truncated media chunk or incorrect completion marker.');
    const chunk = Uint8Array.from(decoded, x => x.charCodeAt(0));
    if (await digest(chunk) !== part.chunk_sha256) throw new Error('Media chunk SHA-256 mismatch.');
    valid();
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  if (await digest(bytes) !== media.sha256) throw new Error('Complete media SHA-256 mismatch.');
  valid();
  return new Blob([bytes], { type: result.mime });
}
function useMedia(model, media, purpose) {
  const [lease, setLease] = useState(null), [failure, setFailure] = useState(''), [loading, setLoading] = useState(false);
  const resource = useRef(null), sequence = useRef(0), mounted = useRef(true);
  const selection = JSON.stringify([media?.media_id, media?.sha256, purpose, model.s.epoch, model.s.project, model.s.composition, ownerKey(model.s.owner), transportReady(model.s.owner)]);
  const selected = useRef(selection); selected.current = selection;
  const boot = model.boot.data?.data || {}, transports = boot.transport_capabilities || {}, seams = boot.host_seams || {};
  const qualified = transports.range_media && (transports.same_origin_cookie === true || seams.media_transports?.includes('same_origin_cookie'));
  const blobLimit = boot.limits?.media_blob_bytes;
  const blobAvailable = transports.authenticated_blob === true && seams.media_transports?.includes('authenticated_blob') && Number.isSafeInteger(blobLimit) && blobLimit > 0 && blobLimit <= MEDIA_BLOB_BYTES && Boolean(globalThis.crypto?.subtle?.digest && globalThis.URL?.createObjectURL && globalThis.URL?.revokeObjectURL);
  const clear = () => { resource.current?.cancelExpiry?.(); if (resource.current?.blob) URL.revokeObjectURL(resource.current.url); resource.current = null; };
  useEffect(() => {
    mounted.current = true;
    sequence.current++; clear(); setLease(null); setFailure(''); setLoading(false);
    return () => { mounted.current = false; sequence.current++; clear(); };
  }, [selection]);
  const available = Boolean(media?.media_id && mediaHash(media?.sha256) && (qualified || blobAvailable));
  const resolve = async (requested = null) => {
    // Button events are not transport names. No loading occurs during render/effect.
    const transport = requested === 'authenticated_blob' ? requested : qualified ? 'same_origin_cookie' : 'authenticated_blob';
    if (!available || (transport === 'authenticated_blob' && !blobAvailable)) { setFailure('No installed authenticated media transport with safe browser bounds is advertised.'); return; }
    if (loading) return;
    const cap = capture(), pin = { media_id: media.media_id, sha256: media.sha256 }, scope = clone(model.scope), path = model.ppath, token = ++sequence.current, key = selection;
    const current = () => mounted.current && token === sequence.current && selected.current === key && isCurrent(cap);
    clear(); setLease(null); setFailure(''); setLoading(true);
    try {
      const result = await command(path + '/media-access', 'OP-MEDIA-ACCESS', scope, { media_sha256: pin.sha256 }, { media_id: pin.media_id, purpose, transport, requested_ttl_seconds: 300 }, `${scopeKey(scope)}:media:${pin.media_id}`);
      if (!current()) return;
      let url;
      if (transport === 'authenticated_blob') {
        const blob = await verifiedMediaBlob(result, pin, blobLimit, async (id, offset, length) => {
          if (!current()) throw new Error('Media context changed.');
          const response = await read(`${path}/media-access/${enc(id)}/chunks`, { offset, length }, scope, cap);
          if (!current()) throw new Error('Media context changed.');
          return response.data;
        }, current);
        if (!current()) return;
        url = URL.createObjectURL(blob);
      } else {
        if (result.media_id !== pin.media_id || result.sha256 !== pin.sha256 || !playableMediaMime(result.mime) || !(Date.parse(result.expires_at) > Date.now())) throw new Error('Media pin, browser MIME support or lease expiry is invalid.');
        url = qualifiedMediaRoute(result, scope);
      }
      if (!current()) { if (transport === 'authenticated_blob') URL.revokeObjectURL(url); return; }
      resource.current = { url, blob: transport === 'authenticated_blob', selection: key, cap, expires_at: result.expires_at };
      resource.current.cancelExpiry = context.setTimeout(() => {
        if (!current()) return;
        clear(); setLease(null); setFailure('Media access expired. Load again explicitly to renew authorization.');
      }, Math.max(0, Date.parse(result.expires_at) - Date.now()));
      setLease(resource.current);
    } catch (e) {
      if (current()) { clear(); setLease(null); setFailure(`${errorText(e)} Nothing was loaded. Restore the connection or renew access with an explicit Load retry.`); }
    } finally { if (current()) setLoading(false); }
  };
  const usable = lease && lease.selection === selection && isCurrent(lease.cap) && Date.parse(lease.expires_at) > Date.now() ? lease : null;
  const fail = () => { sequence.current++; clear(); setLease(null); setLoading(false); setFailure('Playback failed, disconnected, unsupported or expired. Load again explicitly; no automatic retry or conform was attempted.'); };
  return { lease: usable, failure, available, blobAvailable, loading, resolve, fail };
}
function Monitor({ model, reviewMedia = null, purpose = 'preview' }) {
  const mediaRef = useRef(null);
  const [playing, setPlaying] = useState(false), [buffering, setBuffering] = useState(false), [loop, setLoop] = useState(false), [guides, setGuides] = useState(false), [volume, setVolume] = useState(1), [fit, setFit] = useState('fit');
  const { s, version } = model;
  const source = !reviewMedia && model.s.monitor === 'source' ? model.s.sourceAsset : null;
  const sourceStream = source?.streams?.find(stream => stream.type === 'video') || source?.streams?.find(stream => stream.type === 'audio');
  const preview = model.head.data?.data?.preview;
  const medium = reviewMedia || (source ? { media_id: source.media_ids?.[0], sha256: source.sha256 } : preview?.media_id ? preview : null);
  const media = useMedia(model, medium, purpose);
  const fps = reviewMedia?.probe?.fps || reviewMedia?.fps || sourceStream?.rate || version?.format.fps || { num: 24, den: 1 };
  const frame = s.monitor === 'source' ? s.sourceFrame : s.frame;
  const duration = reviewMedia?.probe?.duration_frames || reviewMedia?.duration_frames || (source ? sourceStream?.duration_frames || 0 : version?.format.duration_frames || 0);
  function seek(n) {
    const next = Math.max(0, Math.min(Math.max(0, duration - 1), n));
    updateLocal(s.monitor === 'source' ? { sourceFrame: next } : { frame: next });
    if (mediaRef.current && media.lease) mediaRef.current.currentTime = next * fps.den / fps.num;
  }
  useEffect(() => { if (mediaRef.current && !playing && media.lease) { const target = frame * fps.den / fps.num; if (Math.abs(mediaRef.current.currentTime - target) > fps.den / fps.num / 2) mediaRef.current.currentTime = target; } }, [frame, playing, media.lease]);
  const toggle = guard(async () => { if (!mediaRef.current || !media.lease) { await media.resolve(); return; } if (mediaRef.current.paused) await mediaRef.current.play(); else mediaRef.current.pause(); });
  return h('section', { 'aria-label': purpose === 'review' ? 'Encoded candidate player' : 'Media monitor', tabIndex: 0, onKeyDown: e => monitorKeys(e, model, seek, toggle) }, h('div', { className: 'bar spread' }, h('div', { className: 'row' }, h(B, { onClick: () => updateLocal({ monitor: 'program' }), 'aria-pressed': s.monitor === 'program' }, 'Program'), h(B, { onClick: () => updateLocal({ monitor: 'source' }), 'aria-pressed': s.monitor === 'source' }, 'Source')), h(Badge, {}, purpose === 'review' ? 'Encoded candidate' : preview?.version_id && preview.version_id !== model.saved?.version_id ? `Preview ${preview.version_id}; edits r${model.saved?.composition_revision}` : medium ? 'Pinned media' : 'Rendered preview required')), media.blobAvailable && h(B, { disabled: !media.available || media.loading, title: 'Explicit serial authenticated REST load; full Blob limited to the advertised maximum, never autoplay', onClick: () => media.resolve('authenticated_blob') }, media.loading ? 'Loading and verifying media…' : 'Load verified Blob fallback'), media.failure && h(Notice, { error: true }, media.failure), h('div', { className: 'monitor' }, media.lease ? h('video', { ref: mediaRef, src: media.lease.url, controls: true, preload: 'metadata', playsInline: true, style: { objectFit: fit === 'fit' ? 'contain' : 'none' }, onPlay: () => setPlaying(true), onPause: () => setPlaying(false), onWaiting: () => setBuffering(true), onPlaying: () => setBuffering(false), onError: media.fail, onTimeUpdate: e => { const f = Math.max(0, Math.min(Math.max(0, duration - 1), Math.floor(e.currentTarget.currentTime * fps.num / fps.den))); if (loop && s.range && f >= s.range.end_frame) { e.currentTarget.currentTime = s.range.start_frame * fps.den / fps.num; return; } change(s.monitor === 'source' ? { sourceFrame: f } : { frame: f }); }, onEnded: () => { if (loop && s.range) { mediaRef.current.currentTime = s.range.start_frame * fps.den / fps.num; guard(() => mediaRef.current.play())(); } else setPlaying(false); } }) : h(Unavailable, { title: medium ? 'Playback not opened' : 'No playable media for this view', reason: media.failure || (medium ? 'Open the exact authorized media; no synthetic playback clock is used.' : s.monitor === 'source' ? 'Select a registered source in Assets.' : 'Prepare a rendered preview of these saved edits. Source playback remains separate.'), action: medium ? h(B, { onClick: media.resolve }, 'Open playback') : h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'diagnose' }), disabled: !version }, 'Prepare preview…') }), guides && h('div', { className: 'guides', 'aria-hidden': true })), h('div', { className: 'bar' }, h(B, { onClick: () => seek(0), 'aria-label': 'Go to start' }, '|‹'), h(B, { onClick: () => seek(frame - 1), 'aria-label': 'Previous frame' }, '‹'), h(B, { onClick: toggle, 'aria-label': playing ? 'Pause' : 'Play', disabled: !medium }, h(Icon, { name: playing ? 'pause' : 'play' })), h(B, { onClick: () => seek(frame + 1), 'aria-label': 'Next frame' }, '›'), h(B, { onClick: () => seek(duration - 1), 'aria-label': 'Last frame' }, '›|'), h('span', { className: 'mono', 'aria-live': 'off' }, `${timecode(frame, fps)} NDF`), h(Badge, {}, buffering ? 'Buffering · clock paused by media' : playing ? 'Playing actual media' : 'Paused'), medium && h(B, { onClick: media.resolve }, 'Renew media access')), h('div', { className: 'body' }, h('div', { className: 'grid' }, h(NumberField, { label: 'Current frame', value: frame, onChange: v => { try { seek(safeInteger(v)); } catch (e) { change({ message: errorText(e) }); } } }), h('label', {}, 'Monitor volume · not clip gain', h('input', { type: 'range', min: 0, max: 1, step: .01, value: volume, onChange: e => { const n = Number(e.target.value); setVolume(n); if (mediaRef.current) mediaRef.current.volume = n; } }))), h('div', { className: 'row' }, h(B, { onClick: () => setLoop(!loop), 'aria-pressed': loop }, 'Loop range'), h(B, { onClick: () => setGuides(!guides), 'aria-pressed': guides }, 'Safe guides'), h(B, { onClick: () => setFit(fit === 'fit' ? '100%' : 'fit') }, fit === 'fit' ? 'Fit' : '100%'), h('span', { className: 'muted' }, `Frame ${frame} / ${duration} · ${fps.num}/${fps.den} fps`)), h('small', {}, mediaRef.current?.getVideoPlaybackQuality ? `Dropped frames: ${mediaRef.current.getVideoPlaybackQuality().droppedVideoFrames}` : 'Dropped-frame measurement not available before playback.')));
}
function monitorKeys(e, model, seek, toggle) {
  if (e.defaultPrevented || e.target.closest('input,textarea,select,button,dialog,[contenteditable=true]')) return;
  const f = model.s.frame;
  if (e.key === ' ') { e.preventDefault(); toggle(); }
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); seek(f + (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 10 : 1)); }
  else if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); seek(e.key === 'Home' ? 0 : model.version.format.duration_frames - 1); }
  else if (e.key.toLowerCase() === 'i') updateLocal({ range: { start_frame: f, end_frame: Math.max(f + 1, model.s.range?.end_frame || f + 1) } });
  else if (e.key.toLowerCase() === 'o') updateLocal({ range: { start_frame: model.s.range?.start_frame ?? f, end_frame: f + 1 } });
}
function NewComposition({ model }) {
  const [name, setName] = useState('Untitled composition'), [preset, setPreset] = useState('landscape-hd');
  const [width, setWidth] = useState('1920'), [height, setHeight] = useState('1080'), [num, setNum] = useState('30'), [den, setDen] = useState('1'), [sample, setSample] = useState('48000');
  const choosePreset = id => {
    const p = COMPOSITION_PRESETS.find(p => p.id === id);
    if (!p) return;
    setPreset(id); setWidth(String(p.width)); setHeight(String(p.height)); setNum(String(p.fps)); setDen('1'); setSample('48000');
  };
  const custom = setter => value => { setPreset('custom'); setter(value); };
  return h(Modal, { title: 'New composition' },
    h('p', { className: 'muted' }, 'Choose a canvas, then add media. Your original files stay unchanged. This edit belongs to the selected Hermes Project.'),
    h('label', {}, 'Name', h('input', { value: name, maxLength: 120, onChange: e => setName(e.target.value), autoFocus: true })),
    h('label', {}, 'Canvas preset', h('select', { value: preset, onChange: e => choosePreset(e.target.value) },
      ...COMPOSITION_PRESETS.map(p => h('option', { key: p.id, value: p.id }, `${p.label} · ${p.width} × ${p.height} · ${p.fps} fps`)),
      preset === 'custom' ? h('option', { value: 'custom' }, 'Custom settings') : null)),
    h('p', {}, `${width} × ${height} pixels · ${num}/${den} fps · ${sample} Hz stereo. The timeline grows as you add media.`),
    h('details', {}, h('summary', {}, 'Advanced canvas settings'), h('div', { className: 'grid' },
      h(NumberField, { label: 'Canvas width', unit: 'pixels', value: width, min: 1, onChange: custom(setWidth) }),
      h(NumberField, { label: 'Canvas height', unit: 'pixels', value: height, min: 1, onChange: custom(setHeight) }),
      h(NumberField, { label: 'Frame-rate numerator', unit: 'rational', value: num, min: 1, onChange: custom(setNum) }),
      h(NumberField, { label: 'Frame-rate denominator', unit: 'rational', value: den, min: 1, onChange: custom(setDen) }),
      h(NumberField, { label: 'Audio sample rate', unit: 'Hz', value: sample, min: 1, onChange: custom(setSample) }))),
    h(B, { primary: true, disabled: !name.trim(), onClick: async () => {
      const r = await command(model.ppath + '/compositions', 'OP-COMPOSITION-CREATE', model.scope, { catalog_revision: model.catalog.data.data.catalog_revision }, { name: name.trim(), format: { width: safeInteger(width, 1), height: safeInteger(height, 1), fps: { num: safeInteger(num, 1), den: safeInteger(den, 1) }, sample_rate: safeInteger(sample, 1), channels: 2, duration_frames: 0 }, template_ref: null }, `${scopeKey(model.scope)}:catalog`);
      const id = r.summary?.composition_id || r.composition?.composition_id || r.composition_id;
      if (id) updateLocal({ composition: id, dialog: null, frame: 0, tab: 'Assets' });
    } }, 'Create composition'));
}
function EditPlacement({ model }) {
  const c = model.version?.clips.find(c => c.clip_id === model.s.selected[0]);
  const [start, setStart] = useState(String(c?.start_frame ?? 0)), [end, setEnd] = useState(String(c?.end_frame ?? 1)), [track, setTrack] = useState(c?.track_id || ''), [slip, setSlip] = useState(String(c?.source_mapping?.in_index ?? 0));
  const [mode, setMode] = useState('move');
  if (!c) return h(Modal, { title: 'Edit placement' }, h('p', {}, 'Select a placement first.'));
  return h(Modal, { title: 'Edit placement · precise timing' }, h('p', { className: 'mono' }, `${c.clip_id} · [${c.start_frame}, ${c.end_frame}) · end exclusive`), h('label', {}, 'Edit mode', h('select', { value: mode, onChange: e => setMode(e.target.value) }, ...['move', 'trim', 'slip'].map(v => h('option', { key: v, value: v }, v)))), h('div', { className: 'grid' }, h(NumberField, { label: 'Timeline start', value: start, onChange: setStart }), h(NumberField, { label: 'Timeline end · exclusive', value: end, onChange: setEnd, min: 1 }), h(NumberField, { label: 'Source in', value: slip, onChange: setSlip, disabled: c.source_mapping?.domain !== 'frame' }), h('label', {}, 'Destination track', h('select', { value: track, onChange: e => setTrack(e.target.value) }, ...model.version.tracks.map(t => h('option', { key: t.track_id, value: t.track_id, disabled: t.locked }, `${t.name}${t.locked ? ' · Locked' : ''}`))))), h('p', { className: 'muted' }, 'Move preserves duration and source bounds. Trim preserves speed. Slip preserves the output range. Linked placements retain their relationship; unsupported source mappings are rejected, never rounded silently.'), h(B, { primary: true, onClick: () => { let ops; if (mode === 'move') { if (model.s.selected.length > 1 && track !== c.track_id) throw new Error('Move linked or multi-track selections on their existing tracks, or edit explicit destinations individually.'); ops = [buildMove(model.version, model.s.selected, safeInteger(start) - c.start_frame, track === c.track_id ? null : track)]; } else if (mode === 'trim') { const ds = safeInteger(start) - c.start_frame, de = safeInteger(end, 1) - c.end_frame; ops = model.version.clips.filter(x => model.s.selected.includes(x.clip_id)).map(x => buildTrim(x, x.start_frame + ds, x.end_frame + de, model.version.format.fps)); } else { if (c.source_mapping?.domain !== 'frame') throw new Error('Source conform mapping is unavailable.'); const d = safeInteger(slip) - c.source_mapping.in_index; ops = [{ op: 'clip.trim', clip_id: c.clip_id, start_frame: c.start_frame, end_frame: c.end_frame, source_mapping: { ...c.source_mapping, in_index: c.source_mapping.in_index + d, out_index: c.source_mapping.out_index + d }, link_policy: 'preserve' }]; } stage(model, ops, `${mode} selection`); change({ dialog: null }); } }, `Apply to ${model.s.selected.length} selected placement(s)`));
}
function confirmDelete(model, ripple = false) { change({ dialog: 'delete', ripple }); }
function DeleteDialog({ model }) {
  const [ack, setAck] = useState(false);
  const clips = model.version.clips.filter(c => model.s.selected.includes(c.clip_id));
  let range = model.s.range;
  if (!range && clips.length && clips.every(c => c.start_frame === clips[0].start_frame && c.end_frame === clips[0].end_frame)) range = { start_frame: clips[0].start_frame, end_frame: clips[0].end_frame };
  const trackIds = [...new Set(clips.map(c => c.track_id))];
  const affected = range ? model.version.clips.filter(c => trackIds.includes(c.track_id) && c.end_frame > range.start_frame) : clips;
  return h(Modal, { title: model.s.ripple ? 'Remove and close gap' : 'Remove placements' }, h('p', {}, model.s.ripple ? range ? `Close [${range.start_frame}, ${range.end_frame}) across ${trackIds.length} explicit tracks. ${affected.length} placements may change.` : 'Choose one contiguous ruler range, or placements with identical bounds.' : `Remove ${clips.length} placements and leave a gap. Original source bytes are retained.`), h('ul', {}, ...affected.map(c => h('li', { key: c.clip_id }, `${c.clip_id} · ${c.start_frame}–${c.end_frame} · ${model.version.tracks.find(t => t.track_id === c.track_id)?.name}`))), h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: ack, onChange: e => setAck(e.target.checked) }), 'I reviewed the complete affected selection and tracks.'), h(B, { disabled: !ack || !clips.length || (model.s.ripple && !range), onClick: () => { if (affected.some(c => model.version.tracks.find(t => t.track_id === c.track_id)?.locked)) throw new Error('Locked participants block the entire edit.'); if (model.s.ripple) { const a = range.start_frame, b = range.end_frame; if (b <= a) throw new Error('Range end must be after its start.'); if (affected.some(c => (c.start_frame < a && c.end_frame > a) || (c.start_frame < b && c.end_frame > b))) throw new Error('Split placements at both range boundaries first; the affected set must be reviewed again before closing the gap.'); stage(model, [{ op: 'timeline.ripple', track_ids: trackIds, range, action: 'delete', delta_frames: a - b, link_policy: 'preserve', expected_affected_ids: affected.map(c => c.clip_id) }], 'Ripple delete reviewed range', affected.map(c => c.clip_id)); } else stage(model, [{ op: 'entity.delete', targets: clips.map(c => ({ kind: 'clip', id: c.clip_id })), expected_dependency_ids: [] }], 'Remove placements'); updateLocal({ dialog: null, selected: [] }); } }, model.s.ripple ? 'Remove and close gap' : 'Remove selection'));
}
function TimelineTools({ model }) {
  const { s } = model;
  const menu = useRef(null), menuId = useRef(`timeline-actions-${uid()}`).current;
  const zoom = className => h('label', { className }, 'Timeline zoom', h('input', { type: 'range', min: .5, max: 8, step: .1, value: s.zoom, onChange: e => updateLocal({ zoom: Number(e.target.value) }) }));
  const openMore = e => {
    const panel = menu.current;
    if (!panel) return;
    if (!panel.togglePopover()) return;
    const button = e.currentTarget.getBoundingClientRect(), bounds = panel.getBoundingClientRect();
    const viewport = e.currentTarget.ownerDocument.documentElement;
    panel.style.left = `${Math.max(8, Math.min(button.left, viewport.clientWidth - bounds.width - 8))}px`;
    panel.style.top = `${Math.max(8, Math.min(button.bottom + 4, viewport.clientHeight - bounds.height - 8))}px`;
  };
  return h('div', { className: 'bar' }, h('h3', {}, 'TIMELINE'),
    h(B, { title: 'Select and move clips on the timeline', onClick: () => updateLocal({ tool: 'select' }), 'aria-pressed': s.tool === 'select' }, 'Select'),
    h(B, { title: 'Split selected clips at the playhead', disabled: !s.selected.length, onClick: () => stage(model, buildSplit(model.version, s.selected, s.frame), 'Split selection') }, 'Split'),
    h(B, { title: 'Snap moving clips to nearby edges and the playhead', onClick: () => updateLocal({ snap: !s.snap }), 'aria-pressed': s.snap }, 'Snap'),
    h(B, { title: 'Fit the complete timeline to the available width', onClick: () => updateLocal({ zoom: 1 }) }, 'Fit'), zoom('timeline-zoom'),
    h(B, { title: 'Open editing actions, track controls and range settings', onClick: openMore, 'aria-haspopup': 'dialog', 'aria-controls': menuId }, 'More…'),
    h('div', { ref: menu, id: menuId, popover: 'auto', className: 'timeline-more-menu', role: 'dialog', 'aria-label': 'More timeline actions' },
      h('h3', {}, 'Timeline actions'),
      h('div', { className: 'row', onClick: () => menu.current?.hidePopover() },
        h(B, { onClick: () => updateLocal({ tool: 'slip' }), 'aria-pressed': s.tool === 'slip' }, 'Slip'),
        h(B, { disabled: !s.selected.length, onClick: () => change({ dialog: 'placement' }) }, 'Edit placement…'),
        h(B, { disabled: !s.selected.length, onClick: () => confirmDelete(model) }, 'Remove…'),
        h(B, { disabled: !s.selected.length, onClick: () => confirmDelete(model, true) }, 'Ripple…'),
        h(B, { onClick: () => updateLocal({ table: !s.table }), 'aria-pressed': s.table }, 'Table'),
        h(B, { onClick: () => change({ dialog: 'track' }), disabled: !model.version }, 'Add track…'),
        h(B, { disabled: !s.undo || Boolean(model.draft), onClick: () => undo(model, 'undo') }, 'Undo'),
        h(B, { disabled: !s.redo || Boolean(model.draft), onClick: () => undo(model, 'redo') }, 'Redo')),
      zoom('timeline-more-zoom'),
      h(NumberField, { label: 'Range in', value: s.range?.start_frame ?? '', onChange: v => updateLocal({ range: { start_frame: safeInteger(v), end_frame: s.range?.end_frame || safeInteger(v) + 1 } }) }),
      h(NumberField, { label: 'Range out · exclusive', value: s.range?.end_frame ?? '', onChange: v => updateLocal({ range: { start_frame: s.range?.start_frame || 0, end_frame: safeInteger(v, 1) } }) })));
}
async function undo(model, direction) { const r = await command(model.cpath + '/undo', 'OP-UNDO', model.scope, model.cas, { undo_token: model.s[direction], direction }); change(direction === 'undo' ? { undo: null, redo: r.undo_token } : { redo: null, undo: r.undo_token }); }
// Viewport extent is not composition duration: an empty edit still needs a ruler.
export function timelineScale(format, width) {
  const nominal = Math.ceil(format.fps.num / format.fps.den);
  const duration = Math.max(format.duration_frames, nominal * 10);
  const target = Math.max(1, duration / Math.max(1, Math.floor(width / 120)));
  const unit = target >= nominal ? nominal : 1;
  const magnitude = unit * 10 ** Math.floor(Math.log10(target / unit));
  const step = [1, 2, 5, 10].map(n => n * magnitude).find(n => n >= target);
  const ticks = [];
  for (let frame = 0; frame < duration; frame += step) ticks.push({ frame, label: timecode(frame, format.fps) });
  return { duration, px: width / duration, step, ticks };
}
const timelineStyles = `
.ms.timeline-pane{container-type:size;overflow:hidden}
.ms .focusgrid{grid-template-rows:minmax(0,2fr) minmax(0,1fr)}
.ms .timeline-editor{--ms-track-header:210px;display:flex;flex-direction:column;min-height:0;min-width:0;flex:1;overflow:hidden}
.ms .timeline-tools{flex:none;min-width:0}
.ms .timeline-tools>.bar{flex-wrap:wrap;white-space:nowrap;padding:5px 8px;gap:6px}
.ms .timeline-tools>.bar>*{flex-shrink:0}
.ms .timeline-tools label{flex-direction:row;align-items:center;gap:6px}
.ms .timeline-tools input[type=range]{width:100px}
.ms .timeline-fields{flex:none;flex-wrap:nowrap;white-space:nowrap;padding:5px 8px;gap:12px}
.ms .timeline-fields>*{flex-shrink:0}
.ms .timeline-fields label{font-size:11px;gap:6px;flex-direction:row;align-items:center}
.ms .timeline-fields input{width:64px;min-height:28px;height:28px;padding:3px 6px;font-size:12px}
.ms .timeline-fields .timeline-format{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis}
.ms .timeline-more-menu{position:fixed;inset:auto;margin:0;width:min(320px,calc(100vw - 16px));max-height:calc(100vh - 16px);overflow:auto;padding:12px;white-space:normal;border:1px solid var(--ms-line);border-radius:6px;background:var(--ms-panel);color:var(--ms-text);box-shadow:0 8px 24px #0006}
.ms .timeline-more-menu:popover-open{display:flex;flex-direction:column;gap:12px}
.ms .timeline-more-menu label{flex-direction:column;align-items:stretch}
.ms .timeline-more-menu input[type=range]{width:100%}
.ms .edit-timeline{position:relative;display:flex;flex-direction:column;min-height:0;flex:1;overflow:auto;overscroll-behavior:contain;scrollbar-color:var(--ms-muted) var(--ms-bg)}
.ms .timeline-rows{display:flex;flex-direction:column;flex:1;min-height:0}
.ms .timeline-table{min-height:0;flex:1;overflow:auto}
.ms .edit-timeline .trackhead{flex-shrink:0;width:var(--ms-track-header);min-width:var(--ms-track-header);padding:2px 4px;display:grid;grid-template-columns:minmax(20px,1fr) auto;align-items:center;gap:2px}
.ms .edit-timeline .trackhead .tracktitle{min-height:18px;padding:0 3px;line-height:18px;text-align:left}
.ms .edit-timeline .trackhead .row{flex-wrap:nowrap;gap:3px}
.ms .edit-timeline .trackhead .row button{min-height:22px;min-width:24px;padding:1px 3px;font-size:11px}
.ms .edit-timeline .ruler{flex:none;height:26px;border-bottom:1px solid var(--ms-line)}
.ms .edit-timeline .ruler .lane{min-height:26px;height:26px;cursor:crosshair}
.ms .edit-timeline .ruler .trackhead{z-index:4;font-size:10px;padding:5px 6px;display:block}
.ms .timeline-tick{position:absolute;top:0;bottom:0;padding:5px 0 0 6px;border-left:1px solid var(--ms-muted);white-space:nowrap;font-size:11px;pointer-events:none}
.ms .edit-timeline .track{flex:1;min-height:27px;max-height:64px}
.ms .edit-timeline .track>.lane{min-height:0;flex-shrink:0;cursor:crosshair}
.ms .edit-timeline .tracktitle{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ms .edit-timeline .clip{height:calc(100% - 12px);top:6px;border-radius:4px;min-width:0}
.ms .edit-timeline .track[data-kind=audio] .clip{border-style:dashed}
.ms .edit-timeline .playhead{width:2px;z-index:2}
.ms .ruler .playhead:before{content:'';position:absolute;left:-4px;top:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:8px solid var(--ms-accent)}
.ms .timeline-empty{position:absolute;right:8px;bottom:4px;max-width:calc(100% - var(--ms-track-header) - 16px);padding:0 4px;display:flex;align-items:center;gap:8px;font-size:11px;background:var(--ms-bg);pointer-events:none}
.ms .timeline-empty button{pointer-events:auto}
.ms .timeline-empty p{margin:0;max-width:60ch}
@container(max-width:600px){.ms .timeline-editor{--ms-track-header:170px}.ms .timeline-tools>.bar>h3,.ms .timeline-zoom,.ms .timeline-empty p{display:none}}
`;
export function TimelineContent({ model }) {
  const { s, version } = model;
  const [drag, setDrag] = useState(null);
  const [availableWidth, setAvailableWidth] = useState(1000);
  const ref = useRef(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const gutter = element.querySelector('.trackhead')?.getBoundingClientRect().width || 0;
      setAvailableWidth(Math.max(1, element.clientWidth - gutter));
    };
    measure();
    if (typeof ResizeObserver !== 'function') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [version?.version_id, s.table]);
  if (!version) return h(CompositionEmpty, { model });
  const width = availableWidth * s.zoom;
  const { duration, px, step, ticks } = timelineScale(version.format, width);
  function snap(frame, excluded, alt) {
    let n = Math.max(0, Math.round(frame));
    if (s.snap && !alt) {
      const targets = [s.frame, s.range?.start_frame, s.range?.end_frame, ...version.clips.filter(c => !excluded.includes(c.clip_id)).flatMap(c => [c.start_frame, c.end_frame])].filter(Number.isFinite);
      targets.sort((a, b) => Math.abs(a - n) - Math.abs(b - n) || a - b);
      if (targets.length && Math.abs(targets[0] - n) * px <= 8) n = targets[0];
    }
    return n;
  }
  function pointerDown(e, clip) {
    if (e.button !== 0) return;
    choose(model, clip, e);
    if (version.tracks.find(t => t.track_id === clip.track_id)?.locked) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ clip, origin: e.clientX, original: clip.start_frame, delta: 0, edge: e.target.dataset.edge || null, ids: linkedSelection(version, e.shiftKey ? [...new Set([...s.selected, clip.clip_id])] : [clip.clip_id], e.altKey) });
  }
  function pointerMove(e) {
    if (!drag) return;
    const offset = (e.clientX - drag.origin) / px;
    const anchor = drag.edge === 'end' ? drag.clip.end_frame : drag.clip.start_frame;
    setDrag({ ...drag, delta: snap(anchor + offset, drag.ids, e.altKey) - anchor });
  }
  function pointerUp() {
    if (!drag) return;
    const d = drag; setDrag(null);
    if (!d.delta) return;
    guard(() => {
      if (d.edge) stage(model, version.clips.filter(c => d.ids.includes(c.clip_id)).map(c => buildTrim(c, c.start_frame + (d.edge === 'start' ? d.delta : 0), c.end_frame + (d.edge === 'end' ? d.delta : 0), version.format.fps)), 'Trim placement edges');
      else if (s.tool === 'slip') { const m = d.clip.source_mapping; if (m?.domain !== 'frame') throw new Error('Slip requires an available source-frame mapping.'); stage(model, [{ op: 'clip.trim', clip_id: d.clip.clip_id, start_frame: d.clip.start_frame, end_frame: d.clip.end_frame, source_mapping: { ...m, in_index: safeInteger(m.in_index + d.delta), out_index: safeInteger(m.out_index + d.delta, 1) }, link_policy: 'preserve' }], 'Slip source range'); }
      else stage(model, [buildMove(version, d.ids, d.delta)], 'Move placements');
    })();
  }
  const seek = e => {
    const bounds = e.currentTarget.getBoundingClientRect();
    updateLocal({ frame: Math.min(duration - 1, Math.max(0, Math.round((e.clientX - bounds.left) / px))) });
  };
  const grid = {
    width,
    backgroundImage: 'linear-gradient(to right,var(--ms-line) 1px,transparent 1px)',
    backgroundSize: `${step * px}px 100%`
  };
  const onKeyDown = e => {
    if (e.key === 'Escape') setDrag(null);
    if (e.defaultPrevented || e.target.closest('input,textarea,select,button,dialog,[contenteditable=true]')) return;
    if (e.key.toLowerCase() === 's') { e.preventDefault(); guard(() => stage(model, buildSplit(version, s.selected, s.frame), 'Split selection'))(); }
    else if (e.key === 'Delete') { e.preventDefault(); confirmDelete(model, e.shiftKey); }
    else if (e.key.toLowerCase() === 'v') updateLocal({ tool: 'select' });
    else if (e.key.toLowerCase() === 'y') updateLocal({ tool: 'slip' });
    else if (e.key.toLowerCase() === 'f') updateLocal({ zoom: 1 });
    else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); guard(() => undo(model, e.shiftKey ? 'redo' : 'undo'))(); }
    else monitorKeys(e, model, f => updateLocal({ frame: f }), () => change({ message: 'Focus the Program monitor to control its actual media playback.' }));
  };
  const playhead = () => h('div', { className: 'playhead', style: { left: s.frame * px }, 'aria-hidden': true });
  const table = () => h('table', {}, h('caption', {}, 'Precise placement alternative'),
    h('thead', {}, h('tr', {}, ...['Placement', 'Track', 'In', 'Out', 'Actions'].map(t => h('th', { key: t, scope: 'col' }, t)))),
    h('tbody', {}, ...version.clips.map(c => h('tr', { key: c.clip_id }, h('td', {}, c.clip_id),
      h('td', {}, version.tracks.find(t => t.track_id === c.track_id)?.name), h('td', {}, c.start_frame), h('td', {}, c.end_frame),
      h('td', {}, h(B, { onClick: () => { choose(model, c); change({ dialog: 'placement' }); } }, 'Edit timing…'))))));
  const track = t => h('div', { key: t.track_id, className: 'track', 'data-kind': t.kind },
    h('div', { className: 'trackhead' }, h('button', { className: 'tracktitle', type: 'button',
      onClick: () => updateLocal({ selectedTrack: t.track_id, selected: [] }), title: `Select track ${t.name}`, 'aria-pressed': s.selectedTrack === t.track_id }, t.name),
    h('div', { className: 'row' },
      h(B, { 'aria-label': `${t.locked ? 'Unlock' : 'Lock'} ${t.name}`, onClick: () => stage(model, [{ op: 'track.update', track_id: t.track_id, name: t.name, order: t.order, locked: !t.locked, visible: t.visible, muted: t.muted }], `Toggle ${t.name} lock`) }, t.locked ? 'Unlock' : 'Lock'),
      h(B, { 'aria-label': `${t.kind === 'audio' ? t.muted ? 'Unmute' : 'Mute' : t.visible ? 'Hide' : 'Show'} ${t.name}`, onClick: () => stage(model, [{ op: 'track.update', track_id: t.track_id, name: t.name, order: t.order, locked: t.locked, visible: t.kind === 'audio' ? t.visible : !t.visible, muted: t.kind === 'audio' ? !t.muted : t.muted }], `Toggle ${t.name} inclusion`) }, t.kind === 'audio' ? t.muted ? 'Unmute' : 'Mute' : t.visible ? 'Hide' : 'Show'),
      h(B, { title: 'Solo is unavailable for rendered previews; export inclusion is unchanged', disabled: true, 'aria-label': `Monitor-only solo ${t.name}`, 'aria-pressed': s.solo === t.track_id, onClick: () => change({ solo: s.solo === t.track_id ? null : t.track_id, message: 'Monitor-only solo is unavailable for this rendered preview; export inclusion is unchanged.' }) }, 'Solo'))),
    h('div', { className: 'lane', style: grid, onClick: e => { if (e.target === e.currentTarget) seek(e); } }, playhead(),
      ...version.clips.filter(c => c.track_id === t.track_id).map(c => h('button', { key: c.clip_id, type: 'button', className: 'clip',
        'aria-label': `${c.subject.kind} placement ${c.clip_id}, frames ${c.start_frame} to ${c.end_frame}, ${t.name}`, 'aria-pressed': s.selected.includes(c.clip_id),
        style: { left: c.start_frame * px + (drag?.ids.includes(c.clip_id) && !drag.edge ? drag.delta * px : 0), width: Math.max(1, (c.end_frame - c.start_frame) * px) },
        onClick: e => { e.stopPropagation(); if (!drag) choose(model, c, e); }, onDoubleClick: () => change({ dialog: 'placement' }),
        onPointerDown: e => pointerDown(e, c), onPointerMove: pointerMove, onPointerUp: pointerUp, onPointerCancel: () => setDrag(null) },
      h('span', { className: 'handle start', 'data-edge': 'start', 'aria-hidden': true }),
      h('span', { style: { paddingInline: 9 } }, `${c.subject.kind} · ${c.subject.id}`),
      h('span', { className: 'handle end', 'data-edge': 'end', 'aria-hidden': true })))));
  return h('div', { className: 'timeline-editor', tabIndex: 0, 'aria-label': 'Composition timeline', onKeyDown },
    h('style', {}, timelineStyles), h('div', { className: 'timeline-tools' }, h(TimelineTools, { model })),
    h('div', { className: 'bar timeline-fields' }, h('output', { className: 'mono', 'aria-label': 'Playhead timecode' }, timecode(s.frame, version.format.fps)),
      h(NumberField, { label: 'Playhead', value: s.frame, onChange: v => updateLocal({ frame: safeInteger(v) }) }),
      h('span', { className: 'mono muted timeline-format', title: `${version.format.fps.num}/${version.format.fps.den} fps · NDF · ${version.format.duration_frames} frames` }, `${version.format.fps.num}/${version.format.fps.den} fps · NDF · ${version.format.duration_frames} frames`)),
    drag && h('div', { className: 'dragreadout', role: 'status' }, `${drag.edge ? 'Trim' : s.tool} ${drag.delta >= 0 ? '+' : ''}${drag.delta} frames · release to apply · Escape to cancel`),
    s.table ? h('div', { className: 'timeline-table' }, table()) : h('div', { className: 'timeline edit-timeline', ref },
      h('div', { className: 'timeline-rows', style: { minWidth: `calc(${width}px + var(--ms-track-header))` } },
        h('div', { className: 'ruler' }, h('div', { className: 'trackhead' }, 'Tracks · NDF'),
          h('div', { className: 'lane', style: { width }, onClick: seek },
            ...ticks.map(t => h('span', { key: t.frame, className: 'timeline-tick mono muted', style: { left: t.frame * px } }, t.label)), playhead())),
        ...[...version.tracks].sort((a, b) => a.order - b.order).map(track)),
      !version.clips.length && h('div', { className: 'timeline-empty' },
        h('p', { title: 'The ruler shows editing space, not recorded media.' }, 'No clips yet. Open Assets to insert a source range.'),
        h(B, { title: 'No clips yet. Open Assets to insert a source range.', onClick: () => updateLocal({ tab: 'Assets' }) }, 'Open Assets'))));
}
function TrackDialog({ model }) {
  const [name, setName] = useState(''), [kind, setKind] = useState('video');
  return h(Modal, { title: 'Add track' }, h('label', {}, 'Name', h('input', { value: name, onChange: e => setName(e.target.value) })), h('label', {}, 'Kind', h('select', { value: kind, onChange: e => setKind(e.target.value) }, ...[['video', 'Picture'], ['audio', 'Audio'], ['overlay', 'Title'], ['caption', 'Caption']].map(([v, label]) => h('option', { key: v, value: v }, label)))), h(B, { primary: true, disabled: !name.trim(), onClick: () => { stage(model, [{ op: 'track.create', create_ref: uid(), kind, name, order: model.version.tracks.length, overlap_policy: kind === 'audio' || kind === 'video' ? 'exclusive' : 'composite' }], 'Create track'); change({ dialog: null }); } }, 'Create track'));
}
function useCollection(path, values, model, poll = false) {
  const [cursor, setCursor] = useState(null), [previous, setPrevious] = useState([]);
  useEffect(() => { setCursor(null); setPrevious([]); }, [path, canonical(values || {}), model.s.epoch]);
  const query = useRead(path, { ...values, ...(cursor ? { cursor } : {}), limit: 50 }, model.scope, Boolean(path && model.scope), poll && !cursor);
  const data = query.data?.data;
  const merged = [...previous, ...(data?.items || data?.entries || [])];
  const items = [...new Map(merged.map(x => [x.asset_id || x.job_id || x.node_id || x.entry_id || x.proposal_id || x.candidate_id || x.delivery_set_id || x.composition_id || x.id, x])).values()];
  return { query, data, items, more: data?.next_cursor ? () => { setPrevious(items); setCursor(data.next_cursor); } : null, reset: () => { setCursor(null); setPrevious([]); query.refetch(); } };
}
function Assets({ model }) {
  const [view, setView] = useState('catalog'), [search, setSearch] = useState(''), [root, setRoot] = useState(null), [parents, setParents] = useState([]), [nodes, setNodes] = useState([]), [scan, setScan] = useState(null);
  const roots = model.pcontext.data?.data?.roots || model.pcontext.data?.data?.project?.roots || [];
  const selectedRoot = roots.find(r => r.root_id === root);
  const files = useCollection(root ? `${model.ppath}/roots/${enc(root)}/entries` : null, { parent_node_id: parents.at(-1) || null, expected_root_revision: selectedRoot?.root_revision, kind_filter: 'all' }, model);
  const catalog = useCollection(model.ppath && model.ppath + '/assets', { search: search || undefined }, model);
  const manifestPages = useCollection(scan ? `${model.ppath}/import-scans/${enc(scan)}` : null, { status_filter: 'all' }, model, true);
  const manifest = manifestPages.query;
  return h('div', { className: 'body' }, h('div', { className: 'row' }, ...['catalog', 'files', 'outputs'].map(v => h(B, { key: v, onClick: () => setView(v), 'aria-pressed': view === v }, v === 'catalog' ? 'Composition catalog' : v === 'files' ? 'Project files' : 'Outputs')), h(B, { onClick: () => change({ dialog: 'add-assets' }) }, 'Add assets…')), view === 'files' ? h('section', { className: 'list' }, h('label', {}, 'Authorized Project root', h('select', { value: root || '', onChange: e => { setRoot(e.target.value); setParents([]); setNodes([]); } }, h('option', { value: '' }, 'Choose root'), ...roots.map(r => h('option', { key: r.root_id, value: r.root_id, disabled: !r.available }, `${r.label}${r.available ? '' : ' · ' + r.reason}`)))), parents.length > 0 && h(B, { onClick: () => setParents(parents.slice(0, -1)) }, 'Parent folder'), root && h(QueryState, { query: files.query, emptyText: 'This folder has no visible files' }, files.items.length > 0 && files.items.map(n => h('div', { className: 'item', key: n.node_id }, h('input', { type: 'checkbox', 'aria-label': `Select ${n.name}`, checked: nodes.includes(n.node_id), disabled: !n.importable && n.kind !== 'directory', onChange: e => setNodes(e.target.checked ? [...nodes, n.node_id] : nodes.filter(id => id !== n.node_id)) }), h(B, { onClick: () => n.kind === 'directory' ? setParents([...parents, n.node_id]) : change({ message: `${n.name} · ${n.byte_length ?? 'Unknown'} bytes · ${n.reason || 'Available for bounded scan'}` }) }, n.kind === 'directory' ? `▸ ${n.name}` : n.name), h('small', {}, n.reason)))), files.more && h(B, { onClick: files.more }, 'Load more files'), h(B, { disabled: !nodes.length, onClick: async () => { const r = await command(model.ppath + '/import-scans', 'OP-IMPORT-SCAN', model.scope, { root_revisions: [{ root_id: root, revision: selectedRoot.root_revision }] }, { selections: nodes.map(node_id => ({ root_id: root, node_id })), recursive: true, filters: { kinds: [], extensions: [], include_hidden: false }, max_files: model.boot.data.data.limits?.scan_files || 1000, max_bytes: model.boot.data.data.limits?.scan_bytes || 1073741824, symlink_policy: 'deny' }, `${scopeKey(model.scope)}:scan`); setScan(r.scan_id); } }, 'Scan selected folders recursively'), scan && h('div', { className: 'card' }, h('h3', {}, 'Frozen import manifest'), h('p', {}, manifest.data?.data?.complete ? 'Complete scan. Review entries before admitting immutable copies.' : 'Scan incomplete or still running. Nothing has been imported.'), ...manifestPages.items.map(e => h('div', { key: e.entry_id, className: 'row' }, e.name || e.relative_display_path, h(Badge, {}, e.status || e.reason))), manifestPages.more && h(B, { onClick: manifestPages.more }, 'Review next manifest page'), h(B, { disabled: !manifest.data?.data?.complete || Boolean(manifestPages.more), onClick: () => { const m = manifest.data.data; if (manifestPages.more) throw new Error('Load and review the complete manifest before importing.'); return command(model.ppath + '/imports', 'OP-IMPORT-COMMIT', model.scope, { manifest_sha256: m.manifest_sha256 }, { manifest_id: m.manifest_id, entry_ids: manifestPages.items.filter(e => e.eligible || e.status === 'eligible').map(e => e.entry_id), copy_policy: 'managed_immutable_copy', dedup_policy: 'reuse_authorized_hash', allow_partial_manifest: false, rights_assertions: [], target_composition_id: model.s.composition || null }, `${scopeKey(model.scope)}:import`); } }, 'Import reviewed immutable copies'))) : view === 'outputs' ? h(Candidates, { model }) : h('section', { className: 'list' }, h('label', {}, 'Search registered assets', h('input', { type: 'search', maxLength: 200, value: search, onChange: e => setSearch(e.target.value) })), h(QueryState, { query: catalog.query, emptyText: search ? `No matches for ${search}` : 'No registered assets yet' }, catalog.items.length > 0 && catalog.items.map(a => h('div', { key: a.asset_id, className: 'item' }, h('div', { className: 'grow' }, h('strong', {}, a.display_name), h('div', { className: 'muted' }, `${a.kind} · ${a.byte_length ?? 'Unknown'} bytes`), h(Badge, {}, typeof a.readiness === 'string' ? a.readiness : a.readiness?.state || 'Readiness unknown')), h(B, { onClick: async () => { const result = await read(`${model.ppath}/assets/${enc(a.asset_id)}`, {}, model.scope); updateLocal({ monitor: 'source', tab: 'Preview' }); change({ sourceAsset: result.data.asset || result.data }); } }, 'Source'), h(B, { onClick: () => change({ dialog: 'asset-details', asset: a }) }, 'Details'), h(B, { disabled: !model.version, onClick: () => change({ dialog: 'insert', asset: a }) }, 'Insert…')))), catalog.more && h(B, { onClick: catalog.more }, 'Load more assets')));
}
export function exactAssetPlacement(version, asset, track, input, output, start) {
  const i = safeInteger(input), o = safeInteger(output, i + 1);
  if (!asset?.rate || !Number.isSafeInteger(asset.duration_frames) || o > asset.duration_frames) throw new Error('Pinned source frame bounds/rate are unknown or exceeded. Exact conform is required.');
  const n = BigInt(o - i) * BigInt(asset.rate.den) * BigInt(version.format.fps.num);
  const d = BigInt(asset.rate.num) * BigInt(version.format.fps.den);
  if (n % d) throw new Error('Exact source/output duration needs a conform derivative; no frame/sample count was guessed.');
  return { op: 'clip.insert', create_ref: uid(), track_id: track, subject: { kind: 'asset', id: asset.asset_id, version_id: asset.asset_version_id }, start_frame: safeInteger(start), end_frame: safeInteger(Number(start) + Number(n / d)), source_mapping: { domain: 'frame', in_index: i, out_index: o, rate: asset.rate, speed: { num: 1, den: 1 } }, linked_group_id: null, enabled: true };
}
export function selectedRegisteredAsset(selected, observed) {
  return selected && observed && ['asset_id', 'asset_version_id', 'sha256'].every(k => typeof selected[k] === 'string' && selected[k] === observed[k]) ? observed : null;
}
export function exactSourcePin(version, asset) {
  if (!asset?.asset_id || !asset.asset_version_id || !/^[a-f0-9]{64}$/.test(asset.sha256)) return null;
  return version?.asset_refs?.find(r => r.asset_id === asset?.asset_id && r.asset_version_id === asset?.asset_version_id && r.sha256 === asset?.sha256) || null;
}
export function sourcePreparationIdentity(model, asset) {
  return canonical({ scope: model.scope, epoch: model.s.epoch, composition: model.s.composition, version_id: model.saved?.version_id, composition_revision: model.saved?.composition_revision, asset_id: asset?.asset_id, asset_version_id: asset?.asset_version_id, sha256: asset?.sha256 });
}
export function committedSourceReceipt(job, jobId, asset) {
  const r = job?.source_probe;
  return jobId && job?.job_id === jobId && job.state === 'succeeded' && r?.receipt_id && r.asset_id === asset?.asset_id && r.asset_version_id === asset?.asset_version_id ? r : null;
}
export function sourcePreparationRequest(model, asset, receipt = null, fullDecode = false) {
  if (model.readOnly || !model.saved || !model.scope || !model.cpath || !asset?.asset_id || !asset.asset_version_id || !/^[a-f0-9]{64}$/.test(asset.sha256) || !Number.isSafeInteger(asset.entity_revision) || asset.entity_revision < 1 || !model.saved.version_id || !Number.isSafeInteger(model.saved.composition_revision)) throw new Error('Exact saved Composition and admitted asset identity/revision are required.');
  const operation = receipt ? 'OP-ASSET-BIND' : 'OP-ASSET-PROBE';
  if (!model.can(operation) || (!receipt && !model.can('OP-JOB-GET'))) throw new Error('This backend does not advertise the required source preparation operations.');
  if (typeof fullDecode !== 'boolean') throw new Error('Choose an explicit full-decode policy.');
  if (receipt && (!receipt.receipt_id || receipt.asset_id !== asset.asset_id || receipt.asset_version_id !== asset.asset_version_id || receipt.full_decode === 'fail' || !receipt.streams?.some(s => s.index === 0 && ['video', 'audio'].includes(s.type)))) throw new Error('A committed matching probe receipt with supported stream zero is required.');
  if (receipt) {
    const stream = receipt.streams.find(s => s.index === 0);
    const rational = r => Number.isSafeInteger(r?.num) && r.num > 0 && Number.isSafeInteger(r?.den) && r.den > 0;
    const frames = receipt.vfr === 'no' && rational(stream.rate) && Number.isSafeInteger(stream.frame_count) && stream.frame_count > 0;
    const ticks = rational(stream.time_base) && Number.isSafeInteger(stream.start_pts) && Number.isSafeInteger(stream.duration_ticks) && stream.duration_ticks > 0;
    if ((!frames && !ticks) || (stream.type === 'audio' && (!Number.isSafeInteger(stream.sample_rate) || stream.sample_rate <= 0))) throw new Error('Source timing/sample facts are unknown. Binding for insertion stays blocked; no conform or facts were inferred.');
  }
  return { operation, route: `${model.cpath}/assets/${enc(asset.asset_id)}/${receipt ? 'bind' : 'probe'}`, preconditions: { entity_revision: asset.entity_revision, composition_revision: model.saved.composition_revision, version_id: model.saved.version_id }, input: { asset_version_id: asset.asset_version_id, sha256: asset.sha256, ...(receipt ? { receipt_id: receipt.receipt_id, stream_index: 0 } : { full_decode: fullDecode }) } };
}
// The public bind service publishes the hydrated saved pin around its adapter.
// The client confirms that version; it never invents a private ArtifactRef.
export function preparedSourceProbeText(model, asset, fullDecode) {
  const request = sourcePreparationRequest(model, asset, null, fullDecode);
  return 'Motion Studio exact source probe request — PREPARED ONLY. Review and submit this conversation yourself. This text is not approval, execution, a session identity, or a permission grant.\n' + canonical({ scope: model.scope, composition_id: model.s.composition, saved_version_id: model.saved.version_id, request }) + '\nUse only the installed supported native execution tools in this admitted conversation turn. Resolve these exact public pins through the authorized service; request normal exact-plan approval before decoder work. Do not inject host session IDs, bypass policy, mutate Hermes core, or treat REST preparation as an admitted turn. Return the real committed owned job identity and source receipt through the supported service correlation, if available. If no such supported bridge exists, report blocked; do not invent a job or pin. Preserve all local unsaved Composition edits.';
}
function SourcePreparation({ model, asset }) {
  const identity = sourcePreparationIdentity(model, asset);
  const [fullDecode, setFullDecode] = useState(false), [active, setActive] = useState(null), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [verification, setVerification] = useState(null), [prepared, setPrepared] = useState(null), [insertion, setInsertion] = useState('');
  const jobs = useCollection(model.ppath && model.can('OP-JOBS') ? model.ppath + '/jobs' : null, {}, model, true);
  const mountedIdentity = useRef(identity); mountedIdentity.current = identity;
  useEffect(() => () => { mountedIdentity.current = null; }, [identity]);
  const journal = model.s.journals?.[model.key];
  const journalMatches = journal && ['OP-ASSET-PROBE', 'OP-ASSET-BIND'].includes(journal.operation) && journal.route === `${model.cpath}/assets/${enc(asset?.asset_id)}/${journal.operation === 'OP-ASSET-PROBE' ? 'probe' : 'bind'}` && same(journal.body.scope, model.scope) && journal.body.input.asset_version_id === asset?.asset_version_id && journal.body.input.sha256 === asset?.sha256;
  const result = journalMatches && journal.state === 'committed' ? journal.status?.result || journal.result : null;
  const tracked = active?.identity === identity ? active : null;
  const jobId = tracked?.job_id || (journalMatches && journal.operation === 'OP-ASSET-PROBE' && result?.asset_id === asset?.asset_id && result.asset_version_id === asset?.asset_version_id ? result?.job?.job_id : null);
  const q = useRead(jobId ? `${model.ppath}/jobs/${enc(jobId)}` : null, {}, model.scope, Boolean(jobId && model.can('OP-JOB-GET')), true);
  const job = q.data?.data?.job || q.data?.data;
  const receipt = committedSourceReceipt(job, jobId, asset);
  const accepted = journalMatches && journal.operation === 'OP-ASSET-BIND' && journal.state === 'committed' && result?.readiness === 'bound' && result.asset_id === asset?.asset_id && result.asset_version_id === asset?.asset_version_id && result.source_facts?.sha256 === asset?.sha256;
  const refresh = async () => {
    const cap = capture(), selected = identity;
    setVerification(null);
    // Read the exact targets after acceptance. Invalidation alone is not proof.
    const [head, currentAsset] = await Promise.all([read(model.cpath, {}, model.scope, cap), read(`${model.ppath}/assets/${enc(asset.asset_id)}`, {}, model.scope, cap), read(model.ppath + '/context', {}, model.scope, cap), read(model.ppath + '/assets', { limit: 50 }, model.scope, cap)]);
    if (mountedIdentity.current !== selected || !isCurrent(cap)) return;
    const observedAsset = currentAsset.data?.asset || currentAsset.data;
    const saved = head.data?.version;
    const exact = observedAsset?.asset_id === asset.asset_id && observedAsset.asset_version_id === asset.asset_version_id && observedAsset.sha256 === asset.sha256 && exactSourcePin(saved, asset);
    setVerification({ identity: selected, pinned: Boolean(exact) });
    await invalidate();
  };
  useEffect(() => { if (accepted) guard(refresh)(); }, [identity, accepted, journal?.body?.command_id]);
  const prepareProbe = () => {
    cancelAutosave?.(); cancelAutosave = null;
    const target = { owner_key: ownerKey(ownerNow()), session_id: host.state.focusedStoredSessionId.get() };
    if (!target.session_id || !host.composer?.getDraft || !host.composer?.insertText) throw new Error('Open the intended saved conversation on a supported host with acknowledged composer insertion.');
    setPrepared({ identity, target, text: preparedSourceProbeText(model, asset, fullDecode) }); setInsertion('');
  };
  const submitBind = async () => {
    const selected = identity, cap = capture();
    setBusy(true); setNotice('');
    // Freeze any original local draft; preparation must not autosave or replace it.
    cancelAutosave?.(); cancelAutosave = null;
    try {
      if (!receipt) throw new Error('No committed matching receipt is available for binding.');
      const request = sourcePreparationRequest(model, asset, receipt, fullDecode);
      const r = await command(request.route, request.operation, model.scope, request.preconditions, request.input, model.key);
      if (!isCurrent(cap) || mountedIdentity.current !== selected) return;
      const committed = storage.journals[model.key]?.state === 'committed';
      setNotice(committed && r?.readiness === 'bound' ? 'Binding committed; checking the service-published saved graph pin.' : 'Binding outcome is pending or unsupported. Reconcile the original command before continuing; no binding was assumed.');
    } finally { if (mountedIdentity.current === selected) setBusy(false); }
  };
  let probeBlocked = '', bindBlocked = '';
  try { sourcePreparationRequest(model, asset, null, fullDecode); } catch (e) { probeBlocked = errorText(e); }
  try { if (!receipt) throw new Error('Wait for a succeeded owned job and committed matching source_probe receipt.'); sourcePreparationRequest(model, asset, receipt, fullDecode); } catch (e) { bindBlocked = errorText(e); }
  const unresolved = journal && !['committed', 'failed'].includes(journal.state);
  const verified = verification?.identity === identity ? verification : null;
  return h('section', { className: 'card' }, h('h3', {}, 'Prepare exact source for saved Composition'), h('p', { className: 'mono' }, `${model.s.composition || 'No Composition'} · ${model.saved?.version_id || 'No saved version'}`), h('p', {}, 'Probe copies this exact registered source into the selected saved Composition and may launch decoder work. A trusted host session and normal exact-plan approval are required; Studio does not create session authority or approval grants. Local unsaved edits and source selection are retained.'), h('label', {}, h('input', { type: 'checkbox', checked: fullDecode, disabled: busy, onChange: e => setFullDecode(e.target.checked) }), 'Request full decode explicitly'), probeBlocked && h(Notice, {}, probeBlocked), h(Notice, {}, 'Direct REST probing is blocked: this host does not admit REST into its conversation approval turn. No Hermes core changes are allowed. Prepare the exact request below, insert it into the visible conversation, then review and submit it yourself.'), h(B, { disabled: true, title: 'No admitted-turn / policy-notifier authority exists on this REST route' }, 'Direct probe unavailable'), h(B, { disabled: busy || unresolved || Boolean(probeBlocked) || !host.composer?.getDraft || !host.composer?.insertText || !host.state.focusedStoredSessionId.get(), onClick: prepareProbe }, 'Prepare exact source probe request'), prepared?.identity === identity && h('div', {}, h('pre', {}, prepared.text), h(B, { disabled: Boolean(insertion), onClick: async () => { setInsertion('Insertion pending — inspect conversation before any retry'); try { await insertPreparedRequest(prepared.target, prepared.text); setInsertion('Acknowledged insertion only — not submitted, approved or executed. Submit it yourself in the conversation.'); } catch (e) { setInsertion(errorText(e)); } } }, 'Insert prepared request in conversation'), insertion && h(Notice, {}, insertion)), h('p', {}, 'Prepared text is not a tracked probe. Only real jobs returned by this service can be selected below; native conversation execution without supported job/result correlation remains blocked.'), h('label', {}, 'Observed owned job', h('select', { value: jobId || '', disabled: !model.can('OP-JOBS') || !model.can('OP-JOB-GET'), onChange: e => setActive(e.target.value ? { identity, job_id: e.target.value } : null) }, h('option', { value: '' }, 'Choose an actual observed job'), ...jobs.items.filter(j => j.version_id === model.saved?.version_id).map(j => h('option', { key: j.job_id, value: j.job_id }, `${j.kind} · ${j.job_id} · ${j.state}`)))), jobs.more && h(B, { onClick: jobs.more }, 'Load more owned jobs'), !model.can('OP-JOBS') && h(Notice, {}, 'No owned-job discovery operation is advertised; prepared request/result correlation is unavailable.'), jobId && h('div', {}, h(Facts, { value: job || { job_id: jobId }, fields: ['job_id', 'state', 'effect_state'] }), h(QueryState, { query: q }, receipt ? h(SchemaRead, { value: receipt }) : h('p', {}, 'No committed source receipt observed. Failed, interrupted, approval-waiting and unknown-effect jobs do not authorize binding.')), h(B, { onClick: () => change({ dialog: 'job', job: jobId }) }, 'Open owned job / recovery…')), h('p', {}, 'Binding selects observed stream index 0 only. Other streams, unknown timing and source conform remain unsupported; receipt metadata is not fabricated.'), bindBlocked && h(Notice, {}, bindBlocked), h(B, { disabled: busy || unresolved || Boolean(bindBlocked), onClick: submitBind }, 'Bind committed receipt · stream 0'), notice && h(Notice, {}, notice), accepted && h('div', {}, h(B, { disabled: busy, onClick: refresh }, 'Refresh saved pin / catalog / context'), h(Notice, {}, verified?.pinned ? 'Readback confirms this exact asset/version/hash is pinned in the saved graph. Insertion still requires observed bounds and compatible tracks.' : 'No exact saved graph pin confirmed yet. The binding service publishes a version; refresh or reconcile the original command before insertion.')));
}
function InsertDialog({ model }) {
  const assetQuery = useRead(model.s.asset ? `${model.ppath}/assets/${enc(model.s.asset.asset_id)}` : null, {}, model.scope, Boolean(model.s.asset));
  const a = assetQuery.data?.data?.asset || assetQuery.data?.data || model.s.asset;
  const admitted = selectedRegisteredAsset(model.s.asset, assetQuery.data?.data?.asset || assetQuery.data?.data);
  const primary = exactSourcePin(model.saved, admitted) && exactSourcePin(model.version, admitted);
  const kind = primary?.kind === 'audio' ? 'audio' : 'video';
  const hasAudio = kind === 'video' && a?.streams?.some(s => s.type === 'audio');
  const [target, setTarget] = useState(''), [sourceIn, setSourceIn] = useState('0'), [sourceOut, setSourceOut] = useState(''), [at, setAt] = useState(String(model.s.frame)), [mode, setMode] = useState('place');
  const [streamChoice, setStreamChoice] = useState('linked'), [audioId, setAudioId] = useState(''), [audioTrack, setAudioTrack] = useState(''), [audioIn, setAudioIn] = useState('0'), [audioOut, setAudioOut] = useState(''), [acknowledged, setAcknowledged] = useState(false);
  useEffect(() => setAcknowledged(false), [target, sourceIn, sourceOut, at, mode, streamChoice, audioId, audioTrack, audioIn, audioOut, model.version]);
  let plan = [], failure = '', review = null;
  try {
    if (!primary) throw new Error('This exact source asset/version/hash is not confirmed in the saved graph. Prepare and bind below, then confirm the service-published saved pin.');
    const newTracks = [];
    const choose = (value, type) => {
      if (value !== 'new') { if (!value) throw new Error('Choose explicit compatible tracks.'); return value; }
      const id = uid(); newTracks.push({ op: 'track.create', create_ref: id, kind: type, name: type === 'audio' ? 'Audio' : 'Picture', order: model.version.tracks.length + newTracks.length, overlap_policy: type === 'audio' ? 'mix' : 'exclusive' }); return id;
    };
    const placements = [exactAssetPlacement(model.version, primary, choose(target, kind), sourceIn, sourceOut, at)];
    if (hasAudio && streamChoice === 'linked') {
      const audio = model.version.asset_refs?.find(r => r.asset_version_id === audioId && r.kind === 'audio');
      if (!audio) throw new Error('Same-source audio stream placement is not supported by this backend: clip.insert has no stream selector and audio tracks require a separately pinned audio asset. Choose a known registered audio companion with explicit bounds, or explicitly choose Video only.');
      placements.push(exactAssetPlacement(model.version, audio, choose(audioTrack, 'audio'), audioIn, audioOut, at));
    }
    const graph = projectDraft(model.version, newTracks);
    review = insertionAffected(graph, placements, mode);
    plan = buildInsertion(model.version, placements, mode, newTracks);
  } catch (e) { failure = errorText(e); }
  const trackSelect = (value, set, type, label) => h('label', {}, label, h('select', { value, onChange: e => set(e.target.value) }, h('option', { value: '' }, 'Choose compatible unlocked track'), ...model.version.tracks.filter(t => t.kind === type || (type === 'video' && t.kind === 'overlay')).map(t => h('option', { key: t.track_id, value: t.track_id, disabled: t.locked }, t.name)), h('option', { value: 'new' }, `Create ${type} track atomically`)));
  return h(Modal, { title: `Insert ${a?.display_name || 'asset'}` }, h(SourcePreparation, { key: sourcePreparationIdentity(model, admitted), model, asset: admitted }), h('p', {}, 'Exact pinned source bounds and explicit compatible tracks. No samples, source rates or stream offsets are inferred.'), trackSelect(target, setTarget, kind, 'Target track'), h('div', { className: 'grid' }, h(NumberField, { label: 'Source in · frame index', value: sourceIn, onChange: setSourceIn }), h(NumberField, { label: 'Source out · exclusive frame index', value: sourceOut, onChange: setSourceOut, min: 1 }), h(NumberField, { label: 'Timeline start', value: at, onChange: setAt })), hasAudio && h('div', { className: 'card' }, h('label', {}, 'Source streams', h('select', { value: streamChoice, onChange: e => setStreamChoice(e.target.value) }, h('option', { value: 'linked' }, 'Linked video + registered audio companion'), h('option', { value: 'video' }, 'Video only · explicitly omit source audio'))), streamChoice === 'linked' && h('div', {}, h('label', {}, 'Explicit registered audio companion · no inferred association', h('select', { value: audioId, onChange: e => setAudioId(e.target.value) }, h('option', { value: '' }, 'Choose exact pinned audio version'), ...(model.version.asset_refs || []).filter(r => r.kind === 'audio').map(r => h('option', { key: r.asset_version_id, value: r.asset_version_id }, r.asset_version_id)))), trackSelect(audioTrack, setAudioTrack, 'audio', 'Audio track'), h(NumberField, { label: 'Audio source in · observed frame/sample index', value: audioIn, onChange: setAudioIn }), h(NumberField, { label: 'Audio source out · exclusive observed index', value: audioOut, onChange: setAudioOut }))), h('label', {}, 'Insertion behavior', h('select', { value: mode, onChange: e => setMode(e.target.value) }, h('option', { value: 'place' }, 'Place in empty range'), h('option', { value: 'insert' }, 'Ripple insert · preserve linked closure'), h('option', { value: 'overwrite' }, 'Overwrite · preserve linked residuals'))), failure && h(Notice, { error: true }, failure), review && h('div', { className: 'card' }, h('h3', {}, 'Affected tracks and placements'), h('p', { className: 'mono' }, review.track_ids.join(' · ')), ...review.clips.map(c => h('p', { key: c.clip_id, className: 'mono' }, `${c.clip_id} · ${c.track_id} · [${c.start_frame}, ${c.end_frame})${c.linked_group_id ? ' · linked companion included' : ''}`))), h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: acknowledged, onChange: e => setAcknowledged(e.target.checked) }), 'I reviewed exact source ranges, stream choice, new tracks and the entire affected linked set.'), h(B, { disabled: Boolean(failure) || !plan.length || !acknowledged, primary: true, onClick: () => { stage(model, plan, 'Insert reviewed exact source placements and linked closure'); change({ dialog: null }); } }, 'Apply reviewed source insertion'));
}
function AssetDetails({ model }) {
  const assetQuery = useRead(model.s.asset ? `${model.ppath}/assets/${enc(model.s.asset.asset_id)}` : null, {}, model.scope, Boolean(model.s.asset));
  const a = assetQuery.data?.data?.asset || assetQuery.data?.data || model.s.asset;
  return h(Modal, { title: a?.display_name || 'Asset details' }, h(Facts, { value: a, fields: ['asset_id', 'asset_version_id', 'sha256', 'byte_length', 'mime', 'kind', 'entity_revision'] }), h(SourcePreparation, { key: sourcePreparationIdentity(model, selectedRegisteredAsset(model.s.asset, assetQuery.data?.data?.asset || assetQuery.data?.data)), model, asset: selectedRegisteredAsset(model.s.asset, assetQuery.data?.data?.asset || assetQuery.data?.data) }), h('h3', {}, 'Provenance and rights'), h('p', {}, `Rights: ${a.rights?.status || 'Unknown'}. A registered file is not a license.`), h('p', {}, a.provenance?.source_display || 'Source provenance not recorded'), h('h3', {}, 'Streams'), ...(a.streams || []).map((stream, i) => h(Facts, { key: i, value: stream, fields: ['index', 'type', 'sample_rate', 'channels', 'duration_frames'] })), h('h3', {}, 'Derivatives'), ...(a.derivatives || []).map((d, i) => h('div', { className: 'row', key: i }, d.kind, h(Badge, {}, d.state || 'Unknown'))), h(B, { disabled: !model.can('OP-HANDOFF-PREPARE'), onClick: () => change({ dialog: 'production-action', productionIntent: 'diagnose' }) }, 'Prepare separate diagnostic handoff…'));
}
function Facts({ value, fields }) { return h('dl', { className: 'grid' }, ...fields.flatMap(k => [h('dt', { key: k + 'k', className: 'muted' }, k.replaceAll('_', ' ')), h('dd', { key: k, className: 'mono', style: { margin: 0, overflowWrap: 'anywhere' } }, value?.[k] == null ? 'Not recorded' : typeof value[k] === 'object' ? canonical(value[k]) : String(value[k]))])); }
function Layers({ model }) {
  if (!model.version) return h(CompositionEmpty, { model });
  return h('div', { className: 'body' }, h('h3', {}, 'Scene hierarchy'), h('p', { className: 'muted' }, 'List selection is exact. Direct canvas manipulation is unavailable without engine hit geometry.'), ...model.version.scenes.map(scene => h('section', { key: scene.scene_id, className: 'card' }, h('h3', {}, scene.name), ...model.version.layers.filter(l => l.scene_id === scene.scene_id).sort((a, b) => a.order - b.order).map(layer => h('div', { className: 'item', key: layer.layer_id }, h(B, { onClick: () => change({ layer: layer.layer_id, tab: 'Inspector' }) }, `${layer.type} · ${layer.layer_id}`), h(B, { onClick: () => change({ dialog: 'layer', layer: layer.layer_id }) }, 'Edit…'), h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'scene_generate' }) }, 'Render prepared scene…'))))), !model.version.scenes.length && h(Unavailable, { title: 'No scenes yet', reason: 'Ask Hermes to author a scene first. This panel can render an existing prepared scene; it does not create or open source code.', action: h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'scene_generate' }) }, 'Render prepared scene…') }));
}
function Inspector({ model }) {
  const [panel, setPanel] = useState('Timing');
  const selected = model.version?.clips.filter(c => model.s.selected.includes(c.clip_id)) || [];
  const c = selected[0];
  if (!model.version) return h(CompositionEmpty, { model });
  return h('div', { className: 'body' }, h('h3', {}, selected.length ? `${selected.length} selected · ${c.subject.kind}` : 'Composition inspector'), h('div', { className: 'row' }, ...['Picture', 'Audio', 'Timing', 'Effects', 'Captions', 'Details'].map(p => h(B, { key: p, onClick: () => setPanel(p), 'aria-pressed': panel === p }, p))), panel === 'Timing' ? c ? h('div', { className: 'card' }, h(Facts, { value: c, fields: ['clip_id', 'track_id', 'start_frame', 'end_frame', 'linked_group_id', 'enabled'] }), h(B, { onClick: () => change({ dialog: 'placement' }) }, 'Edit placement…'), h(B, { onClick: () => stage(model, [{ op: 'link.set', clip_ids: model.s.selected, group_id: c.linked_group_id ? null : uid() }], c.linked_group_id ? 'Unlink placements' : 'Link placements') }, c.linked_group_id ? 'Unlink explicitly' : 'Link selection')) : h('p', {}, 'Select a placement in the timeline.') : panel === 'Captions' ? h(Captions, { model }) : panel === 'Details' ? h(Facts, { value: c || model.summary, fields: c ? ['clip_id', 'track_id', 'subject', 'source_mapping'] : ['composition_id', 'native_project_id', 'head_version_id', 'head_sha256', 'metadata_revision'] }) : panel === 'Audio' ? h(AudioInspector, { model, clip: c }) : panel === 'Effects' ? h(Effects, { model, clip: c }) : h('div', { className: 'card' }, h('p', {}, 'Position is output pixels from top-left; scale is percent; rotation is clockwise. Properties must map to the saved renderer schema, not browser-only CSS.'), model.s.layer ? h(B, { onClick: () => change({ dialog: 'layer' }) }, 'Edit selected layer properties…') : h(Unavailable, { title: 'Select a scene layer', reason: 'No supported transform binding is asserted for this placement. Use Layers to select an editable source.' })), h(B, { onClick: () => change({ dialog: 'composition-settings' }) }, 'Composition settings…'));
}
function AudioInspector({ model, clip }) {
  const [gain, setGain] = useState(String(clip?.audio?.gain_db_milli || 0)), [pan, setPan] = useState(String(clip?.audio?.pan_milli || 0));
  const binding = model.capabilities.data?.data?.audio_mix_schema || { gain_min: -60000, gain_max: 12000, pan: false };
  if (!clip) return h('p', {}, 'Select an audio placement.');
  return h('div', { className: 'card' }, h('p', {}, 'Saved clip gain is separate from monitor playback volume. Waveforms do not establish measured loudness.'), h('div', { className: 'grid' }, h(NumberField, { label: 'Clip gain', unit: 'millidecibels', value: gain, onChange: setGain, min: binding?.gain_min ?? 0, max: binding?.gain_max ?? 0, disabled: !binding }), h(NumberField, { label: 'Stereo pan', unit: 'milli · −1000 left / +1000 right', value: pan, onChange: setPan, min: -1000, max: 1000, disabled: !binding?.pan })), h(B, { disabled: !binding, onClick: () => stage(model, [{ op: 'audio.set', target: { kind: 'clip', id: clip.clip_id }, gain_db_milli: safeInteger(gain, binding.gain_min, binding.gain_max), pan_milli: safeInteger(pan, -1000, 1000), muted: clip.audio?.muted || false, fades: clip.audio?.fades || [], envelope: clip.audio?.envelope || [] }], 'Apply audio properties') }, 'Apply saved audio properties'), !binding && h('p', { className: 'muted' }, 'Audio mixing ranges and renderer support are not advertised by this route.'), h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'audio_process' }) }, 'Cleanup / voice / ducking…'));
}
function Effects({ model, clip }) {
  const effects = model.version.effects.filter(e => !clip || e.target.id === clip.clip_id);
  return h('div', { className: 'list' }, ...effects.map(e => h('div', { key: e.effect_id, className: 'card' }, h('h3', {}, e.schema_ref.id), h(Badge, {}, e.enabled ? 'Enabled' : 'Bypassed'), h(B, { onClick: () => stage(model, [{ op: 'effect.update', effect_id: e.effect_id, schema_ref: e.schema_ref, enabled: !e.enabled, parameters: e.parameters, keyframes: e.keyframes }], 'Toggle effect') }, e.enabled ? 'Bypass' : 'Enable'), h(B, { onClick: () => change({ dialog: 'effect', effect: e.effect_id }) }, 'Edit schema parameters…'))), h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'scene_generate', selectedOperation: null }) }, 'Render prepared scene…'), !effects.length && h('p', { className: 'muted' }, 'No effect is applied. Supported operations are supplied by the connected renderer.'));
}
function Captions({ model }) {
  const [language, setLanguage] = useState('all'), [search, setSearch] = useState('');
  const cues = model.version.captions || [];
  return h('div', { className: 'list' }, h('div', { className: 'row' }, h(B, { onClick: () => change({ dialog: 'caption', cue: null }) }, 'Add cue…'), h(B, { onClick: () => change({ dialog: 'caption-import' }) }, 'Import SRT / VTT…'), h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'caption_generate' }) }, 'Transcribe / translate…')), h('label', {}, 'Language', h('select', { value: language, onChange: e => setLanguage(e.target.value) }, h('option', { value: 'all' }, 'All languages'), ...[...new Set(cues.map(c => c.language))].map(l => h('option', { key: l, value: l }, l)))), h('label', {}, 'Search cue text', h('input', { value: search, onChange: e => setSearch(e.target.value) })), h('p', { className: 'muted' }, `${cues.length} authored cues. Dialogue coverage is not established by cue count; untranscribed gaps remain Needs listening.`), ...cues.filter(c => (language === 'all' || c.language === language) && c.text.includes(search)).map(c => h('div', { className: 'item', key: c.cue_id }, h(B, { onClick: () => { updateLocal({ frame: c.start_frame, selectedTrack: c.track_id }); change({ cue: c.cue_id, dialog: 'caption' }); } }, `${c.start_frame}–${c.end_frame}`), h('span', { className: 'grow', dir: 'auto' }, c.text), h(Badge, {}, c.review_state || 'Needs review'))));
}
function CaptionDialog({ model }) {
  const cue = model.version.captions.find(c => c.cue_id === model.s.cue);
  const [text, setText] = useState(cue?.text || ''), [start, setStart] = useState(String(cue?.start_frame ?? model.s.frame)), [end, setEnd] = useState(String(cue?.end_frame ?? model.s.frame + 1)), [language, setLanguage] = useState(cue?.language || ''), [track, setTrack] = useState(cue?.track_id || '');
  const styles = model.capabilities.data?.data?.caption_styles || [];
  const [style, setStyle] = useState(cue?.style_ref?.id || styles[0]?.id || '');
  return h(Modal, { title: cue ? 'Edit caption cue' : 'Add caption cue' }, h('label', {}, 'Text · literal Unicode', h('textarea', { value: text, dir: 'auto', onChange: e => setText(e.target.value) })), h('div', { className: 'grid' }, h(NumberField, { label: 'Start', value: start, onChange: setStart }), h(NumberField, { label: 'End · exclusive', value: end, onChange: setEnd, min: 1 }), h('label', {}, 'Language tag', h('input', { value: language, onChange: e => setLanguage(e.target.value) })), h('label', {}, 'Caption track', h('select', { value: track, onChange: e => setTrack(e.target.value) }, h('option', { value: '' }, 'Choose track'), ...model.version.tracks.filter(t => t.kind === 'caption').map(t => h('option', { key: t.track_id, value: t.track_id, disabled: t.locked }, t.name)))), h('label', {}, 'Supported style', h('select', { value: style, onChange: e => setStyle(e.target.value) }, h('option', { value: '' }, 'Choose advertised style'), ...styles.map(s => h('option', { key: s.id, value: s.id }, s.name || s.id))))), !styles.length && h('p', {}, 'No custom caption rendering style is advertised. Save as plain captions; export still requires a qualified caption route.'), h(B, { primary: true, disabled: !text || !language || !track, onClick: () => { const a = safeInteger(start), b = safeInteger(end, a + 1); stage(model, [{ op: 'caption.upsert', cue_id: cue?.cue_id || null, create_ref: cue ? null : uid(), track_id: track, start_frame: a, end_frame: b, text, language, style_ref: cue?.style_ref || styles.find(s => s.id === style)?.schema_ref || styles.find(s => s.id === style) || null }], 'Edit caption cue'); change({ dialog: null }); } }, 'Apply cue'));
}
export function parseTimedCaptions(text, fps, exactTimes = false) {
  if (text.includes('\u0000')) throw new Error('Caption file contains invalid text.');
  const blocks = text.replace(/^\uFEFF/, '').replace(/^WEBVTT[^\n]*\n/, '').trim().split(/\r?\n\s*\r?\n/);
  const stamp = s => { const m = /^(?:(\d{2,}):)?(\d{2}):(\d{2})[.,](\d{3})$/.exec(s); if (!m || Number(m[2]) > 59 || Number(m[3]) > 59) throw new Error(`Invalid caption timestamp: ${s}`); return BigInt(m[1] || 0) * 3600000n + BigInt(m[2]) * 60000n + BigInt(m[3]) * 1000n + BigInt(m[4]); };
  const result = [];
  for (const [index, block] of blocks.entries()) {
    const lines = block.split(/\r?\n/); if (!lines[0]) continue;
    if (/^\d+$/.test(lines[0]) || !lines[0].includes('-->')) lines.shift();
    const match = /^(\S+)\s+-->\s+(\S+)\s*$/.exec(lines.shift() || '');
    if (!match || !lines.length) throw new Error(`Cue ${index + 1}: malformed timing or missing text.`);
    const a = stamp(match[1]), b = stamp(match[2]);
    const body = lines.join('\n');
    if (b <= a || /<[^>]*>/.test(body)) throw new Error(`Cue ${index + 1}: nonpositive duration or unsupported markup.`);
    const den = 1000n * BigInt(fps.den), rate = BigInt(fps.num);
    result.push({ start_frame: Number(a * rate / den), end_frame: Number((b * rate + den - 1n) / den), text: body, ...(exactTimes ? { source_start_ms: String(a), source_end_ms: String(b) } : {}) });
  }
  return result;
}
export function mapCaptionImport(version, cues, placementIds = [], clipBounds = false) {
  const placements = placementIds.map(id => version.clips.find(c => c.clip_id === id));
  if (placements.some(p => !p)) throw new Error('Selected source placement changed.');
  const floor = (n, d) => n >= 0n ? n / d : -((-n + d - 1n) / d);
  const ceil = (n, d) => -floor(-n, d);
  const rows = [], output = [];
  for (const [index, cue] of cues.entries()) {
    let occurrences = 0;
    const mapped = [];
    for (const p of placements.length ? placements : [null]) {
      const m = p?.source_mapping;
      if (p && (!['frame', 'source_tick'].includes(m?.domain) || m.conform_ref)) throw new Error('Unknown source conform: caption mapping cannot be represented by typed cue operations.');
      if (p && (cue.source_start_ms == null || cue.source_end_ms == null)) throw new Error('Original exact timestamp data is required; re-open the caption file.');
      const map = (ms, end) => {
        const fps = version.format.fps;
        let n, d;
        if (m.domain === 'frame') {
          n = (BigInt(ms) * BigInt(m.rate.num) - BigInt(m.in_index) * BigInt(m.rate.den) * 1000n) * BigInt(m.speed.den) * BigInt(fps.num);
          d = 1000n * BigInt(m.rate.num) * BigInt(m.speed.num) * BigInt(fps.den);
        } else {
          n = (BigInt(ms) * BigInt(m.time_base.den) - (BigInt(m.in_pts) - BigInt(m.start_pts)) * BigInt(m.time_base.num) * 1000n) * BigInt(fps.num);
          d = 1000n * BigInt(m.time_base.den) * BigInt(fps.den);
        }
        if (d <= 0n) throw new Error('Unknown source rate/conform.');
        return Number((end ? ceil : floor)(n, d)) + p.start_frame;
      };
      const rawStart = p ? map(cue.source_start_ms, false) : cue.start_frame;
      const rawEnd = p ? map(cue.source_end_ms, true) : cue.end_frame;
      const start = Math.max(p?.start_frame || 0, rawStart, 0), end = Math.min(p?.end_frame ?? version.format.duration_frames, rawEnd, version.format.duration_frames);
      const excluded = end <= start, clipped = !excluded && (start !== rawStart || end !== rawEnd);
      const row = { cue: index + 1, placement_id: p?.clip_id || null, original: [cue.source_start_ms, cue.source_end_ms], raw_start_frame: rawStart, raw_end_frame: rawEnd, start_frame: start, end_frame: end, text: cue.text, status: excluded ? 'excluded' : clipped ? 'clipped' : 'included' };
      mapped.push(row);
      if (!excluded) { occurrences++; output.push({ start_frame: start, end_frame: end, text: cue.text }); }
    }
    for (const row of mapped) rows.push({ ...row, repeated: occurrences > 1 });
  }
  if (!clipBounds && rows.some(r => r.status !== 'included')) return { rows, cues: output, blocked: 'Review excluded/clipped cues and explicitly choose Clip to placement/Composition, or cancel.' };
  return { rows, cues: output, blocked: null };
}
function CaptionImport({ model }) {
  const [cues, setCues] = useState([]), [language, setLanguage] = useState(''), [track, setTrack] = useState(''), [failure, setFailure] = useState(''), [basis, setBasis] = useState('composition'), [placementId, setPlacementId] = useState(''), [repeats, setRepeats] = useState(false), [clipBounds, setClipBounds] = useState(false), [reviewed, setReviewed] = useState(false);
  const style = model.capabilities.data?.data?.caption_styles?.[0];
  useEffect(() => setReviewed(false), [cues, language, track, basis, placementId, repeats, clipBounds, model.version]);
  const placement = model.version.clips.find(c => c.clip_id === placementId);
  const sameSource = c => c.subject.kind === placement?.subject.kind && c.subject.id === placement?.subject.id && c.subject.version_id === placement?.subject.version_id && model.version.tracks.find(t => t.track_id === c.track_id)?.kind !== 'audio';
  let preview = { rows: [], cues: [] }, blocked = '';
  try {
    if (basis === 'source' && !placement) throw new Error('Choose the exact source placement.');
    preview = mapCaptionImport(model.version, cues, basis === 'source' ? repeats ? model.version.clips.filter(sameSource).map(c => c.clip_id) : [placementId] : [], clipBounds);
    blocked = preview.blocked;
    const sorted = [...preview.cues].sort((a, b) => a.start_frame - b.start_frame);
    const existing = track === 'new' ? [] : model.version.captions.filter(c => c.track_id === track);
    if (sorted.some((c, i) => (i && c.start_frame < sorted[i - 1].end_frame) || existing.some(e => e.start_frame < c.end_frame && e.end_frame > c.start_frame))) blocked = 'Overlapping imported/existing cues require explicit timing edits; this renderer binding has no qualified overlap support.';
    if (model.version.tracks.find(t => t.track_id === track)?.locked) blocked = 'Destination caption track is locked.';
  } catch (e) { blocked = errorText(e); }
  return h(Modal, { title: 'Import timed captions' }, h('p', {}, 'Literal UTF-8 text. Exact timestamps are retained before source mapping and outward output-frame rounding.'), h('input', { type: 'file', accept: '.srt,.vtt,text/vtt', 'aria-label': 'Choose SRT or VTT file', onChange: async e => { const file = e.target.files?.[0]; if (!file) return; try { if (file.size > 1048576) throw new Error('Caption file exceeds the 1 MiB client draft limit.'); const value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); setCues(parseTimedCaptions(value, model.version.format.fps, true)); setFailure(''); } catch (e) { setFailure(errorText(e)); setCues([]); } } }), h('label', {}, 'Timing basis', h('select', { value: basis, onChange: e => setBasis(e.target.value) }, h('option', { value: 'composition' }, 'Composition-relative'), h('option', { value: 'source' }, 'Selected source placement'))), basis === 'source' && h('div', {}, h('label', {}, 'Exact placement', h('select', { value: placementId, onChange: e => setPlacementId(e.target.value) }, h('option', { value: '' }, 'Choose placement'), ...model.version.clips.filter(c => c.subject.kind === 'asset').map(c => h('option', { key: c.clip_id, value: c.clip_id }, `${c.clip_id} · ${c.subject.version_id}`)))), h('label', {}, h('input', { type: 'checkbox', checked: repeats, onChange: e => setRepeats(e.target.checked) }), 'Map all repeated picture placements of this exact source version')), h('label', {}, h('input', { type: 'checkbox', checked: clipBounds, onChange: e => setClipBounds(e.target.checked) }), 'Clip to placement/Composition and exclude out-of-range cues · explicit decision'), (failure || blocked) && h(Notice, { error: true }, failure || blocked), h('label', {}, 'Language tag', h('input', { value: language, onChange: e => setLanguage(e.target.value) })), h('label', {}, 'Destination caption track', h('select', { value: track, onChange: e => setTrack(e.target.value) }, h('option', { value: '' }, 'Choose existing track'), ...model.version.tracks.filter(t => t.kind === 'caption').map(t => h('option', { key: t.track_id, value: t.track_id, disabled: t.locked }, t.name)), h('option', { value: 'new' }, 'Create caption track atomically'))), ...preview.rows.map((c, i) => h('div', { className: 'card', key: i }, h('span', { className: 'mono' }, `Cue ${c.cue} · source ${c.original.join('–')} ms · ${c.placement_id || 'Composition'} · output [${c.start_frame}, ${c.end_frame}) · ${c.status}${c.repeated ? ' · repeated' : ''}`), h('p', { dir: 'auto' }, c.text))), h('label', {}, h('input', { type: 'checkbox', checked: reviewed, onChange: e => setReviewed(e.target.checked) }), 'I reviewed mapped timing, excluded/clipped/repeated rows and literal text.'), h(B, { disabled: Boolean(failure || blocked) || !preview.cues.length || !language || !track || !reviewed, onClick: () => {
    const id = track === 'new' ? uid() : track, operations = [];
    if (track === 'new') operations.push({ op: 'track.create', create_ref: id, kind: 'caption', name: 'Captions', order: model.version.tracks.length, overlap_policy: 'exclusive' });
    operations.push(...preview.cues.map(c => ({ op: 'caption.upsert', cue_id: null, create_ref: uid(), track_id: id, ...c, language, style_ref: style?.schema_ref || style || null })));
    stage(model, operations, 'Import reviewed timed captions · Needs review'); change({ dialog: null });
  } }, 'Apply reviewed cues · Needs review'));
}
function schemaRecords(model) {
  const list = model.capabilities.data?.data?.schemas;
  const initial = model.boot.data?.data?.schemas || model.boot.data?.data?.registry_schemas || {};
  const base = Array.isArray(initial) ? initial : Object.entries(initial).map(([kind, entry]) => ({ kind, ...entry }));
  return [...base, ...(Array.isArray(list) ? list : []), ...(model.capabilities.data?.data?.items || []).filter(item => item.schema_ref && item.schema)];
}
function schemaByRef(model, ref) { return schemaRecords(model).find(s => ref && /^[a-f0-9]{64}$/.test(ref.sha256 || '') && canonical(s.schema_ref) === canonical(ref)) || null; }
export function resolveSchema(schema, root = schema, seen = new Set()) {
  if (!schema) return null;
  if (schema.$ref) {
    if (!schema.$ref.startsWith('#/$defs/') || seen.has(schema.$ref)) return null;
    const name = schema.$ref.slice(8).replaceAll('~1', '/').replaceAll('~0', '~');
    return resolveSchema(root.$defs?.[name], root, new Set([...seen, schema.$ref]));
  }
  const variants = schema.anyOf || schema.oneOf;
  if (variants) { const nonNull = variants.filter(s => s.type !== 'null'); if (nonNull.length === 1) return { ...resolveSchema(nonNull[0], root, seen), nullable: variants.some(s => s.type === 'null') }; }
  return schema;
}
export function schemaSeed(input, root = input, depth = 0) {
  if (depth > 12) return null;
  const schema = resolveSchema(input, root);
  if (!schema) return null;
  if ('default' in schema) return clone(schema.default);
  if ('const' in schema) return schema.const;
  if (schema.nullable) return null;
  if (schema.enum) return schema.enum[0];
  if (schema.type === 'array') return Array.from({ length: Math.min(schema.minItems || 0, 100) }, () => schemaSeed(schema.items, root, depth + 1));
  if (schema.type === 'object') return Object.fromEntries((schema.required || []).filter(k => schema.properties?.[k]).map(k => [k, schemaSeed(schema.properties[k], root, depth + 1)]));
  if (schema.type === 'boolean') return false;
  if (schema.type === 'integer' || schema.type === 'number') return Math.max(0, schema.minimum || 0);
  return '';
}
function SchemaFields({ schema: original, value, onChange, root = original, name = 'Value', depth = 0 }) {
  const schema = resolveSchema(original, root);
  if (!schema || depth > 12) return h('p', { className: 'muted' }, 'This typed binding is not editable on this client. Existing values are retained.');
  if (schema.nullable) return h('fieldset', {}, h('legend', {}, name), h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: value !== null && value !== undefined, onChange: e => onChange(e.target.checked ? schemaSeed({ ...schema, nullable: false }, root) : null) }), 'Use an explicit value'), value !== null && value !== undefined && h(SchemaFields, { schema: { ...schema, nullable: false }, value, onChange, root, name, depth: depth + 1 }));
  if (schema.readOnly || 'const' in schema) return h('label', {}, name, h('output', {}, String(value ?? schema.const ?? 'Not recorded')));
  if (schema.enum) return h('label', {}, name, h('select', { value: value == null ? '' : String(value), onChange: e => onChange(schema.enum.find(x => String(x) === e.target.value)) }, h('option', { value: '' }, 'Choose…'), ...schema.enum.map(v => h('option', { key: String(v), value: String(v) }, String(v)))));
  if (schema.type === 'array') {
    const entries = Array.isArray(value) ? value : [];
    return h('fieldset', { className: 'list' }, h('legend', {}, `${name} · ${entries.length} items`), ...entries.map((entry, i) => h('section', { key: i, className: 'card' }, h('div', { className: 'row spread' }, h('strong', {}, `${name} ${i + 1}`), h('div', { className: 'row' }, h(B, { disabled: i === 0, 'aria-label': `Move ${name} ${i + 1} up`, onClick: () => { const a = clone(entries); [a[i - 1], a[i]] = [a[i], a[i - 1]]; onChange(a); } }, 'Up'), h(B, { disabled: i === entries.length - 1, 'aria-label': `Move ${name} ${i + 1} down`, onClick: () => { const a = clone(entries); [a[i + 1], a[i]] = [a[i], a[i + 1]]; onChange(a); } }, 'Down'), h(B, { disabled: entries.length <= (schema.minItems || 0), 'aria-label': `Remove ${name} ${i + 1}`, onClick: () => onChange(entries.filter((_, n) => n !== i)) }, 'Remove'))), h(SchemaFields, { schema: schema.items, value: entry, onChange: next => onChange(entries.map((v, n) => n === i ? next : v)), root, name: `${name} ${i + 1}`, depth: depth + 1 }))), h(B, { disabled: entries.length >= Math.min(schema.maxItems ?? 1000, 1000), onClick: () => onChange([...entries, schemaSeed(schema.items, root)]) }, `Add ${name} item`));
  }
  if (schema.type === 'object' || schema.properties) {
    const values = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    return h('div', { className: 'list' }, ...Object.entries(schema.properties || {}).map(([key, field]) => {
      const optional = !(schema.required || []).includes(key), present = key in values;
      const next = val => onChange({ ...values, [key]: val });
      return h('div', { key, className: 'list' }, optional && h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: present, onChange: e => { if (e.target.checked) next(schemaSeed(field, root)); else { const a = { ...values }; delete a[key]; onChange(a); } } }), `Include ${field.title || key.replaceAll('_', ' ')}`), (!optional || present) && h(SchemaFields, { schema: field, value: values[key], onChange: next, root, name: field.title || key.replaceAll('_', ' '), depth: depth + 1 }), field.description && h('small', {}, field.description));
    }));
  }
  if (schema.type === 'boolean') return h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: Boolean(value), onChange: e => onChange(e.target.checked) }), name);
  if (schema.type === 'integer' || schema.type === 'number') return h(NumberField, { label: name, unit: schema.unit || 'binding units', value: value ?? '', min: schema.minimum ?? -Number.MAX_SAFE_INTEGER, max: schema.maximum ?? Number.MAX_SAFE_INTEGER, step: schema.type === 'integer' ? 1 : schema.multipleOf || .01, onChange: v => onChange(v === '' ? '' : Number(v)) });
  if (schema.type === 'string') return h('label', {}, name, h(schema.maxLength > 200 || schema.format === 'multiline' ? 'textarea' : 'input', { value: value ?? '', maxLength: schema.maxLength, dir: 'auto', onChange: e => onChange(e.target.value) }));
  return h('p', { className: 'muted' }, `${name}: this union has no qualified edit form. Existing value retained.`);
}
function LayerEffectDialog({ model, effect = false }) {
  const item = effect ? model.version.effects.find(e => e.effect_id === model.s.effect) : model.version.layers.find(l => l.layer_id === model.s.layer);
  const [value, setValue] = useState(clone(item?.parameters || {}));
  const schema = schemaByRef(model, item?.schema_ref);
  return h(Modal, { title: effect ? 'Effect parameters' : 'Layer properties' }, h('p', {}, item?.schema_ref?.id || 'No layer selected'), h(SchemaFields, { schema: effect ? schema?.schema : schema?.schema?.properties?.parameters || schema?.schema, root: schema?.schema, value, onChange: setValue }), h(B, { primary: true, disabled: !schema || !item, onClick: () => { const op = effect ? { op: 'effect.update', effect_id: item.effect_id, schema_ref: item.schema_ref, enabled: item.enabled, parameters: value, keyframes: item.keyframes } : { op: 'layer.update', layer_id: item.layer_id, schema_ref: item.schema_ref, parameters: value, keyframes: item.keyframes, start_frame: item.start_frame, end_frame: item.end_frame, order: item.order }; stage(model, [op], 'Apply grouped source properties'); change({ dialog: null }); } }, 'Apply supported properties'));
}
function Production({ model }) {
  const [section, setSection] = useState('Storyboard');
  const proposals = useCollection(model.cpath && model.cpath + '/proposals', { state: 'all' }, model, true);
  if (!model.version) return h(CompositionEmpty, { model });
  return h('div', { className: 'body' }, h('div', { className: 'row' }, ...['Storyboard', 'Brief & brand', 'Creative plan', 'Voice', 'Proposals', 'Review & delivery'].map(s => h(B, { key: s, onClick: () => setSection(s), 'aria-pressed': section === s }, s))), section === 'Proposals' ? h(QueryState, { query: proposals.query, emptyText: 'No admitted agent proposals' }, proposals.items.length > 0 && proposals.items.map(p => h('div', { key: p.proposal_id, className: 'card' }, h('h3', {}, p.summary || p.proposal_id), h(Badge, {}, p.validity || p.state), h('p', { className: 'mono' }, `Base ${p.base_version_id}`), h(B, { onClick: () => change({ proposal: p.proposal_id, dialog: 'proposal' }) }, 'Compare scoped changes…')))) : section === 'Review & delivery' ? h(Candidates, { model }) : section === 'Voice' ? h('div', { className: 'card' }, h('h3', {}, 'Voice production'), h(ProductionDocument, { model, kind: 'voice_preferences' }), h('p', {}, 'Script, language, voice identity and style are supplied only by the selected voice schema. Preview and full takes are separate consuming actions. Reference use requires exact-byte authority.'), h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'audio_process' }) }, 'Choose voice / audio route…')) : section === 'Brief & brand' ? h('div', { className: 'list' }, h(ProductionDocument, { model, kind: 'brief' }), h(ProductionDocument, { model, kind: 'brand' })) : h(ProductionDocument, { model, kind: section === 'Storyboard' ? 'storyboard' : 'creative_plan' }), h('div', { className: 'row' }, h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'scene_generate' }) }, 'Author / generate…'), h(B, { onClick: () => change({ dialog: 'settings' }) }, 'Capabilities & route settings')));
}
export function documentMatchesReference(ref, document) {
  return Boolean(ref && document && /^[a-f0-9]{64}$/.test(ref.sha256 || '') && document.document_id === ref.document_id && document.document_version_id === ref.document_version_id && document.kind === ref.kind && document.sha256 === ref.sha256 && canonical(document.schema_ref) === canonical(ref.schema_ref) && document.value != null);
}
function ProductionDocument({ model, kind }) {
  const ref = model.saved?.production_documents.find(d => d.kind === kind);
  const pending = [...(model.draft?.operations || [])].reverse().find(o => o.op === 'document.put' && o.kind === kind);
  // Values are fetched only through the exact authorized saved Composition version.
  const query = useRead(ref ? `${model.cpath}/documents/${enc(ref.document_id)}` : null, { version_id: model.saved?.version_id }, model.scope, Boolean(ref));
  const fetched = query.data?.data;
  const loaded = !ref || documentMatchesReference(ref, fetched);
  const [editing, setEditing] = useState(false), [value, setValue] = useState(null);
  const schemas = schemaRecords(model);
  const schema = ref ? schemaByRef(model, ref.schema_ref) : schemas.find(s => s.kind === kind);
  const doc = value ?? pending?.value ?? fetched?.value ?? (schema ? schemaSeed(schema.schema) : {});
  useEffect(() => { setValue(null); setEditing(false); }, [kind, ref?.sha256, model.saved?.version_id]);
  if (ref && !loaded) return h(QueryState, { query }, query.data && h(Notice, { error: true }, 'Document identity/hash/schema does not match the pinned saved Composition reference. Refresh before editing.'));
  if (pending) return h('div', { className: 'list' }, h('h3', {}, kind.replaceAll('_', ' ')), h(Badge, {}, 'Local document change · Needs save'), h(SchemaRead, { value: doc }), h('p', {}, 'Save/reconcile this exact document batch before editing it again or requesting saved-revision acceptance.'));
  return h('div', { className: 'list' }, h('div', { className: 'row spread' }, h('h3', {}, kind.replaceAll('_', ' ')), h(Badge, {}, ref ? `Saved · ${ref.sha256.slice(0, 8)}` : 'Not authored')), kind === 'storyboard' && !editing ? h('div', { className: 'list' }, ...(doc.panels || []).map((p, i) => h('section', { className: 'card', key: p.panel_id || i }, h('h3', {}, p.title || `Panel ${i + 1}`), h('p', { dir: 'auto' }, p.description || p.beat || ''), h(Badge, {}, p.render_candidate_id ? 'Candidate recorded · inspect separately' : 'Not rendered'), h('p', {}, `Duration: ${p.duration_frames ?? 'Unknown'} frames`), h(B, { onClick: () => change({ dialog: 'production-action', productionIntent: 'scene_generate', productionSelection: [p.panel_id].filter(Boolean) }) }, 'Render prepared panel…'))), !(doc.panels || []).length && h(Unavailable, { title: 'No storyboard panels', reason: 'Unrendered or unauthored panels are never represented as completed images.' })) : editing ? h(SchemaFields, { schema: schema?.schema, value: doc, onChange: setValue }) : h(SchemaRead, { value: doc }), h('div', { className: 'row' }, h(B, { disabled: !schema, onClick: () => setEditing(!editing) }, editing ? 'Cancel editing' : 'Edit document'), editing && h(B, { primary: true, onClick: () => { stage(model, [{ op: 'document.put', kind, document_id: ref?.document_id || null, create_ref: ref ? null : uid(), schema_ref: ref?.schema_ref || schema.schema_ref, value: doc, expected_document_sha256: ref?.sha256 || null }], `Update ${kind}`); setEditing(false); } }, 'Apply document'), h(B, { disabled: !ref, onClick: () => change({ dialog: 'acceptance', document: ref }) }, 'Request exact-revision acceptance…')), !schema && h('p', { className: 'muted' }, 'The connected facade has not advertised an editable public document schema. Existing bytes are preserved read-only.'));
}
function SchemaRead({ value }) {
  if (value == null || typeof value !== 'object') return h('span', { dir: 'auto' }, String(value ?? 'Not recorded'));
  return h('dl', {}, ...Object.entries(value).map(([key, v]) => h('div', { key, className: 'card' }, h('dt', { className: 'muted' }, key.replaceAll('_', ' ')), h('dd', { style: { margin: 0 } }, Array.isArray(v) ? v.map((x, i) => h(SchemaRead, { key: i, value: x })) : typeof v === 'object' && v ? h(SchemaRead, { value: v }) : String(v ?? 'Not recorded')))));
}
export async function insertPreparedRequest(target, text) {
  const current = () => target && ownerKey(ownerNow()) === target.owner_key && host.state.focusedStoredSessionId.get() === target.session_id;
  if (!target?.session_id || !current()) throw new Error('The exact conversation or owner changed. Prepare again for the intended visible conversation.');
  if (!host.composer?.getDraft || !host.composer?.insertText) throw new Error('This host does not expose acknowledged public composer insertion.');
  const before = await host.composer.getDraft(target.session_id);
  if (typeof before !== 'string' || !current()) throw new Error('The captured visible composer is unavailable or changed; nothing was inserted.');
  const acknowledged = await host.composer.insertText(target.session_id, text, { mode: 'block' });
  if (!acknowledged || !current()) throw new Error('Composer insertion was not acknowledged in the captured context. It may have inserted; inspect that conversation before retrying.');
  const after = await host.composer.getDraft(target.session_id);
  if (!current() || typeof after !== 'string' || !after.includes(text)) throw new Error('Insertion acknowledgement could not be read back in the captured conversation. Inspect it before retrying.');
  return { state: 'inserted_not_submitted', session_id: target.session_id };
}
function HandoffDialog({ model }) {
  const data = model.capabilities.data?.data;
  const actions = data?.allowed_handoff_actions || [];
  const [actionId, setActionId] = useState(model.s.selectedOperation || ''), [parameters, setParameters] = useState({}), [rationale, setRationale] = useState(''), [prepared, setPrepared] = useState(null);
  const [conversation, setConversation] = useState(null), [frozenText, setFrozenText] = useState(''), [insertion, setInsertion] = useState('');
  const action = actions.find(a => a.operation_schema_ref?.id === actionId || a.id === actionId);
  const schema = action?.schema || schemaByRef(model, action?.operation_schema_ref)?.schema;
  const status = useRead(prepared ? `${model.cpath}/handoffs/${enc(prepared.handoff_id)}` : null, {}, model.scope, Boolean(prepared), true);
  return h(Modal, { title: 'Scoped production handoff' }, h('p', {}, 'Preparation is not execution. Hermes’ trusted composer and approvals remain authoritative; Studio never calls private tool handlers.'), h('label', {}, 'Advertised operation', h('select', { value: actionId, onChange: e => { setActionId(e.target.value); setParameters({}); setPrepared(null); } }, h('option', { value: '' }, 'Choose a compatible route'), ...actions.map(a => h('option', { key: a.id || a.operation_schema_ref.id, value: a.id || a.operation_schema_ref.id, disabled: a.available === false }, `${a.label || a.id || a.operation_schema_ref.id}${a.reason ? ' · ' + a.reason : ''}`)))), h(SchemaFields, { schema, value: parameters, onChange: setParameters }), h('label', {}, 'Rationale / scoped feedback', h('textarea', { value: rationale, dir: 'auto', onChange: e => setRationale(e.target.value) })), !actions.length && h(Unavailable, { title: 'No compatible handoff is advertised', reason: 'A skill or discovered tool name is not an execution route. Open native capability setup or ask in the main conversation.' }), action && h(SchemaRead, { value: { execution_host: action.execution_host || 'Not observed', expected_effects: action.expected_effects || [], support: action.support || 'Unknown', approval: action.approval || 'Not established' } }), h(B, { disabled: !action || !schema || !rationale || Boolean(model.draft), onClick: async () => { const target = { owner_key: ownerKey(ownerNow()), session_id: host.state.focusedStoredSessionId.get() };
      const input = clone({ intent: action.intent || model.s.productionIntent || 'diagnose', operation_schema_ref: action.operation_schema_ref, selected_entity_ids: model.s.productionSelection || model.s.selected, parameters, expected_effects: action.expected_effects || [], rationale });
      const scope = clone(model.scope), composition = model.s.composition;
      const r = await command(model.cpath + '/handoffs', 'OP-HANDOFF-PREPARE', scope, model.cas, input);
      setPrepared(r); setConversation(target); setInsertion('');
      setFrozenText('Motion Studio prepared request — review before sending. This is prepared context, not execution, acceptance or a permission/spend grant.\n' + canonical({ scope, composition_id: composition, handoff: r, requested_operation: input }) + '\nPlease inspect these exact immutable pins and request any required approvals. Do not infer that preparation authorized or executed effects.'); } }, 'Prepare exact scoped handoff'), prepared && h('div', { className: 'card' }, h(Badge, {}, status.data?.data?.state || 'Prepared · not sent'), h('p', {}, `Version ${prepared.version_id} · expires ${prepared.expires_at}`), h(B, { disabled: !conversation?.session_id || !frozenText || Boolean(insertion), onClick: async () => { setInsertion('Insertion pending · do not retry'); try { await insertPreparedRequest(conversation, frozenText); setInsertion('Acknowledged insertion in captured conversation · not submitted, not executed'); } catch (e) { setInsertion(errorText(e)); } } }, 'Insert prepared request in conversation'), insertion && h(Notice, {}, insertion), !conversation?.session_id && h(Notice, {}, 'No exact stored conversation was captured. Open the intended saved conversation and prepare again; runtime-only session identity is not inferred.'), h('p', { className: 'muted' }, 'Public composer block insertion preserves the existing draft. Nothing is auto-submitted. Handoff/result correlation remains unavailable until the backend confirms an actual request receipt; prepared or inserted never means executed.')));
}
function ProposalDialog({ model }) {
  const q = useRead(`${model.cpath}/proposals/${enc(model.s.proposal)}`, {}, model.scope);
  const p = q.data?.data;
  return h(Modal, { title: 'Compare agent proposal' }, h(QueryState, { query: q }, p && h('div', { className: 'list' }, h(Facts, { value: p, fields: ['proposal_id', 'base_version_id', 'base_composition_revision', 'validity', 'expires_at'] }), h(SchemaRead, { value: p.diff }), h('h3', {}, 'Source evidence'), h(SchemaRead, { value: p.source_evidence || { status: 'Not recorded' } }), ...['apply', 'reject'].map(decision => h(B, { key: decision, disabled: decision === 'apply' && (p.base_version_id !== model.saved.version_id || Boolean(model.draft)), onClick: async () => { await command(`${model.cpath}/proposals/${enc(p.proposal_id)}/decision`, 'OP-PROPOSAL-DECIDE', model.scope, { ...model.cas, entity_revision: p.entity_revision }, { decision, proposal_sha256: p.sha256 || p.proposal_sha256, reason: decision === 'apply' ? 'Reviewed exact scoped changes' : 'Rejected from native Studio', acknowledged_dependency_ids: [] }); change({ dialog: null }); } }, decision === 'apply' ? 'Apply atomically · one undo unit' : 'Reject proposal')))));
}
function Jobs({ model }) {
  const [filter, setFilter] = useState('');
  const jobs = useCollection(model.ppath && model.ppath + '/jobs', { ...(filter ? { state: filter } : {}) }, model, true);
  return h('div', { className: 'body' }, h('div', { className: 'row spread' }, h('h3', {}, 'Observed work'), h('select', { 'aria-label': 'Job state filter', value: filter, onChange: e => setFilter(e.target.value) }, h('option', { value: '' }, 'All states'), ...['queued', 'waiting_for_approval', 'running', 'cancel_requested', 'succeeded', 'failed', 'interrupted', 'reconciliation_required'].map(s => h('option', { key: s, value: s }, s.replaceAll('_', ' '))))), h(QueryState, { query: jobs.query, emptyText: 'No jobs in this Project' }, jobs.items.length > 0 && jobs.items.map(job => h('section', { key: job.job_id, className: 'card' }, h('div', { className: 'row spread' }, h('h3', {}, job.kind), h(Badge, {}, job.state.replaceAll('_', ' '))), h('p', { className: 'mono muted' }, `${job.job_id} · ${job.version_id || 'Project-level job'}`), job.progress?.percent_milli != null ? h('progress', { max: 100000, value: job.progress.percent_milli, 'aria-label': `${job.kind} measured progress` }) : h('p', {}, 'Progress not measured'), h('p', {}, job.progress?.phase || 'Stage not observed'), h('small', {}, job.progress?.observed_at ? `Observed ${job.progress.observed_at} · ${job.progress.source || 'source unspecified'}` : 'No progress observation timestamp'), job.error && h(Notice, { error: true }, job.error.message || 'Job failed; inspect recovery details.'), h('div', { className: 'row' }, h(B, { onClick: () => change({ dialog: 'job', job: job.job_id }) }, 'Details / recovery…'), h(B, { disabled: !job.cancel?.supported || ['succeeded', 'failed', 'cancelled'].includes(job.state), onClick: () => change({ dialog: 'cancel-job', jobObject: job }) }, 'Stop…'))))), jobs.more && h(B, { onClick: jobs.more }, 'Load more jobs'));
}
function JobDialog({ model }) {
  const q = useRead(`${model.ppath}/jobs/${enc(model.s.job)}`, {}, model.scope, true, true);
  const job = q.data?.data?.job || q.data?.data;
  return h(Modal, { title: 'Job detail and recovery' }, h(QueryState, { query: q }, job && h('div', { className: 'list' }, h(Facts, { value: job, fields: ['job_id', 'state', 'kind', 'version_id', 'effect_state', 'entity_revision'] }), h(SchemaRead, { value: { attempts: job.attempts, results: job.result_refs, error: job.error, progress: job.progress, source_probe: job.source_probe } }), h('p', {}, 'Cancellation requested is not a worker-confirmed stop. Unknown effects must be reconciled before another attempt.'), ...(job.recovery_actions || []).map(a => h(B, { key: a.action, onClick: () => command(`${model.ppath}/jobs/${enc(job.job_id)}/recovery`, 'OP-JOB-RECOVER', model.scope, { entity_revision: job.entity_revision }, { action: a.action, checkpoint_id: a.checkpoint_id || null, checkpoint_sha256: a.checkpoint_sha256 || null, approval_refs: a.approval_refs || [], acknowledge_unknown_effects: false }) }, a.label || a.action)))));
}
function CancelJob({ model }) { const job = model.s.jobObject; return h(Modal, { title: `Stop ${job.kind}?` }, h('p', {}, 'Completed outputs will be retained. Cancellation is best-effort and may race with completion.'), h(B, { onClick: async () => { await command(`${model.ppath}/jobs/${enc(job.job_id)}/cancel`, 'OP-JOB-CANCEL', model.scope, { entity_revision: job.entity_revision }, { reason: 'User requested stop from native Studio', mode: 'best_effort_owned' }); change({ dialog: null, tab: 'Jobs' }); } }, 'Stop job'), h(B, { onClick: () => change({ dialog: null }) }, 'Keep running')); }
function Candidates({ model }) {
  const candidates = useCollection(model.cpath && model.cpath + '/candidates', {}, model, true);
  const deliveries = useCollection(model.cpath && model.cpath + '/delivery-sets', {}, model, true);
  return h('div', { className: 'list' }, h('h3', {}, 'Encoded candidates'), h(QueryState, { query: candidates.query, emptyText: 'No collected, hash-verified candidate' }, candidates.items.length > 0 && candidates.items.map(c => h('div', { className: 'card', key: c.candidate_id }, h('strong', {}, c.candidate_id), h(Badge, {}, c.head_relation || c.relation_to_head || 'Version relationship not observed'), h('p', { className: 'mono' }, c.sha256), h(B, { onClick: () => change({ dialog: 'review', candidate: c.candidate_id }) }, 'Review actual encoded files…')))), candidates.more && h(B, { onClick: candidates.more }, 'Load more candidates'), h('h3', {}, 'Exact delivery sets'), h(QueryState, { query: deliveries.query, emptyText: 'No frozen delivery sets' }, deliveries.items.length > 0 && deliveries.items.map(d => h('div', { className: 'card', key: d.delivery_set_id }, h('strong', {}, d.delivery_set_id), h(Badge, {}, typeof d.completeness === 'string' ? d.completeness : 'Inspect exact completeness'), h(B, { onClick: () => change({ dialog: 'delivery', delivery: d.delivery_set_id }) }, 'Inspect manifest and transfer…')))));
}
function ExportDialog({ model }) {
  const data = model.capabilities.data?.data;
  const recipes = data?.recipes?.filter(r => r.action === 'render' || r.operation === 'render') || [];
  const [recipeId, setRecipeId] = useState(''), [parameters, setParameters] = useState({}), [quality, setQuality] = useState('preview'), [preflight, setPreflight] = useState(null), [snapshot, setSnapshot] = useState(null), [approval, setApproval] = useState(null), [older, setOlder] = useState(false);
  const recipe = recipes.find(r => r.recipe_ref?.id === recipeId);
  const approvalStatus = useRead(approval ? `${model.cpath}/approval-requests/${enc(approval.approval_request_id)}` : null, {}, model.scope, Boolean(approval), true);
  return h(Modal, { title: 'Export saved composition' }, h('p', {}, `Pinned saved revision r${model.saved?.composition_revision}. Export does not include unsynchronized drafts.`), h('label', {}, 'Qualified render recipe', h('select', { value: recipeId, onChange: e => { setRecipeId(e.target.value); setParameters({}); setPreflight(null); setSnapshot(null); } }, h('option', { value: '' }, 'Choose compatible route'), ...recipes.map(r => h('option', { key: r.recipe_ref.id, value: r.recipe_ref.id, disabled: r.available === false }, `${r.label || r.recipe_ref.id}${r.reason ? ' · ' + r.reason : ''}`)))), h('label', {}, 'Quality purpose', h('select', { value: quality, onChange: e => { setQuality(e.target.value); setPreflight(null); setSnapshot(null); } }, h('option', { value: 'preview' }, 'Review preview · not final checked delivery'), h('option', { value: 'master' }, 'Master candidate · checks still required'))), h(SchemaFields, { schema: recipe?.parameter_schema, value: parameters, onChange: v => { setParameters(v); setPreflight(null); setSnapshot(null); } }), !recipes.length && h(Unavailable, { title: 'No qualified render recipe', reason: 'Formats, codecs, captions and output destinations must come from the selected route, not a universal invented menu.' }), h(B, { disabled: !recipe || Boolean(model.draft), onClick: async () => { const range = model.s.range || { start_frame: 0, end_frame: model.saved.format.duration_frames }; const r = await command(model.cpath + '/preflights', 'OP-PREFLIGHT', model.scope, model.cas, { action: 'render', recipe_ref: recipe.recipe_ref, parameters: { ...parameters, range, quality, deliverable_profiles: recipe.deliverable_profiles || [] }, dependency_hashes: recipe.dependency_hashes || [], probe_policy: 'cached_only', acknowledged_effects: [] }); setPreflight(r); } }, 'Check exact plan · no production'), preflight && h('div', { className: 'card' }, h('h3', {}, 'Preflight'), h(SchemaRead, { value: { readiness: preflight.readiness, blockers: preflight.blockers, required_approvals: preflight.required_approvals, expires_at: preflight.expires_at } }), h(B, { disabled: Boolean(preflight.blockers?.length), onClick: async () => setApproval(await command(`${model.cpath}/preflights/${enc(preflight.preflight_id)}/approval-requests`, 'OP-APPROVAL-REQUEST', model.scope, { preflight_sha256: preflight.preflight_sha256 }, { plan_sha256: preflight.plan_sha256, effects_sha256: preflight.effects_sha256, approval_kind: 'host_policy', reason: 'Export this exact saved render plan' })) }, 'Request native host approval'), approval && h(Badge, {}, `Host decision: ${approvalStatus.data?.data?.state || 'pending'}`), h(B, { disabled: Boolean(preflight.blockers?.length), onClick: async () => setSnapshot(await command(model.cpath + '/render-snapshots', 'OP-RENDER-PREPARE', model.scope, model.cas, { preflight_id: preflight.preflight_id, recipe_ref: recipe.recipe_ref, deliverable_profiles: recipe.deliverable_profiles || [], range: model.s.range || { start_frame: 0, end_frame: model.saved.format.duration_frames }, quality, dependency_hashes: recipe.dependency_hashes || [] })) }, 'Freeze exact render snapshot')), snapshot && h('div', { className: 'card' }, h(Facts, { value: snapshot, fields: ['snapshot_id', 'version_id', 'snapshot_sha256'] }), h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: older, onChange: e => setOlder(e.target.checked) }), 'If the editor advances, I still want this exact older snapshot.'), h(B, { primary: true, disabled: Boolean(snapshot.blockers?.length) || (Boolean(preflight.required_approvals?.length) && approvalStatus.data?.data?.state !== 'approved'), onClick: async () => { const a = approvalStatus.data?.data; await command(model.cpath + '/renders', 'OP-RENDER-LAUNCH', model.scope, { snapshot_id: snapshot.snapshot_id, snapshot_sha256: snapshot.snapshot_sha256 || snapshot.sha256 }, { approval_refs: a?.approval_ref ? [a.approval_ref] : a?.approval_refs || [], acknowledge_older_head: older }); change({ dialog: null, tab: 'Jobs' }); } }, 'Start exact authorized render')));
}
function ReviewDialog({ model }) {
  const q = useRead(`${model.cpath}/candidates/${enc(model.s.candidate)}`, {}, model.scope, true, true);
  const data = q.data?.data, candidate = data?.candidate || data;
  const [gate, setGate] = useState(''), [decision, setDecision] = useState('needs_changes'), [note, setNote] = useState(''), [start, setStart] = useState('0'), [end, setEnd] = useState(''), [selectedFiles, setSelectedFiles] = useState([]);
  const gates = data?.gates || data?.gate_results || [];
  const rules = Array.isArray(gates) ? gates : gates.items || [];
  const file = candidate?.files?.find(f => f.role === 'video' || f.probe?.video) || candidate?.files?.[0];
  return h(Modal, { title: 'Review encoded candidate' }, h(QueryState, { query: q }, candidate && h('div', { className: 'list' }, h(Facts, { value: candidate, fields: ['candidate_id', 'sha256', 'snapshot_id', 'entity_revision'] }), file && h(Monitor, { model, reviewMedia: file, purpose: 'review' }), h('h3', {}, 'Required gates · exact candidate'), h(SchemaRead, { value: gates }), h('label', {}, 'Human editorial gate', h('select', { value: gate, onChange: e => setGate(e.target.value) }, h('option', { value: '' }, 'Choose returned rule'), ...rules.filter(g => g.gate_ref).map(g => h('option', { key: g.gate_ref.rule_id, value: g.gate_ref.rule_id }, g.label || g.gate_ref.rule_id)))), h('div', { className: 'grid' }, h(NumberField, { label: 'Actually inspected range in', value: start, onChange: setStart }), h(NumberField, { label: 'Actually inspected range out', value: end, onChange: setEnd, min: 1 })), h('label', {}, 'Findings / uncovered intervals', h('textarea', { value: note, dir: 'auto', onChange: e => setNote(e.target.value) })), h('label', {}, 'Editorial decision · not an automated check', h('select', { value: decision, onChange: e => setDecision(e.target.value) }, ...['needs_changes', 'fail', 'pass'].map(v => h('option', { key: v, value: v }, v)))), h(B, { disabled: !gate || !note || !end, onClick: () => command(`${model.cpath}/candidates/${enc(candidate.candidate_id)}/reviews`, 'OP-REVIEW-RECORD', model.scope, { candidate_sha256: candidate.sha256, gate_revision: data.gate_revision }, { gate_ref: rules.find(g => g.gate_ref?.rule_id === gate).gate_ref, review_kind: 'human_editorial', coverage: [{ file_id: file.file_id, start_frame: safeInteger(start), end_frame: safeInteger(end, safeInteger(start) + 1) }], findings: [{ severity: decision === 'pass' ? 'info' : 'warning', code: 'HUMAN_EDITORIAL_NOTE', message: note, entity_ref: null, frame_range: { start_frame: safeInteger(start), end_frame: safeInteger(end) } }], decision, evidence_refs: [], check_recipe_ref: null }) }, 'Record actual editorial observation'), h('h3', {}, 'Exact delivery file set'), ...(candidate.files || []).map(f => h('label', { key: f.file_id, className: 'card' }, h('span', { className: 'row' }, h('input', { type: 'checkbox', checked: selectedFiles.includes(f.file_id), onChange: e => setSelectedFiles(e.target.checked ? [...selectedFiles, f.file_id] : selectedFiles.filter(id => id !== f.file_id)) }), `${f.display_name || f.file_id} · ${f.role}`), h('span', { className: 'mono' }, `${f.byte_length} bytes · ${f.sha256}`))), h(B, { disabled: !selectedFiles.length, onClick: async () => { const profiles = candidate.files.filter(f => selectedFiles.includes(f.file_id)); const r = await command(model.cpath + '/delivery-sets', 'OP-DELIVERY-SET-CREATE', model.scope, { candidate_sha256: candidate.sha256, gate_revision: data.gate_revision }, { candidate_id: candidate.candidate_id, requested_items: profiles.map(f => ({ profile_id: f.profile_id, role: f.role, required: true })), selected_file_ids: selectedFiles, required_gate_refs: rules.filter(g => g.required).map(g => g.gate_ref), omissions: [], destination_kind: 'client_download', destination_id: null }); change({ dialog: 'delivery', delivery: r.delivery_set_id }); } }, 'Freeze selected delivery set · check blockers'))));
}
function DeliveryDialog({ model }) {
  const q = useRead(`${model.cpath}/delivery-sets/${enc(model.s.delivery)}`, {}, model.scope, true, true);
  const d = q.data?.data;
  return h(Modal, { title: 'Exact-set delivery manifest' }, h(QueryState, { query: q }, d && h('div', { className: 'list' }, h(Facts, { value: d, fields: ['delivery_set_id', 'manifest_sha256', 'candidate_id', 'snapshot_id', 'entity_revision'] }), h(SchemaRead, { value: { completeness: d.completeness, blockers: d.blockers, items: d.items, transfers: d.transfers } }), h('p', {}, 'Ready to download is not delivered. Video, sidecars and packages have separate hashes and checks. Recipient acceptance is never inferred.'), h(B, { disabled: true, title: 'No qualified browser-supported exact-manifest local save path is installed' }, 'Download exact verified manifest'), h('p', { className: 'muted' }, 'Verified playback is not proof of a local download. Exact-manifest browser saving is not qualified; no file was downloaded and no recipient receipt is claimed.'))));
}
// Recovery reviews hash only public, immutable source/document/schema bytes.
const RECOVERY_GRAPH_FIELDS = ['schema_version', 'format', 'tracks', 'clips', 'scenes', 'layers', 'effects', 'audio_buses', 'captions', 'asset_refs', 'settings', 'production_documents'];
function recoveryPin(version) {
  const pin = Object.fromEntries(['composition_id', 'version_id', 'composition_revision', 'sha256'].map(k => [k, version?.[k]]));
  if (!pin.composition_id || !pin.version_id || !Number.isSafeInteger(pin.composition_revision) || !/^[a-f0-9]{64}$/.test(pin.sha256)) throw new Error('Recovery blocked: authoritative saved version pin is incomplete.');
  return pin;
}
function recoveryIntention(key) {
  const d = storage.drafts[key], j = storage.journals[key], owner = studioState.get().owner;
  if ((d && ownerKey(d.owner) !== ownerKey(owner)) || (j && ownerKey(j.owner) !== ownerKey(owner))) throw new Error('Recovery blocked: retained intention belongs to another connection/profile.');
  if (j) {
    if (j.operation !== 'OP-TRANSACTION' || !Array.isArray(j.body.input.operations) || !j.body.input.operations.length || j.body.input.dependency_policy !== 'reject_unlisted' || !Array.isArray(j.body.input.acknowledged_dependency_ids)) throw new Error('Recovery blocked: original frozen typed transaction is unavailable.');
    if (d && (canonical(j.body.input.operations) !== canonical(d.operations) || canonical(j.body.input.acknowledged_dependency_ids) !== canonical(d.dependencies || []) || j.body.preconditions.version_id !== d.base?.version_id || j.body.preconditions.composition_revision !== d.base?.composition_revision)) throw new Error('Recovery blocked: draft differs from original frozen transaction/base. Export both for review; neither is replayed.');
    return clone({ base: j.body.preconditions, operations: j.body.input.operations, acknowledged_dependency_ids: j.body.input.acknowledged_dependency_ids });
  }
  if (!d?.base || !Array.isArray(d.operations) || !d.operations.length) throw new Error('Recovery blocked: no exact retained transaction/base.');
  return clone({ base: d.base, operations: d.operations, acknowledged_dependency_ids: d.dependencies || [] });
}
function recoveryContext(model, cap) {
  if (!isCurrent(cap) || model.key !== compositionKey(model.scope) || cap.project !== model.s.project || cap.composition !== model.s.composition || !transportReady(cap.owner)) throw new Error('Recovery context changed; return to the original connection, Project and Composition.');
  if (!model.can('OP-RECOVERY-REVIEW') || !model.can('OP-RECOVER-AS-NEW')) throw new Error('Recovery unavailable: backend must advertise both recovery operations.');
}
async function recoveryOriginals(model, cap) {
  for (const [key, j] of Object.entries(storage.journals)) {
    if (ownerKey(j.owner) !== ownerKey(cap.owner) || scopeKey(j.body.scope) !== scopeKey(model.scope) || ['OP-RECOVERY-REVIEW', 'OP-RECOVER-AS-NEW'].includes(j.operation)) continue;
    if (!['committed', 'failed'].includes(j.state) || j.error?.effect_state === 'unknown') {
      // Never re-submit an ambiguous original, including a NOT_FOUND status lookup.
      const r = await read(`/commands/${enc(j.body.command_id)}`, { scope: j.body.scope, request_sha256: j.request_sha256 }, model.scope, cap);
      if (r.data.command_id !== j.body.command_id || r.data.request_sha256 !== j.request_sha256) throw new Error('Recovery blocked: original status does not match frozen command/hash.');
      j.state = r.data.status; j.status = r.data; persist();
      if (!isCurrent(cap)) throw new Error('Connection changed during original command reconciliation.');
      if (!['committed', 'failed'].includes(j.state) || r.data.effect_state === 'unknown') throw new Error(`Recovery blocked: original command ${j.body.command_id} remains ambiguous. No replay was sent.`);
    }
    if (key === model.key && j.state === 'committed') throw new Error('Recovery blocked: the original edit already committed. Refresh its receipt/version instead of recovering it again.');
  }
}
export async function makeRecoveryReview({ sourceVersion, headVersion, schemas, intention, documentRebindIds = [] }) {
  if (!Array.isArray(intention?.operations) || !intention.operations.length || !Array.isArray(intention.acknowledged_dependency_ids)) throw new Error('Recovery blocked: exact retained operations/dependency decisions are absent.');
  const source = recoveryPin(sourceVersion), current_head = recoveryPin(headVersion);
  if (source.version_id !== intention.base.version_id || source.composition_revision !== intention.base.composition_revision || source.composition_id !== current_head.composition_id) throw new Error('Recovery blocked: immutable source does not match the retained base.');
  if (!schemas || typeof schemas !== 'object' || !Object.keys(schemas).length) throw new Error('Recovery blocked: exact authoritative schema catalog bytes are absent.');
  const graph = {};
  for (const key of RECOVERY_GRAPH_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(sourceVersion, key)) throw new Error(`Recovery blocked: source graph field ${key} is absent.`);
    graph[key] = clone(sourceVersion[key]);
  }
  if (!Array.isArray(graph.production_documents) || graph.production_documents.some(d => !Object.prototype.hasOwnProperty.call(d, 'value'))) throw new Error('Recovery blocked: immutable source document values are absent.');
  if (!Array.isArray(documentRebindIds) || new Set(documentRebindIds).size !== documentRebindIds.length || documentRebindIds.some(id => typeof id !== 'string' || !id)) throw new Error('Recovery blocked: document rebind decisions must be distinct exact document IDs or create_ref aliases.');
  return { source, current_head, base_graph_sha256: await publicHash(graph), schema_catalog_sha256: await publicHash(schemas), transaction: { operations: clone(intention.operations), dependency_policy: 'reject_unlisted', acknowledged_dependency_ids: clone(intention.acknowledged_dependency_ids), document_rebind_ids: clone(documentRebindIds) } };
}
async function loadRecoveryReview(model, documentRebindIds) {
  const cap = capture(); recoveryContext(model, cap);
  const intention = recoveryIntention(model.key);
  await recoveryOriginals(model, cap);
  const [source, head, bootstrap, catalog] = await Promise.all([
    read(model.cpath, { version_id: intention.base.version_id }, model.scope, cap),
    read(model.cpath, {}, model.scope, cap), read('/bootstrap', { client_contract: 'ui.v1', client_kind: 'desktop' }, null, cap),
    read(model.ppath + '/compositions', { include_archived: false, limit: 1 }, model.scope, cap),
  ]);
  const sourceVersion = clone(source.data.version);
  if (!sourceVersion?.production_documents) throw new Error('Recovery blocked: immutable source graph/documents unavailable.');
  sourceVersion.production_documents = await Promise.all(sourceVersion.production_documents.map(async pin => {
    const r = await read(model.cpath + `/documents/${enc(pin.document_id)}`, { version_id: sourceVersion.version_id }, model.scope, cap);
    if (r.data.document_id !== pin.document_id || r.data.document_version_id !== pin.document_version_id || r.data.sha256 !== pin.sha256 || !Object.prototype.hasOwnProperty.call(r.data, 'value') || await publicHash(r.data.value) !== pin.sha256 || canonical(Object.fromEntries(Object.entries(r.data).filter(([k]) => k !== 'value'))) !== canonical(Object.fromEntries(Object.entries(pin).filter(([k]) => k !== 'value')))) throw new Error('Recovery blocked: exact source document read-back does not match its immutable pin.');
    return r.data;
  }));
  recoveryContext(model, cap);
  if (canonical(intention) !== canonical(recoveryIntention(model.key))) throw new Error('Retained edits changed while loading; review again.');
  const review = await makeRecoveryReview({ sourceVersion, headVersion: head.data.version, schemas: bootstrap.data.schemas, intention, documentRebindIds });
  const revision = catalog.data.catalog_revision;
  if (!Number.isSafeInteger(revision)) throw new Error('Recovery blocked: authoritative catalog revision unavailable.');
  return { cap, intention, review, review_sha256: await publicHash(review), preconditions: { composition_revision: review.current_head.composition_revision, version_id: review.current_head.version_id, catalog_revision: revision } };
}
async function checkRecoveryFresh(model, prepared, token = null) {
  recoveryContext(model, prepared.cap);
  if (canonical(prepared.intention) !== canonical(recoveryIntention(model.key)) || await publicHash(prepared.review) !== prepared.review_sha256) throw new Error('Recovery review changed; prepare a new review.');
  const fresh = await loadRecoveryReview(model, prepared.review.transaction.document_rebind_ids);
  if (fresh.review_sha256 !== prepared.review_sha256 || canonical(fresh.preconditions) !== canonical(prepared.preconditions)) throw new Error('Recovery source/head/schema/catalog changed. Prepare and explicitly review again.');
  if (token) validateRecoveryToken(prepared, token);
  recoveryContext(model, prepared.cap);
}
export function validateRecoveryToken(prepared, token, now = Date.now()) {
  if (token.review_sha256 !== prepared.review_sha256 || typeof token.review_token !== 'string' || !token.review_token || !Number.isFinite(Date.parse(token.expires_at)) || Date.parse(token.expires_at) <= now || canonical(token.source) !== canonical(prepared.review.source) || canonical(token.current_head) !== canonical(prepared.review.current_head) || token.catalog_revision !== prepared.preconditions.catalog_revision || !Object.prototype.hasOwnProperty.call(token, 'affected_entities') || !Array.isArray(token.blockers) || token.blockers.length) throw new Error('Recovery token is expired, mismatched or blocked; request a new review.');
}
async function finishRecovery(model, key) {
  const cap = capture(); recoveryContext(model, cap);
  const j = storage.journals[key];
  if (!j || j.operation !== 'OP-RECOVER-AS-NEW' || j.recovery_original_key !== model.key || ownerKey(j.owner) !== ownerKey(cap.owner)) throw new Error('Recovery journal/owner mismatch.');
  const status = (await read(`/commands/${enc(j.body.command_id)}`, { scope: j.body.scope, request_sha256: j.request_sha256 }, model.scope, cap)).data;
  if (status.command_id !== j.body.command_id || status.request_sha256 !== j.request_sha256) throw new Error('Recovery status does not match frozen command/hash.');
  j.state = status.status; j.status = status; persist();
  if (status.status !== 'committed' || status.effect_state !== 'committed' || !status.receipt_id) throw new Error(`Recovery command is ${status.status}; original remains unreplayed. Reconcile this recovery command, do not create another.`);
  const receipt = (await read(model.ppath + `/receipts/${enc(status.receipt_id)}`, {}, model.scope, cap)).data;
  if (receipt.receipt_id !== status.receipt_id || receipt.command_id !== j.body.command_id || receipt.request_sha256 !== j.request_sha256 || receipt.kind !== j.operation || receipt.effect_state !== 'committed' || scopeKey(receipt.scope) !== scopeKey(model.scope)) throw new Error('Recovery receipt does not match the separate frozen command.');
  const verifiedResult = j.result && await publicHash(j.result) === receipt.result_sha256 ? j.result : null;
  const refs = receipt.subject_refs || [], cid = refs.find(r => r.kind === 'composition')?.id || verifiedResult?.recovery_receipt?.composition_id, vid = refs.find(r => r.kind === 'version')?.id || verifiedResult?.recovery_receipt?.version_id;
  if (!cid || !vid || cid === cap.composition) throw new Error('Recovery blocked: receipt lacks exact separate composition/version references.');
  const version = (await read(model.ppath + `/compositions/${enc(cid)}`, { version_id: vid }, model.scope, cap)).data.version;
  recoveryPin(version);
  if (version?.composition_id !== cid || version?.version_id !== vid || version?.transaction_receipt_id !== receipt.receipt_id || (verifiedResult && canonical(version) !== canonical(verifiedResult.version))) throw new Error('Recovery version read-back did not prove exact receipt publication.');
  recoveryContext(model, cap);
  // Do not edit, delete, rekey or mark the source journal/draft applied.
  j.recovery_verified = { composition_id: cid, version_id: vid, receipt_id: receipt.receipt_id }; persist();
  updateLocal({ composition: cid, dialog: null, selected: [], frame: 0 });
  change({ journals: { ...storage.journals }, message: 'Recovered into a separate Composition. Original local draft/journal retained, unreplayed.' });
}
function RecoveryDialog({ model }) {
  const [prepared, setPrepared] = useState(null), [token, setToken] = useState(null), [reviewed, setReviewed] = useState(false), [confirmed, setConfirmed] = useState(false), [name, setName] = useState(''), [rebind, setRebind] = useState('[]');
  const supported = model.can('OP-RECOVERY-REVIEW') && model.can('OP-RECOVER-AS-NEW');
  const retained = Object.entries(storage.journals).filter(([, j]) => j.recovery_original_key === model.key && j.operation === 'OP-RECOVER-AS-NEW' && ownerKey(j.owner) === ownerKey(model.s.owner));
  const active = retained.find(([, j]) => j.state !== 'failed' || j.error?.effect_state !== 'none');
  const reset = () => { setPrepared(null); setToken(null); setReviewed(false); setConfirmed(false); };
  if (!supported) return h(Notice, {}, 'Recover as new Composition unavailable: backend does not advertise both authoritative recovery operations. Original retained; no client remapping or duplicate fallback.');
  return h('section', { className: 'card' }, h('h3', {}, 'Recover as a new Composition'), h('p', {}, 'Original local draft and command journal stay retained and unreplayed. Recovery uses the immutable original base, never the current graph as a guessed base.'),
    ...retained.map(([key, j]) => h('div', { key }, h('p', {}, `Separate recovery command ${j.body.command_id}: ${j.state}. Original unreplayed.`), h(B, { onClick: () => finishRecovery(model, key) }, 'Reconcile recovery receipt and exact new version'))),
    h('label', {}, 'Document value rebind decisions (JSON array of exact original document IDs or create_ref aliases; [] keeps historical pins)', h('textarea', { value: rebind, onChange: e => { setRebind(e.target.value); reset(); } })),
    h(B, { disabled: Boolean(active), onClick: async () => { reset(); setPrepared(await loadRecoveryReview(model, JSON.parse(rebind))); } }, 'Load original source, reconcile originals and prepare review'),
    prepared && h(SchemaRead, { value: { source: prepared.review.source, current_head: prepared.review.current_head, original_operations: prepared.review.transaction.operations, dependency_policy: prepared.review.transaction.dependency_policy, acknowledged_dependency_ids: prepared.review.transaction.acknowledged_dependency_ids, document_rebind_ids: prepared.review.transaction.document_rebind_ids, review_sha256: prepared.review_sha256 } }),
    h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: reviewed, disabled: !prepared, onChange: e => { setReviewed(e.target.checked); setToken(null); setConfirmed(false); } }), 'I reviewed source versus head, every retained operation, dependency acknowledgements and document rebind decisions.'),
    h(B, { disabled: !prepared || !reviewed || Boolean(active), onClick: async () => { await checkRecoveryFresh(model, prepared); const key = `${model.key}:recovery-review:${uid()}`; const r = await command(model.cpath + '/recovery-review', 'OP-RECOVERY-REVIEW', model.scope, prepared.preconditions, { review: prepared.review }, key); await checkRecoveryFresh(model, prepared, r); setToken(clone(r)); setConfirmed(false); } }, 'Request authoritative review token'),
    token && h(SchemaRead, { value: { affected_entities: token.affected_entities, blockers: token.blockers, review_sha256: token.review_sha256, expires_at: token.expires_at } }),
    h('label', {}, 'New Composition name', h('input', { value: name, maxLength: 120, onChange: e => { setName(e.target.value); setConfirmed(false); } })),
    h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: confirmed, disabled: !token, onChange: e => setConfirmed(e.target.checked) }), 'I reviewed the authoritative affected entities and confirm creation of a separate Composition; the original is not replayed.'),
    h(B, { primary: true, disabled: !token || !reviewed || !confirmed || !name.trim() || Boolean(active), onClick: async () => {
      await checkRecoveryFresh(model, prepared, token);
      const key = `${model.key}:recover-as-new:${uid()}`;
      // Freeze/persist metadata before network submission so disconnects can reconcile this exact command.
      const route = model.cpath + '/recover-as-new', operation = 'OP-RECOVER-AS-NEW';
      const input = { name: name.trim(), review: clone(prepared.review), review_token: token.review_token };
      const body = frozenCommand(model.scope, prepared.preconditions, input);
      const j = { route, operation, body, request_sha256: await requestHash(operation, route, model.scope, body.preconditions, body.input), state: 'prepared', owner: clone(prepared.cap.owner), result: null, recovery_original_key: model.key };
      recoveryContext(model, prepared.cap);
      if (Date.parse(token.expires_at) <= Date.now()) throw new Error('Recovery review expired before submission.');
      if (Object.values(storage.journals).some(old => old.recovery_original_key === model.key && (old.state !== 'failed' || old.error?.effect_state !== 'none'))) throw new Error('A separate recovery command already exists. Reconcile it instead of launching another.');
      storage.journals[key] = j;
      if (!persist()) throw new Error('Cannot persist separate recovery journal; no request sent.');
      await transmit(key, prepared.cap);
      await finishRecovery(model, key);
    } }, 'Confirm recover as new Composition'));
}
function ConflictDialog({ model }) {
  const d = model.draft, j = storage.journals[model.key];
  const recovery = useRead(model.cpath && model.cpath + '/recovery', { pending_command_ids: j ? [j.body.command_id] : [], known_version_id: d?.base.version_id || model.saved?.version_id }, model.scope, Boolean(model.cpath));
  const [discard, setDiscard] = useState(false), [reviewed, setReviewed] = useState(false);
  return h(Modal, { title: 'Local recovery and revision conflict' }, h('p', {}, 'Both sides remain retained. No automatic ripple, split or source replacement is replayed against another saved version.'), h(RecoveryDialog, { model }), h('div', { className: 'grid' }, h('div', { className: 'card' }, h('h3', {}, 'Local intention'), h(SchemaRead, { value: d ? { base: d.base, summary: d.summary, operations: d.operations } : j?.body.input || { state: 'No local changes' } })), h('div', { className: 'card' }, h('h3', {}, 'Current authoritative version'), h(Facts, { value: model.saved, fields: ['version_id', 'composition_revision', 'sha256'] }), h(SchemaRead, { value: recovery.data?.data?.allowed_recovery_actions || recovery.data?.data?.recovery_actions || [] }))), j && h(B, { onClick: () => reconcile(model.key, model.scope) }, 'Reconcile original request ID'), h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: reviewed, onChange: e => setReviewed(e.target.checked) }), 'I compared the intended fields/ranges and the current saved version.'), h(B, { disabled: hasRecoveryJournal(model.key) || !reviewed || !d || d.base.version_id !== model.saved?.version_id || Boolean(j && !['committed', 'failed'].includes(j.state)), onClick: () => { d.recovered = false; d.manual = false; persist(); change({ dialog: null, drafts: { ...storage.drafts } }); return saveDraft(model); } }, 'Apply reviewed local change · matching base only'), d && d.base.version_id !== model.saved?.version_id && h('p', {}, 'The base changed. Re-enter reviewed edits against current values or export local recovery; this client will not fabricate a safe rebase.'), h(B, { onClick: async () => { const ok = await context.os.writeClipboard(canonical({ schema: 'motion-studio-local-recovery.v1', scope: model.scope, composition_id: model.s.composition, draft: d || null, journal: j || null })); if (!ok) throw new Error('Recovery clipboard is unavailable. Local journal remains retained.'); change({ message: 'Recovery data copied. It contains scoped edit intentions, not media bytes or credentials.' }); } }, 'Copy local recovery data'), h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: discard, onChange: e => setDiscard(e.target.checked) }), 'Discard only this local unsent recovery; keep current backend version.'), h(B, { disabled: hasRecoveryJournal(model.key) || !discard || Boolean(j && !['committed', 'failed', 'prepared'].includes(j.state)), onClick: () => { delete storage.drafts[model.key]; if (j?.state === 'prepared') delete storage.journals[model.key]; persist(); change({ drafts: { ...storage.drafts }, journals: { ...storage.journals }, dialog: null, message: 'Local unsent changes discarded. Backend and source media unchanged.' }); } }, 'Keep current saved version'));
}
function Settings({ model }) {
  const settings = useRead('/settings', {}, model.baseScope, Boolean(model.baseScope));
  const [tab, setTab] = useState('Capabilities');
  const large = Boolean(model.s.largeControls), setLarge = value => updateLocal({ largeControls: value });
  const [preferences, setPreferences] = useState(null);
  const data = model.capabilities.data?.data;
  const options = data?.items || data?.capabilities || [];
  return h('div', { className: large ? 'body large' : 'body' }, h('div', { className: 'row' }, ...['Capabilities', 'Defaults', 'Storage & playback', 'Accessibility'].map(t => h(B, { key: t, onClick: () => setTab(t), 'aria-pressed': tab === t }, t))), tab === 'Capabilities' ? h('div', { className: 'list' }, h('p', {}, 'Availability, permission, support and exercised evidence are separate. Refresh is passive and never installs or launches tools.'), h(B, { onClick: () => model.capabilities.refetch() }, 'Refresh readiness'), h(QueryState, { query: model.capabilities, emptyText: 'No capability facts advertised' }, options.length > 0 && options.map((c, i) => h('section', { key: c.id || i, className: 'card' }, h('h3', {}, c.label || c.id || c.operation), h(SchemaRead, { value: { binding: c.binding, execution_host: c.execution_host, support: c.support, availability: c.availability, permission: c.permission, observed_at: c.observed_at, exercised_at: c.exercised_at, reason: c.reason || null } }), h(B, { disabled: !model.version, onClick: () => change({ dialog: 'production-action', productionIntent: 'capability_setup', selectedOperation: c.operation_schema_ref?.id }) }, 'Review compatible setup handoff…'))))) : tab === 'Defaults' ? h(QueryState, { query: settings }, settings.data && h('div', { className: 'list' }, h(SchemaFields, { schema: model.boot.data?.data?.settings_schema, value: preferences || settings.data.data.preferences, onChange: setPreferences }), h(B, { disabled: !preferences, onClick: async () => { await command('/settings', 'OP-SETTINGS-SAVE', model.baseScope, { settings_revision: settings.data.data.settings_revision }, { preferences }, `${scopeKey(model.baseScope)}:settings`); setPreferences(null); await settings.refetch(); } }, 'Save defaults · existing edits unchanged'), h('p', {}, 'Credentials stay in native Hermes credential settings. This form never accepts secrets.'))) : tab === 'Storage & playback' ? h('div', { className: 'list' }, h(SchemaRead, { value: model.boot.data?.data?.transport_capabilities || {} }), h('p', {}, 'Edits use the scoped local journal. Media cache is separate. Missing thumbnails and local cache do not imply missing backend source.'), h(B, { disabled: true, title: 'No public media cache capability is installed' }, 'Review local media cache clear…'), h('p', { className: 'muted' }, 'Binary uploads require a public authenticated chunk transport; a client file path is never sent as a server path.')) : h('div', { className: 'list' }, h(B, { 'aria-pressed': model.s.table, onClick: () => updateLocal({ table: !model.s.table }) }, 'Timeline table alternative'), h(B, { 'aria-pressed': large, onClick: () => setLarge(!large) }, 'Use larger controls'), h('p', {}, 'Reduced motion follows system preference. Native numeric inputs offer keyboard and touch editing. Studio shortcuts apply only within focused Studio surfaces, never inside chat or editable text.')));
}
function CompositionSettings({ model }) {
  const [name, setName] = useState(model.summary?.name || '');
  return h(Modal, { title: 'Composition settings' }, h(Facts, { value: model.summary, fields: ['composition_id', 'native_project_id', 'composition_revision', 'metadata_revision'] }), h('label', {}, 'Composition display name', h('input', { value: name, maxLength: 120, onChange: e => setName(e.target.value) })), h(B, { disabled: !name.trim(), onClick: () => command(model.cpath + '/metadata', 'OP-COMPOSITION-METADATA', model.scope, { metadata_revision: model.summary.metadata_revision }, { name }) }, 'Rename composition only'), h(Facts, { value: model.version.format, fields: ['width', 'height', 'fps', 'sample_rate', 'channels', 'duration_frames'] }), h('p', {}, 'Changing canvas or fps is an explicit typed conform. Review every affected placement and choose a retiming policy; the exact old saved version remains retained.'), h(B, { disabled: Boolean(model.draft), onClick: () => change({ dialog: 'format' }) }, 'Review canvas / frame-rate conform…'), h('div', { className: 'row' }, h(B, { onClick: () => change({ dialog: 'conflict' }) }, 'Saved version recovery…'), h(B, { onClick: () => change({ dialog: 'duplicate' }) }, 'Duplicate saved version…'), h(B, { onClick: () => change({ dialog: 'archive' }) }, 'Archive composition…')));
}
function FormatDialog({ model }) {
  const f = model.saved.format;
  const [width, setWidth] = useState(String(f.width)), [height, setHeight] = useState(String(f.height)), [num, setNum] = useState(String(f.fps.num)), [den, setDen] = useState(String(f.fps.den)), [policy, setPolicy] = useState('preserve_frames'), [reviewed, setReviewed] = useState(false);
  return h(Modal, { title: 'Review format conform' }, h('p', { className: 'mono' }, `Retained recovery version: ${model.saved.version_id}`), h('p', {}, 'Canvas, frame-rate and output-time changes affect every listed placement, cue, keyframe and dependent review. Source mappings and renderer constraints remain authoritative; unsupported conform is rejected atomically.'), h('div', { className: 'grid' }, h(NumberField, { label: 'Canvas width', unit: 'pixels', value: width, min: 1, onChange: setWidth }), h(NumberField, { label: 'Canvas height', unit: 'pixels', value: height, min: 1, onChange: setHeight }), h(NumberField, { label: 'FPS numerator', unit: 'rational', value: num, min: 1, onChange: setNum }), h(NumberField, { label: 'FPS denominator', unit: 'rational', value: den, min: 1, onChange: setDen })), h('label', {}, 'Explicit timing policy', h('select', { value: policy, onChange: e => setPolicy(e.target.value) }, h('option', { value: 'preserve_frames' }, 'Preserve output frame indexes; wall-clock timing may change'), h('option', { value: 'preserve_time_nearest_even' }, 'Preserve wall-clock time; nearest-even frame conversion'))), h('ul', {}, ...model.saved.clips.map(c => h('li', { key: c.clip_id }, `${c.clip_id}: [${c.start_frame}, ${c.end_frame})`)), ...model.saved.captions.map(c => h('li', { key: c.cue_id }, `${c.cue_id}: [${c.start_frame}, ${c.end_frame})`))), h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: reviewed, onChange: e => setReviewed(e.target.checked) }), 'I reviewed the complete affected Composition and explicit retiming policy.'), h(B, { primary: true, disabled: !reviewed || Boolean(model.draft), onClick: () => { stage(model, [{ op: 'settings.set', format: { ...f, width: safeInteger(width, 1), height: safeInteger(height, 1), fps: { num: safeInteger(num, 1), den: safeInteger(den, 1) } }, retime_policy: policy, color_profile_ref: model.saved.settings.color_profile_ref || null, output_profile_refs: model.saved.settings.output_profile_refs || [], font_fallback_policy: model.saved.settings.font_fallback_policy || 'reject' }], 'Apply reviewed Composition conform'); change({ dialog: null }); } }, 'Apply atomically · retain old immutable version'));
}
function CompositionLifecycle({ model, archive = false }) {
  const [name, setName] = useState(`${model.summary?.name || 'Composition'} copy`), [acknowledged, setAcknowledged] = useState(false);
  return h(Modal, { title: archive ? 'Archive composition' : 'Duplicate saved composition' }, h('p', {}, archive ? 'Archiving hides this Composition from the active catalog. Native Project identity, source media and running jobs are retained.' : 'Copies the exact saved version into the same native Project. Local unsynchronized edits and private authority receipts are not copied.'), archive ? h('label', { className: 'row' }, h('input', { type: 'checkbox', checked: acknowledged, onChange: e => setAcknowledged(e.target.checked) }), 'I understand existing jobs may continue for the archived Composition.') : h('label', {}, 'New Composition name', h('input', { value: name, onChange: e => setName(e.target.value), maxLength: 120 })), h(B, { primary: true, disabled: archive ? !acknowledged || Boolean(model.draft) : !name.trim() || Boolean(model.draft), onClick: async () => { const r = archive ? await command(model.cpath + '/archive', 'OP-COMPOSITION-ARCHIVE', model.scope, { metadata_revision: model.summary.metadata_revision, catalog_revision: model.catalog.data.data.catalog_revision }, { archived: true, acknowledge_running_jobs: acknowledged }, `${scopeKey(model.scope)}:catalog`) : await command(model.cpath + '/duplicate', 'OP-COMPOSITION-DUPLICATE', model.scope, { ...model.cas, catalog_revision: model.catalog.data.data.catalog_revision }, { source_version_id: model.saved.version_id, name, include_rights_assertions: false }, `${scopeKey(model.scope)}:catalog`); const id = r.composition?.composition_id || r.summary?.composition_id || r.composition_id; updateLocal({ composition: archive ? null : id || model.s.composition, selected: [], dialog: null }); } }, archive ? 'Archive · retain source and work' : 'Duplicate exact saved version'));
}
function Acceptance({ model }) {
  const doc = model.s.document;
  return h(Modal, { title: 'Request creative acceptance' }, h('p', {}, 'Acceptance binds the exact document closure and becomes stale when its dependencies change. It does not grant provider spend, likeness use, publication or execution permission.'), h(Facts, { value: doc, fields: ['kind', 'document_id', 'document_version_id', 'sha256'] }), h(B, { disabled: Boolean(model.draft), onClick: () => command(model.cpath + '/authority-requests', 'OP-AUTHORITY-REQUEST', model.scope, model.cas, { kind: 'creative_acceptance', subject_refs: [doc], subject_sha256: doc.sha256, purpose: 'Review exact saved creative document', limits: { operation_schema_ref: null, asset_ids: [], destination_ids: [], expires_at: null }, reason: 'User requested review through native Studio' }) }, 'Open trusted acceptance request'));
}
function AddAssets({ model }) { return h(Modal, { title: 'Add assets' }, h('p', {}, 'Use the Assets → Project files browser to scan authorized roots and import immutable copies.'), h(B, { onClick: () => { updateLocal({ tab: 'Assets' }); change({ dialog: null }); } }, 'Browse Project files'), h('h3', {}, 'Choose local file / resume upload'), h('p', {}, 'Unavailable: this SDK has no public authenticated chunk transport with scope, digest and content-range metadata. Native path pickers are not file upload.'), h('h3', {}, 'Public source acquisition'), h('p', {}, 'Approved provider and resource ID only. No arbitrary URL, cookies, playlist or hidden transfer.'), h(B, { disabled: !model.version, onClick: () => change({ dialog: 'production-action', productionIntent: 'acquire_media' }) }, 'Choose advertised bounded acquisition route…'));
}
function Dialogs({ model }) {
  switch (model.s.dialog) {
    case 'new': return h(NewComposition, { model });
    case 'placement': return h(EditPlacement, { model });
    case 'delete': return h(DeleteDialog, { model });
    case 'track': return h(TrackDialog, { model });
    case 'asset-details': return h(AssetDetails, { model });
    case 'insert': return h(InsertDialog, { model });
    case 'add-assets': return h(AddAssets, { model });
    case 'caption': return h(CaptionDialog, { model });
    case 'caption-import': return h(CaptionImport, { model });
    case 'layer': return h(LayerEffectDialog, { model });
    case 'effect': return h(LayerEffectDialog, { model, effect: true });
    case 'production-action': return h(HandoffDialog, { model });
    case 'proposal': return h(ProposalDialog, { model });
    case 'job': return h(JobDialog, { model });
    case 'cancel-job': return h(CancelJob, { model });
    case 'export': return h(ExportDialog, { model });
    case 'review': return h(ReviewDialog, { model });
    case 'delivery': return h(DeliveryDialog, { model });
    case 'conflict': return h(ConflictDialog, { model });
    case 'composition-settings': return h(CompositionSettings, { model });
    case 'format': return h(FormatDialog, { model });
    case 'duplicate': return h(CompositionLifecycle, { model });
    case 'archive': return h(CompositionLifecycle, { model, archive: true });
    case 'acceptance': return h(Acceptance, { model });
    case 'settings': return h(Modal, { title: 'Studio Settings' }, h(Settings, { model }));
    case 'clear-cache': return h(Modal, { title: 'Clear local playback cache?' }, h('p', {}, 'Only media bytes for this scope are cleared. Pending edit journals and backend assets are retained.'), h(B, { disabled: true, title: 'No public media cache capability is installed' }, 'Clear this scope’s local media cache'));
    default: return null;
  }
}
function DockBody({ model }) {
  const s = model.s;
  const component = { Preview: Monitor, Assets, Layers, Inspector, Production, Jobs }[s.tab];
  return h('section', { className: s.largeControls ? 'ms studio-dock large' : 'ms studio-dock', 'aria-label': 'Motion Studio dock' }, h('style', {}, CSS), h(Header, { model, focus: s.focus }), h(SaveControls, { model }), h('div', { className: 'tabs', role: 'tablist', 'aria-label': 'Studio workspace', onKeyDown: e => { if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return; e.preventDefault(); const n = e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : (TABS.indexOf(s.tab) + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length; updateLocal({ tab: TABS[n] }); e.currentTarget.children[n]?.focus(); } }, ...TABS.map(tab => h('button', { type: 'button', key: tab, role: 'tab', 'aria-selected': s.tab === tab, 'aria-controls': `motion-studio-panel-${tab}`, tabIndex: s.tab === tab ? 0 : -1, onClick: () => updateLocal({ tab }) }, tab))), h('div', { className: 'scroll', role: 'tabpanel', id: `motion-studio-panel-${s.tab}`, 'aria-label': s.tab, tabIndex: 0 }, !s.project && s.tab !== 'Jobs' ? h(CompositionEmpty, { model }) : component ? s.tab === 'Preview' && !model.version ? h(CompositionEmpty, { model }) : h(component, { model }) : null), h(Dialogs, { model }));
}
export function StudioDock() { const model = useModel(); return h(DockBody, { model }); }
export function StudioTimeline() { const model = useModel(); return h('section', { className: 'ms timeline-pane', 'aria-label': 'Motion Studio timeline' }, h('style', {}, CSS), h(TimelineContent, { model })); }
export function StudioFocus() {
  const model = useModel();
  useEffect(() => { change({ focus: true }); return () => change({ focus: false }); }, []);
  return h('section', { className: 'ms', 'aria-label': 'Studio focus workspace', onKeyDown: e => { if (e.key === 'Escape' && !e.target.closest('dialog,[popover]')) { e.preventDefault(); leaveFocus(); } } }, h('style', {}, CSS), h('div', { className: 'focusgrid' }, h(DockBody, { model }), h('section', { className: 'ms timeline-pane' }, h(TimelineContent, { model }))));
}
function StudioSettingsPage() { const model = useModel(); return h('section', { className: 'ms' }, h('style', {}, CSS), h(Settings, { model })); }

export default {
  id: 'motion-studio', name: 'Motion Studio', description: 'Native composition editing, production and exact encoded review beside the Hermes conversation.', defaultEnabled: false,
  register(ctx) {
    backendBuildIdentity = null;
    context = ctx; alive = true;
    const loaded = ctx.storage.get(ROOT_KEY, { drafts: {}, journals: {}, scopes: {} });
    if (!loaded || typeof loaded !== 'object' || !loaded.drafts || !loaded.journals || !loaded.scopes) {
      storage = { drafts: {}, journals: {}, scopes: {}, corruptRecovery: loaded };
      change({ storageError: 'Local recovery journal is unreadable. It has been retained; editing is paused.' });
    } else {
      storage = clone(loaded);
      for (const d of Object.values(storage.drafts)) d.recovered = true;
      for (const j of Object.values(storage.journals)) if (j.state === 'sending') j.state = 'unknown';
    }
    change({ drafts: storage.drafts, journals: storage.journals });
    transitionOwner();
    const offOwner = host.state.focusedSessionOwner.subscribe(transitionOwner);
    let previousTransport = ownerKey(transportOwner());
    const observeTransport = () => { const next = ownerKey(transportOwner()); if (previousTransport === next) return; previousTransport = next; const s = studioState.get(); cancelAutosave?.(); change({ epoch: s.epoch + 1, message: transportReady(s.owner) ? 'Native transport restored. Retained commands will be reconciled before retry.' : 'Ambient connection changed. Edits are frozen until the focused owner matches the active transport.' }); queryClient.cancelQueries({ queryKey: ['motion-studio'] }); };
    const offProfile = host.state.profile.subscribe(observeTransport);
    const offConnection = host.state.connectionId.subscribe(observeTransport);
    ctx.registerMany([
      { id: 'studio', title: 'Studio', area: PANES_AREA, order: 80, data: { placement: 'right', dock: { pane: 'workspace', pos: 'right' }, width: '640px', minWidth: '360px', maxWidth: '900px', collapsible: true, lifecycleKeepAlive: true }, render: StudioDock },
      { id: 'timeline', title: 'Timeline', area: PANES_AREA, order: 81, data: { placement: 'bottom', dock: { pane: 'workspace', pos: 'bottom' }, height: 'clamp(160px, 24vh, 280px)', minHeight: 'min(120px, 24vh)', maxHeight: '40vh', lifecycleKeepAlive: true }, render: StudioTimeline },
      { id: 'focus', area: ROUTES_AREA, data: { path: '/motion-studio' }, render: StudioFocus },
      { id: 'focus-command', area: PALETTE_AREA, data: { id: 'motion-studio.focus', label: 'Motion Studio: Focus workspace', keywords: ['studio', 'timeline', 'composition'], run: enterFocus } },
      { id: 'return-command', area: PALETTE_AREA, data: { id: 'motion-studio.return', label: 'Motion Studio: Return to chat', run: leaveFocus } },
      { id: 'focus-keybind', area: KEYBINDS_AREA, data: { id: 'motion-studio.focus', label: 'Focus Motion Studio', defaults: ['mod+alt+m'], run: enterFocus } }
    ]);
    ctx.registerSettingsPage?.({ id: 'studio-settings', title: 'Motion Studio', render: StudioSettingsPage });
    ctx.onDispose(() => { alive = false; cancelAutosave?.(); offOwner(); offProfile(); offConnection(); queryClient.cancelQueries({ queryKey: ['motion-studio'] }); context = null; change({ epoch: studioState.get().epoch + 1 }); });
  }
};
