"""Production adapter contracts; source-only authoring, never executed here."""
import copy
from types import SimpleNamespace
import uuid

import pytest

from studio.contracts import ContractError
from studio.ui_execution import UIExecution, backend_data, build_integrations, command_id
from studio.ui_files import UIFileBroker
from studio.ui_media import UIMedia, sha


@pytest.fixture
def setup(tmp_path):
    records = [{'id': 'native', 'name': 'Project', 'archived': False, 'folders': []}]
    registry = lambda: records
    broker = UIFileBroker(tmp_path / 'handles', registry)
    media = UIMedia(tmp_path / 'ui', registry, broker)
    execution = UIExecution(media)
    context = {'scope': {'backend_instance_id': 'backend', 'connection_id': 'connection',
                         'profile_id': 'default', 'native_project_id': 'native'},
               'principal': 'user', 'params': {}, 'private_project_id': 'private-never-public',
               'private_project_revision': 4, 'project_store': object(),
               'composition': {'composition_id': 'composition', 'composition_revision': 2},
               'version': {'version_id': 'version', 'sha256': 'a' * 64},
               'command_id': str(uuid.uuid4()), 'idempotency_key': str(uuid.uuid4())}
    return execution, media, context, registry, broker


def test_build_is_lazy_and_exposes_stable_host_transport(setup, tmp_path, monkeypatch):
    execution, media, context, registry, broker = setup
    def forbidden(*args, **kwargs):
        raise AssertionError('No runtime or worker may start while building integrations')
    monkeypatch.setattr(UIExecution, 'runtime', forbidden)
    root = tmp_path / 'not-created'
    adapters = build_integrations(root, registry, broker)
    assert root.exists() is False
    assert set(k for k in adapters if not k.startswith('_')) == set(UIMedia.OPERATIONS) | set(UIExecution.OPERATIONS)
    assert callable(adapters['_media_store'].open_access)
    assert callable(adapters['_media_store'].put_chunk)
    assert callable(adapters['_media_store'].read_media_chunk)
    assert 'motion_run' not in adapters and 'execute' not in adapters


def test_probe_binding_projects_only_observed_source_facts():
    asset = dict(asset_id='asset_' + uuid.uuid4().hex,
                 asset_version_id='assetversion_' + uuid.uuid4().hex, sha256='a' * 64, kind='media')
    pin = dict(artifact_id='art_' + str(uuid.uuid4()), sha256='sha256:' + asset['sha256'])
    # Synthetic unit fixture, not observed execution evidence.
    receipt: dict = dict(schema='motion/v1/probe-receipt', artifact=pin, full_decode='not_tested',
                   vfr='unknown', streams=[dict(index=0, type='video', rate={'num': 30, 'den': 1},
                   frame_count=90, time_base={'num': 1, 'den': 90000}, start_pts=180000,
                   duration_ticks=270000, sample_rate=None)])
    facts = UIExecution.source_facts(asset, pin, receipt, 0)
    assert facts['kind'] == 'video' and facts['artifact'] == pin
    assert facts['start_pts'] == 180000 and facts['duration_ticks'] == 270000
    assert 'sample_rate' not in facts and 'duration_frames' not in facts and 'rate' not in facts
    cfr = UIExecution.source_facts(asset, pin, {**receipt, 'vfr': 'no'}, 0)
    assert cfr['duration_frames'] == 90 and cfr['rate'] == {'num': 30, 'den': 1}
    sparse = {**receipt, 'streams': [{**receipt['streams'][0], 'start_pts': None,
                                     'duration_ticks': None, 'frame_count': None}]}
    assert not {'start_pts', 'duration_ticks', 'duration_frames'} & UIExecution.source_facts(asset, pin, sparse, 0).keys()
    for invalid, index, code in [({**receipt, 'artifact': {**pin, 'sha256': 'sha256:' + 'b' * 64}}, 0, 'HASH_MISMATCH'),
                                  ({**receipt, 'full_decode': 'fail'}, 0, 'OUTPUT_INVALID'),
                                  (receipt, 1, 'UNSUPPORTED_OPERATION'),
                                  (receipt, False, 'UNSUPPORTED_OPERATION')]:
        with pytest.raises(ContractError) as err:
            UIExecution.source_facts(asset, pin, invalid, index)
        assert err.value.code == code


