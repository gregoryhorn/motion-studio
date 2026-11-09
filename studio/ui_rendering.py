"""Canonical UI graph -> owned compositor -> NativeRuntime.plan integration.

No task runner, worker, rendering thread, registry mutation or provider probe is
created here. Host registration/schema and timing-router wiring remain explicit.
The legacy B03 document compiler is deliberately a separate target: canonical
layers cannot be represented by silently deleting fields from a B03 Scene.
"""
from __future__ import annotations

import copy
from pathlib import Path

from .adapters import ui_compositor as compositor
from .contracts import ContractError, D, canonical, digest, validate

RECIPE_ID = 'canonical_graph_render_v1'
_PUBLIC_PIN_KEYS = {'kind', 'document_id', 'document_version_id', 'sha256'}
_ASSET_PIN_KEYS = {'asset_id', 'asset_version_id', 'sha256'}


def _require(condition, code, message):
    if not condition:
        raise ContractError(code, message)


def compile_canonical_graph(graph, recipe):
    """Pure exact graph/schema closure, not a B03 Scene or execution receipt.

    Recipe is mandatory: caption font/style and RGB background are content, not
    renderer defaults. Empty editable projects remain supported by the legacy
    compiler; actual compositor plans require a nonempty bounded composition.
    """
    from .ui_graph import schema_catalog, validate_graph
    validate_graph(graph)
    compositor.validate_graph(graph, recipe)
    schemas = schema_catalog()
    return dict(schema='motion/ui/canonical-graph-closure/v1', recipe_id=RECIPE_ID,
                graph=copy.deepcopy(graph), graph_sha256=digest(graph),
                recipe=copy.deepcopy(recipe), recipe_sha256=digest(recipe),
                schemas=schemas, schemas_sha256=digest(schemas))


def _public_pin(doc):
    return {key: copy.deepcopy(doc[key]) for key in sorted(_PUBLIC_PIN_KEYS)}


def _walk(value, keys):
    if isinstance(value, dict):
        if set(value) == keys:
            yield value
        else:
            for child in value.values():
                yield from _walk(child, keys)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, keys)


def document_closure(runtime, context, graph, *, resolve_document=None):
    """Publish actual public document bytes with exact public identity preserved.

    The graph is a trusted saved version supplied by UIExecution, not a browser
    payload. An optional trusted historical resolver(runtime, context, public_pin)
    must return the COMPLETE public production-document record (including schema
    pin and value), never a current-head substitution or backend-only envelope.
    All recursive references are validated before publication. Artifacts retain
    public hashes unchanged; engine artifact hashes retain their sha256: prefix.
    """
    from .ui_graph import _validate_document, schema_catalog
    docs = graph['production_documents']
    if not docs:
        return []
    _require(isinstance(context.get('private_project_id'), str),
             'INTEGRATION_UNAVAILABLE', 'Exact owned native project binding required.')
    pid = context['private_project_id']
    by_pin = {canonical(_public_pin(doc)): copy.deepcopy(doc) for doc in docs}
    queue = list(by_pin)
    visited = set()
    assets = {(a['asset_id'], a['asset_version_id'], a['sha256']): a['artifact']
              for a in graph['asset_refs']}
    dependencies = {}
    while queue:
        key = queue.pop(0)
        if key in visited:
            continue
        _require(len(visited) < 1000, 'LIMIT_EXCEEDED', 'Document closure exceeds bound.')
        visited.add(key)
        doc = by_pin[key]
        _validate_document(doc)
        pins = []
        for asset in _walk(doc['value'], _ASSET_PIN_KEYS):
            pin = assets.get((asset['asset_id'], asset['asset_version_id'], asset['sha256']))
            _require(pin is not None, 'ASSETS_UNRESOLVED',
                     'Document asset is absent from exact frozen graph hydration.')
            runtime.artifacts.resolve(pid, pin)
            if pin not in pins:
                pins.append(copy.deepcopy(pin))
        dependencies[key] = pins
        for ref in _walk(doc['value'], _PUBLIC_PIN_KEYS):
            child = canonical(ref)
            if child not in by_pin:
                if not callable(resolve_document):
                    raise ContractError('INTEGRATION_UNAVAILABLE',
                                        'Historical public document bytes require an authorized resolver.')
                record = resolve_document(runtime, context, copy.deepcopy(ref))
                _require(isinstance(record, dict) and
                         set(record) == _PUBLIC_PIN_KEYS | {'schema_ref', 'value'} and
                         _public_pin(record) == ref,
                         'STALE_DEPENDENCY', 'Resolver returned a different public document pin.')
                _validate_document(record)
                by_pin[child] = copy.deepcopy(record)
            queue.append(child)
    catalog = schema_catalog()
    result = []
    for key in sorted(visited):
        doc = by_pin[key]
        value = dict(schema='motion/ui/public-document-closure/v1',
                     public_ref=_public_pin(doc), schema_ref=copy.deepcopy(doc['schema_ref']),
                     public_schema=copy.deepcopy(catalog[doc['kind']]['schema']),
                     value=copy.deepcopy(doc['value']))
        pin = runtime.artifacts.publish_json(pid, value, inputs=dependencies[key])
        validate(pin, D['ArtifactRef'])
        runtime.artifacts.resolve(pid, pin)
        path = Path(runtime.artifact_path(pid, pin))
        _require(not path.is_symlink() and path.is_file(), 'PATH_UNSAFE',
                 'Document closure publication is not an owned regular file.')
        _require(path.read_bytes() == canonical(value) and pin['sha256'] == digest(value),
                 'HASH_MISMATCH', 'Document closure publication differs from canonical bytes.')
        if pin not in result:
            result.append(copy.deepcopy(pin))
    return result


