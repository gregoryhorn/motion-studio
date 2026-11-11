"""Offline tests of real admission wiring; no installed producer/model is executed."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from studio.domain import Fault, SaveRequest
from studio.persistence.store import Store, identity
from studio.producer import local_sfx as sfx
from studio.producer.contracts import PrepareApp, SetupCLI
from studio.producer.live_sfx import ScopedRuntime, USE, resources
from studio.producer.stable_adapter import StableAudio
from studio.runs.admission import OneCandidate
from studio.runs.service import LocalRuns


class RealAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = LocalRuns(Store(self.root / 'var'))
        adapter = StableAudio()
        proposal = SetupCLI(adapter=adapter.id, interface_version=adapter.interface, executable=str(sfx.WRAPPER))
        value = self.runs.catalog.compatibility(sfx.Binding())
        value['pins'] = adapter.validate_setup(proposal, sfx.FILE_PINS[str(sfx.WRAPPER)], False)
        self.record = self.runs.bindings.put(value)
        saved = self.runs.store.save(SaveRequest(command=identity(), expected=0, text='Non-private admission unit case', kind='Sound effects'))
        self.model = PrepareApp(command=identity(), request=saved['id'], revision=1, binding=self.record['id'],
                                binding_revision=1, operation='sfx', options=dict(seconds=3.0, seed=42, language='en'))
        self.item = self.runs.prepare_app(self.model)
        self.owner = 'non-private-operator-session-proof-123456'
        self.scope = OneCandidate(self.runs, self.item['id'], self.owner, USE)
        self.runtime = ScopedRuntime(record=self.record, scope=self.scope)
        self.scope.install(self.runtime)
        self.output = self.root / 'allocation' / 'candidate.wav'
        self.output.parent.mkdir(mode=0o700)
        self.plan = self.runs.records.get(self.item['id'])['plan']

    def tearDown(self):
        self.runs.close()
        self.temp.cleanup()

    def test_real_admission_uses_exact_model_pins_resource_use_and_output_checks(self):
        with patch('studio.producer.live_sfx.sfx.check_pins') as pins, \
             patch('studio.producer.live_sfx.resources', return_value=(9000, False)):
            self.runtime.admit(self.plan, self.output)
            pins.assert_called_once_with({**sfx.FILE_PINS, **sfx.model_pins()})
            self.assertEqual(self.scope.observation['free_mib'], 9000)
            self.assertEqual(self.runs.bindings.runtime(self.plan), self.runtime)
            self.runs.bindings.check(self.plan)
            for observed, reason in (((100, False), 'RESOURCE_BUSY'), ((9000, True), 'RESOURCE_BUSY')):
                with patch('studio.producer.live_sfx.resources', return_value=observed), self.assertRaises(Fault) as denied:
                    self.runtime.admit(self.plan, self.output)
                self.assertEqual(denied.exception.code, reason)
            with patch('studio.producer.live_sfx.shutil.disk_usage') as disk:
                disk.return_value.free = 0
                with self.assertRaises(Fault) as denied:
                    self.runtime.admit(self.plan, self.output)
                self.assertEqual(denied.exception.code, 'STORAGE_UNAVAILABLE')
            for leaf in (self.output, self.output.with_suffix('.wav.json')):
                leaf.write_bytes(b'non-private collision')
                with self.assertRaises(Fault) as denied:
                    self.runtime.admit(self.plan, self.output)
                self.assertEqual(denied.exception.code, 'OUTPUT_EXISTS')
                leaf.unlink()
            self.scope.use = 'commercial-unknown'
            with self.assertRaises(Fault):
                self.runtime.admit(self.plan, self.output)

    def test_final_dispatch_preserves_v2_scope_and_rechecks_mutable_resources(self):
        adapter = StableAudio()
        with patch('studio.producer.live_sfx.sfx.check_pins'), \
             patch('studio.producer.live_sfx.resources', return_value=(9000, False)) as observed:
            dispatch = adapter.build_dispatch(self.plan, self.output, self.runtime)
            adapter.validate_dispatch(self.plan, self.output, list(dispatch.argv), self.runtime)
            self.assertEqual(observed.call_count, 2)
            with patch('studio.producer.live_sfx.resources', return_value=(100, False)), self.assertRaises(Fault) as denied:
                adapter.validate_dispatch(self.plan, self.output, list(dispatch.argv), self.runtime)
            self.assertEqual(denied.exception.code, 'RESOURCE_BUSY')

    def test_owner_plan_binding_scope_consumption_and_reopen_are_closed(self):
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            with self.assertRaises(Fault) as denied:
                self.runs.start(self.item['id'], lambda: 'different-non-private-session-proof-1234')
            self.assertEqual(denied.exception.code, 'SCOPE_OWNER_DENIED')
            with self.assertRaises(Fault):
                self.scope.check_plan(dict(self.plan, direction='Different non-private input'))
            self.scope.enter()
            with self.assertRaises(Fault):
                self.scope.enter()
            self.scope.close()
            with self.assertRaises(Fault):
                OneCandidate(self.runs, self.item['id'], self.owner, USE)
            self.runs.close()
            self.runs = LocalRuns(Store(self.runs.store.home))
            with self.assertRaises(Fault) as denied:
                self.runs.bindings.check(self.plan)
            self.assertEqual(denied.exception.code, 'FEATURE_DISABLED')
            spawn.assert_not_called()

    def test_binding_change_and_runtime_drift_deny_without_launch(self):
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            with patch('studio.producer.live_sfx.sfx.check_pins', side_effect=Fault('RUNTIME_DRIFT', 409)):
                with self.assertRaises(Fault) as denied:
                    self.runtime.admit(self.plan, self.output)
                self.assertEqual(denied.exception.code, 'RUNTIME_DRIFT')
            self.runs.bindings.revise(self.record['id'], 1, enabled=False)
            with self.assertRaises(Fault):
                self.runs.bindings.check(self.plan)
            spawn.assert_not_called()

    def test_real_pin_reader_and_driver_observation_failure(self):
        file = self.root / 'non-private-pin'
        file.write_bytes(b'controlled non-private content')
        expected = sfx.fingerprint(file.read_bytes())
        sfx.check_pins({str(file): expected})
        file.write_bytes(b'controlled drift')
        with self.assertRaises(Fault):
            sfx.check_pins({str(file): expected})
        with patch('studio.producer.live_sfx.subprocess.run', side_effect=OSError()), self.assertRaises(Fault) as denied:
            resources()
        self.assertEqual(denied.exception.code, 'RESOURCE_OBSERVATION_UNAVAILABLE')
