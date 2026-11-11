"""Explicit test-only Music admission and deterministic child. No installed producer."""
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import pydantic
from studio.domain import Fault
from studio.native.creation.policy import MusicAssociation
from studio.producer.music.adapter import AceStep, Runtime
from studio.producer.music.admission import POLICY
from studio.producer.contracts import DispatchSpec
from studio.persistence.primitives import canonical
from tests.creation_support import setup as sfx_setup, settle

ROOT = Path(__file__).resolve().parents[1]


class FixtureRuntime(Runtime):
    def admit(self, plan, output):
        if not self.record['fixture_only'] or self.scope is None: raise Fault('FIXTURE_DENIED')
        self.scope.check_plan(plan)
        for name, digest in self.record['pins']['files'].items():
            path = Path(name)
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise Fault('RUNTIME_DRIFT')


class FixtureAdapter(AceStep):
    def normal_runtime(self, record, scope): return FixtureRuntime(record, scope)

    def vector(self, plan, output, runtime):
        return [runtime.record['executable'], str(ROOT), canonical(plan), str(output)]

    def build_dispatch(self, plan, output, runtime):
        self.validate(plan); runtime.admit(plan, output)
        env = dict(PATH='/usr/bin:/bin', HOME=str(output.parent), TMPDIR=str(output.parent),
                   PYTHONNOUSERSITE='1', LANG='C.UTF-8')
        return DispatchSpec(tuple(self.vector(plan, output, runtime)), env,
                            validation_profile=self.validation_profile).validate()

    def validate_dispatch(self, plan, output, effective, runtime):
        if effective != list(self.build_dispatch(plan, output, runtime).argv): raise Fault('ARGUMENT_INVALID')


def setup(root, mode='good', *, effects=True):
    ctx, runtime, sfx = sfx_setup(root)
    path = attach(runtime, root, mode=mode, effects=effects)
    ctx.methods['creation.admit']({}, session_id='canonical-root')
    ctx.methods['creation.admit_music']({}, session_id='canonical-root')
    return ctx, runtime, path


def attach(runtime, root, mode='good', *, effects=True):
    adapter = FixtureAdapter()
    runtime.runs.catalog.adapters[(adapter.id, adapter.version)] = adapter
    runtime.runs.bindings.allow_fixtures = True
    path = root / 'music-fixture' / 'child'
    path.parent.mkdir(parents=True)
    text = Path(__file__).with_name('music_fixture_child.py').read_text()
    # The closed child disables user-site discovery. Pin the already imported
    # test dependency directory explicitly; never inherit PYTHONPATH or secrets.
    dependency_root = str(Path(pydantic.__file__).resolve().parents[1])
    text = text.replace('sys.path.insert(0, sys.argv[1])',
                        'sys.path.insert(0, sys.argv[1]); sys.path.append(' + repr(dependency_root) + ')')
    path.write_text('#!' + sys.executable + '\n' + text.split('\n', 1)[1]); path.chmod(0o700)
    (path.parent / 'mode').write_text(mode)
    files = [path, *sorted((ROOT / 'studio/producer/music').glob('*.py'))]
    pins = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    record = runtime.runs.bindings.put(dict(adapter=adapter.id, adapter_version=1,
        interface_version=adapter.interface, executable=str(path), pins=dict(files=pins),
        file_digest=pins[str(path)], fixture_only=True, enabled=True, qualification='Offline tested only',
        availability='Unavailable', reason='OFFLINE_ONLY', action='Synthetic evidence only',
        capabilities=adapter.describe(), evaluation_scope=POLICY))
    runtime.policy = replace(runtime.policy, music=type(runtime.policy.music)(revision='music-source-fixture-v1',
        prepare=True, effects=effects, binding=record['id'], binding_revision=record['revision']))
    return path


def effects(runtime):
    return list((runtime.store.home / 'staging').glob('sfx-*/fixture-effects'))


def effect_count(runtime):
    return sum(len(path.read_text().splitlines()) for path in effects(runtime))


def command(row): return {k:row[k] for k in ('request','revision','command','run')}
