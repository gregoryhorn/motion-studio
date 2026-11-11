"""CF-RR1 controlled historical scenarios; no model and no historical user records."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from tests.http_support import TestClient
from studio.domain import Fault
from studio.persistence.store import canonical
from studio.producer.live_sfx import USE
from studio.producer.stable_adapter import StableAudio
from studio.runs.admission import OneCandidate
from studio.runs.reconciliation import commit, observe
from studio.server import create_app
from tests.producer_support import fixture_binding, prepare, wait_run, effects
from tools.qualify_local_sfx import Evaluation, post
from tools.qualify_runtime_recovery import prepare_successor, RecoveryCandidate


class HistoricalReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binding = fixture_binding(self.root / 'tool', mode='output-directory')
        self.app = create_app(self.root / 'var', b'controlled-offline-reconciliation-test', 'http://testserver', _test_binding=self.binding)
        self.runs = self.app.state.runs
        self.runs.worker.grace = 0.1
        self.item, _ = prepare(self.runs, text='Non-private synthetic reconciliation whoosh', seconds=3.0)
        self.client = TestClient(self.app)
        self.client.headers['origin'] = 'http://testserver'
        login = post(self.client, '/api/login', {'secret':'controlled-offline-reconciliation-test'})
        self.client.headers['x-csrf-token'] = login['csrf']
        scope = OneCandidate(self.runs, self.item['id'], login['csrf'], USE)
        row = self.runs.records.get(self.item['id'])
        scope.install(StableAudio().runtime(row['plan']['binding']))
        post(self.client, f'/api/sfx/runs/{self.item["id"]}/start', {})
        row = wait_run(self.runs, self.item['id'])
        self.assertEqual(row['status'], 'Failed')
        self.runs.threads[self.item['id']].join(timeout=8)
        self.assertFalse(self.runs.threads[self.item['id']].is_alive(), 'Historical scenario requires the controlled worker to be retired')
        scope.close()
        # Synthetic historical durable-loss scenario: preserve the actual fixture
        # incarnation but deliberately remove its exit receipt. Not a real producer.
        process = {k:v for k,v in row['process'].items() if k not in ('exited','exit_code','retirement','group_retired','cleanup_error')}
        self.runs.records.update(self.item['id'], status='Outcome unknown', certainty='started', process=process)
        with self.runs.store.transaction() as db:
            db.execute('UPDATE local_runs SET fixture=0 WHERE id=?', (self.item['id'],))
        self.original = self.runs.records.get(self.item['id'])
        self.contract = patch.object(StableAudio, 'validate_retirement_contract', return_value=None)
        self.contract.start()
        self.clock = patch('studio.runs.reconciliation.retirement', return_value=(True, [dict(elapsed=700, retired=True)] * 2))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.contract.stop()
        self.client.close()
        self.runs.close()
        self.temp.cleanup()

    def test_authenticated_atomic_idempotent_reconcile_preserves_started_no_exit_and_scope(self):
        route = f'/api/sfx/runs/{self.item["id"]}/reconcile'
        unauth = TestClient(self.app)
        try:
            self.assertEqual(unauth.post(route, json={}, headers={'origin':'http://testserver'}).status_code, 401)
        finally:
            unauth.close()
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch')), \
             patch('os.killpg', side_effect=AssertionError('must not signal')):
            public = post(self.client, route, {})
            self.assertEqual(public, post(self.client, route, {}))
            self.runs.start(self.item['id'], lambda: True)
        final = self.runs.records.get(self.item['id'])
        self.assertEqual((final['status'],final['certainty'],final['error']), ('Failed','started','OUTPUT_UNSAFE'))
        self.assertNotIn('exit_code', final['process'])
        self.assertTrue(final['process']['exit_code_unobserved'])
        for key in ('id','candidate','plan','plan_digest','nonce','generation','collection'):
            self.assertEqual(final[key], self.original[key])
        self.assertIn('exit code unobserved', public['outcome_note'])
        with self.runs.store.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM run_reconciliations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT state FROM bounded_admission').fetchone()[0], 'closed_consumed')
        self.assertEqual(len(effects(self.binding)), 1)

    def test_surviving_group_reused_pid_visibility_or_boot_cannot_clear(self):
        for issue in ('survivor','pid-reuse','visibility','boot'):
            with self.subTest(issue=issue), patch('studio.runs.reconciliation.retirement', return_value=(False, [{'issue':issue}])):
                with self.assertRaises(Fault) as denied:
                    commit(self.runs, self.item['id'])
                self.assertEqual(denied.exception.code, 'GROUP_RETIREMENT_UNPROVEN')
                self.assertEqual(self.runs.records.get(self.item['id'])['status'], 'Outcome unknown')

    def test_insufficient_time_context_does_not_prove_death(self):
        with patch('studio.runs.reconciliation.retirement', return_value=(True, [dict(elapsed=10)] * 2)):
            with self.assertRaises(Fault) as denied:
                commit(self.runs, self.item['id'])
        self.assertEqual(denied.exception.code, 'DEADLINE_CONTEXT_INSUFFICIENT')

    def test_changed_allocation_and_concurrent_row_refuse(self):
        from studio.assets.runtime_workspace import paths
        _, outputs, _ = paths(self.runs.store, self.original)
        outputs.rename(outputs.with_name('controlled-retained-outputs'))
        outputs.mkdir(mode=0o700)
        with self.assertRaises(Fault):
            commit(self.runs, self.item['id'])
        outputs.rmdir()
        outputs.with_name('controlled-retained-outputs').rename(outputs)
        real_observe = observe
        def changed(runs, run):
            evidence = real_observe(runs, run)
            runs.records.update(run, error='CONTROLLED_CONCURRENT_CHANGE')
            return evidence
        with patch('studio.runs.reconciliation.observe', side_effect=changed):
            with self.assertRaises(Fault) as denied:
                commit(self.runs, self.item['id'])
        self.assertEqual(denied.exception.code, 'RECONCILIATION_STATE_CHANGED')
        self.assertEqual(self.runs.records.get(self.item['id'])['status'], 'Outcome unknown')

    def test_valid_looking_output_or_stale_observation_does_not_unlock(self):
        from studio.assets.runtime_workspace import paths
        _, outputs, _ = paths(self.runs.store, self.original)
        output = outputs / 'candidate.wav'
        output.write_bytes(b'CONTROLLED_NOT_A_VALID_WAV')
        output.chmod(0o600)
        with self.assertRaises(Fault) as denied:
            commit(self.runs, self.item['id'])
        self.assertEqual(denied.exception.code, 'RECONCILIATION_OUTPUT_PRESENT')
        output.unlink()
        real_observe = observe
        def stale(runs, run):
            evidence = real_observe(runs, run)
            evidence['observed_monotonic'] -= 10
            return evidence
        with patch('studio.runs.reconciliation.observe', side_effect=stale), self.assertRaises(Fault):
            commit(self.runs, self.item['id'])
        self.assertEqual(self.runs.records.get(self.item['id'])['status'], 'Outcome unknown')

    def test_successor_refuses_unresolved_then_distinct_once_only_authenticated_api(self):
        previous = dict(run=self.item['id'], candidate=self.item['candidate'])
        value = Evaluation(direction=self.original['plan']['direction'], use=USE)
        with self.assertRaises(Fault) as denied:
            prepare_successor(self.client, self.runs, previous, value)
        self.assertEqual(denied.exception.code, 'RECOVERY_UNRESOLVED')
        post(self.client, f'/api/sfx/runs/{self.item["id"]}/reconcile', {})
        new, body, record = prepare_successor(self.client, self.runs, previous, value)
        self.assertNotEqual(new['id'], self.item['id'])
        self.assertNotEqual(new['candidate'], self.item['candidate'])
        with self.assertRaises(Fault):
            prepare_successor(self.client, self.runs, previous, value)
        (self.binding.path.parent / 'mode').write_text('runtime-good')
        owner = self.client.headers['x-csrf-token']
        scope = RecoveryCandidate(self.runs, new['id'], owner, USE)
        scope.install(StableAudio().runtime(record))
        try:
            post(self.client, f'/api/sfx/runs/{new["id"]}/start', {})
            self.assertEqual(wait_run(self.runs, new['id'])['status'], 'Ready for review')
            post(self.client, f'/api/sfx/runs/{new["id"]}/start', {})
            self.assertEqual(post(self.client, '/api/apps/plans', body)['id'], new['id'])
        finally:
            scope.close()
        self.assertEqual(len(effects(self.binding)), 2)
        self.assertEqual(self.runs.records.get(self.item['id'])['certainty'], 'started')
        self.assertEqual(self.runs.records.get(new['id'])['process']['layout'], 2)
        self.assertEqual(self.runs.records.public(new['id'])['origin'], 'test_fixture')

    def test_full_successor_driver_synthetic_sensitivity_and_duplicate_denial(self):
        from contextlib import redirect_stdout
        import io
        from tools.qualify_local_sfx import evaluate
        previous = dict(status='stopped_no_retry', error='OUTPUT_UNSAFE', run=self.item['id'], candidate=self.item['candidate'])
        (self.runs.store.home / 'state/lq1-resume-intent.json').write_text(json.dumps(previous))
        operation = self.root / 'controlled-operation.json'
        operation.write_text(json.dumps(dict(direction=self.original['plan']['direction'], use=USE)))
        (self.binding.path.parent / 'mode').write_text('runtime-good')
        def fixture_app(home, secret, origin):
            return create_app(home, secret, origin, _test_binding=self.binding)
        with patch('tools.qualify_local_sfx.create_app', side_effect=fixture_app), \
             patch('tools.qualify_local_sfx.ScopedRuntime', side_effect=lambda record, scope: StableAudio().runtime(record)), \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(Fault) as denied:
                evaluate(self.runs.store.home, operation, _recovery=True)
            self.assertEqual(denied.exception.code, 'PROVENANCE_MISMATCH')
            with self.assertRaises(Fault) as duplicate:
                evaluate(self.runs.store.home, operation, _recovery=True)
            self.assertEqual(duplicate.exception.code, 'RECOVERY_ALREADY_ATTEMPTED')
        self.assertEqual(len(effects(self.binding)), 2)
        self.assertEqual(json.loads((self.runs.store.home / 'state/lq1-resume-intent.json').read_text()), previous)
