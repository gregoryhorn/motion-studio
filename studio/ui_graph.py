"""Pure Composition v1 editing and the deliberately bounded B03 compiler.

No filesystem, probes, jobs, rendering, permission grants or store revisions are
performed here. IDs are opaque UUIDs. ``created_ids`` maps transaction-local UUID
aliases to durable IDs; aliases are never substituted in text/parameter values.

The service owns asset hydration: asset_refs entries pin asset_id,
asset_version_id, sha256, kind, artifact (the owned backend ArtifactRef), and
stream facts (rate/duration_frames, or time_base/start_pts/duration_ticks).
Optional audio facts include sample_rate; no sample-conform receipt is invented.
Unknown facts block source edits rather than becoming guessed durations. Public
production values derive from the existing closed definitions with public
asset/document version pins and bare lowercase hashes. schema_catalog() publishes
exact expanded schema bytes; private ArtifactRefs exist only in hydrated graphs
and compiled documents, never the facade's public CompositionVersion projection.

The legacy B03 document compiler cannot represent rich layers, background paint,
manual captions or mixed picture tracks. The explicit canonical_graph_render_v1
compiler target retains the full graph and validates the real owned compositor
contract instead. Its public schema pins are exposed unchanged; typed image,
media, shape and text layers and their keyframes are validated on edit, never
flattened into Layout metadata. Effects/groups/buses/retime remain unsupported.
Legacy compiler output is still the same exact five-field value-document set;
canonical output is an immutable graph/schema closure, not invented B03 records.
A store integration must persist the selected target without dropping intent.
"""
from __future__ import annotations

import copy
import re
import uuid
from fractions import Fraction
from math import gcd
from typing import NoReturn

from .contracts import (BOOL, D, DIGEST, KEY, LABEL, MAX_INT, STAGES, TEXT,
                        UUID_PATTERN, ContractError, arr, canonical,
                        default_gate_policy, digest, domain, empty_brief, enum,
                        integer, nullable, obj, string, validate)
from .timeline import validate_timeline

_FORMAT = obj({'fps': D['Rate'], 'width': integer(1), 'height': integer(1),
               'sample_rate': integer(1), 'channels': integer(1),
               'duration_frames': integer()})
_PUBLIC_DIGEST = string(r'[0-9a-f]{64}')
_SCHEMA_REF = obj({'id': LABEL, 'version': integer(1), 'sha256': _PUBLIC_DIGEST})


def public_hash(value):
    """Facade hashes use JCS bytes but not the engine's sha256: prefix."""
    return digest(value).removeprefix('sha256:')


def _public_schema(schema):
    """Expand only the requested schema; never publish private engine $defs."""
    if isinstance(schema, list):
        return [_public_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if '$ref' in schema:
        name = schema['$ref'].rsplit('/', 1)[-1]
        if name == 'ArtifactRef':
            return obj({'asset_id': string(minimum=1, maximum=160),
                        'asset_version_id': string(minimum=1, maximum=160),
                        'sha256': _PUBLIC_DIGEST})
        if name == 'DocumentRef':
            return obj({'kind': D['DocumentRef']['properties']['kind'],
                        'document_id': string(minimum=1, maximum=160),
                        'document_version_id': string(minimum=1, maximum=160),
                        'sha256': _PUBLIC_DIGEST})
        return _public_schema(D[name])
    if schema == DIGEST:
        return copy.deepcopy(_PUBLIC_DIGEST)
    return {key: _public_schema(value) for key, value in schema.items()}
_ID = string(minimum=1, maximum=160)
_ALIAS = string(UUID_PATTERN)
_KINDS = ('track', 'clip', 'scene', 'layer', 'effect', 'bus', 'cue', 'document')
_COLLECTIONS = dict(zip(_KINDS, ('tracks', 'clips', 'scenes', 'layers', 'effects',
                                'audio_buses', 'captions', 'production_documents')))
_ID_FIELDS = {k: k + '_id' for k in _KINDS}
_ID_FIELDS.update(cue='cue_id', document='document_id')
_PREFIX = {'track': 'trk', 'clip': 'clp', 'scene': 'scn', 'layer': 'lyr',
           'effect': 'eff', 'bus': 'bus', 'cue': 'cue', 'document': 'doc'}
_DOC_NAMES = {'brief': 'Brief', 'brand': 'Brand', 'asset_library': 'AssetLibrary',
              'storyboard': 'Storyboard', 'creative_plan': 'CreativePlan',
              'editorial': 'Editorial', 'bindings': 'Bindings',
              'execution_policy': 'ExecutionPolicy', 'gate_policy': 'GatePolicy',
              'delivery_profile': 'DeliveryProfile', 'variants': None,
              'voice_preferences': 'VoicePreferences', 'stage': None}
_DOC_SCHEMAS = {k: D[v] for k, v in _DOC_NAMES.items() if v}
_DOC_SCHEMAS.update(variants=arr(D['Variant']), stage=enum(*STAGES))
_DOC_SCHEMAS['voice_preferences'] = nullable(D['VoicePreferences'])
_DOC_SCHEMAS = {kind: _public_schema(schema) for kind, schema in _DOC_SCHEMAS.items()}
_LAYOUT_SCHEMA = obj({'type': enum('image'), 'parameters': _public_schema(D['Layout']),
                      'keyframes': {'type': 'array', 'items': obj({}), 'maxItems': 0}})


def _schema_document(schema):
    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            return expand(D[value['$ref'].rsplit('/', 1)[-1]])
        return {key: expand(item) for key, item in value.items()}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            **expand(schema)}


def _pin(name, schema):
    return {'id': name, 'version': 1, 'sha256': public_hash(_schema_document(schema))}


def schema_catalog():
    """Return exact public schemas, including the owned compositor's pins.

    Compositor pins hash its raw closed schema bytes, NOT the B03 expanded
    schema-document wrapper. Never rehash or rewrite these public identifiers.
    """
    from .adapters.ui_compositor import schema_catalog as compositor_catalog
    return {**{k: {'schema_ref': _pin('motion.ui.document.' + k, s),
                  'schema': _schema_document(s)} for k, s in _DOC_SCHEMAS.items()},
            'layer.layout': {'schema_ref': _pin('motion.ui.layer.layout', _LAYOUT_SCHEMA),
                             'schema': _schema_document(_LAYOUT_SCHEMA)},
            **compositor_catalog()}


def _fail(code, message, **details) -> NoReturn:
    raise ContractError(code, message, details or {'resource': 'composition', 'reason': message})


def _require(ok, message, code='INVALID_GRAPH', **details):
    if not ok:
        _fail(code, message, **details)


def _json(value, depth=0):
    """Reject floats (including NaN), Python-only values, cycles and huge input."""
    _require(depth < 80, 'JSON nesting limit exceeded.', 'LIMIT_EXCEEDED')
    if value is None or type(value) in (str, bool):
        if type(value) is str:
            _require(len(value) <= 1048576, 'String limit exceeded.', 'LIMIT_EXCEEDED')
            try:
                value.encode('utf-8')
            except UnicodeEncodeError:
                _fail('INVALID_ARGUMENT', 'Unpaired Unicode surrogate.')
        return
    if type(value) is int:
        _require(abs(value) <= MAX_INT, 'Integer exceeds exact JSON range.', 'INVALID_ARGUMENT')
        return
    if type(value) is list:
        _require(len(value) <= 10000, 'Array limit exceeded.', 'LIMIT_EXCEEDED')
        for v in value:
            _json(v, depth + 1)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        _require(len(value) <= 10000, 'Object limit exceeded.', 'LIMIT_EXCEEDED')
        for k, v in value.items():
            _json(k, depth + 1)
            _json(v, depth + 1)
        return
    _fail('INVALID_ARGUMENT', 'Only finite integer-only JSON values are accepted.')


def _shape(value, fields, optional=()):
    validate(value, obj(fields, optional))


def _rate(value):
    validate(value, D['Rate'])
    _require(gcd(value['num'], value['den']) == 1, 'Rate must be reduced.', 'TIMING_INVALID')
    return Fraction(value['num'], value['den'])


def _format(value):
    validate(value, _FORMAT)
    _rate(value['fps'])


def _new(kind):
    return _PREFIX[kind] + '_' + str(uuid.uuid4())


def init_graph(format):
    """Seed V1, A1, Captions and Overlay, always empty and zero duration."""
    _json(format)
    _format(format)
    _require(format['duration_frames'] == 0, 'A new Composition must have zero duration.', 'TIMING_INVALID')
    graph = {'schema_version': 'composition.v1', 'format': copy.deepcopy(format),
             **{name: [] for name in _COLLECTIONS.values()}, 'asset_refs': [],
             'settings': {'color_profile_ref': None, 'output_profile_refs': [],
                          'font_fallback_policy': 'reject'}}
    for order, (kind, name) in enumerate((('video', 'V1'), ('audio', 'A1'),
                                         ('caption', 'Captions'), ('overlay', 'Overlay'))):
        graph['tracks'].append({'track_id': _new('track'), 'kind': kind,
                                'name': name, 'order': order, 'locked': False,
                                'visible': True, 'muted': False,
                                'overlap_policy': 'exclusive', 'clip_ids': []})
    return graph


