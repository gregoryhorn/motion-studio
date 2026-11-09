"""Shared local video bounds; these are adapter policy, not engine limits."""
MAX_WIDTH = 4096
MAX_HEIGHT = 4096
MAX_FRAMES = 216000  # One hour at 60 fps; rates.bounds also checks elapsed time.


def output_byte_limit(port):
    """Lossless intermediates and editable archives need more room than reports."""
    if (port['kind'],port['media_type']) in (('media','video/x-matroska'),('archive','application/zip')):
        return 256 * 1024 * 1024
    return 16 * 1024 * 1024


def output_file_limit(port):
    """Explicit bounded production files; byte APIs retain their smaller limits."""
    if ((port['kind'] == 'media' and port['media_type'] in (
            'video/x-matroska', 'video/mp4', 'video/quicktime', 'audio/wav', 'audio/x-wav'))
            or (port['kind'] == 'audio' and port['media_type'] in ('audio/wav','audio/x-wav'))):
        return 16 * 1024 * 1024 * 1024
    return output_byte_limit(port)


def output_payload(source, port):
    """Stable bounded bytes or a sealed Linux snapshot, never a writable mmap.

    Snapshot in 1 MiB chunks before decoding. Source truncation cannot SIGBUS
    a consumer, and subprocesses open the sealed fd instead of retaining an
    exported Python memoryview across timeout/exception cleanup.
    """
    from collections import namedtuple
    from contextlib import contextmanager
    import fcntl
    import mmap
    import os
    import stat
    from ..contracts import ContractError
    observed = namedtuple('OutputPayload', 'data input_path')

    @contextmanager
    def opened():
        before = os.fstat(source.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= output_file_limit(port)):
            raise ContractError('OUTPUT_INVALID', 'Output must be a bounded owned regular file, not a link.')
        def unchanged():
            after = os.fstat(source.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ContractError('OUTPUT_INVALID', 'Output changed during validation/publication.')
        if before.st_size > output_byte_limit(port):
            # Fail closed if sealed memfd support is unavailable; no mutable
            # on-disk/mmap fallback. This local adapter already targets Linux.
            fd = os.memfd_create('motion-output', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            with os.fdopen(fd, 'w+b') as snapshot:
                remaining = before.st_size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ContractError('OUTPUT_INVALID', 'Output truncated during snapshot.')
                    snapshot.write(chunk)
                    remaining -= len(chunk)
                snapshot.flush()
                unchanged()
                # Linux UAPI constants (linux/fcntl.h); standalone Python
                # builds may omit these names despite kernel memfd support.
                add_seals = getattr(fcntl, 'F_ADD_SEALS', 1033)
                get_seals = getattr(fcntl, 'F_GET_SEALS', 1034)
                seals = 0x0001 | 0x0002 | 0x0004 | 0x0008
                fcntl.fcntl(fd, add_seals, seals)
                if fcntl.fcntl(fd, get_seals) & seals != seals:
                    raise ContractError('OUTPUT_INVALID', 'Output snapshot could not be sealed.')
                with mmap.mmap(fd, 0, access=mmap.ACCESS_READ) as payload:
                    yield observed(payload, f'/proc/{os.getpid()}/fd/{fd}')
                    unchanged()
        else:
            payload = source.read(output_byte_limit(port) + 1)
            unchanged()
            if len(payload) != before.st_size:
                raise ContractError('OUTPUT_INVALID', 'Output changed during validation.')
            yield observed(payload, None)
            unchanged()
    return opened()
