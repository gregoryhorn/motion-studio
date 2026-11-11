"""Closed, content-free metadata for retained selected-output handoff."""
import math
import re
from ..domain import Fault
from ..media_import.validation import MIME

LIMIT = 16 * 1024 * 1024  # Matches the existing verified retained-byte transport.
ID = re.compile(r'^[a-f0-9]{32}$')
HASH = re.compile(r'^[a-f0-9]{64}$')


def media_format(kind, facts):
    """Only the existing import contract and retained WAV route are exportable."""
    format = facts.get('format', 'wav')
    allowed = {'Image': ('png', 'jpeg'), 'Video': ('mp4',),
               'Sound effects': ('wav',), 'Music': ('wav',), 'Voice': ('wav',)}
    if (format not in allowed.get(kind, ()) or
            facts.get('mime', MIME.get(format)) != MIME.get(format) or
            facts.get('storage') not in (None, 'original-v1') or
            (format != 'wav' and facts.get('storage') != 'original-v1')):
        raise Fault('EXPORT_FORMAT_UNSUPPORTED', 422)
    return format


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Fault('EXPORT_ID_INVALID', 422)
    return value


def positive(value):
    if type(value) is not int or value < 1:
        raise Fault('EXPORT_VERSION_INVALID', 422)
    return value


def reference_pins(snapshot, asset):
    references = {item['id']: item for item in snapshot.get('references', [])}
    result = []
    for pin in asset.get('selection_references', []):
        source = references.get(pin['id'])
        if not source or source['revision'] != pin['revision']:
            raise Fault('EXPORT_SELECTION_STALE', 409)
        take = source['take']
        digest = take['digest']
        if not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise Fault('EXPORT_LINEAGE_INVALID', 409)
        result.append(dict(reference=identifier(pin['id']), revision=positive(pin['revision']),
            request=identifier(take['request']), take=identifier(take['id']),
            artifact=identifier(take['artifact']), sha256=digest))
    return sorted(result, key=lambda item: item['reference'])


def select(snapshot, asset_ids):
    """Freeze only selected identity/version fields, never labels or prompts."""
    identifier(snapshot['id'])
    positive(snapshot['revision'])
    if not isinstance(asset_ids, (list, tuple)) or not 1 <= len(asset_ids) <= 100:
        raise Fault('EXPORT_SELECTION_INVALID', 422)
    if len(set(asset_ids)) != len(asset_ids):
        raise Fault('EXPORT_SELECTION_INVALID', 422)
    for item in asset_ids:
        identifier(item)
    assets = {asset['id']: asset for asset in snapshot['assets']}
    result = []
    for asset_id in sorted(asset_ids):
        asset = assets.get(asset_id)
        if not asset or not asset['selected_take']:
            raise Fault('EXPORT_SELECTED_TAKE_MISSING', 409)
        if asset['stale']:
            raise Fault('EXPORT_SELECTION_STALE', 409)
        takes = [take for take in asset['takes'] if take['id'] == asset['selected_take']]
        if len(takes) != 1:
            raise Fault('EXPORT_SELECTED_TAKE_MISSING', 409)
        take = takes[0]
        format = media_format(asset['kind'], take['facts'])
        take_index = next(index for index, item in enumerate(asset['takes'], 1)
                          if item['id'] == take['id'])
        filename = (f"media/{asset['position'] + 1:02d}-"
                    f"{asset['kind'].lower().replace(' ', '-')}-take-{take_index:02d}.{format}")
        digest = take['digest']
        if not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise Fault('EXPORT_INTEGRITY_FAILED', 409)
        size = positive(take['size'])
        if size > LIMIT:
            raise Fault('EXPORT_SIZE_UNSUPPORTED', 413)
        dependencies = [dict(asset=identifier(pin['id']), take=identifier(pin['take']),
            selection_revision=positive(pin['pointer_revision'])) for pin in asset.get('selection_dependencies', [])]
        result.append(dict(asset=identifier(asset_id), asset_revision=positive(asset['revision']),
            selection_revision=positive(asset['pointer_revision']), kind=asset['kind'],
            take=identifier(take['id']), request=identifier(take['request']),
            request_revision=positive(take['source_request_revision']), artifact=identifier(take['artifact']),
            sha256=digest, bytes=size, position=asset['position'], format=format,
            filename=filename,
            storage=take['facts'].get('storage'), review_status=take.get('review', 'Not reviewed'),
            references=reference_pins(snapshot, asset),
            dependencies=sorted(dependencies, key=lambda item: item['asset'])))
    return result


