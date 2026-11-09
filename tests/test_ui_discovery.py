"""Finite, metadata-only Project discovery behavior and continuation boundaries."""
import sqlite3
from types import SimpleNamespace

import pytest

from studio.contracts import ContractError
from studio.ui_discovery import UIDiscovery, digest
from studio.ui_files import UIFileBroker
from studio.ui_media import UIMedia


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    records = [{'id': 'native', 'folders': [{'path': str(source)}]}]
    now = [1000]
    broker = UIFileBroker(tmp_path / 'broker', lambda: records, clock=lambda: now[0])
    discovery = UIDiscovery(SimpleNamespace(broker=broker, clock=lambda: now[0], save=UIMedia.save))
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE records(kind TEXT,id TEXT,value TEXT,PRIMARY KEY(kind,id))')
    context = {'scope': {'native_project_id': 'native', 'connection_id': 'connection'},
               'principal': 'user'}
    yield discovery, db, context, source, now, records
    db.close()


def scan(setup, cursor=None, entries=200, directories=8):
    discovery, db, context, *_ = setup
    value = {'max_entries': entries, 'max_directories': directories}
    if cursor is not None:
        value['cursor'] = cursor
    return discovery.scan(db, None, context, value,
        {'root_revisions': discovery.revisions(discovery.roots(context))})


def status(setup, **query):
    discovery, db, context, *_ = setup
    return discovery.status(db, None, context, query, {})


def test_recursive_metadata_scan_filters_and_continues(setup, monkeypatch):
    discovery, db, context, source, *_ = setup
    for directory in ('nested', '.hidden', 'credentials', 'node_modules'):
        (source / directory).mkdir()
        (source / directory / 'image.png').write_bytes(b'inert')
    for name in ('clip.mp4', 'secret.png', 'readme.txt'):
        (source / name).write_bytes(b'inert')
    (source / 'linked.png').symlink_to(source / 'nested/image.png')
    monkeypatch.setattr(discovery.media.broker, 'open_node', lambda *a, **k: pytest.fail('source bytes opened'))
    result = scan(setup, entries=2, directories=1)
    while True:
        assert result['observed_entries'] <= 10
        if not result['next_cursor']:
            break
        previous = result['next_cursor']
        result = scan(setup, previous, entries=2, directories=1)
        with pytest.raises(ContractError, match='continuation'):
            scan(setup, previous)
    assert result['complete'] is True
    assert {r['relative_display_path'] for r in result['items']} == {'clip.mp4', 'nested/image.png'}
    assert all(r['readiness'] == 'discovered' and r['admission'] == 'not_checked' for r in result['items'])
    monkeypatch.setattr(discovery.media.broker, 'browse', lambda *a, **k: pytest.fail('status rescanned'))
    first = status(setup, limit=1)
    second = status(setup, limit=1, cursor=first['next_page_cursor'])
    assert first['items'][0]['discovery_id'] != second['items'][0]['discovery_id']
    assert second['next_page_cursor'] is None


@pytest.mark.parametrize('suffix', ['\u00b2', '9' * 5000, '10001'],
                         ids=['nondecimal-digit', 'oversized-integer', 'out-of-range'])
def test_malformed_page_cursor_is_contract_error(setup, suffix):
    scan(setup)
    discovery, db, context, *_ = setup
    state = discovery.load(db, context)
    cursor = 'page_' + digest([state['scan_id'], state['revision']])[:24] + '_' + suffix
    with pytest.raises(ContractError) as exc:
        status(setup, cursor=cursor)
    assert exc.value.code == 'CURSOR_EXPIRED'


def test_total_entry_limit_is_not_exceeded_on_continuation(setup):
    discovery, db, context, source, *_ = setup
    for n in range(4):
        (source / f'{n}.png').write_bytes(b'inert')
    first = scan(setup, entries=1)
    state = discovery.load(db, context)
    state['observed_entries'] = 39999
    discovery.media.save(db, 'discovery', discovery.identity(context), state)
    result = scan(setup, first['next_cursor'])
    assert result['observed_entries'] == 40000
    assert result['partial_causes'] == ['ENTRY_LIMIT']
    assert result['state'] == 'partial'
    assert not result['complete'] and result['next_cursor'] is None


