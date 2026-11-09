"""Hermes host boundary for the accepted native Motion Studio UI.

The host authenticates requests before mounting the dashboard router. Only the
host-resolved Hermes home selects a profile; renderer paths/profile assertions
never choose a filesystem. Importing this module performs no discovery or IO.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from .contracts import ContractError
from .project import ManagedFS

_LOCK = threading.RLock()
_SERVICES = {}
_CONNECTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _home():
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()).absolute()


def native_projects(home):
    """Read native identity through the host-owned registry API when available.

    The host selects its own profile/path and owns SQLite/WAL admission. Never
    pass this function's path argument to its connection factory. A detached
    non-WAL registry image remains readable without the host for scoped fixtures
    and offline metadata; it is not a stale substitute for a live WAL registry.
    """
    try:
        from hermes_cli import projects_db
    except ModuleNotFoundError as exc:
        if exc.name not in ('hermes_cli', 'hermes_cli.projects_db'):
            raise
        projects_db = None
    if projects_db is not None and Path(home).absolute() == projects_db.projects_db_path().parent.absolute():
        # Public native API: its default path comes from the authenticated host
        # profile, not a plugin/renderer override. A read transaction includes
        # committed WAL content and keeps project/folder rows consistent.
        with projects_db.connect_closing() as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            try:
                return [project.to_dict() for project in projects_db.list_projects(db, include_archived=True)]
            finally:
                db.rollback()
    from .ui_sqlite import _image
    fs = ManagedFS(Path(home))
    try:
        with fs.directory() as directory:
            payload, _ = _image(directory, 'projects.db')
    except FileNotFoundError:
        return []
    if payload is None:
        return []
    if not payload:
        raise ContractError('STORAGE_UNSUPPORTED', 'Native registry is not an initialized SQLite image.')
    db = sqlite3.connect(':memory:')
    try:
        if not hasattr(db, 'deserialize'):
            raise ContractError('STORAGE_UNSUPPORTED', 'Native registry requires SQLite deserialize support.')
        db.deserialize(payload)
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.row_factory = sqlite3.Row
        projects = []
        for row in db.execute("SELECT id, name, archived FROM projects ORDER BY name, id"):
            folders = [dict(folder) for folder in db.execute(
                "SELECT path, label, is_primary FROM project_folders WHERE project_id=? ORDER BY is_primary DESC, path",
                (row["id"],))]
            projects.append({"id": row["id"], "name": row["name"],
                             "archived": bool(row["archived"]), "folders": folders})
        return projects
    finally:
        db.close()


def _server_identity(home):
    fs = ManagedFS(Path(home) / "motion-studio" / "identity")
    try:
        value = fs.read("backend.json")
    except FileNotFoundError:
        value = {"schema": "motion-ui-backend.v1", "id": "backend_" + uuid.uuid4().hex}
        try:
            fs.write("backend.json", value)
        except FileExistsError:
            value = fs.read("backend.json")
    if not isinstance(value, dict) or value.get("schema") != "motion-ui-backend.v1" or not re.fullmatch(
            r"backend_[a-f0-9]{32}", value.get("id", "")):
        raise ContractError("STORAGE_UNSUPPORTED", "Backend identity requires operator recovery.")
    return value["id"]


def service_for_request(connection_id="local"):
    """Bind an SDK routing assertion to the already-authenticated host profile.

    connection_id is a client route label only. It never selects a home, changes
    an authenticated principal, or admits a foreign backend/profile assertion.
    """
    if not isinstance(connection_id, str) or not _CONNECTION.fullmatch(connection_id):
        raise ContractError("SCOPE_MISMATCH", "Connection routing identity is invalid.")
    from .host_compatibility import assert_supported_host
    assert_supported_host()
    home = _home()
    profile_id = "profile_" + hashlib.sha256(os.fsencode(home)).hexdigest()[:32]
    key = (str(home), connection_id)
    with _LOCK:
        service = _SERVICES.get(key)
        if service is None:
            from .ui_service import UIService
            from .ui_files import UIFileBroker
            from .ui_execution import build_integrations
            root = home / "motion-studio" / "ui"
            registry = lambda: native_projects(home)
            broker = UIFileBroker(root / "file-broker", registry)
            integrations = build_integrations(root, registry, broker)
            from .ui_sqlite import database_backend
            integrations['_media_store'].bind_database(database_backend)
            integrations["root_broker"] = broker
            # Product recipe, not a schema default or an implicit caption font.
            # Caption authors must explicitly save a supported caption_style.
            integrations['_graph_recipe'] = dict(id='ui-rgb-lossless-v1',
                color='srgb-rgb-full-unmanaged-v1', background=[0, 0, 0, 255], caption_style=None)
            service = UIService(root, registry,
                                profile_id=profile_id, backend_instance_id=_server_identity(home),
                                connection_id=connection_id, integrations=integrations)
            from .ui_handoff import build_handoff_integrations
            handoffs = build_handoff_integrations(root,
                execution=integrations['_execution_adapter'],resolve_binding=service.resolve_binding)
            service.integrations.update({key:value for key,value in handoffs.items() if key.startswith('OP-')})
            # Only authentic tool-turn context may supply execution authority;
            # a focused conversation ID is never a host_session_id substitute.
            _SERVICES[key] = service
        return service


def error_envelope(code, message, status=400):
    return status, {"api_version": "ui.v1", "request_id": str(uuid.uuid4()),
                    "scope": {}, "error": {"code": code, "message": message,
                    "retryable": False, "effect_state": "none", "details": {},
                    "recovery_actions": []}}


def _decode_json(raw, *, limit):
    """Decode bounded finite UTF-8 JSON, with a shared command/query policy."""
    if not isinstance(raw, (str, bytes, bytearray)):
        raise ValueError("JSON text required")
    if isinstance(raw, str):
        text = raw
        size = len(text.encode("utf-8", errors="strict"))
    else:
        size = len(raw)
        # json.loads(bytes) auto-detects UTF-16/32; that is not this API's wire
        # format. Decode explicitly before handing text to the JSON parser.
        text = bytes(raw).decode("utf-8", errors="strict")
    if size > limit:
        raise ContractError("LIMIT_EXCEEDED", "JSON input exceeds its byte limit.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def finite_float(token):
        number = float(token)
        if not math.isfinite(number):
            raise ValueError("nonfinite JSON number")
        return number

    def invalid_constant(_):
        raise ValueError("nonfinite JSON constant")

    value = json.loads(text, object_pairs_hook=pairs, parse_float=finite_float,
                       parse_constant=invalid_constant)
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError("JSON nesting exceeds its bound")
        if isinstance(item, dict):
            for key, child in item.items():
                key.encode("utf-8", errors="strict")
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            item.encode("utf-8", errors="strict")
    return value


def strict_json(raw):
    """Strict finite UTF-8 JSON object; malformed/deep input is a client error."""
    try:
        value = _decode_json(raw, limit=1048576)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ContractError("INVALID_ARGUMENT", "Body must be bounded strict UTF-8 JSON.") from None
    if not isinstance(value, dict):
        raise ContractError("INVALID_ARGUMENT", "Command body must be an object.")
    return value


def decode_query(query):
    """Decode only declared typed query fields, never literal IDs/search text.

    URLSearchParams transports scalars as strings and structured values as
    JSON. A strict facade must receive the original types without permissive
    coercion of arbitrary fields, duplicate keys, or nonfinite JSON values.
    """
    result = dict(query)
    numeric = {"limit", "wait_ms", "master_revision", "known_entity_revision", "offset", "length"}
    nullable = {"parent_node_id", "known_version_id", "after_cursor", "known_etag", "version_id"}
    structured = {"scope": dict, "pending_command_ids": list}
    for key, value in result.items():
        try:
            valid_text = isinstance(value, str) and len(value.encode("utf-8", errors="strict")) <= 65536
        except UnicodeError:
            valid_text = False
        if not valid_text:
            raise ContractError("INVALID_ARGUMENT", "Query value must be bounded UTF-8 text.")
        if key == "include_archived":
            if value not in {"true", "false"}:
                raise ContractError("INVALID_ARGUMENT", "include_archived must be true or false.")
            result[key] = value == "true"
        elif key in numeric:
            if not re.fullmatch(r"0|[1-9][0-9]{0,15}", value) or int(value) > 9007199254740991:
                raise ContractError("INVALID_ARGUMENT", "Query number must be an exact nonnegative integer.")
            result[key] = int(value)
        elif key in nullable and value == "null":
            result[key] = None
        elif key in structured:
            try:
                decoded = _decode_json(value, limit=65536)
            except (ValueError, UnicodeError, RecursionError):
                raise ContractError("INVALID_ARGUMENT", "Structured query field must be strict JSON.") from None
            if not isinstance(decoded, structured[key]):
                raise ContractError("INVALID_ARGUMENT", "Structured query field has the wrong type.")
            result[key] = decoded
    return result
