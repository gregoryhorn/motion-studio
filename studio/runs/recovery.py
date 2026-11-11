"""One durable automatic allowance per request lineage; finite installed corrections only."""
from datetime import date
import json
from ..domain import Fault
from ..persistence.store import canonical, identity
from ..producer.contracts import PrepareApp
from ..runs.technical_knowledge import TechnicalKnowledge
from ..runs.recovery_recipes import shared_runtime_cache

NEXT = {
    'unknown': 'Resolve recorded process/group ownership with supported reconciliation before new work.',
    'unsupported': 'Inspect the preserved failed attempt; no supported automatic correction applies.',
    'intent': 'Intent changed or stopped. Review the current request explicitly; no automatic retry.',
    'exhausted': 'Automatic allowance used. Inspect the recorded recovery result before deliberate new work.',
    'denied': 'Recheck current binding, resources and evaluation eligibility explicitly; no automatic retry.',
    'interrupted': 'Recovery interrupted. Observe the recorded action; do not infer that it never executed.',
    'collection': 'Inspect the preserved original output pair; do not regenerate to recover a download.'}


class Recovery:
    def __init__(self, runs):
        self.runs, self.store = runs, runs.store
        self.knowledge = TechnicalKnowledge(self.store)
        self.before_action = lambda: None  # Test scheduling seam, never an HTTP option.
        with self.store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS normal_admissions(run TEXT PRIMARY KEY, plan TEXT, owner TEXT, state TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS recovery_suppressions(run TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS request_recovery(request TEXT PRIMARY KEY, body TEXT)')

    def normal(self, run):
        with self.store.transaction() as db:
            return db.execute('SELECT 1 FROM normal_admissions WHERE run=?', (run,)).fetchone() is not None

    def get(self, request):
        with self.store.transaction() as db:
            row = db.execute('SELECT body FROM request_recovery WHERE request=?', (request,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def put(db, record):
        record['revision'] = record.get('revision', 0) + 1
        db.execute('INSERT OR REPLACE INTO request_recovery VALUES(?,?)', (record['request'],canonical(record)))

    def check_intent(self, run, *, recovery=False):
        row = self.runs.records.get(run)
        plan = row['plan']
        with self.store.transaction() as db:
            self.store.request(db, plan['request'], plan['revision'])
            selected = db.execute('SELECT * FROM app_methods WHERE request=?', (plan['request'],)).fetchone()
            if not selected or (selected['binding'], selected['revision'], selected['operation']) != (
                    plan['binding']['id'], plan['binding']['revision'], plan['operation']):
                raise Fault('INTENT_CHANGED', 409)
        record = self.get(plan['request'])
        root = record['failed_run'] if record and record.get('successor') == run else run
        if recovery or root != run:
            with self.store.transaction() as db:
                suppressed = db.execute('SELECT 1 FROM recovery_suppressions WHERE run=?', (root,)).fetchone()
            if suppressed:
                raise Fault('RECOVERY_SUPPRESSED', 409)
        if row['stop'] or (record and record.get('successor') == run and (
                record['state'] != 'Applying' or self.runs.records.get(record['failed_run'])['stop'])):
            raise Fault('RECOVERY_SUPPRESSED', 409)

    def attention(self, row, reason):
        with self.store.transaction() as db:
            found = db.execute('SELECT body FROM request_recovery WHERE request=?', (row['plan']['request'],)).fetchone()
            record = json.loads(found[0]) if found else dict(request=row['plan']['request'],
                failed_run=row['id'], failed_candidate=row['candidate'], reserved=False,
                error_class='EFFECT_UNCERTAIN' if reason == 'unknown' else 'UNSUPPORTED_FAILURE',
                cause='unknown', evidence=dict(run=row['id'], plan=row['plan_digest']), recipe=None, successor=None)
            if found and record['state'] == 'Completed':
                return  # Late callbacks cannot erase established completion.
            record.update(state='Needs attention', next_action=NEXT[reason], last_result=row['id'])
            self.put(db, record)

    def claim_collection(self, record, row):
        """Linearize collection start against committed stop, edits and suppression."""
        with self.store.transaction() as db:
            current = json.loads(db.execute('SELECT body FROM request_recovery WHERE request=?', (record['request'],)).fetchone()[0])
            if current['command'] != record['command'] or current['state'] != 'Reserved' or current.get('action_started'):
                raise Fault('RECOVERY_SUPPRESSED', 409)
            self.store.request(db, row['plan']['request'], row['plan']['revision'])
            selected = db.execute('SELECT * FROM app_methods WHERE request=?', (record['request'],)).fetchone()
            binding = row['plan']['binding']
            if not selected or (selected['binding'],selected['revision'],selected['operation']) != (
                    binding['id'],binding['revision'],row['plan']['operation']):
                raise Fault('INTENT_CHANGED', 409)
            latest = db.execute('SELECT * FROM local_runs WHERE id=?', (row['id'],)).fetchone()
            if latest['stop'] or db.execute('SELECT 1 FROM recovery_suppressions WHERE run=?', (row['id'],)).fetchone():
                raise Fault('RECOVERY_SUPPRESSED', 409)
            process = json.loads(latest['process']) if latest['process'] else {}
            active = db.execute("SELECT 1 FROM local_runs WHERE status IN ('Starting','Running','Cancelling','Outcome unknown')").fetchone()
            if (current['recipe'] != 'original-collection' or current['failed_run'] != row['id'] or not current['reserved'] or
                    latest['status'] not in ('Collecting','Collection blocked') or latest['plan_digest'] != row['plan_digest'] or
                    latest['certainty'] != row['certainty'] or latest['nonce'] != row['nonce'] or latest['generation'] != row['generation'] or
                    process != row['process'] or not process.get('exited') or not process.get('group_retired') or
                    process.get('exit_code') != 0 or active):
                raise Fault('EFFECT_UNCERTAIN', 409)
            current.update(state='Applying', action_started=True,
                           next_action='Original collection already applying; cancellation cannot undo this action. Observe its outcome.')
            self.put(db,current)

    def reserve(self, row, recipe):
        process = row['process'] or {}
        if recipe not in ('isolated-layout','original-collection'):
            raise Fault('UNSUPPORTED_CORRECTION', 409)
        if not self.normal(row['id']) or not (process.get('exited') and process.get('group_retired')):
            raise Fault('EFFECT_UNCERTAIN', 409)
        if recipe == 'isolated-layout' and not (row['status'] == 'Failed' and row['error'] == 'OUTPUT_UNSAFE' and shared_runtime_cache(self.store,row)):
            raise Fault('UNSUPPORTED_CORRECTION', 409)
        if recipe == 'original-collection':
            if row['status'] not in ('Collecting','Collection blocked'):
                raise Fault('UNSUPPORTED_CORRECTION', 409)
            self.runs.collection.verify_original(row['id'])
        # SQL BEGIN IMMEDIATE is the cross-worker/restart CAS; in-memory locks are not authority.
        with self.store.transaction() as db:
            self.store.request(db, row['plan']['request'], row['plan']['revision'])
            selected = db.execute('SELECT * FROM app_methods WHERE request=?', (row['plan']['request'],)).fetchone()
            binding = row['plan']['binding']
            if not selected or (selected['binding'],selected['revision'],selected['operation']) != (
                    binding['id'],binding['revision'],row['plan']['operation']):
                raise Fault('INTENT_CHANGED', 409)
            latest = db.execute('SELECT * FROM local_runs WHERE id=?', (row['id'],)).fetchone()
            if latest['stop']:
                raise Fault('RECOVERY_SUPPRESSED', 409)
            suppressed = db.execute('SELECT 1 FROM recovery_suppressions WHERE run=?', (row['id'],)).fetchone()
            if suppressed:
                raise Fault('RECOVERY_SUPPRESSED', 409)
            if (latest['status'] != row['status'] or latest['plan_digest'] != row['plan_digest'] or
                    json.loads(latest['process']) != row['process'] or latest['certainty'] != row['certainty']):
                raise Fault('EFFECT_UNCERTAIN', 409)
            existing = db.execute('SELECT body FROM request_recovery WHERE request=?', (row['plan']['request'],)).fetchone()
            if existing and json.loads(existing[0])['reserved']:
                return None
            active = db.execute("SELECT 1 FROM local_runs WHERE status IN ('Starting','Running','Cancelling','Outcome unknown')").fetchone()
            if active:
                raise Fault('EFFECT_UNCERTAIN', 409)
            record = dict(request=row['plan']['request'], failed_run=row['id'], failed_candidate=row['candidate'],
                error_class='OUTPUT_UNSAFE' if recipe == 'isolated-layout' else 'COLLECTION_INTERRUPTED',
                cause='hypothesis' if recipe == 'isolated-layout' else 'evidence-supported',
                evidence=dict(run=row['id'], plan=row['plan_digest'], binding=row['plan']['binding_digest'],
                              nonce=row['nonce'], generation=row['generation']),
                recipe=recipe, recipe_version=1, state='Reserved', reserved=True, command=identity(),
                successor=None, next_action='One supported local recovery action reserved; observing original evidence.',
                revision=json.loads(existing[0])['revision'] if existing else 0)
            self.put(db, record)
            return record

    def after(self, run, authority):
        if not self.normal(run):
            return
        row = self.runs.records.get(run)
        record = self.get(row['plan']['request'])
        if record and record.get('successor') == run:
            if row['status'] == 'Ready for review':
                self.finish(record, row)
            else:
                self.attention(row, 'unknown' if row['status'] == 'Outcome unknown' else 'exhausted')
            return
        if record and record['reserved']:
            return  # Duplicate callback/polling cannot repeat or replace a recorded action.
        if row['status'] == 'Ready for review':
            return
        process = row['process'] or {}
        if row['status'] == 'Outcome unknown' or not (process.get('exited') and process.get('group_retired')):
            self.attention(row, 'unknown' if row['certainty'] != 'not attempted' else 'unsupported')
            return
        try:
            self.check_intent(run, recovery=True)
        except Fault:
            self.attention(row, 'intent')
            return
        if row['status'] in ('Collecting','Collection blocked'):
            try:
                self.runs.collection.verify_original(run)
            except (Fault, OSError):
                self.attention(row, 'collection')
                return
            recipe = 'original-collection'
        elif row['status'] == 'Failed' and row['error'] == 'OUTPUT_UNSAFE' and shared_runtime_cache(self.store,row):
            recipe = 'isolated-layout'
        else:
            self.attention(row, 'unsupported')
            return
        try:
            record = self.reserve(row, recipe)
            if record is None:
                return
            self.before_action()
            authority()
            self.check_intent(run, recovery=True)
            current = self.get(row['plan']['request'])
            if not current or current['command'] != record['command'] or current['state'] != 'Reserved':
                raise Fault('RECOVERY_SUPPRESSED', 409)
            if recipe == 'original-collection':
                self.claim_collection(record,row)
                self.runs.collection.collect(run)
                self.finish(record, self.runs.records.get(run))
            else:
                self.successor(record, row, authority)
        except Fault as error:
            self.attention(row, 'intent' if error.code in ('RECOVERY_SUPPRESSED','INTENT_CHANGED','STALE_REVISION') else 'denied')
        except BaseException:
            self.attention(row, 'denied')  # Never replace the original run outcome/evidence.

    def successor(self, record, row, authority):
        if row['plan'].get('adapter', 'stable-audio-local') != 'stable-audio-local':
            raise Fault('UNSUPPORTED_CORRECTION', 409)
        plan = row['plan']
        params = plan['parameters']
        receipt = self.runs.prepare_app(PrepareApp(command=record['command'], request=plan['request'],
            revision=plan['revision'], binding=plan['binding']['id'], binding_revision=plan['binding']['revision'],
            operation=plan['operation'], options={key: params[key] for key in ('seconds','seed','language')}))
        with self.store.transaction() as db:
            current = json.loads(db.execute('SELECT body FROM request_recovery WHERE request=?', (plan['request'],)).fetchone()[0])
            if current['command'] != record['command'] or current['state'] != 'Reserved':
                raise Fault('RECOVERY_SUPPRESSED', 409)
            current.update(successor=receipt['id'], state='Applying', next_action='Observing linked isolated-layout successor; no second automatic action.')
            self.put(db,current)
        self.runs.start(receipt['id'], authority)

    def finish(self, record, row):
        if row['status'] != 'Ready for review':
            self.attention(row, 'exhausted')
            return
        with self.store.transaction() as db:
            current = json.loads(db.execute('SELECT body FROM request_recovery WHERE request=?', (record['request'],)).fetchone()[0])
            current.update(state='Completed', last_result=row['id'], next_action='Technical checks passed. Listening Not reviewed; review or download the original.')
            self.put(db,current)
        recipe = record['recipe']
        try:
            self.knowledge.remember(dict(recipe=recipe, verified_on=date.today().isoformat(), result='verified',
                confidence='fixture-tested' if row['fixture'] else 'evidence-supported',
                error_class='OUTPUT_UNSAFE' if recipe == 'isolated-layout' else 'COLLECTION_INTERRUPTED',
                condition='shared-runtime-outputs' if recipe == 'isolated-layout' else 'verified-original-pair',
                summary='isolated-runtime-strict-outputs' if recipe == 'isolated-layout' else 'same-original-bytes-retained'))
        except BaseException:
            pass  # Advisory learning cannot change verified outcome or authority.

    def interrupted(self):
        with self.store.transaction() as db:
            records = [json.loads(row[0]) for row in db.execute('SELECT body FROM request_recovery')]
        for record in records:
            if record['state'] in ('Reserved','Applying'):
                target = record.get('successor') or record['failed_run']
                row = self.runs.records.get(target)
                if row['status'] == 'Ready for review':
                    self.finish(record,row)
                else:
                    self.attention(row,'interrupted')

    def cancel(self, run):
        row = self.runs.records.get(run)
        record = self.get(row['plan']['request'])
        if record and record['failed_run'] == run and record.get('successor'):
            return record['successor']
        return None

    def suppress(self, run):
        row = self.runs.records.get(run)
        successor = None
        with self.store.transaction() as db:
            db.execute('INSERT OR IGNORE INTO recovery_suppressions VALUES(?)', (run,))
            found = db.execute('SELECT body FROM request_recovery WHERE request=?', (row['plan']['request'],)).fetchone()
            record = json.loads(found[0]) if found else None
            outcome = self.collection_outcome(record)
            if record and record['failed_run'] == run and outcome:
                return dict(recovery_suppressed=False, **outcome)
            if record and record['failed_run'] == run and record['state'] in ('Reserved','Applying'):
                record.update(state='Needs attention',next_action=NEXT['intent'],last_result=run)
                self.put(db,record)
                successor = record.get('successor')
        if successor:
            self.runs.stop(successor)
        return dict(recovery_suppressed=True)

    @staticmethod
    def collection_outcome(record):
        if not record or record['recipe'] != 'original-collection' or not record.get('action_started'):
            return {}
        state = record['state']
        return dict(recovery_action='completion-won' if state == 'Completed' else
                    'already-applying' if state == 'Applying' else 'already-started',
                    recovery_notice='Collection action already started; stop/edit cannot undo it. Observe the recorded outcome.')

    def collection_status(self, run):
        row = self.runs.records.get(run)
        record = self.get(row['plan']['request'])
        return self.collection_outcome(record) if record and record['failed_run'] == run else {}

    def public(self):
        with self.store.transaction() as db:
            records = [json.loads(row[0]) for row in db.execute('SELECT body FROM request_recovery ORDER BY rowid')]
        return [{key: record.get(key) for key in ('request','failed_run','failed_candidate','error_class','cause',
                 'recipe','recipe_version','state','revision','reserved','action_started','successor','last_result','next_action')} for record in records]
