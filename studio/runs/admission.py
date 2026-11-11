"""Trusted, plan-bound one-candidate evaluation policy; never a browser enable flag."""
import hashlib
import time
from ..domain import Fault
from ..persistence.store import canonical


def plan_key(plan):
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


class OneCandidate:
    scope = 'bounded-local-qualification-r1'

    def __init__(self, runs, run, owner, use):
        self.runs, self.run, self.use = runs, run, use
        self.owner = self.owner_key(owner)
        row = runs.records.get(run)
        self.plan, self.key = row['plan'], row['plan_digest']
        self.runtime = None
        self.observation = {}
        if self.plan['schema'] != 2 or row['status'] != 'Prepared' or self.key != plan_key(self.plan):
            raise Fault('SCOPE_CONFLICT', 409)
        with runs.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS bounded_admission(
                scope TEXT PRIMARY KEY, run TEXT UNIQUE, plan TEXT, owner TEXT,
                use TEXT, expires REAL, state TEXT)''')
            if db.execute('SELECT 1 FROM bounded_admission WHERE scope=?', (self.scope,)).fetchone():
                raise Fault('SCOPE_ALREADY_USED', 409)
            db.execute('INSERT INTO bounded_admission VALUES(?,?,?,?,?,?,?)',
                       (self.scope, run, self.key, self.owner, use, time.time() + 900, 'armed'))

    @staticmethod
    def owner_key(value):
        if not isinstance(value, str) or len(value) < 32:
            raise Fault('AUTH_REQUIRED', 401)
        return hashlib.sha256(value.encode()).hexdigest()

    def check_owner(self, owner):
        if self.owner_key(owner) != self.owner:
            raise Fault('SCOPE_OWNER_DENIED', 403)

    def check_plan(self, plan):
        if plan != self.plan or plan_key(plan) != self.key:
            raise Fault('SCOPE_CONFLICT', 409)
        with self.runs.store.transaction() as db:
            row = db.execute('SELECT * FROM bounded_admission WHERE scope=?', (self.scope,)).fetchone()
        if (not row or row['run'] != self.run or row['plan'] != self.key or row['owner'] != self.owner
                or row['use'] != self.use or row['state'] != 'armed' or row['expires'] < time.time()):
            raise Fault('SCOPE_CLOSED', 409)
        latest = self.runs.bindings.get(plan['binding']['id'])
        if latest != plan['binding']:
            raise Fault('BINDING_CONFLICT', 409)

    def install(self, runtime):
        self.runtime = runtime
        self.runs.scopes[self.run] = self
        self.runs.bindings.scopes[self.key] = self

    def enter(self):
        self.check_plan(self.plan)
        with self.runs.store.transaction() as db:
            changed = db.execute("UPDATE bounded_admission SET state='entered' WHERE scope=? AND state='armed'",
                                 (self.scope,)).rowcount
            if changed != 1:
                raise Fault('SCOPE_ALREADY_USED', 409)

    def close(self):
        with self.runs.store.transaction() as db:
            db.execute("""UPDATE bounded_admission SET state=CASE state
                       WHEN 'entered' THEN 'closed_consumed'
                       WHEN 'armed' THEN 'closed_unconsumed' ELSE state END WHERE scope=?""", (self.scope,))
        self.runs.scopes.pop(self.run, None)
        self.runs.bindings.scopes.pop(self.key, None)
