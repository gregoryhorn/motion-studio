"""Prepare recovery-as-new; never persist, mutate a head, or start production.

Finite API: prepare_recovery(base_graph, *, source, current_head, review,
reviewed_sha256, authorize_reference, id_factory=None) -> dict. ``source`` and
``current_head`` are authoritative server pins, each containing composition_id,
version_id, composition_revision and sha256 (the saved VERSION hash, not the
helper's graph hash). ``base_graph`` is the exact retained source graph.

``review`` has exactly source, current_head, base_graph_sha256,
schema_catalog_sha256 and transaction. Transaction has exactly operations,
dependency_policy='reject_unlisted', acknowledged_dependency_ids and
 document_rebind_ids. The last list authorizes value-level rebinding inside
those production documents (original document IDs or transaction create_ref
aliases). Other immutable document pins remain exact historical references.
``reviewed_sha256`` must come from the service's bound, explicitly confirmed
review, not from a client assertion of consent. It hashes the entire review.

``authorize_reference(kind, pin)`` must return True for each preserved immutable
asset/document pin, using authoritative project/retention ownership facts. It
must be side-effect free. No implicit grants or fetching arbitrary client IDs.
``id_factory(prefix)`` is SERVER injection only; default UUID4. Replay uses the
real graph engine, then replaces its provisional new IDs too. No monkeypatching
of graph globals, independent database, or invented operation language.

Publication integration: resolve command status first, authorize exact retained
source in the same native project, load source + observed head, verify scoped
review capability and CAS/catalog preconditions, then call this helper. Freeze
its result in the existing command journal and publish graph with comp=None,
never the source comp, through the existing duplicate/create machinery. Recheck
BOTH source/head pins and catalog after any freeze lock release, including the
new-composition path. Return the prepared receipt only as committed after exact
new-version read-back. A retry reuses frozen work, never regenerates identities.
The service remains responsible for compiler/storage capability validation and
native membership, retention, rights policy, provenance and publication atomicity.
Do not run ordinary duplicate remapping or strip rights again on this graph.

Proposed route: POST existing composition path + '/recover-as-new',
OP-RECOVER-AS-NEW, usual command/scope/idempotency envelope; input exactly
{name, review, review_token}; preconditions exact observed source-composition
head/revision plus catalog_revision. Server-bound review_token supplies the
reviewed_sha256 (and principal/native/project/source/head/expiry binding).
Frontend must retain the original journal/body/hash/base unchanged, resolve
unknown old submissions, compare exact retained base and current head, display
original typed operations and explicit rebind/dependency approvals, and issue a
NEW command in a separate recovery journal. Never overwrite/rekey or mark the
old draft applied; switch to the new Composition only after receipt read-back.
"""
from __future__ import annotations

import copy
import re
import uuid

from .contracts import ContractError, validate
from .ui_graph import apply_operations, public_hash, schema_catalog, validate_graph

_FAMILIES = (
    ('tracks', 'track_id', 'trk'), ('clips', 'clip_id', 'clp'),
    ('scenes', 'scene_id', 'scn'), ('layers', 'layer_id', 'lyr'),
    ('effects', 'effect_id', 'eff'), ('audio_buses', 'bus_id', 'bus'),
    ('captions', 'cue_id', 'cue'), ('production_documents', 'document_id', 'doc'),
)
_DOCUMENT_PIN = {'kind', 'document_id', 'document_version_id', 'sha256'}
_ASSET_PIN = {'asset_id', 'asset_version_id', 'sha256'}


def _fail(code, message):
    raise ContractError(code, message)


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        _fail('INVALID_ARGUMENT', 'Recovery object has missing or unknown fields.')


def _hash(value):
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        _fail('INVALID_ARGUMENT', 'Recovery requires an exact public SHA-256.')


