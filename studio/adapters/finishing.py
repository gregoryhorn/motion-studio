"""Owned finishing jobs: normalized PCM, pinned SDR transforms, alpha masters."""
import copy
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from ..contracts import ContractError, canonical, digest, safe_relative, validate, D
from . import ffmpeg, rates

ADAPTER_ID = 'local.media-finishing'
OPERATIONS = ('audio.normalize@1', 'audio.cleanup@1', 'audio.duck@1', 'media.color@1', 'delivery.encode@1')
PORTS = {'audio.normalize@1': [('audio', 'audio', 'audio/wav'), ('report', 'report', 'application/json')],
         'audio.cleanup@1': [('audio', 'audio', 'audio/wav'), ('report', 'report', 'application/json')],
         'audio.duck@1': [('audio', 'audio', 'audio/wav'), ('report', 'report', 'application/json')],
         'media.color@1': [('media', 'media', 'video/x-matroska'), ('report', 'report', 'application/json')],
         'delivery.encode@1': [('candidate', 'media', 'video/quicktime')]}
INPUTS = {'audio.normalize@1': {'audio'}, 'audio.cleanup@1': {'audio'},
          'audio.duck@1': {'music', 'speech'}, 'media.color@1': {'media', 'config'}, 'delivery.encode@1': {'media'}}


def registration():
    from ..capabilities import PARAMS, expanded
    source = ffmpeg.registration()
    declaration = ffmpeg.declaration()
    prototype = declaration['operations'][0]
    result = source['schemas'][prototype['result_schema']]
    declaration.update(adapter_id=ADAPTER_ID, label='Local normalization, SDR conversion and alpha masters', implementation_version='1.0.0')
    declaration['operations'] = []
    schemas: dict = {'motion/v1/no-options': ffmpeg.NO_OPTIONS, 'motion/v1/media-finishing/no-options': ffmpeg.NO_OPTIONS}
    for operation in OPERATIONS:
        item = copy.deepcopy(prototype)
        item.update(operation=operation, request_schema='motion/v1/media-finishing/' + operation + '/request',
                    result_schema='motion/v1/media-finishing/' + operation + '/result',
                    features={'audio.normalize@1': ['audio.loudness_normalize', 'audio.true_peak_limit'],
                              'audio.cleanup@1': ['audio.explicit_dialogue_cleanup'],
                              'audio.duck@1': ['audio.speech_stem_ducking'],
                              'media.color@1': ['color.pinned_sdr_pipeline'],
                              'delivery.encode@1': ['alpha.prores4444', 'alpha.decoded_planes']}[operation],
                    default_timeout_seconds=7200)
        item['constraints'].update(media_types=['application/json', 'audio/wav', 'video/x-matroska', 'video/quicktime'],
            codecs=['ffv1', 'pcm_s16le', 'prores_ks', 'prores'], color_spaces=['bt709', 'bt2020', 'smpte170m', 'bt470bg'],
            alpha_modes=['straight'] if operation == 'delivery.encode@1' else ['none'])
        declaration['operations'].append(item)
        schemas[item['request_schema']] = expanded(PARAMS[operation])
        schemas[item['result_schema']] = result
    files = ('finishing.py', 'mastering.py', 'dialogue.py', 'color_pipeline.py', 'rates.py', 'limits.py')
    return dict(declaration=declaration, implementation_sha256=digest({name: ffmpeg.digest(Path(__file__).with_name(name)) for name in files}),
                schemas=schemas, outputs={op: [dict(port=p, kind=k, media_type=m) for p, k, m in specs] for op, specs in PORTS.items()})


def discover():
    available = all(shutil.which(name) for name in ('ffmpeg', 'ffprobe'))
    return dict(status='available' if available else 'unavailable', reason='PATH metadata only; no finishing route executed')


