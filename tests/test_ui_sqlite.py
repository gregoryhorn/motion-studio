"""Authored safety regressions; intentionally NOT run during source assembly."""
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from studio.contracts import ContractError
from studio.project import ManagedFS
from studio.ui_sqlite import database_backend, open_owned


def _blocked_writer(root, started, acquired, release):
    started.set()
    db = open_owned(Path(root), 'state.db')
    try:
        acquired.set()
        if not release.wait(10):
            raise RuntimeError('parent did not release writer')
        db.execute('INSERT INTO records VALUES(2)')
        db.commit()
    finally:
        db.close()


class OwnedSQLiteTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch')))
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch, prefix='owned-sqlite-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'store'

    def seed(self):
        db = open_owned(self.root, 'state.db')
        try:
            db.execute('CREATE TABLE records(value INTEGER)')
            db.execute('INSERT INTO records VALUES(1)')
            db.commit()
        finally:
            db.close()

    def values(self):
        db = open_owned(self.root, 'state.db')
        try:
            return [row[0] for row in db.execute('SELECT value FROM records ORDER BY value')]
        finally:
            db.close()

    def test_commit_rollback_close_and_reopen(self):
        self.seed()
        db = open_owned(self.root, 'state.db')
        db.execute('INSERT INTO records VALUES(2)')
        db.rollback()
        db.execute('INSERT INTO records VALUES(3)')
        db.commit()
        db.execute('INSERT INTO records VALUES(4)')
        db.close()
        db.close()
        self.assertEqual(self.values(), [1, 3])
        self.assertFalse((self.root / 'state.db-wal').exists())
        self.assertTrue((self.root / 'state.db.lock').is_file())

    def test_empty_commit_bootstraps_private_root_and_persists_without_tables(self):
        db = open_owned(self.root, 'state.db')
        try:
            db.commit()
        finally:
            db.close()
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        db = open_owned(self.root, 'state.db')
        try:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0], 0)
        finally:
            db.close()

    def test_connection_context_preserves_sqlite_commit_and_no_close_semantics(self):
        self.seed()
        db = open_owned(self.root, 'state.db')
        try:
            with db:
                db.execute('INSERT INTO records VALUES(2)')
            with self.assertRaises(ValueError):
                with db:
                    db.execute('INSERT INTO records VALUES(3)')
                    raise ValueError('rollback')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 2)
        finally:
            db.close()
        self.assertEqual(self.values(), [1, 2])

    def test_sqlite_only_connects_to_memory(self):
        real_connect = sqlite3.connect
        opened = []
        def checked(database, *args, **kwargs):
            opened.append(database)
            self.assertEqual(database, ':memory:')
            return real_connect(database, *args, **kwargs)
        with patch('studio.ui_sqlite.sqlite3.connect', side_effect=checked):
            self.seed()
            self.assertEqual(self.values(), [1])
        self.assertEqual(opened, [':memory:', ':memory:'])

    def test_backend_exception_discards_uncommitted_work(self):
        self.seed()
        fs = ManagedFS(self.root)
        with fs.directory() as directory:
            with self.assertRaises(ValueError):
                with database_backend(fs, directory, 'state.db') as db:
                    db.execute('INSERT INTO records VALUES(2)')
                    raise ValueError('caller failure')
        self.assertEqual(self.values(), [1])

    def test_replacement_or_inplace_mutation_conflicts_before_publish(self):
        self.seed()
        for replacement in (True, False):
            with self.subTest(replacement=replacement):
                db = open_owned(self.root, 'state.db')
                try:
                    db.execute('INSERT INTO records VALUES(2)')
                    target = self.root / 'state.db'
                    payload = target.read_bytes()
                    if replacement:
                        alternate = self.root / 'alternate'
                        alternate.write_bytes(payload)
                        alternate.replace(target)
                    else:
                        # Same bytes, but a changed source generation must conflict.
                        with target.open('r+b') as stream:
                            stream.write(payload)
                            stream.flush()
                            os.fsync(stream.fileno())
                    with self.assertRaises(ContractError) as caught:
                        db.commit()
                    self.assertEqual(caught.exception.code, 'REVISION_CONFLICT')
                finally:
                    db.close()
                self.assertEqual(self.values(), [1])

    def test_lock_inode_replacement_conflicts(self):
        self.seed()
        db = open_owned(self.root, 'state.db')
        try:
            db.execute('INSERT INTO records VALUES(2)')
            lock = self.root / 'state.db.lock'
            lock.unlink()
            lock.touch(mode=0o600)
            with self.assertRaises(ContractError):
                db.commit()
        finally:
            db.close()
        self.assertEqual(self.values(), [1])

    def test_database_sidecars_lock_and_ancestor_symlinks_are_refused(self):
        self.seed()
        outside = self.root.parent / 'outside'
        outside.write_bytes(b'never write here')
        original = (self.root / 'state.db').read_bytes()
        for name in ('state.db', 'state.db.lock', 'state.db-wal', 'state.db-shm', 'state.db-journal'):
            target = self.root / name
            previous = target.read_bytes() if target.exists() else None
            if target.exists():
                target.unlink()
            target.symlink_to(outside)
            try:
                with self.assertRaises((ContractError, OSError)):
                    open_owned(self.root, 'state.db')
            finally:
                target.unlink()
                if previous is not None:
                    target.write_bytes(previous)
            self.assertEqual(outside.read_bytes(), b'never write here')
        alias = self.root.parent / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((ContractError, OSError)):
            open_owned(alias, 'state.db')
        self.assertEqual((self.root / 'state.db').read_bytes(), original)

    def test_regular_wal_is_not_ignored_and_wal_header_is_not_deserialized(self):
        self.seed()
        wal = self.root / 'state.db-wal'
        wal.write_bytes(b'pending native data')
        with self.assertRaises(ContractError) as caught:
            open_owned(self.root, 'state.db')
        self.assertEqual(caught.exception.code, 'STORAGE_UNSUPPORTED')
        wal.unlink()
        target = self.root / 'state.db'
        payload = bytearray(target.read_bytes())
        payload[18:20] = b'\x02\x02'
        target.write_bytes(payload)
        with self.assertRaises(ContractError):
            open_owned(self.root, 'state.db')

    def test_bound_refuses_image_before_deserialize(self):
        self.seed()
        with patch('studio.ui_sqlite.MAX_IMAGE_BYTES', 100):
            with self.assertRaises(ContractError) as caught:
                open_owned(self.root, 'state.db')
        self.assertEqual(caught.exception.code, 'LIMIT_EXCEEDED')

    def test_atomic_publish_failure_keeps_prior_image_and_cleans_staging(self):
        self.seed()
        db = open_owned(self.root, 'state.db')
        try:
            db.execute('INSERT INTO records VALUES(2)')
            with patch('studio.ui_sqlite.os.replace', side_effect=OSError('injected rename failure')):
                with self.assertRaises(OSError):
                    db.commit()
        finally:
            db.close()
        self.assertEqual(self.values(), [1])
        self.assertEqual(list(self.root.glob('.sqlite-*.new')), [])

    def test_flock_serializes_processes_despite_unrelated_fd_close(self):
        self.seed()
        db = open_owned(self.root, 'state.db')
        context = multiprocessing.get_context('spawn')
        started, acquired, release = (context.Event() for _ in range(3))
        child = context.Process(target=_blocked_writer, args=(str(self.root), started, acquired, release))
        child.start()
        try:
            self.assertTrue(started.wait(10))
            fd = os.open(self.root / 'state.db.lock', os.O_RDONLY)
            os.close(fd)  # flock must not have POSIX record-lock close semantics.
            self.assertFalse(acquired.wait(0.2))
            db.close()
            self.assertTrue(acquired.wait(10))
            release.set()
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        finally:
            db.close()
            release.set()
            if child.is_alive():
                child.terminate()
            child.join(10)
        self.assertEqual(self.values(), [1, 2])
