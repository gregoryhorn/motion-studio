"""Deferred source-only coverage for the plugin-owned admitted-turn bridge.

These unit fixtures are not host admission, approval, native execution or media
receipts. Run only after the operator's requested commit/enable boundary.
"""
import copy
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
from typing import Any

from studio.contracts import ContractError
from studio.ui_handoff import (UIHandoff, PROBE, RENDER, _args, _identity,
                               handoff_tool_schema, build_handoff_integrations)
from studio.ui_execution import command_id


class MediaFixture:
    def __init__(self):
        self.asset = {'asset_id': 'asset_source', 'asset_version_id': 'asset_version',
            'sha256': 'a' * 64, 'entity_revision': 1}

    @contextmanager
    def database(self, context, **kwargs):
        yield None, None

    def get(self, db, kind, identity):
        if kind != 'asset' or identity != self.asset['asset_id']:
            raise ContractError('NOT_FOUND', 'Fixture source missing.')
        return copy.deepcopy(self.asset)


class ExecutionFixture:
    def __init__(self):
        self.media = MediaFixture()
        self.calls = []
        self.plan = {'plan_id': 'plan_exact', 'plan_revision': 1, 'plan_sha256': 'b' * 64}
        self.native = MagicMock()
        self.native.compiler.load.return_value = {'effects': []}
        self.preflight: Any = None
        self.job: Any = None

    def _selected_asset(self, db, context, input, pre):
        source = self.media.asset
        if (context['params']['asset_id'] != source['asset_id'] or
                input['asset_version_id'] != source['asset_version_id'] or
                input['sha256'] != source['sha256'] or pre['entity_revision'] != source['entity_revision']):
            raise ContractError('STALE_DEPENDENCY', 'Fixture source changed.')
        return copy.deepcopy(source)

    def get(self, db, context, kind, identity):
        if kind != 'preflight' or identity != 'preflight_exact':
            raise ContractError('NOT_FOUND', 'Fixture preflight missing.')
        return self.preflight

    def runtime(self, context):
        return self.native

    def callback(self, context, input, pre):
        self.calls.append((copy.deepcopy({k: v for k, v in context.items() if k != 'project_store'}),
                           copy.deepcopy(input), copy.deepcopy(pre)))
        label = 'asset-probe' if context['operation_id'] == 'OP-ASSET-PROBE' else 'launch'
        if context['operation_id'] == 'OP-ASSET-PROBE':
            self._selected_asset(None, context, input, pre)
        self.job = {'job_id': 'job_exact', 'job_revision': 1, 'project_id': 'prj_private',
            'request_id': command_id(context, label), 'request_sha256': 'c' * 64,
            'plan': self.plan, 'state': 'queued', 'outputs': []}
        self.native.jobs.return_value.read.return_value = {'job': self.job, 'artifacts': []}
        return {'job_id': self.job['job_id'], 'state': 'queued'}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ui-handoff-')
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(patch.stopall)
        patch('studio.ui_handoff._home', return_value='/fixture/profile').start()
        patch('studio.ui_handoff._same_owner', side_effect=lambda a, b: a == b).start()
        self.execution = ExecutionFixture()
        self.context = {'scope': {'backend_instance_id': 'backend_fixture',
            'connection_id': 'connection_fixture', 'profile_id': 'profile_fixture',
            'native_project_id': 'native_fixture'}, 'principal': 'uid:fixture',
            'params': {'native_project_id': 'native_fixture', 'composition_id': 'composition_fixture'},
            'composition': {'composition_id': 'composition_fixture', 'composition_revision': 2},
            'version': {'version_id': 'version_fixture', 'sha256': 'd' * 64},
            'private_project_id': 'prj_private', 'private_project_revision': 3,
            'project_store': object()}
        self.pre = {'version_id': 'version_fixture', 'composition_revision': 2}
        self.target = {'session_id': 'history_actual', 'session_key': 'route_actual',
                       'owner_subject': 'uid:fixture', 'profile_home': '/fixture/profile'}
        self.identity = {**self.target, 'profile_name': 'default', 'surface': 'desktop', 'task_id': 'task_actual'}
        self.resolver = Mock(side_effect=lambda *a, **kw: self.context)
        self.bridge = UIHandoff(self.temporary.name, execution=self.execution,
            resolve_binding=self.resolver, session_binding=lambda c: self.target,
            clock=lambda: 1000)
        self.input = {'intent': 'diagnose', 'operation_schema_ref': PROBE,
            'selected_entity_ids': ['asset_source'], 'parameters': {
                'asset_version_id': 'asset_version', 'sha256': 'a' * 64, 'full_decode': False},
            'expected_effects': [], 'rationale': 'Inspect the selected source.'}

    def prepare(self):
        return self.bridge.prepare(self.context, self.input, self.pre)

    def admitted(self, result, action='execute', **identity):
        args = {'action': action, 'handoff_id': result['handoff_id']}
        actor = {**self.identity, **identity}
        self.bridge.observe(args, actor, {'tool_call_id': 'call_' + action,
            'turn_id': 'turn_actual', 'api_request_id': 'api_actual'})
        return self.bridge.tool(args, actor)

    def test_prepare_status_and_reopen_never_execute(self):
        public = self.prepare()
        status = self.bridge.status(self.context, public['handoff_id'])
        self.assertEqual(status['state'], 'prepared')
        self.assertEqual(status['sha256'], public['sha256'])
        self.assertFalse(self.execution.calls)
        self.assertEqual(public['composer_payload']['arguments']['action'], 'inspect')
        reopened = UIHandoff(self.temporary.name, execution=self.execution,
            resolve_binding=self.resolver, clock=lambda: 1000)
        self.assertEqual(reopened.status(self.context, public['handoff_id'])['sha256'], public['sha256'])

    def test_unobserved_direct_call_has_no_authority(self):
        public = self.prepare()
        with self.assertRaises(ContractError):
            self.bridge.tool({'action': 'execute', 'handoff_id': public['handoff_id']}, self.identity)
        self.assertFalse(self.execution.calls)

    def test_inspect_is_not_execute_and_pre_call_is_single_use(self):
        public = self.prepare()
        self.assertEqual(self.admitted(public, 'inspect')['state'], 'prepared')
        self.assertFalse(self.execution.calls)
        with self.assertRaises(ContractError):
            self.bridge.tool({'action': 'inspect', 'handoff_id': public['handoff_id']}, self.identity)

    def test_actual_result_correlates_job_plan_and_durable_request(self):
        public = self.prepare()
        result = self.admitted(public)
        observed = result['observation']
        self.assertEqual(observed['job_id'], 'job_exact')
        self.assertEqual(observed['plan'], self.execution.plan)
        self.assertEqual(observed['native_request_id'], self.execution.job['request_id'])
        self.assertEqual(observed['session_id'], 'history_actual')
        self.assertEqual(len(self.execution.calls), 1)
        self.assertEqual(self.execution.calls[0][0]['host_session_id'], 'history_actual')
        # Same immutable request cannot submit a second native job.
        args = {'action': 'execute', 'handoff_id': public['handoff_id']}
        self.bridge.observe(args, self.identity, {'tool_call_id': 'call_retry',
            'turn_id': 'turn_retry', 'api_request_id': 'api_retry'})
        self.bridge.tool(args, self.identity)
        self.assertEqual(len(self.execution.calls), 1)

    def test_owner_profile_and_session_mismatch_reject(self):
        public = self.prepare()
        for changed in ({'owner_subject': 'uid:other'}, {'session_id': 'history_other'},
                        {'session_key': 'route_other'}, {'profile_home': '/other/profile'}):
            with self.subTest(changed=changed), self.assertRaises(ContractError):
                self.admitted(public, **changed)
        self.assertFalse(self.execution.calls)

    def test_no_trusted_target_is_prepared_only(self):
        self.bridge.session_binding = None
        public = self.prepare()
        self.assertEqual(public['state'], 'prepared')
        self.assertIn('TRUSTED_TARGET_SESSION_UNAVAILABLE', public['evidence_gaps'])
        with self.assertRaises(ContractError):
            self.admitted(public)
        self.assertFalse(self.execution.calls)

    def test_foreign_owner_cannot_read_status(self):
        public = self.prepare()
        for context in ({**self.context, 'principal': 'uid:other'},
                        {**self.context, 'scope': {**self.context['scope'], 'connection_id': 'foreign'}},
                        {**self.context, 'params': {'composition_id': 'other'}}):
            with self.assertRaises(ContractError):
                self.bridge.status(context, public['handoff_id'])

    def test_expired_request_does_not_execute(self):
        public = self.prepare()
        self.bridge.clock = lambda: 9999
        self.assertEqual(self.bridge.status(self.context, public['handoff_id'])['state'], 'expired')
        with self.assertRaises(ContractError):
            self.admitted(public)
        self.assertFalse(self.execution.calls)

    def test_stale_composition_and_source_fail_closed(self):
        public = self.prepare()
        self.context['version']['sha256'] = 'e' * 64
        result = self.admitted(public)
        self.assertEqual(result['observation']['error']['code'], 'STALE_DEPENDENCY')
        self.assertFalse(self.execution.calls)

    def test_source_revision_is_frozen_and_rechecked(self):
        public = self.prepare()
        self.execution.media.asset['entity_revision'] += 1
        result = self.admitted(public)
        self.assertEqual(result['observation']['error']['code'], 'STALE_DEPENDENCY')
        self.assertNotIn('job_id', result['observation'])

    def test_unsupported_intent_and_arbitrary_dispatch_reject(self):
        for changed in ({'intent': 'caption_generate'},
                        {'operation_schema_ref': 'terminal'},
                        {'parameters': {'path': '/foreign/source', 'tool': 'terminal'}}):
            self.input.update(changed)
            with self.assertRaises(ContractError):
                self.prepare()
        for args in ({'action': 'execute', 'handoff_id': '../foreign'},
                     {'action': 'dispatch', 'handoff_id': 'handoff_' + 'a' * 32},
                     {'action': 'execute', 'handoff_id': 'handoff_' + 'a' * 32, 'root': '/foreign'}):
            with self.assertRaises(ContractError):
                _args(args)

    def test_frozen_hash_tamper_rejects(self):
        public = self.prepare()
        with self.bridge.database() as db:
            row, frozen = self.bridge._load(db, public['handoff_id'])
            frozen['request']['rationale'] = 'Changed after preparation.'
            db.execute('UPDATE handoffs SET frozen=? WHERE id=?',
                       (self.bridge._json(frozen), public['handoff_id']))
        with self.assertRaises(ContractError):
            self.bridge.status(self.context, public['handoff_id'])

    def test_unknown_crash_claim_never_retries(self):
        public = self.prepare()
        with self.bridge.database() as db:
            db.execute("UPDATE handoffs SET state='observed',outcome=? WHERE id=?",
                       (json.dumps({'effect_state': 'unknown'}), public['handoff_id']))
        result = self.admitted(public)
        self.assertEqual(result['observation']['effect_state'], 'unknown')
        self.assertFalse(self.execution.calls)

    def test_render_launch_requires_exact_existing_plan_effects(self):
        self.execution.preflight = {'public': {'action': 'render', 'version_id': 'version_fixture',
            'composition_revision': 2, 'preflight_sha256': 'f' * 64,
            'plan_id': 'plan_exact', 'plan_sha256': 'b' * 64, 'effects_sha256': 'c' * 64},
            'plan': self.execution.plan}
        self.input.update(intent='scene_generate', operation_schema_ref=RENDER,
            selected_entity_ids=['preflight_exact'], parameters={
                'plan_id': 'plan_exact', 'plan_sha256': 'b' * 64, 'effects_sha256': 'c' * 64})
        public = self.prepare()
        result = self.admitted(public)
        self.assertEqual(result['observation']['plan'], self.execution.plan)
        self.assertEqual(self.execution.calls[0][0]['operation_id'], 'OP-JOB-LAUNCH')
        self.input['expected_effects'] = [{'effect': 'invented'}]
        with self.assertRaises(ContractError):
            self.prepare()

    def test_status_uses_only_exact_job_not_latest_source_receipt(self):
        public = self.prepare()
        self.admitted(public)
        status = self.bridge.status(self.context, public['handoff_id'])
        self.assertIn('NATIVE_JOB_NOT_SUCCEEDED', status['observation']['evidence_gaps'])
        self.assertEqual(status['observation']['receipt_refs'], [])
        self.execution.native.jobs.return_value.read.assert_called_with('prj_private', 'job_exact')
        self.assertEqual(len(self.execution.calls), 1)
        self.execution.job['request_id'] = 'foreign_request'
        status = self.bridge.status(self.context, public['handoff_id'])
        self.assertEqual(status['observation']['correlation_error'], 'HASH_MISMATCH')

    def test_receipt_is_from_exact_job_report_and_selected_bytes(self):
        public = self.prepare()
        self.admitted(public)
        source = {'artifact_id': 'art_source', 'sha256': 'a' * 64}
        report = {'artifact_id': 'art_report', 'sha256': 'f' * 64}
        self.execution.job.update(state='succeeded', outputs=[report])
        bundle = self.execution.native.jobs.return_value.read.return_value
        bundle['artifacts'] = [{**report, 'kind': 'report', 'producer': {'adapter_id': 'ffmpeg.probe'},
                                'inputs': [source]}]
        receipt = {'schema': 'motion/v1/probe-receipt', 'receipt_id': 'rcp_actual', 'artifact': source}
        self.execution.native.artifacts.open_record.return_value.__enter__.side_effect = (
            lambda: io.BytesIO(json.dumps(receipt).encode()))
        status = self.bridge.status(self.context, public['handoff_id'])
        ref = status['observation']['receipt_refs'][0]
        self.assertEqual(ref, {'receipt_id': 'rcp_actual', 'report': report,
                               'source': source, 'job_id': 'job_exact'})
        receipt['artifact'] = {'artifact_id': 'art_other', 'sha256': 'a' * 64}
        status = self.bridge.status(self.context, public['handoff_id'])
        self.assertEqual(status['observation']['correlation_error'], 'HASH_MISMATCH')

    def test_identity_requires_actual_task_local_route_and_durable_session(self):
        import sys
        from types import ModuleType
        plugin_session: Any = ModuleType('hermes_cli.plugin_session')
        plugin_session.session_key = lambda: 'route_actual'
        plugin_session.session_surface = lambda: 'desktop'
        session_context: Any = ModuleType('gateway.session_context')
        env = {'HERMES_SESSION_ID': 'history_actual',
               'HERMES_SESSION_USER_ID': 'uid:fixture', 'HERMES_SESSION_PROFILE': 'default'}
        session_context.bound_session_key = lambda: 'route_actual'
        session_context.get_session_env = lambda k, default='': env.get(k, default)
        with patch.dict(sys.modules, {'hermes_cli.plugin_session': plugin_session,
                                     'gateway.session_context': session_context}):
            actual = _identity({'session_id': 'history_actual', 'task_id': 'task_actual'})
            self.assertEqual(actual['session_key'], 'route_actual')
            self.assertEqual(actual['owner_subject'], 'uid:fixture')
            with self.assertRaises(ContractError):
                _identity({'session_id': 'focused_ui_not_history'})
            session_context.bound_session_key = lambda: ''
            with self.assertRaises(ContractError):
                _identity({'session_id': 'history_actual'})

    def test_schema_is_closed_finite_and_has_no_authority_fields(self):
        schema = handoff_tool_schema()['parameters']
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['properties']), {'action', 'handoff_id'})
        self.assertEqual(schema['properties']['action']['enum'], ['inspect', 'execute'])

    def test_factory_constructs_without_storage_effects(self):
        root = Path(self.temporary.name) / 'not-created'
        integrations = build_handoff_integrations(root, execution=self.execution,
            resolve_binding=self.resolver)
        self.assertFalse(root.exists())
        self.assertEqual({k for k in integrations if k.startswith('OP-')},
                         {'OP-HANDOFF-PREPARE', 'OP-HANDOFF-STATUS'})


if __name__ == '__main__':
    unittest.main()