def validate_timing(project_id, request, metadata, documents, *, resolve_artifact):
    """Preflight explicit finishing intent without running a decoder or engine."""
    from decimal import Decimal
    from .color_pipeline import space
    operation, params = request['operation'], request['parameters']
    if operation not in OPERATIONS:
        raise ContractError('UNSUPPORTED_OPERATION', 'Undeclared finishing operation')
    if set(request['inputs']) != INPUTS[operation]:
        raise ContractError('INVALID_ARGUMENT', 'Exact finishing input closure required')
    try:
        for port,binding in request['inputs'].items():
            if binding.get('kind') == 'node_output' and port != 'config':
                continue  # Immutable upstream output is resolved and decoded by the owned worker.
            if binding.get('kind') != 'artifact':
                raise ValueError('Finishing source ports require immutable artifact pins')
            resolve_artifact(binding['artifact'])
        if operation == 'audio.normalize@1':
            values = [Decimal(params[key]) for key in ('loudness_lufs','true_peak_dbtp','tolerance_lu')]
            if (not all(v.is_finite() for v in values) or not -70 <= values[0] <= -5
                    or not -9 <= values[1] <= 0 or not 0 <= values[2] <= 2):
                raise ValueError('Mastering targets outside explicit processor bounds')
        elif operation in ('audio.cleanup@1', 'audio.duck@1'):
            from .dialogue import validate_parameters
            validate_parameters(operation, params)
        elif operation == 'media.color@1':
            config = Path(resolve_artifact(request['inputs']['config']['artifact']))
            if not 0 < config.stat().st_size <= 1048576:
                raise ValueError('Color recipe must be a bounded self-contained JSON artifact')
            recipe = json.loads(config.read_bytes())
            if (set(recipe) != {'schema','input_space','working_space','output_space','spaces'}
                    or recipe['schema'] != 'motion/v1/sdr-color-pipeline'
                    or recipe['input_space'] != params['input_space']
                    or recipe['output_space'] != params['output_space']
                    or not 1 <= len(recipe['spaces']) <= 8):
                raise ValueError('Pinned SDR recipe identity differs')
            for value in recipe['spaces'].values():
                space(value)
            for key in ('input_space','working_space','output_space'):
                space(recipe['spaces'][recipe[key]])
            if recipe['spaces'][recipe['output_space']] != params['output_color']:
                raise ValueError('Recipe output differs from frozen output color')
        else:
            pin = params['variant_document']
            document = documents.get(('variants', pin['id']))
            if document is None or document['revision'] != pin['revision'] or digest(document) != pin['sha256']:
                raise ValueError('Alpha export requires the exact frozen variants document')
            matches = [v for v in document['value'] if v['variant_id'] == params['variant']]
            if len(matches) != 1:
                raise ValueError('Alpha export requires one exact variant')
            variant = matches[0]
            rates.bounds(variant['width_px'],variant['height_px'],variant['duration_frames'],variant['rate'])
            if (variant['container'],variant['video_codec'],variant['pixel_format'],variant['alpha']) != (
                    'mov','prores','yuva444p12le','straight'):
                raise ValueError('Selected alpha route requires straight ProRes 4444 MOV')
        return []
    except (ValueError,KeyError,OSError,TypeError) as exc:
        raise ContractError('TIMING_INVALID',str(exc)) from exc


