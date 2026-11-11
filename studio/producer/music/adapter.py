"""Explicit ACE-Step adapter; source planning works, real dispatch is default denied."""
import os
import sys
from pathlib import Path
from ...child_env import child_environment
from ...domain import Fault, MAX_BYTES
from ...assets.producer_files import read_leaf
from ...assets.retention import read_private
from ...persistence.primitives import canonical
from ...producer.contracts import DispatchSpec, normalize_exit
from ...producer.bindings import digest
from ...producer.music import contract, receipt
from ...producer.music.audio import pcm16
from ...producer.music.bridge import atomic


class Runtime:
    def __init__(self, record, scope=None):
        self.record, self.scope = record, scope
        self.fixture_only = record['fixture_only']

    def launcher(self): return Path.home() / '.local/bin/ace-step-music'

    def verify_sources(self):
        from ...producer.music.pins import known_files, verify
        verify(known_files())

    def producer_environment(self, output):
        # Fixed installed source locations; no ambient overrides or browser paths.
        home = Path.home()
        runtime = output.parent.parent / 'runtime'
        return child_environment('ace-step-local', dict(HOME=str(runtime / 'home'), TMPDIR=str(runtime / 'tmp'),
            XDG_CACHE_HOME=str(runtime / 'cache'), PYTHONNOUSERSITE='1',
            ACESTEP_PATH=str(home / 'tools/ACE-Step-1.5'),
            ACE_STEP_UI_PATH=str(home / 'tools/ace-step-ui'),
            ACESTEP_PYTHON=str(home / 'tools/ACE-Step-1.5/.venv/bin/python'),
            ACE_STEP_OUTPUT_DIR=str(output.parent), ACE_STEP_MODEL_CONFIG='acestep-v15-turbo',
            HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1'))

    def admit(self, plan, output) -> None:
        # Source hashes alone cannot qualify checkpoint bytes, init download/code-sync
        # suppression, imported dependencies/device/cache/resource envelope or host.
        # CF-MU1 explicitly leaves these decisions for later approved checks. No
        # boolean or fixture flag is interpreted as evidence for those missing gates.
        raise Fault('MUSIC_LIVE_UNQUALIFIED', 409)


class AceStep:
    id = 'ace-step-local'
    version = 1
    interface = 'ace-step-cue-v1'
    validation_profile = contract.PROFILE

    def describe(self):
        return dict(id=self.id, version=1, name='Local ACE-Step instrumental cue',
            interface_versions=[self.interface], operations=[contract.OPERATION], media=['Music'],
            input='Instrumental direction; integer 10-30 seconds (default 30), seed 42',
            output='Original native 48k stereo WAV plus disclosed PCM16 derivative',
            execution='owned_local_argv', destination='Private per-run allocation only',
            cost='Local; no paid/cloud fallback', use='Music rights and intended use unqualified',
            disclosure='Turbo, batch 1, 8 steps; no extra LM. Effective seed unverified.',
            restrictions='Source/offline only; live runtime/checkpoint/resource/initialization gates open')

    def prepare(self, snapshot, options, operation):
        return contract.parameters(snapshot, options, operation)

    def validate(self, plan):
        p = plan['parameters']
        options = {key:p[key] for key in ('seconds','seed','instrumental')}
        expected = self.prepare(dict(kind=plan['kind'], text=plan['direction']), options, plan['operation'])
        if (canonical(p) != canonical(expected) or type(plan['schema']) is not int or plan['schema'] != 2 or
                type(plan['candidates']) is not int or plan['candidates'] != 1 or
                plan['execution_kind'] != 'local_producer_tool' or plan['outputs'] != self.validation_profile or
                plan['adapter'] != self.id or type(plan['adapter_version']) is not int or plan['adapter_version'] != 1 or
                plan['binding']['adapter'] != self.id or plan['binding']['interface_version'] != self.interface or
                digest(plan['binding']) != plan['binding_digest']):
            raise Fault('PLAN_CONFLICT', 409)

    def runtime(self, record): return Runtime(record)

    def normal_runtime(self, record, scope): return Runtime(record, scope)

    def construct_dispatch(self, plan, output, runtime):
        """Pure inactive real recipe, testable without probing/launching the tool."""
        self.validate(plan)
        entry = Path(__file__).with_name('entry.py')
        argv = (sys.executable, '-I', str(entry), '--plan', canonical(plan), '--output', str(output))
        env = child_environment('music-bridge', dict(PYTHONNOUSERSITE='1', LANG='C.UTF-8', DO_NOT_TRACK='1'))
        return DispatchSpec(argv, env, validation_profile=self.validation_profile).validate()

    def build_dispatch(self, plan, output, runtime):
        self.validate(plan)
        runtime.admit(plan, output)
        runtime.verify_sources()
        return self.construct_dispatch(plan, output, runtime)

    def validate_dispatch(self, plan, output, effective, runtime):
        self.validate(plan)
        runtime.admit(plan, output)
        runtime.verify_sources()
        if effective != list(self.construct_dispatch(plan, output, runtime).argv):
            raise Fault('ARGUMENT_INVALID', 409)

    def normalize_observation(self, result): return normalize_exit(result)

    def validate_retirement_contract(self, plan):
        raise Fault('DETACHED_SURVIVOR_NOT_EXCLUDED', 409)

    def validate_native_output(self, data, raw, plan, output):
        self.validate(plan)
        value = receipt.parse(raw, plan, output)
        fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            native = read_leaf(fd, 'native.wav', MAX_BYTES)
        finally:
            os.close(fd)
        derivative, facts = pcm16(native, plan['parameters']['seconds'] * 48000)
        if (data != derivative or value['native'] != dict(facts, sha256=receipt.digest(native)) or
                value['derivative'] != dict(encoding='PCM', bits=16, channels=2, rate=48000,
                    frames=facts['frames'], bytes=len(data), sha256=receipt.digest(data))):
            raise Fault('MUSIC_LINEAGE_MISMATCH')
        return facts['frames']

    def collection_evidence(self, raw, plan, output):
        value = receipt.parse(raw, plan, output)
        return dict(native=value['native'], derivative=value['derivative'], conversion=value['conversion'],
                    seed_requested=value['seed_requested'], seed_effective=None, upstream=value['upstream'])

    def retain_evidence(self, store, row, output, raw):
        value = receipt.parse(raw, row['plan'], output)
        fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: native = read_leaf(fd, 'native.wav', MAX_BYTES)
        finally: os.close(fd)
        if receipt.digest(native) != value['native']['sha256']: raise Fault('OUTPUT_CHANGED')
        final = store.home / 'media' / (row['candidate'] + '.native.wav')
        if final.exists() or final.is_symlink():
            if read_private(final) != native: raise Fault('RETAINED_FILE_CORRUPT')
        else:
            atomic(final.parent, final.name, native)
            final.chmod(0o400)

    def validate_setup(self, proposal, file_digest, fixture_only):
        raise Fault('MUSIC_LIVE_UNQUALIFIED', 409)
