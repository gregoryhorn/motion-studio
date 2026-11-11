"""Failure sensitivity and output isolation for the focused runner itself."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from tools.check_workspace_e2e import run_check, spans


class HarnessTests(unittest.TestCase):
    def test_nonzero_command_is_preserved_not_reported_as_pass(self):
        with tempfile.TemporaryDirectory(prefix='workspace-runner-', dir=os.environ.get('TMPDIR')) as temp:
            output = Path(temp)
            failed = run_check('failure', [sys.executable, '-m', 'unittest',
                'tests.workspace_e2e.intentionally_missing_test'], output)
            self.assertNotEqual(failed['exit_code'], 0)
            self.assertIn('FAILED', (output / 'failure.txt').read_text())
            passed = run_check('success', [sys.executable, '-m', 'unittest',
                'tests.workspace_e2e.test_lifecycle.WorkspaceLifecycleTests.test_cancelled_import_cannot_publish_take_or_bytes'], output)
            self.assertEqual(passed['exit_code'], 0)
            self.assertIn('OK', (output / 'success.txt').read_text())
            self.assertTrue((output / 'failure.txt').exists())

    def test_python_function_span_cap(self):
        self.assertLessEqual(spans(), 300)


if __name__ == '__main__':
    unittest.main()
