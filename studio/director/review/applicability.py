"""MA-r1 byte classification and effective core-only checker options."""
import json
from typing import Any

REVISION = 'MA-r1'
SENSES = 'core-only/hear-see-rhythm-scenes-read-disabled/judge-off'
KINDS = {'image', 'audio-only', 'video', 'video-without-audio'}


def classify(source, *, call, env, cwd):
    """Probe decoded streams, excluding cover art; never use filename/tab hints."""
    result = call(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                   '-show_format', '-of', 'json', str(source)], cwd=cwd, env=env, timeout=30)
    if result.returncode:
        return None  # Checker retains applicable decode failures for corrupt inputs.
    doc = json.loads(result.stdout)
    picture = [s for s in doc.get('streams', []) if s.get('codec_type') == 'video'
               and not s.get('disposition', {}).get('attached_pic')]
    audio = any(s.get('codec_type') == 'audio' for s in doc.get('streams', []))
    formats = set(doc.get('format', {}).get('format_name', '').split(','))
    if formats & {'image2', 'png_pipe', 'jpeg_pipe', 'webp_pipe', 'bmp_pipe', 'tiff_pipe', 'gif', 'apng'}:
        return 'image' if not audio and len(picture) == 1 and str(picture[0].get('nb_read_frames', picture[0].get('nb_frames'))) == '1' else None
    if len(picture) > 1:
        return None
    if picture:
        return 'video' if audio else 'video-without-audio'
    return 'audio-only' if audio else None


def settings(*, mode='quick', platform='custom', shape=None) -> dict[str, Any]:
    if mode not in ('quick', 'full') or shape not in (None, '9:16', '16:9', '1:1'):
        raise ValueError('Invalid checker options')
    if platform not in ('custom', 'youtube', 'shorts', 'reels', 'tiktok'):
        raise ValueError('Invalid video destination')
    return dict(mode=mode, platform=platform, shape=shape)


def effective(kind, options):
    return dict(options, platform=options['platform'] if kind in ('video', 'video-without-audio') else 'custom')


def identity(kind, options, version):
    return json.dumps(dict(revision=REVISION, version=version, media_kind=kind,
        **effective(kind, options), explicit_targets={}, senses=SENSES), sort_keys=True, separators=(',', ':'))


def summarize(checks, compact, kind):
    """Applicable FAIL wins even when decode cannot complete; SKIP is not PASS."""
    statuses = [item.get('status') for item in checks]
    counts = {state: statuses.count(state) for state in ('PASS', 'WARN', 'FAIL', 'SKIP')}
    omissions = [dict(id=str(item.get('id', 'check')),
        summary=str(item.get('summary', 'Not checked: reason unavailable')),
        skip_reason=item.get('skip_reason', 'unavailable')) for item in checks if item.get('status') == 'SKIP']
    result: dict[str, Any] = dict(counts=counts, media_kind=kind, not_checked=[item['id'] for item in omissions],
        not_checked_details=omissions, not_checked_omitted_count=compact.get('not_checked_omitted_count', 0),
        omitted_details=compact.get('omitted_details', 0))
    if counts['FAIL']:
        result['status'] = 'FAIL'
    elif kind not in KINDS or not any(item.get('id') == 'decode' and item.get('status') == 'PASS' for item in checks):
        result['reason'] = 'Not checked: no completed applicable decode check'
    else:
        result['status'] = 'WARN' if counts['WARN'] else 'PASS'
    return result
