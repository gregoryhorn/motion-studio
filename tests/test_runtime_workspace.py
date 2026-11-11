"""CF-RR1 synthetic actual-child workspace, observation and failure regressions."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from studio.assets import runtime_workspace as workspace
from studio.domain import Fault
from studio.persistence.store import Store
from studio.runs.service import LocalRuns
from studio.runs.owned_process import OwnedProcess, is_owned
from tests.producer_support import fixture_binding, prepare, wait_run, effects
from tests.test_helper_environment import SENTINELS


class RuntimeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binding = fixture_binding(self.root / 'tool')
        self.store = Store(self.root / 'var')
        self.runs = LocalRuns(self.store, self.binding, OwnedProcess(deadline=2, grace=0.1))

    def tearDown(self):
        self.runs.close()
        self.temp.cleanup()

    def start(self, mode):
        (self.binding.path.parent / 'mode').write_text(mode)
        item, _ = prepare(self.runs)
        self.runs.start(item['id'], lambda: True)
        return wait_run(self.runs, item['id'])

    def test_actual_nested_runtime_fixed_env_cwd_and_strict_collection(self):
        with patch.dict(os.environ, SENTINELS, clear=True):
            row = self.start('runtime-good')
        self.assertEqual(row['status'], 'Ready for review')
        self.assertTrue(row['process']['group_retired'])
        self.assertEqual(row['process']['layout'], 2)
        root, outputs, runtime = workspace.paths(self.store, row)
        observed = effects(self.binding)[0]
        self.assertEqual(observed['cwd'], str(runtime))
        for key, suffix in [('HOME','home'),('TMPDIR','tmp'),('XDG_CACHE_HOME','cache'),('CUDA_CACHE_PATH','cache/cuda')]:
            self.assertEqual(observed['env'][key], str(runtime / suffix))
            self.assertTrue((runtime / suffix / 'controlled-nested/controlled-state').is_file())
        self.assertTrue(set(SENTINELS).isdisjoint(observed['env']))
        self.assertEqual(set(p.name for p in outputs.iterdir()), {'candidate.wav','candidate.wav.json'})
        self.assertEqual(workspace.pin(root), row['process']['root'])
        self.assertEqual(workspace.pin(runtime), row['process']['runtime'])
        self.assertTrue((self.store.home / 'media' / (row['candidate'] + '.wav')).is_file())
        self.assertEqual(self.runs.records.public(row['id'])['origin'], 'test_fixture')

    def test_actual_output_directory_and_runtime_link_special_fail_with_known_exit(self):
        for mode in ('output-directory','runtime-link','runtime-special'):
            with self.subTest(mode=mode):
                row = self.start(mode)
                self.assertEqual(row['status'], 'Failed')
                self.assertEqual(row['error'], 'OUTPUT_UNSAFE')
                self.assertEqual(row['certainty'], 'exited')
                self.assertTrue(row['process']['exited'])
                self.assertTrue(row['process']['group_retired'])
                self.assertIsInstance(row['process']['exit_code'], int)
                self.assertIsNone(row['collection'])

    def test_combined_runtime_plus_output_budget(self):
        self.runs.worker.staging_limit = 70000
        row = self.start('runtime-budget')
        self.assertEqual(row['status'], 'Failed')
        self.assertEqual(row['error'], 'STAGING_LIMIT')
        self.assertTrue(row['process']['group_retired'])
        self.assertIsNone(row['collection'])

    def test_runtime_traversal_depth_entries_and_hardlink_are_bounded(self):
        base = self.root / 'controlled-tree'
        base.mkdir(mode=0o700)
        current = base
        for _ in range(workspace.MAX_DEPTH + 1):
            current = current / 'controlled-depth'
            current.mkdir(mode=0o700)
        with self.assertRaises(Fault) as limited:
            workspace.tree_snapshot(base)
        self.assertEqual(limited.exception.code, 'RUNTIME_LIMIT')
        flat = self.root / 'controlled-flat'
        flat.mkdir(mode=0o700)
        for n in range(4):
            (flat / str(n)).mkdir(mode=0o700)
        with patch.object(workspace, 'MAX_ENTRIES', 3), self.assertRaises(Fault):
            workspace.tree_snapshot(flat)
        linked = self.root / 'controlled-links'
        linked.mkdir(mode=0o700)
        original = linked / 'original'
        original.write_bytes(b'CONTROLLED')
        original.chmod(0o600)
        os.link(original, linked / 'hardlink')
        with self.assertRaises(Fault):
            workspace.tree_snapshot(linked)

    def test_effective_env_and_runtime_inode_rechecked_before_launch(self):
        original = self.runs.worker.execute
        def mutate(argv, env, directory, *args, **options):
            env['HOME'] = str(self.root / 'not-approved')
            return original(argv, env, directory, *args, **options)
        with patch.object(self.runs.worker, 'execute', side_effect=mutate):
            row = self.start('good')
        self.assertEqual((row['status'],row['error']), ('Blocked','ALLOCATION_UNSAFE'))
        self.assertEqual(effects(self.binding), [])
        def replace(argv, env, directory, *args, **options):
            directory.rename(directory.with_name('retained-original-runtime'))
            directory.mkdir(mode=0o700)
            return original(argv, env, directory, *args, **options)
        with patch.object(self.runs.worker, 'execute', side_effect=replace):
            row = self.start('good')
        self.assertEqual((row['status'],row['error']), ('Blocked','ALLOCATION_UNSAFE'))
        self.assertEqual(effects(self.binding), [])

    def test_monitor_fault_exit_survives_secondary_cleanup_error_and_reopen(self):
        def cleanup_error(child, pin):
            if child.returncode is not None:
                raise OSError('controlled cleanup observation failure')
            return is_owned(child, pin)
        with patch('studio.runs.owned_process.is_owned', side_effect=cleanup_error):
            row = self.start('output-directory')
        self.assertEqual((row['status'],row['error']), ('Failed','OUTPUT_UNSAFE'))
        self.assertTrue(row['process']['exited'])
        self.assertTrue(row['process']['group_retired'])
        self.assertEqual(row['process']['cleanup_error'], 'OSError')
        self.runs.close()
        self.runs = LocalRuns(self.store, self.binding)
        reopened = self.runs.records.get(row['id'])
        self.assertEqual(reopened['process'], row['process'])
        self.runs.start(row['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), 1)

    def test_unproven_group_keeps_active_risk_even_with_observed_exit(self):
        with patch('studio.runs.owned_process.retirement', return_value=(False, [])):
            row = self.start('output-directory')
        self.assertEqual(row['status'], 'Outcome unknown')
        self.assertEqual(row['error'], 'OUTPUT_UNSAFE')
        self.assertTrue(row['process']['exited'])
        other, _ = prepare(self.runs)
        with self.assertRaises(Fault):
            self.runs.start(other['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), 1)

    def test_lost_durable_exit_remains_unknown_nonreplayable(self):
        update = self.runs.records.update
        def loss(run, **values):
            if (values.get('process') or {}).get('exited'):
                raise OSError('controlled persistence loss')
            return update(run, **values)
        with patch.object(self.runs.records, 'update', side_effect=loss):
            row = self.start('output-directory')
        self.assertEqual(row['status'], 'Outcome unknown')
        self.assertNotIn('exited', row['process'])
        self.runs.start(row['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), 1)
