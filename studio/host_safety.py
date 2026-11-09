"""Measured host diagnostics and fail-closed owned-tree admission.

No import-time IO, services, installation, RLIMIT_AS or unrelated PID signalling.
A trusted administrator must delegate a cgroup-v2 subtree with cpu/memory/pids
already enabled and set MOTION_CGROUP_ROOT. Diagnostics never configure the host.
"""
from __future__ import annotations

from contextlib import contextmanager
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import socket
import sys
import time
import uuid

from .contracts import ContractError

_GIB = 1024 ** 3
_DEFAULTS = {'memory_bytes': 512 * 1024 ** 2, 'cpu_cores': 1.0,
             'disk_bytes': 512 * 1024 ** 2, 'pids': 128, 'gpu': False}


def _text(path):
    return Path(path).read_text().strip()


def _state_root():
    # Deliberately outside Hermes profiles: one user's Studio workers share it.
    return Path.home() / '.local/state/motion-studio/host-safety'


def _mounts():
    mounts = []
    for line in _text('/proc/self/mountinfo').splitlines():
        left, right = line.split(' - ', 1)
        if right.split()[0] == 'cgroup2':
            fields = left.split()
            # mountinfo escapes whitespace and backslash as octal sequences.
            def decode(value):
                for old, new in (('\\040', ' '), ('\\011', '\t'), ('\\012', '\n'), ('\\134', '\\')):
                    value = value.replace(old, new)
                return value
            mounts.append((Path(decode(fields[4])).resolve(), decode(fields[3])))
    return mounts


def _current_cgroup():
    relative = next(line[3:] for line in _text('/proc/self/cgroup').splitlines()
                    if line.startswith('0::'))
    for mount, namespace_root in _mounts():
        # A cgroup namespace may show '/' even when mountinfo retains the host root.
        if namespace_root == '/' or relative == '/':
            candidate = mount / relative.lstrip('/')
        else:
            try:
                candidate = mount / str(Path(relative).relative_to(namespace_root))
            except ValueError:
                continue
        if candidate.is_dir():
            return candidate, mount
    raise OSError('Current cgroup-v2 location is not visible.')


def _ancestors(path, mount):
    while True:
        yield path
        if path == mount:
            return
        path = path.parent


def delegation_candidates():
    """Read-only candidates; never select a root or broaden execution authority.

    Inspect only visible ancestors of this process, never scan arbitrary host
    trees. A writable owned subtree is a configuration candidate, not proof of
    exercised limits. Existing systemd delegation needs no new host setup.
    """
    result = {'candidates': [], 'automatic_selection': False,
              'qualification': 'metadata_only', 'reason': None}
    if platform.system() != 'Linux':
        result['reason'] = 'Linux cgroup-v2 delegation is required.'
        return result
    try:
        current, mount = _current_cgroup()
        for root in _ancestors(current, mount):
            try:
                if (root.is_symlink() or root.stat().st_uid != os.getuid()
                        or not os.access(root, os.W_OK | os.X_OK)):
                    continue
                enabled = set(_text(root / 'cgroup.subtree_control').split())
                if {'cpu', 'memory', 'pids'} <= enabled:
                    result['candidates'].append({'root': str(root),
                        'controllers': sorted(enabled), 'selected': False,
                        'verified': False})
            except OSError:
                continue  # A disappearing or unreadable ancestor is not usable.
        if not result['candidates']:
            result['reason'] = 'No visible owned writable pre-enabled ancestor observed.'
    except (OSError, ValueError, StopIteration):
        result['reason'] = 'Current cgroup-v2 ancestry is unavailable.'
    return result


