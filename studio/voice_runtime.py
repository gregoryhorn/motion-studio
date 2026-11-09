"""Normal-runtime voice joins; passive metadata and plugin-owned source consent.

Source consent is not a consuming/spend grant. All engine work remains behind
normal job admission. No provider, model, credential or fallback is inferred.
"""
from __future__ import annotations

import copy
import re

from .contracts import D, DIGEST, TEXT, ContractError, digest, ident, integer, obj, validate
from .voice_preferences import (OPERATION, VOICE_ACTION_SCHEMAS, VoicePreferencesStore,
    resolve_voice_preferences, validate_voice_preferences, visible_voice_default, voice_action)

BASE = 'voice/source-consent'
LEDGER = BASE + '/ledger.json'
USE = 'speech_reference_conditioning'
SCOPE_SCHEMA = obj({'project_id': ident('prj'), 'audio': D['ArtifactRef'],
    'transcript': D['ArtifactRef'], 'source_identity': TEXT, 'use': {'const': USE}})
SOURCE_ACTION_SCHEMAS = [
    obj({'action': {'const': 'voice_source_disclose'}, 'scope': SCOPE_SCHEMA}),
    obj({'action': {'const': 'voice_source_authorize'}, 'candidate_sha256': DIGEST,
         'message_id': TEXT, 'expected_revision': integer(0)}),
    obj({'action': {'const': 'voice_source_revoke'}, 'authorization_ref': DIGEST,
         'expected_revision': integer(0)}),
    obj({'action': {'const': 'voice_source_get'}})]


def branches():
    """Branches for the existing motion_capabilities oneOf, not a new tool."""
    return copy.deepcopy(VOICE_ACTION_SCHEMAS + SOURCE_ACTION_SCHEMAS)


def _session(runtime, session_id=None):
    bridge = getattr(runtime, 'host_bridge', None)
    observed = getattr(bridge, 'session', None)
    if session_id is not None and observed and session_id != observed:
        raise ContractError('PERMISSION_DENIED', 'Voice source session differs from the current host session.')
    value = session_id if session_id is not None else observed
    if not isinstance(value, str) or not value:
        raise ContractError('PERMISSION_DENIED', 'Trusted current host session is required for voice source consent.')
    return value


def _ledger(fs):
    try:
        record = fs.read(LEDGER)
    except FileNotFoundError:
        return {'revision': 0, 'candidates': {}, 'grants': {}, 'evidence': {}}
    # Persisted plugin data is not treated as an unvalidated capability token.
    if (not isinstance(record, dict) or set(record) != {'revision', 'candidates', 'grants', 'evidence'}
            or type(record['revision']) is not int or record['revision'] < 0
            or any(not isinstance(record[key], dict) for key in ('candidates', 'grants', 'evidence'))):
        raise ContractError('PERMISSION_DENIED', 'Voice source consent ledger is malformed.')
    return record


def _write(fs, record):
    record['revision'] += 1
    fs.write(LEDGER, record, replace=True)
    if fs.read(LEDGER) != record:
        raise ContractError('STORAGE_UNSUPPORTED', 'Voice source consent read-back differs.')


def _cas(record, expected):
    if record['revision'] != expected:
        raise ContractError('REVISION_CONFLICT', 'Voice source consent changed; inspect before updating.')


def _verify_sources(runtime, scope):
    validate(scope, SCOPE_SCHEMA)
    # ArtifactCatalog.resolve verifies owning project/history and actual bytes;
    # neither caller-supplied paths nor catalog labels confer ownership.
    for key in ('audio', 'transcript'):
        record = runtime.artifacts.resolve(scope['project_id'], scope[key])
        if (record['project_id'] != scope['project_id'] or
                any(record[field] != scope[key][field] for field in ('artifact_id', 'sha256'))):
            raise ContractError('HASH_MISMATCH', 'Voice reference ownership or immutable pin differs.')
        supported = (record['kind'] == 'audio' and record['media_type'].startswith('audio/')) if key == 'audio' else record['media_type'] == 'text/plain'
        if not supported:
            raise ContractError('INVALID_ARGUMENT', 'Voice reference requires audio and a plain-text transcript artifact.')


