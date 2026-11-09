"""Editable, self-contained HTML film capture through Studio's owned job path.

Source is trusted authored code, NOT an OS sandbox. Only manifest members are
served; browser networking is denied. No provider dispatch, installs or services.
"""
from __future__ import annotations
import copy
import hashlib
import json
import mimetypes
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from datetime import datetime, timezone

from ..contracts import ContractError, D, canonical, digest, validate
from . import ffmpeg
from .media_probe import result_schema
from .limits import MAX_FRAMES, MAX_WIDTH, MAX_HEIGHT
from .. import gpu_route
from ..monitoring import sanitize

ADAPTER_ID = 'local.filmmaking'
VERSION = '1.2.0'
RESOURCES = Path(__file__).resolve().parents[1] / 'filmmaking'
OPERATIONS = ('scene.render@1', 'scene.frame@1')
FEATURES = ['timing.frame_exact', 'filmmaking.editable', 'filmmaking.cut_aware']
EFFECTS = dict(ffmpeg.EFFECTS)


def discover():
    """Passive host-local path discovery. Availability is not an exercised render."""
    configured = os.environ.get('MOTION_CHROME')
    chrome = (shutil.which(configured) if configured else None) or (None if configured else next(
        (p for name in ('google-chrome', 'chromium', 'chromium-browser', 'chrome')
         if (p := shutil.which(name))), None))
    found: dict[str, Any] = {n: shutil.which(n) for n in ('node', 'ffmpeg', 'ffprobe')}
    found['chrome'] = chrome
    found['available'] = all(found.values())
    found['missing'] = [k for k, v in found.items() if k not in ('available', 'missing') and not v]
    return found


def runtime_versions(found, run):
    """Observe only the engines used by the owned render/reconstruction attempt."""
    versions={}
    for name,args in [('node',['--version']),('chrome',['--version']),('ffmpeg',['-version']),('ffprobe',['-version'])]:
        completed=run([found[name],*args])
        output=completed.stdout
        if isinstance(output,bytes):output=output.decode(errors='replace')
        versions[name]=(output or '').strip().splitlines()[0] if (output or '').strip() else ''
        if not versions[name]:raise ValueError('No observed runtime version: '+name)
    match=re.fullmatch(r'v(\d+)\.\d+\.\d+(?:[-+].*)?',versions['node'])
    if not match or int(match[1])<22:
        raise ContractError('DEPENDENCY_UNAVAILABLE','Filmmaking requires Node >=22 with built-in WebSocket; observed '+versions['node'])
    return versions


