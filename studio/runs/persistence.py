"""Run persistence in the existing SQLite authority; permanent command identities."""
import hashlib
import json
import time
from ..domain import Fault, opaque
from ..persistence.store import canonical, identity
from ..producer.bindings import digest

ACTIVE = ('Starting', 'Running', 'Cancelling', 'Outcome unknown')
MAX_IDENTITIES = 10000


class RunStore:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS local_runs(
                id TEXT PRIMARY KEY, candidate TEXT UNIQUE, plan TEXT, plan_digest TEXT,
                status TEXT, certainty TEXT, nonce TEXT, generation INTEGER,
                process TEXT, collection TEXT, error TEXT, stop INTEGER, fixture INTEGER,
                created REAL, updated REAL)''')
            db.execute('CREATE TABLE IF NOT EXISTS run_cleanup(id TEXT PRIMARY KEY, run TEXT, report TEXT)')

    def get(self, run):
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM local_runs WHERE id=?', (opaque(run),)).fetchone()
        if not row:
            raise Fault('RUN_NOT_FOUND', 404)
        result = dict(row)
        for field in ('plan', 'process', 'collection'):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def prepare(self, model, binding, adapter, options, *, operation, command_payload=None):
        with self.store.transaction() as db:
            def create():
                snapshot = dict(self.store.request(db, model.request, model.revision))
                parameters = (adapter.prepare_bound(snapshot,options,operation,binding) if hasattr(adapter,'prepare_bound')
                              else adapter.prepare(snapshot,options,operation))
                plan: dict = dict(schema=2, request=snapshot['id'], revision=snapshot['revision'],
                            snapshot=hashlib.sha256(canonical(snapshot).encode()).hexdigest(),
                            kind=snapshot['kind'], direction=snapshot['text'], purpose=snapshot['purpose'],
                            adapter=adapter.id, adapter_version=adapter.version, operation=operation,
                            parameters=parameters,
                            binding=binding, binding_digest=digest(binding), outputs=adapter.validation_profile,
                            method=binding.get('capabilities',adapter.describe())['name'], execution_kind='local_producer_tool', candidates=1)
                if binding.get('evaluation_scope'):
                    plan['parameters']['use'] = binding['evaluation_scope']['use']
                adapter.validate(plan)
                encoded = canonical(plan)
                if len(encoded.encode()) > 16384:
                    raise Fault('PLAN_TOO_LARGE')
                if binding.get('evaluation_scope'):
                    recovery = db.execute('SELECT body FROM request_recovery WHERE request=?', (model.request,)).fetchone()
                    corrective = recovery and json.loads(recovery[0]).get('command') == model.command
                    if not corrective:
                        existing = db.execute('SELECT id,candidate FROM local_runs WHERE plan_digest=? ORDER BY created LIMIT 1',
                            (hashlib.sha256(encoded.encode()).hexdigest(),)).fetchone()
                        if existing:
                            return dict(existing)
                # Never evict old run/command identities to free an admission slot.
                if db.execute('SELECT count(*) FROM local_runs').fetchone()[0] >= MAX_IDENTITIES:
                    raise Fault('IDENTITY_STORAGE_FULL', 409)
                run, candidate, nonce = identity(), identity(), identity()
                now = time.time()
                db.execute('INSERT INTO local_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (run, candidate, encoded, hashlib.sha256(encoded.encode()).hexdigest(),
                            'Prepared', 'not attempted', nonce, 1, None, None, None, 0,
                            int(binding['fixture_only']), now, now))
                return {'id': run, 'candidate': candidate}
            payload = command_payload or {'operation': 'prepare-app', 'input': model.model_dump()}
            return self.store.command(db, model.command, payload, create)

    def update(self, run, **values):
        allowed = {'status', 'certainty', 'process', 'collection', 'error', 'stop'}
        if not values or not set(values) <= allowed:
            raise ValueError('Internal run fields only')
        for field in ('process', 'collection'):
            if field in values:
                values[field] = canonical(values[field])
        values['updated'] = time.time()
        with self.store.transaction() as db:
            db.execute('UPDATE local_runs SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE id=?',
                       (*values.values(), opaque(run)))

    def note_cleanup(self, run, resources):
        # Append secondary evidence without touching outcome, process or collection.
        with self.store.transaction() as db:
            row = db.execute('SELECT nonce,generation FROM local_runs WHERE id=?', (opaque(run),)).fetchone()
            if row is None:
                raise Fault('RUN_NOT_FOUND', 404)
            report = dict(version=1, nonce=row['nonce'], generation=row['generation'], resources=resources)
            db.execute('INSERT INTO run_cleanup VALUES(?,?,?)', (identity(), run, canonical(report)))

    def cleanup(self, run):
        with self.store.transaction() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT report FROM run_cleanup WHERE run=? ORDER BY rowid', (opaque(run),))]

    def claim(self, run):
        """Commit possible launch BEFORE spawn; uncertainty blocks this entire route."""
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM local_runs WHERE id=?', (opaque(run),)).fetchone()
            if not row:
                raise Fault('RUN_NOT_FOUND', 404)
            if row['status'] not in ('Prepared', 'Blocked') or row['stop']:
                return False
            busy = db.execute("SELECT id FROM local_runs WHERE status IN (?,?,?,?)", ACTIVE).fetchone()
            if busy:
                raise Fault('RESOURCE_BUSY', 409)
            self.store.request(db, json.loads(row['plan'])['request'], json.loads(row['plan'])['revision'])
            if hashlib.sha256(row['plan'].encode()).hexdigest() != row['plan_digest']:
                raise Fault('PLAN_CONFLICT', 409)
            db.execute("UPDATE local_runs SET status='Starting',certainty='possibly started',error=NULL,updated=? WHERE id=?",
                       (time.time(), run))
            return True

    def rows(self):
        with self.store.transaction() as db:
            return [self.get_row(row) for row in db.execute('SELECT * FROM local_runs ORDER BY created')]

    @staticmethod
    def get_row(row):
        return dict(row)

    def public(self, run):
        row = self.get(run)
        return dict(id=row['id'], candidate=row['candidate'], request=row['plan']['request'],
                    revision=row['plan']['revision'], status=row['status'], certainty=row['certainty'],
                    error=row['error'], execution_kind='local_producer_tool',
                    method=row['plan'].get('method', 'Preserved local tool run'),
                    origin='test_fixture' if row['fixture'] else 'producer_output',
                    host_session=None, host_run=None, host_admission=None, host_tool_call=None,
                    generation=row['generation'], stop_requested=bool(row['stop']),
                    admission=(row['process'] or {}).get('admission'),
                    local_gpu_busy=(row['process'] or {}).get('local_gpu_busy'),
                    local_gpu_release=(row['process'] or {}).get('local_gpu_release'),
                    limitations='Test only - not generated' if row['fixture'] else 'Listening and usage unverified',
                    outcome_note='Failed - no retained result; exit code unobserved (reconciled)'
                    if (row['process'] or {}).get('retirement_reconciled') else None)
