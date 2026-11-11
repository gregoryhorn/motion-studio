"""Owned Linux child/process-group supervision; no PID supplied by a caller."""
import hashlib
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from ..child_env import child_environment
from ..assets.producer_files import staging_size
from ..domain import Fault
from ..runs.process_observation import retirement

BOOTSTRAP = Path(__file__).with_name('child_entry.py')


def incarnation(pid):
    try:
        tail = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, parent=int(tail[1]), group=int(tail[2]), session=int(tail[3]),
                    start=tail[19], boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    except (OSError, ValueError, IndexError):
        return None


def is_owned(child, pin):
    actual = incarnation(child.pid)
    return (actual is not None and actual == pin and pin['parent'] == os.getpid()
            and pin['group'] == child.pid and pin['session'] == child.pid)


def signal_owned(child, pin, sig):
    if not is_owned(child, pin):
        raise Fault('PROCESS_OWNERSHIP_UNKNOWN', 409)
    os.killpg(pin['group'], sig)


def observed_exit(pin, code, reason, counts):
    try:
        retired, facts = retirement(pin)
        cleanup_error = None
    except Exception as error:
        retired, facts, cleanup_error = False, None, type(error).__name__
    return dict(code=code, reason=reason, process=pin, capture=counts,
                group_retired=retired, retirement=facts, cleanup_error=cleanup_error,
                process_gone=incarnation(pin['pid']) is None)


class OwnedProcess:
    def __init__(self, deadline: float = 600, grace: float = 5, capture_limit=65536, staging_limit=64 * 1024 * 1024):
        self.deadline, self.grace = deadline, grace
        self.capture_limit, self.staging_limit = capture_limit, staging_limit
        self.after_spawn = lambda: None
        self.capture_chunk = lambda name, chunk: None

    def execute(self, argv, environment, directory, descriptor, final_admission, persist, stop, launching=None, *, monitor=None, deadline=None):
        """Limits bootstrap execs the tool in the SAME owned PID, never a shell supervisor."""
        budget = self.deadline if deadline is None else min(self.deadline,deadline)
        child = None
        pin = None
        selector = selectors.DefaultSelector()
        counts = {'stdout': 0, 'stderr': 0}
        observation = None
        usage = monitor or (lambda: staging_size(descriptor))
        try:
            child_environment_values = child_environment('owned', environment)
            # The only final admission point. Nothing rewrites argv/env/cwd afterward.
            final_admission(argv)
            if incarnation(os.getpid()) is None:
                raise Fault('SUPERVISION_UNAVAILABLE', 409)
            executable_digest = hashlib.sha256(Path(argv[0]).read_bytes()).hexdigest()
            # Entering Popen is the uncertainty boundary, NOT later ownership persistence.
            # A returned child (or a fault within Popen) cannot prove no effect occurred.
            if launching is not None:
                launching()
            child = subprocess.Popen([sys.executable, '-I', str(BOOTSTRAP), executable_digest, str(budget), *argv],
                                     shell=False, cwd=directory, env=child_environment_values,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
            pin = incarnation(child.pid)
            if pin is None or not is_owned(child, pin):
                raise Fault('PROCESS_OWNERSHIP_UNKNOWN', 409)
            self.after_spawn()
            persist(pin)

            for stream, name in ((child.stdout, 'stdout'), (child.stderr, 'stderr')):
                assert stream is not None
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            start = time.monotonic()
            termination, terminating_at = None, 0.0
            while selector.get_map():
                if termination is None:
                    termination = stop()
                    if time.monotonic() - start >= budget:
                        termination = 'TIMEOUT'
                    if usage() > self.staging_limit:
                        termination = 'STAGING_LIMIT'
                    if termination is not None:
                        signal_owned(child, pin, signal.SIGTERM)
                        terminating_at = time.monotonic()
                elif time.monotonic() - terminating_at >= self.grace:
                    signal_owned(child, pin, signal.SIGKILL)
                for key, _ in selector.select(0.02):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    counts[key.data] += len(chunk)
                    if counts[key.data] <= self.capture_limit:
                        self.capture_chunk(key.data, chunk)
                    if counts[key.data] > self.capture_limit and termination is None:
                        termination, terminating_at = 'CAPTURE_LIMIT', time.monotonic()
                        signal_owned(child, pin, signal.SIGTERM)
                # Pipes can close before process exit. Reap only after confirmed exit,
                # retaining the original leader PID until all group signalling is done.
                actual = incarnation(child.pid)
                if actual is None or actual != pin:
                    raise Fault('PROCESS_OWNERSHIP_UNKNOWN', 409)
            # A child may close both pipes and continue running. Bound that interval too.
            while True:
                info = Path(f'/proc/{child.pid}/stat').read_text().rsplit(')', 1)[1].split()
                if usage() > self.staging_limit and termination is None:
                    termination = 'STAGING_LIMIT'
                if info[0] == 'Z':
                    break
                reason = stop() or ('TIMEOUT' if time.monotonic() - start >= budget else None)
                if usage() > self.staging_limit:
                    reason = 'STAGING_LIMIT'
                if termination is None and reason:
                    termination, terminating_at = reason, time.monotonic()
                    signal_owned(child, pin, signal.SIGTERM)
                if termination and time.monotonic() - terminating_at >= self.grace:
                    signal_owned(child, pin, signal.SIGKILL)
                time.sleep(0.02)
            # Kill any remaining group members while the unreaped leader still proves
            # group identity. The selected wrapper must not detach/double-fork.
            signal_owned(child, pin, signal.SIGKILL)
            code = child.wait(timeout=self.grace + 1)
            if code == -signal.SIGALRM and termination is None:
                termination = 'TIMEOUT'
            observation = observed_exit(pin, code, termination, counts)
            return observation
        except Exception as error:
            # A verified exceptional stop/reap is factual exit evidence, not an
            # unknown outcome merely because output monitoring failed.
            if child is not None and pin is not None and is_owned(child, pin):
                try:
                    signal_owned(child, pin, signal.SIGKILL)
                    code = child.wait(timeout=self.grace + 1)
                    observation = observed_exit(pin, code, error.code if isinstance(error, Fault) else 'MONITOR_FAILED', counts)
                    return observation
                except BaseException:
                    pass  # Preserve the original uncertainty; do not invent an exit.
            raise
        finally:
            try:
                selector.close()
            except Exception as error:
                if observation is not None:
                    observation['cleanup_error'] = type(error).__name__
            if child is not None:
                try:
                    if pin is not None and is_owned(child, pin):
                        signal_owned(child, pin, signal.SIGKILL)
                        child.wait(timeout=self.grace + 1)
                except BaseException as error:
                    if observation is not None:
                        observation['cleanup_error'] = type(error).__name__
                finally:
                    for stream in (child.stdout, child.stderr):
                        try:
                            if stream:
                                stream.close()
                        except Exception as error:
                            if observation is not None:
                                observation['cleanup_error'] = type(error).__name__
