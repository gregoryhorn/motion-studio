"""Owned canonical UI compositor; no optional imports or execution on import.

Integration (explicit registration; this module does not activate itself):
  registry.register(**registration())
  LocalUICompositorAdapter(runtime, binding)
Compile with source_bytes(graph, recipe), ingest those *actual bytes* as an owned
JSON source artifact, and pass its ArtifactRef as inputs.source plus the complete
dependencies as inputs.assets. make_plan_builder supplies the real native plan.
Do not translate
this graph to B03 Timeline/Scene. validate_source is the renderer-side validator;
the UI graph service must additionally retain its UUID/transaction/ownership
checks while replacing B03-only capability restrictions with schema_catalog().
Both operations evaluate identical full-resolution frames via Evaluator.frame.
Preview is lossless PNG, export lossless RGB FFV1 + optional PCM stereo, not a
low-quality or separate approximation. No ASR/transcript receipt is fabricated.

Boundaries: RGB SDR only, no ICC/HDR/YUV color conversion, no source-tick/VFR,
retiming, resampling, effects, groups, bus routing or arbitrary recipes. Video
inputs must already be CFR RGB FFV1 Matroska, audio PCM16 WAV at output sample rate.
Integer geometry, linear/hold scalar keyframes, ASCII pinned-font text, rectangles
and ellipses are implemented. Complex shaping is explicitly refused, not faked.
All media work occurs in one bounded child admitted by WorkerContext.run. The
private child is not a daemon and never launches another process.
"""
from __future__ import annotations

import array
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction

from ..contracts import ContractError, D, canonical, digest, validate, safe_relative
from . import ffmpeg

ADAPTER_ID = 'local.ui-compositor'
VERSION = '1.0.0'
OPERATIONS = ('ui.compose@1', 'ui.frame@1')
SOURCE_SCHEMA = 'motion/ui-compositor-source/v1'
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ASSET_BYTES = 1024 ** 3
MAX_FRAMES = 18000
MAX_PIXELS = 3840 * 2160
FEATURES = ['ui.canonical_graph', 'ui.frame_parity', 'ui.picture_composite',
            'ui.transforms', 'ui.crop', 'ui.opacity', 'ui.z_order',
            'ui.text.pinned_ascii', 'ui.shape', 'ui.manual_captions',
            'ui.background', 'ui.audio.pcm_mix', 'ui.audio.gain_pan_fades',
            'ui.keyframes.linear_hold']


def _obj(fields, optional=()):
    return dict(type='object', properties=fields,
                required=[k for k in fields if k not in optional], additionalProperties=False)


def _int(lo, hi):
    return dict(type='integer', minimum=lo, maximum=hi)


def _enum(*values):
    return dict(enum=list(values))


RATE = _obj(dict(num=_int(1, 60000), den=_int(1, 60000)))
COLOR = dict(type='array', items=_int(0, 255), minItems=4, maxItems=4)
RECT = _obj(dict(x=_int(0, 8192), y=_int(0, 8192), width=_int(1, 8192), height=_int(1, 8192)))
TRANSFORM = _obj(dict(x=_int(-8192, 8192), y=_int(-8192, 8192),
    width=_int(1, 8192), height=_int(1, 8192), rotation_mdeg=_int(-360000, 360000),
    opacity_milli=_int(0, 1000), crop=dict(anyOf=[{'type': 'null'}, RECT])))
ASSET_PIN = _obj(dict(asset_id={'type': 'string'}, asset_version_id={'type': 'string'},
    sha256={'type': 'string', 'pattern': '^[0-9a-f]{64}$'}))
TEXT = _obj(dict(text={'type': 'string', 'maxLength': 8192},
    font_binding_id={'type': 'string'}, size=_obj(dict(num=_int(1, 4096), den=_int(1, 4096))),
    weight={'const': 'face'}, style={'const': 'face'}, color=COLOR,
    alignment=_enum('left', 'center', 'right'), safe_box=RECT, transform=TRANSFORM))
LAYER_SCHEMAS = {
    'text': TEXT,
    'image': _obj(dict(asset=ASSET_PIN, transform=TRANSFORM)),
    'media': _obj(dict(asset=ASSET_PIN, source_in=_int(0, MAX_FRAMES), transform=TRANSFORM)),
    'shape': _obj(dict(shape=_enum('rectangle', 'ellipse'), color=COLOR, transform=TRANSFORM)),
}
EASINGS = {'linear': {'type': 'number'}, 'hold': {'type': 'number'}}
COLOR_SCHEMA = {'const': 'srgb-rgb-full-unmanaged-v1'}
FADE_SCHEMA = {'const': 'linear-amplitude-in-out-v1'}
RECIPE_SCHEMA = _obj(dict(id={'const': 'ui-rgb-lossless-v1'},
    color={'const': 'srgb-rgb-full-unmanaged-v1'}, background=COLOR,
    caption_style=dict(anyOf=[{'type': 'null'}, TEXT])))
PARAMS = _obj(dict(frame=dict(anyOf=[{'type': 'null'}, _int(0, MAX_FRAMES - 1)])))


def _public_hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _schema_pin(name, schema):
    return dict(id=name, version=1, sha256=_public_hash(schema))


def schema_catalog():
    """Exact immutable schemas for UI capability/command validation."""
    entries = {'layer.' + k: (f'motion.ui.compositor.layer.{k}', s)
               for k, s in LAYER_SCHEMAS.items()}
    entries.update({'easing.' + k: (f'motion.ui.compositor.easing.{k}', s) for k, s in EASINGS.items()})
    entries.update({'color': ('motion.ui.compositor.color', COLOR_SCHEMA),
                    'fade': ('motion.ui.compositor.fade', FADE_SCHEMA),
                    'caption': ('motion.ui.compositor.caption', TEXT),
                    'recipe': ('motion.ui.compositor.recipe', RECIPE_SCHEMA)})
    return {k: dict(schema_ref=_schema_pin(name, s), schema=copy.deepcopy(s)) for k, (name, s) in entries.items()}


def _check(ok, message, code='UNSUPPORTED_OPERATION'):
    if not ok:
        raise ContractError(code, message)


def _keys(value, required, optional=()):
    _check(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional),
           'Unexpected or missing canonical fields: ' + str(required), 'INVALID_GRAPH')


def _number(value, lo, hi):
    _check(type(value) is int and lo <= value <= hi, 'Integer outside renderer bounds', 'INVALID_GRAPH')
    return value


def _rate(value):
    validate(value, RATE)
    return Fraction(value['num'], value['den'])


def _range(row, limit):
    _number(row['start_frame'], 0, limit - 1)
    _number(row['end_frame'], row['start_frame'] + 1, limit)


def _audio(value, duration):
    _keys(value, ('gain_db_milli', 'pan_milli', 'muted', 'fades', 'envelope'))
    _number(value['gain_db_milli'], -60000, 12000)
    _number(value['pan_milli'], -1000, 1000)
    _check(type(value['muted']) is bool, 'Audio mute must be boolean', 'INVALID_GRAPH')
    frames = []
    for point in value['envelope']:
        _keys(point, ('frame', 'gain_db_milli'))
        frames.append(_number(point['frame'], 0, duration))
        _number(point['gain_db_milli'], -60000, 12000)
    _check(frames == sorted(set(frames)), 'Gain envelope must be ordered and unique', 'INVALID_GRAPH')
    _check(len(value['fades']) <= 2, 'At most one edge fade per end')
    previous = -1
    for fade in value['fades']:
        _keys(fade, ('start_frame', 'end_frame', 'curve_ref'))
        _range(fade, duration)
        _check(fade['curve_ref'] == schema_catalog()['fade']['schema_ref'], 'Unknown fade recipe')
        _check(fade['start_frame'] == 0 or fade['end_frame'] == duration, 'Fades must touch a clip edge')
        _check(fade['start_frame'] >= previous, 'Overlapping fades require an explicit different recipe')
        previous = fade['end_frame']


def default_audio():
    return dict(gain_db_milli=0, pan_milli=0, muted=False, fades=[], envelope=[])


