"""UI ingest/transport acceptance tests. Authored during source-only pass.

No test runner, import smoke, decoder or media job was invoked by the author.
Fixtures are data-format samples, not claims of playable decoded media.
"""
import base64
import hashlib
import io
import uuid

import pytest

from studio.contracts import ContractError
from studio.project import ProjectStore
from studio.ui_files import UIFileBroker
from studio.ui_media import UIMedia, byte_range, display_name, sniff_media


PNG = b'\x89PNG\r\n\x1a\n' + b'fixture-for-byte-transport-not-decoder-proof'


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'still.png').write_bytes(PNG)
    records = [{'id': 'native-a', 'name': 'A', 'archived': False, 'folders': [{'path': str(source)}]},
               {'id': 'native-b', 'name': 'B', 'archived': False, 'folders': []}]
    registry = lambda: records
    broker = UIFileBroker(tmp_path / 'handles', registry)
    media = UIMedia(tmp_path / 'ui', registry, broker)
    context = {'scope': {'backend_instance_id': 'backend', 'connection_id': 'connection',
                         'profile_id': 'default', 'native_project_id': 'native-a'},
               'principal': 'host-user', 'project_store': ProjectStore(tmp_path / 'projects'),
               'params': {}}
    return media, broker, context, source, records


def call(media, context, operation, input, pre=None, params=None, key=None):
    ctx = {**context, 'operation_id': operation, 'params': params or {},
           'idempotency_key': key or str(uuid.uuid4()), 'command_id': str(uuid.uuid4())}
    return media.callback(ctx, input, pre or {})


def create_upload(media, context, body=PNG):
    fingerprint = hashlib.sha256(body).hexdigest()
    result = call(media, context, 'OP-UPLOAD-CREATE', dict(display_name='still.png', byte_length=len(body),
        declared_mime='image/png', total_sha256=fingerprint, chunk_size=16,
        source_kind='client_file', relative_display_name=None), {'quota_revision': 1})
    return result, fingerprint


def send_chunks(media, context, upload, body=PNG):
    revision = upload['entity_revision']
    for index in range(upload['chunk_count']):
        start = index * upload['chunk_size']
        chunk = body[start:start + upload['chunk_size']]
        status = media.put_chunk(context, upload['upload_id'], index, chunk,
            expected_revision=revision, content_range=f'bytes {start}-{start + len(chunk) - 1}/{len(body)}',
            digest=base64.b64encode(hashlib.sha256(chunk).digest()).decode(), content_length=len(chunk))
        revision = status['entity_revision']
    return revision


def commit_upload(media, context, upload, fingerprint, revision, body=PNG):
    return call(media, context, 'OP-UPLOAD-COMMIT',
        {'total_sha256': fingerprint, 'byte_length': len(body), 'rights_assertions': []},
        {'entity_revision': revision}, {'upload_id': upload['upload_id']})


def test_exact_upload_admits_immutable_asset_and_serves_real_bytes(setup):
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    revision = send_chunks(media, context, upload)
    admitted = commit_upload(media, context, upload, fingerprint, revision)
    asset = admitted['asset']
    assert admitted['state'] == 'committed'
    assert asset['sha256'] == fingerprint
    assert asset['byte_length'] == len(PNG)
    assert asset['probe'] is None and asset['streams'] == []
    assert asset['readiness'] == 'probe_required'
    with media.open_media(context, asset['media_id'], fingerprint) as (stream, metadata):
        assert stream.read() == PNG
        assert metadata['mime'] == 'image/png'
        assert 'path' not in metadata and 'project_id' not in metadata
    assert (source / 'still.png').read_bytes() == PNG