def _enforcement():
    report = {'backend': None, 'available': False, 'root': None,
              'reason': 'Linux cgroup-v2 delegation is required.', 'verified': False}
    if platform.system() != 'Linux':
        return report
    configured = os.environ.get('MOTION_CGROUP_ROOT')
    if not configured:
        report['delegation_discovery'] = delegation_candidates()
        if report['delegation_discovery']['candidates']:
            report['reason'] = ('Existing delegated subtree candidates were observed; '
                'explicit execution-process MOTION_CGROUP_ROOT selection is required. '
                'No new host delegation setup is implied; no host changes were made.')
        else:
            report['reason'] = 'MOTION_CGROUP_ROOT is not configured; no host changes were made.'
        return report
    try:
        raw = Path(configured)
        root = raw.resolve(strict=True)
        if not raw.is_absolute() or raw.is_symlink():
            raise OSError('Delegated root must be an absolute non-symlink directory.')
        if not any(root == mount or mount in root.parents for mount, _ in _mounts()):
            raise OSError('Delegated root is not on a visible cgroup-v2 mount.')
        if root.stat().st_uid != os.getuid():
            raise OSError('Delegated root must belong to this execution user.')
        if not {'cpu', 'memory', 'pids'} <= set(_text(root / 'cgroup.subtree_control').split()):
            raise OSError('Delegated root lacks pre-enabled cpu/memory/pids controllers.')
        if not os.access(root, os.W_OK | os.X_OK):
            raise OSError('Delegated root is not writable.')
        report.update(backend='cgroup-v2', available=True, root=str(root),
                      reason='Delegation candidate; child controls are verified during admission.')
    except (OSError, ValueError) as exc:
        report['reason'] = str(exc)
    return report


def _gpu():
    devices = []
    try:
        for device in Path('/sys/bus/pci/devices').iterdir():
            if _text(device / 'class').startswith('0x03'):
                devices.append({'pci_id': device.name, 'vendor': _text(device / 'vendor'),
                                'device': _text(device / 'device')})
        return {'state': 'detected' if devices else 'not_detected',
                'devices': devices, 'qualified': False,
                'reason': 'PCI detection is not driver, engine, VRAM or route qualification.'}
    except OSError as exc:
        return {'state': 'unknown', 'devices': devices, 'qualified': False, 'reason': str(exc)}


def _cpu_ids(value):
    ids = set()
    for span in value.split(','):
        first, sep, last = span.partition('-')
        lo, hi = int(first), int(last) if sep else int(first)
        if lo < 0 or hi < lo or hi > 1048575:
            raise ValueError('Invalid CPU identity range.')
        ids.update(range(lo, hi + 1))
    if not ids:
        raise ValueError('Empty CPU identity set.')
    return frozenset(ids)


def _cpu_frame(enforcement):
    """One bounded read window; cpu.stat usage includes ALL descendants/siblings.

    Both current and destination ancestry constrain admission conservatively.
    Hidden ancestors cannot be inferred; this measures only visible hierarchy.
    """
    started = time.monotonic()
    current, mount = _current_cgroup()
    locations = [(current, mount)]
    if enforcement['available']:
        root = Path(enforcement['root'])
        root_mount = max((m for m, _ in _mounts() if root == m or m in root.parents),
                         key=lambda m: len(m.parts))
        locations.append((root, root_mount))
    online = _cpu_ids(_text('/sys/devices/system/cpu/online'))
    affinity = frozenset(os.sched_getaffinity(0))
    eligible = online & affinity
    configs, usages = {}, {}
    for location, boundary in locations:
        # Walk top-down so a disabled child's exact inherited cpuset is already
        # observed, never guessed from affinity/online CPUs or a host-wide default.
        for group in reversed(tuple(_ancestors(location, boundary))):
            if str(group) in configs:
                continue
            info = group.stat()
            controllers = frozenset(_text(group / 'cgroup.controllers').split())
            subtree = frozenset(_text(group / 'cgroup.subtree_control').split())
            if (not subtree <= controllers or any(
                    not token.isascii() or not token.replace('_', '').isalnum()
                    for token in controllers | subtree)):
                raise ValueError('Invalid cgroup controller declarations.')
            parent = None
            if group == boundary:
                cpuset_enabled = True  # Visible root's effective set is mandatory.
            else:
                parent = configs[str(group.parent)]
                parent_subtree = parent[6][1]
                cpuset_enabled = 'cpuset' in parent_subtree
                if cpuset_enabled != ('cpuset' in controllers):
                    raise ValueError('Inconsistent cpuset controller hierarchy.')
            try:
                cpus = _cpu_ids(_text(group / 'cpuset.cpus.effective'))
            except FileNotFoundError:
                if cpuset_enabled or parent is None:
                    raise
                cpus, cpuset_source = parent[4], parent[6][2]
            else:
                if not cpuset_enabled or 'cpuset' not in controllers:
                    raise ValueError('Unexpected cpuset interface without controller.')
                cpuset_source = str(group)
            # Only the actual hierarchy root is allowed to lack cpu.max.
            try:
                quota, period = _text(group / 'cpu.max').split()
            except FileNotFoundError:
                if group != boundary:
                    raise
                quota, period = 'max', '100000'
            period = int(period)
            if period <= 0 or (quota != 'max' and int(quota) <= 0):
                raise ValueError('Invalid CPU quota.')
            eligible &= cpus
            capacity = None if quota == 'max' else int(quota) / period
            # Preserve each node's identity and declarations plus the actual
            # cpuset source in BOTH samples, even when the inherited IDs agree.
            configs[str(group)] = (info.st_dev, info.st_ino, quota, period, cpus, capacity,
                                   (controllers, subtree, cpuset_source))
            if capacity is not None:
                stats = dict(line.split() for line in _text(group / 'cpu.stat').splitlines())
                usages[str(group)] = int(stats['usage_usec'])
                if usages[str(group)] < 0:
                    raise ValueError('Negative cgroup CPU usage.')
    counters = {}
    for line in _text('/proc/stat').splitlines():
        fields = line.split()
        if fields and fields[0].startswith('cpu') and fields[0][3:].isdigit():
            values = tuple(map(int, fields[1:]))
            if len(values) < 8 or any(v < 0 for v in values):
                raise ValueError('Invalid per-CPU counters.')
            counters[int(fields[0][3:])] = values
    if set(counters) != online or not eligible:
        raise ValueError('CPU topology missing or empty execution intersection.')
    ended = time.monotonic()
    if not 0 <= ended - started <= .05:
        raise ValueError('CPU read window too slow.')
    return {'started': started, 'ended': ended, 'online': online, 'affinity': affinity,
            'eligible': eligible, 'configs': configs, 'usages': usages, 'counters': counters,
            'locations': tuple(locations), 'boot': _text('/proc/sys/kernel/random/boot_id'),
            'hz': os.sysconf('SC_CLK_TCK')}


