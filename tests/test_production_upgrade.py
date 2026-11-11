"""Offline old ZIP -> exact overlay -> reload -> old ZIP, using disposable state only."""
from dataclasses import replace
import base64
import importlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import unittest
from typing import Any, cast
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

import tools.prepare_production_upgrade as upgrade
from tests.test_native_package import FakeRemoteRuntime, HOST
from tests.producer_support import fixture_binding, effects

from tests.frozen_sources import require_baselines, require_history

ROOT = upgrade.ROOT
OLD = ROOT / 'dist/native/motion-studio-afc-source.zip'


class FrozenSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_baselines(upgrade.ARCHIVE)
        require_history('2eea2e37f46d9310bf0518b196885ac532bd4c83')
        # Exact manifest-listed Git bytes only, not a checkout/worktree.
        cls.source_temp = tempfile.TemporaryDirectory(prefix='motion-production-source-fixture-')
        cls.addClassCleanup(cls.source_temp.cleanup)
        cls.source = Path(cls.source_temp.name)
        with zipfile.ZipFile(upgrade.ARCHIVE) as archive:
            sources = json.loads(archive.read('motion-studio/SOURCE.json'))
        for name, digest in sources.items():
            data = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                '2eea2e37f46d9310bf0518b196885ac532bd4c83:'+name])
            if upgrade.sha(data) != digest:
                raise AssertionError('Frozen Production package/Git identity mismatch: '+name)
            target = cls.source/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


class BundleTests(FrozenSourceTests):
    def test_future_source_is_not_accepted_by_frozen_preparer(self):
        with self.assertRaisesRegex(ValueError, 'PRODUCT_SOURCE_MISMATCH'):
            upgrade.prepare()

    def test_cli_resolves_relative_output_from_checkout_and_rejects_escape(self):
        with patch.object(sys, 'argv', ['prepare', '--output', 'dist/setup/cli-fixture']), \
                patch.object(upgrade, 'write', return_value={}) as write, patch('builtins.print'):
            upgrade.main()
        self.assertEqual(write.call_args.args[0], ROOT/'dist/setup/cli-fixture')
        with patch.object(sys, 'argv', ['prepare', '--output', 'dist/setup/../../escape']), \
                patch.object(upgrade, 'prepare') as prepare:
            with self.assertRaises(ValueError): upgrade.main()
        prepare.assert_not_called()

    def test_reproduction_exact_tree_and_overlay_only(self):
        first, second = upgrade.prepare(checkout=self.source), upgrade.prepare(checkout=self.source)
        self.assertEqual(first, second)
        with zipfile.ZipFile(io.BytesIO(first['combined-tree.zip'])) as archive:
            combined = {n.removeprefix('motion-studio/'): archive.read(n) for n in archive.namelist()}
        original = upgrade.inspect(upgrade.ARCHIVE, self.source, HOST)
        self.assertEqual([k for k in original if original[k] != combined[k]], ['__init__.py'])
        self.assertEqual(json.loads(first['combined-tree.json']), upgrade.manifest(combined))
        self.assertEqual(len(combined), 84)
        self.assertEqual(len(json.loads(first['desktop-tree.json'])), 12)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upgrade.write(root/'one', root, checkout=self.source)
            upgrade.write(root/'two', root, checkout=self.source)
            self.assertEqual({p.name:p.read_bytes() for p in (root/'one').iterdir()},
                             {p.name:p.read_bytes() for p in (root/'two').iterdir()})
            with self.assertRaises(FileExistsError): upgrade.write(root/'one', root)
            (root/'link').symlink_to(root/'one', target_is_directory=True)
            with self.assertRaises(ValueError): upgrade.write(root/'link'/'escape', root)
            with self.assertRaises(ValueError): upgrade.write(root/'..'/'escape', root)

    def test_archive_entry_source_and_host_drift_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root/'changed.zip'; archive.write_bytes(upgrade.ARCHIVE.read_bytes()+b'x')
            entry = root/'entry.py'; entry.write_bytes(upgrade.ENTRY.read_bytes()+b'\n')
            for kwargs, error in ((dict(archive=archive), 'PACKAGE_PIN_MISMATCH'),
                                  (dict(entry=entry), 'UPGRADE_ENTRY_MISMATCH'),
                                  (dict(checkout=root), None)):
                with self.subTest(kwargs=list(kwargs)):
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        upgrade.write(root/'absent', root, **kwargs)
                    self.assertFalse((root/'absent').exists())
            with patch.object(upgrade, 'host_contract', return_value={'commit':'wrong'}):
                with self.assertRaisesRegex(ValueError, 'HOST_INTERFACE_MISMATCH'):
                    upgrade.prepare(checkout=self.source)
            # Real single-source drift, with all other source paths unchanged.
            changed = root/'source'; changed.mkdir()
            with zipfile.ZipFile(upgrade.ARCHIVE) as archive:
                sources = json.loads(archive.read('motion-studio/SOURCE.json'))
            for name in sources:
                target = changed/name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((self.source/name).read_bytes())
            (changed/'native-package/__init__.py').write_bytes(b'# drift\n')
            with self.assertRaisesRegex(ValueError, 'PRODUCT_SOURCE_MISMATCH'):
                upgrade.prepare(checkout=changed)


