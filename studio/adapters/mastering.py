"""Explicit local audio mastering and straight-alpha ProRes export primitives."""
import json
import math
import subprocess
import wave
from decimal import Decimal
from fractions import Fraction
from typing import Any

from . import ffmpeg, rates


def _run(context, argv):
    return context.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def loudness(context, path, filters=''):
    chain = (filters + ',' if filters else '') + 'loudnorm=print_format=json'
    command = ['ffmpeg', '-nostdin', '-v', 'info', '-xerror', '-i', str(path),
               '-map', '0:a:0', '-vn', '-af', chain, '-f', 'null', '-']
    result = _run(context, command)
    text = result.stderr.decode('utf-8')
    report, _ = json.JSONDecoder().raw_decode(text[text.rindex('{'):])
    for key in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset'):
        if not Decimal(str(report[key])).is_finite():
            raise ValueError('Silence/nonfinite audio cannot satisfy a finite mastering target')
    return report


def normalize(context, source, target, parameters):
    """Two-pass EBU R128 normalization, then independently measure actual PCM."""
    integrated = Decimal(parameters['loudness_lufs'])
    ceiling = Decimal(parameters['true_peak_dbtp'])
    tolerance = Decimal(parameters['tolerance_lu'])
    if (not all(x.is_finite() for x in (integrated, ceiling, tolerance))
            or not Decimal('-70') <= integrated <= Decimal('-5')
            or not Decimal('-9') <= ceiling <= Decimal('0') or not 0 <= tolerance <= 2):
        raise ValueError('Mastering targets outside loudnorm bounds')
    with wave.open(str(source), 'rb') as wav:
        channels, width, rate, count, compression, _ = wav.getparams()
        if (width != 2 or channels not in (1, 2) or not 0 < rate <= 48000
                or not 0 < count <= rate * rates.MAX_SECONDS or compression != 'NONE'):
            raise ValueError('Mastering requires bounded mono/stereo PCM16 WAV')
    # Leave an explicit quantization guard below the requested hard ceiling.
    processing_peak = max(Decimal('-9'), ceiling - Decimal('0.1'))
    settings = f'I={integrated}:TP={processing_peak}:LRA=11'
    # Analyze with the SAME targets used by the processing pass.
    result = _run(context, ['ffmpeg', '-nostdin', '-v', 'info', '-xerror', '-i', str(source),
        '-af', f'loudnorm={settings}:print_format=json', '-f', 'null', '-'])
    log = result.stderr.decode('utf-8')
    first, _ = json.JSONDecoder().raw_decode(log[log.rindex('{'):])
    if any(not Decimal(str(first[k])).is_finite() for k in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')):
        raise ValueError('Normalization analysis produced nonfinite measurements')
    measured = ':'.join(f'{key}={first[value]}' for key, value in (
        ('measured_I', 'input_i'), ('measured_TP', 'input_tp'),
        ('measured_LRA', 'input_lra'), ('measured_thresh', 'input_thresh'), ('offset', 'target_offset')))
    filters = (f'loudnorm={settings}:{measured}:linear=true,aresample={rate},'
               f'atrim=end_sample={count},asetpts=PTS-STARTPTS')
    _run(context, ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(source),
        '-map', '0:a:0', '-vn', '-af', filters, '-ar', str(rate), '-ac', str(channels),
        '-c:a', 'pcm_s16le', str(target)])
    with wave.open(str(target), 'rb') as wav:
        if wav.getparams()[:5] != (channels, width, rate, count, compression):
            raise ValueError('Normalization changed the original PCM sample clock or duration')
    final = loudness(context, target)
    if abs(Decimal(final['input_i']) - integrated) > tolerance or Decimal(final['input_tp']) > ceiling:
        raise ValueError('Actual normalized PCM fails requested loudness or hard true-peak ceiling')
    return dict(schema='motion/v1/audio-normalization', source_sha256=ffmpeg.digest(source),
        output_sha256=ffmpeg.digest(target), parameters=parameters, processing_peak_dbtp=str(processing_peak),
        source_measurement=first, output_measurement=final, presentation_samples=count,
        sample_rate_hz=rate, channels=channels, method='ffmpeg.loudnorm.two_pass_then_remeasure')


