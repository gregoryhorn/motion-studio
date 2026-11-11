"""Passive exact source verification; never imports/executes installed producer code."""
import hashlib
import os
from pathlib import Path
import stat
from ...domain import Fault
from ...producer.music.contract import SOURCE_PINS


def known_files():
    home = Path.home()
    return {str(home / '.local/bin/ace-step-music'): SOURCE_PINS['launcher'],
        str(home / 'tools/ace-step-ui/server/scripts/simple_generate.py'): SOURCE_PINS['generator'],
        str(home / 'tools/ACE-Step-1.5/acestep/inference.py'): SOURCE_PINS['inference']}


def verify(files):
    for name, expected in files.items():
        fd = None
        try:
            path = Path(name)
            # Reject symlinked components; do not normalize a changed source path.
            if not path.is_absolute() or '..' in path.parts or path.resolve() != path:
                raise Fault('RUNTIME_DRIFT', 409)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                    before.st_mode & 0o022 or before.st_size > 2 * 1024 * 1024):
                raise Fault('RUNTIME_DRIFT', 409)
            with os.fdopen(os.dup(fd), 'rb') as stream:
                observed = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = os.fstat(fd)
            if (observed != expected or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) !=
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)):
                raise Fault('RUNTIME_DRIFT', 409)
        except OSError:
            raise Fault('RUNTIME_DRIFT', 409) from None
        finally:
            if fd is not None: os.close(fd)
