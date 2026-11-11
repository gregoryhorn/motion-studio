"""Timed collection fixtures; deliberately separate from short import fixtures."""
import io
import shutil
import subprocess
import wave
from tests.media_import_fixtures import encoded as imported_image


def wav(seconds=0.5):
    target = io.BytesIO()
    with wave.open(target, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44100)
        output.writeframes(b'\x00\x00' * int(44100 * seconds))
    return target.getvalue()


def encoded(format, seconds=0.5):
    if format != 'mp4':
        return imported_image(format)
    return subprocess.run([shutil.which('ffmpeg'), '-hide_banner', '-v', 'error',
        '-f', 'lavfi', '-i', 'color=c=blue:s=32x24:r=10', '-threads', '1',
        '-t', str(seconds), '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p',
        '-movflags', 'frag_keyframe+empty_moov', '-f', 'mp4', 'pipe:1'],
        capture_output=True, timeout=15, check=True).stdout
