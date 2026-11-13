"""Real deterministic media and explicit source-only checker test boundary."""
from contextlib import contextmanager
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from unittest.mock import patch
import wave
import zlib
from studio.director import process
from studio.director.review import crystal_ball

SOURCE = Path(__file__).resolve().parents[2] / 'crystal-ball'


def still():
    def chunk(kind, body):
        return struct.pack('>I', len(body))+kind+body+struct.pack('>I', zlib.crc32(kind+body))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>2I5B', 32, 32, 8, 2, 0, 0, 0))+
        chunk(b'IDAT', zlib.compress((b'\x00'+b'\x10\x80\xf0'*32)*32))+chunk(b'IEND', b''))


def audio(silent=False, clipped=False):
    out = io.BytesIO()
    with wave.open(out, 'wb') as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(44100)
        # A non-silent low-level square tone, no synthesis dependency.
        level = 32767 if clipped else 1000
        samples = [0 if silent else (level if n % 200 < 100 else -level) for n in range(44100)]
        target.writeframes(struct.pack('<'+str(len(samples))+'h', *samples))
    return out.getvalue()


def movie(with_audio):
    with tempfile.TemporaryDirectory(prefix='director-media-fixture-') as temporary:
        target = Path(temporary)/'fixture.mp4'
        command = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=15:duration=1']
        if with_audio:
            command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=1', '-c:a', 'aac']
        command += ['-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', '-y', str(target)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)
        return target.read_bytes()


@contextmanager
def source_checker():
    """No install or production source override: patch only launch environment/version.

    All subprocesses and report parsing/retention remain real. Production still
    rejects ambient PYTHONPATH and requires its installed pinned distribution.
    """
    real_call = process.call
    calls = []
    def launch(argv, *, cwd, env, timeout):
        calls.append(list(argv))
        result = real_call(argv, cwd=cwd, env=dict(env, PYTHONPATH=str(SOURCE)), timeout=timeout)
        if 'crystal_ball' in argv and result.returncode in (0, 1):
            assert len(result.stdout.strip()) <= 1500, 'Compact report exceeds contract'
        return result
    with patch.object(crystal_ball.importlib.metadata, 'version', return_value=crystal_ball.VERSION), patch.object(process, 'call', side_effect=launch):
        yield calls


def full(result):
    return next(json.loads(body) for name, body in result['assets'].items() if name.endswith('/full.json'))


AVAILABLE = SOURCE.joinpath('crystal_ball/core.py').is_file() and all(shutil.which(name) for name in ('ffmpeg', 'ffprobe'))
