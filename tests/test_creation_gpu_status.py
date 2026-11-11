"""Persisted GPU etiquette observations cross Creation tool/RPC boundaries; no GPU calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.creation_support import setup, effects


class CreationGPUStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.ctx, self.runtime, self.binding = setup(Path(temporary.name))
        self.addCleanup(self.runtime.unload)
        self.rpc('admit')

    def rpc(self, operation, payload=None, root='gpu-fixture-root'):
        return self.ctx.methods['creation.' + operation](payload or {}, session_id=root)

    def tool(self, operation, **payload):
        handler = self.ctx.tools['motion_studio_creation'][1]
        return json.loads(handler(dict(operation=operation, **payload),
                                  session_id='fixture-session', conversation_id='gpu-fixture-root'))

    def test_status_and_list_pass_through_persisted_gpu_observations(self):
        # Prepare only: no producer launch, device query or synthetic media generation.
        prepared = self.tool('prepare', direction='Controlled GPU status fixture')
        self.assertNotIn('error', prepared)
        busy = dict(free_mib=1024, required_mib=8192,
                    processes=[dict(name='fixture-model', used_mib=7000)])
        releases = [None, dict(owned_process_gone=True, released=True),
                    dict(owned_process_gone=False, released=False),
                    dict(owned_process_gone=True, released=None,
                         error='RESOURCE_OBSERVATION_UNAVAILABLE')]
        with patch('subprocess.Popen', side_effect=AssertionError('No launch')), \
                patch('studio.producer.local_gpu.subprocess.run', side_effect=AssertionError('No GPU query')):
            for release in releases:
                with self.subTest(release=release):
                    self.runtime.runs.records.update(prepared['run'],
                        process=dict(local_gpu_busy=busy, local_gpu_release=release))
                    public = self.runtime.runs.records.public(prepared['run'])
                    responses = [self.tool('status', request=prepared['request']),
                                 self.tool('status'),
                                 self.rpc('status', dict(request=prepared['request'])),
                                 self.rpc('list')['creations'][0]]
                    for result in responses:
                        self.assertEqual(result['local_gpu_busy'], public['local_gpu_busy'])
                        self.assertEqual(result['local_gpu_release'], public['local_gpu_release'])
                    self.assertEqual(public['local_gpu_busy'], busy)
                    self.assertEqual(public['local_gpu_release'], release)
        self.assertEqual(effects(self.binding), [])

    def test_absent_observations_are_null_and_foreign_scope_stays_denied(self):
        row = self.tool('prepare', direction='Controlled empty observation fixture')
        for result in (row, self.tool('status'), self.rpc('list')['creations'][0]):
            self.assertIsNone(result['local_gpu_busy'])
            self.assertIsNone(result['local_gpu_release'])
        self.rpc('admit', root='foreign-root')
        self.assertEqual(self.rpc('status', dict(request=row['request']), root='foreign-root')['error'],
                         'CREATION_SCOPE_DENIED')
        self.assertEqual(self.rpc('list', root='foreign-root')['creations'], [])
        self.assertEqual(effects(self.binding), [])


if __name__ == '__main__':
    unittest.main()
