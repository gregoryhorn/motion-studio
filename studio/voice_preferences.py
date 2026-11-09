"""Profile-owned voice defaults and pure Settings override resolution.

Selections are atomic: never merge options across speakers/providers. A saved
choice pins the exact implementation/schema and voice request; display labels
are not identity. No imports initialize providers and no operation invokes them.
Project overrides belong solely in existing Settings.voice_preferences.
"""
from __future__ import annotations
import copy

from .contracts import (ADAPTER, D, DIGEST, TEXT, ContractError, digest, enum,
                        ident, integer, nullable, obj, validate)
from .project import ProjectStore

OPERATION = 'speech.synthesize@1'
FROZEN_VOICE_BINDING_SCHEMA = obj({
    'adapter_id': ADAPTER, 'implementation_version': TEXT, 'implementation_sha256': DIGEST,
    'abi_version': TEXT, 'request_schema': TEXT, 'result_schema': TEXT, 'schema_sha256': DIGEST})
# Only the values bag is dynamic; the exact current registered schema validates
# it before save or use. This schema is not an arbitrary provider options API.
OPTIONS_SCHEMA = obj({'schema_id': TEXT, 'schema_sha256': DIGEST,
                      'values': {'type': 'object', 'additionalProperties': {}}})
VOICE_PREFERENCES_SCHEMA = copy.deepcopy(D['VoicePreferences'])
PROFILE_RECORD_SCHEMA = obj({'revision': integer(0), 'value': nullable(VOICE_PREFERENCES_SCHEMA)})
# Parent expands these branches into motion_capabilities; no eleventh tool.
VOICE_ACTION_SCHEMAS = [
    obj({'action': {'const': 'voice_get'}, 'project_id': ident('prj')}, ['project_id']),
    obj({'action': {'const': 'voice_resolve'}, 'project_id': ident('prj'),
         'explicit': nullable(VOICE_PREFERENCES_SCHEMA)}, ['explicit']),
    obj({'action': {'const': 'voice_save'}, 'expected_revision': integer(0),
         'value': VOICE_PREFERENCES_SCHEMA, 'project_id': ident('prj')}, ['project_id']),
    obj({'action': {'const': 'voice_remove'}, 'expected_revision': integer(0)})]


def _validate_identity(registry, value, *, available=False):
    validate(value, VOICE_PREFERENCES_SCHEMA)
    binding = value['binding']
    adapter_id = binding['adapter_id']
    try:
        observed = registry.inspect(adapter_id)
        current = registry.binding(adapter_id, OPERATION, value['parameters'], value['binding_parameters'])
    except (KeyError, StopIteration):
        raise ContractError('SCHEMA_UNSUPPORTED', 'Saved speech operation/binding is no longer registered.') from None
    if binding != current:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Voice implementation/model/schema is obsolete; explicitly update the selection.')
    if available and observed['availability']['state'] != 'available':
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Selected voice is not currently available; no fallback was selected.')
    # Local voice support is stricter than generic PARAMS. Other providers rely
    # on their exact registered request/options schema, never this local catalog.
    from .adapters import alternative
    if adapter_id in alternative.ADAPTER_IDS:
        live = alternative.registration_binding(adapter_id, OPERATION,
            value['parameters'], value['binding_parameters'])
        if binding != live:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Installed speech mapping changed since cached registration; refresh and reselect explicitly.')
        from .adapters.voice_controls import synthesis_controls
        synthesis_controls(adapter_id, value['parameters'], value['binding_parameters'])
    return copy.deepcopy(value)


def _reference(value):
    """Only the verified local binding currently advertises this reference form."""
    from .adapters.voice_controls import BREEZE_ID, validate_options
    if value['binding']['adapter_id'] == BREEZE_ID:
        options = validate_options(BREEZE_ID, value['binding_parameters'])
        return options['reference'] if options else None
    return None


def validate_voice_preferences(value, registry, *, project_id=None, authorize_reference=None):
    """ProjectChange/save hook: validate choice and source authority, no inference.

    None clears a project override; profile removal uses revisioned tombstones.
    Callback(project_id, reference) -> True must check immutable pins, artifact
    ownership/access and explicit source-identity consent; a preference is no grant.
    """
    if value is None:
        return None
    value = _validate_identity(registry, value)
    reference = _reference(value)
    if reference is not None:
        from .adapters.voice_controls import require_reference_scope
        require_reference_scope(reference, project_id=project_id, authorize_reference=authorize_reference)
    return value


def inspect_voice_preferences(registry, value):
    """Passive inspection labels obsolete values, including currently unavailable."""
    if value is None:
        return {'value': None, 'status': 'unset', 'error': None}
    try:
        _validate_identity(registry, value, available=True)
    except ContractError as exc:
        return {'value': copy.deepcopy(value), 'status': 'obsolete' if exc.code != 'DEPENDENCY_UNAVAILABLE' else 'unavailable',
                'error': {'code': exc.code, 'message': exc.message}}
    return {'value': copy.deepcopy(value), 'status': 'current', 'error': None}


def visible_voice_default(registry, adapter_id):
    """Use defaults from the caller-selected registered binding, never fallback.

    None means no fully specified public default; callers must ask for selection.
    This is read-only metadata discovery, not permission or engine initialization.
    """
    inspected = registry.inspect(adapter_id)
    operation = next((op for op in inspected['declaration']['operations'] if op['operation'] == OPERATION), None)
    if operation is None:
        return None
    schema = registry.schema_bundle(adapter_id)['schemas'][operation['request_schema']]
    properties = schema.get('properties', {})
    fields = ('language', 'voice', 'seed')
    if any('default' not in properties.get(field, {}) for field in fields):
        return None
    parameters = {field: copy.deepcopy(properties[field]['default']) for field in fields}
    return {'label': inspected['declaration']['label'],
            'binding': registry.binding(adapter_id, OPERATION, parameters),
            'parameters': parameters, 'binding_parameters': None}


