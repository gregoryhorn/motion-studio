"""PTP1 fake isolated/public context + real temporary SQLite/flock, no provider."""
import concurrent.futures
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from typing import Any
from studio.native.technical.registration import register as register_native
from studio.native.technical.runtime import TechnicalPolicy
from studio.connectors.synthesis.host import Route
from studio.persistence.primitives import identity
from tests.synthesis_support import selection, route, Facade

register: Any = register_native  # Dynamic isolated test context, checked at runtime.


class RemoteContext:
    __slots__ = ('plugin_id', 'profile_name', 'state', 'llm', 'methods', 'unloads')
    def __init__(self, root):
        self.plugin_id, self.profile_name = 'motion-studio', 'same-label'
        self.state, self.llm = SimpleNamespace(data_dir=root), Facade()
        self.methods, self.unloads = {}, []
    def register_rpc(self, name, callback): self.methods[name] = callback
    def on_unload(self, callback): self.unloads.append(callback)


class TechnicalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx = RemoteContext(Path(self.temp.name)/'plugin-data')
        self.policy = TechnicalPolicy(audience_accepted=True, revision='test-only', create_store=True, route=route())
        self.runtime = register(self.ctx, policy=self.policy)
        self.addCleanup(self.runtime.unload)

    def rpc(self, operation, payload=None, session: str | None='session-a', ctx=None):
        return (ctx or self.ctx).methods['technical.'+operation](payload or {}, session_id=session)

    def selected(self, index=0, expected=0, session='session-a'):
        return self.rpc('evidence.select', dict(expected=expected, selection=selection(index)), session)

    def prepare(self, selected, command=None, session='session-a'):
        return self.rpc('prepare', dict(command=command or identity(), evidence=selected['id'],
            revision=selected['revision'], template=selected['template']), session)

    def settle(self):
        for worker in self.runtime.service.workers: worker.join(5)

    def test_default_import_register_open_status_no_state_or_facade(self):
        ctx = RemoteContext(Path(self.temp.name)/'default')
        runtime = register(ctx)
        self.assertFalse(hasattr(ctx, '_manager'))
        self.assertEqual(len(ctx.methods), 7)
        self.assertEqual(self.rpc('status', ctx=ctx)['error'], 'TECHNICAL_ACCESS_UNAVAILABLE')
        self.assertFalse(ctx.state.data_dir.exists())
        self.assertFalse(ctx.llm.calls)
        runtime.unload(); runtime.unload()
        self.assertEqual(self.rpc('status', ctx=ctx)['error'], 'TECHNICAL_ACCESS_UNAVAILABLE')

    def test_gateway_session_required_and_closed_before_state(self):
        for operation, payload in [('status', {}), ('evidence.select', dict(expected=0, selection=selection()))]:
            self.assertEqual(self.rpc(operation, payload, session=None)['error'], 'TECHNICAL_SESSION_REQUIRED')
        for payload in ({'session_id':'other'}, {'owner':True}, {'profile':'default'}, {'path':'ignored'}, {'authorized':True}):
            self.assertIn('error', self.rpc('status', payload))
        self.assertIsNone(self.runtime.store)
        self.assertFalse(self.ctx.llm.calls)

    def test_two_fixture_proposals_same_schema_session_and_revision_recovery(self):
        for index in (0, 1):
            selected = self.selected(index, expected=index)
            row = self.prepare(selected)
            self.settle()
            reopened = self.rpc('result', dict(job=row['id']))
            self.assertEqual(reopened['state'], 'Proposal ready')
            self.assertFalse(reopened['active'])
            self.assertFalse(reopened['result']['enabled'])
            self.assertFalse(reopened['result']['qualified'])
            self.assertEqual(self.rpc('status')['latest'][0]['id'], row['id'])
            self.assertEqual(self.rpc('evidence.read', dict(evidence=selected['id']))['body'], selection(index))
        self.assertEqual(len(self.ctx.llm.calls), 2)

    def test_sessions_share_only_same_session_records_and_slot_errors_hide_identity(self):
        selected = self.selected()
        other = self.selected(session='session-b')
        self.assertIn('error', self.rpc('evidence.read', dict(evidence=selected['id']), 'session-b'))
        self.assertEqual(self.rpc('status', session='session-b')['latest'], [])
        held = []
        self.runtime.service.launch = held.append
        row = self.prepare(selected)
        conflict = self.prepare(other, session='session-b')
        self.assertEqual(conflict, dict(error='TECHNICAL_PREPARATION_ACTIVE', pre_admission=True))
        self.assertIn('error', self.rpc('result', dict(job=row['id']), 'session-b'))
        self.assertIn('error', self.rpc('abandon', dict(job=row['id']), 'session-b'))
        self.assertEqual(self.rpc('status', dict(job=row['id']))['id'], row['id'])
        self.rpc('abandon', dict(job=row['id']));held[0]()
        self.assertFalse(self.ctx.llm.calls)

    def test_exclusive_lock_same_profile_labels_and_existing_store_review(self):
        selected = self.selected()
        ctx = RemoteContext(self.ctx.state.data_dir)
        competitor = register(ctx, policy=self.policy)
        self.assertEqual(self.rpc('status', ctx=ctx)['error'], 'TECHNICAL_STORE_BUSY')
        competitor.unload()
        independent = RemoteContext(Path(self.temp.name)/'other-data')
        independent_runtime = register(independent, policy=self.policy)
        self.addCleanup(independent_runtime.unload)
        self.rpc('status', ctx=independent)
        self.assertNotEqual(self.runtime.store.instance, independent_runtime.store.instance)
        self.assertIn('error', self.rpc('evidence.read', dict(evidence=selected['id']), ctx=independent))
        instance = self.runtime.store.instance
        self.runtime.unload()
        unreviewed = RemoteContext(self.ctx.state.data_dir)
        rejected = register(unreviewed, policy=self.policy)
        self.assertEqual(self.rpc('status', ctx=unreviewed)['error'], 'TECHNICAL_STORE_REVIEW_REQUIRED')
        rejected.unload()
        restarted = register(unreviewed, policy=replace(self.policy, expected_instance=instance))
        self.addCleanup(restarted.unload)
        self.assertEqual(self.rpc('evidence.read', dict(evidence=selected['id']), ctx=unreviewed)['id'], selected['id'])
        self.assertEqual(restarted.store.generation, 2)

    def test_atomic_duplicate_changed_command_and_current_revision(self):
        selected = self.selected();held = [];self.runtime.service.launch = held.append
        command = identity()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _:self.prepare(selected, command), range(4)))
        self.assertEqual(len({row['id'] for row in rows}), 1)
        self.assertEqual(len(held), 1)
        newer = self.selected(1, expected=1)
        self.assertEqual(self.prepare(newer, command)['error'], 'COMMAND_CONFLICT')
        held[0]()
        self.assertFalse(self.ctx.llm.calls)
        self.assertEqual(self.rpc('result', dict(job=rows[0]['id']))['state'], 'Stale proposal')
        self.assertEqual(self.selected(expected=0)['error'], 'TECHNICAL_EVIDENCE_STALE')

    def test_unknown_restart_blocks_replay_and_preclaim_restart_cancels(self):
        selected = self.selected();held = [];self.runtime.service.launch = held.append
        first = self.prepare(selected)
        instance = self.runtime.store.instance
        self.runtime.unload()
        ctx = RemoteContext(self.ctx.state.data_dir)
        runtime = register(ctx, policy=replace(self.policy, expected_instance=instance))
        self.addCleanup(runtime.unload)
        self.assertEqual(self.rpc('status', dict(job=first['id']), ctx=ctx)['state'], 'Cancelled before dispatch')
        runtime.ctx.llm.hook = lambda: (_ for _ in ()).throw(RuntimeError('CONTROLLED_REJECTED_PROVIDER'))
        self.runtime, self.ctx = runtime, ctx
        second = self.prepare(selected);self.settle()
        self.assertEqual(self.rpc('result', dict(job=second['id']))['state'], 'Outcome unknown')
        runtime.unload()
        ctx2 = RemoteContext(ctx.state.data_dir)
        runtime2 = register(ctx2, policy=replace(self.policy, expected_instance=instance))
        self.addCleanup(runtime2.unload)
        self.assertTrue(self.rpc('status', dict(job=second['id']), ctx=ctx2)['active'])
        self.assertEqual(self.rpc('prepare', dict(command=identity(), evidence=selected['id'], revision=1, template=selected['template']), ctx=ctx2)['error'], 'TECHNICAL_PREPARATION_ACTIVE')
        self.assertFalse(ctx2.llm.calls)
        self.assertNotIn(b'CONTROLLED_REJECTED_PROVIDER', runtime2.store.database.read_bytes())

    def test_unload_holds_lease_until_observed_settlement_never_publishes(self):
        selected = self.selected();entered = threading.Event();release = threading.Event()
        self.ctx.llm.hook = lambda:(entered.set(), release.wait(5))
        row = self.prepare(selected);self.assertTrue(entered.wait(5))
        self.runtime.unload()
        ctx = RemoteContext(self.ctx.state.data_dir)
        competing = register(ctx, policy=replace(self.policy, expected_instance=self.runtime.store.instance))
        self.assertEqual(self.rpc('status', ctx=ctx)['error'], 'TECHNICAL_STORE_BUSY')
        release.set();self.settle()
        self.runtime.retirement.join(5)
        self.assertFalse(self.runtime.retirement.is_alive())
        reopened = self.rpc('result', dict(job=row['id']), ctx=ctx)
        self.assertEqual(reopened['state'], 'Stale proposal')
        self.assertIsNone(reopened['result'])
        competing.unload()
        self.assertEqual(len(self.ctx.llm.calls), 1)

    def test_policy_revision_drift_discards_observed_result_without_replay(self):
        selected = self.selected()
        self.ctx.llm.hook = lambda:setattr(self.policy, 'revision', 'changed-during-call')
        row = self.prepare(selected);self.settle()
        result = self.rpc('result', dict(job=row['id']))
        self.assertEqual(result['state'], 'Stale proposal')
        self.assertFalse(result['active'])
        self.assertIsNone(result['result'])
        self.assertEqual(len(self.ctx.llm.calls), 1)

    def test_fake_gateway_controllers_and_operators_share_session_not_foreign_access(self):
        dispatched = []
        def gateway(actor, operation, payload, *, operator=False, session='session-a'):
            if actor not in ('controller-one', 'controller-two') and not operator:
                return dict(error='GATEWAY_DENIED')
            dispatched.append(operation)
            return self.rpc(operation, payload, session)
        self.assertEqual(gateway('ordinary-foreign', 'status', {})['error'], 'GATEWAY_DENIED')
        self.assertEqual(dispatched, [])
        selected = gateway('controller-one', 'evidence.select', dict(expected=0, selection=selection()))
        for actor, operator in [('controller-two', False), ('session-operator', True)]:
            self.assertEqual(gateway(actor, 'evidence.read', dict(evidence=selected['id']), operator=operator)['id'], selected['id'])
        self.assertIn('error', gateway('controller-two', 'evidence.read', dict(evidence=selected['id']), session='session-b'))
        self.assertFalse(self.ctx.llm.calls)

    def test_privacy_policy_and_validator_refuse_without_raw_persistence(self):
        docs = selection();docs['sources'][0]['excerpts'][0]['text'] = 'private credential CONTROLLED_SENTINEL'
        self.assertEqual(self.rpc('evidence.select', dict(expected=0, selection=docs))['error'], 'TECHNICAL_EVIDENCE_EXCLUDED')
        self.assertIsNone(self.runtime.store)
        selected = self.selected();self.policy.route = Route()
        self.assertEqual(self.prepare(selected)['error'], 'SYNTHESIS_UNAVAILABLE')
        self.assertFalse(self.ctx.llm.calls)
        self.policy.route = route();self.ctx.llm.reply = 'CONTROLLED_REJECTED_OUTPUT'
        row = self.prepare(selected);self.settle()
        self.assertEqual(self.rpc('result', dict(job=row['id']))['state'], 'Invalid proposal')
        self.assertNotIn(b'CONTROLLED_REJECTED_OUTPUT', self.runtime.store.database.read_bytes())
        self.assertNotIn(b'CONTROLLED_SENTINEL', self.runtime.store.database.read_bytes())