def _index(graph):
    return {kind: {row[_ID_FIELDS[kind]]: row for row in graph[name]}
            for kind, name in _COLLECTIONS.items()}


def _get(graph, kind, id_):
    _require(kind in _COLLECTIONS, 'Unknown entity kind.', 'INVALID_ARGUMENT', kind=kind)
    found = _index(graph)[kind].get(id_)
    if found is None:
        _fail('ENTITY_NOT_FOUND', 'Referenced entity does not exist.', kind=kind, id=id_)
    return found


def _track(graph, clip):
    return _get(graph, 'track', clip['track_id'])


def _unlocked(graph, kind, id_):
    row = _get(graph, kind, id_)
    tracks = []
    if kind == 'track':
        tracks = [row]
    elif kind in ('clip', 'cue'):
        tracks = [_get(graph, 'track', row['track_id'])]
    elif kind in ('scene', 'layer'):
        sid = id_ if kind == 'scene' else row['scene_id']
        tracks = [_track(graph, c) for c in graph['clips']
                  if c['subject']['kind'] == 'scene' and c['subject']['id'] == sid]
    elif kind == 'effect':
        _unlocked(graph, row['target']['kind'], row['target']['id'])
    _require(not any(t['locked'] for t in tracks), 'Edit touches a locked track.', 'TRACK_LOCKED', id=id_)


def _linked(graph, ids):
    ids = set(ids)
    groups = {c['linked_group_id'] for c in graph['clips']
              if c['clip_id'] in ids and c['linked_group_id'] is not None}
    return ids | {c['clip_id'] for c in graph['clips'] if c['linked_group_id'] in groups}


def _closure_links(graph, ids):
    _require(set(ids) == _linked(graph, ids), 'All linked companions must be explicit.',
             'LINKED_CLOSURE_REQUIRED', required_ids=sorted(_linked(graph, ids)))


def _sync(graph):
    """Refresh only derived projections, never validate away an invalid edit."""
    for t in graph['tracks']:
        t['clip_ids'] = [c['clip_id'] for c in sorted(graph['clips'],
                          key=lambda c: (c['start_frame'], c['clip_id'])) if c['track_id'] == t['track_id']]
    for s in graph['scenes']:
        s['layer_ids'] = [l['layer_id'] for l in sorted(graph['layers'],
                          key=lambda l: (l['order'], l['layer_id'])) if l['scene_id'] == s['scene_id']]
    graph['format']['duration_frames'] = max([0] + [c['end_frame'] for c in graph['clips']] +
                                            [c['end_frame'] for c in graph['captions']])


def _range(row, limit=None):
    validate(row['start_frame'], integer())
    validate(row['end_frame'], integer(1))
    _require(row['start_frame'] < row['end_frame'] and
             (limit is None or row['end_frame'] <= limit),
             'Invalid nonempty half-open frame interval.', 'TIMING_INVALID')


def _source(graph, clip):
    mapping = clip['source_mapping']
    subject = clip['subject']
    fps = _rate(graph['format']['fps'])
    _shape(subject, {'kind': enum('asset', 'scene', 'caption'), 'id': _ID,
                     'version_id': nullable(_ID)})
    if mapping.get('domain') == 'frame':
        _shape(mapping, {'domain': enum('frame'), 'in_index': integer(), 'out_index': integer(1),
                         'rate': D['Rate'], 'speed': D['Rate']})
        rate, speed = _rate(mapping['rate']), _rate(mapping['speed'])
        _require(mapping['out_index'] > mapping['in_index'], 'Empty source interval.', 'TIMING_INVALID')
        seconds = Fraction(mapping['out_index'] - mapping['in_index']) / rate / speed
    elif mapping.get('domain') == 'source_tick':
        _shape(mapping, {'domain': enum('source_tick'), 'in_pts': integer(-MAX_INT),
                         'out_pts': integer(-MAX_INT), 'time_base': D['Rate'],
                         'start_pts': integer(-MAX_INT), 'conform_ref': nullable(_SCHEMA_REF)})
        _require(mapping['out_pts'] > mapping['in_pts'], 'Empty source PTS interval.', 'TIMING_INVALID')
        _require(mapping['conform_ref'] is None, 'Conform recipes require an executed backend binding.', 'UNSUPPORTED_OPERATION')
        seconds = (mapping['out_pts'] - mapping['in_pts']) * _rate(mapping['time_base'])
    else:
        _fail('UNSUPPORTED_OPERATION', 'Unsupported source mapping domain.')
    _require(seconds == Fraction(clip['end_frame'] - clip['start_frame']) / fps,
             'Exact source/output duration mismatch.', 'TIMING_INVALID', clip_id=clip['clip_id'])
    if subject['kind'] == 'scene':
        scene = _get(graph, 'scene', subject['id'])
        _require(subject['version_id'] is None, 'Scene references are version-local.')
        _require(mapping['domain'] == 'frame' and mapping['rate'] == graph['format']['fps'] and
                 mapping['out_index'] <= scene['duration_frames'], 'Scene source exceeds its bounds.', 'TIMING_INVALID')
        _require(_track(graph, clip)['kind'] in ('video', 'overlay'), 'Scene needs a picture track.')
    elif subject['kind'] == 'caption':
        _fail('UNSUPPORTED_OPERATION', 'Use caption.upsert for manual cues; pinned ASR placement needs a caption-document adapter.')
    else:
        candidates = [a for a in graph['asset_refs'] if a['asset_id'] == subject['id'] and
                      a['asset_version_id'] == subject['version_id']]
        _require(len(candidates) == 1, 'Asset version is not pinned in this graph.', 'ASSET_UNRESOLVED')
        asset = candidates[0]
        tk = _track(graph, clip)['kind']
        _require((tk == 'audio' and asset['kind'] == 'audio') or
                 (tk in ('video', 'overlay') and asset['kind'] in ('video', 'image')),
                 'Asset kind incompatible with target track.', 'INVALID_GRAPH')
        if mapping['domain'] == 'frame':
            _require('duration_frames' in asset and 'rate' in asset,
                     'Known source frame bounds and rate are required.', 'SOURCE_BOUNDS_UNKNOWN')
            _require(mapping['out_index'] <= asset['duration_frames'] and mapping['rate'] == asset['rate'],
                     'Mapping exceeds pinned frame facts.', 'TIMING_INVALID')
        else:
            _require(all(k in asset for k in ('start_pts', 'duration_ticks', 'time_base')),
                     'Known source PTS bounds are required.', 'SOURCE_BOUNDS_UNKNOWN')
            _require(mapping['start_pts'] == asset['start_pts'] and mapping['time_base'] == asset['time_base'] and
                     asset['start_pts'] <= mapping['in_pts'] < mapping['out_pts'] <= asset['start_pts'] + asset['duration_ticks'],
                     'Mapping exceeds pinned PTS facts.', 'TIMING_INVALID')
        if tk == 'audio':
            _require(asset.get('sample_rate') == graph['format']['sample_rate'],
                     'Audio requires matching observed sample rate; prepare conform externally.', 'UNSUPPORTED_OPERATION')


def _validate_layer(layer):
    if layer['schema_ref'] == _pin('motion.ui.layer.layout', _LAYOUT_SCHEMA):
        _require(layer['type'] == 'image' and not layer['keyframes'],
                 'Only static B03 layout metadata is supported.', 'UNSUPPORTED_OPERATION')
        validate(layer['parameters'], _public_schema(D['Layout']))
        domain(layer['parameters'])
        return
    from .adapters.ui_compositor import LAYER_SCHEMAS, TRANSFORM, EASINGS
    catalog = schema_catalog()
    kind = layer['type']
    _require(kind in LAYER_SCHEMAS and
             layer['schema_ref'] == catalog['layer.' + kind]['schema_ref'],
             'Layer schema has no supported backend binding.', 'UNSUPPORTED_OPERATION')
    validate(layer['parameters'], LAYER_SCHEMAS[kind])
    seen = set()
    for key in layer['keyframes']:
        _shape(key, {'property': enum('x', 'y', 'width', 'height', 'rotation_mdeg', 'opacity_milli'),
                     'frame': integer(), 'value': integer(-MAX_INT), 'easing_ref': _SCHEMA_REF})
        validate(key['value'], TRANSFORM['properties'][key['property']])
        _require(key['easing_ref'] in [catalog['easing.' + name]['schema_ref'] for name in EASINGS],
                 'Unknown easing schema.', 'UNSUPPORTED_OPERATION')
        pair = key['property'], key['frame']
        _require(pair not in seen, 'Duplicate animated property/frame.')
        seen.add(pair)


def _validate_document(doc):
    kind = doc['kind']
    _require(kind in _DOC_SCHEMAS, 'Unknown production document family.', 'UNSUPPORTED_OPERATION')
    _require(doc['schema_ref'] == _pin('motion.ui.document.' + kind, _DOC_SCHEMAS[kind]),
             'Document schema pin does not match the supported catalog.', 'UNSUPPORTED_OPERATION')
    validate(doc['value'], _DOC_SCHEMAS[kind])
    domain(doc['value'])
    _require(doc['sha256'] == public_hash(doc['value']), 'Document content hash mismatch.')


