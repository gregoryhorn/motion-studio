"""Bounded environment probe for the installed AnyIO cross-thread portal.

An empty portal reproduces the host dependency hang without application code.
Only HTTP tests skip when that probe times out; no application guard is mocked.
"""
from functools import lru_cache
import subprocess
import sys
import unittest
from fastapi.testclient import TestClient as FastAPITestClient


@lru_cache(maxsize=1)
def portal_available():
    code = ('from anyio.from_thread import start_blocking_portal\n'
            'with start_blocking_portal() as portal:\n'
            '    assert portal.call(lambda: True)\n')
    try:
        result = subprocess.run([sys.executable, '-c', code],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=5, check=False)
    except subprocess.TimeoutExpired:
        return False
    if result.returncode:
        raise RuntimeError('Installed AnyIO portal environment probe failed')
    return True


class TestClient(FastAPITestClient):
    def __init__(self, *args, **kwargs):
        if not portal_available():
            raise unittest.SkipTest(
                'Environment: installed AnyIO cross-thread portal hangs on an empty app (5s probe)')
        super().__init__(*args, **kwargs)