def registration() -> dict[str, Any]:
    from ..capabilities import expanded, PARAMS
    constraints = dict(media_types=['application/vnd.motion.source-bundle+json', 'image/png',
        'image/jpeg', 'image/svg+xml', 'video/mp4', 'font/ttf', 'font/otf',
        'font/woff2', 'application/json'], codecs=['ffv1'],
        max_width_px=MAX_WIDTH, max_height_px=MAX_HEIGHT,
        min_rate={'num':24000,'den':1001}, max_rate={'num':60,'den':1}, languages=[],
        color_spaces=['bt709'], alpha_modes=['none'], timing='frame', max_duration_frames=MAX_FRAMES)
    operations: list[dict[str, Any]] = [dict(operation=op,request_schema='motion/v1/filmmaking/'+op+'/request',
        result_schema='motion/v1/filmmaking/'+op+'/result', features=FEATURES,
        constraints=constraints, determinism='unknown',
        supports=dict(status=False,cancel=False,collect=False,resume=False,
                      provider_idempotency=False,lookup_by_request=False),
        default_timeout_seconds=1800) for op in OPERATIONS]
    declaration = dict(schema='motion/v1/adapter-declaration', adapter_id=ADAPTER_ID,
        label='Editable local filmmaking / Chromium and FFmpeg',abi_version='1.0',
        implementation_version=VERSION,transport='cli',location='local',operations=operations,
        dependencies=[dict(name=n,kind='executable',version_constraint='>=22' if n=='node' else None,
                           required=True) for n in ('node','Chromium','ffmpeg','ffprobe')],
        credential_refs=[],effects=EFFECTS,license=None,
        resource_needs=dict(cpu_threads=1,ram_bytes=None,gpu_vram_bytes=gpu_route.MIN_FREE_BYTES,
                            exclusive_resource='chromium-native-nvidia-linux-v1'))
    files = [Path(__file__), Path(gpu_route.__file__), *sorted(p for p in RESOURCES.rglob('*') if p.is_file())]
    identity = hashlib.sha256()
    for p in files:
        name = p.relative_to(RESOURCES).as_posix() if p.is_relative_to(RESOURCES) else p.name
        identity.update(name.encode()); identity.update(b'\0'); identity.update(p.read_bytes())
    schemas, outputs = {}, {}
    for op in operations:
        schemas[op['request_schema']] = expanded(PARAMS[op['operation']])
        schemas[op['result_schema']] = result_schema()
        # Explicit open diagnostics must agree in native and JSON Schema validators.
        schemas[op['result_schema']]['properties']['error']['anyOf'][0]['properties']['details']['additionalProperties'] = {}
        outputs[op['operation']] = [dict(port='media' if op['operation']=='scene.render@1' else 'frame',
            kind='media' if op['operation']=='scene.render@1' else 'frame',
            media_type='video/x-matroska' if op['operation']=='scene.render@1' else 'image/png'),
            dict(port='report',kind='report',media_type='application/json')]
    return dict(declaration=declaration,implementation_sha256='sha256:'+identity.hexdigest(),
                schemas=schemas,outputs=outputs)


def source_entry(manifest):
    return ffmpeg._bundle_entry(Path(manifest))


def package_source(root, entry, members):
    """Create closure metadata from actual local bytes, never acquire assets."""
    root = Path(root).resolve(strict=True)
    rows=[]
    for name in members:
        from ..contracts import safe_relative
        safe_relative(name)
        file=root/name
        if any(part.is_symlink() for part in [file, *file.parents] if part != root and part.is_relative_to(root)):
            raise ValueError('Symlink source member')
        file.resolve(strict=True).relative_to(root)
        if not file.is_file(): raise ValueError('Regular source member required')
        rows.append(dict(relative_path=name,sha256=ffmpeg.digest(file),size_bytes=file.stat().st_size,
                         media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream'))
    if entry not in members or len(set(members)) != len(members):
        raise ValueError('Unique closure and declared entry required')
    return dict(schema='motion/v1/source-bundle',entry_member=entry,members=rows)


def package_kinetic_source(root, members):
    """Vendor the local engine beside an existing spec.js and known assets.

    No provider calls, dependencies, original-profile paths or overwritten files.
    The inherited Kinetic blocks retain their native 1920x1080 composition;
    independently composed canvases use package_source/bindScene instead.
    """
    root = Path(root).resolve(strict=True)
    if 'spec.js' not in members:
        raise ValueError('An explicit editable spec.js is required')
    # Validate every authored input before writing any resources.
    package_source(root, 'spec.js', members)
    engine = RESOURCES / 'kinetic'
    resources = sorted(p for p in engine.rglob('*') if p.is_file())
    names = [p.relative_to(engine).as_posix() for p in resources]
    if any((root / name).exists() or (root / name).is_symlink() for name in names):
        raise ValueError('Engine destinations must be unused; refusing overwrite')
    for source, name in zip(resources, names):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return package_source(root, 'index.html', [*members, *names])


def shutter_window(t, fps, cuts, shutter=1.0, duration=None):
    """Half-open shot exposure; mirrors filmmaking/timing.mjs without cut epsilons.

    Duration is required by capture; the optional value keeps the authoring helper
    usable for an interior frame when the final film duration is not yet known.
    """
    if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (t,fps,shutter))
            or t<0 or fps<=0 or not 0<=shutter<=8):
        raise ValueError('Invalid exposure')
    if duration is not None and (not math.isfinite(duration) or not 0<=t<duration):
        raise ValueError('Frame outside film')
    if (not isinstance(cuts,list) or any(type(c) not in (int,float) or not math.isfinite(c)
            or c<=0 or (duration is not None and c>=duration)
            or (i and c<=cuts[i-1]) for i,c in enumerate(cuts))):
        raise ValueError('Cuts must be unique ascending interior seconds')
    left=max([0,*[c for c in cuts if c<=t]])
    right=next((c for c in cuts if c>t), duration if duration is not None else math.inf)
    length=0.5*shutter/fps
    a,b=t,min(t+length,right)
    if b<t+length:a=max(left,b-length)
    if b==right:b=max(t,math.nextafter(right,-math.inf))
    return min(a,b),b


