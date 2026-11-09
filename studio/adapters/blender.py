"""Optional editable Blender scenes on the owned native job ABI.

Discovery is PATH metadata only. Authored .blend files are trusted native code,
NOT sandboxed. No JSON-supplied Python, command lines, plugins or acquisition.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..contracts import ContractError, D, canonical, digest, enum, integer, obj, validate
from . import ffmpeg
from . import rates
from .limits import MAX_WIDTH, MAX_HEIGHT, MAX_FRAMES
from .media_probe import result_schema

ADAPTER_ID = 'local.blender'
VERSION = '0.1.0'
OPERATIONS = ('scene.render@1', 'scene.frame@1')
ENGINES = ('CYCLES', 'BLENDER_EEVEE_NEXT', 'BLENDER_WORKBENCH')
HELPER = Path(__file__).resolve().parents[1] / 'filmmaking' / 'blender_render.py'
EFFECTS = dict(ffmpeg.EFFECTS)
SOURCE_MIME = 'application/vnd.motion.source-bundle+json'
WARNING = ('Trusted authored Blender files are not an OS sandbox; automatic embedded '
           'scripts are disabled, but native parsers, drivers and installed render engines remain trusted.')


def discover() -> dict[str, Any]:
    """No execution, version probe, import of bpy, installation or environment mutation."""
    found = {name: shutil.which(name) for name in ('blender', 'ffmpeg', 'ffprobe')}
    return dict(found, available=all(found.values()), missing=[k for k, v in found.items() if not v])


def operation_schema(operation):
    """Adapter-local schema; parent must coordinate the public PARAMS vocabulary.

    Keep existing scene operation identities. Canvas/rate are explicit and must
    agree with frozen Scene/project settings, not implicit Blender defaults.
    """
    if operation not in OPERATIONS:
        raise ValueError('Unsupported Blender operation')
    fields = dict(scene=copy.deepcopy(D['DocumentRef']),
                  canvas=obj(dict(width_px=integer(160, MAX_WIDTH), height_px=integer(120, MAX_HEIGHT))),
                  rate=copy.deepcopy(D['Rate']), alpha=enum('none', 'straight'),
                  engine=enum(*ENGINES))
    if operation == 'scene.render@1':
        fields.update(range=obj(dict(start_frame=integer(), end_frame=integer(1))),
                      quality=enum('preview', 'final'))
    else:
        fields['frame'] = integer()
    return obj(fields, optional=['engine'])


def registration() -> dict[str, Any]:
    """Pure declaration with a complete adapter + static helper implementation hash."""
    from ..capabilities import expanded
    base = dict(media_types=[SOURCE_MIME, 'application/x-blender', 'application/octet-stream'],
                codecs=['ffv1', 'png'], max_width_px=MAX_WIDTH, max_height_px=MAX_HEIGHT,
                min_rate={'num': 24000, 'den': 1001}, max_rate={'num': 60, 'den': 1},
                languages=[], color_spaces=[], alpha_modes=['none'], timing='frame',
                max_duration_frames=MAX_FRAMES)
    operations, schemas, outputs = [], {}, {}
    for operation in OPERATIONS:
        prefix = 'motion/v1/blender/' + operation
        constraints = dict(base, codecs=['png'] if operation == 'scene.frame@1' else ['ffv1'],
                           alpha_modes=['none', 'straight'] if operation == 'scene.frame@1' else ['none'])
        operations.append(dict(operation=operation, request_schema=prefix+'/request', result_schema=prefix+'/result',
            features=['timing.frame_exact', 'scene.editable', 'scene.physical'] +
                     (['image.alpha'] if operation == 'scene.frame@1' else []),
            constraints=constraints, determinism='unknown',
            supports=dict(status=False, cancel=False, collect=False, resume=False,
                          provider_idempotency=False, lookup_by_request=False), default_timeout_seconds=3600))
        schemas[prefix+'/request'] = expanded(operation_schema(operation))
        schemas[prefix+'/result'] = result_schema()
        movie = operation == 'scene.render@1'
        outputs[operation] = [dict(port='media' if movie else 'frame', kind='media' if movie else 'frame',
            media_type='video/x-matroska' if movie else 'image/png'),
            dict(port='source', kind='scene_source', media_type=SOURCE_MIME),
            dict(port='report', kind='report', media_type='application/json')]
    declaration = dict(schema='motion/v1/adapter-declaration', adapter_id=ADAPTER_ID,
        label='Editable physical scenes / optional local Blender', abi_version='1.0', implementation_version=VERSION,
        transport='cli', location='local', operations=operations,
        dependencies=[dict(name=n, kind='executable', version_constraint='>=4.2' if n == 'blender' else None,
                           required=True) for n in ('blender', 'ffmpeg', 'ffprobe')],
        credential_refs=[], effects=dict(EFFECTS), license=None,
        resource_needs=dict(cpu_threads=1, ram_bytes=None, gpu_vram_bytes=None, exclusive_resource=None))
    identity = hashlib.sha256()
    for name, path in [('adapters/blender.py', Path(__file__)), ('filmmaking/blender_render.py', HELPER)]:
        identity.update(name.encode()); identity.update(b'\0'); identity.update(path.read_bytes()); identity.update(b'\0')
    return dict(declaration=declaration, implementation_sha256='sha256:'+identity.hexdigest(),
                schemas=schemas, outputs=outputs)


def _source(path) -> tuple[Path, list[dict[str, Any]], str]:
    """Accept a verified bundle, or an immutable self-contained .blend artifact.

    Managed artifact paths have no extension; the BLENDER magic identifies the
    native standalone file. Compressed blend files must use the bundle route.
    """
    path = Path(path)
    with path.open('rb') as stream:
        native = stream.read(7) == b'BLENDER'
    if native:
        return path, [dict(relative_path='scene.blend', sha256=ffmpeg.digest(path),
                           size_bytes=path.stat().st_size, media_type='application/x-blender')], 'scene.blend'
    entry = ffmpeg._bundle_entry(path)
    bundle = json.loads(path.read_bytes())
    if entry.suffix.lower() != '.blend':
        raise ValueError('Source bundle entry must be a .blend file')
    return entry, bundle['members'], bundle['entry_member']


def _settings(parameters, scene):
    validate(parameters, operation_schema('scene.render@1' if 'range' in parameters else 'scene.frame@1'))
    canvas = parameters['canvas']
    if canvas != scene['canvas']:
        raise ValueError('Explicit Blender canvas differs from frozen Scene')
    rate = Fraction(parameters['rate']['num'], parameters['rate']['den'])
    from . import rates
    rates.fraction(rate)
    ffmpeg._bounds(canvas['width_px'], canvas['height_px'], scene['duration_frames'],parameters['rate'])
    if 'range' in parameters:
        if parameters['alpha'] != 'none':
            raise ValueError('Animation alpha is unsupported; use straight-alpha scene.frame@1, never flatten implicitly')
        a, b = ffmpeg._range(parameters['range'], scene['duration_frames'])
    else:
        a, b = parameters['frame'], parameters['frame'] + 1
        if not 0 <= a < scene['duration_frames']:
            raise ValueError('Frame outside frozen Scene')
    # Scene coordinates are zero-based; native Blender frame = scene frame + 1.
    return a, b


def validate_timing(project_id, request, metadata, documents, *, resolve_artifact):
    """Plan-time pin/closure validation only; no Blender process or bpy import."""
    ref = request['parameters']['scene']
    record = documents.get(('scene', ref['id']))
    if not record or record['revision'] != ref['revision'] or digest(record) != ref['sha256']:
        raise ContractError('TIMING_INVALID', 'Frozen Blender Scene identity differs')
    scene = record['value']
    from ..preproduction import validate_scene_binding
    validate_scene_binding(scene, documents)
    identity = scene.get('source_runtime')
    if (scene['source_format'] != 'blender' or not identity or identity['adapter_id'] != ADAPTER_ID
            or identity['implementation_version'] != VERSION or identity['engine'] != 'Blender'
            or identity.get('dependencies') != []):
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Explicit blender Scene/runtime identity required')
    if request['inputs'].get('source') != dict(kind='artifact', artifact=scene['authored_source']):
        raise ContractError('TIMING_INVALID', 'Source differs from frozen Blender Scene')
    if request['inputs'].get('assets') != [dict(kind='artifact', artifact=p) for p in scene['assets']]:
        raise ContractError('TIMING_INVALID', 'Frozen asset pins differ')
    if scene['assets']:
        raise ContractError('TIMING_INVALID', 'Blender dependencies must be packed or declared in the source bundle; assets must be empty')
    if request['parameters']['rate'] != documents['settings', 'project']['value']['rate']:
        raise ContractError('TIMING_INVALID', 'Explicit Blender rate differs from project')
    try:
        _settings(request['parameters'], scene)
        path = Path(resolve_artifact(scene['authored_source']))
        if ffmpeg.digest(path) != scene['authored_source']['sha256']:
            raise ValueError('Frozen source pin differs')
        _, _, entry = _source(path)
        if identity['entry_member'] != entry:
            raise ValueError('Native entry differs from source_runtime')
    except (KeyError, ValueError, OSError) as exc:
        raise ContractError('TIMING_INVALID', str(exc)) from exc
    return [WARNING, 'External dependencies and unsupported caches are checked by Blender during the owned execution.']


def _stage_source(path, destination) -> tuple[list[dict[str, Any]], str]:
    entry, members, name = _source(path)
    root = entry
    for _ in Path(name).parts:
        root = root.parent
    destination.mkdir()
    for member in members:
        target = destination / member['relative_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        source = entry if len(members) == 1 and name == 'scene.blend' and path == entry else root/member['relative_path']
        shutil.copyfile(source, target)
        if ffmpeg.digest(target) != member['sha256'] or target.stat().st_size != member['size_bytes']:
            raise ValueError('Staged Blender member differs from immutable source closure')
    return members, name


def _native_manifest(stage, members, entry) -> dict[str, Any]:
    """Retain native scene and its full hashed closure through existing collector."""
    rows = []
    for member in members:
        path = stage/member['relative_path']
        if path.is_symlink() or not path.is_file():
            raise ValueError('Native scene closure changed shape')
        rows.append(dict(member, sha256=ffmpeg.digest(path), size_bytes=path.stat().st_size))
    return dict(schema='motion/v1/source-bundle', entry_member=entry, members=rows)


class BlenderAdapter:
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, copy.deepcopy(binding)

    def validate_request(self, request):
        if request['operation'] not in OPERATIONS:
            raise ContractError('UNSUPPORTED_OPERATION', 'Unsupported Blender operation')
        expected = self.runtime.registry.binding(ADAPTER_ID, request['operation'], request['parameters'],
                                                 request.get('binding_parameters'))
        if self.binding != expected or request['binding'] != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen Blender implementation/schema differs')
        validate(request['parameters'], operation_schema(request['operation']))
        if set(request['inputs']) != {'source', 'assets'} or request['inputs']['assets'] != []:
            raise ContractError('INVALID_ARGUMENT', 'Explicit source and empty assets required; use native source closure')
        validate(request['inputs']['source'], D['ArtifactRef'])
        if request['effects'] != EFFECTS:
            raise ContractError('PERMISSION_DENIED', 'Blender effects differ from declaration')
        declared = next(op for op in registration()['declaration']['operations'] if op['operation'] == request['operation'])
        if set(request['required_features']) - set(declared['features']):
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Unsupported required Blender feature')
        if request.get('binding_parameters') is not None:
            raise ContractError('INVALID_ARGUMENT', 'Blender accepts no opaque binding options')
        return dict(valid=True, effects=dict(EFFECTS))

    def execute(self, request, attempt, context=None):
        self.validate_request(request)
        if not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run required')
        runner = getattr(context, 'run')
        frames = None
        try:
            if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
                raise ContractError('PERMISSION_DENIED', 'Owned attempt authority required')
            found = discover()
            if not found['available']:
                raise ContractError('DEPENDENCY_UNAVAILABLE', 'Missing optional local dependencies: '+', '.join(found['missing']))
            deadline = datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00'))
            def run(argv, **kwargs):
                seconds = (deadline-datetime.now(timezone.utc)).total_seconds()
                if seconds <= 0:
                    raise TimeoutError('Blender attempt deadline elapsed')
                kwargs['timeout'] = min(seconds, kwargs.get('timeout', seconds))
                kwargs['check'] = True
                return runner(argv, **kwargs)
            p, pid = request['parameters'], request['project_id']
            scene = self.runtime.document(pid, p['scene'])['document']['value']
            identity = scene.get('source_runtime')
            if (scene['source_format'] != 'blender' or not identity or identity['adapter_id'] != ADAPTER_ID
                    or identity['implementation_version'] != VERSION or identity['engine'] != 'Blender'
                    or identity.get('dependencies') != []):
                raise ValueError('Explicit frozen Blender source/runtime identity required')
            if request['inputs']['source'] != scene['authored_source'] or scene['assets']:
                raise ValueError('Frozen Blender source/asset closure differs')
            a, b = _settings(p, scene)
            source = Path(self.runtime.artifact_path(pid, scene['authored_source']))
            if ffmpeg.digest(source) != scene['authored_source']['sha256']:
                raise ValueError('Source artifact identity differs')
            out = ffmpeg._output_dir(self.runtime.projects._filesystem().root, attempt['output_dir'])
            # Source members stay adjacent to the output manifest for B07 collection.
            stage = out/'native'
            members, entry = _stage_source(source, stage)
            if identity['entry_member'] != entry:
                raise ValueError('Source runtime entry differs from staged native scene')
            frames = out/'frames'; frames.mkdir()
            config = dict(root=str(stage), entry=entry, members=[m['relative_path'] for m in members],
                          frames=str(frames), report=str(out/'blender-observed.json'),
                          canvas=p['canvas'], rate=p['rate'], start=a, end=b,
                          duration_frames=scene['duration_frames'], alpha=p['alpha'], engine=p.get('engine'))
            config_path = out/'blender-config.json'; config_path.write_bytes(canonical(config))
            helper = out/'blender_render.py'
            shutil.copyfile(HELPER, helper)
            if ffmpeg.digest(helper) != ffmpeg.digest(HELPER):
                raise ValueError('Static Blender helper changed during staging')
            with (out/'blender.log').open('xb') as log:
                run([found['blender'], '--background', '--factory-startup', '--disable-autoexec',
                     '--threads', '1', '--python-exit-code', '1', '--python', str(helper), '--', str(config_path)],
                    stdout=log, stderr=subprocess.STDOUT)
            observed_path = out/'blender-observed.json'
            if observed_path.stat().st_size > 1024*1024:
                raise ValueError('Blender observation report exceeds bound')
            observed = json.loads(observed_path.read_bytes())
            if identity.get('engine_version') not in (None, observed['blender_version']):
                raise ValueError('Observed Blender version differs from pinned runtime engine_version')
            if (observed['canvas'] != p['canvas'] or observed['rate'] != p['rate']
                    or observed['frames'] != b-a or observed['alpha'] != p['alpha']):
                raise ValueError('Blender execution settings differ from request')
            expected_files = [f'{i:08d}.png' for i in range(b-a)]
            if sorted(path.name for path in frames.iterdir()) != expected_files:
                raise ValueError('Blender output frame set differs from exact requested range')
            movie = request['operation'] == 'scene.render@1'
            target = out/('scene.mkv' if movie else 'frame.png')
            if movie:
                rate = f"{p['rate']['num']}/{p['rate']['den']}"
                run([found['ffmpeg'], '-nostdin', '-v', 'error', '-n', '-framerate', rate,
                     '-start_number', '0', '-i', str(frames/'%08d.png'), '-frames:v', str(b-a),
                     '-an', '-r', rate, '-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'bgr0', '-threads', '1',
                     *rates.stamp(p['rate']), str(target)])
            else:
                shutil.copyfile(frames/'00000000.png', target)
            metadata = registration()
            ports = {port['port']: port for port in metadata['outputs'][request['operation']]}
            media_port = ports['media' if movie else 'frame']
            receipt_id = self.runtime.output_probe.validate_file(target, media_port, run_process=run)
            self._check_output(target, p, b-a, movie, found, run)
            # Bundle paths are manifest-relative, including the native/ prefix.
            native = _native_manifest(stage, members, entry)
            native['entry_member'] = 'native/'+native['entry_member']
            for row in native['members']:
                row['relative_path'] = 'native/'+row['relative_path']
            manifest = out/'source-bundle.json'; manifest.write_bytes(canonical(native))
            ffmpeg._bundle_entry(manifest)
            report = out/'render-report.json'
            report.write_bytes(canonical(dict(schema='motion/v1/blender-render', scene=p['scene'],
                input_source=scene['authored_source'], implementation=request['binding']['implementation_sha256'],
                observed=observed, output_probe_receipt=receipt_id, host=found,
                range=dict(start_frame=a, end_frame=b), warning=WARNING,
                color_policy='Native Blender display/view transform retained; no invented BT.709 tagging.',
                quality_policy='Native engine samples and quality retained; preview/final is intent, not an override.')))
            descriptors = [dict(port=port, relative_path=path.name, media_type=ports[port]['media_type'],
                                claimed_sha256=ffmpeg.digest(path)) for port, path in
                           [(media_port['port'], target), ('source', manifest), ('report', report)]]
            result = ffmpeg._result('succeeded', descriptors)
            result['warnings'] = [WARNING]
            return result
        except Exception as exc:
            return ffmpeg._result('failed', [], str(exc)[-1800:], getattr(exc, 'code', 'OUTPUT_INVALID'))
        finally:
            if frames is not None:
                shutil.rmtree(frames, ignore_errors=True)

    @staticmethod
    def _check_output(path, p, count, movie, found, run):
        """Supplement existing decode proof with exact request conformance facts."""
        raw = json.loads(run([found['ffprobe'], '-v', 'error', '-count_frames', '-show_streams',
                              '-of', 'json', str(path)]).stdout)
        streams = raw.get('streams', [])
        if len(streams) != 1 or streams[0]['codec_type'] != 'video':
            raise ValueError('Blender output must have exactly one silent video/image stream')
        stream = streams[0]
        if (stream['width'], stream['height']) != (p['canvas']['width_px'], p['canvas']['height_px']):
            raise ValueError('Decoded Blender canvas differs')
        if int(stream['nb_read_frames']) != count:
            raise ValueError('Decoded Blender frame count differs')
        if movie and (stream['codec_name'] != 'ffv1' or rates.observed(stream) !=
                      Fraction(p['rate']['num'], p['rate']['den'])):
            raise ValueError('Decoded Blender codec/rate differs')
        if not movie:
            alpha_format = stream.get('pix_fmt', '').startswith(('rgba', 'bgra', 'argb', 'abgr', 'yuva', 'gbrap', 'ya'))
            if stream['codec_name'] != 'png' or (p['alpha'] == 'straight') != alpha_format:
                raise ValueError('Decoded PNG alpha/codec differs; alpha is never discarded implicitly')
