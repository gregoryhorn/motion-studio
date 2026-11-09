"""Deferred HTTP transport checks; do not execute until full source completion."""
import hashlib
import io
import unittest
from contextlib import contextmanager

from studio.ui_http import byte_range, media_response


class LeaseFixture:
    """Explicit in-memory transport fixture, not a production access manager."""
    def __init__(self, payload=b'0123456789', mime='video/mp4'):
        self.payload = payload
        self.mime = mime
        self.opens = 0
        self.closes = 0
        self.context = None

    @contextmanager
    def open_access(self, context, access_id):
        if access_id != 'access_fixture' or context['principal'] != 'owner_fixture':
            raise PermissionError('Invalid fixture admission')
        self.opens += 1
        self.context = context
        try:
            with io.BytesIO(self.payload) as stream:
                yield stream, dict(byte_length=len(self.payload),
                    sha256=hashlib.sha256(self.payload).hexdigest(), mime=self.mime,
                    disposition='inline', display_name='../fixture.mp4')
        finally:
            self.closes += 1


class RangeTests(unittest.TestCase):
    def test_full_explicit_and_suffix_ranges(self):
        self.assertIsNone(byte_range(None, 10))
        self.assertEqual(byte_range('bytes=2-5', 10), (2, 5))
        self.assertEqual(byte_range('bytes=2-', 10), (2, 9))
        self.assertEqual(byte_range('bytes=-3', 10), (7, 9))
        self.assertEqual(byte_range('bytes=-50', 10), (0, 9))
        self.assertEqual(byte_range('bytes=0-90', 10), (0, 9))

    def test_invalid_and_multiple_ranges(self):
        for value in ('bytes=', 'bytes=-', 'bytes=-0', 'bytes=10-',
                      'bytes=5-2', 'bytes=0-1,3-4', 'items=0-1',
                      'bytes=+1-2', 'bytes=0-1\r\nInjected: yes'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                byte_range(value, 10)
        with self.assertRaises(ValueError):
            byte_range('bytes=0-', 0)


class MediaResponseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = dict(scope={'native_project_id': 'project_fixture'}, principal='owner_fixture')

    async def consume(self, response):
        try:
            return b''.join([part async for part in response.body_iterator])
        finally:
            if response.background is not None:
                await response.background()

    async def test_partial_stream_and_idempotent_cleanup(self):
        manager = LeaseFixture()
        response = media_response(manager, self.context, 'access_fixture', range_header='bytes=2-5')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers['content-range'], 'bytes 2-5/10')
        self.assertEqual(response.headers['content-length'], '4')
        self.assertEqual(await self.consume(response), b'2345')
        await response.background()
        self.assertEqual((manager.opens, manager.closes), (1, 1))
        self.assertEqual(manager.context, self.context)

    async def test_if_range_mismatch_returns_whole_representation(self):
        manager = LeaseFixture()
        response = media_response(manager, self.context, 'access_fixture',
                                  range_header='bytes=2-5', if_range='"different"')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('content-range', response.headers)
        self.assertEqual(await self.consume(response), manager.payload)

    async def test_head_ignores_range_and_closes_before_return(self):
        manager = LeaseFixture()
        response = media_response(manager, self.context, 'access_fixture', method='HEAD', range_header='bytes=2-5')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-length'], '10')
        self.assertEqual(response.body, b'')
        self.assertEqual(manager.closes, 1)

    async def test_unsatisfiable_range_has_no_bytes_and_closes(self):
        manager = LeaseFixture()
        response = media_response(manager, self.context, 'access_fixture', range_header='bytes=10-')
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.headers['content-range'], 'bytes */10')
        self.assertEqual(response.body, b'')
        self.assertEqual(manager.closes, 1)

    async def test_empty_media(self):
        manager = LeaseFixture(payload=b'')
        response = media_response(manager, self.context, 'access_fixture')
        self.assertEqual(response.headers['content-length'], '0')
        self.assertEqual(await self.consume(response), b'')
        self.assertEqual(manager.closes, 1)

    async def test_active_content_cannot_be_served_inline(self):
        manager = LeaseFixture(mime='image/svg+xml')
        response = media_response(manager, self.context, 'access_fixture')
        self.assertEqual(response.headers['content-type'], 'application/octet-stream')
        self.assertTrue(response.headers['content-disposition'].startswith('attachment;'))
        self.assertNotIn('../', response.headers['content-disposition'])
        self.assertIn('sandbox', response.headers['content-security-policy'])
        await self.consume(response)

    async def test_cancelled_stream_cleanup(self):
        manager = LeaseFixture(payload=b'x' * 100000)
        response = media_response(manager, self.context, 'access_fixture')
        await anext(response.body_iterator)
        await response.background()
        self.assertEqual(manager.closes, 1)

    async def test_invalid_metadata_closes_lease(self):
        manager = LeaseFixture()
        original = manager.open_access

        @contextmanager
        def invalid(context, access_id):
            with original(context, access_id) as (stream, metadata):
                yield stream, {**metadata, 'sha256': 'not-a-hash'}

        manager.open_access = invalid
        with self.assertRaises(ValueError):
            media_response(manager, self.context, 'access_fixture')
        self.assertEqual(manager.closes, 1)

    async def test_conditional_read_reauthenticates_and_returns_no_bytes(self):
        manager = LeaseFixture()
        validator = '"' + hashlib.sha256(manager.payload).hexdigest() + '"'
        response = media_response(manager, self.context, 'access_fixture', if_none_match=validator)
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.body, b'')
        self.assertEqual((manager.opens, manager.closes), (1, 1))

    async def test_range_is_not_a_conditional_304(self):
        manager = LeaseFixture()
        validator = '"' + hashlib.sha256(manager.payload).hexdigest() + '"'
        response = media_response(manager, self.context, 'access_fixture',
                                  range_header='bytes=2-5', if_none_match=validator)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(await self.consume(response), b'2345')
