"""Deterministic real-file mutation after fstat, before managed JSON read."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio.contracts import ContractError
from studio.project import ManagedFS


class MutatingReader:
    def __init__(self, stream, mutate, calls):
        self.stream, self.mutate, self.calls = stream, mutate, calls
    def __enter__(self):
        self.stream.__enter__()
        return self
    def __exit__(self, *args):
        return self.stream.__exit__(*args)
    def fileno(self):
        return self.stream.fileno()
    def read(self, size=-1):
        self.calls.append(size)
        self.mutate()
        return self.stream.read(size)


class ManagedReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'], prefix='managed-read-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'record.json'
        self.path.write_bytes(b'{"a":0}')

    def read_during(self, mutation):
        fdopen, calls = os.fdopen, []
        def opened(fd, mode):
            return MutatingReader(fdopen(fd, mode), mutation, calls)
        with patch('studio.project.os.fdopen', side_effect=opened):
            with self.assertRaises(ContractError) as caught:
                ManagedFS(self.root).read('record.json')
        return caught.exception, calls

    def test_growth_after_stat_is_bounded_and_rejected(self):
        def grow():
            with self.path.open('ab') as stream:
                stream.write(b' ' * 16777217)
        error, calls = self.read_during(grow)
        self.assertEqual(error.code, 'LIMIT_EXCEEDED')
        self.assertEqual(calls, [16777217])

    def test_same_size_mutation_after_stat_is_rejected(self):
        before = self.path.stat()
        def rewrite():
            self.path.write_bytes(b'{"a":1}')
            os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        error, calls = self.read_during(rewrite)
        self.assertEqual(error.code, 'ASSET_CHANGED')
        self.assertEqual(calls, [16777217])


if __name__ == '__main__':
    unittest.main()
