"""Read-only checkout or qualified API-source admission; see docs/host-compatibility.md."""
from __future__ import annotations

import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import sys
from typing import NoReturn

from .contracts import ContractError


_HEX = re.compile(r'[0-9a-f]{40}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_PYTHON_FILES = frozenset({
    'hermes_cli/projects_db.py', 'hermes_cli/plugin_host_http_auth.py',
    'hermes_cli/plugin_session.py', 'gateway/owner_identity.py',
    'gateway/session_context.py', 'hermes_constants.py',
    'hermes_cli/web_server_plugin_profiles.py', 'hermes_cli/web_server_dashboard.py',
})
_SDK_FILES = frozenset({'apps/desktop/src/sdk/index.ts', 'apps/desktop/src/sdk/composer.ts'})


def _unsupported() -> NoReturn:
    raise ContractError('HOST_VERSION_UNSUPPORTED',
                        'Hermes differs from this plugin\'s locked host version; explicit compatibility review is required.')


def _source_spec(name, search_path=None):
    """Ask import finders, not import_module/find_spec (which execute parents)."""
    for finder in sys.meta_path:
        spec = finder.find_spec(name, search_path, None)
        if spec is not None:
            if (spec.name != name or not isinstance(spec.loader, importlib.machinery.SourceFileLoader)
                    or not isinstance(spec.origin, str)
                    or spec.loader.name != name or spec.loader.path != spec.origin):
                _unsupported()
            return spec
    _unsupported()


def _plain_path(path):
    path = Path(path).absolute()
    resolved = path.resolve(strict=True)
    # Reject aliases as well as escapes, so source identity is unambiguous.
    if path != resolved:
        _unsupported()
    return resolved


def _check_loaded(name, spec, package_paths):
    if name not in sys.modules:
        return
    module = sys.modules[name]
    loaded = getattr(module, '__spec__', None)
    if (loaded is None or loaded.name != name or loaded.origin != spec.origin
            or not isinstance(loaded.loader, importlib.machinery.SourceFileLoader)
            or loaded.loader.name != name or loaded.loader.path != spec.origin
            or getattr(module, '__file__', None) != spec.origin
            or getattr(module, '__loader__', None) is not loaded.loader):
        _unsupported()
    if package_paths is not None:
        if (list(getattr(module, '__path__', [])) != package_paths
                or list(loaded.submodule_search_locations or []) != package_paths):
            _unsupported()


def host_root():
    spec = _source_spec('hermes_cli')
    return _plain_path(spec.origin).parent.parent


def _origins(root):
    """Validate both future import resolution and already-loaded module origins."""
    packages = {}
    observed = {}
    for name in ('hermes_cli', 'gateway'):
        spec = _source_spec(name)
        expected = root / name / '__init__.py'
        if _plain_path(spec.origin) != expected:
            _unsupported()
        paths = list(spec.submodule_search_locations or [])
        if paths != [str(expected.parent)]:
            _unsupported()
        _check_loaded(name, spec, paths)
        packages[name] = paths
        observed[name] = spec.origin
    for relative in sorted(_PYTHON_FILES):
        name = relative[:-3].replace('/', '.')
        parent = name.rpartition('.')[0]
        spec = _source_spec(name, packages.get(parent))
        if _plain_path(spec.origin) != root / relative or spec.submodule_search_locations is not None:
            _unsupported()
        _check_loaded(name, spec, None)
        observed[name] = spec.origin
    return observed


def _revision(root):
    git = root / '.git'
    if git.is_symlink() or not git.is_dir():
        _unsupported()
    head = (git / 'HEAD').read_text(encoding='ascii').strip()
    if _HEX.fullmatch(head):
        return head
    if not head.startswith('ref: '):
        _unsupported()
    ref = head[len('ref: '):]
    parts = Path(ref).parts
    if (not ref.startswith('refs/') or any(part in ('.', '..') for part in parts) or
            re.fullmatch(r'refs/[A-Za-z0-9._/-]+', ref) is None):
        _unsupported()
    loose = git / ref
    if loose.is_file():
        if not loose.resolve(strict=True).is_relative_to(git.resolve(strict=True)):
            _unsupported()
        revision = loose.read_text(encoding='ascii').strip()
        if not _HEX.fullmatch(revision):
            _unsupported()
        return revision
    packed = git / 'packed-refs'
    if packed.is_file() and not packed.is_symlink():
        for line in packed.read_text(encoding='ascii').splitlines():
            if not line or line.startswith(('#', '^')):
                continue
            fields = line.split(' ')
            if len(fields) == 2 and fields[1] == ref and _HEX.fullmatch(fields[0]):
                return fields[0]
    _unsupported()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate host-lock key')
        result[key] = value
    return result


