"""App-owned one-candidate local run lifecycle. Status/restart never dispatch."""
import fcntl
import hashlib
import os
import threading
from ..child_env import child_environment
from pydantic import ValidationError
from ..assets.producer_files import allocation, staging_size
from ..assets import runtime_workspace as workspace
from ..assets.producer_collection import ProducerCollection
from ..domain import Fault
from ..persistence.store import canonical
from ..producer.catalog import Catalog
from ..producer.bindings import Bindings
from ..runs.owned_process import OwnedProcess
from ..runs.persistence import RunStore
from ..runs.recovery import Recovery
from ..runs.normal_admission import NormalAdmission, configured


class LocalRuns:
    def __init__(self, store, binding=None, worker=None, *, catalog=None, admission_factory=NormalAdmission):
        self.store = store
        self.catalog = catalog or Catalog()
        self.binding = binding or self.catalog.default_runtime()
        self.bindings = Bindings(store, self.catalog, allow_fixtures=self.binding.fixture_only)
        self.bindings.seed(self.binding)
        self.worker = worker or OwnedProcess()
        self.records = RunStore(store)
        self.collection = ProducerCollection(self.records, self.catalog)
        self.lock = threading.RLock()
        self.threads = {}
        self.scopes = {}
        self.admission_factory = admission_factory
        self.cleanup_notes: dict[str, dict] = {}
        self.closed = False
        self.before_spawn = lambda: None
        self.after_exit = lambda: None
        self.recovery = Recovery(self)
        self.recover()

    def prepare(self, model):
        return self.catalog.prepare_compat(self, model, self.binding)

    def prepare_app(self, model):
        record = self.bindings.get(model.binding, model.binding_revision)
        self.bindings.validate(record)
        adapter = self.catalog.lookup(record['adapter'], record['adapter_version'])
        try:
            return self.records.prepare(model, record, adapter, model.options, operation=model.operation)
        except ValidationError:
            raise Fault('INVALID_INPUT', 422) from None

    def recover(self):
        # No process adoption/kill based on persisted PID after restart. A previously
        # verified child exit permits collection only, never another execution.
        for row in self.records.rows():
            if row['status'] in ('Starting', 'Running', 'Cancelling'):
                self.records.update(row['id'], status='Outcome unknown', error='RESTART_OWNERSHIP_UNKNOWN')
            elif row['status'] in ('Collecting', 'Collection blocked'):
                if self.recovery.normal(row['id']):
                    self.recovery.attention(self.records.get(row['id']), 'interrupted')
                    continue  # No unbudgeted automatic collection on every reopen.
                try:
                    self.collection.collect(row['id'])
                except Fault:
                    pass
        self.recovery.interrupted()

    def start(self, run, authority):
        with self.lock:
            if self.closed:
                raise Fault('FEATURE_DISABLED', 409)
            owner = authority()
            row = self.records.get(run)
            if (run not in self.scopes and row['status'] in ('Prepared','Blocked') and
                    row['plan']['schema'] == 2 and configured(row['plan']['binding'])):
                scope = self.admission_factory(self, run, owner)
                scope.install()
            if run in self.scopes:
                self.scopes[run].check_owner(owner)
            if self.records.claim(run):
                thread = threading.Thread(target=self._entry, args=(run, authority), daemon=False)
                self.threads[run] = thread
                thread.start()
            return self.records.public(run)

    def _entry(self, run, authority):
        try:
            self._work(run, authority)
        except BaseException:
            # Storage can fail while reporting failure. Never emit a private worker
            # traceback; the committed active intent remains non-replayable.
            try:
                self.records.update(run, status='Outcome unknown', error='STORAGE_UNAVAILABLE')
            except BaseException:
                pass
        finally:
            scope = self.scopes.get(run)
            if isinstance(scope, NormalAdmission):
                scope.release()
        try:
            self.recovery.after(run, authority)
        except BaseException:
            pass  # Secondary recovery diagnostics cannot erase the original outcome.

    def _work(self, run, authority):
        descriptor = None
        route_lock = None
        launch_possible = False
        try:
            route_lock = os.open(self.store.home / 'state' / 'sfx.lock',
                                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(route_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Fault('RESOURCE_BUSY', 409) from None
            row = self.records.get(run)
            adapter = self.catalog.for_plan(row['plan'])
            if row['process'] is None:
                self.records.update(run, process=workspace.create(self.store, row))
                row = self.records.get(run)
            directory, descriptor, pin = allocation(self.store, row)
            allocation_record = {**row['process'], 'allocation': pin}
            self.records.update(run, process=allocation_record)
            output = directory / 'candidate.wav'
            self.bindings.check(row['plan'])
            runtime = self.catalog.runtime_legacy(row['plan'], self.binding) if row['plan']['schema'] == 1 else self.bindings.runtime(row['plan'])
            dispatch = adapter.build_dispatch(row['plan'], output, runtime).validate()
            argv = list(dispatch.argv)
            separate = allocation_record.get('layout') == 2
            working = workspace.validate(self.store, row) if separate else directory
            base_environment = child_environment(adapter.id, dispatch.environment)
            environment = workspace.environment(adapter, base_environment, working) if separate else base_environment

            def monitor():
                total = staging_size(descriptor)
                if separate:
                    workspace.validate(self.store, row)
                    total += workspace.tree_snapshot(working)[1]
                return total

            def final_admission(effective):
                self.before_spawn()
                authority()
                latest = self.records.get(run)
                if self.closed or latest['stop']:
                    raise Fault('STOP_BEFORE_START', 409)
                if latest['status'] != 'Starting' or latest['nonce'] != row['nonce']:
                    raise Fault('EFFECT_UNCERTAIN', 409)
                if latest['plan'] != row['plan'] or latest['plan_digest'] != row['plan_digest']:
                    raise Fault('PLAN_CONFLICT', 409)
                if hashlib.sha256(canonical(latest['plan']).encode()).hexdigest() != latest['plan_digest']:
                    raise Fault('PLAN_CONFLICT', 409)
                with self.store.transaction() as db:
                    snapshot = dict(self.store.request(db, row['plan']['request'], row['plan']['revision']))
                    if hashlib.sha256(canonical(snapshot).encode()).hexdigest() != row['plan']['snapshot']:
                        raise Fault('PLAN_CONFLICT', 409)
                if staging_size(descriptor) != 0:
                    raise Fault('OUTPUT_EXISTS', 409)
                if separate:
                    if (working != workspace.validate(self.store, row)
                            or environment != workspace.environment(adapter, base_environment, working)):
                        raise Fault('ALLOCATION_UNSAFE', 409)
                if monitor() > self.worker.staging_limit:
                    raise Fault('STAGING_LIMIT', 409)
                self.bindings.check(row['plan'])
                adapter.validate_dispatch(row['plan'], output, effective, runtime)

            def launching():
                nonlocal launch_possible
                authority()
                if self.closed or self.records.get(run)['stop']:
                    raise Fault('STOP_BEFORE_START', 409)
                launch_possible = True
                if run in self.scopes:
                    self.scopes[run].enter()
                    if isinstance(self.scopes[run], NormalAdmission):
                        latest_process = self.records.get(run)['process'] or {}
                        allocation_record.update(admission=self.scopes[run].observation)
                        self.records.update(run, process={**latest_process, 'admission': self.scopes[run].observation})

            def persist(process):
                self.records.update(run, status='Running', certainty='started',
                                    process={**allocation_record, 'incarnation': process,
                                             'nonce': row['nonce'], 'generation': row['generation'],
                                             'argv_digest': hashlib.sha256(canonical(argv).encode()).hexdigest()})

            def stop():
                if self.closed or self.records.get(run)['stop']:
                    return 'STOP_REQUESTED'
                try:
                    authority()
                except Exception:
                    return 'AUTH_REVOKED'
                return None

            result = self.worker.execute(argv, environment, working,
                                         descriptor, final_admission, persist, stop, launching, monitor=monitor, deadline=dispatch.deadline_seconds)
            gpu_release = None
            if not row['fixture'] and adapter.id in ('stable-audio-local', 'ace-step-local'):
                from ..producer.local_gpu import released
                gpu_release = released(result)
            current = self.records.get(run)['process']
            self.records.update(run, process={**current, 'exited': True, 'exit_code': result['code'],
                                             'incarnation': result['process'],
                                             'capture_bytes': result['capture'],
                                             'process_gone': result.get('process_gone', False),
                                             'local_gpu_release': gpu_release,
                                             'group_retired': result.get('group_retired', False),
                                             'retirement': result.get('retirement'),
                                             'cleanup_error': result.get('cleanup_error')}, certainty='exited')
            if not result.get('group_retired', False):
                self.records.update(run, status='Outcome unknown', error=result['reason'] or 'GROUP_RETIREMENT_UNKNOWN')
                return
            status, reason = adapter.normalize_observation(result)
            if status == 'Collecting':
                self.records.update(run, status='Collecting')
                self.after_exit()
                self.collection.collect(run)
            else:
                self.records.update(run, status=status, error=reason)
        except Fault as error:
            row = self.records.get(run)
            if hasattr(error, 'gpu'):
                self.records.update(run, process={**(row['process'] or {}), 'local_gpu_busy': error.gpu})
            if (row['process'] or {}).get('exited') and row['process'].get('group_retired'):
                if row['status'] not in ('Collecting', 'Collection blocked', 'Ready for review'):
                    self.records.update(run, status='Failed', error=error.code, certainty='exited')
                return
            if row['status'] not in ('Collecting', 'Collection blocked', 'Ready for review'):
                status = 'Outcome unknown' if launch_possible else 'Blocked'
                if error.code == 'STOP_BEFORE_START' and not launch_possible:
                    status = 'Cancelled'
                certainty = 'started' if (row['process'] or {}).get('incarnation') else 'possibly started'
                self.records.update(run, status=status, error=error.code,
                                    certainty=certainty if launch_possible else 'not attempted')
        except BaseException:
            # A crash/fault around spawn cannot be converted into permission to rerun.
            row = self.records.get(run)
            if (row['process'] or {}).get('exited') and row['status'] in ('Collecting', 'Collection blocked'):
                self.records.update(run, error='COLLECTION_INTERRUPTED')
            else:
                self.records.update(run, status='Outcome unknown', error='EXECUTION_UNCERTAIN')
        finally:
            self._close_resources(run, (('outputs', descriptor), ('route_lock', route_lock)))

    def _close_resources(self, run, resources):
        reports = []
        for name, descriptor in resources:
            if descriptor is None:
                continue
            report = dict(resource=name, close='confirmed')
            try:
                os.close(descriptor)
            except BaseException:
                # Linux may already have released/reused the FD. Never retry or
                # claim the resource is released based on an unsuccessful close.
                report.update(close='unconfirmed', error='FD_CLOSE_UNCONFIRMED')
            reports.append(report)
        if any(item['close'] == 'unconfirmed' for item in reports):
            note = dict(resources=reports, persistence='unconfirmed')
            self.cleanup_notes[run] = note
            try:
                self.records.note_cleanup(run, reports)
                note['persistence'] = 'confirmed'
            except BaseException:
                # Missing secondary evidence cannot erase a durable run outcome.
                # Keep an in-memory unconfirmed diagnostic, with no raw FD/error.
                pass

    def stop(self, run):
        with self.lock:
            row = self.records.get(run)
            if self.recovery.normal(run):
                self.records.update(run, stop=1)
                successor = self.recovery.cancel(run)
                if successor:
                    self.stop(successor)
            if row['status'] in ('Prepared', 'Blocked'):
                self.records.update(run, status='Cancelled', stop=1)
            elif row['status'] in ('Starting', 'Running', 'Cancelling', 'Outcome unknown'):
                self.records.update(run, stop=1,
                                    status='Outcome unknown' if row['status'] == 'Outcome unknown' else 'Cancelling')
            return {**self.records.public(run), **self.recovery.collection_status(run)}

    def close(self):
        self.closed = True
        for thread in list(self.threads.values()):
            thread.join(timeout=self.worker.grace + 3)
        # Any unverified surviving execution remains explicitly unknown and blocks route.
        for run, thread in self.threads.items():
            if thread.is_alive():
                self.records.update(run, status='Outcome unknown', error='SHUTDOWN_OWNERSHIP_UNKNOWN')
