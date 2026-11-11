"""Owner setup API: bounded passive files/CAS, never a producer/runtime launch."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.http_support import TestClient
from studio.domain import Fault
from studio.persistence.store import identity
from studio.server import create_app


class SetupAPITests(unittest.TestCase):
    def test_owner_finite_passive_save_check_cas_and_zero_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'controlled-setup-file'
            content = '#!/bin/sh\n# Non-private passive setup fixture; NEVER execute.\nexit 99\n'
            file.write_text(content)
            file.chmod(0o700)
            secret = b'non-private-setup-isolated-owner-credential'
            app = create_app(root / 'var', secret, 'http://testserver')
            runs = app.state.runs
            runs.catalog.setup_locations[('stable-audio-local', 1)] = (str(file),)
            adapter = runs.catalog.lookup('stable-audio-local', 1)
            def supported(proposal, digest, fixture_only):
                if proposal.interface_version != adapter.interface:
                    raise Fault('UNSUPPORTED_INTERFACE', 409)
                return dict(wrapper=proposal.executable, files={proposal.executable:digest})
            try:
                with TestClient(app) as client, patch.object(adapter, 'validate_setup', side_effect=supported), \
                     patch('studio.runs.owned_process.subprocess.Popen') as spawn:
                    self.assertEqual(client.get('/api/apps/setup').status_code, 401)
                    login = client.post('/api/login', json={'secret':secret.decode()}, headers={'origin':'http://testserver'})
                    client.headers.update({'origin':'http://testserver','x-csrf-token':login.json()['csrf']})
                    spec = client.get('/api/apps/setup').json()
                    self.assertEqual(len(spec['cards']), 1)
                    self.assertIn('No process', spec['cards'][0]['checks'])
                    proposal = dict(adapter='stable-audio-local', adapter_version=1,
                        interface_version=adapter.interface, executable=str(file))
                    self.assertEqual(client.post('/api/apps/bindings', json=proposal, headers={'x-csrf-token':'wrong'}).status_code, 403)
                    for field in ('env','argv','enabled','fixture_only','qualification','permitted','pins','runtime'):
                        self.assertEqual(client.post('/api/apps/bindings', json=dict(proposal, **{field:'deny'})).status_code, 422)
                    self.assertEqual(client.post('/api/apps/bindings', json=dict(proposal, executable='/not-approved')).json()['error'], 'LOCATION_DENIED')
                    self.assertEqual(client.post('/api/apps/bindings', json=dict(proposal, adapter='test-stable-cli')).json()['error'], 'UNSUPPORTED_SETUP')
                    self.assertEqual(client.post('/api/apps/bindings', json=dict(proposal, interface_version='unsupported')).json()['error'], 'UNSUPPORTED_INTERFACE')
                    response = client.post('/api/apps/bindings', json=proposal)
                    self.assertEqual(response.status_code, 200)
                    shown = response.json()['binding']
                    self.assertFalse(shown['enabled'])
                    self.assertEqual(shown['qualification'], 'Setup checked')
                    self.assertNotIn(str(file), str(shown))
                    record = runs.bindings.get(shown['binding'], shown['revision'])
                    self.assertFalse(record['enabled'])
                    check = dict(binding=shown['binding'], expected=shown['revision'])
                    self.assertEqual(client.post('/api/apps/bindings/check', json=check).status_code, 200)
                    revised = client.post('/api/apps/bindings', json=dict(proposal, **check)).json()['binding']
                    self.assertEqual(revised['revision'], 2)
                    self.assertEqual(runs.bindings.get(shown['binding'], 1), record)
                    self.assertEqual(client.post('/api/apps/bindings', json=dict(proposal, **check)).json()['error'], 'BINDING_CONFLICT')
                    self.assertEqual(client.post('/api/apps/bindings/check', json=check).json()['error'], 'BINDING_CONFLICT')
                    saved = client.post('/api/requests', json=dict(command=identity(), expected=0,
                        text='Non-private setup selection case', kind='Sound effects')).json()
                    selected = client.post('/api/apps/method', json=dict(request=saved['id'],
                        binding=shown['binding'], revision=1, operation='sfx'))
                    self.assertEqual(selected.status_code, 200)
                    file.write_text(content + '# controlled drift\n')
                    stale = client.post('/api/apps/bindings/check', json=dict(binding=shown['binding'], expected=2)).json()['binding']
                    self.assertEqual(stale['reason'], 'RUNTIME_DRIFT')
                    self.assertFalse(stale['enabled'])
                    file.unlink()
                    missing = client.post('/api/apps/bindings/check', json=dict(binding=shown['binding'], expected=3)).json()['binding']
                    self.assertEqual(missing['reason'], 'APP_MISSING')
                    self.assertEqual(runs.records.rows(), [])
                    spawn.assert_not_called()
            finally:
                runs.close()
