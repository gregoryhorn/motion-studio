"""B06 cached declarations and exact matching; never imports or executes engines.

Registration is a trusted code boundary, not a project JSON operation. Schemas,
implementation identities and normalized ports are pinned on registration.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import os
from pathlib import Path
import re
import shutil

from .contracts import (ADAPTER, BOOL, D, DECIMAL, DIGEST, KEY, LABEL, STAMP, TEXT,
                        UUID_PATTERN, ContractError, arr, canonical, digest, enum,
                        ident, integer, mapping, nullable, obj, ref, string, validate)
from .project import ProjectStore, _now

DEFS = copy.deepcopy(D)
EFFECTS_SCHEMA = obj({'writes_local': BOOL, 'uploads': BOOL, 'destinations': arr(TEXT, unique=True),
    'generates': BOOL, 'launches_process': BOOL, 'pricing': enum('free', 'metered', 'subscription', 'unknown'),
    'charging_basis': nullable(TEXT), 'estimate': nullable(obj({'amount': DECIMAL, 'currency': TEXT, 'source': TEXT}))})
DEFS['Effects'] = EFFECTS_SCHEMA
DEFS['RegisteredOptions'] = obj({'schema_id': TEXT, 'schema_sha256': DIGEST,
    'values': {'type': 'object', 'additionalProperties': False}})  # dynamically replaced by the exact registered schema
RANGE = obj({'start_frame': integer(), 'end_frame': integer(1)})
CANVAS = obj({'width_px': integer(1), 'height_px': integer(1)})
RATE = ref('Rate')
DIALOGUE_DECIMAL = string(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', minimum=1, maximum=32)
PARAMS = {
    'asset.acquire@1': obj({'url': TEXT, 'max_bytes': integer(1, 16777216), 'max_duration_seconds': integer(1, 120)}),
    'media.probe@1': obj({'full_decode': BOOL}, ['full_decode']),
    'media.stage@1': obj({'source': {'oneOf': [obj({'kind': {'const': 'local'}, 'path': TEXT}), obj({'kind': {'const': 'remote'}, 'url': TEXT})]}, 'max_bytes': integer(1)}),
    'media.extract_frame@1': obj({'at': ref('TimePoint'), 'format': enum('png', 'jpeg'), 'apply_rotation': BOOL}),
    'media.extract_audio@1': obj({'stream_index': integer(), 'format': enum('wav', 'flac', 'm4a'), 'sample_rate': nullable(integer(1))}),
    'media.matte@1': obj({'temporal': BOOL, 'background': enum('transparent', 'mask'), 'quality': enum('preview', 'final')}),
    'speech.transcribe@1': obj({'language': nullable(TEXT), 'granularity': enum('segment', 'word'), 'diarize': BOOL}),
    'speech.align@1': obj({'language': TEXT, 'granularity': enum('segment', 'word')}),
    'speech.synthesize@1': obj({'language': TEXT, 'voice': TEXT, 'seed': nullable(integer(-9007199254740991))}),
    'asset.search@1': obj({'media_kind': enum('image', 'video', 'audio'), 'limit': integer(1, 100), 'rights_requirement': TEXT}),
    'scene.author@1': obj({'source_format': TEXT}),
    'scene.render@1': obj({'scene': ref('DocumentRef'), 'range': RANGE, 'quality': enum('preview', 'final'), 'alpha': enum('none', 'straight', 'premultiplied'), 'rate': RATE, 'canvas': CANVAS, 'engine': enum('CYCLES','BLENDER_EEVEE_NEXT','BLENDER_WORKBENCH')}, ['rate','canvas','engine']),
    'scene.frame@1': obj({'scene': ref('DocumentRef'), 'frame': integer(), 'alpha': enum('none', 'straight', 'premultiplied'), 'rate': RATE, 'canvas': CANVAS, 'engine': enum('CYCLES','BLENDER_EEVEE_NEXT','BLENDER_WORKBENCH')}, ['rate','canvas','engine']),
    'edit.assemble@1': obj({'range': RANGE, 'canvas': CANVAS, 'rate': RATE}),
    'audio.generate@1': obj({'kind': enum('music', 'sfx'), 'duration_samples': integer(1), 'sample_rate': integer(1), 'seed': nullable(integer(-9007199254740991))}),
    'audio.mix@1': obj({'sample_rate': integer(1), 'duration_samples': integer(1), 'channels': integer(1), 'loudness_lufs': nullable(DECIMAL), 'true_peak_dbtp': nullable(DECIMAL), 'rate': RATE}, ['rate']),
    'audio.normalize@1': obj({'loudness_lufs': DECIMAL, 'true_peak_dbtp': DECIMAL, 'tolerance_lu': DECIMAL}),
    'audio.cleanup@1': obj({
        'denoise': nullable(obj({'reduction_db': DIALOGUE_DECIMAL, 'noise_floor_db': DIALOGUE_DECIMAL})),
        'highpass_hz': nullable(DIALOGUE_DECIMAL), 'lowpass_hz': nullable(DIALOGUE_DECIMAL),
        'eq': {**arr(obj({'frequency_hz': DIALOGUE_DECIMAL, 'gain_db': DIALOGUE_DECIMAL, 'q': DIALOGUE_DECIMAL})), 'maxItems': 8},
        'compressor': nullable(obj({'threshold_db': DIALOGUE_DECIMAL, 'ratio': DIALOGUE_DECIMAL,
            'attack_ms': DIALOGUE_DECIMAL, 'release_ms': DIALOGUE_DECIMAL, 'knee_db': DIALOGUE_DECIMAL, 'makeup_db': DIALOGUE_DECIMAL}))}),
    'audio.duck@1': obj({'threshold_db': DIALOGUE_DECIMAL, 'ratio': DIALOGUE_DECIMAL,
        'attack_ms': DIALOGUE_DECIMAL, 'release_ms': DIALOGUE_DECIMAL, 'knee_db': DIALOGUE_DECIMAL}),
    'media.color@1': obj({'input_space': TEXT, 'output_space': TEXT,
        'output_color': copy.deepcopy(D['Variant']['properties']['color']), 'range_policy': enum('clip')}),
    'audio.measure@1': obj({'checks': arr(enum('loudness', 'true_peak', 'clipping', 'silence'), unique=True)}),
    'caption.layout@1': obj({'variant': KEY, 'renderer_fingerprint': DIGEST}),
    'caption.render@1': obj({'variant': KEY, 'range': RANGE, 'frames': arr(integer(), 1), 'renderer_fingerprint': DIGEST}, ['frames']),
    'caption.export@1': obj({'format': enum('srt', 'vtt', 'ass'), 'rounding': enum('nearest_even', 'coverage'), 'time_origin': enum('source', 'delivery')}),
    'delivery.encode@1': obj({'variant': KEY, 'variant_document': ref('DocumentRef'), 'encoder_options': ref('RegisteredOptions')}),
    'review.check@1': obj({'gate': enum('creative', 'technical', 'art', 'audio', 'delivery_profile'), 'policy': ref('DocumentRef'), 'checks': arr(TEXT, unique=True)}),
    'inspection.visual@1': obj({'criteria': arr(TEXT)}),
    'inspection.audio@1': obj({'criteria': arr(TEXT)}),
    'inspection.playback@1': obj({'sample_frames': arr(integer()), 'check_seek': BOOL, 'check_end': BOOL}),
    'delivery.package@1': obj({'mode': enum('build', 'validate_existing'), 'format': enum('zip', 'tar'), 'reconstruct': BOOL}),
}
for operation in ['image.generate@1', 'image.edit@1', 'video.generate@1']:
    fields = {**CANVAS['properties'], 'seed': nullable(integer(-9007199254740991))}
    if operation.startswith('video'):
        fields.update(duration_frames=integer(1), rate=RATE)
    PARAMS[operation] = obj(fields)
TRANSFORMS = {'crop': obj({'rect': ref('Rect')}), 'scale': obj({**CANVAS['properties'], 'fit': enum('contain', 'cover')}),
    'rate_conform': obj({'rate': RATE, 'method': enum('drop_duplicate', 'optical_flow')}),
    'sample_conform': obj({'sample_rate': integer(1)}), 'rotate': obj({'degrees': {'type': 'integer', 'enum': [0, 90, 180, 270]}}),
    'retime': obj({'speed': RATE, 'preserve_audio_pitch': BOOL}),
    'color': copy.deepcopy(D['Variant']['properties']['color']), 'flatten_alpha': obj({'background': string(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?')})}
PARAMS['media.transform@1'] = {'oneOf': [obj({'kind': {'const': k}, 'spec': v}) for k, v in TRANSFORMS.items()]}
from .adapters.reframe import PARAMS as REFRAME_PARAMS
PARAMS['media.reframe@1'] = copy.deepcopy(REFRAME_PARAMS)
from .adapters.ui_compositor import PARAMS as UI_COMPOSITOR_PARAMS
for operation in ('ui.compose@1', 'ui.frame@1'):
    PARAMS[operation] = copy.deepcopy(UI_COMPOSITOR_PARAMS)
OPERATION = enum(*sorted(PARAMS))
CONSTRAINTS = obj({'media_types': arr(TEXT, unique=True), 'codecs': arr(TEXT, unique=True),
    'max_width_px': nullable(integer(1)), 'max_height_px': nullable(integer(1)), 'min_rate': nullable(RATE),
    'max_rate': nullable(RATE), 'languages': arr(TEXT, unique=True), 'color_spaces': arr(TEXT, unique=True),
    'alpha_modes': arr(TEXT, unique=True), 'timing': enum('frame', 'sample', 'word', 'segment', 'none'),
    'max_duration_frames': nullable(integer(1))})
OP_DECL = obj({'operation': OPERATION, 'request_schema': TEXT, 'result_schema': TEXT, 'features': arr(TEXT, unique=True),
    'constraints': CONSTRAINTS, 'determinism': enum('yes', 'no', 'unknown'),
    'supports': obj({k: BOOL for k in ['status', 'cancel', 'collect', 'resume', 'provider_idempotency', 'lookup_by_request']}),
    'default_timeout_seconds': integer(1)})
DECLARATION_SCHEMA = obj({'schema': {'const': 'motion/v1/adapter-declaration'}, 'adapter_id': ADAPTER,
    'label': LABEL, 'abi_version': string(r'1\.[0-9]+'), 'implementation_version': TEXT,
    'transport': enum('cli', 'python', 'api', 'host_handoff', 'gui_handoff'), 'location': enum('local', 'remote', 'agent'),
    'operations': arr(OP_DECL, 1), 'dependencies': arr(obj({'name': LABEL,
        'kind': enum('executable', 'library', 'model_file', 'endpoint', 'host_tool'), 'version_constraint': nullable(TEXT), 'required': BOOL})),
    'credential_refs': arr(TEXT, unique=True), 'effects': EFFECTS_SCHEMA, 'license': nullable(TEXT),
    'resource_needs': obj({'cpu_threads': nullable(integer(1)), 'ram_bytes': nullable(integer(1)),
        'gpu_vram_bytes': nullable(integer(1)), 'exclusive_resource': nullable(TEXT)})})
DEFS['AdapterDeclaration'] = DECLARATION_SCHEMA
DEFS['FrozenBinding'] = obj({'adapter_id': ADAPTER, 'implementation_version': TEXT, 'implementation_sha256': DIGEST,
    'abi_version': TEXT, 'request_schema': TEXT, 'result_schema': TEXT, 'schema_sha256': DIGEST})
DEFS['ExpectedOutput'] = obj({'port': TEXT, 'kind': enum('report', 'caption', 'scene_source', 'assembly_source', 'media', 'audio', 'image', 'frame', 'json', 'archive'), 'media_type': TEXT})
PAGINATION = {'limit': integer(1, 100), 'cursor': TEXT, 'snapshot_id': ident('snp')}
common = {'project_id': ident('prj'), 'operation': OPERATION, 'required_features': arr(TEXT, unique=True), **PAGINATION}
CAPABILITY_REQUEST_SCHEMA = {'oneOf': [
    obj({'action': {'const': 'discover'}, **common}, list(common)),
    obj({'action': {'const': 'list'}, **common, 'selected_only': BOOL}, list(common) + ['selected_only']),
    obj({'action': {'const': 'inspect'}, 'project_id': ident('prj'), 'adapter_id': ADAPTER, 'mode': enum('cached', 'readonly')}, ['project_id', 'mode'])]}


def expanded(schema, definitions=None):
    definitions = DEFS if definitions is None else definitions
    if isinstance(schema, dict):
        if '$ref' in schema:
            name = schema['$ref'].rsplit('/', 1)[-1]
            if name not in definitions:
                raise ContractError('SCHEMA_UNSUPPORTED', 'Unregistered schema reference: ' + name)
            return expanded(definitions[name], definitions)
        return {k: expanded(v, definitions) for k, v in schema.items() if k != '$defs'}
    if isinstance(schema, list):
        return [expanded(v, definitions) for v in schema]
    return schema


def checked(value, schema):
    validate(value, expanded(schema))
    return value


def _fail(code, message):
    raise ContractError(code, message)


class CapabilityRegistry:
    def __init__(self):
        self._entries = {}

    def register(self, declaration, *, implementation_sha256, schemas, outputs, state='unknown', checks=(), output_variants=None, option_metadata=None):
        checked(declaration, DECLARATION_SCHEMA)
        checked(implementation_sha256, DIGEST)
        checked(state, enum('available', 'unavailable', 'unknown', 'disabled'))
        aid = declaration['adapter_id']
        if aid in self._entries:
            _fail('INVALID_ARGUMENT', 'Adapter already registered: ' + aid)
        ops = [x['operation'] for x in declaration['operations']]
        if len(set(ops)) != len(ops) or set(outputs) != set(ops):
            _fail('INVALID_ARGUMENT', 'Operation declarations and registered output ports must agree uniquely.')
        resolved = {}
        schemas = {**schemas, 'motion/v1/no-options': obj({})}
        for sid, schema in schemas.items():
            checked(sid, TEXT)
            resolved[sid] = expanded(schema, {**DEFS, **schema.get('$defs', {})})
        for op in declaration['operations']:
            if any(op[k] not in resolved for k in ['request_schema', 'result_schema']):
                _fail('SCHEMA_UNSUPPORTED', 'Operation schemas must be registered before binding.')
            checked(outputs[op['operation']], arr(ref('ExpectedOutput'), 1))
            if len({o['port'] for o in outputs[op['operation']]}) != len(outputs[op['operation']]):
                _fail('INVALID_ARGUMENT', 'Output ports must be unique.')
        if output_variants is not None:
            if set(output_variants) - set(ops):
                _fail('INVALID_ARGUMENT', 'Output variants must name registered operations.')
            for variants in output_variants.values():
                for kind, ports in variants.items():
                    checked(kind, TEXT)
                    checked(ports, arr(ref('ExpectedOutput'), 1))
                    if len({p['port'] for p in ports}) != len(ports):
                        _fail('INVALID_ARGUMENT', 'Variant output ports must be unique.')
        # Trusted registration metadata describes identities/roles, never readiness.
        # It cannot be supplied by a project or an options request.
        if option_metadata is not None:
            if not isinstance(option_metadata, dict) or set(option_metadata) - set(ops):
                _fail('INVALID_ARGUMENT', 'Option metadata must name registered operations only.')
            for metadata in option_metadata.values():
                checked(metadata, obj({
                    'identities': obj({name: nullable(TEXT) for name in ('provider', 'model', 'account')},
                                      ['provider', 'model', 'account']),
                    'schema_roles': {'type': 'object', 'additionalProperties': enum('binding_parameters', 'artifact_controls')},
                    'unsupported_controls': arr(TEXT, unique=True)},
                    ['identities', 'schema_roles', 'unsupported_controls']))
                if set(metadata.get('schema_roles', {})) - set(resolved):
                    _fail('SCHEMA_UNSUPPORTED', 'Option schema roles must reference registered exact schemas.')
        timestamp = datetime.now(timezone.utc)
        availability = {'adapter_id': aid, 'observed_at': _now(), 'state': state,
            'checks': list(checks), 'declared': True, 'inspected': False, 'contract_tested': False,
            'exercised_evidence': [], 'expires_at': (timestamp + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')}
        self._entries[aid] = copy.deepcopy({'declaration': declaration, 'availability': availability,
            'schemas': resolved, 'outputs': outputs, 'implementation_sha256': implementation_sha256,
            **({'output_variants': output_variants} if output_variants is not None else {}),
            **({'option_metadata': option_metadata} if option_metadata is not None else {})})

    def inspect(self, adapter_id, mode='cached'):
        checked(adapter_id, ADAPTER)
        checked(mode, enum('cached', 'readonly'))
        if adapter_id not in self._entries:
            _fail('NOT_FOUND', 'Adapter is not registered: ' + adapter_id)
        e = self._entries[adapter_id]
        availability = copy.deepcopy(e['availability'])
        if availability['state'] == 'available' and datetime.fromisoformat(availability['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
            availability['state'] = 'unknown'
        # readonly permits metadata checks; this implementation intentionally uses
        # only the cache, never initializes a transport or claims a fresh inspection.
        return {'declaration': copy.deepcopy(e['declaration']), 'availability': availability, 'schema_refs': []}

    def discover(self, *, operation=None, required_features=(), selected=(), selected_only=False):
        result = []
        for aid in sorted(self._entries):
            d = self.inspect(aid)
            dec, availability = d['declaration'], d['availability']
            ops = [o for o in dec['operations'] if operation is None or o['operation'] == operation]
            ops = [o for o in ops if set(required_features) <= set(o['features'])]
            if not ops or (selected_only and aid not in selected):
                continue
            result.append({'adapter_id': aid, 'label': dec['label'], 'transport': dec['transport'], 'location': dec['location'],
                'operations': sorted(o['operation'] for o in ops), 'features': sorted({f for o in ops for f in o['features']}),
                'availability': availability['state'], 'selected': aid in selected, 'qualification': 'declared'})
        return result

    def match(self, operation, required_features, selected, parameters=None, media_types=()):
        matches = []
        for summary in self.discover(operation=operation, required_features=required_features, selected=selected, selected_only=True):
            aid = summary['adapter_id']
            if summary['availability'] != 'available':
                continue
            op = next(o for o in self._entries[aid]['declaration']['operations'] if o['operation'] == operation)
            c, p = op['constraints'], parameters or {}
            # Exact request schemas can narrow the shared operation vocabulary.
            # Exclude an incompatible binding before resolving preferences or
            # ambiguity, rather than selecting it and failing after selection.
            if parameters is not None:
                try:
                    checked(parameters, self._entries[aid]['schemas'][op['request_schema']])
                except ContractError:
                    continue
            if media_types and not set(media_types) <= set(c['media_types']):
                continue
            canvas = p.get('canvas', p)
            if any(c[k] is not None and canvas.get(pk, 0) > c[k] for k, pk in [('max_width_px', 'width_px'), ('max_height_px', 'height_px')]):
                continue
            if p.get('language') is not None and p['language'] not in c['languages'] and '*' not in c['languages']:
                continue
            if 'alpha' in p and p['alpha'] not in c['alpha_modes']:
                continue
            if p.get('granularity') == 'word' and c['timing'] != 'word':
                continue
            if p.get('duration_frames', 0) > (c['max_duration_frames'] or 9007199254740991):
                continue
            rate = p.get('rate')
            if rate:
                exact_rate = Fraction(rate['num'], rate['den'])
                if c['min_rate'] and exact_rate < Fraction(c['min_rate']['num'], c['min_rate']['den']):
                    continue
                if c['max_rate'] and exact_rate > Fraction(c['max_rate']['num'], c['max_rate']['den']):
                    continue
            matches.append(aid)
        return matches

    def validate_parameters(self, operation, parameters):
        if operation not in PARAMS:
            _fail('UNSUPPORTED_OPERATION', 'Unknown operation: ' + operation)
        # RegisteredOptions values are checked only against the exact adapter
        # schema at binding time; no arbitrary object is admitted beforehand.
        params = copy.deepcopy(parameters)
        options = params.get('encoder_options')
        if options is not None:
            params['encoder_options'] = {**options, 'values': {}}
        checked(params, PARAMS[operation])
        if operation == 'media.probe@1':
            params.setdefault('full_decode', False)
        if 'range' in params and params['range']['end_frame'] <= params['range']['start_frame']:
            _fail('INVALID_ARGUMENT', 'Frame range must be nonempty and half-open.')
        if options is not None:
            params['encoder_options'] = copy.deepcopy(options)
        return params

    def options_schema(self):
        choices = {}
        for entry in self._entries.values():
            operation_schemas = {op[k] for op in entry['declaration']['operations'] for k in ['request_schema', 'result_schema']}
            for sid, schema in entry['schemas'].items():
                if sid not in operation_schemas:
                    sha = digest(schema)
                    choices[(sid, sha)] = obj({'schema_id': {'const': sid}, 'schema_sha256': {'const': sha}, 'values': schema})
        return {'oneOf': list(choices.values())} if choices else DEFS['RegisteredOptions']

    def binding(self, adapter_id, operation, parameters, binding_parameters=None):
        e = self._entries[adapter_id]
        op = next(o for o in e['declaration']['operations'] if o['operation'] == operation)
        checked(parameters, e['schemas'][op['request_schema']])
        for options in [binding_parameters, parameters.get('encoder_options')]:
            if options is not None:
                header = {**options, 'values': {}}
                checked(header, DEFS['RegisteredOptions'])
                sid = options['schema_id']
                if sid not in e['schemas'] or digest(e['schemas'][sid]) != options['schema_sha256']:
                    _fail('SCHEMA_UNSUPPORTED', 'Options schema ID/hash is not registered for this binding.')
                checked(options['values'], e['schemas'][sid])
        d = e['declaration']
        return {'adapter_id': adapter_id, 'implementation_version': d['implementation_version'],
            'implementation_sha256': e['implementation_sha256'], 'abi_version': d['abi_version'],
            'request_schema': op['request_schema'], 'result_schema': op['result_schema'],
            'schema_sha256': digest(self.schema_bundle(adapter_id))}

    def option_descriptor(self, adapter_id, operation):
        """Return cached exact schemas/identities, without probing or validating a job."""
        inspected = self.inspect(adapter_id)
        declared = next((op for op in inspected['declaration']['operations']
                         if op['operation'] == operation), None)
        if declared is None:
            raise ContractError('UNSUPPORTED_OPERATION', 'Operation is not registered for this exact adapter.')
        entry = self._entries[adapter_id]
        declaration = inspected['declaration']
        return copy.deepcopy({
            'declaration': declaration, 'operation': declared,
            'availability': inspected['availability'],
            'schemas': entry['schemas'],
            'option_metadata': entry.get('option_metadata', {}).get(operation, {}),
            'binding': {'adapter_id': adapter_id,
                'implementation_version': declaration['implementation_version'],
                'implementation_sha256': entry['implementation_sha256'],
                'abi_version': declaration['abi_version'],
                'request_schema': declared['request_schema'],
                'result_schema': declared['result_schema'],
                'schema_sha256': digest(self.schema_bundle(adapter_id))}})

    def schema_bundle(self, adapter_id):
        e = self._entries[adapter_id]
        return copy.deepcopy({k:e[k] for k in ('schemas','outputs','output_variants','option_metadata') if k in e})

    def outputs(self, adapter_id, operation, parameters=None):
        e = self._entries[adapter_id]
        if parameters is not None:
            self.binding(adapter_id, operation, parameters)
            variants = e.get('output_variants', {}).get(operation)
            if variants is not None:
                if parameters.get('kind') not in variants:
                    _fail('SCHEMA_UNSUPPORTED', 'No output type for this transform kind.')
                return copy.deepcopy(variants[parameters['kind']])
        return copy.deepcopy(e['outputs'][operation])

    def effects(self, adapter_id):
        return copy.deepcopy(self._entries[adapter_id]['declaration']['effects'])

    def dispatch(self, args, store=None):
        """Validated service API; handler wraps ContractError into native envelope."""
        checked(args, CAPABILITY_REQUEST_SCHEMA)
        selected = []
        store = store or ProjectStore()
        fs = store._filesystem()
        if args.get('cursor') or args.get('snapshot_id'):
            return store._page(fs, {**args, '_tool': 'motion_capabilities'}, None)
        if 'project_id' in args:
            pointer = store._pointer(fs, args['project_id'])
            _, documents = store._load(fs, pointer)
            selected = documents['bindings', 'project']['value']['selected_adapter_ids']
        if args['action'] == 'inspect':
            return self.inspect(args['adapter_id'], args.get('mode', 'cached'))
        if args.get('selected_only') and 'project_id' not in args:
            _fail('INVALID_ARGUMENT', 'selected_only requires explicit project_id.')
        items = self.discover(operation=args.get('operation'), required_features=args.get('required_features', []),
            selected=selected, selected_only=args.get('selected_only', False))
        return store._page(fs, {**args, '_tool': 'motion_capabilities'}, None if args.get('cursor') or args.get('snapshot_id') else items)


def capability_tool_schema():
    return expanded(CAPABILITY_REQUEST_SCHEMA)


def builtin_ffmpeg(executable):
    """A probe-only semantic declaration; availability is not media exercise."""
    constraints = {'media_types': ['audio/flac', 'audio/mpeg', 'audio/wav', 'audio/x-wav', 'image/jpeg', 'image/png', 'video/mp4', 'video/quicktime', 'video/webm'],
        'codecs': [], 'max_width_px': None, 'max_height_px': None, 'min_rate': None, 'max_rate': None,
        'languages': [], 'color_spaces': [], 'alpha_modes': [], 'timing': 'none', 'max_duration_frames': None}
    declaration = {'schema': 'motion/v1/adapter-declaration', 'adapter_id': 'ffmpeg.probe', 'label': 'FFmpeg / ffprobe metadata',
        'abi_version': '1.0', 'implementation_version': '1.0', 'transport': 'cli', 'location': 'local',
        'operations': [{'operation': 'media.probe@1', 'request_schema': 'motion/v1/ffmpeg-probe-request',
            'result_schema': 'motion/v1/ffmpeg-probe-result', 'features': [], 'constraints': constraints,
            'determinism': 'unknown', 'supports': {k: False for k in ['status', 'cancel', 'collect', 'resume', 'provider_idempotency', 'lookup_by_request']},
            'default_timeout_seconds': 60}],
        'dependencies': [{'name': 'ffprobe', 'kind': 'executable', 'version_constraint': None, 'required': True}],
        'credential_refs': [], 'effects': {'writes_local': True, 'uploads': False, 'destinations': [],
            'generates': False, 'launches_process': True, 'pricing': 'free', 'charging_basis': None, 'estimate': None},
        'license': None, 'resource_needs': {'cpu_threads': None, 'ram_bytes': None, 'gpu_vram_bytes': None, 'exclusive_resource': None}}
    return declaration, 'available' if executable else 'unavailable'


def installed_registry():
    """Explicit read-only PATH/source observation. No startup/import probing."""
    registry = CapabilityRegistry()
    executable = shutil.which('ffprobe')
    declaration, state = builtin_ffmpeg(executable)
    hashes = {'adapter_source': 'sha256:' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if executable:
        try:
            with open(executable, 'rb') as stream:
                hashes['executable'] = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
        except OSError:
            state = 'unknown'
    from .adapters.media_probe import result_schema
    hashes['probe_source'] = 'sha256:' + hashlib.sha256(
        Path(__file__).with_name('adapters').joinpath('media_probe.py').read_bytes()).hexdigest()
    decoder = shutil.which('ffmpeg')
    if decoder:
        with open(decoder, 'rb') as stream:
            hashes['decoder'] = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
    op = declaration['operations'][0]
    registry.register(declaration, implementation_sha256=digest(hashes),
        schemas={op['request_schema']: PARAMS['media.probe@1'], op['result_schema']: result_schema()},
        outputs={'media.probe@1': [{'port': 'report', 'kind': 'report', 'media_type': 'application/json'}]}, state=state,
        checks=[{'name': 'executable', 'status': 'pass' if state == 'available' else 'fail', 'reason': 'Read-only executable availability; no version or media process executed.'}])
    return registry
