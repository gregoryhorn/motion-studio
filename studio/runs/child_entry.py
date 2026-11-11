"""Fixed argv-native child bootstrap: limits apply before exec in the same PID.

Only the server constructs this private vector. There is no CLI/browser route to select
an executable; the executor has already admitted and pinned the complete tool vector.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import resource
import signal
import sys

# Python -I intentionally has no application import path. Load only the sibling
# pure builder, without importing plugin registration or the host environment.
spec = importlib.util.spec_from_file_location('_motion_child_env', Path(__file__).resolve().parents[1] / 'child_env.py')
child_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(child_env)


def main():
    expected, deadline, executable, *arguments = sys.argv[1:]
    fd = os.open(executable, os.O_RDONLY)
    try:
        with os.fdopen(os.dup(fd), 'rb') as source:
            if hashlib.sha256(source.read()).hexdigest() != expected:
                return 120
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        # ITIMER_REAL survives exec in this same PID; the parent also supervises the
        # group/deadline. The fixed wrapper must not detach or replace this timer.
        signal.setitimer(signal.ITIMER_REAL, float(deadline))
        os.umask(0o077)
        # The reviewed executable may be a shebang script; no command-string shell.
        os.execve(executable, [executable, *arguments], child_env.child_environment('owned', os.environ))
    finally:
        os.close(fd)
    return 121


if __name__ == '__main__':
    sys.exit(main())
