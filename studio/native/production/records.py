"""SQLite projections for versioned productions over existing immutable takes."""
import json
import time
from ...domain import Fault, opaque
from ...persistence.primitives import canonical


SCHEMA = '''
CREATE TABLE IF NOT EXISTS production_roots(root TEXT PRIMARY KEY, policy TEXT);
CREATE TABLE IF NOT EXISTS productions(
    id TEXT PRIMARY KEY, root TEXT, policy TEXT, command TEXT, title TEXT,
    text TEXT, purpose TEXT, audience TEXT, usage TEXT, revision INTEGER,
    brief_revision INTEGER, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS production_assets(
    production TEXT, id TEXT, position INTEGER, kind TEXT, intent TEXT,
    selected_take TEXT, stale INTEGER, depends_on TEXT, revision INTEGER,
    pointer_revision INTEGER, selection_brief_revision INTEGER,
    selection_asset_revision INTEGER, PRIMARY KEY(production, id));
CREATE TABLE IF NOT EXISTS production_asset_takes(
    production TEXT, asset TEXT, request TEXT, take TEXT, source_revision INTEGER,
    artifact TEXT, added REAL, PRIMARY KEY(production, asset, take));
CREATE TABLE IF NOT EXISTS production_references(
    production TEXT, id TEXT, revision INTEGER, request TEXT, take TEXT,
    label TEXT, PRIMARY KEY(production, id));
CREATE TABLE IF NOT EXISTS production_reference_history(
    production TEXT, id TEXT, revision INTEGER, request TEXT, take TEXT,
    label TEXT, PRIMARY KEY(production, id, revision));
CREATE TABLE IF NOT EXISTS production_dependencies(
    production TEXT, asset TEXT, reference TEXT, revision INTEGER,
    PRIMARY KEY(production, asset, reference));
CREATE TABLE IF NOT EXISTS production_selection_references(
    production TEXT, asset TEXT, reference TEXT, revision INTEGER,
    PRIMARY KEY(production, asset, reference));
CREATE TABLE IF NOT EXISTS production_selection_dependencies(
    production TEXT, asset TEXT, dependency TEXT, take TEXT, pointer_revision INTEGER,
    PRIMARY KEY(production, asset, dependency));
CREATE TABLE IF NOT EXISTS production_revisions(
    production TEXT, revision INTEGER, snapshot TEXT,
    PRIMARY KEY(production, revision));
CREATE INDEX IF NOT EXISTS production_root_list ON productions(root, created);
'''


class ProductionRecords:
    def __init__(self, store, creations):
        self.store, self.creations = store, creations
        with store.transaction() as db:
            db.executescript(SCHEMA)

    def owned(self, db, root, production, expected=None):
        row = db.execute('SELECT * FROM productions WHERE id=? AND root=?',
                         (opaque(production), root)).fetchone()
        if not row:
            raise Fault('PRODUCTION_SCOPE_DENIED', 403)
        if expected is not None and row['revision'] != expected:
            raise Fault('PRODUCTION_STALE_REVISION', 409)
        return row

    def asset(self, db, production, asset):
        row = db.execute('SELECT * FROM production_assets WHERE production=? AND id=?',
                         (production, opaque(asset))).fetchone()
        if not row:
            raise Fault('PRODUCTION_ASSET_NOT_FOUND', 404)
        return row

    def take(self, db, root, request, take):
        request_row = self.creations.authorize_request(db, root, request)
        row = self.store.take(db, take)
        if row['request'] != request:
            raise Fault('PRODUCTION_TAKE_SCOPE_MISMATCH', 403)
        return request_row, row

    @staticmethod
    def take_summary(row, selected=None):
        return dict(id=row['id'], request=row['request'], request_revision=row['revision'],
                    source_request_revision=row['revision'], artifact=row['artifact'],
                    review=row['review'], origin=row['origin'], digest=row['digest'],
                    size=row['size'], facts=json.loads(row['facts']), selected=selected)

    def rows(self, db, sql, parameters):
        return [dict(row) for row in db.execute(sql, parameters)]

    def projection(self, db, production):
        row = db.execute('SELECT * FROM productions WHERE id=?', (production,)).fetchone()
        result = dict(id=row['id'], revision=row['revision'], brief_revision=row['brief_revision'],
                      command=row['command'], title=row['title'], created=row['created'],
                      updated=row['updated'], policy=row['policy'],
                      brief={key: row[key] for key in ('text', 'purpose', 'audience', 'usage')},
                      assets=[], references=[])
        for reference in db.execute(
                'SELECT * FROM production_references WHERE production=? ORDER BY rowid', (production,)):
            _, take = self.take(db, row['root'], reference['request'], reference['take'])
            result['references'].append(dict(id=reference['id'], revision=reference['revision'],
                label=reference['label'], take=self.take_summary(take)))
        for asset in db.execute(
                'SELECT * FROM production_assets WHERE production=? ORDER BY position', (production,)):
            takes = [self.take_summary(self.take(db, row['root'], link['request'], link['take'])[1],
                                       asset['selected_take'] == link['take'])
                     for link in db.execute('''SELECT * FROM production_asset_takes
                         WHERE production=? AND asset=? ORDER BY added, take''',
                         (production, asset['id']))]
            references = self.rows(db, '''SELECT reference AS id,revision FROM production_dependencies
                WHERE production=? AND asset=? ORDER BY reference''', (production, asset['id']))
            selection_references = self.rows(db, '''SELECT reference AS id,revision
                FROM production_selection_references WHERE production=? AND asset=? ORDER BY reference''',
                (production, asset['id']))
            selection_dependencies = self.rows(db, '''SELECT dependency AS id,take,pointer_revision
                FROM production_selection_dependencies WHERE production=? AND asset=? ORDER BY dependency''',
                (production, asset['id']))
            result['assets'].append(dict(id=asset['id'], position=asset['position'],
                kind=asset['kind'], intent=asset['intent'], selected_take=asset['selected_take'],
                stale=bool(asset['stale']), depends_on=json.loads(asset['depends_on']),
                revision=asset['revision'], pointer_revision=asset['pointer_revision'],
                selection_brief_revision=asset['selection_brief_revision'],
                selection_asset_revision=asset['selection_asset_revision'],
                references=references, selection_references=selection_references,
                selection_dependencies=selection_dependencies, takes=takes))
        return result

    def record_revision(self, db, production, revision):
        snapshot = self.projection(db, production)
        db.execute('INSERT INTO production_revisions VALUES(?,?,?)',
                   (production, revision, canonical(snapshot)))

    def available(self, db, root):
        rows = db.execute('''SELECT request FROM creation_commands WHERE root=?
                             ORDER BY rowid DESC LIMIT 100''', (root,))
        result = []
        for item in rows:
            request = self.creations.authorize_request(db, root, item['request'])
            for take in db.execute('SELECT * FROM takes WHERE request=? ORDER BY rowid', (request['id'],)):
                summary = self.take_summary(take)
                summary.update(direction=request['text'], kind=request['kind'])
                result.append(summary)
        return result[:200]

    @staticmethod
    def touch(db, production, revision):
        db.execute('UPDATE productions SET revision=?,updated=? WHERE id=?',
                   (revision, time.time(), production))
