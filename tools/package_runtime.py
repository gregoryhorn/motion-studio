#!/usr/bin/env python3
"""Build a runtime-only plugin archive without modifying source or profiles.

Tests and developer evidence remain in the repository, outside the installable
payload. This does not disable or bypass the host's installation scanner.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile

PAYLOAD = ('plugin.yaml', '__init__.py', 'studio', 'schemas', 'skills', 'desktop', 'dashboard', 'studio-manifest.json')


def read_member(path):
    """Read one regular member without following a replaced final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Non-regular runtime member: ' + str(path))
        data = stream.read()
        after = os.fstat(stream.fileno())
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size,
                value.st_mtime_ns, value.st_ctime_ns, value.st_mode)
    if identity(before) != identity(after) or len(data) != before.st_size:
        raise ValueError('Runtime member changed while reading: ' + str(path))
    return data, stat.S_IMODE(before.st_mode)


def package(root, output):
    root, output = Path(root).resolve(strict=True), Path(output).absolute()
    files = []
    for name in PAYLOAD:
        path = root / name
        if path.is_symlink():
            raise ValueError('Runtime symlink refused: ' + name)
        if not path.exists():
            raise ValueError('Missing runtime payload: ' + name)
        candidates = [path] if path.is_file() else sorted(path.rglob('*'))
        for item in candidates:
            relative = item.relative_to(root)
            if '__pycache__' in relative.parts or item.suffix == '.pyc':
                continue
            if item.is_symlink():
                raise ValueError('Runtime symlink refused: ' + str(relative))
            mode = item.stat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError('Non-regular runtime member: ' + str(relative))
            if item.resolve() == output:
                raise ValueError('Archive destination cannot be a payload member.')
            files.append((relative.as_posix(), item))
    # UI/backend source is part of the same immutable runtime payload. Refuse
    # a stale manifest before creating an archive, rather than ship new panes
    # alongside an old backend identity. This is packaging, not activation.
    manifest_bytes, manifest_mode = read_member(root / 'studio-manifest.json')
    manifest = json.loads(manifest_bytes)
    declared = manifest.get('payload')
    observed = []
    for name, path in sorted(files):
        if name == 'studio-manifest.json':
            continue
        data, mode = read_member(path)
        observed.append(dict(path=name, size=len(data),
                             sha256=hashlib.sha256(data).hexdigest(),
                             mode=mode))
    if declared != observed:
        raise ValueError('Runtime payload manifest is stale; refresh it from the complete source before packaging.')
    expected_files = {row['path']: row for row in observed}
    expected_files['studio-manifest.json'] = dict(size=len(manifest_bytes),
        sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        mode=manifest_mode)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents clobbering an unrelated deliverable.
    with output.open('xb') as target:
        try:
            with gzip.GzipFile(fileobj=target, mode='wb', filename='', mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|') as archive:
                    for name, path in sorted(files):
                        payload, mode = read_member(path)
                        record = tarfile.TarInfo('motion-studio/' + name)
                        expected = expected_files[name]
                        if (len(payload) != expected['size'] or
                                hashlib.sha256(payload).hexdigest() != expected['sha256'] or
                                mode != expected['mode']):
                            raise ValueError('Runtime source changed during packaging: ' + name)
                        record.mode = mode
                        record.mtime = record.uid = record.gid = 0
                        record.uname = record.gname = ''
                        record.size = len(payload)
                        archive.addfile(record, io.BytesIO(payload))
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    return dict(archive=str(output), payload_files=len(files), scanner_bypass=False)


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(Path(__file__).resolve().parents[1], args.output), sort_keys=True))


if __name__ == '__main__':
    main()
