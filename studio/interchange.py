"""Editable OTIO interchange over the authoritative project timeline.

Registration is dependency-free. Only execution loads the optional OTIO core
JSON adapter; no media is opened by OTIO and no adapter/plugin is auto-installed.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
from fractions import Fraction
from typing import Any, NoReturn

from .contracts import (ContractError, MAX_INT, UUID_PATTERN, arr, digest,
                        enum, ident, integer, obj, ref, string, validate)
from .editorial import checked_update, document_pin
from .timeline import rate_fraction, validate_timeline

BUNDLE_SCHEMA = 'motion/v1/otio-interchange'
MAX_BYTES = 16 * 1024 * 1024


def branches():
    """Closed motion_plan branches; the parent owns dispatch registration."""
    span = obj({'start_index': integer(-MAX_INT), 'duration': integer(1), 'rate': ref('Rate')})
    binding = obj({'reference': string(minimum=1), 'artifact': ref('ArtifactRef'),
                   'available_range': span})
    common = {'project_id': ident('prj'), 'expected_revision': integer(1),
              'request_id': string(UUID_PATTERN), 'adapter': enum('otio_json'),
              'media_bindings': arr(binding, unique=True)}
    return [obj({'action': {'const': 'interchange_import'}, **common,
                 'source_artifact': ref('ArtifactRef')}),
            obj({'action': {'const': 'interchange_export'}, **common,
                 'source_timeline': ref('DocumentRef'), 'source_bundle': ref('ArtifactRef')},
                optional=['source_bundle'])]


def fail(feature, message, *, code='UNSUPPORTED_FEATURE') -> NoReturn:
    raise ContractError(code, message, details={'feature': feature})


def _engine():
    try:
        return importlib.import_module('opentimelineio')
    except ImportError as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE',
            'Editable interchange requires optional OpenTimelineIO installed by the operator; no install was attempted.') from exc


def _parse(text, otio):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        fail('document_size', 'OTIO text must be UTF-8 and at most 16 MiB.', code='INVALID_ARGUMENT')
    try:
        raw = json.loads(text)
        _features(raw)
        value = otio.adapters.read_from_string(text, adapter_name='otio_json')
        if not isinstance(value, otio.schema.Timeline):
            fail('root', 'Only an OTIO Timeline root is supported.')
        normalized = otio.adapters.write_to_string(value, adapter_name='otio_json')
        document = json.loads(normalized)
        _features(document)
        return value, document, normalized
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError('INVALID_ARGUMENT', 'OTIO core could not parse/serialize this timeline.',
                            details={'reason': str(exc)[:1000]}) from exc


def _features(node, depth=0):
    """Fail before the engine can discard semantic constructs it cannot retain."""
    if depth > 32:
        fail('nesting', 'OTIO object nesting exceeds the supported document depth.')
    if isinstance(node, list):
        for child in node:
            _features(child, depth + 1)
    elif isinstance(node, dict):
        schema = node.get('OTIO_SCHEMA', '').split('.')[0]
        if schema == 'Transition':
            fail('transition', 'Transitions require explicit conform; interchange does not flatten them.')
        if schema in ('Effect', 'TimeEffect', 'LinearTimeWarp', 'FreezeFrame') or node.get('effects'):
            fail('effect_or_retime', 'Effects, speed changes and freeze frames are unsupported.')
        if node.get('enabled') is False:
            fail('disabled_item', 'Disabled/muted OTIO items cannot be silently enabled.')
        # Metadata is opaque, retained in the original document, not interpreted
        # as executable OTIO structure or canonical source provenance.
        for key, child in node.items():
            if key not in ('metadata', 'markers'):
                _features(child, depth + 1)


def _read(runtime, fs, pid, pin):
    record = runtime.artifacts.resolve(pid, pin)
    if record['size_bytes'] > MAX_BYTES:
        fail('document_size', 'Interchange input exceeds 16 MiB.', code='INVALID_ARGUMENT')
    with runtime.artifacts.open_record(fs, record) as stream:
        payload = stream.read(MAX_BYTES + 1)
    try:
        return payload.decode('utf-8')
    except UnicodeError as exc:
        raise ContractError('INVALID_ARGUMENT', 'Interchange input must contain UTF-8 JSON.') from exc


def _source_text(runtime, fs, pid, pin):
    text = _read(runtime, fs, pid, pin)
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ContractError('INVALID_ARGUMENT', 'Source artifact is not JSON.') from exc
    if isinstance(value, dict) and value.get('schema') == BUNDLE_SCHEMA:
        if not isinstance(value.get('otio_text'), str):
            fail('bundle', 'Interchange bundle lacks its real OTIO text.', code='INVALID_ARGUMENT')
        text = value['otio_text']
        if value.get('otio_sha256') != _text_hash(text):
            fail('bundle', 'Retained OTIO text hash differs.', code='HASH_MISMATCH')
    return text


def _text_hash(text):
    return 'sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest()


def _rational(rate):
    return {'num': rate.numerator, 'den': rate.denominator}


def _number(value, label):
    if type(value) not in (int, float) or abs(value) > MAX_INT or not math.isfinite(value):
        fail('rational_timing', label + ' must be a finite OTIO number.', code='TIMING_INVALID')
    return Fraction(str(value))


def _time(value, bindings, project_rate):
    if not isinstance(value, dict) or value.get('OTIO_SCHEMA') != 'RationalTime.1':
        fail('rational_timing', 'Expected an explicit OTIO RationalTime.', code='TIMING_INVALID')
    count = _number(value.get('value'), 'RationalTime value')
    if count.denominator != 1:
        fail('subframe', 'Subframe time values are not supported.', code='TIMING_INVALID')
    encoded = value.get('rate')
    numeric = _number(encoded, 'RationalTime rate')
    if numeric <= 0:
        fail('rational_timing', 'Time rates must be positive.', code='TIMING_INVALID')
    # OTIO stores rate as double. An explicitly pinned rational rate disambiguates
    # its serialized double, without guessing 23.98/29.97 or rounding frames.
    candidates = {project_rate, *(rate_fraction(b['available_range']['rate']) for b in bindings)}
    matches = [rate for rate in candidates if float(rate) == encoded]
    if len(matches) > 1:
        fail('rational_timing', 'Ambiguous double rate matches multiple explicit rational pins.', code='TIMING_INVALID')
    rate = matches[0] if matches else numeric
    return int(count), rate


def _range(value, bindings, fps):
    if not isinstance(value, dict) or value.get('OTIO_SCHEMA') != 'TimeRange.1':
        fail('source_range', 'Every clip/gap needs an explicit OTIO TimeRange.', code='TIMING_INVALID')
    start, start_rate = _time(value.get('start_time'), bindings, fps)
    length, rate = _time(value.get('duration'), bindings, fps)
    if length <= 0:
        fail('source_range', 'Ranges must have a positive duration.', code='TIMING_INVALID')
    return Fraction(start, start_rate), Fraction(length, rate)


def _frame(seconds, fps):
    result = seconds * fps
    if result.denominator != 1 or not 0 <= result <= MAX_INT:
        fail('subframe', 'Timing is not exactly representable on the fixed project frame grid.', code='TIMING_INVALID')
    return int(result)


def _bindings(runtime, pid, rows):
    found = {}
    for row in rows:
        reference = row['reference']
        if reference in found:
            fail('media_binding', 'Each media reference must have exactly one explicit pin.', code='INVALID_ARGUMENT')
        record = runtime.artifacts.resolve(pid, row['artifact'])
        media_kind = record['kind']
        if media_kind == 'media':
            # Core video assets/outputs use kind=media, not kind=video.
            # This is declared MIME compatibility, never a decode claim.
            media_kind = {'video': 'video', 'audio': 'audio'}.get(record['media_type'].split('/', 1)[0])
        if media_kind not in ('video', 'audio', 'image'):
            fail('media_kind', 'Media bindings must pin video, audio or image artifacts.', code='INVALID_ARGUMENT')
        rate_fraction(row['available_range']['rate'])
        found[reference] = dict(copy.deepcopy(row), _artifact_kind=media_kind)
    return found


def _track_media(kind, binding):
    if ((kind == 'video' and binding['_artifact_kind'] not in ('video', 'image')) or
            (kind == 'audio' and binding['_artifact_kind'] not in ('video', 'audio'))):
        fail('media_kind', 'Bound artifact kind is incompatible with its audio/video track.', code='INVALID_GRAPH')


def _media(clip):
    references = clip.get('media_references')
    if references is not None:
        if not isinstance(references, dict) or len(references) != 1:
            fail('alternate_media', 'Alternate/multiple media references are unsupported.')
        key = clip.get('active_media_reference_key')
        if key not in references:
            fail('media_reference', 'Active media reference is missing.', code='INVALID_ARGUMENT')
        media = references[key]
    else:
        media = clip.get('media_reference')
    if not isinstance(media, dict) or media.get('OTIO_SCHEMA', '').split('.')[0] != 'ExternalReference':
        fail('media_reference', 'Only explicit ExternalReference media is supported; not generators, sequences or missing media.')
    return media


def _available(binding):
    span = binding['available_range']
    rate = rate_fraction(span['rate'])
    return Fraction(span['start_index'], rate), Fraction(span['duration'], rate)


def _decode(document, bindings, settings):
    fps = rate_fraction(settings['rate'])
    rows = list(bindings.values())
    stack = document.get('tracks')
    if not isinstance(stack, dict) or stack.get('OTIO_SCHEMA', '').split('.')[0] != 'Stack':
        fail('tracks', 'Timeline tracks must be a single root Stack.')
    if stack.get('source_range') is not None:
        fail('stack_trim', 'Root stack trims cannot be flattened.')
    tracks, used, duration, source_map = [], set(), 0, []
    for ti, track in enumerate(stack.get('children', [])):
        if track.get('OTIO_SCHEMA', '').split('.')[0] != 'Track':
            fail('nesting', 'Nested stacks/tracks are unsupported.')
        if track.get('source_range') is not None:
            fail('track_trim', 'Trimmed tracks require explicit conform.')
        kind = {'Video': 'video', 'Audio': 'audio'}.get(track.get('kind'))
        if kind is None:
            fail('track_kind', 'Only Video and Audio tracks are supported.')
        target: dict[str, Any] = dict(track_id='track_' + str(ti), kind=kind, items=[])
        cursor = 0
        for ci, child in enumerate(track.get('children', [])):
            schema = child.get('OTIO_SCHEMA', '').split('.')[0]
            if schema not in ('Gap', 'Clip'):
                fail('nesting', 'Tracks may contain only clips and gaps; nesting/transitions are unsupported.')
            start, length = _range(child.get('source_range'), rows, fps)
            frames = _frame(length, fps)
            if schema == 'Gap':
                if start != 0:
                    fail('gap', 'Gap source ranges must start at zero.', code='TIMING_INVALID')
                cursor += frames
                continue
            media = _media(child)
            reference = media.get('target_url')
            if reference not in bindings:
                fail('media_binding', 'Every target_url needs an explicit artifact remap; no URL is acquired.', code='ASSETS_UNRESOLVED')
            binding = bindings[reference]
            _track_media(kind, binding)
            available = _range(media.get('available_range'), rows, fps)
            if available != _available(binding):
                fail('source_bounds', 'OTIO available range differs from its explicitly pinned binding.', code='TIMING_INVALID')
            offset = start - available[0]
            if offset < 0 or offset + length > available[1]:
                fail('source_bounds', 'Clip source range exceeds its bound available range.', code='TIMING_INVALID')
            point = dict(domain='frame', index=_frame(offset, fps), rate=settings['rate'],
                         origin='source', source_artifact=binding['artifact'])
            item_id = 'item_' + str(ti) + '_' + str(ci)
            target['items'].append(dict(item_id=item_id, start_frame=cursor, end_frame=cursor + frames,
                subject=dict(kind='artifact', artifact=binding['artifact']), source_in=point))
            source_map.append(dict(item_id=item_id, reference=reference, artifact=binding['artifact'],
                source_start_seconds=_rational(start), source_duration_seconds=_rational(length),
                available_start_seconds=_rational(available[0]), available_duration_seconds=_rational(available[1])))
            used.add(reference)
            cursor += frames
        duration = max(duration, cursor)
        tracks.append(target)
    if set(bindings) != used:
        fail('media_binding', 'Unused media bindings are rejected; scope pins to the actual document.', code='INVALID_ARGUMENT')
    timeline = dict(duration_frames=duration, tracks=tracks)
    validate_timeline(timeline, settings['rate'], settings['sample_rate'])
    return timeline, source_map


def _rt(index, rate):
    return {'OTIO_SCHEMA': 'RationalTime.1', 'value': index, 'rate': float(rate)}


def _tr(start, duration, rate):
    return {'OTIO_SCHEMA': 'TimeRange.1', 'start_time': _rt(start, rate), 'duration': _rt(duration, rate)}


def _metadata(node):
    value = node.get('metadata', {})
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _encode(timeline, bindings, settings, template=None):
    fps = rate_fraction(settings['rate'])
    rows = list(bindings.values())
    by_pin = {}
    for row in rows:
        key = digest(row['artifact'])
        if key in by_pin:
            fail('media_binding', 'Export requires one unambiguous reference per artifact pin.', code='INVALID_ARGUMENT')
        by_pin[key] = row
    original_tracks = template.get('tracks', {}).get('children', []) if template else []
    tracks, used = [], set()
    for ti, track in enumerate(timeline['tracks']):
        if track['kind'] not in ('video', 'audio'):
            fail('caption_track', 'Caption tracks need separate caption interchange; no flattening is performed.')
        old = original_tracks[ti] if ti < len(original_tracks) else {}
        target: dict[str, Any] = dict(OTIO_SCHEMA='Track.1', name=track['track_id'], kind=track['kind'].title(),
                      children=[], source_range=None, effects=[], markers=[], metadata=_metadata(old))
        cursor = 0
        for item in sorted(track['items'], key=lambda value: value['start_frame']):
            if 'gain_db' in item or 'transform' in item:
                fail('gain_or_transform', 'Gain/layout transforms cannot be silently dropped from editable export.')
            if item['subject']['kind'] != 'artifact':
                fail('unrendered_subject', 'Editable export only supports pinned media; scenes/captions are not rendered or substituted.')
            row = by_pin.get(digest(item['subject']['artifact']))
            if row is None:
                fail('media_binding', 'Each timeline artifact needs an explicit media binding.', code='ASSETS_UNRESOLVED')
            _track_media(track['kind'], row)
            gap = item['start_frame'] - cursor
            if gap < 0:
                fail('overlap', 'Overlapping items are unsupported.', code='TIMING_INVALID')
            if gap:
                target['children'].append(dict(OTIO_SCHEMA='Gap.1', name='', source_range=_tr(0, gap, fps), effects=[], metadata={}))
            point = item.get('source_in')
            if point is None:
                fail('source_in', 'Explicit source_in is required; export does not guess source origin.', code='TIMING_INVALID')
            if point['domain'] == 'source_tick':
                fail('source_tick', 'Raw source PTS requires existing conform; interchange does not reset its origin.')
            if point['origin'] != 'source' or point.get('source_artifact') != row['artifact']:
                fail('source_in', 'Media source_in must pin its bound source artifact.', code='TIMING_INVALID')
            offset = Fraction(point['index'], rate_fraction(point['rate']))
            available_start, available_length = _available(row)
            length = Fraction(item['end_frame'] - item['start_frame'], fps)
            if offset < 0 or offset + length > available_length:
                fail('source_bounds', 'Timeline trim exceeds explicit source bounds.', code='TIMING_INVALID')
            rate = rate_fraction(row['available_range']['rate'])
            start_units, length_units = (available_start + offset) * rate, length * rate
            if start_units.denominator != 1 or length_units.denominator != 1:
                fail('subframe', 'Source trim is not integral at its explicitly pinned source rate.', code='TIMING_INVALID')
            available = row['available_range']
            media = dict(OTIO_SCHEMA='ExternalReference.1', target_url=row['reference'], metadata={},
                         available_range=_tr(available['start_index'], available['duration'], rate))
            target['children'].append(dict(OTIO_SCHEMA='Clip.2', name=item['item_id'],
                source_range=_tr(int(start_units), int(length_units), rate),
                media_references={'DEFAULT_MEDIA': media}, active_media_reference_key='DEFAULT_MEDIA',
                effects=[], markers=[], metadata={}))
            used.add(row['reference'])
            cursor = item['end_frame']
        if cursor < timeline['duration_frames']:
            target['children'].append(dict(OTIO_SCHEMA='Gap.1', name='',
                source_range=_tr(0, timeline['duration_frames'] - cursor, fps), effects=[], metadata={}))
        tracks.append(target)
    if used != set(bindings):
        fail('media_binding', 'Unused export bindings are rejected.', code='INVALID_ARGUMENT')
    if not tracks and timeline['duration_frames']:
        fail('empty_tracks', 'A nonzero empty timeline requires at least one explicit gap track.')
    return dict(OTIO_SCHEMA='Timeline.1', name='Motion Studio', metadata=_metadata(template or {}),
        global_start_time=copy.deepcopy(template.get('global_start_time')) if template else None,
        tracks=dict(OTIO_SCHEMA='Stack.1', name='tracks', children=tracks, source_range=None,
                    effects=[], markers=[], metadata={}))


def _snapshot(runtime, fs, pid, revision):
    pointer = runtime.projects._pointer(fs, pid)
    while pointer and pointer['revision'] > revision:
        pointer = runtime.projects._transaction(fs, pointer)['previous']
    if pointer is None or pointer['revision'] != revision:
        raise ContractError('REVISION_CONFLICT', 'Requested committed project revision is unavailable.')
    _, docs = runtime.projects._load(fs, pointer)
    return pointer, docs


def _bundle(runtime, pid, args, text, source_map, timeline_pin, inputs, **extra):
    value = dict(schema=BUNDLE_SCHEMA, adapter='otio_json', project_id=pid,
        project_revision=args['expected_revision'], request_id=args['request_id'],
        source_timeline=timeline_pin, otio_text=text, otio_sha256=_text_hash(text),
        media_bindings=args['media_bindings'], source_map=source_map,
        source_bounds_authority='explicit_binding_and_otio_available_range_not_media_probe',
        metadata_storage='Original OTIO metadata/timecode retained here; canonical timeline has no metadata field.',
        human_editor_round_trip_verified=False, **extra)
    pin = runtime.artifacts.publish_json(pid, value, inputs=inputs)
    runtime.artifacts.resolve(pid, pin)
    return pin


def dispatch(runtime, args):
    """Execute only an explicitly selected public import/export branch."""
    validate(args, {'oneOf': branches()})
    pid = args['project_id']
    fs = runtime.projects._filesystem(write=True)
    base = runtime.projects._base(pid)
    runtime.projects._pointer(fs, pid)  # Missing IDs must not create ghost project locks.
    # Receipts bind the public request (including source provenance), not merely
    # the resulting set_timeline patch, and permit safe retry after interruption.
    with fs.lock(base + '/locks/interchange.lock'):
        receipt_path = base + '/interchange-requests/' + args['request_id'] + '.json'
        try:
            receipt = fs.read(receipt_path)
        except FileNotFoundError:
            receipt = None
        request_hash = digest(args)
        if receipt is not None:
            if receipt.get('request_sha256') != request_hash:
                raise ContractError('IDEMPOTENCY_CONFLICT', 'Interchange request_id was already used with different arguments.')
            for pin in receipt['artifacts']:
                runtime.artifacts.resolve(pid, pin)
            return receipt['result']
        intent_path = base + '/interchange-requests/' + args['request_id'] + '.request.json'
        try:
            intent = fs.read(intent_path)
        except FileNotFoundError:
            intent = None
        if intent is not None and intent.get('request_sha256') != request_hash:
            raise ContractError('IDEMPOTENCY_CONFLICT', 'Interchange request_id already binds a different request.')
        if intent is None:
            # Retain public provenance identity even across a crash between the
            # project transaction and final result receipt.
            fs.write(intent_path, dict(request_sha256=request_hash), replace=False)
        pointer, docs = _snapshot(runtime, fs, pid, args['expected_revision'])
        settings = docs['settings', 'project']['value']
        timeline_record = docs['timeline', 'project']
        bindings = _bindings(runtime, pid, args['media_bindings'])
        otio = _engine()
        inputs = [row['artifact'] for row in args['media_bindings']]
        if args['action'] == 'interchange_import':
            source = args['source_artifact']
            inputs.append(source)
            text = _source_text(runtime, fs, pid, source)
            _, document, normalized = _parse(text, otio)
            timeline, source_map = _decode(document, bindings, settings)
            bundle = _bundle(runtime, pid, args, text, source_map, document_pin(timeline_record),
                inputs, direction='import', source_artifact=source,
                imported_timeline_sha256=digest(timeline))
            variants = copy.deepcopy(docs['variants', 'project']['value'])
            if not timeline['duration_frames'] and variants:
                fail('empty_timeline', 'Configured variants require a positive timeline duration.', code='TIMING_INVALID')
            for variant in variants:
                variant['duration_frames'] = timeline['duration_frames']
            updated = checked_update(runtime, args, [dict(op='set_timeline', value=timeline),
                dict(op='set_variants', value=variants)])
            result = dict(updated, interchange_bundle=bundle, source_artifact=source,
                          imported_timeline_sha256=digest(timeline), production_started=False)
        else:
            if args['source_timeline'] != document_pin(timeline_record):
                fail('timeline_pin', 'Export source_timeline must exactly pin the selected project timeline.', code='HASH_MISMATCH')
            template = None
            if 'source_bundle' in args:
                retained = json.loads(_read(runtime, fs, pid, args['source_bundle']))
                if (not isinstance(retained, dict) or retained.get('schema') != BUNDLE_SCHEMA or
                        retained.get('imported_timeline_sha256') != digest(timeline_record['value']) or
                        retained.get('media_bindings') != args['media_bindings']):
                    fail('metadata_binding', 'Metadata reuse requires the exact unchanged imported timeline.', code='HASH_MISMATCH')
                _, template, _ = _parse(_source_text(runtime, fs, pid, args['source_bundle']), otio)
                inputs.append(args['source_bundle'])
            # Exact unchanged imports can retain all original metadata/markers/
            # timecode, rather than pretending canonical storage has those fields.
            document = copy.deepcopy(template) if template is not None else _encode(
                timeline_record['value'], bindings, settings)
            document.setdefault('metadata', {})['motion_studio'] = dict(
                project_id=pid, project_revision=pointer['revision'],
                source_timeline=args['source_timeline'], media_bindings=args['media_bindings'])
            _, normalized_document, text = _parse(json.dumps(document, allow_nan=False), otio)
            decoded, source_map = _decode(normalized_document, bindings, settings)
            # Track/item identifiers are labels; compare source placements instead.
            if _semantic(decoded) != _semantic(timeline_record['value']):
                fail('export_fidelity', 'OTIO core serialization changed canonical source placements.', code='TIMING_INVALID')
            bundle = _bundle(runtime, pid, args, text, source_map, args['source_timeline'], inputs,
                direction='export', content_format='OpenTimelineIO otio_json', content_member='otio_text')
            result = dict(interchange_bundle=bundle, source_timeline=args['source_timeline'],
                project_revision=pointer['revision'], content_member='otio_text',
                media_acquired=False, human_editor_round_trip_verified=False, production_started=False)
        fs.write(receipt_path, dict(request_sha256=request_hash, artifacts=[bundle, *inputs], result=result), replace=False)
        return result


def _semantic(timeline):
    tracks = []
    for track in timeline['tracks']:
        items = []
        for item in sorted(track['items'], key=lambda row: row['start_frame']):
            point = item.get('source_in')
            seconds = None if point is None else Fraction(point['index'], rate_fraction(point['rate']))
            items.append((item['start_frame'], item['end_frame'], item['subject'], seconds))
        tracks.append((track['kind'], items))
    return timeline['duration_frames'], tracks