def alpha_statistics(context, path):
    """Decode EVERY alpha plane; a pixel-format tag is not alpha evidence."""
    result = _run(context, ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
        '-map', '0:v:0', '-an', '-vf',
        'alphaextract,scale=in_range=full:out_range=full:flags=bitexact,format=yuv444p16le,'
        'signalstats,metadata=mode=print:key=lavfi.signalstats.YMIN:file=-,'
        'metadata=mode=print:key=lavfi.signalstats.YMAX:file=-',
        '-f', 'null', '-'])
    minima, maxima = [], []
    for line in result.stdout.decode('utf-8').splitlines():
        if line.startswith('lavfi.signalstats.YMIN='):
            minima.append(int(float(line.split('=', 1)[1])))
        elif line.startswith('lavfi.signalstats.YMAX='):
            maxima.append(int(float(line.split('=', 1)[1])))
    if not minima or len(minima) != len(maxima):
        raise ValueError('No complete decoded alpha-plane statistics')
    return dict(decoded_alpha_frames=len(minima), alpha_min=min(minima), alpha_max=max(maxima),
                normalized_bit_depth=16, range='full',
                method='ffmpeg.alphaextract.full_range_16bit.signalstats.every_frame')


def alpha_difference(context, source, target):
    """Compare every decoded alpha pixel by frame index in a common 16-bit domain."""
    filters = ('[0:v:0]alphaextract,format=gray16le,settb=1/1,setpts=N[a];'
               '[1:v:0]alphaextract,format=gray16le,settb=1/1,setpts=N[b];'
               '[a][b]blend=all_mode=difference:shortest=1,'
               'scale=in_range=full:out_range=full:flags=bitexact,format=yuv444p16le,'
               'signalstats,metadata=mode=print:key=lavfi.signalstats.YMAX:file=-')
    result = _run(context, ['ffmpeg', '-nostdin', '-v', 'error', '-xerror',
        '-i', str(source), '-i', str(target), '-filter_complex', filters, '-an', '-f', 'null', '-'])
    maxima = [int(float(line.split('=', 1)[1])) for line in result.stdout.decode('utf-8').splitlines()
              if line.startswith('lavfi.signalstats.YMAX=')]
    if not maxima:
        raise ValueError('No decoded alpha comparison frames')
    return dict(compared_frames=len(maxima), max_absolute_error_16bit=max(maxima),
                tolerance_16bit=128, method='decoded_frame_index_every_pixel_full_range_16bit')


def alpha_encode(context, source, target, variant) -> dict[str, Any]:
    """Selected final master: silent straight-alpha ProRes 4444 MOV, not MP4."""
    if (variant['container'] != 'mov' or variant['video_codec'] != 'prores'
            or variant['pixel_format'] != 'yuva444p12le' or variant['alpha'] != 'straight'
            or variant['audio']['mode'] != 'none' or variant['captions'] != 'none'
            or variant['color'] != dict(primaries='bt709', transfer='bt709', matrix='bt709', range='limited')):
        raise ValueError('Alpha route requires straight ProRes 4444 MOV, silent, caption-free BT.709 limited')
    w, h, count = variant['width_px'], variant['height_px'], variant['duration_frames']
    rates.bounds(w, h, count, variant['rate'])
    facts = json.loads(_run(context, ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)]).stdout)
    streams = facts['streams']
    if len(streams) != 1:
        raise ValueError('Alpha export requires a silent single video source')
    stream = streams[0]
    if (stream.get('pix_fmt') not in ('rgba', 'bgra', 'argb', 'abgr', 'gbrap', 'gbrap16le', 'yuva444p10le', 'yuva444p12le')
            or (stream['width'], stream['height']) != (w, h)
            or rates.observed(stream) != rates.fraction(variant['rate'])):
        raise ValueError('Source must already have explicit alpha, matching canvas and exact cadence')
    before = alpha_statistics(context, source)
    if before['decoded_alpha_frames'] != count:
        raise ValueError('Source alpha frame count differs from frozen master range')
    _run(context, ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(source),
        '-map', '0:v:0', '-an', '-c:v', 'prores_ks', '-profile:v', '4', '-alpha_bits', '16',
        '-pix_fmt', 'yuva444p10le', '-threads', '1', '-r', rates.text(variant['rate']),
        '-video_track_timescale', str(variant['rate']['num']),
        '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
        '-metadata', 'motion_alpha_mode=straight', '-movflags', '+faststart', str(target)])
    after = alpha_statistics(context, target)
    if after['decoded_alpha_frames'] != count:
        raise ValueError('Encoded master lost alpha frames')
    if before['alpha_min'] < before['alpha_max'] and after['alpha_min'] >= after['alpha_max']:
        raise ValueError('Encoded master flattened nonuniform source alpha')
    comparison = alpha_difference(context, source, target)
    if int(comparison['compared_frames']) != count or int(comparison['max_absolute_error_16bit']) > int(comparison['tolerance_16bit']):
        raise ValueError('Encoded alpha differs beyond the explicit ProRes quantization tolerance')
    return dict(schema='motion/v1/alpha-master', source=before, output=after, alpha_mode='straight',
                alpha_comparison=comparison,
                output_sha256=ffmpeg.digest(target), codec='prores_ks', profile='4444')
