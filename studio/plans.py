"""B06 frozen DAG compiler. Validation and local metadata commits only.

Core integrations are explicit: artifact_resolver(project_id, ArtifactRef) must
verify ownership, original/reference bytes and return ArtifactRecord metadata;
timing_validator(project_id, request, input_metadata, documents) returns explicit
loss strings, or raises ContractError. Without them affected routes fail closed.
reuse_lookup(project_id, fingerprint, expected_outputs) returns ordered refs or
None; every returned ref is revalidated. No provider selection/execution occurs.
"""
from __future__ import annotations

import copy
import uuid

from .capabilities import (ADAPTER, BOOL, DEFS, DIGEST, KEY, OPERATION, PAGINATION,
    PARAMS, TEXT, UUID_PATTERN, CapabilityRegistry, checked, expanded)
from .contracts import (ContractError, arr, canonical, digest, enum, ident, integer,
    mapping, nullable, obj, ref, string, validate)
from .project import _now
from .options import SELECTION_SCHEMA

INPUT = {'oneOf': [obj({'kind': {'const': 'artifact'}, 'artifact': ref('ArtifactRef')}),
    obj({'kind': {'const': 'document'}, 'document': ref('DocumentRef')}),
    obj({'kind': {'const': 'node_output'}, 'target_key': KEY, 'port': TEXT})]}
# Required, optional and array input ports. Empty arrays remain explicit; no
# undeclared input, missing port or implicit conversion is accepted.
PORTS = {
    'media.probe@1': ('media', '', ''), 'media.stage@1': ('', '', ''),
    'asset.acquire@1': ('', '', ''),
    'media.extract_frame@1': ('media', '', ''), 'media.extract_audio@1': ('media', '', ''),
    'media.transform@1': ('media', '', ''), 'media.matte@1': ('media', '', ''),
    'media.reframe@1': ('media', '', ''),
    'speech.transcribe@1': ('audio', '', ''), 'speech.align@1': ('audio caption', '', ''),
    'speech.synthesize@1': ('text', 'reference_audio reference_text', ''), 'asset.search@1': ('query', '', ''),
    'image.generate@1': ('prompt references', '', 'references'), 'image.edit@1': ('image prompt references', '', 'references'),
    'video.generate@1': ('prompt references', '', 'references'), 'scene.author@1': ('scene assets', '', 'assets'),
    'scene.render@1': ('source assets', '', 'assets'), 'scene.frame@1': ('source assets', '', 'assets'),
    'ui.compose@1': ('source assets', '', 'assets'), 'ui.frame@1': ('source assets', '', 'assets'),
    'edit.assemble@1': ('timeline media', '', 'media'), 'audio.generate@1': ('prompt', '', ''),
    'audio.mix@1': ('audio cue_sheet', '', 'audio'), 'audio.measure@1': ('audio', '', ''),
    'audio.normalize@1': ('audio', '', ''), 'media.color@1': ('media config', '', ''),
    'audio.cleanup@1': ('audio', '', ''), 'audio.duck@1': ('music speech', '', ''),
    'caption.layout@1': ('caption placement style fonts', '', 'fonts'),
    'caption.render@1': ('caption placement style fonts background', '', 'fonts'),
    'caption.export@1': ('caption', 'placement', ''), 'delivery.encode@1': ('media', 'audio captions sidecars sidecar_manifest', 'sidecars'),
    'review.check@1': ('candidate evidence', '', 'evidence'), 'inspection.visual@1': ('frames brief references', '', 'frames references'),
    'inspection.audio@1': ('audio references', '', 'references'), 'inspection.playback@1': ('candidate', '', ''),
    'delivery.package@1': ('', 'masters sources sidecars provenance archive manifest', 'masters sources sidecars')}
