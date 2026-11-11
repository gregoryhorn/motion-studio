"""Linux cooperative store lease, independent of host/private workspace identity."""
import contextlib
import fcntl
import os
from pathlib import Path
import sqlite3
from ...domain import Fault
from ...persistence.primitives import identity


class TechnicalStore:
    def __init__(self, data_dir, *, expected_instance='', create=False):
        self.home = Path(data_dir)/'technical-proposals'
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.home.is_symlink(): raise Fault('TECHNICAL_STORE_UNAVAILABLE', 409)
        self.database = self.home/'records.sqlite3'
        if self.database.is_symlink(): raise Fault('TECHNICAL_STORE_UNAVAILABLE', 409)
        self.fd = os.open(self.home/'service.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600)
        self.held = False
        self.generation = None
        try:
            try: fcntl.flock(self.fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise Fault('TECHNICAL_STORE_BUSY', 409) from None
            self.held = True
            with self.transaction() as db:
                db.execute('CREATE TABLE IF NOT EXISTS technical_owner(instance TEXT, generation INTEGER)')
                row = db.execute('SELECT * FROM technical_owner').fetchone()
                if row:
                    if expected_instance != row['instance']: raise Fault('TECHNICAL_STORE_REVIEW_REQUIRED', 409)
                    self.instance, generation = row['instance'], row['generation']+1
                    db.execute('UPDATE technical_owner SET generation=?', (generation,))
                else:
                    if not create or expected_instance: raise Fault('TECHNICAL_STORE_REVIEW_REQUIRED', 409)
                    self.instance, generation = identity(), 1
                    db.execute('INSERT INTO technical_owner VALUES(?,?)', (self.instance, generation))
            self.generation = generation
            os.chmod(self.database, 0o600)
        except BaseException:
            self.close()
            raise

    @contextlib.contextmanager
    def transaction(self):
        if not self.held: raise Fault('TECHNICAL_SERVICE_RETIRED', 409)
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            if self.generation is not None:
                row = db.execute('SELECT * FROM technical_owner').fetchone()
                if not row or row['instance'] != self.instance or row['generation'] != self.generation:
                    raise Fault('TECHNICAL_SERVICE_RETIRED', 409)
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally: db.close()

    def close(self):
        if self.fd is not None:
            self.held = False
            fd, self.fd = self.fd, None
            os.close(fd)  # One close attempt, no PID guesses or lease stealing.
