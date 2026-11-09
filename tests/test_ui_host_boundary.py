"""Deferred source-review regressions. Authored, NOT executed during build.

Run only after the complete source is assembled and the owner's test gate opens.
These tests use real JSON parsing, SQLite registries and broker filesystem IO.
"""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from studio.contracts import ContractError
from studio import ui
from studio.ui_files import UIFileBroker
from studio.ui_service import UIService


class NativeRegistrySQLiteBoundaryTests(unittest.TestCase):
    """The live WAL obstacle must stay explicit, never become an empty registry."""

    def test_native_identity_from_descriptor_image_and_live_wal_refusal(self):
        from studio.ui import native_projects
        from studio.contracts import ContractError
        import sqlite3
        scratch = Path(os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch')))
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            home = Path(temporary)
            db = sqlite3.connect(':memory:')
            try:
                db.executescript('''CREATE TABLE projects(id TEXT,name TEXT,archived INTEGER);
                    CREATE TABLE project_folders(project_id TEXT,path TEXT,label TEXT,is_primary INTEGER);
                    INSERT INTO projects VALUES('native-exact-id','Native Project',0);
                    INSERT INTO project_folders VALUES('native-exact-id','/unchanged/native/folder','Primary',1);''')
                payload = db.serialize()
            finally:
                db.close()
            (home / 'projects.db').write_bytes(payload)
            self.assertEqual(native_projects(home), [dict(id='native-exact-id', name='Native Project',
                                                         archived=False, folders=[dict(path='/unchanged/native/folder', label='Primary', is_primary=1)])])
            (home / 'projects.db-wal').write_bytes(b'uncheckpointed native state')
            with self.assertRaises(ContractError) as caught:
                native_projects(home)
            self.assertEqual(caught.exception.code, 'STORAGE_UNSUPPORTED')
            self.assertEqual((home / 'projects.db').read_bytes(), payload)
            (home / 'projects.db-wal').unlink()
            outside = home / 'outside'
            outside.write_bytes(payload)
            (home / 'projects.db').unlink()
            (home / 'projects.db').symlink_to(outside)
            with self.assertRaises((ContractError, OSError)):
                native_projects(home)
            alias = home / 'alias'
            alias.symlink_to(home, target_is_directory=True)
            with self.assertRaises((ContractError, OSError)):
                native_projects(alias)


class HostBoundaryTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get("TMPDIR", str(Path.home() / ".hermes/cache/scratch")))
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch, prefix="ui-boundary-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def test_strict_json_rejects_non_utf8_and_nonfinite_overflow(self):
        for raw in ('{"x":1}'.encode("utf-16"), b'{"x":1e999}',
                    b'{"x":NaN}', b'{"x":1,"x":2}', b'[]'):
            with self.subTest(raw=raw):
                with self.assertRaises(ContractError) as caught:
                    ui.strict_json(raw)
                self.assertEqual(caught.exception.code, "INVALID_ARGUMENT")
        self.assertEqual(ui.strict_json(b'{"x":1,"nested":{"ok":true}}'),
                         {"x": 1, "nested": {"ok": True}})

    def test_deep_json_is_a_contract_error_not_unhandled_recursion(self):
        with self.assertRaises(ContractError) as caught:
            ui.strict_json(b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}')
        self.assertEqual(caught.exception.code, "INVALID_ARGUMENT")

    def test_structured_query_uses_the_same_finite_utf8_depth_policy(self):
        invalid = ['{"x":1e999}', '{"x":-1e999}', '{"x":NaN}',
                   '{"x":1,"x":2}', '{"x":"\\ud800"}',
                   '{"x":' + '[' * 65 + '0' + ']' * 65 + '}',
                   '{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}']
        for value in invalid:
            with self.subTest(value=value[:40]):
                with self.assertRaises(ContractError) as caught:
                    ui.decode_query({"scope": value})
                self.assertEqual(caught.exception.code, "INVALID_ARGUMENT")
        self.assertEqual(ui.decode_query({"scope": '{"x":1.25}', "limit": "2",
                                          "include_archived": "false", "version_id": "null",
                                          "search": "null"}),
                         {"scope": {"x": 1.25}, "limit": 2, "include_archived": False,
                          "version_id": None, "search": "null"})
        for raw in ('{"x":-1e999}', '{"x":"\\ud800"}', None):
            with self.subTest(raw=raw):
                with self.assertRaises(ContractError) as caught:
                    ui.strict_json(raw)
                self.assertEqual(caught.exception.code, "INVALID_ARGUMENT")

    def test_host_context_copies_only_allowlisted_media_transports(self):
        service = UIService(self.base / "ui", lambda: [], profile_id="profile-A", backend_instance_id="backend-A")
        contexts = []

        def capture(_db, _operation, context, _query):
            contexts.append(context)
            return 200, {}

        with patch.object(service, "_read", side_effect=capture):
            for host_context in (None,
                                 {"qualified_media_transports": "same_origin_cookie"},
                                 {"qualified_media_transports": ["same_origin_cookie", "authenticated_blob", 7],
                                  "principal": "forged", "project_store": "forged"}):
                status, _ = service.handle("GET", "/bootstrap",
                                           {"client_contract": "ui.v1", "client_kind": "desktop"},
                                           principal="real-host", host_context=host_context)
                self.assertEqual(status, 200)
        self.assertEqual([item["qualified_media_transports"] for item in contexts],
                         [(), (), ("same_origin_cookie", "authenticated_blob")])
        self.assertTrue(all(item["principal"] == "real-host" for item in contexts))
        self.assertTrue(all(item["project_store"] is service.store for item in contexts))

    def test_bootstrap_transport_advertisement_is_request_qualified(self):
        capabilities = {"range_media": True, "authenticated_blob": True,
                        "media_transports": ["same_origin_cookie", "authenticated_blob"]}
        service = UIService(self.base / "ui", lambda: [], profile_id="profile-A", backend_instance_id="backend-A",
                            integrations={"host_capabilities": capabilities})
        query = {"client_contract": "ui.v1", "client_kind": "desktop"}
        status, response = service.handle("GET", "/bootstrap", query)
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["host_seams"]["media_transports"], [])
        self.assertFalse(response["data"]["transport_capabilities"]["range_media"])
        self.assertFalse(response["data"]["transport_capabilities"]["authenticated_blob"])
        host_context = {"qualified_media_transports": ("authenticated_blob",)}
        status, response = service.handle("GET", "/bootstrap", query, host_context=host_context)
        self.assertEqual(status, 200)
        self.assertFalse(response["data"]["transport_capabilities"]["authenticated_blob"])
        service.integrations["OP-MEDIA-CHUNK"] = lambda *_: {}
        status, response = service.handle("GET", "/bootstrap", query, host_context=host_context)
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["host_seams"]["media_transports"], ["authenticated_blob"])
        self.assertTrue(response["data"]["transport_capabilities"]["authenticated_blob"])
        self.assertFalse(response["data"]["transport_capabilities"]["range_media"])
        self.assertEqual(response["data"]["limits"]["media_blob_bytes"], 64 * 1024 * 1024)
        self.assertEqual(capabilities["media_transports"], ["same_origin_cookie", "authenticated_blob"])

    def test_missing_native_registry_is_read_only(self):
        self.assertEqual(ui.native_projects(self.base), [])
        self.assertFalse((self.base / "projects.db").exists())

    def test_native_registry_uses_exact_ids_not_duplicate_names(self):
        database = self.base / "projects.db"
        with sqlite3.connect(database) as db:
            db.executescript("CREATE TABLE projects(id TEXT, name TEXT, archived INTEGER);"
                             "CREATE TABLE project_folders(project_id TEXT,path TEXT,label TEXT,is_primary INTEGER);")
            db.executemany("INSERT INTO projects VALUES(?,?,?)", [("A", "Same", 0), ("B", "Same", 1)])
            db.execute("INSERT INTO project_folders VALUES(?,?,?,?)", ("B", str(self.base), "Footage", 1))
        records = ui.native_projects(self.base)
        self.assertEqual([row["id"] for row in records], ["A", "B"])
        self.assertEqual(records[0]["folders"], [])
        self.assertTrue(records[1]["archived"])
        self.assertEqual(records[1]["folders"][0]["label"], "Footage")

    def test_native_registry_symlink_is_denied(self):
        outside = self.base / "outside.db"
        with sqlite3.connect(outside) as db:
            db.execute("CREATE TABLE secret(value TEXT)")
        (self.base / "projects.db").symlink_to(outside)
        with self.assertRaises(ContractError) as caught:
            ui.native_projects(self.base)
        self.assertEqual(caught.exception.code, "PATH_UNSAFE")

    def broker(self):
        media = self.base / "media"
        media.mkdir()
        records = [dict(id="native-A", name="A", archived=False,
                        folders=[dict(path=str(media), is_primary=True)])]
        broker = UIFileBroker(self.base / "broker", lambda: records)
        return broker, media

    def test_root_replacement_between_revision_check_and_listing_is_denied(self):
        broker, media = self.broker()
        (media / "authorized.mp4").write_bytes(b"authorized")
        root = broker.roots("native-A")["items"][0]
        original_root = broker._root

        def replace_after_validation(*args):
            selected = original_root(*args)
            media.rename(self.base / "old-media")
            media.mkdir()
            (media / "unexpected.mp4").write_bytes(b"replacement")
            return selected

        # Inject just the race; root validation, listing and broker DB are real.
        with patch.object(broker, "_root", side_effect=replace_after_validation):
            with self.assertRaises(ContractError) as caught:
                broker.browse("native-A", root["root_id"], expected_root_revision=root["root_revision"])
        self.assertEqual(caught.exception.code, "ROOT_CHANGED")

    def test_selected_directory_inode_replacement_is_denied(self):
        broker, media = self.broker()
        selected = media / "selected"
        selected.mkdir()
        root = broker.roots("native-A")["items"][0]
        entry = broker.browse("native-A", root["root_id"], expected_root_revision=root["root_revision"])["items"][0]
        selected.rename(media / "old-selected")
        selected.mkdir()
        (selected / "unexpected.mp4").write_bytes(b"replacement")
        with self.assertRaises(ContractError):
            broker.browse("native-A", root["root_id"], expected_root_revision=root["root_revision"],
                          parent_node_id=entry["node_id"])

    def test_broker_sqlite_swap_at_connect_cannot_write_outside_store(self):
        broker, _ = self.broker()
        outside = self.base / "outside.db"
        with sqlite3.connect(outside) as db:
            db.execute("CREATE TABLE sentinel(value TEXT)")
        real_connect = sqlite3.connect
        database = broker.root / "file-handles.sqlite3"
        swapped = False

        def swap_then_connect(target, *args, **kwargs):
            nonlocal swapped
            self.assertEqual(target, ':memory:')
            if not swapped:
                swapped = True
                database.unlink(missing_ok=True)
                database.symlink_to(outside)
            return real_connect(target, *args, **kwargs)

        # The invariant is no outside writes, whether admission rejects or uses a
        # pinned safe inode. Do not mock the database or broker implementation.
        with patch("studio.ui_sqlite.sqlite3.connect", side_effect=swap_then_connect):
            try:
                with broker._database():
                    pass
            except (ContractError, OSError, sqlite3.Error):
                pass
        self.assertTrue(swapped, 'The post-admission swap must actually be exercised')
        with real_connect(outside) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names, {"sentinel"}, "broker schema escaped to a symlink target")

    def test_service_metadata_rejects_symlinked_ancestor_before_creation(self):
        outside = self.base / "outside"
        outside.mkdir()
        service = UIService(self.base / "ui", lambda: [], profile_id="profile-A", backend_instance_id="backend-A")
        service.root.mkdir()
        (service.root / "ui-v1").symlink_to(outside, target_is_directory=True)
        before = sorted(str(item.relative_to(outside)) for item in outside.rglob("*"))
        try:
            db = service._connect()
        except (ContractError, OSError, sqlite3.Error):
            pass
        else:
            db.close()
            self.fail("metadata admission followed a symlinked ancestor")
        self.assertEqual(sorted(str(item.relative_to(outside)) for item in outside.rglob("*")), before)

    def test_service_metadata_database_symlink_cannot_initialize_foreign_db(self):
        service = UIService(self.base / "ui", lambda: [], profile_id="profile-A", backend_instance_id="backend-A")
        service.directory.mkdir(parents=True)
        outside = self.base / "outside.db"
        with sqlite3.connect(outside) as db:
            db.execute("CREATE TABLE sentinel(value TEXT)")
        service.database.symlink_to(outside)
        try:
            connection = service._connect()
        except (ContractError, OSError, sqlite3.Error):
            pass
        else:
            connection.close()
        with sqlite3.connect(outside) as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names, {"sentinel"})
