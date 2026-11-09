import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8');
const prelude = `const atom = value => ({ get: () => value, set: next => { value = next; } });
const host = {}, useValue = a => a.get(), useQuery = () => ({}), queryClient = {};
const PANES_AREA = '', ROUTES_AREA = '', PALETTE_AREA = '', KEYBINDS_AREA = '';
const h = (type, props, ...children) => ({ type, props, children });
const useEffect = () => {}, useRef = current => ({ current }), useState = value => [value, () => {}];\n`;
const ui = await import('data:text/javascript;base64,' + Buffer.from(prelude + source.replace(/^import .*$/gm, '')).toString('base64'));

test('frontend fingerprint is stable across host import rewrites, but not code changes', async () => {
  assert.equal(typeof ui.frontendSourceFingerprint, 'function');
  const original = "import { host } from '@hermes/plugin-sdk';\nimport { useState } from 'react';\nconst x = 1;\n";
  const rewritten = "import { host } from 'blob:host-sdk';\nimport { useState } from 'blob:host-react';\nconst x = 1;\n";
  const expected = createHash('sha256').update('import { host } from "<host-import>";\nimport { useState } from "<host-import>";\nconst x = 1;\n').digest('hex');
  assert.equal(await ui.frontendSourceFingerprint(original), expected);
  assert.equal(await ui.frontendSourceFingerprint(rewritten.replaceAll('\n', '\r\n')), expected);
  assert.notEqual(await ui.frontendSourceFingerprint(original.replace('x = 1', 'x = 2')), expected);
  assert.notEqual(await ui.frontendSourceFingerprint(original.replace('{ host }', '{ other }')), expected);
});

test('build parity distinguishes current, stale and unverified instead of inventing success', () => {
  const matching = { frontend_hash_algorithm: 'motion/import-normalized-sha256/v1', frontend_source_sha256: 'a'.repeat(64) };
  assert.equal(typeof ui.buildParity, 'function');
  assert.equal(ui.buildParity(matching, { status: 'ready', sha256: 'a'.repeat(64) }).status, 'current');
  assert.equal(ui.buildParity(matching, { status: 'ready', sha256: 'b'.repeat(64) }).status, 'stale');
  assert.equal(ui.buildParity(null, { status: 'ready', sha256: 'a'.repeat(64) }).status, 'unverified');
  assert.equal(ui.buildParity(matching, { status: 'pending' }).status, 'checking');
  assert.equal(ui.buildParity({ ...matching, frontend_hash_algorithm: 'future' }, { status: 'ready', sha256: 'a'.repeat(64) }).status, 'unverified');
});
