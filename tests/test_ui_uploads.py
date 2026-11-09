"""Deferred binary-upload transport regressions; execute only after code gate."""
import base64
import hashlib
import json
import unittest
import uuid

from studio.contracts import ContractError
from studio.ui_uploads import chunk_headers, verify_chunk

try:
    from starlette.datastructures import Headers
except ImportError:
    Headers = None


@unittest.skipIf(Headers is None, 'Host HTTP test dependencies are not installed')
class UploadHeaderTests(unittest.TestCase):
    def setUp(self):
        self.payload = b'fixture upload bytes'
        self.scope = dict(backend_instance_id='backend_fixture', connection_id='local',
                          profile_id='profile_fixture', native_project_id='project_fixture')
        self.values = {
            'content-type': 'application/octet-stream',
            'content-length': str(len(self.payload)),
            'content-range': f'bytes 0-{len(self.payload) - 1}/{len(self.payload)}',
            'digest': 'sha-256=' + base64.b64encode(hashlib.sha256(self.payload).digest()).decode('ascii'),
            'x-motion-scope': json.dumps(self.scope),
            'x-motion-command-id': str(uuid.uuid4()),
            'idempotency-key': str(uuid.uuid4()),
            'x-motion-upload-revision': '1',
        }

    def decode(self, values=None):
        assert Headers is not None
        return chunk_headers(Headers(self.values if values is None else values), json.loads)

    def test_exact_bytes_bind_frozen_command_metadata(self):
        command = self.decode()
        self.assertEqual(command['scope'], self.scope)
        self.assertEqual(command['preconditions'], {'entity_revision': 1})
        self.assertEqual(command['input']['sha256'], hashlib.sha256(self.payload).hexdigest())
        self.assertNotIn('binary_upload_chunk', command)
        verify_chunk(command, self.payload)

    def test_changed_same_length_body_rejected(self):
        changed = b'x' * len(self.payload)
        with self.assertRaises(ContractError) as caught:
            verify_chunk(self.decode(), changed)
        self.assertEqual(caught.exception.code, 'DIGEST_MISMATCH')

    def test_truncated_body_rejected(self):
        with self.assertRaises(ContractError) as caught:
            verify_chunk(self.decode(), self.payload[:-1])
        self.assertEqual(caught.exception.code, 'RANGE_INVALID')

    def test_oversized_or_invalid_lengths_rejected_before_body(self):
        for length in ('0', '9999999999', '-1', '+1', '1.0', ''):
            with self.subTest(length=length), self.assertRaises(ContractError):
                self.decode({**self.values, 'content-length': length})

    def test_range_must_match_length_and_total(self):
        for content_range in ('bytes 2-1/9', 'bytes 0-1/1', 'bytes 0-1/99', 'items 0-1/2', 'bytes 0-1/*'):
            with self.subTest(content_range=content_range), self.assertRaises(ContractError):
                self.decode({**self.values, 'content-range': content_range})

    def test_duplicate_command_header_rejected(self):
        assert Headers is not None
        raw = [(name.encode('ascii'), value.encode('ascii')) for name, value in self.values.items()]
        raw.append((b'x-motion-command-id', self.values['x-motion-command-id'].encode('ascii')))
        with self.assertRaises(ContractError):
            chunk_headers(Headers(raw=raw), json.loads)

    def test_invalid_digests_and_noncanonical_uuids_rejected(self):
        for digest in ('sha-256=invalid', 'sha-512=' + 'A' * 44, 'sha-256=' + 'A' * 44):
            with self.subTest(digest=digest), self.assertRaises(ContractError):
                self.decode({**self.values, 'digest': digest})
        with self.assertRaises(ContractError):
            self.decode({**self.values, 'x-motion-command-id': 'not-a-uuid'})

    def test_missing_scope_cannot_default_to_another_project(self):
        missing = {k: v for k, v in self.values.items() if k != 'x-motion-scope'}
        with self.assertRaises(ContractError):
            self.decode(missing)
        with self.assertRaises(ContractError):
            self.decode({**self.values, 'x-motion-scope': '[]'})

    def test_transport_cannot_be_disguised_as_json(self):
        with self.assertRaises(ContractError):
            self.decode({**self.values, 'content-type': 'application/json'})
