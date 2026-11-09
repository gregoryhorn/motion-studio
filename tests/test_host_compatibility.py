"""Deferred host-lock checks. Fixtures never modify an installed Hermes host."""
import copy
import hashlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from typing import Any
from unittest.mock import patch

from studio import host_compatibility
from studio.contracts import ContractError


class HostLockTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch')))
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / '.git').mkdir()
        self.revision = 'a' * 40
        (self.root / '.git/HEAD').write_text(self.revision + '\n', encoding='ascii')
        (self.root / 'hermes_cli').mkdir()
        self.api = self.root / 'hermes_cli/fixture.py'
        self.api.write_bytes(b'# Explicit fixture, not host code.\n')
        self.lock: dict[str, Any] = dict(schema='motion/hermes-host-lock/v1', revision=self.revision,
                         version_label='fixture-only', files={
                             'hermes_cli/fixture.py': hashlib.sha256(self.api.read_bytes()).hexdigest()})
        self.loader = patch.object(host_compatibility, '_load_lock', return_value=self.lock)
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def reject(self):
        with self.assertRaises(ContractError) as caught:
            host_compatibility.assert_supported_host(self.root)
        self.assertEqual(caught.exception.code, 'HOST_VERSION_UNSUPPORTED')

    def test_matching_revision_and_api_bytes_admitted(self):
        result = host_compatibility.assert_supported_host(self.root)
        self.assertEqual(result, {'revision': self.revision, 'version_label': 'fixture-only'})

    def test_changed_revision_rejected(self):
        (self.root / '.git/HEAD').write_text('b' * 40, encoding='ascii')
        self.reject()

    def test_dirty_consumed_api_rejected(self):
        self.api.write_bytes(b'# Different fixture implementation\n')
        self.reject()

    def test_missing_api_rejected(self):
        self.api.unlink()
        self.reject()

    def test_loose_and_packed_references(self):
        git = self.root / '.git'
        (git / 'HEAD').write_text('ref: refs/heads/main\n', encoding='ascii')
        (git / 'refs/heads').mkdir(parents=True)
        (git / 'refs/heads/main').write_text(self.revision, encoding='ascii')
        host_compatibility.assert_supported_host(self.root)
        (git / 'refs/heads/main').unlink()
        (git / 'packed-refs').write_text(self.revision + ' refs/heads/main\n', encoding='ascii')
        host_compatibility.assert_supported_host(self.root)

    def test_path_escape_in_lock_is_rejected(self):
        expected = next(iter(self.lock['files'].values()))
        self.lock['files'] = {'../outside.py': expected}
        self.reject()

    def test_invalid_revision_is_not_normalized(self):
        self.lock['revision'] = 'G' * 40
        self.reject()

    def test_host_update_during_admission_is_rejected(self):
        with patch.object(host_compatibility, '_revision', side_effect=[self.revision, 'b' * 40]):
            self.reject()

    def test_absent_git_identity_is_not_guessed_from_label(self):
        (self.root / '.git/HEAD').unlink()
        self.reject()


PYTHON_FILES = (
    'hermes_cli/projects_db.py', 'hermes_cli/plugin_host_http_auth.py',
    'hermes_cli/plugin_session.py', 'gateway/owner_identity.py',
    'gateway/session_context.py', 'hermes_constants.py',
    'hermes_cli/web_server_plugin_profiles.py', 'hermes_cli/web_server_dashboard.py',
)
SDK_FILES = ('apps/desktop/src/sdk/index.ts', 'apps/desktop/src/sdk/composer.ts')


class ManagedRuntimeTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch')))
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.revision = 'a' * 40
        files = {}
        for name in PYTHON_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('raise AssertionError("must not import qualification fixtures")\n')
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ('hermes_cli', 'gateway'):
            (self.root / name / '__init__.py').write_text('raise AssertionError("no parent import")\n')
        self.lock = {
            'schema': 'motion/hermes-host-lock/v2',
            'reference_revision': self.revision,
            'version_label': 'fixture-only',
            'checkout': {'files': {**files, **{name: 'b' * 64 for name in SDK_FILES}}},
            'managed_runtime': {'admission': 'qualified-api-source-bytes', 'files': files},
            'desktop_sdk': {'status': 'unverified-client',
                            'files': {name: 'b' * 64 for name in SDK_FILES}},
        }
        self.loader = patch.object(host_compatibility, '_load_lock', return_value=self.lock)
        self.loader.start()
        self.addCleanup(self.loader.stop)
        # Use real import discovery, but never import any fixture module.
        self.paths = patch.object(sys, 'path', [str(self.root), *sys.path])
        self.paths.start()
        self.addCleanup(self.paths.stop)
        names = {name[:-3].replace('/', '.') for name in PYTHON_FILES} | {'hermes_cli', 'gateway'}
        self.saved_modules = {name: sys.modules.pop(name) for name in names if name in sys.modules}
        self.addCleanup(self.restore_modules, names)

    def restore_modules(self, names):
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(self.saved_modules)

    def reject(self, *, default=False):
        with self.assertRaises(ContractError) as caught:
            host_compatibility.assert_supported_host() if default else host_compatibility.assert_supported_host(self.root)
        self.assertEqual(caught.exception.code, 'HOST_VERSION_UNSUPPORTED')

    def test_managed_runtime_admits_python_without_git_or_desktop(self):
        result = host_compatibility.assert_supported_host(self.root)
        self.assertEqual(result['admission'], 'qualified-api-source-bytes')
        self.assertEqual(result['reference_revision'], self.revision)
        self.assertNotIn('revision', result)  # Not an observed runtime Git revision.
        self.assertEqual(result['desktop_sdk'], 'unverified-client')

    def test_default_checks_real_specs_without_importing_modules(self):
        result = host_compatibility.assert_supported_host()
        self.assertEqual(result['admission'], 'qualified-api-source-bytes')
        self.assertNotIn('hermes_cli', sys.modules)
        self.assertNotIn('gateway.owner_identity', sys.modules)

    def test_tampered_python_is_rejected(self):
        (self.root / PYTHON_FILES[0]).write_text('# tampered\n')
        self.reject()

    def test_missing_python_is_not_skipped_with_desktop(self):
        (self.root / PYTHON_FILES[0]).unlink()
        self.reject()

    def test_checkout_requires_revision_and_desktop_bytes(self):
        (self.root / '.git').mkdir()
        (self.root / '.git/HEAD').write_text(self.revision)
        self.reject()  # Desktop files are absent: no runtime-mode downgrade.
        for name in SDK_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'// fixture\n')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.lock['checkout']['files'][name] = digest
            self.lock['desktop_sdk']['files'][name] = digest
        result = host_compatibility.assert_supported_host(self.root)
        self.assertEqual(result['revision'], self.revision)
        (self.root / '.git/HEAD').write_text('c' * 40)
        self.reject()

    def test_loaded_foreign_origin_is_rejected(self):
        name = 'hermes_cli.projects_db'
        module = ModuleType(name)
        foreign = self.root / 'foreign.py'
        foreign.write_bytes((self.root / PYTHON_FILES[0]).read_bytes())
        module.__spec__ = importlib.util.spec_from_file_location(name, foreign)
        module.__file__ = str(foreign)
        assert module.__spec__ is not None
        module.__loader__ = module.__spec__.loader
        sys.modules[name] = module
        self.reject(default=True)

    def test_loaded_file_disagrees_with_spec_is_rejected(self):
        name = 'hermes_cli.projects_db'
        module = ModuleType(name)
        module.__spec__ = importlib.util.spec_from_file_location(name, self.root / PYTHON_FILES[0])
        module.__file__ = str(self.root / 'foreign.py')
        assert module.__spec__ is not None
        module.__loader__ = module.__spec__.loader
        sys.modules[name] = module
        self.reject(default=True)

    def test_foreign_parent_search_path_is_rejected(self):
        package = ModuleType('gateway')
        package.__spec__ = importlib.util.spec_from_file_location('gateway', self.root / 'gateway/__init__.py')
        package.__file__ = str(self.root / 'gateway/__init__.py')
        assert package.__spec__ is not None
        package.__loader__ = package.__spec__.loader
        package.__path__ = [str(self.root / 'hermes_cli')]
        sys.modules['gateway'] = package
        self.reject(default=True)

    def test_non_source_loader_is_rejected(self):
        name = 'hermes_cli.projects_db'
        module = ModuleType(name)
        module.__spec__ = importlib.machinery.ModuleSpec(name, None, origin=str(self.root / PYTHON_FILES[0]))
        module.__file__ = str(self.root / PYTHON_FILES[0])
        sys.modules[name] = module
        self.reject(default=True)

    def test_symlink_escape_is_rejected_even_when_bytes_match(self):
        target = self.root / PYTHON_FILES[0]
        outside = self.root.parent / (self.root.name + '-outside.py')
        self.addCleanup(outside.unlink)
        outside.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(outside)
        self.reject()

    def test_invalid_schema_fails_closed(self):
        original = copy.deepcopy(self.lock)
        mutations = [
            lambda lock: lock.update(schema='motion/hermes-host-lock/v3'),
            lambda lock: lock.update(reference_revision='A' * 40),
            lambda lock: lock.update(unexpected=True),
            lambda lock: lock.update(version_label=None),
            lambda lock: lock['managed_runtime'].update(admission='any-source'),
            lambda lock: lock['managed_runtime']['files'].pop(PYTHON_FILES[0]),
            lambda lock: lock['managed_runtime']['files'].update({'../escape.py': 'b' * 64}),
            lambda lock: lock['managed_runtime']['files'].update({PYTHON_FILES[0]: 42}),
            lambda lock: lock['desktop_sdk'].update(status='verified'),
            lambda lock: lock['desktop_sdk']['files'].clear(),
            lambda lock: lock['checkout']['files'].update({PYTHON_FILES[0]: 'c' * 64}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.lock.clear()
                self.lock.update(copy.deepcopy(original))
                mutate(self.lock)
                self.reject()

    def test_file_changed_after_hash_before_return_is_rejected(self):
        original = hashlib.sha256
        calls = 0

        def checksum(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == len(PYTHON_FILES):
                (self.root / PYTHON_FILES[0]).write_text('# changed after earlier hash\n')
            return original(*args, **kwargs)

        with patch.object(host_compatibility.hashlib, 'sha256', side_effect=checksum):
            self.reject()

    def test_matching_loaded_source_origin_is_admitted(self):
        name = 'hermes_cli.projects_db'
        module = ModuleType(name)
        module.__spec__ = importlib.util.spec_from_file_location(name, self.root / PYTHON_FILES[0])
        assert module.__spec__ is not None
        module.__file__ = module.__spec__.origin
        module.__loader__ = module.__spec__.loader
        sys.modules[name] = module
        self.assertEqual(host_compatibility.assert_supported_host()['admission'],
                         'qualified-api-source-bytes')

    def test_foreign_unloaded_module_spec_is_rejected(self):
        name = 'hermes_cli.projects_db'
        foreign = self.root / 'foreign.py'
        foreign.write_bytes((self.root / PYTHON_FILES[0]).read_bytes())

        class ForeignFinder:
            @staticmethod
            def find_spec(fullname, path=None, target=None):
                if fullname == name:
                    return importlib.util.spec_from_file_location(name, foreign)
                return None

        with patch.object(sys, 'meta_path', [ForeignFinder(), *sys.meta_path]):
            self.reject(default=True)

    def test_git_appearing_during_runtime_admission_is_rejected(self):
        original = hashlib.sha256

        def checksum(*args, **kwargs):
            (self.root / '.git').mkdir(exist_ok=True)
            return original(*args, **kwargs)

        with patch.object(host_compatibility.hashlib, 'sha256', side_effect=checksum):
            self.reject()

    def test_duplicate_json_fields_rejected(self):
        with patch.object(Path, 'read_text', return_value='{"schema": 1, "schema": 2}'):
            with self.assertRaises(ValueError):
                self.loader.stop()
                try:
                    host_compatibility._load_lock()
                finally:
                    self.loader.start()
