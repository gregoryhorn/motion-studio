"""Finite recovery reservation, restarts, denials, cancellation and advisory privacy."""
from datetime import date
import json
import threading
import time
from unittest.mock import patch
from pydantic import ValidationError
from studio.domain import Fault
from studio.persistence.store import canonical, identity
from studio.runs.recovery import Recovery
from studio.runs.service import LocalRuns
from studio.runs.technical_knowledge import TechnicalKnowledge
from tests.test_quick_create import NormalFixture
from tests.producer_support import effects


class RecoveryGuardTests(NormalFixture):
    def test_unsaved_draft_suppression_persists_without_stopping_or_changing_original(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        self.legacy(item['id'])
        self.runs.recovery.before_action = lambda: self.post(f'/api/sfx/runs/{item["id"]}/suppress-recovery',{})
        original = self.start(item)
        record = self.runs.recovery.get(request['id'])
        self.assertEqual(original['plan']['revision'],1)
        self.assertFalse(original['stop'])
        self.assertTrue(record['reserved'])
        self.assertIsNone(record['successor'])
        self.assertEqual(record['state'],'Needs attention')
        self.runs.close()
        self.runs = LocalRuns(self.runs.store,self.binding)
        self.runs.recovery.after(item['id'],lambda:self.owner)
        self.assertEqual(len(effects(self.binding)),1)

    def test_unsupported_recipe_cannot_reserve_or_launch(self):
        item, _, _ = self.prepare(options={'seconds':0.1})
        self.runs.recovery.after = lambda *args: None
        self.legacy(item['id'])
        original = self.start(item)
        with self.assertRaises(Fault):
            self.runs.recovery.reserve(original,'unshipped-instruction')
        self.assertEqual(len(effects(self.binding)),1)

    def test_real_absent_leader_unresolved_descendant_never_recovers(self):
        (self.binding.path.parent/'mode').write_text('unresolved-descendant')
        item, request, _ = self.prepare(options={'seconds':0.1})
        row = self.start(item)
        self.assertEqual(row['status'],'Outcome unknown')
        self.assertEqual(row['process']['exit_code'],0)
        self.assertFalse(row['process']['group_retired'])
        self.assertEqual(self.runs.recovery.get(request['id'])['state'],'Needs attention')
        time.sleep(0.7)  # Bounded fixture survivor exits itself; no unverified PID signal.
        self.runs.recovery.after(item['id'],lambda:self.owner)
        self.assertEqual(len(effects(self.binding)),1)
        self.assertEqual(self.runs.records.get(item['id'])['status'],'Outcome unknown')

    def test_cancel_or_changed_intent_after_reservation_dispatches_zero_successors(self):
        for stop in (True,False):
            with self.subTest(stop=stop):
                item, request, _ = self.prepare(options={'seconds':0.1})
                self.legacy(item['id'])
                def suppress():
                    if stop: self.runs.stop(item['id'])
                    else: self.post('/api/requests',dict(command=identity(),id=request['id'],expected=1,
                        text='Changed controlled intent',kind='Sound effects',purpose='Fixture'))
                self.runs.recovery.before_action = suppress
                self.start(item)
                record = self.runs.recovery.get(request['id'])
                self.assertTrue(record['reserved'])
                self.assertIsNone(record['successor'])
                self.assertEqual(record['state'],'Needs attention')
        self.assertEqual(len(effects(self.binding)),2)

    def test_denied_current_binding_consumes_allowance_without_new_effect(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        self.legacy(item['id'])
        self.runs.recovery.before_action = lambda: self.runs.bindings.revise(
            self.record['id'],self.record['revision'],enabled=False)
        self.start(item)
        record = self.runs.recovery.get(request['id'])
        self.assertTrue(record['reserved'])
        self.assertEqual(record['state'],'Needs attention')
        successor = self.runs.records.get(record['successor'])
        self.assertEqual(successor['status'],'Blocked')
        self.assertEqual(successor['certainty'],'not attempted')
        self.assertEqual(len(effects(self.binding)),1)

    def test_failed_recovery_exhausts_shared_budget_across_edits_restart_and_callbacks(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        self.legacy(item['id'])
        self.runs.recovery.before_action = lambda: (self.binding.path.parent/'mode').write_text('output-directory')
        self.start(item)
        record = self.runs.recovery.get(request['id'])
        self.assertEqual(record['state'],'Needs attention')
        self.assertEqual(len(effects(self.binding)),2)
        self.runs.close()
        self.runs = LocalRuns(self.runs.store,self.binding)
        self.runs.recovery.after(item['id'],lambda:self.owner)
        self.assertEqual(self.runs.recovery.get(request['id'])['command'],record['command'])
        revised = self.runs.store.save(__import__('studio.domain',fromlist=['SaveRequest']).SaveRequest(
            command=identity(),id=request['id'],expected=1,text='Revised controlled fixture',kind='Sound effects',purpose='Fixture'))
        # A deliberate normal request after editing is allowed; its failure cannot refill recovery.
        from studio.producer.contracts import PrepareApp
        new = self.runs.prepare_app(PrepareApp(command=identity(),request=revised['id'],revision=2,
            binding=self.record['id'],binding_revision=self.record['revision'],operation='sfx',options={'seconds':0.1}))
        self.legacy(new['id'])
        self.runs.start(new['id'],lambda:self.owner)
        self.settle()
        self.assertEqual(len(effects(self.binding)),3)
        self.assertEqual(self.runs.recovery.get(request['id'])['command'],record['command'])

    def test_reservation_cross_worker_cas_and_restart_does_not_repeat(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        self.legacy(item['id'])
        entered, release = threading.Event(), threading.Event()
        def hold():
            entered.set()
            self.assertTrue(release.wait(5))
        self.runs.recovery.before_action = hold
        self.runs.start(item['id'],lambda:self.owner)
        self.assertTrue(entered.wait(5))
        row = self.runs.records.get(item['id'])
        peer = Recovery(self.runs)
        answers = []
        threads = [threading.Thread(target=lambda: answers.append(peer.reserve(row,'isolated-layout'))) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(answers,[None]*4)
        peer.interrupted()  # Simulates restart observation after durable reservation, before dispatch.
        release.set()
        self.settle()
        self.assertEqual(len(effects(self.binding)),1)
        record = self.runs.recovery.get(request['id'])
        self.assertTrue(record['reserved'])
        self.assertEqual(record['state'],'Needs attention')
        self.assertIsNone(record['successor'])

    def test_restart_after_linked_launch_observes_unknown_never_adopts_or_retries(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        self.legacy(item['id'])
        # Supported recipe completes once, then simulate a persisted active state at restart.
        self.start(item)
        record = self.runs.recovery.get(request['id'])
        self.runs.records.update(record['successor'],status='Running')
        with self.runs.store.transaction() as db:
            record.update(state='Applying')
            Recovery.put(db,record)
        self.runs.close()
        self.runs = LocalRuns(self.runs.store,self.binding)
        self.assertEqual(self.runs.records.get(record['successor'])['status'],'Outcome unknown')
        self.assertEqual(self.runs.recovery.get(request['id'])['state'],'Needs attention')
        self.runs.recovery.after(record['successor'],lambda:self.owner)
        self.assertEqual(len(effects(self.binding)),2)

    def test_invalid_collection_pair_no_retry_or_generation(self):
        (self.binding.path.parent/'mode').write_text('missing-receipt')
        item, request, _ = self.prepare(options={'seconds':0.1})
        row = self.start(item)
        self.assertEqual(row['status'],'Collection blocked')
        record = self.runs.recovery.get(request['id'])
        self.assertEqual(record['state'],'Needs attention')
        self.assertFalse(record['reserved'])
        self.assertEqual(len(effects(self.binding)),1)
        self.assertEqual(self.runs.store.snapshot()['takes'],[])

    def test_collection_allowance_cannot_cascade_or_retry_after_restart(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        self.runs.collection.after_finalize = lambda: (_ for _ in ()).throw(OSError('controlled fixture interruption'))
        self.start(item)
        record = self.runs.recovery.get(request['id'])
        self.assertEqual(record['recipe'],'original-collection')
        self.assertTrue(record['reserved'])
        self.assertEqual(record['state'],'Needs attention')
        self.runs.close()
        self.runs = LocalRuns(self.runs.store,self.binding)
        self.assertEqual(self.runs.records.get(item['id'])['status'],'Collection blocked')
        self.runs.recovery.after(item['id'],lambda:self.owner)
        self.assertEqual(len(effects(self.binding)),1)
        self.assertEqual(self.runs.store.snapshot()['takes'],[])

    def test_sanitized_advisory_knowledge_restart_stale_contradictory_and_sentinels(self):
        knowledge = self.runs.recovery.knowledge
        safe = dict(recipe='isolated-layout',error_class='OUTPUT_UNSAFE',condition='shared-runtime-outputs',
            result='verified',confidence='fixture-tested',verified_on=date.today().isoformat(),summary='isolated-runtime-strict-outputs')
        knowledge.remember(safe)
        knowledge = TechnicalKnowledge(self.runs.store)
        self.assertEqual(len(knowledge.applicable()['claims']),1)
        sentinel = 'NON_PRIVATE_SENSITIVE_SENTINEL'
        for patch_value in ({'prompt':sentinel},{'summary':sentinel},{'interface':sentinel},{'recipe':sentinel}):
            with self.assertRaises(ValidationError):
                knowledge.remember(dict(safe,**patch_value))
        knowledge.remember(dict(safe,result='contradicted'))
        with self.runs.store.transaction() as db:
            db.execute('INSERT INTO technical_claims VALUES(?,?)',(identity(),canonical(dict(safe,recipe_version=99))))
            db.execute('INSERT INTO technical_claims VALUES(?,?)',(identity(),canonical(dict(safe,instruction=sentinel))))
        found = knowledge.applicable()
        self.assertEqual(found['stale_or_invalid'],2)
        self.assertEqual(found['authority'],'none')
        self.assertTrue(all(claim['applicability']=='disputed' for claim in found['claims']))
        self.assertNotIn(sentinel,json.dumps(found))
        self.assertEqual(effects(self.binding),[])
