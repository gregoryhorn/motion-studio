"""SAME behavioral lifecycle contract over two genuinely different offline adapters."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from studio.assets.retention import Assets
from studio.domain import Fault, SaveRequest, TakeAction
from studio.persistence.store import Store, identity
from studio.producer.contracts import PrepareApp
from studio.runs.owned_process import OwnedProcess, incarnation
from studio.runs.service import LocalRuns
from tests.adapter_fixtures import OfflineCatalog, FixtureA, FixtureB, worker_location, setup
from tests.producer_support import wait_run
from tests.ownership_regressions import initial_ownership_loss
import json


class LifecycleContract(unittest.TestCase):
    adapter_class: type

    def valid_options(self) -> dict:
        raise NotImplementedError

    def changed_options(self) -> dict:
        raise NotImplementedError

    def expected_argv(self, plan, output):
        raise NotImplementedError

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.adapter = self.adapter_class()
        self.location = worker_location(self.root / 'tool', self.adapter)
        self.store = Store(self.root / 'var')
        self.runs = LocalRuns(self.store, worker=OwnedProcess(deadline=2, grace=0.1), catalog=OfflineCatalog())
        self.record = setup(self.runs, self.adapter, self.location)
        self.options = self.valid_options()
        self.operation = self.adapter.describe()['operations'][0]

    def tearDown(self):
        self.runs.close()
        self.temp.cleanup()

    def effects(self, location=None):
        file = (location or self.location).parent / 'effects.jsonl'
        return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []

    def prepare(self, text="Non-private ' ; $(touch NEVER)\nfixture", request=None, revision=1, record=None):
        record = record or self.record
        if request is None:
            saved = self.store.save(SaveRequest(command=identity(), expected=0, text=text, kind='Sound effects'))
            request = saved['id']
        model = PrepareApp(command=identity(), request=request, revision=revision, binding=record['id'],
                           binding_revision=record['revision'], operation=self.operation, options=self.options)
        return self.runs.prepare_app(model), model

    def start(self, item):
        self.runs.start(item['id'], lambda: True)
        wait_run(self.runs, item['id'])
        worker = self.runs.threads.get(item['id'])
        if worker is not None:  # Persisted replay intentionally creates no worker.
            worker.join(timeout=8)
            self.assertFalse(worker.is_alive(), 'Controlled worker cleanup must finish before the next fixture start')
        return self.runs.records.get(item['id'])

    def reopen(self):
        self.runs.close()
        self.store = Store(self.store.home)
        self.runs = LocalRuns(self.store, worker=OwnedProcess(deadline=2, grace=0.1), catalog=OfflineCatalog())

    def test_exact_vector_boundary_and_final_mutation_zero_effects(self):
        first, _ = self.prepare()
        self.assertEqual(self.start(first)['status'], 'Ready for review')
        row = self.runs.records.get(first['id'])
        output = self.store.home / 'staging' / ('sfx-' + first['id']) / 'outputs/candidate.wav'
        expected = self.expected_argv(row['plan'], output)
        self.assertEqual(self.effects()[0]['argv'], expected)
        self.assertNotIn('PYTHONPATH', self.effects()[0]['env'])
        self.assertFalse((self.location.parent / 'NEVER').exists())
        second, _ = self.prepare()
        original = self.adapter_class.validate_dispatch
        with patch.object(self.adapter_class, 'validate_dispatch',
                          lambda adapter, plan, path, argv, runtime: original(adapter, plan, path, argv + ['--extra'], runtime)):
            self.assertEqual(self.start(second)['status'], 'Blocked')
        self.assertEqual(len(self.effects()), 1)

    def test_resource_use_admission_and_disable_zero_effects(self):
        for reason in ('RESOURCE_BUSY', 'USE_RESTRICTED'):
            with self.subTest(reason=reason):
                old, _ = self.prepare()
                self.record = self.runs.bindings.revise(self.record['id'], self.record['revision'], reason=reason)
                self.assertEqual(self.start(old)['error'], reason)
                self.assertEqual(self.effects(), [])
                self.record = self.runs.bindings.revise(self.record['id'], self.record['revision'], reason='OFFLINE_ONLY')
        item, _ = self.prepare()
        self.runs.bindings.revise(self.record['id'], self.record['revision'], enabled=False)
        self.assertEqual(self.start(item)['status'], 'Blocked')
        self.assertEqual(self.effects(), [])

    def test_selected_historical_revision_discloses_current_restrictions(self):
        item, model = self.prepare()
        original = self.runs.records.get(item['id'])
        old = self.record
        selected = self.runs.bindings.select(model.request, old['id'], old['revision'], self.operation)
        for reason, availability, action in (
                ('RESOURCE_BUSY', 'Unavailable', 'Review current resource issue'),
                ('USE_RESTRICTED', 'Restricted for this use', 'Resolve the named use restriction')):
            latest = self.runs.bindings.get(old['id'])
            current = self.runs.bindings.revise(old['id'], latest['revision'], reason=reason,
                                              availability=availability, action=action)
            with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                shown = next(row for row in self.runs.bindings.rows()
                             if (row['binding'], row['revision']) == (old['id'], old['revision']))
                self.assertEqual((shown['reason'], shown['availability'], shown['action']),
                                 (reason, availability, action))
                self.assertEqual(shown['current_revision'], current['revision'])
                self.assertEqual(shown['qualification'], old['qualification'])
                self.assertEqual(shown['checked_at'], old['checked_at'])
                self.assertEqual(self.runs.bindings.selections(), [selected])
                self.assertEqual(self.start(item)['error'], reason)
                spawn.assert_not_called()
            row = self.runs.records.get(item['id'])
            self.assertEqual(row['plan'], original['plan'])
            self.assertEqual(row['plan_digest'], original['plan_digest'])
            self.assertEqual(self.effects(), [])

    def test_same_command_replay_conflict_and_single_effect(self):
        item, model = self.prepare()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertTrue(all(value == item for value in pool.map(lambda _: self.runs.prepare_app(model), range(4))))
        with self.assertRaises(Fault) as caught:
            self.runs.prepare_app(model.model_copy(update={'options': self.changed_options()}))
        self.assertEqual(caught.exception.code, 'COMMAND_CONFLICT')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.runs.start(item['id'], lambda: True), range(4)))
        self.assertEqual(wait_run(self.runs, item['id'])['status'], 'Ready for review')
        self.reopen()
        self.assertEqual(self.runs.prepare_app(model), item)
        self.assertEqual(self.start(item)['status'], 'Ready for review')
        self.assertEqual(len(self.effects()), 1)

    def test_actual_delayed_effect_unknown_restart_never_relaunch(self):
        (self.location.parent / 'mode').write_text('sleep')
        item, _ = self.prepare()
        def lost_receipt():
            deadline = time.monotonic() + 1
            while not self.effects() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(self.effects()), 1)
            raise SystemExit()
        self.runs.worker.after_spawn = lost_receipt
        self.assertEqual(self.start(item)['status'], 'Outcome unknown')
        self.assertEqual(len(self.effects()), 1)
        self.reopen()
        self.assertEqual(self.start(item)['status'], 'Outcome unknown')
        another, _ = self.prepare()
        with self.assertRaises(Fault):
            self.runs.start(another['id'], lambda: True)
        self.assertEqual(len(self.effects()), 1)

    def test_initial_incarnation_missing_after_actual_spawn(self):
        initial_ownership_loss(self, 'no-incarnation')

    def test_initial_ownership_mismatch_after_actual_spawn(self):
        initial_ownership_loss(self, 'ownership-mismatch')

    def test_initial_ownership_fault_after_actual_spawn(self):
        initial_ownership_loss(self, 'ownership-fault')

    def test_popen_fault_with_actual_child_cannot_prove_no_launch(self):
        initial_ownership_loss(self, 'popen-fault')

    def test_proven_pre_spawn_refusal_remains_retryable(self):
        item, _ = self.prepare()
        with patch('studio.runs.owned_process.incarnation', return_value=None), \
             patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            row = self.start(item)
            self.assertEqual(row['status'], 'Blocked')
            self.assertEqual(row['certainty'], 'not attempted')
            self.assertEqual(row['error'], 'SUPERVISION_UNAVAILABLE')
            spawn.assert_not_called()
            self.assertEqual(self.effects(), [])
        self.assertEqual(self.start(item)['status'], 'Ready for review')
        self.assertEqual(len(self.effects()), 1)

    def test_owned_cancel_and_completion_won(self):
        (self.location.parent / 'mode').write_text('sleep')
        item, _ = self.prepare()
        self.runs.start(item['id'], lambda: True)
        row = wait_run(self.runs, item['id'], {'Running'})
        deadline = time.monotonic() + 1
        while not self.effects() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(self.effects()), 1)
        self.runs.stop(item['id'])
        self.assertEqual(wait_run(self.runs, item['id'])['status'], 'Cancelled')
        self.assertIsNone(incarnation(row['process']['incarnation']['pid']))
        (self.location.parent / 'mode').write_text('good')
        complete, _ = self.prepare()
        self.assertEqual(self.start(complete)['status'], 'Ready for review')
        self.assertEqual(self.runs.stop(complete['id'])['status'], 'Ready for review')
        self.assertEqual(len(self.effects()), 2)

    def test_bad_native_evidence_and_output_never_ready(self):
        for mode in ('mismatch', 'corrupt-receipt', 'bad-output'):
            with self.subTest(mode=mode):
                (self.location.parent / 'mode').write_text(mode)
                item, _ = self.prepare()
                self.assertEqual(self.start(item)['status'], 'Collection blocked')
                self.assertEqual(self.start(item)['status'], 'Collection blocked')
                with self.assertRaises(Fault):
                    self.runs.collection.collect(item['id'])
        self.assertEqual(self.store.snapshot()['takes'], [])
        self.assertEqual(len(self.effects()), 3)

    def test_collection_crash_exact_bytes_original_candidate_and_selection(self):
        first, model = self.prepare()
        self.assertEqual(self.start(first)['status'], 'Ready for review')
        self.store.select(TakeAction(command=identity(), request=model.request, expected=1, take=first['candidate']))
        old = Assets(self.store).retrieve(first['candidate'])[0]
        self.runs.collection.after_finalize = lambda: (_ for _ in ()).throw(SystemExit())
        second, _ = self.prepare(request=model.request, revision=2)
        self.runs.start(second['id'], lambda: True)
        wait_run(self.runs, second['id'], {'Collecting'})
        self.runs.threads[second['id']].join(3)
        final = self.store.home / 'media' / (second['candidate'] + '.wav')
        original = final.read_bytes()
        self.assertEqual(len(self.store.snapshot()['takes']), 1)
        self.reopen()
        self.assertEqual(self.runs.records.get(second['id'])['status'], 'Ready for review')
        data, take = Assets(self.store).retrieve(second['candidate'])
        self.assertEqual(data, original)
        self.assertEqual(take['digest'], hashlib.sha256(original).hexdigest())
        self.assertEqual(take['origin'], 'test_fixture')
        self.assertEqual(Assets(self.store).retrieve(first['candidate'])[0], old)
        self.assertEqual(self.store.snapshot()['requests'][0]['selected'], first['candidate'])
        self.assertEqual(self.start(second)['status'], 'Ready for review')
        self.assertEqual(len(self.effects()), 2)

    def test_removed_adapter_keeps_original_record_and_artifact_readable(self):
        item, _ = self.prepare()
        self.assertEqual(self.start(item)['status'], 'Ready for review')
        original = Assets(self.store).retrieve(item['candidate'])[0]
        plan = self.runs.records.get(item['id'])['plan']
        self.runs.close()
        # Normal catalog does not ship either TEST adapter; no fallback or re-execution.
        self.runs = LocalRuns(Store(self.store.home))
        self.assertEqual(self.runs.records.get(item['id'])['plan'], plan)
        self.assertEqual(self.runs.start(item['id'], lambda: True)['status'], 'Ready for review')
        self.assertEqual(Assets(self.store).retrieve(item['candidate'])[0], original)
        self.assertEqual(self.runs.catalog.describe(self.adapter.id, 1)['availability'], 'Unsupported')
        self.assertEqual(len(self.effects()), 1)

    def test_new_location_and_selection_do_not_rebind_old_plan(self):
        old, model = self.prepare()
        before = self.runs.records.get(old['id'])['plan']
        self.runs.bindings.select(model.request, self.record['id'], self.record['revision'], self.operation)
        second_location = worker_location(self.root / 'second-tool', self.adapter)
        self.record = setup(self.runs, self.adapter, second_location, self.record['id'], self.record['revision'])
        new, _ = self.prepare(request=model.request)
        self.runs.bindings.select(model.request, self.record['id'], self.record['revision'], self.operation)
        self.assertEqual(self.runs.records.get(old['id'])['plan'], before)
        self.assertEqual(self.start(old)['status'], 'Ready for review')
        self.assertEqual(self.start(new)['status'], 'Ready for review')
        self.assertEqual(self.effects()[0]['argv'][0], str(self.location))
        self.assertEqual(self.effects(second_location)[0]['argv'][0], str(second_location))
        self.reopen()
        self.assertEqual(self.runs.records.get(old['id'])['plan'], before)
        self.assertEqual(self.runs.prepare_app(model), old)
        self.assertEqual(len(self.effects()), 1)
        self.assertEqual(len(self.effects(second_location)), 1)


class FixtureAContract(LifecycleContract):
    adapter_class = FixtureA

    def valid_options(self):
        return dict(seconds=0.1, seed=7, language='en')

    def changed_options(self):
        return dict(self.options, seed=8)

    def expected_argv(self, plan, output):
        from studio.producer.local_sfx import vector
        return vector(self.location, plan, output)


class FixtureBContract(LifecycleContract):
    adapter_class = FixtureB

    def valid_options(self):
        return dict(frame_count=4410, timbre='soft')

    def changed_options(self):
        return dict(self.options, timbre='bright')

    def expected_argv(self, plan, output):
        return [str(self.location), 'render', '--description', plan['direction'], '--frame-count', '4410',
                '--timbre', 'soft', '--target', str(output)]


def load_tests(loader, tests, pattern):
    # Built-in discovery runs the same concrete cases for EACH adapter, not the abstract base.
    return unittest.TestSuite(loader.loadTestsFromTestCase(case) for case in (FixtureAContract, FixtureBContract))