def validate_graph(graph, recipe):
    """Validate full renderer closure, including disabled/unplaced records.

    This intentionally does not call ui_graph.validate_graph: that validator
    currently rejects the very schemas implemented here. Parent must integrate
    these capabilities, not bypass public transaction/asset ownership validation.
    """
    _keys(graph, ('schema_version', 'format', 'tracks', 'clips', 'scenes', 'layers',
                  'effects', 'audio_buses', 'captions', 'asset_refs', 'settings', 'production_documents'))
    _check(graph['schema_version'] == 'composition.v1', 'Unknown graph schema')
    _check(len(canonical(graph)) <= MAX_SOURCE_BYTES, 'Graph source exceeds byte bound', 'LIMIT_EXCEEDED')
    validate(recipe, RECIPE_SCHEMA)
    _check(recipe['background'][3] == 255, 'Output recipe background must be opaque RGB')
    f = graph['format']
    _keys(f, ('fps', 'width', 'height', 'sample_rate', 'channels', 'duration_frames'))
    fps = _rate(f['fps'])
    _check(Fraction(1) <= fps <= 60, 'Frame rate outside 1..60')
    _number(f['width'], 1, 3840); _number(f['height'], 1, 3840)
    _check(f['width'] * f['height'] <= MAX_PIXELS, 'Raster exceeds pixel bound')
    _number(f['duration_frames'], 1, MAX_FRAMES)
    _check(Fraction(f['duration_frames']) / fps <= 600, 'Bounded compositor duration exceeds 600 seconds', 'LIMIT_EXCEEDED')
    _number(f['sample_rate'], 8000, 96000)
    _check(f['channels'] == 2, 'Output is explicitly stereo PCM, not implicit channel conform')
    _check((Fraction(f['duration_frames'] * f['sample_rate']) / fps).denominator == 1,
           'Composition duration must end on a sample boundary')
    _keys(graph['settings'], ('color_profile_ref', 'output_profile_refs', 'font_fallback_policy'))
    _check(graph['settings']['color_profile_ref'] in (None, schema_catalog()['color']['schema_ref']),
           'Unsupported color management profile; prepare an explicit supported RGB source')
    _check(graph['settings']['output_profile_refs'] == [] and graph['settings']['font_fallback_policy'] == 'reject',
           'Output profiles and implicit font fallback are not supported')
    _check(not graph['effects'], 'Effect schemas are not implemented by this renderer')
    # Buses have no source-membership field in composition.v1; accepting a bus
    # would silently invent routing. Clip mixing is implemented, buses rejected.
    _check(not graph['audio_buses'], 'Bus source membership/routing is not defined for this renderer')
    ids = set()
    indices = {}
    for collection, field in [('tracks', 'track_id'), ('clips', 'clip_id'), ('scenes', 'scene_id'),
                              ('layers', 'layer_id'), ('captions', 'cue_id')]:
        _check(isinstance(graph[collection], list) and len(graph[collection]) <= 4096,
               'Collection exceeds bounded record count', 'INVALID_GRAPH')
        indices[collection] = {}
        for row in graph[collection]:
            identity = row.get(field)
            _check(isinstance(identity, str) and identity and identity not in ids,
                   'Record IDs must be unique', 'INVALID_GRAPH')
            ids.add(identity); indices[collection][identity] = row
    assets = {}
    _check(len(graph['asset_refs']) <= 32, 'At most 32 pinned assets per bounded compositor job', 'LIMIT_EXCEEDED')
    for asset in graph['asset_refs']:
        _keys(asset, ('asset_id', 'asset_version_id', 'sha256', 'kind', 'artifact'),
              ('rate', 'duration_frames', 'time_base', 'start_pts', 'duration_ticks', 'sample_rate', 'stream_index'))
        validate(asset['artifact'], D['ArtifactRef'])
        _check(re.fullmatch('[0-9a-f]{64}', asset['sha256']) is not None and
               'sha256:' + asset['sha256'] == asset['artifact']['sha256'], 'Asset byte pin differs', 'HASH_MISMATCH')
        key = (asset['asset_id'], asset['asset_version_id'])
        _check(key not in assets, 'Duplicate asset version', 'INVALID_GRAPH')
        _check(asset['kind'] in ('image', 'video', 'audio', 'font'), 'Unsupported source asset kind')
        _check(asset.get('stream_index', 0) == 0, 'Only explicit first media stream is supported')
        assets[key] = asset
    def asset_for(pin, kinds):
        validate(pin, ASSET_PIN)
        a = assets.get((pin['asset_id'], pin['asset_version_id']))
        _check(a is not None and a['sha256'] == pin['sha256'] and a['kind'] in kinds,
               'Unresolved exact typed asset pin', 'ASSET_UNRESOLVED')
        return a
    def text_check(p):
        _check(all(c == '\n' or 32 <= ord(c) <= 126 for c in p['text']),
               'This route requires ASCII text; complex shaping must use a qualified shaping renderer')
        fonts = [a for a in assets.values() if a['kind'] == 'font' and a['asset_id'] == p['font_binding_id']]
        _check(len(fonts) == 1, 'Font binding must resolve one byte-pinned face', 'ASSET_UNRESOLVED')
        size = Fraction(p['size']['num'], p['size']['den'])
        _check(size.denominator == 1 and 1 <= size <= 1024, 'Font size requires integral design pixels')
        box = p['safe_box']
        _check(box['x'] + box['width'] <= p['transform']['width'] and
               box['y'] + box['height'] <= p['transform']['height'], 'Safe box exceeds text-local raster')
    if recipe['caption_style'] is not None:
        text_check(recipe['caption_style'])
    for scene in graph['scenes']:
        _keys(scene, ('scene_id', 'name', 'duration_frames', 'layer_ids', 'background'))
        _number(scene['duration_frames'], 1, MAX_FRAMES)
        if scene['background'] is not None:
            validate(scene['background'], COLOR)
        ls = sorted((l for l in graph['layers'] if l['scene_id'] == scene['scene_id']), key=lambda l: (l['order'], l['layer_id']))
        _check(scene['layer_ids'] == [l['layer_id'] for l in ls] and len({l['order'] for l in ls}) == len(ls),
               'Scene layer order/projection differs', 'INVALID_GRAPH')
    for layer in graph['layers']:
        _keys(layer, ('layer_id', 'scene_id', 'type', 'schema_ref', 'order', 'start_frame', 'end_frame', 'parameters', 'keyframes'))
        _number(layer['order'], 0, 4096)
        scene = indices['scenes'].get(layer['scene_id'])
        _check(scene is not None, 'Layer scene is absent', 'INVALID_GRAPH')
        _range(layer, scene['duration_frames'])
        kind, p = layer['type'], layer['parameters']
        _check(kind in LAYER_SCHEMAS and layer['schema_ref'] == schema_catalog()['layer.' + kind]['schema_ref'],
               'Unknown layer type/schema pin')
        validate(p, LAYER_SCHEMAS[kind])
        _check(p['transform']['width'] * p['transform']['height'] <= MAX_PIXELS,
               'Layer raster exceeds bound', 'LIMIT_EXCEEDED')
        if kind in ('image', 'media'):
            a = asset_for(p['asset'], ('image',) if kind == 'image' else ('video',))
            if kind == 'media':
                _check(a.get('rate') == f['fps'] and p['source_in'] + layer['end_frame'] - layer['start_frame'] <= a.get('duration_frames', 0),
                       'Media layer requires exact CFR source range/rate')
        elif kind == 'text':
            text_check(p)
        pairs = set()
        for key in layer['keyframes']:
            _keys(key, ('property', 'frame', 'value', 'easing_ref'))
            prop = key['property']
            _check(prop in ('x', 'y', 'width', 'height', 'rotation_mdeg', 'opacity_milli'), 'Unknown animated property')
            _number(key['frame'], 0, scene['duration_frames'] - 1)
            validate(key['value'], TRANSFORM['properties'][prop])
            _check(key['easing_ref'] in [schema_catalog()['easing.' + k]['schema_ref'] for k in EASINGS], 'Unknown easing schema')
            _check((prop, key['frame']) not in pairs, 'Duplicate keyframe', 'INVALID_GRAPH')
            pairs.add((prop, key['frame']))
    _check(sorted(t['order'] for t in graph['tracks']) == list(range(len(graph['tracks']))), 'Track order must be contiguous', 'INVALID_GRAPH')
    for track in graph['tracks']:
        _keys(track, ('track_id', 'kind', 'name', 'order', 'locked', 'visible', 'muted', 'overlap_policy', 'clip_ids'))
        _check(track['kind'] in ('video', 'overlay', 'audio', 'caption'), 'Unknown track kind')
        for name in ('locked', 'visible', 'muted'):
            _check(type(track[name]) is bool, 'Track flags must be boolean', 'INVALID_GRAPH')
        _check(track['overlap_policy'] == 'exclusive' or
               track['overlap_policy'] == ('mix' if track['kind'] == 'audio' else 'composite') and track['kind'] != 'caption',
               'Track overlap policy differs from renderer')
        cs = sorted((c for c in graph['clips'] if c['track_id'] == track['track_id']), key=lambda c: (c['start_frame'], c['clip_id']))
        _check(track['clip_ids'] == [c['clip_id'] for c in cs], 'Track clip projection differs', 'INVALID_GRAPH')
        if track['overlap_policy'] == 'exclusive':
            intervals = sorted(cs + [c for c in graph['captions'] if c['track_id'] == track['track_id']], key=lambda c: c['start_frame'])
            _check(all(a['end_frame'] <= b['start_frame'] for a, b in zip(intervals, intervals[1:])), 'Exclusive intervals overlap', 'TIMING_INVALID')
    for clip in graph['clips']:
        _keys(clip, ('clip_id', 'track_id', 'subject', 'start_frame', 'end_frame', 'source_mapping', 'linked_group_id', 'enabled', 'effect_ids'), ('audio', 'transform'))
        _range(clip, f['duration_frames'])
        _check(type(clip['enabled']) is bool and not clip['effect_ids'], 'Enabled flag/effect list unsupported')
        track = indices['tracks'].get(clip['track_id'])
        _check(track is not None, 'Clip track is absent', 'INVALID_GRAPH')
        _check(track['kind'] != 'caption', 'Caption tracks use explicit cue records')
        if 'transform' in clip:
            validate(clip['transform'], TRANSFORM)
        subject, mapping = clip['subject'], clip['source_mapping']
        _keys(subject, ('kind', 'id', 'version_id'))
        _keys(mapping, ('domain', 'in_index', 'out_index', 'rate', 'speed'))
        _check(mapping['domain'] == 'frame' and _rate(mapping['speed']) == 1 and mapping['rate'] == f['fps'],
               'Explicit CFR unit-speed frame mapping required; source-tick/conform/retime not supported')
        _number(mapping['in_index'], 0, MAX_FRAMES)
        _check(mapping['out_index'] - mapping['in_index'] == clip['end_frame'] - clip['start_frame'], 'Exact source duration mismatch', 'TIMING_INVALID')
        if subject['kind'] == 'scene':
            s = indices['scenes'].get(subject['id'])
            _check(track['kind'] in ('video', 'overlay') and subject['version_id'] is None and s is not None and mapping['out_index'] <= s['duration_frames'], 'Invalid scene placement', 'TIMING_INVALID')
        else:
            _check(subject['kind'] == 'asset', 'Caption subjects must use manual cue records')
            a = assets.get((subject['id'], subject['version_id']))
            _check(a is not None, 'Clip asset pin absent', 'ASSET_UNRESOLVED')
            _check(a['kind'] in (('audio',) if track['kind'] == 'audio' else ('image', 'video')), 'Clip asset kind differs')
            if a['kind'] != 'image':
                _check(a.get('rate') == f['fps'] and mapping['out_index'] <= a.get('duration_frames', 0), 'Source rate/bounds require conform', 'TIMING_INVALID')
            if a['kind'] == 'audio':
                _check(a.get('sample_rate') == f['sample_rate'], 'Sample-rate conversion recipe is unsupported')
                _check((Fraction(mapping['in_index'] * f['sample_rate']) / fps).denominator == 1, 'Audio source offset requires integral samples')
                _check(all((Fraction(clip[k] * f['sample_rate']) / fps).denominator == 1 for k in ('start_frame', 'end_frame')),
                       'Audio clip edges require integral samples; no implicit fractional-delay conform')
        if 'audio' in clip:
            _check(track['kind'] == 'audio', 'Audio properties require separate explicit audio clip')
            _audio(clip['audio'], clip['end_frame'] - clip['start_frame'])
    for cue in graph['captions']:
        _keys(cue, ('cue_id', 'track_id', 'start_frame', 'end_frame', 'text', 'language', 'style_ref', 'source', 'editorial_revision'))
        _range(cue, f['duration_frames'])
        _check(indices['tracks'].get(cue['track_id'], {}).get('kind') == 'caption', 'Cue track is absent', 'INVALID_GRAPH')
        _check(cue['source'] == {'kind': 'manual'}, 'Only explicitly manual cue provenance is supported; ASR/import must retain their real evidence')
        _check(recipe['caption_style'] is not None and cue['style_ref'] == schema_catalog()['caption']['schema_ref'], 'Manual captions need the exact explicit pinned-font style')
        p = copy.deepcopy(recipe['caption_style']); p['text'] = cue['text']
        validate(p, TEXT); text_check(p)
    # Preserve and byte-pin all production documents without treating them as
    # drawing instructions or silently claiming they were executed.
    for document in graph['production_documents']:
        _check(isinstance(document, dict) and isinstance(document.get('schema_ref'), dict) and
               document.get('sha256') == _public_hash(document.get('value')), 'Production document byte pin differs', 'HASH_MISMATCH')
    return dict(format=copy.deepcopy(f), asset_count=len(assets), frame_evaluator='rgb-pillow-v1',
                unsupported_omitted=False)


