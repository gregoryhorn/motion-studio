"""Immutable UI ingestion and authenticated byte access.

No worker/daemon, decoder, provider or filesystem scan runs on import/read.
Scan and admission commands are bounded synchronous operations with durable
per-entry progress; they do not pretend to be queued NativeRuntime jobs.
Host-only methods ``put_chunk``, ``open_media`` and ``open_access`` are binary
transport boundaries, not renderer tool-dispatch endpoints. Every call requires
an already authenticated, server-built context. The host must enforce CSRF and
re-authorize long transfers. No pathname or bearer credential is returned.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timezone

import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import NoReturn, Any
import re
import secrets
import sqlite3
import stat
import threading
import time
import uuid
from urllib.parse import quote

from .assets import AssetStore, AssetRegistry
from .artifacts import ArtifactCatalog
from .contracts import ContractError
from .project import ManagedFS, ProjectStore, _now

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 1000
MAX_CHUNK = 4 * 1024 * 1024
HASH = re.compile(r'^[0-9a-f]{64}$')
# Data-only formats; never ingest authored code, archives or HTML as playback.
EXTENSIONS = {'.mp4': 'media', '.mov': 'media', '.mkv': 'media', '.webm': 'media',
              '.mp3': 'audio', '.wav': 'audio', '.flac': 'audio', '.m4a': 'audio',
              '.aac': 'audio', '.ogg': 'audio', '.opus': 'audio', '.png': 'image',
              '.jpg': 'image', '.jpeg': 'image', '.webp': 'image', '.tif': 'image',
              '.tiff': 'image', '.bmp': 'image', '.srt': 'caption', '.vtt': 'caption',
              '.ass': 'caption', '.ttf': 'font', '.otf': 'font'}


def fail(code, message) -> NoReturn:
    raise ContractError(code, message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def sha(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def opaque(prefix):
    return prefix + '_' + secrets.token_hex(16)


def hexhash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        fail('HASH_INVALID', 'A lowercase SHA-256 is required.')
    return value


def display_name(value):
    if (not isinstance(value, str) or not value or len(value) > 160 or
            any(ord(c) < 32 or ord(c) == 127 for c in value) or
            any(c in value for c in '/\\:') or value in ('.', '..')):
        fail('NAME_UNSAFE', 'Only a safe display filename is accepted.')
    return value


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        fail('LIMIT_EXCEEDED', 'The requested bound is unsupported.')
    return value


def unwrap(result):
    if not result.get('ok'):
        err = result.get('error', {})
        # Backend diagnostics can contain private paths; never forward them.
        fail(err.get('code', 'BACKEND_UNAVAILABLE'), 'The owned backend rejected this operation.')
    return result['data']


def byte_range(header, length):
    """Normalize one HTTP bytes range; end is inclusive. No multipart ranges."""
    if not header:
        return 0, length - 1, False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
    if not match or not any(match.groups()) or length == 0:
        fail('RANGE_INVALID', 'One satisfiable byte range is required.')
    left, right = match.groups()
    if not left:
        size = int(right)
        if not size:
            fail('RANGE_INVALID', 'Suffix range must be nonzero.')
        return max(0, length - size), length - 1, True
    start, end = int(left), min(int(right), length - 1) if right else length - 1
    if start >= length or start > end:
        fail('RANGE_INVALID', 'Range is outside retained bytes.')
    return start, end, True


def sniff_media(stream, name):
    """Bounded signature admission, NOT a claim that a decoder/probe passed."""
    head = stream.read(65536)
    stream.seek(0)
    ext = Path(name).suffix.lower()
    signature = {
        '.png': (head.startswith(b'\x89PNG\r\n\x1a\n'), 'image/png'),
        '.jpg': (head.startswith(b'\xff\xd8\xff'), 'image/jpeg'),
        '.jpeg': (head.startswith(b'\xff\xd8\xff'), 'image/jpeg'),
        '.webp': (head[:4] == b'RIFF' and head[8:12] == b'WEBP', 'image/webp'),
        '.wav': (head[:4] == b'RIFF' and head[8:12] == b'WAVE', 'audio/wav'),
        '.bmp': (head.startswith(b'BM'), 'image/bmp'),
        '.tif': (head[:4] in (b'II*\x00', b'MM\x00*'), 'image/tiff'),
        '.tiff': (head[:4] in (b'II*\x00', b'MM\x00*'), 'image/tiff'),
        '.mp4': (head[4:8] == b'ftyp', 'video/mp4'),
        '.mov': (head[4:8] in (b'ftyp', b'moov', b'mdat', b'wide'), 'video/quicktime'),
        '.m4a': (head[4:8] == b'ftyp', 'audio/mp4'),
        '.webm': (head.startswith(b'\x1aE\xdf\xa3'), 'video/webm'),
        '.mkv': (head.startswith(b'\x1aE\xdf\xa3'), 'video/x-matroska'),
        '.flac': (head.startswith(b'fLaC'), 'audio/flac'),
        '.ogg': (head.startswith(b'OggS'), 'audio/ogg'),
        '.opus': (head.startswith(b'OggS') and b'OpusHead' in head, 'audio/ogg'),
        '.mp3': (head.startswith(b'ID3') or (len(head) > 1 and head[0] == 255 and head[1] & 224 == 224), 'audio/mpeg'),
        '.aac': (len(head) > 1 and head[0] == 255 and head[1] & 246 == 240, 'audio/aac'),
        '.ttf': (head[:4] in (b'\x00\x01\x00\x00', b'true'), 'font/ttf'),
        '.otf': (head[:4] == b'OTTO', 'font/otf')}
    if ext in ('.srt', '.vtt', '.ass'):
        try:
            text = head.decode('utf-8-sig')
        except UnicodeDecodeError:
            fail('MEDIA_INVALID', 'Caption text must be valid UTF-8.')
        if '\x00' in text or '<html' in text.casefold() or '<script' in text.casefold():
            fail('MEDIA_INVALID', 'Executable markup is not an admitted caption.')
        return 'text/vtt' if ext == '.vtt' else 'text/plain'
    accepted, mime = signature.get(ext, (False, 'application/octet-stream'))
    if not accepted:
        fail('MEDIA_INVALID', 'File signature does not match an admitted data format.')
    return mime


class UIMedia:
    OPERATIONS = ('OP-IMPORT-SCAN', 'OP-IMPORT-MANIFEST', 'OP-IMPORT-COMMIT',
                  'OP-UPLOAD-CREATE', 'OP-UPLOAD-CHUNK', 'OP-UPLOAD-STATUS', 'OP-UPLOAD-COMMIT',
                  'OP-UPLOAD-ABORT', 'OP-ASSETS', 'OP-ASSET', 'OP-ASSET-RIGHTS',
                  'OP-MEDIA-ACCESS', 'OP-MEDIA-CHUNK', 'OP-DISCOVERY-SCAN', 'OP-DISCOVERY-STATUS')

    def __init__(self, root, native_registry, root_broker, *, clock=time.time):
        self.root = Path(root) / 'ui-media-v1'
        self.registry, self.broker, self.clock = native_registry, root_broker, clock
        self.lock = threading.RLock()
        self.database_backend: Any = None

    def bind_database(self, backend):
        """Trusted shared SQLite helper hook, not a renderer setting.

        backend(managed_fs, admitted_directory_fd, filename) is a context
        manager yielding a SQLite connection with admission/locking/persistence
        owned by the shared helper. No checked pathname is reopened here.
        """
        if not callable(backend):
            raise TypeError('A trusted safe SQLite context manager is required.')
        self.database_backend = backend

    def authorize(self, context, *, write=False):
        scope = context.get('scope', {})
        if not context.get('principal') or not all(scope.get(k) for k in
                ('backend_instance_id', 'connection_id', 'profile_id', 'native_project_id')):
            fail('AUTH_REQUIRED', 'Authenticated Project context is required.')
        record = next((p for p in self.registry() if p.get('id') == scope['native_project_id']), None)
        if record is None:
            fail('NOT_FOUND', 'Project is unavailable.')
        if write and record.get('archived'):
            fail('PROJECT_ARCHIVED', 'Restore the Project before changing assets.')
        return sha(scope)

    @contextmanager
    def database(self, context, *, write=False):
        namespace = self.authorize(context, write=write)
        fs = ManagedFS(self.root / namespace)
        with self.lock, fs.directory(create=True) as directory:
            if self.database_backend is not None:
                with self.database_backend(fs, directory, 'catalog.sqlite3') as db:
                    db.row_factory = sqlite3.Row
                    db.execute('CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,value TEXT,PRIMARY KEY(kind,id))')
                    db.execute('BEGIN IMMEDIATE')
                    try:
                        yield db, fs
                        db.commit()
                    except BaseException:
                        db.rollback()
                        raise
                return
            # SQLite never reopens a checked pathname: operate on an admitted
            # descriptor snapshot in memory, then atomically publish serialized
            # bytes under a stable, nofollow, cross-process namespace lock.
            try:
                import fcntl
            except ImportError:
                fail('STORAGE_UNSUPPORTED', 'This host requires the shared safe SQLite backend.')
            lock = os.open('catalog.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            db = None
            try:
                if not stat.S_ISREG(os.fstat(lock).st_mode):
                    fail('PATH_UNSAFE', 'Media metadata lock is not a regular file.')
                fcntl.flock(lock, fcntl.LOCK_EX)
                db = sqlite3.connect(':memory:')
                if not hasattr(db, 'deserialize') or not hasattr(db, 'serialize'):
                    fail('STORAGE_UNSUPPORTED', 'Safe descriptor-backed SQLite snapshots are unavailable.')
                try:
                    fd = os.open('catalog.sqlite3', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                except FileNotFoundError:
                    fd = None
                if fd is not None:
                    with os.fdopen(fd, 'rb') as source:
                        metadata = os.fstat(source.fileno())
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 67108864:
                            fail('PATH_UNSAFE', 'Media metadata is unsafe or exceeds its bound.')
                        data = source.read(67108865)
                        if data:
                            db.deserialize(data)
                db.row_factory = sqlite3.Row
                db.execute('CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,value TEXT,PRIMARY KEY(kind,id))')
                db.execute('BEGIN IMMEDIATE')
                yield db, fs
                db.commit()
                payload = db.serialize()
                if len(payload) > 67108864:
                    fail('QUOTA_EXCEEDED', 'Media metadata exceeds its namespace bound.')
                temporary = 'catalog-' + secrets.token_hex(16) + '.new'
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
                try:
                    with os.fdopen(fd, 'wb') as target:
                        target.write(payload); target.flush(); os.fsync(target.fileno())
                    os.replace(temporary, 'catalog.sqlite3', src_dir_fd=directory, dst_dir_fd=directory)
                    os.fsync(directory)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        pass
            except BaseException:
                if db is not None:
                    db.rollback()
                raise
            finally:
                if db is not None:
                    db.close()
                os.close(lock)

    @staticmethod
    def get(db, kind, identity):
        row = db.execute('SELECT value FROM records WHERE kind=? AND id=?', (kind, identity)).fetchone()
        if row is None:
            fail('NOT_FOUND', 'The scoped resource is unavailable.')
        return json.loads(row['value'])

    @staticmethod
    def save(db, kind, identity, value):
        db.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET value=excluded.value',
                   (kind, identity, encoded(value)))

    def all(self, db, kind):
        return [json.loads(row['value']) for row in db.execute(
            'SELECT value FROM records WHERE kind=? ORDER BY id', (kind,))]

    def _replay(self, db, context, input, pre):
        key = context.get('idempotency_key')
        if not key:
            fail('PRECONDITION_REQUIRED', 'A durable command identity is required.')
        identity = sha([context['principal'], key])
        fingerprint = sha([context['operation_id'], context.get('params', {}), input, pre])
        row = db.execute('SELECT value FROM records WHERE kind=? AND id=?', ('command', identity)).fetchone()
        if row:
            receipt = json.loads(row['value'])
            if receipt['sha256'] != fingerprint:
                fail('IDEMPOTENCY_CONFLICT', 'The command key is already bound to another intent.')
            return identity, fingerprint, receipt['result']
        return identity, fingerprint, None

    def callback(self, context, input, pre):
        operation = context['operation_id']
        if operation not in self.OPERATIONS:
            fail('UNSUPPORTED_OPERATION', 'This media operation is not advertised.')
        if operation == 'OP-MEDIA-CHUNK':
            return self.read_media_chunk(context, context['params']['access_id'],
                offset=int(input.get('offset', 0)), length=int(input.get('length', 262144)))
        if operation == 'OP-UPLOAD-CHUNK':
            # Service owns the command journal. Never hold our catalog lock while
            # calling put_chunk, which atomically owns the upload catalog itself.
            body = context.get('binary_upload_chunk')
            if not isinstance(body, bytes):
                fail('AUTHORITY_REQUIRED', 'An authenticated host binary body is required.')
            if len(body) != input['content_length'] or hashlib.sha256(body).hexdigest() != input['sha256']:
                fail('DIGEST_MISMATCH', 'Binary body differs from the command metadata.')
            return self.put_chunk(context, context['params']['upload_id'],
                int(context['params']['chunk_index']), body,
                expected_revision=pre['entity_revision'], content_range=input['content_range'],
                digest=input['digest'], content_length=input['content_length'])
        commands = operation not in ('OP-ASSETS', 'OP-ASSET', 'OP-IMPORT-MANIFEST', 'OP-UPLOAD-STATUS', 'OP-DISCOVERY-STATUS')
        with self.database(context, write=commands) as (db, fs):
            replay = self._replay(db, context, input, pre) if commands else None
            if replay and replay[2] is not None:
                return replay[2]
            handlers = {'OP-IMPORT-SCAN': self.scan, 'OP-IMPORT-MANIFEST': self.manifest,
                        'OP-IMPORT-COMMIT': self.import_entries, 'OP-UPLOAD-CREATE': self.upload_create,
                        'OP-UPLOAD-STATUS': self.upload_status, 'OP-UPLOAD-COMMIT': self.upload_commit,
                        'OP-UPLOAD-ABORT': self.upload_abort, 'OP-ASSETS': self.assets,
                        'OP-ASSET': self.asset, 'OP-ASSET-RIGHTS': self.rights,
                        'OP-MEDIA-ACCESS': self.access}
            if operation in ('OP-DISCOVERY-SCAN', 'OP-DISCOVERY-STATUS'):
                from .ui_discovery import UIDiscovery
                discovery = UIDiscovery(self)
                handlers.update({'OP-DISCOVERY-SCAN': discovery.scan, 'OP-DISCOVERY-STATUS': discovery.status})
            result = handlers[operation](db, fs, context, input, pre)
            if replay:
                self.save(db, 'command', replay[0], {'sha256': replay[1], 'result': result})
            return result

    def scan(self, db, fs, context, input, pre):
        if input['symlink_policy'] != 'deny':
            fail('SCAN_POLICY_UNSUPPORTED', 'Symlinks are never followed.')
        max_files = integer(input['max_files'], 1, MAX_FILES)
        max_bytes = integer(input['max_bytes'], 1, MAX_BYTES)
        native = context['scope']['native_project_id']
        revisions = {r['root_id']: r['revision'] for r in pre['root_revisions']}
        available = {r['root_id']: r['root_revision'] for r in self.broker.roots(native)['items']}
        if any(available.get(k) != v for k, v in revisions.items()):
            fail('ROOT_CHANGED', 'Refresh Project roots before scanning.')
        entries, causes, seen, total = [], [], set(), 0
        filters = input['filters']
        queue = list(input['selections'])
        while queue:
            selection = queue.pop(0)
            root, node = selection['root_id'], selection['node_id']
            if root not in revisions or (root, node) in seen:
                if root not in revisions:
                    fail('SELECTION_INVALID', 'Selection lacks its root revision.')
                continue
            seen.add((root, node))
            if len(seen) > MAX_FILES * 4:
                causes.append('DIRECTORY_LIMIT'); break
            # Browse directories through opaque handles only. A regular file is
            # observed through open_node, never by reconstructing its pathname.
            try:
                with self.broker.open_node(native, root, node, revisions[root]) as (stream, metadata):
                    st = os.fstat(stream.fileno())
                    name = metadata['display_name']
                    # A selected file handle's name is acquired from its parent
                    # browse record by the broker's optional metadata method;
                    # fallback is safe opaque display, never a private path.
                    name = name or ('import-' + node[-12:])
                    row: dict[str, Any] = dict(entry_id=opaque('entry'), root_id=root, node_id=node,
                               root_revision=revisions[root], display_name=name,
                               byte_length=st.st_size, observed_token=sha(list((st.st_dev,
                               st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))),
                               mtime_token=selection.get('mtime_token'), kind=selection.get('kind'),
                               status='eligible', reasons=[], hash_on_admission_required=True)
            except ContractError as exc:
                # PATH_UNSAFE for a directory is expected; browse itself checks
                # type/identity. Other failures are retained as exact failures.
                try:
                    cursor = None
                    while True:
                        page = self.broker.browse(native, root, parent_node_id=node,
                            expected_root_revision=revisions[root], kind_filter='all',
                            limit=200, cursor=cursor)
                        for child in page['items']:
                            if len(queue) + len(seen) >= MAX_FILES * 4:
                                causes.append('DIRECTORY_LIMIT')
                                break
                            child = {**child, 'root_id': root, 'display_name': child['name']}
                            if child['kind'] == 'directory' and not input['recursive']:
                                continue
                            if child['hidden'] and not filters['include_hidden']:
                                continue
                            queue.append(child)
                        cursor = page.get('next_cursor')
                        if not cursor or causes:
                            break
                    continue
                except ContractError:
                    entries.append(dict(entry_id=opaque('entry'), root_id=root, node_id=node,
                                        status='failed', reasons=[exc.code], byte_length=0))
                    continue
            extension = Path(name).suffix.lower()
            row['kind'] = EXTENSIONS.get(extension, row['kind'])
            if extension not in EXTENSIONS:
                row.update(status='excluded', reasons=['TYPE_UNSUPPORTED'])
            elif filters['extensions'] and extension.lstrip('.') not in [s.lower().lstrip('.') for s in filters['extensions']]:
                row.update(status='excluded', reasons=['EXTENSION_FILTER'])
            elif filters['kinds'] and row['kind'] not in filters['kinds']:
                row.update(status='excluded', reasons=['KIND_FILTER'])
            if row['status'] == 'eligible':
                if total + row['byte_length'] > max_bytes:
                    causes.append('BYTE_LIMIT'); break
                total += row['byte_length']
            entries.append(row)
            if len(entries) >= max_files and queue:
                causes.append('FILE_LIMIT'); break
        record = dict(scan_id=opaque('scan'), manifest_id=opaque('manifest'), state='succeeded',
                      complete=not causes, partial_causes=causes, root_revisions=pre['root_revisions'],
                      entries=entries, total_bytes=total, counts={k: sum(e['status'] == k for e in entries)
                      for k in ('eligible', 'excluded', 'failed')})
        record['manifest_sha256'] = sha(record)
        self.save(db, 'manifest', record['manifest_id'], record)
        self.save(db, 'scan', record['scan_id'], {'manifest_id': record['manifest_id']})
        return self._manifest_page(record, {'status_filter': 'all'})

    @staticmethod
    def _manifest_page(record, query):
        status = query.get('status_filter', 'all')
        entries = [e for e in record['entries'] if status == 'all' or e['status'] == status]
        offset = int(query.get('cursor') or 0)
        limit = integer(query.get('limit', 100), 1, 200)
        return {**record, 'entries': entries[offset:offset + limit],
                'next_cursor': str(offset + limit) if offset + limit < len(entries) else None}

    def manifest(self, db, fs, context, input, pre):
        scan = self.get(db, 'scan', context['params']['scan_id'])
        return self._manifest_page(self.get(db, 'manifest', scan['manifest_id']), input)

    def _asset_store(self, context):
        store = context.get('project_store')
        if store is None:
            fail('BACKEND_UNAVAILABLE', 'A trusted ProjectStore is required.')
        return AssetStore(root=store.root)

    def _library(self, db, context):
        store = self._asset_store(context)
        request = str(uuid.uuid5(uuid.NAMESPACE_URL, 'motion-ui-assets:' + sha(context['scope'])))
        # AssetStore.dispatch owns asset actions, not project creation. Use the
        # project contract at the same trusted root; return AssetStore for import.
        result = ProjectStore(root=store.root).dispatch(dict(action='create', request_id=request, name='Project asset library',
                                     rate={'num': 24, 'den': 1}, sample_rate=48000))
        unwrap(result)
        return store, result['project_id']

    def _admit(self, db, fs, context, blob, name, digest_hex, length, request_id, assertions):
        for assertion in assertions:
            if (not isinstance(assertion, dict) or set(assertion) != {'kind', 'value', 'evidence_ref'}
                    or assertion['evidence_ref'] is not None
                    or not isinstance(assertion['kind'], str) or not isinstance(assertion['value'], str)):
                fail('RIGHTS_SCHEMA_INVALID', 'Admission records declarations, not unverifiable external evidence.')
        with fs.directory('quarantine') as directory:
            fd = os.open(Path(blob).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, 'rb') as stream:
                detected_mime = sniff_media(stream, name)
        store, pid = self._library(db, context)
        # Reuse only already-authorized immutable records in this namespace.
        existing = next((a for a in self.all(db, 'asset') if a['sha256'] == digest_hex), None)
        if existing:
            return existing
        pointer = store._pointer(store._filesystem(), pid)
        provenance = {'origin': 'user_import', 'acquired_at': _now(), 'source_locator': None,
                      'provider': None, 'model': None, 'model_version': None, 'seed': None,
                      'deterministic': 'unknown', 'rights': {'status': 'unknown', 'license': None,
                      'attribution': None, 'evidence': []},
                      'notes': 'Authenticated user import; declarations are not verified licenses.'}
        retained = next((pair for pair in AssetRegistry(store).records(store._filesystem(), pointer)
                         if pair[1]['sha256'] == 'sha256:' + digest_hex and pair[1]['size_bytes'] == length), None)
        if retained:
            asset = retained[0]
        else:
            result = store.dispatch(dict(action='import', project_id=pid, expected_revision=pointer['revision'],
                request_id=request_id, source={'kind': 'local', 'path': str(fs.root / blob)},
                label=name, provenance=provenance, kind=EXTENSIONS.get(Path(name).suffix.lower(), 'media')))
            asset = unwrap(result)['asset']
        artifact = ArtifactCatalog(store).resolve(pid, asset['artifact'])
        if artifact['sha256'] != 'sha256:' + digest_hex or artifact['size_bytes'] != length:
            fail('DIGEST_MISMATCH', 'Admission did not retain the selected exact bytes.')
        public = dict(asset_id=opaque('asset'), asset_version_id=opaque('assetversion'),
                      entity_revision=1, display_name=name, kind=artifact['kind'],
                      sha256=digest_hex, byte_length=length, mime=detected_mime,
                      media_id=opaque('media'), readiness='probe_required', streams=[],
                      probe=None, metadata_gaps=['PROBE_REQUIRED'], derivatives=[], usages=[],
                      rights_assertions=assertions, rights_status='unknown')
        self.save(db, 'binding', public['media_id'], {'owner': pid, 'pin': asset['artifact'],
                                                    'store_root': str(store._filesystem().root)})
        self.save(db, 'asset', public['asset_id'], public)
        return public

    def _copy(self, fs, stream, name, max_length):
        relative = 'quarantine/' + opaque('blob') + Path(name).suffix.lower()
        digest, count = hashlib.sha256(), 0
        with fs.directory('quarantine', create=True) as directory:
            fd = os.open(Path(relative).name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, 'wb') as target:
                while True:
                    data = stream.read(min(MAX_CHUNK, max_length - count + 1))
                    if not data:
                        break
                    count += len(data)
                    if count > max_length:
                        fail('QUOTA_EXCEEDED', 'Selected bytes exceed the admission bound.')
                    target.write(data); digest.update(data)
                target.flush(); os.fsync(target.fileno())
            immutable = digest.hexdigest() + Path(name).suffix.lower()
            try:
                os.link(Path(relative).name, immutable, src_dir_fd=directory,
                        dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                retained_fd = os.open(immutable, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(retained_fd, 'rb') as retained:
                    known, known_count = hashlib.sha256(), 0
                    while data := retained.read(MAX_CHUNK):
                        known.update(data); known_count += len(data)
                    if known.hexdigest() != digest.hexdigest() or known_count != count:
                        fail('DIGEST_MISMATCH', 'Retained immutable quarantine bytes changed.')
            os.unlink(Path(relative).name, dir_fd=directory)
            os.fsync(directory)
        return 'quarantine/' + immutable, digest.hexdigest(), count

    def import_entries(self, db, fs, context, input, pre):
        if input['copy_policy'] != 'managed_immutable_copy' or input['dedup_policy'] != 'reuse_authorized_hash':
            fail('SCAN_POLICY_UNSUPPORTED', 'Only managed immutable admission is supported.')
        record = self.get(db, 'manifest', input['manifest_id'])
        if record['manifest_sha256'] != pre['manifest_sha256']:
            fail('HASH_MISMATCH', 'The frozen manifest differs.')
        if not record['complete'] and not input['allow_partial_manifest']:
            fail('PARTIAL_MANIFEST_UNACKNOWLEDGED', 'Acknowledge the incomplete scan explicitly.')
        requested = input['entry_ids']
        by_id = {e['entry_id']: e for e in record['entries']}
        if not requested or len(set(requested)) != len(requested) or any(i not in by_id for i in requested):
            fail('SELECTION_INVALID', 'Select distinct entries from this immutable manifest.')
        progress = {'import_id': opaque('import'), 'state': 'running', 'entries': [],
                    'manifest_id': record['manifest_id'], 'manifest_sha256': record['manifest_sha256'],
                    'target_composition_id': input['target_composition_id']}
        for identity in requested:
            entry = by_id[identity]
            row = {'entry_id': identity, 'state': 'skipped', 'asset_id': None}
            if entry['status'] != 'eligible':
                row['reason'] = 'ENTRY_INELIGIBLE'
            else:
                try:
                    with self.broker.open_node(context['scope']['native_project_id'], entry['root_id'],
                            entry['node_id'], entry['root_revision'],
                            expected_mtime_token=entry.get('mtime_token')) as (stream, metadata):
                        st = os.fstat(stream.fileno())
                        token = sha([st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns])
                        if token != entry['observed_token']:
                            fail('SOURCE_CHANGED', 'Selected file identity changed.')
                        blob, fingerprint, size = self._copy(fs, stream, entry['display_name'], entry['byte_length'])
                        after = os.fstat(stream.fileno())
                        if sha([after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns]) != token:
                            fail('SOURCE_CHANGED', 'Selected file changed while copying.')
                    request_id = str(uuid.uuid5(uuid.UUID(context['idempotency_key']), identity))
                    asset = self._admit(db, fs, context, blob, entry['display_name'], fingerprint,
                                        size, request_id, input['rights_assertions'])
                    row.update(state='admitted', asset_id=asset['asset_id'])
                except ContractError as exc:
                    row.update(state='failed', reason=exc.code)
            progress['entries'].append(row)
            self.save(db, 'import', progress['import_id'], progress)
            # Each entry's committed AssetStore transaction is recoverable under
            # its deterministic UUID even if facade response/transaction is lost.
        progress['state'] = 'completed_with_failures' if any(e['state'] == 'failed' for e in progress['entries']) else 'succeeded'
        progress['counts'] = {k: sum(e['state'] == k for e in progress['entries']) for k in ('admitted', 'skipped', 'failed')}
        self.save(db, 'import', progress['import_id'], progress)
        return progress

    def upload_create(self, db, fs, context, input, pre):
        name = display_name(input['display_name'])
        if input['relative_display_name'] is not None:
            # Preserve a label only; directory upload is not an executable path.
            for part in input['relative_display_name'].split('/'):
                display_name(part)
        if input['source_kind'] != 'client_file' or Path(name).suffix.lower() not in EXTENSIONS:
            fail('MIME_DISALLOWED', 'This data format is not supported.')
        length = integer(input['byte_length'], 1, MAX_BYTES)
        chunk = integer(input['chunk_size'], 1, MAX_CHUNK)
        hexhash(input['total_sha256'])
        active = sum(u['byte_length'] for u in self.all(db, 'upload')
                     if u['state'] == 'open' and u['expires_at_epoch'] > self.clock())
        if active + length > MAX_BYTES:
            fail('QUOTA_EXCEEDED', 'The namespace upload reservation is exhausted.')
        # quota revision is an observed reservation set, not a renderer grant.
        quota = self._quota(db)['quota_revision']
        if pre['quota_revision'] != quota:
            fail('REVISION_CONFLICT', 'Upload quota reservation changed.')
        upload = dict(upload_id=opaque('upload'), entity_revision=1, state='open', display_name=name,
                      declared_mime=input['declared_mime'], byte_length=length,
                      total_sha256=input['total_sha256'], chunk_size=chunk,
                      chunk_count=(length + chunk - 1) // chunk, accepted_chunks=[],
                      principal=context['principal'], expires_at_epoch=self.clock() + 86400,
                      transport_ref={'kind': 'authenticated_binary', 'operation_id': 'OP-UPLOAD-CHUNK'},
                      asset_id=None)
        self.save(db, 'upload', upload['upload_id'], upload)
        return {**self._upload_public(upload), 'quota_revision': self._quota(db)['quota_revision']}

    def _quota(self, db):
        records = self.all(db, 'upload')
        reserved = sum(u['byte_length'] for u in records if u['state'] == 'open' and u['expires_at_epoch'] > self.clock())
        return {'quota_revision': 1 + sum(u['entity_revision'] for u in records),
                'max_bytes': MAX_BYTES, 'reserved_bytes': reserved, 'available_bytes': MAX_BYTES - reserved,
                'max_chunk_bytes': MAX_CHUNK}

    def quota(self, context):
        """Host bootstrap projection; never scans/probes or admits bytes."""
        with self.database(context) as (db, fs):
            return self._quota(db)

    @staticmethod
    def _upload_public(upload):
        return {**{k: v for k, v in upload.items() if k not in ('principal', 'expires_at_epoch')},
                'expires_at': datetime.fromtimestamp(upload['expires_at_epoch'], timezone.utc).isoformat()}

    def _upload(self, db, context):
        record = self.get(db, 'upload', context['params']['upload_id'])
        if record['principal'] != context['principal']:
            fail('NOT_FOUND', 'Upload is not owned by this authenticated principal.')
        if record['state'] == 'open' and record['expires_at_epoch'] <= self.clock():
            fail('UPLOAD_EXPIRED', 'Upload reservation expired.')
        return record

    def upload_status(self, db, fs, context, input, pre):
        record = self.get(db, 'upload', context['params']['upload_id'])
        if record['principal'] != context['principal']:
            fail('NOT_FOUND', 'Upload is not owned by this principal.')
        if record['state'] == 'open' and record['expires_at_epoch'] <= self.clock():
            record['state'] = 'expired'
        return {**self._upload_public(record), 'quota_revision': self._quota(db)['quota_revision']}

    def put_chunk(self, context, upload_id, chunk_index, body, *, expected_revision,
                  content_range, digest, content_length):
        """Host-only binary request boundary. ``body`` is bytes, not a pathname.

        The host authenticates and validates scope/CSRF/command UUIDs before
        calling. Digest is the HTTP base64 sha-256 value (without algorithm).
        Duplicate identical bytes are accepted despite a later entity revision.
        """
        context = {**context, 'params': {'upload_id': upload_id}}
        if not isinstance(body, bytes) or len(body) > MAX_CHUNK or len(body) != content_length:
            fail('RANGE_INVALID', 'Binary body has an invalid bounded length.')
        try:
            supplied = base64.b64decode(digest, validate=True)
        except (ValueError, TypeError):
            fail('DIGEST_MISMATCH', 'A base64 SHA-256 digest is required.')
        actual = hashlib.sha256(body).digest()
        if supplied != actual:
            fail('DIGEST_MISMATCH', 'Chunk digest differs from exact bytes.')
        with self.database(context, write=True) as (db, fs):
            upload = self._upload(db, context)
            index = integer(chunk_index, 0, upload['chunk_count'] - 1)
            start = index * upload['chunk_size']
            size = min(upload['chunk_size'], upload['byte_length'] - start)
            if len(body) != size or content_range != f'bytes {start}-{start + size - 1}/{upload["byte_length"]}':
                fail('RANGE_INVALID', 'Chunk range differs from the reserved session.')
            previous = next((c for c in upload['accepted_chunks'] if c['chunk_index'] == index), None)
            if previous:
                if previous['sha256'] != actual.hex():
                    fail('CHUNK_MISMATCH', 'A different chunk is already retained.')
                return self._upload_public(upload)
            if upload['state'] != 'open':
                fail('UPLOAD_SEALED', 'This upload is sealed.')
            if upload['entity_revision'] != expected_revision:
                fail('REVISION_CONFLICT', 'Refresh upload status before sending more bytes.')
            path = f'uploads/{upload_id}/{index}.chunk'
            with fs.directory(f'uploads/{upload_id}', create=True) as directory:
                filename = str(index) + '.chunk'
                try:
                    fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
                except FileExistsError:
                    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                    with os.fdopen(fd, 'rb') as retained:
                        if retained.read(MAX_CHUNK + 1) != body:
                            fail('CHUNK_MISMATCH', 'Uncommitted retained chunk differs.')
                else:
                    with os.fdopen(fd, 'wb') as target:
                        target.write(body); target.flush(); os.fsync(target.fileno())
            upload['accepted_chunks'].append({'chunk_index': index, 'sha256': actual.hex(), 'byte_length': size})
            upload['accepted_chunks'].sort(key=lambda c: c['chunk_index'])
            upload['entity_revision'] += 1
            self.save(db, 'upload', upload_id, upload)
            return self._upload_public(upload)

    def upload_commit(self, db, fs, context, input, pre):
        upload = self._upload(db, context)
        if upload['state'] == 'committed':
            return self._upload_public(upload)
        if upload['state'] != 'open':
            fail('UPLOAD_SEALED', 'Upload is not open.')
        if pre['entity_revision'] != upload['entity_revision']:
            fail('REVISION_CONFLICT', 'Upload revision changed.')
        if input['total_sha256'] != upload['total_sha256'] or input['byte_length'] != upload['byte_length']:
            fail('DIGEST_MISMATCH', 'Commit differs from the reserved bytes.')
        if len(upload['accepted_chunks']) != upload['chunk_count']:
            fail('CHUNKS_MISSING', 'Send all missing chunks before committing.')
        # Assemble only server-generated chunk paths. _copy has a hard byte cap.
        class Chunks:
            def __init__(self, directory, chunks):
                self.directory, self.chunks, self.current = directory, iter(chunks), None
            def read(self, count):
                while True:
                    if self.current is None:
                        try:
                            chunk = next(self.chunks)
                        except StopIteration:
                            return b''
                        fd = os.open(str(chunk['chunk_index']) + '.chunk', os.O_RDONLY | os.O_NOFOLLOW,
                                     dir_fd=self.directory)
                        self.current = os.fdopen(fd, 'rb')
                        if not stat.S_ISREG(os.fstat(fd).st_mode):
                            self.current.close()
                            fail('PATH_UNSAFE', 'Retained chunk is not a regular file.')
                        data = self.current.read(MAX_CHUNK + 1)
                        if len(data) != chunk['byte_length'] or hashlib.sha256(data).hexdigest() != chunk['sha256']:
                            self.current.close()
                            fail('DIGEST_MISMATCH', 'Retained chunk changed before admission.')
                        self.current.seek(0)
                    data = self.current.read(count)
                    if data:
                        return data
                    self.current.close(); self.current = None
            def close(self):
                if self.current:
                    self.current.close()
        with fs.directory('uploads/' + upload['upload_id']) as directory:
            stream = Chunks(directory, upload['accepted_chunks'])
            try:
                blob, fingerprint, size = self._copy(fs, stream, upload['display_name'], upload['byte_length'])
            finally:
                stream.close()
        if fingerprint != upload['total_sha256'] or size != upload['byte_length']:
            fail('DIGEST_MISMATCH', 'Assembled upload differs from its declared hash/length.')
        # Admission signature-sniffs bounded bytes. Stream/probe facts
        # stay absent; unsupported decoder/probe approval is not fabricated.
        asset = self._admit(db, fs, context, blob, upload['display_name'], fingerprint, size,
                            str(uuid.uuid5(uuid.NAMESPACE_URL, upload['upload_id'])), input['rights_assertions'])
        upload.update(state='committed', asset_id=asset['asset_id'], entity_revision=upload['entity_revision'] + 1)
        self.save(db, 'upload', upload['upload_id'], upload)
        return {**self._upload_public(upload), 'asset': asset}

    def upload_abort(self, db, fs, context, input, pre):
        upload = self._upload(db, context)
        if upload['state'] == 'committed':
            fail('UPLOAD_ALREADY_COMMITTED', 'A committed asset cannot be aborted.')
        if upload['entity_revision'] != pre['entity_revision']:
            fail('REVISION_CONFLICT', 'Upload revision changed.')
        upload.update(state='aborted', entity_revision=upload['entity_revision'] + 1)
        self.save(db, 'upload', upload['upload_id'], upload)
        return {**self._upload_public(upload), 'cleanup_state': 'quarantined_pending_cleanup'}

    def assets(self, db, fs, context, input, pre):
        items = self.all(db, 'asset')
        for key in ('kind', 'readiness'):
            if key in input:
                items = [a for a in items if a[key] == input[key]]
        if input.get('composition_id'):
            items = [a for a in items if input['composition_id'] in a['usages']]
        if input.get('search'):
            items = [a for a in items if input['search'].casefold() in a['display_name'].casefold()]
        offset = integer(int(input.get('cursor') or 0), 0, MAX_FILES * 100)
        limit = integer(input.get('limit', 100), 1, 200)
        return {'items': items[offset:offset + limit], 'next_cursor': str(offset + limit) if offset + limit < len(items) else None}

    def asset(self, db, fs, context, input, pre):
        record = self.get(db, 'asset', context['params']['asset_id'])
        if input.get('asset_version_id', record['asset_version_id']) != record['asset_version_id']:
            fail('NOT_FOUND', 'Asset version is unavailable.')
        return record

    def rights(self, db, fs, context, input, pre):
        record = self.asset(db, fs, context, {}, {})
        if record['entity_revision'] != pre['entity_revision']:
            fail('REVISION_CONFLICT', 'Asset metadata changed.')
        if input['replace_assertion_ids']:
            fail('RIGHTS_SCHEMA_INVALID', 'Replacement requires identified retained assertions.')
        for assertion in input['assertions']:
            if set(assertion) != {'kind', 'value', 'evidence_ref'} or assertion['evidence_ref'] is not None:
                fail('EVIDENCE_UNAVAILABLE', 'Only attributed declarations without unverifiable evidence are supported.')
        record['rights_assertions'] += [{'assertion_id': opaque('assertion'), **a,
                                        'asserted_by': context['principal']} for a in input['assertions']]
        record['entity_revision'] += 1
        self.save(db, 'asset', record['asset_id'], record)
        return record

    @staticmethod
    def association_id(context, record):
        return sha([context['composition']['composition_id'], context['private_project_id'],
                    record['asset_id'], record['asset_version_id'], record['sha256']])

    def associate(self, db, context, record, request_id):
        """Explicit command only: copy admitted bytes into the composition owner.

        Native AssetStore owns mutation/replay and byte verification. The UI
        catalog only maps public pins to that authoritative committed asset.
        No parser, caption importer, decoder or worker runs here.
        """
        if record['kind'] not in ('media', 'video', 'audio', 'image', 'frame'):
            fail('UNSUPPORTED_OPERATION', 'Only media bytes can enter this source binding; captions require their explicit provenance workflow.')
        identity = self.association_id(context, record)
        retained = next((r for r in self.all(db, 'composition-asset') if r['id'] == identity), None)
        store = context['project_store']
        target = AssetStore(store.root)
        pid = context['private_project_id']
        fs = target._filesystem(write=True)
        if retained is not None:
            artifact = ArtifactCatalog(target).resolve(pid, retained['pin'])
            if artifact['sha256'] != 'sha256:' + record['sha256'] or artifact['size_bytes'] != record['byte_length']:
                fail('DIGEST_MISMATCH', 'Composition copy no longer matches admission.')
            return retained
        binding = self.get(db, 'binding', record['media_id'])
        source_store = self._asset_store(context)
        if binding['store_root'] != str(source_store._filesystem().root):
            fail('NOT_FOUND', 'Admission store binding differs.')
        catalog = ArtifactCatalog(source_store)
        artifact = catalog.resolve(binding['owner'], binding['pin'])
        if artifact['sha256'] != 'sha256:' + record['sha256'] or artifact['size_bytes'] != record['byte_length']:
            fail('DIGEST_MISMATCH', 'Admission binding differs from selected public bytes.')
        # A verified descriptor stays open across the native copy operation;
        # native import independently checks the path and copied byte closure.
        with catalog.open_record(source_store._filesystem(), artifact) as stream:
            if artifact['storage']['mode'] != 'managed':
                fail('ASSET_UNRESOLVED', 'Composition sources must be admitted managed copies.')
            relative = artifact['storage']['relative_path']
            base = source_store._base(binding['owner'])
            # Catalog's committed record defines the same two producer path
            # conventions as open_record; never consume a caller-supplied path.
            if artifact['producer']['job_id'] is None or not relative.startswith(base + '/'):
                relative = base + '/' + relative
            source = source_store._filesystem().root / relative
            pointer = target._pointer(fs, pid)
            if pointer is None:
                fail('NOT_FOUND', 'Composition engine project is unavailable.')
            expected_revision = pointer['revision']
            history = pointer
            while history:
                transaction = target._transaction(fs, history)
                if transaction is None:
                    fail('INVALID_GRAPH', 'Composition commit history is unavailable.')
                if transaction['request_id'] == request_id:
                    previous = transaction['previous']
                    if previous is None:
                        fail('IDEMPOTENCY_CONFLICT', 'Asset request collides with project creation.')
                    expected_revision = previous['revision']
                    break
                history = transaction['previous']
            result = unwrap(target.dispatch(dict(action='import', project_id=pid,
                expected_revision=expected_revision, request_id=request_id,
                source={'kind': 'local', 'path': str(source)}, label=record['display_name'],
                kind='media' if record['kind'] == 'video' else record['kind'], provenance=artifact['provenance'])))
        copied = result['asset']
        committed = ArtifactCatalog(target).resolve(pid, copied['artifact'])
        if committed['sha256'] != 'sha256:' + record['sha256'] or committed['size_bytes'] != record['byte_length']:
            fail('DIGEST_MISMATCH', 'Composition import differs from admission.')
        retained = dict(id=identity, owner=pid, native_asset_id=copied['asset_id'],
                        pin=copied['artifact'], imported_revision=result['project_revision'],
                        composition_id=context['composition']['composition_id'],
                        public_asset_id=record['asset_id'], public_version_id=record['asset_version_id'])
        self.save(db, 'composition-asset', identity, retained)
        return retained

    def resolve_source(self, context, pin):
        """Host graph hydration: resolve(context, public asset pin) -> graph asset.

        Read-only; no import, probing, readiness refresh or stream selection.
        The explicit bind command must have selected one observed stream first.
        The service must hydrate before apply_operations and freeze the returned
        private artifact pin in the canonical graph (never trust renderer facts).
        """
        with self.database(context) as (db, fs):
            record = self.get(db, 'asset', pin['asset_id'])
            if (pin['asset_version_id'] != record['asset_version_id'] or pin['sha256'] != record['sha256']):
                fail('ASSET_UNRESOLVED', 'Public source pin changed.')
            association = self.get(db, 'composition-asset', self.association_id(context, record))
            graph_asset = association.get('graph_asset')
            if graph_asset is None:
                fail('PROBE_REQUIRED', 'Explicit approved probing and source binding are required.')
            artifact = ArtifactCatalog(AssetStore(context['project_store'].root)).resolve(
                context['private_project_id'], association['pin'])
            if artifact['sha256'] != 'sha256:' + record['sha256'] or artifact['size_bytes'] != record['byte_length']:
                fail('DIGEST_MISMATCH', 'Bound source bytes differ.')
            return json.loads(encoded(graph_asset))

    def register_output(self, db, context, owner, pin, label):
        """Host-only projection of a real committed artifact, never a path."""
        store = self._asset_store(context)
        catalog = ArtifactCatalog(store)
        record = catalog.resolve(owner, pin)
        media_id = 'media_' + sha([owner, pin])[:32]
        existing = next((a for a in self.all(db, 'asset') if a['media_id'] == media_id), None)
        if existing:
            return existing
        # Do not serve reports/source scripts as active browser content.
        mime = record['media_type']
        if (record['kind'] not in ('media', 'audio', 'image', 'frame') or
                mime in ('image/svg+xml', 'text/html', 'application/xhtml+xml')):
            mime = 'application/octet-stream'
        public = dict(asset_id='output_' + sha([owner, pin])[:32],
                      asset_version_id='assetversion_' + sha(pin)[:32], entity_revision=1,
                      display_name=display_name(label), kind=record['kind'],
                      sha256=record['sha256'].removeprefix('sha256:'),
                      byte_length=record['size_bytes'], mime=mime, media_id=media_id,
                      readiness='bytes_verified', streams=[], probe=None,
                      metadata_gaps=['PROBE_FACTS_NOT_PROJECTED'], derivatives=[], usages=[],
                      rights_assertions=[], rights_status=record['provenance']['rights']['status'])
        self.save(db, 'binding', media_id, {'owner': owner, 'pin': pin,
                                          'store_root': str(store._filesystem().root)})
        self.save(db, 'asset', public['asset_id'], public)
        return public

    def access(self, db, fs, context, input, pre):
        record = next((a for a in self.all(db, 'asset') if a['media_id'] == input['media_id']), None)
        if record is None:
            fail('NOT_FOUND', 'Media is unavailable in this namespace.')
        if pre['media_sha256'] != record['sha256']:
            fail('MEDIA_CHANGED', 'Media hash changed.')
        # Host must explicitly qualify transport in server-private context.
        # No remote/browser cookie support is inferred from a renderer string.
        qualified = context.get('qualified_media_transports', ())
        if input['transport'] not in qualified:
            fail('MEDIA_TRANSPORT_UNAVAILABLE', 'The authenticated host has not qualified this byte transport.')
        ttl = integer(input['requested_ttl_seconds'], 1, 900)
        access: dict[str, Any] = dict(access_id=opaque('access'), media_id=record['media_id'], sha256=record['sha256'],
                      mime=record['mime'], byte_length=record['byte_length'], transport=input['transport'],
                      disposition='attachment' if input['purpose'] == 'download' else 'inline',
                      range_supported=True, expires_at_epoch=self.clock() + ttl,
                      principal=context['principal'])
        self.save(db, 'access', access['access_id'], access)
        # Host prefixes its authenticated namespace; these segments are all
        # server-created opaque IDs. This is not an absolute URL or credential.
        public = {k: v for k, v in access.items() if k not in ('principal', 'expires_at_epoch')}
        public['relative_stream_route'] = ('/api/plugins/motion-studio/ui/v1/projects/' +
            quote(context['scope']['native_project_id'], safe='') + '/media-access/' + access['access_id'] + '/bytes')
        public['expires_in_seconds'] = ttl
        public['expires_at'] = datetime.fromtimestamp(access['expires_at_epoch'], timezone.utc).isoformat()
        return public

    @contextmanager
    def open_media(self, context, media_id, sha256):
        """Yield (verified seekable stream, safe metadata), never a pathname.

        Parent retains authentication per binary request, supports bounded
        Range/HEAD, and closes this context on auth revocation/disconnect.
        """
        hexhash(sha256)
        with self.database(context) as (db, fs):
            public = next((a for a in self.all(db, 'asset') if a['media_id'] == media_id), None)
            if public is None:
                fail('NOT_FOUND', 'Media is not owned by this namespace.')
            if public['sha256'] != sha256:
                fail('MEDIA_CHANGED', 'The immutable media pin differs.')
            binding = self.get(db, 'binding', media_id)
        # Binary GET context contains only authenticated scope and principal.
        # Store locators come from private committed metadata, never a caller.
        if not binding.get('store_root'):
            fail('ASSET_BYTES_UNAVAILABLE', 'Retained media lacks a private store binding.')
        store = AssetStore(binding['store_root'])
        catalog = ArtifactCatalog(store)
        record = catalog.resolve(binding['owner'], binding['pin'])
        with catalog.open_record(store._filesystem(), record) as stream:
            yield stream, {k: public[k] for k in ('media_id', 'sha256', 'mime', 'byte_length', 'display_name')}

    @contextmanager
    def open_access(self, context, access_id):
        with self.database(context) as (db, fs):
            access = self.get(db, 'access', access_id)
            if access['principal'] != context['principal']:
                fail('NOT_FOUND', 'Access lease is not owned by this principal.')
            if access['expires_at_epoch'] <= self.clock():
                fail('MEDIA_ACCESS_EXPIRED', 'Resolve a new authenticated media lease.')
        with self.open_media(context, access['media_id'], access['sha256']) as opened:
            stream, metadata = opened
            yield stream, {**metadata, 'disposition': access['disposition'],
                           'transport': access['transport'], 'range_supported': True}

    def read_media_chunk(self, context, access_id, *, offset=0, length=262144):
        """Authenticated JSON bridge for hosts without credentialed <video>.

        Only bounded base64 chunks cross the bridge; the renderer assembles a
        Blob URL. The host must explicitly advertise authenticated_blob support.
        """
        if 'authenticated_blob' not in context.get('qualified_media_transports', ()):
            fail('MEDIA_TRANSPORT_UNAVAILABLE', 'The host has not qualified the authenticated Blob bridge.')
        length = integer(length, 1, 262144)
        with self.open_access(context, access_id) as (stream, metadata):
            if metadata['transport'] != 'authenticated_blob':
                fail('MEDIA_TRANSPORT_UNAVAILABLE', 'This lease is not an authenticated Blob lease.')
            integer(offset, 0, metadata['byte_length'])
            stream.seek(offset)
            body = stream.read(min(length, metadata['byte_length'] - offset))
            return {**metadata, 'offset': offset, 'bytes_base64': base64.b64encode(body).decode('ascii'),
                    'chunk_sha256': hashlib.sha256(body).hexdigest(), 'eof': offset + len(body) == metadata['byte_length']}
