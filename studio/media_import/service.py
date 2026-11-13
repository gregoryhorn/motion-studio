"""Same-Store staged imports. Caller owns native admission and request authority."""
import base64
import binascii
import hashlib
import json
import os
import stat
from ..assets.retention import Assets, read_private, sync_directory
from ..domain import Fault, opaque
from ..persistence.primitives import canonical, identity
from ..media_import.contracts import CHUNK_BYTES, READ_CHUNK_BYTES, describe_take
from ..media_import.validation import inspect_media

SCHEMA = '''CREATE TABLE IF NOT EXISTS media_import_scopes(
    id TEXT PRIMARY KEY, scope TEXT NOT NULL, format TEXT NOT NULL, kind TEXT)'''


class MediaImports:
    """authorize(db, trusted_scope, request_id) must deny unowned/unadmitted requests.

    All public operations require the currently host-authorized scope, not a client
    root. Authorizer is called on every read/write, including receipt replay.
    No producer, request creation, selection or Production mutation is performed.
    """
    def __init__(self, store, authorize, *, assets=None):
        if not callable(authorize):
            raise TypeError('A trusted request authorizer is required')
        self.store, self.authorize = store, authorize
        self.assets = assets if assets is not None else Assets(store)
        if self.assets.store is not store:
            raise ValueError('Assets must use the same Store')
        self.after_finalize = lambda: None
        with store.transaction() as db:
            db.execute(SCHEMA)
            if 'kind' not in {row['name'] for row in db.execute('PRAGMA table_info(media_import_scopes)')}:
                db.execute('ALTER TABLE media_import_scopes ADD COLUMN kind TEXT')

    def check_scope(self, db, scope, request):
        if not isinstance(scope, str) or not scope:
            raise Fault('MEDIA_SCOPE_DENIED', 403)
        if self.authorize(db, scope, opaque(request)) is False:
            raise Fault('MEDIA_SCOPE_DENIED', 403)
        return self.store.request(db, request)

    def owned(self, db, scope, import_id):
        row = db.execute('''SELECT i.*,m.scope,m.format,m.kind FROM imports i
            JOIN media_import_scopes m ON m.id=i.id WHERE i.id=?''', (opaque(import_id),)).fetchone()
        if not row or row['scope'] != scope:
            raise Fault('MEDIA_SCOPE_DENIED', 403)
        self.check_scope(db, scope, row['request'])
        return row

    def path(self, import_id, final=False):
        return self.assets.path('media' if final else 'staging', import_id,
                                '.original' if final else '.media-part')

    @staticmethod
    def projection(row):
        return dict(id=row['id'], take=row['take'], status=row['status'], error=row['error'])

    def begin(self, scope, model):
        with self.store.transaction() as db:
            self.check_scope(db, scope, model.request)
            def operation():
                request = self.store.request(db, model.request, model.revision)
                expected_kind = {'png': 'Image', 'jpeg': 'Image', 'mp4': 'Video'}
                if (model.format in expected_kind and request['kind'] != expected_kind[model.format]
                        or model.format == 'wav' and request['kind'] not in ('Sound effects', 'Music', 'Voice')):
                    raise Fault('MEDIA_KIND_MISMATCH', 409)
                import_id, take = identity(), identity()
                db.execute('INSERT INTO imports VALUES(?,?,?,?,?,?,?,?,?)',
                           (import_id, model.request, model.revision, model.digest, model.size,
                            model.name, 'Media receiving', None, take))
                db.execute('INSERT INTO media_import_scopes(id,scope,format,kind) VALUES(?,?,?,?)',
                           (import_id, scope, model.format, request['kind']))
                return dict(id=import_id, take=take)
            return self.store.command(db, model.command,
                dict(operation='media_import', scope=scope, **model.model_dump()), operation)

    def status(self, scope, model):
        with self.store.transaction() as db:
            row = self.owned(db, scope, model.id)
            result = self.projection(row)
            try:
                path = self.path(model.id, row['status'] == 'Ready for review')
                result['received'] = len(read_private(path))
            except FileNotFoundError:
                result['received'] = 0
            except OSError:
                raise Fault('STORAGE_UNAVAILABLE') from None
            return result

    def chunk(self, scope, model):
        try:
            data = base64.b64decode(model.data, validate=True)
        except (ValueError, binascii.Error):
            raise Fault('INVALID_MEDIA_CHUNK') from None
        if not 0 < len(data) <= CHUNK_BYTES:
            raise Fault('INVALID_MEDIA_CHUNK')
        with self.store.transaction() as db:
            row = self.owned(db, scope, model.id)
            if row['status'] == 'Cancelled':
                raise Fault('IMPORT_CANCELLED', 409)
            if model.offset + len(data) > row['size']:
                raise Fault('IMPORT_BYTES_CONFLICT', 409)
            final = row['status'] == 'Ready for review' or self.path(model.id, True).exists()
            path = self.path(model.id, final)
            try:
                flags = os.O_RDONLY if final else os.O_RDWR | os.O_CREAT
                fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    os.close(fd)
                    raise Fault('UNSAFE_MEDIA_FILE')
                with os.fdopen(fd, 'rb' if final else 'r+b') as target:
                    size = os.fstat(target.fileno()).st_size
                    if size > row['size']:
                        raise Fault('IMPORT_BYTES_CONFLICT', 409)
                    if model.offset < size:
                        target.seek(model.offset)
                        if model.offset + len(data) > size or target.read(len(data)) != data:
                            raise Fault('IMPORT_BYTES_CONFLICT', 409)
                    elif model.offset == size and not final:
                        target.seek(size)
                        target.write(data)
                        target.flush()
                        os.fsync(target.fileno())
                        size += len(data)
                        sync_directory(path.parent)
                    else:
                        raise Fault('IMPORT_OFFSET_CONFLICT', 409)
            except OSError:
                raise Fault('STORAGE_UNAVAILABLE') from None
            return dict(id=model.id, received=size, status=row['status'])

    def finish(self, db, row):
        import_id = row['id']
        final, stage = self.path(import_id, True), self.path(import_id)
        try:
            data = read_private(final if final.exists() else stage)
            if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['digest']:
                raise Fault('IMPORT_BYTES_CONFLICT', 409)
            facts = inspect_media(data, row['format'])
            facts['storage'] = 'original-v1'
            # Decoding can take time; authorization must still hold before the
            # durable finalization, even if policy changed outside this DB.
            self.check_scope(db, row['scope'], row['request'])
            if not final.exists():
                os.link(stage, final, follow_symlinks=False)
                os.chmod(final, 0o400)
                sync_directory(final.parent)
            self.after_finalize()
            db.execute('INSERT INTO takes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (row['take'], import_id, import_id, row['request'], row['revision'],
                        row['digest'], row['size'], row['name'], canonical(facts),
                        'Not reviewed', 'user_import'))
            from ..director.review.reports import retained
            retained(self.store, db, row['take'], data)
            db.execute("UPDATE imports SET status='Ready for review',error=NULL WHERE id=?", (import_id,))
            return dict(id=import_id, take=row['take'], status='Ready for review', error=None)
        except OSError:
            raise Fault('STORAGE_UNAVAILABLE') from None

    def commit(self, scope, model):
        failure = None
        result = None
        with self.store.transaction() as db:
            row = self.owned(db, scope, model.id)
            if row['status'] == 'Ready for review':
                return self.projection(row)
            if row['status'] == 'Cancelled':
                raise Fault('IMPORT_CANCELLED', 409)
            try:
                result = self.finish(db, row)
            except Fault as error:
                failure = error
                db.execute("UPDATE imports SET status='Media failed',error=? WHERE id=?", (error.code, model.id))
        if failure:
            raise failure
        return result

    def cancel(self, scope, model):
        with self.store.transaction() as db:
            row = self.owned(db, scope, model.id)
            if row['status'] == 'Ready for review':
                return self.projection(row)
            # A durable final file is an uncertain commit, not permission to discard.
            if self.path(model.id, True).exists():
                return self.finish(db, row)
            db.execute("UPDATE imports SET status='Cancelled',error=NULL WHERE id=?", (model.id,))
            return dict(id=model.id, take=row['take'], status='Cancelled', error=None)

    def retrieve(self, scope, model):
        with self.store.transaction() as db:
            take = self.store.take(db, model.take)
            self.owned(db, scope, take['import_id'])
        data, row = self.assets.retrieve(model.take)
        with self.store.transaction() as db:
            self.owned(db, scope, row['import_id'])
        return data, row

    def read_chunk(self, scope, model):
        data, row = self.retrieve(scope, model)
        if model.offset >= len(data):
            raise Fault('MEDIA_CHUNK_INVALID', 422)
        part = data[model.offset:model.offset + READ_CHUNK_BYTES]
        return dict(take=row['id'], offset=model.offset, total=len(data),
                    bytes=base64.b64encode(part).decode(), sha256=row['digest'],
                    chunk_sha256=hashlib.sha256(part).hexdigest(),
                    mime=json.loads(row['facts'])['mime'])

    def describe(self, scope, model):
        """Authorize before exposing immutable identity and measured facts."""
        with self.store.transaction() as db:
            take = self.store.take(db, model.take)
            imported = self.owned(db, scope, take['import_id'])
            kind = imported['kind'] or {'png': 'Image', 'jpeg': 'Image', 'mp4': 'Video'}.get(imported['format'])
            if kind is None:
                request = self.store.request(db, take['request'])
                # Early WIP receipts did not retain the audio application kind.
                # A later request edit cannot establish that historical fact.
                if request['revision'] != take['revision']:
                    raise Fault('MEDIA_DESCRIPTOR_UNAVAILABLE', 409)
                kind = request['kind']
            return describe_take(take, kind=kind)