def validate_graph(graph):
    """Validate canonical records, projections, references and exact timing.

    Does not change the graph and does not assert renderability. compile_graph
    applies the additional explicit restrictions of the existing backend.
    """
    _json(graph)
    _shape(graph, {'schema_version': enum('composition.v1'), 'format': _FORMAT,
                   **{name: arr({'type': 'object', 'additionalProperties': {}})
                      for name in _COLLECTIONS.values()},
                   'asset_refs': arr({'type': 'object', 'additionalProperties': {}}),
                   'settings': obj({'color_profile_ref': nullable(_SCHEMA_REF),
                                    'output_profile_refs': arr(_SCHEMA_REF),
                                    'font_fallback_policy': enum('reject', 'explicit')})})
    _format(graph['format'])
    seen = set()
    for kind, collection in _COLLECTIONS.items():
        for row in graph[collection]:
            validate(row, _RECORD_SCHEMAS[kind])
            id_ = row.get(_ID_FIELDS[kind])
            _require(type(id_) is str and re.fullmatch(_PREFIX[kind] + '_' + UUID_PATTERN, id_) is not None,
                     'Entity ID must be a server UUID with its opaque prefix.', id=id_)
            _require(id_ not in seen, 'Duplicate entity ID.', id=id_)
            seen.add(id_)
    index = _index(graph)
    asset_ids = set()
    for a in graph['asset_refs']:
        _shape(a, {'asset_id': _ID, 'asset_version_id': _ID, 'sha256': _PUBLIC_DIGEST,
                   'kind': enum('video', 'audio', 'image', 'media', 'frame', 'font',
                                'scene_source', 'assembly_source', 'caption', 'caption_style',
                                'json', 'report', 'archive'), 'artifact': D['ArtifactRef'],
                   'rate': D['Rate'], 'duration_frames': integer(1),
                   'time_base': D['Rate'], 'start_pts': integer(-MAX_INT),
                   'duration_ticks': integer(1), 'sample_rate': integer(1)},
               ('rate', 'duration_frames', 'time_base', 'start_pts', 'duration_ticks', 'sample_rate'))
        key = (a['asset_id'], a['asset_version_id'])
        _require(key not in asset_ids, 'Duplicate pinned asset version.')
        asset_ids.add(key)
        _require('sha256:' + a['sha256'] == a['artifact']['sha256'], 'Asset/artifact hash mismatch.')
        for k in ('rate', 'time_base'):
            if k in a:
                _rate(a[k])
    _require(sorted(t['order'] for t in graph['tracks']) == list(range(len(graph['tracks']))),
             'Track orders must form a contiguous permutation.')
    for t in graph['tracks']:
        _shape(t, {'track_id': _ID, 'kind': enum('video', 'audio', 'caption', 'overlay'),
                   'name': LABEL, 'order': integer(), 'locked': BOOL, 'visible': BOOL,
                   'muted': BOOL, 'overlap_policy': enum('exclusive', 'composite', 'mix'), 'clip_ids': arr(_ID, unique=True)})
        _require(t['overlap_policy'] == 'exclusive' or
                 (t['overlap_policy'] == 'mix' and t['kind'] == 'audio') or
                 (t['overlap_policy'] == 'composite' and t['kind'] in ('video', 'overlay')),
                 'Overlap policy incompatible with track kind.')
        clips = [c for c in graph['clips'] if c.get('track_id') == t['track_id']]
        expected = [c['clip_id'] for c in sorted(clips, key=lambda c: (c['start_frame'], c['clip_id']))]
        _require(t['clip_ids'] == expected, 'Track clip projection mismatch.')
        intervals = clips + [c for c in graph['captions'] if c.get('track_id') == t['track_id']]
        if t['overlap_policy'] == 'exclusive':
            previous_end = 0
            for c in sorted(intervals, key=lambda c: c['start_frame']):
                _require(c['start_frame'] >= previous_end, 'Exclusive track overlap.', 'TIMING_INVALID', track_id=t['track_id'])
                previous_end = c['end_frame']
    for c in graph['clips']:
        _shape(c, {'clip_id': _ID, 'track_id': _ID,
                   'subject': obj({'kind': enum('asset', 'scene', 'caption'), 'id': _ID, 'version_id': nullable(_ID)}),
                   'start_frame': integer(), 'end_frame': integer(1),
                   'source_mapping': {'type': 'object', 'additionalProperties': {}},
                   'linked_group_id': nullable(_ID), 'enabled': BOOL, 'effect_ids': arr(_ID, unique=True),
                   'audio': {'type': 'object', 'additionalProperties': {}}}, ('audio',))
        _range(c, graph['format']['duration_frames'])
        _get(graph, 'track', c['track_id'])
        _require(c['linked_group_id'] is None or re.fullmatch('lnk_' + UUID_PATTERN, c['linked_group_id']) is not None,
                 'Linked group IDs must be server-created UUIDs.')
        _source(graph, c)
        _require(not c['effect_ids'], 'Backend effect pipeline is unavailable.', 'UNSUPPORTED_OPERATION')
        if 'audio' in c:
            _require(_track(graph, c)['kind'] == 'audio', 'Audio properties require an audio track.')
            _validate_audio(c['audio'], c['end_frame'] - c['start_frame'])
    for s in graph['scenes']:
        _shape(s, {'scene_id': _ID, 'name': LABEL, 'duration_frames': integer(1),
                   'layer_ids': arr(_ID, unique=True), 'background': nullable(arr(integer(0, 255), 4))})
        _require(s['background'] is None or len(s['background']) == 4, 'Background must be RGBA bytes.')
        layers = sorted([l for l in graph['layers'] if l['scene_id'] == s['scene_id']], key=lambda l: (l['order'], l['layer_id']))
        _require(s['layer_ids'] == [l['layer_id'] for l in layers], 'Scene layer projection mismatch.')
        _require(len({l['order'] for l in layers}) == len(layers), 'Duplicate layer order.')
    for l in graph['layers']:
        _shape(l, {'layer_id': _ID, 'scene_id': _ID, 'type': enum('text', 'image', 'shape', 'media', 'group'),
                   'schema_ref': _SCHEMA_REF, 'order': integer(), 'start_frame': integer(), 'end_frame': integer(1),
                   'parameters': {'type': 'object', 'additionalProperties': {}}, 'keyframes': arr({'type': 'object', 'additionalProperties': {}})})
        _range(l, _get(graph, 'scene', l['scene_id'])['duration_frames'])
        _validate_layer(l)
        if l['schema_ref'] == _pin('motion.ui.layer.layout', _LAYOUT_SCHEMA):
            _require(l['parameters']['z'] == l['order'],
                     'Layout z must equal the explicit scene-layer order.')
            _require('asset' in l['parameters'] and any(
                a['kind'] == 'image' and {key:a[key] for key in ('asset_id','asset_version_id','sha256')} == l['parameters']['asset']
                for a in graph['asset_refs']), 'Layout image must pin an owned image asset version.', 'ASSET_UNRESOLVED')
        else:
            _require(l['order'] >= 0, 'Compositor layer order must be nonnegative.')
            for key in l['keyframes']:
                _require(key['frame'] < _get(graph, 'scene', l['scene_id'])['duration_frames'],
                         'Keyframe exceeds scene duration.', 'TIMING_INVALID')
            p = l['parameters']
            if l['type'] in ('image', 'media'):
                kind = 'image' if l['type'] == 'image' else 'video'
                _require(any(a['kind'] == kind and {key:a[key] for key in ('asset_id','asset_version_id','sha256')} == p['asset']
                             for a in graph['asset_refs']), 'Layer must pin an owned asset version.', 'ASSET_UNRESOLVED')
            if l['type'] == 'text':
                _require(sum(a['kind'] == 'font' and a['asset_id'] == p['font_binding_id'] for a in graph['asset_refs']) == 1,
                         'Text must bind one exact owned font face.', 'ASSET_UNRESOLVED')
    _require(not graph['effects'], 'Backend effect pipeline is unavailable.', 'UNSUPPORTED_OPERATION')
    for b in graph['audio_buses']:
        _shape(b, {'bus_id': _ID, 'name': LABEL, 'gain_db_milli': integer(-60000, 12000),
                   'pan_milli': integer(-1000, 1000), 'muted': BOOL, 'routing_ids': arr(_ID, unique=True),
                   'audio': {'type': 'object', 'additionalProperties': {}}}, ('audio',))
        if 'audio' in b:
            _validate_audio(b['audio'], graph['format']['duration_frames'])
        for target in b['routing_ids']:
            _get(graph, 'bus', target)
    visited = set()
    for bus_id in index['bus']:
        active = set()
        stack = [(bus_id, False)]
        while stack:
            current, leaving = stack.pop()
            if leaving:
                active.remove(current)
                visited.add(current)
            elif current not in visited:
                _require(current not in active, 'Audio bus routing cycle.')
                active.add(current)
                stack.append((current, True))
                stack.extend((target, False) for target in index['bus'][current]['routing_ids'])
    for c in graph['captions']:
        _shape(c, {'cue_id': _ID, 'track_id': _ID, 'start_frame': integer(), 'end_frame': integer(1),
                   'text': TEXT, 'language': LABEL, 'style_ref': nullable(_SCHEMA_REF),
                   'source': obj({'kind': enum('manual', 'import', 'asr'), 'asset_id': _ID,
                                  'job_id': _ID, 'confidence_milli': nullable(integer(0, 1000))},
                                 ('asset_id', 'job_id', 'confidence_milli')),
                   'editorial_revision': integer(1)})
        _range(c, graph['format']['duration_frames'])
        _require(_get(graph, 'track', c['track_id'])['kind'] == 'caption', 'Cue requires a caption track.')
        _require(c['style_ref'] is None or c['style_ref'] == schema_catalog()['caption']['schema_ref'],
                 'Caption style has no owned renderer binding.', 'UNSUPPORTED_OPERATION')
    singletons = set()
    for d in graph['production_documents']:
        _shape(d, {'kind': enum(*_DOC_SCHEMAS), 'document_id': _ID, 'document_version_id': _ID,
                   'schema_ref': _SCHEMA_REF, 'sha256': _PUBLIC_DIGEST, 'value': {}})
        _require(re.fullmatch('dvr_' + UUID_PATTERN, d['document_version_id']) is not None, 'Invalid document version ID.')
        _validate_document(d)
        if d['kind'] != 'delivery_profile':
            _require(d['kind'] not in singletons, 'Duplicate singleton production document.')
            singletons.add(d['kind'])
    # The service/store validates pinned external ownership. Local semantic
    # couplings are enforced here against the entire post-transaction graph.
    docs = {d['kind']: d['value'] for d in graph['production_documents'] if d['kind'] != 'delivery_profile'}
    if 'asset_library' in docs:
        library = docs['asset_library']
        requirements = library['requirements']
        _require(len({r['requirement_id'] for r in requirements}) == len(requirements),
                 'Asset requirement IDs must be unique.')
        for requirement in requirements:
            if requirement['status'] == 'ready':
                _require('asset' in requirement and bool(requirement['assessment'].strip()),
                         'Ready asset requires its immutable asset pin and assessment.', 'ASSETS_UNRESOLVED')
            else:
                _require(bool(requirement['acquisition'].strip()),
                         'Missing/planned assets require an acquisition approach.', 'ASSETS_UNRESOLVED')
        if library['assessed']:
            _require(bool(library['notes'].strip()) and all(not r['required'] or r['status'] == 'ready' for r in requirements),
                     'Assessed library requires notes and all required assets ready.', 'ASSETS_UNRESOLVED')
    if 'storyboard' in docs:
        _require('asset_library' in docs and docs['asset_library']['assessed'],
                 'Storyboard requires an assessed local asset library.', 'ASSETS_UNRESOLVED')
        panels = docs['storyboard']['panels']
        _require(len({p['panel_id'] for p in panels}) == len(panels), 'Storyboard panel IDs must be unique.')
        reqs = {r['requirement_id']: r for r in docs['asset_library']['requirements']}
        for panel in panels:
            _require(len(set(panel['asset_requirements'])) == len(panel['asset_requirements']),
                     'Panel requirements must be unique.')
            _require(all(r in reqs and reqs[r]['status'] == 'ready' for r in panel['asset_requirements']) and
                     any(r['status'] == 'ready' and r.get('asset') == panel['visual'] for r in reqs.values()),
                     'Panel visual and requirements need ready asset assessments.', 'ASSETS_UNRESOLVED')
    if 'storyboard' in docs and 'asset_library' in docs:
        _require(docs['storyboard']['asset_library_sha256'] == public_hash(docs['asset_library']),
                 'Storyboard asset-library pin is stale.', 'STALE_DEPENDENCY')
        requirements = {r['requirement_id'] for r in docs['asset_library']['requirements']}
        for panel in docs['storyboard']['panels']:
            _require(set(panel['asset_requirements']) <= requirements, 'Storyboard requirement is unresolved.')
    if 'creative_plan' in docs:
        from .creative import validate_plan
        local_docs = {(kind, 'project'): {'value': value} for kind, value in docs.items()}
        local_docs.update({('scene', scene['scene_id']): {'value': scene} for scene in graph['scenes']})
        validate_plan(docs['creative_plan'], local_docs)
        plan = docs['creative_plan']
        panel_ids = {p['panel_id'] for p in docs.get('storyboard', {}).get('panels', [])}
        for beat in plan['beats']:
            if beat['scene_id'] is not None:
                _get(graph, 'scene', beat['scene_id'])
            if beat['panel_id'] is not None:
                _require(beat['panel_id'] in panel_ids, 'Creative beat panel is unresolved.')
            _require(beat['start_frame'] + beat['duration_frames'] <= plan['duration_frames'], 'Creative beat exceeds plan.')
    bindings = docs.get('bindings')
    if bindings:
        selected = set(bindings['selected_adapter_ids'])
        _require(all(set(values) <= selected for values in bindings['preferences'].values()) and
                 set(bindings['pins'].values()) <= selected,
                 'Bindings reference an unselected adapter.')
    duration = max([0] + [c['end_frame'] for c in graph['clips']] + [c['end_frame'] for c in graph['captions']])
    _require(graph['format']['duration_frames'] == duration, 'Timeline duration must be derived from placements and cues.', 'TIMING_INVALID')