class LocalFinishingAdapter:
    owned_local = True
    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, copy.deepcopy(binding)

    def validate_request(self, request):
        operation = request['operation']
        if operation not in OPERATIONS or set(request.get('inputs', {})) != INPUTS[operation]:
            raise ContractError('INVALID_ARGUMENT', 'Exact declared finishing source closure required')
        expected = self.runtime.registry.binding(ADAPTER_ID, operation, request['parameters'], request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen finishing implementation differs')
        for pin in request['inputs'].values():
            validate(pin, D['ArtifactRef'])
        if request.get('binding_parameters') is not None:
            raise ContractError('INVALID_ARGUMENT', 'Finishing has no arbitrary engine options')
        if operation in ('audio.cleanup@1', 'audio.duck@1'):
            from .dialogue import validate_parameters
            try:
                validate_parameters(operation, request['parameters'])
            except ValueError as exc:
                raise ContractError('INVALID_ARGUMENT', str(exc)) from exc
        effects = self.runtime.registry.effects(ADAPTER_ID)
        if request.get('effects', effects) != effects:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Finishing effects differ')
        return dict(valid=True, effects=effects)

    def execute(self, request, attempt, context=None):
        from .media_probe import _result
        from .mastering import normalize, alpha_encode
        from .color_pipeline import transform
        from .dialogue import cleanup, duck
        if not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext required')
        runner = getattr(context, 'run')
        try:
            self.validate_request(request)
            if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
                raise ContractError('PERMISSION_DENIED', 'Exact owned attempt authority required')
            relative = safe_relative(attempt['output_dir'])
            expected = self.runtime.projects._base(request['project_id']) + '/jobs/' + attempt['job_id'] + '/attempts/' + attempt['attempt_id']
            if relative != expected:
                raise ContractError('PATH_UNSAFE', 'Finishing output differs from exact owning attempt')
            deadline = time.monotonic() + (datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds()
            def run(argv, **kwargs):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ContractError('DEADLINE_EXCEEDED', 'Finishing deadline elapsed')
                kwargs['timeout'] = min(kwargs.get('timeout', remaining), remaining)
                return runner(argv, **kwargs)
            worker = SimpleNamespace(run=run)
            fs = self.runtime.projects._filesystem(write=True)
            inputs, params, operation = request['inputs'], request['parameters'], request['operation']
            paths = {key: Path(self.runtime.artifact_path(request['project_id'], pin)) for key, pin in inputs.items()}
            for key,path in paths.items():
                if ffmpeg.digest(path) != inputs[key]['sha256']:
                    raise ContractError('HASH_MISMATCH','Pinned finishing input changed: '+key)
            with fs.directory(relative, create=True):
                out = fs.root / relative
                if operation == 'audio.normalize@1':
                    target = out / 'normalized.wav'
                    report = normalize(worker, paths['audio'], target, params)
                elif operation == 'audio.cleanup@1':
                    target = out / 'cleaned.wav'
                    report = cleanup(worker, paths['audio'], target, params)
                elif operation == 'audio.duck@1':
                    target = out / 'ducked-music.wav'
                    report = duck(worker, paths['music'], paths['speech'], target, params)
                elif operation == 'media.color@1':
                    target = out / 'converted.mkv'
                    report = transform(worker, paths['media'], paths['config'], target, params)
                else:
                    variants = ffmpeg._input_json(params['variant_document'], lambda pin: Path(self.runtime.artifact_path(request['project_id'], pin)))
                    matches = [v for v in variants if v['variant_id'] == params['variant']]
                    if len(matches) != 1:
                        raise ValueError('Exactly one frozen alpha variant required')
                    document = matches[0]
                    validate(document, D['Variant'])
                    options = params['encoder_options']
                    if (options['schema_id'] not in ('motion/v1/no-options','motion/v1/media-finishing/no-options')
                            or options['schema_sha256'] != digest(ffmpeg.NO_OPTIONS) or options['values'] != {}):
                        raise ValueError('Alpha variant or empty encoder options differ')
                    target = out / 'master.mov'
                    report = alpha_encode(worker, paths['media'], target, document)
                report_path = out / 'finishing-report.json'
                for key,path in paths.items():
                    if ffmpeg.digest(path) != inputs[key]['sha256']:
                        raise ContractError('HASH_MISMATCH','Finishing input changed during processing: '+key)
                with report_path.open('xb') as stream:
                    stream.write(canonical(report))
                outputs = []
                for port, kind, mime in PORTS[operation]:
                    path = report_path if port == 'report' else target
                    # Core acceptance validates canonical JSON and pinned bytes;
                    # media decoders must never receive the report port.
                    if mime != 'application/json':
                        self.runtime.output_probe.validate_file(path, dict(kind=kind, media_type=mime), run_process=run)
                    outputs.append(dict(port=port, relative_path=path.name, media_type=mime, claimed_sha256=ffmpeg.digest(path)))
                return _result(outputs)
        except (ContractError, ValueError, KeyError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
            return _result([], dict(code=getattr(exc, 'code', 'OUTPUT_INVALID'), message=str(exc), retry='after_input_change', effect='none', details={}))