def _cpu_scopes(first, second, now):
    """Reduce two same-window samples, never scale host load by affinity/quota."""
    for key in ('online', 'affinity', 'eligible', 'configs', 'locations', 'boot', 'hz'):
        if first[key] != second[key]:
            raise ValueError('CPU topology/configuration changed: ' + key)
    elapsed = second['ended'] - first['ended']
    if (not .08 <= elapsed <= .5 or not 0 <= now - second['ended'] <= .25
            or first['hz'] <= 0):
        raise ValueError('Stale or invalid CPU measurement window.')
    busy = 0.0
    for cpu in first['online']:
        before, after = first['counters'][cpu], second['counters'][cpu]
        if len(before) != len(after):
            raise ValueError('CPU counter layout changed.')
        delta = [b - a for a, b in zip(before, after)]
        if any(v < 0 for v in delta):
            raise ValueError('CPU counters reset.')
        # guest/guest_nice are already in user/nice. Only idle is available;
        # iowait and steal consume conservative headroom, never count as idle.
        total = sum(delta[:8]) / first['hz']
        if abs(total - elapsed) > .06 + elapsed * .20:
            raise ValueError('CPU counters inconsistent with sample window.')
        if cpu in first['eligible']:
            busy += (sum(delta[:8]) - delta[3]) / first['hz'] / elapsed
    scopes = [{'kind': 'eligible', 'capacity': float(len(first['eligible'])), 'demand': busy}]
    if first['usages'].keys() != second['usages'].keys():
        raise ValueError('Quota scope changed.')
    for group, before in first['usages'].items():
        used = second['usages'][group] - before
        if used < 0 or used / 1e6 > len(first['online']) * (elapsed + .1):
            raise ValueError('Cgroup usage reset or inconsistent.')
        scopes.append({'kind': 'quota', 'path': group,
                       'capacity': first['configs'][group][5], 'demand': used / 1e6 / elapsed})
    return {'window_seconds': elapsed, 'sampled_at': second['ended'],
            'eligible_ids': sorted(first['eligible']),
            'host_count': len(first['online']), 'scopes': scopes}


def _collect_cpu(enforcement):
    first = _cpu_frame(enforcement)
    time.sleep(.12)  # Fixed bounded sample, no polling/retries or workload launch.
    second = _cpu_frame(enforcement)
    return _cpu_scopes(first, second, time.monotonic())