def _validate_audio(value, duration):
    _shape(value, {'gain_db_milli': integer(-60000, 12000), 'pan_milli': integer(-1000, 1000),
                   'muted': BOOL, 'fades': arr(obj({'start_frame': integer(), 'end_frame': integer(1), 'curve_ref': _SCHEMA_REF})),
                   'envelope': arr(obj({'frame': integer(), 'gain_db_milli': integer(-60000, 12000)}))})
    # Public fade records are start/end/curve_ref; the compositor's fade
    # contract is frames/direction. Do not translate one into the other by guess.
    _require(not value['fades'],
             'Public fade intervals have no exact owned compositor representation.', 'UNSUPPORTED_OPERATION')
    frames = [point['frame'] for point in value['envelope']]
    _require(frames == sorted(set(frames)) and all(frame < duration for frame in frames),
             'Envelope frames must be unique, sorted and inside their clip.', 'TIMING_INVALID')


_TARGET = obj({'kind': enum(*_KINDS), 'id': _ID})
_MAPPING = {'type': 'object', 'additionalProperties': {}}
_OPS = {
    'track.create': {'create_ref': _ALIAS, 'kind': enum('video', 'audio', 'caption', 'overlay'), 'name': LABEL, 'order': integer(), 'overlap_policy': enum('exclusive', 'composite', 'mix')},
    'track.update': {'track_id': _ID, 'name': LABEL, 'order': integer(), 'locked': BOOL, 'visible': BOOL, 'muted': BOOL},
    'clip.insert': {'create_ref': _ALIAS, 'track_id': _ID, 'subject': obj({'kind': enum('asset', 'scene', 'caption'), 'id': _ID, 'version_id': nullable(_ID)}), 'start_frame': integer(), 'end_frame': integer(1), 'source_mapping': _MAPPING, 'linked_group_id': nullable(_ID), 'enabled': BOOL},
    'clip.enable': {'clip_id': _ID, 'enabled': BOOL},
    'clip.move': {'placements': arr(obj({'clip_id': _ID, 'target_track_id': _ID, 'start_frame': integer()}), 1), 'link_policy': enum('preserve')},
    'clip.trim': {'clip_id': _ID, 'start_frame': integer(), 'end_frame': integer(1), 'source_mapping': _MAPPING, 'link_policy': enum('preserve')},
    'clip.split': {'clip_id': _ID, 'at_frame': integer(), 'right_create_ref': _ALIAS, 'link_policy': enum('preserve')},
    'timeline.ripple': {'track_ids': arr(_ID, 1, True), 'range': obj({'start_frame': integer(), 'end_frame': integer()}), 'action': enum('delete', 'insert_gap', 'close_gap'), 'delta_frames': integer(-MAX_INT), 'link_policy': enum('preserve'), 'expected_affected_ids': arr(_ID, unique=True)},
    'entity.delete': {'targets': arr(_TARGET, 1), 'expected_dependency_ids': arr(_ID, unique=True)},
    'scene.create': {'create_ref': _ALIAS, 'name': LABEL, 'duration_frames': integer(1), 'background': nullable(arr(integer(0, 255), 4))},
    'scene.update': {'scene_id': _ID, 'name': LABEL, 'duration_frames': integer(1), 'background': nullable(arr(integer(0, 255), 4))},
    'layer.create': {'create_ref': _ALIAS, 'scene_id': _ID, 'type': enum('text', 'image', 'shape', 'media', 'group'), 'schema_ref': _SCHEMA_REF, 'order': integer(), 'start_frame': integer(), 'end_frame': integer(1), 'parameters': _MAPPING, 'keyframes': arr(_MAPPING)},
    'layer.update': {'layer_id': _ID, 'schema_ref': _SCHEMA_REF, 'parameters': _MAPPING, 'keyframes': arr(_MAPPING), 'start_frame': integer(), 'end_frame': integer(1), 'order': integer()},
    'effect.create': {'create_ref': _ALIAS, 'target': _TARGET, 'schema_ref': _SCHEMA_REF, 'enabled': BOOL, 'parameters': _MAPPING, 'keyframes': arr(_MAPPING)},
    'effect.update': {'effect_id': _ID, 'schema_ref': _SCHEMA_REF, 'enabled': BOOL, 'parameters': _MAPPING, 'keyframes': arr(_MAPPING)},
    'audio.set': {'target': obj({'kind': enum('clip', 'bus'), 'id': _ID}), 'gain_db_milli': integer(-60000, 12000), 'pan_milli': integer(-1000, 1000), 'muted': BOOL, 'fades': arr(obj({'start_frame': integer(), 'end_frame': integer(1), 'curve_ref': _SCHEMA_REF})), 'envelope': arr(obj({'frame': integer(), 'gain_db_milli': integer(-60000, 12000)}))},
    'caption.upsert': {'cue_id': nullable(_ID), 'create_ref': nullable(_ALIAS), 'track_id': _ID, 'start_frame': integer(), 'end_frame': integer(1), 'text': TEXT, 'language': LABEL, 'style_ref': nullable(_SCHEMA_REF)},
    'settings.set': {'format': _FORMAT, 'retime_policy': enum('preserve_frames', 'preserve_time_nearest_even'), 'color_profile_ref': nullable(_SCHEMA_REF), 'output_profile_refs': arr(_SCHEMA_REF), 'font_fallback_policy': enum('reject', 'explicit')},
    'link.set': {'clip_ids': arr(_ID, 1, True), 'group_id': nullable(_ID)},
    'document.put': {'kind': enum(*_DOC_SCHEMAS), 'document_id': nullable(_ID), 'create_ref': nullable(_ALIAS), 'schema_ref': _SCHEMA_REF, 'value': {}, 'expected_document_sha256': nullable(_PUBLIC_DIGEST)},
    'document.remove': {'document_id': _ID, 'expected_document_sha256': _PUBLIC_DIGEST, 'expected_dependency_ids': arr(_ID, unique=True)},
}