def source_bytes(graph, recipe, *, document_dependencies=()):
    """Compile the *whole* canonical graph, not a legacy lossy projection."""
    validate_graph(graph, recipe)
    document_dependencies = list(document_dependencies)
    for dependency in document_dependencies:
        validate(dependency, D['ArtifactRef'])
    value = dict(schema=SOURCE_SCHEMA, graph=copy.deepcopy(graph), graph_sha256=_public_hash(graph),
                 recipe=copy.deepcopy(recipe), schemas=schema_catalog(),
                 document_dependencies=copy.deepcopy(list(document_dependencies)),
                 dependencies=[copy.deepcopy(a['artifact']) for a in graph['asset_refs']] + copy.deepcopy(list(document_dependencies)))
    data = canonical(value)
    _check(len(data) <= MAX_SOURCE_BYTES, 'Source closure exceeds byte bound', 'LIMIT_EXCEEDED')
    return data


def validate_source(value):
    _keys(value, ('schema', 'graph', 'graph_sha256', 'recipe', 'schemas', 'dependencies', 'document_dependencies'))
    _check(value['schema'] == SOURCE_SCHEMA and value['schemas'] == schema_catalog(), 'Source schema closure changed', 'HASH_MISMATCH')
    _check(value['graph_sha256'] == _public_hash(value['graph']) and
           value['dependencies'] == [a['artifact'] for a in value['graph']['asset_refs']] + value['document_dependencies'], 'Graph/dependency closure differs', 'HASH_MISMATCH')
    for dependency in value['document_dependencies']:
        validate(dependency, D['ArtifactRef'])
    return validate_graph(value['graph'], value['recipe'])


def engine_identity():
    """Passive byte identities; parent should include this in snapshot hashes.

    Uses installed package declarations, never imports optional engines or runs a
    version command. Changes to Python/Pillow/libav or any helper invalidate it.
    """
    from ..engine_identity import file_identity, library_identity, executable_identity
    root = Path(__file__).resolve().parents[1]
    return dict(schema='motion/ui-compositor-engine/v1', python=file_identity(sys.executable),
                executables={n: executable_identity(n) for n in ('ffprobe', 'ffmpeg')},
                libraries={n: library_identity(n) for n in ('Pillow', 'av')},
                helpers={n: file_identity(root / n) for n in
                         ('adapters/ui_compositor.py', 'contracts.py', 'adapters/media_probe.py',
                          'adapters/ffmpeg.py', 'adapters/rates.py', 'adapters/limits.py',
                          'adapters/caption_render.py', 'captions.py', 'engine_identity.py')})


