"""Owned-worker fixtures; real tiny children, synthetic host admission/limits.

These are not kernel/resource qualification or an unenforced production route.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

from studio.contracts import ContractError, digest
from studio.project import ProjectStore
from resource_fixture import fixture_spawn, fixture_run


def uid(prefix):
    return prefix + '_' + str(uuid.uuid4())


class FixtureAuthority:
    """Explicit test-only authority provider, not a host approval integration."""
    def authorize(self, plan, args):
        return {'evidence_ref': 'fixture:local-only', 'plan_sha256': plan['plan_sha256'],
                'effects_sha256': digest(plan['effects'])}


def fixture_plan(pid):
    node = {'node_id': uid('nod'), 'target_key': 'report', 'operation': 'review.check@1',
            'dependencies': [], 'inputs': {}, 'parameters': {}, 'required_features': [],
            'binding': {'adapter_id': 'fixture.local', 'implementation_version': '1',
                        'implementation_sha256': digest('fixture'), 'abi_version': '1.0',
                        'request_schema': 'fixture/request', 'result_schema': 'fixture/result',
                        'schema_sha256': digest('schemas')},
            'expected_outputs': [{'port': 'report', 'kind': 'report', 'media_type': 'application/json'}],
            'fingerprint': digest('node'), 'reuse': None, 'conversion_losses': []}
    plan = {'schema': 'motion/v1/plan', 'plan_id': uid('pln'), 'plan_revision': 1,
            'project_id': pid, 'project_revision': 1, 'snapshot_sha256': digest('snapshot'),
            'created_at': '2026-11-05T00:00:00Z', 'requests': [], 'targets': ['report'],
            'nodes': [node], 'status': 'ready', 'gaps': [], 'effects': [{'writes_local': True,
                'uploads': False, 'destinations': [], 'generates': False, 'launches_process': True,
                'pricing': 'free', 'charging_basis': None, 'estimate': None}]}
    plan['plan_sha256'] = digest({k: v for k, v in plan.items() if k not in ('created_at', 'plan_sha256')})
    return plan


class LocalAdapter:
    owned_local = True

    def validate_request(self, request):
        return {'valid': True, 'issues': [], 'effects': request['effects'], 'required_features': []}

    def execute(self, request, attempt, worker):
        # A real no-network process; argv is registered Python code, never public RPC input.
        proc = fixture_spawn(worker, [sys.executable, '-c',
                             'from pathlib import Path; Path("report.json").write_text("{\\"measured\\":true}")'])
        code = proc.wait(timeout=5)
        return {'state': 'succeeded' if code == 0 else 'failed', 'submission_state': 'confirmed',
                'external_handle': None, 'remote_state': 'none', 'progress': None,
                'outputs': [{'port': 'report', 'relative_path': 'report.json',
                             'media_type': 'application/json', 'claimed_sha256': None}],
                'warnings': [], 'error': None, 'observed_cost': None, 'logs_ref': None, 'handoff': None}


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'], prefix='motion-b07-')
        self.addCleanup(self.tmp.cleanup)
        self.projects = ProjectStore(root=Path(self.tmp.name) / 'store')
        self.pid = self.projects.dispatch({'action': 'create', 'request_id': str(uuid.uuid4()), 'name': 'B07'})['project_id']
        self.plan = fixture_plan(self.pid)

    def store(self, **kw):
        from studio.jobs import JobStore
        return JobStore(self.projects, plan_reader=lambda pid, pin: copy.deepcopy(self.plan),
                        authority=FixtureAuthority(), adapter_resolver=lambda binding: LocalAdapter(), **kw)

    def args(self):
        return {'action': 'submit', 'project_id': self.pid, 'expected_revision': 1,
                'request_id': str(uuid.uuid4()), 'plan': {k: self.plan[k] for k in ['plan_id', 'plan_revision', 'plan_sha256']}}

    def test_submit_replay_precedes_cas_and_changed_identity_refused(self):
        store, args = self.store(), self.args()
        first = store.submit(args)
        self.projects.dispatch({'action': 'update', 'project_id': self.pid, 'expected_revision': 1,
                                'request_id': str(uuid.uuid4()), 'changes': [{'op': 'set_stage', 'value': 'concept'}]})
        self.assertEqual(self.store().submit(args), first)
        with self.assertRaises(ContractError) as cm:
            store.submit(args | {'expected_revision': 2})
        self.assertEqual(cm.exception.code, 'IDEMPOTENCY_CONFLICT')

    def test_status_ignores_stage_but_detects_frozen_policy_change(self):
        store = self.store()
        jid = store.submit(self.args())['job']['job_id']
        changed = self.projects.dispatch({'action':'update','project_id':self.pid,'expected_revision':1,
            'request_id':str(uuid.uuid4()),'changes':[{'op':'set_stage','value':'review'}]})
        self.assertTrue(changed['ok'],changed)
        self.assertFalse(store.status(self.pid,jid)['stale'])
        fs = self.projects._filesystem()
        _, docs = self.projects._load(fs,self.projects._pointer(fs,self.pid))
        policy = copy.deepcopy(docs['settings','project']['value']['policy'])
        policy['max_concurrent_nodes'] += 1
        changed = self.projects.dispatch({'action':'update','project_id':self.pid,'expected_revision':2,
            'request_id':str(uuid.uuid4()),'changes':[{'op':'set_execution_policy','value':policy}]})
        self.assertTrue(changed['ok'],changed)
        status = store.status(self.pid,jid)
        self.assertTrue(status['stale'],status)
        self.assertEqual(status['stale_node_ids'],[self.plan['nodes'][0]['node_id']])

    def test_real_owned_execution_validates_and_publishes_bytes(self):
        store = self.store()
        job = store.submit(self.args())['job']
        result = store.run_queued(self.pid, job['job_id'])
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(result['output_count'], 1)
        bundle = store.read(self.pid, job['job_id'])
        artifact = bundle['artifacts'][0]
        self.assertEqual(artifact['sha256'], result['outputs'][0]['sha256'])
        self.assertTrue((self.projects.root / artifact['storage']['relative_path']).is_file())
        attempt = next(iter(bundle['attempts'].values()))
        self.assertIsNotNone(attempt['owner']['process_started_at'])
        self.assertFalse(store.process_alive(attempt['owner']))
        self.assertEqual(self.store().status(self.pid, job['job_id'])['state'], 'succeeded')
        public = store.dispatch({'action': 'status', 'project_id': self.pid, 'job_id': job['job_id'], 'section': 'attempts'})
        self.assertTrue(public['ok'], public)
        self.assertNotIn('owner', public['data']['items'][0])
        self.assertNotIn('output_dir', public['data']['items'][0])
        outputs = store.dispatch({'action': 'status', 'project_id': self.pid, 'job_id': job['job_id'], 'section': 'outputs'})
        self.assertEqual(outputs['data']['items'][0]['schema'], 'motion/v1/artifact')

    def freeze(self):
        self.plan['plan_sha256'] = digest({k: v for k, v in self.plan.items() if k not in ('created_at', 'plan_sha256')})

    def test_dag_exact_output_feeds_owned_subprocess(self):
        first = self.plan['nodes'][0]
        second = copy.deepcopy(first)
        second.update(node_id=uid('nod'), target_key='consumer', fingerprint=digest('consumer'),
                      dependencies=[first['node_id']], inputs={'candidate': {'kind': 'node_output',
                          'node_id': first['node_id'], 'port': 'report'}, 'evidence': []})
        # Deliberately not topologically sorted: execution follows edges, not order.
        self.plan['nodes'] = [second, first]
        self.plan['effects'] *= 2
        self.freeze()
        store = self.store()
        calls = []
        outer = self
        class Consumer(LocalAdapter):
            def execute(self, request, attempt, worker):
                calls.append(request['node_id'])
                if request['node_id'] == first['node_id']:
                    return super().execute(request, attempt, worker)
                pin = request['inputs']['candidate']
                self.assertion = request['inputs']['evidence'] == []
                bundle = store.read(outer.pid, attempt['job_id'])
                record = next(a for a in bundle['artifacts'] if a['artifact_id'] == pin['artifact_id'])
                path = outer.projects.root / record['storage']['relative_path']
                proc = fixture_spawn(worker, [sys.executable, '-c',
                    'import json,sys; from pathlib import Path; x=json.loads(Path(sys.argv[1]).read_text()); '
                    'assert x["measured"]; Path("report.json").write_text(json.dumps({"consumed":True}))', str(path)])
                assert proc.wait(timeout=5) == 0
                return {'state': 'succeeded', 'submission_state': 'confirmed', 'external_handle': None,
                    'remote_state': 'none', 'outputs': [{'port':'report','relative_path':'report.json',
                    'media_type':'application/json','claimed_sha256':None}], 'error':None}
        store.adapter_resolver = lambda b: Consumer()
        job = store.submit(self.args())['job']
        result = store.run_queued(self.pid, job['job_id'])
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(calls, [first['node_id'], second['node_id']])
        bundle = store.read(self.pid, job['job_id'])
        self.assertEqual(len(bundle['attempts']), 2)
        self.assertEqual(result['output_count'], 2)
        self.assertTrue(all(not store.process_alive(a['owner']) for a in bundle['attempts'].values()))

    def test_uncertain_recovery_never_executes(self):
        store = self.store()
        job = store.submit(self.args())['job']
        fs = self.projects._filesystem(write=True)
        bundle = store.read(self.pid, job['job_id'])
        bundle['job']['state'] = 'running'
        bundle['job']['submission_state'] = 'uncertain'
        fs.write(store.path(self.pid, job['job_id']), bundle, replace=True)
        args = {'project_id': self.pid, 'job_id': job['job_id'], 'expected_job_revision': 1,
                'request_id': str(uuid.uuid4()), 'action': 'reconcile'}
        result = store.reconcile(args)
        self.assertEqual(result['job']['state'], 'awaiting_external')
        self.assertEqual(result['job']['remote_state'], 'unknown')
        self.assertEqual(store.read(self.pid, job['job_id'])['attempts'], {})
        self.assertEqual(store.reconcile(args), result)

    def test_restart_observes_uncertain_real_attempt_without_execution(self):
        from unittest.mock import patch
        processes = []
        class Interrupted(LocalAdapter):
            def execute(self, request, attempt, worker):
                fixture_run(worker, [sys.executable, '-c', 'print("owned attempt finished")'],
                    timeout=5, check=True)
                processes.append(worker.process)
                raise RuntimeError('injected interruption before result publication')
        store = self.store()
        store.adapter_resolver = lambda b: Interrupted()
        args = self.args()
        jid = store.submit(args)['job']['job_id']
        self.assertEqual(store.run_queued(self.pid,jid)['state'], 'awaiting_external')
        prior = store.read(self.pid,jid)
        fresh = self.store()
        reconcile = dict(action='reconcile', project_id=self.pid, job_id=jid,
            expected_job_revision=prior['job']['job_revision'], request_id=str(uuid.uuid4()))
        with patch('subprocess.Popen', side_effect=AssertionError('restart/read must not spawn')):
            self.assertEqual(fresh.status(self.pid,jid)['state'], 'awaiting_external')
            self.assertEqual(fresh.run_queued(self.pid,jid)['state'], 'awaiting_external')
            result = fresh.reconcile(reconcile)
            assert isinstance(result, dict) and isinstance(result['job'], dict)
            self.assertEqual(result['job']['remote_state'], 'unknown')
            before_replay = fresh.read(self.pid, jid)
            replay = fresh.reconcile(reconcile)
            assert isinstance(replay, dict) and isinstance(replay['job'], dict)
            # Monitoring timers advance on observation; replay refreshes status
            # without repeating the action or writing another job revision.
            self.assertEqual(replay['reconciled'], result['reconciled'])
            self.assertEqual(replay['unresolved'], result['unresolved'])
            self.assertEqual({k: v for k, v in replay['job'].items() if k != 'monitoring'},
                             {k: v for k, v in result['job'].items() if k != 'monitoring'})
            self.assertEqual(fresh.read(self.pid, jid), before_replay)
            self.assertEqual(fresh.submit(args)['job']['job_id'],jid)
        current = fresh.read(self.pid,jid)
        self.assertEqual(current['attempts'], prior['attempts'])
        self.assertEqual(current['artifacts'], [])
        self.assertEqual(len(current['attempts']), 1)
        for process in processes:
            self.assertIsNotNone(process.returncode)
            with self.assertRaises(ChildProcessError):
                os.waitpid(process.pid, os.WNOHANG)

    def stopped_local_exception(self):
        class BrokenLocal(LocalAdapter):
            local_effects_only = True
            def execute(self, request, attempt, worker):
                fixture_run(worker, [sys.executable, '-c', 'pass'],timeout=5,check=True)
                raise RuntimeError('local package validation interrupted')
        store=self.store();store.adapter_resolver=lambda binding:BrokenLocal()
        jid=store.submit(self.args())['job']['job_id']
        self.assertEqual(store.run_queued(self.pid,jid)['state'],'awaiting_external')
        current=store.read(self.pid,jid)
        store.cancel(dict(action='cancel',project_id=self.pid,job_id=jid,
            expected_job_revision=current['job']['job_revision'],request_id=str(uuid.uuid4())))
        return store, jid

    def test_stopped_local_only_exception_can_reconcile_explicit_cancel(self):
        store, jid = self.stopped_local_exception()
        current=store.read(self.pid,jid)
        result=store.reconcile(dict(action='reconcile',project_id=self.pid,job_id=jid,
            expected_job_revision=current['job']['job_revision'],request_id=str(uuid.uuid4())))
        assert isinstance(result,dict) and isinstance(result['job'],dict)
        self.assertEqual(result['job']['state'],'cancelled')
        self.assertFalse(result['job']['cancel']['external_may_continue'])
        self.assertEqual(result['job']['submission_state'], 'confirmed')
        self.assertEqual(result['job']['remote_state'], 'none')
        retained = store.read(self.pid,jid)
        self.assertEqual(retained['artifacts'],[])
        attempt = next(iter(retained['attempts'].values()))
        self.assertIsNotNone(attempt['ended_at'])
        self.assertEqual(attempt['submission_state'], 'confirmed')
        self.assertEqual(attempt['remote_state'], 'none')

    def test_local_cancel_does_not_override_remote_evidence_or_missing_adapter(self):
        for case in ('remote_running', 'external_handle', 'not_local_only', 'missing_adapter'):
            with self.subTest(case=case):
                store, jid = self.stopped_local_exception()
                current = store.read(self.pid,jid)
                attempt = next(iter(current['attempts'].values()))
                if case == 'remote_running':
                    attempt['remote_state'] = 'running'
                elif case == 'external_handle':
                    # Even remote_state=none cannot erase a recorded handle.
                    attempt.update(remote_state='none', external_handle='provider:observed')
                elif case == 'not_local_only':
                    store.adapter_resolver = lambda binding: LocalAdapter()
                else:
                    def missing(binding):
                        raise ContractError('ADAPTER_UNAVAILABLE', 'Pinned adapter unavailable.')
                    store.adapter_resolver = missing
                store._commit(self.projects._filesystem(write=True), current)
                result = store.reconcile(dict(action='reconcile', project_id=self.pid, job_id=jid,
                    expected_job_revision=current['job']['job_revision'], request_id=str(uuid.uuid4())))
                assert isinstance(result, dict) and isinstance(result['job'], dict)
                self.assertEqual(result['job']['state'], 'awaiting_external')
                self.assertEqual(result['job']['cancel']['disposition'], 'unsupported')
                self.assertTrue(result['job']['cancel']['external_may_continue'])
                self.assertIsNone(next(iter(store.read(self.pid,jid)['attempts'].values()))['ended_at'])

    def test_cancel_waits_for_real_project_job_lock(self):
        import fcntl
        import threading
        from unittest.mock import patch

        store = self.store()
        job = store.submit(self.args())['job']
        args = dict(action='cancel', project_id=self.pid, job_id=job['job_id'],
                    expected_job_revision=job['job_revision'], request_id=str(uuid.uuid4()),
                    reason='deterministic held-lock cancellation')
        contended, finished = threading.Event(), threading.Event()
        results, errors = [], []
        real_flock = fcntl.flock

        def observe_flock(fd, operation):
            # Observe a real kernel refusal; never fake acquisition or unlock.
            try:
                return real_flock(fd, operation)
            except BlockingIOError:
                contended.set()
                raise

        def cancel():
            try:
                results.append(store.cancel(args))
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        fs = self.projects._filesystem(write=True)
        with patch('studio.project.fcntl.flock', observe_flock):
            thread = threading.Thread(target=cancel)
            try:
                with fs.lock(store.lock_path(self.pid)):
                    thread.start()
                    self.assertTrue(contended.wait(2), 'cancel never reached the held real lock')
                    self.assertFalse(store.read(self.pid, job['job_id'])['job']['cancel']['requested'])
                # Release follows observed contention, never an arbitrary sleep.
            finally:
                if thread.ident is not None:
                    thread.join(2)
        self.assertFalse(thread.is_alive(), 'cancel did not finish after lock release')
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [], [getattr(exc, 'code', str(exc)) for exc in errors])
        self.assertEqual(results[0]['job']['state'], 'cancelled')
        self.assertEqual(results[0]['cancel']['disposition'], 'confirmed')
        retained = store.read(self.pid, job['job_id'])
        self.assertTrue(retained['job']['cancel']['requested'])
        self.assertEqual(retained['attempts'], {})
        self.assertEqual(retained['artifacts'], [])
        replay = store.cancel(args)
        self.assertEqual(replay['cancel'], results[0]['cancel'])
        self.assertEqual({k: v for k, v in replay['job'].items() if k != 'monitoring'},
                         {k: v for k, v in results[0]['job'].items() if k != 'monitoring'})
        self.assertEqual(replay['job']['monitoring']['ended_at'], retained['monitoring']['ended_at'])
        self.assertEqual(store.read(self.pid, job['job_id']), retained)

    def test_real_owned_cancel_then_reconcile(self):
        import threading
        processes = []
        class SleepingAdapter(LocalAdapter):
            def execute(self, request, attempt, worker):
                proc = fixture_spawn(worker, [sys.executable, '-c', 'import time; time.sleep(20)'])
                processes.append(proc)
                proc.wait(timeout=25)
                return {'state': 'cancelled', 'submission_state': 'confirmed', 'external_handle': None,
                        'remote_state': 'none', 'progress': None, 'outputs': [], 'warnings': [],
                        'error': None, 'observed_cost': None, 'logs_ref': None, 'handoff': None}
        store = self.store()
        store.adapter_resolver = lambda b: SleepingAdapter()
        job = store.submit(self.args())['job']
        worker = store.start_worker(self.pid, job['job_id'])
        self.addCleanup(worker.join, 2)
        for _ in range(200):
            bundle = store.read(self.pid, job['job_id'])
            if bundle['attempts'] and next(iter(bundle['attempts'].values()))['owner']['pid']:
                break
            threading.Event().wait(.01)
        owner = next(iter(bundle['attempts'].values()))['owner']
        self.assertTrue(store.process_alive(owner))
        cancelled = store.cancel({'action': 'cancel', 'project_id': self.pid, 'job_id': job['job_id'],
                                 'expected_job_revision': bundle['job']['job_revision'], 'request_id': str(uuid.uuid4()), 'reason': 'Task-owned cancellation test'})
        self.assertEqual(cancelled['cancel']['disposition'], 'pending')
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(store.process_alive(owner))
        bundle = store.read(self.pid, job['job_id'])
        result = store.reconcile({'action': 'reconcile', 'project_id': self.pid, 'job_id': job['job_id'],
                                 'expected_job_revision': bundle['job']['job_revision'], 'request_id': str(uuid.uuid4())})
        self.assertEqual(result['job']['state'], 'cancelled')
        self.assertEqual(result['job']['cancel']['disposition'], 'confirmed')
        self.assertEqual(store.read(self.pid,job['job_id'])['artifacts'], [])
        for process in processes:
            self.assertIsNotNone(process.returncode)
            with self.assertRaises(ChildProcessError):
                os.waitpid(process.pid, os.WNOHANG)

    def test_mismatched_identity_never_signals_live_owned_process(self):
        store = self.store()
        case = self
        class Sentinel(LocalAdapter):
            def execute(self, request, attempt, worker):
                proc = fixture_spawn(worker, [sys.executable, '-c', 'import time; time.sleep(20)'])
                try:
                    owner = store.read(case.pid,attempt['job_id'])['attempts'][attempt['attempt_id']]['owner']
                    case.assertTrue(store.process_alive(owner))
                    for key, wrong in (('worker_token','wrong'), ('process_started_at','wrong'),
                            ('boot_id','wrong')):
                        case.assertFalse(store._signal_owned(owner | {key:wrong}))
                        case.assertIsNone(proc.poll())
                finally:
                    proc.terminate()
                    proc.wait(timeout=5)
                return super().execute(request,attempt,worker)
        store.adapter_resolver = lambda b: Sentinel()
        job = store.submit(self.args())['job']
        self.assertEqual(store.run_queued(self.pid,job['job_id'])['state'], 'succeeded')

    def test_cancel_quarantines_late_success_without_publication(self):
        store = self.store()
        case = self
        class LateSuccess(LocalAdapter):
            def execute(self, request, attempt, worker):
                result = super().execute(request,attempt,worker)
                bundle = store.read(case.pid,attempt['job_id'])
                store.cancel(dict(action='cancel', project_id=case.pid, job_id=attempt['job_id'],
                    expected_job_revision=bundle['job']['job_revision'],
                    request_id=str(uuid.uuid4()), reason='controlled late completion race'))
                return result
        store.adapter_resolver = lambda b: LateSuccess()
        jid = store.submit(self.args())['job']['job_id']
        result = store.run_queued(self.pid,jid)
        self.assertNotEqual(result['state'],'succeeded')
        bundle = store.read(self.pid,jid)
        self.assertEqual(bundle['artifacts'], [])
        self.assertEqual(bundle['job']['outputs'], [])
        self.assertIn('quarantined',bundle['job']['node_states'][0]['blocked_reason'])
        self.assertTrue((self.projects.root / next(iter(bundle['attempts'].values()))['output_dir'] / 'report.json').exists())

    def test_b06_compiler_loader_to_owned_job(self):
        from studio.jobs import JobStore
        from studio.plans import PlanCompiler
        from test_capabilities import registry
        self.projects.dispatch({'action': 'update', 'project_id': self.pid, 'expected_revision': 1,
            'request_id': str(uuid.uuid4()), 'changes': [{'op': 'set_bindings', 'value': {
                'selected_adapter_ids': ['fixture.probe'], 'preferences': {}, 'pins': {}}}]})
        from studio.assets import AssetStore, AssetRegistry
        from test_assets import provenance
        source_path = Path(self.tmp.name) / 'input.mp4'
        source_path.write_bytes(b'opaque input fixture; no media decode asserted')
        imported = AssetStore(root=self.projects.root).dispatch({'action':'import', 'project_id':self.pid,
            'expected_revision':2, 'request_id':str(uuid.uuid4()), 'source':{'kind':'local','path':str(source_path)},
            'label':'real opaque bytes', 'kind':'media', 'provenance':provenance()})
        self.assertTrue(imported['ok'], imported)
        artifact = AssetStore(root=self.projects.root).dispatch({'action':'get', 'project_id':self.pid,
            'asset_id':imported['data']['asset']['asset_id']})['data']['artifact']
        source = {k: artifact[k] for k in ('artifact_id','sha256')}
        compiler = PlanCompiler(self.projects, registry(), artifact_resolver=lambda pid, pin: artifact)
        self.plan = compiler.compile({'action': 'compile', 'project_id': self.pid,
            'expected_revision': 3, 'request_id': str(uuid.uuid4()), 'requests': [{
                'target_key': 'report', 'operation': 'media.probe@1', 'parameters': {},
                'inputs': {'media': {'kind': 'artifact', 'artifact': source}}}], 'targets': ['report']})
        store = JobStore(self.projects, plan_reader=compiler.load, authority=FixtureAuthority(),
                         adapter_resolver=lambda binding: LocalAdapter(),
                         input_validator=lambda pid, inputs: None)  # Explicit contract fixture, not a media probe.
        args = self.args() | {'expected_revision': 3}
        result = store.submit(args)
        self.assertEqual(store.run_queued(self.pid, result['job']['job_id'])['state'], 'succeeded')

    def test_serial_owned_stdin_and_timeout_cleanup(self):
        store = self.store()
        self_case = self
        seen = []
        class Serial(LocalAdapter):
            def execute(self, request, attempt, worker):
                for payload in (b'first', b'second'):
                    result = fixture_run(worker, [sys.executable, '-c',
                        'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper()); sys.stderr.write("measured")'],
                        input=payload, timeout=5, check=True)
                    assert result.stdout == payload.upper() and result.stderr == b'measured'
                    seen.append(worker.process.pid)
                import subprocess
                try:
                    fixture_run(worker, [sys.executable, '-c', 'import time; time.sleep(60)'], timeout=.02)
                    raise AssertionError('timeout expected')
                except subprocess.TimeoutExpired:
                    assert worker.process.poll() is not None
                    with self_case.assertRaises(ChildProcessError):
                        os.waitpid(worker.process.pid, os.WNOHANG)
                return super().execute(request, attempt, worker)
        store.adapter_resolver = lambda b: Serial()
        job = store.submit(self.args())['job']
        self.assertEqual(store.run_queued(self.pid, job['job_id'])['state'], 'succeeded')
        self.assertEqual(len(set(seen)), 2)

    def test_failed_dependency_blocks_only_descendants(self):
        first = self.plan['nodes'][0]
        child = copy.deepcopy(first)
        child.update(node_id=uid('nod'), target_key='child', dependencies=[first['node_id']])
        independent = copy.deepcopy(first)
        independent.update(node_id=uid('nod'), target_key='independent')
        self.plan['nodes'].extend([child, independent])
        self.plan['effects'] *= 3
        self.freeze()
        store = self.store()
        calls = []
        class Selective(LocalAdapter):
            def execute(self, request, attempt, worker):
                calls.append(request['node_id'])
                if request['node_id'] == first['node_id']:
                    return {'state':'failed', 'submission_state':'confirmed', 'external_handle':None,
                        'remote_state':'none', 'outputs':[], 'error':None}
                return super().execute(request, attempt, worker)
        store.adapter_resolver = lambda b: Selective()
        job = store.submit(self.args())['job']
        self.assertEqual(store.run_queued(self.pid, job['job_id'])['state'], 'failed')
        bundle = store.read(self.pid, job['job_id'])
        self.assertEqual(calls, [first['node_id'], independent['node_id']])
        self.assertEqual(len(bundle['attempts']), 2)
        self.assertTrue(next(n for n in bundle['job']['node_states'] if n['node_id'] == child['node_id'])['blocked_reason'])
        self.assertEqual(len(bundle['job']['outputs']), 1)

    def test_reuse_rehashes_complete_outputs_without_adapter_effect(self):
        store = self.store()
        job = store.submit(self.args())['job']
        store.run_queued(self.pid, job['job_id'])
        prior = store.read(self.pid, job['job_id'])
        self.plan['plan_id'] = uid('pln')
        self.plan['nodes'][0]['reuse'] = prior['job']['outputs']
        self.freeze()
        def no_adapter(binding):
            raise AssertionError('Reuse must not resolve or call adapter')
        store.adapter_resolver = no_adapter
        reused_job = store.submit(self.args())['job']
        self.assertEqual(store.run_queued(self.pid, reused_job['job_id'])['state'], 'succeeded')
        reused = store.read(self.pid, reused_job['job_id'])
        self.assertEqual(reused['job']['attempt_ids'], [])
        self.assertEqual(reused['job']['outputs'], prior['job']['outputs'])
        tampered = self.projects.root / prior['artifacts'][0]['storage']['relative_path']
        tampered.chmod(0o600)
        tampered.write_bytes(b'tampered')
        with self.assertRaises(ContractError) as cm:
            store.submit(self.args())
        self.assertEqual(cm.exception.code, 'HASH_MISMATCH')

    def test_reuse_requires_exact_port_order(self):
        class TwoOutputs(LocalAdapter):
            def execute(self, request, attempt, worker):
                result = super().execute(request, attempt, worker)
                result['outputs'].append(dict(result['outputs'][0], port='second'))
                return result
        self.plan['nodes'][0]['expected_outputs'].append(
            {'port': 'second', 'kind': 'report', 'media_type': 'application/json'})
        self.freeze()
        store = self.store()
        store.adapter_resolver = lambda binding: TwoOutputs()
        jid = store.submit(self.args())['job']['job_id']
        self.assertEqual(store.run_queued(self.pid, jid)['state'], 'succeeded')
        prior = store.read(self.pid, jid)
        self.plan['plan_id'] = uid('pln')
        self.plan['nodes'][0]['reuse'] = list(reversed(prior['job']['outputs']))
        self.freeze()
        with self.assertRaises(ContractError) as cm:
            store.submit(self.args())
        self.assertEqual(cm.exception.code, 'OUTPUT_INVALID')

    def test_document_pin_materializes_real_core_artifact(self):
        from studio.assets import AssetStore
        from test_assets import provenance
        fs = self.projects._filesystem()
        snapshot, docs = self.projects._load(fs, self.projects._pointer(fs, self.pid))
        pin = next(p for p in snapshot['documents'] if p['kind'] == 'brand')
        document = docs['brand', 'project']
        source = Path(self.tmp.name) / 'brand.json'
        source.write_text(json.dumps(document))
        assets = AssetStore(root=self.projects.root)
        imported = assets.dispatch({'action':'import','project_id':self.pid,'expected_revision':1,
            'request_id':str(uuid.uuid4()),'source':{'kind':'local','path':str(source)},
            'label':'document materialization fixture','kind':'json','provenance':provenance()})
        self.assertTrue(imported['ok'], imported)
        artifact = assets.dispatch({'action':'get','project_id':self.pid,
            'asset_id':imported['data']['asset']['asset_id']})['data']['artifact']
        self.plan['project_revision'] = 2
        self.plan['nodes'][0]['inputs'] = {'brand':{'kind':'document','document':pin}}
        self.freeze()
        store = self.store()
        store.document_resolver = lambda pid, frozen: {'document':document, 'artifact':artifact}
        job = store.submit(self.args() | {'expected_revision':2})['job']
        self.assertEqual(store.run_queued(self.pid, job['job_id'])['state'], 'succeeded')
        bundle = store.read(self.pid, job['job_id'])
        material_pin = {k:artifact[k] for k in ('artifact_id','sha256')}
        self.assertEqual(bundle['resolved_inputs'][self.plan['nodes'][0]['node_id']]['brand'], material_pin)
        self.assertFalse(store.status(self.pid, job['job_id'])['stale'])
        # ProjectStore still refuses content writes once later-unit records exist;
        # dependency-scoped status itself is read-only and does not overwrite pins.
        wrong = copy.deepcopy(document)
        wrong['revision'] += 1
        store.document_resolver = lambda pid, frozen: {'document':wrong, 'artifact':artifact}
        with self.assertRaises(ContractError) as cm:
            store._inputs(self.plan, self.plan['nodes'][0])
        self.assertEqual(cm.exception.code, 'HASH_MISMATCH')

    def test_source_bundle_output_commits_verified_sibling_closure(self):
        import hashlib
        member = b'owned source bytes; not executed'
        manifest = {'schema':'motion/v1/source-bundle','entry_member':'main.py','members':[
            {'relative_path':'main.py','sha256':'sha256:'+hashlib.sha256(member).hexdigest(),
             'size_bytes':len(member),'media_type':'text/plain'}]}
        self.plan['nodes'][0]['expected_outputs'][0]['kind'] = 'scene_source'
        self.freeze()
        class Bundle(LocalAdapter):
            def execute(self, request, attempt, worker):
                fixture_run(worker, [sys.executable,'-c',
                    'from pathlib import Path; import sys; Path("report.json").write_text(sys.argv[1]); Path("main.py").write_bytes(sys.argv[2].encode())',
                    json.dumps(manifest), member.decode()], timeout=5, check=True)
                return {'state':'succeeded','submission_state':'confirmed','external_handle':None,
                    'remote_state':'none','outputs':[{'port':'report','relative_path':'report.json',
                    'media_type':'application/json','claimed_sha256':None}],'error':None}
        store = self.store()
        store.adapter_resolver = lambda binding: Bundle()
        job = store.submit(self.args())['job']
        self.assertEqual(store.run_queued(self.pid, job['job_id'])['state'], 'succeeded')
        bundle = store.read(self.pid, job['job_id'])
        pin = bundle['job']['outputs'][0]
        record = store._artifact(self.pid, pin, bundle)
        closure = self.projects.root / (record['storage']['relative_path'] + '.members') / 'main.py'
        self.assertEqual(closure.read_bytes(), member)
        closure.write_bytes(b'changed')
        with self.assertRaises(ContractError) as cm:
            store._artifact(self.pid, pin, bundle)
        self.assertEqual(cm.exception.code, 'HASH_MISMATCH')

    def test_cross_action_and_cross_job_request_namespace(self):
        store = self.store()
        args = self.args()
        job = store.submit(args)['job']
        second = store.submit(self.args())['job']
        for target in (job, second):
            with self.assertRaises(ContractError) as cm:
                store.cancel({'action':'cancel', 'project_id':self.pid, 'job_id':target['job_id'],
                    'expected_job_revision':1, 'request_id':args['request_id'], 'reason':'collision'})
            self.assertEqual(cm.exception.code, 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(store.submit(args)['job']['job_id'], job['job_id'])

    def test_no_host_authority_is_not_local_approval(self):
        from studio.jobs import JobStore
        store = JobStore(self.projects, plan_reader=lambda pid, pin: self.plan)
        with self.assertRaises(ContractError) as cm:
            store.submit(self.args())
        self.assertEqual(cm.exception.code, 'PERMISSION_DENIED')


if __name__ == '__main__':
    unittest.main()
