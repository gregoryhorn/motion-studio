"""B12 opt-in local bindings. No engine startup on import/registration.

Breeze, eSpeak NG and Flite are distinct local speech engines.
No FFmpeg CLI, active Blender session, install, network, or model startup.
Core supplies frozen requests, authority, immutable resolver and attempt path.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from ..contracts import ContractError, D, canonical, digest, validate

VERSION = '0.1.0'
ESPEAK_ID = 'local.espeak-ng'
FLITE_ID = 'local.flite-kal'
BREEZE_ID = 'local.breeze-tts-2'
BREEZE_VOICE = 'A warm, clear male voice with a calm conversational delivery.'
ADAPTER_IDS = (ESPEAK_ID, FLITE_ID, BREEZE_ID)


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()


def declaration(adapter_id=ESPEAK_ID) -> dict[str, Any]:
    if adapter_id not in ADAPTER_IDS:
        raise ValueError('Unknown alternative adapter')
    dependencies = ([('breeze-tts', 'executable'), ('breeze-status', 'executable')] if adapter_id == BREEZE_ID
                    else [('espeak-ng', 'executable')] if adapter_id == ESPEAK_ID
                    else [('libflite.so.1', 'library'), ('libflite_cmu_us_kal.so.1', 'library')])
    constraints = dict(media_types=['text/plain', 'audio/wav'], codecs=['pcm_s16le'],
        max_width_px=None, max_height_px=None, min_rate=None, max_rate=None,
        languages=['en-US'], color_spaces=[], alpha_modes=[], timing='none', max_duration_frames=None)
    return dict(schema='motion/v1/adapter-declaration', adapter_id=adapter_id,
        label={'local.espeak-ng': 'eSpeak NG local speech',
               'local.flite-kal': 'Flite KAL local speech',
               BREEZE_ID: 'Breeze TTS 2 selected local narration'}[adapter_id], abi_version='1.0',
        implementation_version=VERSION, transport='cli', location='local',
        operations=[dict(operation=op, request_schema=f'motion/v1/{adapter_id}/{op.split("@")[0]}-request',
            result_schema=f'motion/v1/{adapter_id}/{op.split("@")[0]}-result',
            features=[],
            constraints=constraints, determinism='unknown',
            supports={k: False for k in ('status', 'cancel', 'collect', 'resume', 'provider_idempotency', 'lookup_by_request')},
            default_timeout_seconds=85 if adapter_id == BREEZE_ID else 120) for op in ['speech.synthesize@1']],
        dependencies=[dict(name=n, kind=k, version_constraint=None, required=True) for n, k in dependencies],
        credential_refs=[], effects=dict(writes_local=True, uploads=False, destinations=[], generates=True,
            launches_process=True, pricing='free', charging_basis=None, estimate=None), license=None,
        resource_needs=dict(cpu_threads=1, ram_bytes=None, gpu_vram_bytes=None,
            exclusive_resource='local-audio-gpu' if adapter_id == BREEZE_ID else None))


def registration(adapter_id=ESPEAK_ID) -> dict[str, Any]:
    """Exact CapabilityRegistry.register(**registration(id)); metadata only."""
    from ..capabilities import PARAMS, expanded
    from ..contracts import TEXT, DIGEST, nullable, obj, arr, enum
    result_schema = obj(dict(state=enum('succeeded', 'failed'), submission_state=enum('confirmed', 'not_sent'),
        external_handle={'type': 'null'}, remote_state={'const': 'none'}, progress={'type': 'null'},
        outputs=arr(obj(dict(port=TEXT, relative_path=TEXT, media_type=TEXT, claimed_sha256=DIGEST))),
        warnings=arr(TEXT), error=nullable(obj(dict(code=TEXT, message=TEXT, retry=TEXT, effect=TEXT,
            details={'type': 'object', 'additionalProperties': {}}))), observed_cost={'type': 'null'}, logs_ref={'type': 'null'}, handoff={'type': 'null'}))
    schemas, outputs = {'motion/v1/no-options': obj({})}, {}
    decl = declaration(adapter_id)
    for operation in decl['operations']:
        op = operation['operation']
        schemas[operation['request_schema']] = expanded(PARAMS[op])
        properties = schemas[operation['request_schema']]['properties']
        properties['voice']['default'] = BREEZE_VOICE if adapter_id == BREEZE_ID else 'en-us' if adapter_id == ESPEAK_ID else 'kal'
        properties['language']['default'] = 'en-US'
        properties['seed']['default'] = None
        schemas[operation['result_schema']] = result_schema
        port, kind, mime = 'audio', 'audio', 'audio/wav'
        outputs[op] = [dict(port=port, kind=kind, media_type=mime)]
    from .voice_controls import registration_metadata
    extra_schemas, option_metadata = registration_metadata(adapter_id)
    schemas.update(extra_schemas)
    # Both executable mappings participate in implementation freshness.
    from . import voice_controls
    implementation = digest(dict(adapter=file_digest(__file__), controls=file_digest(voice_controls.__file__),
        engine=voice_controls.breeze_cli_evidence() if adapter_id == BREEZE_ID else None))
    return dict(declaration=decl, implementation_sha256=implementation,
                schemas=schemas, outputs=outputs,
                **({'option_metadata': option_metadata} if adapter_id == BREEZE_ID else {}))


def registration_binding(adapter_id, operation, parameters, binding_parameters=None, *, metadata=None):
    """Canonical live identity, including normalized schemas and option metadata.

    Registration is passive; use the registry's public API rather than a
    parallel digest implementation which can drift from its frozen bundle.
    """
    from ..capabilities import CapabilityRegistry
    registry = CapabilityRegistry()
    registry.register(**(registration(adapter_id) if metadata is None else metadata))
    return registry.binding(adapter_id, operation, parameters, binding_parameters)


def discover():
    """Read-only installed runtime facts; never claim contract/exercise status."""
    import sysconfig
    multiarch = sysconfig.get_config_var('MULTIARCH')
    roots = [Path('/lib'), Path('/usr/lib'), Path('/usr/local/lib')]
    if multiarch:
        roots += [root / multiarch for root in tuple(roots)]
    def library(name):
        return next((str((root / name).resolve()) for root in roots if (root / name).is_file()), None)
    return dict(breeze=shutil.which('breeze-tts') if shutil.which('breeze-status') else None,
        espeak_ng=shutil.which('espeak-ng'),
        flite=library('libflite.so.1'), flite_voice=library('libflite_cmu_us_kal.so.1'))


def _result(outputs=None, error=None, started=False):
    return dict(state='failed' if error else 'succeeded', submission_state='confirmed' if started else 'not_sent',
        external_handle=None, remote_state='none', progress=None, outputs=outputs or [], warnings=[],
        error=None if error is None else dict(code=error.code if isinstance(error, ContractError) else
            'INVALID_ARGUMENT' if isinstance(error, (ValueError, KeyError)) else 'INTERNAL_ERROR',
            message=error.message if isinstance(error, ContractError) else str(error),
            retry='after_reconcile' if started else 'after_input_change',
            effect='unknown' if started else getattr(error, 'effect', 'none'),
            details=error.details if isinstance(error, ContractError) else {}),
        observed_cost=None, logs_ref=None, handoff=None)


def _relative(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative or Path(relative).is_absolute() or any(x in ('', '.', '..') for x in relative.split('/')):
        raise ValueError('Unsafe relative path')
    p = root
    for part in relative.split('/'):
        p = p/part
        if p.is_symlink():
            raise ValueError('Symlink refused')
    p.resolve().relative_to(root)
    return p


def execute(request, attempt, *, project_root, resolve_artifact, run_process=None, output_probe=None,
            authorize_reference=None) -> dict[str, Any]:
    """Same synchronous ABI as baseline; core remains the authority/collector.

    No status/cancel/resume is claimed. Bounded children use factory startup,
    offline mode and a closed trusted script, not user-supplied executable code.
    Speech and the actual engine log stay in the owned quarantine.
    """
    started = False
    try:
        aid, op = request['binding']['adapter_id'], request['operation']
        meta = registration(aid)
        decl = meta['declaration']
        matches = [d for d in decl['operations'] if d['operation'] == op]
        if len(matches) != 1:
            raise ValueError('Unsupported operation')
        declared = matches[0]
        expected = registration_binding(aid, op, request['parameters'],
            request['binding_parameters'], metadata=meta)
        if request['binding'] != expected:
            raise ValueError('Frozen implementation/schema binding differs')
        if request['effects'] != decl['effects']:
            raise ValueError('Effects/options differ from declaration')
        if set(request['required_features']) - set(declared['features']):
            raise ValueError('Required feature unavailable')
        if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
            raise ValueError('Missing authority or mismatched attempt')
        params, inputs = request['parameters'], request['inputs']
        validate(params, meta['schemas'][declared['request_schema']])
        deadline = datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00'))
        def remaining():
            seconds = min(120, (deadline - datetime.now(timezone.utc)).total_seconds())
            if seconds <= 0:
                raise TimeoutError('Attempt deadline elapsed')
            return seconds
        remaining()
        root = Path(project_root).resolve(strict=True)
        out = _relative(root, attempt['output_dir'])
        def resolve(ref):
            validate(ref, D['ArtifactRef'])
            p = Path(resolve_artifact(ref))
            if p.is_symlink() or not p.is_file() or file_digest(p) != ref['sha256']:
                raise ValueError('Immutable input identity differs')
            return p.resolve(strict=True)
        from .voice_controls import synthesis_controls, require_reference_scope
        controls = synthesis_controls(aid, params, request['binding_parameters'])
        reference = controls['reference']
        expected_inputs = {'text', 'reference_audio', 'reference_text'} if reference else {'text'}
        if set(inputs) != expected_inputs or params['language'] != 'en-US':
            raise ValueError('Unsupported speech input ports/language')
        reference_audio = reference_text = None
        if reference is not None:
            require_reference_scope(reference, project_id=request['project_id'], authorize_reference=authorize_reference)
            if inputs['reference_audio'] != reference['audio'] or inputs['reference_text'] != reference['transcript']:
                raise ValueError('Reference input pins differ from selected authorized source')
            reference_audio = resolve(inputs['reference_audio'])
            transcript_path = resolve(inputs['reference_text'])
            if not 1 <= transcript_path.stat().st_size <= 4096:
                raise ValueError('Reference transcript must be 1..4096 UTF-8 bytes')
            reference_text = transcript_path.read_text(encoding='utf-8')
            if not reference_text.strip() or any(ord(c) < 32 and c not in '\n\r\t' for c in reference_text):
                raise ValueError('Reference transcript is empty or contains control characters')
        voice = controls['instruction']
        text_path = resolve(inputs['text'])
        if not 1 <= text_path.stat().st_size <= 4096:
            raise ValueError('Text must be 1..4096 UTF-8 bytes')
        text = text_path.read_text(encoding='utf-8')
        if not text.strip() or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            raise ValueError('Empty or control-containing text refused')
        # Never clobber any preexisting target; core issues a fresh attempt dir.
        out.mkdir(parents=True, exist_ok=False)
        def run(argv):
            nonlocal started
            started = True
            options: dict[str, Any] = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=remaining(), check=False)
            if run_process is None:
                options['cwd'] = out
            p = (run_process or subprocess.run)(argv, **options)
            with (out/'engine.log').open('xb') as log:
                log.write(p.stdout)
            if p.returncode:
                raise RuntimeError('Engine failed; inspect attempt engine.log, exit '+str(p.returncode))
        target, port, mime = out/'speech.wav', 'audio', 'audio/wav'
        (out/'text.txt').write_text(text, encoding='utf-8')
        if aid == BREEZE_ID:
            # Refuse duplicate residency or competing work; never load/unload a service.
            status = (run_process or subprocess.run)(['breeze-status'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=min(10, remaining()), check=False)
            if status.returncode:
                raise RuntimeError('Breeze preflight unavailable')
            state = json.loads(status.stdout)
            gpu = state['gpu']
            if state['breeze']['state'] != 'unloaded':
                raise RuntimeError('Resident Breeze requires its managed API; CLI duplicate refused')
            if (gpu['process_activity']['compute_active'] or gpu['free_mib'] < 10240
                    or gpu.get('comfyui', {}).get('state') not in ('idle', 'unknown')):
                raise RuntimeError('Breeze GPU preflight busy or insufficient headroom')
            (out/'breeze-preflight.json').write_text(json.dumps(state, indent=2))
            from .voice_controls import breeze_argv
            argv = breeze_argv(text, controls, target, reference_audio=reference_audio, reference_text=reference_text)
            run(argv)
        elif aid == ESPEAK_ID:
            # Both execution routes set cwd to the fresh owned attempt.
            # eSpeak has a bounded internal filename buffer; absolute deep
            # project paths are truncated even though the OS accepts them.
            run(['espeak-ng', '-v', 'en-us', '-s', '165', '-w', target.name, '-f', 'text.txt'])
        else:
            (out/'flite.py').write_text(_FLITE_SCRIPT)
            run([sys.executable, '-I', str(out/'flite.py'), str(out/'text.txt'), str(target)])
        import wave
        with wave.open(str(target), 'rb') as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getnframes() <= 0:
                raise ValueError('Engine returned invalid PCM speech')
            if not any(audio.readframes(audio.getnframes())):
                raise ValueError('Engine returned silence')
        if output_probe is not None:
            spec = next(p for p in registration(aid)['outputs'][op] if p['port'] == port)
            output_probe.validate(target.read_bytes(), spec, run_process=run_process)
        # B07 collectors resolve owned descriptors against attempt.output_dir.
        # Preserve the standalone root-relative ABI used by direct callers.
        descriptor_root = out if run_process is not None else root
        return _result([dict(port=port, relative_path=str(target.relative_to(descriptor_root)), media_type=mime,
                             claimed_sha256=file_digest(target))], started=started)
    except Exception as exc:
        return _result(error=exc, started=started)


_FLITE_SCRIPT = '''import ctypes, sys
from pathlib import Path
lib = ctypes.CDLL('libflite.so.1', mode=ctypes.RTLD_GLOBAL)
voice_lib = ctypes.CDLL('libflite_cmu_us_kal.so.1')
lib.flite_init.argtypes = []
lib.flite_init.restype = ctypes.c_int
lib.flite_init()
voice_lib.register_cmu_us_kal.argtypes = [ctypes.c_char_p]
voice_lib.register_cmu_us_kal.restype = ctypes.c_void_p
voice = voice_lib.register_cmu_us_kal(None)
if not voice: raise RuntimeError('Flite KAL voice unavailable')
lib.flite_text_to_wave.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
lib.flite_text_to_wave.restype = ctypes.c_void_p
lib.cst_wave_save_riff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
lib.cst_wave_save_riff.restype = ctypes.c_int
lib.delete_wave.argtypes = [ctypes.c_void_p]
lib.delete_wave.restype = None
wave = lib.flite_text_to_wave(Path(sys.argv[1]).read_bytes(), voice)
if not wave: raise RuntimeError('Flite produced no wave')
try:
    if lib.cst_wave_save_riff(wave, sys.argv[2].encode()) != 0:
        raise RuntimeError('Flite could not save wave')
finally:
    lib.delete_wave(wave)
'''
