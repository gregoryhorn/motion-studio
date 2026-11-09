"""Owned, bounded ffprobe receipts. No discovery/process work at import time."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from fractions import Fraction

from ..contracts import (ContractError, TEXT, DIGEST, arr, enum, nullable, obj,
                         canonical, safe_relative)
from ..project import _id, _now

ADAPTER_ID = 'ffmpeg.probe'
MAX_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
# Deliberately excludes playlists, concat, SDP and other external-resource demuxers.
FORMATS = 'mov,matroska,webm,wav,flac,mp3,ogg,aac,png_pipe,jpeg_pipe'


def result_schema():
    """Native adapter envelope, NOT the separately published ProbeReceipt."""
    descriptor = obj(dict(port=TEXT, relative_path=TEXT, media_type=TEXT,
                          claimed_sha256=nullable(DIGEST)))
    return obj(dict(
        state=enum('running', 'awaiting_external', 'review_needed', 'succeeded',
                   'failed', 'cancelled', 'interrupted'),
        submission_state=enum('not_sent', 'intent_recorded', 'confirmed', 'uncertain'),
        external_handle={'type': 'null'}, remote_state={'const': 'none'},
        progress={'type': 'null'}, outputs=arr(descriptor), warnings=arr(TEXT),
        error=nullable(obj(dict(code=TEXT, message=TEXT, retry=TEXT, effect=TEXT,
                                details={'type': 'object'}))),
        observed_cost={'type': 'null'}, logs_ref={'type': 'null'}, handoff={'type': 'null'}))


def _result(outputs, error=None):
    return dict(state='failed' if error else 'succeeded', submission_state='confirmed',
                external_handle=None, remote_state='none', progress=None,
                outputs=outputs, warnings=[], error=error, observed_cost=None,
                logs_ref=None, handoff=None)


def _integer(value, *, minimum=None):
    try:
        if isinstance(value, bool) or str(int(value)) != str(value):
            return None
        n = int(value)
        return n if abs(n) <= 9007199254740991 and (minimum is None or n >= minimum) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _rate(value):
    try:
        f = Fraction(value)
        if f <= 0 or max(f.numerator, f.denominator) > 9007199254740991:
            return None
        return dict(num=f.numerator, den=f.denominator)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def _stream(raw):
    kind = raw.get('codec_type')
    if kind not in ('video', 'audio', 'subtitle', 'data'):
        raise ContractError('OUTPUT_INVALID', 'Unsupported stream type; cannot silently omit source streams.')
    index, base = _integer(raw.get('index'), minimum=0), _rate(raw.get('time_base'))
    if index is None or base is None or not raw.get('codec_name'):
        raise ContractError('OUTPUT_INVALID', 'Stream lacks required codec/time-base/index facts.')
    color = None
    values = {k: raw.get(v) for k, v in dict(primaries='color_primaries',
              transfer='color_transfer', matrix='color_space', range='color_range').items()}
    if all(values.values()) and values['range'] in ('tv', 'pc') and all(v != 'unknown' for v in values.values()):
        color = {**values, 'range': 'limited' if values['range'] == 'tv' else 'full'}
    return dict(index=index, type=kind, codec=raw['codec_name'], time_base=base,
                start_pts=_integer(raw.get('start_pts')),
                duration_ticks=_integer(raw.get('duration_ts'), minimum=0),
                frame_count=_integer(raw.get('nb_frames'), minimum=0),
                rate=_rate(raw.get('avg_frame_rate')) if kind == 'video' else None,
                width_px=_integer(raw.get('width'), minimum=1) if kind == 'video' else None,
                height_px=_integer(raw.get('height'), minimum=1) if kind == 'video' else None,
                pixel_format=raw.get('pix_fmt') if kind == 'video' else None,
                color=color, alpha='unknown' if kind == 'video' else 'none',
                sample_rate=_integer(raw.get('sample_rate'), minimum=1) if kind == 'audio' else None,
                channels=_integer(raw.get('channels'), minimum=1) if kind == 'audio' else None,
                channel_layout=raw.get('channel_layout') if kind == 'audio' else None)


class MediaProbeAdapter:
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, copy.deepcopy(binding)

    def validate_request(self, request):
        if request.get('operation') != 'media.probe@1':
            raise ContractError('UNSUPPORTED_OPERATION', 'Probe adapter only implements media.probe@1.')
        expected = self.runtime.registry.binding(ADAPTER_ID, request['operation'],
                    request['parameters'], request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen probe executable/schema binding differs.')
        if request['parameters'].get('full_decode', False) and not shutil.which('ffmpeg'):
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Full decode requires installed ffmpeg.')
        if set(request.get('inputs', {})) != {'media'}:
            raise ContractError('INVALID_ARGUMENT', 'Probe requires exactly one media ArtifactRef.')
        from ..contracts import D, validate
        validate(request['inputs']['media'], D['ArtifactRef'])
        return dict(valid=True, effects=self.runtime.registry.effects(ADAPTER_ID))

    def execute(self, request, attempt, context=None):
        self.validate_request(request)
        if context is None or not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run is required.')
        probe = shutil.which('ffprobe')
        if not probe:
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Installed ffprobe is required.')
        deadline = time.monotonic() + 60
        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError('Probe attempt deadline elapsed.')
            return seconds
        fs = self.runtime.projects._filesystem(write=True)
        relative = safe_relative(attempt['output_dir'])
        pin = copy.deepcopy(request['inputs']['media'])
        path = self.runtime.artifact_path(request['project_id'], pin)
        from ..assets import _local_file, _identity
        try:
            # Read a bounded exact pin before handing any path to a media parser.
            with _local_file(str(path)) as stream:
                before = _identity(stream)
                if before[2] > MAX_BYTES:
                    raise ContractError('INVALID_ARGUMENT', 'Probe source exceeds 16 MiB bound.')
                payload = stream.read(MAX_BYTES + 1)
                if _identity(stream) != before or len(payload) > MAX_BYTES:
                    raise ContractError('ASSET_CHANGED', 'Probe source changed while staging.')
            if 'sha256:' + hashlib.sha256(payload).hexdigest() != pin['sha256']:
                raise ContractError('ASSET_CHANGED', 'Probe source bytes differ from frozen artifact pin.')
            with fs.directory(relative, create=True) as directory:
                def create(name, data=None):
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
                    target = os.fdopen(fd, 'wb')
                    if data is not None:
                        with target:
                            target.write(data)
                            target.flush()
                            os.fsync(target.fileno())
                    return target
                create('probe-input.bin', payload)
                staged = fs.root / relative / 'probe-input.bin'
                flags = ['-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMATS,
                         '-max_alloc', '67108864', '-probesize', str(MAX_BYTES), '-analyzeduration', '10000000']
                # Disk sinks avoid accumulating unbounded subprocess output in memory.
                with create('probe-stdout.json') as stdout:
                    completed = context.run([probe, '-v', 'error', *flags,
                        '-show_program_version', '-show_streams', '-show_format', '-of', 'json',
                        str(staged)], timeout=remaining(), stdout=stdout, stderr=subprocess.DEVNULL)
                if completed.returncode != 0:
                    raise ContractError('OUTPUT_INVALID', 'ffprobe could not parse the staged media.')
                raw_path = fs.root / relative / 'probe-stdout.json'
                if raw_path.stat().st_size > MAX_REPORT_BYTES:
                    raise ContractError('OUTPUT_INVALID', 'ffprobe report exceeds bounded report size.')
                raw = json.loads(raw_path.read_bytes())
                version = raw.get('program_version', {}).get('version')
                if not isinstance(version, str) or not version:
                    raise ContractError('OUTPUT_INVALID', 'ffprobe did not report its actual version.')
                streams = [_stream(s) for s in raw.get('streams', [])]
                if not streams:
                    raise ContractError('OUTPUT_INVALID', 'No media streams observed.')
                rotations = []
                for s in raw['streams']:
                    if s.get('codec_type') != 'video':
                        continue
                    values = [d['rotation'] for d in s.get('side_data_list', []) if 'rotation' in d]
                    if 'rotate' in s.get('tags', {}):
                        values.append(s['tags']['rotate'])
                    rotations.extend(_integer(v) for v in values)
                rotation = rotations[0] if rotations and rotations[0] is not None and all(r == rotations[0] for r in rotations) else None
                decode = 'not_run'
                if request['parameters'].get('full_decode', False):
                    if not any(s['type'] in ('video', 'audio') for s in streams):
                        raise ContractError('OUTPUT_INVALID', 'Full decode requires a video/audio stream.')
                    decoded = context.run([shutil.which('ffmpeg'), '-nostdin', '-v', 'error',
                        '-xerror', *flags, '-threads', '1', '-i', str(staged),
                        '-map', '0:v?', '-map', '0:a?', '-threads', '1', '-f', 'null', '-'],
                        timeout=remaining(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    decode = 'pass' if decoded.returncode == 0 else 'fail'
                receipt = dict(schema='motion/v1/probe-receipt', receipt_id=_id('rcp'),
                    artifact=pin, tool='ffprobe', tool_version=version, observed_at=_now(),
                    has_video=any(s['type'] == 'video' for s in streams),
                    has_audio=any(s['type'] == 'audio' for s in streams), streams=streams,
                    rotation_degrees=rotation, vfr='unknown', full_decode=decode,
                    measurements=[], logs_ref=None)
                report = canonical(receipt)
                create('report.json', report)
                return _result([dict(port='report', relative_path='report.json',
                    media_type='application/json',
                    claimed_sha256='sha256:' + hashlib.sha256(report).hexdigest())])
        except (ContractError, OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return _result([], dict(code=getattr(exc, 'code', 'OUTPUT_INVALID'),
                message=str(exc), retry='after_input_change', effect='none', details={}))
