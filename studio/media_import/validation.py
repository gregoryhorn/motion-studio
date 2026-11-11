"""Bounded original-byte validation using installed FFmpeg, never conversion."""
import json
import math
import shutil
import subprocess

from ..child_env import child_environment
import tempfile
from ..assets.wav import inspect_wav
from ..domain import Fault, MAX_BYTES
from ..media_import.containers import check_png, check_mp4
from ..media_import.contracts import MIME

DEMUX = {'png': 'png_pipe', 'jpeg': 'jpeg_pipe', 'mp4': 'mov'}
MAX_PIXELS = 4096 * 4096
MAX_SECONDS = 47


def codec_call(tool, arguments, data):
    executable = shutil.which(tool)
    if not executable:
        raise Fault('MEDIA_VALIDATOR_UNAVAILABLE', 409)
    try:
        # Anonymous seekable input also supports ordinary MP4s whose moov index
        # follows mdat. A pipe cannot seek back to those already consumed frames.
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
            source.write(data)
            source.seek(0)
            result = subprocess.run([executable, '-hide_banner', '-v', 'error', *arguments],
                                    stdin=source, stdout=output, stderr=subprocess.DEVNULL, timeout=20,
                                    env=child_environment('helper'))
            output.seek(0)
            body = output.read(65537)
    except (OSError, subprocess.TimeoutExpired):
        raise Fault('MEDIA_VALIDATION_FAILED') from None
    if result.returncode or len(body) > 65536:
        raise Fault('MEDIA_VALIDATION_FAILED')
    return body


def inspect_media(data, format):
    if not 0 < len(data) <= MAX_BYTES:
        raise Fault('FILE_TOO_LARGE', 413)
    if format == 'wav':
        return {**inspect_wav(data), 'mime': MIME[format], 'format': format, 'kind': 'audio'}
    signatures = {'png': data.startswith(b'\x89PNG\r\n\x1a\n'),
                  'jpeg': data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'),
                  'mp4': len(data) >= 12 and data[4:8] == b'ftyp'}
    if format not in DEMUX or not signatures.get(format):
        raise Fault('UNSUPPORTED_MEDIA')
    if format == 'png':
        check_png(data)
    if format == 'mp4':
        check_mp4(data)
    # file access is restricted to the inherited anonymous descriptor. External
    # MOV data references stay disabled; no network protocol is admitted.
    source = ['-protocol_whitelist', 'file', '-f', DEMUX[format]]
    if format == 'mp4':
        source += ['-enable_drefs', '0', '-use_absolute_path', '0']
    source += ['-i', 'file:/proc/self/fd/0']
    raw = codec_call('ffprobe', [*source, '-show_entries',
        'stream=codec_type,codec_name,width,height,duration,sample_rate,channels,avg_frame_rate:format=duration',
        '-of', 'json'], data)
    try:
        probe = json.loads(raw)
        streams = probe['streams']
        videos = [s for s in streams if s['codec_type'] == 'video']
        audios = [s for s in streams if s['codec_type'] == 'audio']
        if len(videos) != 1 or len(audios) > 1 or len(streams) != len(videos) + len(audios):
            raise ValueError()
        video = videos[0]
        width, height = int(video['width']), int(video['height'])
        if not (0 < width <= 4096 and 0 < height <= 4096 and width * height <= MAX_PIXELS):
            raise ValueError()
        expected = {'png': ('png',), 'jpeg': ('mjpeg',), 'mp4': ('h264', 'mpeg4')}
        if video['codec_name'] not in expected[format]:
            raise ValueError()
        facts: dict = dict(format=format, mime=MIME[format], kind='video' if format == 'mp4' else 'image',
                     width=width, height=height, codec=video['codec_name'])
        if format != 'mp4' and audios:
            raise ValueError()
        if format == 'mp4':
            duration = float(probe.get('format', {}).get('duration', video.get('duration', 'nan')))
            if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
                raise ValueError()
            facts.update(duration=duration, frame_rate=video['avg_frame_rate'], audio=bool(audios))
            if audios:
                audio = audios[0]
                if (audio['codec_name'] != 'aac' or int(audio['channels']) not in (1, 2)
                        or int(audio['sample_rate']) not in (44100, 48000)):
                    raise ValueError()
                facts.update(channels=int(audio['channels']), rate=int(audio['sample_rate']))
    except (KeyError, ValueError, TypeError):
        raise Fault('UNSUPPORTED_MEDIA') from None
    # Full decoding to a null sink; one thread, no output media, no network protocols.
    codec_call('ffmpeg', ['-nostdin', '-xerror', '-threads', '1', *source,
                         '-map', '0:v:0', '-map', '0:a?', '-threads', '1', '-f', 'null', '-'], data)
    return facts
