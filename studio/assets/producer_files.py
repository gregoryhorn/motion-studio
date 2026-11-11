"""Symlink-safe, allocation-bound producer files. No caller paths or folder discovery."""
import os
import stat
from ..domain import Fault


def allocation(store, row):
    directory = store.home / 'staging' / ('sfx-' + row['id'])
    if (row['process'] or {}).get('layout') == 2:
        from ..assets.runtime_workspace import validate
        validate(store, row)
        directory = directory / 'outputs'
    known = (row['process'] or {}).get('allocation')
    if known is None:
        directory.mkdir(mode=0o700)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    info = os.fstat(descriptor)
    pin = {'dev': info.st_dev, 'ino': info.st_ino}
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or (known is not None and known != pin):
        os.close(descriptor)
        raise Fault('ALLOCATION_UNSAFE')
    return directory, descriptor, pin


def read_leaf(descriptor, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                before.st_uid != os.getuid() or before.st_size > limit):
            raise Fault('OUTPUT_UNSAFE')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        if len(data) > limit or (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino):
            raise Fault('OUTPUT_CHANGED')
        return data
    finally:
        os.close(fd)


def staging_size(descriptor):
    total = 0
    for name in os.listdir(descriptor):
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Fault('OUTPUT_UNSAFE')
        total += info.st_size
    return total
