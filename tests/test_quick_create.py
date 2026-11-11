"""Normal app API authority + real harmless child; no qualification intents or model."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from tests.http_support import TestClient
from studio.domain import Fault
from studio.persistence.store import identity
from studio.producer.evaluation import enable_evaluation
from studio.runs.service import LocalRuns
from studio.runs.normal_admission import NormalAdmission
from studio.server import create_app
from tests.producer_support import fixture_binding, effects


class NormalFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binding = fixture_binding(self.root / 'tool')
        self.app = create_app(self.root / 'var', b'controlled-ordinary-owner-fixture', 'http://testserver', _test_binding=self.binding)
        self.runs = self.app.state.runs
        self.runs.worker.grace = 0.1
        seeded = self.runs.bindings.seed(self.binding)
        self.record = enable_evaluation(self.runs.bindings, seeded['id'], seeded['revision'])
        self.client = TestClient(self.app)
        self.client.headers['origin'] = 'http://testserver'
        login = self.client.post('/api/login', json={'secret':'controlled-ordinary-owner-fixture'}).json()
        self.owner = login['csrf']
        self.client.headers['x-csrf-token'] = self.owner
        self.addCleanup(self.finish)

    def finish(self):
        self.runs.close()
        self.client.close()
        self.temp.cleanup()

    def post(self, endpoint, data):
        result = self.client.post(endpoint, json=data)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def request(self, text='Non-private English sound effect fixture', kind='Sound effects'):
        return self.post('/api/requests', dict(command=identity(),expected=0,text=text,kind=kind,purpose='Non-private fixture'))

    def prepare(self, request=None, options=None):
        request = request or self.request()
        self.post('/api/apps/method', dict(request=request['id'],binding=self.record['id'],revision=self.record['revision'],operation='sfx'))
        payload = dict(command=identity(),request=request['id'],revision=request['revision'],binding=self.record['id'],
                       binding_revision=self.record['revision'],operation='sfx',options=options or {})
        return self.post('/api/apps/plans',payload), request, payload

    def settle(self):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            threads = list(self.runs.threads.values())
            for thread in threads:
                thread.join(timeout=0.1)
            if not any(t.is_alive() for t in threads) and len(threads) == len(self.runs.threads):
                return
        self.fail('Controlled ordinary worker did not settle')

    def start(self, item):
        self.post(f'/api/sfx/runs/{item["id"]}/start', {})
        self.settle()
        return self.runs.records.get(item['id'])

    def legacy(self, run):
        # Explicit fixture-only old allocation; never configurable by a browser.
        from studio.assets.producer_files import allocation
        import os
        row = self.runs.records.get(run)
        _, descriptor, pin = allocation(self.runs.store,row)
        os.close(descriptor)
        self.runs.records.update(run,process=dict(allocation=pin))
        (self.binding.path.parent / 'mode').write_text('cache-layout-mismatch')


class QuickCreateTests(NormalFixture):
    def test_direction_and_media_boundaries_without_effect(self):
        for text in ('','   '):
            response = self.client.post('/api/requests',json=dict(command=identity(),expected=0,text=text,kind='Sound effects'))
            self.assertEqual(response.status_code,422)
        for text in ('x'*2001,):
            saved = self.request(text=text)
            self.post('/api/apps/method',dict(request=saved['id'],binding=self.record['id'],revision=self.record['revision'],operation='sfx'))
            response = self.client.post('/api/apps/plans',json=dict(command=identity(),request=saved['id'],revision=1,
                binding=self.record['id'],binding_revision=self.record['revision'],operation='sfx',options={}))
            self.assertEqual(response.status_code,400)
        saved = self.request(kind='Music')
        response = self.client.post('/api/apps/method',json=dict(request=saved['id'],binding=self.record['id'],revision=self.record['revision'],operation='sfx'))
        self.assertEqual(response.status_code,409)
        self.assertEqual(effects(self.binding),[])

    def test_ordinary_real_admission_general_bounds_and_fresh_resource_refusal(self):
        from types import SimpleNamespace
        from studio.producer.live_sfx import OrdinaryRuntime, USE
        from studio.producer import local_sfx as sfx
        item, _, _ = self.prepare(options={'seconds':1.7,'seed':12345})
        plan = self.runs.records.get(item['id'])['plan']
        record = dict(plan['binding'],fixture_only=False,executable=str(sfx.WRAPPER),pins=dict(files={**sfx.FILE_PINS,**sfx.model_pins()}))
        plan = dict(plan,binding=record)
        scope = SimpleNamespace(use=USE,check_plan=lambda value:None)
        runtime = OrdinaryRuntime(record=record,scope=scope,fixture_only=False)
        directory = self.root/'controlled-admission'
        directory.mkdir(mode=0o700)
        output = directory/'candidate.wav'
        with patch('studio.producer.live_sfx.sfx.check_pins') as pins, patch('studio.producer.live_sfx.resources',return_value=(8191,False)):
            with self.assertRaises(Fault) as blocked: runtime.admit(plan,output)
            self.assertEqual(blocked.exception.code,'RESOURCE_BUSY')
            pins.assert_called_with(record['pins']['files'])
        with patch('studio.producer.live_sfx.sfx.check_pins'), patch('studio.producer.live_sfx.resources',return_value=(8192,False)):
            runtime.final(plan,output,sfx.vector(sfx.WRAPPER,plan,output))
            self.assertEqual(scope.observation['free_mib'],8192)
        self.assertEqual(effects(self.binding),[])

    def test_held_route_lock_is_no_effect_resource_refusal(self):
        import fcntl, os
        item, _, _ = self.prepare(options={'seconds':0.1})
        descriptor = os.open(self.runs.store.home/'state/sfx.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            row = self.start(item)
            self.assertEqual((row['status'],row['error'],row['certainty']),('Blocked','RESOURCE_BUSY','not attempted'))
            self.assertEqual(effects(self.binding),[])
        finally:
            os.close(descriptor)

    def test_latest_resource_and_use_restrictions_zero_effect(self):
        item, _, _ = self.prepare(options={'seconds':0.1})
        self.runs.bindings.revise(self.record['id'],self.record['revision'],reason='USE_RESTRICTED',
            availability='Restricted for this use',action='Use configured noncommercial local technical evaluation only')
        row = self.start(item)
        self.assertEqual((row['status'],row['error']),('Blocked','USE_RESTRICTED'))
        self.assertEqual(effects(self.binding),[])

    def test_current_executable_drift_zero_effect(self):
        item, _, _ = self.prepare(options={'seconds':0.1})
        self.binding.path.write_text(self.binding.path.read_text()+'\n# controlled drift\n')
        row = self.start(item)
        self.assertEqual((row['status'],row['error']),('Blocked','RUNTIME_DRIFT'))
        self.assertEqual(effects(self.binding),[])

    def test_default_normal_api_no_effect_until_create_exact_reopen_and_duplicate(self):
        item, request, payload = self.prepare()
        self.assertEqual(effects(self.binding), [])
        plan = self.runs.records.get(item['id'])['plan']
        self.assertEqual((plan['parameters']['seconds'],plan['parameters']['seed'],plan['parameters']['steps']), (3,42,100))
        self.assertEqual(plan['parameters']['use'], 'noncommercial_local_technical_evaluation')
        self.assertTrue(self.client.get('/api/apps/catalog').json()['bindings'][-1]['enabled'])
        other = self.post('/api/apps/plans',dict(payload,command=identity()))
        self.assertEqual(other['id'],item['id'])
        row = self.start(item)
        self.assertEqual(row['status'], 'Ready for review')
        self.assertTrue(row['process']['group_retired'])
        self.assertEqual(len(effects(self.binding)),1)
        original = self.client.get(f'/api/takes/{row["candidate"]}/media').content
        self.assertGreater(len(original),44)
        self.runs.start(row['id'],lambda:self.owner)
        self.runs.close()
        self.runs = LocalRuns(self.runs.store,self.binding)
        self.assertEqual(self.runs.records.get(row['id'])['process'],row['process'])
        self.assertEqual((self.runs.store.home/'media'/(row['candidate']+'.wav')).read_bytes(),original)
        self.assertEqual(len(effects(self.binding)),1)
        self.assertEqual(self.runs.store.snapshot()['takes'][0]['review'],'Not reviewed')

    def test_parameters_bounds_unknown_and_use_injection_refused_without_effect(self):
        _, _, payload = self.prepare()
        for options in ({'seconds':0.09},{'seconds':10.1},{'seed':-1},{'seed':4294967296},
                        {'seed':1.5},{'language':'fr'},{'use':'commercial'},{'steps':2},{'negative':'changed'}):
            response = self.client.post('/api/apps/plans',json=dict(payload,command=identity(),options=options))
            self.assertIn(response.status_code,(400,409,422))
        for options in ({'seconds':0.1,'seed':0},{'seconds':10,'seed':4294967295}):
            self.post('/api/apps/plans',dict(payload,command=identity(),options=options))
        self.assertEqual(effects(self.binding),[])

    def test_current_disable_and_dirty_snapshot_zero_effect(self):
        item, request, _ = self.prepare()
        self.post('/api/requests',dict(command=identity(),id=request['id'],expected=1,text='Changed fixture intent',kind='Sound effects',purpose='Fixture'))
        result = self.client.post(f'/api/sfx/runs/{item["id"]}/start',json={})
        self.assertEqual(result.status_code,409)
        item, _, _ = self.prepare()
        self.runs.bindings.revise(self.record['id'],self.record['revision'],enabled=False)
        row = self.start(item)
        self.assertEqual(row['status'],'Blocked')
        self.assertEqual(effects(self.binding),[])

    def test_foreign_owner_plan_mutation_and_extra_start_fields_refused(self):
        item, _, _ = self.prepare()
        scope = NormalAdmission(self.runs,item['id'],self.owner)
        with self.assertRaises(Fault):
            scope.check_owner('b'*64)
        changed = dict(scope.plan,revision=99)
        with self.assertRaises(Fault):
            scope.check_plan(changed)
        response = self.client.post(f'/api/sfx/runs/{item["id"]}/start',json={'use':'commercial'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(effects(self.binding),[])

    def test_duplicate_concurrent_start_one_effect(self):
        item, _, _ = self.prepare(options={'seconds':0.1})
        errors = []
        def start():
            try: self.runs.start(item['id'],lambda:self.owner)
            except BaseException as error: errors.append(type(error).__name__)
        threads = [threading.Thread(target=start) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.settle()
        self.assertEqual(errors,[])
        self.assertEqual(len(effects(self.binding)),1)

    def test_actual_cache_mismatch_one_linked_isolated_recovery(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        self.legacy(item['id'])
        old = self.start(item)
        record = self.runs.recovery.get(request['id'])
        self.assertEqual(old['status'],'Failed')
        self.assertEqual(old['error'],'OUTPUT_UNSAFE')
        self.assertTrue(old['process']['exited'] and old['process']['group_retired'])
        self.assertEqual(record['state'],'Completed')
        self.assertTrue(record['reserved'])
        self.assertEqual(record['cause'],'hypothesis')
        new = self.runs.records.get(record['successor'])
        self.assertNotEqual(new['candidate'],old['candidate'])
        self.assertEqual(new['plan'],old['plan'])
        self.assertEqual(new['process']['layout'],2)
        self.assertEqual(new['status'],'Ready for review')
        self.assertEqual(len(effects(self.binding)),2)
        self.assertTrue((self.runs.store.home/'staging'/('sfx-'+old['id'])/'.nv/ComputeCache/controlled-cache').is_file())
        claims = self.runs.recovery.knowledge.applicable()
        self.assertEqual(claims['claims'][0]['confidence'],'fixture-tested')
        self.assertNotIn(request['id'],str(claims))
        self.runs.recovery.after(item['id'],lambda:self.owner)
        self.assertEqual(len(effects(self.binding)),2)

    def test_unresolved_group_blocks_recovery_and_next_dispatch(self):
        item, _, _ = self.prepare(options={'seconds':0.1})
        self.legacy(item['id'])
        with patch('studio.runs.owned_process.retirement',return_value=(False,[])):
            row = self.start(item)
        self.assertEqual(row['status'],'Outcome unknown')
        record = self.runs.recovery.get(row['plan']['request'])
        self.assertEqual(record['state'],'Needs attention')
        self.assertFalse(record['reserved'])
        other, _, _ = self.prepare()
        self.assertEqual(self.client.post(f'/api/sfx/runs/{other["id"]}/start',json={}).status_code,409)
        self.assertEqual(len(effects(self.binding)),1)

    def test_collection_interruption_recovers_original_bytes_no_generation(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        calls = []
        def fail_once():
            calls.append(True)
            if len(calls) == 1: raise OSError('controlled non-private storage interruption')
        self.runs.collection.after_finalize = fail_once
        row = self.start(item)
        record = self.runs.recovery.get(request['id'])
        self.assertEqual(record['recipe'],'original-collection')
        self.assertEqual(record['state'],'Completed')
        self.assertIsNone(record['successor'])
        self.assertEqual(row['status'],'Ready for review')
        self.assertEqual(len(effects(self.binding)),1)
        original = (self.runs.store.home/'staging'/('sfx-'+row['id'])/'outputs/candidate.wav').read_bytes()
        self.assertEqual(self.client.get(f'/api/takes/{row["candidate"]}/media').content,original)