def test_still_binding_does_not_invent_source_duration():
    asset = dict(asset_id='asset_' + uuid.uuid4().hex,
                 asset_version_id='assetversion_' + uuid.uuid4().hex, sha256='c' * 64, kind='image')
    pin = dict(artifact_id='art_' + str(uuid.uuid4()), sha256='sha256:' + asset['sha256'])
    receipt = dict(schema='motion/v1/probe-receipt', artifact=pin, vfr='unknown',
                   full_decode='not_tested', streams=[dict(index=0, type='video', rate=None,
                   frame_count=None, time_base={'num': 1, 'den': 25}, start_pts=None,
                   duration_ticks=None, sample_rate=None)])
    assert UIExecution.source_facts(asset, pin, receipt, 0) == {**asset, 'artifact': pin}


def test_probe_requires_host_session_before_copy_or_job(setup, monkeypatch):
    execution, media, context, registry, broker = setup
    monkeypatch.setattr(execution, 'runtime', lambda ctx: pytest.fail('No authority, no runtime'))
    asset = dict(asset_id='asset_' + uuid.uuid4().hex,
                 asset_version_id='assetversion_' + uuid.uuid4().hex, sha256='d' * 64,
                 entity_revision=1, kind='media')
    with media.database(context, write=True) as (db, fs):
        media.save(db, 'asset', asset['asset_id'], asset)
    selected = {**context, 'params': {'asset_id': asset['asset_id']}, 'operation_id': 'OP-ASSET-PROBE'}
    payload = dict(asset_version_id=asset['asset_version_id'], sha256=asset['sha256'], full_decode=False)
    pre = dict(entity_revision=1, version_id=context['version']['version_id'],
               composition_revision=context['composition']['composition_revision'])
    with pytest.raises(ContractError) as err:
        execution.callback(selected, payload, pre)
    assert err.value.code == 'AUTHORITY_REQUIRED'
    with media.database(context) as (db, fs):
        assert media.all(db, 'composition-asset') == []
        assert media.all(db, 'exec-job') == []


def test_bind_requires_committed_receipt_and_retains_private_graph_binding(setup, monkeypatch):
    execution, media, context, registry, broker = setup
    asset: dict = dict(asset_id='asset_' + uuid.uuid4().hex,
                 asset_version_id='assetversion_' + uuid.uuid4().hex, sha256='e' * 64,
                 entity_revision=1, kind='audio', usages=[])
    pin = dict(artifact_id='art_' + str(uuid.uuid4()), sha256='sha256:' + asset['sha256'])
    association = dict(id=media.association_id(context, asset), owner=context['private_project_id'],
                       native_asset_id='ast_' + str(uuid.uuid4()), pin=pin,
                       composition_id=context['composition']['composition_id'])
    with media.database(context, write=True) as (db, fs):
        media.save(db, 'asset', asset['asset_id'], asset)
        media.save(db, 'composition-asset', association['id'], association)
    native_data: dict = dict(asset={'artifact': pin}, latest_probe=None)
    requests = []
    def native_asset(args):
        requests.append(args)
        return {'ok': True, 'data': copy.deepcopy(native_data)}
    monkeypatch.setattr(execution, 'runtime', lambda ctx: SimpleNamespace(asset=native_asset))
    selected = {**context, 'operation_id': 'OP-ASSET-BIND', 'params': {'asset_id': asset['asset_id']}}
    rid = 'rcp_' + str(uuid.uuid4())
    payload = dict(asset_version_id=asset['asset_version_id'], sha256=asset['sha256'],
                   receipt_id=rid, stream_index=0)
    pre = dict(entity_revision=1, version_id=context['version']['version_id'],
               composition_revision=context['composition']['composition_revision'])
    with pytest.raises(ContractError) as err:
        execution.callback(selected, payload, pre)
    assert err.value.code == 'PROBE_REQUIRED'
    native_data['latest_probe'] = dict(schema='motion/v1/probe-receipt', artifact=pin,
        receipt_id=rid, full_decode='not_tested', vfr='unknown', streams=[dict(
            index=0, type='audio', sample_rate=48000, time_base={'num': 1, 'den': 48000},
            start_pts=0, duration_ticks=96000, frame_count=None, rate=None)])
    result = execution.callback(selected, payload, pre)
    assert result['readiness'] == 'bound'
    assert result['source_facts']['sample_rate'] == 48000
    assert 'artifact' not in result['source_facts']
    assert all(r['action'] == 'get' for r in requests)
    with media.database(context) as (db, fs):
        retained = media.get(db, 'composition-asset', association['id'])
        assert retained['graph_asset']['artifact'] == pin
        assert retained['probe']['receipt_id'] == rid
        public = media.get(db, 'asset', asset['asset_id'])
        assert public['usages'] == [context['composition']['composition_id']]


