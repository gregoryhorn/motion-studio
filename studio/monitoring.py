"""Read-only, bounded task projections; canonical job/attempt records stay closed.

No probes or persistence on import/read. Execution writers alone retain timing,
phase, host and diagnostics in the compatible job bundle's ``monitoring`` field.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import copy
import math
import os
import re

TERMINAL = frozenset(('succeeded', 'failed', 'cancelled', 'interrupted'))
MAX_TEXT = 4096
MAX_EVENTS = 16
FENCE_NAME = 'native-update.lock'
_SECRET = re.compile(r'(?:authorization|password|passwd|secret|token|api[_-]?key|credential|cookie)', re.I)
_ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|$))')


def sanitize(value, *, limit=MAX_TEXT, depth=0):
    """Bound structure and strings, redact secrets and strip terminal controls.

    Not a promise to identify arbitrary secrets embedded in natural language.
    Never pass raw argv, environment, worker tokens or absolute paths here.
    """
    if depth >= 4:
        return '[depth limit]'
    if isinstance(value, dict):
        return {str(k)[:80]: '[redacted]' if _SECRET.search(str(k)) else
                sanitize(v, limit=limit, depth=depth + 1)
                for k, v in list(value.items())[:16]}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, limit=limit, depth=depth + 1) for v in value[:16]]
    if isinstance(value, float):
        # Durable core JSON forbids binary floats. Observed diagnostics use
        # documented decimal strings, never relaxed canonical validation.
        return format(Decimal(str(value)), 'f') if math.isfinite(value) else '[nonfinite observation]'
    if value is None or isinstance(value, (bool, int)):
        return value
    text = _ANSI.sub('', str(value)[:limit * 2])
    text = re.sub(r'https?://[^\s<>]+', '[url redacted]', text, flags=re.I)
    text = re.sub(r'(?i)\b(authorization|password|passwd|secret|token|api[_-]?key|cookie)\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+',
                  r'\1=[redacted]', text)
    text = re.sub(r'(?<![\w:])/(?:[^\s/:]+/)*[^\s,;:]*', '[path redacted]', text)
    text = ''.join(c for c in text if c in '\n\t' or (ord(c) >= 32 and ord(c) != 127))
    return text if len(text) <= limit else text[:limit - 14] + '...[truncated]'


def retain_error(bundle, error, *, attempt_id=None, source='execution', at=None):
    """Persist only sanitized bounded diagnostics, preserving the first error."""
    if not error:
        return
    monitor = bundle.setdefault('monitoring', {})
    event = {'at': at or _stamp(), 'attempt_id': attempt_id, 'source': source,
             'error': sanitize(error)}
    monitor.setdefault('first_error', copy.deepcopy(event))
    if source == 'engine':
        monitor.setdefault('first_engine_error', copy.deepcopy(event['error']))
    events = monitor.setdefault('diagnostics', [])
    events.append(event)
    del events[:-MAX_EVENTS]


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _parse(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _elapsed(start, end):
    start, end = _parse(start), _parse(end)
    if start is None or end is None:
        return None
    microseconds = (end - start) // timedelta(microseconds=1)
    if microseconds < 0:
        return None
    return f'{microseconds // 1000000}.{microseconds % 1000000:06d}'


def project_monitor(bundle, *, now=None):
    """Project existing records only; never repair, renew, reconcile or probe."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    job = bundle['job']
    monitor = bundle.get('monitoring', {})
    attempts = list(bundle.get('attempts', {}).values())
    starts = [a['started_at'] for a in attempts if a.get('started_at')]
    started = monitor.get('started_at') or (min(starts) if starts else None)
    ended = monitor.get('ended_at')
    terminal = job['state'] in TERMINAL
    # A last heartbeat/update is NOT a completion timestamp, including legacy data.
    end_for_timer = ended if terminal else stamp
    elapsed = _elapsed(started, end_for_timer)
    active = [a for a in attempts if not a.get('ended_at') and not terminal]
    leases = [a.get('owner', {}).get('lease_expires_at') for a in active]
    parsed_leases = [parsed for v in leases if (parsed := _parse(v)) is not None]
    expired = any(parsed < now for parsed in parsed_leases)
    blocked = [sanitize(n['blocked_reason']) for n in job.get('node_states', []) if n.get('blocked_reason')]
    stale = [sanitize(r) for r in job.get('stale_reasons', [])]
    if expired:
        stale.append('Observation lease expired; explicit reconcile required.')
    first = monitor.get('first_error')
    fallback = next((a.get('error') for a in attempts if a.get('error')), None) or job.get('error')
    error = first.get('error') if first else fallback
    phase = job['state'] if terminal else monitor.get('phase', job['state'])
    attempt_timers = []
    for attempt in attempts[-20:]:
        end = attempt.get('ended_at')
        attempt_elapsed = _elapsed(attempt.get('started_at'), end or (None if terminal else stamp))
        attempt_timers.append({'attempt_id': attempt.get('attempt_id'),
            'started_at': attempt.get('started_at'), 'ended_at': end,
            'elapsed_seconds': attempt_elapsed,
            'timer_final': bool(end and attempt_elapsed is not None),
            'lease_expires_at': attempt.get('owner', {}).get('lease_expires_at')})
    return {'phase': phase, 'host': sanitize(monitor.get('host')), 'started_at': started,
            'ended_at': ended, 'elapsed_seconds': elapsed,
            'timer_final': bool(terminal and ended and elapsed is not None),
            'clock_warning': 'Elapsed time unavailable: missing or regressed wall clock.' if started and elapsed is None else None,
            'lease_expired': expired, 'lease_expires_at': min((v for v in leases if v), default=None),
            'last_heartbeat_at': monitor.get('last_heartbeat_at'),
            'blocked_reasons': blocked[:16], 'stale_reasons': stale[:16],
            'cancel': copy.deepcopy(job.get('cancel')), 'first_error': sanitize(error),
            'first_engine_error': sanitize(monitor.get('first_engine_error')),
            'diagnostics': sanitize(monitor.get('diagnostics', [])[-MAX_EVENTS:]),
            'resources': sanitize(monitor.get('resources')),
            'attempt_timers': attempt_timers, 'attempt_count': len(attempts)}


