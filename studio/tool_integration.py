"""Read-only exact native mappings, not generic tool/shell delegation.

Inventory must come from the current trusted HostBridge.inventory(). Discovery
never builds a registry, installs, invokes tools, connects to or probes a service.
Schema compatibility is explicitly not execution/output-adoption evidence.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .contracts import ContractError, digest, validate
from . import resources
from .adapters import native_tools
from . import host_bridge


def _mappings():
    return [(b.adapter_id, b.operation, b.tool_name, b) for b in native_tools.BINDINGS.values()] + [
        (host_bridge.ADAPTER_ID, host_bridge.OPERATION, host_bridge.FRAME_TOOL, None)]


def _identity(recipe, schema):
    if recipe is not None:
        return native_tools.implementation_identity(recipe, schema)
    # Keep the exact register_frame_adapter source-bytes/schema formula.
    return digest(dict(bridge_source=host_bridge.digest_bytes(Path(host_bridge.__file__).read_bytes()),
        host_schema=digest(schema) if schema else None))


def observed_tool_snapshot(bridge=None):
    """Read only the already observed exact request; never refresh inventory.

    Scope travels with option selections so a new session/request cannot reuse
    an old selection, even when the tool input schemas happen to be identical.
    """
    scope = {'session_id': None, 'api_request_id': None}
    if bridge is None:
        return dict(scope=scope, inventory=None, state='unknown',
                    error_code='HOST_SCHEMA_UNAVAILABLE',
                    reason='No trusted current session/request observation available.')
    identity = bridge.identity
    scope = {key: identity.get(key) or None for key in scope}
    if not all(scope.values()):
        return dict(scope=scope, inventory=None, state='unknown',
                    error_code='HOST_SCHEMA_UNAVAILABLE',
                    reason='Exact current session and API request identities are required.')
    try:
        inventory = bridge.observed_inventory()
    except ContractError as exc:
        return dict(scope=scope, inventory=None, state='unknown',
                    error_code=exc.code, reason=str(exc))
    if not isinstance(inventory, dict):
        return dict(scope=scope, inventory=None, state='unknown',
                    error_code='HOST_SCHEMA_UNAVAILABLE', reason='Observed inventory is not an exact schema mapping.')
    return dict(scope=scope, inventory=copy.deepcopy(inventory), state='current',
                error_code=None, reason='Existing trusted current request observation; not execution evidence.')


def native_option_identity(registry, adapter_id, operation, snapshot):
    """Qualify a frozen native mapping without asking for request parameters."""
    mapping = next((row for row in _mappings() if row[:2] == (adapter_id, operation)), None)
    if mapping is None:
        return None
    _, _, tool_name, recipe = mapping
    inventory = snapshot['inventory']
    schema = inventory.get(tool_name) if inventory is not None else None
    result = dict(tool_name=tool_name, state='unknown', schema_sha256=None,
                  reason=snapshot['reason'])
    if inventory is None:
        return result
    if schema is None:
        result.update(state='unavailable', reason='Exact mapped tool absent from the observed current request.')
    elif not isinstance(schema, dict) or not schema:
        result.update(state='unavailable', reason='Exact mapped tool has no usable input schema.')
    else:
        result['schema_sha256'] = digest(schema)
        observed = _identity(recipe, schema)
        frozen = registry.option_descriptor(adapter_id, operation)['binding']['implementation_sha256']
        result.update(state='supported' if observed == frozen else 'unavailable',
                      reason='Exact registered mapping identity matches current observed schema.' if observed == frozen
                      else 'Registered mapping identity differs from current observed tool schema; refresh registration explicitly.')
    return result


def tool_readiness(registry, inventory=None):
    """Return passive JSON-safe diagnostics from an EXISTING registry/inventory.

    inventory: current trusted session/request {exact_tool_name: input_schema},
    or None when no session-bound inventory is available. No HostBridge method,
    provider method, registry builder or model probe is called here. Caller owns
    provenance/session freshness; an arbitrary project dict is NOT trusted input.
    ready remains False until compatible_tools validates actual request controls.
    """
    if inventory is not None and not isinstance(inventory, dict):
        raise ContractError('INVALID_ARGUMENT', 'Inventory must be a trusted exact-name/schema mapping or None.')
    entries = {entry['adapter_id']: entry for entry in registry.discover()} if registry is not None else {}
    rows = []
    for adapter_id, operation, tool_name, recipe in _mappings():
        if adapter_id not in entries:
            continue  # supported source code is not a registered/connected operation
        row = dict(adapter_id=adapter_id, operation=operation, tool_name=tool_name,
            availability=entries[adapter_id]['availability'], connected=False,
            ready=False, schema_sha256=None, binding=None, binding_identity_state='not_checked',
            state='inventory_not_observed', request_compatibility='not_evaluated',
            qualification='not_executed', output_adoption='trusted_host_receipt_and_validated_output_required',
            execution_isolation='external_host_not_qualified_by_local_kernel_limits',
            error_code=None, reason='No trusted current session/request inventory supplied.')
        if inventory is not None:
            schema = inventory.get(tool_name)
            if schema is None:
                row.update(state='tool_absent', error_code='DEPENDENCY_UNAVAILABLE',
                    reason='Exact typed tool is absent from current trusted inventory.')
            elif not isinstance(schema, dict) or not schema:
                row.update(state='invalid_schema', error_code='SCHEMA_UNSUPPORTED', reason='No usable exact input schema observed.')
            else:
                row['schema_sha256'] = digest(schema)
                if row['availability'] != 'available':
                    row.update(state='adapter_unavailable', error_code='DEPENDENCY_UNAVAILABLE',
                        reason='Registry does not qualify this adapter as available.')
                else:
                    row.update(connected=True, state='schema_observed_binding_unchecked',
                        reason='Exact tool name/schema observed; frozen binding identity and request controls remain unchecked.')
        rows.append(row)
    resource_names = sorted(set(resources._PROVIDERS) | {'local-audio-gpu'})
    lifecycle = [dict(resource=name, **resources.provider_capabilities(name),
        execution_isolation='provider_not_kernel_qualified',
        note='Code capability only; no service readiness probe or lease acquired.') for name in resource_names]
    return dict(schema='motion/v1/tool-lifecycle-readiness',
        inventory_state='not_observed' if inventory is None else 'trusted_current_request_supplied',
        observed_tools=[dict(tool_name=name, schema_sha256=digest(schema))
            for name, schema in sorted((inventory or {}).items()) if isinstance(schema, dict) and schema],
        registry_state='not_constructed' if registry is None else 'existing_registry',
        candidates=rows, advertised_operations=[],
        resources=lifecycle, execution_verified=False,
        safety_blockers=[
            'External host tools and resident services need execution-host admission; local child limits do not constrain them.',
            'In-process provider model loading/inference is not kernel-qualified; use a supported independently admitted service boundary.'])


def compatible_tools(registry, bridge=None, *, operation, parameters, selected=(),
                     binding_parameters=None, inventory=None, required_features=()):
    """Validate bounded request controls and exact frozen mapping without dispatch.

    Symbolic file paths test only input-schema shape, not any artifact or media.
    The existing adapter resolves real pins and uses the normal trusted handoff
    and output validation during execution. A restricted literal-path schema can
    conservatively refuse this dry compatibility check; it is never bypassed.
    """
    if inventory is not None and bridge is not None:
        raise ContractError('INVALID_ARGUMENT', 'Supply either trusted inventory or bridge, not both.')
    if bridge is not None:
        inventory = bridge.inventory()
    report = tool_readiness(registry, inventory)
    recipes = {adapter_id: recipe for adapter_id, _, _, recipe in _mappings()}
    selected = tuple(selected)
    considered = selected or tuple(row['adapter_id'] for row in report['candidates'] if row['operation'] == operation)
    matched = set(registry.match(operation, required_features, considered, parameters=parameters))
    rows = []
    for source in report['candidates']:
        if source['operation'] != operation or (selected and source['adapter_id'] not in selected):
            continue
        row = copy.deepcopy(source)
        rows.append(row)
        if not row['connected']:
            continue
        try:
            if row['adapter_id'] not in matched:
                raise ContractError('ADAPTER_INCOMPATIBLE', 'Adapter does not match exact parameters/features/options.')
            if binding_parameters is not None:
                raise ContractError('UNSUPPORTED_FEATURE', 'This bounded native mapping accepts no binding options.')
            recipe = recipes[row['adapter_id']]
            if recipe is not None:
                recipe.validate_parameters(parameters)
                arguments = recipe.arguments('/__motion_schema_only__/input',
                    '/__motion_schema_only__/output.' + recipe.extension, parameters)
            else:
                at = parameters['at']
                if (parameters['format'] != 'png' or parameters['apply_rotation'] is not True
                        or at['domain'] != 'frame' or at['origin'] != 'source' or at['index'] != 0):
                    raise ContractError('UNSUPPORTED_FEATURE', 'Frame mapping accepts source frame zero PNG/native rotation only.')
                arguments = dict(input='/__motion_schema_only__/input', output='/__motion_schema_only__/output.png',
                    time=0, format='png', overwrite=False, timeout_s=60)
            validate(arguments, inventory[row['tool_name']])
            binding = registry.binding(row['adapter_id'], operation, parameters, binding_parameters)
            # Detect a registry refresh/change during compatibility inspection.
            if binding['implementation_sha256'] != _identity(recipe, inventory[row['tool_name']]):
                raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen binding changed during selection.')
            row.update(ready=True, binding=copy.deepcopy(binding), binding_identity_state='exact', request_compatibility='compatible',
                qualification='typed_schema_compatible_not_executed',
                reason='Bounded controls and mapped argument shape accepted; input pins/output remain unverified.')
        except (ContractError, KeyError, TypeError, ValueError) as exc:
            row.update(ready=False, request_compatibility='incompatible',
                binding_identity_state='changed_or_incompatible',
                error_code=getattr(exc, 'code', 'SCHEMA_UNSUPPORTED'),
                reason='Exact bounded controls or mapped argument shape are incompatible with the registered/current schema.')
    report['candidates'] = rows
    report['advertised_operations'] = sorted({r['operation'] for r in rows if r['ready']})
    report['selection_policy'] = 'exact_unique_compatible_mapping_no_silent_fallback'
    return report


def select_compatible_tool(report, *, adapter_id=None):
    """Select one compatible exact identity; ambiguity never triggers fallback."""
    candidates = [row for row in report['candidates'] if row['ready'] and
        (adapter_id is None or row['adapter_id'] == adapter_id)]
    if len(candidates) != 1:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Select exactly one compatible registered typed mapping; no fallback was chosen.')
    return copy.deepcopy(candidates[0])


def require_compatible_binding(registry, binding, *, operation, parameters,
                               binding_parameters=None, bridge=None, inventory=None):
    """Gate an already selected exact native identity; never choose a fallback.

    Non-native adapters keep their own validation. Native mappings require a
    trusted current inventory and the complete unchanged frozen core binding.
    The caller owns the bridge/inventory, neither comes from project JSON.
    """
    adapter_id = binding['adapter_id']
    if adapter_id not in {aid for aid, _, _, _ in _mappings()}:
        return None
    report = compatible_tools(registry, bridge, operation=operation, parameters=parameters,
        selected=[adapter_id], binding_parameters=binding_parameters, inventory=inventory)
    candidate = select_compatible_tool(report, adapter_id=adapter_id)
    if candidate['binding'] != binding:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Current typed mapping differs from the complete frozen binding.')
    return candidate
