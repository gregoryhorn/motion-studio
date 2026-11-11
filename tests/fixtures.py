"""Non-private test fixtures, not generated media or claimed listening evidence."""
import hashlib
import io
import math
import struct
import wave
from studio.persistence.store import identity


def wav(rate=44100, channels=1, seconds=0.2):
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(rate)
        data = b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 440 * n / rate)))
                        * channels for n in range(int(rate * seconds)))
        target.writeframes(data)
    return output.getvalue()


def intent_payload(request, data, name="non-private-tone.wav"):
    return dict(command=identity(), request=request["id"], revision=request["revision"],
                digest=hashlib.sha256(data).hexdigest(), size=len(data), name=name)
