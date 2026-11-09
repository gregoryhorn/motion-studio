"""Prepared UI requests are data, not admission or execution authority.

Host wiring (plugin-only, no host HTTP tool-dispatch route)::

    handoffs = build_handoff_integrations(
        plugin_root, execution=integrations['_execution_adapter'],
        resolve_binding=service.resolve_binding,
        session_binding=verified_target_session)
    service.integrations.update({k: v for k, v in handoffs.items()
                                 if k.startswith('OP-')})

``verified_target_session(context)`` is a SERVER-ONLY resolver. Return None when
no independently authenticated conversation binding exists, or a dict containing
session_id (durable history ID), session_key (approval route), owner_subject,
and profile_home. Never copy a focused browser ID or request JSON into it.
Without this resolver preparation still works, but execution fails closed.
The factory installs the bridge for tools in THIS plugin process/profile. A
separate plugin process must construct the same integrations against the same
owned root; no daemon, RPC execution endpoint or alternate job engine is added.

Finite schema refs: motion/ui/asset-probe/v1 (diagnose) and
motion/ui/render-launch/v1 (scene_generate). All other intents are unsupported.
The latter launches an existing exact render preflight, not scene generation.
Status reads the stored actual return and that exact native job's manifests;
it does not run workers, infer receipts, or turn composer insertion into sent.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import json
from pathlib import Path
import re
import threading
import time
import uuid

from .contracts import ContractError, digest
from .ui_media import fail, sha
from .ui_sqlite import open_owned

TOOL = 'motion_ui_handoff'
PROBE = 'motion/ui/asset-probe/v1'
RENDER = 'motion/ui/render-launch/v1'
_BRIDGES = {}
_LOCK = threading.RLock()
_ID = re.compile(r'^handoff_[0-9a-f]{32}$')


def handoff_tool_schema():
    return {'name': TOOL, 'description':
        'Inspect or execute one immutable prepared Motion Studio UI request. '
        'Execute only in its matched admitted conversation; native exact-plan '
        'approval remains required. Preparation/insertion is never a grant.',
        'parameters': {'type': 'object', 'additionalProperties': False,
            'properties': {'action': {'type': 'string', 'enum': ['inspect', 'execute']},
                'handoff_id': {'type': 'string', 'pattern': _ID.pattern}},
            'required': ['action', 'handoff_id']}}


def _args(args):
    if (not isinstance(args, dict) or set(args) != {'action', 'handoff_id'} or
            args['action'] not in ('inspect', 'execute') or
            not isinstance(args['handoff_id'], str) or not _ID.fullmatch(args['handoff_id'])):
        fail('INVALID_ARGUMENT', 'Only action and an immutable prepared handoff_id are accepted.')


def _home():
    from hermes_constants import get_hermes_home
    return str(get_hermes_home())


def _identity(host_context):
    """Read real task-local host values, never tool JSON or UI connection IDs."""
    from hermes_cli.plugin_session import session_key, session_surface
    from gateway.session_context import bound_session_key, get_session_env
    key = bound_session_key()
    sid = get_session_env('HERMES_SESSION_ID', '')
    owner = get_session_env('HERMES_SESSION_USER_ID', '')
    profile = get_session_env('HERMES_SESSION_PROFILE', '')
    if (not key or key != session_key() or not sid or not owner or
            host_context.get('session_id') != sid):
        fail('AUTHORITY_REQUIRED', 'A real task-local admitted Hermes session is required.')
    return {'session_id': sid, 'session_key': key, 'owner_subject': owner,
            'profile_home': _home(), 'profile_name': profile,
            'surface': session_surface(), 'task_id': host_context.get('task_id') or ''}


def _same_owner(stored, subject):
    from gateway.owner_identity import same_owner
    return bool(stored and subject and same_owner(stored, subject))


def _installed():
    with _LOCK:
        bridge = _BRIDGES.get(_home())
    if bridge is None:
        fail('INTEGRATION_UNAVAILABLE', 'Prepared-request service is not installed in this plugin process/profile.')
    return bridge


def observe_handoff_call(**event):
    """Public pre_tool_call hook: persist exact normal-loop association only."""
    if event.get('tool_name') != TOOL:
        return
    try:
        bridge = _installed()
        identity = _identity(event)
        args = event.get('args')
        _args(args)
        required = ('tool_call_id', 'turn_id', 'api_request_id')
        if not all(isinstance(event.get(k), str) and event[k] for k in required):
            return  # Absence never becomes a fabricated call/turn ID.
        bridge.observe(args, identity, {k: event[k] for k in required})
    except (ContractError, ImportError):
        return  # Handler reports a closed admission failure; no effects here.


def handoff_handler(args, **host_context):
    try:
        _args(args)
        result = _installed().tool(args, _identity(host_context))
        return json.dumps({'ok': True, 'tool': TOOL, 'action': args['action'], 'data': result},
                          ensure_ascii=True, allow_nan=False)
    except ContractError as exc:
        return json.dumps({'ok': False, 'tool': TOOL, 'error': {
            'code': exc.code, 'message': exc.message,
            'effect': getattr(exc, 'effect', 'none')}}, ensure_ascii=True, allow_nan=False)


class UIHandoff:
    def __init__(self, root, *, execution, resolve_binding, session_binding=None,
                 clock=time.time):
        self.root = Path(root) / 'ui-handoffs-v1'
        self.execution = execution
        self.resolve_binding = resolve_binding
        self.session_binding = session_binding
        self.clock = clock
        self.profile_home = _home()

    @contextmanager
    def database(self):
        db = open_owned(self.root, 'handoffs.sqlite3')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS handoffs(id TEXT PRIMARY KEY, frozen TEXT NOT NULL, hash TEXT NOT NULL, state TEXT NOT NULL, outcome TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, args_hash TEXT NOT NULL, identity TEXT NOT NULL, observation TEXT NOT NULL, consumed INTEGER NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)

    def _load(self, db, hid):
        row = db.execute('SELECT * FROM handoffs WHERE id=?', (hid,)).fetchone()
        if row is None:
            fail('NOT_FOUND', 'Prepared request is unavailable.')
        frozen = json.loads(row['frozen'])
        if sha(frozen) != row['hash'] or frozen['handoff_id'] != hid:
            fail('HASH_MISMATCH', 'Prepared request identity/hash differs.')
        return row, frozen

    @staticmethod
    def _scope(context):
        scope = context.get('scope', {})
        keys = ('backend_instance_id', 'connection_id', 'profile_id', 'native_project_id')
        if not context.get('principal') or not all(isinstance(scope.get(k), str) and scope[k] for k in keys):
            fail('AUTH_REQUIRED', 'Authenticated exact Project scope is required.')
        return {k: scope[k] for k in keys}

    def _pins(self, context):
        self._scope(context)
        try:
            return {'scope': context['scope'], 'principal': context['principal'],
                'composition_id': context['composition']['composition_id'],
                'composition_revision': context['composition']['composition_revision'],
                'version_id': context['version']['version_id'],
                'version_sha256': context['version']['sha256'],
                'private_project_id': context['private_project_id'],
                'private_project_revision': context['private_project_revision']}
        except KeyError:
            fail('PRECONDITION_REQUIRED', 'A saved exact composition binding is required.')

    def _target(self, context):
        target = self.session_binding(context) if self.session_binding else None
        if target is None:
            return None
        keys = ('session_id', 'session_key', 'owner_subject', 'profile_home')
        if (not isinstance(target, dict) or not all(isinstance(target.get(k), str) and target[k] for k in keys)
                or target['profile_home'] != self.profile_home
                or not _same_owner(context['principal'], target['owner_subject'])):
            fail('PERMISSION_DENIED', 'Independent target session owner/profile binding is unavailable.')
        return {k: target[k] for k in keys}

    def callback(self, context, input, pre):
        if context['operation_id'] == 'OP-HANDOFF-PREPARE':
            return self.prepare(context, input, pre)
        if context['operation_id'] == 'OP-HANDOFF-STATUS':
            return self.status(context, context['params']['handoff_id'])
        fail('UNSUPPORTED_OPERATION', 'No other handoff operation is supported.')

    def prepare(self, context, input, pre):
        pins = self._pins(context)
        if (pre.get('version_id') != pins['version_id'] or
                pre.get('composition_revision') != pins['composition_revision']):
            fail('STALE_DEPENDENCY', 'Handoff must name this exact saved version/revision.')
        required = {'intent', 'operation_schema_ref', 'selected_entity_ids', 'parameters', 'expected_effects', 'rationale'}
        if not isinstance(input, dict) or set(input) != required:
            fail('PARAMETER_INVALID', 'A complete finite handoff request is required.')
        recipe = input['operation_schema_ref']
        if isinstance(recipe, dict):
            # Explicitly reject unverified object refs: only these literal schema IDs are supported.
            fail('INTENT_UNSUPPORTED', 'Select a literal supported handoff schema ID.')
        selected, parameters = input['selected_entity_ids'], input['parameters']
        if (not isinstance(selected, list) or len(selected) != 1 or
                not isinstance(selected[0], str) or not isinstance(parameters, dict) or
                not isinstance(input['expected_effects'], list) or
                not isinstance(input['rationale'], str) or not 1 <= len(input['rationale']) <= 4096):
            fail('PARAMETER_INVALID', 'Select one resource with typed parameters and bounded rationale.')
        native_plan = None
        with self.execution.media.database(context) as (db, _):
            if recipe == PROBE and input['intent'] == 'diagnose':
                if (set(parameters) != {'asset_version_id', 'sha256', 'full_decode'} or
                        type(parameters['full_decode']) is not bool):
                    fail('PARAMETER_INVALID', 'Probe requires an exact asset version/hash and full_decode boolean.')
                record = self.execution.media.get(db, 'asset', selected[0])
                source_pre = {**pre, 'entity_revision': record['entity_revision']}
                selected_context = {**context, 'params': {**context['params'], 'asset_id': selected[0]}}
                record = self.execution._selected_asset(db, selected_context, parameters, source_pre)
                source = {k: copy.deepcopy(record[k]) for k in ('asset_id', 'asset_version_id', 'sha256', 'entity_revision')}
                operation = 'OP-ASSET-PROBE'
                payload = parameters
            elif recipe == RENDER and input['intent'] == 'scene_generate':
                if set(parameters) != {'plan_id', 'plan_sha256', 'effects_sha256'}:
                    fail('PARAMETER_INVALID', 'Render launch requires exact plan/effects pins.')
                retained = self.execution.get(db, context, 'preflight', selected[0])
                public = retained['public']
                if (public['action'] != 'render' or public['version_id'] != pins['version_id'] or
                        public['composition_revision'] != pins['composition_revision'] or
                        any(parameters[k] != public[k] for k in parameters)):
                    fail('STALE_DEPENDENCY', 'Select an exact render preflight for this saved version.')
                runtime = self.execution.runtime(context)
                plan = runtime.compiler.load(pins['private_project_id'], retained['plan'])
                if input['expected_effects'] != plan['effects']:
                    fail('PARAMETER_INVALID', 'Expected effects differ from the immutable native plan.')
                source = {'preflight_id': selected[0], 'preflight_sha256': public['preflight_sha256']}
                native_plan = retained['plan']
                source_pre = pre
                operation = 'OP-JOB-LAUNCH'
                payload = {**parameters, 'preflight_id': selected[0]}
            else:
                fail('INTENT_UNSUPPORTED', 'Only exact asset probes and existing render-preflight launches are supported.')
        frozen = {'handoff_id': 'handoff_' + uuid.uuid4().hex, 'pins': copy.deepcopy(pins),
            'profile_home': self.profile_home, 'target': self._target(context),
            'request': copy.deepcopy(input), 'source': source, 'operation': operation,
            'input': copy.deepcopy(payload), 'pre': copy.deepcopy(source_pre),
            'plan': copy.deepcopy(native_plan), 'expires_epoch': self.clock() + 1800}
        # Also bounds retained structured values. No caller storage path is ever used.
        if len(self._json(frozen).encode('utf-8')) > 65536:
            fail('PARAMETER_INVALID', 'Prepared request exceeds its bound.')
        with self.database() as db:
            db.execute('INSERT INTO handoffs VALUES(?,?,?,?,NULL)',
                       (frozen['handoff_id'], self._json(frozen), sha(frozen), 'prepared'))
        return self._public(frozen, 'prepared', None)

    def _public(self, frozen, state, outcome):
        from datetime import datetime, timezone
        hid = frozen['handoff_id']
        expired = self.clock() >= frozen['expires_epoch'] and state == 'prepared'
        result = {'handoff_id': hid, 'version_id': frozen['pins']['version_id'],
            'sha256': sha(frozen), 'state': 'expired' if expired else state,
            'expires_at': datetime.fromtimestamp(frozen['expires_epoch'], timezone.utc).isoformat(),
            'expected_effects': frozen['request']['expected_effects'],
            'composer_payload': {'tool': TOOL, 'arguments': {'action': 'inspect', 'handoff_id': hid},
                                 'request_sha256': sha(frozen)},
            'request': frozen['request'], 'source': frozen['source'],
            'evidence_gaps': ([] if frozen['target'] else ['TRUSTED_TARGET_SESSION_UNAVAILABLE'])}
        if outcome:
            result['observation'] = outcome
        return copy.deepcopy(result)

    def status(self, context, hid):
        scope = self._scope(context)
        with self.database() as db:
            row, frozen = self._load(db, hid)
        if (scope != frozen['pins']['scope'] or context['principal'] != frozen['pins']['principal'] or
                context.get('params', {}).get('composition_id') != frozen['pins']['composition_id']):
            fail('NOT_FOUND', 'Prepared request is unavailable in this owner/scope.')
        outcome = json.loads(row['outcome']) if row['outcome'] else None
        if outcome and outcome.get('job_id'):
            outcome = self._native_observation(frozen, outcome, context)
        return self._public(frozen, row['state'], outcome)

    def _native_observation(self, frozen, retained, context):
        """Read only this admitted result's job; never search 'latest probe'."""
        outcome = copy.deepcopy(retained)
        try:
            runtime = self.execution.runtime({**context,
                'private_project_id': frozen['pins']['private_project_id']})
            pid, jid = frozen['pins']['private_project_id'], retained['job_id']
            bundle = runtime.jobs().read(pid, jid)
            job = bundle['job']
            if (job['job_id'] != jid or job['project_id'] != pid or
                    job['request_id'] != retained['native_request_id'] or
                    job['request_sha256'] != retained['native_request_sha256'] or
                    job['plan'] != retained['plan']):
                fail('HASH_MISMATCH', 'Native job correlation changed.')
            runtime.compiler.load(pid, job['plan'])
            outcome['backend_state'] = job['state']
            outcome['job_revision'] = job['job_revision']
            outcome['receipt_refs'] = []
            if frozen['operation'] == 'OP-ASSET-PROBE':
                for record in bundle['artifacts']:
                    pin = {k: record[k] for k in ('artifact_id', 'sha256')}
                    if (pin not in job['outputs'] or record['kind'] != 'report' or
                            record['producer']['adapter_id'] != 'ffmpeg.probe'):
                        continue
                    expected = frozen['source']['sha256'].removeprefix('sha256:')
                    sources = [p for p in record['inputs'] if p['sha256'].removeprefix('sha256:') == expected]
                    if len(sources) != 1:
                        fail('HASH_MISMATCH', 'Probe report source differs from the prepared bytes.')
                    resolved = runtime.artifacts.resolve(pid, pin)
                    with runtime.artifacts.open_record(runtime.projects._filesystem(), resolved) as stream:
                        payload = stream.read(1048577)
                    if len(payload) > 1048576:
                        fail('LIMIT_EXCEEDED', 'Probe receipt exceeds its bounded read.')
                    receipt = json.loads(payload)
                    if (receipt.get('schema') != 'motion/v1/probe-receipt' or
                            receipt.get('artifact') != sources[0] or not receipt.get('receipt_id')):
                        fail('HASH_MISMATCH', 'Exact job probe receipt does not bind its source.')
                    outcome['receipt_refs'].append({'receipt_id': receipt['receipt_id'],
                        'report': pin, 'source': receipt['artifact'], 'job_id': jid})
            outcome['evidence_gaps'] = [] if job['state'] == 'succeeded' else ['NATIVE_JOB_NOT_SUCCEEDED']
            if frozen['operation'] == 'OP-ASSET-PROBE' and not outcome['receipt_refs']:
                outcome['evidence_gaps'].append('EXACT_JOB_PROBE_RECEIPT_UNAVAILABLE')
        except ContractError as exc:
            outcome['evidence_gaps'] = ['NATIVE_CORRELATION_UNAVAILABLE']
            outcome['correlation_error'] = exc.code
        except Exception:
            outcome['evidence_gaps'] = ['NATIVE_CORRELATION_UNAVAILABLE']
        return outcome

    def observe(self, args, identity, observation):
        with self.database() as db:
            db.execute('INSERT OR IGNORE INTO calls VALUES(?,?,?,?,0)',
                (observation['tool_call_id'], digest(args), self._json(identity), self._json(observation)))

    def _admit(self, db, args, identity):
        rows = db.execute('SELECT * FROM calls WHERE args_hash=? AND identity=? AND consumed=0',
                          (digest(args), self._json(identity))).fetchall()
        if len(rows) != 1:
            fail('AUTHORITY_REQUIRED', 'Exactly one unconsumed normal agent tool call must match this request/session/task.')
        row = rows[0]
        db.execute('UPDATE calls SET consumed=1 WHERE id=?', (row['id'],))
        return json.loads(row['observation'])

    def _authorize(self, frozen, identity):
        target = frozen['target']
        if (not target or frozen['profile_home'] != identity['profile_home'] or
                any(target[k] != identity[k] for k in ('session_id', 'session_key', 'profile_home')) or
                not _same_owner(frozen['pins']['principal'], identity['owner_subject']) or
                not _same_owner(target['owner_subject'], identity['owner_subject'])):
            fail('PERMISSION_DENIED', 'Prepared request does not match the actual admitted owner/profile/session.')

    def _context(self, frozen):
        pins = frozen['pins']
        resolved = self.resolve_binding(pins['scope']['native_project_id'], pins['composition_id'],
            version_id=pins['version_id'], principal=pins['principal'])
        context = {**resolved, 'principal': pins['principal'],
            'params': {'native_project_id': pins['scope']['native_project_id'],
                       'composition_id': pins['composition_id']}}
        if self._pins(context) != pins:
            fail('STALE_DEPENDENCY', 'Prepared composition/source scope no longer matches the server binding.')
        return context

    def _validate_source(self, context, frozen):
        """Recheck retained request pins BEFORE entering an effectful callback."""
        with self.execution.media.database(context) as (db, _):
            if frozen['operation'] == 'OP-ASSET-PROBE':
                selected = {**context, 'params': {**context['params'],
                    'asset_id': frozen['source']['asset_id']}}
                record = self.execution._selected_asset(db, selected, frozen['input'], frozen['pre'])
                if any(record[k] != v for k, v in frozen['source'].items()):
                    fail('STALE_DEPENDENCY', 'Prepared source pins differ from the current exact source.')
            else:
                retained = self.execution.get(db, context, 'preflight', frozen['source']['preflight_id'])
                if (retained['plan'] != frozen['plan'] or
                        retained['public']['preflight_sha256'] != frozen['source']['preflight_sha256']):
                    fail('STALE_DEPENDENCY', 'Prepared preflight/plan identity changed.')
                self.execution.runtime(context).compiler.load(context['private_project_id'], frozen['plan'])

    def tool(self, args, identity):
        _args(args)
        with self.database() as db:
            row, frozen = self._load(db, args['handoff_id'])
            self._authorize(frozen, identity)
            observation = self._admit(db, args, identity)
            if args['action'] == 'inspect':
                return self._public(frozen, row['state'], json.loads(row['outcome']) if row['outcome'] else None)
            if row['state'] != 'prepared':
                # Unknown/in-progress is deliberately not retried after a process crash.
                return self._public(frozen, row['state'], json.loads(row['outcome']) if row['outcome'] else None)
            if self.clock() >= frozen['expires_epoch']:
                fail('EXPIRED', 'Prepare a new exact request; this request has expired.')
            db.execute("UPDATE handoffs SET state='observed',outcome=? WHERE id=?",
                       (self._json({'call': observation, 'effect_state': 'unknown'}), frozen['handoff_id']))
        # Persist the claim BEFORE effects; never hold the SQLite lock through approvals.
        outcome = {'call': observation, 'session_id': identity['session_id'],
                   'request_sha256': sha(frozen), 'effect_state': 'unknown'}
        state = 'observed'
        try:
            context = self._context(frozen)
            self._validate_source(context, frozen)
            context.update(operation_id=frozen['operation'],
                command_id=str(uuid.uuid5(uuid.NAMESPACE_URL, frozen['handoff_id'])),
                host_session_id=identity['session_id'], host_task_id=identity['task_id'])
            if frozen['operation'] == 'OP-ASSET-PROBE':
                context['params']['asset_id'] = frozen['source']['asset_id']
            # These are the ONLY callbacks invoked, inside the genuine admitted call.
            # NativeRuntime still obtains its own exact plan/effects policy grant.
            returned = self.execution.callback(context, frozen['input'], frozen['pre'])
            outcome['result'] = copy.deepcopy(returned)
            job = returned.get('job', returned)
            jid = job.get('job_id') if isinstance(job, dict) else None
            if not isinstance(jid, str) or not jid:
                fail('CORRELATION_UNAVAILABLE', 'The backend did not return a real native job identity.')
            native = self.execution.runtime(context).jobs().read(context['private_project_id'], jid)
            from .ui_execution import command_id
            label = 'asset-probe' if frozen['operation'] == 'OP-ASSET-PROBE' else 'launch'
            actual = native['job']
            if (actual['job_id'] != jid or actual['project_id'] != context['private_project_id'] or
                    actual['request_id'] != command_id(context, label) or
                    (frozen['plan'] is not None and actual['plan'] != frozen['plan'])):
                fail('HASH_MISMATCH', 'Returned native job does not match the prepared request identity/plan.')
            outcome.update(effect_state='committed', job_id=jid, plan=actual['plan'],
                native_request_id=actual['request_id'], native_request_sha256=actual['request_sha256'],
                backend_state=actual['state'], result_sha256=sha(returned),
                evidence_gaps=['NATIVE_JOB_COMPLETION_NOT_OBSERVED'])
            # No receipt ID is invented; later job/asset APIs expose collected receipts.
        except ContractError as exc:
            effect = getattr(exc, 'effect', 'unknown')
            outcome['error'] = {'code': exc.code, 'effect': effect}
            # Once entered, noncommitted failures may still have compiled a plan.
            # Do not automatically retry or claim no effects from an error envelope.
            outcome['effect_state'] = 'unknown'
            state = 'rejected' if exc.code in ('PERMISSION_DENIED', 'AUTHORITY_REQUIRED', 'STALE_DEPENDENCY') else 'observed'
        except Exception:
            outcome['error'] = {'code': 'BACKEND_UNAVAILABLE', 'effect': 'unknown'}
        with self.database() as db:
            db.execute('UPDATE handoffs SET state=?,outcome=? WHERE id=?',
                       (state, self._json(outcome), frozen['handoff_id']))
        return self._public(frozen, state, outcome)


def build_handoff_integrations(root, *, execution, resolve_binding,
                               session_binding=None, clock=time.time):
    """Register lazy plugin-owned callbacks; no storage or engine work at construction.

    Merge only OP-* keys into UIService.integrations; keep _handoff_bridge private.
    resolve_binding is UIService.resolve_binding (it reauthorizes edit/Project).
    session_binding is optional, independently authenticated host correlation,
    NEVER an approval or effect grant. Absent binding yields prepared-only data.
    """
    bridge = UIHandoff(root, execution=execution, resolve_binding=resolve_binding,
                       session_binding=session_binding, clock=clock)
    with _LOCK:
        _BRIDGES[bridge.profile_home] = bridge
    return {'OP-HANDOFF-PREPARE': bridge.callback, 'OP-HANDOFF-STATUS': bridge.callback,
            '_handoff_bridge': bridge}