def sample_times(t, window, requested, cap):
    if any(type(n) is not int or not 1<=n<=64 for n in (requested,cap)):
        raise ValueError('Invalid subframe samples')
    a,b=window
    n=1 if a==b else min(requested,cap)
    return [t] if n==1 else [min(b,a+(b-a)*j/(n-1)) for j in range(n)]


def _storyboard_panel(runtime, project_id, panel_id):
    # Use the same authoritative public read path as the storyboard tool.
    from ..preproduction import production_handler
    result=json.loads(production_handler('motion_storyboard',dict(action='get',project_id=project_id),_runtime=runtime))
    if not result.get('ok') or result['data'].get('stale') or not result['data'].get('value'):
        raise ContractError('ASSETS_UNRESOLVED','Current assessed storyboard required.')
    board=result['data']['value']
    library=json.loads(production_handler('motion_asset_library',dict(action='get',project_id=project_id),_runtime=runtime))
    if not library.get('ok') or not library['data']['value']['assessed']:
        raise ContractError('ASSETS_UNRESOLVED','Current assessed asset library required.')
    if board['asset_library_sha256'] != library['data']['document']['sha256']:
        raise ContractError('ASSETS_UNRESOLVED','Storyboard asset-library identity changed.')
    matches=[p for p in board['panels'] if p['panel_id']==panel_id]
    if len(matches)!=1: raise ContractError('NOT_FOUND','Storyboard panel missing.')
    p=matches[0]
    assets=[p['visual']]
    requirements={r['requirement_id']:r for r in library['data']['value']['requirements']}
    for key in p['asset_requirements']:
        requirement=requirements.get(key)
        if not requirement or requirement['status']!='ready' or not requirement.get('asset'):
            raise ContractError('ASSETS_UNRESOLVED','Panel asset requirement is not ready.')
        if requirement['asset'] not in assets:assets.append(requirement['asset'])
    return p, assets, dict(schema='motion/v1/storyboard-panel',panel=p,
        storyboard=result['data']['document'],asset_library=library['data']['document'])


def package_storyboard_source(runtime, project_id, panel_id, root, entry, members):
    """Retain the complete saved panel beside authored source, without another store."""
    _, _, record = _storyboard_panel(runtime, project_id, panel_id)
    package_source(root, entry, members)
    target=Path(root)/'storyboard-panel.json'
    with target.open('xb') as stream:stream.write(canonical(record))
    return package_source(root, entry, [*members,'storyboard-panel.json'])


def _source_panel(manifest):
    entry=source_entry(manifest)
    bundle=json.loads(manifest.read_bytes())
    if 'storyboard-panel.json' not in [m['relative_path'] for m in bundle['members']]:
        raise ContractError('ASSETS_UNRESOLVED','Bound source must retain storyboard-panel.json.')
    root=entry
    for _ in Path(bundle['entry_member']).parts:root=root.parent
    return json.loads((root/'storyboard-panel.json').read_bytes())