def snapshot(paths=()):
    """Read-only JSON diagnostics on THIS execution host, never the Desktop client.

    Paths identify every input/output/cache volume. Nonexistent outputs use the
    nearest existing ancestor for statvfs; no paths means unknown storage readiness.
    available=True describes delegation discovery, not an exercised kernel limit.
    """
    report = {'platform': platform.system(), 'host': socket.gethostname(),
              'cpu': {'effective_count': None, 'load_1m': None},
              'memory': {'total_bytes': None, 'available_bytes': None},
              'disks': [], 'hardware': {'gpu': _gpu()},
              'enforcement': _enforcement(), 'errors': []}
    if report['platform'] == 'Linux':
        try:
            memory = {}
            for line in _text('/proc/meminfo').splitlines():
                key, value = line.split(':', 1)
                memory[key] = int(value.split()[0]) * 1024
            report['memory'].update(total_bytes=memory['MemTotal'], available_bytes=memory['MemAvailable'])
        except (OSError, ValueError, KeyError) as exc:
            report['errors'].append('memory: ' + str(exc))
        try:
            # This marker is ALWAYS present in real snapshots, including errors.
            # Old injected policy fixtures may omit it; real collection cannot.
            report['cpu']['scope_measurement'] = None
            report['cpu']['load_1m'] = os.getloadavg()[0]
            scopes = _collect_cpu(report['enforcement'])
            report['cpu']['scope_measurement'] = scopes
            report['cpu']['effective_count'] = min(s['capacity'] for s in scopes['scopes'])
        except (OSError, AttributeError, ValueError, KeyError, StopIteration) as exc:
            report['errors'].append('cpu: ' + str(exc))
        try:
            current, mount = _current_cgroup()
            groups = list(_ancestors(current, mount))
            if report['enforcement']['available']:
                root = Path(report['enforcement']['root'])
                root_mount = max((m for m, _ in _mounts() if root == m or m in root.parents),
                                 key=lambda m: len(m.parts))
                groups.extend(_ancestors(root, root_mount))
            mountpoints = {m for m, _ in _mounts()}
            for group in dict.fromkeys(groups):
                try:
                    limit = _text(group / 'memory.max')
                except FileNotFoundError:
                    if group not in mountpoints:
                        raise
                    limit = 'max'  # the real hierarchy root has no limit file
                if limit != 'max':
                    maximum, used = int(limit), int(_text(group / 'memory.current'))
                    mem = report['memory']
                    if mem['total_bytes'] is not None:
                        mem['total_bytes'] = min(mem['total_bytes'], maximum)
                        mem['available_bytes'] = min(mem['available_bytes'], max(0, maximum - used))
        except (OSError, ValueError, StopIteration) as exc:
            # Missing container limits cannot be mistaken for bare-host capacity.
            report['memory'].update(total_bytes=None, available_bytes=None)
            report['cpu']['effective_count'] = None
            report['errors'].append('cgroup capacity: ' + str(exc))
    else:
        report['errors'].append('CPU/RAM admission measurement is unsupported on this platform.')
    for requested in paths:
        entry = {'path': os.fspath(requested), 'device': None, 'total_bytes': None,
                 'available_bytes': None, 'error': None}
        try:
            target = Path(requested).expanduser().absolute()
            while not target.exists() and target != target.parent:
                target = target.parent
            info, volume = target.stat(), os.statvfs(target)
            entry.update(device=str(info.st_dev), measured_at=str(target.resolve()),
                         total_bytes=volume.f_blocks * volume.f_frsize,
                         available_bytes=volume.f_bavail * volume.f_frsize)
        except (OSError, ValueError, AttributeError) as exc:
            entry['error'] = str(exc)
        report['disks'].append(entry)
    report['reservations'] = {'memory_bytes': 0, 'cpu_cores': 0, 'disk_bytes': {}}
    if report['enforcement']['available']:
        try:
            report['reservations'] = _reservations(Path(report['enforcement']['root']), _state_root())
        except (OSError, ContractError) as exc:
            report['enforcement'].update(available=False, reason=str(exc))
    return report


