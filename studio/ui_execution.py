"""Finite UI -> owned NativeRuntime/NativeDeliveryService adapters.

No renderer-selected tool/action dispatch, daemon, subprocess or independent
job engine. Only preflight/command callbacks compile or submit. Reads inspect
committed manifests. Host authentication/approval is server-private context:
``host_session_id`` and ``host_task_id`` feed the existing Hermes authority;
``host_review_attribution`` feeds the identified review bridge. Serialized UI
approval IDs are never grants. Default host absence stays blocked.

build_integrations returns OP callbacks plus the host-only ``_media_store``
(UIMedia): open_access(context, access_id) / open_media(context, media_id,sha256)
yield (seekable_verified_binary_stream, safe_metadata) context managers. The
host authenticates its normal scoped GET, checks CSRF for commands and supplies
``qualified_media_transports`` only after wiring that binary route. Access IDs
are non-bearer, principal/scope/hash/TTL-bound and contain no credentials.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

from .contracts import ContractError, digest
from .project import _now
from .ui_media import UIMedia, fail, sha, opaque, unwrap


GRAPH_KEYS = ('schema_version', 'format', 'tracks', 'clips', 'scenes', 'layers',
              'effects', 'audio_buses', 'captions', 'asset_refs', 'settings', 'production_documents')
RECIPES = {'timeline_assemble_v1': 'render'}


def unprefix(value):
    return value.removeprefix('sha256:') if isinstance(value, str) else value


def command_id(context, label):
    key = context.get('idempotency_key') or context.get('command_id')
    if not key:
        fail('PRECONDITION_REQUIRED', 'A durable command identity is required.')
    return str(uuid.uuid5(uuid.UUID(key), label))


def backend_data(result):
    # NativeRuntime.run returns data directly on success; other endpoints use
    # the shared envelope. Neither route may leak raw backend error text.
    if isinstance(result, dict) and 'ok' in result:
        return unwrap(result)
    if not isinstance(result, dict):
        fail('BACKEND_UNAVAILABLE', 'The owned backend returned no structured result.')
    return result


class UIExecution:
    OPERATIONS = ('OP-PREFLIGHT', 'OP-PREFLIGHT-GET', 'OP-RENDER-PREPARE',
        'OP-RENDER-SNAPSHOT-GET', 'OP-RENDER-LAUNCH', 'OP-JOB-LAUNCH', 'OP-JOBS', 'OP-JOB-GET',
        'OP-JOB-CANCEL', 'OP-CANDIDATES', 'OP-CANDIDATE-GET', 'OP-CANDIDATE-CHECK',
        'OP-REVIEW-RECORD', 'OP-MASTER-PROMOTE', 'OP-MASTERS', 'OP-MASTER-GET', 'OP-REVIEWS',
        'OP-PACKAGE-CREATE', 'OP-PACKAGES', 'OP-PACKAGE-GET', 'OP-PACKAGE-VALIDATE', 'OP-DERIVATIVE',
        'OP-ASSET-PROBE', 'OP-ASSET-BIND')

    def __init__(self, media):
        self.media = media
        self.graph_plan_builder = None
        self.graph_recipe_id = None

    def bind_graph_renderer(self, builder, *, recipe_id='canonical_graph_render_v1'):
        """Trusted host registration, never a JSON/renderer operation.

        builder(runtime, context, pinned_graph, frame_range) returns the normal
        NativeRuntime.plan envelope (including real committed blocked plans).
        It must resolve public document references through the trusted snapshot
        resolver and create a real immutable graph/artifact closure. The host
        installs the compositor's advertised capability/binding, not the UI.
        """
        if not callable(builder):
            raise TypeError('A trusted graph plan builder is required.')
        self.graph_plan_builder = builder
        self.graph_recipe_id = recipe_id

    def runtime(self, context):
        from .runtime import NativeRuntime
        projects = context.get('project_store')
        if projects is None or not context.get('private_project_id'):
            fail('INTEGRATION_UNAVAILABLE', 'An exact composition/ProjectStore binding is required.')
        # Readiness/probes are not refreshed by constructing the runtime. The
        # registry and adapters remain lazy until explicit plan/execute paths.
        return NativeRuntime(projects=projects)

    @staticmethod
    def identity(context):
        if not context.get('composition') or not context.get('version'):
            fail('PRECONDITION_REQUIRED', 'Select a saved composition version.')
        return context['composition']['composition_id']

    def save(self, db, context, kind, identity, value):
        self.media.save(db, 'execution:' + kind, identity,
                        {'composition_id': self.identity(context), 'value': value})

    def get(self, db, context, kind, identity):
        record = self.media.get(db, 'execution:' + kind, identity)
        if record['composition_id'] != self.identity(context):
            fail('NOT_FOUND', 'Resource does not belong to this composition.')
        return record['value']

    def callback(self, context, input, pre):
        operation = context['operation_id']
        if operation not in self.OPERATIONS:
            fail('UNSUPPORTED_OPERATION', 'This execution operation is not advertised.')
        reads = {'OP-PREFLIGHT-GET', 'OP-RENDER-SNAPSHOT-GET', 'OP-JOBS', 'OP-JOB-GET',
                 'OP-CANDIDATES', 'OP-CANDIDATE-GET', 'OP-PACKAGE-GET', 'OP-PACKAGES',
                 'OP-MASTERS', 'OP-MASTER-GET', 'OP-REVIEWS'}
        with self.media.database(context, write=operation not in reads) as (db, fs):
            if operation in ('OP-JOB-GET', 'OP-JOB-CANCEL'):
                bound = self.media.get(db, 'job-binding', context['params']['job_id'])
                context = {**context, **bound}
            if operation not in ('OP-JOBS', 'OP-DERIVATIVE'):
                self.identity(context)
            handlers = {'OP-PREFLIGHT': self.preflight, 'OP-PREFLIGHT-GET': self.preflight_get,
                'OP-RENDER-PREPARE': self.snapshot, 'OP-RENDER-SNAPSHOT-GET': self.snapshot_get,
                'OP-RENDER-LAUNCH': self.submit, 'OP-JOB-LAUNCH': self.launch,
                'OP-JOBS': self.jobs, 'OP-JOB-GET': self.job,
                'OP-JOB-CANCEL': self.cancel, 'OP-CANDIDATES': self.candidates,
                'OP-CANDIDATE-GET': self.candidate, 'OP-CANDIDATE-CHECK': self.check,
                'OP-REVIEW-RECORD': self.review, 'OP-MASTER-PROMOTE': self.promote,
                'OP-MASTERS': self.masters, 'OP-MASTER-GET': self.master_get, 'OP-REVIEWS': self.reviews,
                'OP-PACKAGE-CREATE': self.package, 'OP-PACKAGE-GET': self.package_get,
                'OP-PACKAGES': self.packages, 'OP-PACKAGE-VALIDATE': self.package_check,
                'OP-DERIVATIVE': self.derivative, 'OP-ASSET-PROBE': self.asset_probe,
                'OP-ASSET-BIND': self.asset_bind}
            replay = self.media._replay(db, context, input, pre) if operation not in reads else None
            if replay and replay[2] is not None:
                return replay[2]
            result = handlers[operation](db, context, input, pre)
            if replay:
                self.media.save(db, 'command', replay[0], {'sha256': replay[1], 'result': result})
            return result

    def _selected_asset(self, db, context, input, pre):
        record = self.media.get(db, 'asset', context['params']['asset_id'])
        if (record['asset_version_id'] != input['asset_version_id'] or
                record['sha256'] != input['sha256']):
            fail('ASSET_UNRESOLVED', 'Select the exact admitted asset version/hash.')
        if record['entity_revision'] != pre['entity_revision']:
            fail('REVISION_CONFLICT', 'Asset metadata changed.')
        if (context['version']['version_id'] != pre['version_id'] or
                context['composition']['composition_revision'] != pre['composition_revision']):
            fail('PLAN_STALE', 'Composition changed before asset preparation.')
        return record

    def asset_probe(self, db, context, input, pre):
        """Explicit command contract (host must add the finite route/schema).

        POST C/assets/{asset_id}/probe, OP-ASSET-PROBE.
        input = {asset_version_id, sha256, full_decode: boolean}.
        pre = {entity_revision, version_id, composition_revision}.
        Returns {asset_id, asset_version_id, job}; no decoder on read/import.
        Copies bytes to this composition using AssetStore, then submits exactly
        ffmpeg.probe/media.probe@1 through NativeRuntime.asset and Hermes policy.
        Poll existing OP-JOB-GET; the owned worker lifecycle collects the report.
        """
        record = self._selected_asset(db, context, input, pre)
        if not isinstance(input['full_decode'], bool):
            fail('INVALID_ARGUMENT', 'full_decode must be explicit boolean.')
        if not context.get('host_session_id'):
            fail('AUTHORITY_REQUIRED', 'Probing requires the trusted host session and normal exact-plan approval.')
        runtime = self.runtime(context)
        association = self.media.associate(db, context, record,
            str(uuid.uuid5(uuid.NAMESPACE_URL, 'composition-asset:' + self.media.association_id(context, record))))
        fs = runtime.projects._filesystem()
        pointer = runtime.projects._pointer(fs, context['private_project_id'])
        if pointer is None:
            fail('NOT_FOUND', 'Composition engine project is unavailable.')
        result = runtime.asset(dict(action='probe', project_id=context['private_project_id'],
            expected_revision=pointer['revision'], request_id=command_id(context, 'asset-probe'),
            artifact=association['pin'], adapter_id='ffmpeg.probe', full_decode=input['full_decode']),
            session_id=context['host_session_id'], task_id=context.get('host_task_id'))
        data = backend_data(result)
        bound = {**context, 'private_project_revision': pointer['revision']}
        self.track_job(db, bound, data['job'])
        tracked = self.get(db, bound, 'job', data['job']['job_id'])
        tracked['source_asset'] = {'asset_id': record['asset_id'],
                                   'asset_version_id': record['asset_version_id'],
                                   'association_id': association['id']}
        self.save(db, bound, 'job', data['job']['job_id'], tracked)
        return {'asset_id': record['asset_id'], 'asset_version_id': record['asset_version_id'],
                'job': self._job_public(data['job'])}

    @staticmethod
    def source_facts(record, pin, receipt, stream_index):
        """Project only observed exact stream facts, never guessed durations/rates.

        composition.v1 has no stream selector field, and the compositor only
        implements index zero. Reject other indices instead of rendering a
        different stream or inserting an unsupported hidden graph property.
        """
        if receipt.get('schema') != 'motion/v1/probe-receipt' or receipt.get('artifact') != pin:
            fail('HASH_MISMATCH', 'Probe receipt differs from the composition artifact.')
        if receipt.get('full_decode') == 'fail':
            fail('OUTPUT_INVALID', 'The committed source failed full decode.')
        if type(stream_index) is not int or stream_index != 0:
            fail('UNSUPPORTED_OPERATION', 'Current canonical compositor binding supports stream index zero only.')
        streams = [s for s in receipt['streams'] if s['index'] == stream_index]
        if len(streams) != 1 or streams[0]['type'] not in ('video', 'audio'):
            fail('ASSET_UNRESOLVED', 'Select an observed picture/audio stream.')
        stream = streams[0]
        kind = 'image' if record['kind'] in ('image', 'frame') else stream['type']
        facts = dict(asset_id=record['asset_id'], asset_version_id=record['asset_version_id'],
                     sha256=record['sha256'], kind=kind, artifact=copy.deepcopy(pin))
        # NB avg_frame_rate does not prove CFR. Canonical frame mapping is
        # exposed only when the receipt actually establishes constant timing.
        if (receipt.get('vfr') == 'no' and stream.get('rate') is not None and
                type(stream.get('frame_count')) is int and stream['frame_count'] > 0):
            facts.update(rate=copy.deepcopy(stream['rate']), duration_frames=stream['frame_count'])
        if (stream.get('time_base') is not None and type(stream.get('start_pts')) is int and
                type(stream.get('duration_ticks')) is int and stream['duration_ticks'] > 0):
            facts.update(time_base=copy.deepcopy(stream['time_base']), start_pts=stream['start_pts'],
                         duration_ticks=stream['duration_ticks'])
        if kind == 'audio' and type(stream.get('sample_rate')) is int and stream['sample_rate'] > 0:
            facts['sample_rate'] = stream['sample_rate']
        return facts

    def asset_bind(self, db, context, input, pre):
        """POST C/assets/{asset_id}/bind, OP-ASSET-BIND (explicit metadata write).

        input = {asset_version_id, sha256, receipt_id, stream_index: 0}; pre is
        the same as probe. Read the real committed latest receipt, never probe.
        Return public {asset_id, asset_version_id, readiness, source_facts}.
        source_facts excludes the private artifact; resolve_source hydrates it.
        """
        record = self._selected_asset(db, context, input, pre)
        association = self.media.get(db, 'composition-asset', self.media.association_id(context, record))
        runtime = self.runtime(context)
        data = unwrap(runtime.asset(dict(action='get', project_id=context['private_project_id'],
                                         asset_id=association['native_asset_id'])))
        if data['asset']['artifact'] != association['pin']:
            fail('HASH_MISMATCH', 'Native asset association changed.')
        receipt = data['latest_probe']
        if receipt is None:
            fail('PROBE_REQUIRED', 'No collected committed probe report is available yet.')
        if receipt['receipt_id'] != input['receipt_id']:
            fail('REVISION_CONFLICT', 'The selected probe receipt is not the current committed receipt.')
        facts = self.source_facts(record, association['pin'], receipt, input['stream_index'])
        association.update(graph_asset=facts, probe=copy.deepcopy(receipt))
        self.media.save(db, 'composition-asset', association['id'], association)
        if association['composition_id'] not in record['usages']:
            record['usages'].append(association['composition_id'])
        record['entity_revision'] += 1
        # Readiness remains composition-specific; project list is not a grant
        # to resolve the same public asset in some other composition.
        self.media.save(db, 'asset', record['asset_id'], record)
        return dict(asset_id=record['asset_id'], asset_version_id=record['asset_version_id'],
                    entity_revision=record['entity_revision'], readiness='bound',
                    source_facts={k: v for k, v in facts.items() if k != 'artifact'})

    def _compile(self, context, *, range_=None):
        from .ui_graph import compile_graph
        version = context['version']
        graph = {k: copy.deepcopy(version[k]) for k in GRAPH_KEYS}
        if self.graph_plan_builder is not None:
            runtime = self.runtime(context)
            frames = range_ or {'start_frame': 0, 'end_frame': graph['format']['duration_frames']}
            if not 0 <= frames['start_frame'] < frames['end_frame'] <= graph['format']['duration_frames']:
                fail('SOURCE_BOUNDS_UNKNOWN', 'Render range is outside the pinned canonical graph.')
            result: Any = self.graph_plan_builder(runtime, context, graph, frames)
            data = result.get('data') if result.get('data', {}).get('gaps') else unwrap(result)
            plan = runtime.compiler.load(context['private_project_id'], data['plan']['plan'])
            if (plan['project_id'] != context['private_project_id'] or
                    plan['project_revision'] != context['private_project_revision']):
                fail('PLAN_STALE', 'Graph renderer returned a plan for different saved content.')
            return runtime, data, frames
        # compile_graph explicitly rejects effects, text/rich layers, audio
        # buses/manual caption compilation and unsupported document envelopes.
        # Preserve its exact explanatory ContractError; do not degrade content.
        compiled = compile_graph(graph)
        runtime = self.runtime(context)
        store, pid = runtime.projects, context['private_project_id']
        fs = store._filesystem()
        pointer = store._pointer(fs, pid)
        if pointer['revision'] != context['private_project_revision']:
            fail('PLAN_STALE', 'Engine head differs from the selected saved version.')
        snapshot, docs = store._load(fs, pointer)
        settings = compiled['settings']
        frame_range = range_ or {'start_frame': 0, 'end_frame': compiled['timeline']['duration_frames']}
        if frame_range['end_frame'] <= frame_range['start_frame'] or frame_range['end_frame'] > compiled['timeline']['duration_frames']:
            fail('SOURCE_BOUNDS_UNKNOWN', 'Render range is outside the saved timeline.')
        if compiled['scenes']:
            fail('CAPABILITY_MISSING', 'Timeline assembly requires previously rendered scene media; no implicit scene renderer is selected.')
        from .delivery import NativeDeliveryService
        timeline_pin = NativeDeliveryService._document_pin(docs['timeline', 'project'])
        pins = []
        for track in compiled['timeline']['tracks']:
            for item in track['items']:
                if item['subject']['kind'] != 'artifact':
                    fail('CAPABILITY_MISSING', 'The timeline contains an unresolved rendered scene.')
                pin = item['subject']['artifact']
                if pin not in pins:
                    pins.append(pin)
        if not pins:
            fail('SOURCE_UNAVAILABLE', 'Timeline contains no committed media.')
        request = {'target_key': 'ui_assembly', 'operation': 'edit.assemble@1',
            'inputs': {'timeline': {'kind': 'document', 'document': timeline_pin},
                       'media': [{'kind': 'artifact', 'artifact': p} for p in pins]},
            'parameters': {'range': frame_range,
                           'canvas': {'width_px': version['format']['width'], 'height_px': version['format']['height']},
                           'rate': settings['rate']}}
        result = runtime.plan({'action': 'compile', 'project_id': pid,
                    'expected_revision': context['private_project_revision'],
                    'request_id': command_id(context, 'compile:' + sha(frame_range)),
                    'requests': [request], 'targets': ['ui_assembly']})
        if result.get('data', {}).get('gaps'):
            return runtime, result['data'], frame_range
        return runtime, unwrap(result), frame_range

    def preflight(self, db, context, input, pre):
        recipe_id = input['recipe_ref'].get('id') if isinstance(input['recipe_ref'], dict) else input['recipe_ref']
        if input['probe_policy'] != 'cached_only':
            fail('AUTHORITY_REQUIRED', 'Explicit probe execution needs a separately pinned approved NativeRuntime probe plan.')
        if input['action'] == 'render':
            accepted_recipe = self.graph_recipe_id if self.graph_plan_builder is not None else 'timeline_assemble_v1'
            if recipe_id != accepted_recipe or input['parameters']:
                fail('CAPABILITY_MISSING', 'Select timeline_assemble_v1 with saved-composition parameters.')
            runtime, result, frames = self._compile(context)
        else:
            runtime, result, frames = self.delivery_preflight(db, context, input)
        summary = result['plan']
        plan = runtime.compiler.load(context['private_project_id'], summary['plan'])
        record = {'preflight_id': opaque('preflight'), 'state': summary['status'],
            'version_id': context['version']['version_id'], 'version_sha256': context['version']['sha256'],
            'composition_revision': context['composition']['composition_revision'],
            'action': input['action'], 'recipe_ref': input['recipe_ref'], 'frame_range': frames,
            'effects': plan['effects'], 'effects_sha256': unprefix(digest(plan['effects'])),
            'dependency_hashes': input['dependency_hashes'],
            'blockers': [{'code': g['code'], 'reason': g['reason']} for g in result['gaps']],
            'launchable': not result['gaps'], 'observed_at': _now()}
        record.update(plan_id=summary['plan']['plan_id'], plan_sha256=unprefix(summary['plan']['plan_sha256']),
                      parameters_sha256=sha(input['parameters']), verified_snapshot_sha256=unprefix(plan['snapshot_sha256']))
        if input['action'] == 'render' and self.graph_plan_builder is None:
            record.update(output_kind='preview_assembly', render_gaps=['VARIANT_ENCODE_NOT_SELECTED'])
        record['preflight_sha256'] = sha(record)
        self.save(db, context, 'preflight', record['preflight_id'], {'public': record, 'plan': summary['plan'],
                    'private_revision': context['private_project_revision']})
        return record

    def delivery_preflight(self, db, context, input):
        """Compile native package/check recipes without submitting a job."""
        from .adapters.delivery import ADAPTER_ID
        service = self.delivery(context)
        runtime = service.runtime
        pid = context['private_project_id']
        fs = service.store._filesystem()
        pointer = service.store._pointer(fs, pid)
        if pointer['revision'] != context['private_project_revision']:
            fail('PLAN_STALE', 'Saved content differs from engine head.')
        params = input['parameters']
        recipe = input['recipe_ref'].get('id') if isinstance(input['recipe_ref'], dict) else input['recipe_ref']
        base = dict(project_id=pid, expected_revision=pointer['revision'],
                    request_id=command_id(context, 'delivery-preflight'), adapter_id=ADAPTER_ID)
        if input['action'] == 'package' and recipe == 'native_package_v1':
            required = {'master_refs', 'format', 'include_source', 'source_refs', 'sidecar_file_ids', 'reconstruct'}
            if set(params) != required or params['format'] != 'zip' or params['include_source'] is not True or params['source_refs'] or params['sidecar_file_ids']:
                fail('CAPABILITY_MISSING', 'Package recipe requires whole master-owned portable ZIP source closure.')
            masters = service._records(fs, pid, 'masters')
            ids = []
            for ref in params['master_refs']:
                matches = [m for m in masters if m['master_id'] == ref['master_id'] and m['revision'] == ref['master_revision']]
                if not matches or unprefix(matches[0]['candidate']['sha256']) != ref['candidate_sha256']:
                    fail('MASTER_CONFLICT', 'Package preflight master pin is unavailable.')
                ids.append(ref['master_id'])
            if not ids or len(ids) != len(set(ids)):
                fail('INVALID_ARGUMENT', 'Select distinct exact masters.')
            tasks = service.executor.package_tasks(dict(base, action='package', master_ids=ids,
                    format='zip', include_sources=True, reconstruct=params['reconstruct']), fs, pointer)
        elif input['action'] == 'package_check' and recipe == 'native_package_check_v1':
            if set(params) != {'package_id', 'entity_revision', 'manifest_sha256'}:
                fail('INVALID_ARGUMENT', 'Package-check recipe requires exact package revision/manifest.')
            versions = [p for p in service._records(fs, pid, 'packages') if p['package_id'] == params['package_id']]
            if not versions:
                fail('NOT_FOUND', 'Package is unavailable.')
            package = max(versions, key=lambda p: p['revision'])
            if package['revision'] != params['entity_revision'] or unprefix(package['manifest']['sha256']) != params['manifest_sha256']:
                fail('REVISION_CONFLICT', 'Package-check manifest pin differs.')
            tasks = service.executor.package_tasks(dict(base, action='package_validate',
                    package_id=package['package_id'], expected_package_revision=package['revision']), fs, pointer)
        elif input['action'] == 'candidate_check' and recipe == 'native_candidate_check_v1':
            if set(params) != {'candidate_id', 'candidate_sha256', 'gate_revision', 'gate_refs'}:
                fail('INVALID_ARGUMENT', 'Candidate-check recipe requires exact candidate/gate refs.')
            selected = {**context, 'params': {**context['params'], 'candidate_id': params['candidate_id']}}
            public = self.require_gates(db, selected, params)
            _, binding, candidate = self._candidate(db, context, params['candidate_id'])
            gate_context = service.context(fs, pointer, candidate)
            tasks = []
            for ref in params['gate_refs']:
                if ref not in public['gate_refs'] or ref['gate_kind'] not in ('technical', 'audio', 'delivery_profile'):
                    fail('CAPABILITY_MISSING', 'Measured checks cannot stand in for art/creative review.')
                tasks.append(dict(target_key='check_' + ref['gate_kind'], operation='review.check@1',
                    adapter_id=ADAPTER_ID, inputs={'candidate': {'kind': 'artifact', 'artifact': binding['pin']}, 'evidence': []},
                    parameters={'gate': ref['gate_kind'], 'policy': gate_context.policy_pin, 'checks': []}))
            if not tasks:
                fail('INVALID_ARGUMENT', 'Select one or more supported exact check gates.')
        else:
            fail('CAPABILITY_MISSING', 'No finite adapter recipe is advertised for this action.')
        result = runtime.plan(dict(action='compile', project_id=pid, expected_revision=pointer['revision'],
            request_id=command_id(context, 'delivery-compile'), requests=tasks,
            targets=[t['target_key'] for t in tasks], reuse_outputs=False))
        data = result.get('data') if result.get('data', {}).get('gaps') else unwrap(result)
        return runtime, data, None

    def preflight_get(self, db, context, input, pre):
        record = self.get(db, context, 'preflight', context['params']['preflight_id'])['public']
        # A stored receipt is not a live execution grant.
        return {**record, 'launchable': False, 'launch_blockers': [{'code': 'LIVE_DEPENDENCY_RECHECK_REQUIRED'}]}

    def snapshot(self, db, context, input, pre):
        retained = self.get(db, context, 'preflight', input['preflight_id'])
        public = retained['public']
        if public['version_id'] != pre['version_id'] or public['composition_revision'] != pre['composition_revision']:
            fail('PLAN_STALE', 'Preflight does not match this saved version.')
        if public['blockers']:
            fail('PLAN_BLOCKED', 'Resolve exact preflight blockers before freezing a snapshot.')
        if input['recipe_ref'] != public['recipe_ref'] or input['range'] != public['frame_range']:
            fail('PLAN_STALE', 'Snapshot recipe/range differs from its compiled preflight.')
        if input['quality'] != 'preview':
            fail('CAPABILITY_MISSING', 'Master output needs a separately pinned variant/profile encode plan; a preview render is not a release candidate.')
        if input['deliverable_profiles']:
            fail('CAPABILITY_MISSING', 'Variant encoding requires saved delivery profile/options; timeline_assemble_v1 produces a preview assembly only.')
        if input['dependency_hashes'] != public['dependency_hashes']:
            fail('DEPENDENCY_CHANGED', 'Snapshot dependencies differ from preflight.')
        record = {'render_snapshot_id': opaque('snapshot'), 'version_id': public['version_id'],
                  'version_sha256': public['version_sha256'], 'preflight_id': public['preflight_id'],
                  'effects_sha256': public['effects_sha256'], 'frame_range': public['frame_range'],
                  'state': 'frozen', 'created_at': _now()}
        record['snapshot_sha256'] = sha(record)
        record['snapshot_id'] = record['render_snapshot_id']
        self.save(db, context, 'snapshot', record['render_snapshot_id'],
                  {'public': record, 'plan': retained['plan'], 'private_revision': retained['private_revision']})
        return record

    def snapshot_get(self, db, context, input, pre):
        return self.get(db, context, 'snapshot', context['params']['snapshot_id'])['public']

    def _submit_plan(self, context, plan, revision, label):
        if not context.get('host_session_id'):
            fail('AUTHORITY_REQUIRED', 'No trusted Hermes session is bound for exact-plan authorization; UI approval IDs are not grants.')
        result = self.runtime(context).run({'action': 'submit', 'project_id': context['private_project_id'],
            'expected_revision': revision, 'request_id': command_id(context, label), 'plan': plan},
            session_id=context['host_session_id'], task_id=context.get('host_task_id'))
        return backend_data(result)

    def submit(self, db, context, input, pre):
        snapshot = self.get(db, context, 'snapshot', pre['snapshot_id'])
        if snapshot['public']['snapshot_sha256'] != pre['snapshot_sha256']:
            fail('PLAN_STALE', 'Snapshot bytes differ from the selected pin.')
        if not input['acknowledge_older_head'] and snapshot['public']['version_id'] != context['version']['version_id']:
            fail('PLAN_STALE', 'Acknowledge rendering the older saved version explicitly.')
        runtime = self.runtime(context)
        # Load verifies immutable plan hash; submit performs live dependency and
        # Hermes policy checks inside existing JobStore, not here via booleans.
        runtime.compiler.load(context['private_project_id'], snapshot['plan'])
        data = self._submit_plan(context, snapshot['plan'], snapshot['private_revision'], 'submit')
        self.track_job(db, context, data['job'])
        return self._job_public(data['job'])

    def track_job(self, db, context, job):
        self.media.save(db, 'job-binding', job['job_id'],
                        {k: context[k] for k in ('private_project_id', 'private_project_revision',
                                                'composition', 'version')})

    def launch(self, db, context, input, pre):
        retained = self.get(db, context, 'preflight', input['preflight_id'])
        public = retained['public']
        if (input['plan_id'] != retained['plan']['plan_id'] or input['plan_sha256'] != public['plan_sha256']
                or input['effects_sha256'] != public['effects_sha256']
                or pre['version_id'] != public['version_id']):
            fail('PLAN_STALE', 'Launch intent differs from the exact preflight pins.')
        data = self._submit_plan(context, retained['plan'], retained['private_revision'], 'launch')
        self.track_job(db, context, data['job'])
        return self._job_public(data['job'])

    @staticmethod
    def _job_public(job):
        public = {k: copy.deepcopy(job[k]) for k in ('job_id', 'job_revision', 'state', 'created_at',
                'updated_at', 'stale', 'stale_reasons', 'cancel', 'submission_state', 'remote_state') if k in job}
        if 'job_revision' in job:
            public['entity_revision'] = job['job_revision']
        return public

    def jobs(self, db, context, input, pre):
        if input.get('kind') or input.get('version_id') or input.get('plan_id'):
            fail('UNSUPPORTED_OPERATION', 'These job filters lack an exact backend mapping.')
        rows = db.execute('SELECT id,value FROM records WHERE kind=? ORDER BY id', ('job-binding',)).fetchall()
        items = []
        import json
        for row in rows:
            binding = json.loads(row['value'])
            if input.get('composition_id') and binding['composition']['composition_id'] != input['composition_id']:
                continue
            bound = {**context, **binding}
            bundle = self.runtime(bound).jobs().read(bound['private_project_id'], row['id'])
            job = self._job_public(bundle['job'])
            if input.get('state') and job['state'] != input['state']:
                continue
            job['composition_id'] = binding['composition']['composition_id']
            items.append(job)
        from .ui_media import integer
        offset = integer(int(input.get('cursor') or 0), 0, 100000)
        limit = integer(input.get('limit', 100), 1, 200)
        return {'items': items[offset:offset + limit],
                'next_cursor': str(offset + limit) if offset + limit < len(items) else None}

    def job(self, db, context, input, pre):
        runtime = self.runtime(context)
        bundle = runtime.jobs().read(context['private_project_id'], context['params']['job_id'])
        if bundle is None:
            fail('NOT_FOUND', 'Owned job is unavailable.')
        tracked = self.get(db, context, 'job', context['params']['job_id'])
        source = tracked.get('source_asset')
        result = self._job_public(bundle['job'])
        result['outputs'] = []
        if source is not None:
            # Probe reports carry native artifact identities. Expose only the
            # observed public facts, not a downloadable private JSON report.
            result['source_probe'] = None
            if bundle['job']['state'] == 'succeeded':
                association = self.media.get(db, 'composition-asset', source['association_id'])
                data = unwrap(runtime.asset(dict(action='get', project_id=context['private_project_id'],
                                                asset_id=association['native_asset_id'])))
                receipt = data['latest_probe']
                if receipt is not None:
                    if receipt['artifact'] != association['pin']:
                        fail('HASH_MISMATCH', 'Committed probe differs from the selected source.')
                    result['source_probe'] = {k: copy.deepcopy(receipt[k]) for k in
                        ('receipt_id', 'streams', 'vfr', 'full_decode', 'metadata_gaps')}
                    result['source_probe'].update(asset_id=source['asset_id'],
                                                  asset_version_id=source['asset_version_id'])
            return result
        for pin in bundle['job']['outputs']:
            # Byte-backed output references are registered in same namespace;
            # this read creates no derivative, playback or generation job.
            result['outputs'].append(self.media.register_output(db, context,
                context['private_project_id'], pin, 'Job output'))
        return result

    def cancel(self, db, context, input, pre):
        result = self.runtime(context).run({'action': 'cancel', 'project_id': context['private_project_id'],
            'job_id': context['params']['job_id'], 'expected_job_revision': pre['entity_revision'],
            'request_id': command_id(context, 'cancel'), 'reason': input['reason']},
            session_id=context.get('host_session_id'), task_id=context.get('host_task_id'))
        data = backend_data(result)
        return self._job_public(data['job'])

    def preview(self, db, context, input, pre):
        if input['quality'] != 'draft' or input['resolution'] is not None:
            fail('CAPABILITY_MISSING', 'Preview quality/resolution variants are not declared by the timeline assembly recipe.')
        runtime, compiled, frame_range = self._compile(context, range_=input['frame_range'])
        if compiled['gaps']:
            return {'preview_id': opaque('preview'), 'state': 'blocked',
                    'blockers': [{'code': g['code'], 'reason': g['reason']} for g in compiled['gaps']]}
        data = self._submit_plan(context, compiled['plan']['plan'], context['private_project_revision'], 'preview')
        self.track_job(db, context, data['job'])
        record = {'preview_id': opaque('preview'), 'job_id': data['job']['job_id'],
                  'state': data['job']['state'], 'version_id': context['version']['version_id'],
                  'version_sha256': context['version']['sha256'], 'frame_range': frame_range,
                  'playback': None, 'audio_state': 'not_tested'}
        self.save(db, context, 'preview', record['preview_id'], record)
        return record

    def preview_get(self, db, context, input, pre):
        record = self.get(db, context, 'preview', context['params']['preview_id'])
        bundle = self.runtime(context).jobs().read(context['private_project_id'], record['job_id'])
        record['state'] = bundle['job']['state']
        if record['state'] == 'succeeded':
            runtime = self.runtime(context)
            for pin in bundle['job']['outputs']:
                artifact = runtime.artifacts.resolve(context['private_project_id'], pin)
                if artifact['kind'] in ('media', 'audio', 'image', 'frame'):
                    record['playback'] = self.media.register_output(db, context, context['private_project_id'], pin, 'Composition preview')
                    break
        return record

    def preview_cancel(self, db, context, input, pre):
        record = self.get(db, context, 'preview', context['params']['preview_id'])
        bundle = self.runtime(context).jobs().read(context['private_project_id'], record['job_id'])
        revised = {**context, 'params': {'job_id': record['job_id']}}
        result = self.cancel(db, revised, input, {'job_revision': bundle['job']['job_revision']})
        return {**record, 'state': result['state'], 'cancel': result.get('cancel')}

    def delivery(self, context):
        from .delivery import NativeDeliveryService
        return NativeDeliveryService(self.runtime(context), session_id=context.get('host_session_id'),
                                     task_id=context.get('host_task_id'))

    def _candidate(self, db, context, identity):
        binding = self.get(db, context, 'candidate', identity)
        service = self.delivery(context)
        fs = service.store._filesystem()
        pointer = service.store._pointer(fs, context['private_project_id'])
        candidate = service.candidate(fs, pointer, binding['pin'])
        return service, binding, candidate

    def candidates(self, db, context, input, pre):
        service = self.delivery(context)
        args = dict(action='status', project_id=context['private_project_id'], section='candidates')
        for k in ('variant_id', 'limit', 'cursor'):
            if k in input:
                args[k] = input[k]
        page = service.dispatch(args)
        items = []
        for candidate in page['items']:
            identity = 'candidate_' + sha(candidate['artifact'])[:32]
            self.save(db, context, 'candidate', identity, {'pin': candidate['artifact']})
            items.append(self._candidate_public(identity, candidate))
        return {'items': items, 'next_cursor': page.get('next_cursor')}

    @staticmethod
    def _candidate_public(identity, record):
        gates = record.get('gates', {})
        return {'candidate_id': identity, 'candidate_manifest_sha256': unprefix(record.get('candidate_manifest_sha256')),
                'sha256': unprefix(record.get('artifact', {}).get('sha256')),
                'variant_id': record.get('variant_id'), 'created_at': record.get('created_at'),
                'gates': [{'gate': g['gate'], 'result': g['result'], 'freshness': g['freshness'],
                           'reason': g['reason']} for g in gates.get('gates', [])],
                'promotion_eligible': gates.get('promotion_eligible', False),
                'blockers': gates.get('missing', [])}

    def candidate(self, db, context, input, pre):
        identity = context['params']['candidate_id']
        service, binding, candidate = self._candidate(db, context, identity)
        fs = service.store._filesystem()
        pointer = service.store._pointer(fs, context['private_project_id'])
        gates = service.reviews.gates(fs, pointer, candidate)
        public = self._candidate_public(identity, {**candidate, 'gates': gates,
                                                  'candidate_manifest_sha256': digest(candidate)})
        public['media'] = self.media.register_output(db, context, context['private_project_id'],
                                                     binding['pin'], 'Candidate')
        public['candidate_sha256'] = unprefix(binding['pin']['sha256'])
        public['files'] = [{**public['media'], 'file_id': public['media']['media_id'], 'role': 'master'}]
        public['gate_revision'] = int(sha(gates)[:12], 16)
        gate_context = service.context(fs, pointer, candidate)
        policy = candidate['gate_policy']
        public['gate_refs'] = [dict(policy_id=policy['id'], policy_version_id=str(policy['revision']),
                                  policy_sha256=unprefix(policy['sha256']), rule_id='rule_' + sha(rule)[:32],
                                  gate_kind=rule['gate']) for rule in gate_context.policy['gates']]
        documents = service._snapshot(fs, pointer, candidate['project_revision'])
        variant = next(v for v in documents['variants', 'project']['value'] if v['variant_id'] == candidate['variant_id'])
        public['profile_ref'] = {**variant['profile'], 'sha256': unprefix(variant['profile']['sha256'])}
        public['review_refs'] = [{'review_id': r} for r in sorted({r for g in gates['gates'] for r in g['review_ids']})]
        return public

    def require_gates(self, db, context, pre):
        public = self.candidate(db, context, {}, {})
        if public['candidate_sha256'] != pre['candidate_sha256']:
            fail('CANDIDATE_CHANGED', 'Candidate bytes differ from the selected exact pin.')
        if public['gate_revision'] != pre['gate_revision']:
            fail('GATE_CHANGED', 'Gate dependencies/evidence changed; refresh candidate.')
        return public

    def check(self, db, context, input, pre):
        public = self.require_gates(db, context, pre)
        service, binding, candidate = self._candidate(db, context, context['params']['candidate_id'])
        if not context.get('host_session_id'):
            fail('AUTHORITY_REQUIRED', 'Candidate checks need a trusted exact-plan Hermes authorization context.')
        if input['recipe_ref'] != 'native_candidate_check_v1':
            fail('CAPABILITY_MISSING', 'Candidate-check recipe is not advertised.')
        if input['parameters'] or any(r not in public['gate_refs'] for r in input['gate_refs']):
            fail('GATE_REF_INVALID', 'Check selection is not an exact current policy rule.')
        parameters = {'candidate_id': context['params']['candidate_id'], 'candidate_sha256': pre['candidate_sha256'],
                      'gate_revision': pre['gate_revision'], 'gate_refs': input['gate_refs']}
        return self.launch_preflight(db, context, input['preflight_id'], 'candidate_check', parameters)

    def launch_preflight(self, db, context, identity, action, parameters):
        retained = self.get(db, context, 'preflight', identity)
        public = retained['public']
        if (public['action'] != action or public['parameters_sha256'] != sha(parameters)
                or public['version_id'] != context['version']['version_id'] or public['blockers']):
            fail('PLAN_STALE', 'Execution differs from its own exact preflight parameters/version.')
        data = self._submit_plan(context, retained['plan'], retained['private_revision'], action)
        self.track_job(db, context, data['job'])
        return self._job_public(data['job'])

    def review(self, db, context, input, pre):
        public = self.require_gates(db, context, pre)
        service, binding, candidate = self._candidate(db, context, context['params']['candidate_id'])
        if input['gate_ref'] not in public['gate_refs']:
            fail('GATE_REF_INVALID', 'Review rule is not from the pinned candidate policy.')
        if input['review_kind'] != 'human_editorial' or input['check_recipe_ref'] is not None:
            fail('REVIEW_AUTHORITY_INVALID', 'Measured checks must come from owned check-job collection, not renderer assertions.')
        if input['evidence_refs'] or input['findings']:
            fail('EVIDENCE_MISSING', 'Public evidence/finding translation requires exact retained artifacts; no arbitrary core pins are accepted.')
        ranges = []
        for coverage in input['coverage']:
            if coverage['file_id'] != public['media']['media_id'] or set(coverage) != {'file_id', 'start_frame', 'end_frame'}:
                fail('COVERAGE_INVALID', 'Coverage must bind exact candidate media frames.')
            if type(coverage['start_frame']) is not int or type(coverage['end_frame']) is not int or not 0 <= coverage['start_frame'] < coverage['end_frame']:
                fail('COVERAGE_INVALID', 'Coverage must contain a nonempty integer frame range.')
            ranges.append({k: coverage[k] for k in ('start_frame', 'end_frame')})
        attribution = context.get('host_review_attribution')
        if not callable(attribution):
            fail('REVIEW_AUTHORITY_UNAVAILABLE', 'An identified trusted review attribution bridge is required.')
        service.reviews.attribution = attribution
        verifier = context.get('host_review_verifier')
        if not callable(verifier):
            fail('REVIEW_AUTHORITY_UNAVAILABLE', 'A trusted exact-evidence review verifier is required.')
        service.reviews.verify_review = verifier
        args = dict(action='record', project_id=context['private_project_id'], request_id=command_id(context, 'review'),
                    candidate=binding['pin'], expected_candidate_manifest_sha256=digest(candidate),
                    gate=input['gate_ref']['gate_kind'], result='pass' if input['decision'] == 'pass' else 'fail', method='user',
                    coverage=dict(frame_ranges=ranges, sample_ranges=[], scene_ids=[], transition_keys=[],
                                  whole_decode=False, playback='not_tested'), evidence=[], findings=[],
                    reason='Authenticated human editorial observation; coverage does not claim decoder/playback measurement.')
        data = service.reviews.dispatch(args)
        # Do not expose private core subject/project references.
        record = data.get('review', data)
        return {k: record[k] for k in ('review_id', 'gate', 'result', 'method', 'created_at', 'reason') if k in record}

    def promote(self, db, context, input, pre):
        context = {**context, 'params': {**context['params'], 'candidate_id': input['candidate_id']}}
        public = self.require_gates(db, context, pre)
        service, binding, candidate = self._candidate(db, context, input['candidate_id'])
        if input['variant_id'] != candidate['variant_id']:
            fail('DELIVERY_BLOCKED', 'Variant is not the selected exact candidate variant.')
        if input['profile_ref'] != public['profile_ref'] or input['review_refs'] != public['review_refs']:
            fail('GATES_STALE', 'Profile or selected review pins differ from the exact current candidate.')
        if any(r not in public['gate_refs'] for r in input['required_gate_refs']):
            fail('GATE_REF_INVALID', 'Promotion must reference exact current policy rules.')
        if set(input['selected_file_ids']) != {public['media']['media_id']}:
            fail('DELIVERY_BLOCKED', 'Promotion file selection differs from the exact candidate.')
        # Native promotion independently reevaluates every required gate, not
        # merely the caller-supplied subset of rule/review references.
        data = service.dispatch(dict(action='promote', project_id=context['private_project_id'],
            expected_revision=context['private_project_revision'], request_id=command_id(context, 'promote'),
            candidate=binding['pin'], expected_candidate_manifest_sha256=digest(candidate),
            expected_master_revision=pre['expected_master_revision']))
        master = data.get('master', data)
        return {k: master[k] for k in ('master_id', 'revision', 'variant_id', 'created_at') if k in master}

    def package(self, db, context, input, pre):
        if not context.get('host_session_id'):
            fail('AUTHORITY_REQUIRED', 'Package execution requires a trusted Hermes authorization context.')
        # Existing native route compiles its exact registered recipe. Input
        # format/flavor mappings must be explicit, never generic tool passthrough.
        if input['recipe_ref'] != 'native_package_v1' or input['format'] != 'zip' or not input['include_source']:
            fail('CAPABILITY_MISSING', 'Only native_package_v1 editable ZIP is supported.')
        service = self.delivery(context)
        fs = service.store._filesystem()
        masters = service._records(fs, context['private_project_id'], 'masters')
        ids = []
        for ref in input['master_refs']:
            master = next((m for m in masters if m['master_id'] == ref['master_id']), None)
            if master is None or master['revision'] != ref['master_revision'] or unprefix(master['candidate']['sha256']) != ref['candidate_sha256']:
                fail('MASTER_CONFLICT', 'Package master selection is stale or out of scope.')
            ids.append(master['master_id'])
        if not ids or len(ids) != len(set(ids)) or input['source_refs'] or input['sidecar_file_ids']:
            fail('CAPABILITY_MISSING', 'Native portable package requires whole master-owned source/sidecar closure, not an arbitrary subset.')
        parameters = {k: input[k] for k in ('master_refs', 'format', 'include_source', 'source_refs', 'sidecar_file_ids', 'reconstruct')}
        return self.launch_preflight(db, context, input['preflight_id'], 'package', parameters)

    def package_get(self, db, context, input, pre):
        service = self.delivery(context)
        page = service.dispatch(dict(action='status', project_id=context['private_project_id'], section='packages'))
        record = next((r for r in page['items'] if r['package_id'] == context['params']['package_id']), None)
        if record is None:
            fail('NOT_FOUND', 'Package is not committed in this composition.')
        return {k: record[k] for k in ('package_id', 'revision', 'state', 'created_at', 'updated_at', 'format') if k in record}

    def package_check(self, db, context, input, pre):
        if not context.get('host_session_id'):
            fail('AUTHORITY_REQUIRED', 'Package validation needs trusted exact-plan authorization.')
        if input['recipe_ref'] != 'native_package_check_v1':
            fail('CAPABILITY_MISSING', 'Package-check recipe is not advertised.')
        service = self.delivery(context)
        records = service._records(service.store._filesystem(), context['private_project_id'], 'packages')
        versions = [p for p in records if p['package_id'] == context['params']['package_id']]
        if not versions:
            fail('NOT_FOUND', 'Package is unavailable.')
        package = max(versions, key=lambda p: p['revision'])
        if package['revision'] != pre['entity_revision'] or unprefix(package['manifest']['sha256']) != pre['manifest_sha256']:
            fail('REVISION_CONFLICT', 'Package revision or manifest differs.')
        parameters = dict(package_id=package['package_id'], entity_revision=package['revision'], manifest_sha256=pre['manifest_sha256'])
        return self.launch_preflight(db, context, input['preflight_id'], 'package_check', parameters)

    def masters(self, db, context, input, pre):
        service = self.delivery(context)
        page = service.dispatch(dict(action='status', project_id=context['private_project_id'], section='masters',
                                     **{k: input[k] for k in ('variant_id', 'limit', 'cursor') if k in input}))
        return {'items': [{k: m[k] for k in ('master_id', 'revision', 'variant_id', 'created_at') if k in m}
                          for m in page['items']], 'next_cursor': page.get('next_cursor')}

    def master_get(self, db, context, input, pre):
        service = self.delivery(context)
        records = service._records(service.store._filesystem(), context['private_project_id'], 'masters')
        record = next((m for m in records if m['master_id'] == context['params']['master_id'] and
                       m['revision'] == input['master_revision']), None)
        if record is None:
            fail('NOT_FOUND', 'Master revision is unavailable.')
        files = self.files(db, context, {'master_ids': [record['master_id']]}, {})['items']
        return {**{k: record[k] for k in ('master_id', 'revision', 'variant_id', 'created_at') if k in record}, 'files': files}

    def packages(self, db, context, input, pre):
        page = self.delivery(context).dispatch(dict(action='status', project_id=context['private_project_id'],
                section='packages', **{k: input[k] for k in ('limit', 'cursor') if k in input}))
        items = [{k: p[k] for k in ('package_id', 'revision', 'state', 'created_at', 'blockers') if k in p}
                 for p in page['items'] if not input.get('state') or p['state'] == input['state']]
        return {'items': items, 'next_cursor': page.get('next_cursor')}

    def reviews(self, db, context, input, pre):
        service, binding, candidate = self._candidate(db, context, context['params']['candidate_id'])
        page = service.reviews.dispatch(dict(action='list', project_id=context['private_project_id'],
            candidate=binding['pin'], **{k: input[k] for k in ('limit', 'cursor') if k in input}))
        return {'items': [{k: r[k] for k in ('review_id', 'gate', 'result', 'method', 'created_at', 'reason') if k in r}
                          for r in page['items']], 'next_cursor': page.get('next_cursor')}

    def files(self, db, context, input, pre):
        if not input.get('master_ids') and not input.get('package_id'):
            fail('INVALID_ARGUMENT', 'Select committed masters or a package.')
        args = {'action': 'files', 'project_id': context['private_project_id']}
        for k in ('master_ids', 'package_id', 'limit', 'cursor'):
            if k in input:
                args[k] = input[k]
        # NativeDeliveryService rechecks current release gates. Its private
        # delivery_handle is discarded; consumers get opaque authenticated media.
        page = self.delivery(context).dispatch(args)
        files = []
        for file in page['items']:
            public = self.media.register_output(db, context, context['private_project_id'],
                                                file['artifact'], file['filename'])
            files.append({**public, 'role': file['role'], 'verification': file['verification']})
        return {'items': files, 'next_cursor': page.get('next_cursor')}

    def derivative(self, db, context, input, pre):
        if input['kind'] not in ('thumbnail', 'waveform', 'proxy'):
            fail('DERIVATIVE_UNSUPPORTED', 'Derivative kind is not supported.')
        fail('DERIVATIVE_UNSUPPORTED', 'No approved exact derivative recipe is advertised; source playback remains available without a synthetic proxy.')


def build_integrations(root, native_registry, root_broker):
    """Construct lazy adapters. Does not import engines, scan files or execute.

    Parent host may keep _media_store, and inject qualified_media_transports,
    host_session_id/task_id/review_attribution into callback contexts. These are
    host-private capabilities, never accepted as renderer JSON or approvals.
    """
    media = UIMedia(root, native_registry, root_broker)
    execution = UIExecution(media)
    integrations: dict[str, Any] = {op: media.callback for op in media.OPERATIONS}
    integrations.update({op: execution.callback for op in execution.OPERATIONS})
    integrations['_media_store'] = media
    integrations['_asset_source_resolver'] = media.resolve_source
    integrations['_execution_adapter'] = execution
    return integrations
