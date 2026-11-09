"""Scoped native Project file handles; never accept renderer filesystem paths.

Directory browsing performs no import, probing, subprocess or media generation.
Handles are server-owned, short-lived, root-revision-bound and Project-scoped.
The HTTP layer must retain the host's authentication for every binary request.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import threading
import time

from .contracts import ContractError
from .project import ManagedFS

MEDIA_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".mxf", ".m4v", ".mts",
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff",
    ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".exr", ".bmp",
    ".srt", ".vtt", ".ass", ".ttf", ".otf"})


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _identity(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


class UIFileBroker:
    def __init__(self, root, native_registry, *, clock=time.time):
        self.root = Path(root)
        self.native_registry = native_registry
        self.clock = clock
        self._lock = threading.RLock()

    @contextmanager
    def _database(self):
        fs = ManagedFS(self.root)
        from .ui_sqlite import database_backend
        with self._lock, fs.directory(create=True) as directory:
            with database_backend(fs, directory, "file-handles.sqlite3") as db:
                db.execute("""CREATE TABLE IF NOT EXISTS nodes(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    root_id TEXT NOT NULL, root_revision TEXT NOT NULL,
                    relative TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    expires REAL NOT NULL)""")
                db.execute("CREATE INDEX IF NOT EXISTS nodes_scope ON nodes(project_id,root_id)")
                db.execute("DELETE FROM nodes WHERE expires < ?", (self.clock(),))
                yield db

    def _project(self, project_id, *, writable=False):
        project = next((p for p in self.native_registry() if p.get("id") == project_id), None)
        if project is None:
            raise ContractError("NOT_FOUND", "Hermes Project is unavailable.")
        if writable and project.get("archived"):
            raise ContractError("PROJECT_ARCHIVED", "Restore this Hermes Project before importing.")
        return project

    def _roots(self, project_id):
        project = self._project(project_id)
        roots = []
        for folder in project.get("folders", []):
            raw_path = folder.get("path") if isinstance(folder, dict) else folder
            if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                continue
            path = Path(raw_path)
            # Path hash is an opaque lookup key, never an admission credential.
            root_id = "root_" + _hash([project_id, str(path)])[:32]
            try:
                with ManagedFS(path).directory() as fd:
                    root_stat = os.fstat(fd)
                available = True
                identity = [root_stat.st_dev, root_stat.st_ino]
            except (OSError, ContractError):
                available, identity = False, None
            revision = _hash([project_id, project.get("archived", False),
                              project.get("folders", []), str(path), identity])
            label = folder.get("label") if isinstance(folder, dict) else None
            roots.append({"root_id": root_id, "revision": revision,
                          "name": label or path.name or "Project folder", "path": path,
                          "available": available, "identity": identity,
                          "primary": bool(isinstance(folder, dict) and folder.get("is_primary"))})
        return roots

    def roots(self, project_id):
        roots = self._roots(project_id)
        return {"items": [{"root_id": r["root_id"], "name": r["name"],
                           "root_revision": r["revision"], "available": r["available"],
                           "primary": r["primary"], "reason": None if r["available"] else "ROOT_UNAVAILABLE"}
                          for r in roots],
                "next_cursor": None, "has_more": False, "total": len(roots),
                "snapshot_id": "roots_" + _hash([r["revision"] for r in roots])[:32]}

    def _root(self, project_id, root_id, revision):
        root = next((r for r in self._roots(project_id) if r["root_id"] == root_id), None)
        if root is None:
            raise ContractError("NOT_FOUND", "Project folder is unavailable.")
        if root["revision"] != revision:
            raise ContractError("ROOT_CHANGED", "Project folder membership changed. Refresh folders.")
        if not root["available"]:
            raise ContractError("ROOT_UNAVAILABLE", "Project folder is unavailable on the execution host.")
        return root

    @contextmanager
    def _directory(self, root, relative=""):
        """Bind admission to the descriptor actually used for traversal.

        A revision describes a root inode, not whichever directory later appears
        at its pathname. Descendants are opened relative to this verified root.
        """
        parts = relative.split("/") if relative else []
        if any(part in {"", ".", ".."} for part in parts) or relative.startswith("/"):
            raise ContractError("PATH_UNSAFE", "Invalid stored folder selection.")
        with ManagedFS(root["path"]).directory() as root_fd:
            info = os.fstat(root_fd)
            if [info.st_dev, info.st_ino] != root["identity"]:
                raise ContractError("ROOT_CHANGED", "Project folder changed. Refresh folders.")
            opened = []
            current = root_fd
            try:
                for part in parts:
                    current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=current)
                    opened.append(current)
                yield current
            finally:
                for fd in reversed(opened):
                    os.close(fd)

    def _node(self, db, project_id, root, node_id):
        row = db.execute("SELECT * FROM nodes WHERE id=? AND project_id=? AND root_id=?",
                         (node_id, project_id, root["root_id"])).fetchone()
        if row is None:
            raise ContractError("NODE_EXPIRED", "File selection expired. Refresh this folder.")
        if row["expires"] < self.clock() or row["root_revision"] != root["revision"]:
            raise ContractError("NODE_EXPIRED", "File selection expired. Refresh this folder.")
        return row

    def browse(self, project_id, root_id, *, expected_root_revision,
               parent_node_id=None, kind_filter="all", limit=50, cursor=None):
        if kind_filter not in {"all", "media", "directory"}:
            raise ContractError("INVALID_ARGUMENT", "Unsupported folder filter.")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ContractError("INVALID_ARGUMENT", "Folder page size must be 1-200.")
        if cursor is not None:
            return self.browse_next(project_id, root_id,
                                    expected_root_revision=expected_root_revision,
                                    cursor=cursor, parent_node_id=parent_node_id,
                                    kind_filter=kind_filter, limit=limit)
        root = self._root(project_id, root_id, expected_root_revision)
        with self._database() as db:
            parent = None if parent_node_id is None else self._node(db, project_id, root, parent_node_id)
            relative = "" if parent is None else parent["relative"]
            with self._directory(root, relative) as fd:
                before = _identity(os.fstat(fd))
                if parent is not None and _hash(before) != parent["fingerprint"]:
                    raise ContractError("ASSET_CHANGED", "Selected folder changed. Refresh the selection.")
                entries = []
                with os.scandir(fd) as iterator:
                    for entry in iterator:
                        if len(entries) >= 10000:
                            raise ContractError("LIMIT_EXCEEDED", "Folder exceeds the 10,000-entry snapshot bound. Use a narrower folder.")
                        if entry.is_symlink():
                            # Still visible, never traversable/importable.
                            info = entry.stat(follow_symlinks=False)
                            kind = "symlink"
                        else:
                            info = entry.stat(follow_symlinks=False)
                            kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "unsupported"
                        entries.append((entry.name, kind, info))
                if before != _identity(os.fstat(fd)):
                    raise ContractError("ROOT_CHANGED", "Folder changed while listing. Refresh it.")
            entries.sort(key=lambda item: (item[1] != "directory", item[0].casefold(), item[0]))
            projected = []
            expires = self.clock() + 900
            for name, kind, info in entries:
                supported = kind == "file" and Path(name).suffix.lower() in MEDIA_EXTENSIONS
                if kind_filter == "directory" and kind != "directory":
                    continue
                if kind_filter == "media" and kind != "directory" and not supported:
                    continue
                rel = str(Path(relative) / name) if relative else name
                fingerprint = _hash(_identity(info))
                node_id = "node_" + secrets.token_hex(16)
                db.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?)",
                           (node_id, project_id, root_id, root["revision"], rel, fingerprint, expires))
                projected.append({"node_id": node_id, "parent_node_id": parent_node_id,
                                  "name": name, "relative_display_path": rel, "kind": kind,
                                  "byte_length": info.st_size if kind == "file" else None,
                                  "mtime_token": fingerprint, "importable": supported,
                                  "hidden": any(part.startswith(".") for part in Path(rel).parts),
                                  "reason": None if supported or kind == "directory" else
                                  "SYMLINK_DENIED" if kind == "symlink" else "UNSUPPORTED_MEDIA"})
            # Never label a truncated folder complete. Pagination snapshots are
            # immutable scoped records, not offsets into a freshly scanned tree.
            snapshot_id = "listing_" + secrets.token_hex(16)
            db.execute("""CREATE TABLE IF NOT EXISTS listings(
                id TEXT PRIMARY KEY, project_id TEXT, root_id TEXT, root_revision TEXT,
                parent_id TEXT, filter TEXT, entries TEXT, expires REAL)""")
            db.execute("INSERT INTO listings VALUES(?,?,?,?,?,?,?,?)",
                       (snapshot_id, project_id, root_id, root["revision"], parent_node_id,
                        kind_filter, json.dumps(projected), expires))
            return self._page(db, snapshot_id, projected, 0, limit, root["revision"])

    def _page(self, db, snapshot_id, entries, offset, limit, revision):
        end = min(len(entries), offset + limit)
        next_cursor = None
        if end < len(entries):
            next_cursor = "cursor_" + secrets.token_hex(16)
            db.execute("""CREATE TABLE IF NOT EXISTS file_cursors(
                id TEXT PRIMARY KEY, snapshot_id TEXT, offset INTEGER, expires REAL)""")
            db.execute("INSERT INTO file_cursors VALUES(?,?,?,?)",
                       (next_cursor, snapshot_id, end, self.clock() + 900))
        return {"items": entries[offset:end], "next_cursor": next_cursor,
                "has_more": next_cursor is not None, "snapshot_id": snapshot_id,
                "total": len(entries), "root_revision": revision}

    def browse_next(self, project_id, root_id, *, expected_root_revision, cursor,
                    parent_node_id=None, kind_filter="all", limit=50):
        self._root(project_id, root_id, expected_root_revision)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ContractError("INVALID_ARGUMENT", "Folder page size must be 1-200.")
        with self._database() as db:
            db.execute("CREATE TABLE IF NOT EXISTS file_cursors(id TEXT PRIMARY KEY,snapshot_id TEXT,offset INTEGER,expires REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS listings(id TEXT PRIMARY KEY,project_id TEXT,root_id TEXT,root_revision TEXT,parent_id TEXT,filter TEXT,entries TEXT,expires REAL)")
            row = db.execute("SELECT * FROM file_cursors WHERE id=?", (cursor,)).fetchone()
            listing = None if row is None else db.execute("SELECT * FROM listings WHERE id=?", (row["snapshot_id"],)).fetchone()
            if row is None or listing is None or min(row["expires"], listing["expires"]) < self.clock():
                raise ContractError("CURSOR_EXPIRED", "Folder snapshot expired. Refresh it.")
            if (listing["project_id"], listing["root_id"], listing["root_revision"], listing["parent_id"], listing["filter"]) != (
                    project_id, root_id, expected_root_revision, parent_node_id, kind_filter):
                raise ContractError("CURSOR_EXPIRED", "Folder snapshot does not match this selection.")
            return self._page(db, listing["id"], json.loads(listing["entries"]), row["offset"], limit, expected_root_revision)

    @contextmanager
    def open_node(self, project_id, root_id, node_id, expected_root_revision, *, expected_mtime_token=None):
        root = self._root(project_id, root_id, expected_root_revision)
        with self._database() as db:
            row = self._node(db, project_id, root, node_id)
            relative = row["relative"]
            expected = row["fingerprint"]
        if expected_mtime_token is not None and expected_mtime_token != expected:
            raise ContractError("ASSET_CHANGED", "Selected source changed. Refresh the selection.")
        parent, _, leaf = relative.rpartition("/")
        if Path(leaf).suffix.lower() not in MEDIA_EXTENSIONS:
            raise ContractError("UNSUPPORTED_MEDIA", "Only selected supported media, captions and fonts may be opened by Studio.")
        with self._directory(root, parent) as directory:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or _hash(_identity(info)) != expected:
                    raise ContractError("ASSET_CHANGED", "Selected source changed or is not a regular file.")
                before = _identity(info)
                yield stream, {"display_name": leaf, "byte_length": info.st_size,
                               "mime": mimetypes.guess_type(leaf)[0] or "application/octet-stream"}
                if before != _identity(os.fstat(stream.fileno())):
                    raise ContractError("ASSET_CHANGED", "Source changed during use.")
