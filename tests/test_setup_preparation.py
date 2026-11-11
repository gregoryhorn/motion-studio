"""Inactive activation preparation and real temporary-store lifecycle tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from studio.domain import Fault
from studio.native import setup_preparation as preparation
from studio.native.creation import policy, registration
from studio.producer import evaluation
from tests.creation_support import Context
activation_cli = importlib.import_module('tools.prepare_motion_studio_activation')

from tests.frozen_sources import require_baselines, require_history

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'dist/native/motion-studio-afc-source.zip'
HOST = Path.home() / '.hermes/hermes-agent-official'
ENTRY = ROOT / 'native-package/activation-entry.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_baselines(ARCHIVE)
        require_history(preparation.PRODUCT_BASE)
        # Frozen AFC is tested against its immutable Git source, not today's Production WIP.
        # Only manifest-listed files form this disposable fixture; no checkout/worktree is created.
        cls.source_temp = tempfile.TemporaryDirectory(prefix='motion-afc-source-fixture-')
        cls.addClassCleanup(cls.source_temp.cleanup)
        cls.source = Path(cls.source_temp.name)
        with zipfile.ZipFile(ARCHIVE) as archive:
            manifest = json.loads(archive.read('motion-studio/SOURCE.json'))
        for name, digest in manifest.items():
            data = subprocess.check_output(['git', '-C', str(ROOT), 'show', preparation.PRODUCT_BASE+':'+name])
            if hashlib.sha256(data).hexdigest() != digest:
                raise AssertionError('Frozen package/Git source identity mismatch: '+name)
            target = cls.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = {}
        self.pins = {}
        for name in ('wrapper', 'model'):
            path = self.root / name
            data = ('synthetic-' + name).encode()
            path.write_bytes(data)
            self.files[name] = data
            self.pins[str(path)] = hashlib.sha256(data).hexdigest()
        self.versions = {'pydantic': '2.14.1', 'fastapi': '0.133.1'}

    def plan(self, **kwargs):
        return preparation.prepare(ARCHIVE, self.source, HOST, ENTRY, generator_pins=self.pins,
                                   dependency_inspector=self.versions.__getitem__, **kwargs)

    def test_deterministic_inactive_artifacts_and_existing_target_preservation(self):
        first, second = self.plan(), self.plan()
        self.assertEqual(first, second)
        self.assertTrue(first['ready'])
        self.assertFalse(first['apply_implemented'])
        self.assertFalse(first['approval']['granted_by_this_artifact'])
        self.assertTrue(first['approval']['exact_bundle_may_use_one_explicit_approval'])
        self.assertEqual(first['dependencies']['python_plugin']['interpreter']['executable'], preparation.sys.executable)
        self.assertEqual(first['package']['sha256'], preparation.PACKAGE_SHA256)
        self.assertEqual(first['combined_tree']['count'], 73)
        self.assertEqual(first['server_entry']['target'], '__init__.py')
        self.assertNotIn('Association', (ARCHIVE.parent / 'never-created').name)
        one, two = self.root / 'one', self.root / 'two'
        preparation.write_preparation(first, ENTRY, one, self.root)
        preparation.write_preparation(second, ENTRY, two, self.root)
        self.assertEqual({p.name: p.read_bytes() for p in one.iterdir()},
                         {p.name: p.read_bytes() for p in two.iterdir()})
        self.assertEqual((one / 'combined-tree.json').read_bytes(),
                         preparation.encoded(first['combined_tree']['files']))
        rendered = (one / 'activation-plan.md').read_text()
        self.assertIn('One explicit approval may cover the exact foreseeable A1-A7 bundle', rendered)
        self.assertIn('memory-provider on_profile_created callback', rendered)
        self.assertIn('notify a live default multiplexer', rendered)
        self.assertIn('register an s6 service without starting it', rendered)
        self.assertIn('Approval also covers immediate A5 register/bootstrap', rendered)
        before = {p.name: sha(p) for p in one.iterdir()}
        with self.assertRaises(FileExistsError):
            preparation.write_preparation(first, ENTRY, one, self.root)
        self.assertEqual(before, {p.name: sha(p) for p in one.iterdir()})
        self.assertEqual({name: path.read_bytes() for name, path in
                          (('wrapper', self.root / 'wrapper'), ('model', self.root / 'model'))}, self.files)

    def test_cli_rejects_traversal_before_preparation(self):
        output = ROOT / 'dist/setup/../../activation-cli-escape-must-not-exist'
        arguments = ['prepare', '--host-source', '/unused', '--output', str(output)]
        with patch.object(sys, 'argv', arguments), patch.object(activation_cli, 'prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'traversal'):
                activation_cli.main()
        prepare.assert_not_called()
        self.assertFalse((ROOT / 'activation-cli-escape-must-not-exist').exists())

    def test_output_traversal_and_symlink_ancestry_preserve_external_targets(self):
        allowed = self.root / 'allowed'
        external = self.root / 'external'
        allowed.mkdir()
        external.mkdir()
        sentinel = external / 'sentinel.txt'
        sentinel.write_text('preserved')
        plan = self.plan()
        for target in (allowed / '..' / 'external', allowed / '..' / 'outside-created'):
            with self.assertRaisesRegex(ValueError, 'traversal'):
                preparation.write_preparation(plan, ENTRY, target, allowed)
        (allowed / 'link').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink ancestry'):
            preparation.write_preparation(plan, ENTRY, allowed / 'link' / 'created', allowed)
        self.assertFalse((self.root / 'outside-created').exists())
        self.assertFalse((external / 'created').exists())
        self.assertEqual(sentinel.read_text(), 'preserved')
        self.assertEqual(list(allowed.iterdir()), [allowed / 'link'])

    def test_relative_output_rejects_symlinked_allowed_root_without_external_mutation(self):
        external = self.root / 'external'
        external.mkdir()
        sentinel = external / 'sentinel.txt'
        sentinel.write_text('preserved')
        linked_root = self.root / 'linked-root'
        linked_root.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Allowed root symlink ancestry'):
            preparation.write_preparation(self.plan(), ENTRY, Path('relative-output'), linked_root)
        self.assertFalse((external / 'relative-output').exists())
        self.assertEqual(sentinel.read_text(), 'preserved')
        self.assertEqual(list(external.iterdir()), [sentinel])

    def test_relative_output_rejects_symlinked_allowed_root_ancestor(self):
        external = self.root / 'external'
        external_setup = external / 'setup'
        external_setup.mkdir(parents=True)
        sentinel = external / 'sentinel.txt'
        sentinel.write_text('preserved')
        linked_ancestor = self.root / 'linked-ancestor'
        linked_ancestor.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Allowed root symlink ancestry'):
            preparation.write_preparation(self.plan(), ENTRY, Path('relative-output'),
                                          linked_ancestor / 'setup')
        self.assertFalse((external_setup / 'relative-output').exists())
        self.assertEqual(sentinel.read_text(), 'preserved')
        self.assertEqual(list(external_setup.iterdir()), [])

    def test_overlay_change_between_prepare_and_write_creates_no_output(self):
        entry = self.root / 'entry.py'
        entry.write_bytes(ENTRY.read_bytes())
        plan = preparation.prepare(ARCHIVE, self.source, HOST, entry, generator_pins=self.pins,
                                   dependency_inspector=self.versions.__getitem__)
        entry.write_bytes(entry.read_bytes() + b'\n# changed after review\n')
        output = self.root / 'changed-output'
        with self.assertRaisesRegex(ValueError, 'SERVER_ENTRY_CHANGED_BETWEEN_PREPARE_AND_WRITE'):
            preparation.write_preparation(plan, entry, output, self.root)
        self.assertFalse(output.exists())

    def test_wrong_package_source_host_and_default_entry_refuse(self):
        changed = self.root / 'changed.zip'
        changed.write_bytes(ARCHIVE.read_bytes() + b'x')
        with self.assertRaisesRegex(ValueError, 'PACKAGE_PIN_MISMATCH'):
            preparation.prepare(changed, self.source, HOST, ENTRY, generator_pins=self.pins,
                                dependency_inspector=self.versions.__getitem__)
        with patch('studio.native.setup_preparation.check_content', side_effect=ValueError('PRIVATE_CONTENT')):
            with self.assertRaisesRegex(ValueError, 'PRIVATE_CONTENT'):
                self.plan()
        with patch('studio.native.setup_preparation.host_contract', return_value={'commit': 'wrong'}):
            with self.assertRaisesRegex(ValueError, 'HOST_INTERFACE_MISMATCH'):
                self.plan()
        with patch('studio.native.setup_preparation.host_contract', side_effect=ValueError('HOST_PIN_CHANGED')):
            with self.assertRaisesRegex(ValueError, 'HOST_PIN_CHANGED'):
                self.plan()

    def test_missing_dependency_and_changed_generator_pin_block_activation(self):
        def missing(name):
            if name == 'fastapi':
                raise preparation.importlib.metadata.PackageNotFoundError(name)
            return self.versions[name]
        blocked = preparation.prepare(ARCHIVE, self.source, HOST, ENTRY, generator_pins=self.pins,
                                      dependency_inspector=missing)
        self.assertFalse(blocked['ready'])
        self.assertFalse(blocked['dependencies']['python_plugin']['ready'])
        changed = self.root / 'model'
        changed.write_bytes(b'changed')
        blocked = self.plan()
        self.assertFalse(blocked['ready'])
        self.assertFalse(blocked['dependencies']['local_generator']['ready'])
        self.assertIn('Ready: False', preparation.render(blocked))


    def test_frozen_source_integrity_still_rejects_changed_fixture(self):
        target = self.source / 'native-package/__init__.py'
        original = target.read_bytes()
        try:
            target.write_bytes(original+b'\n# controlled source drift\n')
            with self.assertRaisesRegex(ValueError, 'PRODUCT_SOURCE_MISMATCH'):
                self.plan()
        finally:
            target.write_bytes(original)


class ActivationEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location('motion_studio_activation_entry_test', ENTRY)
        assert spec and spec.loader
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.contexts = []

    def context(self, profile='motion-studio'):
        ctx = Context(self.root / 'plugin-data')
        ctx.profile_name = profile
        self.contexts.append(ctx)
        return ctx

    def register(self, ctx):
        technical = type('Technical', (), {'register': staticmethod(lambda _ctx: type('Runtime', (), {})())})
        modules = {
            '.studio.native.creation.policy': policy,
            '.studio.native.technical.registration': technical,
            '.studio.native.creation.registration': registration,
            '.studio.producer.evaluation': evaluation,
        }
        with patch.object(self.module, 'import_module', side_effect=lambda name, _package: modules[name]), \
                patch.object(evaluation.sfx, 'check_pins', return_value=None):
            return self.module.register(ctx)

    def test_fresh_store_records_generated_identity_and_fixed_binding_across_reload(self):
        first = self.register(self.context())
        record_path = self.root / 'plugin-data/creation-activation.json'
        record = json.loads(record_path.read_text())
        self.assertEqual(record['instance'], first.creation.instance)
        self.assertEqual(record['binding_revision'], 2)
        self.assertTrue(first.creation.binding()['enabled'])
        self.assertEqual(record_path.stat().st_mode & 0o077, 0)
        original = record_path.read_bytes()
        first.creation.unload()
        second = self.register(self.context())
        self.assertEqual(second.creation.instance, record['instance'])
        self.assertEqual(second.creation.policy.binding, record['binding'])
        self.assertEqual(second.creation.policy.binding_revision, 2)
        self.assertFalse(second.creation.policy.create_store)
        self.assertEqual(record_path.read_bytes(), original)
        self.assertEqual(list((self.root / 'plugin-data/media/media').iterdir()), [])
        self.assertEqual(list(self.root.rglob('*.wav')), [])

    def test_wrong_profile_instance_and_binding_revision_refuse_without_rewrite(self):
        first = self.register(self.context())
        first.creation.unload()
        path = self.root / 'plugin-data/creation-activation.json'
        original = json.loads(path.read_text())
        with self.assertRaises(Fault) as denied:
            self.register(self.context('wrong-profile'))
        self.assertEqual(denied.exception.code, 'CREATION_ACCESS_UNAVAILABLE')
        self.assertEqual(json.loads(path.read_text()), original)
        for field, value in (('instance', 'b' * 32), ('binding_revision', 1)):
            changed = dict(original, **{field: value})
            path.write_text(json.dumps(changed))
            with self.assertRaises((Fault, ValueError)):
                self.register(self.context())
            self.assertEqual(json.loads(path.read_text()), changed)
            path.write_text(json.dumps(original))

    def test_existing_unrecorded_store_stops_for_same_target_reconciliation(self):
        media = self.root / 'plugin-data/media'
        media.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'ACTIVATION_RECONCILE_SAME_STORE'):
            self.register(self.context())
        self.assertTrue(media.is_dir())
        self.assertEqual(list(media.iterdir()), [])
        self.assertFalse((self.root / 'plugin-data/creation-activation.json').exists())


if __name__ == '__main__':
    unittest.main()
