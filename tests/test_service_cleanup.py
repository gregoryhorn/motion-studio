"""Service FD close faults use synthetic children only; no real producer or credentials."""
import errno
import fcntl
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch
from tests.http_support import TestClient
from studio.domain import Fault
from studio.server import create_app
from studio.runs.service import LocalRuns
from studio.assets.producer_files import allocation
from tests.producer_support import fixture_binding, prepare, effects


class ServiceCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binding = fixture_binding(self.root / 'tool')
        self.secret = b'controlled-service-cleanup-fixture-owner'
        self.app = create_app(self.root / 'var', self.secret, 'http://testserver', _test_binding=self.binding)
        self.runs = self.app.state.runs
        self.runs.worker.grace = 0.1
        self.sentinels = []
        self.fds, self.attempts = {}, []
        self.addCleanup(self.finish)

    def finish(self):
        self.runs.close()
        # Only descriptors known by the fixture to remain owned are closed here.
        for resource, fd in self.fds.items():
            if resource not in self.attempts:
                os.close(fd)
        for fd in self.sentinels:
            os.close(fd)
        self.temp.cleanup()

    def run_fault(self, mode='good', failed=('outputs','route_lock'), *, storage_failure=False, unknown=False):
        (self.binding.path.parent / 'mode').write_text('sleep' if unknown else mode)
        item, _ = prepare(self.runs)
        def open_route(*args, **kwargs):
            fd = os.open(*args, **kwargs)
            self.fds['route_lock'] = fd
            return fd
        def open_outputs(*args):
            result = allocation(*args)
            self.fds['outputs'] = result[1]
            return result
        def close(fd):
            resource = next(name for name, value in self.fds.items() if value == fd and name not in self.attempts)
            self.attempts.append(resource)
            if resource in failed:
                # Model Linux close's release-before-error behavior. A blind retry
                # would close this new, unrelated fixture-owned descriptor.
                # Replace the STILL fixture-owned target atomically; open-after-close
                # need not reuse its number when other lower descriptors are free.
                sentinel = os.open(self.root / ('controlled-' + resource), os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    os.dup2(sentinel,fd)
                finally:
                    os.close(sentinel)
                self.sentinels.append(fd)
                raise OSError(errno.EIO, 'controlled close diagnostic, not private data')
            os.close(fd)
        if unknown:
            def crash_after_effect():
                end = time.monotonic() + 3
                while not effects(self.binding) and time.monotonic() < end:
                    time.sleep(0.005)
                self.assertEqual(len(effects(self.binding)), 1)
                raise SystemExit()
            self.runs.worker.after_spawn = crash_after_effect
        with patch('studio.runs.service.os', SimpleNamespace(open=open_route, close=close,
                 O_CREAT=os.O_CREAT, O_RDWR=os.O_RDWR, O_NOFOLLOW=os.O_NOFOLLOW)), \
             patch('studio.runs.service.allocation', side_effect=open_outputs):
            if storage_failure:
                with patch.object(self.runs.records, 'note_cleanup', side_effect=OSError('controlled metadata failure')):
                    self.runs.start(item['id'], lambda: True)
                    self.runs.threads[item['id']].join(timeout=8)
            else:
                self.runs.start(item['id'], lambda: True)
                self.runs.threads[item['id']].join(timeout=8)
        self.assertFalse(self.runs.threads[item['id']].is_alive())
        return self.runs.records.get(item['id'])

    def assert_secondary(self, row, failed):
        self.assertEqual(self.attempts, ['outputs','route_lock'])
        records = self.runs.records.cleanup(row['id'])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['nonce'], row['nonce'])
        self.assertEqual(records[0]['generation'], row['generation'])
        notes = records[0]['resources']
        self.assertEqual([item['resource'] for item in notes], self.attempts)
        for item in notes:
            expected = 'unconfirmed' if item['resource'] in failed else 'confirmed'
            self.assertEqual(item['close'], expected)
            self.assertNotIn('fd', item)
            if expected == 'unconfirmed':
                self.assertEqual(item['error'], 'FD_CLOSE_UNCONFIRMED')
        self.assertTrue(any(fd in self.fds.values() for fd in self.sentinels), 'fixture must exercise FD reuse')
        for fd in self.sentinels:
            os.fstat(fd)  # Still owned/open: failed closes were not blindly retried.

    def test_ready_survives_both_close_faults_same_bytes_and_restart_no_relaunch(self):
        row = self.run_fault()
        self.assertEqual(len(effects(self.binding)), 1)
        self.assertIsNotNone(row['collection'])
        self.assertTrue((self.runs.store.home / 'media' / (row['candidate'] + '.wav')).is_file())
        self.assertEqual((row['status'],row['certainty']), ('Ready for review','exited'))
        self.assertEqual(row['process']['exit_code'], 0)
        self.assertTrue(row['process']['group_retired'])
        self.assert_secondary(row, ('outputs','route_lock'))
        original = (self.runs.store.home / 'media' / (row['candidate'] + '.wav')).read_bytes()
        with TestClient(self.app) as client:
            client.headers['origin'] = 'http://testserver'
            login = client.post('/api/login', json={'secret':self.secret.decode()}).json()
            client.headers['x-csrf-token'] = login['csrf']
            self.assertEqual(client.get(f'/api/takes/{row["candidate"]}/media').content, original)
        self.runs = LocalRuns(self.runs.store, self.binding)
        reopened = self.runs.records.get(row['id'])
        self.assertEqual(reopened['process'], row['process'])
        self.assertEqual(reopened['status'], 'Ready for review')
        self.assert_secondary(reopened, ('outputs','route_lock'))
        self.runs.start(row['id'], lambda: True)
        self.assertEqual((self.runs.store.home / 'media' / (row['candidate'] + '.wav')).read_bytes(), original)
        self.assertEqual(len(effects(self.binding)), 1)

    def test_failed_terminal_exit_and_original_error_survive_close_fault(self):
        row = self.run_fault('output-directory', failed=('outputs',))
        self.assertEqual((row['status'],row['certainty'],row['error']), ('Failed','exited','OUTPUT_UNSAFE'))
        self.assertTrue(row['process']['group_retired'])
        self.assertIsInstance(row['process']['exit_code'], int)
        self.assert_secondary(row, ('outputs',))
        self.assertIsNone(row['collection'])
        self.runs.close()
        self.runs = LocalRuns(self.runs.store, self.binding)
        self.assertEqual(self.runs.records.get(row['id']), row)
        self.runs.start(row['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), 1)

    def test_route_close_fault_does_not_rewrite_ready(self):
        row = self.run_fault(failed=('route_lock',))
        self.assertEqual(row['status'], 'Ready for review')
        self.assert_secondary(row, ('route_lock',))
        self.assertEqual(len(effects(self.binding)), 1)

    def test_genuine_unknown_remains_active_nonreplayable_after_cleanup_faults(self):
        row = self.run_fault(unknown=True)
        self.assertEqual((row['status'],row['error']), ('Outcome unknown','EXECUTION_UNCERTAIN'))
        self.assertNotIn('exited', row['process'])
        self.assert_secondary(row, ('outputs','route_lock'))
        self.runs.start(row['id'], lambda: True)
        other, _ = prepare(self.runs)
        with self.assertRaises(Fault):
            self.runs.start(other['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), 1)

    def test_secondary_metadata_storage_failure_cannot_destroy_ready(self):
        row = self.run_fault(storage_failure=True)
        self.assertEqual(row['status'], 'Ready for review')
        self.assertEqual(self.attempts, ['outputs','route_lock'])
        self.assertEqual(self.runs.cleanup_notes[row['id']]['persistence'], 'unconfirmed')
        self.assertEqual(len(effects(self.binding)), 1)

    def test_unconfirmed_route_close_can_still_hold_lock_without_outcome_change(self):
        row = self.run_fault(failed=())
        output = os.open(self.root / 'controlled-output-fd', os.O_CREAT | os.O_RDWR, 0o600)
        route_path = self.root / 'controlled-route-fd'
        route = os.open(route_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(route, fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempts = []
        def close(fd):
            attempts.append(fd)
            if fd == route:
                raise OSError(errno.EIO, 'controlled refusal before close')
            os.close(fd)
        try:
            with patch('studio.runs.service.os', SimpleNamespace(close=close)):
                self.runs._close_resources(row['id'], (('outputs', output), ('route_lock', route)))
            self.assertEqual(attempts, [output,route])
            self.assertEqual(self.runs.records.get(row['id']), row)
            self.assertEqual(self.runs.records.cleanup(row['id'])[0]['resources'][1]['close'], 'unconfirmed')
            with route_path.open('rb') as probe:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(len(effects(self.binding)), 1)
        finally:
            # Fixture-owned teardown: the injected route close never executed.
            # Production does not retry an uncertain FD.
            os.close(route)
