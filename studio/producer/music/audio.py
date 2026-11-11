"""Bounded native RIFF decode and disclosed PCM16 encoding, stdlib only."""
import io
import math
import struct
import wave
from ...domain import Fault, MAX_BYTES


def decode(data, frames):
    if len(data) > MAX_BYTES: raise Fault('FILE_TOO_LARGE', 413)
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise Fault('MUSIC_NATIVE_FORMAT')
    if struct.unpack_from('<I', data, 4)[0] + 8 != len(data): raise Fault('TRUNCATED_OR_TRAILING_WAV')
    pos, fmt, pcm = 12, None, None
    while pos < len(data):
        if pos + 8 > len(data): raise Fault('TRUNCATED_CHUNK')
        tag, size = struct.unpack_from('<4sI', data, pos)
        start, end = pos + 8, pos + 8 + size
        if end + size % 2 > len(data): raise Fault('TRUNCATED_CHUNK')
        if tag == b'fmt ':
            if fmt is not None or size != 16: raise Fault('MUSIC_NATIVE_FORMAT')
            fmt = struct.unpack_from('<HHIIHH', data, start)
        elif tag == b'data':
            if pcm is not None: raise Fault('DUPLICATE_DATA')
            pcm = data[start:end]
        pos = end + size % 2
    if fmt is None or pcm is None: raise Fault('MISSING_WAV_CHUNK')
    encoding, channels, rate, byte_rate, align, bits = fmt
    if (channels != 2 or rate != 48000 or align != channels * bits // 8 or
            byte_rate != rate * align or len(pcm) != frames * align or
            not ((encoding == 1 and bits in (16, 24, 32)) or (encoding == 3 and bits in (32, 64)))):
        raise Fault('MUSIC_NATIVE_FORMAT')
    return pcm, encoding, bits


def pcm16(data, frames):
    pcm, encoding, bits = decode(data, frames)
    result = bytearray()
    width = bits // 8
    for offset in range(0, len(pcm), width):
        if encoding == 3:
            value = struct.unpack_from('<f' if bits == 32 else '<d', pcm, offset)[0]
            if not math.isfinite(value): raise Fault('MUSIC_NONFINITE')
            clipped = abs(value) >= 1
        else:
            integer = int.from_bytes(pcm[offset:offset + width], 'little', signed=True)
            bound = 1 << (bits - 1)
            value = integer / bound
            clipped = integer in (-bound, bound - 1)
        if clipped: raise Fault('MUSIC_CLIPPED')
        encoded = round(value * 32768)
        if not -32767 <= encoded <= 32766: raise Fault('MUSIC_PCM16_CLIPPED')
        result.extend(struct.pack('<h', encoded))
    target = io.BytesIO()
    with wave.open(target, 'wb') as writer:
        writer.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
        writer.writeframes(result)
    derivative = target.getvalue()
    if len(derivative) > MAX_BYTES: raise Fault('FILE_TOO_LARGE', 413)
    return derivative, dict(encoding='IEEE_FLOAT' if encoding == 3 else 'PCM', bits=bits,
                            channels=2, rate=48000, frames=frames, bytes=len(data))