def _load_lock():
    return json.loads(Path(__file__).with_name('host-lock.json').read_text(encoding='utf-8'),
                      object_pairs_hook=_unique_object)


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        _unsupported()


def _files(files, names=None):
    if not isinstance(files, dict) or not files or (names is not None and set(files) != names):
        _unsupported()
    for name, digest in files.items():
        if not isinstance(name, str) or not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            _unsupported()
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or path.as_posix() != name or name in ('', '.'):
            _unsupported()


def _validate_lock(lock):
    if not isinstance(lock, dict):
        _unsupported()
    schema = lock.get('schema')
    if schema == 'motion/hermes-host-lock/v1':
        _keys(lock, {'schema', 'revision', 'version_label', 'files'})
        revision = lock['revision']
        _files(lock['files'])
    elif schema == 'motion/hermes-host-lock/v2':
        _keys(lock, {'schema', 'reference_revision', 'version_label', 'checkout', 'managed_runtime', 'desktop_sdk'})
        revision = lock['reference_revision']
        _keys(lock['checkout'], {'files'})
        _keys(lock['managed_runtime'], {'admission', 'files'})
        _keys(lock['desktop_sdk'], {'status', 'files'})
        if (lock['managed_runtime']['admission'] != 'qualified-api-source-bytes'
                or lock['desktop_sdk']['status'] != 'unverified-client'):
            _unsupported()
        _files(lock['managed_runtime']['files'], _PYTHON_FILES)
        _files(lock['desktop_sdk']['files'], _SDK_FILES)
        _files(lock['checkout']['files'], _PYTHON_FILES | _SDK_FILES)
        if lock['checkout']['files'] != {**lock['managed_runtime']['files'], **lock['desktop_sdk']['files']}:
            _unsupported()
    else:
        _unsupported()
    if (not isinstance(revision, str) or not _HEX.fullmatch(revision)
            or not isinstance(lock['version_label'], str) or not lock['version_label'].strip()):
        _unsupported()


def _identity(item):
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def _hash_files(root, files):
    snapshots = {}
    for name, expected in files.items():
        path = _plain_path(root / name)
        if not path.is_relative_to(root) or not path.is_file():
            _unsupported()
        with path.open('rb') as stream:
            before = os.fstat(stream.fileno())
            checksum = hashlib.sha256()
            for block in iter(lambda: stream.read(65536), b''):
                checksum.update(block)
            after = os.fstat(stream.fileno())
        if _identity(before) != _identity(after) or checksum.hexdigest() != expected:
            _unsupported()
        snapshots[path] = _identity(after)
    return snapshots


def _stable(snapshots):
    for path, identity in snapshots.items():
        if _plain_path(path) != path or _identity(path.stat()) != identity:
            _unsupported()


def assert_supported_host(root=None):
    """Admit exact checkouts or qualified managed-runtime API source bytes.

    Explicit roots validate files only (installer/test use). Default HTTP use
    also validates import specs and loaded origins without executing host code.
    No stamp, environment claim, or version-info fallback establishes identity.
    """
    try:
        lock = _load_lock()
        _validate_lock(lock)
        default = root is None
        root = host_root() if default else Path(root).resolve(strict=True)
        v1 = lock['schema'] == 'motion/hermes-host-lock/v1'
        checkout = v1 or (root / '.git').exists() or (root / '.git').is_symlink()
        revision = lock['revision'] if v1 else lock['reference_revision']
        origins = _origins(root) if default and not v1 else None
        if checkout and _revision(root) != revision:
            _unsupported()
        files = lock['files'] if v1 else lock['checkout' if checkout else 'managed_runtime']['files']
        snapshots = _hash_files(root, files)
        if origins is not None and _origins(root) != origins:
            _unsupported()
        if checkout and _revision(root) != revision:
            _unsupported()
        if not checkout and ((root / '.git').exists() or (root / '.git').is_symlink()):
            _unsupported()
        _stable(snapshots)
        if checkout:
            return {'revision': revision, 'version_label': lock['version_label']}
        return {'admission': 'qualified-api-source-bytes', 'reference_revision': revision,
                'version_label': lock['version_label'], 'desktop_sdk': 'unverified-client'}
    except ContractError:
        raise
    except (OSError, ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
        raise ContractError('HOST_VERSION_UNSUPPORTED',
                            'The locked Hermes host identity could not be established.') from exc