# Structural validation precedes cross-record lookups, so malformed stored
# records fail with ContractError rather than incidental KeyError/TypeError.
def _record_fields(operation, remove, extra):
    return {k: copy.deepcopy(v) for k, v in _OPS[operation].items() if k not in remove} | extra


_RECORD_SCHEMAS = {
    'track': obj(_record_fields('track.create', ('create_ref',),
        {'track_id': _ID, 'locked': BOOL, 'visible': BOOL, 'muted': BOOL, 'clip_ids': arr(_ID, unique=True)})),
    'clip': obj(_record_fields('clip.insert', ('create_ref',),
        {'clip_id': _ID, 'effect_ids': arr(_ID, unique=True), 'audio': _MAPPING}), ('audio',)),
    'scene': obj(_record_fields('scene.create', ('create_ref',), {'scene_id': _ID, 'layer_ids': arr(_ID, unique=True)})),
    'layer': obj(_record_fields('layer.create', ('create_ref',), {'layer_id': _ID})),
    'effect': obj(_record_fields('effect.create', ('create_ref',), {'effect_id': _ID})),
    'bus': obj({'bus_id': _ID, 'name': LABEL, 'gain_db_milli': integer(-60000, 12000),
                'pan_milli': integer(-1000, 1000), 'muted': BOOL, 'routing_ids': arr(_ID, unique=True), 'audio': _MAPPING}, ('audio',)),
    'cue': obj(_record_fields('caption.upsert', ('create_ref',),
        {'cue_id': _ID, 'editorial_revision': integer(1),
         'source': obj({'kind': enum('manual', 'import', 'asr'), 'asset_id': _ID, 'job_id': _ID,
                        'confidence_milli': nullable(integer(0, 1000))}, ('asset_id', 'job_id', 'confidence_milli'))})),
    'document': obj(_record_fields('document.put', ('create_ref', 'expected_document_sha256'),
        {'document_id': _ID, 'document_version_id': _ID, 'sha256': _PUBLIC_DIGEST})),
}


def _resolve(op, aliases):
    op = copy.deepcopy(op)
    # Only typed identity fields are aliases; literal text and schema IDs never
    # participate. An unresolved UUID later fails normal entity lookup.
    for k in ('track_id', 'clip_id', 'scene_id', 'layer_id', 'effect_id', 'cue_id', 'document_id', 'group_id', 'linked_group_id'):
        if op.get(k) in aliases:
            op[k] = aliases[op[k]]
    if 'subject' in op:
        op['subject']['id'] = aliases.get(op['subject']['id'], op['subject']['id'])
    if 'target' in op:
        op['target']['id'] = aliases.get(op['target']['id'], op['target']['id'])
    for p in op.get('placements', []):
        for k in ('clip_id', 'target_track_id'):
            p[k] = aliases.get(p[k], p[k])
    for t in op.get('targets', []):
        t['id'] = aliases.get(t['id'], t['id'])
    for k in ('clip_ids', 'track_ids', 'expected_affected_ids', 'expected_dependency_ids'):
        if k in op:
            op[k] = [aliases.get(id_, id_) for id_ in op[k]]
    return op


def _allocate(graph, kind, alias, created):
    validate(alias, _ALIAS)
    _require(alias not in created, 'create_ref alias reused.', 'INVALID_ARGUMENT', create_ref=alias)
    id_ = _new(kind)
    created[alias] = id_
    return id_


def _reorder(rows, row, order):
    _require(order < len(rows), 'Order is outside the collection.', 'INVALID_ARGUMENT')
    ordered = sorted(rows, key=lambda r: r['order'])
    ordered.remove(row)
    ordered.insert(order, row)
    for i, r in enumerate(ordered):
        _require(not r.get('locked') or r['order'] == i,
                 'Ordering would move a locked track.', 'TRACK_LOCKED')
        r['order'] = i


def _split_mapping(mapping, fraction):
    left, right = copy.deepcopy(mapping), copy.deepcopy(mapping)
    a, b = ('in_index', 'out_index') if mapping['domain'] == 'frame' else ('in_pts', 'out_pts')
    split = mapping[a] + (mapping[b] - mapping[a]) * fraction
    _require(split.denominator == 1, 'Split cannot land on a fractional source index.', 'TIMING_INVALID')
    left[b], right[a] = int(split), int(split)
    return left, right


def _deps(graph, kind, id_):
    """Immediate dependent entities, including local production references."""
    result = set()
    if kind == 'track':
        result |= {('clip', c['clip_id']) for c in graph['clips'] if c['track_id'] == id_}
        result |= {('cue', c['cue_id']) for c in graph['captions'] if c['track_id'] == id_}
    if kind == 'scene':
        result |= {('layer', l['layer_id']) for l in graph['layers'] if l['scene_id'] == id_}
        result |= {('clip', c['clip_id']) for c in graph['clips'] if c['subject']['kind'] == 'scene' and c['subject']['id'] == id_}
    if kind == 'clip':
        result |= {('clip', cid) for cid in _linked(graph, [id_]) if cid != id_}
    result |= {('effect', e['effect_id']) for e in graph['effects'] if e['target'] == {'kind': kind, 'id': id_}}
    def has_reference(value):
        if isinstance(value, list):
            return any(has_reference(v) for v in value)
        if isinstance(value, dict):
            return any((k in ('scene_id', 'document_id', 'id') and v == id_) or has_reference(v)
                       for k, v in value.items())
        return False
    for d in graph['production_documents']:
        if (kind, id_) != ('document', d['document_id']) and has_reference(d['value']):
            result.add(('document', d['document_id']))
    if kind == 'document':
        target = _get(graph, 'document', id_)
        if target['kind'] == 'asset_library':
            result |= {('document', d['document_id']) for d in graph['production_documents'] if d['kind'] == 'storyboard'}
        if target['kind'] == 'storyboard':
            result |= {('document', d['document_id']) for d in graph['production_documents'] if d['kind'] == 'creative_plan' and any(b['panel_id'] is not None for b in d['value']['beats'])}
    return result


def _delete(graph, targets, expected, acknowledged):
    _require(len(set(targets)) == len(targets), 'Duplicate delete targets.', 'INVALID_ARGUMENT')
    closure = set(targets)
    for kind, id_ in closure:
        _get(graph, kind, id_)
    while True:
        expanded = closure | {dep for kind, id_ in closure for dep in _deps(graph, kind, id_)}
        if expanded == closure:
            break
        closure = expanded
    dependencies = {id_ for kind, id_ in closure - set(targets)}
    _require(dependencies == set(expected), 'Dependent deletion closure differs from acknowledgement.',
             'AFFECTED_SET_MISMATCH', expected_dependency_ids=sorted(dependencies))
    _require(dependencies <= acknowledged, 'Transaction must acknowledge every dependent entity.',
             'DEPENDENCY_ACKNOWLEDGEMENT_REQUIRED', required_ids=sorted(dependencies))
    for kind, id_ in closure:
        _unlocked(graph, kind, id_)
    for kind, name in _COLLECTIONS.items():
        graph[name] = [r for r in graph[name] if (kind, r[_ID_FIELDS[kind]]) not in closure]
    for n, t in enumerate(sorted(graph['tracks'], key=lambda t: t['order'])):
        _require(not t['locked'] or t['order'] == n,
                 'Deletion would reorder a locked track.', 'TRACK_LOCKED')
        t['order'] = n


