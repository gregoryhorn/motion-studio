"""Authenticated Hermes dashboard namespace for the native Studio extension.

No standalone listener, permissive CORS, filesystem URL, or separate login is
introduced. Hermes' plugin mount owns authentication, profile selection and
consent; this module only handles the namespaced UI contract.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import hashlib
import re
import sys
import threading
from urllib.parse import quote

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

router = APIRouter()
_IMPORT_LOCK = threading.RLock()


def _boundary():
    # Dashboard APIs are loaded as standalone modules by Hermes. Keep this
    # package isolated from other plugins; never prepend user code to sys.path.
    root = Path(__file__).resolve().parents[1]
    name = "hermes_motion_ui_" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    with _IMPORT_LOCK:
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                name, root / "__init__.py", submodule_search_locations=[str(root)])
            if spec is None or spec.loader is None:
                raise RuntimeError("Motion Studio package is unavailable")
            package = importlib.util.module_from_spec(spec)
            sys.modules[name] = package
            try:
                spec.loader.exec_module(package)
            except BaseException:
                sys.modules.pop(name, None)
                raise
        return importlib.import_module(name + ".studio.ui")


def _authenticated_principal(request):
    from hermes_cli.plugin_host_http_auth import admitted_for_sensitive_route
    if not admitted_for_sensitive_route(request):
        raise HTTPException(status_code=401)
    native = getattr(request.state, "native_http_principal", None)
    session = getattr(request.state, "session", None)
    if isinstance(native, dict) and isinstance(native.get("subject"), str):
        return native["subject"]
    if session is not None:
        from gateway.owner_identity import principal_subject
        return principal_subject({"user_id": session.user_id,
                                  "provider": session.provider, "issuer": session.issuer})
    # Admission on the isolated host is conveyed only over trusted private IPC.
    from gateway.owner_identity import host_owner_subject
    return host_owner_subject()


# Binary chunks use the regular command journal, but never JSON/base64 as a
# pretend byte stream. Only metadata is journaled; exact bytes stay host-only.
@router.put("/ui/v1/projects/{native_project_id}/uploads/{upload_id}/chunks/{chunk_index}")
async def upload_chunk(request: Request, native_project_id: str, upload_id: str, chunk_index: str):
    boundary = _boundary()
    try:
        principal = _authenticated_principal(request)
        query = dict(request.query_params)
        if len(query) != len(request.query_params.multi_items()) or set(query) - {"profile"}:
            raise HTTPException(status_code=400)
        if re.fullmatch(r'(?:0|[1-9][0-9]{0,9})', chunk_index) is None:
            raise HTTPException(status_code=400)
        package_name = boundary.__package__
        if not isinstance(package_name, str) or not package_name:
            raise RuntimeError("UI boundary package is unavailable")
        upload = importlib.import_module(package_name + ".ui_uploads")
        command = upload.chunk_headers(request.headers, boundary.strict_json)
        service = await run_in_threadpool(boundary.service_for_request, command['scope'].get('connection_id', 'local'))
        await run_in_threadpool(service._assert_scope, command['scope'], native_project_id)
        await run_in_threadpool(service._native, native_project_id)
        pieces, received = [], 0
        expected_length = command['input']['content_length']
        async for piece in request.stream():
            received += len(piece)
            if received > expected_length or received > upload.MAX_CHUNK:
                status, envelope = boundary.error_envelope("LIMIT_EXCEEDED", "Upload body exceeds the declared chunk length.", 413)
                return JSONResponse(envelope, status_code=status, headers={"Cache-Control": "no-store"})
            pieces.append(piece)
        raw = b''.join(pieces)
        upload.verify_chunk(command, raw)
        path = '/projects/' + quote(native_project_id, safe='') + '/uploads/' + quote(upload_id, safe='') + '/chunks/' + chunk_index
        status, envelope = await run_in_threadpool(service.handle, 'PUT', path, {}, command, principal,
                                                  host_context={'binary_upload_chunk': raw})
        return JSONResponse(envelope, status_code=status,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except HTTPException as exc:
        code = "AUTH_REQUIRED" if exc.status_code == 401 else "INVALID_ARGUMENT" if exc.status_code == 400 else "PERMISSION_DENIED"
        status, envelope = boundary.error_envelope(code, "Hermes denied this upload request.", exc.status_code)
    except Exception as exc:
        known = {"INVALID_ARGUMENT": 400, "SCOPE_MISMATCH": 400, "NOT_FOUND": 404,
                 "DIGEST_MISMATCH": 422, "RANGE_INVALID": 416, "LIMIT_EXCEEDED": 413,
                 "PERMISSION_DENIED": 403, "BACKEND_UNAVAILABLE": 503,
                 "HOST_VERSION_UNSUPPORTED": 503}
        code = getattr(exc, 'code', 'BACKEND_UNAVAILABLE')
        code = code if code in known else 'BACKEND_UNAVAILABLE'
        message = ("Hermes differs from this plugin's locked host version; compatibility review is required."
                   if code == 'HOST_VERSION_UNSUPPORTED' else
                   "Upload chunk was not accepted; query upload and command status before retrying.")
        status, envelope = boundary.error_envelope(code, message, known[code])
    return JSONResponse(envelope, status_code=status, headers={"Cache-Control": "no-store"})


# Register the binary route before the catch-all JSON contract. Every range
# request re-authenticates; access_id alone grants no access to bytes.
@router.api_route("/ui/v1/projects/{native_project_id}/media-access/{access_id}/bytes",
                  methods=["GET", "HEAD"])
async def media_bytes(request: Request, native_project_id: str, access_id: str):
    boundary = _boundary()
    try:
        principal = _authenticated_principal(request)
        query = dict(request.query_params)
        if (len(query) != len(request.query_params.multi_items()) or
                set(query) - {"profile", "connection_id"}):
            status, envelope = boundary.error_envelope("INVALID_ARGUMENT", "Unexpected or duplicate media query fields.")
            return JSONResponse(envelope, status_code=status)
        # The host consumed profile admission. Neither it nor a caller path can
        # choose storage here; service_for_request admits only configured IDs.
        service = await run_in_threadpool(boundary.service_for_request, query.get("connection_id", "local"))
        await run_in_threadpool(service._native, native_project_id)
        manager = service.integrations.get("_media_store")
        if manager is None:
            status, envelope = boundary.error_envelope("HOST_TRANSPORT_REQUIRED", "Authenticated media transport is unavailable.", 503)
            return JSONResponse(envelope, status_code=status)
        context = {"scope": service._scope(native_project_id), "principal": principal}
        package_name = boundary.__package__
        if not isinstance(package_name, str) or not package_name:
            raise RuntimeError("UI boundary package is unavailable")
        transport = importlib.import_module(package_name + ".ui_http")
        return await run_in_threadpool(transport.media_response, manager, context, access_id,
            method=request.method, range_header=request.headers.get("range"),
            if_range=request.headers.get("if-range"), if_none_match=request.headers.get("if-none-match"))
    except HTTPException as exc:
        status, envelope = boundary.error_envelope("AUTH_REQUIRED" if exc.status_code == 401 else "PERMISSION_DENIED",
                                                   "Hermes denied this media request.", exc.status_code)
    except Exception as exc:
        # Do not publish engine exception text: it may contain retained paths.
        code = getattr(exc, "code", "BACKEND_UNAVAILABLE")
        known = {"NOT_FOUND": 404, "MEDIA_ACCESS_EXPIRED": 410, "MEDIA_CHANGED": 409,
                 "PERMISSION_DENIED": 403, "SCOPE_MISMATCH": 400,
                 "AUTH_REQUIRED": 401, "BACKEND_UNAVAILABLE": 503,
                 "HOST_VERSION_UNSUPPORTED": 503}
        code = code if code in known else "BACKEND_UNAVAILABLE"
        message = ("Hermes differs from this plugin's locked host version; compatibility review is required."
                   if code == 'HOST_VERSION_UNSUPPORTED' else
                   "Media bytes are unavailable; resolve a fresh authorized lease.")
        status, envelope = boundary.error_envelope(code, message, known[code])
    return JSONResponse(envelope, status_code=status, headers={"Cache-Control": "no-store"})


@router.api_route("/ui/v1/{route:path}", methods=["GET", "POST"])
async def ui_api(request: Request, route: str):
    boundary = _boundary()
    body = None
    try:
        principal = _authenticated_principal(request)
        query = dict(request.query_params)
        # Profile is consumed by Hermes' authenticated scope before dispatch.
        # Never interpret it as an arbitrary local path/profile here.
        query.pop("profile", None)
        if len(set(request.query_params.keys())) != len(request.query_params.multi_items()):
            status, envelope = boundary.error_envelope("INVALID_ARGUMENT", "Duplicate query fields are not accepted.")
            return JSONResponse(envelope, status_code=status)
        if request.method == "POST":
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                status, envelope = boundary.error_envelope("INVALID_ARGUMENT", "Use application/json for commands.")
                return JSONResponse(envelope, status_code=status)
            chunks, length = [], 0
            async for chunk in request.stream():
                length += len(chunk)
                if length > 1048576:
                    status, envelope = boundary.error_envelope("LIMIT_EXCEEDED", "Command body exceeds 1 MiB.", 413)
                    return JSONResponse(envelope, status_code=status)
                chunks.append(chunk)
            body = boundary.strict_json(b"".join(chunks))
        scope = body.get("scope", {}) if isinstance(body, dict) else {}
        if not isinstance(scope, dict):
            status, envelope = boundary.error_envelope("INVALID_ARGUMENT", "Scope must be an object.")
            return JSONResponse(envelope, status_code=status)
        connection_id = scope.get("connection_id", query.pop("connection_id", "local"))
        if request.method == "GET":
            query = boundary.decode_query(query)
        service = await run_in_threadpool(boundary.service_for_request, connection_id)
        # Credentialed <video>/<audio> requests can use ambient auth only for
        # this request's actual browser session. Native ticket admission does
        # not establish cookies on the renderer's origin.
        cookie_authenticated = (getattr(request.state, "session", None) is not None and
                                getattr(request.state, "native_http_principal", None) is None)
        # Unlike a credentialed media element, the bounded JSON byte bridge
        # works through this already-admitted REST call on native and web.
        host_context = {"qualified_media_transports": ("authenticated_blob", "same_origin_cookie")
                        if cookie_authenticated else ("authenticated_blob",)}
        status, envelope = await run_in_threadpool(
            service.handle, request.method, "/" + route, query, body, principal,
            host_context=host_context)
        return JSONResponse(envelope, status_code=status,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except HTTPException as exc:
        status, envelope = boundary.error_envelope("AUTH_REQUIRED" if exc.status_code == 401 else "PERMISSION_DENIED",
                                                   "Hermes denied this request.", exc.status_code)
        return JSONResponse(envelope, status_code=status)
    except Exception as exc:
        # Contract failures are safe to project. Unexpected exception contents
        # may include private paths/credentials and never become client copy.
        code = getattr(exc, "code", None)
        message = getattr(exc, "message", None)
        if isinstance(code, str) and isinstance(message, str):
            status, envelope = boundary.error_envelope(code, message,
                {"LIMIT_EXCEEDED": 413, "SCOPE_MISMATCH": 400,
                 "PERMISSION_DENIED": 403, "BACKEND_UNAVAILABLE": 503,
                 "HOST_VERSION_UNSUPPORTED": 503}.get(code, 400))
        else:
            status, envelope = boundary.error_envelope("BACKEND_UNAVAILABLE",
                "Studio is unavailable. Preserve your draft and reconnect.", 503)
        return JSONResponse(envelope, status_code=status, headers={"Cache-Control": "no-store"})
