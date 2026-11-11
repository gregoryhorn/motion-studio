"""Helper environment regressions using only controlled, harmless sentinel values."""
import os
import subprocess
import unittest
from unittest.mock import patch
from studio.producer.live_sfx import resources
from studio.runs.helper_environment import helper_environment

SENTINELS = {key:'harmless-test-sentinel' for key in (
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'UNKNOWN_PROVIDER_TOKEN', 'PYTHONPATH',
    'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')}


class HelperEnvironmentTests(unittest.TestCase):
    def test_observation_dispatch_has_explicit_fixed_environment(self):
        observations = [subprocess.CompletedProcess([], 0, '9000\n', ''),
                        subprocess.CompletedProcess([], 0, '', '')]
        with patch.dict(os.environ, SENTINELS, clear=True), \
             patch('studio.producer.live_sfx.subprocess.run', side_effect=observations) as dispatch:
            self.assertEqual(resources(), (9000, False))
            self.assertEqual(dispatch.call_count, 2)
            for call in dispatch.call_args_list:
                self.assertEqual(call.args[0][0], '/usr/bin/nvidia-smi')
                self.assertEqual(call.kwargs['env'], {'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'})
                self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)
                self.assertEqual(call.kwargs['timeout'], 5)
                self.assertTrue(set(SENTINELS).isdisjoint(call.kwargs['env']))
        first = helper_environment()
        first['UNSAFE'] = 'controlled mutation'
        self.assertNotIn('UNSAFE', helper_environment())