def resolve_voice_preferences(registry, *, project_id, explicit=None, project=None,
                              profile=None, engine_default=None, authorize_reference=None):
    """Request > Settings > saved profile > trusted visible engine default.

    engine_default is host-discovered metadata, not an implicit alternate route.
    A stale higher-priority choice fails rather than descending to another layer.
    Reference authorization is rechecked on every use, never inferred from save.
    """
    validate(project_id, ident('prj'))
    layers = [('explicit', explicit), ('project', project), ('profile', profile), ('engine_default', engine_default)]
    source, value = next(((name, val) for name, val in layers if val is not None), (None, None))
    if value is None:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'No selected voice or visible engine default is available.')
    selected = validate_voice_preferences(value, registry, project_id=project_id, authorize_reference=authorize_reference)
    assert selected is not None
    _validate_identity(registry, selected, available=True)
    inputs = {}
    reference = _reference(selected)
    if reference is not None:
        inputs = {'reference_audio': copy.deepcopy(reference['audio']), 'reference_text': copy.deepcopy(reference['transcript'])}
    return {'source': source, 'selection': selected, 'operation': OPERATION,
            'reference_inputs': inputs, 'selection_sha256': digest({key: val for key, val in selected.items() if key != 'label'}),
            'requires_consuming_permission': True}


def validate_voice_request(request, registry, *, authorize_reference=None):
    """Consumption-boundary hook, after normal permission claim, before invoke.

    Authorize/hash exactly these returned reference pins in the normal request.
    This hook grants no authority and never starts a process or alternate engine.
    """
    if request.get('operation') != OPERATION:
        return
    selection = {'label': 'frozen request', 'binding': request['binding'],
                 'parameters': request['parameters'], 'binding_parameters': request.get('binding_parameters')}
    resolved = resolve_voice_preferences(registry, project_id=request['project_id'], explicit=selection,
                                         authorize_reference=authorize_reference)
    expected = resolved['reference_inputs']
    supplied = {key: value for key, value in request['inputs'].items() if key in ('reference_audio', 'reference_text')}
    if supplied != expected:
        raise ContractError('ASSET_CHANGED', 'Frozen speech reference input pins differ from the selected authorized source.')


class VoicePreferencesStore:
    """Active profile plugin data only. No separate project preference database."""
    RECORD = 'voice/preferences.json'
    LOCK = 'voice/preferences.lock'

    def __init__(self, projects=None):
        self.projects = projects if projects is not None else ProjectStore()

    def read(self):
        try:
            record = self.projects._filesystem().read(self.RECORD)
        except FileNotFoundError:
            return {'revision': 0, 'value': None}
        validate(record, PROFILE_RECORD_SCHEMA)
        return copy.deepcopy(record)

    def save(self, value, *, expected_revision, registry, project_id=None, authorize_reference=None):
        selected = validate_voice_preferences(value, registry, project_id=project_id,
                                               authorize_reference=authorize_reference)
        return self._replace(selected, expected_revision)

    def remove(self, *, expected_revision):
        # A tombstone preserves CAS and cannot delete referenced original bytes.
        return self._replace(None, expected_revision)

    def _replace(self, value, expected_revision):
        validate(expected_revision, integer(0))
        fs = self.projects._filesystem(write=True)
        with fs.lock(self.LOCK):
            try:
                current = fs.read(self.RECORD)
            except FileNotFoundError:
                current = {'revision': 0, 'value': None}
            validate(current, PROFILE_RECORD_SCHEMA)
            if current['revision'] != expected_revision:
                raise ContractError('REVISION_CONFLICT', 'Saved voice defaults changed; inspect before updating.')
            updated = {'revision': current['revision'] + 1, 'value': copy.deepcopy(value)}
            validate(updated, PROFILE_RECORD_SCHEMA)
            fs.write(self.RECORD, updated, replace=True)
            # Exact target read-back; no inference or artifact deletion.
            if fs.read(self.RECORD) != updated:
                raise ContractError('STORAGE_UNSUPPORTED', 'Voice preference write read-back differs.')
            return updated


def voice_action(args, *, registry, preferences, project_preferences=None,
                 engine_default=None, authorize_reference=None):
    """Runtime dispatch for motion_capabilities; parent supplies Settings value.

    profile writes only: project changes use set_voice_preferences in the existing
    motion_project transaction/revision/idempotency machinery. Callers must not
    supply project_preferences or engine_default from untrusted request payloads.
    """
    validate(args, {'oneOf': VOICE_ACTION_SCHEMAS})
    action = args['action']
    if action == 'voice_save':
        return preferences.save(args['value'], expected_revision=args['expected_revision'], registry=registry,
                                project_id=args.get('project_id'), authorize_reference=authorize_reference)
    if action == 'voice_remove':
        return preferences.remove(expected_revision=args['expected_revision'])
    profile = preferences.read()
    if action == 'voice_get':
        return {'profile': {'revision': profile['revision'], **inspect_voice_preferences(registry, profile['value'])},
                'project': inspect_voice_preferences(registry, project_preferences),
                'engine_default': inspect_voice_preferences(registry, engine_default)}
    return resolve_voice_preferences(registry, project_id=args['project_id'], explicit=args.get('explicit'),
        project=project_preferences, profile=profile['value'], engine_default=engine_default,
        authorize_reference=authorize_reference)
