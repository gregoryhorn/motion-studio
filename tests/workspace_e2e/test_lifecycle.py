"""C09 and bounded C10 API evidence. Controlled fixtures are NOT Windows proof."""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from studio.domain import Fault, ImportIntent
from studio.persistence.primitives import identity
from tests.workspace_e2e.fixture import WorkspaceFixture, controlled_wav


class WorkspaceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workspace-api-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.fixture = WorkspaceFixture(self.temp.name)
        self.addCleanup(self.fixture.close)

    def rpc(self, operation, payload=None, root='session-a'):
        return self.fixture.rpc('production.' + operation, payload, root)

    def mutate(self, operation, current, **fields):
        result = self.rpc(operation, dict(command=identity(), production=current['id'],
                                         expected=current['revision'], **fields))
        self.assertNotIn('error', result, result)
        return result['current']

    def create(self):
        result = self.rpc('create', dict(command=identity(), title='Controlled production',
            brief=dict(text='Controlled integrated lifecycle'),
            kinds=['Sound effects', 'Music', 'Voice', 'Image', 'Video']))
        self.assertNotIn('error', result, result)
        return result['current']

    def linked(self):
        first, second = self.fixture.seed(), self.fixture.seed(1400)
        current = self.create()
        asset = current['assets'][0]['id']
        for source in (first, second):
            current = self.mutate('link_take', current, asset=asset,
                                  request=source['request'], take=source['take'])
        return current, asset, first, second

    def test_integrated_brief_reference_plan_selection_exact_bytes_and_reopen(self):
        current, asset, first, second = self.linked()
        baseline = self.fixture.counts()
        self.assertIsNone(current['assets'][0]['selected_take'])
        current = self.mutate('select_take', current, asset=asset,
                              request=first['request'], take=first['take'])
        current = self.mutate('add_reference', current, request=first['request'],
                              take=first['take'], label='Controlled reference')
        reference = current['references'][0]['id']
        current = self.mutate('update_asset', current, asset=asset, kind='Sound effects',
                              intent='Use exact retained audio', references=[reference], depends_on=[])
        current = self.mutate('select_take', current, asset=asset,
                              request=first['request'], take=first['take'])
        current = self.mutate('update_reference', current, reference=reference,
                              request=second['request'], take=second['take'], label='Revised reference')
        self.assertTrue(current['assets'][0]['stale'])
        self.assertFalse(current['assets'][1]['stale'])
        self.assertEqual(current['assets'][0]['selected_take'], first['take'])
        stale = self.rpc('select_take', dict(command=identity(), production=current['id'],
            expected=1, asset=asset, request=second['request'], take=second['take']))
        self.assertEqual(stale['error'], 'PRODUCTION_STALE_REVISION')
        self.assertEqual(self.rpc('open', dict(production=current['id']))['current'], current)
        chunk = self.rpc('chunk', dict(production=current['id'], asset=asset,
            request=first['request'], take=first['take'], offset=0))
        data = base64.b64decode(chunk['bytes'])
        self.assertEqual(data, base64.b64decode(first['bytes']))
        self.assertEqual(hashlib.sha256(data).hexdigest(), chunk['sha256'])
        self.fixture.reopen()
        self.assertEqual(self.rpc('open', dict(production=current['id']))['current'], current)
        after = self.fixture.counts()
        for key in ('requests', 'takes', 'local_runs', 'media_files'):
            self.assertEqual(after[key], baseline[key])
        self.assertEqual(after['generator_calls'], 0)
        with self.fixture.store.transaction() as db:
            self.assertIsNone(self.fixture.store.request(db, first['request'])['selected'])

    def test_lost_create_ack_replay_after_cold_reopen_does_not_duplicate(self):
        payload = dict(command=identity(), title='Controlled lost reply', kinds=['Image'])
        delivered = self.rpc('create', payload)
        before = self.fixture.counts()
        self.fixture.reopen()  # No client-known Production ID is needed to recover create.
        replay = self.rpc('create', payload)
        self.assertEqual(replay['current']['id'], delivered['current']['id'])
        self.assertEqual(self.fixture.counts(), before)
        conflict = self.rpc('create', dict(payload, title='Different payload'))
        self.assertEqual(conflict['error'], 'COMMAND_CONFLICT')

    def test_scope_profile_and_unlinked_output_refuse_without_mutation(self):
        current, asset, first, _ = self.linked()
        before = self.fixture.counts()
        self.fixture.ctx.methods['creation.admit']({}, session_id='other-root')
        self.rpc('admit', root='other-root')
        denied = self.rpc('open', dict(production=current['id']), root='other-root')
        self.assertEqual(denied['error'], 'PRODUCTION_SCOPE_DENIED')
        denied = self.rpc('chunk', dict(production=current['id'], asset=current['assets'][3]['id'],
            request=first['request'], take=first['take'], offset=0))
        self.assertEqual(denied['error'], 'PRODUCTION_TAKE_NOT_LINKED')
        self.fixture.ctx.profile_name = 'different-profile'
        self.assertIn('error', self.rpc('open', dict(production=current['id'])))
        self.fixture.ctx.profile_name = 'offline-fixture'
        self.assertEqual(self.fixture.counts(), before)

    def test_cancelled_import_cannot_publish_take_or_bytes(self):
        source = self.fixture.seed()
        data = controlled_wav(2100)
        assets = self.fixture.assets
        intent = assets.intent(ImportIntent(command=identity(), request=source['request'], revision=1,
            digest=hashlib.sha256(data).hexdigest(), size=len(data), name='cancelled.wav'))
        before = self.fixture.counts()
        self.assertEqual(assets.cancel(intent['id'])['status'], 'Cancelled')
        with self.assertRaises(Fault) as caught:
            assets.upload(intent['id'], data)
        self.assertEqual(caught.exception.code, 'IMPORT_CANCELLED')
        self.assertEqual(self.fixture.counts(), before)
        self.assertFalse(assets.path('media', intent['id'], '.wav').exists())

    def test_generator_trap_is_sensitive(self):
        with self.assertRaisesRegex(AssertionError, 'WORKSPACE_GENERATOR_FORBIDDEN'):
            self.fixture.runs.start(None, None)
        self.assertEqual(self.fixture.generator_calls, 1)

    def test_owned_private_state_directory_is_removed(self):
        with tempfile.TemporaryDirectory(prefix='workspace-cleanup-', dir=os.environ.get('TMPDIR')) as temp:
            fixture = WorkspaceFixture(temp)
            try:
                fixture.seed()
                home = fixture.store.home
                self.assertTrue(home.is_dir())
            finally:
                fixture.close()
        self.assertFalse(Path(temp).exists())
        self.assertFalse(home.exists())


if __name__ == '__main__':
    unittest.main()
