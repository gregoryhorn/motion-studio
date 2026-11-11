"""Actual proc metadata: absent leader is not proof of group retirement."""
from pathlib import Path
import subprocess
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from studio.runs.owned_process import incarnation
from studio.runs.process_observation import snapshot, retirement
from studio.runs.helper_environment import helper_environment


class ProcessObservationTests(unittest.TestCase):
    def test_retirement_requires_consecutive_clear_scans_after_settlement(self):
        scans = [dict(retired=value) for value in (False, True, False, True, True)]
        with patch('studio.runs.process_observation.snapshot', side_effect=scans) as observe, \
                patch('studio.runs.process_observation.time.sleep'):
            retired, facts = retirement({'synthetic': True})
        self.assertTrue(retired)
        self.assertEqual(observe.call_count, 5)
        self.assertEqual(facts, scans[-2:])

    def test_retirement_never_accepts_a_persistent_survivor_or_scan_error(self):
        with patch('studio.runs.process_observation.snapshot', return_value=dict(retired=False)) as observe, \
                patch('studio.runs.process_observation.time.sleep'):
            retired, facts = retirement({'synthetic': True})
        self.assertFalse(retired)
        self.assertEqual(observe.call_count, 10)
        self.assertEqual(facts, [dict(retired=False)] * 2)

    def test_actual_survivor_then_retirement_without_adoption_or_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('group_fixture_child.py')), str(root)],
                start_new_session=True, env=helper_environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                end = time.monotonic() + 2
                while not (root / 'ready').exists() and time.monotonic() < end:
                    time.sleep(0.005)
                self.assertTrue((root / 'ready').exists())
                pin = incarnation(child.pid)
                assert pin is not None
                (root / 'release').write_text('CONTROLLED')
                child.wait(timeout=3)
                facts = snapshot(pin)
                self.assertIsNone(facts['leader'])
                self.assertFalse(facts['retired'])
                self.assertTrue(any(v['state'] not in ('Z','X') for v in facts['members']))
                (root / 'finish').write_text('CONTROLLED')
                end = time.monotonic() + 3
                while not snapshot(pin)['retired'] and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertTrue(retirement(pin)[0])
                reused = dict(pin, pid=os.getpid())
                self.assertFalse(snapshot(reused)['retired'])
                wrong_boot = dict(pin, boot='controlled-other-boot')
                self.assertFalse(snapshot(wrong_boot)['retired'])
                with patch('studio.runs.process_observation.MAX_PROCESSES', 0):
                    self.assertFalse(snapshot(pin)['retired'])
            finally:
                (root / 'release').touch()
                (root / 'finish').touch()
                child.wait(timeout=4)