def storyboard_scene(runtime, project_id, panel_id, variant, canvas, source):
    """Bridge one current assessed panel and its editable source to a native scene."""
    p, assets, record = _storyboard_panel(runtime, project_id, panel_id)
    runtime.artifacts.resolve(project_id,source)
    manifest=Path(runtime.artifact_path(project_id,source))
    if _source_panel(manifest)!=record:
        raise ContractError('ASSETS_UNRESOLVED','Editable source panel differs from current storyboard.')
    entry=json.loads(manifest.read_text())['entry_member']
    return dict(label=p['title']+' / '+variant,duration_frames=p['duration_frames'],canvas=canvas,
        assets=assets,layout=[dict(element_key=p['panel_id'],rect=dict(x_px=0,y_px=0,**canvas),
            z=0,opacity='1',asset=p['visual'])],safe_zones=[],
        motion_intent=p['motion']+'\nText: '+p['on_screen_text']+'\nNarration: '+p['narration']+'\nTransition: '+p['transition'],
        camera_intent='Explicit '+variant+' native layout; '+p['notes'],
        authored_source=source,source_format='motion-html',source_runtime=dict(adapter_id=ADAPTER_ID,
            implementation_version=VERSION,engine='Chromium',engine_version=None,dependencies=[],
            entry_member=entry),storyboard_binding=dict(storyboard=record['storyboard'],
            asset_library=record['asset_library'],panel_id=panel_id,variant_id=variant))


def validate_timing(project_id, request, metadata, documents, *, resolve_artifact, projects=None):
    params=request['parameters']; ref=params['scene']
    document=documents.get(('scene',ref['id']))
    if (ref.get('kind') != 'scene' or document is None or
            document['project_id'] != project_id or document['kind'] != 'scene' or
            document['id'] != ref['id'] or document['revision'] != ref['revision'] or
            digest(document) != ref['sha256']):
        raise ContractError('TIMING_INVALID','Frozen scene identity differs.')
    scene=document['value']
    from ..preproduction import validate_scene_binding, validate_stored_scene_binding
    # The runtime supplies its existing store, never a new registry or a caller
    # supplied source document. Standalone validators remain strict-current.
    if projects is None:
        panel = validate_scene_binding(scene, documents)
    else:
        fs = projects._filesystem()
        pointer = projects._pointer(fs, project_id)
        panel = validate_stored_scene_binding(projects, fs, pointer, scene, documents)
    source=request['inputs']['source']
    if source.get('kind')!='artifact' or source['artifact']!=scene['authored_source']:
        raise ContractError('TIMING_INVALID','Source differs from frozen scene authored_source.')
    from . import rates
    cadence = documents['settings','project']['value']['rate']
    rates.fraction(cadence)
    if rates.fraction(params.get('rate', '30')) != rates.fraction(cadence):
        raise ContractError('TIMING_INVALID','Freeze the exact project cadence in scene parameters.rate.')
    if params['alpha']!='none':
        raise ContractError('TIMING_INVALID','This binding supports opaque films.')
    identity=scene['source_runtime']
    if not identity or identity['adapter_id']!=ADAPTER_ID or scene['source_format']!='motion-html':
        raise ContractError('TIMING_INVALID','Explicit motion-html authored source required.')
    if identity['implementation_version']!=VERSION or identity['engine']!='Chromium':
        raise ContractError('ADAPTER_INCOMPATIBLE','Authored scene requires the current filmmaking runtime identity.')
    assets=request['inputs'].get('assets')
    if assets!=[dict(kind='artifact',artifact=pin) for pin in scene['assets']]:
        raise ContractError('TIMING_INVALID','Render assets differ from the frozen scene closure.')
    try:
        ffmpeg._bounds(scene['canvas']['width_px'],scene['canvas']['height_px'],scene['duration_frames'],cadence)
        if request['operation']=='scene.render@1':ffmpeg._range(params['range'],scene['duration_frames'])
        elif not 0<=params['frame']<scene['duration_frames']:raise ValueError('Frame outside scene')
        manifest=Path(resolve_artifact(scene['authored_source']))
        entry=source_entry(manifest)
        if binding:=scene.get('storyboard_binding'):
            actual = _source_panel(manifest)
            if (not isinstance(panel, dict) or not isinstance(actual, dict) or
                    not isinstance(actual.get('panel'), dict)):
                raise ValueError('Editable source panel must be a storyboard panel record')
            # Review-only notes are deliberately absent from panel_projection;
            # keep every pin and production field exact in the source manifest.
            expected_panel = copy.deepcopy(panel)
            expected_panel.pop('notes', None)
            expected = dict(schema='motion/v1/storyboard-panel', panel=expected_panel,
                storyboard=binding['storyboard'], asset_library=binding['asset_library'])
            actual = copy.deepcopy(actual)
            actual['panel'].pop('notes', None)
            if actual != expected:
                raise ValueError('Editable source panel differs from frozen storyboard')
        if entry.suffix!='.html' or json.loads(manifest.read_text())['entry_member']!=scene['source_runtime']['entry_member']:
            raise ValueError('Authored HTML entry differs')
    except (ValueError,KeyError,OSError) as e:
        raise ContractError('TIMING_INVALID',str(e)) from e
    return ['Trusted authored JavaScript executes in Chromium; not an OS sandbox.']


