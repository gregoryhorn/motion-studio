"""Deferred HTTP -> UIService -> SQLite/ProjectStore/file-broker integration.

Authoring only: do not execute until the full UI build's test gate opens.
Only host discovery and authenticated identity establishment are fixture seams;
the router, parser, service, command journal, compiler and broker remain real.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from typing import Any

import httpx
from fastapi import FastAPI

from dashboard import plugin_api
from studio import ui
from studio.ui_files import UIFileBroker
from studio.ui_service import UIService


class CrossLayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from hermes_cli.plugin_host_http_auth import with_hosted_admission

        scratch = Path(os.environ.get("TMPDIR", str(Path.home() / ".hermes/cache/scratch")))
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch, prefix="ui-cross-layer-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.media = self.base / "media"
        self.media.mkdir()
        self.records = [dict(id="native-A", name="Native A", archived=False,
                             folders=[dict(path=str(self.media), label="Footage", is_primary=True)])]
        self.broker = UIFileBroker(self.base / "broker", lambda: copy.deepcopy(self.records))
        self.service = UIService(self.base / "ui", lambda: copy.deepcopy(self.records),
                                 profile_id="profile-A", backend_instance_id="backend-A",
                                 integrations={"root_broker": self.broker})
        self.scope = dict(backend_instance_id="backend-A", connection_id="local",
                          profile_id="profile-A", native_project_id="native-A")
        self.actor = "subject-A"
        app = FastAPI()
        app.state.auth_required = True

        @app.middleware("http")
        async def establish_fixture_identity(request, call_next):
            # This is trusted host state, not a client-supplied actor/header.
            if self.actor is not None:
                request.state.native_http_principal = {"subject": self.actor}
            return await call_next(request)

        app.include_router(plugin_api.router)
        boundary_patch = patch.object(plugin_api, "_boundary", return_value=ui)
        boundary_patch.start()
        self.addCleanup(boundary_patch.stop)
        service_patch = patch.object(ui, "service_for_request", return_value=self.service)
        service_patch.start()
        self.addCleanup(service_patch.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=with_hosted_admission(app, False)),
                                       base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def get(self, path, values=None):
        # Match desktop/plugin.js query encoding, including JSON objects/null.
        params = {key: json.dumps(value, separators=(",", ":"))
                  if isinstance(value, (dict, list, bool)) or value is None else str(value)
                  for key, value in (values or {}).items()}
        return await self.client.get("/ui/v1" + path, params=params)

    def create_body(self) -> dict[str, Any]:
        return dict(scope=copy.deepcopy(self.scope), command_id=str(uuid.uuid4()),
                    idempotency_key=str(uuid.uuid4()), preconditions={"catalog_revision": 1},
                    input=dict(name="Composition", template_ref=None,
                               format=dict(fps=dict(num=30, den=1), width=1920, height=1080,
                                           sample_rate=48000, channels=2, duration_frames=0)))

    async def test_native_owner_bootstrap_reaches_real_service(self):
        response = await self.get("/bootstrap", {"client_contract": "ui.v1", "client_kind": "desktop"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"]["profile_id"], "profile-A")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    async def test_unauthenticated_request_does_not_create_service_metadata(self):
        self.actor = None
        response = await self.get("/projects/native-A/context")
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["error"]["code"], "AUTH_REQUIRED")
        self.assertFalse(self.service.database.exists())

    async def test_desktop_boolean_and_integer_query_types_round_trip(self):
        response = await self.get("/projects", {"include_archived": False, "limit": 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["items"][0]["native_project_id"], "native-A")

    async def test_root_listing_json_null_and_limit_reach_real_broker(self):
        (self.media / "a.mp4").write_bytes(b"a")
        (self.media / "b.wav").write_bytes(b"b")
        context = await self.get("/projects/native-A/context")
        self.assertEqual(context.status_code, 200, context.text)
        root = context.json()["data"]["roots"][0]
        response = await self.get("/projects/native-A/roots/" + root["root_id"] + "/entries",
                                  dict(parent_node_id=None, expected_root_revision=root["root_revision"],
                                       kind_filter="all", limit=1))
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["total"], 2)
        self.assertTrue(data["has_more"])
        self.assertEqual(len(data["items"]), 1)
        self.assertNotIn(str(self.media), response.text)

    async def test_http_create_replay_status_and_authenticated_receipt_actor(self):
        body = self.create_body()
        path = "/projects/native-A/compositions"
        first = await self.client.post("/ui/v1" + path, json=body)
        self.assertEqual(first.status_code, 201, first.text)
        # Reconstruct the service: replay/receipt evidence must survive an owned
        # image reopen, not merely a still-live in-memory SQLite connection.
        self.service = UIService(self.base / "ui", lambda: copy.deepcopy(self.records),
                                 profile_id="profile-A", backend_instance_id="backend-A",
                                 integrations={"root_broker": self.broker})
        replay = await self.client.post("/ui/v1" + path, json=body)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()["command"]["replayed"])
        self.assertEqual(first.json()["data"]["composition"]["composition_id"],
                         replay.json()["data"]["composition"]["composition_id"])
        receipt = await self.get("/projects/native-A/receipts/" + first.json()["command"]["receipt_id"])
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json()["data"]["actor"]["actor_ref"], self.actor)
        digest = UIService.request_hash("OP-COMPOSITION-CREATE", path, body)
        status = await self.get("/commands/" + body["command_id"],
                                dict(scope=body["scope"], request_sha256=digest))
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["data"]["status"], "committed")
        # Verify exact persisted cardinality, not just response replay markers.
        connection = self.service._connect()
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM compositions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM commands").fetchone()[0], 1)
        finally:
            connection.close()

    async def test_frozen_intent_change_is_not_replayed(self):
        body = self.create_body()
        first = await self.client.post("/ui/v1/projects/native-A/compositions", json=body)
        self.assertEqual(first.status_code, 201, first.text)
        body["input"]["name"] = "Changed intent"
        changed = await self.client.post("/ui/v1/projects/native-A/compositions", json=body)
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(changed.json()["error"]["code"], "IDEMPOTENCY_MISMATCH")

    async def test_scope_assertion_cannot_select_foreign_profile(self):
        body = self.create_body()
        body["scope"]["profile_id"] = "profile-foreign"
        response = await self.client.post("/ui/v1/projects/native-A/compositions", json=body)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["error"]["code"], "SCOPE_MISMATCH")
        self.assertFalse(self.service.database.exists())

    async def test_duplicate_queries_and_post_keys_are_rejected_before_storage(self):
        duplicate_query = await self.client.get("/ui/v1/bootstrap?client_contract=ui.v1&client_contract=ui.v1&client_kind=desktop")
        self.assertEqual(duplicate_query.status_code, 400, duplicate_query.text)
        duplicate_body = await self.client.post("/ui/v1/projects/native-A/compositions",
                                                content=b'{"scope":{},"scope":{}}',
                                                headers={"content-type": "application/json"})
        self.assertEqual(duplicate_body.status_code, 400, duplicate_body.text)
        self.assertEqual(duplicate_body.json()["error"]["code"], "INVALID_ARGUMENT")
        self.assertFalse(self.service.database.exists())

    async def test_invalid_utf8_overflow_and_depth_stay_client_errors_before_storage(self):
        cases = [('{"x":1}'.encode("utf-16")), b'{"x":1e999}', b'{"x":-1e999}',
                 b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}']
        for raw in cases:
            with self.subTest(raw=raw[:40]):
                response = await self.client.post("/ui/v1/projects/native-A/compositions",
                                                  content=raw, headers={"content-type": "application/json"})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error"]["code"], "INVALID_ARGUMENT")
        for raw in ('{"x":1e999}', '{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}'):
            response = await self.client.get("/ui/v1/commands/" + str(uuid.uuid4()),
                                             params={"scope": raw, "request_sha256": "0" * 64})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(response.json()["error"]["code"], "INVALID_ARGUMENT")
        self.assertFalse(self.service.database.exists())

    async def test_nested_publication_refs_survive_command_status_reconciliation(self):
        body = self.create_body()
        response = await self.client.post('/ui/v1/projects/native-A/compositions',json=body)
        self.assertEqual(response.status_code,201,response.text)
        saved = response.json()['data']
        request_sha = self.service.request_hash('OP-COMPOSITION-CREATE','/projects/native-A/compositions',body)
        observed = await self.get('/commands/'+body['command_id'],dict(scope=self.scope,request_sha256=request_sha))
        self.assertEqual(observed.status_code,200,observed.text)
        refs = observed.json()['data']['result_refs']
        self.assertIn(dict(kind='composition',id=saved['composition']['composition_id']),refs)
        self.assertIn(dict(kind='version',id=saved['version']['version_id']),refs)

    async def test_no_binary_backdoor_through_json_facade(self):
        response = await self.get("/projects/native-A/media/media_test/bytes")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["error"]["code"], "HOST_TRANSPORT_REQUIRED")