class SameStoreTests(FrozenSourceTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sys.path.insert(0, str(HOST))
        from hermes_cli.plugin_host_child import _import_plugin, RemotePluginContext, HostRuntime
        cls.loader = staticmethod(_import_plugin)
        cls.context_type = RemotePluginContext
        cls.host_unload = staticmethod(HostRuntime.op_unload)

    def setUp(self):
        require_baselines(OLD)
        self.temp = tempfile.TemporaryDirectory(prefix='production-upgrade-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.loads = []
        self.addCleanup(self.dispose_all)
        self.old = self.root/'old'
        with zipfile.ZipFile(OLD) as archive: archive.extractall(self.old)
        (self.old/'motion-studio/__init__.py').write_bytes((ROOT/'native-package/activation-entry.py').read_bytes())
        self.new = self.root/'new'
        outputs = upgrade.prepare(checkout=self.source)
        with zipfile.ZipFile(io.BytesIO(outputs['combined-tree.zip'])) as archive: archive.extractall(self.new)
        self.data = self.root/'data'
        self.remote, self.runtime, self.key = self.load(self.old, bootstrap=True)
        self.record_path = self.data/'creation-activation.json'
        self.record = self.record_path.read_bytes()

    def dispose(self, remote, key):
        # Run the selected host's real unload/disposal body without starting a host.
        handlers = list(remote.methods.values())
        host = SimpleNamespace(unload_callbacks=remote.unload_callbacks, _run=lambda value:value,
            _lock=threading.Lock(), refs=dict(enumerate(handlers)),
            owners={i:key for i in range(len(handlers))}, loads={key:True}, modules={key:key})
        result = self.host_unload(cast(Any, host), dict(plugin_key=key))
        self.assertEqual(result, {'errors':[]})
        self.assertEqual(host.refs, {})
        self.assertEqual(host.owners, {})
        self.assertNotIn(key, sys.modules)

    def dispose_all(self):
        for remote, key in reversed(self.loads): self.dispose(remote, key)

    def load(self, tree, bootstrap=False):
        key = 'upgrade_fixture_'+str(len(self.loads))
        remote = FakeRemoteRuntime(self.data)
        ctx = self.context_type(cast(Any, remote), key, dict(plugin_id='motion-studio', profile_name='motion-studio',
            ctx_methods=['register_rpc','register_tool','register_system_prompt_section']))
        self.loads.append((remote, key))
        module = self.loader(dict(path=str(tree/'motion-studio'), module_name=key))
        if bootstrap:
            evaluation = importlib.import_module(key+'.studio.producer.evaluation')
            with patch.object(evaluation.sfx, 'check_pins'):
                runtime = module.register(ctx)
        else:
            with patch('subprocess.Popen', side_effect=AssertionError('No generation')), \
                    patch.object(importlib.import_module(key+'.studio.producer.evaluation'),
                                 'enable_evaluation', side_effect=AssertionError('No bootstrap')):
                runtime = module.register(ctx)
        return remote, runtime, key

    def rpc(self, remote, op, payload=None, root='canonical-root'):
        return remote.methods[op](payload or {}, session_id=root)

    def retained(self):
        creation = self.runtime.creation
        self.rpc(self.remote, 'creation.admit')
        binding = fixture_binding(self.root/'synthetic-producer')
        creation.runs.binding = binding
        creation.runs.bindings.allow_fixtures = True
        seeded = creation.runs.bindings.seed(binding)
        evaluation = importlib.import_module(self.key+'.studio.producer.evaluation')
        enabled = evaluation.enable_evaluation(creation.runs.bindings, seeded['id'], seeded['revision'])
        original = creation.policy
        creation.policy = replace(original, binding=enabled['id'], binding_revision=enabled['revision'])
        prepared = self.rpc(self.remote, 'creation.prepare', dict(direction='Harmless synthetic fixture', seconds=0.1))
        self.assertNotIn('error', prepared, prepared)
        command = {k:prepared[k] for k in ('request','revision','command','run')}
        self.assertNotIn('error', self.rpc(self.remote, 'creation.start', command))
        for _ in range(3):
            for worker in list(creation.runs.threads.values()): worker.join(10)
        saved = self.rpc(self.remote, 'creation.status')
        self.assertIsNotNone(saved.get('candidate'), saved)
        creation.policy = original
        return saved, binding

    def snapshot(self, creation):
        with creation.store.transaction() as db:
            result = {name:[tuple(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')]
                    for name in ('creation_meta','creation_roots','creation_commands','requests',
                                 'receipts','takes','local_runs','app_bindings')}
            # Production legitimately adds its own receipts to the shared table.
            # Compare every original receipt exactly, not the enlarged table size.
            result['receipts'] = [r for r in result['receipts'] if 'root' not in json.loads(r[1])]
            return result

    def test_same_receipt_audio_reload_and_code_rollback_no_effects_or_restore(self):
        saved, binding = self.retained()
        no_launch = patch('subprocess.Popen', side_effect=AssertionError('Upgrade cannot launch a producer'))
        no_launch.start()
        self.addCleanup(no_launch.stop)
        payload = dict(request=saved['request'], take=saved['candidate'], offset=0)
        before_audio = self.rpc(self.remote, 'creation.chunk', payload)
        self.assertNotIn('error', before_audio)
        self.assertEqual(len(base64.b64decode(before_audio['bytes'])), before_audio['total'])
        before = self.snapshot(self.runtime.creation)
        before_effects = len(effects(binding))
        self.dispose(self.remote, self.key)
        remote, runtime, key = self.load(self.new)
        self.assertEqual(len(remote.methods), 27)
        self.assertFalse(runtime.creation.policy.create_store)
        self.assertEqual(self.snapshot(runtime.creation), before)
        self.assertEqual(self.rpc(remote, 'creation.status'), saved)
        self.assertEqual(self.rpc(remote, 'creation.chunk', payload), before_audio)
        self.assertIn('error', self.rpc(remote, 'production.list'))
        self.assertIn('error', self.rpc(remote, 'production.admit', root='unadmitted-root'))
        self.assertTrue(self.rpc(remote, 'production.admit')['admitted'])
        created = self.rpc(remote, 'production.create', dict(command='a'*32, kinds=['Sound effects']))
        self.assertNotIn('error', created, created)
        head = created['current']; asset = head['assets'][0]['id']
        linked = self.rpc(remote, 'production.link_take', dict(command='b'*32, production=head['id'], expected=1,
            asset=asset, request=saved['request'], take=saved['candidate']))
        self.assertNotIn('error', linked, linked)
        production_chunk = self.rpc(remote, 'production.chunk', dict(production=head['id'], asset=asset,
            request=saved['request'], take=saved['candidate'], offset=0))
        self.assertNotIn('error', production_chunk, production_chunk)
        self.assertEqual(production_chunk['bytes'], before_audio['bytes'])
        enabled_policy = runtime.production.association
        runtime.production.association = replace(enabled_policy, revision='unadmitted-revision')
        self.assertIn('error', self.rpc(remote, 'production.open', dict(production=head['id'])))
        runtime.production.association = enabled_policy
        self.assertEqual(self.snapshot(runtime.creation), before)
        self.dispose(remote, key)
        remote, runtime, key = self.load(self.new)
        self.assertEqual(self.rpc(remote, 'production.open', dict(production=head['id']))['current'], linked['current'])
        self.dispose(remote, key)
        remote, runtime, key = self.load(self.old)
        self.assertEqual(self.rpc(remote, 'creation.status'), saved)
        self.assertEqual(self.rpc(remote, 'creation.chunk', payload), before_audio)
        self.assertEqual(self.snapshot(runtime.creation), before)
        with runtime.creation.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM productions').fetchone()[0], 1)
        self.assertEqual(self.record_path.read_bytes(), self.record)
        self.assertEqual(len(effects(binding)), before_effects)
        self.assertNotIn('production.list', remote.methods)

    def test_missing_malformed_identity_binding_and_policy_fail_closed_preserve(self):
        self.dispose(self.remote, self.key)
        original = json.loads(self.record)
        self.record_path.unlink()  # Controlled adverse fixture only; entry never deletes state.
        with self.assertRaises(ValueError): self.load(self.new)
        self.record_path.write_bytes(self.record)
        for field, value in [('instance','f'*32), ('binding','e'*32), ('binding_revision',1),
                             ('revision','wrong'), ('profile','wrong'), ('binding_revision',True)]:
            changed = json.dumps(dict(original, **{field:value})).encode()
            self.record_path.write_bytes(changed)
            with self.subTest(field=field), self.assertRaises(Exception): self.load(self.new)
            self.assertEqual(self.record_path.read_bytes(), changed)
        self.record_path.write_bytes(self.record)
        remote, runtime, key = self.load(self.new)
        runtime.production.association = replace(runtime.production.association, production_management=False)
        self.assertEqual(self.rpc(remote, 'production.admit')['error'], 'PRODUCTION_ACCESS_UNAVAILABLE')
        runtime.production.association = replace(runtime.production.association, production_management=True, revision='')
        self.assertEqual(self.rpc(remote, 'production.list')['error'], 'PRODUCTION_ACCESS_UNAVAILABLE')

    def test_no_store_bootstrap_and_record_symlinks_duplicates_refuse(self):
        self.dispose(self.remote, self.key)
        database = self.data/'media/state/studio.db'
        saved_database = database.read_bytes()
        database.rename(database.with_suffix('.preserved'))
        with self.assertRaises(ValueError): self.load(self.new)
        self.assertFalse(database.exists())
        self.assertEqual(database.with_suffix('.preserved').read_bytes(), saved_database)
        database.with_suffix('.preserved').rename(database)
        self.record_path.rename(self.data/'record-preserved')
        self.record_path.symlink_to(self.data/'record-preserved')
        with self.assertRaises(ValueError): self.load(self.new)
        self.record_path.unlink()
        self.record_path.write_bytes(self.record[:-2]+b', "schema":1}\n')
        with self.assertRaises(ValueError): self.load(self.new)
        self.record_path.write_bytes(self.record)
        remote, runtime, key = self.load(self.new)
        self.assertEqual(self.record_path.read_bytes(), self.record)
        self.assertEqual(runtime.creation.instance, json.loads(self.record)['instance'])

    def test_newer_binding_revision_requires_reconciliation_without_updating_record(self):
        creation = self.runtime.creation
        current = creation.binding()
        changed = {k:v for k,v in current.items() if k not in ('id','revision','schema_version')}
        changed['enabled'] = False
        creation.runs.bindings.put(changed, current['id'], current['revision'])
        self.dispose(self.remote, self.key)
        with self.assertRaisesRegex(ValueError, 'ACTIVATION_BINDING_REVIEW_REQUIRED'):
            self.load(self.new)
        self.assertEqual(self.record_path.read_bytes(), self.record)

    def test_selected_registration_serializes_and_disposes_releases_lease(self):
        self.dispose(self.remote, self.key)
        remote, runtime, key = self.load(self.new)
        with self.assertRaises(Exception): self.load(self.new)  # Competing owner cannot acquire.
        entered, done = threading.Event(), threading.Event()
        def read():
            entered.set()
            self.rpc(remote, 'production.list')
            done.set()
        with runtime.creation.mutex:
            thread = threading.Thread(target=read); thread.start()
            self.assertTrue(entered.wait(2))
            self.assertFalse(done.wait(0.05))
        thread.join(5); self.assertTrue(done.is_set())
        stale = remote.methods['production.list']
        retiring, retired = threading.Event(), threading.Event()
        def unload():
            retiring.set()
            self.dispose(remote, key)
            retired.set()
        with runtime.creation.mutex:
            thread = threading.Thread(target=unload); thread.start()
            self.assertTrue(retiring.wait(2))
            self.assertFalse(retired.wait(0.05))
            self.assertFalse(runtime.creation.closed)
        thread.join(5); self.assertTrue(retired.is_set())
        self.assertEqual(stale({}, session_id='canonical-root')['error'], 'CREATION_RETIRED')
        _, reloaded, _ = self.load(self.new)
        self.assertEqual(reloaded.creation.instance, json.loads(self.record)['instance'])


if __name__ == '__main__':
    unittest.main()