def declaration():
    d = ffmpeg.declaration()
    d.update(adapter_id=ADAPTER_ID, label='Canonical UI RGB compositor', implementation_version=VERSION)
    prototype = copy.deepcopy(d['operations'][0])
    d['operations'] = []
    for op in OPERATIONS:
        item = copy.deepcopy(prototype)
        item.update(operation=op, request_schema='motion/v1/ui-compositor/' + op.split('@')[0] + '/request',
                    result_schema='motion/v1/ui-compositor/result', features=list(FEATURES), determinism='unknown')
        item['constraints'].update(media_types=['application/json', 'image/png', 'video/x-matroska', 'audio/wav', 'font/ttf', 'font/otf'],
            codecs=['ffv1', 'pcm_s16le'], max_width_px=3840, max_height_px=3840,
            min_rate={'num': 1, 'den': 1}, max_rate={'num': 60, 'den': 1}, max_duration_frames=MAX_FRAMES,
            color_spaces=['srgb'], alpha_modes=['none'])
        d['operations'].append(item)
    d['dependencies'] = [dict(name=n, kind=k, version_constraint=None, required=True)
                         for n, k in (('Pillow', 'library'), ('av', 'library'),
                                      ('ffprobe', 'executable'), ('ffmpeg', 'executable'))]
    return d


def registration():
    from .media_probe import result_schema
    from ..engine_identity import file_identity
    schemas = {'motion/v1/ui-compositor/result': result_schema()}
    for item in declaration()['operations']:
        schemas[item['request_schema']] = copy.deepcopy(PARAMS)
    outputs = {}
    for op in OPERATIONS:
        outputs[op] = [dict(port='frame' if op == 'ui.frame@1' else 'media', kind='frame' if op == 'ui.frame@1' else 'media',
                            media_type='image/png' if op == 'ui.frame@1' else 'video/x-matroska'),
                       dict(port='source', kind='json', media_type='application/json'),
                       dict(port='report', kind='report', media_type='application/json')]
    # A declaration must remain inspectable when an optional decoder is absent.
    # Full interpreter/library/executable identities are frozen by the native
    # compiler's engine_identity hook before a plan can execute.
    return dict(declaration=declaration(), implementation_sha256=file_identity(__file__)['sha256'], schemas=schemas, outputs=outputs)


def make_plan_builder(recipe, *, resolve_documents=None, mode='composition'):
    """Return UIExecution.bind_graph_renderer-compatible trusted plan builder.

    resolve_documents(runtime, context, pinned_graph) -> list[ArtifactRef] must
    use the host's historical public-document resolver, publish/resolve actual
    native document bytes and return the complete transitive closure. It is
    mandatory when production_documents is nonempty. This module never guesses
    that a public document ID/hash is a native DocumentRef.
    mode='composition' produces FFV1, including one-frame compositions;
    mode='frame' accepts exactly one requested frame and produces PNG.

    REQUIRED HOST INTEGRATION (outside this module's ownership):
      * capabilities.OPERATION and capabilities.PARAMS: add OPERATIONS/PARAMS;
        regenerate closed TaskRequest/PlanNode/job schemas during module setup.
      * plans.PORTS[op] = ('source assets', '', 'assets');
        plans.EXPECTED_PORTS[op] = 'media source report' / 'frame source report'.
      * register registration(), select ADAPTER_ID in committed project bindings,
        install LocalUICompositorAdapter in NativeRuntime.adapter_resolver.
      * route native timing validation to validate_timing below and include
        engine_identity in snapshot revalidation; do not fall through B03 checks.
      * integrate schema_catalog/validate_graph with public UUID/asset ownership
        and saved graph transactions; bind the returned callable on UIExecution.
      * import and ACTUALLY probe/copy assets into this composition's native
        project first. This builder resolves pins, never fabricates stream facts.

    Ancillary publish_json retains current project revision and rehashes every
    input. NativeRuntime.plan performs normal selection/frozen effects/permission
    hashing and returns its real envelope, including real committed blocked plans.
    No job/render/probe runs here. Unsupported partial exports are refused, not
    expanded to a whole-composition render behind the user's back.
    """
    frozen_recipe = copy.deepcopy(recipe)
    validate(frozen_recipe, RECIPE_SCHEMA)
    _check(mode in ('composition', 'frame'), 'Unknown plan-builder output mode', 'INVALID_ARGUMENT')

    def build(runtime, context, pinned_graph, frame_range):
        import uuid
        from ..plans import PORTS, EXPECTED_PORTS
        from ..capabilities import PARAMS as NATIVE_PARAMS
        graph = copy.deepcopy(pinned_graph)
        validate_graph(graph, frozen_recipe)
        _keys(frame_range, ('start_frame', 'end_frame'))
        _range(frame_range, graph['format']['duration_frames'])
        single_frame = frame_range['end_frame'] - frame_range['start_frame'] == 1
        op = 'ui.frame@1' if mode == 'frame' else 'ui.compose@1'
        _check(single_frame if mode == 'frame' else frame_range == dict(start_frame=0, end_frame=graph['format']['duration_frames']),
               'Partial multi-frame export is not implemented; use full composition or one exact frame')
        # Refuse before any publication if the host has not extended its CLOSED
        # native schemas. Registering a declaration alone cannot make tasks legal.
        _check(op in NATIVE_PARAMS and NATIVE_PARAMS[op] == PARAMS and
               PORTS.get(op) == ('source assets', '', 'assets') and op in EXPECTED_PORTS,
               'Native closed task schemas/ports lack UI compositor integration; see make_plan_builder docstring',
               'INTEGRATION_UNAVAILABLE')
        pid = context.get('private_project_id')
        revision = context.get('private_project_revision')
        _check(pid is not None and type(revision) is int, 'Exact native composition binding required', 'INTEGRATION_UNAVAILABLE')
        store = runtime.projects
        fs = store._filesystem()
        pointer = store._pointer(fs, pid)
        _check(pointer['revision'] == revision, 'Selected composition engine head is stale', 'PLAN_STALE')
        version = context.get('version', {})
        _check(all(version.get(k) == graph[k] for k in graph), 'Builder graph differs from trusted saved version', 'PLAN_STALE')
        document_dependencies = []
        if graph['production_documents']:
            _check(callable(resolve_documents), 'Historical public-document resolver is required for this graph', 'INTEGRATION_UNAVAILABLE')
            document_dependencies = resolve_documents(runtime, context, copy.deepcopy(graph))
            _check(isinstance(document_dependencies, list) and bool(document_dependencies),
                   'Resolver must return actual pinned document closure, not a synthetic receipt', 'INTEGRATION_UNAVAILABLE')
        value = json.loads(source_bytes(graph, frozen_recipe, document_dependencies=document_dependencies))
        for dependency in value['dependencies']:
            runtime.artifacts.resolve_at(fs, pointer, dependency)
            _file(runtime.artifact_path(pid, dependency), dependency)
        # The native source port accepts authored scene_source artifacts, not
        # arbitrary JSON. Preserve that typed admission instead of broadening
        # every renderer's source port to accept unrelated JSON documents.
        source_pin = runtime.artifacts.publish_json(pid, value, kind='scene_source', inputs=value['dependencies'])
        # Read exact publication back before returning a plan for it.
        publication = _file(runtime.artifact_path(pid, source_pin), source_pin, MAX_SOURCE_BYTES)
        _check(publication.read_bytes() == canonical(value), 'Published graph bytes differ', 'HASH_MISMATCH')
        _check(store._pointer(fs, pid)['revision'] == revision, 'Project changed while freezing graph closure', 'PLAN_STALE')
        key = context.get('idempotency_key') or context.get('command_id')
        _check(isinstance(key, str), 'Durable UI command UUID required', 'PRECONDITION_REQUIRED')
        request_id = str(uuid.uuid5(uuid.UUID(key), 'ui-compositor-plan:' + digest(dict(source=source_pin, range=frame_range))))
        task = dict(target_key='ui_composition', operation=op, adapter_id=ADAPTER_ID,
                    inputs=dict(source=dict(kind='artifact', artifact=source_pin),
                                assets=[dict(kind='artifact', artifact=p) for p in value['dependencies']]),
                    parameters=dict(frame=frame_range['start_frame'] if mode == 'frame' else None),
                    required_features=['ui.canonical_graph', 'ui.frame_parity'])
        return runtime.plan(dict(action='compile', project_id=pid, expected_revision=revision,
                                 request_id=request_id, requests=[task], targets=['ui_composition']),
                            session_id=context.get('host_session_id'))
    return build


