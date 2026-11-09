"""B05 bounded explicit temporal conform, no import-time execution."""

import hashlib
import json
from fractions import Fraction
from pathlib import Path
import subprocess
import time
from typing import Any
import copy
from ..contracts import D, ContractError, validate
from ..timeline import validate_temporal_transform, rate_fraction


def _rational(value):
    return {'num':value.numerator,'den':value.denominator}


def execute_conform(payload, source_pin, receipt, parameters, *, context, output_path):
    """Owned-runner-only primitive, NOT a registered adapter or artifact publisher.

    Core supplies a trusted retained B04 receipt and fresh attempt-local MOV path.
    One bounded zero-origin stream only. No implicit VFR classification, retiming,
    mixing, timeline trims, optical flow, or private subprocess fallback.
    """
    prepared = prepare_conform(source_pin, receipt, parameters)
    if not callable(getattr(context, 'run', None)):
        raise ContractError('PERMISSION_DENIED','WorkerContext.run is required.')
    if not isinstance(payload, bytes) or not 0 < len(payload) <= 16777216:
        raise ContractError('LIMIT_EXCEEDED','Conform input must be 1..16 MiB.')
    if 'sha256:'+hashlib.sha256(payload).hexdigest() != source_pin['sha256']:
        raise ContractError('HASH_MISMATCH','Source bytes differ from B04 receipt pin.')
    output_path = Path(output_path)
    if not output_path.is_absolute() or output_path.suffix != '.mov' or output_path.exists():
        raise ContractError('INVALID_ARGUMENT','Core must provide a fresh absolute attempt-local MOV path.')
    deadline = time.monotonic()+60
    commands = []
    def run(argv, data=payload):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise ContractError('DEADLINE_EXCEEDED','Conform execution deadline elapsed.')
        commands.append(argv)
        return context.run(argv,input=data,timeout=remaining,check=True,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
    flags = ['-protocol_whitelist','pipe','-format_whitelist','mov',
             '-max_alloc','67108864','-probesize','16777216','-analyzeduration','10000000']
    def measure(data) -> dict[str, Any]:
        raw = json.loads(run(['ffprobe','-v','error',*flags,'-show_streams','-show_frames','-of','json','pipe:0'],data))
        streams = raw.get('streams',[])
        if len(streams) != 1:
            raise ContractError('OUTPUT_INVALID','Actual media must have exactly one stream.')
        stream = streams[0]
        frames = raw.get('frames',[])
        if not frames or int(stream.get('start_pts',-1)) != 0:
            raise ContractError('TIMING_INVALID','Actual zero-origin frames are required.')
        base = Fraction(stream['time_base'])
        points = [int(f['pts'])*base for f in frames]
        if points[0] != 0 or any(b<=a for a,b in zip(points,points[1:])):
            raise ContractError('TIMING_INVALID','Frame timestamps must increase from zero.')
        if stream['codec_type'] == 'video':
            if stream.get('pix_fmt') != 'rgb24':
                raise ContractError('UNSUPPORTED_FEATURE','Bounded conform requires rgb24; no implicit pixel conversion.')
            if not 0 < len(frames) <= 360 or not 0 < stream['width'] <= 640 or not 0 < stream['height'] <= 360:
                raise ContractError('LIMIT_EXCEEDED','Video exceeds bounded conform geometry/frame limits.')
            duration = int(frames[-1].get('duration',frames[-1].get('pkt_duration',0)))*base
            if duration <= 0:
                raise ContractError('TIMING_INVALID','Actual final frame duration is unknown.')
            end = points[-1]+duration
            rate = Fraction(stream['avg_frame_rate'])
            decoded = run(['ffmpeg','-nostdin','-v','error','-xerror',*flags,'-threads','1','-i','pipe:0',
                           '-map','0:v:0','-an','-f','framemd5','-'],data)
            count = sum(1 for line in decoded.splitlines() if line and not line.startswith(b'#'))
            if count != len(frames):
                raise ContractError('OUTPUT_INVALID','Decoded frame count differs from probe.')
        elif stream['codec_type'] == 'audio':
            if stream.get('codec_name') != 'pcm_s16le' or not 0 < stream.get('channels',0) <= 2:
                raise ContractError('UNSUPPORTED_FEATURE','Bounded conform requires mono/stereo s16le PCM; no implicit quantization.')
            rate = Fraction(int(stream['sample_rate']))
            offset = 0
            for point, frame in zip(points,frames):
                if point != Fraction(offset,rate):
                    raise ContractError('TIMING_INVALID','Audio has gaps/overlap; no implicit sample timeline repair.')
                offset += int(frame['nb_samples'])
            decoded = run(['ffmpeg','-nostdin','-v','error','-xerror',*flags,'-threads','1','-i','pipe:0',
                           '-map','0:a:0','-vn','-c:a','pcm_s16le','-f','s16le','-'],data)
            count, extra = divmod(len(decoded),2*int(stream['channels']))
            if extra or not 0 < count <= 576000 or count != sum(int(f['nb_samples']) for f in frames):
                raise ContractError('OUTPUT_INVALID','Actual decoded sample count invalid or differs from probe.')
            end = Fraction(count,rate)
        else:
            raise ContractError('UNSUPPORTED_FEATURE','Only video/audio conform is supported.')
        if end > 12:
            raise ContractError('LIMIT_EXCEEDED','Actual conform duration exceeds 12 seconds.')
        return dict(count=count,rate=rate,end=end,points=points,
                    decode_sha256='sha256:'+hashlib.sha256(decoded).hexdigest(),probe=raw)
    source = measure(payload)
    actual_stream = source['probe']['streams'][0]
    if actual_stream['codec_type'] != prepared['stream']['type']:
        raise ContractError('TIMING_INVALID','Observed stream type differs from B04 receipt.')
    if (prepared['stream'].get('time_base') is None or
            Fraction(actual_stream['time_base']) != rate_fraction(prepared['stream']['time_base'])):
        raise ContractError('TIMING_INVALID','Observed source tick base differs from B04 receipt.')
    observed_rate = (prepared['stream'].get('rate') if prepared['stream']['type']=='video'
                     else {'num':prepared['stream']['sample_rate'],'den':1})
    if observed_rate is None or source['rate'] != Fraction(observed_rate['num'],observed_rate['den']):
        raise ContractError('TIMING_INVALID','Observed source rate differs from pinned B04 facts.')
    video = parameters['kind'] == 'rate_conform'
    if video:
        rate = parameters['spec']['rate']
        target = Fraction(rate['num'],rate['den'])
        # FFmpeg near rounds half ties away, not the project's ties-to-even.
        # Refuse that case rather than publish a misleading canonical receipt.
        if any((point*target).denominator == 2 for point in source['points']+[source['end']]):
            raise ContractError('UNSUPPORTED_FEATURE','FFmpeg half-tie mapping is not nearest-even; explicit alternative required.')
        encoding = ['-map','0:v:0','-an','-vf',prepared['filter'],'-fps_mode','passthrough',
                    '-c:v','png','-threads','1','-video_track_timescale',str(rate['num'])]
        target = Fraction(rate['num'],rate['den'])
    else:
        encoding = ['-map','0:a:0','-vn','-af',prepared['filter'],'-c:a','pcm_s16le']
        target = Fraction(parameters['spec']['sample_rate'])
    run(['ffmpeg','-nostdin','-v','error','-n',*flags,'-threads','1','-i','pipe:0',
         *encoding,'-movflags','+faststart',str(output_path)])
    output = output_path.read_bytes()
    if len(output) > 16777216:
        raise ContractError('LIMIT_EXCEEDED','Encoded conform exceeds output byte bound.')
    final = measure(output)
    if final['rate'] != target:
        raise ContractError('OUTPUT_INVALID','Actual output rate differs from explicit conform.')
    if final['count'] != round(source['end']*target):
        raise ContractError('OUTPUT_INVALID','Engine endpoint rounding differs from canonical nearest-even.')
    if video and final['points'] != [Fraction(i,target) for i in range(final['count'])]:
        raise ContractError('OUTPUT_INVALID','Output frame timestamps are not the exact target grid.')
    error = final['end']-source['end']
    if abs(error) > 1/target:
        raise ContractError('OUTPUT_INVALID','Conform duration error exceeds one target frame/sample.')
    return dict(schema='motion/v1/local-conform-observation',source=copy.deepcopy(source_pin),
        probe_receipt_id=receipt.get('receipt_id'),parameters=prepared['parameters'],
        source_vfr=receipt.get('vfr'),output_sha256='sha256:'+hashlib.sha256(output).hexdigest(),
        source_count=source['count'],output_count=final['count'],source_rate=_rational(source['rate']),
        output_rate=_rational(final['rate']),source_end_seconds=_rational(source['end']),
        output_end_seconds=_rational(final['end']),error_seconds=_rational(error),
        rounding='nearest_even',engine_rounding='ffmpeg_fps_near_eof_round' if video else 'libswresample_actual_count',
        offset_seconds={'num':0,'den':1},conversion_kind='frame_rate' if video else 'sample_rate',
        losses=prepared['losses'],source_decode_sha256=source['decode_sha256'],
        output_decode_sha256=final['decode_sha256'],source_probe=source['probe'],output_probe=final['probe'],
        commands=commands,claim_boundary='Actual local observation; core must publish output ArtifactRef and ConversionRecord.')



def prepare_conform(source_pin, receipt, parameters) -> dict[str, Any]:
    """Pure narrow admission; trusted core must resolve the retained B04 receipt."""
    validate(source_pin, D['ArtifactRef'])
    parameters = validate_temporal_transform(parameters)
    if receipt.get('schema') != 'motion/v1/probe-receipt' or receipt.get('artifact') != source_pin:
        raise ContractError('HASH_MISMATCH', 'B04 receipt does not pin the exact input.')
    streams = receipt.get('streams', [])
    if len(streams) != 1 or streams[0].get('type') not in ('video', 'audio'):
        raise ContractError('UNSUPPORTED_FEATURE', 'Bounded conform requires one video or audio stream.')
    stream = streams[0]
    if stream.get('start_pts') != 0:
        raise ContractError('TIMING_INVALID', 'Only observed zero-origin inputs are supported; no implicit timestamp reset.')
    if parameters['kind'] == 'sample_conform' and stream['type'] == 'audio':
        if type(stream.get('sample_rate')) is not int or stream['sample_rate'] <= 0:
            raise ContractError('TIMING_INVALID', 'Unknown source sample rate blocks conform.')
        rate = parameters['spec']['sample_rate']
        if rate > 96000 or stream['sample_rate'] > 96000:
            raise ContractError('LIMIT_EXCEEDED','Bounded sample conform rates are at most 96000 Hz.')
        return dict(parameters=parameters, stream=copy.deepcopy(stream),
            filter=f'aresample={rate}:async=0:first_pts=0',
            losses=['Resampling changes sample values; output is lossless PCM s16le.'])
    if (parameters['kind'] != 'rate_conform' or stream['type'] != 'video'
            or parameters['spec']['method'] != 'drop_duplicate'):
        raise ContractError('UNSUPPORTED_FEATURE', 'Only explicit drop/duplicate conform is supported.')
    rate = parameters['spec']['rate']
    if rate_fraction(rate) > 120:
        raise ContractError('LIMIT_EXCEEDED','Bounded conform target is at most 120 fps.')
    return dict(parameters=parameters, stream=copy.deepcopy(stream),
        filter=f"fps=fps={rate['num']}/{rate['den']}:start_time=0:round=near:eof_action=round",
        losses=['Frames may be dropped or duplicated; no optical flow.'])


ADAPTER_ID = 'ffmpeg.conform'
VERSION = '1.0'


def registration():
    """Metadata-only bounded sample and drop/duplicate frame conform."""
    from .alternative import registration as base, ESPEAK_ID
    from .media_probe import result_schema
    from ..contracts import obj, integer
    from ..capabilities import RATE
    meta = base(ESPEAK_ID)
    decl = meta['declaration']
    decl.update(adapter_id=ADAPTER_ID, label='Bounded explicit sample/frame conform',
                implementation_version=VERSION)
    op = decl['operations'][0]
    op.update(operation='media.transform@1',
        request_schema='motion/v1/ffmpeg.conform/request',
        result_schema='motion/v1/ffmpeg.conform/result', default_timeout_seconds=60)
    op['constraints'].update(media_types=['audio/quicktime','video/quicktime','audio/wav'],
                            languages=[], timing='frame')
    op['features'] = ['timing.vfr_conform']
    decl['dependencies'] = [dict(name=n, kind='executable', version_constraint=None,
                                required=True) for n in ('ffmpeg','ffprobe')]
    meta.update(implementation_sha256='sha256:'+hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        schemas={op['request_schema']:{'oneOf':[
            obj(dict(kind={'const':'sample_conform'},spec=obj(dict(sample_rate=integer(1,48000))))),
            obj(dict(kind={'const':'rate_conform'},spec=obj(dict(rate=RATE,method={'const':'drop_duplicate'}))))]},
            op['result_schema']:result_schema()},
        outputs={'media.transform@1':[dict(port='media',kind='media',media_type='audio/wav')]},
        output_variants={'media.transform@1':{kind:[dict(port='media',kind='media',media_type=mime)]
            for kind,mime in [('sample_conform','audio/wav'),('rate_conform','video/quicktime')]}})
    return meta


def validate_timing(project_id, request, input_metadata, documents, *, resolve_artifact):
    """Only existing source pins; no inferred/generated source timing."""
    if request.get('adapter_id') != ADAPTER_ID or request.get('operation') != 'media.transform@1':
        raise ContractError('DEPENDENCY_UNAVAILABLE','No timing validator for this binding.')
    validate(request['parameters'], registration()['schemas']['motion/v1/ffmpeg.conform/request'])
    media = request.get('inputs',{}).get('media',{})
    records = input_metadata.get('media',[])
    if set(request.get('inputs',{})) != {'media'} or media.get('kind') != 'artifact' or len(records) != 1:
        raise ContractError('TIMING_INVALID','One existing pinned source required.')
    pin = media['artifact']
    validate(pin,D['ArtifactRef'])
    if any(records[0].get(k) != pin[k] for k in ('artifact_id','sha256')):
        raise ContractError('HASH_MISMATCH','Source metadata differs from frozen pin.')
    from ..assets import _local_file
    with _local_file(str(resolve_artifact(pin))) as stream:
        payload = stream.read(16777217)
    if len(payload) > 16777216 or 'sha256:'+hashlib.sha256(payload).hexdigest() != pin['sha256']:
        raise ContractError('HASH_MISMATCH','Source differs from frozen bounded pin.')
    return (['Frames may be dropped or duplicated; no optical flow.']
            if request['parameters']['kind'] == 'rate_conform' else
            ['Resampling changes sample values; output is lossless PCM s16le.'])


def finalize_conversion(observation, output_pin):
    """Bind only after the collector has assigned a real immutable output pin."""
    validate(output_pin,D['ArtifactRef'])
    validate(observation['source'],D['ArtifactRef'])
    validate(observation['parameters'],registration()['schemas']['motion/v1/ffmpeg.conform/request'])
    kind = 'frame_rate' if observation['parameters']['kind'] == 'rate_conform' else 'sample_rate'
    if observation['conversion_kind'] != kind or observation['rounding'] != 'nearest_even':
        raise ContractError('OUTPUT_INVALID','Unexpected native conform observation type/rounding.')
    for name in ('offset_seconds','error_seconds'):
        value = observation[name]
        if (set(value) != {'num','den'} or type(value['num']) is not int or
            type(value['den']) is not int or value['den'] <= 0 or
            _rational(Fraction(value['num'],value['den'])) != value):
            raise ContractError('OUTPUT_INVALID','Conversion timing must be exact reduced signed rates.')
    if not isinstance(observation['losses'],list) or not all(isinstance(x,str) and x for x in observation['losses']):
        raise ContractError('OUTPUT_INVALID','Conversion losses must be explicit strings.')
    if observation['output_sha256'] != output_pin['sha256']:
        raise ContractError('HASH_MISMATCH','Collected output differs from measured conform bytes.')
    return dict(kind=observation['conversion_kind'],input=copy.deepcopy(observation['source']),
        output=copy.deepcopy(output_pin), **{k:copy.deepcopy(observation[k]) for k in
        ('parameters','rounding','offset_seconds','error_seconds','losses')})


class LocalConformAdapter:
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, copy.deepcopy(binding)

    def validate_request(self, request):
        if request.get('operation') != 'media.transform@1':
            raise ContractError('UNSUPPORTED_OPERATION','Only explicit sample/frame conform is registered.')
        expected = self.runtime.registry.binding(ADAPTER_ID,request['operation'],
            request['parameters'],request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE','Frozen conform binding differs.')
        if set(request.get('inputs',{})) != {'media'}:
            raise ContractError('INVALID_ARGUMENT','Exactly one media source pin required.')
        validate(request['inputs']['media'],D['ArtifactRef'])
        effects = self.runtime.registry.effects(ADAPTER_ID)
        if (request.get('effects',effects) != effects or
                set(request.get('required_features',[])) - {'timing.vfr_conform'}):
            raise ContractError('ADAPTER_INCOMPATIBLE','Conform effects/features differ.')
        return dict(valid=True,effects=effects)

    def execute(self, request, attempt, context=None):
        import os
        import wave
        from .media_probe import _result
        from ..assets import _local_file, _identity
        from ..contracts import canonical, safe_relative
        if not callable(getattr(context,'run',None)):
            raise ContractError('PERMISSION_DENIED','Owned WorkerContext.run required.')
        try:
            self.validate_request(request)
            if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
                raise ContractError('PERMISSION_DENIED','Owned attempt identity and authority required.')
            pin = request['inputs']['media']
            receipt = self.runtime._latest_probe(request['project_id'],pin)
            if receipt is None or receipt.get('full_decode') != 'pass':
                raise ContractError('TIMING_INVALID','Retained source-bound full-decode B04 receipt required.')
            prepared = prepare_conform(pin,receipt,request['parameters'])
            with _local_file(str(self.runtime.artifact_path(request['project_id'],pin))) as stream:
                before = _identity(stream)
                payload = stream.read(16777217)
                if before != _identity(stream):
                    raise ContractError('ASSET_CHANGED','Source changed during staging.')
            fs = self.runtime.projects._filesystem(write=True)
            relative = safe_relative(attempt['output_dir'])
            expected_dir = (self.runtime.projects._base(request['project_id']) + '/jobs/' +
                            attempt['job_id'] + '/attempts/' + attempt['attempt_id'])
            if relative != expected_dir:
                raise ContractError('PATH_UNSAFE','Output directory differs from exact owning attempt.')
            from datetime import datetime, timezone
            from types import SimpleNamespace
            ends = datetime.fromisoformat(attempt['deadline_at'].replace('Z','+00:00'))
            budget = min(60,(ends-datetime.now(timezone.utc)).total_seconds())
            deadline = time.monotonic()+budget
            runner = getattr(context,'run')
            def run(argv, **kwargs):
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise ContractError('DEADLINE_EXCEEDED','Owned conform attempt deadline elapsed.')
                kwargs['timeout'] = min(kwargs.get('timeout',remaining),remaining)
                return runner(argv,**kwargs)
            worker = SimpleNamespace(run=run)
            with fs.directory(relative,create=True) as directory:
                out = fs.root / relative
                observed = execute_conform(payload,pin,receipt,request['parameters'],
                    context=worker,output_path=out/'conform.mov')
                filename, mime = 'conform.mov', 'video/quicktime'
                if prepared['stream']['type'] == 'audio':
                    # Container-only stream copy; retained engine observation measures PCM.
                    completed = worker.run(['ffmpeg','-nostdin','-v','error','-n',
                        '-protocol_whitelist','file','-format_whitelist','mov','-i',str(out/'conform.mov'),
                        '-map','0:a:0','-c:a','copy',str(out/'media.wav')],
                        timeout=15,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    with wave.open(str(out/'media.wav'),'rb') as wav:
                        raw = wav.readframes(wav.getnframes())
                        if (wav.getnframes() != observed['output_count'] or
                            wav.getframerate() != request['parameters']['spec']['sample_rate'] or
                            wav.getsampwidth() != 2 or wav.getnchannels() not in (1,2) or
                            'sha256:'+hashlib.sha256(raw).hexdigest() != observed['output_decode_sha256']):
                            raise ContractError('OUTPUT_INVALID','WAV remux differs from measured PCM.')
                    observed['engine_output_sha256'] = observed['output_sha256']
                    observed['output_sha256'] = 'sha256:'+hashlib.sha256((out/'media.wav').read_bytes()).hexdigest()
                    observed['commands'].append(completed.args)
                    filename, mime = 'media.wav', 'audio/wav'
                fd = os.open('conform-observation.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                             0o600,dir_fd=directory)
                with os.fdopen(fd,'wb') as report:
                    report.write(canonical(observed))
                self.runtime.output_probe.validate((out/filename).read_bytes(),
                    dict(kind='media',media_type=mime),run_process=worker.run)
                return _result([dict(port='media',relative_path=filename,media_type=mime,
                                     claimed_sha256=observed['output_sha256'])])
        except (ContractError,OSError,ValueError,TimeoutError,subprocess.SubprocessError) as exc:
            return _result([],dict(code=getattr(exc,'code','OUTPUT_INVALID'),message=str(exc),
                retry='after_input_change',effect='none',details={}))
