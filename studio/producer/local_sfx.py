"""Fixed local tool binding. Production admission is deliberately disabled."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Literal
from pydantic import Field
from ..child_env import child_environment
from ..domain import Strict, Fault

WRAPPER = Path.home() / '.hermes/profiles/video/tools/bin/stable-audio'
ROOT = Path.home() / '.hermes/profiles/video/tools/stable-audio-open'
MODEL = 'stabilityai/stable-audio-open-1.0'
REVISION = 'f21265c1e2710b3bd2386596943f0007f55f802e'
NEGATIVE = 'Low quality, distorted, music, speech, voices'
METHOD = 'Local Stable Audio - existing video producer tool'
DISCLOSURE = 'Direct local tool route; no Hermes agent conversation'
FILE_PINS = {
    str(WRAPPER): 'f26db6337f33e09e3ff38d646fbd72a025e080aefb8b011625eccd0d9cd57dea',
    str(ROOT / 'audio.py'): '5e26a2f8afb0f3dc0fa1bbd1a16766b840584b82ca803f972f8b6eb4106b2b7f',
    str(ROOT / 'venv/bin/python'): '6759dcc6aa5a3fe3377349092f92f6700f1f79017294c1d0085009eb8802cb1e',
}


class PrepareSFX(Strict):
    command: str
    request: str
    revision: int = Field(ge=1)
    seconds: float = Field(ge=0.1, le=10, allow_inf_nan=False)
    seed: int = Field(ge=0, le=4294967295)
    language: Literal['en'] = 'en'


def fingerprint(value):
    return hashlib.sha256(value).hexdigest()


def model_pins():
    values = json.loads(Path(__file__).with_name('stable_model_pins.json').read_text())
    return {str(ROOT / 'model' / name): value for name, value in values.items()}


def vector(executable, plan, output):
    """The sole tool vector; creative text remains a single argv element."""
    plan = legacy_view(plan)
    return [str(executable), 'generate', '--prompt', plan['direction'], '--negative',
            NEGATIVE, '--seconds', repr(plan['seconds']), '--steps', '100',
            '--seed', str(plan['seed']), '--out', str(output)]


def validate_plan(plan):
    expected = {'schema', 'request', 'revision', 'snapshot', 'kind', 'direction', 'purpose',
                'seconds', 'steps', 'seed', 'negative', 'language', 'model', 'model_revision',
                'binding', 'execution_kind', 'candidates', 'format', 'use'}
    if set(plan) != expected or plan['kind'] != 'Sound effects':
        raise Fault('PLAN_CONFLICT', 409)
    PrepareSFX(command='0' * 32, request=plan['request'], revision=plan['revision'],
               seconds=plan['seconds'], seed=plan['seed'], language=plan['language'])
    if not isinstance(plan['direction'], str) or not plan['direction'].strip() or len(plan['direction']) > 2000:
        raise Fault('ARGUMENT_INVALID')
    if (plan['steps'], plan['negative'], plan['model'], plan['model_revision'],
        plan['execution_kind'], plan['schema'], plan['candidates'], plan['format']) != (
        100, NEGATIVE, MODEL, REVISION, 'local_producer_tool', 1, 1, 'stereo-44100-PCM16'):
        raise Fault('PLAN_CONFLICT', 409)


@dataclass(frozen=True)
class Binding:
    """No live enable switch or credential discovery. Tests supply a separate subclass."""
    fixture_only: bool = False

    def pins(self):
        # This describes a disabled binding without resolving or executing producer files.
        return {'route': 'stable-audio-local-v1', 'qualification': 'disabled-unqualified',
                'wrapper': str(WRAPPER), 'runtime': str(ROOT / 'venv/bin/python'),
                'model_revision': REVISION, 'files': dict(FILE_PINS)}

    def executable(self):
        return WRAPPER

    def environment(self, directory):
        return child_environment('stable-audio-local', {'HOME': str(directory), 'TMPDIR': str(directory),
                'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1'})

    def admit(self, plan, output) -> None:
        # No real wrapper/model is resolved, probed, imported or started in this candidate.
        raise Fault('FEATURE_DISABLED', 409)

    def final(self, plan, output, argv):
        plan = legacy_view(plan)
        validate_plan(plan)
        if plan['binding'] != self.pins() or argv != vector(self.executable(), plan, output):
            raise Fault('ARGUMENT_INVALID')
        self.admit(plan, output)


def check_pins(pins):
    """Exact file pins for a later reviewed binding; never downloads or repairs."""
    for name, expected in pins.items():
        path = Path(name)
        if not path.is_file():
            raise Fault('RUNTIME_DRIFT', 409)
        try:
            with path.open('rb') as stream:
                before = os.fstat(stream.fileno())
                observed = hashlib.file_digest(stream, 'sha256').hexdigest()
                after = os.fstat(stream.fileno())
            if (observed != expected or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                raise Fault('RUNTIME_DRIFT', 409)
        except OSError:
            raise Fault('RUNTIME_DRIFT', 409) from None


def eligible_resources(free_mib, use_allowed, disk_bytes, conflict=False):
    if not use_allowed:
        raise Fault('USE_RESTRICTED', 409)
    if not math.isfinite(free_mib) or free_mib < 8192 or conflict:
        raise Fault('RESOURCE_BUSY', 409)
    if disk_bytes < 64 * 1024 * 1024:
        raise Fault('STORAGE_UNAVAILABLE', 503)


def legacy_view(plan) -> dict:
    if plan['schema'] == 1:
        return plan
    shared = {key: plan[key] for key in ('request', 'revision', 'snapshot', 'kind', 'direction', 'purpose')}
    return dict(shared, **plan['parameters'], schema=1, binding=plan['binding']['pins'],
                execution_kind='local_producer_tool', candidates=1)


RECEIPT_FIELDS = {'model', 'revision', 'prompt', 'negative_prompt', 'seconds', 'sample_rate',
                  'channels', 'steps', 'seed', 'output', 'elapsed_seconds', 'peak_before_gain',
                  'gain', 'rms_before_gain', 'gpu_peak_allocated_mib', 'perceptual_review',
                  'commercial_clearance'}


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Fault('RECEIPT_INVALID')
        result[key] = value
    return result


def native_output(data, raw, plan, output):
    plan = legacy_view(plan)
    try:
        receipt = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=lambda value: None)
        if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
            raise Fault('RECEIPT_INVALID')
        frames = round(plan['seconds'] * 44100)
        expected = dict(model=MODEL, revision=REVISION, prompt=plan['direction'],
                        negative_prompt=NEGATIVE, seconds=frames / 44100, sample_rate=44100,
                        channels=2, steps=100, seed=plan['seed'], output=str(output))
        for key, value in expected.items():
            if type(receipt[key]) is bool or receipt[key] != value:
                raise Fault('RECEIPT_MISMATCH')
        for key in ('elapsed_seconds', 'peak_before_gain', 'gain', 'rms_before_gain', 'gpu_peak_allocated_mib'):
            value = receipt[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise Fault('RECEIPT_INVALID')
        if receipt['gain'] > 1 or receipt['perceptual_review'] != 'not performed' or receipt[
                'commercial_clearance'] != 'not established; see bundled LICENSE.md':
            raise Fault('RECEIPT_INVALID')
        return frames
    except (ValueError, TypeError, KeyError, RecursionError):
        raise Fault('RECEIPT_INVALID') from None
