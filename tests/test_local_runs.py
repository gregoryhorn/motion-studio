"""CF-B2 offline invocation, admission, identity and lifecycle regressions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import os
import signal
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pydantic import ValidationError
from studio.domain import Fault
from studio.persistence.store import Store, identity
from studio.producer.local_sfx import Binding, PrepareSFX, vector
from studio.runs.service import LocalRuns
from studio.runs.owned_process import OwnedProcess, incarnation, signal_owned
from tests.producer_support import fixture_binding, prepare, wait_run, effects


class LocalRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binding = fixture_binding(self.root / 'tool')
        self.store = Store(self.root / 'var')
        self.runs = LocalRuns(self.store, self.binding, OwnedProcess(deadline=2, grace=0.1))

    def tearDown(self):
        self.runs.close()
        self.temp.cleanup()

    def start(self, run):
        self.runs.start(run, lambda: True)
        return wait_run(self.runs, run)

    def test_actual_argv_hostile_direction_environment_and_no_shell_effect(self):
        direction = "English whoosh ' \" ; $(touch DO_NOT_CREATE)\n`false` & | > /tmp/no"
        item, _ = prepare(self.runs, direction)
        with patch.dict(os.environ, {'PYTHONPATH': '/do-not-inherit', 'PROVIDER_API_KEY': 'TEST_NOT_A_SECRET'}):
            row = self.start(item['id'])
        self.assertEqual(row['status'], 'Ready for review')
        observed = effects(self.binding)
        self.assertEqual(len(observed), 1)
        output = self.root / 'var/staging' / ('sfx-' + item['id']) / 'outputs/candidate.wav'
        self.assertEqual(observed[0]['argv'], vector(self.binding.path, row['plan'], output))
        self.assertNotIn('PROVIDER_API_KEY', observed[0]['env'])
        self.assertNotIn('PYTHONPATH', observed[0]['env'])
        self.assertFalse((self.binding.path.parent / 'DO_NOT_CREATE').exists())
        self.assertEqual(row['certainty'], 'exited')
        self.assertEqual(row['plan']['direction'], direction)
        self.assertEqual(row['plan']['purpose'], 'Non-private test')
        public = self.runs.records.public(item['id'])
        self.assertEqual(public['origin'], 'test_fixture')
        self.assertIsNone(public['host_session'])
        self.assertNotIn(direction, str(public))
        self.assertNotIn(str(output), str(public))

    def test_finite_inputs_and_final_argument_denial_zero_starts(self):
        item, model = prepare(self.runs)
        for extra in ('executable', 'output', 'env', 'profile', 'uri', 'owner', 'receipt', 'direction'):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                PrepareSFX(**{**model.model_dump(), extra: 'not allowed'})
        for seconds in (float('nan'), float('inf'), 0.09, 10.1):
            with self.assertRaises(ValidationError):
                PrepareSFX(**{**model.model_dump(), 'seconds': seconds})
        with self.assertRaises(ValidationError):
            PrepareSFX(**{**model.model_dump(), 'seed': 4294967296})
        original = self.binding.final
        with patch.object(type(self.binding), 'final', side_effect=lambda p, o, a: original(p, o, a + ['--unknown'])):
            with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                row = self.start(item['id'])
                self.assertEqual(row['status'], 'Blocked')
                spawn.assert_not_called()
        self.assertEqual(effects(self.binding), [])

    def test_admission_denials_and_pin_drift_zero_child_starts(self):
        variants = [replace(self.binding, free_mib=8191), replace(self.binding, use_allowed=False),
                    replace(self.binding, disk_bytes=0), replace(self.binding, conflict=True), Binding()]
        for binding in variants:
            with self.subTest(binding=type(binding).__name__):
                self.runs.binding = binding
                item, _ = prepare(self.runs)
                with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                    row = self.start(item['id'])
                    self.assertEqual(row['status'], 'Blocked')
                    spawn.assert_not_called()
        self.runs.binding = self.binding
        item, _ = prepare(self.runs)
        self.binding.path.write_text(self.binding.path.read_text() + '\n# drift\n')
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            self.assertEqual(self.start(item['id'])['error'], 'RUNTIME_DRIFT')
            spawn.assert_not_called()

    def test_store_authority_exception_and_stale_snapshot_deny_launch(self):
        item, _ = prepare(self.runs)
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            with self.assertRaises(Fault):
                self.runs.start(item['id'], lambda: (_ for _ in ()).throw(Fault('AUTH_REQUIRED', 401)))
            with patch.object(self.runs.records, 'claim', side_effect=OSError()):
                with self.assertRaises(OSError):
                    self.runs.start(item['id'], lambda: True)
            self.runs.before_spawn = lambda: (_ for _ in ()).throw(RuntimeError('not logged'))
            self.assertEqual(self.start(item['id'])['status'], 'Outcome unknown')
            spawn.assert_not_called()
        self.assertEqual(effects(self.binding), [])

    def test_missing_proc_supervision_fails_before_spawn(self):
        item, _ = prepare(self.runs)
        with patch('studio.runs.owned_process.incarnation', return_value=None):
            with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                row = self.start(item['id'])
                self.assertEqual(row['status'], 'Blocked')
                self.assertEqual(row['error'], 'SUPERVISION_UNAVAILABLE')
                spawn.assert_not_called()

    def test_simultaneous_replay_changed_plan_restart_and_tombstones(self):
        item, model = prepare(self.runs)
        with ThreadPoolExecutor(max_workers=6) as pool:
            receipts = list(pool.map(lambda _: self.runs.prepare(model), range(6)))
        self.assertTrue(all(x == item for x in receipts))
        with self.assertRaises(Fault) as error:
            self.runs.prepare(model.model_copy(update={'seed': 1}))
        self.assertEqual(error.exception.code, 'COMMAND_CONFLICT')
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: self.runs.start(item['id'], lambda: True), range(6)))
        self.assertEqual(wait_run(self.runs, item['id'])['status'], 'Ready for review')
        self.runs.close()
        self.runs = LocalRuns(Store(self.root / 'var'), self.binding)
        self.assertEqual(self.runs.prepare(model), item)
        self.runs.start(item['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), 1)
        self.assertEqual(self.runs.records.get(item['id'])['generation'], 1)

    def test_identity_quota_and_final_snapshot_change_deny_without_eviction(self):
        item, model = prepare(self.runs)
        with patch('studio.runs.persistence.MAX_IDENTITIES', 1):
            self.assertEqual(self.runs.prepare(model), item)
            with self.assertRaises(Fault) as error:
                prepare(self.runs)
            self.assertEqual(error.exception.code, 'IDENTITY_STORAGE_FULL')
        request = model.request
        def revise():
            with self.store.transaction() as db:
                db.execute('UPDATE requests SET revision=2,text=? WHERE id=?', ('Later fixture', request))
        self.runs.before_spawn = revise
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            row = self.start(item['id'])
            self.assertEqual(row['status'], 'Blocked')
            self.assertEqual(row['error'], 'STALE_REVISION')
            spawn.assert_not_called()
        self.assertEqual(self.runs.prepare(model), item)
        self.assertEqual(effects(self.binding), [])

    def test_starting_restart_and_stop_race_zero_launch(self):
        first, _ = prepare(self.runs)
        self.assertTrue(self.runs.records.claim(first['id']))
        reopened = LocalRuns(self.store, self.binding)
        self.assertEqual(reopened.records.get(first['id'])['status'], 'Outcome unknown')
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            reopened.start(first['id'], lambda: True)
            spawn.assert_not_called()
        reopened.close()
        # A separate isolated state avoids clearing the unresolved original tombstone.
        store = Store(self.root / 'race-var')
        runs = LocalRuns(store, self.binding, OwnedProcess(grace=0.1))
        try:
            second, _ = prepare(runs)
            def stop_before_spawn():
                runs.stop(second['id'])
            runs.before_spawn = stop_before_spawn
            with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                runs.start(second['id'], lambda: True)
                self.assertEqual(wait_run(runs, second['id'])['status'], 'Cancelled')
                spawn.assert_not_called()
        finally:
            runs.close()
        self.assertEqual(effects(self.binding), [])

    def test_stop_before_start_running_kill_completion_won_and_unrelated_pid(self):
        first, _ = prepare(self.runs)
        self.assertEqual(self.runs.stop(first['id'])['status'], 'Cancelled')
        self.assertEqual(self.start(first['id'])['status'], 'Cancelled')
        self.assertEqual(effects(self.binding), [])
        (self.binding.path.parent / 'mode').write_text('ignore-term')
        second, _ = prepare(self.runs)
        self.runs.start(second['id'], lambda: True)
        running = wait_run(self.runs, second['id'], {'Running'})
        ready = self.binding.path.parent / ('ready-' + str(running['process']['incarnation']['pid']))
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists())
        self.runs.stop(second['id'])
        row = wait_run(self.runs, second['id'])
        self.assertEqual(row['status'], 'Cancelled')
        self.assertEqual(row['process']['exit_code'], -signal.SIGKILL)
        pid = row['process']['incarnation']['pid']
        self.assertIsNone(incarnation(pid))
        # Simulate PID reuse: a wrong incarnation must never reach killpg.
        with patch('studio.runs.owned_process.os.killpg') as kill:
            fake = type('Child', (), {'pid': os.getpid()})()
            with self.assertRaises(Fault):
                signal_owned(fake, {'pid': os.getpid(), 'start': 'wrong'}, signal.SIGTERM)
            kill.assert_not_called()
        (self.binding.path.parent / 'mode').write_text('good')
        third, _ = prepare(self.runs)
        self.assertEqual(self.start(third['id'])['status'], 'Ready for review')
        self.assertEqual(self.runs.stop(third['id'])['status'], 'Ready for review')

    def test_kernel_deadline_survives_exec_without_parent_clock_progress(self):
        (self.binding.path.parent / 'mode').write_text('sleep')
        self.runs.worker = OwnedProcess(deadline=0.2, grace=0.1)
        item, _ = prepare(self.runs)
        with patch('studio.runs.owned_process.time', SimpleNamespace(monotonic=lambda: 0, sleep=time.sleep)):
            row = self.start(item['id'])
        self.assertEqual(row['status'], 'Failed')
        self.assertEqual(row['error'], 'TIMEOUT')
        self.assertEqual(row['process']['exit_code'], -signal.SIGALRM)

    def test_deadline_capture_and_file_limits(self):
        for mode, reason in [('sleep', 'TIMEOUT'), ('closed-pipes-sleep', 'TIMEOUT'), ('flood-stdout', 'CAPTURE_LIMIT'),
                             ('flood-stderr', 'CAPTURE_LIMIT'), ('file-limit', 'CHILD_FAILED'),
                             ('staging-limit', 'STAGING_LIMIT')]:
            with self.subTest(mode=mode):
                (self.binding.path.parent / 'mode').write_text(mode)
                self.runs.worker = OwnedProcess(deadline=0.4, grace=0.1, staging_limit=20 * 1024 * 1024)
                item, _ = prepare(self.runs)
                row = self.start(item['id'])
                self.assertEqual(row['status'], 'Failed')
                self.assertEqual(row['error'], reason)
                self.assertTrue(row['process']['exited'])
                self.assertIsNone(incarnation(row['process']['incarnation']['pid']))

    def test_shutdown_revocation_unknown_restart_no_rerun_and_route_busy(self):
        (self.binding.path.parent / 'mode').write_text('sleep')
        item, _ = prepare(self.runs)
        allowed = threading.Event()
        allowed.set()
        def authority():
            if not allowed.is_set():
                raise Fault('AUTH_REQUIRED', 401)
        self.runs.start(item['id'], authority)
        wait_run(self.runs, item['id'], {'Running'})
        allowed.clear()
        self.assertEqual(wait_run(self.runs, item['id'])['status'], 'Cancelled')
        other, _ = prepare(self.runs)
        self.runs.start(other['id'], lambda: True)
        wait_run(self.runs, other['id'], {'Running'})
        self.runs.close()
        self.assertEqual(self.runs.records.get(other['id'])['status'], 'Cancelled')
        self.runs = LocalRuns(self.store, self.binding, OwnedProcess(grace=0.1))
        uncertain, _ = prepare(self.runs)
        self.runs.worker.after_spawn = lambda: (_ for _ in ()).throw(SystemExit())
        row = self.start(uncertain['id'])
        self.assertEqual(row['status'], 'Outcome unknown')
        count = len(effects(self.binding))
        self.runs.close()
        self.runs = LocalRuns(self.store, self.binding)
        self.runs.start(uncertain['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), count)
        blocked, _ = prepare(self.runs)
        with self.assertRaises(Fault):
            self.runs.start(blocked['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), count)


if __name__ == '__main__':
    unittest.main()
