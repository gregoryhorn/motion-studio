"""Native tool registration with explicit blocked later-unit boundaries.

Project operations use their closed B03 schemas and durable handler. Later-unit
production actions stay blocked until their schemas and implementations exist.
No resource acquisition or production occurs during registration.
"""
from __future__ import annotations

import json
from functools import partial


ACTIONS = {
    "motion_project": ("create", "list", "open", "status", "update"),
    "motion_capabilities": ("discover", "list", "inspect", "usage", "host_readiness", "task_overview", "setup_report", "topology_check", "tool_readiness", "options", "voice_get", "voice_resolve", "voice_save", "voice_remove", "voice_source_disclose", "voice_source_authorize", "voice_source_revoke", "voice_source_get"),
    "motion_asset": ("import", "reference", "list", "get", "probe"),
    "motion_asset_library": ("get", "update", "view"),
    "motion_storyboard": ("get", "update", "view"),
    "motion_plan": ("compile", "list", "inspect", "creative_get", "creative_update", "creative_accept",
                    "eta", "eta_calibrate", "editorial_get", "editorial_update", "editorial_reconform",
                    "extract_inspect", "extract_apply", "extract_bind", "full_master_apply", "full_master_bind", "interchange_import", "interchange_export"),
    "motion_run": ("submit", "list", "status", "cancel", "reconcile", "handoff_claim", "collect", "permission_disclose", "permission_grant", "permission_inspect", "permission_revoke"),
    "motion_caption": ("transcribe", "align", "adopt", "get", "correct", "style", "timing_review", "preview", "export"),
    "motion_review": ("check", "record", "list", "inspect", "gates"),
    "motion_deliver": ("encode", "status", "validate", "promote", "package", "package_validate", "files"),
}


# Human-facing host help. Action fields and constraints remain owned by the
# schema producers below; scripts/docs.py exports this exact registration.
TOOL_HELP = {
    'motion_project': (
        'Create/list/open durable profile-local projects, inspect status and update '
        'revisioned content atomically. Create requires a UUID request_id; updates '
        'require the current expected_revision and a new request_id. Use returned '
        'project IDs explicitly; open does not set an implicit current project. '
        'Project operations do not render media or authorize execution.'),
    'motion_capabilities': (
        'Discover/list/inspect installed adapter declarations, operation schemas, '
        'dependencies and availability without executing engines or models. '
        'Inspect a selected adapter before binding or compiling work; availability '
        'is not permission, proof of successful media execution or universal support. '
        'host_readiness measures the backend host and selected paths/adapter requirements '
        'without starting work; it is not a resource reservation or remote-client proof. '
        'task_overview pages existing job statuses and failed/blocked/stale counts '
        'for one project without renewing leases or launching work. '
        'setup_report passively inspects this plugin bundle and declared dependency '
        'presence without executing engines, installing packs or overriding scanner findings. '
        'topology_check validates declared Desktop locations/addresses, not reachability. '
        'tool_readiness reports cached typed mapping/provider gaps, not execution readiness.'),
    'motion_asset': (
        'Import exact authorized local file bytes into a project, or reference '
        'external local bytes without taking ownership; list/get registered assets. '
        'Use canonical absolute regular-file paths and preserve returned IDs/hashes. '
        'Probe compiles media.probe and submits an owned job using the selected '
        'adapter, expected_revision and UUID request_id; collect/inspect the job '
        'before treating metadata as verified. No remote acquisition is performed.'),
    'motion_asset_library': (
        'Get/update a project asset inventory, requirements, missing material and '
        'assessments before storyboarding. Update takes the complete value, '
        'expected_revision and UUID request_id; get/view may select a historical '
        'revision. View writes a self-contained HTML asset sheet, not a live editor. '
        'No external assets are acquired.'),
    'motion_storyboard': (
        'Get/update ordered visual panels, timing, narration, motion, transitions '
        'and feedback. Requires a committed assessed asset library and registered '
        'image for every panel. Update takes the complete value, expected_revision '
        'and UUID request_id. View exports HTML; edit through update, not the view. '
        'Library changes can make a board stale; ready is agent readiness, not user approval.'),
    'motion_plan': (
        'Compile immutable capability-bound plans from explicit project revisions '
        'and inspect their nodes, effects, gaps and verified manifest handles. '
        'Resolve unsupported bindings before submission. Compile/inspect does '
        'not execute, approve data upload or grant spend authority. Recompile '
        'after changing content or installed bindings; existing plans do not refresh. '
        'Creative actions retain editable script and user delegation; editorial actions '
        'retain source-linked extract selections, selective reconform and deliverable gaps. '
        'ETA uses explicit remaining scope and measured job evidence, never a promised finish time. '
        'Metadata selection/estimation does not start production.'),
    # Existing tool identity intentionally owns creative/editorial/ETA actions;
    # these are not new execution backends or a separate task service.
    'motion_run': (
        'Submit/list/inspect durable owned jobs, cancel/reconcile attempts and '
        'claim/collect typed native handoffs. Submit requires the exact plan pin, '
        'expected_revision and UUID request_id plus existing runtime authority. '
        'A claim or successful host call is not collected output: validate receipts '
        'and status. Unknown authority fails closed; never invent approval or receipt fields.'),
    'motion_caption': (
        'Transcribe/align through connected execution routes; adopt/get/correct/style '
        'canonical captions and request timing review, raster preview or export. '
        'Preserve returned caption/style/timeline pins and exact revisions. '
        'Timing approval requires verified evidence; a preview or transcript is '
        'not approval. Unsupported or unconnected routes fail closed.'),
    'motion_review': (
        'Request deterministic checks, record/list/inspect exact-candidate reviews '
        'and inspect release gates. Reviews bind actual bytes and revisions; '
        'runtime provenance determines actor authority, not a caller claiming to '
        'be the user. Inspect gate results before promotion. Metadata presence '
        'does not establish visual/audio quality or personal acceptance.'),
    'motion_deliver': (
        'Encode/validate delivery candidates through explicit jobs, inspect status, '
        'promote already checked exact bytes, retrieve delivery file records and '
        'build/revalidate supported editable packages. Preserve master/artifact '
        'pins; promotion does not render or repair failed gates. Reconstruction '
        'support is route-specific, not a guarantee for every engine, audio or caption workflow.'),
}


