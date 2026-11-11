"""Frozen r2 Production candidate against its exact source and disposable store."""
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import tests.test_production_upgrade as historical
import tools.prepare_production_workspace as current
from tests.frozen_sources import materialize


class FrozenWorkspaceMixin:
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='motion-workspace-source-')
        self.addCleanup(temp.cleanup)
        source = materialize(current.ARCHIVE, temp.name)
        self.source = source
        prepare, inspect = current.prepare, current.inspect
        def frozen_prepare(*args, **kwargs):
            kwargs.setdefault('checkout', source)
            return prepare(*args, **kwargs)
        def frozen_inspect(*args, **kwargs):
            if len(args) < 2:
                kwargs.setdefault('checkout', source)
            return inspect(*args, **kwargs)
        for name, function in (('prepare', frozen_prepare), ('inspect', frozen_inspect)):
            replacement = patch.object(current, name, function)
            replacement.start()
            self.addCleanup(replacement.stop)
        super().setUp()


class CurrentBundleTests(FrozenWorkspaceMixin, unittest.TestCase):
    def test_exact_reproduction_overlay_desktop_and_no_grants(self):
        first, second = current.prepare(), current.prepare()
        self.assertEqual(first, second)
        with zipfile.ZipFile(io.BytesIO(first['combined-tree.zip'])) as archive:
            combined = {n.removeprefix('motion-studio/'):archive.read(n) for n in archive.namelist()}
        original = current.inspect()
        self.assertEqual([k for k in original if original[k] != combined[k]], ['__init__.py'])
        self.assertEqual(len(combined), 98)
        self.assertEqual(json.loads(first['combined-tree.json']), current.manifest(combined))
        self.assertEqual(len(json.loads(first['desktop-tree.json'])), 15)
        plan = json.loads(first['upgrade-plan.json'])
        self.assertFalse(plan['approval_granted'])
        self.assertFalse(plan['apply_implemented'])
        self.assertFalse(plan['creation']['create_store'])
        self.assertEqual(plan['music'], dict(prepare=False,effects=False,binding='',admission=False))
        self.assertEqual(first['production-upgrade-entry.py'], current.ENTRY.read_bytes())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current.write(root/'one', root)
            current.write(root/'two', root)
            self.assertEqual({p.name:p.read_bytes() for p in (root/'one').iterdir()},
                             {p.name:p.read_bytes() for p in (root/'two').iterdir()})
            # Historical live-tree preservation must reject the intentional sprint edits.
            with self.assertRaisesRegex(ValueError, 'AUTHORITY_SOURCE_MISMATCH|HISTORICAL_PRESERVATION_MISMATCH'):
                current.verify(root/'one')
            with self.assertRaises(FileExistsError): current.write(root/'one', root)
            (root/'link').symlink_to(root/'one', target_is_directory=True)
            with self.assertRaises(ValueError): current.write(root/'link'/'escape', root)
            with self.assertRaises(ValueError): current.write(root/'..'/'escape', root)

    def test_package_overlay_source_and_host_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root/'changed.zip'; archive.write_bytes(current.ARCHIVE.read_bytes()+b'x')
            entry = root/'entry.py'; entry.write_bytes(current.ENTRY.read_bytes()+b'\n')
            for kwargs in (dict(archive=archive), dict(entry=entry), dict(checkout=root)):
                with self.subTest(kwargs=list(kwargs)), self.assertRaises((ValueError,FileNotFoundError)):
                    current.write(root/'absent', root, **kwargs)
                self.assertFalse((root/'absent').exists())
            with patch.object(current, 'host_contract', return_value={'commit':'wrong'}):
                with self.assertRaisesRegex(ValueError, 'HOST_INTERFACE_MISMATCH'): current.prepare()


class CurrentSameStoreTests(FrozenWorkspaceMixin, historical.SameStoreTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Each test materializes the source matching this historical archive.

    def setUp(self):
        # Reuse the adverse reload/lease tests with the exact r2 archive bytes.
        replacement = patch.object(historical.upgrade, 'prepare',
                                   lambda **kwargs: current.prepare(checkout=self.source))
        replacement.start()
        self.addCleanup(replacement.stop)
        super().setUp()

    def test_same_receipt_audio_reload_and_code_rollback_no_effects_or_restore(self):
        saved, binding = self.retained()
        from tests.producer_support import effects
        before = self.snapshot(self.runtime.creation)
        before_effects = len(effects(binding))
        payload = dict(request=saved['request'],take=saved['candidate'],offset=0)
        audio = self.rpc(self.remote,'creation.chunk',payload)
        self.assertEqual(len(base64.b64decode(audio['bytes'])),audio['total'])
        self.dispose(self.remote,self.key)
        with patch('subprocess.Popen',side_effect=AssertionError('No generator activation')):
            remote,runtime,key = self.load(self.new)
            self.assertEqual(len(remote.methods),28)
            observed = self.rpc(remote,'creation.status')
            self.assertEqual(observed['kind'],'Sound effects')
            self.assertTrue(observed['method'])
            self.assertEqual({k:v for k,v in observed.items() if k not in ('kind','method')},saved)
            self.assertEqual(self.rpc(remote,'creation.chunk',payload),audio)
            self.assertEqual(self.snapshot(runtime.creation),before)
            self.assertFalse(runtime.creation.policy.music.prepare)
            self.assertFalse(runtime.creation.policy.music.effects)
            self.assertEqual(self.rpc(remote,'creation.admit_music')['error'],'MUSIC_SCOPE_REVIEW_REQUIRED')
            self.assertIn('error',self.rpc(remote,'production.list'))
            self.assertTrue(self.rpc(remote,'production.admit')['admitted'])
            created = self.rpc(remote,'production.create',dict(command='a'*32,kinds=['Sound effects']))
            head = created['current']; asset = head['assets'][0]['id']
            linked = self.rpc(remote,'production.link_take',dict(command='b'*32,production=head['id'],expected=1,
                asset=asset,request=saved['request'],take=saved['candidate']))
            self.assertNotIn('error',linked,linked)
            selected = self.rpc(remote,'production.select_take',dict(command='c'*32,production=head['id'],expected=2,
                asset=asset,request=saved['request'],take=saved['candidate']))
            self.assertNotIn('error',selected,selected)
            chunk = dict(production=head['id'],asset=asset,**payload)
            self.assertEqual(self.rpc(remote,'production.chunk',chunk)['bytes'],audio['bytes'])
            self.dispose(remote,key)
            remote,runtime,key = self.load(self.new)
            self.assertEqual(self.rpc(remote,'production.open',dict(production=head['id']))['current'],selected['current'])
            self.assertEqual(self.rpc(remote,'production.chunk',chunk)['bytes'],audio['bytes'])
            self.dispose(remote,key)
            remote,runtime,key = self.load(self.old)
            self.assertEqual(self.rpc(remote,'creation.status'),saved)
            self.assertEqual(self.rpc(remote,'creation.chunk',payload),audio)
            self.assertEqual(self.snapshot(runtime.creation),before)
            self.assertEqual(self.record_path.read_bytes(),self.record)
            with runtime.creation.store.transaction() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM productions').fetchone()[0],1)
            self.assertNotIn('production.list',remote.methods)
        self.assertEqual(len(effects(binding)),before_effects)


if __name__ == '__main__':
    unittest.main()
