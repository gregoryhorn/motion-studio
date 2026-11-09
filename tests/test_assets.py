"""Focused B04 tests; all runtime data stays in owned scratch fixtures."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from studio.project import ProjectStore
from studio.assets import AssetStore, AssetRegistry, asset_tool_schema


def rid():
    return str(uuid.uuid4())


def provenance():
    return {'origin': 'user_import', 'acquired_at': '2026-11-05T00:00:00Z',
            'source_locator': None, 'provider': None, 'model': None,
            'model_version': None, 'seed': None, 'deterministic': 'unknown',
            'rights': {'status': 'unknown', 'license': None, 'attribution': None,
                       'evidence': []}, 'notes': 'Controlled local test input.'}


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'], prefix='motion-b04-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'store'
        self.source = Path(self.tmp.name) / 'input.txt'
        self.source.write_bytes(b'original asset bytes\n')
        self.store = AssetStore(root=self.root)
        created = ProjectStore(root=self.root).dispatch({'action': 'create', 'request_id': rid(), 'name': 'Asset fixture'})
        self.assertTrue(created['ok'], created)
        self.pid = created['project_id']

    def request(self, action='import', revision=1):
        return {'action': action, 'project_id': self.pid, 'request_id': rid(),
                'expected_revision': revision, 'source': {'kind': 'local', 'path': str(self.source)},
                'label': 'Input', 'kind': 'media', 'provenance': provenance()}

    def get(self, aid):
        return self.store.dispatch({'action': 'get', 'project_id': self.pid, 'asset_id': aid})

    def test_copy_and_reference_restart_pagination_and_changed_bytes(self):
        original = self.source.read_bytes()
        copied = self.store.dispatch(self.request())
        self.assertTrue(copied['ok'], copied)
        asset = copied['data']['asset']
        detail = self.get(asset['asset_id'])
        self.assertEqual(detail['data']['latest_probe'], None)
        artifact = detail['data']['artifact']
        staged = self.root / 'projects' / self.pid / artifact['storage']['relative_path']
        self.assertEqual(staged.read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), original)
        reference = self.store.dispatch(self.request('reference', 2))
        self.assertTrue(reference['ok'], reference)
        self.store = AssetStore(root=self.root)
        first = self.store.dispatch({'action': 'list', 'project_id': self.pid, 'limit': 1})['data']
        self.assertEqual(first['total'], 2)
        second = self.store.dispatch({'action': 'list', 'project_id': self.pid, 'cursor': first['next_cursor']})['data']
        self.assertEqual(len(second['items']), 1)
        self.assertFalse(second['has_more'])
        self.source.write_bytes(b'changed original\n')
        self.assertTrue(self.get(asset['asset_id'])['ok'])
        changed = self.get(reference['data']['asset']['asset_id'])
        self.assertEqual(changed['error']['code'], 'ASSET_CHANGED')
        staged.write_bytes(b'changed managed payload')
        self.assertEqual(self.get(asset['asset_id'])['error']['code'], 'HASH_MISMATCH')

    def test_artifact_context_preserves_consumer_errors_and_checks_mutation(self):
        from studio.contracts import ContractError
        accepted = self.store.dispatch(self.request())
        self.assertTrue(accepted['ok'], accepted)
        record = self.get(accepted['data']['asset']['asset_id'])['data']['artifact']
        registry = AssetRegistry(self.store)
        for error in (ContractError('MEDIA_TRANSPORT_UNAVAILABLE', 'Consumer refused'),
                      OSError('Consumer operation failed')):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)) as caught:
                    with registry.open_artifact(self.store._filesystem(), record):
                        raise error
                self.assertIs(caught.exception, error)
        staged = self.root / 'projects' / self.pid / record['storage']['relative_path']
        with self.assertRaises(ContractError) as caught:
            with registry.open_artifact(self.store._filesystem(), record):
                staged.write_bytes(b'changed during use')
        self.assertEqual(caught.exception.code, 'HASH_MISMATCH')

    def test_cas_idempotency_and_no_publication_on_bad_input(self):
        request = self.request()
        accepted = self.store.dispatch(request)
        self.assertTrue(accepted['ok'], accepted)
        self.source.unlink()  # Replay must not reopen an already accepted source.
        self.assertEqual(self.store.dispatch(request)['data'], accepted['data'])
        changed = {**request, 'action': 'reference'}
        self.assertEqual(self.store.dispatch(changed)['error']['code'], 'IDEMPOTENCY_CONFLICT')
        stale = self.request()
        self.assertEqual(self.store.dispatch(stale)['error']['code'], 'REVISION_CONFLICT')
        self.assertEqual(ProjectStore(root=self.root).dispatch({'action': 'open', 'project_id': self.pid})['project_revision'], 2)

    def test_strict_paths_rights_and_probe_boundary(self):
        for source in [{'kind': 'remote', 'url': 'https://example.invalid/input'},
                       {'kind': 'local', 'path': 'relative/file'},
                       {'kind': 'local', 'path': str(self.source.parent) + '/../input.txt'}]:
            result = self.store.dispatch({**self.request(), 'source': source})
            self.assertFalse(result['ok'], result)
        link = self.source.with_name('link')
        link.symlink_to(self.source)
        self.assertEqual(self.store.dispatch({**self.request(), 'source': {'kind': 'local', 'path': str(link)}})['error']['code'], 'PATH_UNSAFE')
        bad = self.request()
        bad['provenance']['rights']['status'] = 'approved'
        self.assertFalse(self.store.dispatch(bad)['ok'])
        accepted = self.store.dispatch(self.request())
        self.assertTrue(accepted['ok'], accepted)
        probe = {'action': 'probe', 'project_id': self.pid, 'expected_revision': 2,
                 'request_id': rid(), 'artifact': accepted['data']['asset']['artifact'],
                 'adapter_id': 'local.ffprobe'}
        result = self.store.dispatch(probe)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['error']['code'], 'UNSUPPORTED_FEATURE')
        self.assertEqual(result['error']['effect'], 'none')
        self.assertNotIn('job', result.get('data', {}))
        self.assertIn('oneOf', asset_tool_schema()['parameters'])


if __name__ == '__main__':
    unittest.main()
