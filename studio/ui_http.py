"""Authenticated, descriptor-pinned HTTP delivery for UI media leases.

The dashboard authenticates every request. A lease ID is only a locator, never
an authentication credential. No local pathname crosses this interface.
"""
from __future__ import annotations

import re
from contextlib import ExitStack
from threading import Lock
from urllib.parse import quote


_CHUNK_SIZE = 65536
_INLINE_TYPES = frozenset({
    'video/mp4', 'video/webm', 'video/quicktime', 'audio/mpeg', 'audio/mp4',
    'audio/wav', 'audio/x-wav', 'audio/flac', 'audio/ogg', 'audio/webm',
    'image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/avif',
})


def byte_range(value: str | None, length: int) -> tuple[int, int] | None:
    """Resolve one inclusive byte range; reject malformed/multiple ranges.

    None means a full response. A suffix larger than the file resolves to the
    whole file, but still receives 206 because a valid Range was requested.
    """
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 128 or length <= 0:
        raise ValueError('Unsatisfiable byte range')
    match = re.fullmatch(r'bytes=([0-9]*)-([0-9]*)', value.strip())
    if match is None or not any(match.groups()):
        raise ValueError('Unsatisfiable byte range')
    left, right = match.groups()
    if not left:
        suffix = int(right)
        if suffix == 0:
            raise ValueError('Unsatisfiable byte range')
        return max(0, length - suffix), length - 1
    start = int(left)
    end = min(int(right), length - 1) if right else length - 1
    if start >= length or end < start:
        raise ValueError('Unsatisfiable byte range')
    return start, end


def media_response(manager, context, access_id, *, method='GET',
                   range_header=None, if_range=None, if_none_match=None):
    """Open and validate a scoped lease before emitting response headers.

    Intended for a threadpool call. Both normal completion and ASGI response
    cancellation close the context. A read failure terminates the stream; it
    never fabricates missing bytes to meet the advertised content hash.
    """
    from starlette.background import BackgroundTask
    from starlette.responses import Response, StreamingResponse

    if method not in ('GET', 'HEAD'):
        raise ValueError('Media transport only supports GET and HEAD')
    stack = ExitStack()
    lock = Lock()

    def release():
        with lock:
            stack.close()

    try:
        stream, metadata = stack.enter_context(manager.open_access(context, access_id))
        length, digest = metadata['byte_length'], metadata['sha256']
        if type(length) is not int or length < 0 or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid retained media metadata')
        mime = metadata.get('mime')
        mime = mime if mime in _INLINE_TYPES else 'application/octet-stream'
        disposition = 'inline' if mime in _INLINE_TYPES and metadata.get('disposition') == 'inline' else 'attachment'
        name = metadata.get('display_name', 'media')
        if not isinstance(name, str):
            name = 'media'
        # Keep the human label a label, not a suggested directory path.
        name = name.replace('\\', '/').rsplit('/', 1)[-1][:180] or 'media'
        etag = '"' + digest + '"'
        headers = {
            'Accept-Ranges': 'bytes', 'ETag': etag,
            'Cache-Control': 'private, no-store',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "sandbox; default-src 'none'",
            'Cross-Origin-Resource-Policy': 'same-origin',
            'Content-Disposition': disposition + "; filename*=UTF-8''" + quote(name, safe=''),
        }
        if range_header is None and isinstance(if_none_match, str) and len(if_none_match) <= 8192:
            validators = {item.strip() for item in if_none_match.split(',')}
            if '*' in validators or etag in validators or 'W/' + etag in validators:
                release()
                return Response(status_code=304, headers=headers)
        # If-Range accepts only this exact strong content ETag. Date validators
        # and weak ETags cannot validate an immutable lease and get full bytes.
        if method == 'HEAD' or (if_range is not None and if_range != etag):
            range_header = None
        try:
            selected = byte_range(range_header, length)
        except ValueError:
            release()
            return Response(status_code=416, headers={**headers, 'Content-Range': f'bytes */{length}', 'Content-Length': '0'})
        start, end = selected if selected is not None else (0, length - 1)
        count = max(0, end - start + 1)
        status = 206 if selected is not None else 200
        headers['Content-Length'] = str(count)
        if selected is not None:
            headers['Content-Range'] = f'bytes {start}-{end}/{length}'
        stream.seek(start)
        if method == 'HEAD':
            release()
            return Response(status_code=status, headers=headers, media_type=mime)

        def chunks():
            remaining = count
            try:
                while remaining:
                    body = stream.read(min(_CHUNK_SIZE, remaining))
                    if not body or len(body) > remaining:
                        raise OSError('Retained media changed during delivery')
                    remaining -= len(body)
                    yield body
            finally:
                release()

        return StreamingResponse(chunks(), status_code=status, media_type=mime,
                                 headers=headers, background=BackgroundTask(release))
    except BaseException:
        release()
        raise
