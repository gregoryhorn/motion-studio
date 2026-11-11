"""Backend placement preserves runtime state and Desktop files in a disposable profile."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.install_current_production_backend import install


class CurrentBackendInstallTests(unittest.TestCase):
    def test_code_backup_and_backend_only_install(self):
        with tempfile.TemporaryDirectory() as home:
            profile = Path(home)
            target = profile / 'plugins/motion-studio'
            (target / 'desktop').mkdir(parents=True)
            (target / 'desktop/plugin.js').write_text('held desktop')
            (target / '__init__.py').write_text('old entry')
            state = profile / 'plugin_data/media/state/studio.db'
            state.parent.mkdir(parents=True)
            state.write_bytes(b'preserved runtime state')
            archive = profile / 'current.zip'
            names = ('studio/native/production/media.py', 'studio/native/production/registration.py',
                     'studio/media_import/service.py', 'studio/production_export/service.py')
            with zipfile.ZipFile(archive, 'w') as bundle:
                for name in names:
                    bundle.writestr('motion-studio/' + name, '"""controlled code"""\n')
                bundle.writestr('motion-studio/desktop/plugin.js', 'not installed')
            result = install(archive, profile=profile)
            self.assertEqual((Path(str(result['backup'])) / '__init__.py').read_text(), 'old entry')
            self.assertEqual((target / 'desktop/plugin.js').read_text(), 'held desktop')
            self.assertEqual(state.read_bytes(), b'preserved runtime state')
            self.assertIn('production-integrated-backend-r1', (target / '__init__.py').read_text())
            self.assertFalse(result['runtime_state_copied'])

    def test_unintegrated_archive_denied_without_writes(self):
        with tempfile.TemporaryDirectory() as home:
            profile = Path(home)
            target = profile / 'plugins/motion-studio'
            target.mkdir(parents=True)
            archive = profile / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('motion-studio/__init__.py', '')
            with self.assertRaisesRegex(ValueError, 'INTEGRATED_BACKEND_REQUIRED'):
                install(archive, profile=profile)
            self.assertFalse((profile / 'development-backups').exists())
