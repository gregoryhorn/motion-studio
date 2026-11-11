"""No inference: fake driver observations and harmless owned CPU children only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from studio.domain import Fault
from studio.producer import local_gpu
from studio.producer.live_sfx import resources
from studio.producer.music.bridge import foreground
from studio.runs.owned_process import OwnedProcess, incarnation
from studio.persistence.store import Store
from studio.runs.service import LocalRuns
from tests.producer_support import FixtureBinding, fixture_binding, prepare, wait_run


def driver(free=1024, processes='321,/private/models/python3,7000\n'):
    return [subprocess.CompletedProcess([], 0, str(free) + '\n', ''),
            subprocess.CompletedProcess([], 0, processes, '')]


class LocalModelEtiquetteTests(unittest.TestCase):
    def test_busy_gpu_reports_names_and_mb_without_eviction_or_spawn(self):
        with patch('studio.producer.local_gpu.subprocess.run', side_effect=driver()) as query, \
                patch('subprocess.Popen') as spawn, patch('os.killpg') as kill:
            with self.assertRaises(Fault) as blocked:
                resources()
        self.assertEqual(blocked.exception.code, 'LOCAL_GPU_BUSY')
        self.assertEqual(blocked.exception.gpu, dict(free_mib=1024, required_mib=8192,
                         processes=[dict(name='python3', used_mib=7000)]))
        self.assertEqual(query.call_count, 2)
        self.assertIn('--query-compute-apps=pid,process_name,used_memory', query.call_args.args[0])
        spawn.assert_not_called()
        kill.assert_not_called()

    def test_fitting_job_leaves_other_loaded_model_untouched(self):
        with patch('studio.producer.local_gpu.subprocess.run', side_effect=driver(10000)), \
                patch('os.killpg') as kill:
            self.assertEqual(resources(), (10000, False))
        kill.assert_not_called()

    def test_existing_sfx_competitor_remains_a_refusal_without_eviction(self):
        from studio.producer.local_sfx import ROOT
        with patch('studio.producer.local_gpu.subprocess.run',
                   side_effect=driver(10000, f'321,{ROOT}/venv/bin/python,1000\n')), \
                patch('os.killpg') as kill, self.assertRaises(Fault) as blocked:
            resources()
        self.assertEqual(blocked.exception.code, 'LOCAL_GPU_BUSY')
        kill.assert_not_called()

    def test_service_records_post_completion_gpu_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binding = fixture_binding(root / 'tool')
            runs = LocalRuns(Store(root / 'var'), binding)
            self.addCleanup(runs.close)
            item, _ = prepare(runs)
            # Simulated live bookkeeping with an explicitly synthetic CPU producer;
            # the real GPU/runtime is never admitted or touched by this test.
            with runs.store.transaction() as db:
                db.execute('UPDATE local_runs SET fixture=0 WHERE id=?', (item['id'],))
            with patch('studio.producer.local_gpu.subprocess.run', side_effect=driver(10000)) as query:
                runs.start(item['id'], lambda: True)
                row = wait_run(runs, item['id'])
            self.assertEqual(row['status'], 'Ready for review')
            self.assertEqual(runs.records.public(item['id'])['local_gpu_release'],
                             dict(owned_process_gone=True, released=True))
            self.assertEqual(query.call_count, 2)

    def test_unavailable_or_malformed_observations_do_not_allow_start(self):
        for observations in (driver(processes='321,private,unknown\n'),
                             driver(processes='invalid\n'), driver(-1)):
            with self.subTest(observations=observations), \
                    patch('studio.producer.local_gpu.subprocess.run', side_effect=observations), \
                    self.assertRaises(Fault) as blocked:
                resources()
            self.assertEqual(blocked.exception.code, 'RESOURCE_OBSERVATION_UNAVAILABLE')

    def test_busy_summary_is_saved_in_run_status_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binding = fixture_binding(root / 'tool')
            runs = LocalRuns(Store(root / 'var'), binding)
            self.addCleanup(runs.close)
            item, _ = prepare(runs)
            with patch.object(FixtureBinding, 'admit', side_effect=lambda *args: local_gpu.require_available(8192)), \
                    patch('studio.producer.local_gpu.subprocess.run', side_effect=driver()) as query, \
                    patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                runs.start(item['id'], lambda: True)
                row = wait_run(runs, item['id'])
            self.assertEqual((row['status'], row['error']), ('Blocked', 'LOCAL_GPU_BUSY'))
            public = runs.records.public(item['id'])
            self.assertEqual(public['local_gpu_busy']['processes'], [dict(name='python3', used_mib=7000)])
            self.assertEqual(query.call_count, 2)
            spawn.assert_not_called()

    def test_owned_jobs_end_and_preexisting_process_survives(self):
        with tempfile.TemporaryDirectory() as temp, subprocess.Popen(
                [sys.executable, '-I', '-c', 'import time; time.sleep(30)']) as existing:
            try:
                for mode, code, stop in (
                        ('success', 'pass', lambda: None),
                        ('failure', 'raise SystemExit(2)', lambda: None),
                        ('cancel', 'import time; time.sleep(30)', lambda: 'STOP_REQUESTED')):
                    with self.subTest(mode=mode):
                        fd = os.open(temp, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            worker = OwnedProcess(deadline=2, grace=0.1)
                            result = worker.execute([sys.executable, '-I', '-c', code], {},
                                Path(temp), fd, lambda _: None, lambda _: None, stop)
                        finally:
                            os.close(fd)
                        self.assertTrue(result['process_gone'])
                        self.assertTrue(result['group_retired'])
                        self.assertIsNone(incarnation(result['process']['pid']))
                        observations = driver(10000, f'{existing.pid},/private/python3,7000\n')
                        with patch('studio.producer.local_gpu.subprocess.run', side_effect=observations):
                            self.assertEqual(local_gpu.released(result),
                                             dict(owned_process_gone=True, released=True))
                        self.assertIsNone(existing.poll())
            finally:
                existing.terminate()
                existing.wait(timeout=3)

    def test_release_unknown_or_still_held_is_not_claimed(self):
        result = dict(process=dict(pid=321), group_retired=True, process_gone=True)
        with patch('studio.producer.local_gpu.subprocess.run', side_effect=driver(10000)):
            self.assertFalse(local_gpu.released(result)['released'])
        with patch('studio.producer.local_gpu.subprocess.run', side_effect=OSError()):
            self.assertIsNone(local_gpu.released(result)['released'])

    def test_music_foreground_reaps_success_failure_and_capture_exception(self):
        # The live Music runtime stays closed. Its synchronous bridge owns only its
        # newly spawned foreground child; outer OwnedProcess supervises the group.
        for code, expected in (('pass', 0), ('raise SystemExit(2)', 2)):
            with self.subTest(code=code):
                status, _, _ = foreground([sys.executable, '-I', '-c', code], {}, None)
                self.assertEqual(status, expected)
        spawned = []
        original = subprocess.Popen
        def record(*args, **kwargs):
            child = original(*args, **kwargs)
            spawned.append(child)
            return child
        with patch('studio.producer.music.bridge.subprocess.Popen', side_effect=record), \
                patch('studio.producer.music.bridge.CAPTURE_LIMIT', 1), self.assertRaises(Fault):
            foreground([sys.executable, '-I', '-c', 'print("bounded fake output")'], {}, None)
        self.assertIsNotNone(spawned[0].returncode)
        self.assertIsNone(incarnation(spawned[0].pid))
