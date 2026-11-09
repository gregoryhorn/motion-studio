"""Explicit, bounded dialogue post through the existing owned finishing worker.

Only PCM16 mono/stereo WAV is accepted. Ducking returns music, not a mixed bus.
No speech inference, presets, loudness normalization, models or downloads.
"""
import math
import re
import shutil
import struct
import subprocess
import wave
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import ffmpeg

# All controls are required, including explicit null/empty bypass decisions.
CLEANUP_KEYS = {'denoise', 'highpass_hz', 'lowpass_hz', 'eq', 'compressor'}
COMPRESSOR_KEYS = {'threshold_db', 'ratio', 'attack_ms', 'release_ms', 'knee_db'}
MAX_SECONDS = 3600


def number(value, low, high):
    """Accept contract decimal strings only; never interpolated engine syntax."""
    if not isinstance(value, str) or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value) or len(value) > 32:
        raise ValueError('Processor controls require bounded plain decimal strings')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Invalid processor decimal') from exc
    if not result.is_finite() or not Decimal(str(low)) <= result <= Decimal(str(high)):
        raise ValueError('Processor control outside finite bounds')
    return result


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('Exact explicit dialogue parameter closure required')


def _compressor(value, makeup=False):
    _keys(value, COMPRESSOR_KEYS | ({'makeup_db'} if makeup else set()))
    limits = {'threshold_db': (-60, 0), 'ratio': (1, 20), 'attack_ms': (0.1, 200),
              'release_ms': (10, 2000), 'knee_db': (0, 18)}
    if makeup:
        limits['makeup_db'] = (0, 12)
    return {key: number(value[key], *bounds) for key, bounds in limits.items()}


def validate_parameters(operation, parameters):
    if operation == 'audio.cleanup@1':
        _keys(parameters, CLEANUP_KEYS)
        denoise = parameters['denoise']
        if denoise is not None:
            _keys(denoise, {'reduction_db', 'noise_floor_db'})
            number(denoise['reduction_db'], 0.01, 30)
            number(denoise['noise_floor_db'], -80, -20)
        for key, low, high in [('highpass_hz', 20, 1000), ('lowpass_hz', 1000, 20000)]:
            if parameters[key] is not None:
                number(parameters[key], low, high)
        if (parameters['highpass_hz'] is not None and parameters['lowpass_hz'] is not None
                and Decimal(parameters['highpass_hz']) >= Decimal(parameters['lowpass_hz'])):
            raise ValueError('Highpass must be below lowpass')
        if not isinstance(parameters['eq'], list) or len(parameters['eq']) > 8:
            raise ValueError('At most eight explicit EQ bands supported')
        for band in parameters['eq']:
            _keys(band, {'frequency_hz', 'gain_db', 'q'})
            number(band['frequency_hz'], 20, 20000)
            number(band['gain_db'], -18, 18)
            number(band['q'], 0.1, 10)
        if parameters['compressor'] is not None:
            _compressor(parameters['compressor'], makeup=True)
    elif operation == 'audio.duck@1':
        _compressor(parameters)
    else:
        raise ValueError('Unsupported dialogue operation')


def _linear(db):
    return format(10 ** (float(db) / 20), '.15g')


def _compressor_chain(values):
    settings = _compressor(values, makeup='makeup_db' in values)
    chain = (f"threshold={_linear(settings['threshold_db'])}:ratio={settings['ratio']}:"
             f"attack={settings['attack_ms']}:release={settings['release_ms']}:"
             f"knee={_linear(settings['knee_db'])}:detection=rms:link=maximum:mix=1")
    return chain + ':makeup=' + _linear(settings.get('makeup_db', Decimal(0)))


def cleanup_chain(parameters, rate):
    validate_parameters('audio.cleanup@1', parameters)
    chain = []
    denoise = parameters['denoise']
    if denoise is not None:
        chain.append(f"afftdn=nr={denoise['reduction_db']}:nf={denoise['noise_floor_db']}:tn=0:tr=0")
    for key, name in [('highpass_hz', 'highpass'), ('lowpass_hz', 'lowpass')]:
        frequency = parameters[key]
        if frequency is not None:
            if Decimal(frequency) >= Decimal(rate) / 2:
                raise ValueError('Filter frequency must be strictly below source Nyquist')
            chain.append(f'{name}=f={frequency}:p=2')
    for band in parameters['eq']:
        if Decimal(band['frequency_hz']) >= Decimal(rate) / 2:
            raise ValueError('EQ frequency must be strictly below source Nyquist')
        chain.append(f"equalizer=f={band['frequency_hz']}:t=q:w={band['q']}:g={band['gain_db']}")
    if parameters['compressor'] is not None:
        chain.append('acompressor=' + _compressor_chain(parameters['compressor']))
    return ','.join(chain or ['anull'])


def _run(context, argv):
    if not callable(getattr(context, 'run', None)):
        raise ValueError('Owned process runner required')
    result = context.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    # Retain the check at this boundary even when a runner ignores check=True.
    result.check_returncode()
    return result


