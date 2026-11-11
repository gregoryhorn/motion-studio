"""Execute preserved B2 layers against non-private fixtures, then reopen under F1.

Only these fixed checkpoint modules are loaded, in tests only. This is not an app plugin
loader or a copied repository/worktree. No installed producer file is read or executed.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from studio.assets.retention import Assets
from studio.persistence.store import Store, identity
from studio.producer.local_sfx import PrepareSFX
from studio.runs.owned_process import OwnedProcess
from studio.runs.service import LocalRuns
from tests.producer_support import fixture_binding, prepare, wait_run, effects

from tests.frozen_sources import require_history

CHECKPOINT = '165982a7300b74debdce282997d4eca854459a6a'
MODULES = ('studio/runs/persistence.py', 'studio/assets/producer_collection.py', 'studio/runs/service.py')


def checkpoint_source(path):
    require_history(CHECKPOINT)
    manifest = json.loads(subprocess.check_output(['git', 'show', CHECKPOINT + ':docs/evidence/code-manifest.json']))
    source = subprocess.check_output(['git', 'show', CHECKPOINT + ':' + path])
    expected = next(row['sha256'] for row in manifest if row['path'] == path)
    if hashlib.sha256(source).hexdigest() != expected:
        raise AssertionError('Checkpoint source mismatch')
    return source


def original_runs(store, binding):
    loaded = []
    for path in MODULES:
        namespace = {'__name__': 'tests.fixed_b2_checkpoint'}
        exec(compile(checkpoint_source(path), path, 'exec'), namespace)
        loaded.append(namespace)
    loaded[2]['RunStore'] = loaded[0]['RunStore']
    loaded[2]['ProducerCollection'] = loaded[1]['ProducerCollection']
    return loaded[2]['LocalRuns'](store, binding, OwnedProcess(deadline=2, grace=0.1))


class LegacyCheckpointTests(unittest.TestCase):
    def exercise(self, interrupted):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding = fixture_binding(root / 'tool')
            raw = checkpoint_source('tests/producer_fixture_child.py').decode()
            binding.path.write_text(binding.path.read_text().split('\n', 1)[0] + '\n' + raw.split('\n', 1)[1])
            binding = replace(binding, digest=hashlib.sha256(binding.path.read_bytes()).hexdigest())
            store = Store(root / 'var')
            old = original_runs(store, binding)
            try:
                item, model = prepare(old)
                if interrupted:
                    old.after_exit = lambda: (_ for _ in ()).throw(SystemExit())
                old.start(item['id'], lambda: True)
                wait_run(old, item['id'], {'Collecting'} if interrupted else {'Ready for review'})
                old.threads[item['id']].join(3)
                row = old.records.get(item['id'])
                self.assertEqual(row['plan']['schema'], 1)
                encoded = row['plan_digest']
                staged = store.home / 'staging' / ('sfx-' + item['id']) / 'candidate.wav'
                original = staged.read_bytes()
                if not interrupted:
                    self.assertEqual(Assets(store).retrieve(item['candidate'])[0], original)
                uncertain = old.prepare(PrepareSFX(**{**model.model_dump(), 'command': identity()}))
                old.records.claim(uncertain['id'])
            finally:
                old.close()
            # Normal launch metadata is deliberately disabled, not the fixture binding.
            new = LocalRuns(Store(store.home))
            try:
                record = new.bindings.seed(new.binding)
                new.bindings.revise(record['id'], record['revision'], enabled=False)
                self.assertEqual(new.records.get(item['id'])['status'], 'Ready for review')
                self.assertEqual(new.records.get(item['id'])['plan_digest'], encoded)
                self.assertEqual(new.prepare(model), item)
                new.start(item['id'], lambda: True)
                self.assertEqual(Assets(new.store).retrieve(item['candidate'])[0], original)
                self.assertEqual(new.records.get(uncertain['id'])['status'], 'Outcome unknown')
                new.start(uncertain['id'], lambda: True)
                self.assertEqual(new.records.get(uncertain['id'])['status'], 'Outcome unknown')
                self.assertEqual(len(effects(binding)), 1)
                self.assertEqual(len(new.store.snapshot()['takes']), 1)
                self.assertEqual(new.records.public(item['id'])['origin'], 'test_fixture')
            finally:
                new.close()

    def test_preserved_b2_v1_ready_replay_retrieval_disable_and_unknown(self):
        self.exercise(False)

    def test_preserved_b2_v1_exited_pair_recovers_without_fixture_enable(self):
        self.exercise(True)