def validate_timing(project_id, request, metadata, documents, *, resolve_source):
    """Native compiler hook; resolve_source(pin) must resolve owned actual JSON.

    Called only for OPERATIONS/ADAPTER_ID by the normal runtime timing router.
    No metadata values are invented and no decoder or renderer is started.
    """
    _check(request.get('operation') in OPERATIONS and request.get('adapter_id') == ADAPTER_ID,
           'Wrong compositor timing route', 'ADAPTER_INCOMPATIBLE')
    _check(set(request['inputs']) == {'source', 'assets'}, 'Exact source and dependency ports required', 'TIMING_INVALID')
    binding = request['inputs']['source']
    _check(binding.get('kind') == 'artifact', 'Compositor requires a previously committed immutable source artifact', 'TIMING_INVALID')
    value = resolve_source(binding['artifact'])
    validate_source(value)
    expected = [dict(kind='artifact', artifact=p) for p in value['dependencies']]
    _check(request['inputs']['assets'] == expected, 'Frozen input closure differs from graph dependency pins', 'TIMING_INVALID')
    validate(request['parameters'], PARAMS)
    index = request['parameters']['frame']
    _check((request['operation'] == 'ui.frame@1') == (index is not None), 'Frame operation/parameter mismatch', 'TIMING_INVALID')
    if index is not None:
        _number(index, 0, value['graph']['format']['duration_frames'] - 1)
    return []


def _file(path, pin, maximum=MAX_ASSET_BYTES):
    path = Path(path)
    _check(not path.is_symlink() and path.is_file() and 0 < path.stat().st_size <= maximum,
           'Unsafe, empty or oversized artifact', 'PATH_UNSAFE')
    _check(ffmpeg.digest(path) == pin['sha256'], 'Pinned bytes changed', 'HASH_MISMATCH')
    return path