EXPECTED_PORTS = {
    'media.probe@1': 'report', 'media.stage@1': 'media', 'media.extract_frame@1': 'frame', 'media.extract_audio@1': 'audio',
    'asset.acquire@1': 'media report',
    'media.transform@1': 'media', 'media.matte@1': 'foreground matte', 'speech.transcribe@1': 'caption',
    'speech.align@1': 'caption', 'speech.synthesize@1': 'audio', 'asset.search@1': 'report',
    'image.generate@1': 'image', 'image.edit@1': 'image', 'video.generate@1': 'media', 'scene.author@1': 'source',
    'scene.render@1': 'media source report', 'scene.frame@1': 'frame source report', 'edit.assemble@1': 'media source', 'audio.generate@1': 'audio',
    'ui.compose@1': 'media source report', 'ui.frame@1': 'frame source report',
    'audio.mix@1': 'audio source', 'audio.measure@1': 'report',
    'audio.normalize@1': 'audio report', 'media.color@1': 'media report', 'caption.layout@1': 'layout',
    'audio.cleanup@1': 'audio report', 'audio.duck@1': 'audio report', 'media.reframe@1': 'media trace',
    'caption.render@1': 'media frame', 'caption.export@1': 'sidecar receipt', 'delivery.encode@1': 'candidate',
    'review.check@1': 'report', 'inspection.visual@1': 'report', 'inspection.audio@1': 'report',
    'inspection.playback@1': 'report', 'delivery.package@1': 'archive report'}


def task_schema(operation):
    required, optional, arrays = (set(p.split()) for p in PORTS[operation])
    inputs = obj({p: arr(INPUT) if p in arrays else INPUT for p in sorted(required | optional)}, optional)
    fields = {'target_key': KEY, 'operation': {'const': operation}, 'inputs': inputs,
        'parameters': PARAMS[operation], 'required_features': arr(TEXT, unique=True), 'adapter_id': ADAPTER,
        'binding_parameters': ref('RegisteredOptions'), 'selection': SELECTION_SCHEMA}
    optional_fields = ['required_features', 'adapter_id', 'binding_parameters', 'selection']
    if operation == 'speech.synthesize@1':
        fields.update(voice_preferences=ref('VoicePreferences'), use_voice_defaults=BOOL)
        fields['parameters'] = {'oneOf': [PARAMS[operation], obj({})]}
        optional_fields.extend(['voice_preferences', 'use_voice_defaults'])
    return obj(fields, optional_fields)


TASK_SCHEMA = {'oneOf': [task_schema(op) for op in sorted(PARAMS)]}
DEFS['TaskRequest'] = TASK_SCHEMA
DEFS['PlanRef'] = obj({'plan_id': ident('pln'), 'plan_revision': {'const': 1}, 'plan_sha256': DIGEST})
DEFS['Gap'] = obj({'target_key': KEY, 'code': TEXT, 'operation': OPERATION,
    'missing_features': arr(TEXT, unique=True), 'reason': TEXT, 'alternatives': arr(ADAPTER, unique=True)})
COMPILED_INPUT = {'oneOf': INPUT['oneOf'][:2] + [obj({'kind': {'const': 'node_output'}, 'node_id': ident('nod'), 'port': TEXT})]}
DEFS['PlanNode'] = obj({'node_id': ident('nod'), 'target_key': KEY, 'operation': OPERATION,
    'dependencies': arr(ident('nod'), unique=True), 'inputs': mapping({'oneOf': [COMPILED_INPUT, arr(COMPILED_INPUT)]}),
    'parameters': {'anyOf': list(PARAMS.values())}, 'binding': ref('FrozenBinding'),
    'expected_outputs': arr(ref('ExpectedOutput'), 1), 'fingerprint': DIGEST,
    'reuse': nullable(arr(ref('ArtifactRef'))), 'conversion_losses': arr(TEXT),
    'selection': SELECTION_SCHEMA}, ['selection'])
PLAN_RECORD_SCHEMA = obj({'schema': {'const': 'motion/v1/plan'}, 'plan_id': ident('pln'), 'plan_revision': {'const': 1},
    'project_id': ident('prj'), 'project_revision': integer(1), 'snapshot_sha256': DIGEST, 'created_at': DEFS['ProjectRecord']['properties']['created_at'],
    'requests': arr(ref('TaskRequest'), 1), 'targets': arr(KEY, 1, True), 'nodes': arr(ref('PlanNode')),
    'status': enum('ready', 'blocked'), 'gaps': arr(ref('Gap')), 'effects': arr(ref('Effects')), 'plan_sha256': DIGEST})