def _settings(graph, op):
    old = graph['format']
    new = copy.deepcopy(op['format'])
    _format(new)
    _require(new['duration_frames'] == old['duration_frames'],
             'Duration is derived; settings cannot author a blank tail.', 'TIMING_INVALID')
    old_rate, new_rate = _rate(old['fps']), _rate(new['fps'])
    if new != old or any(op[k] != graph['settings'][k] for k in graph['settings']):
        for t in graph['tracks']:
            _unlocked(graph, 'track', t['track_id'])
    if old_rate != new_rate:
        ratio = new_rate / old_rate
        if op['retime_policy'] == 'preserve_time_nearest_even':
            convert = lambda v: round(v * ratio)
            for c in graph['clips'] + graph['captions'] + graph['layers']:
                c['start_frame'], c['end_frame'] = convert(c['start_frame']), convert(c['end_frame'])
            for s in graph['scenes']:
                s['duration_frames'] = convert(s['duration_frames'])
            for c in graph['clips']:
                if c['subject']['kind'] == 'scene':
                    m = c['source_mapping']
                    _require(m['domain'] == 'frame', 'Scene conform needs frame mapping.', 'TIMING_INVALID')
                    m['in_index'], m['out_index'], m['rate'] = convert(m['in_index']), convert(m['out_index']), new['fps']
        else:
            for c in graph['clips']:
                if c['subject']['kind'] == 'scene':
                    c['source_mapping']['rate'] = copy.deepcopy(new['fps'])
        # Asset mapping remains byte-for-byte pinned. Any rounding that makes
        # output duration disagree is rejected by final exact source validation.
        # Production plans with frame geometry need an explicit coupled put.
    graph['format'] = new
    graph['settings'] = {k: copy.deepcopy(op[k]) for k in ('color_profile_ref', 'output_profile_refs', 'font_fallback_policy')}


def _operate(graph, op, created, acknowledged, planned_trim_ids):
    kind = op['op']
    if kind == 'track.create':
        _require(op['order'] <= len(graph['tracks']), 'Track order out of range.', 'INVALID_ARGUMENT')
        row = {k: op[k] for k in ('kind', 'name', 'overlap_policy')}
        row.update(track_id=_allocate(graph, 'track', op['create_ref'], created),
                   order=len(graph['tracks']), locked=False, visible=True, muted=False, clip_ids=[])
        graph['tracks'].append(row)
        _reorder(graph['tracks'], row, op['order'])
    elif kind == 'track.update':
        row = _get(graph, 'track', op['track_id'])
        if row['locked']:
            _require(not op['locked'] and all(op[k] == row[k] for k in ('name', 'order', 'visible', 'muted')),
                     'A locked track can only be explicitly unlocked.', 'TRACK_LOCKED')
        _reorder(graph['tracks'], row, op['order'])
        row.update({k: op[k] for k in ('name', 'locked', 'visible', 'muted')})
    elif kind == 'clip.insert':
        _unlocked(graph, 'track', op['track_id'])
        _require(op['linked_group_id'] is None or any(c['linked_group_id'] == op['linked_group_id'] for c in graph['clips']),
                 'Insert may join an existing group only; create new groups with link.set.', 'ENTITY_NOT_FOUND')
        _require(op['linked_group_id'] is None or not any(c['linked_group_id'] == op['linked_group_id'] and _track(graph, c)['locked'] for c in graph['clips']),
                 'Cannot append a companion to a locked linked group.', 'TRACK_LOCKED')
        row = {k: copy.deepcopy(v) for k, v in op.items() if k not in ('op', 'create_ref')}
        row.update(clip_id=_allocate(graph, 'clip', op['create_ref'], created), effect_ids=[])
        graph['clips'].append(row)
    elif kind == 'clip.enable':
        ids = _linked(graph, [op['clip_id']])
        for id_ in ids:
            _unlocked(graph, 'clip', id_)
            _get(graph, 'clip', id_)['enabled'] = op['enabled']
    elif kind == 'clip.move':
        ids = [p['clip_id'] for p in op['placements']]
        _require(len(set(ids)) == len(ids), 'Duplicate moved clip.', 'INVALID_ARGUMENT')
        _closure_links(graph, ids)
        deltas = {}
        for p in op['placements']:
            _unlocked(graph, 'clip', p['clip_id'])
            _unlocked(graph, 'track', p['target_track_id'])
            c = _get(graph, 'clip', p['clip_id'])
            delta = p['start_frame'] - c['start_frame']
            group = c['linked_group_id']
            if group is not None:
                _require(group not in deltas or deltas[group] == delta, 'Linked offsets must be preserved.', 'LINKED_OFFSET_CONFLICT')
                deltas[group] = delta
            c['track_id'], c['start_frame'], c['end_frame'] = p['target_track_id'], p['start_frame'], c['end_frame'] + delta
    elif kind == 'clip.trim':
        c = _get(graph, 'clip', op['clip_id'])
        _unlocked(graph, 'clip', op['clip_id'])
        companions = _linked(graph, [op['clip_id']])
        _require(companions <= planned_trim_ids, 'Linked trim requires an explicit trim for each companion.', 'LINKED_CLOSURE_REQUIRED', required_ids=sorted(companions))
        for id_ in companions:
            _unlocked(graph, 'clip', id_)
        c.update({k: copy.deepcopy(op[k]) for k in ('start_frame', 'end_frame', 'source_mapping')})
    elif kind == 'clip.split':
        c = _get(graph, 'clip', op['clip_id'])
        ids = sorted(_linked(graph, [op['clip_id']]))
        group = 'lnk_' + str(uuid.uuid4()) if len(ids) > 1 else None
        for id_ in ids:
            _unlocked(graph, 'clip', id_)
            current = _get(graph, 'clip', id_)
            _require(current['start_frame'] < op['at_frame'] < current['end_frame'], 'Split must be interior to every linked companion.', 'TIMING_INVALID')
            left_mapping, right_mapping = _split_mapping(current['source_mapping'], Fraction(op['at_frame'] - current['start_frame'], current['end_frame'] - current['start_frame']))
            right = copy.deepcopy(current)
            # Companion IDs are returned under a deterministic compound key;
            # the requested clip always uses the caller's UUID alias.
            if id_ == op['clip_id']:
                right['clip_id'] = _allocate(graph, 'clip', op['right_create_ref'], created)
            else:
                key = op['right_create_ref'] + ':' + id_
                right['clip_id'] = _new('clip')
                created[key] = right['clip_id']
            current['end_frame'], current['source_mapping'] = op['at_frame'], left_mapping
            right['start_frame'], right['source_mapping'] = op['at_frame'], right_mapping
            if group:
                right['linked_group_id'] = group
            graph['clips'].append(right)
    elif kind == 'timeline.ripple':
        tracks = set(op['track_ids'])
        for id_ in tracks:
            _unlocked(graph, 'track', id_)
        start, end, delta = op['range']['start_frame'], op['range']['end_frame'], op['delta_frames']
        action = op['action']
        _require((action == 'insert_gap' and start == end and delta > 0) or
                 (action in ('delete', 'close_gap') and end > start and delta == start - end),
                 'Ripple range/action/delta disagree.', 'TIMING_INVALID')
        affected, removed = [], []
        for entity_kind, collection in (('clip', 'clips'), ('cue', 'captions')):
            for c in graph[collection]:
                if c['track_id'] not in tracks or c['end_frame'] <= start:
                    continue
                inside = start <= c['start_frame'] and c['end_frame'] <= end and start < end
                crossing = c['start_frame'] < start < c['end_frame'] or (start < end and c['start_frame'] < end < c['end_frame'])
                _require(not crossing, 'Split boundary-crossing placements before ripple.', 'TIMING_INVALID')
                if action == 'close_gap':
                    _require(not inside, 'close_gap span must actually be empty.', 'TIMING_INVALID')
                if inside and action == 'delete':
                    removed.append((entity_kind, c[_ID_FIELDS[entity_kind]]))
                affected.append((entity_kind, c))
        actual = {c[_ID_FIELDS[k]] for k, c in affected}
        _require(actual == set(op['expected_affected_ids']), 'Ripple affected set changed.', 'AFFECTED_SET_MISMATCH', expected_affected_ids=sorted(actual))
        _closure_links(graph, [c['clip_id'] for k, c in affected if k == 'clip'])
        for k, c in affected:
            _unlocked(graph, k, c[_ID_FIELDS[k]])
            if (k, c[_ID_FIELDS[k]]) not in removed:
                c['start_frame'] += delta
                c['end_frame'] += delta
        # Dependencies other than links cannot disappear implicitly.
        for k, id_ in removed:
            _require(_deps(graph, k, id_) <= set(removed), 'Ripple removal has unlisted dependents.', 'DEPENDENCY_ACKNOWLEDGEMENT_REQUIRED')
        for k, collection in (('clip', 'clips'), ('cue', 'captions')):
            graph[collection] = [c for c in graph[collection] if (k, c[_ID_FIELDS[k]]) not in removed]
    elif kind == 'entity.delete':
        _delete(graph, [(t['kind'], t['id']) for t in op['targets']], op['expected_dependency_ids'], acknowledged)
    elif kind in ('scene.create', 'scene.update'):
        if kind.endswith('create'):
            row = {'scene_id': _allocate(graph, 'scene', op['create_ref'], created), 'layer_ids': []}
            graph['scenes'].append(row)
        else:
            _unlocked(graph, 'scene', op['scene_id'])
            row = _get(graph, 'scene', op['scene_id'])
        row.update({k: copy.deepcopy(op[k]) for k in ('name', 'duration_frames', 'background')})
    elif kind in ('layer.create', 'layer.update'):
        if kind.endswith('create'):
            _unlocked(graph, 'scene', op['scene_id'])
            row = {'layer_id': _allocate(graph, 'layer', op['create_ref'], created), 'scene_id': op['scene_id'], 'type': op['type']}
            graph['layers'].append(row)
        else:
            _unlocked(graph, 'layer', op['layer_id'])
            row = _get(graph, 'layer', op['layer_id'])
        row.update({k: copy.deepcopy(op[k]) for k in ('schema_ref', 'parameters', 'keyframes', 'start_frame', 'end_frame', 'order')})
        _validate_layer(row)
    elif kind.startswith('effect.'):
        _fail('UNSUPPORTED_OPERATION', 'Existing backend exposes no effect-stack compiler; no effect schema is advertised.')
    elif kind == 'audio.set':
        target = op['target']
        _unlocked(graph, target['kind'], target['id'])
        row = _get(graph, target['kind'], target['id'])
        if target['kind'] == 'clip':
            _require(_track(graph, row)['kind'] == 'audio', 'Audio target must be an audio clip.')
        audio = {k: copy.deepcopy(op[k]) for k in ('gain_db_milli', 'pan_milli', 'muted', 'fades', 'envelope')}
        _validate_audio(audio, graph['format']['duration_frames'])
        row['audio'] = audio
        if target['kind'] == 'bus':
            row.update({k: audio[k] for k in ('gain_db_milli', 'pan_milli', 'muted')})
    elif kind == 'caption.upsert':
        _require((op['cue_id'] is None) != (op['create_ref'] is None), 'Supply exactly one cue ID or create_ref.', 'INVALID_ARGUMENT')
        _unlocked(graph, 'track', op['track_id'])
        if op['cue_id'] is None:
            row = {'cue_id': _allocate(graph, 'cue', op['create_ref'], created), 'source': {'kind': 'manual'}, 'editorial_revision': 1}
            graph['captions'].append(row)
        else:
            _unlocked(graph, 'cue', op['cue_id'])
            row = _get(graph, 'cue', op['cue_id'])
            row['editorial_revision'] += 1
        row.update({k: copy.deepcopy(op[k]) for k in ('track_id', 'start_frame', 'end_frame', 'text', 'language', 'style_ref')})
    elif kind == 'settings.set':
        _settings(graph, op)
    elif kind == 'link.set':
        for id_ in op['clip_ids']:
            _unlocked(graph, 'clip', id_)
        _closure_links(graph, op['clip_ids'])
        group_id = op['group_id']
        if op['group_id'] is not None:
            existing = {c['clip_id'] for c in graph['clips'] if c['linked_group_id'] == op['group_id']}
            _require(existing <= set(op['clip_ids']), 'Destination link group closure must be explicit.', 'LINKED_CLOSURE_REQUIRED')
            if not existing:
                validate(group_id, _ALIAS)
                _require(group_id not in created, 'Group alias reused.', 'INVALID_ARGUMENT')
                group_id = 'lnk_' + str(uuid.uuid4())
                created[op['group_id']] = group_id
        for id_ in op['clip_ids']:
            _get(graph, 'clip', id_)['linked_group_id'] = group_id
    elif kind == 'document.put':
        _require((op['document_id'] is None) != (op['create_ref'] is None), 'Supply exactly one document ID or create_ref.', 'INVALID_ARGUMENT')
        if op['document_id'] is None:
            _require(op['expected_document_sha256'] is None, 'New document cannot expect an old hash.', 'INVALID_ARGUMENT')
            row = {'document_id': _allocate(graph, 'document', op['create_ref'], created)}
            graph['production_documents'].append(row)
        else:
            row = _get(graph, 'document', op['document_id'])
            _require(row['sha256'] == op['expected_document_sha256'], 'Document expected hash differs.', 'STALE_DEPENDENCY')
            _require(row['kind'] == op['kind'], 'Document family cannot change.', 'INVALID_ARGUMENT')
        row.update({k: copy.deepcopy(op[k]) for k in ('kind', 'schema_ref', 'value')})
        row.update(document_version_id='dvr_' + str(uuid.uuid4()), sha256=public_hash(op['value']))
        _validate_document(row)
    elif kind == 'document.remove':
        row = _get(graph, 'document', op['document_id'])
        _require(row['sha256'] == op['expected_document_sha256'], 'Document expected hash differs.', 'STALE_DEPENDENCY')
        _delete(graph, [('document', op['document_id'])], op['expected_dependency_ids'], acknowledged)