def test_unknown_operation_never_dispatches_runtime(setup, monkeypatch):
    execution, media, context, registry, broker = setup
    monkeypatch.setattr(execution, 'runtime', lambda ctx: pytest.fail('arbitrary tool dispatch'))
    with pytest.raises(ContractError) as err:
        execution.callback({**context, 'operation_id': 'motion_run'}, {'action': 'execute'}, {})
    assert err.value.code == 'UNSUPPORTED_OPERATION'


def test_renderer_approval_ids_are_not_execution_authority(setup, monkeypatch):
    execution, media, context, registry, broker = setup
    monkeypatch.setattr(execution, 'runtime', lambda ctx: pytest.fail('untrusted submission'))
    forged = {**context, 'approval_refs': ['approved'], 'principal': 'admin'}
    with pytest.raises(ContractError) as err:
        execution._submit_plan(forged, {'plan_id': 'plan'}, 4, 'submit')
    assert err.value.code == 'AUTHORITY_REQUIRED'


def test_submit_uses_exact_owned_native_runtime_and_host_session(setup, monkeypatch):
    execution, media, context, registry, broker = setup
    calls = []
    def run(args, **kwargs):
        calls.append((copy.deepcopy(args), kwargs))
        return {'job': {'job_id': 'job-owned', 'state': 'queued'}}
    monkeypatch.setattr(execution, 'runtime', lambda ctx: SimpleNamespace(run=run))
    pin = {'plan_id': 'plan-owned', 'plan_revision': 1, 'plan_sha256': 'sha256:' + 'a' * 64}
    result = execution._submit_plan({**context, 'host_session_id': 'trusted-session',
        'host_task_id': 'trusted-task'}, pin, 4, 'submit')
    assert result['job']['job_id'] == 'job-owned'
    args, host = calls[0]
    assert args['plan'] == pin and args['expected_revision'] == 4
    assert args['project_id'] == context['private_project_id']
    assert host == {'session_id': 'trusted-session', 'task_id': 'trusted-task'}
    assert 'authority_ref' not in args


def test_backend_error_does_not_leak_private_diagnostics():
    with pytest.raises(ContractError) as err:
        backend_data({'ok': False, 'error': {'code': 'PATH_UNSAFE',
                      'message': '/secret/profile/token'}})
    assert err.value.code == 'PATH_UNSAFE'
    assert '/secret' not in err.value.message


def test_preflight_honestly_preserves_graph_compiler_gap(setup, monkeypatch):
    execution, media, context, registry, broker = setup
    def compile_(context, **kwargs):
        raise ContractError('UNSUPPORTED_OPERATION', 'Effects cannot compile to backend timeline.')
    monkeypatch.setattr(execution, '_compile', compile_)
    with pytest.raises(ContractError) as err:
        execution.preflight(None, context, {'action': 'render', 'recipe_ref': 'timeline_assemble_v1',
            'parameters': {}, 'dependency_hashes': [], 'probe_policy': 'cached_only',
            'acknowledged_effects': []}, {})
    assert err.value.message == 'Effects cannot compile to backend timeline.'


def test_preflight_read_is_not_a_live_grant(setup):
    execution, media, context, registry, broker = setup
    with media.database(context) as (db, fs):
        record = {'preflight_id': 'preflight', 'state': 'ready', 'launchable': True}
        execution.save(db, context, 'preflight', 'preflight', {'public': record})
    result = execution.callback({**context, 'operation_id': 'OP-PREFLIGHT-GET',
                                 'params': {'preflight_id': 'preflight'}}, {}, {})
    assert result['launchable'] is False
    assert result['launch_blockers'] == [{'code': 'LIVE_DEPENDENCY_RECHECK_REQUIRED'}]


def test_resources_cannot_cross_compositions(setup):
    execution, media, context, registry, broker = setup
    with media.database(context) as (db, fs):
        execution.save(db, context, 'snapshot', 'snapshot', {'public': {'snapshot_id': 'snapshot'}})
        other = {**context, 'composition': {'composition_id': 'other'}}
        with pytest.raises(ContractError) as err:
            execution.get(db, other, 'snapshot', 'snapshot')
        assert err.value.code == 'NOT_FOUND'


