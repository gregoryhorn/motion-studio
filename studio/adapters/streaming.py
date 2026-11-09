"""Frame-bounded raster composition and block-bounded exact PCM mixing."""
import array
import hashlib
import math
import os
import sys
import tempfile
import wave
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from . import rates


def mix(inputs, parameters, resolve, target, timeline):
    """Publish only a complete validated mix, never a partial WAV on failure."""
    target = Path(target)
    if target.exists():
        raise ValueError('Mix target already exists')
    descriptor, name = tempfile.mkstemp(prefix='.mix-', suffix='.wav', dir=target.parent)
    os.close(descriptor)
    staged = Path(name)
    try:
        receipt = _mix(inputs, parameters, resolve, staged, timeline)
        # An exclusive link preserves any target created concurrently.
        os.link(staged, target)
        return receipt
    finally:
        staged.unlink(missing_ok=True)


def _mix(inputs, parameters, resolve, target, timeline):
    channels, rate, count = (parameters[k] for k in ('channels', 'sample_rate', 'duration_samples'))
    cadence = rates.fraction(parameters.get('rate', '30'))
    if (channels not in (1, 2) or not 0 < rate <= 48000 or not 0 < count <= rate * rates.MAX_SECONDS
            or Fraction(count, rate) != Fraction(timeline['duration_frames'], 1) / cadence
            or parameters['loudness_lufs'] is not None or parameters['true_peak_dbtp'] is not None):
        raise ValueError('Exact mono/stereo PCM16 sample clock required; use audio.normalize for mastering')
    items = [i for t in timeline['tracks'] if t['kind'] == 'audio' for i in t['items']]
    if not 1 <= len(items) <= 256:
        raise ValueError('One to 256 explicit audio intervals required')
    intervals, used, sources = [], [], []
    with ExitStack() as stack:
        for item in items:
            if set(item) - {'item_id', 'start_frame', 'end_frame', 'subject', 'source_in', 'gain_db'}:
                raise ValueError('Unsupported audio cue fields')
            pin = item['subject'].get('artifact')
            point = item.get('source_in')
            gain = float(item.get('gain_db', '0'))
            if item['subject']['kind'] != 'artifact' or pin not in inputs['audio']:
                raise ValueError('Cue source not in explicit input closure')
            if (not point or point['domain'] != 'sample' or point['index'] < 0
                    or point['rate'] != dict(num=rate, den=1) or point['origin'] != 'source'
                    or point['source_artifact'] != pin or not math.isfinite(gain) or not -96 <= gain <= 12):
                raise ValueError('Explicit source sample origin and bounded gain required')
            lo, hi = (rates.samples(item[key], cadence, rate) for key in ('start_frame', 'end_frame'))
            if not 0 <= lo < hi <= count:
                raise ValueError('Cue interval outside exact output samples')
            wav = stack.enter_context(wave.open(str(resolve(pin)), 'rb'))
            if ((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (channels, 2, rate)
                    or point['index'] + hi - lo > wav.getnframes()):
                raise ValueError('Explicit matching PCM16 source interval required')
            sources.append((wav, lo, hi, point['index'], 10 ** (gain / 20)))
            intervals.append(dict(item_id=item['item_id'], source=pin, source_start_sample=point['index'],
                source_end_sample=point['index'] + hi - lo, output_start_sample=lo, output_end_sample=hi,
                gain_db=item.get('gain_db', '0')))
            if pin not in used:
                used.append(pin)
        if any(pin not in used for pin in inputs['audio']):
            raise ValueError('Unaccounted audio input')
        pcm_hash = hashlib.sha256()
        output = stack.enter_context(wave.open(str(target), 'wb'))
        output.setparams((channels, 2, rate, count, 'NONE', 'not compressed'))
        for start in range(0, count, 4096):
            end = min(start + 4096, count)
            mixed = array.array('d', [0.0]) * ((end - start) * channels)
            for wav, lo, hi, source_in, gain in sources:
                a, b = max(start, lo), min(end, hi)
                if a >= b:
                    continue
                wav.setpos(source_in + a - lo)
                values = array.array('h', wav.readframes(b - a))
                if sys.byteorder != 'little':
                    values.byteswap()
                if len(values) != (b - a) * channels:
                    raise ValueError('Truncated PCM source')
                for offset, value in enumerate(values, (a - start) * channels):
                    mixed[offset] += value * gain
            if any(v < -32768 or v > 32767 for v in mixed):
                raise ValueError('Mix would clip; lower explicit stem gains')
            pcm = array.array('h', (round(v) for v in mixed))
            if sys.byteorder != 'little':
                pcm.byteswap()
            payload = pcm.tobytes()
            output.writeframesraw(payload)
            pcm_hash.update(payload)
    receipt = dict(schema='motion/v1/local-audio-cues', timeline=timeline, parameters=parameters,
        intervals=intervals, sources=used, duration_samples=count, pcm_sha256='sha256:' + pcm_hash.hexdigest())
    if len(intervals) == 1:
        receipt.update({k: v for k, v in intervals[0].items() if k not in ('item_id', 'gain_db')})
    return receipt


def captions(background, target, caption, placement, style, font, *, start, end, preview, save_preview):
    """Decode/render/encode one frame at a time, with exact seek-free parity."""
    import av
    from . import caption_render
    cadence = rates.fraction(placement['output_rate'])
    with av.open(str(background)) as incoming, av.open(str(target), 'w', format='matroska') as outgoing:
        if len(incoming.streams) != 1 or incoming.streams[0].type != 'video':
            raise ValueError('Caption background must be silent single video')
        source = incoming.streams.video[0]
        nominal = rates.observed(dict(r_frame_rate=str(source.average_rate),
            codec_name=source.codec_context.name,tags=source.metadata)) if source.average_rate else None
        if nominal != cadence:
            raise ValueError('Caption background cadence differs from placement')
        encoder = outgoing.add_stream('ffv1', rate=cadence)
        encoder.width, encoder.height = source.width, source.height
        encoder.pix_fmt = 'bgr0'
        encoder.codec_context.thread_count = 1
        encoder.metadata['motion_rate'] = rates.text(cadence)
        outgoing.metadata.update(motion_caption_sha256=__import__('studio.contracts', fromlist=['digest']).digest(caption),
                                 motion_renderer_sha256=caption_render.fingerprint())
        actual = 0
        for index, frame in enumerate(incoming.decode(source)):
            if index >= end:
                raise ValueError('Background contains frames outside requested full range')
            if index < start:
                continue
            image = caption_render.render_frame(caption, placement, style, index, frame.to_image().convert('RGB'), font)
            if index == preview:
                save_preview(image)
            output = av.VideoFrame.from_image(image)
            output.pts = index - start
            output.time_base = Fraction(1, 1) / cadence
            for packet in encoder.encode(output):
                outgoing.mux(packet)
            actual += 1
        if actual != end - start:
            raise ValueError('Truncated caption background')
        for packet in encoder.encode():
            outgoing.mux(packet)