def _changes(before, after):
    a, b = _index(before), _index(after)
    entities, ranges = [], []
    for kind in _KINDS:
        for id_ in sorted(set(a[kind]) | set(b[kind])):
            old, new = a[kind].get(id_), b[kind].get(id_)
            if old == new:
                continue
            entities.append({'kind': kind, 'id': id_})
            for row in (old, new):
                if row is None:
                    continue
                if kind in ('clip', 'cue'):
                    ranges.append({'start_frame': row['start_frame'], 'end_frame': row['end_frame']})
                elif kind == 'track':
                    for g in (before, after):
                        for c in g['clips'] + g['captions']:
                            if c['track_id'] == id_:
                                ranges.append({'start_frame': c['start_frame'], 'end_frame': c['end_frame']})
                elif kind in ('scene', 'layer'):
                    sid = id_ if kind == 'scene' else row['scene_id']
                    for g in (before, after):
                        for c in g['clips']:
                            if c['subject']['kind'] == 'scene' and c['subject']['id'] == sid:
                                ranges.append({'start_frame': c['start_frame'], 'end_frame': c['end_frame']})
    if before['format'] != after['format'] or before['settings'] != after['settings']:
        entities.append({'kind': 'settings', 'id': 'composition'})
        duration = max(before['format']['duration_frames'], after['format']['duration_frames'])
        if duration:
            ranges.append({'start_frame': 0, 'end_frame': duration})
    merged = []
    for r in sorted(ranges, key=lambda r: (r['start_frame'], r['end_frame'])):
        if merged and r['start_frame'] <= merged[-1]['end_frame']:
            merged[-1]['end_frame'] = max(merged[-1]['end_frame'], r['end_frame'])
        else:
            merged.append(dict(r))
    invalidated = [{'kind': 'entity_content', 'id': e['id'], 'entity_kind': e['kind']} for e in entities]
    return entities, merged, invalidated


def apply_operations(graph, operations, acknowledged_dependency_ids=()):
    """Apply a finite typed transaction atomically to a deep copy.

    1..1000 operations, <=1 MiB canonical input. Locks are evaluated in operation
    order (an explicit unlock may precede an edit); graph constraints are checked
    on the full post-state so coupled changes may repair intermediate geometry.
    ``invalidated_refs`` names changed content refs only, never invented jobs or
    quality gates. Store/snapshot invalidation is the service owner's concern.
    """
    validate_graph(graph)
    _json(operations)
    _require(type(operations) is list and 1 <= len(operations) <= 1000,
             'Transaction requires 1..1000 operations.', 'INVALID_ARGUMENT')
    _require(len(canonical(operations)) <= 1048576, 'Transaction exceeds 1 MiB.', 'LIMIT_EXCEEDED')
    _require(type(acknowledged_dependency_ids) in (tuple, list),
             'Dependency acknowledgement must be an array of IDs.', 'INVALID_ARGUMENT')
    validate(list(acknowledged_dependency_ids), arr(_ID, unique=True))
    for op in operations:
        _require(type(op) is dict and type(op.get('op')) is str and op['op'] in _OPS,
                 'Unknown typed edit variant.', 'UNSUPPORTED_OPERATION')
        _shape(op, {'op': enum(op['op']), **_OPS[op['op']]})
    result, created = copy.deepcopy(graph), {}
    trim_deltas = {}
    for raw in operations:
        op = _resolve(raw, created)
        planned = {_resolve(o, created)['clip_id'] for o in operations if o['op'] == 'clip.trim'}
        if op['op'] == 'clip.trim':
            c = _get(result, 'clip', op['clip_id'])
            group = c['linked_group_id']
            delta = (op['start_frame'] - c['start_frame'], op['end_frame'] - c['end_frame'])
            if group is not None:
                trim_deltas.setdefault(group, []).append(delta)
        ack = {created.get(id_, id_) for id_ in acknowledged_dependency_ids}
        _operate(result, op, created, ack, planned)
        _sync(result)
    for deltas in trim_deltas.values():
        _require(len(set(deltas)) == 1, 'Linked trim edge deltas must agree.', 'LINKED_OFFSET_CONFLICT')
    result['tracks'].sort(key=lambda t: t['order'])
    result['production_documents'].sort(key=lambda d: (d['kind'], d['document_id']))
    _sync(result)
    validate_graph(result)
    entities, ranges, invalidated = _changes(graph, result)
    return {'graph': result, 'created_ids': created, 'affected_entities': entities,
            'affected_frame_ranges': ranges, 'invalidated_refs': invalidated}


def _backend_key(prefix, id_):
    return prefix + '_' + id_.split('_', 1)[1].replace('-', '')


