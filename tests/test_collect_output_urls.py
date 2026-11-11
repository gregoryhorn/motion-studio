"""Synthetic provider responses; never contacts a provider or generates media."""
import base64
import io
import struct
import unittest
import zlib
from unittest.mock import patch
from urllib.request import Request

from studio.domain import Fault, MAX_BYTES
from studio.native.creation import hermes as sources
from tests import test_collect_output as local_tests
from tests.media_import_fixtures import png
from tests.duration_fixtures import encoded


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, url, headers=None):
        super().__init__(data)
        self.url = url
        self.headers = headers or {}

    def geturl(self):
        return self.url


class ProviderOutputTests(unittest.TestCase):
    setUp = local_tests.CollectOutputTests.setUp
    rpc = local_tests.CollectOutputTests.rpc
    tool = local_tests.CollectOutputTests.tool
    prepare = local_tests.CollectOutputTests.prepare

    def remote_collect(self, row, **source):
        return self.tool('collect_output', request=row['request'], submission=row['submission'],
                         attempt=row['attempt'], tool=source.pop('tool', 'image_generate'), **source)

    def test_https_video_and_image_retention_and_idempotency(self):
        parent = None
        for kind, tool, data in [('Image', 'image_generate', png()),
                                 ('Video', 'video_generate', encoded('mp4'))]:
            row = self.prepare(kind, **({'parent': parent} if parent else {}))
            url = 'https://files-cdn.x.ai/controlled-output'
            with patch.object(sources, 'urlopen', side_effect=lambda *a, **kw: Response(data, url)) as opened:
                first = self.remote_collect(row, url=url, tool=tool)
                self.assertNotIn('error', first)
                self.assertEqual(first, self.remote_collect(row, url=url, tool=tool))
                request = opened.call_args.args[0]
                self.assertEqual(request.header_items(), [('Accept-encoding', 'identity')])
                self.assertEqual(opened.call_args.kwargs['timeout'], 60)
            retained, _ = self.runtime.service.assets.retrieve(first['take'])
            self.assertEqual(retained, data)
            self.assertEqual(len(self.rpc('status')['takes']), 1)
            parent = row['request']

    def test_base64_image_and_schema_source_exclusivity(self):
        row = self.prepare()
        # Exercise the registered tool above its old 8 KiB request cap with
        # an actual valid PNG, including a non-private ancillary text chunk.
        text = b'fixture\x00' + b'x' * 10000
        chunk = (struct.pack('>I', len(text)) + b'tEXt' + text
                 + struct.pack('>I', zlib.crc32(b'tEXt' + text)))
        image = png()[:-12] + chunk + png()[-12:]
        data = base64.b64encode(image).decode()
        first = self.remote_collect(row, data=data)
        self.assertNotIn('error', first)
        self.assertEqual(self.runtime.service.assets.retrieve(first['take'])[0], image)
        self.assertEqual(first, self.remote_collect(row, data='data:image/png;base64,' + data))
        for source in ({}, dict(path='/tmp/a', url='https://files-cdn.x.ai/a'),
                       dict(data=data, url='https://files-cdn.x.ai/a'), dict(data='!!')):
            self.assertEqual(self.remote_collect(row, **source)['error'], 'INVALID_CREATION_INPUT')
        self.assertEqual(self.remote_collect(row, data=data, tool='video_generate')['error'], 'INVALID_CREATION_INPUT')

    def test_disallowed_urls_never_open_network(self):
        row = self.prepare()
        for url in ('http://files-cdn.x.ai/a', 'https://127.0.0.1/a', 'https://[::1]/a',
                    'https://localhost/a', 'https://x.ai.evil.example/a', 'https://evilx.ai/a',
                    'https://user:secret@files-cdn.x.ai/a', 'https://files-cdn.x.ai:444/a',
                    'https://files-cdn.x.ai/a\nInjected: header'):
            with self.subTest(url=url), patch.object(sources, 'urlopen') as opened:
                self.assertEqual(self.remote_collect(row, url=url)['error'], 'HERMES_OUTPUT_URL_DENIED')
                opened.assert_not_called()

    def test_redirect_invalid_media_size_and_network_failures(self):
        row = self.prepare()
        url = 'https://files-cdn.x.ai/a.png'
        for response, expected in (
            (Response(png(), 'https://localhost/a'), 'HERMES_OUTPUT_URL_DENIED'),
            (Response(png(), 'https://other.x.ai/a'), 'HERMES_OUTPUT_URL_DENIED'),
            (Response(b'not media', url), 'UNSUPPORTED_MEDIA'),
            (Response(b'\x89PNG\r\n\x1a\ninvalid', url), 'MALFORMED_MEDIA'),
            (Response(b'x', url, {'Content-Length': str(MAX_BYTES + 1)}), 'FILE_TOO_LARGE'),
            (Response(b'x' * (MAX_BYTES + 1), url), 'FILE_TOO_LARGE'),
            (Response(png(), url, {'Content-Length': '9999'}), 'HERMES_OUTPUT_DOWNLOAD_FAILED'),
        ):
            with patch.object(sources, 'urlopen', return_value=response):
                result = self.remote_collect(row, url=url)
                self.assertEqual(result.get('error'), expected, result)
        with patch.object(sources, 'urlopen', side_effect=TimeoutError):
            self.assertEqual(self.remote_collect(row, url=url)['error'], 'HERMES_OUTPUT_DOWNLOAD_FAILED')
        self.assertEqual(self.rpc('status')['takes'], [])


class SourcePolicyTests(unittest.TestCase):
    def test_provider_domains_and_redirect_handler(self):
        for host in ('files-cdn.x.ai', 'cdn.x.ai', 'oaiusercontent.com', 'a.openai.com',
                     'v3.fal.media', 'fal.run', 'api.deepinfra.com', 'api.krea.ai'):
            self.assertEqual(sources.checked_url('https://' + host + '/a').hostname, host)
        handler = sources.ProviderRedirects()
        request = Request('https://files-cdn.x.ai/a')
        self.assertEqual(handler.redirect_request(request, None, 302, '', {},
                         'https://files-cdn.x.ai/b').full_url, 'https://files-cdn.x.ai/b')
        for target in ('https://localhost/a', 'http://files-cdn.x.ai/a', 'https://other.x.ai/a'):
            with self.assertRaises(Fault):
                handler.redirect_request(request, None, 302, '', {}, target)

    def test_base64_size_limit_and_download_deadline(self):
        with self.assertRaises(Fault) as caught:
            sources.image_data('A' * (sources.MAX_BASE64 + 1))
        self.assertEqual(caught.exception.code, 'FILE_TOO_LARGE')
        url = 'https://files-cdn.x.ai/a'
        with patch.object(sources, 'urlopen', return_value=Response(png(), url)), \
                patch.object(sources.time, 'monotonic', side_effect=[0, 61]):
            with self.assertRaises(Fault) as caught:
                sources.download(url)
        self.assertEqual(caught.exception.code, 'HERMES_OUTPUT_DOWNLOAD_FAILED')