def _requirements(value):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(_DEFAULTS):
        raise ContractError('INVALID_ARGUMENT', 'Unknown host resource requirement.')
    req = dict(_DEFAULTS, **value)
    for key in ('memory_bytes', 'disk_bytes', 'pids'):
        if type(req[key]) is not int or req[key] <= 0:
            raise ContractError('INVALID_ARGUMENT', key + ' must be a positive integer.')
    cpu = req['cpu_cores']
    if type(cpu) not in (int, float) or not math.isfinite(cpu) or cpu <= 0:
        raise ContractError('INVALID_ARGUMENT', 'cpu_cores must be positive and finite.')
    if type(req['gpu']) is not bool:
        raise ContractError('INVALID_ARGUMENT', 'gpu must be boolean.')
    return req


def _policy(measured, requirements, reserved, *, gpu_route=None):
    req = _requirements(requirements)
    reasons = []
    if req['gpu']:
        from . import gpu_route as routes
        if not routes.is_supported(gpu_route):
            reasons.append('GPU_ROUTE_UNQUALIFIED')
        else:
            native = routes.hardware()
            measured['hardware']['gpu']['native_admission'] = native
            if native.get('available') is not True:
                reasons.append('GPU_HEADROOM_UNAVAILABLE')
    # Check CPU sample freshness AFTER the bounded GPU metadata query as well.
    memory, cpu = measured['memory'], measured['cpu']
    total, available = memory['total_bytes'], memory['available_bytes']
    memory_budget = None
    if total is None or available is None:
        reasons.append('MEMORY_UNKNOWN')
    else:
        memory_budget = max(0, available - max(_GIB, math.ceil(total * .20)) - reserved.get('memory_bytes', 0))
        if req['memory_bytes'] > memory_budget:
            reasons.append('MEMORY_HEADROOM')
    cores, load = cpu['effective_count'], cpu['load_1m']
    cpu_budget = None
    scope_data = cpu.get('scope_measurement')
    if 'scope_measurement' in cpu:
        # Host queue pressure and narrower execution utilization are distinct
        # guards. Neither replaces the other. Min budgets avoid adding scopes.
        try:
            if not 0 <= time.monotonic() - scope_data['sampled_at'] <= .5:
                raise ValueError('Stale CPU scope.')
            scopes = [{'capacity': scope_data['host_count'], 'demand': load},
                      *scope_data['scopes']]
            if cores is None or not scopes[1:] or scopes[1]['kind'] != 'eligible':
                raise ValueError('Missing execution scope.')
            budgets = []
            for scope in scopes:
                capacity, demand = scope['capacity'], scope['demand']
                if (not all(type(v) in (int, float) and math.isfinite(v)
                            for v in (capacity, demand)) or capacity <= 0 or demand < 0):
                    raise ValueError('Unknown CPU scope.')
                budgets.append(max(0, capacity - max(.5, capacity * .20)
                                   - demand - reserved.get('cpu_cores', 0)))
            cpu_budget = min(budgets)
        except (KeyError, TypeError, ValueError):
            reasons.append('CPU_UNKNOWN')
    elif (cores is None or load is None or not math.isfinite(cores)
          or not math.isfinite(load) or cores <= 0 or load < 0):
        # Compatibility for injected legacy policy fixtures only: production
        # snapshot always sets scope_measurement, even when collection fails.
        reasons.append('CPU_UNKNOWN')
    else:
        cpu_budget = max(0, cores - max(.5, cores * .20) - load - reserved.get('cpu_cores', 0))
    if cpu_budget is not None and req['cpu_cores'] > cpu_budget:
        reasons.append('CPU_HEADROOM')
    disks = {}
    if not measured['disks']:
        reasons.append('DISK_UNKNOWN')
    for disk in measured['disks']:
        device = disk['device']
        if disk.get('error') or device is None or disk['total_bytes'] is None or disk['available_bytes'] is None:
            reasons.append('DISK_UNKNOWN')
            continue
        budget = max(0, disk['available_bytes'] - max(_GIB, math.ceil(disk['total_bytes'] * .10))
                     - reserved.get('disk_bytes', {}).get(device, 0))
        disks[device] = min(disks.get(device, budget), budget)
        if req['disk_bytes'] > budget:
            reasons.append('DISK_HEADROOM')
    if not measured['enforcement']['available']:
        reasons.append('ENFORCEMENT_UNAVAILABLE')
    return {'allowed': not reasons, 'reasons': sorted(set(reasons)), 'requirements': req,
            'budget': {'memory_bytes': memory_budget, 'cpu_cores': cpu_budget, 'disk_bytes': disks},
            'snapshot': measured, 'paths': [d['path'] for d in measured['disks']],
            'enforced': False, 'advisory': True}