def make_plan_builder(recipe, *, resolve_document=None, resolve_asset=None, mode='auto'):
    """Return builder(runtime, context, pinned_graph, frame_range).

    Bind with execution.bind_graph_renderer(builder, recipe_id=RECIPE_ID).
    Pass resolve_asset=integrations['_asset_source_resolver']; its authoritative
    graph record must match the frozen private asset exactly. Public callers do
    not supply artifact pins or stream facts. The optional resolve_document is a
    trusted historical public-record resolver, not a current-head lookup.
    Auto mode uses compose for the full range and frame for a partial singleton.
    The actual owned builder verifies revision/version identity, validates every
    disabled/unplaced record, verifies source/dependency bytes, publishes immutable
    source, reads it back and calls runtime.plan(action='compile'). Its normal
    envelope (including honest blocked gaps) is returned unchanged. It never runs
    or approves the plan. 'frame' is a separate owned operation, not a background
    render shortcut. Partial multi-frame ranges remain explicitly unsupported.
    """
    _require(mode in ('auto', 'composition', 'render', 'frame'), 'INVALID_ARGUMENT',
             'Use auto, composition or frame mode (render is a compatibility alias).')
    frozen_recipe = copy.deepcopy(recipe)

    def resolve_documents(runtime, context, graph):
        return document_closure(runtime, context, graph, resolve_document=resolve_document)

    owned_builder = compositor.make_plan_builder(frozen_recipe,
                                                resolve_documents=resolve_documents,
                                                mode='composition' if mode in ('auto', 'render') else mode)

    def build(runtime, context, pinned_graph, frame_range):
        # Both contracts matter: the renderer validates supported pixels while
        # the public graph validator validates native identities/document pins.
        # Neither can replace the other or authorize a browser-provided graph.
        for asset in pinned_graph['asset_refs']:
            if not callable(resolve_asset):
                raise ContractError('INTEGRATION_UNAVAILABLE',
                                    'Graph assets require the trusted UI asset-source resolver.')
            public = {key: copy.deepcopy(asset[key]) for key in sorted(_ASSET_PIN_KEYS)}
            authoritative = resolve_asset(context, public)
            _require(authoritative == asset, 'STALE_DEPENDENCY',
                     'Frozen graph asset differs from its exact owned association/probe facts.')
        compile_canonical_graph(pinned_graph, frozen_recipe)
        selected = owned_builder
        full = dict(start_frame=0, end_frame=pinned_graph['format']['duration_frames'])
        if mode == 'auto' and frame_range != full and frame_range['end_frame'] - frame_range['start_frame'] == 1:
            selected = compositor.make_plan_builder(frozen_recipe,
                                                   resolve_documents=resolve_documents, mode='frame')
        return selected(runtime, context, pinned_graph, frame_range)

    return build
