"""Passive, byte-based identities at compile/admission/execution boundaries.

Nothing is resolved at import/registration. No version command, engine import,
model initialization or subprocess is used here.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import stat
import sys
import threading

from .contracts import ContractError, digest

_HASHES = {}
_HASH_LOCK = threading.Lock()
_ROOT = Path(__file__).resolve().parent


def file_identity(path):
    """Hash bytes, caching only while device/inode/size/mtime/ctime agree.

    Read through one descriptor and reject concurrent replacement/mutation. A
    symlink target change also changes the resolved path/key on the next check.
    """
    try:
        path = Path(path).resolve(strict=True)
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise OSError('Dependency is not a regular file')
            def key(value):
                return (str(path), value.st_dev, value.st_ino, value.st_size,
                        value.st_mtime_ns, value.st_ctime_ns)
            identity = key(before)
            with _HASH_LOCK:
                sha = _HASHES.get(identity)
            if sha is None:
                h = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
                sha = 'sha256:' + h.hexdigest()
            if key(os.fstat(stream.fileno())) != identity or key(path.stat()) != identity:
                raise OSError('Dependency changed while hashing')
            with _HASH_LOCK:
                # Bound old stat generations rather than accumulating every edit.
                for old in list(_HASHES):
                    if old[0] == str(path) and old != identity:
                        del _HASHES[old]
                _HASHES[identity] = sha
            return {'path': str(path), 'sha256': sha}
    except (OSError, ValueError, TypeError) as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Cannot establish dependency byte identity: ' + str(path)) from exc


def executable_identity(name):
    path = shutil.which(name)
    if path is None:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Required engine executable is missing: ' + name)
    return file_identity(path)


def library_identity(name):
    """Installed distribution bytes, including extension/shared-library files.

    Distribution metadata is read without importing the package. RECORD hashes
    alone are not evidence: every installed listed file is stat/hash checked.
    """
    try:
        distribution = importlib.metadata.distribution(name)
        files = distribution.files
        if not files:
            raise ValueError('Distribution has no verifiable file manifest')
        identities = {}
        for member in files:
            # Interpreter-generated caches do not determine implementation.
            if str(member).endswith(('.pyc', '.pyo')):
                continue
            identities[str(member)] = file_identity(distribution.locate_file(member))
        if not identities:
            raise ValueError('Empty distribution')
        return {'version': distribution.version, 'files': identities}
    except (importlib.metadata.PackageNotFoundError, ValueError) as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Required library identity is unavailable: ' + name) from exc


def local_engine_identity(task, binding):
    """Resolve only the engines/helpers used by the selected native route."""
    aid, operation = binding['adapter_id'], task['operation']
    if aid == 'local.ui-compositor':
        # Re-read exact renderer/dependency bytes for frozen-plan admission;
        # the registered identity is not evidence of the currently loaded code.
        from .adapters.ui_compositor import engine_identity
        return engine_identity()
    executables, libraries, sources = [], [], []
    if aid == 'local.filmmaking':
        executables = ['node', 'ffmpeg', 'ffprobe']
        chrome = os.environ.get('MOTION_CHROME') or next((name for name in
            ('google-chrome', 'chromium', 'chromium-browser', 'chrome') if shutil.which(name)), 'chromium')
        executables.append(chrome)
        sources = ['adapters/filmmaking.py', 'filmmaking/capture.mjs', 'filmmaking/timing.mjs']
    elif aid == 'local.blender':
        executables = ['blender', 'ffmpeg', 'ffprobe']
        sources = ['adapters/blender.py', 'filmmaking/blender_render.py']
    elif aid == 'local.media-finishing':
        executables = ['ffmpeg', 'ffprobe']
        sources = ['adapters/finishing.py', 'adapters/mastering.py', 'adapters/color_pipeline.py']
        if operation in ('audio.cleanup@1', 'audio.duck@1'):
            sources.append('adapters/dialogue.py')
    elif aid == 'local.portrait-reframe':
        executables = ['ffmpeg', 'ffprobe']
        libraries = ['Pillow', 'av']
        sources = ['adapters/reframe.py']
    elif aid in ('local.ffmpeg-post', 'ffmpeg.probe', 'ffmpeg.conform'):
        executables = ['ffprobe'] if aid == 'ffmpeg.probe' and not task['parameters'].get('full_decode') else ['ffmpeg', 'ffprobe']
        sources = ['adapters/ffmpeg.py', 'adapters/rates.py', 'adapters/probe.py', 'adapters/limits.py']
        if aid == 'ffmpeg.conform':
            sources.append('adapters/conform.py')
        if aid == 'ffmpeg.probe':
            sources.append('adapters/media_probe.py')
        if operation in ('edit.assemble@1', 'audio.mix@1', 'caption.render@1'):
            libraries.append('av')
            sources += ['adapters/streaming.py', 'adapters/stream_evidence.py']
        if operation == 'delivery.encode@1':
            sources.append('adapters/color_pipeline.py')
        if operation == 'caption.render@1':
            libraries.append('Pillow')
            sources += ['captions.py', 'adapters/caption_render.py', 'adapters/caption_shaping.py',
                        'adapters/caption_animation.py']
    else:
        # External/custom adapters retain their registered immutable identity.
        return {'registered_implementation': binding['implementation_sha256']}
    if aid in ('local.filmmaking', 'local.blender', 'local.media-finishing', 'local.portrait-reframe'):
        # These adapters call shared FFmpeg/clock/bounds helpers too. A registry
        # snapshot is not a refreshed identity after an in-process source edit.
        sources += ['adapters/ffmpeg.py', 'adapters/rates.py', 'adapters/limits.py', 'adapters/probe.py']
    return {'format': 'motion/engine-bytes-v1',
            'python': file_identity(sys.executable),
            'executables': {name: executable_identity(name) for name in executables},
            'libraries': {name: library_identity(name) for name in libraries},
            'helpers': {name: file_identity(_ROOT / name) for name in sources}}


def semantic_closure(task, documents, *, artifact_resolver, project_id):
    """Follow consumed document values, scene subjects and artifact pins only.

    Document envelope revisions are deliberately absent for indirect scene refs:
    updating another scene/project stage cannot poison this node's closure.
    Explicit pins remain exact and must belong to the frozen snapshot.
    """
    document_values, artifacts, visiting = {}, {}, set()

    def document(kind, identifier, pin=None):
        key = (kind, identifier)
        doc = documents.get(key)
        if doc is None:
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Relevant document dependency is missing: ' + repr(key))
        if pin is not None and (doc.get('revision') != pin['revision'] or digest(doc) != pin['sha256']):
            raise ContractError('HASH_MISMATCH', 'Relevant document dependency does not match its frozen pin.')
        if key in visiting:
            return
        visiting.add(key)
        document_values[kind + ':' + identifier] = doc['value']
        walk(doc['value'])

    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if set(value) == {'artifact_id', 'sha256'}:
                if artifact_resolver is None:
                    raise ContractError('DEPENDENCY_UNAVAILABLE', 'Relevant asset verification is unavailable.')
                record = artifact_resolver(project_id, value)
                if any(record.get(k) != v for k, v in value.items()) or record.get('project_id') != project_id:
                    raise ContractError('HASH_MISMATCH', 'Relevant asset bytes/ownership differ from the pin.')
                artifacts[value['artifact_id']] = value
            elif set(value) == {'kind', 'id', 'revision', 'sha256'}:
                document(value['kind'], value['id'], value)
            elif value.get('kind') == 'scene' and 'scene_id' in value:
                document('scene', value['scene_id'])
            else:
                for item in value.values():
                    walk(item)

    walk(task['inputs'])
    walk(task['parameters'])
    walk(task.get('binding_parameters'))
    settings = documents.get(('settings', 'project'))
    if settings is None:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Relevant render settings are missing.')
    # Stage/gate-review edits are not rendering inputs; policy is already hashed
    # by the compiler. Probe/search/staging do not consume project clocks.
    operation = task['operation']
    if operation in ('edit.assemble@1', 'audio.mix@1', 'delivery.encode@1'):
        clock_keys = ('rate', 'sample_rate', 'audio_mode')
    elif operation in ('scene.render@1', 'scene.frame@1', 'caption.layout@1',
                       'caption.render@1', 'caption.export@1', 'speech.align@1',
                       'speech.transcribe@1'):
        clock_keys = ('rate',)
    else:
        # Native finishing/reframe derive their clocks from source streams and
        # explicit parameters; probe/search/authoring consume no project clock.
        clock_keys = ()
    try:
        clocks = {key: settings['value'][key] for key in clock_keys}
    except KeyError as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Relevant render clock setting is missing.') from exc
    return {'documents': document_values, 'assets': artifacts, 'settings': clocks}