@contextmanager
def native_work_fence(root, *, exclusive=False, recovery=False):
    """Profile storage-root fence shared by submit/workers and native updater.

    Updater MUST acquire exclusive=True on the same root for its complete native
    transaction. Reads/status never acquire or create this fence. Nonblocking:
    callers get a concrete LOCK_BUSY instead of racing an update. Descriptors are
    CLOEXEC and owner-scoped, released on all paths/process death; no lock unlink.
    Shared admission refuses a durable maintenance/pending.json crash marker.
    recovery=True is exclusive-only and bypasses only that marker, not the idle
    ledger. Check the marker via no-follow descriptors; never repair it here.
    The yielded FD belongs to this context, not to queued/detached executors.
    """
    from .contracts import ContractError
    from .project import ManagedFS
    try:
        import fcntl
    except ImportError:
        raise ContractError('STORAGE_UNSUPPORTED', 'Native update/work fence requires kernel file locks.') from None
    if recovery and not exclusive:
        raise ContractError('RECOVERY_REQUIRES_EXCLUSIVE', 'Recovery requires the exclusive native fence.')
    fs = ManagedFS(root)
    with fs.directory(create=True) as directory:
        fd = os.open(FENCE_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     0o600, dir_fd=directory)
        try:
            import stat
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise ContractError('PATH_UNSAFE', 'Unsafe native update/work fence.')
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ContractError('LOCK_BUSY', 'Native update or active work holds the profile fence.') from None
            if not recovery:
                # Missing maintenance is normal; any existing marker (including
                # an unsafe symlink) blocks work without opening or changing it.
                try:
                    maintenance = os.open('maintenance', os.O_RDONLY | os.O_DIRECTORY |
                                          os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                except FileNotFoundError:
                    maintenance = None
                if maintenance is not None:
                    try:
                        try:
                            os.stat('pending.json', dir_fd=maintenance, follow_symlinks=False)
                        except FileNotFoundError:
                            pass
                        else:
                            raise ContractError('RECOVERY_REQUIRED', 'Interrupted native update requires explicit recovery.')
                    finally:
                        os.close(maintenance)
            if exclusive:
                _require_idle_ledger(fs)
            yield fd
        finally:
            os.close(fd)


def _require_idle_ledger(fs):
    """Crash-safe writer refusal: lock death is not evidence children stopped.

    A running/uncertain durable record must be explicitly reconciled before a
    native update, even after its worker's shared lock has vanished on death.
    """
    from .contracts import ContractError, validate
    from .jobs import JOB_RECORD
    for project in fs.names('projects'):
        for name in fs.names('projects/' + project + '/jobs'):
            if not name.endswith('.json'):
                continue
            bundle = fs.read('projects/' + project + '/jobs/' + name)
            job = bundle['job']
            validate(job, JOB_RECORD)
            if (job['state'] not in TERMINAL | {'planned', 'queued'}
                    or job['submission_state'] in ('intent_recorded', 'uncertain')):
                raise ContractError('RESOURCE_BUSY', 'Durable active/uncertain job requires observed reconciliation before native update.')
