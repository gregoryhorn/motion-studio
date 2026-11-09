"""Deferred file-broker acceptance tests.

Authoring only during the implementation pass. Run after the full UI build is
assembled, per the user's explicit sequencing requirement.
"""
import os
from pathlib import Path
import tempfile
import unittest

from studio.contracts import ContractError
from studio.ui_files import UIFileBroker


class FileBrokerTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get("TMPDIR", str(Path.home() / ".hermes/cache/scratch")))
        scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.media = self.base / "media"
        self.media.mkdir()
        self.records = [{"id": "p_native", "name": "Native Project", "archived": False,
                         "folders": [{"path": str(self.media), "label": "Footage", "is_primary": True}]}]
        self.now = 1000.0
        self.broker = UIFileBroker(self.base / "broker", lambda: self.records,
                                   clock=lambda: self.now)

    def folder(self):
        return self.broker.roots("p_native")["items"][0]

    def browse(self, **kwargs):
        root = self.folder()
        return self.broker.browse("p_native", root["root_id"],
                                  expected_root_revision=root["root_revision"], **kwargs)

    def test_native_identity_does_not_accept_display_name(self):
        with self.assertRaises(ContractError) as caught:
            self.broker.roots("Native Project")
        self.assertEqual(caught.exception.code, "NOT_FOUND")

    def test_empty_folder_is_visible_without_composition_or_ingest(self):
        result = self.browse()
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)
        self.assertFalse(result["has_more"])
        self.assertFalse((self.base / "projects").exists())

    def test_pagination_keeps_all_entries_and_exact_total(self):
        for name in ["one.mp4", "two.wav", "three.jpg", "four.vtt", "five.txt"]:
            (self.media / name).write_bytes(b"inert source bytes")
        result = self.browse(limit=2)
        total = result["total"]
        found = list(result["items"])
        root = self.folder()
        while result["has_more"]:
            self.assertIsNotNone(result["next_cursor"])
            result = self.broker.browse("p_native", root["root_id"],
                expected_root_revision=root["root_revision"], limit=2, cursor=result["next_cursor"])
            found.extend(result["items"])
            self.assertEqual(result["total"], total)
        self.assertEqual(total, 5)
        self.assertEqual(len({entry["name"] for entry in found}), total)
        self.assertIsNone(result["next_cursor"])

    def test_symlink_visible_but_not_importable(self):
        outside = self.base / "private.mp4"
        outside.write_bytes(b"not authorized through project root")
        (self.media / "shortcut.mp4").symlink_to(outside)
        entry = self.browse()["items"][0]
        self.assertEqual(entry["kind"], "symlink")
        self.assertFalse(entry["importable"])
        self.assertEqual(entry["reason"], "SYMLINK_DENIED")
        root = self.folder()
        with self.assertRaises((ContractError, OSError)):
            with self.broker.open_node("p_native", root["root_id"], entry["node_id"], root["root_revision"]):
                self.fail("must never yield a symlink source")

    def test_source_change_invalidates_selected_node(self):
        source = self.media / "clip.mp4"
        source.write_bytes(b"before")
        entry = self.browse()["items"][0]
        source.write_bytes(b"changed bytes")
        root = self.folder()
        with self.assertRaises(ContractError) as caught:
            with self.broker.open_node("p_native", root["root_id"], entry["node_id"], root["root_revision"]):
                self.fail("must never yield changed bytes")
        self.assertEqual(caught.exception.code, "ASSET_CHANGED")

    def test_foreign_native_project_cannot_reuse_node(self):
        (self.media / "clip.mp4").write_bytes(b"source")
        entry = self.browse()["items"][0]
        root = self.folder()
        self.records.append({"id": "p_other", "name": "Native Project", "archived": False,
                             "folders": [{"path": str(self.media)}]})
        with self.assertRaises(ContractError) as caught:
            with self.broker.open_node("p_other", root["root_id"], entry["node_id"], root["root_revision"]):
                self.fail("must never yield foreign node")
        self.assertEqual(caught.exception.code, "NOT_FOUND")

    def test_expired_selection_requires_refresh(self):
        (self.media / "clip.mp4").write_bytes(b"source")
        entry = self.browse()["items"][0]
        self.now += 901
        root = self.folder()
        with self.assertRaises(ContractError) as caught:
            with self.broker.open_node("p_native", root["root_id"], entry["node_id"], root["root_revision"]):
                self.fail("must never yield expired node")
        self.assertEqual(caught.exception.code, "NODE_EXPIRED")

    def test_safe_stream_is_exact_and_has_no_server_path_in_metadata(self):
        (self.media / "clip.mp4").write_bytes(b"actual file bytes")
        entry = self.browse()["items"][0]
        root = self.folder()
        with self.broker.open_node("p_native", root["root_id"], entry["node_id"], root["root_revision"]) as (stream, metadata):
            self.assertEqual(stream.read(), b"actual file bytes")
            self.assertEqual(metadata["display_name"], "clip.mp4")
            self.assertEqual(set(metadata), {"display_name", "byte_length", "mime"})
        self.assertNotIn(str(self.media), repr(self.broker.roots("p_native")))
