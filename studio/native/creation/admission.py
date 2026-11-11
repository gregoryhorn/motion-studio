"""Native authority adapter to the shared ordinary admission/recovery protocol."""
from ...domain import Fault
from ...producer.live_sfx import OrdinaryRuntime, USE
from ...runs.normal_admission import NormalAdmission
from ...native.creation.policy import Scope


class NativeAdmission(NormalAdmission):
    def __init__(self, runs, run, owner):
        # Do not call the standalone app-session constructor. This is a typed
        # store/root/policy association; no conversation ID is used as a token.
        if not isinstance(owner, Scope):
            raise Fault('CREATION_SCOPE_DENIED', 403)
        self.runs, self.run, self.use = runs, run, USE
        self.scope, self.owner = owner, owner.key()
        self.observation = {}
        row = runs.records.get(run)
        self.plan, self.key = row['plan'], row['plan_digest']
        request = self.plan['request']
        with runs.store.transaction() as db:
            association = db.execute('SELECT root,policy FROM creation_commands WHERE request=?', (request,)).fetchone()
            meta = db.execute('SELECT instance FROM creation_meta').fetchone()
            if (not association or association['root'] != owner.root or association['policy'] != owner.revision
                    or not meta or meta[0] != owner.instance):
                raise Fault('CREATION_SCOPE_DENIED', 403)
            existing = db.execute('SELECT * FROM normal_admissions WHERE run=?', (run,)).fetchone()
            if existing and (existing['owner'] != self.owner or existing['plan'] != self.key):
                raise Fault('CREATION_SCOPE_DENIED', 403)
            if not existing:
                db.execute('INSERT INTO normal_admissions VALUES(?,?,?,?)', (run, self.key, self.owner, 'armed'))
        adapter = runs.catalog.for_plan(self.plan)
        if self.plan['kind'] == 'Music':
            from ...native.creation.music import MusicScope
            if not isinstance(owner, MusicScope): raise Fault('MUSIC_SCOPE_REVIEW_REQUIRED', 403)
            with runs.store.transaction() as db:
                pinned = db.execute('SELECT policy FROM music_intents WHERE request=?', (request,)).fetchone()
            if not pinned or pinned[0] != owner.music_revision: raise Fault('MUSIC_POLICY_CHANGED', 403)
            self.use = 'Music rights and intended use unqualified'
        self.runtime = (adapter.normal_runtime(self.plan['binding'], self) if hasattr(adapter, 'normal_runtime')
                        else OrdinaryRuntime(record=self.plan['binding'], fixture_only=row['fixture'], scope=self))

    def check_owner(self, owner):
        if not isinstance(owner, Scope) or owner != self.scope:
            raise Fault('CREATION_SCOPE_DENIED', 403)
