"""Bounded, read-only export over the actual Production service.

The trusted native caller supplies root and its observed current projection. This
module grants no authority, registers no endpoint, and never writes a destination.
"""
import base64
import copy
import hashlib
import io
import json
import secrets
import zipfile
from ..domain import Fault
from ..assets.wav import inspect_wav
from ..media_import.contracts import RetrieveTake
from .manifest import LIMIT, select, entry


class ExportArtifact:
    """Caller-owned transient bytes; each chunk repeats scope and revision checks."""
    def __init__(self, data, filename, mime, check):
        self._data, self._check = data, check
        self.filename, self.mime = filename, mime
        self.size = len(data)
        self.sha256 = hashlib.sha256(data).hexdigest()
        # An opaque transport identity, not a private path or content hash.
        self.take = secrets.token_hex(16)
        self.closed = False

    def descriptor(self):
        self._check()
        if self.closed:
            raise Fault('EXPORT_CLOSED', 409)
        return dict(take=self.take, filename=self.filename, mime=self.mime,
                    size=self.size, sha256=self.sha256)

    def chunk(self, offset):
        self._check()
        if self.closed:
            raise Fault('EXPORT_CLOSED', 409)
        if type(offset) is not int or not 0 <= offset < self.size:
            raise Fault('EXPORT_OFFSET_INVALID', 422)
        part = self._data[offset:offset + 49152]
        self._check()
        return dict(take=self.take, offset=offset, total=self.size,
                    bytes=base64.b64encode(part).decode('ascii'), sha256=self.sha256,
                    chunk_sha256=hashlib.sha256(part).hexdigest())

    def close(self):
        self.closed = True
        self._data = b''


class ProductionExport:
    """Use ProductionExport(productions).prepare(root, snapshot, asset_ids, ...).

    productions is the existing Productions instance (not its registration
    wrapper). Supply Lane B's same-Store MediaImports as media_imports for
    original-v1 imports; its trusted scope must use the canonical root here.
    assets.retrieve is the existing immutable-byte verification path for SFX.
    No user-supplied paths, retrieval callbacks or destination names are accepted.
    """
    def __init__(self, productions, *, media_imports=None):
        self.productions, self.media_imports = productions, media_imports
        if media_imports is not None and media_imports.store is not productions.store:
            raise ValueError('Export and media imports must use the same Store')

    def _authorize_imports(self, root, pins):
        imported = [pin for pin in pins if pin['storage'] == 'original-v1']
        if not imported:
            return
        if self.media_imports is None:
            raise Fault('EXPORT_IMPORT_UNAVAILABLE', 409)
        with self.productions.store.transaction() as db:
            for pin in imported:
                self.media_imports.owned(db, root, pin['artifact'])

    def prepare(self, root, snapshot, asset_ids, *, mode='zip', cancelled=lambda: False):
        snapshot = copy.deepcopy(snapshot)
        asset_ids = tuple(asset_ids)
        pins = select(snapshot, asset_ids)
        if mode not in ('zip', 'file') or (mode == 'file' and len(pins) != 1):
            raise Fault('EXPORT_MODE_UNSUPPORTED', 422)
        if sum(pin['bytes'] for pin in pins) > LIMIT:
            raise Fault('EXPORT_SIZE_UNSUPPORTED', 413)
        scope = copy.deepcopy(self.productions.scope(root))
        policy = copy.deepcopy(self.productions.policy)

        def check():
            if cancelled():
                raise Fault('EXPORT_CANCELLED', 409)
            if self.productions.scope(root) != scope or self.productions.policy != policy:
                raise Fault('EXPORT_SCOPE_CHANGED', 403)
            current = self.productions.read(root, snapshot['id'])['current']
            if current['id'] != snapshot['id'] or current['revision'] != snapshot['revision']:
                raise Fault('EXPORT_REVISION_CONFLICT', 409)
            if select(current, asset_ids) != pins:
                raise Fault('EXPORT_REVISION_CONFLICT', 409)
            self._authorize_imports(root, pins)

        check()
        output = io.BytesIO()
        entries = []
        if mode == 'zip':
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
                for pin in pins:
                    data, item = self._retrieve(root, pin, check)
                    entries.append(item)
                    self._write(archive, item['filename'], data, check)
                manifest = dict(schema_version=1, production=snapshot['id'],
                                revision=snapshot['revision'], outputs=entries)
                encoded = (json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
                self._write(archive, 'manifest.json', encoded, check)
            data = output.getvalue()
            filename, mime = 'motion-studio-selected.zip', 'application/zip'
        else:
            data, item = self._retrieve(root, pins[0], check)
            filename, mime = str(item['filename']).split('/')[-1], item['mime']
        if len(data) > LIMIT:
            raise Fault('EXPORT_SIZE_UNSUPPORTED', 413)
        check()
        return ExportArtifact(data, filename, mime, check)

    def _retrieve(self, root, pin, check):
        check()
        if pin['storage'] == 'original-v1':
            data, row = self.media_imports.retrieve(root, RetrieveTake(take=pin['take']))
        else:
            data, row = self.productions.assets.retrieve(pin['take'])
        check()
        # retrieve already verifies disk bytes; independently bind them to the
        # exact selected projection rather than trusting a self-consistent reply.
        if (row['id'] != pin['take'] or row['request'] != pin['request'] or
                row['artifact'] != pin['artifact'] or row['revision'] != pin['request_revision'] or
                len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']):
            raise Fault('EXPORT_INTEGRITY_FAILED', 409)
        stored = row['facts'] if isinstance(row['facts'], dict) else json.loads(row['facts'])
        facts = dict(stored)
        if pin['format'] == 'wav':
            facts.update(inspect_wav(data))
        from ..director.review.reports import check as check_take
        with self.productions.store.transaction() as db:
            coverage = check_take(db, row, data)
        item = entry(pin, facts)
        item['crystal_ball'] = coverage
        item['your_review'] = row['review']
        item['delivery_approval'] = 'Not granted by automated checks'
        return data, item

    @staticmethod
    def _write(archive, name, data, check):
        # Fixed timestamp, permissions, order and STORE encoding give identical
        # ZIP bytes across runs; payloads remain media-only, without sidecars.
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system, info.external_attr = 3, 0o100644 << 16
        with archive.open(info, 'w') as target:
            for offset in range(0, len(data), 49152):
                check()
                target.write(data[offset:offset + 49152])
        check()