def test_launch_checks_all_frozen_plan_and_effect_pins(setup, monkeypatch):
    execution, media, context, registry, broker = setup
    public = {'preflight_id': 'preflight', 'version_id': 'version',
              'plan_sha256': 'a' * 64, 'effects_sha256': 'b' * 64}
    with media.database(context) as (db, fs):
        execution.save(db, context, 'preflight', 'preflight',
            {'public': public, 'plan': {'plan_id': 'plan'}, 'private_revision': 4})
    monkeypatch.setattr(execution, '_submit_plan', lambda *a, **k: pytest.fail('stale plan submitted'))
    with pytest.raises(ContractError) as err:
        execution.callback({**context, 'operation_id': 'OP-JOB-LAUNCH'},
            {'preflight_id': 'preflight', 'plan_id': 'plan', 'plan_sha256': 'a' * 64,
             'effects_sha256': 'c' * 64, 'approval_refs': [], 'client_intent': 'launch_exact_saved_version'},
            {'version_id': 'version', 'composition_revision': 2})
    assert err.value.code == 'PLAN_STALE'


def test_job_projection_never_returns_private_project_or_path():
    result = UIExecution._job_public({'job_id': 'job', 'state': 'running',
        'project_id': 'private', 'output_dir': '/private', 'authority_evidence_ref': 'secret',
        'plan': {'private_project_id': 'private'}, 'job_revision': 3})
    assert result == {'job_id': 'job', 'job_revision': 3, 'entity_revision': 3, 'state': 'running'}


def test_derivative_does_not_create_a_fake_proxy(setup):
    execution, media, context, registry, broker = setup
    with pytest.raises(ContractError) as err:
        execution.callback({**context, 'operation_id': 'OP-DERIVATIVE'},
            {'kind': 'proxy', 'recipe_ref': 'fake', 'frame_range': None,
             'resolution': None, 'tile_size': None}, {})
    assert err.value.code == 'DERIVATIVE_UNSUPPORTED'


def test_stable_native_request_ids_are_derived_from_frozen_command(setup):
    execution, media, context, registry, broker = setup
    assert command_id(context, 'compile') == command_id(context, 'compile')
    assert command_id(context, 'compile') != command_id(context, 'submit')


def test_canonical_graph_hook_bypasses_lossy_b03_compiler(setup, monkeypatch):
    from studio.ui_execution import GRAPH_KEYS
    execution, media, context, registry, broker = setup
    version = {k: [] for k in GRAPH_KEYS}
    version.update(format={'duration_frames': 50}, version_id='version', sha256='a' * 64)
    context = {**context, 'version': version}
    calls = []
    plan_pin = {'plan_id': 'real-plan', 'plan_revision': 1, 'plan_sha256': 'sha256:' + 'a' * 64}
    runtime = SimpleNamespace(compiler=SimpleNamespace(load=lambda pid, pin: {
        'project_id': context['private_project_id'], 'project_revision': 4}))
    monkeypatch.setattr(execution, 'runtime', lambda ctx: runtime)
    def builder(actual_runtime, actual_context, pinned_graph, frame_range):
        calls.append((actual_runtime, actual_context, pinned_graph, frame_range))
        return {'ok': True, 'data': {'plan': {'plan': plan_pin}, 'gaps': []}}
    execution.bind_graph_renderer(builder)
    actual_runtime, data, frames = execution._compile(context)
    assert actual_runtime is runtime
    assert data['plan']['plan'] == plan_pin
    assert frames == {'start_frame': 0, 'end_frame': 50}
    assert calls[0][2]['effects'] == []


def test_canonical_graph_hook_cannot_return_another_project_plan(setup, monkeypatch):
    from studio.ui_execution import GRAPH_KEYS
    execution, media, context, registry, broker = setup
    version = {k: [] for k in GRAPH_KEYS}
    version.update(format={'duration_frames': 50}, version_id='version', sha256='a' * 64)
    context = {**context, 'version': version}
    runtime = SimpleNamespace(compiler=SimpleNamespace(load=lambda pid, pin: {
        'project_id': 'another-project', 'project_revision': 4}))
    monkeypatch.setattr(execution, 'runtime', lambda ctx: runtime)
    execution.bind_graph_renderer(lambda *args: {'ok': True, 'data': {'plan': {'plan': {}}, 'gaps': []}})
    with pytest.raises(ContractError) as err:
        execution._compile(context)
    assert err.value.code == 'PLAN_STALE'
