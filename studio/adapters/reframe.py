"""G016: one bounded, seeded template route; all decoding runs in an owned child.

Registration is metadata-only. No face recognition, model downloads, audio
removal, VFR conform, scale-adaptive tracker or implicit subject selection.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..contracts import ContractError, D, canonical, digest, safe_relative, validate
from . import ffmpeg, rates

ADAPTER_ID = 'local.portrait-reframe'
OPERATION = 'media.reframe@1'
MAX_SOURCE_BYTES = 1024 ** 3
MAX_FRAMES = 3600
MAX_REPORT_BYTES = 8 * 1024 ** 2
PORTS = [('media', 'media', 'video/x-matroska'), ('trace', 'report', 'application/json')]


def _integer(lo, hi):
    return dict(type='integer', minimum=lo, maximum=hi)


def _object(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


RECT_SCHEMA = _object(dict(x=_integer(0, 4095), y=_integer(0, 4095),
                           width=_integer(1, 4096), height=_integer(1, 4096)))
# Parent capabilities must use this exact schema, not a permissive second copy.
PARAMS = _object(dict(
    route={'const': 'seeded-template-v1'},
    source_width_px=_integer(2, 1920), source_height_px=_integer(2, 1080),
    duration_frames=_integer(1, MAX_FRAMES),
    rate=_object(dict(num=_integer(1, 60000), den=_integer(1, 1001))),
    seed=RECT_SCHEMA, crop_width_px=_integer(2, 1920), crop_height_px=_integer(2, 1080),
    width_px=_integer(2, 1080), height_px=_integer(2, 1920),
    search_radius_px=_integer(1, 16), max_mean_error=_integer(0, 64),
    caption_safe=RECT_SCHEMA, audio={'const': 'require-silent'}))


def check_parameters(params: dict[str, Any]):
    validate(params, PARAMS)
    sw, sh = params['source_width_px'], params['source_height_px']
    cw, ch = params['crop_width_px'], params['crop_height_px']
    ow, oh = params['width_px'], params['height_px']
    cadence = rates.fraction(params['rate'])
    if (any(v % 2 for v in (sw, sh, cw, ch, ow, oh)) or sw <= sh or ow >= oh
            or cw > sw or ch > sh or cw * oh != ch * ow
            or Fraction(params['duration_frames'], 1) / cadence > 150):
        raise ValueError('Even landscape source, portrait output, exact crop aspect and <=150 seconds required')
    seed = params['seed']
    _inside(seed, sw, sh)
    if not 8 <= seed['width'] <= 256 or not 8 <= seed['height'] <= 256:
        raise ValueError('Seed dimensions must be 8..256 source pixels')
    if seed['width'] > cw or seed['height'] > ch:
        raise ValueError('Seed cannot fit selected crop')
    _inside(params['caption_safe'], ow, oh)
    return cadence


def _inside(rect, width, height):
    if (rect['x'] < 0 or rect['y'] < 0 or rect['width'] <= 0 or rect['height'] <= 0
            or rect['x'] + rect['width'] > width or rect['y'] + rect['height'] > height):
        raise ValueError('Rectangle exceeds explicit canvas bounds')


def crop_for(subject: dict[str, int], params: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    """Integer source crop, containment, and separate output caption exclusion."""
    sw, sh, cw, ch, ow, oh = (params[k] for k in ('source_width_px', 'source_height_px',
        'crop_width_px', 'crop_height_px', 'width_px', 'height_px'))
    _inside(subject, sw, sh)
    x = max(0, min(sw - cw, (2 * subject['x'] + subject['width'] - cw) // 2))
    y = max(0, min(sh - ch, (2 * subject['y'] + subject['height'] - ch) // 2))
    if (subject['x'] < x or subject['y'] < y or subject['x'] + subject['width'] > x + cw
            or subject['y'] + subject['height'] > y + ch):
        raise ValueError('Tracked subject is not contained by applied crop')
    # Outward rounding proves the entire transformed subject box is excluded
    # from the independently declared caption-safe rectangle.
    left, top = (subject['x'] - x) * ow // cw, (subject['y'] - y) * oh // ch
    right = ((subject['x'] + subject['width'] - x) * ow + cw - 1) // cw
    bottom = ((subject['y'] + subject['height'] - y) * oh + ch - 1) // ch
    safe = params['caption_safe']
    overlap = (left < safe['x'] + safe['width'] and right > safe['x']
               and top < safe['y'] + safe['height'] and bottom > safe['y'])
    if overlap:
        raise ValueError('Transformed subject overlaps separately declared caption-safe rectangle')
    return dict(x=x, y=y, width=cw, height=ch), dict(x=left, y=top, width=right-left, height=bottom-top)


def registration() -> dict[str, Any]:
    source = ffmpeg.registration()
    declaration = ffmpeg.declaration()
    item = copy.deepcopy(declaration['operations'][0])
    prototype = item['result_schema']
    item.update(operation=OPERATION, request_schema='motion/v1/portrait-reframe/request',
                result_schema='motion/v1/portrait-reframe/result',
                features=['reframe.seeded_template', 'reframe.applied_crop', 'reframe.caption_safe'],
                default_timeout_seconds=7200)
    # Local asset import uses the registered video/matroska MIME alias on
    # some hosts; retain x-matroska for upstream native artifacts as well.
    item['constraints'].update(media_types=['video/mp4', 'video/quicktime', 'video/matroska', 'video/x-matroska', 'application/json'],
        codecs=['h264', 'ffv1', 'prores'], max_width_px=1920, max_height_px=1920,
        max_duration_frames=MAX_FRAMES, alpha_modes=['none'])
    declaration.update(adapter_id=ADAPTER_ID, implementation_version='1.0.0',
        label='Seeded moving-subject portrait reframing', operations=[item])
    return dict(declaration=declaration,
        implementation_sha256=digest({name: ffmpeg.digest(Path(__file__).with_name(name))
                                      for name in ('reframe.py', 'rates.py', 'ffmpeg.py')}),
        schemas={item['request_schema']: PARAMS, item['result_schema']: source['schemas'][prototype]},
        outputs={OPERATION: [dict(port=p, kind=k, media_type=m) for p, k, m in PORTS]})


def discover():
    available = (all(importlib.util.find_spec(name) is not None for name in ('PIL', 'av'))
                 and all(shutil.which(name) for name in ('ffmpeg', 'ffprobe')))
    return dict(status='available' if available else 'unavailable',
                reason='Library/PATH metadata only; no tracker, decoder or encoder executed')


def validate_timing(project_id, request, metadata, documents, *, resolve_artifact):
    try:
        if request['operation'] != OPERATION or set(request['inputs']) != {'media'}:
            raise ValueError('Reframing requires exact media input closure')
        check_parameters(request['parameters'])
        binding = request['inputs']['media']
        if binding.get('kind') == 'node_output':
            return []  # Native core resolves immutable output before execution.
        if binding.get('kind') != 'artifact':
            raise ValueError('Reframing requires immutable media pin')
        resolve_artifact(binding['artifact'])
        return []
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ContractError('TIMING_INVALID', str(exc)) from exc


def _box(rect):
    return (rect['x'], rect['y'], rect['x'] + rect['width'], rect['y'] + rect['height'])


class TemplateTracker:
    """Fixed first-frame RGB template, exhaustive integer local search, no drift.

    A 16x16 nearest-neighbor signature bounds work independently of seed size.
    Exact best-score ties reject ambiguity rather than choosing another person.
    """
    def __init__(self, image, seed, radius, max_error):
        from PIL import Image, ImageStat
        self.seed, self.position = dict(seed), dict(seed)
        self.radius, self.max_error = radius, max_error
        self.template = image.crop(_box(seed)).resize((16, 16), Image.Resampling.NEAREST).convert('RGB')
        if max(ImageStat.Stat(self.template).stddev) < 8:
            raise ValueError('Tracking seed has insufficient texture/contrast')

    def track(self, image):
        from PIL import Image, ImageChops, ImageStat
        previous, best, ties = self.position, None, 0
        for y in range(max(0, previous['y'] - self.radius),
                       min(image.height - self.seed['height'], previous['y'] + self.radius) + 1):
            for x in range(max(0, previous['x'] - self.radius),
                           min(image.width - self.seed['width'], previous['x'] + self.radius) + 1):
                rect = dict(x=x, y=y, width=self.seed['width'], height=self.seed['height'])
                patch = image.crop(_box(rect)).resize((16, 16), Image.Resampling.NEAREST).convert('RGB')
                score = int(sum(ImageStat.Stat(ImageChops.difference(self.template, patch)).sum))
                if best is None or score < best[0]:
                    best, ties = (score, rect), 1
                elif score == best[0]:
                    ties += 1
        if best is None or best[0] > self.max_error * 768 or ties != 1:
            raise ValueError('Tracking lost: template error or ambiguous best match')
        self.position = best[1]
        return dict(self.position), best[0]


def _engine_identity():
    """Execution-only identity; imports never occur during registration."""
    import av
    import av._core
    import PIL
    from PIL import _imaging
    facts: dict[str, Any] = dict(route='seeded-template-v1',
        implementation={name: ffmpeg.digest(Path(__file__).with_name(name))
                        for name in ('reframe.py', 'rates.py', 'ffmpeg.py')},
        python=ffmpeg.digest(Path(sys.executable).resolve()), python_version=sys.version,
        pyav_version=av.__version__, pyav_core=ffmpeg.digest(Path(av._core.__file__)),
        pillow_version=PIL.__version__, pillow_core=ffmpeg.digest(Path(_imaging.__file__)),
        libav_versions={k: list(v) for k, v in av.library_versions.items()},
        resize='Pillow.BICUBIC', signature='RGB.16x16.NEAREST.SAD', encoder='ffv1.bgr0.threads1')
    # Shared-library byte hashes pin the actual dynamically loaded engine, not
    # just a package version string. Linux is the native owned-worker platform.
    loaded = set()
    for line in Path('/proc/self/maps').read_text().splitlines():
        path = line.split()[-1]
        if path.startswith('/') and any(name in Path(path).name for name in
                ('libavcodec', 'libavformat', 'libavutil', 'libswscale', 'libswresample')):
            loaded.add(path)
    if not loaded:
        raise ValueError('Cannot establish loaded libav engine byte identity')
    facts['loaded_libraries'] = {path: ffmpeg.digest(path) for path in sorted(loaded)}
    return dict(sha256=digest(facts), facts=facts)


def render(source, target, params, trace_path):
    """Worker-only streaming decode/crop/resize/encode; no subprocess fallback."""
    import av
    from PIL import Image
    cadence = check_parameters(params)
    source, target, trace_path = Path(source), Path(target), Path(trace_path)
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
        raise ValueError('Source must be a bounded regular local media file')
    if target.exists() or trace_path.exists():
        raise ValueError('Reframe never overwrites existing outputs')
    source_hash, engine = ffmpeg.digest(source), _engine_identity()
    entries = []  # Bounded <=3600 small records, never retained raster frames.
    try:
        with av.open(str(source), options={'protocol_whitelist': 'file',
                     'format_whitelist': 'mov,matroska,webm', 'enable_drefs': '0',
                     'use_absolute_path': '0'}) as incoming:
            if len(incoming.streams) != 1 or len(incoming.streams.video) != 1:
                raise ValueError('Require silent single-video input; extract audio explicitly before reframing')
            stream = incoming.streams.video[0]
            if (stream.codec_context.name not in ('h264', 'ffv1', 'prores')
                    or (stream.width, stream.height) != (params['source_width_px'], params['source_height_px'])
                    or stream.average_rate is None or Fraction(stream.average_rate) != cadence
                    or stream.sample_aspect_ratio not in (None, Fraction(1))
                    or stream.codec_context.pix_fmt not in ('bgr0', 'rgb24', 'gbrp', 'gbrp10le',
                        'yuv420p', 'yuv422p', 'yuv444p', 'yuv420p10le', 'yuv422p10le', 'yuv444p10le')
                    or any(key.lower() == 'rotate' and str(value) != '0' for key, value in stream.metadata.items())):
                raise ValueError('Source codec, geometry, cadence, aspect or rotation requires explicit conform')
            stream.codec_context.thread_count = 1
            with av.open(str(target), 'w', format='matroska') as outgoing:
                encoder = outgoing.add_stream('ffv1', rate=cadence)
                encoder.width, encoder.height = params['width_px'], params['height_px']
                encoder.pix_fmt, encoder.codec_context.thread_count = 'bgr0', 1
                encoder.metadata['motion_rate'] = rates.text(cadence)
                tracker, previous = None, None
                for index, frame in enumerate(incoming.decode(stream)):
                    if index >= params['duration_frames']:
                        raise ValueError('Source frame count exceeds explicit full-range contract')
                    if frame.pts is None or frame.time_base is None:
                        raise ValueError('Every decoded frame must carry an exact timestamp')
                    tick = Fraction(frame.time_base)
                    stamp = frame.pts * tick
                    if (tick <= 0 or tick > Fraction(1, 2) / cadence
                            or abs(stamp - Fraction(index, 1) / cadence) > tick / 2
                            or (previous is not None and stamp <= previous)):
                        raise ValueError('VFR/nonzero origin exceeds half-tick CFR quantization tolerance')
                    if getattr(frame, 'rotation', 0) != 0 or any('DISPLAYMATRIX' in str(s).upper() for s in frame.side_data):
                        raise ValueError('Display rotation must be explicitly conformed')
                    if (frame.width, frame.height) != (params['source_width_px'], params['source_height_px']):
                        raise ValueError('Changing source dimensions are unsupported')
                    previous = stamp
                    image = frame.reformat(format='rgb24', threads=1).to_image().convert('RGB')
                    if tracker is None:
                        tracker = TemplateTracker(image, params['seed'], params['search_radius_px'], params['max_mean_error'])
                        subject, error = dict(params['seed']), 0
                    else:
                        subject, error = tracker.track(image)
                    crop, transformed = crop_for(subject, params)
                    applied = image.crop(_box(crop)).resize((params['width_px'], params['height_px']), Image.Resampling.BICUBIC)
                    output = av.VideoFrame.from_image(applied)
                    output.pts, output.time_base = index, Fraction(1, 1) / cadence
                    for packet in encoder.encode(output):
                        outgoing.mux(packet)
                    entries.append(dict(frame=index, source_pts=frame.pts, source_time_base=str(tick),
                        subject=subject, crop=crop, output_subject=transformed, signature_sad=error,
                        subject_contained=True, caption_safe_clear=True))
                if len(entries) != params['duration_frames']:
                    raise ValueError('Truncated source: exact full frame range required')
                for packet in encoder.encode():
                    outgoing.mux(packet)
        if ffmpeg.digest(source) != source_hash:
            raise ValueError('Source bytes changed during tracking')
        # Independently decode actual encoded output, including its frame clock.
        decoded = 0
        with av.open(str(target)) as result:
            if len(result.streams) != 1:
                raise ValueError('Encoded output contains unexpected streams')
            result.streams.video[0].codec_context.thread_count = 1
            for index, frame in enumerate(result.decode(video=0)):
                if ((frame.width, frame.height) != (params['width_px'], params['height_px'])
                        or frame.pts is None or frame.time_base is None or abs(frame.pts * Fraction(frame.time_base)
                                                   - Fraction(index, 1) / cadence) > Fraction(frame.time_base) / 2):
                    raise ValueError('Encoded output geometry or presentation clock differs')
                decoded += 1
        if decoded != len(entries):
            raise ValueError('Encoded output frame count differs from applied trace')
        report = dict(schema='motion/v1/portrait-reframe-trace', source_sha256=source_hash,
            output_sha256=ffmpeg.digest(target), engine=engine, parameters=params,
            decoded_output_frames=decoded, audio='verified-silent', frames=entries)
        payload = canonical(report)
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError('Crop trace exceeds bounded report size')
        with trace_path.open('xb') as stream:
            stream.write(payload)
        return report
    except BaseException:
        target.unlink(missing_ok=True)
        trace_path.unlink(missing_ok=True)
        raise


class LocalReframeAdapter:
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, copy.deepcopy(binding)

    def validate_request(self, request):
        if request.get('operation') != OPERATION or set(request.get('inputs', {})) != {'media'}:
            raise ContractError('INVALID_ARGUMENT', 'Exact media.reframe media source required')
        check_parameters(request['parameters'])
        expected = self.runtime.registry.binding(ADAPTER_ID, OPERATION, request['parameters'], request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen reframe implementation differs')
        validate(request['inputs']['media'], D['ArtifactRef'])
        if request.get('binding_parameters') is not None:
            raise ContractError('INVALID_ARGUMENT', 'Reframe has no arbitrary engine options')
        effects = self.runtime.registry.effects(ADAPTER_ID)
        if request.get('effects', effects) != effects:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Reframe effects differ')
        if set(request.get('required_features', [])) - set(registration()['declaration']['operations'][0]['features']):
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Unsupported reframing feature')
        return dict(valid=True, effects=effects)

    def execute(self, request, attempt, context=None):
        from .media_probe import _result
        if not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext required')
        runner = getattr(context, 'run')
        try:
            self.validate_request(request)
            if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
                raise ContractError('PERMISSION_DENIED', 'Exact owned attempt authority required')
            relative = safe_relative(attempt['output_dir'])
            expected = self.runtime.projects._base(request['project_id']) + '/jobs/' + attempt['job_id'] + '/attempts/' + attempt['attempt_id']
            if relative != expected:
                raise ContractError('PATH_UNSAFE', 'Reframe output differs from exact owning attempt')
            deadline = time.monotonic() + (datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds()
            def run(argv, **kwargs):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Reframe deadline elapsed')
                kwargs['timeout'] = min(kwargs.get('timeout', remaining), remaining)
                return runner(argv, **kwargs)
            pin = request['inputs']['media']
            source = Path(self.runtime.artifact_path(request['project_id'], pin))
            if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
                raise ValueError('Unsafe or oversized reframe source')
            if ffmpeg.digest(source) != pin['sha256']:
                raise ContractError('HASH_MISMATCH', 'Pinned source changed')
            fs = self.runtime.projects._filesystem(write=True)
            with fs.directory(relative, create=True):
                out = fs.root / relative
                params_path, target, trace = out / 'reframe-parameters.json', out / 'portrait.mkv', out / 'crop-trace.json'
                with params_path.open('xb') as stream:
                    stream.write(canonical(request['parameters']))
                # Worker cwd is the attempt, not checkout. Explicit package root
                # permits source checkout execution without environment mutation.
                bootstrap = ('import sys;sys.path.insert(0,sys.argv.pop(1));'
                             'from studio.adapters.reframe import _worker;_worker()')
                completed = run([sys.executable, '-c', bootstrap, str(Path(__file__).resolve().parents[2]),
                     str(source.resolve()), str(target.resolve()), str(params_path.resolve()), str(trace.resolve())],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if completed.returncode:
                    failure = out / 'reframe-error.json'
                    message = 'Owned reframe worker failed (exit %s)' % completed.returncode
                    if failure.is_file() and 0 < failure.stat().st_size <= 4096:
                        message = json.loads(failure.read_bytes())['message']
                    raise ValueError(message)
                if ffmpeg.digest(source) != pin['sha256']:
                    raise ContractError('HASH_MISMATCH', 'Pinned source changed during processing')
                if not 0 < trace.stat().st_size <= MAX_REPORT_BYTES:
                    raise ValueError('Missing or oversized crop trace')
                receipt = json.loads(trace.read_bytes())
                if (receipt['source_sha256'] != pin['sha256'] or receipt['output_sha256'] != ffmpeg.digest(target)
                        or receipt['parameters'] != request['parameters']
                        or receipt['decoded_output_frames'] != request['parameters']['duration_frames']):
                    raise ValueError('Worker trace differs from exact source/output contract')
                self.runtime.output_probe.validate_file(target, dict(kind='media', media_type='video/x-matroska'), run_process=run)
                return _result([dict(port=p, relative_path=path.name, media_type=m, claimed_sha256=ffmpeg.digest(path))
                                for (p, _, m), path in zip(PORTS, (target, trace))])
        except (ContractError, ValueError, KeyError, TypeError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
            return _result([], dict(code=getattr(exc, 'code', 'OUTPUT_INVALID'), message=str(exc),
                                   retry='after_input_change', effect='none', details={}))


def _worker():
    if len(sys.argv) != 5:
        raise ValueError('Private worker requires exact source, target, params and trace paths')
    source, target, params, trace = sys.argv[1:]
    path = Path(params)
    if not 0 < path.stat().st_size <= 16384:
        raise ValueError('Oversized worker parameters')
    try:
        render(source, target, json.loads(path.read_bytes()), trace)
    except Exception as exc:
        failure = Path(trace).with_name('reframe-error.json')
        with failure.open('xb') as stream:
            stream.write(canonical(dict(message=(type(exc).__name__ + ': ' + str(exc))[:2048])))
        raise SystemExit(1) from None
