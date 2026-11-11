"""Ordinary explicit-Create authority, bound to one immutable plan and app session."""
import hashlib
from ..domain import Fault
from ..producer.live_sfx import USE, OrdinaryRuntime
from ..runs.admission import plan_key

POLICY = dict(version=1, use=USE, operation='sfx')


def configured(record):
    if record.get('adapter') == 'ace-step-local':
        from ..producer.music.admission import POLICY as MUSIC_POLICY
        return record.get('evaluation_scope') == MUSIC_POLICY and record['enabled']
    return record.get('evaluation_scope') == POLICY and record['enabled']


class NormalAdmission:
    def __init__(self, runs, run, owner):
        self.runs, self.run, self.use = runs, run, USE
        self.observation = {}
        if not isinstance(owner, str) or len(owner) < 32:
            raise Fault('AUTH_REQUIRED', 401)
        self.owner = hashlib.sha256(owner.encode()).hexdigest()
        row = runs.records.get(run)
        self.plan, self.key = row['plan'], row['plan_digest']
        with runs.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS normal_admissions(
                run TEXT PRIMARY KEY, plan TEXT, owner TEXT, state TEXT)''')
            existing = db.execute('SELECT * FROM normal_admissions WHERE run=?', (run,)).fetchone()
            if not existing:
                db.execute('INSERT INTO normal_admissions(run,plan,owner,state) VALUES(?,?,?,?)', (run,self.key,self.owner,'armed'))
            elif existing['owner'] != self.owner or existing['plan'] != self.key:
                raise Fault('ADMISSION_OWNER_CONFLICT', 409)
        adapter = runs.catalog.for_plan(self.plan)
        self.runtime = (adapter.normal_runtime(self.plan['binding'],self) if hasattr(adapter,'normal_runtime') else
                        OrdinaryRuntime(record=self.plan['binding'], fixture_only=row['fixture'], scope=self))

    def check_owner(self, owner):
        if not isinstance(owner, str) or hashlib.sha256(owner.encode()).hexdigest() != self.owner:
            raise Fault('ADMISSION_OWNER_CONFLICT', 403)

    def check_plan(self, plan):
        if plan != self.plan or plan_key(plan) != self.key:
            raise Fault('PLAN_CONFLICT', 409)
        with self.runs.store.transaction() as db:
            row = db.execute('SELECT * FROM normal_admissions WHERE run=?', (self.run,)).fetchone()
        if not row or row['state'] != 'armed' or row['owner'] != self.owner or row['plan'] != self.key:
            raise Fault('ADMISSION_CONSUMED', 409)
        for binding in (plan['binding'], self.runs.bindings.get(plan['binding']['id'])):
            if 'connector' in plan['binding']['pins'] and plan['binding']['pins'] != binding['pins']:
                raise Fault('CONNECTOR_DRIFT',409)
            if not configured(binding):
                raise Fault('FEATURE_DISABLED', 409)
            if binding['reason'] not in ('EVALUATION_ENABLED', 'OFFLINE_ONLY'):
                raise Fault(binding['reason'], 409)
        self.runs.recovery.check_intent(self.run)

    def enter(self):
        self.check_plan(self.plan)
        with self.runs.store.transaction() as db:
            if db.execute("UPDATE normal_admissions SET state='entered' WHERE run=? AND state='armed'", (self.run,)).rowcount != 1:
                raise Fault('ADMISSION_CONSUMED', 409)

    def install(self):
        self.runs.scopes[self.run] = self
        self.runs.bindings.scopes[self.key] = self

    def release(self):
        self.runs.scopes.pop(self.run, None)
        self.runs.bindings.scopes.pop(self.key, None)