def compile_graph(graph, *, backend='legacy', recipe=None):
    """Compile legacy B03 values or an explicit exact canonical graph closure.

    Canonical output is NOT a B03 Scene/Timeline projection. Its host must retain
    the native Project/Composition binding and persist the immutable artifact
    closure, not strip unsupported content to satisfy legacy store schemas.
    Historical pin verification remains trusted resolver/store work.
    """
    if backend == 'canonical_graph_render_v1':
        from .ui_rendering import compile_canonical_graph
        return compile_canonical_graph(graph, recipe)
    _require(backend == 'legacy', 'Unknown graph compiler target.', 'UNSUPPORTED_OPERATION')
    validate_graph(graph)
    _require(all(l['schema_ref'] == _pin('motion.ui.layer.layout', _LAYOUT_SCHEMA)
                 for l in graph['layers']),
             'Compositor layers require the canonical_graph_render_v1 compiler target.',
             'UNSUPPORTED_OPERATION')
    _require(all(not c.get('audio') or (c['audio']['pan_milli'] == 0 and
                                      not c['audio']['envelope']) for c in graph['clips']),
             'Pan/envelopes require the canonical_graph_render_v1 compiler target.',
             'UNSUPPORTED_OPERATION')
    graph = copy.deepcopy(graph)
    _require(graph['settings'] == {'color_profile_ref': None, 'output_profile_refs': [], 'font_fallback_policy': 'reject'},
             'Backend Settings has no output-color/profile/font-fallback fields.', 'UNSUPPORTED_OPERATION')
    _require(not graph['audio_buses'], 'Backend has no bus mixer.', 'UNSUPPORTED_OPERATION')
    _require(not graph['captions'], 'Cue-only captions cannot become ASR documents: source audio/transcript evidence is required.', 'UNSUPPORTED_OPERATION')
    docs = {(d['kind'], d['document_id']): copy.deepcopy(d['value']) for d in graph['production_documents']}
    by_kind = {d['kind']: d['value'] for d in graph['production_documents'] if d['kind'] != 'delivery_profile'}
    settings = {'rate': graph['format']['fps'], 'sample_rate': graph['format']['sample_rate'],
                'audio_mode': 'silent', 'stage': by_kind.get('stage', 'intake'),
                'policy': by_kind.get('execution_policy', {'remote': 'deny', 'allowed_destinations': [],
                           'paid': 'deny', 'max_concurrent_nodes': 1, 'retain_generated_assets': True}),
                'gate_policy': by_kind.get('gate_policy', default_gate_policy())}
    if 'voice_preferences' in by_kind:
        settings['voice_preferences'] = copy.deepcopy(by_kind['voice_preferences'])
    scenes = {}
    for s in graph['scenes']:
        _require(s['background'] is None, 'Backend Scene does not implement background paint.', 'UNSUPPORTED_OPERATION', scene_id=s['scene_id'])
        layers = [_get(graph, 'layer', id_) for id_ in s['layer_ids']]
        layout = []
        for l in layers:
            _require(l['start_frame'] == 0 and l['end_frame'] == s['duration_frames'],
                     'Backend Layout has no temporal layer visibility.', 'UNSUPPORTED_OPERATION', layer_id=l['layer_id'])
            parameters = copy.deepcopy(l['parameters'])
            pin = parameters['asset']
            asset = next(a for a in graph['asset_refs'] if all(a[key] == pin[key] for key in ('asset_id','asset_version_id','sha256')))
            parameters['asset'] = copy.deepcopy(asset['artifact'])
            layout.append(parameters)
        _require(len({l['element_key'] for l in layout}) == len(layout), 'Duplicate scene layout element key.')
        assets = []
        for l in layout:
            if 'asset' in l and l['asset'] not in assets:
                assets.append(copy.deepcopy(l['asset']))
        scene = {'scene_id': s['scene_id'], 'label': s['name'], 'duration_frames': s['duration_frames'],
                 'canvas': {'width_px': graph['format']['width'], 'height_px': graph['format']['height']},
                 'assets': assets, 'layout': layout, 'safe_zones': [], 'motion_intent': '', 'camera_intent': '',
                 'authored_source': None, 'source_format': None, 'source_runtime': None}
        validate(scene, D['Scene'])
        domain(scene)
        scenes[s['scene_id']] = scene
    timeline = {'duration_frames': graph['format']['duration_frames'], 'tracks': []}
    for t in sorted(graph['tracks'], key=lambda t: t['order']):
        _require(t['overlap_policy'] == 'exclusive', 'Backend has no composite/mix track policy.', 'UNSUPPORTED_OPERATION', track_id=t['track_id'])
        # Empty overlay maps to empty video track, but any actual overlay needs
        # a compositor; multiple video layers must not imply one exists.
        _require(t['kind'] != 'overlay' or not t['clip_ids'], 'Backend has no overlay compositor.', 'UNSUPPORTED_OPERATION')
        track = {'track_id': _backend_key('track', t['track_id']),
                 'kind': 'video' if t['kind'] == 'overlay' else t['kind'], 'items': []}
        for id_ in t['clip_ids']:
            c = _get(graph, 'clip', id_)
            audio = c.get('audio')
            if not c['enabled'] or (t['kind'] == 'audio' and (t['muted'] or (audio and audio['muted']))) or (t['kind'] != 'audio' and not t['visible']):
                continue
            subject, m = c['subject'], c['source_mapping']
            item = {'item_id': _backend_key('clip', c['clip_id']), 'start_frame': c['start_frame'], 'end_frame': c['end_frame']}
            if m['domain'] == 'frame':
                _require(m['speed'] == {'num': 1, 'den': 1} and m['rate'] == settings['rate'],
                         'Backend Timeline has no retime/conform recipe field; prepare explicit derivative.', 'UNSUPPORTED_OPERATION')
                index, domain_name, rate = m['in_index'], 'frame', m['rate']
            else:
                index, domain_name = m['in_pts'], 'source_tick'
                rate = {'num': m['time_base']['den'], 'den': m['time_base']['num']}
            if subject['kind'] == 'scene':
                item['subject'] = {'kind': 'scene', 'scene_id': subject['id']}
                item['source_in'] = {'domain': 'frame', 'index': index, 'rate': rate, 'origin': 'project'}
            else:
                asset = next(a for a in graph['asset_refs'] if a['asset_id'] == subject['id'] and a['asset_version_id'] == subject['version_id'])
                artifact = copy.deepcopy(asset['artifact'])
                item['subject'] = {'kind': 'artifact', 'artifact': artifact}
                item['source_in'] = {'domain': domain_name, 'index': index, 'rate': rate, 'origin': 'source', 'source_artifact': artifact}
            if t['kind'] == 'audio':
                settings['audio_mode'] = 'recorded'
                if audio:
                    gain = audio['gain_db_milli']
                    sign = '-' if gain < 0 else ''
                    whole, remainder = divmod(abs(gain), 1000)
                    item['gain_db'] = sign + str(whole) + ('.' + str(remainder).zfill(3).rstrip('0') if remainder else '')
            track['items'].append(item)
        timeline['tracks'].append(track)
    # Backend has no declared inter-track compositor. Distinct picture tracks
    # with intersecting placements must not silently become a layering promise.
    picture = [i for t in timeline['tracks'] if t['kind'] == 'video' for i in t['items']]
    for n, item in enumerate(picture):
        _require(not any(item['start_frame'] < other['end_frame'] and other['start_frame'] < item['end_frame'] for other in picture[n + 1:]),
                 'Backend has no multi-track picture compositor.', 'UNSUPPORTED_OPERATION')
    # Public pin adaptation needs real persisted backend document envelopes.
    # Variant/profile and board/library pins are resolved under the store lock.
    # Editorial additionally needs historical timeline/caption/job mapping.
    for kind in ('editorial',):
        if by_kind.get(kind):
            _fail('UNSUPPORTED_OPERATION', 'Editorial requires authorized historical timeline/caption/job mapping.', kind=kind)
    validate(settings, _public_schema(D['Settings']))
    domain(settings)
    validate_timeline(timeline, settings['rate'], settings['sample_rate'], scenes=scenes)
    backend_docs = {}
    singleton = {'brief', 'brand', 'asset_library', 'storyboard', 'creative_plan', 'editorial', 'bindings', 'variants'}
    for (kind, id_), value in docs.items():
        if kind in ('execution_policy', 'gate_policy', 'stage', 'voice_preferences'):
            if kind == 'gate_policy':
                backend_docs[('gate_policy', value['policy_id'])] = value
            continue
        key = (kind, 'project' if kind in singleton else value.get('profile_id', id_))
        _require(key not in backend_docs, 'Duplicate backend document identity.')
        backend_docs[key] = value
    backend_docs.setdefault(('brief', 'project'), empty_brief())
    backend_docs.setdefault(('brand', 'project'), {'colors': {}, 'fonts': [], 'spacing_px': {}, 'motion_tokens': {}, 'logo_assets': [], 'reference_assets': []})
    backend_docs.setdefault(('variants', 'project'), [])
    backend_docs.setdefault(('bindings', 'project'), {'selected_adapter_ids': [], 'preferences': {}, 'pins': {}})
    backend_docs.setdefault(('gate_policy', settings['gate_policy']['policy_id']), copy.deepcopy(settings['gate_policy']))
    return {'settings': copy.deepcopy(settings), 'timeline': timeline, 'scenes': scenes,
            'format': copy.deepcopy(graph['format']),
            'production_documents': backend_docs}