def test_binary_duplicate_chunk_is_idempotent_but_mismatch_is_rejected(setup):
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    chunk = PNG[:16]
    kwargs = dict(expected_revision=1, content_range=f'bytes 0-15/{len(PNG)}',
                  digest=base64.b64encode(hashlib.sha256(chunk).digest()).decode(), content_length=16)
    first = media.put_chunk(context, upload['upload_id'], 0, chunk, **kwargs)
    replay = media.put_chunk(context, upload['upload_id'], 0, chunk, **kwargs)
    assert replay == first
    changed = b'x' * 16
    kwargs['digest'] = base64.b64encode(hashlib.sha256(changed).digest()).decode()
    with pytest.raises(ContractError) as err:
        media.put_chunk(context, upload['upload_id'], 0, changed, **kwargs)
    assert err.value.code == 'CHUNK_MISMATCH'


def test_missing_chunks_and_false_total_hash_never_admit(setup):
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    with pytest.raises(ContractError) as err:
        commit_upload(media, context, upload, fingerprint, 1)
    assert err.value.code == 'CHUNKS_MISSING'
    revision = send_chunks(media, context, upload)
    with pytest.raises(ContractError) as err:
        commit_upload(media, context, upload, '0' * 64, revision)
    assert err.value.code == 'DIGEST_MISMATCH'
    assert call(media, context, 'OP-ASSETS', {})['items'] == []


def test_upload_scope_principal_and_archive_are_enforced(setup):
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    other = {**context, 'principal': 'someone-else'}
    with pytest.raises(ContractError) as err:
        call(media, other, 'OP-UPLOAD-STATUS', {}, params={'upload_id': upload['upload_id']})
    assert err.value.code == 'NOT_FOUND'
    other_scope = {**context, 'scope': {**context['scope'], 'native_project_id': 'native-b'}}
    with pytest.raises(ContractError) as err:
        call(media, other_scope, 'OP-UPLOAD-STATUS', {}, params={'upload_id': upload['upload_id']})
    assert err.value.code == 'NOT_FOUND'
    records[0]['archived'] = True
    with pytest.raises(ContractError) as err:
        call(media, context, 'OP-UPLOAD-ABORT', {'reason': 'stop'}, {'entity_revision': 1},
             {'upload_id': upload['upload_id']})
    assert err.value.code == 'PROJECT_ARCHIVED'


def test_scan_commit_uses_broker_handles_and_does_not_overwrite_source(setup):
    media, broker, context, source, records = setup
    root = broker.roots('native-a')['items'][0]
    file = broker.browse('native-a', root['root_id'], expected_root_revision=root['root_revision'])['items'][0]
    manifest = call(media, context, 'OP-IMPORT-SCAN',
        {'selections': [{'root_id': root['root_id'], 'node_id': file['node_id']}],
         'recursive': False, 'filters': {'kinds': [], 'extensions': [], 'include_hidden': False},
         'max_files': 10, 'max_bytes': 100000, 'symlink_policy': 'deny'},
        {'root_revisions': [{'root_id': root['root_id'], 'revision': root['root_revision']}]})
    assert manifest['complete'] is True
    assert manifest['entries'][0]['display_name'] == 'still.png'
    assert manifest['entries'][0]['status'] == 'eligible'
    imported = call(media, context, 'OP-IMPORT-COMMIT',
        {'manifest_id': manifest['manifest_id'], 'entry_ids': [manifest['entries'][0]['entry_id']],
         'copy_policy': 'managed_immutable_copy', 'dedup_policy': 'reuse_authorized_hash',
         'allow_partial_manifest': False, 'rights_assertions': [], 'target_composition_id': None},
        {'manifest_sha256': manifest['manifest_sha256']})
    assert imported['counts']['admitted'] == 1
    asset = call(media, context, 'OP-ASSETS', {})['items'][0]
    (source / 'still.png').write_bytes(b'changed source')
    with media.open_media(context, asset['media_id'], asset['sha256']) as (stream, metadata):
        assert stream.read() == PNG


