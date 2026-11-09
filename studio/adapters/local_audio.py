"""Reusable owned CLI audio connector; ACE-Step and Stable Audio are bindings.

Trusted descriptors map closed schemas to argv and receipts. Prompt artifacts can
never supply commands, output paths or transport code. The existing Adapter ABI,
NativeRuntime and WorkerContext own policy, process groups, cancel and collection.
Discovery only stats local files: presence is not model qualification. No fallback,
installation, model imports, progress guesses, telemetry server or GPU inference.
"""
from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import wave
from typing import Any, Callable

from ..contracts import BOOL, TEXT, ContractError, digest, integer, nullable, obj, validate
from . import alternative

MUSIC_ID = 'local.ace-step-music'
SFX_ID = 'local.stable-audio-open'
OP = 'audio.generate@1'
PROMPT_SCHEMA = 'motion/v1/local-audio-prompt'
MUSIC_PROMPT = obj(dict(schema={'const': PROMPT_SCHEMA}, kind={'const': 'music'},
    prompt=TEXT, steps=integer(1, 100), instrumental=BOOL, lyrics=TEXT))
SFX_PROMPT = obj(dict(schema={'const': PROMPT_SCHEMA}, kind={'const': 'sfx'},
    prompt=TEXT, steps=integer(1, 300), negative_prompt=TEXT))



def _music_paths():
    home = Path.home()
    root = Path(os.environ.get('ACESTEP_PATH', str(home/'tools/ACE-Step-1.5')))
    ui = Path(os.environ.get('ACE_STEP_UI_PATH', str(home/'tools/ace-step-ui')))
    cli = Path(os.environ.get('MOTION_ACE_STEP_MUSIC', str(home/'.local/bin/ace-step-music')))
    python = Path(os.environ.get('ACESTEP_PYTHON', str(root/'.venv/bin/python')))
    files = [ui/'server/scripts/simple_generate.py'] + [root/'checkpoints'/p for p in (
        'acestep-v15-turbo/config.json', 'acestep-v15-turbo/model.safetensors',
        'vae/config.json', 'vae/diffusion_pytorch_model.safetensors',
        'Qwen3-Embedding-0.6B/config.json', 'Qwen3-Embedding-0.6B/model.safetensors',
        'Qwen3-Embedding-0.6B/tokenizer.json')]
    return cli, python, files


def _sfx_paths():
    home = Path.home()
    root = Path(os.environ.get('MOTION_STABLE_AUDIO_ROOT', str(home/'.local/share/motion-studio/engines/stable-audio-open')))
    cli = Path(os.environ.get('MOTION_STABLE_AUDIO', str(home/'.local/bin/stable-audio')))
    return cli, root/'venv/bin/python', [root/'audio.py'] + [root/'model'/p for p in (
        'model_index.json', 'transformer/diffusion_pytorch_model.safetensors',
        'vae/diffusion_pytorch_model.safetensors', 'text_encoder/model.safetensors',
        'projection_model/diffusion_pytorch_model.safetensors', 'tokenizer/tokenizer_config.json',
        'scheduler/scheduler_config.json')]


