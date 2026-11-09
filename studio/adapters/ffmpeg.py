"""Bounded media post-production; no subprocess/import/discovery side effects.

Core owns artifact resolution, plan authority, attempts, candidate records and
publication. execute accepts the exact ABI records and a trusted resolver; it
returns only quarantined output descriptors. No user argv or Python/HTML source.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from contextvars import ContextVar

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_PROCESS_RUNNER: ContextVar[Callable[..., Any] | None] = ContextVar("motion_ffmpeg_process_runner", default=None)

from ..contracts import ContractError, D, validate, canonical, digest as canonical_digest
from .limits import MAX_WIDTH, MAX_HEIGHT, MAX_FRAMES
from . import rates

Timeout = float | Callable[[], float]

ADAPTER_ID = 'local.ffmpeg-post'
VERSION = '0.2.0'
OPERATIONS = ('edit.assemble@1', 'audio.mix@1',
              'caption.render@1', 'delivery.encode@1')
EFFECTS = dict(writes_local=True, uploads=False, destinations=[], generates=True,
               launches_process=True, pricing='free', charging_basis=None, estimate=None)
NO_OPTIONS = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()


def declaration() -> dict:
    """Pure factory. Caller must register request/result schemas before binding."""
    constraints = dict(media_types=['application/vnd.motion.source-bundle+json',
                                   'application/json', 'video/x-matroska', 'video/matroska', 'video/mp4', 'image/png',
                                   'audio/wav', 'audio/x-wav', 'font/ttf', 'text/plain', 'application/octet-stream'],
                       codecs=['ffv1', 'h264', 'pcm_s16le', 'alac', 'aac'], max_width_px=MAX_WIDTH, max_height_px=MAX_HEIGHT,
                       min_rate={'num': 24000, 'den': 1001}, max_rate={'num': 60, 'den': 1},
                       languages=[], color_spaces=['bt709'], alpha_modes=['none'],
                       timing='frame', max_duration_frames=MAX_FRAMES)
    return dict(schema='motion/v1/adapter-declaration', adapter_id=ADAPTER_ID,
                label='Local assembly, audio mix, captions and encoding / FFmpeg', abi_version='1.0',
                implementation_version=VERSION, transport='cli', location='local',
                operations=[dict(operation=op,
                    request_schema='motion/v1/local-ffmpeg/' + op.split('@')[0] + '-request',
                    result_schema='motion/v1/local-ffmpeg/' + op.split('@')[0] + '-result',
                    features=['timing.frame_exact'],
                    constraints=dict(constraints), determinism='unknown',
                    supports=dict(status=False, cancel=False, collect=False, resume=False,
                                  provider_idempotency=False, lookup_by_request=False),
                    default_timeout_seconds=7200) for op in OPERATIONS],
                dependencies=[dict(name=n, kind=k, version_constraint=None, required=True)
                              for n, k in [('ffmpeg', 'executable'), ('ffprobe', 'executable'),
                                           ('av', 'library'), ('Pillow', 'library')]],
                credential_refs=[], effects=dict(EFFECTS), license=None,
                resource_needs=dict(cpu_threads=1, ram_bytes=None, gpu_vram_bytes=None,
                                    exclusive_resource=None))


def _run(args, timeout: Timeout, data=None):
    seconds = timeout() if callable(timeout) else timeout
    if seconds <= 0:
        raise TimeoutError('Attempt deadline elapsed')
    runner = _PROCESS_RUNNER.get() or subprocess.run
    return runner(args, input=data, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, timeout=seconds, check=True)


def probe(path, *, timeout: Timeout = 30):
    return json.loads(_run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                           '-of', 'json', str(path)], timeout).stdout)


def _check_media(path,width,height,frames,timeout,color=None,with_audio=False,rate=None):
    p = probe(path, timeout=timeout)
    streams = p['streams']
    if len(streams) != (2 if with_audio else 1) or streams[0]['codec_type'] != 'video':
        raise ValueError('Unexpected bounded video/audio stream layout')
    s = streams[0]
    if (s['width'], s['height'], rates.observed(s)) != (width, height, rates.fraction(rate or '30')):
        raise ValueError('Explicit conform required: canvas/rate mismatch')
    rates.timestamp_evidence(s,frames,lambda args: _run(
        [str(path) if arg=='pipe:0' else arg for arg in args],timeout).stdout)
    if color is not None:
        expected = dict(color_primaries=color['primaries'], color_transfer=color['transfer'],
                        color_space=color['matrix'],
                        color_range={'limited': 'tv', 'full': 'pc'}[color['range']])
        if any(s.get(key) != value for key, value in expected.items()):
            raise ValueError('Encoded stream color differs from frozen variant')
    # Decode actual frames; metadata duration alone is not an oracle.
    raw = _run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0',
                '-an', '-f', 'framemd5', '-'], timeout).stdout.decode()
    actual = sum(1 for line in raw.splitlines() if line and not line.startswith('#'))
    if actual != frames:
        raise ValueError(f'Frame count mismatch: {actual} != {frames}')
    return p


def _output_dir(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Unsafe attempt output path')
    root = Path(root).resolve(strict=True)
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Symlink output directory')
    path.mkdir(parents=True, exist_ok=True)
    path.resolve().relative_to(root)
    return path


def execute(request, attempt, *, project_root, resolve_artifact, run_process=None, output_probe=None):
    """Execute with owned process/probe injection on the native job path."""
    started = False
    runner = run_process or subprocess.run
    context = getattr(runner, '__self__', None)
    observed_process = hasattr(context, 'process')
    def run(argv, **kwargs):
        nonlocal started
        # WorkerContext retains its last Popen, even after capture/cleanup
        # failure. Calling run is not evidence that admission allowed a child.
        if not observed_process:
            started = True  # Unobservable runners must remain conservative.
        try:
            return runner(argv, **kwargs)
        finally:
            if observed_process:
                started = started or getattr(context, 'process', None) is not None
    token = _PROCESS_RUNNER.set(run)
    try:
        result = _execute(request, attempt, project_root=project_root,
                          resolve_artifact=resolve_artifact, process_started=lambda: started)
        if result['state'] == 'succeeded' and output_probe is not None:
            ports = {p['port']: p for p in registration()['outputs'][request['operation']]}
            for output in result['outputs']:
                port = ports[output['port']]
                if port['media_type'] in ('video/mp4', 'video/x-matroska', 'image/png', 'audio/wav'):
                    output_probe.validate_file(Path(project_root) / output['relative_path'],
                                               port, run_process=run)
        if run_process is not None:
            # B07 descriptors are attempt-relative; standalone ABI evidence used
            # project-root-relative paths. Normalize only for an owned runner.
            for output in result['outputs']:
                output['relative_path'] = str(Path(output['relative_path']).relative_to(attempt['output_dir']))
        return result
    except Exception as exc:
        return _result('failed', [], error=exc, started=started)
    finally:
        _PROCESS_RUNNER.reset(token)


def _execute(request, attempt, *, project_root, resolve_artifact, process_started=lambda: True):
    """Synchronous ABI execute; trusted core resolves ArtifactRef -> local Path.

    Only silent, exact 30fps, contiguous single-video-track assemblies supported.
    Core must validate ABI/envelope, frozen binding hashes, authority and owned
    attempt identity before calling. This boundary independently checks them.
    Returns AdapterResult, never CandidateRecord or a gate verdict.
    """
    try:
        if request['operation'] not in OPERATIONS:
            raise ValueError('Unsupported operation')
        binding = request['binding']
        op = request['operation']
        declared = next(x for x in declaration()['operations'] if x['operation'] == op)
        if (binding['adapter_id'] != ADAPTER_ID or binding['implementation_version'] != VERSION
                or binding['abi_version'] != '1.0'
                or binding['request_schema'] != declared['request_schema']
                or binding['result_schema'] != declared['result_schema']):
            raise ValueError('Frozen binding differs from this implementation')
        metadata = registration()
        if (binding['implementation_sha256'] != metadata['implementation_sha256']
                or binding['schema_sha256'] != canonical_digest({
                    'schemas': metadata['schemas'], 'outputs': metadata['outputs']})):
            raise ValueError('Frozen implementation/schema digest differs')
        validate(request['parameters'], metadata['schemas'][declared['request_schema']])
        if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
            raise ValueError('Missing core authority or mismatched attempt')
        if request['effects'] != EFFECTS:
            raise ValueError('Effects differ from declaration')
        if set(request['required_features']) - set(declared['features']):
            raise ValueError('Unsupported required features')
        if request['binding_parameters'] is not None:
            raise ValueError('No binding options supported')
        deadline = datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00'))
        timeout = lambda: min(7200, (deadline-datetime.now(timezone.utc)).total_seconds())
        if timeout() <= 0:
            raise ValueError('Attempt deadline elapsed')
        out = _output_dir(project_root, attempt['output_dir'])
        def resolve(ref):
            validate(ref, D['ArtifactRef'])
            p = Path(resolve_artifact(ref)).resolve(strict=True)
            if digest(p) != ref['sha256']:
                raise ValueError('ASSET_CHANGED: resolved bytes differ')
            return p
        def save(name, payload):
            path = out / name
            with path.open('xb') as f:
                f.write(payload)
            return path
        params, inputs, outputs = request['parameters'], request['inputs'], []
        def add(port, path, mime):
            outputs.append(dict(port=port, relative_path=str(path.relative_to(Path(project_root).resolve())),
                                media_type=mime, claimed_sha256=digest(path)))
        if op == 'audio.mix@1':
            if set(inputs) != {'audio', 'cue_sheet'}:
                raise ValueError('Explicit audio and timeline cue sheet required')
            target = out / 'mix.wav'
            receipt = _mix_audio(inputs, params, resolve, target)
            add('audio', target, 'audio/wav')
            add('source', save('mix-source.json', canonical(receipt)), 'application/json')
        elif op == 'caption.render@1':
            if set(inputs) != {'caption', 'placement', 'style', 'fonts', 'background'}:
                raise ValueError('Explicit caption render closure required')
            from . import caption_render
            import io
            caption, placement, style, font = _caption_closure(inputs, resolve, resolve_artifact)
            if params['renderer_fingerprint'] != caption_render.fingerprint():
                raise ValueError('Caption renderer fingerprint differs')
            background = resolve(inputs['background'])
            facts = probe(background, timeout=timeout)['streams']
            if len(facts) != 1 or facts[0]['codec_type'] != 'video':
                raise ValueError('Caption background must be silent video')
            w, h = facts[0]['width'], facts[0]['height']
            start, end = _range(params['range'], MAX_FRAMES)
            if start != 0:
                raise ValueError('Caption render requires the explicit full zero-origin range')
            _bounds(w, h, end, placement['output_rate'])
            _check_media(background, w, h, end, timeout, rate=placement['output_rate'])
            previews = params.get('frames', [start])
            if len(previews) != 1 or not start <= previews[0] < end:
                raise ValueError('Exactly one explicit preview frame per render node required')
            def save_preview(image):
                buf = io.BytesIO(); image.save(buf,format='PNG')
                add('frame',save('preview.png',buf.getvalue()),'image/png')
            target = out / 'captioned.mkv'
            from .streaming import captions
            captions(background,target,caption,placement,style,font,start=start,end=end,
                     preview=previews[0],save_preview=save_preview)
            _check_media(target,w,h,end,timeout,rate=placement['output_rate'])
            add('media',target,'video/x-matroska')
        elif op == 'edit.assemble@1':
            if set(inputs) != {'timeline','media'} or set(params) != {'range','canvas','rate'}:
                raise ValueError('Unexpected assembly inputs/parameters')
            timeline = json.loads(resolve(inputs['timeline']).read_text())
            if timeline.get('schema') == 'motion/v1/document':
                from ..project import ProjectStore
                validate(timeline, ProjectStore._document_schema('timeline'))
                if timeline['kind'] != 'timeline':
                    raise ValueError('Assembly requires a frozen timeline document')
                timeline = timeline['value']
            validate(timeline, D['Timeline'])
            # Bounded baseline AssemblyIR: exactly one placed scene and one
            # explicitly wired render input is unambiguous. Never zip arbitrary
            # scene IDs against output positions or silently render missing media.
            scene_ids = {item['subject']['scene_id'] for track in timeline['tracks']
                         for item in track['items'] if item['subject']['kind'] == 'scene'}
            if scene_ids:
                if len(scene_ids) != 1 or len(inputs['media']) != 1:
                    raise ValueError('Baseline scene assembly requires one unique scene/render binding')
                for track in timeline['tracks']:
                    for item in track['items']:
                        if item['subject']['kind'] == 'scene':
                            item['subject'] = {'kind': 'artifact', 'artifact': inputs['media'][0]}
                            item.setdefault('source_in', dict(domain='frame', index=0,
                                rate=params['rate'], origin='project'))
            cadence = rates.text(params['rate'])
            width, height = params['canvas']['width_px'], params['canvas']['height_px']
            _bounds(width, height, timeline['duration_frames'], params['rate'])
            start, end = _range(params['range'], timeline['duration_frames'])
            video_tracks = [t for t in timeline['tracks'] if t['kind'] == 'video']
            if start != 0 or end != timeline['duration_frames'] or len(video_tracks) != 1:
                raise ValueError('Only full-range single-track assembly supported')
            track = video_tracks[0]
            if track['kind'] != 'video' or not track['items']:
                raise ValueError('Video track required')
            refs = inputs['media']
            paths = [resolve(r) for r in refs]
            args, filters, cursor = [], [], 0
            for index, item in enumerate(track['items']):
                if set(item) - {'item_id','start_frame','end_frame','subject','source_in','crop'} or not {'item_id','start_frame','end_frame','subject','source_in'} <= set(item):
                    raise ValueError('Unsupported assembly item fields')
                subject, point = item['subject'], item['source_in']
                if subject['kind'] != 'artifact' or subject['artifact'] not in refs:
                    raise ValueError('Assembly media unresolved')
                expected = dict(domain='frame', index=point['index'], rate=params['rate'], origin=point['origin'])
                if point['origin'] == 'source':
                    expected['source_artifact'] = subject['artifact']
                if point != expected:
                    raise ValueError('Assembly source trim requires exact frame timepoint')
                if item['start_frame'] != cursor or item['end_frame'] <= cursor:
                    raise ValueError('Gaps/overlaps unsupported')
                count = item['end_frame'] - cursor
                media = paths[refs.index(subject['artifact'])]
                facts = probe(media, timeout=timeout)
                stream = facts['streams'][0]
                if len(facts['streams']) != 1 or stream['codec_type'] != 'video' or rates.text(rates.observed(stream)) != cadence:
                    raise ValueError('Explicit media cadence/stream conform required')
                crop = item.get('crop')
                crop_filter = ''
                if crop:
                    x, y, cw, ch = (crop[k] for k in ('x_px','y_px','width_px','height_px'))
                    if x < 0 or y < 0 or x + cw > stream['width'] or y + ch > stream['height'] or cw * height != ch * width:
                        raise ValueError('Crop outside source or output aspect differs; explicit conform required')
                    crop_filter = f',crop={cw}:{ch}:{x}:{y},scale={width}:{height}:flags=lanczos'
                elif (stream['width'],stream['height']) != (width,height):
                    raise ValueError('Explicit media canvas conform required')
                args += ['-i',str(media)]
                filters.append(f'[{index}:v]trim=start_frame={point["index"]}:end_frame={point["index"]+count},setpts=PTS-STARTPTS{crop_filter}[v{index}]')
                cursor = item['end_frame']
            if cursor != end:
                raise ValueError('Timeline coverage incomplete')
            filters.append(''.join(f'[v{i}]' for i in range(len(track['items']))) + f'concat=n={len(track["items"])}:v=1:a=0[out]')
            target = out / 'assembly.mkv'
            _run(['ffmpeg','-v','error','-n',*args,'-filter_complex',';'.join(filters),
                  '-map','[out]','-an','-c:v','ffv1','-pix_fmt','bgr0','-threads','1',
                  '-r',cadence,*rates.stamp(params['rate']),str(target)], timeout)
            _check_media(target,width,height,end,timeout,rate=params['rate'])
            source = save('assembly.json', json.dumps(dict(schema='motion/v1/local-assembly',
                timeline=timeline, media=refs, parameters=params),sort_keys=True,separators=(',',':')).encode())
            bundle = save('source-bundle.json', canonical(dict(schema='motion/v1/source-bundle',
                entry_member='assembly.json',members=[dict(relative_path='assembly.json',
                    sha256=digest(source),size_bytes=source.stat().st_size,
                    media_type='application/vnd.motion.local-assembly+json')])))
            add('media',target,'video/x-matroska')
            add('source',bundle,'application/vnd.motion.source-bundle+json')
        else:
            if set(inputs) - {'sidecars','sidecar_manifest'} not in ({'media'}, {'media','audio'}, {'media','audio','captions'}) or set(params) != {'variant','variant_document','encoder_options'}:
                raise ValueError('Explicit silent or audio plus caption candidate inputs required')
            validate(params['variant_document'], D['DocumentRef'])
            variants = json.loads(resolve_artifact_document(params['variant_document'], resolve_artifact))
            if not isinstance(variants, list):
                raise ValueError('Variant pin must resolve variants singleton document')
            matches = [v for v in variants if v['variant_id'] == params['variant']]
            if len(matches) != 1:
                raise ValueError('Variant ID unresolved or duplicate')
            variant = matches[0]
            validate(variant, D['Variant'])
            # Full operation schema was validated above, including options header.
            options = params['encoder_options']
            expected_hash = 'sha256:' + hashlib.sha256(json.dumps(NO_OPTIONS,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if (options['schema_id'] not in ('motion/v1/no-options','motion/v1/local-ffmpeg/no-options')
                    or options['schema_sha256'] != expected_hash or options['values'] != {}):
                raise ValueError('Unknown registered encoder options')
            rates.fraction(variant['rate'])
            if (variant['variant_id'] != params['variant']
                    or (variant['audio']['mode'], variant['captions']) not in (
                        ('none','none'), ('none','sidecar'), ('required','none'),
                        ('required','sidecar'), ('required','burn'), ('required','both'))
                    or variant['alpha'] != 'none' or variant['container'] != 'mp4'
                    or variant['video_codec'] != 'h264' or variant['pixel_format'] != 'yuv420p'
                    or variant['color'] != dict(primaries='bt709',transfer='bt709',matrix='bt709',range='limited')):
                raise ValueError('Unsupported variant; no implicit conversion')
            w,h,n = variant['width_px'],variant['height_px'],variant['duration_frames']
            _bounds(w,h,n,variant['rate'])
            media = resolve(inputs['media'])
            _check_media(media,w,h,n,timeout,rate=variant['rate'])
            target = out / 'candidate.mp4'
            audio_args = _candidate_audio(inputs,variant,resolve,resolve_artifact,media,timeout)
            spoken = variant['audio']['mode'] == 'required'
            from .color_pipeline import delivery_filter
            color_filter = delivery_filter(probe(media,timeout=timeout)['streams'][0])
            _run(['ffmpeg','-v','error','-n','-i',str(media),*(audio_args[:2] if spoken else []),
                  '-map','0:v:0',*(audio_args[2:] if spoken else audio_args),
                  '-vf',color_filter,
                  '-c:v','libx264','-preset','medium','-crf','18','-threads','1','-r',rates.text(variant['rate']),
                  '-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709',
                  '-colorspace','bt709','-color_range','tv','-movflags','+faststart',str(target)],timeout)
            _check_media(target,w,h,n,timeout,color=variant['color'],with_audio=variant['audio']['mode']=='required',rate=variant['rate'])
            add('candidate',target,'video/mp4')
        return _result('succeeded', outputs, started=process_started())
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception('Local baseline adapter failed')
        return _result('failed', [], error=exc, started=process_started())


def _input_json(pin, resolve):
    value = json.loads(resolve(pin).read_bytes())
    return value['value'] if value.get('schema') == 'motion/v1/document' else value


def _caption_closure(inputs, resolve, resolve_artifact):
    from ..captions import check, caption_pin, require_renderable
    caption = _input_json(inputs['caption'], resolve)
    placement = _input_json(inputs['placement'], resolve)
    style = _input_json(inputs['style'], resolve)
    for value, schema in ((caption,'CaptionDocument'),(placement,'CaptionPlacement'),(style,'CaptionStyle')):
        check(value,schema)
    require_renderable(caption, ())
    if (placement['caption']['id'], placement['caption']['revision']) != (caption['caption_id'], caption['revision']) or placement['source_audio'] != caption['source_audio']:
        raise ValueError('Stale placement/caption closure')
    if not inputs['fonts'] or inputs['fonts'] != [face['face_artifact'] for face in style['fonts']]:
        raise ValueError('Ordered font pins must exactly match the selected style fallback chain')
    font = [resolve(pin) for pin in inputs['fonts']]
    # Retain optional source references; permission documents are not required.
    for face in style['fonts']:
        if 'rights_ref' in face:
            resolve_artifact(face['rights_ref'])
    resolve_artifact(caption['source_audio'])
    for pin in caption['timing_evidence'] + placement['conversion_receipts']:
        resolve_artifact(pin)
    return caption, placement, style, font


def _validate_mix_parameters(params, timeline):
    from fractions import Fraction
    rate, n, channels = params['sample_rate'], params['duration_samples'], params['channels']
    if channels not in (1, 2) or params['loudness_lufs'] is not None or params['true_peak_dbtp'] is not None:
        raise ValueError('No implicit channel or loudness conversion')
    if (not 0 < rate <= 48000 or Fraction(n, rate) != Fraction(timeline['duration_frames'], 1)/rates.fraction(params.get('rate', '30'))
            or not 0 < n <= rate*rates.MAX_SECONDS):
        raise ValueError('Exact bounded timeline/sample length required (one hour, 48 kHz)')


def _mix_audio(inputs, params, resolve, target):
    """Mix explicit sample-aligned PCM16 stems with bounded block memory."""
    from .streaming import mix
    timeline = _input_json(inputs['cue_sheet'], resolve)
    validate(timeline, D['Timeline'])
    _validate_mix_parameters(params, timeline)
    return mix(inputs, params, resolve, target, timeline)


def _candidate_audio(inputs, variant, resolve, resolve_artifact, media, timeout):
    if variant['audio']['mode'] == 'none':
        if set(inputs) - {'sidecars','sidecar_manifest'} != {'media'} or variant['captions'] not in ('none', 'sidecar'):
            raise ValueError('Silent candidate forbids unaccounted audio/captions')
        return ['-an']
    import wave
    from fractions import Fraction
    from ..captions import check, require_renderable
    keys = set(inputs) - {'sidecars','sidecar_manifest'}
    if variant['captions'] in ('burn', 'both'):
        if keys != {'media','audio','captions'}:
            raise ValueError('Burned delivery requires exact caption bindings')
        c = _input_json(inputs['captions'], resolve); check(c,'CaptionDocument'); require_renderable(c,())
        tags = {k.lower():v for k,v in probe(media,timeout=timeout)['format'].get('tags',{}).items()}
        from .caption_render import fingerprint
        if tags.get('motion_caption_sha256') != canonical_digest(c) or tags.get('motion_renderer_sha256') != fingerprint():
            raise ValueError('Burned-caption source does not bind current caption and shared renderer')
    elif keys != {'media','audio'} or variant['captions'] not in ('none','sidecar'):
        raise ValueError('Spoken delivery requires explicit audio and supported caption mode')
    a = variant['audio']
    # Numeric delivery targets are checked against measured final candidate
    # bytes by final_quality; they never authorize normalization or gain here.
    if a['codec'] not in ('alac','aac') or a['channels'] not in (1, 2):
        raise ValueError('Only explicit mono/stereo ALAC or AAC encoding supported')
    if a['codec']=='aac' and a['sample_rate'] not in (7350,8000,11025,12000,16000,22050,24000,32000,44100,48000):
        raise ValueError('AAC requires a supported explicit sample rate; no implicit resampling')
    audio = resolve(inputs['audio'])
    with wave.open(str(audio),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate()) != (a['channels'],2,a['sample_rate']) or Fraction(wav.getnframes(),wav.getframerate()) != Fraction(variant['duration_frames'],1)/rates.fraction(variant['rate']):
            raise ValueError('Candidate requires exact audio samples, no implicit pad/conform')
    codec_args = ['-c:a','alac'] if a['codec']=='alac' else [
        '-c:a','aac','-profile:a','aac_low','-b:a','128k','-ar',str(a['sample_rate'])]
    # MP4 edit-list endpoints otherwise round to its default millisecond clock.
    # Use source sample ticks so exact audio presentation length survives muxing.
    return ['-i',str(audio),'-map','1:a:0','-movie_timescale',str(a['sample_rate']),*codec_args]


def _bundle_entry(manifest):
    """Read the agreed closed source-bundle shape; never execute source code."""
    value = json.loads(manifest.read_text())
    if set(value) != {'schema','entry_member','members'} or value['schema'] != 'motion/v1/source-bundle':
        raise ValueError('Source must be a closed source-bundle manifest')
    if not isinstance(value['members'], list) or not 1 <= len(value['members']) <= 1000:
        raise ValueError('Invalid source bundle members')
    members = {}
    # B04/B07 managed artifacts retain manifest bytes and place closure in the
    # core-assigned <manifest>.members sibling directory. Standalone sources
    # retain original adjacent-member layout. No engine/source format fallback.
    managed_root = Path(str(manifest) + '.members')
    if managed_root.is_symlink():
        raise ValueError('Symlink source closure root')
    member_root = managed_root if managed_root.is_dir() else manifest.parent
    for member in value['members']:
        if set(member) != {'relative_path','sha256','size_bytes','media_type'}:
            raise ValueError('Invalid source bundle member fields')
        relative = member['relative_path']
        if not isinstance(relative,str) or not relative or Path(relative).is_absolute() or any(p in ('','.', '..') for p in relative.split('/')) or '\\' in relative:
            raise ValueError('Unsafe source member path')
        p = member_root
        for part in Path(relative).parts:
            p = p/part
            if p.is_symlink():
                raise ValueError('Symlink source member')
        p.resolve(strict=True).relative_to(member_root.resolve())
        if (relative in members or not p.is_file() or type(member['size_bytes']) is not int
                or p.stat().st_size != member['size_bytes'] or digest(p) != member['sha256']):
            raise ValueError('Source member identity differs')
        members[relative] = p
    if value['entry_member'] not in members:
        raise ValueError('Source entry member missing')
    return members[value['entry_member']]


def resolve_artifact_document(ref, resolver):
    """Resolve and verify an immutable DocumentRecord wrapper (not raw Variant)."""
    record = json.loads(Path(resolver(ref)).read_text())
    if canonical_digest(record) != ref['sha256'] or any(record[k] != ref[k] for k in ('kind','id','revision')):
        raise ValueError('Pinned document identity differs')
    return json.dumps(record['value'])


def _bounds(w,h,n,rate=None):
    rates.bounds(w,h,n,rate)


def _range(value, duration):
    if set(value) != {'start_frame','end_frame'}:
        raise ValueError('Invalid frame range')
    a,b = value['start_frame'],value['end_frame']
    if type(a) is not int or type(b) is not int or not 0<=a<b<=duration:
        raise ValueError('Invalid frame range')
    return a,b


def _result(state, outputs, message=None, code='INTERNAL_ERROR', *, error=None, started=True):
    # Filmmaking/Blender also call this helper, including its historical
    # positional and keyword message/code forms. Keep those forms conservative
    # while the FFmpeg lane passes the original structured exception directly.
    if error is None and message is not None:
        error = message if isinstance(message, BaseException) else ContractError(code, str(message))
    return dict(state=state,submission_state='confirmed' if started else 'not_sent',external_handle=None,
                remote_state='none',progress=None,outputs=outputs,warnings=[],
                error=None if error is None else dict(
                    code=error.code if isinstance(error, ContractError) else
                        'INVALID_ARGUMENT' if isinstance(error, (ValueError, KeyError)) else 'INTERNAL_ERROR',
                    message=error.message if isinstance(error, ContractError) else str(error),
                    retry='after_reconcile' if started else 'after_input_change',
                    effect='unknown' if started else getattr(error, 'effect', 'none'),
                    details=error.details if isinstance(error, ContractError) else {}),
                observed_cost=None,logs_ref=None,handoff=None)


def validate_timing(project_id, request, input_metadata, documents, *, resolve_artifact):
    """Pure narrow B06 compatibility check; actual decode remains owned B07 work.

    Future node media is not called measured: all scene source bytes and frozen
    project timing are checked here and generated media is checked at execution.
    """
    from ..contracts import ContractError
    from ..timeline import validate_timeline
    op, params = request['operation'], request['parameters']
    if op not in OPERATIONS or request.get('adapter_id') != ADAPTER_ID:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'No timing validator for this binding.')
    settings = documents['settings', 'project']['value']
    timeline = documents['timeline', 'project']['value']
    scenes = {key[1]: doc['value'] for key, doc in documents.items() if key[0] == 'scene'}
    rates.fraction(settings['rate'])
    validate_timeline(timeline, settings['rate'], settings['sample_rate'], scenes=scenes)
    try:
        if op == 'edit.assemble@1':
            if params['rate'] != settings['rate']:
                raise ValueError('Assembly rate differs from project')
            if params['range'] != dict(start_frame=0,end_frame=timeline['duration_frames']):
                raise ValueError('Baseline assembly requires exact full timeline')
            _bounds(params['canvas']['width_px'],params['canvas']['height_px'],timeline['duration_frames'],settings['rate'])
            consumed=[scenes[i['subject']['scene_id']] for track in timeline['tracks'] if track['kind']=='video'
                      for i in track['items'] if i['subject']['kind']=='scene']
            placed = [i for track in timeline['tracks'] if track['kind']=='video' for i in track['items'] if i['subject']['kind']=='scene']
            if any(scenes[i['subject']['scene_id']]['canvas'] != params['canvas'] and not i.get('crop') for i in placed):
                raise ValueError('Scene/assembly canvas requires explicit conform')
        elif op == 'audio.mix@1':
            _validate_mix_parameters(params, timeline)
        else:
            variants = documents['variants', 'project']['value']
            variant = next(v for v in variants if v['variant_id'] == params['variant'])
            if variant['duration_frames'] != timeline['duration_frames'] or variant['rate'] != settings['rate']:
                raise ValueError('Variant timing requires explicit conform')
            consumed=[scenes[i['subject']['scene_id']] for track in timeline['tracks'] if track['kind']=='video'
                      for i in track['items'] if i['subject']['kind']=='scene']
            if any((s['canvas']['width_px'],s['canvas']['height_px']) !=
                   (variant['width_px'],variant['height_px']) for s in consumed):
                raise ValueError('Variant canvas requires explicit conform')
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise ContractError('TIMING_INVALID', str(exc)) from exc
    return []


def registration():
    """Explicit read-only metadata for CapabilityRegistry.register(**...).

    Does not mark availability available: caller inspects dependencies and pins
    this implementation in the normal B06/B07 path. No engine is invoked here.
    """
    from ..capabilities import PARAMS, expanded
    from ..contracts import TEXT, DIGEST, nullable, obj, arr, enum, ref
    schemas, outputs = {}, {}
    descriptor = obj(dict(port=TEXT, relative_path=TEXT, media_type=TEXT,
                          claimed_sha256=nullable(DIGEST)))
    result = obj(dict(
        state=enum('running','awaiting_external','review_needed','succeeded','failed','cancelled','interrupted'),
        submission_state=enum('not_sent','intent_recorded','confirmed','uncertain'),
        external_handle={'type':'null'}, remote_state={'const':'none'}, progress={'type':'null'},
        outputs=arr(descriptor), warnings=arr(TEXT),
        error=nullable(obj(dict(code=TEXT,message=TEXT,retry=TEXT,effect=TEXT,
                                details={'type':'object','additionalProperties':{}}))),
        observed_cost={'type':'null'},logs_ref={'type':'null'},handoff={'type':'null'}))
    ports = {
        'edit.assemble@1': [('media','media','video/x-matroska'),
                            ('source','assembly_source','application/vnd.motion.source-bundle+json')],
        'delivery.encode@1': [('candidate','media','video/mp4')],
        'audio.mix@1': [('audio','audio','audio/wav'), ('source','json','application/json')],
        'caption.render@1': [('media','media','video/x-matroska'), ('frame','frame','image/png')]}
    for operation in declaration()['operations']:
        op = operation['operation']
        schemas[operation['request_schema']] = expanded(PARAMS[op])
        schemas[operation['result_schema']] = result
        outputs[op] = [dict(port=p,kind=k,media_type=m) for p,k,m in ports[op]]
    schemas['motion/v1/no-options'] = NO_OPTIONS
    schemas['motion/v1/local-ffmpeg/no-options'] = NO_OPTIONS
    from .caption_render import fingerprint
    return dict(declaration=declaration(), implementation_sha256=canonical_digest(dict(adapter=digest(__file__),
                helpers={name:digest(Path(__file__).with_name(name)) for name in ('limits.py','rates.py','streaming.py','color_pipeline.py')},renderer=fingerprint())),
                schemas=schemas, outputs=outputs)