DEFS['PlanRecord'] = PLAN_RECORD_SCHEMA
PLAN_REQUEST_SCHEMA = {'oneOf': [
    obj({'action': {'const': 'compile'}, 'project_id': ident('prj'), 'request_id': string(UUID_PATTERN),
        'expected_revision': integer(1), 'requests': arr(ref('TaskRequest'), 1), 'targets': arr(KEY, 1, True), 'reuse_outputs': BOOL}, ['reuse_outputs']),
    obj({'action': {'const': 'list'}, 'project_id': ident('prj'), 'state': enum('ready', 'blocked'), **PAGINATION}, ['state', *PAGINATION]),
    obj({'action': {'const': 'inspect'}, 'project_id': ident('prj'), 'plan': ref('PlanRef'),
        'section': enum('summary', 'nodes', 'effects', 'gaps'), **PAGINATION}, ['section', *PAGINATION])]}


def plan_tool_schema(registry=None):
    definitions = DEFS if registry is None else {**DEFS, 'RegisteredOptions': registry.options_schema()}
    return expanded(PLAN_REQUEST_SCHEMA, definitions)


def _error(code, reason):
    raise ContractError(code, reason)


def _bindings(inputs):
    for port, value in inputs.items():
        for binding in value if isinstance(value, list) else [value]:
            yield port, binding


def _kind_allowed(port, kind, media_type):
    expected = {'media': {'media', 'image', 'frame', 'audio'}, 'audio': {'audio'}, 'reference_audio': {'audio'}, 'music': {'audio'}, 'speech': {'audio'}, 'caption': {'caption'},
        'captions': {'caption'}, 'source': {'scene_source', 'assembly_source'}, 'image': {'image', 'frame'},
        'frames': {'frame', 'image'}, 'candidate': {'media'}, 'background': {'media', 'image', 'frame'},
        'fonts': {'font'}, 'archive': {'archive'}, 'masters': {'media'}, 'sidecars': {'caption'},
        'sources': {'scene_source', 'assembly_source'}}
    if port in expected:
        return kind in expected[port]
    if port in ['prompt', 'query', 'text', 'reference_text']:
        return media_type == 'text/plain'
    if port in ['placement', 'cue_sheet', 'style', 'timeline', 'scene', 'brief', 'manifest', 'provenance']:
        return media_type == 'application/json' or media_type.startswith('application/vnd.motion.')
    return True


