"""Internal native GPU route authority and bounded hardware admission.

This is not renderer qualification. A successful driver query cannot replace
per-attempt Chromium attestation. No environment flag grants route authority.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import os
from pathlib import Path
import platform
import re
import selectors
import stat
import subprocess
import time


@dataclass(frozen=True, eq=False)
class _Route:
    name: str


FILMMAKING_ROUTE = _Route('chromium-native-nvidia-linux-v1')
CHROME_VERSION = '153.0.8010.52'
# Admission floor, NOT a measured workload peak or a kernel VRAM reservation.
# 512 MiB covers lightweight headless surfaces; retain 20% of physical VRAM
# (at least 512 MiB) for the desktop/other users. Heavy scenes can still refuse.
MIN_FREE_BYTES = 512 * 1024 ** 2


def is_supported(route):
    return route is FILMMAKING_ROUTE


def for_adapter(adapter, request):
    """Only the actual built-in adapter with a validated frozen binding qualifies."""
    from .adapters.filmmaking import FilmmakingAdapter
    if type(adapter) is not FilmmakingAdapter:
        return None
    adapter.validate_request(request)
    if not is_supported(for_registry(adapter.runtime.registry, 'local.filmmaking')):
        return None
    return FILMMAKING_ROUTE


def for_registry(registry, adapter_id):
    """Read canonical registered binding identity, not inspect()'s projection."""
    if adapter_id != 'local.filmmaking':
        return None
    descriptor = registry.option_descriptor(adapter_id, 'scene.render@1')
    return for_registration({'declaration': descriptor['declaration'],
                             'implementation_sha256': descriptor['binding']['implementation_sha256']})


def for_registration(entry):
    """Diagnostics use exact current built-in bytes, not an adapter-id assertion."""
    if entry.get('declaration', {}).get('adapter_id') != 'local.filmmaking':
        return None
    from .adapters.filmmaking import registration
    current = registration()
    if (entry.get('declaration') == current['declaration'] and
            entry.get('implementation_sha256') == current['implementation_sha256']):
        return FILMMAKING_ROUTE
    return None


def _query():
    executable = Path('/usr/bin/nvidia-smi').resolve(strict=True)
    info = executable.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
            info.st_mode & 0o022 or not os.access(executable, os.X_OK)):
        raise OSError('Untrusted NVIDIA query executable.')
    argv = [str(executable),
        '--query-gpu=index,driver_version,pci.bus_id,pci.device_id,memory.total,memory.free,utilization.gpu',
        '--format=csv,noheader,nounits']
    # Drain incrementally: timeout AND output cap are enforced, not just checked
    # after an unbounded communicate(). stderr cannot fill a second pipe.
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    assert process.stdout is not None  # PIPE is explicit above.
    deadline = time.monotonic() + 2
    data = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, 2)
                if not selector.select(remaining):
                    raise subprocess.TimeoutExpired(argv, 2)
                chunk = os.read(process.stdout.fileno(), min(4096, 65537 - len(data)))
                if not chunk:
                    selector.unregister(process.stdout)
                    break
                data.extend(chunk)
                if len(data) > 65536:
                    raise ValueError('Oversized NVIDIA metadata.')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, 2)
        if process.wait(timeout=remaining):
            raise subprocess.CalledProcessError(process.returncode, argv)
        return data.decode('ascii')
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)
        process.stdout.close()


def _device_available(index):
    for path in (Path('/dev/nvidiactl'), Path('/dev') / ('nvidia' + str(index))):
        if not stat.S_ISCHR(path.stat().st_mode) or not os.access(path, os.R_OK | os.W_OK):
            return False
    return True


def hardware():
    """One <=2s metadata query only when the supported route is requested.

    Ambiguous multi-GPU machines fail closed: Chromium's chosen device must not
    differ from the device whose free memory we admitted. No renderer is started.
    """
    report = {'available': False, 'qualified': False,
              'route': FILMMAKING_ROUTE.name,
              'reason': 'Native NVIDIA hardware/headroom unavailable.'}
    try:
        if platform.system() != 'Linux':
            return report
        rows = list(csv.reader(io.StringIO(_query()), strict=True))
        if len(rows) != 1 or len(rows[0]) != 7:
            raise ValueError('Exactly one complete NVIDIA GPU record required.')
        index, driver, bus, pci, total, free, utilization = [v.strip() for v in rows[0]]
        if not re.fullmatch(r'0|[1-9][0-9]{0,2}', index):
            raise ValueError('Invalid device index.')
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', driver):
            raise ValueError('Unknown NVIDIA driver.')
        if not re.fullmatch(r'[0-9A-Fa-f]{8}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]', bus):
            raise ValueError('Invalid PCI bus identity.')
        if not re.fullmatch(r'0x[0-9A-Fa-f]{8}', pci) or int(pci, 16) & 0xffff != 4318:
            raise ValueError('Non-NVIDIA device.')
        if any(not re.fullmatch(r'[0-9]+', v) for v in (total, free, utilization)):
            raise ValueError('Unknown NVIDIA headroom.')
        total, free = int(total) * 1024 ** 2, int(free) * 1024 ** 2
        utilization = int(utilization)
        if total <= 0 or not 0 <= free <= total or not 0 <= utilization <= 100:
            raise ValueError('Invalid NVIDIA headroom.')
        if not _device_available(int(index)):
            raise ValueError('NVIDIA device nodes unavailable.')
        reserve = max(MIN_FREE_BYTES, (total + 4) // 5)
        report.update(device={'driver_version': driver, 'vendor_id': 4318,
            'device_id': int(pci, 16) >> 16, 'pci_bus_id': bus, 'index': int(index)},
            total_bytes=total, free_bytes=free, utilization_percent=utilization,
            admission_floor_bytes=MIN_FREE_BYTES, reserve_bytes=reserve)
        if free - reserve < MIN_FREE_BYTES or utilization > 80:
            report['reason'] = 'Insufficient observed NVIDIA VRAM/utilization headroom.'
            return report
        report.update(available=True, reason='Driver/device/headroom admitted; renderer attestation still required.')
    except (OSError, ValueError, csv.Error, subprocess.SubprocessError):
        pass
    return report