def tool_schema(name: str) -> dict:
    """Return a fresh strict B01 schema (not the full future action contract)."""
    return {
        "name": name,
        "description": (
            "NOT IMPLEMENTED: B01 registration skeleton only. Every listed action "
            "returns blocked with no effects. Accepts only action; production "
            "arguments and functionality are deferred to later build units."
        ),
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": list(ACTIONS[name])}},
            "required": ["action"],
            "additionalProperties": False,
        },
    }


def blocked_handler(name: str, args, **_host_context) -> str:
    """Fail closed, including direct calls that bypass host schema validation."""
    valid = (
        isinstance(args, dict)
        and set(args) == {"action"}
        and isinstance(args["action"], str)
        and args["action"] in ACTIONS[name]
    )
    action = args["action"] if valid else ""
    if valid:
        code, status = "NOT_IMPLEMENTED", "blocked"
        message = "B01 registration skeleton only; this action is not implemented."
        details = {"resource": name, "reason": "Later build unit required."}
        retry = "after_dependency"
    else:
        code, status = "VALIDATION_ERROR", "error"
        message = "B01 accepts only an action from this tool's declared inventory."
        details = {"field_path": "$", "expected": "closed B01 action envelope",
                   "received_type": type(args).__name__}
        retry = "after_input_change"
    return json.dumps({
        "ok": False, "tool": name, "action": action, "status": status,
        "summary": message,
        "error": {"code": code, "message": message, "retry": retry,
                  "effect": "none", "details": details},
    }, ensure_ascii=True)


def host_tool_schema(schema):
    """Publish visible object properties for hosts that lower root oneOf.

    Preserve the closed action alternatives for JSON-schema-aware hosts and
    runtime validation. The top-level projection only makes arguments visible;
    it does not relax the native handler's per-action contract.
    """
    import copy
    from .host_schema import compact_parameters
    schema = copy.deepcopy(schema)
    parameters = schema.get('parameters', {})
    alternatives = parameters.get('oneOf')
    if not isinstance(alternatives, list):
        schema['parameters'] = compact_parameters(parameters)
        return schema
    fields = {}
    required = None
    for alternative in alternatives:
        if not isinstance(alternative, dict) or 'properties' not in alternative:
            return schema
        required = set(alternative.get('required', [])) if required is None else required.intersection(alternative.get('required', []))
        for key, value in alternative['properties'].items():
            values = fields.setdefault(key, [])
            if value not in values:
                values.append(value)
    properties = {}
    for key, values in fields.items():
        if key == 'action' and all('const' in v for v in values):
            properties[key] = {'type': 'string', 'enum': [v['const'] for v in values]}
        else:
            properties[key] = values[0] if len(values) == 1 else {'anyOf': values}
    parameters.update(type='object', properties=properties, required=sorted(required or []), additionalProperties=False)
    schema['parameters'] = compact_parameters(parameters)
    return schema


