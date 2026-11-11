"""Concrete first shipped adapter. Stable Audio details stop at this module family."""
from dataclasses import dataclass, field
from pathlib import Path
from ..child_env import child_environment
from ..domain import Fault, Strict
from pydantic import Field
from ..producer import local_sfx as sfx
from ..producer.contracts import DispatchSpec, normalize_exit


class Options(Strict):
    seconds: float = Field(default=3, ge=0.1, le=10, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0, le=4294967295)
    language: str = 'en'


@dataclass(frozen=True)
class RevisionRuntime(sfx.Binding):
    record: dict = field(default_factory=dict)

    def pins(self):
        return self.record['pins']

    def executable(self):
        return Path(self.record['executable'])

    def admit(self, plan, output):
        if not self.fixture_only:
            raise Fault('FEATURE_DISABLED', 409)
        sfx.check_pins({str(self.executable()): self.record['file_digest']})


class StableAudio:
    id = 'stable-audio-local'
    version = 1
    interface = 'stable-audio-cli-v1'
    validation_profile = 'stereo-44100-pcm16'

    def describe(self):
        return dict(id=self.id, version=self.version, name=sfx.METHOD,
                    interface_versions=[self.interface], operations=['sfx'], media=['Sound effects'],
                    input='English direction, 0.1-10 seconds; typed seed',
                    output='One stereo 44100 Hz PCM16 WAV', execution='owned_local_argv',
                    destination='Local application staging; no external transfer', cost='Free/local preferred; no paid fallback',
                    use='Eligibility unqualified; no commercial clearance', disclosure=sfx.DISCLOSURE,
                    restrictions='100 steps; fixed negative; wrapper peak limiting; no collector normalization')

    def prepare(self, snapshot, options, operation):
        value = Options(**options)
        if snapshot['kind'] != 'Sound effects' or value.language != 'en':
            raise Fault('UNSUPPORTED_OPERATION', 409)
        if not snapshot['text'].strip() or len(snapshot['text']) > 2000:
            raise Fault('ARGUMENT_INVALID')
        if operation != 'sfx':
            raise Fault('UNSUPPORTED_OPERATION', 409)
        return dict(**value.model_dump(), steps=100, negative=sfx.NEGATIVE, model=sfx.MODEL,
                    model_revision=sfx.REVISION, format='stereo-44100-PCM16',
                    use='Eligibility must be qualified; no commercial clearance')

    def validate(self, plan):
        sfx.validate_plan(sfx.legacy_view(plan))

    def runtime(self, record):
        return RevisionRuntime(record=record, fixture_only=record['fixture_only'])

    def build_dispatch(self, plan, output, runtime):
        runtime.admit(plan, output)
        return DispatchSpec(tuple(sfx.vector(runtime.executable(), plan, output)),
                            runtime.environment(output.parent)).validate()

    def validate_dispatch(self, plan, output, effective, runtime):
        self.validate(plan)
        runtime.final(plan, output, effective)

    def normalize_observation(self, result):
        return normalize_exit(result)

    def runtime_environment(self, environment, directory):
        # Read-only evidence found ~/.nv/ComputeCache, CUDA's documented default.
        # Keep this known cache in runtime; do not infer which process created it.
        value = child_environment('stable-audio-local', environment)
        value['CUDA_CACHE_PATH'] = str(directory / 'cache' / 'cuda')
        return value

    def validate_retirement_contract(self, plan):
        binding = plan['binding']
        if (binding['fixture_only'] or binding['executable'] != str(sfx.WRAPPER)
                or binding['file_digest'] != sfx.FILE_PINS[str(sfx.WRAPPER)]):
            raise Fault('DETACHED_SURVIVOR_NOT_EXCLUDED', 409)
        # The pinned wrapper/bootstrap contract is synchronous and non-detaching.
        sfx.check_pins({str(sfx.WRAPPER): binding['file_digest']})

    def validate_native_output(self, data, raw, plan, output):
        return sfx.native_output(data, raw, plan, output)

    def validate_setup(self, proposal, file_digest, fixture_only):
        if proposal.interface_version != self.interface:
            raise Fault('UNSUPPORTED_INTERFACE', 409)
        if not fixture_only and file_digest != sfx.FILE_PINS[str(sfx.WRAPPER)]:
            raise Fault('UNSUPPORTED_VERSION', 409)
        return dict(route='stable-audio-local-v1', wrapper=proposal.executable,
                    runtime=str(sfx.ROOT / 'venv/bin/python'), model_revision=sfx.REVISION,
                    files={**sfx.FILE_PINS, **({} if fixture_only else sfx.model_pins()), proposal.executable: file_digest})
