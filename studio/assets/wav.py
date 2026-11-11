"""Bounded RIFF/WAVE PCM16 validation; never trust extension or MIME."""
import struct
from ..domain import Fault, MAX_BYTES


def inspect_wav(data):
    if len(data) > MAX_BYTES:
        raise Fault("FILE_TOO_LARGE", 413)
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise Fault("UNSUPPORTED_WAV")
    if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
        raise Fault("TRUNCATED_OR_TRAILING_WAV")
    pos, fmt, pcm = 12, None, None
    while pos < len(data):
        if pos + 8 > len(data):
            raise Fault("TRUNCATED_CHUNK")
        tag, size = struct.unpack_from("<4sI", data, pos)
        start, end = pos + 8, pos + 8 + size
        padded = end + size % 2
        if padded > len(data):
            raise Fault("TRUNCATED_CHUNK")
        if tag == b"fmt ":
            if fmt is not None or size != 16:
                raise Fault("UNSUPPORTED_FORMAT")
            fmt = struct.unpack_from("<HHIIHH", data, start)
        elif tag == b"data":
            if pcm is not None:
                raise Fault("DUPLICATE_DATA")
            pcm = size
        pos = padded
    if fmt is None or pcm is None:
        raise Fault("MISSING_WAV_CHUNK")
    encoding, channels, rate, byte_rate, align, bits = fmt
    if encoding != 1 or bits != 16 or channels not in (1, 2) or rate not in (44100, 48000):
        raise Fault("UNSUPPORTED_FORMAT")
    if align != channels * 2 or byte_rate != rate * align or not pcm or pcm % align:
        raise Fault("INVALID_PCM")
    frames = pcm // align
    duration = frames / rate
    if not 0 < duration <= 47:
        raise Fault("DURATION_LIMIT")
    return dict(duration=duration, rate=rate, channels=channels, frames=frames)