class PlanCompiler:
    def __init__(self, store, registry: CapabilityRegistry, *, artifact_resolver=None,
                 timing_validator=None, reuse_lookup=None, manifest_resolver=None,
                 engine_identity=None, host_bridge=None):
        self.store, self.registry = store, registry
        self.artifact_resolver = artifact_resolver
        self.timing_validator, self.reuse_lookup = timing_validator, reuse_lookup
        from .engine_identity import local_engine_identity
        self.engine_identity = local_engine_identity if engine_identity is None else engine_identity
        self.host_bridge = host_bridge
        self.manifest_resolver = manifest_resolver

    def _checked(self, value, schema):
        validate(value, expanded(schema, {**DEFS, 'RegisteredOptions': self.registry.options_schema()}))

    @classmethod
    def from_core(cls, store, registry, **dependencies):
        """Wire B04 verified resolution without creating a second artifact store.

        B05 pure timeline validation is run here; per-operation compatibility
        remains explicit until probe-receipt lookup is integrated. A caller may
        inject a stricter timing_validator, never a renderer or model initializer.
        """
        from .assets import AssetRegistry
        assets = AssetRegistry(store)
        def resolve(project_id, pin):
            fs = store._filesystem()
            pointer = store._pointer(fs, project_id)
            return assets.artifact(fs, pointer, pin)
        dependencies.setdefault('artifact_resolver', resolve)
        return cls(store, registry, **dependencies)

    @staticmethod
    def plan_ref(plan):
        return {k: plan[k] for k in ['plan_id', 'plan_revision', 'plan_sha256']}

    @staticmethod
    def _hash(plan):
        return digest({k: v for k, v in plan.items() if k not in ['plan_sha256', 'created_at']})

    def load(self, project_id, pin, fs=None):
        checked(project_id, ident('prj')); checked(pin, ref('PlanRef'))
        fs = fs or self.store._filesystem()
        record = fs.read(f"projects/{project_id}/plans/{pin['plan_id']}/plan.json")
        plan = record['plan']
        closure = record.get('schema_closure', {})
        for node in plan.get('nodes', []):
            aid = node['binding']['adapter_id']
            if aid not in closure or digest(closure[aid]) != node['binding']['schema_sha256']:
                _error('HASH_MISMATCH', 'Frozen adapter schema closure is missing or changed.')
        option_choices = {}
        for bundle in closure.values():
            for sid, schema in bundle['schemas'].items():
                sha = digest(schema)
                option_choices[(sid, sha)] = obj({'schema_id': {'const': sid}, 'schema_sha256': {'const': sha}, 'values': schema})
        options = {'oneOf': list(option_choices.values())} if option_choices else DEFS['RegisteredOptions']
        validate(plan, expanded(PLAN_RECORD_SCHEMA, {**DEFS, 'RegisteredOptions': options}))
        if record.get('schema') != 'motion/v1/plan-commit':
            _error('SCHEMA_UNSUPPORTED', 'Unsupported frozen plan commit.')
        if plan['project_id'] != project_id:
            _error('WRONG_PROJECT', 'Plan belongs to another project.')
        if self.plan_ref(plan) != pin or self._hash(plan) != plan['plan_sha256']:
            _error('HASH_MISMATCH', 'Frozen plan identity or digest differs.')
        return copy.deepcopy(plan)

    def _artifact(self, project_id, pin):
        if self.artifact_resolver is None:
            _error('DEPENDENCY_UNAVAILABLE', 'Verified core artifact resolver is not integrated.')
        metadata = self.artifact_resolver(project_id, copy.deepcopy(pin))
        if not isinstance(metadata, dict) or metadata.get('project_id') != project_id:
            _error('WRONG_PROJECT', 'Artifact resolver did not establish project ownership.')
        if any(metadata.get(k) != pin[k] for k in ['artifact_id', 'sha256']):
            _error('HASH_MISMATCH', 'Artifact identity/bytes disagree with the pin.')
        if not isinstance(metadata.get('kind'), str) or not isinstance(metadata.get('media_type'), str):
            _error('DEPENDENCY_UNAVAILABLE', 'Artifact resolver must supply canonical kind and media type.')
        return metadata

    def compile(self, args):
        self._checked(args, PLAN_REQUEST_SCHEMA)
        if args['action'] != 'compile':
            _error('INVALID_ARGUMENT', 'compile requires compile action.')
        args = copy.deepcopy(args)
        args.setdefault('reuse_outputs', True)
        # All persisted semantic fields, including default feature sets and probe
        # defaults, are explicit and validated before acquiring a write lock.
        for task in args['requests']:
            task.setdefault('required_features', [])
            task['required_features'].sort()
            task['parameters'] = self.registry.validate_parameters(task['operation'], task['parameters'])
        fs = self.store._filesystem(write=True)
        base = self.store._base(args['project_id'])
        request_hash = digest(args)
        plan_id = 'pln_' + str(uuid.uuid5(uuid.UUID(args['project_id'][4:]), args['request_id']))
        path = f'{base}/plans/{plan_id}/plan.json'
        pointer = self.store._pointer(fs, args['project_id'])
        try:
            commit = fs.read(path)
        except FileNotFoundError:
            commit = None
        if commit is not None:
            if commit.get('request_sha256') != request_hash:
                _error('IDEMPOTENCY_CONFLICT', 'Request ID was committed with different compile arguments.')
            return self.load(args['project_id'], self.plan_ref(commit['plan']), fs)
        if pointer['revision'] != args['expected_revision']:
            _error('REVISION_CONFLICT', 'Content changed before compile; explicitly recompile the intended revision.')
        snapshot, docs = self.store._load(fs, pointer)
        # Artifact verification/hashing and dependency validation must not hold
        # the content writer lock. Submission rechecks mutable inputs again.
        plan = self._graph(args, pointer, snapshot, docs, plan_id)
        self._checked(plan, PLAN_RECORD_SCHEMA)
        with fs.lock(base + '/locks/content.lock'):
            current = self.store._pointer(fs, args['project_id'])
            try:
                commit = fs.read(path)
            except FileNotFoundError:
                commit = None
            if commit is not None:
                if commit.get('request_sha256') != request_hash:
                    _error('IDEMPOTENCY_CONFLICT', 'Request ID was committed with different compile arguments.')
                return self.load(args['project_id'], self.plan_ref(commit['plan']), fs)
            if current != pointer:
                _error('REVISION_CONFLICT', 'Content changed while preparing the frozen plan.')
            closure = {entry['adapter_id']: self.registry.schema_bundle(entry['adapter_id']) for entry in self.registry.discover()}
            fs.write(path, {'schema': 'motion/v1/plan-commit', 'request_sha256': request_hash, 'plan': plan, 'schema_closure': closure})
        return copy.deepcopy(plan)

    def _graph(self, args, pointer, snapshot, docs, plan_id):
        from .timeline import validate_timeline
        settings = docs['settings', 'project']['value']
        validate_timeline(docs['timeline', 'project']['value'], settings['rate'], settings['sample_rate'],
            scenes={key[1]: doc['value'] for key, doc in docs.items() if key[0] == 'scene'})
        tasks = {t['target_key']: t for t in args['requests']}
        if len(tasks) != len(args['requests']) or any(t not in tasks for t in args['targets']):
            _error('INVALID_ARGUMENT', 'Target keys must be unique and every requested target must resolve.')
        deps = {key: set() for key in tasks}
        for key, task in tasks.items():
            for _, binding in _bindings(task['inputs']):
                if binding['kind'] == 'node_output':
                    other = binding['target_key']
                    if other not in tasks:
                        _error('INVALID_ARGUMENT', 'Node-output target is missing.')
                    if binding['port'] not in EXPECTED_PORTS[tasks[other]['operation']].split():
                        _error('INVALID_ARGUMENT', 'Unknown output port in graph.')
                    deps[key].add(other)
        order, visiting, visited = [], set(), set()
        def visit(key):
            if key in visiting:
                _error('INVALID_ARGUMENT', 'Dependency graph contains a cycle.')
            if key not in visited:
                visiting.add(key)
                for other in sorted(deps[key]):
                    visit(other)
                visiting.remove(key); visited.add(key); order.append(key)
        for key in sorted(args['targets']):
            visit(key)
        if visited != set(tasks):
            _error('INVALID_ARGUMENT', 'Unreachable requests are forbidden; remove unrequested work.')
        pid = args['project_id']
        selection = docs['bindings', 'project']['value']
        selected, preferences, pins = selection['selected_adapter_ids'], selection['preferences'], selection['pins']
        document_pins = {(p['kind'], p['id']): p for p in snapshot['documents']}
        nodes, gaps, effects, by_key = [], [], [], {}
        node_ids = {key: 'nod_' + str(uuid.uuid5(uuid.UUID(plan_id[4:]), key)) for key in tasks}
        for key in order:
            task = tasks[key]; operation = task['operation']
            # Document-valued operation parameters are part of the same frozen
            # snapshot closure as document input ports (never resolve latest).
            for name in ['scene', 'variant_document', 'policy']:
                if name in task['parameters']:
                    pin = task['parameters'][name]
                    if pin != document_pins.get((pin['kind'], pin['id'])):
                        _error('HASH_MISMATCH', 'Operation document parameter is not pinned in this snapshot.')
            if operation == 'caption.export@1':
                if ('placement' in task['inputs']) != (task['parameters']['time_origin'] == 'delivery'):
                    _error('INVALID_ARGUMENT', 'Delivery sidecars require placement; source sidecars forbid placement.')
            if operation == 'delivery.package@1':
                wanted = {'archive', 'manifest'} if task['parameters']['mode'] == 'validate_existing' else {'masters', 'sources', 'sidecars', 'provenance'}
                if set(task['inputs']) != wanted:
                    _error('INVALID_ARGUMENT', 'Package inputs must match its exact build/validate mode.')
            def gap(code, reason, alternatives=()):
                gaps.append({'target_key': key, 'code': code, 'operation': operation,
                    'missing_features': sorted(task['required_features']), 'reason': reason, 'alternatives': sorted(alternatives)})
            if any(d not in by_key for d in deps[key]):
                gap('CAPABILITY_MISSING', 'A dependency is blocked; no downstream work can execute.')
                continue
            metadata, semantic_inputs, compiled_inputs, media_types = {}, {}, copy.deepcopy(task['inputs']), []
            failed = False
            for port, binding in _bindings(task['inputs']):
                try:
                    if binding['kind'] == 'artifact':
                        info = self._artifact(pid, binding['artifact'])
                        semantic = {'kind': 'artifact', **binding['artifact']}
                    elif binding['kind'] == 'document':
                        p = binding['document']; expected = document_pins.get((p['kind'], p['id']))
                        if p != expected:
                            _error('HASH_MISMATCH', 'Document pin is not in this immutable content snapshot.')
                        info = {'kind': 'caption' if p['kind'] == 'caption' else 'json',
                                'media_type': 'application/json', 'document': p}
                        semantic = binding
                    else:
                        parent = by_key[binding['target_key']]
                        info = next((o for o in parent['expected_outputs'] if o['port'] == binding['port']), None)
                        if info is None:
                            _error('INVALID_ARGUMENT', 'Bound result schema does not declare requested output port.')
                        semantic = {'kind': 'node_output', 'fingerprint': parent['fingerprint'], 'port': binding['port']}
                    if not _kind_allowed(port, info['kind'], info['media_type']):
                        _error('INVALID_ARGUMENT', 'Input artifact kind/media type is incompatible with its named port.')
                    metadata.setdefault(port, []).append(info)
                    semantic_inputs.setdefault(port, []).append(semantic)
                    if binding['kind'] != 'document':
                        media_types.append(info['media_type'])
                except ContractError as exc:
                    if exc.code in ['INVALID_ARGUMENT', 'WRONG_PROJECT', 'HASH_MISMATCH', 'ASSET_CHANGED', 'PATH_UNSAFE']:
                        raise
                    gap(exc.code, exc.message); failed = True; break
            if failed:
                continue
            for _, binding in _bindings(compiled_inputs):
                if binding['kind'] == 'node_output':
                    binding['node_id'] = node_ids[binding.pop('target_key')]
            # Semantic features implied by explicit parameters must not be
            # downgraded merely because the caller omitted required_features.
            features = set(task['required_features'])
            p = task['parameters']
            if p.get('granularity') == 'word': features.add('speech.words')
            if p.get('diarize'): features.add('speech.diarization')
            if p.get('alpha') in ['straight', 'premultiplied']: features.add('video.alpha' if operation == 'scene.render@1' else 'image.alpha')
            if operation == 'media.transform@1' and p['kind'] == 'rate_conform': features.add('timing.vfr_conform')
            if operation == 'media.transform@1' and p['kind'] == 'retime' and p['spec']['preserve_audio_pitch']: features.add('audio.pitch_preserve')
            compatible = self.registry.match(operation, sorted(features), selected, p, media_types)
            option_selection = task.get('selection')
            pin = task.get('adapter_id', pins.get(operation))
            if option_selection is not None:
                if pin is not None and pin != option_selection['adapter_id']:
                    _error('INVALID_ARGUMENT', 'Option selection contradicts the explicitly pinned adapter.')
                pin = option_selection['adapter_id']
            if task.get('adapter_id') and pins.get(operation) and pins[operation] != task['adapter_id']:
                _error('INVALID_ARGUMENT', 'Task adapter contradicts project operation pin.')
            alternatives = [r['adapter_id'] for r in self.registry.discover(operation=operation, required_features=sorted(features))
                            if r['availability'] == 'available']
            if pin:
                choices = [pin] if pin in compatible else []
            else:
                ranked = [aid for aid in preferences.get(operation, []) if aid in compatible]
                choices = ranked[:1] or (compatible if len(compatible) == 1 else [])
            if not choices:
                code = 'CAPABILITY_MISSING'
                reason = 'No uniquely selected available binding satisfies exact operation/features/constraints; select or pin explicitly.'
                named = pin or (selected[0] if len(selected) == 1 else None)
                if named:
                    try:
                        observed = self.registry.inspect(named)
                        state = observed['availability']['state']
                        reason = f'Binding {named}: availability={state}; exact operation/features/constraints must all match.'
                        if state == 'disabled': code = 'ADAPTER_DISABLED'
                        elif state != 'available': code = 'DEPENDENCY_UNAVAILABLE'
                    except ContractError:
                        code, reason = 'DEPENDENCY_UNAVAILABLE', f'Selected binding {named} is not installed/registered.'
                gap(code, reason, alternatives)
                advertised = set()
                for summary in self.registry.discover(operation=operation):
                    if summary['adapter_id'] in ([pin] if pin else selected):
                        advertised.update(summary['features'])
                gaps[-1]['missing_features'] = sorted(features - advertised)
                continue
            aid = choices[0]
            try:
                binding = self.registry.binding(aid, operation, p, task.get('binding_parameters'))
                if option_selection is not None:
                    from .options import validate_selection
                    observed_binding = validate_selection(self.registry, option_selection,
                        operation=operation, parameters=p,
                        binding_parameters=task.get('binding_parameters'), bridge=self.host_bridge,
                        required_features=sorted(features))
                    if observed_binding != binding:
                        _error('ADAPTER_INCOMPATIBLE', 'Option selection differs from the compiled executable binding.')
                # Gate the actual selected identity, not a diagnostic-only candidate.
                # An incompatible preferred mapping blocks rather than falling back.
                from .tool_integration import require_compatible_binding
                require_compatible_binding(self.registry, binding, operation=operation,
                    parameters=p, binding_parameters=task.get('binding_parameters'), bridge=self.host_bridge)
            except ContractError as exc:
                gap(exc.code, exc.message, alternatives); continue
            output_specs = self.registry.outputs(aid, operation, p)
            if any(o['port'] not in EXPECTED_PORTS[operation].split() for o in output_specs):
                _error('SCHEMA_UNSUPPORTED', 'Adapter result ports do not match the operation vocabulary.')
            losses = []
            needs_timing = operation not in ['media.probe@1', 'media.stage@1', 'asset.search@1', 'image.generate@1', 'image.edit@1', 'speech.synthesize@1', 'scene.author@1', 'inspection.visual@1']
            if needs_timing and self.timing_validator is None:
                gap('DEPENDENCY_UNAVAILABLE', 'Core timing/compatibility validator is not integrated; conversions cannot be guessed.')
                continue
            if needs_timing and self.timing_validator is not None:
                # Pure compatibility checks need the resolved binding even when
                # the caller selected it through project pins/preferences. Do not
                # mutate caller intent or the frozen requests with that choice.
                timing_task = {**copy.deepcopy(task), 'adapter_id': aid}
                losses = self.timing_validator(pid, timing_task, copy.deepcopy(metadata), copy.deepcopy(docs))
                checked(losses, arr(TEXT))
            route_effects = self.registry.effects(aid)
            policy = docs['settings', 'project']['value']['policy']
            if route_effects['uploads'] and (policy['remote'] == 'deny' or not set(route_effects['destinations']) <= set(policy['allowed_destinations'])):
                gap('PERMISSION_DENIED', 'Frozen execution policy forbids this upload destination.'); continue
            if route_effects['pricing'] != 'free' and policy['paid'] == 'deny':
                gap('PERMISSION_DENIED', 'Frozen execution policy forbids paid/unknown pricing.'); continue
            semantic = {'operation': operation, 'parameters': p, 'binding_parameters': task.get('binding_parameters'),
                'required_features': sorted(features), 'binding': binding, 'inputs': semantic_inputs,
                'policy': policy, 'outputs': output_specs, 'effects': route_effects, 'conversion_losses': losses}
            if option_selection is not None:
                semantic['option_selection'] = option_selection
            from .engine_identity import semantic_closure
            try:
                semantic['closure'] = semantic_closure(task, docs,
                    artifact_resolver=self.artifact_resolver, project_id=pid)
                if self.engine_identity is not None:
                    semantic['engine'] = self.engine_identity(copy.deepcopy(task), copy.deepcopy(binding))
            except ContractError as exc:
                gap(exc.code, exc.message); continue
            fingerprint = digest(semantic)
            reuse = None
            if args['reuse_outputs'] and self.reuse_lookup is not None:
                candidates = self.reuse_lookup(pid, fingerprint, copy.deepcopy(output_specs))
                if candidates is not None:
                    checked(candidates, arr(ref('ArtifactRef')))
                    if len(candidates) != len(output_specs):
                        _error('INVALID_ARGUMENT', 'Reuse must cover all declared outputs in port order.')
                    for candidate, spec in zip(candidates, output_specs):
                        info = self._artifact(pid, candidate)
                        if (info['kind'], info['media_type']) != (spec['kind'], spec['media_type']):
                            _error('INVALID_ARGUMENT', 'Reused output type differs from frozen result schema.')
                    reuse = candidates
            node = {'node_id': node_ids[key], 'target_key': key, 'operation': operation,
                'dependencies': sorted(node_ids[d] for d in deps[key]), 'inputs': compiled_inputs,
                'parameters': p, 'binding': binding, 'expected_outputs': output_specs,
                'fingerprint': fingerprint, 'reuse': reuse, 'conversion_losses': losses}
            if option_selection is not None:
                node['selection'] = copy.deepcopy(option_selection)
            nodes.append(node); by_key[key] = node
            effects.append(route_effects)
        plan = {'schema': 'motion/v1/plan', 'plan_id': plan_id, 'plan_revision': 1,
            'project_id': pid, 'project_revision': pointer['revision'], 'snapshot_sha256': pointer['snapshot_sha256'],
            'created_at': _now(), 'requests': args['requests'], 'targets': args['targets'], 'nodes': nodes,
            'status': 'blocked' if gaps else 'ready', 'gaps': gaps, 'effects': effects}
        plan['plan_sha256'] = self._hash(plan)
        return plan

    def summary(self, plan):
        return {'plan': self.plan_ref(plan), 'project_revision': plan['project_revision'], 'status': plan['status'],
            'node_count': len(plan['nodes']), 'target_keys': plan['targets'],
            'effects_summary': sorted({name for effect in plan['effects'] for name in ['writes_local', 'uploads', 'generates', 'launches_process'] if effect[name]}),
            'requires_reauthoring': any(g['code'] in ['CAPABILITY_MISSING', 'UNSUPPORTED_FEATURE'] for g in plan['gaps']), 'created_at': plan['created_at']}

    def dispatch(self, args):
        """Data API, raises ContractError; compile blocked result is committed.

        Native handler must return ok=false,status=blocked,error.effect=committed
        when data.plan.status is blocked. No job is ever produced here.
        """
        self._checked(args, PLAN_REQUEST_SCHEMA)
        if args['action'] == 'compile':
            plan = self.compile(args)
            return {'plan': self.summary(plan), 'gaps': plan['gaps']}
        fs = self.store._filesystem()
        self.store._pointer(fs, args['project_id'])
        if args.get('cursor') or args.get('snapshot_id'):
            return self.store._page(fs, {**args, '_tool': 'motion_plan'}, None)
        if args['action'] == 'list':
            items = []
            base = self.store._base(args['project_id']) + '/plans'
            for name in fs.names(base):
                checked(name, ident('pln'))
                record = fs.read(base + '/' + name + '/plan.json')
                plan = self.load(args['project_id'], self.plan_ref(record['plan']), fs)
                if 'state' not in args or plan['status'] == args['state']:
                    items.append(self.summary(plan))
            items.sort(key=lambda item: (item['created_at'], item['plan']['plan_id']))
            return self.store._page(fs, {**args, '_tool': 'motion_plan'}, None if args.get('cursor') or args.get('snapshot_id') else items)
        plan = self.load(args['project_id'], args['plan'], fs)
        section = args.get('section', 'summary')
        if section == 'summary':
            if any(k in args for k in PAGINATION):
                _error('INVALID_ARGUMENT', 'Pagination is only accepted for nodes/effects/gaps.')
            if self.manifest_resolver is None:
                _error('DEPENDENCY_UNAVAILABLE', 'Core plan manifest ArtifactRef publication is not integrated.')
            manifest = self.manifest_resolver(args['project_id'], copy.deepcopy(plan))
            checked(manifest, ref('ArtifactRef'))
            self._artifact(args['project_id'], manifest)
            return {'plan': self.summary(plan), 'manifest': manifest}
        return self.store._page(fs, {**args, '_tool': 'motion_plan'}, None if args.get('cursor') or args.get('snapshot_id') else plan[section])