def _phrase(candidate):
    return 'authorize voice identity and reference use ' + candidate


def _evidence(session_id, message_id, candidate):
    from .host_bridge import consuming_user_evidence
    evidence = consuming_user_evidence(session_id, message_id)
    if not re.fullmatch(r'\s*' + re.escape(_phrase(candidate)) + r'[.!\s]*', evidence['content'], re.I):
        raise ContractError('PERMISSION_DENIED', 'User message must explicitly authorize the disclosed identity, exact audio/transcript pins and reference-conditioning use.')
    return {'session_id': session_id, 'message_id': message_id, 'message_sha256': digest(evidence['content'])}


def authorize_reference(runtime, project_id, reference, *, session_id=None):
    """Callback for preferences, pre-read and immediately-pre-invoke fences.

    A saved authorization_ref only locates a revocable record. The current host
    session, exact active user row, explicit consent phrase, scope and actual
    artifact ownership/bytes are all rechecked; strings/credentials never grant.
    """
    from .adapters.voice_controls import REFERENCE_SCHEMA
    validate(reference, REFERENCE_SCHEMA)
    if reference['project_id'] != project_id:
        raise ContractError('PERMISSION_DENIED', 'Voice reference belongs to another project.')
    session = _session(runtime, session_id)
    record = _ledger(runtime.projects._filesystem())
    grant = record['grants'].get(reference['authorization_ref'])
    if not isinstance(grant, dict) or grant.get('state') != 'active':
        raise ContractError('PERMISSION_DENIED', 'Voice source consent is absent or revoked.')
    scope, evidence = grant.get('scope'), grant.get('evidence')
    validate(scope, SCOPE_SCHEMA)
    candidate = record['candidates'].get(reference['authorization_ref'])
    if (not isinstance(scope, dict) or not isinstance(evidence, dict) or evidence.get('session_id') != session
            or not isinstance(candidate, dict) or digest(candidate) != reference['authorization_ref']
            or candidate.get('scope') != scope
            or any(scope[key] != reference[key] for key in ('project_id', 'audio', 'transcript'))):
        raise ContractError('PERMISSION_DENIED', 'Voice source scope or current-session identity differs.')
    if _evidence(session, evidence.get('message_id'), reference['authorization_ref']) != evidence:
        raise ContractError('PERMISSION_DENIED', 'Original voice source user evidence changed or is unavailable.')
    evidence_key = digest({'session_id': session, 'message_id': evidence['message_id']})
    if record['evidence'].get(evidence_key) != reference['authorization_ref']:
        raise ContractError('PERMISSION_DENIED', 'Voice source user evidence is not bound to this scope.')
    _verify_sources(runtime, scope)
    return True