def test_principal_scope_root_and_expiry_boundaries(setup):
    discovery, db, context, source, now, records = setup
    for name in ('a.png', 'b.png'):
        (source / name).write_bytes(b'inert')
    first = scan(setup, entries=1)
    for foreign in ({**context, 'principal': 'other'},
                    {**context, 'scope': {**context['scope'], 'connection_id': 'other'}}):
        assert discovery.status(db, None, foreign, {}, {})['state'] == 'not_started'
        with pytest.raises(ContractError) as exc:
            discovery.scan(db, None, foreign, {'cursor': first['next_cursor'], 'max_entries': 1,
                'max_directories': 1}, {'root_revisions': discovery.revisions(discovery.roots(foreign))})
        assert exc.value.code == 'CURSOR_EXPIRED'
    now[0] += 600
    expired = status(setup)
    assert expired['items'][0]['node_id'] is None
    assert not expired['items'][0]['importable']
    assert expired['next_cursor'] is None
    with pytest.raises(ContractError) as exc:
        scan(setup, first['next_cursor'])
    assert exc.value.code == 'CURSOR_EXPIRED'
    records[0]['folders'][0]['label'] = 'changed'
    stale = status(setup)
    assert stale['state'] == 'stale' and stale['items'] == []


def test_unavailable_root_is_explicitly_partial(setup):
    *_, records = setup
    records[0]['folders'].append({'path': '/nonexistent-motion-discovery-test-root'})
    result = scan(setup)
    assert result['state'] == 'partial'
    assert result['partial_causes'] == ['ROOT_UNAVAILABLE']
    assert result['complete'] is False


@pytest.mark.parametrize('entries,directories', [(0, 1), (201, 1), (True, 1), (1, 0), (1, 9)])
def test_command_limits_are_strict(setup, entries, directories):
    with pytest.raises(ContractError) as exc:
        scan(setup, entries=entries, directories=directories)
    assert exc.value.code == 'INVALID_ARGUMENT'


def test_listing_page_budget_pauses_and_status_page_expires_after_continuation(setup, monkeypatch):
    discovery, db, context, source, *_ = setup
    (source / 'nested').mkdir()
    (source / 'nested/c.png').write_bytes(b'inert')
    for name in ('a.png', 'b.png'):
        (source / name).write_bytes(b'inert')
    calls = []
    browse = discovery.media.broker.browse
    def tracked(*args, **kwargs):
        calls.append(kwargs)
        return browse(*args, **kwargs)
    monkeypatch.setattr(discovery.media.broker, 'browse', tracked)
    first = scan(setup, directories=1)
    assert len(calls) == 1 and first['state'] == 'paused'
    page = status(setup, limit=1)
    assert page['next_page_cursor'] is not None
    second = scan(setup, first['next_cursor'], directories=1)
    assert len(calls) == 2 and second['complete']
    with pytest.raises(ContractError) as exc:
        status(setup, cursor=page['next_page_cursor'])
    assert exc.value.code == 'CURSOR_EXPIRED'


def test_changed_root_precondition_does_not_scan(setup, monkeypatch):
    discovery, db, context, *_ = setup
    monkeypatch.setattr(discovery.media.broker, 'browse', lambda *a, **k: pytest.fail('stale scan'))
    with pytest.raises(ContractError) as exc:
        discovery.scan(db, None, context, {'max_entries': 1, 'max_directories': 1},
                       {'root_revisions': []})
    assert exc.value.code == 'ROOT_CHANGED'
    assert discovery.load(db, context) is None


def test_page_cursor_accepts_upper_bound_offset(setup):
    scan(setup)
    discovery, db, context, *_ = setup
    state = discovery.load(db, context)
    cursor = 'page_' + digest([state['scan_id'], state['revision']])[:24] + '_10000'
    result = status(setup, cursor=cursor)
    assert result['items'] == []
    assert result['next_page_cursor'] is None
    assert result['scan_id'] == state['scan_id']


@pytest.mark.parametrize('cursor', [None, 1, True, [], {}],
                         ids=['null', 'integer', 'boolean', 'list', 'object'])
def test_page_cursor_rejects_nonstring(setup, cursor):
    scan(setup)
    with pytest.raises(ContractError) as exc:
        status(setup, cursor=cursor)
    assert exc.value.code == 'CURSOR_EXPIRED'


def test_page_cursor_rejects_negative_offset(setup):
    scan(setup)
    discovery, db, context, *_ = setup
    state = discovery.load(db, context)
    cursor = 'page_' + digest([state['scan_id'], state['revision']])[:24] + '_-1'
    with pytest.raises(ContractError) as exc:
        status(setup, cursor=cursor)
    assert exc.value.code == 'CURSOR_EXPIRED'
