"""Public import-time build fingerprints, not source-revision attestations.

Capturing once distinguishes an old loaded backend from newer files copied over
it. This cannot attest already executed monkeypatches or imported dependencies.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
import uuid


_IMPORT = re.compile(r'^import (.+) from [\'"][^\'"\r\n]+[\'"];[ \t]*$', re.MULTILINE)


def frontend_source_sha256(source):
    """Ignore only host-rewritten import specifiers, retaining import bindings."""
    source = source.replace('\r\n', '\n')
    normalized = _IMPORT.sub(lambda match: 'import ' + match[1] + ' from "<host-import>";', source)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def capture_identity(root):
    """Capture plain package sources; fail visibly rather than invent a build."""
    root = Path(root).resolve(strict=True)
    paths = sorted([root / '__init__.py', *root.joinpath('studio').rglob('*.py'),
                    *root.joinpath('dashboard').rglob('*.py')])
    backend = hashlib.sha256()
    for path in paths:
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Build source must be an ordinary in-package file')
        source = path.read_bytes()
        backend.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
        backend.update(hashlib.sha256(source).digest())
    return dict(schema='motion/runtime-identity/v1', observation='module_import_snapshot',
                instance_id=uuid.uuid4().hex,
                manifest_sha256=hashlib.sha256((root / 'studio-manifest.json').read_bytes()).hexdigest(),
                backend_source_sha256=backend.hexdigest(),
                frontend_source_sha256=frontend_source_sha256((root / 'desktop/plugin.js').read_text(encoding='utf-8')),
                frontend_hash_algorithm='motion/import-normalized-sha256/v1')


_LOADED = capture_identity(Path(__file__).resolve().parents[1])


def runtime_identity():
    return copy.deepcopy(_LOADED)