class LocalUICompositorAdapter:
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, copy.deepcopy(binding)

    def preflight(self, request):
        self.validate_request(request)
        pid = request['project_id']
        pin = request['inputs']['source']
        path = _file(self.runtime.artifact_path(pid, pin), pin, MAX_SOURCE_BYTES)
        raw = path.read_bytes()
        value = json.loads(raw)
        _check(raw == canonical(value), 'Source artifact must use canonical JSON bytes', 'HASH_MISMATCH')
        facts = validate_source(value)
        _check(request['inputs']['assets'] == value['dependencies'], 'Request dependency ports differ from source closure', 'HASH_MISMATCH')
        for dep in value['dependencies']:
            _file(self.runtime.artifact_path(pid, dep), dep)
        frame = request['parameters']['frame']
        if frame is not None:
            _number(frame, 0, value['graph']['format']['duration_frames'] - 1)
        return dict(valid=True, source_sha256=pin['sha256'], facts=facts, engine=engine_identity())

    def validate_request(self, request):
        _check(request.get('operation') in OPERATIONS and set(request.get('inputs', {})) == {'source', 'assets'}, 'Exact source/assets inputs and UI operation required', 'INVALID_ARGUMENT')
        validate(request['inputs']['source'], D['ArtifactRef'])
        _check(isinstance(request['inputs']['assets'], list), 'Explicit dependency array required', 'INVALID_ARGUMENT')
        for dependency in request['inputs']['assets']:
            validate(dependency, D['ArtifactRef'])
        validate(request['parameters'], PARAMS)
        _check((request['operation'] == 'ui.frame@1') == (request['parameters']['frame'] is not None), 'Frame parameter must match frame/export operation', 'INVALID_ARGUMENT')
        _check(request.get('binding_parameters') is None, 'No arbitrary engine options are accepted', 'INVALID_ARGUMENT')
        expected = self.runtime.registry.binding(ADAPTER_ID, request['operation'], request['parameters'], request.get('binding_parameters'))
        _check(self.binding == expected and request.get('binding') == expected, 'Frozen compositor binding differs', 'ADAPTER_INCOMPATIBLE')
        _check(expected['implementation_sha256'] == digest(engine_identity()),
               'Installed compositor engine bytes changed since binding; recompile required', 'ADAPTER_INCOMPATIBLE')
        effects = self.runtime.registry.effects(ADAPTER_ID)
        _check(request.get('effects', effects) == effects and not set(request.get('required_features', [])) - set(FEATURES), 'Frozen effects/features differ', 'ADAPTER_INCOMPATIBLE')
        return dict(valid=True, effects=effects)

    def execute(self, request, attempt, context=None):
        started = False
        try:
            _check(callable(getattr(context, 'run', None)), 'Owned WorkerContext.run required', 'PERMISSION_DENIED')
            checked = self.preflight(request)
            _check(attempt['node_id'] == request['node_id'] and bool(attempt['authority_evidence_ref']), 'Exact owned attempt authority required', 'PERMISSION_DENIED')
            expected = self.runtime.projects._base(request['project_id']) + '/jobs/' + attempt['job_id'] + '/attempts/' + attempt['attempt_id']
            _check(safe_relative(attempt['output_dir']) == expected, 'Output is not the exact owning attempt', 'PATH_UNSAFE')
            deadline = time.monotonic() + (datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds()
            def run(argv, **kwargs):
                nonlocal started
                remaining = deadline - time.monotonic()
                _check(remaining > 0, 'Compositor deadline elapsed', 'TIMEOUT')
                try:
                    return context.run(argv, timeout=remaining, **kwargs)
                finally:
                    started = getattr(context, 'process', None) is not None
            pin = request['inputs']['source']
            source = _file(self.runtime.artifact_path(request['project_id'], pin), pin, MAX_SOURCE_BYTES)
            value = json.loads(source.read_bytes())
            fs = self.runtime.projects._filesystem(write=True)
            with fs.directory(expected, create=True):
                out = fs.root / expected
                manifest = dict(source=dict(path=str(source.resolve()), pin=pin),
                    assets=[dict(path=str(Path(self.runtime.artifact_path(request['project_id'], a)).resolve()), pin=a) for a in value['dependencies']],
                    operation=request['operation'], frame=request['parameters']['frame'], engine=checked['engine'])
                manifest_path = out / 'compositor-input.json'
                with manifest_path.open('xb') as stream:
                    stream.write(canonical(manifest))
                bootstrap = 'import sys;sys.path.insert(0,sys.argv.pop(1));from studio.adapters.ui_compositor import _worker;_worker()'
                completed = run([sys.executable, '-c', bootstrap, str(Path(__file__).resolve().parents[2]), str(manifest_path.resolve())],
                                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _check(completed.returncode == 0, 'Owned compositor child failed; inspect attempt compositor-error.json', 'OUTPUT_INVALID')
                _check(engine_identity() == checked['engine'], 'Engine changed during render', 'HASH_MISMATCH')
                _file(source, pin, MAX_SOURCE_BYTES)
                for dep in manifest['assets']:
                    _file(dep['path'], dep['pin'])
                report_path = out / 'compositor-report.json'
                _check(not report_path.is_symlink() and 0 < report_path.stat().st_size <= MAX_SOURCE_BYTES, 'Missing/unsafe output report', 'OUTPUT_INVALID')
                report = json.loads(report_path.read_bytes())
                target = out / ('frame.png' if request['operation'] == 'ui.frame@1' else 'composition.mkv')
                source_output = out / 'composition-source.json'
                _check(source_output.read_bytes() == source.read_bytes() and report['source_sha256'] == pin['sha256'] and
                       report['output_sha256'] == ffmpeg.digest(target) and report['engine'] == checked['engine'] and
                       report['operation'] == request['operation'] and report['frame'] == request['parameters']['frame'] and
                       report['verified'] is True, 'Actual output/closure report mismatch', 'OUTPUT_INVALID')
                port = registration()['outputs'][request['operation']][0]
                self.runtime.output_probe.validate_file(target, port, run_process=run)
                outputs = [dict(port=p['port'], relative_path=path.name, media_type=p['media_type'], claimed_sha256=ffmpeg.digest(path))
                           for p, path in zip(registration()['outputs'][request['operation']], (target, source_output, report_path))]
                return ffmpeg._result('succeeded', outputs, started=started)
        except Exception as exc:
            return ffmpeg._result('failed', [], error=exc, started=started)


def _interpolate(points, frame, base):
    """Seekable rational interpolation; key easing applies to outgoing segment."""
    if not points or frame < points[0]['frame']:
        return base
    left = points[0]
    for right in points[1:]:
        if frame < right['frame']:
            if left['easing_ref'] == schema_catalog()['easing.hold']['schema_ref']:
                return left['value']
            return Fraction(left['value']) + Fraction(frame - left['frame'], right['frame'] - left['frame']) * (right['value'] - left['value'])
        left = right
    return left['value']


def _rounded(value):
    value = Fraction(value)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


class Evaluator:
    """Deterministic random-access picture evaluator, also used by export.

    Source video advances one decoder per source; backward seeks restart from
    its beginning. A one-frame cache bounds memory and arbitrary seek results
    do not depend on preceding evaluations. CFR PTS may differ only by the
    nearest representable source time-base tick (e.g. Matroska milliseconds).
    """
    def __init__(self, source, paths):
        from PIL import Image
        self.Image = Image
        self.source, self.graph = source, source['graph']
        self.f = self.graph['format']
        self.size = self.f['width'], self.f['height']
        self.assets = {(a['asset_id'], a['asset_version_id']): a for a in self.graph['asset_refs']}
        self.paths, self.cache, self.fonts = paths, {}, {}
        self.decoders = {}
        self.coverage = {}
        self.layers = {l['layer_id']: l for l in self.graph['layers']}
        self.scenes = {s['scene_id']: s for s in self.graph['scenes']}

    def path(self, asset):
        return self.paths[asset['artifact']['artifact_id']]

    def picture(self, asset, index):
        import av
        key = asset['artifact']['artifact_id']
        cached = self.cache.get(key)
        if cached is not None and cached[0] == index:
            return cached[1].copy()
        if asset['kind'] == 'image':
            with self.Image.open(self.path(asset)) as image:
                _check(not image.info.get('icc_profile') and not image.info.get('exif') and getattr(image, 'n_frames', 1) == 1,
                       'ICC/EXIF/animated images require explicit conform')
                _check(image.width * image.height <= MAX_PIXELS and image.mode in ('RGB', 'RGBA'), 'Only bounded RGB/RGBA source images are supported')
                result = image.convert('RGBA')
        else:
            result = None
            decoder = self.decoders.get(key)
            if decoder is None or decoder['index'] >= index:
                if decoder is not None:
                    decoder['container'].close()
                container = av.open(str(self.path(asset)), format='matroska', options={'protocol_whitelist': 'file'})
                # Store immediately so later validation failures still close
                # the native decoder at the evaluator's owning finally block.
                self.decoders[key] = dict(container=container, frames=iter(()), index=-1)
                _check(len(container.streams.video) == 1, 'Select/conform one source video stream')
                stream = container.streams.video[0]
                _check(stream.codec_context.name == 'ffv1', 'This pinned RGB video route requires FFV1 Matroska source')
                _check(stream.average_rate == _rate(self.f['fps']), 'Actual source CFR rate differs', 'TIMING_INVALID')
                _check(not stream.metadata.get('rotate') and stream.sample_aspect_ratio in (None, Fraction(1)), 'Rotation/SAR require explicit conform')
                decoder = dict(container=container, frames=iter(container.decode(stream)), index=-1)
                self.decoders[key] = decoder
            for frame in decoder['frames']:
                decoder['index'] += 1
                i = decoder['index']
                _check(frame.width * frame.height <= MAX_PIXELS and frame.format.name in ('rgb24', 'rgba', 'bgr24', 'bgr0', 'rgb0', 'bgra'), 'YUV/HDR source conversion is not this RGB route')
                _check(not list(frame.side_data), 'Video side-data/color/display transforms require explicit conform')
                _check(frame.pts is not None and frame.time_base is not None and
                       abs(Fraction(frame.pts) * frame.time_base - Fraction(i) / _rate(self.f['fps'])) <= frame.time_base / 2,
                       'Source must have zero-origin CFR timestamps within half a source tick', 'TIMING_INVALID')
                if i == index:
                    result = frame.to_image().convert('RGBA'); break
            _check(result is not None, 'Requested source frame does not exist', 'OUTPUT_INVALID')
        self.cache[key] = index, result.copy()
        return result

    def text(self, p):
        from PIL import ImageDraw, ImageFont
        from .caption_render import glyphs
        font_asset = next(a for a in self.assets.values() if a['kind'] == 'font' and a['asset_id'] == p['font_binding_id'])
        key = font_asset['artifact']['sha256'], p['size']['num'] // p['size']['den']
        if key[0] not in self.coverage:
            self.coverage[key[0]] = glyphs(self.path(font_asset))
        _check({ord(c) for c in p['text'] if not c.isspace()} <= self.coverage[key[0]],
               'Pinned font lacks authored glyphs; no fallback/tofu substitution')
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(str(self.path(font_asset)), key[1], layout_engine=ImageFont.Layout.BASIC)
        font = self.fonts[key]
        image = self.Image.new('RGBA', (p['transform']['width'], p['transform']['height']), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        box = p['safe_box']
        bounds = draw.multiline_textbbox((0, 0), p['text'], font=font, spacing=0, align=p['alignment'])
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        _check(width <= box['width'] and height <= box['height'], 'Authored text exceeds explicit safe box', 'OUTPUT_INVALID')
        x = box['x'] + (0 if p['alignment'] == 'left' else (box['width'] - width) // (2 if p['alignment'] == 'center' else 1))
        draw.multiline_text((x - bounds[0], box['y'] - bounds[1]), p['text'], font=font,
                            fill=tuple(p['color']), spacing=0, align=p['alignment'])
        return image

    def close(self):
        for decoder in self.decoders.values():
            decoder['container'].close()

    def transformed(self, picture, transform):
        crop = transform['crop']
        if crop is not None:
            _check(crop['x'] + crop['width'] <= picture.width and crop['y'] + crop['height'] <= picture.height,
                   'Explicit source crop exceeds actual raster', 'OUTPUT_INVALID')
            picture = picture.crop((crop['x'], crop['y'], crop['x'] + crop['width'], crop['y'] + crop['height']))
        _check(transform['width'] * transform['height'] <= MAX_PIXELS, 'Animated raster exceeds pixel bound', 'LIMIT_EXCEEDED')
        picture = picture.resize((transform['width'], transform['height']), self.Image.Resampling.LANCZOS)
        opacity = transform['opacity_milli']
        picture.putalpha(picture.getchannel('A').point([i * opacity // 1000 for i in range(256)]))
        if transform['rotation_mdeg']:
            picture = picture.rotate(-transform['rotation_mdeg'] / 1000, resample=self.Image.Resampling.BICUBIC, expand=True)
        # x/y locates the unrotated top-left; rotation is about its center.
        x = transform['x'] + (transform['width'] - picture.width) // 2
        y = transform['y'] + (transform['height'] - picture.height) // 2
        result = self.Image.new('RGBA', self.size, (0, 0, 0, 0))
        result.alpha_composite(picture, (x, y))
        return result

    def scene(self, scene, frame):
        from PIL import ImageDraw
        result = self.Image.new('RGBA', self.size, tuple(scene['background'] or (0, 0, 0, 0)))
        for identity in scene['layer_ids']:
            layer = self.layers[identity]
            if not layer['start_frame'] <= frame < layer['end_frame']:
                continue
            p = layer['parameters']
            transform = copy.deepcopy(p['transform'])
            for prop in ('x', 'y', 'width', 'height', 'rotation_mdeg', 'opacity_milli'):
                points = sorted((k for k in layer['keyframes'] if k['property'] == prop), key=lambda k: k['frame'])
                transform[prop] = _rounded(_interpolate(points, frame, transform[prop]))
            if layer['type'] in ('image', 'media'):
                asset = self.assets[(p['asset']['asset_id'], p['asset']['asset_version_id'])]
                index = 0 if layer['type'] == 'image' else p['source_in'] + frame - layer['start_frame']
                picture = self.picture(asset, index)
            elif layer['type'] == 'text':
                picture = self.text(p)
            else:
                picture = self.Image.new('RGBA', (p['transform']['width'], p['transform']['height']), (0, 0, 0, 0))
                draw = ImageDraw.Draw(picture)
                shape = draw.rectangle if p['shape'] == 'rectangle' else draw.ellipse
                shape((0, 0, picture.width - 1, picture.height - 1), fill=tuple(p['color']))
            result = self.Image.alpha_composite(result, self.transformed(picture, transform))
        return result

    def frame(self, frame):
        _number(frame, 0, self.f['duration_frames'] - 1)
        recipe = self.source['recipe']
        result = self.Image.new('RGBA', self.size, tuple(recipe['background']))
        for track in sorted(self.graph['tracks'], key=lambda t: t['order']):
            if not track['visible'] or track['kind'] == 'audio':
                continue
            for clip in sorted((c for c in self.graph['clips'] if c['track_id'] == track['track_id']), key=lambda c: (c['start_frame'], c['clip_id'])):
                if not clip['enabled'] or not clip['start_frame'] <= frame < clip['end_frame']:
                    continue
                index = frame - clip['start_frame'] + clip['source_mapping']['in_index']
                subject = clip['subject']
                if subject['kind'] == 'scene':
                    picture = self.scene(self.scenes[subject['id']], index)
                else:
                    asset = self.assets[(subject['id'], subject['version_id'])]
                    picture = self.picture(asset, 0 if asset['kind'] == 'image' else index)
                transform = clip.get('transform')
                if transform is None:
                    _check(picture.size == self.size, 'Picture canvas differs: explicit clip transform required')
                else:
                    picture = self.transformed(picture, transform)
                result = self.Image.alpha_composite(result, picture)
            for cue in sorted((c for c in self.graph['captions'] if c['track_id'] == track['track_id']), key=lambda c: (c['start_frame'], c['cue_id'])):
                if cue['start_frame'] <= frame < cue['end_frame']:
                    p = copy.deepcopy(recipe['caption_style']); p['text'] = cue['text']
                    result = self.Image.alpha_composite(result, self.transformed(self.text(p), p['transform']))
        # Opaque recipe background is required by execution, so conversion never
        # silently discards authored alpha. PNG and FFV1 share these RGB bytes.
        return result.convert('RGB')


def _gain(audio, frame, duration):
    if audio['muted']:
        return 0.0, 0.0
    points = audio['envelope']
    db = Fraction(audio['gain_db_milli'])
    if points:
        envelope = Fraction(0)
        if frame >= points[0]['frame']:
            left = points[0]
            envelope = Fraction(left['gain_db_milli'])
            for right in points[1:]:
                if frame < right['frame']:
                    envelope = Fraction(left['gain_db_milli']) + (frame - left['frame']) / (right['frame'] - left['frame']) * (right['gain_db_milli'] - left['gain_db_milli'])
                    break
                left = right
                envelope = Fraction(left['gain_db_milli'])
        db += envelope
    gain = 10 ** (float(db) / 20000)
    for fade in audio['fades']:
        a, b = fade['start_frame'], fade['end_frame']
        phase = max(Fraction(0), min(Fraction(1), (frame - a) / (b - a)))
        gain *= float(phase if a == 0 else 1 - phase)
    pan = audio['pan_milli'] / 1000
    # Explicit stereo balance law: center unity; never implicit mono pan law.
    return gain * (1 - max(0, pan)), gain * (1 + min(0, pan))


class AudioMixer:
    """PCM sample-exact, block bounded stereo summation; no resampling/dither."""
    def __init__(self, evaluator):
        import wave
        self.evaluator = evaluator
        self.f = evaluator.f
        self.fps = _rate(self.f['fps'])
        self.sources = {}
        self.clips = []
        self.clipped_samples = 0
        tracks = {t['track_id']: t for t in evaluator.graph['tracks']}
        try:
            for clip in evaluator.graph['clips']:
                track = tracks[clip['track_id']]
                if track['kind'] != 'audio' or track['muted'] or not clip['enabled']:
                    continue
                subject = clip['subject']
                a = evaluator.assets[(subject['id'], subject['version_id'])]
                identity = a['artifact']['artifact_id']
                if identity not in self.sources:
                    stream = wave.open(str(evaluator.path(a)), 'rb')
                    self.sources[identity] = stream
                    _check(stream.getcomptype() == 'NONE' and stream.getsampwidth() == 2 and
                           stream.getnchannels() in (1, 2) and stream.getframerate() == self.f['sample_rate'],
                           'Audio requires mono/stereo PCM16 WAV at exact output sample rate')
                stream = self.sources[identity]
                offset = int(Fraction(clip['source_mapping']['in_index'] * self.f['sample_rate']) / self.fps)
                needed = self.boundary(clip['end_frame']) - self.boundary(clip['start_frame'])
                _check(offset + needed <= stream.getnframes(), 'Audio mapping exceeds actual sample bounds', 'OUTPUT_INVALID')
                self.clips.append((clip, identity, offset))
        except BaseException:
            self.close(); raise

    def boundary(self, frame):
        return math.ceil(Fraction(frame * self.f['sample_rate']) / self.fps)

    def block(self, start, count):
        mixed = [0.0] * (count * 2)
        for clip, identity, offset in self.clips:
            a = max(start, self.boundary(clip['start_frame']))
            b = min(start + count, self.boundary(clip['end_frame']))
            if a >= b:
                continue
            stream = self.sources[identity]
            stream.setpos(offset + a - self.boundary(clip['start_frame']))
            samples = array.array('h'); samples.frombytes(stream.readframes(b - a))
            if sys.byteorder != 'little':
                samples.byteswap()
            channels = stream.getnchannels()
            _check(len(samples) == (b - a) * channels, 'Short PCM read', 'OUTPUT_INVALID')
            audio = clip.get('audio', default_audio())
            for n in range(b - a):
                # Automation is evaluated at exact sample time in clip-local
                # frames, not quantized to a preceding picture frame.
                frame = Fraction((a + n) * self.fps, self.f['sample_rate']) - clip['start_frame']
                left, right = _gain(audio, frame, clip['end_frame'] - clip['start_frame'])
                dest = (a + n - start) * 2
                mixed[dest] += samples[n * channels] * left
                mixed[dest + 1] += samples[n * channels + channels - 1] * right
        output = array.array('h')
        for value in mixed:
            value = round(value)
            if not -32768 <= value <= 32767:
                self.clipped_samples += 1
            output.append(max(-32768, min(32767, value)))
        if sys.byteorder != 'little':
            output.byteswap()
        return output.tobytes()

    def close(self):
        for stream in self.sources.values():
            stream.close()


def _validate_decoded_pcm(frame, sample_rate):
    # Matroska PCM can retain two interleaved channels without a channel mask.
    # This is the implicit L/R output we authored, not permission to reinterpret
    # another named layout. Full ordered PCM hashes below still prove parity.
    channels = tuple(channel.name for channel in frame.layout.channels)
    stereo = (frame.layout.name == 'stereo' and channels == ('FL', 'FR'))
    implicit = (frame.layout.name == '2 channels' and channels == ('NONE', 'NONE'))
    _check(frame.format.name == 's16' and (stereo or implicit) and
           frame.sample_rate == sample_rate, 'Decoded audio format differs', 'OUTPUT_INVALID')


def _render(source, paths, operation, frame_index, out):
    """Private bounded-child implementation. Actual round-trip checks required."""
    import av
    from PIL import Image
    validate_source(source)
    _check(source['recipe']['background'][3] == 255, 'Output recipe background must be opaque RGB')
    ev = Evaluator(source, paths)
    f = ev.f
    expected_video, expected_audio = hashlib.sha256(), hashlib.sha256()
    decoded_frames = decoded_samples = 0
    mixer = AudioMixer(ev)
    try:
        if operation == 'ui.frame@1':
            target = out / 'frame.png'
            image = ev.frame(frame_index)
            expected_video.update(image.tobytes())
            image.save(target, format='PNG')
            with Image.open(target) as observed:
                _check(observed.size == ev.size and observed.mode == 'RGB' and observed.tobytes() == image.tobytes(), 'PNG round-trip mismatch', 'OUTPUT_INVALID')
            decoded_frames = 1
        else:
            target = out / 'composition.mkv'
            fps = _rate(f['fps'])
            sample_count = int(Fraction(f['duration_frames'] * f['sample_rate']) / fps)
            with av.open(str(target), 'w', format='matroska') as container:
                video = container.add_stream('ffv1', rate=fps)
                video.width, video.height = ev.size
                video.pix_fmt = 'bgr0'
                video.codec_context.thread_count = 1
                video.time_base = 1 / fps
                audio = None
                if mixer.clips:
                    audio = container.add_stream('pcm_s16le', rate=f['sample_rate'])
                    audio.layout = 'stereo'; audio.time_base = Fraction(1, f['sample_rate'])
                sample_position = 0
                for index in range(f['duration_frames']):
                    image = ev.frame(index); expected_video.update(image.tobytes())
                    vf = av.VideoFrame.from_image(image)
                    vf.pts = index; vf.time_base = 1 / fps
                    for packet in video.encode(vf):
                        container.mux(packet)
                    if audio is not None:
                        end = min(sample_count, mixer.boundary(index + 1))
                        while sample_position < end:
                            count = min(4096, end - sample_position)
                            data = mixer.block(sample_position, count); expected_audio.update(data)
                            af = av.AudioFrame(format='s16', layout='stereo', samples=count)
                            af.planes[0].update(data); af.sample_rate = f['sample_rate']
                            af.pts = sample_position; af.time_base = Fraction(1, f['sample_rate'])
                            for packet in audio.encode(af):
                                container.mux(packet)
                            sample_position += count
                for packet in video.encode():
                    container.mux(packet)
                if audio is not None:
                    for packet in audio.encode():
                        container.mux(packet)
            actual_video = hashlib.sha256()
            # Matroska commonly quantizes PTS to milliseconds; compare with the
            # nearest encoded time-base tick, never demand impossible exact PTS.
            with av.open(str(target)) as decoded:
                _check(len(decoded.streams.video) == 1 and len(decoded.streams.audio) == bool(mixer.clips), 'Unexpected output streams', 'OUTPUT_INVALID')
                for vf in decoded.decode(video=0):
                    _check((vf.width, vf.height) == ev.size and vf.pts is not None and
                           abs(Fraction(vf.pts) * vf.time_base - Fraction(decoded_frames) / fps) <= vf.time_base / 2,
                           'Decoded output frame shape/timestamp mismatch', 'OUTPUT_INVALID')
                    actual_video.update(vf.to_image().convert('RGB').tobytes()); decoded_frames += 1
            _check(decoded_frames == f['duration_frames'] and actual_video.digest() == expected_video.digest(), 'Full output frame/pixel verification failed', 'OUTPUT_INVALID')
            if mixer.clips:
                actual_audio = hashlib.sha256()
                with av.open(str(target)) as decoded:
                    for af in decoded.decode(audio=0):
                        _validate_decoded_pcm(af, f['sample_rate'])
                        _check(af.pts is not None and abs(Fraction(af.pts) * af.time_base - Fraction(decoded_samples, f['sample_rate'])) <= af.time_base / 2,
                               'Decoded audio timestamps differ', 'OUTPUT_INVALID')
                        actual_audio.update(bytes(af.planes[0])[:af.samples * 4]); decoded_samples += af.samples
                _check(decoded_samples == sample_count and actual_audio.digest() == expected_audio.digest(), 'Full output PCM sample verification failed', 'OUTPUT_INVALID')
        return dict(verified=True, output_sha256=ffmpeg.digest(target), decoded_frames=decoded_frames,
                    decoded_samples=decoded_samples, rgb_sha256='sha256:' + expected_video.hexdigest(),
                    pcm_sha256=('sha256:' + expected_audio.hexdigest()) if decoded_samples else None,
                    clipped_channel_samples=mixer.clipped_samples, audio_recipe='pcm16-stereo-balance-linear-amplitude-fades-hard-limit-v1',
                    color_recipe=source['recipe']['color'], caption_provenance='manual-only',
                    frame_evaluator='rgb-pillow-v1', quality='full-resolution-lossless',
                    verification='full-decoded-pixels-and-PCM', production_documents_executed=False)
    finally:
        mixer.close()
        ev.close()


def _worker():
    """Only invoked by the registered owned attempt, never a public code RPC."""
    _check(len(sys.argv) == 2, 'Private compositor child needs exact manifest path', 'INVALID_ARGUMENT')
    manifest_path = Path(sys.argv[1])
    out = manifest_path.parent
    try:
        _check(not manifest_path.is_symlink() and 0 < manifest_path.stat().st_size <= MAX_SOURCE_BYTES, 'Unsafe manifest', 'PATH_UNSAFE')
        manifest = json.loads(manifest_path.read_bytes())
        _keys(manifest, ('source', 'assets', 'operation', 'frame', 'engine'))
        _check(manifest['operation'] in OPERATIONS and (manifest['operation'] == 'ui.frame@1') == (manifest['frame'] is not None), 'Unknown worker operation')
        _check(engine_identity() == manifest['engine'], 'Child engine identity differs', 'HASH_MISMATCH')
        source_path = _file(manifest['source']['path'], manifest['source']['pin'], MAX_SOURCE_BYTES)
        raw = source_path.read_bytes(); value = json.loads(raw)
        validate_source(value)
        _check(raw == canonical(value), 'Noncanonical source bytes', 'HASH_MISMATCH')
        _check([a['pin'] for a in manifest['assets']] == value['dependencies'], 'Manifest dependency closure differs', 'HASH_MISMATCH')
        paths = {}
        for dep in manifest['assets']:
            path = _file(dep['path'], dep['pin'])
            identity = dep['pin']['artifact_id']
            _check(identity not in paths or paths[identity] == path, 'Artifact identity resolves inconsistently', 'HASH_MISMATCH')
            paths[identity] = path
        # Exclusive creation makes retries reconcile rather than overwrite.
        for name in ('composition.mkv', 'frame.png', 'composition-source.json', 'compositor-report.json'):
            _check(not (out / name).exists() and not (out / name).is_symlink(), 'Attempt output already exists', 'PATH_UNSAFE')
        report = _render(value, paths, manifest['operation'], manifest['frame'], out)
        for dep in manifest['assets']:
            _file(dep['path'], dep['pin'])
        _file(source_path, manifest['source']['pin'], MAX_SOURCE_BYTES)
        _check(engine_identity() == manifest['engine'], 'Engine changed during child execution', 'HASH_MISMATCH')
        with (out / 'composition-source.json').open('xb') as stream:
            stream.write(raw)
        report.update(source_sha256=manifest['source']['pin']['sha256'], graph_sha256=value['graph_sha256'],
                      dependencies=value['dependencies'], schemas=value['schemas'], recipe=value['recipe'],
                      engine=manifest['engine'], operation=manifest['operation'], frame=manifest['frame'])
        with (out / 'compositor-report.json').open('xb') as stream:
            stream.write(canonical(report))
    except BaseException as exc:
        try:
            with (out / 'compositor-error.json').open('xb') as stream:
                stream.write(canonical(dict(code=getattr(exc, 'code', 'OUTPUT_INVALID'), message=(type(exc).__name__ + ': ' + str(exc))[:4096])))
        finally:
            raise SystemExit(1) from None
