"""Strict native adapter seam; trusted scope and service are supplied out of band."""
from pydantic import ValidationError
import sqlite3
from ..domain import Fault
from ..media_import.contracts import BeginImport, ImportChunk, ImportID, RetrieveTake, ReadChunk

OPERATIONS = {
    'begin': BeginImport,
    'chunk': ImportChunk,
    'status': ImportID,
    'commit': ImportID,
    'cancel': ImportID,
    'retrieve': RetrieveTake,
    'describe': RetrieveTake,
    'read_chunk': ReadChunk,
}


def invoke(service, scope, operation, payload):
    """Return a finite result dict, or (original bytes, take row) for retrieve.

    A native controller must encode retrieved bytes in its existing bounded
    delivery transport. This seam deliberately does not add a path/URL endpoint.
    """
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise Fault('UNKNOWN_MEDIA_OPERATION')
    try:
        model = OPERATIONS[operation].model_validate(payload)
    except ValidationError:
        raise Fault('INVALID_MEDIA_PAYLOAD') from None
    try:
        return getattr(service, operation)(scope, model)
    except (OSError, sqlite3.Error):
        raise Fault('STORAGE_UNAVAILABLE') from None
