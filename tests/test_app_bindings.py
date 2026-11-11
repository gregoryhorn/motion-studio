"""CF-F1 controlled setup/catalog state and authenticated finite plan/selection checks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from tests.http_support import TestClient
from studio.domain import Fault, SaveRequest
from studio.persistence.store import Store, identity
from studio.producer.contracts import PrepareApp
from studio.producer.catalog import Catalog
from studio.runs.service import LocalRuns
from studio.server import create_app
from tests.adapter_fixtures import OfflineCatalog, FixtureA, FixtureB, worker_location, setup
from tests.producer_support import fixture_binding, prepare, wait_run, effects


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = LocalRuns(Store(self.root / 'var'), catalog=OfflineCatalog())
        self.adapter = FixtureB()
        self.path = worker_location(self.root / 'tool', self.adapter)
        self.proposal = dict(adapter=self.adapter.id, adapter_version=1, interface_version=self.adapter.interface,
                             executable=str(self.path))

    def tearDown(self):
        self.runs.close()
        self.temp.cleanup()

    def save(self, value=None, **options):
        return self.runs.bindings.save(value or self.proposal, permitted={str(self.path)}, fixture_only=True, **options)

    def test_setup_cas_unknown_fields_locations_and_no_implicit_effects(self):
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            record = self.save()
            self.assertFalse(record['enabled'])
            self.assertEqual(record['qualification'], 'Setup checked')
            for key in ('env', 'command', 'cwd', 'uri', 'options', 'script'):
                with self.subTest(key=key), self.assertRaises(ValidationError):
                    self.save(dict(self.proposal, **{key: 'deny'}))
            for value in ('relative-worker', str(self.path) + ' --arbitrary', '/not-approved',
                          str(self.path.parent / '..' / 'tool' / 'fixture-worker')):
                with self.subTest(path_case='controlled invalid location'), self.assertRaises(Fault):
                    self.save(dict(self.proposal, executable=value))
            alias = self.root / 'symlink-worker'
            alias.symlink_to(self.path)
            with self.assertRaises(Fault):
                self.runs.bindings.save(dict(self.proposal, executable=str(alias)), permitted={str(alias)}, fixture_only=True)
            for key, value in (('adapter_version', 2), ('interface_version', 'unsupported-v999')):
                with self.assertRaises((ValidationError, Fault)):
                    self.save(dict(self.proposal, **{key: value}))
            with self.assertRaises(Fault) as conflict:
                self.save(binding=record['id'], expected=0)
            self.assertEqual(conflict.exception.code, 'BINDING_CONFLICT')
            request = self.runs.store.save(SaveRequest(command=identity(), expected=0, kind='Sound effects', text='Non-private setup test'))
            self.runs.bindings.select(request['id'], record['id'], record['revision'], 'render-sfx')
            self.runs.bindings.rows()
            self.runs.bindings.check_setup(record['id'], record['revision'])
            self.assertEqual(self.runs.records.rows(), [])
            self.assertFalse((self.path.parent / 'effects.jsonl').exists())
            spawn.assert_not_called()
        for change in ({'schema_version': 99}, {'unknown_field': 'deny'}):
            with self.assertRaises(Fault):
                self.runs.bindings.validate(dict(record, **change))

    def test_truthful_missing_restricted_resource_stale_unsupported_and_offline_states(self):
        record = setup(self.runs, self.adapter, self.path)
        cases = [('RESOURCE_BUSY', 'Unavailable', 'Review current resource issue'),
                 ('USE_RESTRICTED', 'Restricted for this use', 'Choose a suitable local method')]
        for reason, availability, action in cases:
            record = self.runs.bindings.revise(record['id'], record['revision'], reason=reason, availability=availability, action=action)
            public = self.runs.bindings.public(record)
            self.assertEqual((public['availability'], public['reason'], public['action']), (availability, reason, action))
            self.assertEqual(public['descriptor']['media'], ['Sound effects'])
            self.assertEqual(public['descriptor']['operations'], ['render-sfx'])
            self.assertNotIn(str(self.path), str(public))
            self.assertNotEqual(public['availability'], 'Ready')
        self.assertEqual(self.runs.bindings.public(record)['qualification'], 'Offline tested only')
        self.path.write_text(self.path.read_text() + '\n# controlled drift\n')
        stale = self.runs.bindings.check_setup(record['id'], record['revision'])
        self.assertEqual((stale['reason'], stale['qualification'], stale['enabled']), ('RUNTIME_DRIFT', 'Not checked', False))
        self.assertEqual(self.runs.bindings.get(record['id'], record['revision']), record)
        self.path.unlink()
        missing = self.runs.bindings.check_setup(stale['id'], stale['revision'])
        self.assertEqual((missing['availability'], missing['reason']), ('Setup needed', 'APP_MISSING'))
        unsupported = self.runs.catalog.describe('test-render-cli', 1, 'unsupported-v999')
        self.assertEqual(unsupported['availability'], 'Unsupported')
        self.assertTrue(unsupported['action'])
        self.assertEqual(Catalog().describe(FixtureB.id, 1)['availability'], 'Unsupported')
        self.assertFalse((self.path.parent / 'effects.jsonl').exists())

    def test_normal_reopen_cannot_enable_persisted_fixture_or_accept_fixture_setup(self):
        self.runs.close()
        binding = fixture_binding(self.root / 'compat-tool')
        self.runs = LocalRuns(Store(self.root / 'var'), binding)
        item, _ = prepare(self.runs)
        self.runs.close()
        self.runs = LocalRuns(Store(self.root / 'var'))
        with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            self.runs.start(item['id'], lambda: True)
            self.assertEqual(wait_run(self.runs, item['id'])['error'], 'FIXTURE_DENIED')
            spawn.assert_not_called()
        self.assertEqual(effects(binding), [])
        with self.assertRaises(Fault):
            self.runs.bindings.save(self.proposal, permitted={str(self.path)}, fixture_only=True)


class FlexibleAPITests(unittest.TestCase):
    def test_both_adapters_authenticated_typed_envelope_and_same_retrieval_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = b'non-private-F1-isolated-test-credential'
            app = create_app(root / 'var', secret, 'http://testserver', _test_catalog=OfflineCatalog())
            try:
                with TestClient(app) as client:
                    login = client.post('/api/login', json={'secret': secret.decode()}, headers={'origin': 'http://testserver'})
                    client.headers.update({'origin': 'http://testserver', 'x-csrf-token': login.json()['csrf']})
                    for adapter, options in ((FixtureA(), dict(seconds=0.1, seed=1)),
                                             (FixtureB(), dict(frame_count=4410, timbre='soft'))):
                        with self.subTest(adapter=adapter.id):
                            location = worker_location(root / adapter.id, adapter)
                            record = setup(app.state.runs, adapter, location)
                            saved = client.post('/api/requests', json=dict(command=identity(), expected=0,
                                text='Non-private F1 API fixture', kind='Sound effects')).json()
                            body = dict(command=identity(), request=saved['id'], revision=1,
                                        binding=record['id'], binding_revision=record['revision'],
                                        operation=adapter.describe()['operations'][0], options=options)
                            for field in ('path', 'env', 'executable', 'receipt', '_test_catalog', 'output'):
                                self.assertEqual(client.post('/api/apps/plans', json=dict(body, **{field:'deny'})).status_code, 422)
                            self.assertEqual(client.post('/api/apps/plans', json=dict(body, schema_version=99)).status_code, 422)
                            self.assertEqual(client.post('/api/apps/plans', json=dict(body, options=dict(options, env='deny'))).status_code, 422)
                            self.assertEqual(client.post('/api/apps/plans', json=body, headers={'x-csrf-token':'wrong'}).status_code, 403)
                            item = client.post('/api/apps/plans', json=body).json()
                            self.assertEqual(client.post('/api/apps/plans', json=body).json()['id'], item['id'])
                            self.assertEqual(client.post(f'/api/sfx/runs/{item["id"]}/start', json={}).status_code, 200)
                            self.assertEqual(wait_run(app.state.runs, item['id'])['status'], 'Ready for review')
                            replay = client.post('/api/apps/plans', json=body).json()
                            self.assertEqual(replay['status'], 'Ready for review')
                            self.assertEqual(replay['message'], 'Original run restored; no new effect')
                            media = client.get(f'/api/takes/{item["candidate"]}/media')
                            self.assertEqual(media.status_code, 200)
                            self.assertEqual(media.content, (app.state.store.home / 'media' / (item['candidate'] + '.wav')).read_bytes())
                            self.assertEqual(client.get(f'/api/sfx/runs/{item["id"]}').json()['origin'], 'test_fixture')
                            self.assertEqual(len((location.parent / 'effects.jsonl').read_text().splitlines()), 1)
                    catalog = client.get('/api/apps/catalog').json()
                    self.assertNotIn(str(root), str(catalog))
                    self.assertTrue(all(not row['enabled'] for row in catalog['bindings']))
                    self.assertIn('passive', catalog['setup'])
                    self.assertEqual(client.post('/api/apps/bindings', json={'executable':'deny'}).status_code, 422)
            finally:
                app.state.runs.close()