def _gpu_config(context, versions):
    if versions['chrome'] != 'Google Chrome ' + gpu_route.CHROME_VERSION:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Native NVIDIA route requires exactly Google Chrome ' + gpu_route.CHROME_VERSION)
    if not gpu_route.is_supported(getattr(context, 'gpu_route', None)):
        raise ContractError('PERMISSION_DENIED', 'Owned native GPU admission required.')
    # run() cleans up each serial child before returning. Consume the
    # last version-probe child's retained locked admission metadata.
    resources = getattr(context, 'resource_snapshot', None) or {}
    native = resources.get('native_gpu_admission') or {}
    if native.get('available') is not True or not isinstance(native.get('device'), dict):
        raise ContractError('RESOURCE_BUSY', 'Native NVIDIA hardware admission evidence missing.')
    return dict(gpu_route=gpu_route.FILMMAKING_ROUTE.name,
                gpu_device=native['device'], chrome_version=versions['chrome'])


def validate_gpu_qualification(captured, device):
    """Validate actual before/after evidence; JS performs live /proc/BPF checks.

    This is a defense against missing, truncated or inconsistent worker reports,
    not a claim that authored same-UID code is a hostile security boundary.
    """
    try:
        q = captured['gpu_qualification']
        if q['route'] != gpu_route.FILMMAKING_ROUTE.name or q['status'] != 'passed':
            raise ValueError('Native GPU qualification absent.')
        identities = []
        for name in ('before', 'after'):
            snapshot = q[name]
            gpu = snapshot['systemInfo']['gpu']
            aux = gpu['auxAttributes']
            renderer = aux['glRenderer']
            if (not isinstance(renderer, str) or 'NVIDIA' not in renderer or
                    any(v in renderer.lower() for v in ('swiftshader', 'llvmpipe', 'software')) or
                    aux['glImplementationParts'] != '(gl=egl-angle,angle=opengl)' or
                    aux['sandboxed'] is not True or type(aux['processCrashCount']) is not int or
                    aux['processCrashCount'] != 0):
                raise ValueError('GPU is not sandboxed native NVIDIA.')
            devices = gpu['devices']
            if len(devices) != 1:
                raise ValueError('Ambiguous GPU identity.')
            actual = devices[0]
            for observed, expected in [('vendorId', 'vendor_id'), ('deviceId', 'device_id'),
                                       ('driverVersion', 'driver_version')]:
                if actual[observed] != device[expected]:
                    raise ValueError('GPU hardware differs from admission.')
            processes = snapshot['processes']['processInfo']
            gpu_processes = [p for p in processes if p['type'] == 'GPU']
            records = [r for r in snapshot['records'] if r['processInfo']['type'] == 'GPU']
            if len(gpu_processes) != 1 or len(records) != 1:
                raise ValueError('Exactly one GPU process attestation required.')
            record = records[0]
            pid = record['processInfo']['id']
            if type(pid) is not int or pid <= 0 or gpu_processes[0]['id'] != pid:
                raise ValueError('GPU PID differs from observed process.')
            stat_text = record['stat']
            stat_pid = int(stat_text.split(' ', 1)[0])
            fields = stat_text.rsplit(')', 1)[1].split()
            start = int(fields[19])  # proc(5) field 22, after pid/comm.
            if stat_pid != pid or start <= 0:
                raise ValueError('GPU start identity absent.')
            def sandboxed(status):
                fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
                return (fields['Seccomp'].strip() == '2' and fields['NoNewPrivs'].strip() == '1'
                        and int(fields['Seccomp_filters'].strip()) > 0)
            if not sandboxed(record['status']) or not record['threads']:
                raise ValueError('GPU kernel sandbox evidence absent.')
            tids = []
            for thread in record['threads']:
                tid = int(thread['tid'])
                if tid <= 0 or not sandboxed(thread['status']):
                    raise ValueError('GPU thread lacks kernel BPF sandbox.')
                tids.append(tid)
            if pid not in tids or len(set(tids)) != len(tids):
                raise ValueError('GPU thread identity incomplete.')
            identities.append((pid, start, actual['deviceId'], actual['driverVersion'], renderer))
        if identities[0] != identities[1]:
            raise ValueError('GPU process or native backend changed during capture.')
        if 'graphics_probe' in q:
            probe = q['graphics_probe']
            if (type(probe['error']) is not int or probe['error'] != 0 or
                    probe['pixel'] != [0, 255, 0, 255] or
                    not probe['version'].startswith('WebGL 2.0')):
                raise ValueError('WebGL2 readback evidence invalid.')
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ValueError('Missing or malformed GPU qualification evidence.') from exc


