"""Native-only scoped adapters for immutable import, review and selected export."""
import time
from typing import Literal
from ...persistence.primitives import canonical, identity
from pydantic import Field
from ...domain import Fault, Strict
from ...media_import import MediaImports
from ...media_import.operations import invoke
from ...media_import.contracts import describe_take
from ...native.production.models import Chunk, Opaque
from ...production_export import ProductionExport


IMPORT_OPERATIONS = ('intent', 'begin', 'chunk', 'status', 'commit', 'cancel', 'describe', 'read_chunk')


class ImportIntent(Strict):
    production: Opaque
    expected: int = Field(ge=1)
    asset: Opaque
    command: Opaque


class ExportPrepare(Strict):
    production: Opaque
    expected: int = Field(ge=1)
    assets: list[Opaque] = Field(min_length=1, max_length=64)
    mode: Literal['zip', 'file'] = 'zip'


class ExportHandle(Strict):
    take: Opaque


class ExportChunk(ExportHandle):
    offset: int = Field(ge=0)


class Describe(Strict):
    production: Opaque
    asset: Opaque
    request: Opaque
    take: Opaque


EXPORT_SCHEMAS = dict(prepare=ExportPrepare, descriptor=ExportHandle,
                      chunk=ExportChunk, close=ExportHandle)


class ProductionMedia:
    def __init__(self, runtime):
        self.runtime = runtime
        self.imports = None
        self.exports = {}

    def acquire(self, root):
        service = self.runtime.acquire()
        service.scope(root)
        if self.imports is None:
            def authorize(db, scope, request):
                service.scope(scope)
                return service.creations.authorize_request(db, scope, request)
            self.imports = MediaImports(service.store, authorize, assets=service.assets)
        return service

    def close(self):
        for _, artifact in self.exports.values():
            artifact.close()
        self.exports.clear()

    def import_intent(self, service, root, model):
        """Save an asset-scoped import request without any generation prerequisite."""
        with service.store.transaction() as db:
            snapshot = service.read(root, model.production, db=db)['current']
            asset = next((a for a in snapshot['assets'] if a['id'] == model.asset), None)
            if asset is None:
                raise Fault('PRODUCTION_ASSET_NOT_FOUND', 404)
            payload = dict(operation='import_intent', root=root, **model.model_dump())
            def create():
                if snapshot['revision'] != model.expected:
                    raise Fault('PRODUCTION_STALE_REVISION', 409)
                request, now = identity(), time.time()
                value = dict(method='import', kind=asset['kind'], direction=asset['intent'])
                db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,NULL)',
                    (request, 1, asset['intent'], asset['kind'], '', now, now))
                db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                    (request, root, service.creations.scope(root).revision, identity(),
                     canonical(value), None, 'Import only', now))
                return dict(request=request, revision=1, kind=asset['kind'], method='import')
            return service.store.command(db, model.command, payload, create)


    def execute(self, operation, payload, root):
        service = self.acquire(root)
        if operation == 'media_import.intent':
            return self.import_intent(service, root, ImportIntent.model_validate(payload))
        if operation.startswith('media_import.'):
            return invoke(self.imports, root, operation.removeprefix('media_import.'), payload)
        if operation == 'describe':
            model = Describe.model_validate(payload)
            linked = Chunk(**model.model_dump(), offset=0)
            with service.store.transaction() as db:
                service.assert_linked(db, root, linked)
                request, take = service.records.take(db, root, model.request, model.take)
                return describe_take(take, kind=request['kind'], production=model.production, asset=model.asset)
        name = operation.removeprefix('export.')
        if name == 'prepare':
            model = ExportPrepare.model_validate(payload)
            snapshot = service.read(root, model.production)['current']
            if snapshot['revision'] != model.expected:
                raise Fault('PRODUCTION_STALE_REVISION', 409)
            if len(self.exports) >= 4:
                raise Fault('EXPORT_LIMIT_REACHED', 409)
            artifact = ProductionExport(service, media_imports=self.imports).prepare(
                root, snapshot, model.assets, mode=model.mode)
            self.exports[artifact.take] = (root, artifact)
            return artifact.descriptor()
        handle = ExportHandle.model_validate(payload) if name != 'chunk' else ExportChunk.model_validate(payload)
        record = self.exports.get(handle.take)
        if record is None or record[0] != root:
            raise Fault('EXPORT_SCOPE_DENIED', 403)
        artifact = record[1]
        if name == 'close':
            artifact.close()
            del self.exports[handle.take]
            return dict(take=handle.take, closed=True)
        return artifact.chunk(ExportChunk.model_validate(payload).offset) if name == 'chunk' else artifact.descriptor()


OPERATIONS = tuple('media_import.' + name for name in IMPORT_OPERATIONS) + (
    'describe',) + tuple('export.' + name for name in EXPORT_SCHEMAS)
