"""Binary upload metadata decoding; raw bytes remain a trusted host argument.

These headers identify frozen command intent, not an execution permission or a
credential. The host authenticates before reading the body; UIService journals
this metadata and records the normal command receipt before/after admission.
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from typing import Any, NoReturn

from .contracts import ContractError

MAX_CHUNK = 4 * 1024 * 1024
_HEADER_NAMES = ('content-length', 'content-range', 'digest', 'x-motion-scope',
                 'x-motion-command-id', 'idempotency-key', 'x-motion-upload-revision')


def _invalid(message, code='INVALID_ARGUMENT') -> NoReturn:
    raise ContractError(code, message)


def _uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        _invalid('A canonical UUID command identity is required.')
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        _invalid('A canonical UUID command identity is required.')
    if str(parsed) != value:
        _invalid('A canonical UUID command identity is required.')
    return value


def chunk_headers(headers, strict_json) -> dict[str, Any]:
    """Validate bounded headers before consuming an authenticated raw body.

    ``headers`` is Starlette's Headers, including duplicate-aware getlist.
    The scope decoder is the exact UTF-8/finite/depth-bounded UI JSON decoder.
    """
    for name in _HEADER_NAMES:
        if len(headers.getlist(name)) != 1:
            _invalid('Every binary command metadata header must occur exactly once.')
    if headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/octet-stream':
        _invalid('Use application/octet-stream for binary upload chunks.')
    length_text = headers['content-length']
    revision_text = headers['x-motion-upload-revision']
    if not re.fullmatch(r'[0-9]{1,10}', length_text):
        _invalid('A bounded Content-Length is required.')
    length = int(length_text)
    if not 1 <= length <= MAX_CHUNK:
        _invalid('Upload chunk exceeds the supported byte bound.', 'LIMIT_EXCEEDED')
    if not re.fullmatch(r'[0-9]{1,16}', revision_text) or int(revision_text) < 1:
        _invalid('A positive upload entity revision is required.')
    range_value = headers['content-range']
    if len(range_value) > 128:
        _invalid('Invalid upload Content-Range.', 'RANGE_INVALID')
    match = re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)', range_value)
    if match is None:
        _invalid('Invalid upload Content-Range.', 'RANGE_INVALID')
    start, end, total = map(int, match.groups())
    if end < start or end >= total or end - start + 1 != length:
        _invalid('Content-Range differs from the declared chunk length.', 'RANGE_INVALID')
    digest_value = headers['digest']
    if not digest_value.startswith('sha-256=') or len(digest_value) > 128:
        _invalid('Digest must contain one base64 SHA-256.', 'DIGEST_MISMATCH')
    encoded = digest_value[len('sha-256='):]
    try:
        digest = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        _invalid('Digest must contain one base64 SHA-256.', 'DIGEST_MISMATCH')
    if len(digest) != 32 or base64.b64encode(digest).decode('ascii') != encoded:
        _invalid('Digest must contain one canonical base64 SHA-256.', 'DIGEST_MISMATCH')
    scope_text = headers['x-motion-scope']
    if len(scope_text.encode('utf-8')) > 8192:
        _invalid('Binary command scope exceeds the header bound.', 'LIMIT_EXCEEDED')
    scope = strict_json(scope_text.encode('utf-8'))
    if not isinstance(scope, dict):
        _invalid('Binary upload scope must be an object.')
    return dict(scope=scope, command_id=_uuid(headers['x-motion-command-id']),
                idempotency_key=_uuid(headers['idempotency-key']),
                preconditions={'entity_revision': int(revision_text)},
                input={'content_length': length, 'content_range': range_value,
                       'digest': encoded, 'sha256': digest.hex()})


def verify_chunk(command, body):
    """Ensure the journal's frozen hash describes the exact raw request bytes."""
    metadata = command['input']
    if not isinstance(body, bytes) or len(body) != metadata['content_length']:
        _invalid('Upload bytes differ from Content-Length.', 'RANGE_INVALID')
    if hashlib.sha256(body).hexdigest() != metadata['sha256']:
        _invalid('Upload bytes differ from Digest.', 'DIGEST_MISMATCH')
