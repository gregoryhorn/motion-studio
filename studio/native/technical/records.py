"""PTP1 records reuse CS1 jobs/validator, with app-owned generations, not host epochs."""
import json
from ...domain import Fault
from ...persistence.primitives import identity, canonical
from ...connectors.synthesis.evidence import snapshot
from ...connectors.synthesis.jobs import Jobs


class TechnicalJobs(Jobs):
    def select_revision(self, scope, value, expected):
        admitted = snapshot(value)
        with self.store.transaction() as db:
            current = db.execute('SELECT evidence FROM cs_current WHERE profile=? AND session=?', (scope.profile, scope.session)).fetchone()
            revision = self.evidence(db, scope, current[0])['revision'] if current else 0
            if expected != revision: raise Fault('TECHNICAL_EVIDENCE_STALE', 409)
            row = dict(id=identity(), revision=revision+1, **admitted)
            db.execute('INSERT INTO cs_evidence VALUES(?,?,?,?,?)', (row['id'], scope.profile, scope.session, 0, canonical(row)))
            db.execute('INSERT OR REPLACE INTO cs_current VALUES(?,?,?)', (scope.profile, scope.session, row['id']))
        return row

    def prepare(self, scope, command, evidence_id, revision, template, route):
        row, created = super().prepare(scope, command, evidence_id, revision, template, route)
        if created:
            with self.store.transaction() as db:
                row['service_generation'] = self.store.generation
                self.write(db, row)
            return row, True
        return row, False

    def fresh(self, db, scope, row, route):
        return row.get('service_generation') == self.store.generation and super().fresh(db, scope, row, route)

    def overview(self, scope):
        with self.store.transaction() as db:
            current = db.execute('SELECT evidence FROM cs_current WHERE profile=? AND session=?', (scope.profile, scope.session)).fetchone()
            selected = self.evidence(db, scope, current[0]) if current else None
            records = db.execute('SELECT body FROM cs_jobs WHERE profile=? AND session=? ORDER BY rowid DESC LIMIT 5', (scope.profile, scope.session)).fetchall()
            occupied = bool(db.execute('SELECT 1 FROM cs_jobs WHERE active=1').fetchone())
            return dict(current=dict(id=selected['id'], revision=selected['revision']) if selected else None,
                latest=[self.public(json.loads(row[0])) for row in records], occupied=occupied)