def measure(path) -> dict[str, Any]:
    """Streaming decoded PCM peak/RMS and one-second windows; silence stays finite."""
    try:
        with wave.open(str(path), 'rb') as source:
            channels, width, rate, count, compression, _ = source.getparams()
            if (width != 2 or channels not in (1, 2) or not 8000 <= rate <= 48000
                    or not 0 < count <= rate * MAX_SECONDS or compression != 'NONE'):
                raise ValueError('Dialogue processing requires bounded 8–48kHz mono/stereo PCM16 WAV')
            windows, total_square, peak, decoded = [], 0, 0, 0
            while decoded < count:
                data = source.readframes(min(rate, count - decoded))
                if not data or len(data) % (2 * channels):
                    raise ValueError('Incomplete PCM source')
                values = struct.iter_unpack('<h', data)
                square, local_peak = 0, 0
                for (value,) in values:
                    square += value * value
                    local_peak = max(local_peak, abs(value))
                samples = len(data) // (2 * channels)
                windows.append(dict(start_sample=decoded, duration_samples=samples,
                                    rms=math.sqrt(square / (samples * channels)) / 32768,
                                    peak=local_peak / 32768))
                decoded += samples
                total_square += square
                peak = max(peak, local_peak)
            if decoded != count:
                raise ValueError('Decoded PCM count differs from WAV header')
    except (wave.Error, EOFError) as exc:
        raise ValueError('Valid bounded PCM16 WAV required') from exc
    return dict(sample_rate_hz=rate, channels=channels, channel_layout='mono' if channels == 1 else 'stereo',
                presentation_samples=count, peak=peak / 32768,
                rms=math.sqrt(total_square / (count * channels)) / 32768, windows=windows)


def _clock(measurement):
    return tuple(measurement[key] for key in ('sample_rate_hz', 'channels', 'presentation_samples'))


def _engine(context) -> dict[str, Any]:
    executable = shutil.which('ffmpeg')
    if not executable:
        raise ValueError('FFmpeg is not available; no installation is attempted')
    path = Path(executable).resolve()
    identity = ffmpeg.digest(path)
    version = _run(context, [str(path), '-version']).stdout.decode('utf-8', errors='replace')
    return dict(executable=str(path), executable_sha256=identity, version=version)


def _process(context, operation, sources, target, parameters) -> dict[str, Any]:
    validate_parameters(operation, parameters)
    before = {key: measure(path) for key, path in sources.items()}
    main = 'audio' if operation == 'audio.cleanup@1' else 'music'
    rate, channels, count = _clock(before[main])
    if operation == 'audio.duck@1' and _clock(before['speech']) != (rate, channels, count):
        raise ValueError('Speech/music stems must have identical rate, layout and sample count; no implicit resampling/padding')
    hashes = {key: ffmpeg.digest(path) for key, path in sources.items()}
    if operation == 'audio.cleanup@1':
        chain = cleanup_chain(parameters, rate)
    else:
        # Explicitly buffer/reframe both inputs before sidechaincompress: direct
        # decoder inputs can signal EOF while the other stem still has queued
        # frames, dropping its tail. p=0 preserves the real final partial frame;
        # neither durations nor samples are padded, trimmed or regenerated.
        chain = ('[0:a:0]asetnsamples=n=1024:p=0[music];'
                 '[1:a:0]asetnsamples=n=1024:p=0[speech];'
                 '[music][speech]sidechaincompress=' + _compressor_chain(parameters) + '[ducked]')
    engine = _engine(context)
    command = [engine['executable'], '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(sources[main])]
    if operation == 'audio.cleanup@1':
        command += ['-map', '0:a:0', '-af', chain]
    else:
        # The second (speech-only) stem is the sole detector. It is NOT mixed in.
        command += ['-i', str(sources['speech'])]
        command += ['-filter_complex', chain, '-map', '[ducked]']
    command += ['-vn', '-ar', str(rate), '-ac', str(channels), '-c:a', 'pcm_s16le', str(target)]
    # Some FFmpeg builds return zero for -n refusing an existing output. Never
    # mistake that refusal for processing, or measure/publish pre-existing bytes.
    if Path(target).exists() or Path(target).is_symlink():
        raise subprocess.CalledProcessError(1, command, stderr=b'Output already exists; refusing to overwrite')
    _run(context, command)
    after = measure(target)
    if _clock(after) != (rate, channels, count):
        raise ValueError('Processing changed sample rate, channel layout or sample count')
    if ffmpeg.digest(Path(engine['executable'])) != engine['executable_sha256']:
        raise ValueError('FFmpeg executable changed during processing')
    if any(ffmpeg.digest(path) != hashes[key] for key, path in sources.items()):
        raise ValueError('Dialogue source changed during processing')
    return dict(schema='motion/v1/dialogue-post', operation=operation, parameters=parameters,
                engine=engine, processing_chain=chain, argv=command,
                sources={key: dict(sha256=hashes[key], measurement=before[key]) for key in sources},
                output=dict(sha256=ffmpeg.digest(target), measurement=after),
                output_role='cleaned_dialogue' if main == 'audio' else 'ducked_music_only',
                measurement_method='decoded_pcm16_linear_full_scale_peak_rms_one_second_windows',
                limits='Signal measurements do not establish subjective intelligibility; normalization is a separate selected operation.')


def cleanup(context, source, target, parameters) -> dict[str, Any]:
    return _process(context, 'audio.cleanup@1', {'audio': source}, target, parameters)


def duck(context, music, speech, target, parameters) -> dict[str, Any]:
    return _process(context, 'audio.duck@1', {'music': music, 'speech': speech}, target, parameters)
