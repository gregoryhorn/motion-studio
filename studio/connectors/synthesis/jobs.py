"""Private immutable technical evidence and finite durable synthesis control records."""
import json
import time
from ...domain import Fault, opaque
from ...persistence.primitives import canonical, identity
from ...connectors.synthesis.evidence import snapshot, template_ref



class Jobs:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cs_evidence(id TEXT PRIMARY KEY, profile TEXT, session TEXT, epoch INTEGER, body TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS cs_current(profile TEXT, session TEXT, evidence TEXT, PRIMARY KEY(profile,session))')
            db.execute('CREATE TABLE IF NOT EXISTS cs_jobs(id TEXT PRIMARY KEY, profile TEXT, session TEXT, command TEXT, active INTEGER, body TEXT, UNIQUE(profile,session,command))')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS cs_active ON cs_jobs(profile) WHERE active=1')

    def select(self, scope, value):
        """Owned evidence-reader port; not a synthesis RPC and never an inference."""
        admitted = snapshot(value)  # Reject before hashing/persisting any input.
        identifier = identity()
        row = dict(id=identifier, revision=1, **admitted)
        with self.store.transaction() as db:
            db.execute('INSERT INTO cs_evidence VALUES(?,?,?,?,?)', (identifier, scope.profile, scope.session, scope.epoch, canonical(row)))
            db.execute('INSERT OR REPLACE INTO cs_current VALUES(?,?,?)', (scope.profile, scope.session, identifier))
        return row

    def evidence(self, db, scope, identifier):
        row = db.execute('SELECT * FROM cs_evidence WHERE id=?', (opaque(identifier),)).fetchone()
        if not row or (row['profile'], row['session'], row['epoch']) != (scope.profile, scope.session, scope.epoch):
            raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        selected = json.loads(row['body'])
        checked = snapshot(selected['body'])
        if checked['digest'] != selected['digest'] or checked['template'] != selected['template']:
            raise Fault('SYNTHESIS_EVIDENCE_CHANGED', 409)
        return selected

    @staticmethod
    def owned(db, scope, identifier):
        row = db.execute('SELECT * FROM cs_jobs WHERE id=?', (opaque(identifier),)).fetchone()
        if not row or (row['profile'], row['session']) != (scope.profile, scope.session):
            raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        body = json.loads(row['body'])
        if body['epoch'] != scope.epoch: raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        return body

    @staticmethod
    def write(db, row):
        row['updated'] = time.time()
        db.execute('UPDATE cs_jobs SET active=?,body=? WHERE id=?', (int(row['active']), canonical(row), row['id']))

    @staticmethod
    def public(row, result=False):
        keys = ['id', 'state', 'invocation_possible', 'active', 'discarded', 'evidence', 'evidence_digest', 'template', 'route', 'error']
        if result: keys += ['result']
        return {key: row.get(key) for key in keys}

    def recover(self):
        """Called only on exclusive service ownership acquisition, not status/open."""
        with self.store.transaction() as db:
            for record in db.execute('SELECT body FROM cs_jobs WHERE active=1').fetchall():
                row = json.loads(record[0])
                row['state'] = 'Outcome unknown' if row['invocation_possible'] else 'Cancelled before dispatch'
                row['active'] = row['invocation_possible']
                row['error'] = 'SETTLEMENT_UNOBSERVED' if row['active'] else None
                self.write(db, row)

    def prepare(self, scope, command, evidence_id, revision, template, route):
        opaque(command)
        with self.store.transaction() as db:
            selected = self.evidence(db, scope, evidence_id)
            inputs = dict(evidence=evidence_id, revision=revision, template=template)
            old = db.execute('SELECT body FROM cs_jobs WHERE profile=? AND session=? AND command=?',
                             (scope.profile, scope.session, command)).fetchone()
            if old:
                row = json.loads(old[0])
                if row['inputs'] != inputs or row['epoch'] != scope.epoch: raise Fault('COMMAND_CONFLICT', 409)
                return row, False
            if revision != selected['revision'] or template != template_ref(): raise Fault('SYNTHESIS_STALE', 409)
            current = db.execute('SELECT evidence FROM cs_current WHERE profile=? AND session=?', (scope.profile, scope.session)).fetchone()
            if not current or current[0] != evidence_id: raise Fault('SYNTHESIS_STALE', 409)
            if db.execute('SELECT 1 FROM cs_jobs WHERE profile=? AND active=1', (scope.profile,)).fetchone():
                raise Fault('SYNTHESIS_SLOT_BLOCKED', 409)
            row = dict(id=identity(), inputs=inputs, epoch=scope.epoch, evidence=evidence_id,
                evidence_digest=selected['digest'], template=template, route=route, state='Prepared',
                active=True, invocation_possible=False, discarded=False, result=None, error=None,
                created=time.time(), updated=time.time())
            db.execute('INSERT INTO cs_jobs VALUES(?,?,?,?,?,?)',
                       (row['id'], scope.profile, scope.session, command, 1, canonical(row)))
        return row, True

    def fresh(self, db, scope, row, route):
        selected = self.evidence(db, scope, row['evidence'])
        current = db.execute('SELECT evidence FROM cs_current WHERE profile=? AND session=?', (scope.profile, scope.session)).fetchone()
        return bool(current and current[0] == row['evidence'] and row['evidence_digest'] == selected['digest']
                    and row['template'] == template_ref() and row['route'] == route)
