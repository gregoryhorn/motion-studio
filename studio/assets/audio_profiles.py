"""Declared audio checks shared across adapters, never provider receipt schemas."""
import io
import math
import struct
import wave
from ..assets.wav import inspect_wav
from ..domain import Fault


def validate_audio(data, profile, frames):
    rates = {'stereo-44100-pcm16': 44100, 'stereo-48000-pcm16': 48000}
    if profile not in rates:
        raise Fault('UNSUPPORTED_FORMAT', 409)
    facts = inspect_wav(data)
    if (facts['channels'], facts['rate'], facts['frames']) != (2, rates[profile], frames):
        raise Fault('OUTPUT_FORMAT_MISMATCH')
    with wave.open(io.BytesIO(data), 'rb') as reader:
        pcm = reader.readframes(frames)
    samples = [value[0] for value in struct.iter_unpack('<h', pcm)]
    if profile == 'stereo-48000-pcm16' and any(x in (-32768, 32767) for x in samples):
        raise Fault('MUSIC_CLIPPED')
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768 if samples else 0
    if not samples or max(samples) == min(samples) or max(abs(x) for x in samples) < 2 or rms < 1e-6:
        raise Fault('OUTPUT_TRIVIAL')
    return facts
