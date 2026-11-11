"""Offline proof and authenticated same-identity resume; NEVER runs a real producer."""
import os
from tests.http_support import TestClient
import unittest
from unittest.mock import patch
from studio.assets.producer_files import allocation
from studio.domain import Fault
from studio.producer.live_sfx import ScopedRuntime, USE
from studio.server import create_app
from tests import test_real_admission as fixtures
from tools.qualify_local_sfx import Evaluation, private_json, post
from tools.reconcile_local_sfx import inspect_original
from tools.resume_local_sfx import resume_scope


class SameRunResumeTests(unittest.TestCase):
    setUp = fixtures.RealAdmissionTests.setUp
    tearDown = fixtures.RealAdmissionTests.tearDown

    def legacy_refusal(self):
        row = self.runs.records.get(self.item['id'])
        _, fd, pin = allocation(self.runs.store, row)
        os.close(fd)
        self.runs.records.update(row['id'], status='Blocked', certainty='not attempted',
                                 error='SCOPE_CONFLICT', process={'allocation':pin})
        self.scope.close()
        with self.runs.store.transaction() as db:
            db.execute("UPDATE bounded_admission SET state='closed'")  # Actual legacy representation.
        self.ledger = dict(status='stopped_no_retry', app_status='Blocked', error='SCOPE_CONFLICT',
            scope='CF-LQ1-r1', use=USE, run=row['id'], candidate=row['candidate'],
            binding=self.record['id'], binding_revision=1, prepare=self.model.model_dump())
        self.intent = self.runs.store.home / 'state/lq1-intent.json'
        private_json(self.intent, self.ledger)
        self.value = Evaluation(direction=self.plan['direction'], use=USE)
        return self.runs.records.get(row['id'])

    def test_authenticated_resume_preserves_all_identities_consumes_once_and_keeps_evidence(self):
        original = self.legacy_refusal()
        original_bytes = self.intent.read_bytes()
        facts, _, _, _ = inspect_original(self.runs.store.home)
        self.assertTrue(facts['proven_prelaunch_refusal'])
        self.runs.close()
        secret = b'non-private-same-run-resume-owner-test'
        app = create_app(self.runs.store.home, secret, 'http://testserver')
        self.runs = app.state.runs
        with TestClient(app) as client, patch('studio.runs.owned_process.subprocess.Popen') as spawn:
            login = client.post(
                '/api/login', json={'secret':secret.decode()}, headers={'origin':'http://testserver'}).json()
            client.headers.update({'origin':'http://testserver','x-csrf-token':login['csrf']})
            item, body, record, scope = resume_scope(self.runs, login['csrf'], self.ledger, self.value)
            scope.install(ScopedRuntime(record=record, scope=scope))
            with self.assertRaises(Fault):
                scope.check_owner(self.owner)
            self.assertEqual(post(client, '/api/apps/plans', body)['id'], original['id'])
            def simulated_worker(argv, env, directory, descriptor, final, persist, stop, launching, **options):
                final(argv)
                self.assertEqual(env['HF_HUB_OFFLINE'], '1')
                launching()
                persist({'synthetic_process':True})
                raise Fault('SIMULATED_AFTER_LAUNCH_FAILURE', 409)
            with patch.object(self.runs.worker, 'execute', side_effect=simulated_worker) as dispatched, \
                 patch('studio.producer.live_sfx.sfx.check_pins'), \
                 patch('studio.producer.live_sfx.resources', return_value=(9000, False)):
                post(client, f'/api/sfx/runs/{item["id"]}/start', {})
                self.runs.threads[item['id']].join(timeout=3)
                self.assertEqual(dispatched.call_count, 1)
            current = self.runs.records.get(item['id'])
            for key in ('id','candidate','plan','plan_digest','nonce','generation'):
                self.assertEqual(current[key], original[key])
            self.assertEqual(current['status'], 'Outcome unknown')
            scope.close()
            with self.runs.store.transaction() as db:
                self.assertEqual(db.execute('SELECT state FROM bounded_admission').fetchone()[0], 'closed_consumed')
            with self.assertRaises(Fault):
                resume_scope(self.runs, login['csrf'], self.ledger, self.value)
            self.assertEqual(self.intent.read_bytes(), original_bytes)
            spawn.assert_not_called()

    def test_refuses_unsafe_state_even_with_absent_outputs(self):
        self.legacy_refusal()
        cases = [dict(status='Outcome unknown'), dict(status='Running'), dict(certainty='started'),
                 dict(process={'allocation':self.runs.records.get(self.item['id'])['process']['allocation'],
                               'incarnation':{'synthetic_process':True}}),
                 dict(collection={'synthetic':True}), dict(stop=1)]
        for values in cases:
            with self.subTest(fields=tuple(values)):
                before = self.runs.records.get(self.item['id'])
                self.runs.records.update(self.item['id'], **values)
                with self.assertRaises(Fault):
                    resume_scope(self.runs, self.owner, self.ledger, self.value)
                self.runs.records.update(self.item['id'], **{key:before[key] for key in values})
        for state in ('entered','closed_consumed','closed_unconsumed'):
            with self.runs.store.transaction() as db:
                db.execute('UPDATE bounded_admission SET state=?', (state,))
            with self.assertRaises(Fault):
                resume_scope(self.runs, self.owner, self.ledger, self.value)
        with self.runs.store.transaction() as db:
            db.execute("UPDATE bounded_admission SET state='closed'")
        directory = self.runs.store.home / 'staging' / ('sfx-' + self.item['id'])
        for name in ('candidate.wav','candidate.wav.json','unexpected-controlled-file'):
            file = directory / name
            file.write_bytes(b'controlled no-effect collision')
            with self.assertRaises(Fault):
                resume_scope(self.runs, self.owner, self.ledger, self.value)
            file.unlink()
        with self.assertRaises(Fault):
            resume_scope(self.runs, self.owner, self.ledger, Evaluation(direction='Changed controlled input', use=USE))
        scope = resume_scope(self.runs, self.owner, self.ledger, self.value)[3]
        scope.close()
        with self.assertRaises(Fault):
            resume_scope(self.runs, self.owner, self.ledger, self.value)
