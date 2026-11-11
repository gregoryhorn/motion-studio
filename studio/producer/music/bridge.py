"""App-owned format/receipt bridge. Never imports ACE/torch/soundfile.

The process runner is injected only by the deterministic test driver. Production
runtime admission remains closed until the separate live envelope is qualified.
"""
import json
import math
import os
import selectors
import subprocess
from pathlib import Path
from ...child_env import child_environment
from ...domain import Fault, MAX_BYTES
from ...assets.producer_files import read_leaf
from ...assets.retention import sync_directory
from ...persistence.primitives import canonical
from ...producer.local_sfx import unique_pairs
from ...producer.music.audio import pcm16
from ...producer.music.receipt import make

CAPTURE_LIMIT = 65536


def foreground(argv, environment, directory):
    """Synchronous bridge child stays in the caller's owned group. Bounded capture.

    The outer OwnedProcess owns deadline, TERM/KILL and group-retirement proof.
    No detached session, producer polling or retry is introduced here.
    """
    with subprocess.Popen(argv, env=child_environment('ace-step-local', environment), cwd=directory, shell=False, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True) as child:
        counts, output = {'stdout': 0, 'stderr': 0}, bytearray()
        with selectors.DefaultSelector() as selector:
            for stream, name in ((child.stdout, 'stdout'), (child.stderr, 'stderr')):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            try:
                while selector.get_map():
                    for key, _ in selector.select(0.02):
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            selector.unregister(key.fileobj); continue
                        counts[key.data] += len(chunk)
                        if counts[key.data] > CAPTURE_LIMIT: raise Fault('CAPTURE_LIMIT')
                        if key.data == 'stdout': output.extend(chunk)
                return child.wait(), bytes(output), counts['stderr']
            except BaseException:
                child.kill(); child.wait()
                raise


def upstream_json(stdout):
    if len(stdout) > CAPTURE_LIMIT: raise Fault('CAPTURE_LIMIT')
    # Exactly one standalone JSON object line, with arbitrary non-JSON log lines.
    # JSON-looking malformed lines/arrays and duplicate objects are ambiguity, not noise.
    objects = []
    try:
        for line in stdout.decode('utf-8', errors='strict').splitlines():
            stripped = line.strip()
            if not stripped.startswith(('{', '[')):
                if '{' in stripped or '[' in stripped: raise ValueError()
                continue
            objects.append(json.loads(stripped, object_pairs_hook=unique_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        if len(objects) != 1: raise ValueError()
        value = objects[0]
        if not isinstance(value, dict) or set(value) != {'success','audio_paths','elapsed_seconds','output_dir'}:
            raise ValueError()
        if value['success'] is not True or type(value['audio_paths']) is not list or len(value['audio_paths']) != 1:
            raise ValueError()
        elapsed = value['elapsed_seconds']
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0: raise ValueError()
        if not all(type(value[k]) is str for k in ('output_dir',)) or type(value['audio_paths'][0]) is not str:
            raise ValueError()
        return value
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise Fault('MUSIC_UPSTREAM_RECEIPT_INVALID') from None


def atomic(directory, name, data):
    part = directory / (name + '.part')
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    # No overwrite, even for a partial bridge invocation. Never regenerate to repair.
    os.link(part, directory / name, follow_symlinks=False)
    part.unlink()
    sync_directory(directory)


def normalize(plan, output, code, stdout, stderr_bytes=0):
    if code != 0: raise Fault('MUSIC_UPSTREAM_FAILED')
    if stderr_bytes > CAPTURE_LIMIT: raise Fault('CAPTURE_LIMIT')
    value = upstream_json(stdout)
    directory = output.parent
    if value['output_dir'] != str(directory): raise Fault('MUSIC_OUTPUT_ESCAPE')
    path = Path(value['audio_paths'][0])
    if (not path.is_absolute() or path.parent != directory or str(path) != value['audio_paths'][0]
            or path.name in ('candidate.wav','native.wav') or path.suffix.lower() != '.wav'):
        raise Fault('MUSIC_OUTPUT_ESCAPE')
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.listdir(fd) != [path.name]: raise Fault('MUSIC_OUTPUT_COUNT')
        native = read_leaf(fd, path.name, MAX_BYTES)
        derivative, facts = pcm16(native, plan['parameters']['seconds'] * 48000)
        if read_leaf(fd, path.name, MAX_BYTES) != native: raise Fault('OUTPUT_CHANGED')
        receipt = make(plan, output, native, derivative, facts)
        # Preserve the original bytes under the fixed evidence name, never replace it.
        os.rename(path.name, 'native.wav', src_dir_fd=fd, dst_dir_fd=fd)
        atomic(directory, 'candidate.wav', derivative)
        atomic(directory, 'candidate.wav.json', canonical(receipt).encode())
        return receipt
    finally:
        os.close(fd)
