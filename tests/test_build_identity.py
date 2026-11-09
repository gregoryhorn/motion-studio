"""Development identity is observable without treating disk parity as activation."""
import os
import hashlib
from pathlib import Path
import tempfile
import unittest

from studio.ui_service import UIService
from studio.build_identity import capture_identity, frontend_source_sha256, runtime_identity


class BuildIdentityTests(unittest.TestCase):
    def test_bootstrap_reports_import_snapshot_and_expected_frontend(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            service = UIService(Path(tmp) / 'studio', lambda: [],
                                profile_id='fixture', backend_instance_id='fixture-backend')
            status, response = service.handle('GET', '/bootstrap', query={
                'client_contract': 'ui.v1', 'client_kind': 'desktop'})
        self.assertEqual(status, 200, response)
        identity = response['data'].get('runtime_identity')
        self.assertIsInstance(identity, dict, 'Bootstrap must expose loaded build identity')
        self.assertEqual(identity['schema'], 'motion/runtime-identity/v1')
        self.assertEqual(identity['observation'], 'module_import_snapshot')
        self.assertRegex(identity['manifest_sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(identity['frontend_source_sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(identity['backend_source_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(identity['frontend_hash_algorithm'], 'motion/import-normalized-sha256/v1')
        self.assertNotIn('source_revision', identity, 'A manifest is not Git provenance')
        self.assertNotIn(str(Path.cwd()), str(identity), 'Public identity must not expose host paths')

    def test_fingerprint_matches_client_import_normalization_contract(self):
        source = "import { host } from '@hermes/plugin-sdk';\nimport { useState } from 'react';\nconst x = 1;\n"
        expected = hashlib.sha256(b'import { host } from "<host-import>";\nimport { useState } from "<host-import>";\nconst x = 1;\n').hexdigest()
        self.assertEqual(frontend_source_sha256(source), expected)
        self.assertEqual(frontend_source_sha256(source.replace('\n', '\r\n')), expected)
        self.assertNotEqual(frontend_source_sha256(source.replace('x = 1', 'x = 2')), expected)

    def test_import_snapshot_is_not_relabelled_after_disk_changes(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            root = Path(tmp)
            (root / 'studio').mkdir()
            (root / 'desktop').mkdir()
            (root / '__init__.py').write_text('# Fixture package\n')
            (root / 'studio/source.py').write_text('value = 1\n')
            (root / 'desktop/plugin.js').write_text('const value = 1;\n')
            (root / 'studio-manifest.json').write_text('{}')
            loaded = capture_identity(root)
            (root / 'studio/source.py').write_text('value = 2\n')
            (root / 'desktop/plugin.js').write_text('const value = 2;\n')
            changed = capture_identity(root)
            self.assertNotEqual(loaded['backend_source_sha256'], changed['backend_source_sha256'])
            self.assertNotEqual(loaded['frontend_source_sha256'], changed['frontend_source_sha256'])
            self.assertEqual(loaded['observation'], 'module_import_snapshot')
        result = runtime_identity()
        result['manifest_sha256'] = 'caller-mutated'
        self.assertNotEqual(runtime_identity()['manifest_sha256'], 'caller-mutated')