def _source_action(runtime, args, session_id):
    action = args['action']
    fs = runtime.projects._filesystem(write=action != 'voice_source_get')
    if action == 'voice_source_get':
        record = _ledger(fs)
        return {'revision': record['revision'], 'candidates': copy.deepcopy(record['candidates']),
                'grants': copy.deepcopy(record['grants']), 'consuming_permission_granted': False}
    if action == 'voice_source_disclose':
        scope = copy.deepcopy(args['scope'])
        _verify_sources(runtime, scope)
        with fs.lock(BASE + '/ledger.lock'):
            record = _ledger(fs)
            # Reuse a pending/current disclosure; after revocation create a new
            # hash-bound generation so old refs and evidence remain revoked.
            existing = [(key, value) for key, value in record['candidates'].items()
                        if value.get('scope') == scope and
                        record['grants'].get(key, {}).get('state') != 'revoked']
            if existing:
                key = existing[-1][0]
            else:
                candidate = {'scope': scope, 'generation': record['revision']}
                key = digest(candidate)
                record['candidates'][key] = candidate
                _write(fs, record)
            return {'candidate_sha256': key, 'scope': scope, 'revision': record['revision'],
                    'required_user_message': _phrase(key), 'consuming_permission_granted': False,
                    'limitation': 'Identity consent covers only these pins and reference conditioning in the authorizing host session, not training, provider clone objects or spend.'}
    session = _session(runtime, session_id) if action == 'voice_source_authorize' else None
    with fs.lock(BASE + '/ledger.lock'):
        record = _ledger(fs)
        _cas(record, args['expected_revision'])
        key = args.get('candidate_sha256', args.get('authorization_ref'))
        if action == 'voice_source_revoke':
            grant = record['grants'].get(key)
            if grant is None:
                raise ContractError('NOT_FOUND', 'Voice source consent does not exist.')
            if grant['state'] != 'revoked':
                grant['state'] = 'revoked'
                _write(fs, record)
            return {'authorization_ref': key, 'state': 'revoked', 'revision': record['revision'],
                    'consuming_permission_granted': False}
        candidate = record['candidates'].get(key)
        if not isinstance(candidate, dict) or digest(candidate) != key:
            raise ContractError('PERMISSION_DENIED', 'Exact voice source disclosure was not recorded.')
        scope = candidate.get('scope')
        validate(scope, SCOPE_SCHEMA)
        if not isinstance(scope, dict):
            raise ContractError('PERMISSION_DENIED', 'Voice source disclosure is malformed.')
        evidence = _evidence(session, args['message_id'], key)
        evidence_key = digest({'session_id': session, 'message_id': args['message_id']})
        old = record['evidence'].get(evidence_key)
        if old is not None and old != key:
            raise ContractError('PERMISSION_DENIED', 'User consent evidence is already bound to another scope.')
        grant = record['grants'].get(key)
        if grant is not None:
            # A revoked scope cannot be reactivated with replayed old evidence.
            if grant['state'] != 'active' or grant['evidence'] != evidence:
                raise ContractError('PERMISSION_DENIED', 'Existing source scope cannot be reactivated or rebound; disclose a new scope.')
        else:
            _verify_sources(runtime, scope)
            record['grants'][key] = {'scope': copy.deepcopy(scope), 'evidence': evidence, 'state': 'active'}
            record['evidence'][evidence_key] = key
            _write(fs, record)
        reference = {name: copy.deepcopy(scope[name]) for name in ('project_id', 'audio', 'transcript')}
        reference['authorization_ref'] = key
        return {'reference': reference, 'revision': record['revision'], 'state': 'active',
                'consuming_permission_granted': False}


def _documents(runtime, project_id):
    fs = runtime.projects._filesystem()
    pointer = runtime.projects._pointer(fs, project_id)
    return runtime.projects._load(fs, pointer)[1]


def _selected_adapter(runtime, project_id):
    bindings = _documents(runtime, project_id)['bindings', 'project']['value']
    pin = bindings['pins'].get(OPERATION)
    if pin is not None:
        return pin
    candidates = []
    for aid in bindings['selected_adapter_ids']:
        operations = runtime.registry.inspect(aid)['declaration']['operations']
        if any(op['operation'] == OPERATION for op in operations):
            candidates.append(aid)
    # Preference ordering and registry availability never invent a voice route.
    return candidates[0] if len(candidates) == 1 else None


def _engine_default(runtime, project_id, selected_adapter_id=None):
    aid = selected_adapter_id or (_selected_adapter(runtime, project_id) if project_id else None)
    return visible_voice_default(runtime.registry, aid) if aid is not None else None


def _validate_projected(runtime, choice):
    from .options import project_options, validate_selection
    aid = choice['binding']['adapter_id']
    rows = project_options(runtime.registry, getattr(runtime, 'host_bridge', None),
                           operation=OPERATION, adapter_id=aid)['options']
    if len(rows) != 1:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Exact speech option is no longer registered.')
    binding = validate_selection(runtime.registry, rows[0]['selection'], operation=OPERATION,
        parameters=choice['parameters'], binding_parameters=choice['binding_parameters'],
        bridge=getattr(runtime, 'host_bridge', None))
    if binding != choice['binding']:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Selected speech binding changed; no alternate is selected.')


