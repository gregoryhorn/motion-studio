"""Exact frozen AFC/SFX three-file repair, original entry/store/audio preserved."""
import base64
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import tests.test_production_upgrade as harness
from tools.prepare_sfx_development_repair import ARCHIVE, CHANGED, ROOT, baseline, verify
from tools.build_native_package import sha
from tests.producer_support import effects

DELTA = ROOT/'dist/development/afc-sfx-remote-repair-r1'


from tests.frozen_sources import require_baselines


class BaselineRepairTests(unittest.TestCase):
    # Reuse established fixture operations, not historical Production test cases.
    load = harness.SameStoreTests.load
    dispose = harness.SameStoreTests.dispose
    dispose_all = harness.SameStoreTests.dispose_all
    rpc = harness.SameStoreTests.rpc
    retained = harness.SameStoreTests.retained
    snapshot = harness.SameStoreTests.snapshot

    @classmethod
    def setUpClass(cls):
        require_baselines(ARCHIVE)
        sys.path.insert(0,str(harness.HOST))
        from hermes_cli.plugin_host_child import _import_plugin,RemotePluginContext,HostRuntime
        cls.loader = staticmethod(_import_plugin)
        cls.context_type = RemotePluginContext
        cls.host_unload = staticmethod(HostRuntime.op_unload)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='afc-repair-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.loads = []
        self.addCleanup(self.dispose_all)
        # The immutable repair bytes are the integration fixture. Historical
        # screenshots are expected to drift during this UI sprint; never repin them.
        receipt = json.loads((DELTA/'identity.json').read_text())
        self.assertEqual(set(receipt['files']), set(CHANGED))
        for name, facts in receipt['files'].items():
            for prefix in ('before', 'after'):
                self.assertEqual(sha((DELTA/prefix/name).read_bytes()), facts[prefix])
        self.old = self.root/'old'
        with zipfile.ZipFile(ARCHIVE) as archive: archive.extractall(self.old)
        (self.old/'motion-studio/__init__.py').write_bytes((ROOT/'native-package/activation-entry.py').read_bytes())
        self.new = self.root/'new';shutil.copytree(self.old,self.new)
        for name in CHANGED:
            (self.new/'motion-studio'/name).write_bytes((DELTA/'after'/name).read_bytes())
        self.data = self.root/'data'
        self.remote,self.runtime,self.key = self.load(self.old,bootstrap=True)
        self.record_path = self.data/'creation-activation.json';self.record = self.record_path.read_bytes()

    def test_retained_audio_same_identity_reload_rollback_no_new_authority_or_effect(self):
        saved,binding = self.retained()
        original_policy = self.runtime.creation.policy
        before = self.snapshot(self.runtime.creation);count = len(effects(binding))
        payload = dict(request=saved['request'],take=saved['candidate'],offset=0)
        audio = self.rpc(self.remote,'creation.chunk',payload)
        self.assertEqual(len(base64.b64decode(audio['bytes'])),audio['total'])
        with self.runtime.creation.store.transaction() as db:
            tables = [tuple(row) for row in db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")]
        self.dispose(self.remote,self.key)
        with patch('subprocess.Popen',side_effect=AssertionError('Repair cannot generate')):
            for tree in (self.new,self.new,self.old):
                remote,runtime,key = self.load(tree)
                self.assertEqual(asdict(runtime.creation.policy),dict(asdict(original_policy),create_store=False))
                self.assertEqual(self.snapshot(runtime.creation),before)
                self.assertEqual(self.rpc(remote,'creation.chunk',payload),audio)
                self.assertEqual(self.rpc(remote,'creation.status'),saved)
                if tree == self.new:
                    handler = remote.methods['creation.list']
                    ordinary = handler({},session_id='canonical-root')
                    self.assertEqual(handler(dict(profile='motion-studio',session_id='canonical-root'),session_id='canonical-root'),ordinary)
                    for profile in ('wrong','',None,17):
                        self.assertEqual(handler(dict(profile=profile),session_id='canonical-root'),dict(error='CREATION_SCOPE_DENIED'))
                    self.assertEqual(handler(dict(profile='motion-studio',extra=True),session_id='canonical-root'),dict(error='INVALID_CREATION_INPUT'))
                    self.assertEqual(handler(dict(profile='motion-studio',session_id='wrong'),session_id='canonical-root'),dict(error='CREATION_SCOPE_DENIED'))
                self.assertFalse(any(n.startswith('production.') or n=='creation.admit_music' for n in remote.methods))
                self.assertFalse(hasattr(runtime,'production'))
                with runtime.creation.store.transaction() as db:
                    self.assertEqual([tuple(row) for row in db.execute("SELECT name,sql FROM sqlite_master ORDER BY name")],tables)
                self.assertEqual(self.record_path.read_bytes(),self.record)
                self.dispose(remote,key)
        self.assertEqual(len(effects(binding)),count)

    def test_preservation_verifier_still_rejects_changed_evidence(self):
        # Exercise the real verifier on a controlled snapshot, with no changes to
        # the frozen repair or its original historical preservation receipt.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root/'repair'
            shutil.copytree(DELTA, target)
            preserved = root/'evidence.txt'
            preserved.write_bytes(b'controlled original evidence')
            receipt = json.loads((target/'identity.json').read_text())
            receipt['preserved'] = {'evidence.txt': sha(preserved.read_bytes())}
            (target/'identity.json').write_text(json.dumps(receipt))
            with patch('tools.prepare_sfx_development_repair.ROOT', root):
                self.assertTrue(verify(target)['exact'])
                preserved.write_bytes(b'controlled changed evidence')
                with self.assertRaisesRegex(ValueError, 'PRESERVATION_MISMATCH'):
                    verify(target)

    def test_only_three_baseline_files_change_and_schema_contract_remains_exact(self):
        before = baseline()
        changed = [name for name in before if name!='__init__.py' and
            (self.new/'motion-studio'/name).read_bytes()!=before[name]]
        self.assertEqual(sorted(changed),sorted(CHANGED))
        self.assertEqual((self.old/'motion-studio/__init__.py').read_bytes(),(self.new/'motion-studio/__init__.py').read_bytes())
        self.assertNotIn('studio/native/production/registration.py',before)
        self.assertFalse(any('/music/' in name for name in before))
        old = before[CHANGED[0]].decode();new = (DELTA/'after'/CHANGED[0]).read_text()
        self.assertEqual(old.split('CONTRACT_SHA256 = ')[1],new.split('CONTRACT_SHA256 = ')[1])


if __name__ == '__main__':
    unittest.main()