def _music_argv(cli, controls, params, out):
    return [str(cli), '--prompt', controls['prompt'], '--lyrics', controls['lyrics'],
        *(['--instrumental'] if controls['instrumental'] else []),
        '--duration', str(params['duration_samples']//params['sample_rate']),
        '--infer-steps', str(controls['steps']), '--seed', str(params['seed'] if params['seed'] is not None else -1),
        '--batch-size', '1', '--audio-format', 'wav', '--model-config', 'acestep-v15-turbo',
        '--no-cot-metas', '--no-cot-caption', '--no-cot-language',
        '--output-dir', str(out/'engine'), '--json']


def _sfx_argv(cli, controls, params, out):
    return [str(cli), 'generate', '--prompt', controls['prompt'],
        '--negative', controls['negative_prompt'], '--seconds', str(params['duration_samples']/params['sample_rate']),
        '--steps', str(controls['steps']), '--seed', str(params['seed'] if params['seed'] is not None else 0),
        '--out', str(out/'engine'/'audio.wav')]


def _stdout_receipt(stdout):
    """Accept CLI log prefixes and either compact or multiline final JSON."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char == '{' and (index == 0 or stdout[index-1] == '\n'):
            try:
                value, end = decoder.raw_decode(stdout[index:])
                if isinstance(value, dict) and not stdout[index+end:].strip():
                    return value
            except ValueError:
                pass
    raise ValueError('Missing or malformed final CLI JSON receipt')


def _music_output(stdout, out):
    receipt = _stdout_receipt(stdout)
    if receipt.get('success') is not True or not isinstance(receipt.get('audio_paths'), list) or len(receipt['audio_paths']) != 1:
        raise ValueError('ACE-Step must return success and exactly one real audio_paths entry')
    return receipt, receipt['audio_paths'][0]


def _sfx_output(stdout, out):
    receipt = _stdout_receipt(stdout)
    sidecar = _owned_file(out/'engine'/'audio.wav.json', out)
    if sidecar.stat().st_size > 1024*1024 or json.loads(sidecar.read_text()) != receipt:
        raise ValueError('Stable Audio sidecar differs from stdout receipt')
    if not receipt.get('model') or not receipt.get('revision'):
        raise ValueError('Stable Audio receipt lacks actual model/revision')
    return receipt, receipt['output']


@dataclass(frozen=True)
class CliAudioBinding:
    """Extension seam: add a trusted binding, not NativeRuntime/job branches.

    Supply passive path requirements, exact controls, bounded timing, argv builder
    and real receipt/output extractor. argv is always a list, never a shell. Other
    Hermes/MCP transports should use the existing host bridge/Adapter ABI; this
    connector intentionally implements only owned one-shot local CLI audio.
    """
    kind: str
    label: str
    paths: Callable
    argv: Callable
    output: Callable
    controls: dict
    sample_rate: int
    minimum_samples: int
    maximum_samples: int
    integral_seconds: bool = False
    gpu_vram_bytes: int | None = None
    model_identity: str | None = None


BINDINGS = {
    MUSIC_ID: CliAudioBinding('music', 'ACE-Step local music', _music_paths, _music_argv,
        _music_output, MUSIC_PROMPT, 48000, 48000, 75*48000, True,
        model_identity='acestep-v15-turbo'),
    SFX_ID: CliAudioBinding('sfx', 'Stable Audio Open local SFX', _sfx_paths, _sfx_argv,
        _sfx_output, SFX_PROMPT, 44100, 4410, 47*44100, gpu_vram_bytes=8*1024**3,
        model_identity='stable-audio-open'),
}
ADAPTER_IDS = tuple(BINDINGS)


def discover(aid):
    cli, python, files = BINDINGS[aid].paths()
    executable = cli.is_absolute() and cli.is_file() and os.access(cli, os.X_OK)
    runtime = python.is_absolute() and python.is_file() and os.access(python, os.X_OK)
    missing = [str(p) for p in files if not p.is_absolute() or not p.is_file() or p.stat().st_size == 0]
    decoders = all(shutil.which(n) for n in ('ffmpeg', 'ffprobe'))
    return dict(executable=str(cli), executable_present=executable,
        runtime_present=runtime, missing_files=missing, decoders_present=decoders,
        available=bool(executable and runtime and not missing and decoders))


def registration(aid):
    binding = BINDINGS[aid]
    meta = alternative.registration(alternative.ESPEAK_ID)
    dec = meta['declaration']
    cli, python, files = binding.paths()
    req, res = f'motion/v1/{aid}/request', f'motion/v1/{aid}/result'
    dec.update(adapter_id=aid, label=binding.label)
    dec['operations'][0].update(operation=OP, request_schema=req, result_schema=res, default_timeout_seconds=1800)
    dec['operations'][0]['constraints'].update(media_types=['text/plain', 'audio/wav'], languages=[])
    dec['dependencies'] = [dict(name=str(cli), kind='executable', version_constraint=None, required=True)]
    dec['resource_needs'].update(gpu_vram_bytes=binding.gpu_vram_bytes, exclusive_resource='local-audio-gpu')
    params = obj(dict(kind={'const': binding.kind},
        duration_samples=integer(binding.minimum_samples, binding.maximum_samples),
        sample_rate={'const': binding.sample_rate}, seed=nullable(integer(0, 4294967295))))
    old_result = next(v for k, v in meta['schemas'].items() if k.endswith('-result'))
    meta['schemas'] = {req: params, res: old_result, PROMPT_SCHEMA: binding.controls}
    meta['outputs'] = {OP: [dict(port='audio', kind='audio', media_type='audio/wav')]}
    # Speech metadata from the shared result envelope is not audio.generate
    # authority. Publish only this binding's real artifact-controls schema.
    meta['option_metadata'] = {OP: {
        'identities': {'provider': 'local', 'model': binding.model_identity},
        'schema_roles': {PROMPT_SCHEMA: 'artifact_controls'},
        'unsupported_controls': ['voice', 'reference_cloning']}}
    # Small public scripts are hashed; model file presence/size/mtime is observed,
    # not a claimed model-content digest or measured model identity.
    observations = [dict(path=str(p), size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns)
                    if p.is_file() else dict(path=str(p), missing=True) for p in files]
    mappings = {}
    for name in ('paths', 'argv', 'output'):
        function = getattr(binding, name)
        source = inspect.getsourcefile(function)
        if source is None:
            raise ValueError('Trusted CLI mappings need inspectable source files')
        mappings[name] = dict(symbol=function.__qualname__, source_file=str(Path(source).resolve()),
                             source_sha256=alternative.file_digest(source))
    meta['implementation_sha256'] = digest(dict(adapter=alternative.file_digest(__file__),
        mappings=mappings,
        descriptor=dict(kind=binding.kind, label=binding.label, sample_rate=binding.sample_rate,
                        minimum_samples=binding.minimum_samples, maximum_samples=binding.maximum_samples,
                        integral_seconds=binding.integral_seconds, gpu_vram_bytes=binding.gpu_vram_bytes,
                        model_identity=binding.model_identity),
        executable=str(cli), executable_sha256=alternative.file_digest(cli) if cli.is_file() else None,
        entrypoints={str(p): alternative.file_digest(p) for p in files if p.suffix == '.py' and p.is_file()},
        python=str(python), required_file_observations=observations))
    return meta


def _owned_file(path, root):
    """Reject escapes and every symlink component before opening engine outputs."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root/candidate
    if '..' in candidate.parts:
        raise ValueError('Parent traversal in engine result')
    relative = candidate.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor/part
        if cursor.is_symlink():
            raise ValueError('Symlink in engine result')
    if not candidate.is_file() or candidate.stat().st_size <= 0 or candidate.stat().st_nlink != 1:
        raise ValueError('Missing, empty, or hardlinked engine output')
    if candidate.stat().st_size > 64*1024*1024:
        raise ValueError('Engine output exceeds 64 MiB bound')
    return candidate


class LocalAudioConnector:
    def validate_request(self, registry, binding, request):
        aid = binding['adapter_id']
        if aid not in BINDINGS or request['operation'] != OP:
            raise ContractError('UNSUPPORTED_OPERATION', 'Unsupported local audio binding/operation')
        expected = registry.binding(aid, OP, request['parameters'], request.get('binding_parameters'))
        if binding != expected or registration(aid)['implementation_sha256'] != expected['implementation_sha256']:
            raise ContractError('HASH_MISMATCH', 'Selected local CLI/schema/config identity changed')
        validate(request['parameters'], registration(aid)['schemas'][f'motion/v1/{aid}/request'])
        if request.get('binding_parameters') is not None:
            raise ContractError('UNSUPPORTED_OPERATION', 'Local CLI accepts only its frozen prompt controls')
        if not discover(aid)['available']:
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Local CLI, runtime/model files or audio decoder absent')

    def validate_timing(self, project_id, request, metadata, documents, *, resolve_artifact):
        binding = BINDINGS[request['adapter_id']]
        params = request['parameters']
        if binding.integral_seconds and params['duration_samples'] % params['sample_rate']:
            raise ContractError('UNSUPPORTED_OPERATION', 'This CLI supports whole seconds only; sample-exact generation is unsupported')
        prompt = metadata['prompt'][0]
        if prompt['media_type'] != 'text/plain' or prompt['size_bytes'] > 32768:
            raise ContractError('INVALID_ARGUMENT', 'Local audio controls require bounded text/plain JSON')
        value = request['inputs']['prompt']
        pin = value.get('artifact', value)
        source = Path(resolve_artifact(pin))
        raw = source.read_bytes()
        if alternative.file_digest(source) != pin['sha256']:
            raise ContractError('HASH_MISMATCH', 'Pinned prompt controls changed')
        controls = json.loads(raw)
        validate(controls, binding.controls)
        if not controls['prompt'].strip() or any(ord(c) < 32 and c not in '\n\r\t' for c in controls['prompt']):
            raise ContractError('INVALID_ARGUMENT', 'Empty or control-containing prompt')
        if controls.get('instrumental') and controls.get('lyrics'):
            raise ContractError('INVALID_ARGUMENT', 'Instrumental lyrics would be silently ignored by the CLI')
        return []

    def execute(self, request, *, project_root, attempt, input_resolver, registry,
                output_probe=None, artifact_store=None, project_id=None, run_process=None):
        root = Path(project_root).resolve()
        out = root/attempt['output_dir']
        started = False
        created = False
        result: dict[str, Any]
        feedback: dict[str, Any] = dict(schema='motion/v1/local-audio-feedback', adapter_id=request['binding']['adapter_id'],
            binding=request['binding'], requested_parameters=request['parameters'],
            job_id=attempt['job_id'], attempt_id=attempt['attempt_id'], node_id=attempt['node_id'],
            returncode=None, elapsed_ms=0,
            progress='unsupported', cancellation='owned process-group cancellation; engine resume unsupported',
            claims=dict(deterministic=False, sample_exact_generation=False, perceptual_review=False))
        clock = time.monotonic()
        try:
            if run_process is None or output_probe is None:
                raise ValueError('Owned WorkerContext runner and output validator required')
            out.relative_to(root)
            if '..' in Path(attempt['output_dir']).parts or any(p.is_symlink() for p in [out, *out.parents] if p != root.parent):
                raise ValueError('Unsafe owned attempt directory')
            if out.exists():
                raise ValueError('Preexisting attempt output refused')
            aid = request['binding']['adapter_id']
            self.validate_request(registry, request['binding'], request)
            spec = BINDINGS[aid]
            pin = request['inputs']['prompt']
            prompt_path = Path(input_resolver(pin))
            raw = prompt_path.read_bytes()
            if len(raw) > 32768:
                raise ValueError('Prompt controls exceed bound')
            controls = json.loads(raw)
            validate(controls, spec.controls)
            self.validate_timing(project_id, dict(request, adapter_id=aid), dict(prompt=[dict(
                media_type='text/plain', size_bytes=len(raw))]),
                {}, resolve_artifact=lambda _: prompt_path)
            out.mkdir(parents=True, exist_ok=False)
            created = True
            (out/'engine').mkdir()
            (out/'prompt.txt').write_bytes(raw)
            feedback['prompt_artifact'] = pin
            cli, _, _ = spec.paths()
            argv = ['/usr/bin/env', 'HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1',
                'HF_HUB_DISABLE_TELEMETRY=1', 'DO_NOT_TRACK=1', 'ACE_STEP_OUTPUT_DIR='+str(out/'engine'),
                *spec.argv(cli, controls, request['parameters'], out)]
            feedback['argv'] = argv
            feedback['readiness'] = discover(aid)
            from datetime import datetime, timezone
            deadline = datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00'))
            def run(args, **kwargs):
                remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    raise TimeoutError('Owned audio attempt deadline exceeded')
                return run_process(args, timeout=max(.001, remaining), check=False, **kwargs)
            started = True
            engine_run = run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            stdout = engine_run.stdout.decode('utf-8', errors='replace')
            (out/'engine.log').write_bytes(engine_run.stdout)
            feedback['returncode'] = engine_run.returncode
            if engine_run.returncode:
                raise RuntimeError('CLI failed with exit ' + str(engine_run.returncode) + '; inspect engine.log')
            receipt, actual = spec.output(stdout, out)
            feedback['engine_receipt_json'] = json.dumps(receipt, ensure_ascii=False)
            source = _owned_file(actual, out)
            if source.suffix.lower() != '.wav':
                raise ValueError('Engine receipt does not name a WAV')
            feedback['engine_output_relative_path'] = str(source.relative_to(out))
            feedback['engine_output_sha256'] = alternative.file_digest(source)
            probed = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(source)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (out/'source-probe.log').write_bytes(probed.stderr)
            if probed.returncode:
                raise ValueError('Engine WAV source probe failed')
            facts = json.loads(probed.stdout)
            feedback['source_probe_json'] = probed.stdout.decode('utf-8')
            streams = facts.get('streams', [])
            if facts.get('format', {}).get('format_name') != 'wav' or len(streams) != 1:
                raise ValueError('Engine output must be one WAV audio stream')
            stream = streams[0]
            rate, channels = int(stream['sample_rate']), int(stream['channels'])
            source_samples = int(stream['duration_ts'])
            if (stream['codec_type'] != 'audio' or stream['codec_name'] not in
                    ('pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'pcm_f32le', 'pcm_f64le')
                    or rate != spec.sample_rate or channels not in (1, 2)
                    or stream['time_base'] != f'1/{rate}' or not 0 < source_samples <= spec.maximum_samples):
                raise ValueError('Engine WAV source violates PCM/rate/channel/duration bounds')
            if stream['codec_name'].startswith('pcm_f'):
                # Integer quantization can conceal NaN/Inf as nonzero samples.
                # Inspect the actual float source before any conversion.
                from array import array
                import math
                decoded = run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-i', str(source),
                    '-map', '0:a:0', '-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                floats = array('f')
                floats.frombytes(decoded.stdout)
                if decoded.returncode or len(floats) != source_samples*channels or not all(math.isfinite(v) for v in floats):
                    raise ValueError('Nonfinite, truncated or invalid float WAV source')
            # ACE-Step may emit float WAV. Explicit PCM16 quantization changes
            # bytes, not duration/rate. No trim, resampling or exact-time claim.
            target = out/'audio.wav'
            conformed = run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-n', '-i', str(source),
                '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', str(target)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (out/'conform.log').write_bytes(conformed.stderr)
            if conformed.returncode:
                raise ValueError('WAV PCM16 conversion failed; inspect conform.log')
            _owned_file(target, out)
            with wave.open(str(target), 'rb') as wav:
                channels, width, rate, samples, compression, _ = wav.getparams()
                pcm = wav.readframes(samples)
                if width != 2 or channels not in (1, 2) or rate != spec.sample_rate or samples != source_samples:
                    raise ValueError('Observed WAV violates declared local audio bounds')
                if compression != 'NONE' or len(pcm) != samples*channels*width or not any(pcm):
                    raise ValueError('Truncated, compressed or silent WAV')
            port = registration(aid)['outputs'][OP][0]
            output_probe.validate(target.read_bytes(), port, run_process=run_process)
            feedback['observed_audio'] = dict(channels=channels, sample_width_bytes=width, sample_rate=rate, samples=samples)
            feedback['conformance'] = 'PCM16 quantization only; no rate conversion or duration trim'
            feedback['output_sha256'] = alternative.file_digest(target)
            outputs = [dict(port='audio', relative_path='audio.wav', media_type='audio/wav', claimed_sha256=feedback['output_sha256'])]
            result = alternative._result(outputs, started=started)
        except Exception as exc:
            if created and isinstance(exc, subprocess.TimeoutExpired) and exc.output:
                (out/'engine-timeout.log').write_bytes(exc.output)
            feedback['error'] = str(exc)
            result = alternative._result(error=exc, started=started)
        finally:
            feedback['elapsed_ms'] = round((time.monotonic()-clock)*1000)
            if created and out.is_dir() and not out.is_symlink():
                # The receipt remains project-local and bound to exact output hash;
                # no float engine metadata is lost to Studio's integer-only JSON ABI.
                from ..contracts import canonical
                path = out/'generation-receipt.json'
                if not path.exists():
                    with path.open('xb') as stream:
                        stream.write(canonical(feedback))
        if created and result.get('error') is not None:
            # The existing ABI's error.details is closed; do not widen it here.
            result['error']['message'] += '; local feedback: ' + str(Path(attempt['output_dir'])/'generation-receipt.json')
        return result


CONNECTOR = LocalAudioConnector()
validate_request = CONNECTOR.validate_request
validate_timing = CONNECTOR.validate_timing
execute = CONNECTOR.execute


class LocalAudioAdapter:
    """Existing owned Adapter ABI facade; no alternate process/job lifecycle."""
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, binding

    def resource_requirements(self, request):
        # These exact CLI bindings run their own owned child. A provider may
        # reserve the device for that child but must never prepare a second
        # resident model: the CLI cannot consume resident-service handles.
        adapter_id = self.binding['adapter_id']
        if adapter_id not in BINDINGS or request.get('binding') != self.binding:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Unknown or changed local audio binding')
        model = BINDINGS[adapter_id].model_identity
        if not isinstance(model, str) or not model:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'CLI binding needs an explicit process model identity')
        return dict(resource='local-audio-gpu', model=model, lifecycle='process_scoped')

    def validate_request(self, request):
        if request.get('binding') != self.binding:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Request differs from frozen CLI binding')
        CONNECTOR.validate_request(self.runtime.registry, self.binding, request)
        return dict(valid=True, effects=registration(self.binding['adapter_id'])['declaration']['effects'])

    def execute(self, request, attempt, context=None):
        self.validate_request(request)
        if context is None or not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run required')
        from ..resources import OwnedProcessModelLifecycle
        lifecycle = getattr(context, 'model_process_lifecycle', None)
        if (not isinstance(lifecycle, OwnedProcessModelLifecycle) or lifecycle.worker is not context
                or lifecycle.closed or lifecycle.model != self.resource_requirements(request)['model']):
            raise ContractError('PERMISSION_DENIED', 'Active shared process-scoped model lease required')
        return CONNECTOR.execute(request, attempt=attempt,
            project_root=self.runtime.projects._filesystem().root,
            input_resolver=lambda pin: self.runtime.artifact_path(request['project_id'], pin),
            registry=self.runtime.registry, output_probe=self.runtime.output_probe,
            project_id=request['project_id'], run_process=lifecycle.run)