def dispatch(runtime, args, session_id=None):
    """Public motion_capabilities branch dispatch; host supplies session_id."""
    validate(args, {'oneOf': branches()})
    if args['action'].startswith('voice_source_'):
        return _source_action(runtime, args, session_id)
    pid = args.get('project_id')
    project = _documents(runtime, pid)['settings', 'project']['value'].get('voice_preferences') if pid else None
    default = None
    if args['action'] == 'voice_get':
        default = _engine_default(runtime, pid)
    elif (args['action'] == 'voice_resolve' and args.get('explicit') is None
          and project is None and VoicePreferencesStore(runtime.projects).read()['value'] is None):
        default = _engine_default(runtime, pid)
    callback = lambda project_id, reference: authorize_reference(runtime, project_id, reference, session_id=session_id)
    if args['action'] == 'voice_save':
        checked = validate_voice_preferences(args['value'], runtime.registry, project_id=pid,
                                             authorize_reference=callback)
        _validate_projected(runtime, checked)
    result = voice_action(args, registry=runtime.registry, preferences=VoicePreferencesStore(runtime.projects),
        project_preferences=project, engine_default=default, authorize_reference=callback)
    if args['action'] == 'voice_resolve':
        _validate_projected(runtime, result['selection'])
    return result


def resolve_compile_voice(runtime, project_id, task, settings, *, selected_adapter_id=None, session_id=None):
    """Return a copied task with exact speech parameters/reference input pins.

    Call BEFORE generic parameter default expansion, task validation/hash and
    content transaction. `settings` is trusted current Settings.value. Existing
    complete speech parameters are an explicit task choice and beat all defaults.
    New tasks may supply `voice_preferences` (atomic explicit preference), or omit
    language/voice/seed to request Settings > active profile > already-selected
    engine default. Parent schema must expose only those intentional omissions.
    This function strips the optional selector after resolving it; compile and
    normal invocation must still enforce exact adapter/binding and source consent.
    """
    result = copy.deepcopy(task)
    if result.get('operation') != OPERATION:
        return result
    explicit = result.pop('voice_preferences', None)
    use_defaults = result.pop('use_voice_defaults', False)
    params = result.get('parameters', {})
    if explicit is None and not use_defaults and 'voice' in params:
        # Backward compatibility: do not overwrite explicit old speech tasks or
        # guess an adapter ahead of the existing compiler's exact selection.
        return result
    if explicit is None and params:
        raise ContractError('INVALID_ARGUMENT', 'Voice defaults are atomic; omit all speech parameters or supply a complete explicit choice.')
    selected = result.get('adapter_id', selected_adapter_id)
    if selected is None:
        selected = _selected_adapter(runtime, project_id)
    profile = VoicePreferencesStore(runtime.projects).read()['value']
    project = settings.get('voice_preferences')
    default = _engine_default(runtime, project_id, selected) if explicit is None and project is None and profile is None else None
    resolved = resolve_voice_preferences(runtime.registry, project_id=project_id,
        explicit=explicit, project=project, profile=profile, engine_default=default,
        authorize_reference=lambda pid, ref: authorize_reference(runtime, pid, ref, session_id=session_id))
    choice = resolved['selection']
    if selected is not None and choice['binding']['adapter_id'] != selected:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Explicit task adapter differs from resolved voice; no implicit alternate is permitted.')
    _validate_projected(runtime, choice)
    result['adapter_id'] = choice['binding']['adapter_id']
    result['parameters'] = copy.deepcopy(choice['parameters'])
    if choice['binding_parameters'] is not None:
        result['binding_parameters'] = copy.deepcopy(choice['binding_parameters'])
    elif 'binding_parameters' in result:
        raise ContractError('INVALID_ARGUMENT', 'Do not merge task binding options with an atomic voice default.')
    inputs = result.setdefault('inputs', {})
    for port, pin in resolved['reference_inputs'].items():
        bound = {'kind': 'artifact', 'artifact': pin}
        if port in inputs and inputs[port] != bound:
            raise ContractError('ASSET_CHANGED', 'Task reference differs from selected voice source.')
        inputs[port] = bound
    if any(port in inputs and port not in resolved['reference_inputs'] for port in ('reference_audio', 'reference_text')):
        raise ContractError('ASSET_CHANGED', 'Reference inputs require an explicitly authorized voice source.')
    return result
