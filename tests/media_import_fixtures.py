"""Non-private synthetic import fixtures; no live files or generator calls."""
import io
import shutil
import struct
import subprocess
import tempfile
import wave
import zlib


def png(width=16, height=12):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    pixels = (b'\x00' + b'\x40\x80\xc0' * width) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def wav():
    target = io.BytesIO()
    with wave.open(target, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44100)
        output.writeframes(b'\x00\x00' * 4410)
    return target.getvalue()


def encoded(format):
    executable = shutil.which('ffmpeg')
    if not executable:
        raise RuntimeError('Installed ffmpeg required for controlled fixtures')
    args = [executable, '-hide_banner', '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=blue:s=32x24:r=10', '-threads', '1']
    if format == 'jpeg':
        args += ['-frames:v', '1', '-c:v', 'mjpeg', '-f', 'image2pipe', 'pipe:1']
    else:
        args += ['-t', '0.3', '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p',
                 '-movflags', 'frag_keyframe+empty_moov', '-f', 'mp4', 'pipe:1']
    result = subprocess.run(args, capture_output=True, timeout=15, check=True)
    return result.stdout


def seekable_mp4():
    """Ordinary non-faststart MP4 with its index after a multi-packet mdat."""
    with tempfile.TemporaryDirectory(prefix='motion-mp4-fixture-') as directory:
        from pathlib import Path
        target = Path(directory) / 'controlled.mp4'
        subprocess.run([shutil.which('ffmpeg'), '-hide_banner', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=24', '-t', '1',
            '-threads', '1', '-c:v', 'mpeg4', '-q:v', '2', str(target)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True)
        return target.read_bytes()
