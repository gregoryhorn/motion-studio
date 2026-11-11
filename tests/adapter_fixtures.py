"""Two explicit TEST adapters; normal studio imports neither this module nor its workers."""
import hashlib
import json
from pathlib import Path
import sys
from typing import Literal
from pydantic import Field
from studio.domain import Strict, Fault
from studio.producer.catalog import Catalog
from studio.producer.contracts import DispatchSpec, normalize_exit
from studio.producer.stable_adapter import StableAudio


class FixtureA(StableAudio):
    id = 'test-stable-cli'

    def describe(self):
        return dict(super().describe(), name='TEST stable-shaped CLI', use='Synthetic offline test only')


class RenderOptions(Strict):
    frame_count: int = Field(ge=4410, le=44100)
    timbre: Literal['soft', 'bright']


class AssetReceipt(Strict):
    leaf: Literal['candidate.wav']
    length: int = Field(ge=1, le=16 * 1024 * 1024)
    sha256: str = Field(pattern='^[0-9a-f]{64}$')


class NativeInput(RenderOptions):
    description: str = Field(min_length=1, max_length=2000)


class RenderReceipt(Strict):
    schema_version: Literal[1] = Field(alias='schema')
    asset: AssetReceipt
    input: NativeInput
    provenance: Literal['synthetic-not-generated']


class FixtureB:
    id = 'test-render-cli'
    version = 1
    interface = 'test-render-v1'
    validation_profile = 'stereo-44100-pcm16'

    def describe(self):
        return dict(id=self.id, version=1, name='TEST render CLI', interface_versions=[self.interface],
                    operations=['render-sfx'], media=['Sound effects'], input='Description; typed frame count and timbre',
                    output='One stereo 44100 Hz PCM16 WAV', execution='owned_local_argv',
                    destination='Local isolated test staging; no network', cost='No external calls',
                    use='Synthetic offline test only', disclosure='TEST interface; not a real supported app',
                    restrictions='4410-44100 frames; soft/bright timbre; no model, seed or negative option')

    def prepare(self, snapshot, options, operation):
        if operation != 'render-sfx' or snapshot['kind'] != 'Sound effects':
            raise Fault('UNSUPPORTED_OPERATION', 409)
        NativeInput(description=snapshot['text'], **options)
        return RenderOptions(**options).model_dump()

    def validate(self, plan):
        if plan['schema'] != 2 or plan['operation'] != 'render-sfx':
            raise Fault('PLAN_CONFLICT', 409)
        NativeInput(description=plan['direction'], **plan['parameters'])

    def runtime(self, record):
        return record

    def build_dispatch(self, plan, output, runtime):
        self.validate(plan)
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(output.parent), 'TMPDIR': str(output.parent)}
        value = plan['parameters']
        return DispatchSpec((runtime['executable'], 'render', '--description', plan['direction'],
                             '--frame-count', str(value['frame_count']), '--timbre', value['timbre'],
                             '--target', str(output)), environment).validate()

    def validate_dispatch(self, plan, output, effective, runtime):
        if effective != list(self.build_dispatch(plan, output, runtime).argv):
            raise Fault('ARGUMENT_INVALID')
        if hashlib.sha256(Path(runtime['executable']).read_bytes()).hexdigest() != runtime['file_digest']:
            raise Fault('RUNTIME_DRIFT', 409)

    def normalize_observation(self, result):
        return normalize_exit(result)

    def validate_native_output(self, data, raw, plan, output):
        try:
            value = RenderReceipt.model_validate_json(raw)
        except ValueError:
            raise Fault('RECEIPT_INVALID') from None
        # model_validate_json alone accepts duplicate JSON keys: refuse explicitly.
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise Fault('RECEIPT_INVALID')
                result[key] = item
            return result
        json.loads(raw, object_pairs_hook=unique)
        expected = dict(description=plan['direction'], **plan['parameters'])
        if (value.asset.sha256 != hashlib.sha256(data).hexdigest() or value.asset.length != len(data)
                or value.input.model_dump() != expected or value.asset.leaf != output.name):
            raise Fault('RECEIPT_MISMATCH')
        return value.input.frame_count

    def validate_setup(self, proposal, file_digest, fixture_only):
        if not fixture_only or proposal.interface_version != self.interface:
            raise Fault('UNSUPPORTED_INTERFACE', 409)
        return dict(interface=self.interface, executable_digest=file_digest)


class OfflineCatalog(Catalog):
    test_only = True

    def __init__(self):
        super().__init__()
        for adapter in (FixtureA(), FixtureB()):
            self.adapters[(adapter.id, adapter.version)] = adapter


def worker_location(root, adapter, mode='good'):
    root.mkdir(parents=True, exist_ok=True)
    source = 'producer_fixture_child.py' if adapter.id == FixtureA.id else 'render_fixture_child.py'
    path = root / 'fixture-worker'
    text = Path(__file__).with_name(source).read_text()
    path.write_text('#!' + sys.executable + '\n' + text.split('\n', 1)[1])
    path.chmod(0o700)
    (root / 'mode').write_text(mode)
    return path


def setup(runs, adapter, location, binding=None, expected=0) -> dict:
    record = runs.bindings.save(dict(adapter=adapter.id, adapter_version=1,
        interface_version=adapter.interface, executable=str(location)), permitted={str(location)},
        binding=binding, expected=expected, fixture_only=True)
    return runs.bindings.revise(record['id'], record['revision'], enabled=True,
        qualification='Offline tested only', availability='Unavailable', reason='OFFLINE_ONLY', action='Review offline fixture evidence')
