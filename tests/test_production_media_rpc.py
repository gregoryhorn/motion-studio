"""Exercise native registration with real temporary Store/media, no producer calls."""
import base64
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from studio.domain import SaveRequest
from studio.persistence.primitives import identity
from tests.production_support import production_setup
from tests.test_production_export import wav


class ProductionMediaRPCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx, self.creation, self.runtime, _ = production_setup(Path(self.temp.name))
        assert self.creation.store is not None
        self.addCleanup(self.creation.unload)
        self.data = wav()
        self.request = self.creation.store.save(SaveRequest(command=identity(), expected=0,
            text='Controlled import fixture', kind='Sound effects'))['id']
        with self.creation.store.transaction() as db:
            db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                (self.request, 'canonical-root', self.creation.policy.revision, identity(),
                 '{}', None, 'test_import', 0))

    def rpc(self, operation, payload=None, root='canonical-root'):
        return self.ctx.methods['production.' + operation](payload or {}, session_id=root)

    def imported(self):
        result = self.rpc('media_import.begin', dict(command=identity(), request=self.request,
            revision=1, digest=hashlib.sha256(self.data).hexdigest(), size=len(self.data),
            name='controlled.wav', format='wav'))
        self.assertNotIn('error', result, result)
        uploaded = self.rpc('media_import.chunk', dict(id=result['id'], offset=0,
            data=base64.b64encode(self.data).decode()))
        self.assertEqual(uploaded['received'], len(self.data))
        self.assertEqual(self.rpc('media_import.status', dict(id=result['id']))['received'], len(self.data))
        self.assertEqual(self.rpc('media_import.commit', dict(id=result['id']))['status'], 'Ready for review')
        return result

    def selected(self):
        receipt = self.imported()
        current = self.rpc('create', dict(command=identity(), kinds=['Sound effects']))['current']
        for operation in ('link_take', 'select_take'):
            current = self.rpc(operation, dict(command=identity(), production=current['id'],
                expected=current['revision'], asset=current['assets'][0]['id'], request=self.request,
                take=receipt['take']))['current']
        return receipt, current

    def test_import_intent_without_chat_generation_request(self):
        current = self.rpc('create', dict(command=identity(), kinds=['Image', 'Music']))['current']
        for asset in current['assets']:
            payload = dict(command=identity(), production=current['id'], expected=current['revision'], asset=asset['id'])
            intent = self.rpc('media_import.intent', payload)
            self.assertNotIn('error', intent)
            self.assertEqual(intent['kind'], asset['kind'])
            self.assertEqual(intent['method'], 'import')
            self.assertEqual(self.rpc('media_import.intent', payload), intent)
            status = self.ctx.methods['creation.status'](dict(request=intent['request']), session_id='canonical-root')
            self.assertEqual(status['state'], 'Awaiting import')
            with self.creation.store.transaction() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM local_runs').fetchone()[0], 0)
            bad = dict(payload, command=identity(), expected=current['revision'] + 1)
            self.assertEqual(self.rpc('media_import.intent', bad)['error'], 'PRODUCTION_STALE_REVISION')
            self.assertIn('error', self.rpc('media_import.intent', payload, root='foreign'))

    def test_import_describe_review_and_export_exact_bytes(self):
        receipt, current = self.selected()
        descriptor = self.rpc('media_import.describe', dict(take=receipt['take']))
        self.assertEqual(descriptor['byteLength'], len(self.data))
        association = dict(production=current['id'], asset=current['assets'][0]['id'],
                           request=self.request, take=receipt['take'])
        linked = self.rpc('describe', association)
        self.assertEqual(linked['identity']['asset'], association['asset'])
        chunk = self.rpc('media_import.read_chunk', dict(take=receipt['take'], offset=0))
        self.assertEqual(base64.b64decode(chunk['bytes']), self.data)
        prepared = self.rpc('export.prepare', dict(production=current['id'], expected=current['revision'],
            assets=[association['asset']], mode='zip'))
        self.assertNotIn('error', prepared, prepared)
        self.assertEqual(self.rpc('export.descriptor', dict(take=prepared['take'])), prepared)
        data = base64.b64decode(self.rpc('export.chunk', dict(take=prepared['take'], offset=0))['bytes'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.read(archive.namelist()[0]), self.data)
        self.assertTrue(self.rpc('export.close', dict(take=prepared['take']))['closed'])
        self.assertIn('error', self.rpc('export.chunk', dict(take=prepared['take'], offset=0)))

    def test_scope_profile_unknown_fields_and_revocation_deny(self):
        receipt = self.imported()
        self.assertIn('error', self.rpc('media_import.status', dict(id=receipt['id']), root='other'))
        self.assertEqual(self.rpc('media_import.describe', dict(take=receipt['take'],
            profile='wrong'))['error'], 'PRODUCTION_SCOPE_DENIED')
        self.assertEqual(self.rpc('media_import.describe', dict(take=receipt['take'],
            session_id='other'))['error'], 'PRODUCTION_SCOPE_DENIED')
        self.assertEqual(self.rpc('media_import.describe', dict(take=receipt['take'],
            path='forbidden'))['error'], 'INVALID_MEDIA_PAYLOAD')
        self.runtime.association = replace(self.runtime.association, production_management=False)
        self.assertEqual(self.rpc('media_import.describe', dict(take=receipt['take']))['error'],
                         'PRODUCTION_ACCESS_UNAVAILABLE')

    def test_export_stale_revision_and_inflight_revision_change_deny(self):
        _, current = self.selected()
        payload = dict(production=current['id'], expected=current['revision'],
                       assets=[current['assets'][0]['id']])
        self.assertEqual(self.rpc('export.prepare', dict(payload, expected=1))['error'],
                         'PRODUCTION_STALE_REVISION')
        prepared = self.rpc('export.prepare', payload)
        self.rpc('update_brief', dict(command=identity(), production=current['id'],
            expected=current['revision'], brief=dict(text='Changed controlled fixture')))
        self.assertEqual(self.rpc('export.chunk', dict(take=prepared['take'], offset=0))['error'],
                         'EXPORT_REVISION_CONFLICT')
        self.assertTrue(self.rpc('export.close', dict(take=prepared['take']))['closed'])

    def test_cancel_and_chunk_bound(self):
        receipt = self.rpc('media_import.begin', dict(command=identity(), request=self.request,
            revision=1, digest=hashlib.sha256(self.data).hexdigest(), size=len(self.data),
            name='controlled.wav', format='wav'))
        self.assertEqual(self.rpc('media_import.cancel', dict(id=receipt['id']))['status'], 'Cancelled')
        self.assertEqual(self.rpc('media_import.chunk', dict(id=receipt['id'], offset=0,
            data='A' * 270001))['error'], 'INVALID_PRODUCTION_INPUT')


if __name__ == '__main__':
    unittest.main()