def admission(paths=(), requirements=None, *, gpu_route=None):
    """Read-only advisory policy. Acquire OwnedProcessLimits(policy) to reserve.

    Defaults are bounded lightweight work, not workload size prediction. Adapters
    must declare larger peak memory/storage demands. Disk is reservation/admission,
    NOT a filesystem quota; recheck before large output writes.
    """
    measured = snapshot(paths)
    return _policy(measured, requirements, measured.get('reservations', {}), gpu_route=gpu_route)


def _reservations(root, state):
    reserved = {'memory_bytes': 0, 'cpu_cores': 0, 'disk_bytes': {}}
    for group in root.iterdir():
        if not group.name.startswith('motion-') or not group.is_dir():
            continue
        try:
            if group.is_symlink():
                raise ValueError('Symlink cgroup is not an owned reservation.')
            memory = int(_text(group / 'memory.max'))
            quota, period = map(int, _text(group / 'cpu.max').split())
            if memory <= 0 or quota <= 0 or period <= 0:
                raise ValueError('Unbounded existing reservation.')
            record = json.loads(_text(state / (group.name + '.json')))
            disks = record['disk_bytes']
            if not isinstance(disks, dict) or any(type(v) is not int or v <= 0 for v in disks.values()):
                raise ValueError('Invalid disk reservation.')
            reserved['memory_bytes'] += memory
            reserved['cpu_cores'] += quota / period
            for device, amount in disks.items():
                reserved['disk_bytes'][device] = reserved['disk_bytes'].get(device, 0) + amount
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ContractError('RESOURCE_BUSY', 'Existing cgroup reservation cannot be accounted safely: ' + group.name) from exc
    return reserved


