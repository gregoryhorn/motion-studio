"""CF-B2 existing app-auth boundary and same-artifact delivery, offline only."""
import contextlib
import hashlib
import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.http_support import TestClient
from studio.persistence.store import identity
from studio.producer.local_sfx import Binding
from studio.server import create_app
from tests.producer_support import fixture_binding, wait_run, effects

ORIGIN = 'http://testserver'
SECRET = b'non-private-offline-test-credential-only'


class ProducerAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binding = fixture_binding(self.root / 'tool')
        self.app = create_app(self.root / 'var', SECRET, ORIGIN, _test_binding=self.binding)
        self.client = TestClient(self.app)
        self.auth()

    def tearDown(self):
        self.app.state.runs.close()
        self.client.close()
        self.temp.cleanup()

    def auth(self):
        response = self.client.post('/api/login', json={'secret': SECRET.decode()}, headers={'origin': ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.client.headers.update({'origin': ORIGIN, 'x-csrf-token': response.json()['csrf']})

    def plan(self):
        saved = self.client.post('/api/requests', json=dict(command=identity(), expected=0,
                                 text='Non-private SFX API test', purpose='Offline only', kind='Sound effects')).json()
        payload = dict(command=identity(), request=saved['id'], revision=1, seconds=0.1, seed=7)
        response = self.client.post('/api/sfx/plans', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), payload

    def test_auth_csrf_unknown_scope_and_extra_fields_zero_starts(self):
        item, payload = self.plan()
        run = item['id']
        path = f'/api/sfx/runs/{run}/start'
        self.assertEqual(self.client.post(path, json={}, headers={'x-csrf-token':'bad'}).status_code, 403)
        self.assertEqual(self.client.post(path, json={}, headers={'origin':'https://evil.invalid'}).status_code, 403)
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.post(path, json={}, headers={'origin':ORIGIN}).status_code, 401)
            self.assertEqual(anonymous.get(f'/api/sfx/runs/{run}').status_code, 401)
        # A lifecycle close on this test client is not an execution grant; rebuild idle app.
        self.app = create_app(self.root / 'var', SECRET, ORIGIN, _test_binding=self.binding)
        self.client.close()
        self.client = TestClient(self.app)
        self.auth()
        self.assertEqual(self.client.get(f'/api/sfx/runs/{identity()}').status_code, 404)
        self.assertEqual(self.client.post(path, content='{"command":1,"command":2}',
                                         headers={'content-type':'application/json'}).status_code, 422)
        self.assertEqual(self.client.post(path, content=b'x' * 16385).status_code, 413)
        for extra in ('owner', 'path', 'executable', 'env', 'receipt', 'session', 'profile', 'url'):
            response = self.client.post('/api/sfx/plans', json={**payload, 'command':identity(), extra:'deny'})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.client.post(path, json={extra:'deny'}).status_code, 422)
        self.assertEqual(self.client.post('/api/generate', json={'success':True}).status_code, 409)
        self.assertEqual(effects(self.binding), [])
        self.assertEqual(self.client.get('/api/state').json()['takes'], [])

    def test_retention_reauth_same_bytes_and_privacy_safe_projection_logs(self):
        output, logs = io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                item, payload = self.plan()
                self.assertEqual(self.client.post('/api/sfx/plans', json=payload).json()['id'], item['id'])
                response = self.client.post(f'/api/sfx/runs/{item["id"]}/start', json={})
                self.assertEqual(response.status_code, 200)
                row = wait_run(self.app.state.runs, item['id'])
                self.assertEqual(row['status'], 'Ready for review')
                observed = self.client.get(f'/api/sfx/runs/{item["id"]}').json()
                self.assertEqual(observed['origin'], 'test_fixture')
                self.assertIsNone(observed['host_run'])
                for private in ('Non-private SFX API test', str(self.root), '--prompt', 'negative_prompt'):
                    self.assertNotIn(private, str(observed))
                path = f'/api/takes/{item["candidate"]}/media'
                media = self.client.get(path)
                original = media.content
                self.assertEqual(media.status_code, 200)
                self.assertEqual(media.headers['x-artifact-sha256'], hashlib.sha256(original).hexdigest())
                other = self.client.post('/api/requests', json=dict(command=identity(), expected=0,
                    text='Different non-private request', kind='Sound effects')).json()
                self.assertEqual(self.client.post('/api/select', json=dict(command=identity(),
                    request=other['id'], expected=1, take=item['candidate'])).status_code, 403)
                self.assertEqual(self.client.get(path, headers={'Range':'bytes=0-1'}).status_code, 416)
                with self.app.state.store.transaction() as db:
                    db.execute('UPDATE sessions SET expires=0')
                self.assertEqual(self.client.get(path).status_code, 401)
                self.assertEqual(self.client.get(f'/api/sfx/runs/{item["id"]}').status_code, 401)
                self.auth()
                self.assertEqual(self.client.get(path).content, original)
                self.assertEqual(self.client.post('/api/logout', json={}).status_code, 200)
                self.assertEqual(self.client.get(path).status_code, 401)
                self.auth()
                self.assertEqual(self.client.get(path).content, original)
                self.assertEqual(self.client.post('/api/sfx/plans', json=payload).json()['id'], item['id'])
                self.client.post(f'/api/sfx/runs/{item["id"]}/start', json={})
                self.assertEqual(len(self.client.get('/api/state').json()['takes']), 1)
                self.assertEqual(len(effects(self.binding)), 1)
        finally:
            logging.getLogger().removeHandler(handler)
        for private in ('Non-private SFX API test', str(self.root), '--prompt', 'negative_prompt', SECRET.decode()):
            self.assertNotIn(private, output.getvalue() + logs.getvalue())

    def test_new_explicit_plan_keeps_earlier_selection_and_original_pins(self):
        first, payload = self.plan()
        self.client.post(f'/api/sfx/runs/{first["id"]}/start', json={})
        self.assertEqual(wait_run(self.app.state.runs, first['id'])['status'], 'Ready for review')
        selected = self.client.post('/api/select', json=dict(command=identity(), request=payload['request'],
                                    expected=1, take=first['candidate']))
        self.assertEqual(selected.json()['revision'], 2)
        second = self.client.post('/api/sfx/plans', json={**payload, 'command':identity(), 'revision':2, 'seed':8}).json()
        self.client.post(f'/api/sfx/runs/{second["id"]}/start', json={})
        self.assertEqual(wait_run(self.app.state.runs, second['id'])['status'], 'Ready for review')
        state = self.client.get('/api/state').json()
        self.assertEqual(state['requests'][0]['selected'], first['candidate'])
        self.assertEqual(sorted(take['revision'] for take in state['takes']), [1, 2])
        self.assertEqual(len(effects(self.binding)), 2)

    def test_default_binding_disabled_and_fixture_injection_not_http_or_normal_launch(self):
        self.app.state.runs.close()
        production = create_app(self.root / 'production', SECRET, ORIGIN)
        self.client.close()
        self.app = production
        self.client = TestClient(production)
        self.auth()
        with patch.object(Binding, 'executable', side_effect=AssertionError('Must not resolve real wrapper')):
            with patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                item, _ = self.plan()
                self.client.post(f'/api/sfx/runs/{item["id"]}/start', json={})
                row = wait_run(self.app.state.runs, item['id'])
                self.assertEqual(row['status'], 'Blocked')
                self.assertEqual(row['error'], 'FEATURE_DISABLED')
                spawn.assert_not_called()
        state = self.client.get('/api/state').json()
        self.assertFalse(state['local_tool']['enabled'])
        self.assertEqual(state['takes'], [])
        self.assertTrue(all(x['state'] == 'Unavailable' for x in state['capabilities']))
        self.assertEqual(effects(self.binding), [])


if __name__ == '__main__':
    unittest.main()
