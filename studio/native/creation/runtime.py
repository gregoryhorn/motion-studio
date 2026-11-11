"""Lazy, default-denied native media association. No private host imports."""
import contextlib
import fcntl
import os
import stat
from pathlib import Path
import threading
from ...domain import Fault
from ...persistence.store import Store, identity
from ...native.creation.policy import Association, Scope


class MediaStore(Store):
    def __init__(self, home):
        self.local = threading.local()
        super().__init__(home)

    @contextlib.contextmanager
    def transaction(self):
        # Scoped service reads compose inside one SQL transaction on this thread.
        current = getattr(self.local, 'db', None)
        if current is not None:
            yield current
            return
        with super().transaction() as db:
            self.local.db = db
            try: yield db
            finally: self.local.db = None


class CreationRuntime:
    def __init__(self, ctx, association=None):
        self.ctx, self.policy = ctx, association or Association()
        self.store = self.runs = self.service = None
        self.fd = None
        self.instance = ''
        self.closed = False
        self.mutex = threading.RLock()
        self.retirement = None

    def access(self, root=None):
        if self.closed: raise Fault('CREATION_RETIRED', 409)
        self.policy.access(self.ctx.profile_name)
        if root is not None:
            return Scope(self.instance, root, self.policy.revision)

    def acquire(self):
        self.access()
        if self.service is not None: return self.service
        home = Path(self.ctx.state.data_dir) / 'media'
        if home.is_symlink() or (not home.exists() and not self.policy.create_store):
            raise Fault('CREATION_STORE_REVIEW_REQUIRED', 409)
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = home.stat()
        if home.resolve() != home.absolute() or info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISDIR(info.st_mode):
            raise Fault('CREATION_STORE_REVIEW_REQUIRED', 409)
        self.fd = os.open(home / 'service.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            try: fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise Fault('CREATION_STORE_BUSY', 409) from None
            existing_database = (home / 'state' / 'studio.db').exists()
            self.store = MediaStore(home)
            with self.store.transaction() as db:
                db.execute('CREATE TABLE IF NOT EXISTS creation_meta(instance TEXT PRIMARY KEY)')
                row = db.execute('SELECT instance FROM creation_meta').fetchone()
                if row:
                    if self.policy.instance != row[0]: raise Fault('CREATION_STORE_REVIEW_REQUIRED', 409)
                    self.instance = row[0]
                else:
                    if existing_database or not self.policy.create_store or self.policy.instance:
                        raise Fault('CREATION_STORE_REVIEW_REQUIRED', 409)
                    self.instance = identity()
                    db.execute('INSERT INTO creation_meta VALUES(?)', (self.instance,))
            from ...producer.catalog import Catalog
            from ...runs.service import LocalRuns
            from ...native.creation.admission import NativeAdmission
            from ...native.creation.service import Creations
            self.runs = LocalRuns(self.store, catalog=Catalog(declarative=False), admission_factory=NativeAdmission)
            self.service = Creations(self, self.store, self.runs)
            return self.service
        except BaseException:
            fd, self.fd = self.fd, None
            os.close(fd)
            raise

    def binding(self, kind='Sound effects'):
        if self.runs is None: raise Fault('CREATION_ACCESS_UNAVAILABLE', 403)
        if kind == 'Music':
            from ...native.creation.music import disabled_binding
            self.policy.music.access()
            policy = self.policy.music
            record = (self.runs.bindings.get(policy.binding, policy.binding_revision)
                      if policy.binding else disabled_binding(self.runs))
            if record['adapter'] != 'ace-step-local' or record['interface_version'] != 'ace-step-cue-v1':
                raise Fault('MUSIC_BINDING_DENIED', 403)
            return record
        if self.policy.binding:
            record = self.runs.bindings.get(self.policy.binding, self.policy.binding_revision)
        else:
            record = self.runs.bindings.seed(self.runs.binding)
        if record['adapter'] != 'stable-audio-local' or record['interface_version'] != 'stable-audio-cli-v1':
            raise Fault('UNSUPPORTED_OPERATION', 409)
        return record

    def unload(self):
        self.closed = True
        if self.runs is not None:
            self.runs.close()
            pending = [t for t in self.runs.threads.values() if t.is_alive()]
            if pending:
                def retire():
                    for thread in pending: thread.join()
                    self.release()
                self.retirement = threading.Thread(target=retire, daemon=True)
                self.retirement.start()
                return
        self.release()

    def release(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)  # One attempt; never release the lease while a worker survives.