def lineage(facts):
    """Allow only numeric/hash lineage; arbitrary producer text never leaves storage."""
    voice = facts.get('voice_lineage')
    if voice:
        if voice.get('conversion') != 'mono-44100-pcm16':
            raise Fault('EXPORT_LINEAGE_INVALID', 409)
        result = dict(role='retained-derivative', conversion='mono-44100-pcm16')
        for role in ('native', 'derivative'):
            entry = voice.get(role, {})
            digest = entry.get('sha256')
            if not isinstance(digest, str) or not HASH.fullmatch(digest):
                raise Fault('EXPORT_LINEAGE_INVALID', 409)
            result[role] = dict(sha256=digest, bytes=positive(entry.get('bytes')))
        if voice['native'].get('format') not in ('mp3', 'ogg'):
            raise Fault('EXPORT_LINEAGE_INVALID', 409)
        result['native']['format'] = voice['native']['format']
        result['derivative'].update(rate=44100, channels=1, bits=16)
        return result
    source = facts.get('lineage')
    if not source:
        return None
    result = {}
    for role in ('native', 'derivative'):
        entry = source.get(role, {})
        digest = entry.get('sha256')
        if not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise Fault('EXPORT_LINEAGE_INVALID', 409)
        result[role] = dict(sha256=digest, bytes=positive(entry.get('bytes')))
        for key in ('rate', 'channels', 'frames', 'bits'):
            result[role][key] = positive(entry.get(key))
        if entry.get('encoding') not in ('PCM', 'IEEE_FLOAT'):
            raise Fault('EXPORT_LINEAGE_INVALID', 409)
        result[role]['encoding'] = entry['encoding']
    result['role'] = 'retained-derivative'
    return result


def entry(pin, facts):
    format = media_format(pin['kind'], facts)
    if format != pin['format'] or facts.get('storage') != pin['storage']:
        raise Fault('EXPORT_INTEGRITY_FAILED', 409)
    keys = ('duration', 'rate', 'channels', 'frames') if format == 'wav' else ('width', 'height')
    if format == 'mp4':
        keys += ('duration', 'rate', 'channels')
    measured = {}
    for key in keys:
        value = facts.get(key)
        if value is None and key in ('rate', 'channels') and format == 'mp4':
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise Fault('EXPORT_INTEGRITY_FAILED', 409)
        measured[key] = value
    if format == 'mp4':
        # Carry existing validated facts without imposing new requirements on
        # older retained takes which predate these measurements.
        frame_rate = facts.get('frame_rate')
        if isinstance(frame_rate, str) and re.fullmatch(r'[0-9]{1,12}/[0-9]{1,12}', frame_rate):
            measured['frame_rate'] = frame_rate
        if facts.get('codec') in ('h264', 'mpeg4'):
            measured['codec'] = facts['codec']
        if type(facts.get('audio')) is bool:
            measured['audio'] = facts['audio']
    review = pin.get('review_status', 'Not reviewed')
    if review not in ('Not reviewed', 'Matches request', 'Needs work'):
        raise Fault('EXPORT_INTEGRITY_FAILED', 409)
    result = dict(pin, qa=dict(technical='Validated retained format', perceptual=review,
                  useEligibility='Not assessed', userApproval='Not recorded'), mime=MIME[format], measured=measured,
                  limitations=['Selection is not perceptual or usage approval.',
                               'Usage rights are not assessed by this export.'])
    del result['storage']
    ancestry = lineage(facts)
    if ancestry:
        if ancestry['derivative']['sha256'] != pin['sha256'] or ancestry['derivative']['bytes'] != pin['bytes']:
            raise Fault('EXPORT_LINEAGE_INVALID', 409)
        result['lineage'] = ancestry
    else:
        result['lineage'] = dict(role='retained-original', request=pin['request'], artifact=pin['artifact'])
    return result
