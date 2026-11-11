"""Finite layout-1 correction precondition; read metadata only inside pinned allocation."""
import os
import stat
from ..assets.producer_files import allocation
from ..domain import Fault


def shared_runtime_cache(store, row):
    if row['plan'].get('adapter', 'stable-audio-local') != 'stable-audio-local':
        return False  # Music has no generation correction recipe.
    process = row['process'] or {}
    if process.get('layout',1) != 1 or not process.get('allocation'):
        return False
    root_fd = cache_fd = None
    try:
        _, root_fd, _ = allocation(store,row)
        cache_fd = os.open('.nv',os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,dir_fd=root_fd)
        outer = os.fstat(cache_fd)
        inner = os.stat('ComputeCache',dir_fd=cache_fd,follow_symlinks=False)
        return all(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077
                   for info in (outer,inner))
    except (Fault,OSError):
        return False
    finally:
        for descriptor in (cache_fd,root_fd):
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: pass  # Secondary close uncertain; never blindly retry.
