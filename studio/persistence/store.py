"""SQLite authority for requests, revisions, command receipts and imports."""
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import time
from ..domain import Fault, opaque
from ..persistence.primitives import canonical, identity


class Store:
    def __init__(self, home):
        self.home = Path(home).absolute()
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.home.is_symlink():
            raise Fault("UNSAFE_STATE_HOME")
        for part in ("state", "media", "staging"):
            path = self.home / part
            path.mkdir(mode=0o700, exist_ok=True)
            if path.is_symlink():
                raise Fault("UNSAFE_STATE_HOME")
        self.database = self.home / "state" / "studio.db"
        if self.database.is_symlink():
            raise Fault("UNSAFE_STATE_HOME")
        with self.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, revision INTEGER,
                text TEXT, kind TEXT, purpose TEXT, created REAL, updated REAL,
                selected TEXT);
            CREATE TABLE IF NOT EXISTS receipts(command TEXT PRIMARY KEY, payload TEXT,
                result TEXT);
            CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, request TEXT,
                revision INTEGER, digest TEXT, size INTEGER, name TEXT, status TEXT,
                error TEXT, take TEXT);
            CREATE TABLE IF NOT EXISTS takes(id TEXT PRIMARY KEY, artifact TEXT UNIQUE,
                import_id TEXT UNIQUE, request TEXT, revision INTEGER, digest TEXT,
                size INTEGER, name TEXT, facts TEXT, review TEXT, origin TEXT);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT,
                expires REAL);
            """)
            from ..director.review.reports import initialize
            from ..director.state.removal import initialize as initialize_removal
            initialize(db)
            initialize_removal(db)
        os.chmod(self.database, 0o600)

    @contextlib.contextmanager
    def transaction(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def command(self, db, command, payload, operation):
        opaque(command)
        encoded = canonical(payload)
        row = db.execute("SELECT * FROM receipts WHERE command=?", (command,)).fetchone()
        if row:
            if row["payload"] != encoded:
                raise Fault("COMMAND_CONFLICT", 409)
            return json.loads(row["result"])
        result = operation()
        db.execute("INSERT INTO receipts VALUES(?,?,?)", (command, encoded, canonical(result)))
        return result

    def request(self, db, request, revision=None):
        row = db.execute("SELECT * FROM requests WHERE id=?", (opaque(request),)).fetchone()
        if not row:
            raise Fault("REQUEST_NOT_FOUND", 404)
        if revision is not None and row["revision"] != revision:
            raise Fault("STALE_REVISION", 409)
        return row

    def save(self, model):
        payload = {"operation": "save", **model.model_dump()}
        with self.transaction() as db:
            def operation():
                now = time.time()
                if model.id:
                    row = self.request(db, model.id, model.expected)
                    revision = row["revision"] + 1
                    db.execute("UPDATE requests SET revision=?,text=?,kind=?,purpose=?,updated=? WHERE id=?",
                               (revision, model.text, model.kind, model.purpose, now, model.id))
                    return {"id": model.id, "revision": revision}
                if model.expected != 0:
                    raise Fault("STALE_REVISION", 409)
                request = identity()
                db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?,?,NULL)",
                           (request, 1, model.text, model.kind, model.purpose, now, now))
                return {"id": request, "revision": 1}
            return self.command(db, model.command, payload, operation)

    def snapshot(self):
        with self.transaction() as db:
            requests = [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY created DESC")]
            takes = [dict(r) for r in db.execute("SELECT * FROM takes ORDER BY rowid DESC")]
            from ..director.state.removal import visible
            from ..director.review.reports import status
            takes = [take for take in takes if visible(db, take['id'])]
            for take in takes:
                take['check'] = status(db, take)
            imports = [dict(r) for r in db.execute("SELECT * FROM imports ORDER BY rowid DESC")]
        for take in takes:
            take["facts"] = json.loads(take["facts"])
            take["rights"] = "Usage rights not verified"
            take["technical"] = 'Crystal Ball: ' + take['check']['status']
        return dict(requests=requests, takes=takes, imports=imports)

    def take(self, db, take):
        row = db.execute("SELECT * FROM takes WHERE id=?", (opaque(take),)).fetchone()
        if not row:
            raise Fault("TAKE_NOT_FOUND", 404)
        return row

    def review(self, model):
        with self.transaction() as db:
            def operation():
                self.take(db, model.take)
                db.execute("UPDATE takes SET review=? WHERE id=?", (model.outcome, model.take))
                return {"take": model.take, "review": model.outcome}
            return self.command(db, model.command, {"operation": "review", **model.model_dump()}, operation)

    def select(self, model):
        with self.transaction() as db:
            def operation():
                row = self.request(db, model.request, model.expected)
                take = self.take(db, model.take)
                from ..director.state.removal import visible
                if not visible(db, model.take):
                    raise Fault('DIRECTOR_TAKE_REMOVED', 409)
                if take["request"] != model.request:
                    raise Fault("TAKE_SCOPE_MISMATCH", 403)
                revision = row["revision"] + 1
                db.execute("UPDATE requests SET selected=?,revision=?,updated=? WHERE id=?",
                           (model.take, revision, time.time(), model.request))
                return {"id": model.request, "revision": revision}
            return self.command(db, model.command, {"operation": "select", **model.model_dump()}, operation)