def _cleanup_attempt(out, *, succeeded):
    """Retain at most three 2 MiB frame files on failure, never browser state.

    Diagnostics live with the owned attempt until its project is removed; they
    are not collected artifacts or evidence of a complete render.
    """
    import os
    import stat
    try:
        if not succeeded:
            frames = sorted((out / 'frames').glob('*.png'))
            retained = []
            if frames:
                dest = out / 'failure-diagnostics'
                dest.mkdir(exist_ok=True)
                for index in sorted({0, len(frames) // 2, len(frames) - 1}):
                    path = frames[index]
                    try:
                        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    except OSError:
                        continue
                    with os.fdopen(fd, 'rb') as stream:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode) or before.st_size > 2 * 1024 * 1024:
                            continue
                        data = stream.read(2 * 1024 * 1024 + 1)
                        after = os.fstat(stream.fileno())
                    if (len(data) != before.st_size or
                            (before.st_ino, before.st_size, before.st_mtime_ns) !=
                            (after.st_ino, after.st_size, after.st_mtime_ns)):
                        continue
                    (dest / path.name).write_bytes(data)
                    retained.append(path.name)
                (dest / 'index.json').write_bytes(canonical(dict(
                    complete_render=False, observed_frame_files=len(frames), retained=retained,
                    retention='Owned attempt lifetime; at most 3 files of 2 MiB each.')))
    finally:
        for name in ('chrome-profile', 'samples', 'frames'):
            shutil.rmtree(out / name, ignore_errors=True)


class FilmmakingAdapter:
    owned_local=True
    def __init__(self,runtime,binding):
        self.runtime,self.binding=runtime,copy.deepcopy(binding)

    def validate_request(self,request):
        expected=self.runtime.registry.binding(ADAPTER_ID,request['operation'],request['parameters'],request.get('binding_parameters'))
        if self.binding!=expected or request['binding']!=expected:
            raise ContractError('ADAPTER_INCOMPATIBLE','Frozen filmmaking implementation differs.')
        if set(request['inputs'])!={'source','assets'}:
            raise ContractError('INVALID_ARGUMENT','Explicit source and assets required.')
        return dict(valid=True,effects=EFFECTS)

    def execute(self,request,attempt,context=None):
        self.validate_request(request)
        if not callable(getattr(context,'run',None)):
            raise ContractError('PERMISSION_DENIED','Owned WorkerContext.run required.')
        runner = getattr(context, 'run')
        owner = getattr(runner, '__self__', None)
        observed_process = hasattr(owner, 'process')
        started = False
        def owned_run(argv, **kwargs):
            nonlocal started
            # A refused first spawn is not a submitted child. Retained Popen
            # evidence remains authoritative after capture/cleanup failures.
            if not observed_process:
                started = True
            try:
                return runner(argv, **kwargs)
            finally:
                if observed_process:
                    started = started or getattr(owner, 'process', None) is not None
        def failure(exc):
            result = ffmpeg._result('failed', [], error=exc, started=started)
            result['error']['message'] = sanitize(result['error']['message'])
            result['error']['details'] = sanitize(result['error']['details'])
            return result
        out=None
        succeeded=False
        try:
            found=discover()
            if not found['available']:raise ContractError('DEPENDENCY_UNAVAILABLE','Missing local dependencies: '+', '.join(found['missing']))
            if attempt['node_id']!=request['node_id'] or not attempt['authority_evidence_ref']:
                raise ContractError('PERMISSION_DENIED','Owned attempt authority required.')
            params=request['parameters']; pid=request['project_id']
            scene=self.runtime.document(pid,params['scene'])['document']['value']
            if request['inputs']['source']!=scene['authored_source'] or request['inputs']['assets']!=scene['assets']:
                raise ValueError('Frozen source/asset closure differs')
            manifest=Path(self.runtime.artifact_path(pid,scene['authored_source']))
            if ffmpeg.digest(manifest)!=scene['authored_source']['sha256']:raise ValueError('Source hash differs')
            entry=source_entry(manifest); bundle=json.loads(manifest.read_text())
            out=ffmpeg._output_dir(self.runtime.projects._filesystem().root,attempt['output_dir'])
            stage=out/'source';stage.mkdir()
            source_root=entry
            for _ in Path(bundle['entry_member']).parts:source_root=source_root.parent
            for member in bundle['members']:
                target=stage/member['relative_path'];target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source_root/member['relative_path'],target)
                if ffmpeg.digest(target)!=member['sha256']:
                    raise ValueError('Staged source member identity differs')
            a,b=(ffmpeg._range(params['range'],scene['duration_frames']) if request['operation']=='scene.render@1'
                 else (params['frame'],params['frame']+1))
            w,h=scene['canvas']['width_px'],scene['canvas']['height_px']
            sample_cap=4 if params.get('quality')=='final' else 1
            from . import rates
            cadence = params.get('rate', {'num':30,'den':1})
            cfg=dict(root=str(stage),members=[m['relative_path'] for m in bundle['members']],entry=bundle['entry_member'],
                chrome=found['chrome'],profile=str(out/'chrome-profile'),frames=str(out/'samples'),
                report=str(out/'capture.json'),width=w,height=h,rate=cadence,duration_frames=scene['duration_frames'],
                start=a,end=b,samples=sample_cap)
            config=out/'capture-config.json'
            deadline=datetime.fromisoformat(attempt['deadline_at'].replace('Z','+00:00'))
            def run(argv):
                seconds=(deadline-datetime.now(timezone.utc)).total_seconds()
                if seconds<=0:raise TimeoutError('Filmmaking deadline elapsed')
                return owned_run(argv,timeout=seconds,check=True)
            versions=runtime_versions(found,run)
            cfg.update(_gpu_config(context, versions))
            config.write_bytes(canonical(cfg))
            run([found['node'],str(RESOURCES/'capture.mjs'),str(config)])
            from PIL import Image
            captured=json.loads((out/'capture.json').read_text())
            validate_gpu_qualification(captured, cfg['gpu_device'])
            if (captured.get('frames')!=b-a or captured.get('sample_cap')!=cfg['samples']
                    or captured.get('errors')!=[] or len(captured.get('exposures',[]))!=b-a):
                raise ValueError('Malformed capture report or incomplete frame coverage')
            frames=out/'frames';frames.mkdir()
            for k in range(b-a):
                exposure=json.loads((out/'samples'/f'{k}.json').read_text())
                n=exposure.get('samples')
                if (type(n) is not int or not 1<=n<=sample_cap
                        or exposure.get('frame')!=a+k or len(exposure.get('times',[]))!=n
                        or exposure!=captured['exposures'][k]):
                    raise ValueError('Malformed sample manifest or report mismatch')
                image=None
                for j in range(n):
                    sample_path=out/'samples'/f'{k}-{j}.png'
                    if sample_path.is_symlink() or not sample_path.is_file():
                        raise ValueError('Missing or unsafe captured sample')
                    with Image.open(sample_path) as im:
                        if im.size!=(w,h) or im.format!='PNG':
                            raise ValueError('Captured sample canvas or format differs')
                        sample=im.convert('RGB')
                    image=sample if image is None else Image.blend(image,sample,1/(j+1))
                if image is None: raise ValueError('No captured samples')
                image.save(frames/f'{k:06}.png')
            target=out/'scene.mkv' if request['operation']=='scene.render@1' else out/'frame.png'
            if request['operation']=='scene.render@1':
                run([found['ffmpeg'],'-nostdin','-v','error','-n','-framerate',rates.text(cadence),'-i',str(frames/'%06d.png'),
                     '-an','-c:v','ffv1','-pix_fmt','bgr0','-threads','1',*rates.stamp(cadence),str(target)])
            else:shutil.copyfile(frames/'000000.png',target)
            report=out/'render-report.json'
            report.write_bytes(canonical(dict(schema='motion/v1/filmmaking-render',scene=params['scene'],
                source=scene['authored_source'],assets=scene['assets'],canvas=scene['canvas'],range=dict(start_frame=a,end_frame=b),
                implementation=request['binding']['implementation_sha256'],host=found,
                runtime_versions=versions,
                capture=json.loads((out/'capture.json').read_text(),parse_float=str))))
            outputs=[]
            for port,p,mime in [('media' if request['operation']=='scene.render@1' else 'frame',target,
                                'video/x-matroska' if request['operation']=='scene.render@1' else 'image/png'),
                               ('report',report,'application/json')]:
                spec=next(v for v in registration()['outputs'][request['operation']] if v['port']==port)
                if port!='report':self.runtime.output_probe.validate_file(p,spec,run_process=owned_run)
                outputs.append(dict(port=port,relative_path=p.name,media_type=mime,claimed_sha256=ffmpeg.digest(p)))
            shutil.rmtree(out/'chrome-profile',ignore_errors=True)
            shutil.rmtree(out/'samples');shutil.rmtree(frames)
            succeeded=True
            return ffmpeg._result('succeeded',outputs)
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors='replace') if isinstance(exc.stderr,bytes) else exc.stderr
            return failure(ContractError('OUTPUT_INVALID', (detail or str(exc))[-1800:]))
        except Exception as exc:
            return failure(exc if isinstance(exc, ContractError) else ContractError('OUTPUT_INVALID', str(exc)))
        finally:
            if out is not None:
                _cleanup_attempt(out, succeeded=succeeded)
