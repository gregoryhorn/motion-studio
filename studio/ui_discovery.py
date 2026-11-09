"""Finite metadata-only discovery of admitted native Project folders.

Invoked by authenticated UI commands, never at import or in a daemon. Directory
snapshots use the existing broker's 10,000-entry bound; each command consumes at
most 200 entries / eight listing pages. No source bytes, hashes, parsers, native
private-project registries, media probes or subprocesses are opened here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re
import secrets

from .contracts import ContractError
from .ui_files import MEDIA_EXTENSIONS

MAX_INDEX = 10000
TTL = 600
EXCLUDED = frozenset({
    'node_modules', 'cache', 'caches', '__pycache__', 'venv', 'env',
    'site-packages', 'secrets', 'credentials', 'private', 'build', 'dist',
    'coverage', 'tmp', 'temp', 'vendor',
})
SENSITIVE = re.compile(r'(^|[._ -])(secret|secrets|credential|credentials|password|passwd|token|tokens|api[_-]?key|private[_-]?key)([._ -]|$)', re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def allowed(relative):
    parts = PurePosixPath(relative).parts
    return bool(parts) and not PurePosixPath(relative).is_absolute() and all(
        p not in ('.', '..') and not p.startswith('.') and p.casefold() not in EXCLUDED
        and not SENSITIVE.search(p) and p.casefold() not in ('id_rsa', 'id_ed25519')
        for p in parts)


def bounded(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractError('INVALID_ARGUMENT', 'Discovery limits are outside their finite bounds.')
    return value


class UIDiscovery:
    def __init__(self, media):
        self.media = media

    @staticmethod
    def identity(context):
        # A second authenticated principal cannot continue another person's run.
        return 'discovery_' + digest([context['scope'], context['principal']])

    def roots(self, context):
        items = self.media.broker.roots(context['scope']['native_project_id'])['items']
        return {r['root_id']: r for r in items}

    @staticmethod
    def revisions(roots):
        return [{'root_id': k, 'revision': r['root_revision']} for k, r in sorted(roots.items())]

    def load(self, db, context):
        row = db.execute("SELECT value FROM records WHERE kind='discovery' AND id=?",
                         (self.identity(context),)).fetchone()
        return json.loads(row['value']) if row else None

    def status(self, db, fs, context, query, pre):
        state = self.load(db, context)
        roots = self.roots(context)
        if state is None:
            return dict(items=[], state='not_started', complete=False, next_cursor=None,
                        next_page_cursor=None, partial_causes=[], root_revisions=self.revisions(roots),
                        indexed_count=0, scan_id=None)
        if state['root_revisions'] != self.revisions(roots):
            return dict(items=[], state='stale', complete=False, next_cursor=None,
                        next_page_cursor=None, partial_causes=['ROOT_CHANGED'],
                        root_revisions=self.revisions(roots), indexed_count=0, scan_id=state['scan_id'])
        offset = 0
        if 'cursor' in query:
            prefix = 'page_' + digest([state['scan_id'], state['revision']])[:24] + '_'
            cursor = query['cursor']
            if (not isinstance(cursor, str) or not cursor.startswith(prefix)
                    or re.fullmatch(r'[0-9]{1,5}', cursor[len(prefix):]) is None
                    or int(cursor[len(prefix):]) > MAX_INDEX):
                raise ContractError('CURSOR_EXPIRED', 'Discovery page changed. Refresh its status.')
            offset = bounded(int(cursor[len(prefix):]), 0, MAX_INDEX)
        limit = bounded(query.get('limit', 100), 1, 200)
        return self.public(state, offset, limit)

    def public(self, state, offset=0, limit=200):
        values = list(state['files'].values())
        items = values[offset:offset + limit]
        # A retained listing is evidence of observation, not a durable capability.
        if state['expires'] <= self.media.clock():
            items = [{**r, 'node_id': None, 'importable': False,
                      'reason': 'NODE_EXPIRED'} for r in items]
        next_page = None
        if offset + limit < len(values):
            next_page = 'page_' + digest([state['scan_id'], state['revision']])[:24] + '_' + str(offset + limit)
        return dict(items=items, state=state['state'], complete=state['complete'],
                    next_cursor=state['next_cursor'] if state['expires'] > self.media.clock() else None,
                    next_page_cursor=next_page, partial_causes=state['partial_causes'],
                    root_revisions=state['root_revisions'], indexed_count=len(values),
                    scan_id=state['scan_id'], observed_entries=state['observed_entries'],
                    source='native_project_files', qualification='not_qualified')

    def scan(self, db, fs, context, input, pre):
        max_entries = bounded(input['max_entries'], 1, 200)
        max_pages = bounded(input['max_directories'], 1, 8)
        roots = self.roots(context)
        revisions = self.revisions(roots)
        supplied = pre.get('root_revisions')
        if not isinstance(supplied, list) or any(not isinstance(r, dict) or set(r) != {'root_id', 'revision'}
                                                for r in supplied):
            raise ContractError('INVALID_ARGUMENT', 'Exact admitted root revisions are required.')
        if sorted(supplied, key=lambda r: str(r['root_id'])) != revisions:
            raise ContractError('ROOT_CHANGED', 'Refresh admitted Project roots before discovery.')
        cursor = input.get('cursor')
        if cursor is not None:
            state = self.load(db, context)
            if (state is None or cursor != state['next_cursor'] or state['expires'] <= self.media.clock()
                    or state['root_revisions'] != revisions):
                raise ContractError('CURSOR_EXPIRED', 'Discovery continuation expired or changed. Start a fresh scan.')
        else:
            unavailable = [r for r in roots.values() if not r['available']]
            state = dict(scan_id='discovery_scan_' + secrets.token_hex(16), revision=0,
                         root_revisions=revisions, queue=[dict(root_id=k, node_id=None, cursor=None)
                             for k, r in sorted(roots.items()) if r['available']],
                         files={}, partial_causes=['ROOT_UNAVAILABLE'] if unavailable else [],
                         observed_entries=0, expires=self.media.clock() + TTL,
                         next_cursor=None, state='running', complete=False)
        consumed = pages = 0
        native = context['scope']['native_project_id']
        while state['queue'] and consumed < max_entries and pages < max_pages:
            current = state['queue'][0]
            root = roots[current['root_id']]
            try:
                page = self.media.broker.browse(native, current['root_id'],
                    expected_root_revision=root['root_revision'], parent_node_id=current['node_id'],
                    cursor=current['cursor'], kind_filter='all',
                    limit=min(max_entries - consumed, MAX_INDEX * 4 - state['observed_entries']))
            except (ContractError, OSError) as exc:
                reason = exc.code if isinstance(exc, ContractError) else 'SOURCE_UNAVAILABLE'
                state['partial_causes'].append(reason)
                state['queue'].pop(0)
                pages += 1
                continue
            pages += 1
            consumed += len(page['items'])
            state['observed_entries'] += len(page['items'])
            for item in page['items']:
                relative = item['relative_display_path']
                if not allowed(relative):
                    continue
                if item['kind'] == 'directory':
                    if len(state['queue']) >= MAX_INDEX:
                        state['partial_causes'].append('DIRECTORY_LIMIT')
                    else:
                        state['queue'].append(dict(root_id=current['root_id'], node_id=item['node_id'], cursor=None))
                    continue
                if item['kind'] != 'file' or PurePosixPath(item['name']).suffix.lower() not in MEDIA_EXTENSIONS:
                    continue
                key = digest([context['scope'], current['root_id'], relative])
                if len(state['files']) >= MAX_INDEX and key not in state['files']:
                    state['partial_causes'].append('INDEX_LIMIT')
                    continue
                state['files'][key] = dict(discovery_id='file_' + digest([key, item['mtime_token']]),
                    root_id=current['root_id'], root_revision=root['root_revision'], node_id=item['node_id'],
                    display_name=item['name'], relative_display_path=relative, byte_length=item['byte_length'],
                    mtime_token=item['mtime_token'], kind='file', readiness='discovered', admission='not_checked',
                    qualification='not_qualified', importable=True, reason=None)
            if page.get('next_cursor'):
                current['cursor'] = page['next_cursor']
            else:
                state['queue'].pop(0)
            if state['observed_entries'] >= MAX_INDEX * 4:
                state['partial_causes'].append('ENTRY_LIMIT')
                state['queue'] = []
        state['partial_causes'] = sorted(set(state['partial_causes']))
        state['revision'] += 1
        state['complete'] = not state['queue'] and not state['partial_causes']
        state['state'] = 'complete' if state['complete'] else 'paused' if state['queue'] else 'partial'
        state['next_cursor'] = 'discovery_cursor_' + secrets.token_hex(16) if state['queue'] else None
        self.media.save(db, 'discovery', self.identity(context), state)
        return self.public(state)