@contextmanager
def _locked_state(state):
    # Portable import: other OSes can import diagnostic code without fcntl.
    import fcntl
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    if state.is_symlink() or state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077:
        raise ContractError('PERMISSION_DENIED', 'Host admission state must be private and owned by this user.')
    fd = os.open(state / 'admission.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _configure_group(group, req):
    controls = {'memory.max': str(req['memory_bytes']), 'memory.swap.max': '0',
                'memory.oom.group': '1', 'cpu.max': f"{math.ceil(req['cpu_cores'] * 100000)} 100000",
                'pids.max': str(req['pids'])}
    for key, value in controls.items():
        (group / key).write_text(value)
        if _text(group / key) != value:
            raise OSError('Kernel did not confirm ' + key)
    if not (group / 'cgroup.kill').exists():
        raise OSError('Kernel cgroup.kill is required for owned-tree cleanup.')


# No preexec_fn: it is unsafe in a threaded worker. The isolated interpreter joins
# through an inherited cgroup.procs FD BEFORE exec, so the workload cannot fork
# outside the group. The inherited descriptor is closed before the workload exec.
_LAUNCH = ('import os,sys; fd=int(sys.argv[1]); '
           'os.write(fd,str(os.getpid()).encode()); os.close(fd); '
           'os.execvpe(sys.argv[2],sys.argv[2:],os.environ)')


class OwnedProcessLimits:
    """Context reservation for WorkerContext's Popen (never a second owner).

    with OwnedProcessLimits(admission(paths, requirements)) as limits:
        argv, extra = limits.prepare_spawn(argv)
        proc = subprocess.Popen(argv, pass_fds=(*existing_fds, *extra['pass_fds']), ...)
        proc.communicate()  # context MUST outlive Popen and ALL descendants

    __enter__ refreshes measurements while holding the cross-process kernel lock.
    Exit kills only this freshly created cgroup's descendants, then removes it.
    Trusted adapter containment, not a hostile same-UID security sandbox.
    """
    def __init__(self, policy, *, state_root=None, gpu_route=None):
        if not isinstance(policy, dict) or 'requirements' not in policy or 'paths' not in policy:
            raise ContractError('INVALID_ARGUMENT', 'OwnedProcessLimits requires an admission policy.')
        self.paths = tuple(policy['paths'])
        self.requirements = _requirements(policy['requirements'])
        self.policy = policy
        # Authority is deliberately NOT recovered from a serializable policy.
        self.gpu_route = gpu_route
        self.state = Path(state_root) if state_root is not None else _state_root()
        self.group = None
        self._procs_fd = None
        self._lease_fd = None
        self._used = False

    def __enter__(self):
        if self.group is not None:
            raise ContractError('INVALID_ARGUMENT', 'Limits context is already entered.')
        if platform.system() != 'Linux':
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Supported process-tree enforcement is unavailable.')
        import fcntl
        with _locked_state(self.state):
            enforcement = _enforcement()
            if not enforcement['available']:
                raise ContractError('DEPENDENCY_UNAVAILABLE', enforcement['reason'])
            root = Path(enforcement['root'])
            self._reclaim_empty(root)
            measured = snapshot(self.paths)
            # Snapshot also accounts reservations in the canonical state root;
            # injected test state is intentionally used only at this boundary.
            measured['enforcement'] = enforcement
            reserved = _reservations(root, self.state)
            self.policy = _policy(measured, self.requirements, reserved, gpu_route=self.gpu_route)
            if not self.policy['allowed']:
                raise ContractError('RESOURCE_BUSY', 'Host admission refused.', details=self.policy)
            name = 'motion-' + uuid.uuid4().hex
            group = root / name
            record = self.state / (name + '.json')
            lease = self.state / (name + '.lock')
            try:
                self._lease_fd = os.open(lease, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
                fcntl.flock(self._lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                group.mkdir()
                _configure_group(group, self.requirements)
                reservation = {device: self.requirements['disk_bytes'] for device in self.policy['budget']['disk_bytes']}
                fd = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'disk_bytes': reservation}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._procs_fd = os.open(group / 'cgroup.procs', os.O_WRONLY | os.O_CLOEXEC)
                self.group = group
                self.policy.update(enforced=True, advisory=False, cgroup=str(group))
            except BaseException:
                try:
                    if self._procs_fd is not None:
                        os.close(self._procs_fd)
                        self._procs_fd = None
                    if group.exists():
                        group.rmdir()  # no executable has been launched yet
                    record.unlink(missing_ok=True)
                    lease.unlink(missing_ok=True)
                finally:
                    if self._lease_fd is not None:
                        os.close(self._lease_fd)
                        self._lease_fd = None
                raise
        return self

    def _reclaim_empty(self, root):
        import fcntl
        for group in root.iterdir():
            if not group.name.startswith('motion-') or not group.is_dir() or group.is_symlink():
                continue
            lock = self.state / (group.name + '.lock')
            try:
                fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            except FileNotFoundError:
                continue  # unknown ownership is a blocker, not permission to delete
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                if 'populated 0' in _text(group / 'cgroup.events').splitlines():
                    group.rmdir()
                    (self.state / (group.name + '.json')).unlink(missing_ok=True)
                    lock.unlink(missing_ok=True)
            finally:
                os.close(fd)

    def prepare_spawn(self, argv):
        """Return (wrapped_argv, {'pass_fds': (...)}) for exactly ONE owned Popen.

        Merge these FDs with WorkerContext's cwd FD. Preserve start_new_session,
        env, cwd and stdio. Never use shell=True, executable= or preexec_fn with
        this wrapper. Failed containment exits the launcher before workload exec.
        """
        if self.group is None or self._procs_fd is None or self._used:
            raise ContractError('PERMISSION_DENIED', 'Limits must be entered and unused before spawn.')
        if not isinstance(argv, (tuple, list)) or not argv or any(not isinstance(v, str) or '\x00' in v for v in argv):
            raise ContractError('INVALID_ARGUMENT', 'Owned command must be a nonempty string argv.')
        self._used = True
        return [sys.executable, '-I', '-S', '-c', _LAUNCH, str(self._procs_fd), *argv], {'pass_fds': (self._procs_fd,)}

    def measurements(self):
        """Read owned cgroup measurements; no process mutation or admission."""
        if self.group is None:
            return {'state': 'not_entered'}
        result: dict = {'state': 'active', 'cgroup': str(self.group)}
        from . import gpu_route as routes
        if routes.is_supported(self.gpu_route):
            # Preserve observed driver/device metadata after serial child cleanup;
            # WorkerContext.resource_snapshot survives while self.limits does not.
            result['native_gpu_admission'] = self.policy['snapshot']['hardware']['gpu'].get('native_admission')
        for name in ('memory.current', 'memory.peak', 'memory.events', 'cpu.stat', 'pids.current', 'cgroup.events'):
            try:
                result[name] = _text(self.group / name)
            except OSError as exc:
                result[name] = None
                result.setdefault('errors', []).append(str(exc))
        return result

    def __exit__(self, exc_type, exc, tb):
        if self.group is None:
            return False
        group = self.group
        try:
            # cgroup.kill includes descendants even if they changed session/group.
            (group / 'cgroup.kill').write_text('1')
            deadline = time.monotonic() + 5
            while 'populated 0' not in _text(group / 'cgroup.events').splitlines():
                if time.monotonic() >= deadline:
                    raise ContractError('RESOURCE_BUSY', 'Owned cgroup cleanup pending; reservation retained.')
                time.sleep(.02)
            with _locked_state(self.state):
                group.rmdir()
                (self.state / (group.name + '.json')).unlink(missing_ok=True)
                (self.state / (group.name + '.lock')).unlink(missing_ok=True)
        finally:
            if self._procs_fd is not None:
                os.close(self._procs_fd)
                self._procs_fd = None
            if self._lease_fd is not None:
                os.close(self._lease_fd)
                self._lease_fd = None
            self.group = None
        return False


def validate_topology(topology):
    """Pure Desktop configuration validator; never a remote qualification claim.

    All five locations require explicit host identities. Remote backend addresses
    must be literal RFC1918/ULA or Tailscale addresses, not wildcard/public/loopback.
    Authentication/reconnect/accessibility flags are declared requirements only;
    no network reachability, login or Desktop reconnect is exercised here.
    """
    reasons = []
    if not isinstance(topology, dict):
        return {'valid': False, 'reasons': ['TOPOLOGY_REQUIRED'], 'remote_client_qualified': False,
                'remote': None, 'locations': {}, 'evidence': 'configuration_only'}
    locations = {}
    for name in ('client', 'backend', 'files', 'compute', 'preview'):
        value = topology.get(name)
        if not isinstance(value, dict) or not isinstance(value.get('host'), str) or not value['host'].strip():
            reasons.append(name.upper() + '_LOCATION_REQUIRED')
            locations[name] = {}
        else:
            locations[name] = value
    backend = locations['backend'].get('host')
    remote = bool(backend and locations['client'].get('host') and backend != locations['client']['host'])
    if backend and locations['compute'].get('host') != backend:
        reasons.append('COMPUTE_BACKEND_MISMATCH')
    if backend and locations['files'].get('host') != backend:
        reasons.append('FILES_BACKEND_MISMATCH')
    for name in ('files', 'preview'):
        if locations[name].get('accessible') is not True:
            reasons.append(name.upper() + '_ACCESS_UNCONFIRMED')
    address = locations['backend'].get('address')
    try:
        if not isinstance(address, str):
            raise ValueError('An explicit literal IP string is required.')
        ip = ipaddress.ip_address(address)
        tailscale = ip.version == 4 and ip in ipaddress.ip_network('100.64.0.0/10')
        lan = any(ip in ipaddress.ip_network(network) for network in
                  ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))
        if ip.is_unspecified or ip.is_multicast or not (ip.is_loopback or lan or tailscale):
            reasons.append('PUBLIC_OR_WILDCARD_ADDRESS')
        if remote and ip.is_loopback:
            reasons.append('REMOTE_LOOPBACK')
    except (ValueError, TypeError):
        reasons.append('BACKEND_LITERAL_ADDRESS_REQUIRED')
    if remote:
        if topology.get('authentication') is not True:
            reasons.append('AUTHENTICATION_REQUIRED')
        if topology.get('reconnect') is not True:
            reasons.append('RECONNECT_REQUIRED')
    return {'valid': not reasons, 'reasons': sorted(set(reasons)), 'remote': remote,
            'remote_client_qualified': False, 'evidence': 'configuration_only',
            'locations': locations}
