"""AFC root/store/tool -> shared child/collection, synthetic effect evidence only."""
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from studio.domain import SaveRequest
from studio.persistence.store import identity
from studio.native.creation.registration import register
from tests.creation_support import Context, setup, settle, effects


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx, self.runtime, self.binding = setup(Path(self.temp.name))
        self.addCleanup(self.runtime.unload)
        self.assertTrue(self.rpc('admit')['admitted'])

    def rpc(self, operation, payload=None, root='canonical-root'):
        return self.ctx.methods['creation.'+operation](payload or {}, session_id=root)

    def tool(self, operation, payload=None, root: str | None='canonical-root', session: str | None='compressed-physical'):
        handler = self.ctx.tools['motion_studio_creation'][1]
        return json.loads(handler(dict(operation=operation, **(payload or {})), session_id=session, conversation_id=root,
                                  task_id='task-not-identity', user_task='MUST NOT READ CHAT'))

    def prepare(self, **kwargs):
        result = self.tool('prepare', dict(direction='Synthetic metallic door slam', **kwargs))
        self.assertNotIn('error', result)
        return result

    @staticmethod
    def command(row): return {key:row[key] for key in ('request','revision','command','run')}

    def test_default_registration_and_observation_inert(self):
        ctx = Context(Path(self.temp.name)/'not-created')
        runtime = register(ctx)
        self.addCleanup(runtime.unload)
        handler = ctx.tools['motion_studio_creation'][1]
        with patch('subprocess.Popen', side_effect=AssertionError('No effects')):
            for operation in ('status','prepare'):
                args = dict(operation=operation)
                if operation == 'prepare': args['direction'] = 'Synthetic'
                self.assertEqual(json.loads(handler(args, session_id='s', conversation_id='r'))['error'], 'CREATION_ACCESS_UNAVAILABLE')
            self.assertFalse(ctx.state.data_dir.exists())
        self.assertIn('defaults', ctx.sections['motion-studio.creation'])

    def test_context_spoof_missing_foreign_root_and_store_denied(self):
        for session,root in ((None,'canonical-root'),('s',None),('', 'canonical-root')):
            self.assertEqual(self.tool('status',root=root,session=session)['error'], 'CREATION_CONTEXT_REQUIRED')
        row = self.prepare()
        for operation in ('status','start','stop'):
            payload = {'request':row['request']} if operation == 'status' else self.command(row)
            self.assertIn('error', self.tool(operation,payload,root='foreign'))
            self.assertIn('error', self.rpc(operation,payload,root='foreign'))
        self.assertIn('error', self.tool('prepare',dict(direction='x',conversation_id='canonical-root')))
        self.rpc('admit', root='foreign')
        self.assertEqual(self.rpc('status', {'request':row['request']},root='foreign')['error'], 'CREATION_SCOPE_DENIED')
        other_ctx, other, _ = setup(Path(self.temp.name)/'other-store')
        try:
            other_ctx.methods['creation.admit']({},session_id='canonical-root')
            result = other_ctx.methods['creation.status']({'request':row['request']},session_id='canonical-root')
            self.assertEqual(result['error'], 'CREATION_SCOPE_DENIED')
        finally: other.unload()
        self.assertEqual(effects(self.binding), [])

    def test_flat_surviving_schema_is_strictly_validated_per_operation(self):
        row = self.prepare()
        invalid = [
            ('prepare', dict(direction='Synthetic', request=row['request'])),
            ('start', dict(self.command(row), direction='Not a start field')),
            ('status', dict(direction='Not a status field')),
            ('stop', dict(request=row['request'])),
        ]
        for operation, payload in invalid:
            with self.subTest(operation=operation):
                self.assertEqual(self.tool(operation, payload)['error'], 'INVALID_CREATION_INPUT')
        self.assertEqual(effects(self.binding), [])

    def test_lost_prepare_and_start_reply_reconcile_same_command_and_bytes(self):
        row = self.prepare()  # Discard delivered reply, as an interrupted agent would.
        recovered = self.tool('status')
        self.assertEqual(self.command(recovered), self.command(row))
        self.assertEqual(self.prepare()['request'], row['request'])
        self.assertEqual(effects(self.binding), [])
        self.tool('start',self.command(recovered))  # Discard delivered start reply.
        settle(self.runtime)
        original = self.tool('status')
        self.assertEqual(original['state'], 'Ready for review')
        self.tool('start',self.command(row))
        data = bytearray();offset=0
        while True:
            chunk = self.rpc('chunk',dict(request=row['request'],take=row['candidate'],offset=offset))
            part = base64.b64decode(chunk['bytes'])
            self.assertEqual(hashlib.sha256(part).hexdigest(),chunk['chunk_sha256'])
            data.extend(part);offset+=len(part)
            if offset == chunk['total']: break
        self.assertEqual(hashlib.sha256(data).hexdigest(),chunk['sha256'])
        self.assertEqual(len(effects(self.binding)),1)
        self.assertNotIn('direction',original)
        self.assertNotIn(str(self.temp.name),json.dumps(original))
        self.assertEqual(self.rpc('list')['creations'][0]['request'],row['request'])
        self.assertEqual(original['takes'][0]['review'],'Not reviewed')

    def test_listing_import_contract_and_root_scope(self):
        row = self.prepare()
        listing = self.rpc('list')
        self.assertEqual(len(listing['creations']), 1)
        source = listing['creations'][0]
        self.assertEqual({key: source[key] for key in ('request', 'revision', 'kind', 'direction')},
                         dict(request=row['request'], revision=row['revision'], kind='Sound effects',
                              direction='Synthetic metallic door slam'))
        self.assertIn('error', self.rpc('list', root='foreign'))
        self.rpc('admit', root='foreign')
        self.assertEqual(self.rpc('list', root='foreign')['creations'], [])
        self.assertEqual(self.rpc('list', {'root': 'canonical-root'})['error'], 'INVALID_CREATION_INPUT')
        self.assertEqual(effects(self.binding), [])

    def test_concurrent_start_one_child_and_changed_command_refused(self):
        row = self.prepare(seconds=0.1)
        results=[]
        threads=[threading.Thread(target=lambda:results.append(self.tool('start',self.command(row)))) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        settle(self.runtime)
        self.assertTrue(all('error' not in r for r in results),results)
        self.assertEqual(len(effects(self.binding)),1)
        self.assertEqual(self.tool('start',dict(self.command(row),command=identity()))['error'],'CREATION_COMMAND_CONFLICT')

    def test_stale_intent_and_policy_no_effect(self):
        row = self.prepare()
        self.runtime.store.save(SaveRequest(command=identity(),id=row['request'],expected=1,text='Changed synthetic direction',kind='Sound effects'))
        self.assertEqual(self.tool('start',self.command(row))['error'],'STALE_REVISION')
        self.runtime.policy = replace(self.runtime.policy,revision='changed')
        self.assertEqual(self.tool('status')['error'],'CREATION_WORKFLOW_REVIEW_REQUIRED')
        self.assertEqual(effects(self.binding),[])

    def test_denied_effect_prepare_remains_saved_and_not_replanned(self):
        self.runtime.policy = replace(self.runtime.policy,local_generator=False)
        row = self.prepare()
        self.assertEqual(self.tool('start',self.command(row))['error'],'CREATION_EFFECT_REVIEW_REQUIRED')
        self.assertEqual(self.tool('status')['request'],row['request'])
        self.assertEqual(self.tool('prepare',{'direction':'Another direction'})['error'],'CREATION_UNRESOLVED')
        self.assertEqual(effects(self.binding),[])

    def test_stop_before_start_late_start_does_not_launch(self):
        row = self.prepare()
        stopped = self.tool('stop',self.command(row))
        self.assertEqual(stopped['state'],'Cancelled')
        self.tool('start',self.command(row))
        settle(self.runtime)
        self.assertEqual(effects(self.binding),[])

    def test_explicit_selection_review_and_refinement_same_asset(self):
        row = self.prepare(seconds=0.1)
        self.tool('start',self.command(row));settle(self.runtime)
        self.rpc('review',dict(request=row['request'],take=row['candidate'],command=identity(),outcome='Needs work'))
        selected = self.rpc('select',dict(request=row['request'],take=row['candidate'],command=identity(),revision=1))
        self.assertEqual(selected['revision'],2)
        reopened=self.tool('status')
        self.assertTrue(reopened['takes'][0]['selected'])
        self.assertEqual(reopened['takes'][0]['review'],'Needs work')
        refined=self.prepare(parent=row['request'],seconds=0.1,seed=43)
        self.assertNotEqual(refined['request'],row['request'])
        self.assertEqual(len(effects(self.binding)),1)

    def test_restart_retains_unknown_and_never_adopts_or_replays(self):
        row=self.prepare()
        self.runtime.runs.records.update(row['run'],status='Starting',certainty='possibly started')
        instance=self.runtime.instance
        self.runtime.unload()
        from studio.native.creation.runtime import CreationRuntime
        fresh=CreationRuntime(self.ctx,replace(self.runtime.policy,instance=instance,create_store=False))
        try:
            service=fresh.acquire()
            self.assertEqual(service.read('canonical-root')['state'],'Outcome unknown')
            from studio.native.creation.registration import Command
            service.start('canonical-root',Command(**self.command(row)))
            settle(fresh)
            self.assertEqual(effects(self.binding),[])
        finally: fresh.unload()

    def test_final_policy_revocation_and_corrupt_byte_rejection(self):
        row=self.prepare(seconds=0.1)
        self.runtime.runs.before_spawn=lambda:setattr(self.runtime,'policy',replace(self.runtime.policy,local_generator=False))
        self.tool('start',self.command(row));settle(self.runtime)
        self.assertEqual(effects(self.binding),[])
        self.assertEqual(self.tool('status')['state'],'Blocked')
        self.tool('start',self.command(row));settle(self.runtime)
        self.assertEqual(effects(self.binding),[])


    def test_stop_owned_running_and_late_start_no_relaunch(self):
        (self.binding.path.parent/'mode').write_text('sleep')
        self.runtime.runs.worker.grace=0.1
        entered=threading.Event()
        self.runtime.runs.worker.after_spawn=entered.set
        row=self.prepare(seconds=0.1)
        self.tool('start',self.command(row))
        self.assertTrue(entered.wait(5))
        self.tool('stop',self.command(row));settle(self.runtime)
        self.assertEqual(self.tool('status')['state'],'Cancelled')
        self.tool('start',self.command(row));settle(self.runtime)
        self.assertLessEqual(len(effects(self.binding)),1)

    def test_prepare_interruption_after_plan_commit_recovers_by_command(self):
        original=self.runtime.runs.prepare_app
        def lose_reply(model):
            original(model)
            raise RuntimeError('Synthetic interruption after commit')
        with patch.object(self.runtime.runs,'prepare_app',side_effect=lose_reply):
            failed=self.tool('prepare',dict(direction='Synthetic metallic door slam'))
        self.assertEqual(failed['error'],'CREATION_OPERATION_UNAVAILABLE')
        recovered=self.tool('status')
        self.assertTrue(recovered['run'])
        self.assertEqual(self.prepare()['command'],recovered['command'])
        self.assertEqual(effects(self.binding),[])
        self.tool('start',self.command(recovered));settle(self.runtime)
        self.assertEqual(self.tool('status')['state'],'Ready for review')
        self.assertEqual(len(effects(self.binding)),1)

    def test_start_interruption_before_engine_call_is_permanent_no_replay(self):
        row=self.prepare()
        with patch.object(self.runtime.runs,'start',side_effect=RuntimeError('Synthetic interruption')):
            self.assertIn('error',self.tool('start',self.command(row)))
        observed=self.tool('start',self.command(row))
        self.assertEqual(observed['state'],'Start interrupted - observe; no replay')
        self.assertEqual(effects(self.binding),[])

    def test_unfinished_prepare_recovers_same_effect_free_identity(self):
        with patch.object(self.runtime.runs,'prepare_app',side_effect=RuntimeError('Synthetic interruption before plan')):
            self.assertIn('error',self.tool('prepare',dict(direction='Synthetic metallic door slam')))
        row=self.tool('status')
        self.assertIsNone(row['run'])
        self.assertEqual(self.tool('prepare',dict(direction='Changed synthetic direction',parent=row['request']))['error'],
                         'CREATION_UNRESOLVED')
        resumed=self.prepare()
        self.assertEqual(resumed['request'],row['request'])
        self.assertEqual(resumed['command'],row['command'])
        self.assertIsNotNone(resumed['run'])
        self.assertEqual(effects(self.binding),[])
        self.tool('start',self.command(resumed));settle(self.runtime)
        self.assertEqual(self.tool('status')['state'],'Ready for review')
        self.assertEqual(len(effects(self.binding)),1)

    def test_other_root_busy_refusal_can_deliberately_retry_same_unentered_run(self):
        assert self.runtime.runs is not None
        entered,release=threading.Event(),threading.Event()
        self.addCleanup(release.set)
        def hold_before_spawn():
            entered.set();release.wait(10)
        self.runtime.runs.before_spawn=hold_before_spawn
        first=self.prepare(seconds=0.1)
        self.tool('start',self.command(first));self.assertTrue(entered.wait(5))
        self.rpc('admit',root='other-root')
        second=self.tool('prepare',dict(direction='Synthetic second root sound',seconds=0.1),root='other-root')
        try:
            refused=self.tool('start',self.command(second),root='other-root')
            self.assertEqual(refused['error'],'RESOURCE_BUSY')
            observed=self.tool('status',root='other-root')
            self.assertEqual(observed['state'],'Prepared')
            self.assertTrue(observed.get('prelaunch_retryable'))
            self.assertEqual(self.command(observed),self.command(second))
        finally: release.set();settle(self.runtime)
        self.assertEqual(len(effects(self.binding)),1)
        self.runtime.runs.before_spawn=lambda:None
        self.tool('start',self.command(second),root='other-root');settle(self.runtime)
        self.assertEqual(self.tool('status',root='other-root')['state'],'Ready for review')
        self.assertEqual(len(effects(self.binding)),2)

    def test_corrupt_retained_media_and_foreign_take_read_refused(self):
        row=self.prepare(seconds=0.1)
        self.tool('start',self.command(row));settle(self.runtime)
        payload=dict(request=row['request'],take=row['candidate'],offset=0)
        self.rpc('admit',root='foreign')
        self.assertEqual(self.rpc('chunk',payload,root='foreign')['error'],'CREATION_SCOPE_DENIED')
        path=self.runtime.store.home/'media'/(row['candidate']+'.wav')
        path.chmod(0o600);path.write_bytes(b'Synthetic corruption')
        self.assertEqual(self.rpc('chunk',payload)['error'],'RETAINED_FILE_CORRUPT')
        self.assertEqual(len(effects(self.binding)),1)

    def test_legacy_store_and_concurrent_service_lease_refused(self):
        from studio.native.creation.runtime import CreationRuntime, MediaStore
        from studio.domain import Fault
        competing=CreationRuntime(self.ctx,replace(self.runtime.policy,instance=self.runtime.instance))
        try:
            with self.assertRaises(Fault) as denied: competing.acquire()
            self.assertEqual(denied.exception.code,'CREATION_STORE_BUSY')
        finally: competing.unload()
        ctx=Context(Path(self.temp.name)/'legacy-owned-data')
        MediaStore(ctx.state.data_dir/'media')
        legacy=CreationRuntime(ctx,self.runtime.policy)
        try:
            with self.assertRaises(Fault) as denied: legacy.acquire()
            self.assertEqual(denied.exception.code,'CREATION_STORE_REVIEW_REQUIRED')
        finally: legacy.unload()

    def test_native_collection_recovery_retains_original_no_new_generation(self):
        assert self.runtime.runs is not None
        calls=[]
        def interrupted_once():
            calls.append(True)
            if len(calls)==1: raise RuntimeError('Synthetic collection interruption')
        self.runtime.runs.collection.after_finalize=interrupted_once
        row=self.prepare(seconds=0.1)
        self.tool('start',self.command(row));settle(self.runtime)
        recovered=self.tool('status')
        self.assertEqual(recovered['state'],'Ready for review')
        self.assertEqual(recovered['recovery']['state'],'Completed')
        self.assertEqual(recovered['recovery']['last_result'],row['run'])
        self.assertEqual(recovered['takes'][0]['id'],row['candidate'])
        self.assertEqual(len(effects(self.binding)),1)

    def test_release_instruction_drift_refuses_registration(self):
        from studio.domain import Fault
        with patch('studio.native.creation.registration.GUIDANCE','unreviewed substitution'):
            with self.assertRaises(Fault) as denied: register(Context(Path(self.temp.name)/'unused'))
            self.assertEqual(denied.exception.code,'CREATION_CONTRACT_DRIFT')


if __name__=='__main__': unittest.main()
