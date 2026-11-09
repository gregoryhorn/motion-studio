"""Owned SQLite image stores: SQLite's VFS only ever sees ':memory:'.

ManagedFS bootstraps missing ancestors descriptor-relatively (0700); existing
symlink ancestors are never admitted. The store directory must be host-owned
and not group/world writable. Cooperating processes retain a persistent flock
inode for the complete connection lifetime; never remove that lock file.
Existing WAL/journal stores require explicit operator migration, not silent
checkpoint loss. This is not a reader for a live native Hermes WAL registry.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import os
import secrets
import sqlite3
import stat
from typing import NoReturn

from .contracts import ContractError
from .project import ManagedFS

MAX_IMAGE_BYTES = 64 * 1024 * 1024


def _fail(code, message) -> NoReturn:
    raise ContractError(code, message)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _regular(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail('PATH_UNSAFE', 'SQLite storage must be a single-link regular file.')


def _sidecars(directory, filename):
    for suffix in ('-wal', '-shm', '-journal'):
        try:
            info = os.stat(filename + suffix, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            continue
        _regular(info)
        _fail('STORAGE_UNSUPPORTED', 'SQLite sidecars require explicit consistent migration; no WAL or journal is ignored.')


def _image(directory, filename):
    _sidecars(directory, filename)
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise ContractError('PATH_UNSAFE', 'SQLite image could not be safely admitted.') from exc
    try:
        before = os.fstat(fd)
        _regular(before)
        if before.st_size > MAX_IMAGE_BYTES:
            _fail('LIMIT_EXCEEDED', 'SQLite image exceeds its bounded store capacity.')
        chunks, remaining = [], MAX_IMAGE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b''.join(chunks)
        current = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        if (_identity(before) != _identity(os.fstat(fd)) or
                _identity(before) != _identity(current) or len(payload) != before.st_size):
            _fail('REVISION_CONFLICT', 'SQLite image changed during admission.')
        _sidecars(directory, filename)
        if payload and (len(payload) < 100 or payload[:16] != b'SQLite format 3\x00'):
            _fail('STORAGE_UNSUPPORTED', 'SQLite image header is invalid.')
        if payload and payload[18:20] != b'\x01\x01':
            _fail('STORAGE_UNSUPPORTED', 'WAL-mode SQLite images require explicit consistent migration.')
        return payload, (_identity(current), hashlib.sha256(payload).digest())
    finally:
        os.close(fd)


class OwnedConnection(sqlite3.Connection):
    """commit publishes durably; rollback/close never publish pending work.

    A failed publish must be reconciled by reopening: fsync failure after rename
    can have unknown durability. close is idempotent and always releases flock.
    Like sqlite3, connection context exit commits/rolls back but does not close.
    SQL COMMIT/END and executescript's implicit commits are memory-only until
    explicit connection.commit(); callers must use that persistence boundary.
    """
    _store: '_Store | None' = None

    def commit(self):
        super().commit()
        store = self._store
        if store is not None:
            store.publish(self.serialize())

    def close(self):
        store, self._store = self._store, None
        try:
            super().close()
        finally:
            if store is not None:
                store.close()

    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            try:
                self.commit()
            except BaseException:
                self.rollback()
                raise
        else:
            self.rollback()
        return False


class _Store:
    def __init__(self, fs, directory, filename):
        self.fs, self.filename = fs, filename
        self.directory = os.dup(directory)
        self.lock = None
        try:
            info = os.fstat(self.directory)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022):
                _fail('PATH_UNSAFE', 'SQLite store requires a host-owned non-writable-by-others directory.')
            self.directory_identity = (info.st_dev, info.st_ino)
            self.lockname = filename + '.lock'
            self.lock = os.open(self.lockname, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                0o600, dir_fd=self.directory)
            _regular(os.fstat(self.lock))
            fcntl.flock(self.lock, fcntl.LOCK_EX)
            self.check_admission()
            os.fsync(self.directory)
            self.payload, self.expected = _image(self.directory, filename)
        except BaseException:
            self.close()
            raise

    def check_admission(self):
        if self.lock is None or self.directory is None:
            _fail('STORAGE_UNSUPPORTED', 'SQLite store is closed.')
        locked = os.fstat(self.lock)
        current = os.stat(self.lockname, dir_fd=self.directory, follow_symlinks=False)
        _regular(current)
        if locked.st_nlink != 1 or (locked.st_dev, locked.st_ino) != (current.st_dev, current.st_ino):
            _fail('REVISION_CONFLICT', 'SQLite persistent lock inode changed.')
        with self.fs.directory() as directory:
            info = os.fstat(directory)
            if self.directory_identity != (info.st_dev, info.st_ino):
                _fail('REVISION_CONFLICT', 'SQLite admitted directory changed.')

    def publish(self, payload):
        if self.directory is None:
            _fail('STORAGE_UNSUPPORTED', 'SQLite store is closed.')
        if len(payload) > MAX_IMAGE_BYTES:
            _fail('LIMIT_EXCEEDED', 'SQLite image exceeds its bounded store capacity.')
        self.check_admission()
        _, observed = _image(self.directory, self.filename)
        if observed != self.expected:
            _fail('REVISION_CONFLICT', 'SQLite image changed outside the owned store.')
        temporary = '.sqlite-' + secrets.token_hex(16) + '.new'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self.check_admission()
            _, observed = _image(self.directory, self.filename)
            if observed != self.expected:
                _fail('REVISION_CONFLICT', 'SQLite image changed before publication.')
            os.replace(temporary, self.filename, src_dir_fd=self.directory, dst_dir_fd=self.directory)
            os.fsync(self.directory)
            published, expected = _image(self.directory, self.filename)
            if published != payload:
                _fail('REVISION_CONFLICT', 'SQLite publication was replaced by another writer.')
            self.expected = expected
        finally:
            try:
                os.unlink(temporary, dir_fd=self.directory)
            except FileNotFoundError:
                pass

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.directory is not None:
            os.close(self.directory)
            self.directory = None


def connect_owned(managed_fs, admitted_directory_fd, filename):
    """Return an owned connection; caller MUST close, even after commit failure."""
    if not isinstance(filename, str) or not filename or '/' in filename or filename in ('.', '..') or '\x00' in filename:
        _fail('PATH_UNSAFE', 'SQLite store filename must be one literal component.')
    store = _Store(managed_fs, admitted_directory_fd, filename)
    db = None
    try:
        db = sqlite3.connect(':memory:', factory=OwnedConnection)
        if not hasattr(db, 'deserialize') or not hasattr(db, 'serialize'):
            _fail('STORAGE_UNSUPPORTED', 'SQLite serialize/deserialize support is required.')
        if store.payload:
            db.deserialize(store.payload)
        else:
            # Materialize page one so even an otherwise-empty commit serializes.
            db.execute('PRAGMA user_version=0')
        db.execute('PRAGMA journal_mode=MEMORY')
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA foreign_keys=ON')
        db.row_factory = sqlite3.Row
        db._store = store
        return db
    except BaseException:
        if db is not None:
            db.close()
        store.close()
        raise


@contextmanager
def database_backend(managed_fs, admitted_directory_fd, filename):
    """Media/broker hook: successful exit commits; error rolls back; always close."""
    db = connect_owned(managed_fs, admitted_directory_fd, filename)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def open_owned(root, filename):
    """Bootstrap missing directories securely, retaining a duplicate admitted fd."""
    fs = ManagedFS(root)
    with fs.directory(create=True) as directory:
        return connect_owned(fs, directory, filename)
