"""Explicit shipped registry and v1 compatibility mapping; no dynamic imports."""
from ..domain import Fault
from ..producer.local_sfx import Binding, WRAPPER
from ..producer.stable_adapter import StableAudio

from typing import Any


class Catalog:
    test_only = False

    def __init__(self, *, declarative=True):
        adapter = StableAudio()
        self.adapters: dict[tuple[str, int], Any] = {(adapter.id, adapter.version): adapter}
        from ..producer.music.adapter import AceStep
        music = AceStep()
        self.adapters[(music.id, music.version)] = music
        if declarative:
            from ..producer.cli_family import DeclarativeCLI
            family = DeclarativeCLI(self)
            self.adapters[(family.id,family.version)] = family
        self.cli_targets = {}  # Independently approved target locations, never derived from evidence.
        self.setup_locations = {(adapter.id, adapter.version): (str(WRAPPER),)}

    def lookup(self, name, version):
        try:
            return self.adapters[(name, version)]
        except KeyError:
            raise Fault('UNSUPPORTED_ADAPTER', 409) from None

    def for_plan(self, plan):
        if plan.get('schema') == 1:
            # Explicit preserved v1 decoder: do not rewrite its hashed stored bytes.
            adapter = self.lookup('stable-audio-local', 1)
        elif plan.get('schema') == 2:
            expected = {'schema', 'request', 'revision', 'snapshot', 'kind', 'direction', 'purpose',
                        'adapter', 'adapter_version', 'operation', 'binding', 'binding_digest',
                        'parameters', 'outputs', 'method', 'execution_kind', 'candidates'}
            if set(plan) != expected:
                raise Fault('PLAN_CONFLICT', 409)
            adapter = self.lookup(plan['adapter'], plan['adapter_version'])
            if plan['outputs'] != adapter.validation_profile:
                raise Fault('PLAN_CONFLICT', 409)
        else:
            raise Fault('UNSUPPORTED_SCHEMA', 409)
        adapter.validate(plan)
        return adapter

    def compatibility(self, runtime):
        pins = runtime.pins()
        location = pins.get('wrapper', pins.get('executable'))
        adapter = self.lookup('stable-audio-local', 1)
        return dict(adapter=adapter.id, adapter_version=adapter.version,
                    interface_version=adapter.interface, executable=location,
                    pins=pins, file_digest=pins.get('sha256') or pins.get('files', {}).get(location, ''),
                    capabilities=adapter.describe(), checked_at=None,
                    evidence_scope='Explicit offline harness only' if runtime.fixture_only else 'Known disabled metadata; no setup check',
                    fixture_only=runtime.fixture_only,
                    enabled=runtime.fixture_only, qualification='Offline tested only' if runtime.fixture_only else 'Not checked',
                    availability='Unavailable', reason='OFFLINE_ONLY' if runtime.fixture_only else 'FEATURE_DISABLED',
                    action='Review offline evidence' if runtime.fixture_only else 'Complete live admission qualification')

    def default_runtime(self):
        return Binding()

    def prepare_compat(self, runs, model, runtime):
        record = runs.bindings.seed(runtime)
        adapter = self.lookup('stable-audio-local', 1)
        return runs.records.prepare(model, record, adapter,
                                    {key: getattr(model, key) for key in ('seconds', 'seed', 'language')},
                                    operation='sfx', command_payload={'operation': 'prepare-sfx', **model.model_dump()})

    def runtime_legacy(self, plan, runtime):
        if plan['binding'] != runtime.pins():
            raise Fault('RUNTIME_DRIFT', 409)
        return runtime

    def validate_test_runtime(self, binding):
        if not binding.fixture_only or str(binding.executable()) == str(WRAPPER):
            raise ValueError('Test-only binding must never select the real producer')

    def describe(self, name, version, interface=None):
        try:
            item = self.lookup(name, version).describe()
            if interface and interface not in item['interface_versions']:
                raise Fault('UNSUPPORTED_INTERFACE', 409)
            return item
        except Fault:
            return dict(id=name, version=version, availability='Unsupported', qualification='Not checked',
                        media=[], operations=[], reason='UNSUPPORTED_INTERFACE',
                        action='Request app support with name/version and public interface documentation')

    def legacy_method(self):
        return self.lookup('stable-audio-local', 1).describe()