def native_handler(name, handler, args, **host_context):
    from .runtime import NativeRuntime
    from .project import ProjectStore
    from .host_bridge import handler_bridge
    projects = ProjectStore()
    bridge = handler_bridge(projects, name, args, host_context)
    runtime = NativeRuntime(projects, host_bridge=bridge)
    return handler(args, _runtime=runtime, **host_context)


def review_handler(args, **host_context):
    """Expose existing native review semantics without granting actor authority."""
    from .delivery import NativeDeliveryService
    from .runtime import NativeRuntime
    runtime = host_context.pop('_runtime', None) or NativeRuntime()
    return json.dumps(runtime._call('motion_review', args,
        lambda: NativeDeliveryService(runtime, session_id=host_context.get('session_id'),
            task_id=host_context.get('task_id')).reviews.dispatch(args)),
        ensure_ascii=True, allow_nan=False)


def delivery_handler(args, **host_context):
    """Expose existing delivery behavior without granting execution or review authority."""
    from .delivery import NativeDeliveryService
    from .runtime import NativeRuntime
    runtime = host_context.pop('_runtime', None) or NativeRuntime()
    return json.dumps(runtime._call('motion_deliver', args,
        lambda: NativeDeliveryService(runtime, session_id=host_context.get('session_id'),
            task_id=host_context.get('task_id')).dispatch(args)),
        ensure_ascii=True, allow_nan=False)


def register_tools(ctx) -> None:
    """Register only native tools; no authority or runtime resource acquisition."""
    from .contracts import project_tool_schema
    from .project import project_handler
    from .assets import asset_tool_schema, asset_handler
    from .runtime import (capability_tool_schema, capability_handler,
                          plan_tool_schema, plan_handler, run_tool_schema, run_handler,
                          caption_tool_schema, caption_handler)
    from .reviews import review_tool_schema
    from .delivery import delivery_tool_schema
    from .preproduction import production_tool_schema, production_handler
    implemented = {"motion_project": (project_tool_schema, project_handler),
                   "motion_asset": (asset_tool_schema, asset_handler),
                   "motion_capabilities": (capability_tool_schema, capability_handler),
                   "motion_plan": (plan_tool_schema, plan_handler),
                   "motion_run": (run_tool_schema, run_handler),
                   "motion_caption": (caption_tool_schema, caption_handler),
                   "motion_review": (review_tool_schema, review_handler),
                   "motion_deliver": (delivery_tool_schema, delivery_handler)}
    for name in ('motion_asset_library', 'motion_storyboard'):
        implemented[name] = (partial(production_tool_schema, name), partial(production_handler, name))

    for name in ACTIONS:
        schema = implemented[name][0]() if name in implemented else tool_schema(name)
        if name in implemented:
            schema['description'] = TOOL_HELP[name]
        ctx.register_tool(
            name=name,
            toolset="motion_studio",
            schema=host_tool_schema(schema),
            handler=(partial(native_handler, name, implemented[name][1])
                     if name in ('motion_project', 'motion_capabilities', 'motion_plan', 'motion_run', 'motion_caption', 'motion_review', 'motion_deliver', 'motion_asset_library', 'motion_storyboard')
                     else implemented[name][1] if name in implemented else partial(blocked_handler, name)),
            is_async=False,
            override=False,
        )

    # Additive prepared-request bridge. Existing ten native registrations above
    # and their handlers/schemas are intentionally unchanged.
    from .ui_handoff import (handoff_tool_schema, handoff_handler,
                             observe_handoff_call)
    ctx.register_tool(name='motion_ui_handoff', toolset='motion_studio',
        schema=host_tool_schema(handoff_tool_schema()), handler=handoff_handler,
        is_async=False, override=False)
    ctx.register_hook('pre_tool_call', observe_handoff_call)

