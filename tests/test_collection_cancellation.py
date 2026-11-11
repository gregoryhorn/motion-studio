"""Deterministic collection recovery action-start races; harmless native fixture only."""
import threading
from unittest.mock import patch
from studio.persistence.store import identity
from studio.domain import Fault
from studio.runs.recovery import Recovery
from tests.test_quick_create import NormalFixture
from tests.producer_support import effects


class CollectionCancellationTests(NormalFixture):
    def blocked_pair(self):
        item, request, _ = self.prepare(options={'seconds':0.1})
        def interrupted():
            raise OSError('Controlled collection interruption')
        with patch.object(self.runs.collection,'after_finalize',interrupted), patch.object(self.runs.recovery,'after'):
            row = self.start(item)
        self.assertEqual(row['status'],'Collection blocked')
        original = (self.runs.store.home/'media'/(row['candidate']+'.wav')).read_bytes()
        return row, request, original

    def change(self, kind, row, request):
        if kind == 'stop':
            return self.post(f'/api/sfx/runs/{row["id"]}/stop',{})
        if kind == 'suppression':
            return self.post(f'/api/sfx/runs/{row["id"]}/suppress-recovery',{})
        if kind == 'save':
            return self.post('/api/requests',dict(command=identity(),id=request['id'],expected=1,
                text='Changed non-private collection fixture',kind='Sound effects',purpose='Fixture'))
        revised = self.runs.bindings.revise(self.record['id'],self.runs.bindings.get(self.record['id'])['revision'])
        return self.post('/api/apps/method',dict(request=request['id'],binding=revised['id'],revision=revised['revision'],operation='sfx'))

    def worker(self, row):
        thread = threading.Thread(target=self.runs.recovery.after,args=(row['id'],lambda:self.owner))
        thread.start()
        return thread

    def test_committed_stop_save_method_or_suppression_before_action_start_prevents_collection(self):
        for kind in ('stop','save','method','suppression'):
            with self.subTest(kind=kind):
                row, request, original = self.blocked_pair()
                entered, release = threading.Event(), threading.Event()
                recovery = self.runs.recovery
                real_check, real_get = recovery.check_intent, recovery.get
                checks = []
                def checked(*args, **kwargs):
                    real_check(*args, **kwargs)
                    if kwargs.get('recovery'): checks.append(True)
                def final_read(*args):
                    record = real_get(*args)
                    if threading.current_thread() is thread and len(checks) == 2 and not entered.is_set():
                        entered.set()  # Final intent check and Reserved snapshot have both completed.
                        if not release.wait(5): raise RuntimeError('Controlled schedule timed out')
                    return record
                thread = None
                with patch.object(recovery,'check_intent',checked), patch.object(recovery,'get',final_read), patch.object(
                        self.runs.collection,'collect',wraps=self.runs.collection.collect) as collect:
                    # Assign before start so the scheduling seam cannot miss the worker identity.
                    thread = threading.Thread(target=recovery.after,args=(row['id'],lambda:self.owner))
                    thread.start()
                    try:
                        self.assertTrue(entered.wait(5),'Reached final-check/pre-collection interval')
                        self.change(kind,row,request)  # HTTP transaction commits before the claim can start.
                    finally:
                        release.set()
                        thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(collect.call_count,0,'Committed cancellation/edit must win before action-start')
                self.assertEqual(self.runs.records.get(row['id'])['status'],'Collection blocked')
                record = recovery.get(request['id'])
                self.assertEqual(record['state'],'Needs attention')
                self.assertTrue(record['reserved'])
                self.assertFalse(record.get('action_started',False))
                self.assertIsNone(record['successor'])
                self.assertEqual((self.runs.store.home/'media'/(row['candidate']+'.wav')).read_bytes(),original)
                self.assertFalse(any(take['artifact']==row['candidate'] for take in self.runs.store.snapshot()['takes']))
                recovery.after(row['id'],lambda:self.owner)
                self.assertEqual(recovery.get(request['id'])['command'],record['command'])
        self.assertEqual(len(effects(self.binding)),4)

    def test_action_start_wins_and_stop_save_method_or_suppression_does_not_erase_completion(self):
        for kind in ('stop','save','method','suppression'):
            with self.subTest(kind=kind):
                row, request, original = self.blocked_pair()
                entered, release = threading.Event(), threading.Event()
                real_collect = self.runs.collection.collect
                def collect(run):
                    entered.set()  # Action-start must already be durable, before collection I/O.
                    if not release.wait(5): raise RuntimeError('Controlled schedule timed out')
                    return real_collect(run)
                with patch.object(self.runs.collection,'collect',side_effect=collect) as collector:
                    thread = self.worker(row)
                    try:
                        self.assertTrue(entered.wait(5))
                        record = self.runs.recovery.get(request['id'])
                        self.assertEqual(record['state'],'Applying')
                        self.assertTrue(record['action_started'])
                        response = self.change(kind,row,request)
                        if kind in ('stop','suppression'):
                            self.assertEqual(response['recovery_action'],'already-applying')
                        self.assertEqual(self.runs.recovery.get(request['id'])['state'],'Applying')
                    finally:
                        release.set()
                        thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(collector.call_count,1)
                self.assertEqual(self.runs.records.get(row['id'])['status'],'Ready for review')
                record = self.runs.recovery.get(request['id'])
                self.assertEqual(record['state'],'Completed')
                self.runs.recovery.attention(row,'intent')  # Delayed pre-completion callback cannot rewrite success.
                self.assertEqual(self.runs.recovery.get(request['id'])['state'],'Completed')
                self.assertTrue(record['reserved'])
                self.assertIsNone(record['successor'])
                self.assertEqual((self.runs.store.home/'media'/(row['candidate']+'.wav')).read_bytes(),original)
                for operation in ('stop','suppression'):
                    self.assertEqual(self.change(operation,row,request)['recovery_action'],'completion-won')
                    self.assertEqual(self.runs.recovery.get(request['id'])['state'],'Completed')
                self.runs.recovery.interrupted()
                self.runs.recovery.after(row['id'],lambda:self.owner)
                self.assertEqual(self.runs.recovery.get(request['id'])['state'],'Completed')
        self.assertEqual(len(effects(self.binding)),4)

    def test_cross_worker_claim_and_interrupted_start_never_repeats_collection(self):
        row, request, original = self.blocked_pair()
        record = self.runs.recovery.reserve(row,'original-collection')
        peer = Recovery(self.runs)
        barrier = threading.Barrier(2)
        answers = []
        def claim(recovery):
            barrier.wait(timeout=5)
            try:
                recovery.claim_collection(record,row)
                answers.append('claimed')
            except Fault as error:
                answers.append(error.code)
        threads = [threading.Thread(target=claim,args=(recovery,)) for recovery in (self.runs.recovery,peer)]
        for thread in threads: thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(answers,['claimed','RECOVERY_SUPPRESSED'])
        started = peer.get(request['id'])
        assert started is not None
        self.assertTrue(started['action_started'])
        with patch.object(self.runs.collection,'collect') as collect:
            peer.interrupted()  # Crash after durable action-start cannot be assumed to have done no I/O.
            peer.after(row['id'],lambda:self.owner)
            self.assertEqual(collect.call_count,0)
        current = peer.get(request['id'])
        assert current is not None
        self.assertEqual(current['state'],'Needs attention')
        self.assertTrue(current['reserved'])
        self.assertEqual(current['command'],record['command'])
        self.assertEqual((self.runs.store.home/'media'/(row['candidate']+'.wav')).read_bytes(),original)
        self.assertEqual(len(effects(self.binding)),1)

    def test_failed_started_collection_remains_attention_not_cancelled_or_retried(self):
        row, request, original = self.blocked_pair()
        def interrupted():
            raise OSError('Controlled repeated collection interruption')
        with patch.object(self.runs.collection,'after_finalize',interrupted):
            self.runs.recovery.after(row['id'],lambda:self.owner)
        record = self.runs.recovery.get(request['id'])
        self.assertEqual(record['state'],'Needs attention')
        self.assertTrue(record['action_started'])
        for operation in ('stop','suppression'):
            self.assertEqual(self.change(operation,row,request)['recovery_action'],'already-started')
            self.assertEqual(self.runs.recovery.get(request['id'])['state'],'Needs attention')
        with patch.object(self.runs.collection,'collect') as collect:
            self.runs.recovery.interrupted()
            self.runs.recovery.after(row['id'],lambda:self.owner)
            self.assertEqual(collect.call_count,0)
        self.assertEqual(self.runs.records.get(row['id'])['status'],'Collection blocked')
        self.assertEqual((self.runs.store.home/'media'/(row['candidate']+'.wav')).read_bytes(),original)
        self.assertEqual(len(effects(self.binding)),1)
