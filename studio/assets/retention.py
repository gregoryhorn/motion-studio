"""Immutable media retention and reconciliation by original import identity."""
import hashlib
import json
import os
import stat
import threading
from ..assets.wav import inspect_wav
from ..domain import Fault, opaque
from ..persistence.store import identity, canonical


def read_private(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise OSError('Unsafe media file')
        return source.read(16 * 1024 * 1024 + 1)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Assets:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.after_finalize = lambda: None
        self.recover()

    def path(self, area, import_id, suffix):
        return self.store.home / area / (opaque(import_id) + suffix)

    def intent(self, model):
        with self.store.transaction() as db:
            def operation():
                row = self.store.request(db, model.request, model.revision)
                if row["kind"] not in ("Sound effects", "Music", "Voice"):
                    raise Fault("IMPORT_NOT_SUPPORTED")
                import_id, take = identity(), identity()
                db.execute("INSERT INTO imports VALUES(?,?,?,?,?,?,?,?,?)",
                           (import_id, model.request, model.revision, model.digest,
                            model.size, model.name, "Receiving", None, take))
                return {"id": import_id, "take": take}
            return self.store.command(db, model.command,
                                      {"operation": "import", **model.model_dump()}, operation)

    def get(self, db, import_id):
        row = db.execute("SELECT * FROM imports WHERE id=?", (opaque(import_id),)).fetchone()
        if not row:
            raise Fault("IMPORT_NOT_FOUND", 404)
        return row

    def upload(self, import_id, data):
        with self.lock:
            with self.store.transaction() as db:
                row = self.get(db, import_id)
                if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["digest"]:
                    raise Fault("IMPORT_BYTES_CONFLICT", 409)
                if row["status"] == "Ready for review":
                    return {"id": import_id, "take": row["take"], "status": row["status"]}
                if row["status"] == "Cancelled":
                    raise Fault("IMPORT_CANCELLED", 409)
            stage = self.path("staging", import_id, ".complete")
            final = self.path("media", import_id, ".wav")
            if not stage.exists() and not final.exists():
                part = self.path("staging", import_id, "." + identity() + ".part")
                with part.open("xb") as target:
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                os.link(part, stage, follow_symlinks=False)
                sync_directory(stage.parent)
            with self.store.transaction() as db:
                db.execute("UPDATE imports SET status='Checking',error=NULL WHERE id=?", (import_id,))
            return self.finish(import_id)

    def finish(self, import_id):
        with self.lock:
            try:
                with self.store.transaction() as db:
                    row = self.get(db, import_id)
                    if row["status"] == "Cancelled":
                        return {"id": import_id, "status": "Cancelled"}
                    final = self.path("media", import_id, ".wav")
                    stage = self.path("staging", import_id, ".complete")
                    data = read_private(final if final.exists() else stage)
                    if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["digest"]:
                        raise Fault("IMPORT_BYTES_CONFLICT", 409)
                    facts = inspect_wav(data)
                    if not final.exists():
                        os.link(stage, final, follow_symlinks=False)
                        os.chmod(final, 0o400)
                        sync_directory(final.parent)
                    self.after_finalize()
                    db.execute("""INSERT OR IGNORE INTO takes VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                               (row["take"], import_id, import_id, row["request"], row["revision"],
                                row["digest"], row["size"], row["name"], canonical(facts),
                                "Not reviewed", "user_import"))
                    db.execute("UPDATE imports SET status='Ready for review',error=NULL WHERE id=?", (import_id,))
                    return {"id": import_id, "take": row["take"], "status": "Ready for review"}
            except (Fault, OSError) as error:
                code = error.code if isinstance(error, Fault) else "STORAGE_UNAVAILABLE"
                with self.store.transaction() as db:
                    db.execute("UPDATE imports SET status='Failed',error=? WHERE id=?", (code, import_id))
                raise Fault(code)

    def cancel(self, import_id):
        with self.lock, self.store.transaction() as db:
            row = self.get(db, import_id)
            status = row["status"]
            if status != "Ready for review":
                status = "Cancelled"
                db.execute("UPDATE imports SET status=? WHERE id=?", (status, import_id))
            return {"id": import_id, "status": status}

    def recover(self):
        with self.store.transaction() as db:
            rows = list(db.execute("SELECT * FROM imports WHERE status IN ('Receiving','Checking','Interrupted')"))
        for row in rows:
            complete = self.path("staging", row["id"], ".complete")
            final = self.path("media", row["id"], ".wav")
            if complete.exists() or final.exists():
                try:
                    self.finish(row["id"])
                except Fault:
                    pass
            else:
                with self.store.transaction() as db:
                    db.execute("UPDATE imports SET status='Interrupted' WHERE id=?", (row["id"],))

    def retrieve(self, take):
        with self.store.transaction() as db:
            row = dict(self.store.take(db, take))
        facts = json.loads(row['facts'])
        suffix = '.original' if facts.get('storage') == 'original-v1' else '.wav'
        try:
            data = read_private(self.path("media", row["artifact"], suffix))
        except OSError:
            raise Fault("RETAINED_FILE_MISSING", 409) from None
        if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["digest"]:
            raise Fault("RETAINED_FILE_CORRUPT", 409)
        lineage = json.loads(row['facts']).get('lineage')
        if lineage:
            try:
                native = read_private(self.path('media', row['artifact'], '.native.wav'))
                if (len(native) != lineage['native']['bytes'] or
                        hashlib.sha256(native).hexdigest() != lineage['native']['sha256']):
                    raise Fault('RETAINED_NATIVE_CORRUPT', 409)
            except OSError:
                raise Fault('RETAINED_NATIVE_MISSING', 409) from None
        voice = facts.get('voice_lineage')
        if voice:
            try:
                native = read_private(self.path('media', row['artifact'], '.voice-source'))
            except OSError:
                raise Fault('RETAINED_NATIVE_MISSING', 409) from None
            if len(native) != voice['native']['bytes'] or hashlib.sha256(native).hexdigest() != voice['native']['sha256']:
                raise Fault('RETAINED_NATIVE_CORRUPT', 409)
        return data, row
