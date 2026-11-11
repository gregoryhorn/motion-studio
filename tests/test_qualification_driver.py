"""Driver sensitivity test: synthetic output must NEVER qualify as a real result."""
from contextlib import redirect_stdout
import io
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from studio.domain import Fault, SaveRequest
from studio.persistence.store import identity
from studio.producer.local_sfx import PrepareSFX
from studio.producer.live_sfx import USE
from studio.producer.stable_adapter import RevisionRuntime
from studio.server import create_app
from tests.adapter_fixtures import OfflineCatalog, FixtureA, worker_location
from tools.qualify_local_sfx import evaluate, no_previous_test
from tests.http_support import TestClient
from tests.test_helper_environment import SENTINELS
from studio.runs.helper_environment import helper_environment


class QualificationDriverTests(unittest.TestCase):
    def test_authenticated_driver_rejects_fixture_as_real_and_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            location = worker_location(root / 'tool', FixtureA())
            operation = root / 'non-private-operation.json'
            operation.write_text(json.dumps(dict(direction='Non-private synthetic driver sensitivity case', use=USE)))
            apps = []

            def make_app(home, secret, origin):
                app = create_app(home, secret, origin, _test_catalog=OfflineCatalog())
                original = app.state.runs.bindings.save
                def save(proposal, **options):
                    return original(dict(adapter=FixtureA.id, adapter_version=1,
                        interface_version=FixtureA.interface, executable=str(location)),
                        permitted={str(location)}, fixture_only=True)
                app.state.runs.bindings.save = save
                apps.append(app)
                return app

            original_run = subprocess.run
            with patch.dict(os.environ, SENTINELS, clear=True), \
                 patch('tools.qualify_local_sfx.subprocess.run', wraps=original_run) as decode, \
                 patch('tools.qualify_local_sfx.create_app', side_effect=make_app), \
                 patch('tools.qualify_local_sfx.TestClient', TestClient), \
                 patch('tools.qualify_local_sfx.ScopedRuntime',
                       side_effect=lambda record, scope: RevisionRuntime(record=record, fixture_only=True)), \
                 redirect_stdout(io.StringIO()):
                with self.assertRaises(Fault) as denied:
                    evaluate(root / 'var', operation)
                self.assertEqual(denied.exception.code, 'PROVENANCE_MISMATCH')
                with self.assertRaises(Fault) as duplicate:
                    evaluate(root / 'var', operation)
                self.assertEqual(duplicate.exception.code, 'EXISTING_TEST_INTENT_RECONCILE_SAME_RUN')
                self.assertEqual(decode.call_count, 1)
                self.assertEqual(decode.call_args.args[0][0], '/usr/bin/ffmpeg')
                self.assertEqual(decode.call_args.kwargs['env'], helper_environment())
                self.assertTrue(set(SENTINELS).isdisjoint(decode.call_args.kwargs['env']))
            effects = (location.parent / 'effects.jsonl').read_text().splitlines()
            self.assertEqual(len(effects), 1)
            ledger = json.loads((root / 'var/state/lq1-intent.json').read_text())
            self.assertEqual(ledger['status'], 'stopped_no_retry')
            self.assertEqual(ledger['origin'], 'test_fixture')
            self.assertEqual(apps[0].state.runs.scopes, {})
            self.assertTrue(all(not row['enabled'] for row in apps[0].state.runs.bindings.rows()))

    def test_existing_real_record_refuses_before_app_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root / 'var', b'non-private-driver-isolated-credential', 'http://testserver')
            try:
                saved = app.state.store.save(SaveRequest(command=identity(), expected=0,
                    text='Non-private pre-existing prepared case', kind='Sound effects'))
                app.state.runs.prepare(PrepareSFX(command=identity(), request=saved['id'], revision=1, seconds=3.0, seed=42))
                intent = root / 'var/state/lq1-intent.json'
                with self.assertRaises(Fault) as denied:
                    no_previous_test(root / 'var', intent)
                self.assertEqual(denied.exception.code, 'EXISTING_REAL_RUN_RECONCILE_SAME_RUN')
                # A committed intent alone is also enough, before any app is created.
                intent.write_text('{}')
                with self.assertRaises(Fault):
                    no_previous_test(root / 'var', intent)
            finally:
                app.state.runs.close()
