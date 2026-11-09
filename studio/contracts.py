"""Closed B03 schemas and dependency-free contract validation.

The supported JSON Schema subset is deliberately small and is also exported as
Draft 2020-12 for host/tool consumers. No provider payload or arbitrary command
object is accepted. Canonical JSON uses the RFC 8785 integer-only subset.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from decimal import Decimal
from datetime import datetime

MAX_INT = 9007199254740991
UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
STAGES = ['intake', 'concept', 'storyboard', 'animatic', 'audio_lock', 'production', 'review', 'delivery']
GATES = ['creative', 'technical', 'art', 'audio', 'delivery_profile']
METHODS = ['deterministic', 'agent_visual', 'agent_audio', 'user', 'playback']
KINDS = ['brief', 'brand', 'timeline', 'scene', 'settings', 'variants', 'bindings', 'caption', 'caption_style', 'delivery_profile', 'gate_policy', 'asset_library', 'storyboard', 'creative_plan', 'editorial']


def obj(properties, optional=()):
    return {'type': 'object', 'properties': properties,
            'required': [k for k in properties if k not in optional], 'additionalProperties': False}


def arr(item, minimum=0, unique=False):
    return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': 1000, **({'uniqueItems': True} if unique else {})}


def string(pattern=None, minimum=0, maximum=16384):
    return {'type': 'string', 'minLength': minimum, 'maxLength': maximum, **({'pattern': '^' + pattern + '$'} if pattern else {})}


def enum(*values):
    return {'type': 'string', 'enum': list(values)}


def integer(minimum=0, maximum=MAX_INT):
    return {'type': 'integer', 'minimum': minimum, 'maximum': maximum}


def ref(name):
    return {'$ref': '#/$defs/' + name}


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


def mapping(value):
    return {'type': 'object', 'additionalProperties': value, 'maxProperties': 1000,
            'propertyNames': string(maximum=160, minimum=1)}


def ident(prefix):
    return string(prefix + '_' + UUID_PATTERN)


TEXT = string()
LABEL = string(minimum=1, maximum=160)
KEY = string(r'[a-z][a-z0-9_-]{0,63}')
ADAPTER = string(r'[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*', minimum=1, maximum=96)
DECIMAL = string(r'[+-]?[0-9]+(?:\.[0-9]+)?')
BOOL = {'type': 'boolean'}
STAMP = string(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z')
DIGEST = string(r'sha256:[0-9a-f]{64}')
PATH = string(minimum=1)
D = {}
D['Rate'] = obj({'num': integer(1), 'den': integer(1)})
D['ArtifactRef'] = obj({'artifact_id': ident('art'), 'sha256': DIGEST})
D['DocumentRef'] = obj({'kind': enum(*KINDS), 'id': TEXT, 'revision': integer(1), 'sha256': DIGEST})
D['Claim'] = obj({'claim_id': KEY, 'text': TEXT, 'evidence': arr(ref('ArtifactRef')), 'status': enum('supplied', 'verified', 'unverified')})
D['Brief'] = obj({k: TEXT for k in ['audience', 'objective', 'message', 'treatment']} | {'constraints': arr(TEXT), 'claims': arr(ref('Claim')), 'reference_assets': arr(ref('ArtifactRef'))})
D['MotionToken'] = obj({'duration_frames': integer(), 'easing': enum('linear', 'ease_in', 'ease_out', 'ease_in_out', 'hold')})
D['FontRef'] = obj({'family': LABEL, 'face_artifact': ref('ArtifactRef'), 'weight': integer(1, 1000), 'italic': BOOL, 'rights_ref': ref('ArtifactRef')}, optional=['rights_ref'])
D['Brand'] = obj({'colors': mapping(string(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?')), 'fonts': arr(ref('FontRef')), 'spacing_px': mapping(integer()), 'motion_tokens': mapping(ref('MotionToken')), 'logo_assets': arr(ref('ArtifactRef')), 'reference_assets': arr(ref('ArtifactRef'))})
D['ExecutionPolicy'] = obj({'remote': enum('deny', 'selected_only'), 'allowed_destinations': arr(TEXT), 'paid': enum('deny', 'explicit'), 'max_concurrent_nodes': integer(1), 'retain_generated_assets': BOOL, 'budget': obj({'currency': TEXT, 'amount': DECIMAL})}, optional=['budget'])
D['GateRule'] = obj({'gate': enum(*GATES), 'required': {'const': True}, 'allowed_authors': arr(enum('system', 'agent', 'user'), 1, True), 'checks': arr(TEXT), 'not_applicable_when': enum('never', 'no_audio'), 'coverage': enum('whole_file', 'every_scene_and_transition', 'requested_samples'), 'method_groups': arr(arr(enum(*METHODS), 1, True), 1), 'require_user_acceptance': BOOL})
# Legacy rights_rule values remain readable metadata; they have no enforcement effect.
D['GatePolicy'] = obj({'policy_id': KEY, 'revision': integer(1), 'gates': arr(ref('GateRule'), 5), 'rights_rule': enum('require_known', 'allow_documented_restrictions'), 'caption_parity': nullable(obj({'metric': TEXT, 'tolerance': DECIMAL, 'require_visual': BOOL}))}, optional=['rights_rule'])
D['VoicePreferences'] = obj({
    'label': TEXT,
    'binding': obj({'adapter_id': ADAPTER, 'implementation_version': TEXT,
        'implementation_sha256': DIGEST, 'abi_version': TEXT,
        'request_schema': TEXT, 'result_schema': TEXT, 'schema_sha256': DIGEST}),
    'parameters': obj({'language': TEXT, 'voice': TEXT,
        'seed': nullable(integer(-9007199254740991))}),
    'binding_parameters': nullable(obj({'schema_id': TEXT, 'schema_sha256': DIGEST,
        'values': {'type': 'object', 'additionalProperties': {}}}))})
D['Settings'] = obj({'rate': ref('Rate'), 'sample_rate': integer(1), 'audio_mode': enum('silent', 'recorded', 'synthesized', 'mixed'), 'stage': enum(*STAGES), 'policy': ref('ExecutionPolicy'), 'gate_policy': ref('GatePolicy'), 'voice_preferences': nullable(ref('VoicePreferences'))}, optional=['voice_preferences'])
D['Bindings'] = obj({'selected_adapter_ids': arr(ADAPTER, unique=True), 'preferences': mapping(arr(ADAPTER, unique=True)), 'pins': mapping(ADAPTER)})
D['Rect'] = obj({'x_px': integer(-MAX_INT), 'y_px': integer(-MAX_INT), 'width_px': integer(1), 'height_px': integer(1)})
D['Layout'] = obj({'element_key': KEY, 'rect': ref('Rect'), 'z': integer(-MAX_INT), 'opacity': DECIMAL, 'asset': ref('ArtifactRef')}, optional=['asset'])
D['RuntimeIdentity'] = obj({'adapter_id': ADAPTER, 'implementation_version': TEXT, 'engine': TEXT, 'engine_version': nullable(TEXT), 'dependencies': arr(ref('ArtifactRef')), 'entry_member': PATH})
scene_properties = {'scene_id': ident('scn'), 'label': LABEL, 'duration_frames': integer(1), 'canvas': obj({'width_px': integer(1), 'height_px': integer(1)}), 'assets': arr(ref('ArtifactRef')), 'layout': arr(ref('Layout')), 'safe_zones': arr(ref('Rect')), 'motion_intent': TEXT, 'camera_intent': TEXT, 'authored_source': nullable(ref('ArtifactRef')), 'source_format': nullable(TEXT), 'source_runtime': nullable(ref('RuntimeIdentity'))}
D['StoryboardBinding'] = obj({'storyboard': ref('DocumentRef'), 'asset_library': ref('DocumentRef'),
    'panel_id': KEY, 'variant_id': KEY})
scene_properties['storyboard_binding'] = ref('StoryboardBinding')
D['Scene'] = obj(scene_properties, optional=['storyboard_binding'])
D['SceneInput'] = {'oneOf': [obj(scene_properties, optional=['scene_id','storyboard_binding']), obj({k: v for k, v in scene_properties.items() if k != 'scene_id'} | {'new_scene_key': KEY}, optional=['storyboard_binding'])]}
D['TimePoint'] = obj({'domain': enum('frame', 'sample', 'source_tick'), 'index': integer(-MAX_INT), 'rate': ref('Rate'), 'origin': enum('project', 'source'), 'source_artifact': ref('ArtifactRef')}, optional=['source_artifact'])
D['Subject'] = {'oneOf': [obj({'kind': {'const': 'scene'}, 'scene_id': ident('scn')}), obj({'kind': {'const': 'scene'}, 'new_scene_key': KEY}), obj({'kind': {'const': 'artifact'}, 'artifact': ref('ArtifactRef')}), obj({'kind': {'const': 'caption'}, 'caption': ref('DocumentRef')})]}
D['TimelineItem'] = obj({'item_id': KEY, 'start_frame': integer(), 'end_frame': integer(1), 'subject': ref('Subject'), 'source_in': ref('TimePoint'), 'gain_db': DECIMAL, 'transform': ref('Layout'), 'crop': ref('Rect')}, optional=['source_in', 'gain_db', 'transform', 'crop'])
D['Track'] = obj({'track_id': KEY, 'kind': enum('video', 'audio', 'caption'), 'items': arr(ref('TimelineItem'))})
D['Timeline'] = obj({'duration_frames': integer(), 'tracks': arr(ref('Track'))})
constraints = {'allowed_containers': arr(TEXT), 'allowed_video_codecs': arr(TEXT), 'allowed_audio_codecs': arr(TEXT), 'width_px': nullable(integer(1)), 'height_px': nullable(integer(1)), 'rate': nullable(ref('Rate')), 'max_duration_frames': nullable(integer(1)), 'max_bytes': nullable(integer(1)), 'alpha': enum('forbidden', 'optional', 'required'), 'caption_modes': arr(TEXT), 'loudness_lufs': nullable(DECIMAL), 'loudness_tolerance_lu': nullable(DECIMAL), 'true_peak_dbtp': nullable(DECIMAL)}
D['ProfileConstraints'] = obj(constraints)
D['ProfileOverrides'] = obj(constraints | {'reason': TEXT}, optional=list(constraints))
D['DeliveryProfile'] = obj({'profile_id': KEY, 'version': LABEL, 'label': LABEL, 'sources': arr(obj({'locator': TEXT, 'retrieved_at': STAMP})), 'constraints': ref('ProfileConstraints'), 'valid_until': nullable(STAMP)})
D['AudioDelivery'] = obj({'mode': enum('none', 'required'), 'sample_rate': nullable(integer(1)), 'channels': nullable(integer(1)), 'codec': nullable(TEXT), 'loudness_lufs': nullable(DECIMAL), 'true_peak_dbtp': nullable(DECIMAL)})
D['Variant'] = obj({'variant_id': KEY, 'label': LABEL, 'width_px': integer(1), 'height_px': integer(1), 'rate': ref('Rate'), 'duration_frames': integer(1), 'container': TEXT, 'video_codec': TEXT, 'pixel_format': TEXT, 'color': obj({'primaries': TEXT, 'transfer': TEXT, 'matrix': TEXT, 'range': enum('full', 'limited')}), 'alpha': enum('none', 'straight', 'premultiplied'), 'audio': ref('AudioDelivery'), 'captions': enum('none', 'burn', 'sidecar', 'both'), 'profile': ref('DocumentRef'), 'overrides': ref('ProfileOverrides')})
D['AssetRequirement'] = obj({'requirement_id': KEY, 'role': LABEL,
    'kind': enum('image', 'media', 'audio', 'font', 'scene_source', 'other'),
    'required': {'type': 'boolean'}, 'status': enum('missing', 'planned', 'ready'),
    'asset': ref('ArtifactRef'), 'assessment': TEXT, 'acquisition': TEXT}, optional=['asset'])
D['AssetLibrary'] = obj({'assessed': {'type': 'boolean'}, 'notes': TEXT,
    'requirements': arr(ref('AssetRequirement'))})
D['StoryboardPanel'] = obj({'panel_id': KEY, 'title': LABEL, 'duration_frames': integer(1),
    'visual': ref('ArtifactRef'), 'asset_requirements': arr(KEY), 'narration': TEXT,
    'on_screen_text': TEXT, 'motion': TEXT, 'transition': TEXT, 'notes': TEXT})
D['Storyboard'] = obj({'title': LABEL, 'asset_library_sha256': DIGEST,
    'panels': arr(ref('StoryboardPanel'), 1),
    'review': obj({'status': enum('draft', 'feedback', 'ready'), 'notes': TEXT})})
changes = [obj({'op': {'const': 'set_voice_preferences'}, 'value': nullable(ref('VoicePreferences'))})]
D['EditorialRange'] = obj({'start_frame': integer(), 'end_frame': integer(1)})
D['EditorialExtract'] = obj({'extract_id': KEY, 'hook': LABEL,
    'ranges': arr(ref('EditorialRange'), 1), 'caption_decision': TEXT,
    'crop_decision': TEXT, 'caption': nullable(ref('DocumentRef')),
    'crop': nullable(ref('Rect')), 'variants': arr(KEY, 1, unique=True)})
D['EditorialDeliverable'] = obj({'deliverable_id': KEY, 'kind': enum('full_master', 'extract'),
    'extract_id': nullable(KEY), 'variant_id': KEY, 'required': BOOL})
D['EditorialOutput'] = obj({'extract_id': nullable(KEY), 'variant_id': KEY,
    'recipe_sha256': DIGEST, 'artifact': ref('ArtifactRef'), 'job_id': ident('job')})
D['Editorial'] = obj({'parent_timeline': ref('DocumentRef'), 'parent_project_revision': integer(1),
    'extracts': arr(ref('EditorialExtract'), 1),
    'deliverables': arr(ref('EditorialDeliverable'), 1),
    'outputs': arr(ref('EditorialOutput'))})
changes.append(obj({'op': {'const': 'set_editorial'}, 'value': ref('Editorial')}))
D['CreativeBeat'] = obj({'beat_id': KEY, 'title': LABEL, 'start_frame': integer(),
    'duration_frames': integer(1), 'narration': TEXT, 'on_screen_text': TEXT,
    'visual_direction': TEXT, 'asset_requirements': arr(KEY, unique=True),
    'panel_id': nullable(KEY), 'scene_id': nullable(ident('scn'))})
D['CreativeTask'] = obj({'task_id': KEY, 'title': LABEL, 'beat_ids': arr(KEY, unique=True),
    'dependencies': arr(KEY, unique=True), 'adapter_id': nullable(ADAPTER),
    'operation': nullable(TEXT), 'missing_inputs': arr(TEXT)})
D['CreativePlan'] = obj({'title': LABEL, 'involvement': enum('automatic', 'guided', 'granular'),
    'delegation': obj({area: enum('discuss', 'delegated') for area in
        ('script', 'direction', 'storyboard', 'audio', 'timing')}),
    'objective': TEXT, 'audience': TEXT, 'message': TEXT, 'duration_frames': integer(1),
    'assumptions': arr(TEXT), 'open_questions': arr(TEXT),
    'storyboard_choice': enum('discuss', 'requested', 'delegated', 'declined'),
    'beats': arr(ref('CreativeBeat'), 1), 'tasks': arr(ref('CreativeTask'), 1),
    'feedback': arr(TEXT)})
changes.append(obj({'op': {'const': 'set_creative_plan'}, 'value': ref('CreativePlan')}))
for operation, name in [('set_brief', 'Brief'), ('set_brand', 'Brand'), ('set_timeline', 'Timeline'), ('put_scene', 'SceneInput'), ('set_bindings', 'Bindings'), ('set_execution_policy', 'ExecutionPolicy'), ('set_gate_policy', 'GatePolicy'), ('put_delivery_profile', 'DeliveryProfile')]:
    changes.append(obj({'op': {'const': operation}, 'value': ref(name)}))
changes += [obj({'op': {'const': 'remove_scene'}, 'scene_id': ident('scn')}), obj({'op': {'const': 'set_variants'}, 'value': arr(ref('Variant'))}), obj({'op': {'const': 'set_stage'}, 'value': enum(*STAGES)})]
changes += [obj({'op': {'const': 'set_asset_library'}, 'value': ref('AssetLibrary')}),
            obj({'op': {'const': 'set_storyboard'}, 'value': ref('Storyboard')})]
D['ProjectChange'] = {'oneOf': changes}
page = {'limit': integer(1, 100), 'cursor': TEXT, 'snapshot_id': ident('snp')}
request_schemas = [
    obj({'action': {'const': 'create'}, 'request_id': string(UUID_PATTERN), 'name': LABEL, 'rate': ref('Rate'), 'sample_rate': integer(1), 'brief': ref('Brief')}, optional=['rate', 'sample_rate', 'brief']),
    obj({'action': {'const': 'list'}, **page, 'name_contains': TEXT}, optional=list(page) + ['name_contains']),
    obj({'action': {'const': 'open'}, 'project_id': ident('prj'), 'revision': integer(1)}, optional=['revision']),
    obj({'action': {'const': 'status'}, 'project_id': ident('prj'), 'section': enum('summary')}, optional=['section']),
    obj({'action': {'const': 'status'}, 'project_id': ident('prj'), 'section': enum('scenes', 'variants', 'jobs', 'assets'), **page}, optional=list(page)),
    obj({'action': {'const': 'update'}, 'project_id': ident('prj'), 'expected_revision': integer(1), 'request_id': string(UUID_PATTERN), 'changes': arr(ref('ProjectChange'), 1)}),
]
PROJECT_SCHEMA = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'motion/v1/project-request', 'oneOf': request_schemas, '$defs': D}
D['ProjectRecord'] = obj({'schema': {'const': 'motion/v1/project'}, 'project_id': ident('prj'), 'name': LABEL, 'created_at': STAMP, 'updated_at': STAMP, 'revision': integer(1), 'snapshot_sha256': DIGEST, 'manifest_path': PATH})
D['ProjectSnapshot'] = obj({'schema': {'const': 'motion/v1/project-snapshot'}, 'project_id': ident('prj'), 'revision': integer(1), 'documents': arr(ref('DocumentRef')), 'caption_slots': mapping(obj({'caption': ref('DocumentRef'), 'style': nullable(ref('DocumentRef'))}))})


D['ProjectSummary'] = obj({'project_id': ident('prj'), 'name': LABEL, 'revision': integer(1), 'snapshot_sha256': DIGEST, 'stage': enum(*STAGES), 'rate': ref('Rate'), 'sample_rate': integer(1), 'created_at': STAMP, 'updated_at': STAMP})
D['ProjectCreateResult'] = obj({'project': ref('ProjectSummary'), 'documents': arr(ref('DocumentRef'))})
D['ProjectUpdateResult'] = obj({'project': ref('ProjectSummary'), 'changed': arr(ref('DocumentRef')), 'invalidated': arr(obj({'node_id': ident('nod'), 'reason': TEXT}))})
D['ProjectTransaction'] = obj({'schema': {'const': 'motion/v1/project-transaction'}, 'action': enum('create', 'update'), 'request_id': string(UUID_PATTERN), 'request_sha256': DIGEST, 'previous': nullable(ref('ProjectRecord')), 'pointer': ref('ProjectRecord'), 'result': {'oneOf': [ref('ProjectCreateResult'), ref('ProjectUpdateResult')]}})
D['CreateCommit'] = obj({'schema': {'const': 'motion/v1/create-commit'}, 'request_id': string(UUID_PATTERN), 'request_sha256': DIGEST, 'pointer': ref('ProjectRecord')})
D['ProjectNoop'] = obj({'schema': {'const': 'motion/v1/project-noop'}, 'project_id': ident('prj'), 'request_id': string(UUID_PATTERN), 'request_sha256': DIGEST, 'pointer': ref('ProjectRecord'), 'result': ref('ProjectUpdateResult')})


class ContractError(Exception):
    def __init__(self, code, message, details=None, effect='none'):
        super().__init__(message)
        self.code, self.message, self.effect = code, message, effect
        self.details = details or {'resource': 'project', 'reason': message}


def invalid(path, expected, value, code='INVALID_ARGUMENT'):
    raise ContractError(code, 'Project contract validation failed.', {'field_path': path, 'expected': expected, 'received_type': type(value).__name__})


def validate(value, schema, path='$'):
    if '$ref' in schema:
        return validate(value, D[schema['$ref'].rsplit('/', 1)[-1]], path)
    union = schema.get('oneOf', schema.get('anyOf'))
    if union is not None:
        errors, matches = [], 0
        for branch in union:
            try:
                validate(value, branch, path)
                matches += 1
            except ContractError as exc:
                errors.append(exc)
        if matches < 1 or ('oneOf' in schema and matches != 1):
            # Keep useful nested diagnostics without exposing caller values.
            if errors:
                raise max(errors, key=lambda e: len(e.details.get('field_path', '')))
            invalid(path, 'exactly one closed alternative', value)
        return
    if 'const' in schema and (value != schema['const'] or type(value) is not type(schema['const'])):
        invalid(path, 'declared literal', value)
    if 'enum' in schema and value not in schema['enum']:
        invalid(path, 'declared enum', value)
    kind = schema.get('type')
    if kind == 'null':
        if value is not None:
            invalid(path, 'null', value)
    elif kind == 'boolean':
        if type(value) is not bool:
            invalid(path, 'boolean', value)
    elif kind == 'integer':
        if type(value) is not int or not schema.get('minimum', -MAX_INT) <= value <= schema.get('maximum', MAX_INT):
            invalid(path, 'bounded JSON integer', value)
    elif kind == 'string':
        if type(value) is not str:
            invalid(path, 'string', value)
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 16384):
            invalid(path, 'bounded string', value, 'LIMIT_EXCEEDED')
        if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            invalid(path, 'Unicode scalar text', value)
        if 'pattern' in schema and re.fullmatch(schema['pattern'], value) is None:
            invalid(path, 'exact documented format', value)
        if schema.get('pattern') == STAMP['pattern']:
            try:
                # RFC3339 permits leap-second notation. Validate its calendar
                # portion with second 59, while retaining the original string.
                parsed = value[:17] + ('59' if value[17:19] == '60' else value[17:19]) + value[19:]
                datetime.fromisoformat(parsed.replace('Z', '+00:00'))
                if value[17:19] == '60' and value[11:17] != '23:59:':
                    raise ValueError('invalid UTC leap-second position')
            except ValueError:
                invalid(path, 'valid RFC3339 UTC calendar timestamp', value)
    elif kind == 'array':
        if type(value) is not list:
            invalid(path, 'array', value)
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 1000):
            invalid(path, 'bounded array', value, 'LIMIT_EXCEEDED')
        if schema.get('uniqueItems') and len({canonical(v) for v in value}) != len(value):
            invalid(path, 'unique array entries', value)
        for n, v in enumerate(value):
            validate(v, schema['items'], f'{path}[{n}]')
    elif kind == 'object':
        if type(value) is not dict or any(type(k) is not str for k in value):
            invalid(path, 'object with string keys', value)
        if len(value) > schema.get('maxProperties', 1000):
            invalid(path, 'bounded object', value, 'LIMIT_EXCEEDED')
        for key in schema.get('required', []):
            if key not in value:
                invalid(path + '.' + key, 'required field', None)
        props = schema.get('properties', {})
        for key, item in value.items():
            if key in props:
                validate(item, props[key], path + '.' + key)
            elif isinstance(schema.get('additionalProperties'), dict):
                validate(key, schema.get('propertyNames', TEXT), path + '.<key>')
                validate(item, schema['additionalProperties'], path + '.' + key)
            else:
                invalid(path + '.' + key, 'documented field', item, 'UNKNOWN_FIELD')


def canonical(value):
    """RFC 8785 for contract values (integers, no JSON floating point)."""
    def ordered(v, path='$'):
        if isinstance(v, dict):
            return {k: ordered(v[k], path + '.' + k) for k in sorted(v, key=lambda k: k.encode('utf-16be'))}
        if isinstance(v, list):
            return [ordered(x, f'{path}[{i}]') for i, x in enumerate(v)]
        if type(v) is float:
            invalid(path, 'integer, exact rational or documented decimal string; JSON floats are unsupported', v)
        return v
    return json.dumps(ordered(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return 'sha256:' + hashlib.sha256(canonical(value)).hexdigest()


def empty_brief():
    return {'audience': '', 'objective': '', 'message': '', 'treatment': '', 'constraints': [], 'claims': [], 'reference_assets': []}


def default_gate_policy():
    groups = {'creative': [['agent_visual', 'user']], 'art': [['agent_visual', 'user']], 'technical': [['deterministic'], ['playback']], 'audio': [['deterministic'], ['agent_audio', 'user']], 'delivery_profile': [['deterministic']]}
    return {'policy_id': 'default', 'revision': 1, 'gates': [{'gate': gate, 'required': True, 'allowed_authors': ['system', 'agent', 'user'], 'checks': [], 'not_applicable_when': 'no_audio' if gate == 'audio' else 'never', 'coverage': 'whole_file' if gate in ['technical', 'audio', 'delivery_profile'] else 'every_scene_and_transition', 'method_groups': groups[gate], 'require_user_acceptance': False} for gate in GATES], 'caption_parity': None}


def defaults(args):
    value = copy.deepcopy(args)
    if value['action'] == 'create':
        value.setdefault('rate', {'num': 30, 'den': 1})
        value.setdefault('sample_rate', 48000)
        value.setdefault('brief', empty_brief())
    if value['action'] == 'update':
        for change in value['changes']:
            if change['op'] == 'set_bindings':
                change['value']['selected_adapter_ids'] = sorted(change['value']['selected_adapter_ids'])
    if value['action'] == 'status':
        value.setdefault('section', 'summary')
    return value


def validate_request(args):
    if not isinstance(args, dict):
        invalid('$', 'action object', args)
    if 'action' not in args or not isinstance(args['action'], str):
        invalid('$.action', 'action string', args.get('action'))
    if args['action'] not in ['create', 'list', 'open', 'status', 'update']:
        invalid('$.action', 'known project action', args['action'], 'UNKNOWN_ACTION')
    candidates = [s for s in request_schemas if s['properties']['action']['const'] == args['action']]
    validate(args, {'oneOf': candidates})
    result = defaults(args)
    domain(result)
    return result


def domain(value, path='$'):
    """Value-local invariants; ownership and graph checks belong to storage."""
    if isinstance(value, list):
        for i, item in enumerate(value):
            domain(item, f'{path}[{i}]')
    elif isinstance(value, dict):
        if set(value) == {'num', 'den'} and math.gcd(value['num'], value['den']) != 1:
            invalid(path, 'reduced rational rate', value)
        if 'opacity' in value and not Decimal(0) <= Decimal(value['opacity']) <= Decimal(1):
            invalid(path + '.opacity', 'decimal in [0,1]', value['opacity'])
        if 'entry_member' in value:
            safe_relative(value['entry_member'])
        if 'gates' in value:
            gates = value['gates']
            if len(gates) != 5 or {g['gate'] for g in gates} != set(GATES):
                invalid(path + '.gates', 'exactly one rule for each gate', gates)
            for rule in gates:
                if rule['gate'] != 'audio' and rule['not_applicable_when'] != 'never':
                    invalid(path, 'only audio may be inapplicable', rule)
                if rule['require_user_acceptance'] and ['user'] not in rule['method_groups']:
                    invalid(path, 'required user group', rule)
        if {'authored_source', 'source_format', 'source_runtime'} <= set(value):
            if sum(value[k] is None for k in ['authored_source', 'source_format', 'source_runtime']) not in [0, 3]:
                invalid(path, 'source fields all null or all present', value)
        if value.get('mode') == 'none' and 'sample_rate' in value:
            if any(v is not None for k, v in value.items() if k != 'mode'):
                invalid(path, 'no-audio fields must be null', value)
        if value.get('mode') == 'required' and 'sample_rate' in value:
            if any(value[k] is None for k in ['sample_rate', 'channels', 'codec']):
                invalid(path, 'required audio format fields', value)
        if 'origin' in value:
            if (value['origin'] == 'source') != ('source_artifact' in value):
                invalid(path, 'source artifact iff source origin', value)
            if value['origin'] == 'project' and value['index'] < 0:
                invalid(path, 'nonnegative project time', value)
        for k, item in value.items():
            domain(item, path + '.' + k)


def safe_relative(path):
    if not isinstance(path, str) or not path or path.startswith('/') or re.match(r'^[A-Za-z]:', path) or '\\' in path or '\x00' in path or any(p in ['', '.', '..'] for p in path.split('/')):
        raise ContractError('PATH_UNSAFE', 'Expected canonical project-relative POSIX path.')
    return path


def project_tool_schema():
    return {'name': 'motion_project', 'description': 'Create, list, open, inspect and atomically update profile-local project content. No media execution.', 'parameters': copy.deepcopy(PROJECT_SCHEMA)}
