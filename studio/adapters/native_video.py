"""Selected existing video-editor tools, not a second renderer or dispatcher.

Only spatial transforms are mapped. Source metadata is read from bounded pinned
MP4 bytes; real host tools still render under the normal claim/call lifecycle.
"""
from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path
from typing import cast

from ..contracts import ContractError, validate
from .limits import MAX_WIDTH, MAX_HEIGHT


IDS = {'crop': ('hermes.video-crop', 'lk_crop'),
       'scale': ('hermes.video-resize', 'lk_resize'),
       'rotate': ('hermes.video-rotate', 'lk_rotate_flip')}


def parameter_schema(kind):
    from ..capabilities import PARAMS, expanded
    branch = next(s for s in PARAMS['media.transform@1']['oneOf']
                  if s['properties']['kind']['const'] == kind)
    schema = cast(dict, expanded(branch))
    if kind == 'scale':
        schema['properties']['spec']['properties']['fit'] = {'const': 'contain'}
    if kind == 'rotate':
        schema['properties']['spec']['properties']['degrees']['enum'] = [90, 180, 270]
    return schema


def check_parameters(parameters):
    kind = parameters.get('kind')
    if kind not in IDS:
        raise ContractError('UNSUPPORTED_FEATURE', 'Native video supports crop, contain scale and rotation only.')
    validate(parameters, parameter_schema(kind))
    spec = parameters['spec']
    rect = spec['rect'] if kind == 'crop' else spec
    if kind != 'rotate':
        w, h = rect['width_px'], rect['height_px']
        minimum = 16 if kind == 'scale' else 2
        if not minimum <= w <= MAX_WIDTH or not minimum <= h <= MAX_HEIGHT or w % 2 or h % 2:
            raise ContractError('UNSUPPORTED_FEATURE', 'Explicit even native video dimensions within current bounds required.')
    if kind == 'crop' and any(rect[key] < 0 or rect[key] % 2 for key in ('x_px', 'y_px')):
        raise ContractError('UNSUPPORTED_FEATURE', 'Crop offsets must be nonnegative even pixels; no implicit chroma rounding.')


def source_facts(path):
    """No subprocess, network, or source conversion; open a bounded MP4 snapshot."""
    try:
        import av
        from av.error import FFmpegError
    except ImportError as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Native video validation requires existing PyAV with frame rotation support.') from exc
    with Path(path).open('rb') as stream:
        payload = stream.read(16777217)
    if not 0 < len(payload) <= 16777216:
        raise ContractError('LIMIT_EXCEEDED', 'Native video input is limited to 16 MiB.')
    try:
        with av.open(io.BytesIO(payload), mode='r', format='mov', options={'protocol_whitelist': 'pipe'}) as container:
            videos, audios = list(container.streams.video), list(container.streams.audio)
            if len(videos) != 1 or len(audios) > 1 or len(container.streams) != len(videos) + len(audios):
                raise ValueError('One video and optional mono/stereo audio required.')
            video = videos[0]
            w, h = video.width, video.height
            count = video.frames
            base = video.time_base
            if (video.codec_context.name != 'h264' or video.format.name != 'yuv420p'
                    or not 0 < w <= MAX_WIDTH or not 0 < h <= MAX_HEIGHT or w % 2 or h % 2
                    or video.average_rate != 30 or video.base_rate != 30
                    or video.start_time != 0 or not 0 < count <= 3600
                    or video.duration is None or base is None or video.duration * base != Fraction(count, 30)
                    or video.sample_aspect_ratio not in (None, Fraction(1))):
                raise ValueError('Requires zero-origin square-pixel H.264 yuv420p, 30 fps, at most 120 seconds.')
            frame = next(container.decode(video))
            if not hasattr(frame, 'rotation') or frame.rotation or video.metadata.get('rotate', '0') != '0':
                raise ValueError('Pre-rotated display metadata requires explicit conform first.')
            audio = audios[0] if audios else None
            if audio is not None and (audio.codec_context.name not in ('aac', 'alac')
                    or len(audio.codec_context.layout.channels) not in (1, 2)
                    or not 0 < audio.codec_context.sample_rate <= 48000):
                raise ValueError('Only mono/stereo AAC or ALAC up to 48 kHz supported.')
            if audio is not None:
                samples = Fraction(count, 30) * audio.codec_context.sample_rate
                if (samples.denominator != 1 or audio.start_time != 0 or audio.duration is None
                        or audio.time_base is None or audio.duration * audio.time_base != Fraction(count, 30)):
                    raise ValueError('Audio must match the exact zero-origin video presentation duration.')
                if audio.codec_context.name == 'aac' and samples % 1024:
                    raise ValueError('AAC decoder tail padding needs explicit conform to ALAC before native edits.')
            return dict(width=w, height=h, frames=count, audio=audio is not None)
    except (FFmpegError, ValueError, StopIteration, AttributeError, TypeError) as exc:
        raise ContractError('UNSUPPORTED_FEATURE', 'Native video source needs explicit conform: ' + str(exc)) from exc


