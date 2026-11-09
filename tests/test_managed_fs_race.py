"""MS-I021: deterministic actual managed publication, no inference or stress loop."""
import copy
import errno
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from studio.contracts import ContractError
from studio.project import ManagedFS, ProjectStore


class ManagedRecordRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fs = ManagedFS(self.root)

    def interleave(self, relative, publish, read):
        """Publish on a real writer thread between the reader's real fstats.

        No read bytes, stat results, JSON, errors or managed methods are mocked.
        The fstat wrapper is only a deterministic scheduling barrier.
        """
        target = (self.root / relative).stat()
        real_fstat = os.fstat
        seen, evidence, errors = [], {}, []

        def scheduled_fstat(fd):
            value = real_fstat(fd)
            if (value.st_dev, value.st_ino) == (target.st_dev, target.st_ino):
                seen.append(value)
                if len(seen) == 2:
                    def writer():
                        try:
                            publish()
                        except BaseException as exc:
                            errors.append(exc)
                    thread = threading.Thread(target=writer, name='msi021-owned-publisher')
                    thread.start()
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive(), 'owned publication did not finish')
                    if errors:
                        raise errors[0]
                    value = real_fstat(fd)
                    evidence.update(before=seen[0], after=value)
            return value

        with patch('studio.project.os.fstat', side_effect=scheduled_fstat):
            result = read()
        self.assertEqual(len(seen), 2)
        return result, evidence

    def test_atomic_replace_during_managed_read_is_complete_snapshot(self):
        old, new = {'revision': 1, 'payload': 'old'}, {'revision': 2, 'payload': 'new'}
        self.fs.write('record.json', old)
        result, evidence = self.interleave('record.json',
            lambda: self.fs.write('record.json', new, replace=True),
            lambda: self.fs.read('record.json'))
        self.assertIn(result, (old, new))
        before, after = evidence['before'], evidence['after']
        self.assertEqual((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
                         (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual((before.st_nlink, after.st_nlink), (1, 0))
        self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
        self.assertEqual(self.fs.read('record.json'), new)

    def job_fixture(self):
        from studio.jobs import JobStore
        from test_jobs import FixtureAuthority, LocalAdapter, fixture_plan
        projects = ProjectStore(self.root)
        pid = projects.dispatch(dict(action='create', request_id=str(uuid.uuid4()), name='MS-I021'))['project_id']
        plan = fixture_plan(pid)
        store = JobStore(projects, plan_reader=lambda *_: copy.deepcopy(plan),
                         authority=FixtureAuthority(), adapter_resolver=lambda _: LocalAdapter())
        submitted = store.submit(dict(action='submit', project_id=pid, expected_revision=1,
            request_id=str(uuid.uuid4()), plan={k: plan[k] for k in ('plan_id', 'plan_revision', 'plan_sha256')}))
        jid = submitted['job']['job_id']
        return store, pid, jid

    def test_job_commit_during_job_read_retains_coherent_revision(self):
        store, pid, jid = self.job_fixture()
        old = store.read(pid, jid)
        new = copy.deepcopy(old)
        new['monitoring']['publication_marker'] = 'next revision only'
        result, _ = self.interleave(store.path(pid, jid),
            lambda: store._commit(self.fs, new), lambda: store.read(pid, jid))
        self.assertIn(result, (old, new))
        self.assertEqual(new['job']['job_revision'], old['job']['job_revision'] + 1)
        self.assertEqual(store.read(pid, jid), new)

    def test_atomic_replacement_does_not_bypass_job_ownership(self):
        store, pid, jid = self.job_fixture()
        foreign = copy.deepcopy(store.read(pid, jid))
        foreign['job']['project_id'] = 'prj_' + str(uuid.uuid4())
        # Force retry to the newly published inode. Returning the valid old
        # snapshot is also coherent, so ownership is checked on a fresh read.
        self.fs.write(store.path(pid, jid), foreign, replace=True)
        with self.assertRaises(ContractError) as cm:
            store.read(pid, jid)
        self.assertEqual(cm.exception.code, 'HASH_MISMATCH')

    def test_same_inode_edit_with_restored_mtime_is_still_rejected(self):
        self.fs.write('record.json', {'value': 'old'})
        original = (self.root / 'record.json').stat()
        def mutate():
            (self.root / 'record.json').write_bytes(b'{"value":"new"}')
            os.utime(self.root / 'record.json', ns=(original.st_atime_ns, original.st_mtime_ns))
        with self.assertRaises(ContractError) as cm:
            self.interleave('record.json', mutate, lambda: self.fs.read('record.json'))
        self.assertEqual(cm.exception.code, 'ASSET_CHANGED')

    def test_same_inode_metadata_change_is_still_rejected(self):
        self.fs.write('record.json', {'value': 'old'})
        with self.assertRaises(ContractError) as cm:
            self.interleave('record.json', lambda: (self.root / 'record.json').chmod(0o400),
                            lambda: self.fs.read('record.json'))
        self.assertEqual(cm.exception.code, 'ASSET_CHANGED')

    def test_symlink_published_during_read_is_not_followed(self):
        self.fs.write('record.json', {'value': 'old'})
        self.fs.write('outside.json', {'value': 'outside'})
        def publish_link():
            (self.root / 'record.json').unlink()
            (self.root / 'record.json').symlink_to(self.root / 'outside.json')
        with self.assertRaises(ContractError) as cm:
            self.interleave('record.json', publish_link, lambda: self.fs.read('record.json'))
        self.assertEqual(cm.exception.code, 'ASSET_CHANGED')

    def test_continuous_replacement_has_bounded_failure_not_busy_loop(self):
        self.fs.write('record.json', {'revision': 0})
        real_fstat, reads, publications = os.fstat, [], []
        def scheduled_fstat(fd):
            value = real_fstat(fd)
            reads.append(value)
            if len(reads) % 2 == 0:
                # Same causal interleaving on every reopened file; exactly
                # bounded, not a probabilistic stress run.
                publications.append(len(publications) + 1)
                self.fs.write('record.json', {'revision': len(publications)}, replace=True)
                return real_fstat(fd)
            self.assertLessEqual(len(publications), 3, 'read retry bound exceeded')
            return value
        with patch('studio.project.os.fstat', side_effect=scheduled_fstat):
            with self.assertRaises(ContractError) as cm:
                self.fs.read('record.json')
        self.assertEqual(cm.exception.code, 'ASSET_CHANGED')
        self.assertLessEqual(len(publications), 3)

    def test_symlink_leaf_and_ancestor_are_not_followed(self):
        self.fs.write('safe/record.json', {'value': 'old'})
        (self.root / 'leaf.json').symlink_to(self.root / 'safe/record.json')
        (self.root / 'ancestor').symlink_to(self.root / 'safe', target_is_directory=True)
        for relative in ('leaf.json', 'ancestor/record.json'):
            with self.subTest(relative=relative), self.assertRaises(OSError) as cm:
                self.fs.read(relative)
            self.assertIn(cm.exception.errno, (errno.ELOOP, errno.ENOTDIR))

    def test_nonregular_and_oversized_records_stay_rejected(self):
        os.mkfifo(self.root / 'fifo')
        with self.assertRaises(ContractError) as cm:
            self.fs.read('fifo')
        self.assertEqual(cm.exception.code, 'PATH_UNSAFE')
        with (self.root / 'large.json').open('wb') as stream:
            stream.truncate(16777217)
        with self.assertRaises(ContractError) as cm:
            self.fs.read('large.json')
        self.assertEqual(cm.exception.code, 'LIMIT_EXCEEDED')

    def test_immutable_project_snapshot_pin_is_still_verified(self):
        projects = ProjectStore(self.root)
        pid = projects.dispatch(dict(action='create', request_id=str(uuid.uuid4()), name='pin guard'))['project_id']
        pointer = projects._pointer(self.fs, pid)
        altered = copy.deepcopy(pointer)
        altered['snapshot_sha256'] = 'sha256:' + '0' * 64
        with self.assertRaises(ContractError) as cm:
            projects._load(self.fs, altered)
        self.assertEqual(cm.exception.code, 'HASH_MISMATCH')
