"""One passive capability-option projection for conversation, UI and voice.

Only an existing registry and HostBridge's existing request observation are read.
Schema support is not generation evidence, an admission decision, or permission.
Selections pin exact identities; revalidation never picks a replacement adapter.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from .capabilities import DEFS, checked
from .contracts import ADAPTER, DIGEST, STAMP, TEXT, ContractError, arr, digest, enum, nullable, obj
from .tool_integration import (native_option_identity, observed_tool_snapshot,
                               require_compatible_binding)


SELECTION_SCHEMA = obj({
    'adapter_id': ADAPTER, 'operation': TEXT, 'binding': copy.deepcopy(DEFS['FrozenBinding']),
    'identities': obj({name: obj({'state': enum('known', 'unknown'), 'value': nullable(TEXT),
                                  'source': nullable({'const': 'trusted_registration'})})
                       for name in ('provider', 'model', 'account')}),
    'scope': obj({'session_id': nullable(TEXT), 'api_request_id': nullable(TEXT)}),
    'native_tool': nullable(obj({'tool_name': TEXT, 'schema_sha256': nullable(DIGEST)})),
    'observation': obj({'observed_at': STAMP, 'expires_at': STAMP}), 'sha256': DIGEST})


def branches():
    return [obj({'action': {'const': 'options'}, 'operation': TEXT,
                 'adapter_id': ADAPTER,
                 'requested_controls': {**arr(TEXT, unique=True), 'maxItems': 64}},
                ['operation', 'adapter_id', 'requested_controls'])]


def dispatch(runtime, args):
    """motion_capabilities options; deliberately never touch runtime.registry."""
    checked(args, branches()[0])
    return project_options(runtime._registry, runtime.host_bridge,
                           operation=args.get('operation'), adapter_id=args.get('adapter_id'),
                           requested_controls=args.get('requested_controls', ()))


def _identities(metadata):
    supplied = metadata.get('identities', {})
    return {key: {'state': 'known' if supplied.get(key) is not None else 'unknown',
                  'value': supplied.get(key),
                  'source': 'trusted_registration' if supplied.get(key) is not None else None}
            for key in ('provider', 'model', 'account')}


def _controls(schema, schema_id, *, role, unsupported=(), requested=()):
    # Never flatten conditional alternatives into promises of independent knobs.
    # Complete schemas/branches remain available to clients for exact validation.
    properties = schema.get('properties', {})
    required = schema.get('required', [])
    conditional = any(key in schema for key in ('oneOf', 'anyOf', 'allOf', 'if', '$ref'))
    rows = []
    for name in sorted(set(properties) | set(requested) | set(unsupported)):
        supported = name in properties and name not in unsupported
        state = ('supported' if supported else 'unavailable' if name in unsupported or
                 (schema.get('additionalProperties') is False and not conditional) else 'unknown')
        definition = copy.deepcopy(properties.get(name)) if supported else None
        rows.append(dict(name=name, state=state, schema_id=schema_id, role=role,
                         required=name in required, schema=definition,
                         choices=(copy.deepcopy(definition['enum']) if definition and 'enum' in definition
                                  else [copy.deepcopy(definition['const'])] if definition and 'const' in definition
                                  else None),
                         choice_state='finite' if definition and ('enum' in definition or 'const' in definition)
                                      else 'unknown',
                         reason='Exact registered schema; not runtime exercise evidence.' if supported
                                else 'Explicitly unsupported by this binding.' if name in unsupported
                                else 'Closed schema has no such control.' if state == 'unavailable'
                                else 'No exact control support observed.'))
    return rows


def project_options(registry, bridge=None, *, operation=None, adapter_id=None, requested_controls=()) -> dict[str, Any]:
    """Return JSON-safe cached options. No construction, probing or fallback.

    `row['selection']` is the opaque exact identity passed to validate_selection.
    Metadata identities are supplied only by trusted registration, never inferred
    from catalog/adapter labels. Missing model/account identities stay unknown.
    """
    checked({'action': 'options', **({'operation': operation} if operation is not None else {}),
             **({'adapter_id': adapter_id} if adapter_id is not None else {}),
             'requested_controls': list(requested_controls)}, branches()[0])
    snapshot = observed_tool_snapshot(bridge)
    rows = []
    entries = registry.discover() if registry is not None else []
    for entry in entries:
        assert registry is not None  # Entries only come from the existing registry.
        aid = entry['adapter_id']
        if adapter_id is not None and aid != adapter_id:
            continue
        for operation_name in entry['operations']:
            if operation is not None and operation_name != operation:
                continue
            descriptor = registry.option_descriptor(aid, operation_name)
            op = descriptor['operation']
            metadata = descriptor['option_metadata']
            schemas = descriptor['schemas']
            request_id = op['request_schema']
            native = native_option_identity(registry, aid, op['operation'], snapshot)
            availability = descriptor['availability']
            expired = datetime.fromisoformat(availability['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc)
            state = ('supported' if availability['state'] == 'available' and not expired else
                     'unavailable' if availability['state'] in ('unavailable', 'disabled') else 'unknown')
            reason = ('Cached available adapter and exact registered schema; not execution evidence.' if state == 'supported'
                      else 'Cached observation expired; explicit refresh is required.' if expired
                      else 'Adapter is not currently qualified available: ' + availability['state'])
            if native is not None and native['state'] != 'supported':
                state, reason = native['state'], native['reason']
            identities = _identities(metadata)
            roles = {request_id: 'parameters', **metadata.get('schema_roles', {})}
            schema_rows, controls = [], []
            for sid, schema in sorted(schemas.items()):
                role = roles.get(sid, 'result' if sid == op['result_schema'] else 'unclassified')
                schema_rows.append(dict(schema_id=sid, schema_sha256=digest(schema), role=role,
                                        schema=copy.deepcopy(schema)))
                if role in ('parameters', 'binding_parameters', 'artifact_controls'):
                    controls.extend(_controls(schema, sid, role=role,
                        unsupported=metadata.get('unsupported_controls', ()),
                        requested=requested_controls if role == 'parameters' else ()))
            identity = dict(adapter_id=aid, operation=op['operation'], binding=descriptor['binding'],
                            identities=identities, scope=snapshot['scope'],
                            native_tool=None if native is None else
                                {key: native[key] for key in ('tool_name', 'schema_sha256')},
                            observation={'observed_at': availability['observed_at'],
                                         'expires_at': availability['expires_at']})
            selection = {**identity, 'sha256': digest(identity)}
            rows.append(dict(adapter_id=aid, label=descriptor['declaration']['label'],
                operation=op['operation'], state=state, reason=reason, availability=availability,
                freshness='expired' if expired else 'current_cached_observation',
                identities=identities, binding=descriptor['binding'], schemas=schema_rows,
                controls=controls, native_tool=native, selection=selection,
                selectable=state == 'supported', request_compatibility='not_evaluated',
                support={'discoverable': True, 'schema_supported': True,
                         'available': True if state == 'supported' else False if state == 'unavailable' else None,
                         'contract_tested': availability['contract_tested'],
                         'qualified': None, 'temporarily_blocked': None,
                         'qualification_evidence': copy.deepcopy(availability['exercised_evidence']),
                         'note': 'No admission probe; unknown temporary blocking/qualification is not false.'},
                execution_verified=False, execution_authorized=False))
    return dict(schema='motion/v1/capability-options',
                registry_state='not_constructed' if registry is None else 'existing_registry',
                observation={key: value for key, value in snapshot.items() if key != 'inventory'},
                state='observed' if rows else 'unknown' if registry is None else 'unavailable',
                reason=None if rows else 'No matching operation in the existing observed registry; no fallback selected.',
                options=rows, execution_authorized=False, execution_verified=False,
                qualification='Schema-backed passive options, not runtime exercise or permission.')


def validate_selection(registry, selection, *, operation, parameters,
                       binding_parameters=None, bridge=None, required_features=()):
    """Recheck an exact projected selection before compile/execute; return binding.

    Parent must call this again immediately before effectful execution under its
    existing authority fence. This function grants no permission and does not
    validate artifact-control *contents*; their normal adapter validator still
    runs. Selection state must be persisted beside the plan's frozen binding.
    """
    if not isinstance(selection, dict) or not isinstance(selection.get('adapter_id'), str):
        raise ContractError('INVALID_ARGUMENT', 'An exact projected option selection is required.')
    checked(selection, SELECTION_SCHEMA)
    if not isinstance(parameters, dict):
        raise ContractError('INVALID_ARGUMENT', 'Selected operation parameters must be an object.')
    if binding_parameters is not None and (not isinstance(binding_parameters, dict) or
            not isinstance(binding_parameters.get('values'), dict)):
        raise ContractError('INVALID_ARGUMENT', 'Selected binding options require an object values bag.')
    aid = selection['adapter_id']
    report = project_options(registry, bridge, operation=operation, adapter_id=aid)
    if len(report['options']) != 1:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Exact selected adapter/operation is no longer registered; no fallback.')
    row = report['options'][0]
    if row['selection'] != selection:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Selected schema, binding, model/account or session/request identity changed; explicitly select again.')
    if not row['selectable']:
        raise ContractError('DEPENDENCY_UNAVAILABLE', row['reason'])
    metadata = registry.option_descriptor(aid, operation)['option_metadata']
    unsupported = set(metadata.get('unsupported_controls', ()))
    submitted = set(parameters)
    if isinstance(binding_parameters, dict):
        submitted.update(binding_parameters.get('values', {}))
    if unsupported & submitted:
        raise ContractError('SCHEMA_UNSUPPORTED', 'Explicitly unsupported controls: ' + ', '.join(sorted(unsupported & submitted)))
    matched = registry.match(operation, required_features, [aid], parameters=parameters)
    if matched != [aid]:
        raise ContractError('SCHEMA_UNSUPPORTED', 'Controls/features are not supported by the exact selected binding; no fallback.')
    try:
        binding = registry.binding(aid, operation, parameters, binding_parameters)
    except (KeyError, StopIteration) as exc:
        raise ContractError('SCHEMA_UNSUPPORTED', 'Selected request/binding schema is unavailable.') from exc
    if binding != row['binding']:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Exact binding changed while validating options.')
    if row['native_tool'] is not None:
        # Read the same passive API again, never HostBridge.inventory()/refresh.
        snapshot = observed_tool_snapshot(bridge)
        if snapshot['scope'] != selection['scope']:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Host request changed during option validation.')
        require_compatible_binding(registry, binding, operation=operation,
                                   parameters=parameters, binding_parameters=binding_parameters,
                                   inventory=snapshot['inventory'])
    return copy.deepcopy(binding)