def output_size(parameters, source):
    check_parameters(parameters)
    kind, spec = parameters['kind'], parameters['spec']
    w, h = source['width'], source['height']
    if kind == 'crop':
        rect = spec['rect']
        if rect['x_px'] + rect['width_px'] > w or rect['y_px'] + rect['height_px'] > h:
            raise ContractError('INVALID_ARGUMENT', 'Crop rectangle exceeds the source frame.')
        return rect['width_px'], rect['height_px']
    if kind == 'rotate':
        return (h, w) if spec['degrees'] in (90, 270) else (w, h)
    tw, th = spec['width_px'], spec['height_px']
    # FFmpeg force_original_aspect_ratio=decrease rounds to nearest integer;
    # the host then truncates each output dimension to an even pixel count.
    def nearest(num, den):
        return (2 * num + den) // (2 * den)
    result = (min(tw, nearest(w * th, h)) // 2 * 2,
              min(th, nearest(h * tw, w)) // 2 * 2)
    if min(result) < 2:
        raise ContractError('UNSUPPORTED_FEATURE', 'Contain scaling would produce an empty even-size frame.')
    if result[0] * h != result[1] * w:
        raise ContractError('UNSUPPORTED_FEATURE', 'Choose an even contain size that preserves square pixels without aspect rounding.')
    return result


def validate_timing(request, *, resolve_artifact):
    check_parameters(request['parameters'])
    inputs = request.get('inputs', {})
    if set(inputs) != {'media'} or inputs['media'].get('kind') != 'artifact':
        raise ContractError('INVALID_ARGUMENT', 'Native video requires one exact media artifact pin.')
    source = source_facts(resolve_artifact(inputs['media']['artifact']))
    output_size(request['parameters'], source)
    return []


def arguments(source, output, parameters):
    check_parameters(parameters)
    output_size(parameters, source_facts(source))
    result = dict(input=str(source), output=str(output), overwrite=False, timeout_s=60, crf=20)
    kind, spec = parameters['kind'], parameters['spec']
    if kind == 'crop':
        rect = spec['rect']
        result.update(width=rect['width_px'], height=rect['height_px'], x=rect['x_px'], y=rect['y_px'])
    elif kind == 'scale':
        result.update(width=spec['width_px'], height=spec['height_px'], keep_aspect=True)
    else:
        result.update(rotate=spec['degrees'], hflip=False, vflip=False)
    return result


def validate_output(tool_name, args, receipt):
    """Compare the actual full-decode receipt with the requested spatial edit."""
    source = source_facts(args['input'])
    if tool_name == 'lk_crop':
        params = dict(kind='crop', spec=dict(rect=dict(x_px=args['x'], y_px=args['y'],
            width_px=args['width'], height_px=args['height'])))
    elif tool_name == 'lk_resize':
        params = dict(kind='scale', spec=dict(width_px=args['width'], height_px=args['height'], fit='contain'))
    elif tool_name == 'lk_rotate_flip':
        params = dict(kind='rotate', spec=dict(degrees=args['rotate']))
    else:
        raise ContractError('UNSUPPORTED_OPERATION', 'Unknown native spatial tool.')
    expected = output_size(params, source)
    streams = receipt['probe']['streams']
    video = streams[0]
    if ((video['width'], video['height']) != expected or receipt['decoded_frames'] != source['frames']
            or video.get('codec_name') != 'h264' or video.get('pix_fmt') != 'yuv420p'
            or len(streams) != (2 if source['audio'] else 1)
            or video.get('sample_aspect_ratio', '1:1') not in ('1:1', 'N/A')):
        raise ContractError('OUTPUT_INVALID', 'Native spatial output differs from requested geometry, frames or stream layout.')


def bindings():
    from .native_tools import NativeBinding, effects
    constraints = dict(media_types=['video/mp4'], codecs=['h264', 'aac', 'alac'],
        max_width_px=MAX_WIDTH, max_height_px=MAX_HEIGHT, min_rate=dict(num=30, den=1),
        max_rate=dict(num=30, den=1), languages=[], color_spaces=[], alpha_modes=['none'],
        timing='frame', max_duration_frames=3600)
    return [NativeBinding(adapter, tool, 'media.transform@1', 'Existing Hermes video ' + kind,
        parameter_schema(kind), (dict(port='media', kind='media', media_type='video/mp4'),),
        'mp4', arguments, check_parameters, validate_timing, effects(),
        constraints=constraints, validate_output=validate_output,
        dependencies=(dict(name='av', kind='library', version_constraint='>=18', required=True),))
        for kind, (adapter, tool) in IDS.items()]
