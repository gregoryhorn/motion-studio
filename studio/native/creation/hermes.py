"""Collect profile-scoped Hermes deliverables through the existing import service."""
import base64
import binascii
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ...child_env import child_environment
from ...domain import Fault, MAX_BYTES
from ...persistence.primitives import canonical, identity
from ...media_import.service import MediaImports
from ...media_import.contracts import BeginImport, ImportChunk, ImportID, CHUNK_BYTES

ROOTS = {
    'image_generate': ('cache/generated/images', 'cache/images', 'image_cache'),
    'text_to_speech': ('cache/audio', 'audio_cache'),
    'video_generate': ('cache/generated/videos', 'cache/videos', 'video_cache'),
}
KINDS = {'Image': 'image_generate', 'Voice': 'text_to_speech', 'Video': 'video_generate'}


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS external_submissions(
        submission TEXT PRIMARY KEY, request TEXT UNIQUE, kind TEXT, method_id TEXT,
        attempt TEXT UNIQUE, state TEXT, take TEXT, digest TEXT, result TEXT)""")


def submission_status(db, request):
    row = db.execute('SELECT * FROM external_submissions WHERE request=?', (request,)).fetchone()
    if row is None:
        return dict(submission_state='not_started')
    return dict(submission=row['submission'], attempt=row['attempt'], method_id=row['method_id'],
                submission_state=row['state'])


def submission(db, model):
    row = db.execute('SELECT * FROM external_submissions WHERE request=?', (model.request,)).fetchone()
    if not row or row['submission'] != model.submission or row['attempt'] != model.attempt:
        raise Fault('HERMES_SUBMISSION_MISMATCH', 409)
    if row['state'] == 'abandoned':
        raise Fault('HERMES_SUBMISSION_ABANDONED', 409)
    return row


def external(row):
    return json.loads(row['input']).get('method') in ('hermes_tool', 'import')


def prepare(service, root, model):
    scope = service.scope(root)
    value = model.model_dump()
    value['method'] = 'hermes_tool'
    encoded = canonical(value)
    with service.store.transaction() as db:
        if model.parent:
            service.owned(db, root, model.parent)
        recent = db.execute('SELECT * FROM creation_commands WHERE root=? ORDER BY rowid DESC LIMIT 1', (root,)).fetchone()
        if recent and recent['input'] == encoded:
            db.execute('INSERT OR IGNORE INTO external_submissions VALUES(?,?,?,?,?,?,NULL,NULL,NULL)',
                (identity(), recent['request'], model.kind, model.method_id, identity(), 'awaiting_output'))
            return service.read(root, recent['request'], db=db)
        if recent:
            service.new_intent(db, dict(recent), model.parent)
        request, now = identity(), time.time()
        db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,NULL)',
                   (request, 1, model.direction, model.kind, '', now, now))
        db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                   (request, root, scope.revision, identity(), encoded, None, 'Awaiting output', now))
        db.execute('INSERT INTO external_submissions VALUES(?,?,?,?,?,?,NULL,NULL,NULL)',
            (identity(), request, model.kind, model.method_id, identity(), 'awaiting_output'))
        return service.read(root, request, db=db)


def read_output(path, tool):
    """Pin every directory by descriptor, with no symlink-following race."""
    home = os.environ.get('HERMES_HOME')
    if not home:
        raise Fault('HERMES_OUTPUT_ROOT_UNAVAILABLE', 409)
    candidate, base = Path(path), Path(home).absolute()
    if not candidate.is_absolute() or '..' in candidate.parts:
        raise Fault('HERMES_OUTPUT_PATH_DENIED', 403)
    denied = {'auth.json', 'config.yaml', 'config.yml', 'config.json', 'credentials.json', 'secrets.json'}
    roots = [base / part for part in ROOTS[tool]]
    root = next((r for r in roots if candidate.is_relative_to(r) and candidate != r), None)
    if root is not None and any(p.startswith('.') or p.lower() in denied for p in candidate.relative_to(root).parts):
        raise Fault('HERMES_OUTPUT_PATH_DENIED', 403)
    if root is None:
        raise Fault('HERMES_OUTPUT_PATH_DENIED', 403)
    # realpath confinement also rejects a redirected cache root itself.
    try:
        if base.resolve(strict=True) != base or root.resolve(strict=True) != root or not candidate.resolve(strict=True).is_relative_to(root):
            raise Fault('HERMES_OUTPUT_PATH_DENIED', 403)
        fd = os.open(candidate.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in candidate.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            source = os.open(candidate.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(source, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise Fault('HERMES_OUTPUT_PATH_DENIED', 403)
                if not 0 < info.st_size <= MAX_BYTES:
                    raise Fault('FILE_TOO_LARGE', 413)
                data = stream.read(MAX_BYTES + 1)
                after = os.fstat(stream.fileno())
                if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise Fault('HERMES_OUTPUT_CHANGED', 409)
        finally:
            os.close(fd)
    except (OSError, ValueError, RuntimeError):
        raise Fault('HERMES_OUTPUT_PATH_DENIED', 403) from None
    if not 0 < len(data) <= MAX_BYTES:
        raise Fault('FILE_TOO_LARGE', 413)
    return data, candidate.suffix.lower()


def speech_wav(data, suffix):
    executable = shutil.which('ffmpeg')
    if not executable:
        raise Fault('MEDIA_CONVERTER_UNAVAILABLE', 409)
    try:
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
            source.write(data)
            source.seek(0)
            result = subprocess.run([executable, '-hide_banner', '-v', 'error', '-nostdin', '-y',
                '-protocol_whitelist', 'file,pipe', '-f', 'mp3' if suffix == '.mp3' else 'ogg',
                '-i', 'pipe:0', '-map', '0:a:0', '-vn', '-threads', '1', '-ac', '1', '-ar', '44100',
                '-c:a', 'pcm_s16le', '-fs', str(MAX_BYTES + 1), '-f', 'wav', '-rf64', 'never',
                'file:/proc/self/fd/1'], stdin=source, stdout=output, stderr=subprocess.DEVNULL,
                timeout=20, env=child_environment('helper'))
            output.seek(0)
            converted = output.read(MAX_BYTES + 1)
        if result.returncode:
            raise Fault('MEDIA_CONVERSION_FAILED')
        if len(converted) > MAX_BYTES:
            raise Fault('FILE_TOO_LARGE', 413)
        return converted
    except (OSError, subprocess.TimeoutExpired):
        raise Fault('MEDIA_CONVERSION_FAILED') from None


def collect(service, root, model):
    with service.store.transaction() as db:
        row = service.owned(db, root, model.request)
        snapshot = service.authorize_request(db, root, model.request)
        submitted = submission(db, model)
        if not external(row):
            raise Fault('HERMES_REQUEST_REQUIRED', 409)
        if KINDS.get(snapshot['kind']) != model.tool:
            raise Fault('MEDIA_KIND_MISMATCH', 409)
    if model.url is not None:
        data, suffix = download(model.url)
    elif model.data is not None:
        data, suffix = image_data(model.data)
    else:
        data, suffix = read_output(model.path, model.tool)
    converted = model.tool == 'text_to_speech' and suffix in ('.mp3', '.ogg')
    original = data
    original_suffix = suffix
    if converted and not model.conversion_ok:
        raise Fault('VOICE_CONVERSION_APPROVAL_REQUIRED', 409)
    if converted:
        data, suffix = speech_wav(data, suffix), '.wav'
    format = {'.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg', '.wav': 'wav', '.mp4': 'mp4'}.get(suffix)
    if format is None:
        raise Fault('UNSUPPORTED_MEDIA')
    digest = hashlib.sha256(data).hexdigest()
    command = hashlib.sha256(canonical(['hermes_tool', root, model.request, snapshot['revision'], digest]).encode()).hexdigest()[:32]
    imports = MediaImports(service.store, service.authorize_request, assets=service.assets)
    with service.store.transaction() as db:
        service.authorize_request(db, root, model.request)
        submitted = submission(db, model)
        if submitted['state'] == 'collected':
            if submitted['digest'] != digest:
                raise Fault('HERMES_OUTPUT_CONFLICT', 409)
            validate_output_duration(data, format)
            service.assets.retrieve(submitted['take'])
            return json.loads(submitted['result'])
        validate_output_duration(data, format)
        existing = db.execute('SELECT * FROM takes WHERE request=? AND digest=? AND origin=?',
            (model.request, digest, 'hermes_tool:' + model.tool)).fetchone()
        if existing:
            service.assets.retrieve(existing['id'])
            service.authorize_request(db, root, model.request)
            result = dict(id=existing['import_id'], take=existing['id'], status='Ready for review',
                        request=model.request, method='hermes_tool', converted_to_wav=converted)
            return finish_submission(db, model, digest, result)
        receipt = imports.begin(root, BeginImport(command=command, request=model.request,
            revision=snapshot['revision'], digest=digest, size=len(data), name='Hermes output.' + format, format=format))
        for offset in range(0, len(data), CHUNK_BYTES):
            imports.chunk(root, ImportChunk(id=receipt['id'], offset=offset,
                data=base64.b64encode(data[offset:offset + CHUNK_BYTES]).decode()))
        result = imports.commit(root, ImportID(id=receipt['id']))
        db.execute('UPDATE takes SET origin=? WHERE id=?', ('hermes_tool:' + model.tool, result['take']))
        if converted:
            retain_voice_source(service, db, result['take'], original, original_suffix)
        result.pop('error', None)
        result.update(request=model.request, method='hermes_tool', converted_to_wav=converted)
        return finish_submission(db, model, digest, result)


def validate_output_duration(data, format):
    """Measure output bytes before any import/take exists; never trust tool metadata."""
    if format not in ('wav', 'mp4'):
        return
    from ...media_import.validation import inspect_media, codec_call
    facts = inspect_media(data, format)
    if facts['duration'] < 0.5 or facts.get('frames', 1) <= 0:
        raise Fault('OUTPUT_DURATION_TOO_SHORT', 422)
    if format == 'mp4':
        raw = codec_call('ffprobe', ['-protocol_whitelist', 'file', '-f', 'mov',
            '-enable_drefs', '0', '-use_absolute_path', '0', '-i', 'file:/proc/self/fd/0',
            '-select_streams', 'v:0', '-count_frames', '-show_entries',
            'stream=nb_read_frames', '-of', 'json'], data)
        try:
            frames = int(json.loads(raw)['streams'][0]['nb_read_frames'])
        except (ValueError, KeyError, IndexError, TypeError):
            raise Fault('OUTPUT_HAS_NO_FRAMES', 422) from None
        if frames <= 0:
            raise Fault('OUTPUT_HAS_NO_FRAMES', 422)


def finish_submission(db, model, digest, result):
    result.update(submission=model.submission, attempt=model.attempt, submission_state='collected')
    db.execute("UPDATE external_submissions SET state='collected',take=?,digest=?,result=? WHERE submission=?",
               (result['take'], digest, canonical(result), model.submission))
    return result


def retain_voice_source(service, db, take, data, suffix):
    from ...assets.retention import read_private, sync_directory
    row = service.store.take(db, take)
    path = service.assets.path('media', row['artifact'], '.voice-source')
    try:
        with path.open('xb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        path.chmod(0o400)
        sync_directory(path.parent)
    except FileExistsError:
        if read_private(path) != data:
            raise Fault('HERMES_OUTPUT_CONFLICT', 409)
    facts = json.loads(row['facts'])
    facts['voice_lineage'] = dict(role='retained-derivative',
        native=dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), format=suffix[1:]),
        derivative=dict(sha256=row['digest'], bytes=row['size'], rate=44100, channels=1, bits=16),
        conversion='mono-44100-pcm16')
    db.execute('UPDATE takes SET facts=? WHERE id=?', (canonical(facts), take))


# xAI video returns public URLs; FAL video also returns its CDN URL directly.
# OpenAI-compatible image providers normally cache locally; these are the
# explicit provider domains accepted for their best-effort URL fallback.
PROVIDER_DOMAINS = ('x.ai', 'oaiusercontent.com', 'openai.com', 'fal.media', 'fal.run',
                    'deepinfra.com', 'krea.ai')
MAX_BASE64 = 4 * ((MAX_BYTES + 2) // 3)


def checked_url(url):
    try:
        parts = urlsplit(url)
        host = parts.hostname or ''
        if (parts.scheme != 'https' or parts.username is not None or parts.password is not None
                or parts.port not in (None, 443) or parts.fragment
                or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        if not any(host == domain or host.endswith('.' + domain) for domain in PROVIDER_DOMAINS):
            raise ValueError()
        return parts
    except ValueError:
        raise Fault('HERMES_OUTPUT_URL_DENIED', 403) from None


class ProviderRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if checked_url(newurl).hostname != checked_url(req.full_url).hostname:
            raise Fault('HERMES_OUTPUT_URL_DENIED', 403)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen(request, *, timeout):
    # No environment proxies, cookie jar, auth handlers, or provider credentials.
    return build_opener(ProxyHandler({}), ProviderRedirects()).open(request, timeout=timeout)


def media_suffix(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8'):
        return '.jpg'
    if len(data) >= 12 and data[4:8] == b'ftyp':
        return '.mp4'
    if data.startswith(b'RIFF') and data[8:12] == b'WAVE':
        return '.wav'
    if data.startswith(b'OggS'):
        return '.ogg'
    if data.startswith(b'ID3') or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224):
        return '.mp3'
    raise Fault('UNSUPPORTED_MEDIA')


def download(url):
    parts = checked_url(url)
    deadline = time.monotonic() + 60
    try:
        request = Request(url, headers={'Accept-Encoding': 'identity'})
        with urlopen(request, timeout=60) as response:
            if checked_url(response.geturl()).hostname != parts.hostname:
                raise Fault('HERMES_OUTPUT_URL_DENIED', 403)
            if response.status != 200:
                raise Fault('HERMES_OUTPUT_DOWNLOAD_FAILED')
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdecimal() or not 0 < int(length) <= MAX_BYTES):
                raise Fault('FILE_TOO_LARGE', 413)
            data = bytearray()
            # urllib's timeout is per socket operation. Reduce it to the
            # remaining total budget before each single buffered read.
            socket = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Fault('HERMES_OUTPUT_DOWNLOAD_FAILED')
                if socket is not None:
                    socket.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise Fault('FILE_TOO_LARGE', 413)
            if not data or (length is not None and len(data) != int(length)):
                raise Fault('HERMES_OUTPUT_DOWNLOAD_FAILED')
    except (OSError, URLError, ValueError):
        raise Fault('HERMES_OUTPUT_DOWNLOAD_FAILED') from None
    data = bytes(data)
    return data, media_suffix(data)


def image_data(value):
    if value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,')):
        value = value.partition(',')[2]
    if len(value) > MAX_BASE64:
        raise Fault('FILE_TOO_LARGE', 413)
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise Fault('INVALID_CREATION_INPUT', 422) from None
    if not 0 < len(data) <= MAX_BYTES:
        raise Fault('FILE_TOO_LARGE', 413)
    return data, media_suffix(data)
