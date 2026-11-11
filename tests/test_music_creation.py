"""Music saved chat -> owned synthetic bridge -> exact retained delivery."""
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from studio.domain import Fault, KINDS
from studio.persistence.store import identity
from studio.native.creation.policy import MusicAssociation
from studio.native.creation.runtime import CreationRuntime
from studio.producer.music.adapter import AceStep, Runtime
from studio.producer.music.contract import launcher_vector
from tests.music_support import setup, settle, effect_count


class MusicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx, self.runtime, self.path = setup(Path(self.temp.name))
        self.addCleanup(self.runtime.unload)

    def rpc(self, operation, payload=None, root='canonical-root'):
        return self.ctx.methods['creation.'+operation](payload or {}, session_id=root)

    def tool(self, operation, payload=None, root='canonical-root'):
        handler = self.ctx.tools['motion_studio_creation'][1]
        return json.loads(handler(dict(operation=operation, **(payload or {})),
            session_id='physical', conversation_id=root))

    def prepare(self, **options):
        result = self.tool('prepare', dict(schema_version=2, kind='Music',
            direction='Synthetic instrumental cue', seconds=10, **options))
        self.assertNotIn('error', result, result)
        return result

    @staticmethod
    def command(row): return {k:row[k] for k in ('request','revision','command','run')}

    def start(self, row):
        result = self.tool('start', self.command(row))
        self.assertNotIn('error', result, result)
        settle(self.runtime)
        return self.tool('status')

    def test_default_plan_and_native_projection_no_open_effect(self):
        with patch('subprocess.Popen', side_effect=AssertionError('Inert operation')):
            row = self.tool('prepare',dict(schema_version=2,kind='Music',direction='A calm instrumental cue'))
            self.assertEqual(row['defaults'],dict(seconds=30,seed=42,steps=8,instrumental=True,
                model='acestep-v15-turbo',batch=1,extra_lm=False))
            self.assertEqual(self.tool('status')['run'],row['run'])
            self.assertEqual(self.rpc('list')['creations'][0]['request'],row['request'])
            self.assertEqual(effect_count(self.runtime),0)
        plan=self.runtime.runs.records.get(row['run'])['plan']
        self.assertEqual(plan['kind'],'Music');self.assertEqual(plan['parameters']['effective_seed'],'unverified')
        self.assertFalse(plan['parameters']['thinking']);self.assertFalse(plan['parameters']['cot'])
        self.assertEqual(KINDS,('Sound effects','Music','Voice','Image','Video'))

    def test_strict_types_extras_bounds_and_version(self):
        invalid=[dict(seconds=True),dict(seconds='10'),dict(seconds=10.0),dict(seed=True),dict(seed=-1),
            dict(seed=4294967296),dict(instrumental=1),dict(reference_requested='no'),dict(model='xl'),
            dict(provider='anything'),dict(environment={}),dict(binding='a'*32),dict(schema_version=1),
            dict(seconds=0),dict(seconds=601),dict(direction='  '),dict(direction='x\x00x')]
        base=dict(schema_version=2,kind='Music',direction='Synthetic')
        for change in invalid:
            with self.subTest(change=change):
                self.assertEqual(self.tool('prepare',base|change)['error'],'INVALID_CREATION_INPUT')
        self.assertEqual(effect_count(self.runtime),0)

    def test_broader_music_preserved_without_substitution(self):
        parent=None
        for options,reason in ((dict(instrumental=False),'MUSIC_VOCAL_ROUTE_UNQUALIFIED'),
                (dict(seconds=60),'MUSIC_DURATION_ROUTE_UNQUALIFIED'),
                (dict(reference_requested=True),'MUSIC_REFERENCE_ROUTE_UNQUALIFIED')):
            args=dict(schema_version=2,kind='Music',direction='Synthetic broader Music',parent=parent)|options
            row=self.tool('prepare',args)
            self.assertEqual(row['failure'],reason,row);self.assertIsNone(row['run'])
            self.assertEqual(self.tool('prepare',args)['request'],row['request'])
            with self.runtime.store.transaction() as db:
                saved=self.runtime.store.request(db,row['request'])
                self.assertEqual(saved['kind'],'Music');self.assertEqual(saved['text'],args['direction'])
            parent=row['request']
        self.assertEqual(effect_count(self.runtime),0)

    def test_sfx_scope_and_production_cannot_grant_music(self):
        self.runtime.policy=replace(self.runtime.policy,music=MusicAssociation())
        self.assertEqual(self.tool('prepare',dict(schema_version=2,kind='Music',direction='Synthetic'))['error'],
            'MUSIC_SCOPE_REVIEW_REQUIRED')
        self.runtime.policy=replace(self.runtime.policy,music=MusicAssociation(revision='new',prepare=True))
        self.assertEqual(self.tool('prepare',dict(schema_version=2,kind='Music',direction='Synthetic'))['error'],
            'MUSIC_WORKFLOW_REVIEW_REQUIRED')
        self.rpc('admit_music')
        row=self.prepare()
        self.assertEqual(self.tool('start',self.command(row))['error'],'MUSIC_EFFECT_REVIEW_REQUIRED')
        self.assertEqual(effect_count(self.runtime),0)

    def test_inactive_real_recipe_is_fixed_and_live_denied(self):
        row=self.prepare();plan=self.runtime.runs.records.get(row['run'])['plan']
        adapter=AceStep();runtime=Runtime(plan['binding'])
        output=Path(self.temp.name)/('sfx-'+row['run'])/'outputs/candidate.wav'
        with patch('subprocess.Popen',side_effect=AssertionError('No launcher')):
            spec=adapter.construct_dispatch(plan,output,runtime)
            self.assertEqual(spec.validation_profile,'stereo-48000-pcm16')
            self.assertIn('--plan',spec.argv);self.assertNotIn('PYTHONPATH',spec.environment)
            vector=launcher_vector(runtime.launcher(),plan,output.parent)
            self.assertIn('--no-cot-metas',vector);self.assertNotIn('--thinking',vector)
            self.assertEqual(vector[vector.index('--duration')+1],'10')
            env=runtime.producer_environment(output)
            self.assertEqual(env['ACE_STEP_OUTPUT_DIR'],str(output.parent))
            self.assertNotIn('LD_LIBRARY_PATH',env)
            with self.assertRaises(Fault) as denied: adapter.build_dispatch(plan,output,runtime)
            self.assertEqual(denied.exception.code,'MUSIC_LIVE_UNQUALIFIED')
        self.assertEqual(effect_count(self.runtime),0)

    def test_lost_reply_concurrent_duplicate_exact_retrieval_save_and_reopen(self):
        row=self.prepare();self.assertEqual(self.tool('status')['request'],row['request'])
        results=[]
        threads=[threading.Thread(target=lambda:results.append(self.tool('start',self.command(row)))) for _ in range(3)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5)
        settle(self.runtime)
        self.assertTrue(all('error' not in r for r in results),results)
        observed=self.tool('status');self.assertEqual(observed['state'],'Ready for review',observed)
        self.assertEqual(effect_count(self.runtime),1)
        self.tool('start',self.command(row));settle(self.runtime)
        data=bytearray();offset=0
        while True:
            chunk=self.rpc('chunk',dict(request=row['request'],take=row['candidate'],offset=offset))
            part=base64.b64decode(chunk['bytes']);data.extend(part);offset+=len(part)
            self.assertEqual(hashlib.sha256(part).hexdigest(),chunk['chunk_sha256'])
            if offset==chunk['total']:break
        self.assertEqual(hashlib.sha256(data).hexdigest(),chunk['sha256'])
        media=self.runtime.store.home/'media'
        self.assertEqual(bytes(data),(media/(row['candidate']+'.wav')).read_bytes())
        native=(media/(row['candidate']+'.native.wav')).read_bytes()
        self.assertNotEqual(native,bytes(data))
        facts=self.runtime.runs.records.get(row['run'])['collection']['facts']
        self.assertEqual(facts['lineage']['native']['sha256'],hashlib.sha256(native).hexdigest())
        self.assertIsNone(facts['lineage']['seed_effective'])
        saved=self.rpc('select',dict(request=row['request'],take=row['candidate'],command=identity(),revision=1))
        self.assertEqual(saved['revision'],2)
        self.assertEqual(self.rpc('chunk',dict(request=row['request'],take=row['candidate'],offset=0))['total'],len(data))
        instance=self.runtime.instance;self.runtime.unload()
        fresh=CreationRuntime(self.ctx,replace(self.runtime.policy,instance=instance,create_store=False))
        try:
            service=fresh.acquire();reopened=service.read('canonical-root')
            self.assertEqual(reopened['takes'][0]['selected'],True)
            self.assertEqual(service.assets.retrieve(row['candidate'])[0],bytes(data))
            self.assertEqual(effect_count(fresh),1)
        finally:fresh.unload()

    def test_only_same_output_collection_recovery(self):
        calls=[]
        def interrupt():
            calls.append(1)
            if len(calls)==1:raise RuntimeError('Synthetic collection interruption')
        self.runtime.runs.collection.after_finalize=interrupt
        row=self.prepare();result=self.start(row)
        self.assertEqual(result['state'],'Ready for review',result)
        recovery=self.runtime.runs.recovery.get(row['request'])
        self.assertEqual(recovery['recipe'],'original-collection');self.assertIsNone(recovery['successor'])
        self.assertEqual(effect_count(self.runtime),1)
        with self.assertRaises(Fault):self.runtime.runs.recovery.successor(recovery,self.runtime.runs.records.get(row['run']),lambda:None)

    def test_unknown_reload_and_lost_prelaunch_ack_never_rearm(self):
        row=self.prepare()
        with patch.object(self.runtime.runs,'start',side_effect=RuntimeError('Lost engine observation')):
            self.assertIn('error',self.tool('start',self.command(row)))
        self.assertEqual(self.tool('start',self.command(row))['state'],'Start interrupted - observe; no replay')
        self.runtime.runs.records.update(row['run'],status='Starting',certainty='possibly started')
        instance=self.runtime.instance;self.runtime.unload()
        fresh=CreationRuntime(self.ctx,replace(self.runtime.policy,instance=instance,create_store=False))
        try:
            service=fresh.acquire()
            self.assertEqual(service.read('canonical-root')['state'],'Outcome unknown')
            from studio.native.creation.registration import Command
            service.start('canonical-root',Command(**self.command(row)))
            self.assertEqual(effect_count(fresh),0)
        finally:fresh.unload()

    def test_wrong_root_profile_binding_revision_and_privacy(self):
        row=self.prepare()
        self.assertIn('error',self.tool('status',dict(request=row['request']),root='foreign'))
        self.runtime.policy=replace(self.runtime.policy,music=replace(self.runtime.policy.music,revision='changed'))
        self.rpc('admit_music')
        self.assertEqual(self.tool('status')['error'],'MUSIC_POLICY_CHANGED')
        self.runtime.policy=replace(self.runtime.policy,profile='other-profile')
        self.assertEqual(self.tool('status')['error'],'CREATION_ACCESS_UNAVAILABLE')
        self.assertEqual(effect_count(self.runtime),0)

    def test_stop_owned_and_source_drift_no_replay(self):
        (self.path.parent/'mode').write_text('sleep')
        self.runtime.runs.worker.grace=0.1
        entered=threading.Event();self.runtime.runs.worker.after_spawn=entered.set
        row=self.prepare();self.tool('start',self.command(row));self.assertTrue(entered.wait(5))
        self.tool('stop',self.command(row));settle(self.runtime)
        self.assertEqual(self.tool('status')['state'],'Cancelled')
        self.tool('start',self.command(row));settle(self.runtime)
        self.assertLessEqual(effect_count(self.runtime),1)

    def test_dispatch_drift_and_no_sfx_recipe(self):
        row=self.prepare();self.path.write_text(self.path.read_text()+'\n# drift\n')
        observed=self.start(row)
        self.assertEqual(observed['state'],'Blocked',observed)
        self.assertEqual(observed['failure'],'RUNTIME_DRIFT')
        self.assertEqual(effect_count(self.runtime),0)
        from studio.runs.recovery_recipes import shared_runtime_cache
        self.assertFalse(shared_runtime_cache(self.runtime.store,self.runtime.runs.records.get(row['run'])))

    def test_lost_prepare_before_plan_plus_service_reload_same_identity(self):
        args=dict(schema_version=2,kind='Music',direction='Synthetic interrupted Music',seconds=10)
        with patch.object(self.runtime.runs,'prepare_app',side_effect=RuntimeError('Synthetic lost prepare')):
            self.assertIn('error',self.tool('prepare',args))
        pending=self.tool('status');self.assertIsNone(pending['run'])
        instance=self.runtime.instance;self.runtime.unload()
        fresh=CreationRuntime(self.ctx,replace(self.runtime.policy,instance=instance,create_store=False))
        try:
            from studio.native.creation.registration import MusicPrepare
            service=fresh.acquire();observed=service.read('canonical-root')
            self.assertEqual(observed['request'],pending['request'])
            finished=service.prepare('canonical-root',MusicPrepare(**args))
            self.assertEqual(finished['command'],pending['command']);self.assertTrue(finished['run'])
            self.assertEqual(effect_count(fresh),0)
        finally:fresh.unload()

    def test_binding_change_and_final_policy_away_back_never_launch(self):
        row=self.prepare()
        def change():
            self.runtime.policy=replace(self.runtime.policy,music=replace(self.runtime.policy.music,revision='new-revision'))
            self.runtime.service.admit_music('canonical-root')
        self.runtime.runs.before_spawn=change
        self.tool('start',self.command(row));settle(self.runtime)
        self.assertEqual(effect_count(self.runtime),0)
        self.assertEqual(self.runtime.runs.records.get(row['run'])['status'],'Blocked')

    def test_music_revocation_during_byte_read_rechecks_scope(self):
        row=self.prepare();self.start(row)
        original=self.runtime.service.assets.retrieve
        def revoke(take):
            value=original(take)
            self.runtime.policy=replace(self.runtime.policy,music=replace(self.runtime.policy.music,prepare=False))
            return value
        with patch.object(self.runtime.service.assets,'retrieve',side_effect=revoke):
            result=self.rpc('chunk',dict(request=row['request'],take=row['candidate'],offset=0))
        self.assertEqual(result,dict(error='MUSIC_SCOPE_REVIEW_REQUIRED'))

    def test_native_retained_corruption_is_not_reported_as_intact_lineage(self):
        row=self.prepare();self.start(row)
        path=self.runtime.store.home/'media'/(row['candidate']+'.native.wav')
        path.chmod(0o600);path.write_bytes(b'Synthetic native corruption')
        result=self.rpc('chunk',dict(request=row['request'],take=row['candidate'],offset=0))
        self.assertEqual(result,dict(error='RETAINED_NATIVE_CORRUPT'))


if __name__=='__main__':unittest.main()
