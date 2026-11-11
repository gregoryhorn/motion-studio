"""Revision-safe Production commands; no producer or media-copy path."""
import base64
import hashlib
import json
import time
from ...domain import Fault, KINDS, opaque
from ...persistence.primitives import canonical, identity
from ...native.production.records import ProductionRecords


CAPABILITIES = {kind: dict(generation='Separate creation/tool authority required; Music unqualified',
    viewer='Retained image/audio/video in the native panel') for kind in KINDS}


class Productions:
    def __init__(self, runtime, store, creations, policy):
        self.runtime, self.store, self.creations, self.policy = runtime, store, creations, policy
        self.records = ProductionRecords(store, creations)
        self.assets = creations.assets

    def admit(self, root):
        self.policy.access(self.runtime.ctx.profile_name)
        scope = self.creations.scope(root)
        with self.store.transaction() as db:
            db.execute('INSERT OR REPLACE INTO production_roots VALUES(?,?)',
                       (root, self.policy.revision))
        return dict(admitted=True, revision=scope.revision, effects=False)

    def scope(self, root):
        scope = self.creations.scope(root)
        self.policy.access(self.runtime.ctx.profile_name)
        with self.store.transaction() as db:
            row = db.execute('SELECT policy FROM production_roots WHERE root=?', (root,)).fetchone()
        if not row or row[0] != self.policy.revision:
            raise Fault('PRODUCTION_WORKFLOW_REVIEW_REQUIRED', 403)
        return scope

    def read(self, root, production=None, *, db=None):
        self.scope(root)
        if db is None:
            with self.store.transaction() as connection:
                return self.read(root, production, db=connection)
        if production is None:
            row = db.execute('SELECT id FROM productions WHERE root=? ORDER BY created DESC LIMIT 1',
                             (root,)).fetchone()
            if not row:
                return dict(current=None, available=self.records.available(db, root), capabilities=CAPABILITIES)
            production = row[0]
        self.records.owned(db, root, production)
        return dict(current=self.records.projection(db, production),
                    available=self.records.available(db, root), capabilities=CAPABILITIES)

    def listing(self, root):
        self.scope(root)
        with self.store.transaction() as db:
            rows = db.execute('SELECT id FROM productions WHERE root=? ORDER BY created DESC LIMIT 100',
                              (root,)).fetchall()
            return dict(productions=[self.records.projection(db, row[0]) for row in rows],
                        available=self.records.available(db, root), capabilities=CAPABILITIES)

    @staticmethod
    def payload(root, operation, model):
        return dict(root=root, operation=operation, **model.model_dump())

    def envelope(self, root, result, replayed):
        response = self.read(root, result['production'])
        response.update(receipt=result, replayed=replayed)
        return response

    def create(self, root, model):
        self.scope(root)
        with self.store.transaction() as db:
            replayed = db.execute('SELECT 1 FROM receipts WHERE command=?', (model.command,)).fetchone() is not None
            def operation():
                self.scope(root)
                production, now = identity(), time.time()
                brief = model.brief
                db.execute('INSERT INTO productions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (production, root, self.policy.revision, model.command, model.title, brief.text,
                     brief.purpose, brief.audience, brief.usage, 1, 1, now, now))
                for position, kind in enumerate(model.kinds):
                    db.execute('INSERT INTO production_assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                               (production, identity(), position, kind, '', None, 0, '[]', 1, 0, None, None))
                self.records.record_revision(db, production, 1)
                return dict(production=production, revision=1)
            result = self.store.command(db, model.command, self.payload(root, 'create', model), operation)
        return self.envelope(root, result, replayed)

    def command_revision(self, root, model, operation, change):
        self.scope(root)
        with self.store.transaction() as db:
            self.records.owned(db, root, model.production)
            # Reauthorize existing sources before replacement could hide a revoked
            # reference; record_revision repeats this check before the commit.
            self.records.projection(db, model.production)
            replayed = db.execute('SELECT 1 FROM receipts WHERE command=?', (model.command,)).fetchone() is not None
            def perform():
                self.scope(root)
                row = self.records.owned(db, root, model.production, model.expected)
                revision = row['revision'] + 1
                details = change(db, revision) or {}
                self.records.touch(db, model.production, revision)
                self.records.record_revision(db, model.production, revision)
                return dict(production=model.production, revision=revision, **details)
            result = self.store.command(db, model.command, self.payload(root, operation, model), perform)
        return self.envelope(root, result, replayed)

    def update_brief(self, root, model):
        def change(db, revision):
            db.execute('''UPDATE productions SET title=?,text=?,purpose=?,audience=?,usage=?,
                          brief_revision=brief_revision+1 WHERE id=?''',
                       (model.title, model.brief.text, model.brief.purpose, model.brief.audience,
                        model.brief.usage, model.production))
            self.mark_stale(db, model.production, self.selected_assets(db, model.production))
        return self.command_revision(root, model, 'update_brief', change)

    def validate_graph(self, db, production, asset, dependencies):
        graph = {row['id']: set(json.loads(row['depends_on'])) for row in db.execute(
            'SELECT id,depends_on FROM production_assets WHERE production=?', (production,))}
        graph[asset] = set(dependencies)
        for dependency in dependencies:
            if dependency == asset:
                raise Fault('PRODUCTION_DEPENDENCY_INVALID', 422)
            self.records.asset(db, production, dependency)
        def reaches(current, target, seen):
            if current == target:
                return True
            if current in seen:
                return False
            return any(reaches(item, target, seen | {current}) for item in graph.get(current, ()))
        if any(reaches(dependency, asset, set()) for dependency in dependencies):
            raise Fault('PRODUCTION_DEPENDENCY_CYCLE', 409)

    def links(self, db, model, production, asset):
        for dependency in model.depends_on:
            self.records.asset(db, production, dependency)
        db.execute('DELETE FROM production_dependencies WHERE production=? AND asset=?', (production, asset))
        for reference in dict.fromkeys(model.references):
            row = db.execute('SELECT revision FROM production_references WHERE production=? AND id=?',
                             (production, opaque(reference))).fetchone()
            if not row:
                raise Fault('PRODUCTION_REFERENCE_NOT_FOUND', 404)
            db.execute('INSERT INTO production_dependencies VALUES(?,?,?,?)',
                       (production, asset, reference, row[0]))

    def reorder(self, db, production, asset, position):
        if position is None:
            return
        rows = db.execute('''SELECT id FROM production_assets WHERE production=? AND id!=?
                             ORDER BY position,rowid''', (production, asset)).fetchall()
        ordered = [row[0] for row in rows]
        ordered.insert(min(position, len(ordered)), asset)
        for index, identifier in enumerate(ordered):
            db.execute('UPDATE production_assets SET position=? WHERE production=? AND id=?',
                       (index, production, identifier))

    def add_asset(self, root, model):
        def change(db, revision):
            self.validate_graph(db, model.production, asset=None, dependencies=model.depends_on)
            position = db.execute('SELECT COUNT(*) FROM production_assets WHERE production=?',
                                  (model.production,)).fetchone()[0]
            asset = identity()
            db.execute('INSERT INTO production_assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (model.production, asset, position, model.kind, model.intent, None, 0,
                        canonical(model.depends_on), 1, 0, None, None))
            self.links(db, model, model.production, asset)
            self.reorder(db, model.production, asset, model.position)
            return dict(asset=asset)
        return self.command_revision(root, model, 'add_asset', change)

    def update_asset(self, root, model):
        def change(db, revision):
            self.validate_graph(db, model.production, model.asset, model.depends_on)
            asset = self.records.asset(db, model.production, model.asset)
            if asset['kind'] != model.kind and db.execute(
                    'SELECT 1 FROM production_asset_takes WHERE production=? AND asset=?',
                    (model.production, model.asset)).fetchone():
                raise Fault('PRODUCTION_MEDIA_KIND_MISMATCH', 409)
            db.execute('''UPDATE production_assets SET kind=?,intent=?,depends_on=?,revision=revision+1
                          WHERE production=? AND id=?''', (model.kind, model.intent,
                       canonical(model.depends_on), model.production, model.asset))
            self.links(db, model, model.production, model.asset)
            self.reorder(db, model.production, model.asset, model.position)
            self.mark_stale(db, model.production, {model.asset})
        return self.command_revision(root, model, 'update_asset', change)

    def linked_take(self, db, root, model, kind=None):
        request, take = self.records.take(db, root, model.request, model.take)
        if kind is not None and request['kind'] != kind:
            raise Fault('PRODUCTION_MEDIA_KIND_MISMATCH', 409)
        return take

    def add_reference(self, root, model):
        def change(db, revision):
            take = self.linked_take(db, root, model)
            reference = identity()
            values = (model.production, reference, 1, model.request, take['id'], model.label)
            db.execute('INSERT INTO production_references VALUES(?,?,?,?,?,?)', values)
            db.execute('INSERT INTO production_reference_history VALUES(?,?,?,?,?,?)', values)
            return dict(reference=reference)
        return self.command_revision(root, model, 'add_reference', change)

    def update_reference(self, root, model):
        def change(db, revision):
            take = self.linked_take(db, root, model)
            row = db.execute('SELECT * FROM production_references WHERE production=? AND id=?',
                             (model.production, model.reference)).fetchone()
            if not row:
                raise Fault('PRODUCTION_REFERENCE_NOT_FOUND', 404)
            next_revision = row['revision'] + 1
            db.execute('''UPDATE production_references SET revision=?,request=?,take=?,label=?
                          WHERE production=? AND id=?''', (next_revision, model.request, take['id'],
                       model.label, model.production, model.reference))
            db.execute('INSERT INTO production_reference_history VALUES(?,?,?,?,?,?)',
                       (model.production, model.reference, next_revision, model.request, take['id'], model.label))
            affected = {item[0] for item in db.execute('''SELECT asset FROM production_selection_references
                WHERE production=? AND reference=? AND revision<?''',
                (model.production, model.reference, next_revision))}
            self.mark_stale(db, model.production, affected)
            return dict(reference_revision=next_revision)
        return self.command_revision(root, model, 'update_reference', change)

    def link_take(self, root, model):
        def change(db, revision):
            asset = self.records.asset(db, model.production, model.asset)
            take = self.linked_take(db, root, model, asset['kind'])
            db.execute('''INSERT OR IGNORE INTO production_asset_takes VALUES(?,?,?,?,?,?,?)''',
                       (model.production, model.asset, model.request, take['id'], take['revision'],
                        take['artifact'], time.time()))
            return dict(asset=model.asset, take=take['id'], source_request_revision=take['revision'])
        return self.command_revision(root, model, 'link_take', change)

    def selected_assets(self, db, production):
        return {row[0] for row in db.execute('''SELECT id FROM production_assets
            WHERE production=? AND selected_take IS NOT NULL''', (production,))}

    def mark_stale(self, db, production, initial):
        affected = set(initial)
        assets = db.execute('SELECT id,depends_on FROM production_assets WHERE production=?', (production,)).fetchall()
        changed = True
        while changed:
            changed = False
            for asset in assets:
                if asset['id'] not in affected and affected.intersection(json.loads(asset['depends_on'])):
                    affected.add(asset['id'])
                    changed = True
        for asset in affected:
            db.execute('''UPDATE production_assets SET stale=1 WHERE production=? AND id=?
                          AND selected_take IS NOT NULL''', (production, asset))

    def select_take(self, root, model):
        def change(db, revision):
            production = self.records.owned(db, root, model.production)
            asset = self.records.asset(db, model.production, model.asset)
            linked = db.execute('''SELECT 1 FROM production_asset_takes
                WHERE production=? AND asset=? AND request=? AND take=?''',
                (model.production, model.asset, model.request, model.take)).fetchone()
            if not linked:
                raise Fault('PRODUCTION_TAKE_NOT_LINKED', 409)
            self.linked_take(db, root, model, asset['kind'])
            db.execute('''UPDATE production_assets SET selected_take=?,stale=0,pointer_revision=?,
                selection_brief_revision=?,selection_asset_revision=? WHERE production=? AND id=?''',
                (model.take, revision, production['brief_revision'], asset['revision'],
                 model.production, model.asset))
            db.execute('DELETE FROM production_selection_references WHERE production=? AND asset=?',
                       (model.production, model.asset))
            db.execute('''INSERT INTO production_selection_references
                SELECT d.production,d.asset,d.reference,r.revision FROM production_dependencies d
                JOIN production_references r ON r.production=d.production AND r.id=d.reference
                WHERE d.production=? AND d.asset=?''', (model.production, model.asset))
            db.execute('DELETE FROM production_selection_dependencies WHERE production=? AND asset=?',
                       (model.production, model.asset))
            for dependency in json.loads(asset['depends_on']):
                upstream = self.records.asset(db, model.production, dependency)
                db.execute('INSERT INTO production_selection_dependencies VALUES(?,?,?,?,?)',
                           (model.production, model.asset, dependency, upstream['selected_take'],
                            upstream['pointer_revision']))
            direct = {row['id'] for row in db.execute('SELECT id,depends_on FROM production_assets WHERE production=?',
                      (model.production,)) if model.asset in json.loads(row['depends_on'])}
            self.mark_stale(db, model.production, direct)
            return dict(asset=model.asset, take=model.take)
        return self.command_revision(root, model, 'select_take', change)

    def chunk(self, root, model):
        self.scope(root)
        with self.store.transaction() as db:
            self.assert_linked(db, root, model)
        data, row = self.assets.retrieve(model.take)
        part = data[model.offset:model.offset + 49152]
        if model.offset >= len(data):
            raise Fault('CREATION_CHUNK_INVALID', 422)
        self.scope(root)
        with self.store.transaction() as db:
            self.assert_linked(db, root, model)
        return dict(take=row['id'], offset=model.offset, total=len(data),
                    bytes=base64.b64encode(part).decode(), sha256=hashlib.sha256(data).hexdigest(),
                    chunk_sha256=hashlib.sha256(part).hexdigest())

    def assert_linked(self, db, root, model):
        self.records.owned(db, root, model.production)
        self.records.asset(db, model.production, model.asset)
        linked = db.execute('''SELECT 1 FROM production_asset_takes WHERE production=?
            AND asset=? AND request=? AND take=?''', (model.production, model.asset,
            model.request, model.take)).fetchone()
        if not linked:
            raise Fault('PRODUCTION_TAKE_NOT_LINKED', 409)
        self.records.take(db, root, model.request, model.take)
