import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.http_support import TestClient
from studio.domain import KINDS
from studio.server import create_app
from studio.persistence.store import identity
from tests.fixtures import wav, intent_payload

ORIGIN = "http://testserver"
SECRET = b"isolated-non-private-test-secret-only"


class Flow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "var"
        self.app = create_app(self.home, SECRET, ORIGIN)
        self.client = TestClient(self.app)
        self.auth()

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def auth(self):
        response = self.client.post('/api/login', json={'secret': SECRET.decode()}, headers={'origin': ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.client.headers.update({'origin': ORIGIN, 'x-csrf-token': response.json()['csrf']})

    def post(self, path, value):
        return self.client.post(path, json=value)

    def save(self, kind='Sound effects'):
        payload = dict(command=identity(), expected=0, text='Non-private test request', kind=kind, purpose='test')
        response = self.post('/api/requests', payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), payload

    def imported(self, data=None):
        data = wav() if data is None else data
        request, _ = self.save()
        payload = intent_payload(request, data)
        response = self.post('/api/imports', payload)
        self.assertEqual(response.status_code, 200, response.text)
        intent = response.json()
        response = self.client.post(f'/api/imports/{intent["id"]}/bytes', content=data)
        self.assertEqual(response.status_code, 200, response.text)
        return request, intent, payload, data

    def test_five_types_save_replay_conflict_and_unavailable(self):
        for kind in KINDS:
            request, payload = self.save(kind)
            self.assertEqual(self.post('/api/requests', payload).json(), request)
            changed = {**payload, 'text': 'changed'}
            self.assertEqual(self.post('/api/requests', changed).status_code, 409)
            update = {**payload, 'id': request['id'], 'expected': 1, 'command': identity(), 'text': 'Updated'}
            self.assertEqual(self.post('/api/requests', update).json()['revision'], 2)
            update['command'] = identity()
            self.assertEqual(self.post('/api/requests', update).status_code, 409)
            self.assertEqual(self.post('/api/generate', {}).json()['error'], 'GENERATION_UNAVAILABLE')
        state = self.client.get('/api/state').json()
        self.assertEqual(len(state['requests']), len(KINDS))
        self.assertEqual(state['takes'], [])
        self.assertEqual(state['imports'], [])
        self.assertEqual(state['capabilities'][0]['reason'], 'LOCAL_ROUTE_NOT_QUALIFIED')
        self.assertTrue(all(x['reason'] == 'ROUTE_NOT_IMPLEMENTED' for x in state['capabilities'][1:]))

    def test_import_replay_review_selection_lineage_and_retrieval(self):
        request, intent, payload, data = self.imported()
        self.assertEqual(self.post('/api/imports', payload).json(), intent)
        path = f'/api/imports/{intent["id"]}/bytes'
        self.assertEqual(self.client.post(path, content=data).status_code, 200)
        self.assertEqual(self.client.post(path, content=data[:-1]).status_code, 409)
        state = self.client.get('/api/state').json()
        self.assertEqual(len(state['takes']), 1)
        take = state['takes'][0]
        self.assertEqual(take['origin'], 'user_import')
        self.assertEqual(take['review'], 'Not reviewed')
        self.assertIsNone(state['requests'][0]['selected'])
        review = dict(command=identity(), take=take['id'], outcome='Matches request')
        self.assertEqual(self.post('/api/review', review).status_code, 200)
        selection = dict(command=identity(), request=request['id'], expected=1, take=take['id'])
        self.assertEqual(self.post('/api/select', selection).json()['revision'], 2)
        selection['command'] = identity()
        self.assertEqual(self.post('/api/select', selection).status_code, 409)
        update = dict(command=identity(), id=request['id'], expected=2, text='New direction', kind='Music')
        self.assertEqual(self.post('/api/requests', update).status_code, 200)
        self.assertEqual(self.client.get('/api/state').json()['takes'][0]['revision'], 1)
        response = self.client.get(f'/api/takes/{take["id"]}/media?download=true')
        self.assertEqual(response.content, data)
        self.assertEqual(response.headers['x-artifact-sha256'], hashlib.sha256(data).hexdigest())
        self.assertIn('attachment', response.headers['content-disposition'])
        self.assertEqual(self.client.get(f'/api/takes/{take["id"]}/media', headers={'Range':'bytes=0-1'}).status_code, 416)
        # Cold app factory, real SQLite and filesystem reopen; same retained identity.
        app2 = create_app(self.home, SECRET, ORIGIN)
        with TestClient(app2) as reopened:
            reopened.cookies.update(self.client.cookies)
            snapshot = reopened.get('/api/state').json()
            self.assertEqual(snapshot['takes'][0]['id'], take['id'])
            self.assertEqual(snapshot['takes'][0]['review'], 'Matches request')
            self.assertEqual(snapshot['requests'][0]['selected'], take['id'])
            self.assertEqual(reopened.get(f'/api/takes/{take["id"]}/media').content, data)

    def test_invalid_and_storage_failure_preserve_earlier_work(self):
        request, intent, _, good = self.imported()
        for data in (b'not a wav', good[:-1], good + b'X'):
            candidate = self.post('/api/imports', intent_payload(request, data)).json()
            response = self.client.post(f'/api/imports/{candidate["id"]}/bytes', content=data)
            self.assertEqual(response.status_code, 400)
        with patch('studio.assets.retention.os.link', side_effect=PermissionError()):
            candidate = self.post('/api/imports', intent_payload(request, good)).json()
            self.assertEqual(self.client.post(f'/api/imports/{candidate["id"]}/bytes', content=good).status_code, 503)
        state = self.client.get('/api/state').json()
        self.assertEqual(len(state['takes']), 1)
        self.assertEqual(self.client.get(f'/api/takes/{intent["take"]}/media').content, good)

    def test_security_expiry_reauthentication_revocation_and_scope(self):
        request, intent, _, data = self.imported()
        path = f'/api/takes/{intent["take"]}/media'
        self.assertEqual(self.client.get(path, headers={'host':'evil'}).status_code, 403)
        self.assertEqual(self.client.get(path, headers={'origin':'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.post('/api/generate', {'owner':'other'}).status_code, 409)
        self.assertEqual(self.client.post('/api/generate', json={}, headers={'x-csrf-token':'bad'}).status_code, 403)
        self.assertEqual(self.client.get(f'/api/takes/{identity()}/media').status_code, 404)
        other, _ = self.save()
        cross_scope = dict(command=identity(), request=other['id'], expected=other['revision'], take=intent['take'])
        self.assertEqual(self.post('/api/select', cross_scope).status_code, 403)
        with TestClient(self.app) as anonymous:
            self.assertEqual(anonymous.get(path).status_code, 401)
        with self.app.state.store.transaction() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.client.get(path).status_code, 401)
        self.auth()
        self.assertEqual(self.client.get(path).content, data)
        self.assertEqual(len(self.client.get('/api/state').json()['takes']), 1)
        self.assertEqual(self.post('/api/logout', {}).status_code, 200)
        self.assertEqual(self.client.get(path).status_code, 401)
        self.auth()
        self.assertEqual(self.client.get(path).content, data)

    def test_finite_schemas_and_unsupported_media_import(self):
        request, payload = self.save('Image')
        self.assertEqual(self.post('/api/imports', intent_payload(request, wav())).status_code, 400)
        self.assertEqual(self.post('/api/requests', {**payload, 'command':identity(), 'owner':'other'}).status_code, 422)
        self.assertEqual(self.post('/api/requests', {**payload, 'command':identity(), 'text':' '}).status_code, 422)
        self.assertEqual(self.post('/api/requests', {**payload, 'command':identity(), 'text':'x'*8001}).status_code, 422)
        oversized = self.client.post('/api/imports', content=b'x'*65537)
        self.assertEqual(oversized.status_code, 413)


if __name__ == '__main__':
    unittest.main()
