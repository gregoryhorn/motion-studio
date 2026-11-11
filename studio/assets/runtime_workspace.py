"""Version-2 server-owned outputs/runtime siblings; monitored, not sandboxed/quota."""
import os
import stat
from ..domain import Fault

MAX_DEPTH = 8
MAX_ENTRIES = 4096


def pin(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Fault('ALLOCATION_UNSAFE', 409)
        return dict(dev=info.st_dev, ino=info.st_ino)
    finally:
        os.close(fd)


def create(store, row):
    root = store.home / 'staging' / ('sfx-' + row['id'])
    root.mkdir(mode=0o700)
    for leaf in ('outputs', 'runtime'):
        (root / leaf).mkdir(mode=0o700)
    runtime = root / 'runtime'
    for leaf in ('home', 'tmp', 'cache'):
        (runtime / leaf).mkdir(mode=0o700)
    return dict(layout=2, root=pin(root), allocation=pin(root / 'outputs'), runtime=pin(runtime))


def paths(store, row):
    root = store.home / 'staging' / ('sfx-' + row['id'])
    return root, root / 'outputs', root / 'runtime'


def validate(store, row):
    root, outputs, runtime = paths(store, row)
    for path, key in ((root, 'root'), (outputs, 'allocation'), (runtime, 'runtime')):
        if pin(path) != row['process'][key]:
            raise Fault('ALLOCATION_UNSAFE', 409)
    for leaf in ('home', 'tmp', 'cache'):
        pin(runtime / leaf)
    return runtime


def environment(adapter, original, runtime):
    value = dict(original, HOME=str(runtime / 'home'), TMPDIR=str(runtime / 'tmp'),
                 XDG_CACHE_HOME=str(runtime / 'cache'))
    hook = getattr(adapter, 'runtime_environment', None)
    return hook(value, runtime) if hook else value


def tree_snapshot(path):
    """Bounded no-follow metadata traversal; no content reads or directory discovery."""
    entries, size = [], 0
    root_dev = pin(path)['dev']
    def visit(fd, prefix, depth):
        nonlocal size
        if depth > MAX_DEPTH:
            raise Fault('RUNTIME_LIMIT', 409)
        with os.scandir(fd) as scan:
            for entry in scan:
                if len(entries) >= MAX_ENTRIES:
                    raise Fault('RUNTIME_LIMIT', 409)
                info = entry.stat(follow_symlinks=False)
                name = prefix + entry.name
                if (info.st_uid != os.getuid() or info.st_dev != root_dev or info.st_mode & 0o077
                        or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))):
                    raise Fault('OUTPUT_UNSAFE', 409)
                entries.append((name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        current = os.fstat(child)
                        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                            raise Fault('OUTPUT_CHANGED', 409)
                        visit(child, name + '/', depth + 1)
                    finally:
                        os.close(child)
                else:
                    if info.st_nlink != 1:
                        raise Fault('OUTPUT_UNSAFE', 409)
                    size += info.st_size
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(fd, '', 0)
    finally:
        os.close(fd)
    return sorted(entries), size