def test_transport_requires_host_qualification_and_lease_rechecks_scope(setup):
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    revision = send_chunks(media, context, upload)
    asset = commit_upload(media, context, upload, fingerprint, revision)['asset']
    payload = {'media_id': asset['media_id'], 'purpose': 'preview',
               'transport': 'same_origin_cookie', 'requested_ttl_seconds': 10}
    with pytest.raises(ContractError) as err:
        call(media, context, 'OP-MEDIA-ACCESS', payload, {'media_sha256': fingerprint})
    assert err.value.code == 'MEDIA_TRANSPORT_UNAVAILABLE'
    qualified = {**context, 'qualified_media_transports': ['same_origin_cookie']}
    lease = call(media, qualified, 'OP-MEDIA-ACCESS', payload, {'media_sha256': fingerprint})
    assert '?' not in lease['relative_stream_route']
    assert str(source) not in str(lease)
    binary_context = {'scope': context['scope'], 'principal': context['principal']}
    assert lease['relative_stream_route'].startswith('/api/plugins/motion-studio/ui/v1/projects/native-a/media-access/')
    with media.open_access(binary_context, lease['access_id']) as (stream, metadata):
        assert stream.read() == PNG
    with pytest.raises(ContractError):
        with media.open_access({**context, 'principal': 'other'}, lease['access_id']):
            pass
    media.clock = lambda: 10 ** 12
    with pytest.raises(ContractError) as err:
        with media.open_access(context, lease['access_id']):
            pass
    assert err.value.code == 'MEDIA_ACCESS_EXPIRED'


@pytest.mark.parametrize('name', ['../x.png', '/x.png', 'C:x.png', '..', 'x\\y.png', 'a\x00.png'])
def test_display_names_cannot_be_paths(name):
    with pytest.raises(ContractError):
        display_name(name)


@pytest.mark.parametrize('header,length,expected', [
    (None, 10, (0, 9, False)), ('bytes=2-4', 10, (2, 4, True)),
    ('bytes=8-', 10, (8, 9, True)), ('bytes=-3', 10, (7, 9, True)),
    ('bytes=-100', 10, (0, 9, True)), ('bytes=0-100', 10, (0, 9, True))])
def test_bounded_range_normalization(header, length, expected):
    assert byte_range(header, length) == expected


@pytest.mark.parametrize('header', ['bytes=10-', 'bytes=5-1', 'bytes=-0', 'bytes=0-1,4-5', 'items=0-1'])
def test_bad_ranges_are_rejected(header):
    with pytest.raises(ContractError) as err:
        byte_range(header, 10)
    assert err.value.code == 'RANGE_INVALID'


def test_signature_not_filename_controls_admission():
    with pytest.raises(ContractError) as err:
        sniff_media(io.BytesIO(b'<script>active</script>'), 'fake.png')
    assert err.value.code == 'MEDIA_INVALID'
    assert sniff_media(io.BytesIO(PNG), 'still.png') == 'image/png'


def test_binary_callback_requires_host_bytes_and_checks_exact_metadata(setup):
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    body = PNG[:16]
    payload = dict(content_length=len(body), content_range=f'bytes 0-15/{len(PNG)}',
                   digest=base64.b64encode(hashlib.sha256(body).digest()).decode(),
                   sha256=hashlib.sha256(body).hexdigest())
    params = dict(upload_id=upload['upload_id'], chunk_index='0')
    with pytest.raises(ContractError) as err:
        call(media, context, 'OP-UPLOAD-CHUNK', payload, {'entity_revision': 1}, params)
    assert err.value.code == 'AUTHORITY_REQUIRED'
    with pytest.raises(ContractError) as err:
        call(media, {**context, 'binary_upload_chunk': b'x' * 16}, 'OP-UPLOAD-CHUNK',
             payload, {'entity_revision': 1}, params)
    assert err.value.code == 'DIGEST_MISMATCH'
    accepted = call(media, {**context, 'binary_upload_chunk': body}, 'OP-UPLOAD-CHUNK',
                    payload, {'entity_revision': 1}, params)
    assert accepted['accepted_chunks'][0]['sha256'] == payload['sha256']