def _pin(value):
    _keys(value, ('composition_id', 'version_id', 'composition_revision', 'sha256'))
    for key in ('composition_id', 'version_id'):
        if type(value[key]) is not str or not 1 <= len(value[key]) <= 160:
            _fail('INVALID_ARGUMENT', 'Invalid recovery source identity.')
    if type(value['composition_revision']) is not int or value['composition_revision'] < 1:
        _fail('INVALID_ARGUMENT', 'Invalid recovery source revision.')
    _hash(value['sha256'])


def _strings(value):
    """For collision avoidance only, NEVER for remapping text/payloads."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _strings(child)


def _walk(value, schema, pin_visitor):
    """Visit references only at schema-declared pin positions, not arbitrary JSON."""
    if value is None:
        return None
    for choice in ('oneOf', 'anyOf'):
        if choice in schema:
            for variant in schema[choice]:
                try:
                    validate(value, variant)
                except ContractError:
                    continue
                return _walk(value, variant, pin_visitor)
            _fail('INVALID_GRAPH', 'Production value has no supported schema variant.')
    properties = schema.get('properties', {})
    if type(value) is dict:
        if set(properties) == _DOCUMENT_PIN:
            return pin_visitor('document', value)
        if set(properties) == _ASSET_PIN:
            return pin_visitor('asset', value)
        return {key: _walk(child, properties[key], pin_visitor) if key in properties
                else copy.deepcopy(child) for key, child in value.items()}
    if type(value) is list and 'items' in schema:
        return [_walk(child, schema['items'], pin_visitor) for child in value]
    return copy.deepcopy(value)


def prepare_recovery(base_graph, *, source, current_head, review, reviewed_sha256,
                     authorize_reference, id_factory=None):
    """Return validated graph/remap/receipt, or raise without modifying inputs.

    Lock, linked closure, typed shape, operation order, expected document hashes,
    dependent-deletion closure and full post-state semantics are ui_graph's own
    contracts, not relaxed recovery variants. No publication success is claimed.
    """
    _keys(review, ('source', 'current_head', 'base_graph_sha256',
                   'schema_catalog_sha256', 'transaction'))
    for value in (source, current_head, review['source'], review['current_head']):
        _pin(value)
    for value in (reviewed_sha256, review['base_graph_sha256'], review['schema_catalog_sha256']):
        _hash(value)
    if public_hash(review) != reviewed_sha256:
        _fail('RECOVERY_REVIEW_CHANGED', 'Recovery differs from the explicitly reviewed transaction.')
    if (source != review['source'] or current_head != review['current_head'] or
            source['composition_id'] != current_head['composition_id']):
        _fail('SOURCE_CHANGED', 'Retained source or reviewed current head changed; review again.')
    validate_graph(base_graph)
    if public_hash(base_graph) != review['base_graph_sha256']:
        _fail('SOURCE_CHANGED', 'Recovery graph is not the exact reviewed retained base.')
    catalog = schema_catalog()
    if public_hash(catalog) != review['schema_catalog_sha256']:
        _fail('SCHEMA_CHANGED', 'Typed schema catalog changed; review again.')
    tx = review['transaction']
    _keys(tx, ('operations', 'dependency_policy', 'acknowledged_dependency_ids', 'document_rebind_ids'))
    if tx['dependency_policy'] != 'reject_unlisted':
        _fail('INVALID_ARGUMENT', 'Recovery requires reject_unlisted dependencies.')
    rebind_ids = tx['document_rebind_ids']
    if (type(rebind_ids) is not list or len(rebind_ids) > 1000 or
            any(type(item) is not str or not 1 <= len(item) <= 160 for item in rebind_ids) or
            len(set(rebind_ids)) != len(rebind_ids)):
        _fail('INVALID_ARGUMENT', 'Document rebinding approval must be a finite unique ID list.')
    if not callable(authorize_reference) or (id_factory is not None and not callable(id_factory)):
        _fail('INVALID_ARGUMENT', 'Recovery requires server-owned reference authorization and identity generation.')

    # Replaying on the exact retained source (not the observed current head) is
    # critical. apply_operations deep-copies and validates before returning.
    replay = apply_operations(copy.deepcopy(base_graph), copy.deepcopy(tx['operations']),
                              copy.deepcopy(tx['acknowledged_dependency_ids']))
    graph = replay['graph']
    docs = {doc['document_id']: doc for doc in graph['production_documents']}
    authorized = {replay['created_ids'].get(identity, identity) for identity in rebind_ids}
    if not authorized <= set(docs):
        _fail('ENTITY_NOT_FOUND', 'Document rebind approval is outside the recovered document set.')

    forbidden = set(_strings(base_graph)) | set(_strings(review)) | set(_strings(graph))
    mapping = {}
    factory = id_factory or (lambda prefix: prefix + '_' + str(uuid.uuid4()))

    def fresh(identity, prefix):
        if identity in mapping:
            return mapping[identity]
        generated = factory(prefix)
        if (type(generated) is not str or
                re.fullmatch(re.escape(prefix) + r'_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', generated) is None or
                generated in forbidden):
            _fail('RECOVERY_ID_INVALID', 'Server generator returned a malformed or colliding identity.')
        forbidden.add(generated)
        mapping[identity] = generated
        return generated

    # Include deleted source entities in the mapping for the intent receipt;
    # only surviving entities occur in the recovered graph.
    for snapshot in (base_graph, graph):
        for family, identity_key, prefix in _FAMILIES:
            for row in snapshot[family]:
                fresh(row[identity_key], prefix)
                if family == 'production_documents':
                    fresh(row['document_version_id'], 'dvr')
        for clip in snapshot['clips']:
            if clip['linked_group_id'] is not None:
                fresh(clip['linked_group_id'], 'lnk')
    for alias, identity in replay['created_ids'].items():
        if identity not in mapping:
            # A transaction can create and subsequently delete an entity.
            fresh(identity, identity.split('_', 1)[0])

    preserved = {'asset': {}, 'document': {}}
    rebound = []

    def external(kind, pin):
        pin = copy.deepcopy(pin)
        key = public_hash(pin)
        if key not in preserved[kind]:
            if authorize_reference(kind, copy.deepcopy(pin)) is not True:
                _fail('RECOVERY_REFERENCE_UNAUTHORIZED', 'Recovery contains an unauthorized immutable reference.')
            preserved[kind][key] = pin
        return pin

    for asset in graph['asset_refs']:
        external('asset', {key: asset[key] for key in _ASSET_PIN})

    completed, active = {}, set()

    def document(identity):
        if identity in completed:
            return completed[identity]
        if identity in active:
            _fail('INVALID_GRAPH', 'Authorized production-document rebinding contains a cycle.')
        active.add(identity)
        old = docs[identity]
        result = copy.deepcopy(old)
        result['document_id'] = mapping[identity]
        result['document_version_id'] = mapping[old['document_version_id']]

        def pin_visitor(kind, pin):
            if kind == 'document' and pin['document_id'] in docs:
                target = docs[pin['document_id']]
                exact = all(pin[key] == target[key] for key in _DOCUMENT_PIN)
                if pin['document_version_id'] == target['document_version_id'] and not exact:
                    _fail('STALE_DEPENDENCY', 'Production pin does not match its immutable local version.')
                if exact and identity in authorized:
                    new_target = document(pin['document_id'])
                    replacement = {key: new_target[key] for key in _DOCUMENT_PIN}
                    rebound.append({'document_id': identity, 'before': copy.deepcopy(pin),
                                    'after': copy.deepcopy(replacement)})
                    return replacement
            # Historical and external pins are preserved verbatim and require
            # authoritative retention/ownership approval, even for local IDs.
            return external(kind, pin)

        result['value'] = _walk(old['value'], catalog[old['kind']]['schema'], pin_visitor)
        if old['kind'] == 'creative_plan':
            for beat in result['value']['beats']:
                if beat['scene_id'] is not None:
                    if identity not in authorized:
                        _fail('RECOVERY_REBIND_REQUIRED', 'Creative scene references require explicit document rebinding approval.')
                    old_scene = beat['scene_id']
                    beat['scene_id'] = mapping[old_scene]
                    rebound.append({'document_id': identity, 'before': {'scene_id': old_scene},
                                    'after': {'scene_id': beat['scene_id']}})
        if old['kind'] == 'storyboard':
            library = next(doc for doc in docs.values() if doc['kind'] == 'asset_library')
            new_hash = document(library['document_id'])['sha256']
            if result['value']['asset_library_sha256'] != new_hash:
                if identity not in authorized:
                    _fail('RECOVERY_REBIND_REQUIRED', 'Storyboard library hash rebinding requires approval.')
                result['value']['asset_library_sha256'] = new_hash
        result['sha256'] = public_hash(result['value'])
        active.remove(identity)
        completed[identity] = result
        return result

    new_documents = [document(row['document_id']) for row in graph['production_documents']]
    for family, identity_key, _ in _FAMILIES:
        if family == 'production_documents':
            continue
        for row in graph[family]:
            row[identity_key] = mapping[row[identity_key]]
    for track in graph['tracks']:
        track['clip_ids'] = [mapping[identity] for identity in track['clip_ids']]
    for scene in graph['scenes']:
        scene['layer_ids'] = [mapping[identity] for identity in scene['layer_ids']]
    for layer in graph['layers']:
        layer['scene_id'] = mapping[layer['scene_id']]
    for clip in graph['clips']:
        clip['track_id'] = mapping[clip['track_id']]
        if clip['subject']['kind'] in ('scene', 'caption'):
            clip['subject']['id'] = mapping[clip['subject']['id']]
        if clip['linked_group_id'] is not None:
            clip['linked_group_id'] = mapping[clip['linked_group_id']]
        clip['effect_ids'] = [mapping[identity] for identity in clip['effect_ids']]
    for cue in graph['captions']:
        cue['track_id'] = mapping[cue['track_id']]
    for bus in graph['audio_buses']:
        bus['routing_ids'] = [mapping[identity] for identity in bus['routing_ids']]
    # ui_graph currently rejects all effects; fail closed if its contract grows
    # before recovery's finite remapping contract is extended.
    if graph['effects']:
        _fail('UNSUPPORTED_OPERATION', 'Recovery effect-reference remapping is unavailable.')
    graph['production_documents'] = sorted(new_documents, key=lambda doc: (doc['kind'], doc['document_id']))
    # UUID remapping can change equal-start projection tie order.
    for track in graph['tracks']:
        track['clip_ids'] = [clip['clip_id'] for clip in sorted(
            (clip for clip in graph['clips'] if clip['track_id'] == track['track_id']),
            key=lambda clip: (clip['start_frame'], clip['clip_id']))]
    for scene in graph['scenes']:
        scene['layer_ids'] = [layer['layer_id'] for layer in sorted(
            (layer for layer in graph['layers'] if layer['scene_id'] == scene['scene_id']),
            key=lambda layer: (layer['order'], layer['layer_id']))]
    validate_graph(graph)
    return {'graph': graph, 'id_remap': mapping,
            'created_ids': {alias: mapping[identity] for alias, identity in replay['created_ids'].items()},
            'recovery_receipt': {'state': 'prepared', 'kind': 'recovery_as_new.v1',
                                 'source': copy.deepcopy(source), 'observed_head': copy.deepcopy(current_head),
                                 'review_sha256': reviewed_sha256,
                                 'transaction_sha256': public_hash(tx),
                                 'base_graph_sha256': review['base_graph_sha256'],
                                 'schema_catalog_sha256': review['schema_catalog_sha256'],
                                 'proposed_graph_sha256': public_hash(graph),
                                 'original_affected_entities': copy.deepcopy(replay['affected_entities']),
                                 'document_rebindings': rebound,
                                 'preserved_refs': {kind: list(pins.values()) for kind, pins in preserved.items()}}}
