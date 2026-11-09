"""Streaming evidence helpers for large immutable output snapshots."""
import array
import hashlib
import io
import sys


class BufferReader(io.RawIOBase):
    """Seek a bytes/mmap buffer without first copying the entire media file."""
    def __init__(self, payload):
        super().__init__()
        self.payload, self.position = payload, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else len(self.payload) + offset
        if position < 0:
            raise ValueError('Negative media buffer offset')
        self.position = position
        return position

    def read(self, size=-1):
        end = len(self.payload) if size < 0 else min(len(self.payload), self.position + size)
        result = self.payload[self.position:end]
        self.position = end
        return result


def pcm_facts(stream, channels):
    """Exact little-endian PCM16 hash/count/peak/nonzero facts, 1 MiB blocks."""
    checksum, length, peak, nonzero = hashlib.sha256(), 0, 0, 0
    while True:
        raw = stream.read(1024 * 1024)
        if not raw:
            break
        if len(raw) % (2 * channels):
            raise ValueError('Incomplete PCM16 sample frame')
        checksum.update(raw)
        length += len(raw)
        samples = array.array('h', raw)
        if sys.byteorder != 'little':
            samples.byteswap()
        peak = max(peak, max(abs(value) for value in samples))
        nonzero += sum(value != 0 for value in samples)
    return dict(decoded_samples=length // (2 * channels), pcm_sha256='sha256:' + checksum.hexdigest(),
                peak_pcm16=peak, nonzero_samples=nonzero)