def test_blob_callback_is_read_only_and_lease_transport_is_enforced(setup):
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    revision = send_chunks(media, context, upload)
    asset = commit_upload(media, context, upload, fingerprint, revision)['asset']
    qualified = {**context, 'qualified_media_transports': ['authenticated_blob', 'same_origin_cookie']}
    payload = dict(media_id=asset['media_id'], purpose='preview', transport='authenticated_blob',
                   requested_ttl_seconds=30)
    lease = call(media, qualified, 'OP-MEDIA-ACCESS', payload, {'media_sha256': fingerprint})
    # No command/idempotency key on read callbacks; cannot admit or launch work.
    result = media.callback({**qualified, 'operation_id': 'OP-MEDIA-CHUNK',
                             'params': {'access_id': lease['access_id']}},
                            {'offset': '0', 'length': str(len(PNG))}, {})
    assert base64.b64decode(result['bytes_base64']) == PNG
    assert result['chunk_sha256'] == fingerprint and result['eof'] is True
    cookie = call(media, qualified, 'OP-MEDIA-ACCESS', {**payload, 'transport': 'same_origin_cookie'},
                  {'media_sha256': fingerprint})
    with pytest.raises(ContractError) as err:
        media.read_media_chunk(qualified, cookie['access_id'])
    assert err.value.code == 'MEDIA_TRANSPORT_UNAVAILABLE'


def test_admission_copy_is_owned_per_composition_and_recovered_from_native_history(setup, tmp_path):
    from studio.assets import AssetStore
    from studio.artifacts import ArtifactCatalog
    from studio.project import ProjectStore
    media, broker, context, source, records = setup
    upload, fingerprint = create_upload(media, context)
    revision = send_chunks(media, context, upload)
    asset = commit_upload(media, context, upload, fingerprint, revision)['asset']
    store = context['project_store']
    owners = []
    for name in ('first', 'second'):
        created = store.dispatch(dict(action='create', name=name,
            request_id=str(uuid.uuid4()), rate={'num': 24, 'den': 1}, sample_rate=48000))
        assert created['ok'], created
        pid = created['project_id']
        comp = {**context, 'project_store': store, 'private_project_id': pid,
                'composition': {'composition_id': name}}
        request = str(uuid.uuid4())
        with media.database(comp, write=True) as (db, fs):
            binding = media.associate(db, comp, asset, request)
            # Simulate the UI metadata transaction being lost after the native
            # import committed. Retry must replay native history, not recopy.
            db.execute('DELETE FROM records WHERE kind=? AND id=?', ('composition-asset', binding['id']))
            recovered = media.associate(db, comp, asset, request)
            assert recovered == binding
        catalog = ArtifactCatalog(AssetStore(store.root))
        artifact = catalog.resolve(pid, binding['pin'])
        with catalog.open_record(store._filesystem(), artifact) as stream:
            assert stream.read() == PNG
        owners.append(binding)
        with pytest.raises(ContractError) as err:
            media.resolve_source(comp, {k: asset[k] for k in ('asset_id', 'asset_version_id', 'sha256')})
        assert err.value.code == 'PROBE_REQUIRED'
    assert owners[0]['owner'] != owners[1]['owner']
    assert owners[0]['pin']['artifact_id'] != owners[1]['pin']['artifact_id']


def test_command_replay_freezes_intent(setup):
    media, broker, context, source, records = setup
    key = str(uuid.uuid4())
    payload = dict(display_name='still.png', byte_length=len(PNG), declared_mime='image/png',
                   total_sha256=hashlib.sha256(PNG).hexdigest(), chunk_size=16,
                   source_kind='client_file', relative_display_name=None)
    first = call(media, context, 'OP-UPLOAD-CREATE', payload, {'quota_revision': 1}, key=key)
    second = call(media, context, 'OP-UPLOAD-CREATE', payload, {'quota_revision': 1}, key=key)
    assert first == second
    with pytest.raises(ContractError) as err:
        call(media, context, 'OP-UPLOAD-CREATE', {**payload, 'display_name': 'other.png'},
             {'quota_revision': 1}, key=key)
    assert err.value.code == 'IDEMPOTENCY_CONFLICT'
