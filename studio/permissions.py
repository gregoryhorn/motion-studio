"""Profile-owned spending permission, independent of host-policy authorization.

Only host session user rows can approve a disclosure. Prompts, credentials and
media are never persisted here. A durable admitted claim is never made unused,
including after process death. Admission is the point of no return, not proof
that a provider received the request; an absent result is an unknown outcome.
"""
from __future__ import annotations

import copy
import re
from .contracts import (ContractError, TEXT, DIGEST, obj, enum, integer,
                        ident, validate, digest)
from .project import _id, _now

ACTIONS = ('permission_disclose', 'permission_grant', 'permission_inspect', 'permission_revoke')
BASE = 'permissions/consuming'


class PermissionAdmissionRefused(ContractError):
    """This new attempt did not invoke. A prior claim may remain unknown."""


NATIVE_BOUNDARY_MISSING = (
    'Consuming native handoffs are unavailable: Hermes pre_tool_call observes '
    'arguments before other modify directives and tool_execution middleware can '
    'rewrite them later. No supported mandatory fail-closed final-arguments '
    'admission callback immediately before native dispatch is exposed. A Studio '
    'grant cannot substitute for that boundary or native host approval.')


def consuming(effects):
    """Unknown or absent charging information is not an implicit free call."""
    return not isinstance(effects, dict) or effects.get('pricing') != 'free'


def require_native_admission(effects):
    if consuming(effects):
        raise ContractError('DEPENDENCY_UNAVAILABLE', NATIVE_BOUNDARY_MISSING)


def request_identity(request, *, registry=None, executable=None):
    """Hash all resolved executable semantics, retaining only non-secret labels.

    The complete binding pins implementation/schema. Inputs must already be
    resolved ArtifactRefs (JobStore._request owns document/graph resolution).
    Metadata identities are from trusted registry code, never user JSON.
    """
    required = ('project_id', 'project_revision', 'plan', 'node_id', 'request_sha256',
                'operation', 'binding', 'parameters', 'inputs', 'effects')
    if any(key not in request for key in required):
        raise ContractError('PERMISSION_DENIED', 'Resolved frozen executable identity is incomplete.')
    identities = dict(provider=None, model=None, account=None)
    if registry is not None:
        descriptor = registry.option_descriptor(request['binding']['adapter_id'], request['operation'])
        identities.update(descriptor.get('option_metadata', {}).get('identities', {}))
    executable = copy.deepcopy(executable)
    tool = executable.get('tool_name') if isinstance(executable, dict) else None
    material = {key: copy.deepcopy(request[key]) for key in required}
    material.update(binding_parameters=copy.deepcopy(request.get('binding_parameters')),
                    selection=copy.deepcopy(request.get('selection')),
                    required_features=copy.deepcopy(request.get('required_features', [])),
                    identities=identities, executable=executable)
    pins = []
    def collect(value):
        if isinstance(value, dict):
            if set(value) == {'artifact_id', 'sha256'}:
                pins.append(copy.deepcopy(value))
            else:
                for child in value.values():
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(request['inputs'])
    return dict(schema='motion/v1/consuming-request',
        request_sha256=digest(material),
        effect_sha256=digest({k: v for k, v in material.items()
            if k not in ('plan', 'node_id', 'project_revision', 'request_sha256', 'selection')}),
        project_id=request['project_id'],
        project_revision=request['project_revision'], plan=copy.deepcopy(request['plan']),
        node_id=request['node_id'], fingerprint=request['request_sha256'],
        operation=request['operation'], adapter_id=request['binding']['adapter_id'],
        binding_sha256=digest(request['binding']), parameters_sha256=digest({
            'parameters': request['parameters'], 'binding_parameters': request.get('binding_parameters'),
            'selection': request.get('selection'),
            'required_features': request.get('required_features', [])}),
        inputs_sha256=digest(request['inputs']), input_pins=pins, identities=identities, tool=tool,
        executable_sha256=digest(executable), effects=copy.deepcopy(request['effects']))


def _scope(identity, project_scope):
    return dict(project_id=identity['project_id'] if project_scope == 'project' else None,
        adapter_id=identity['adapter_id'], operation=identity['operation'], tool=identity['tool'],
        identities=copy.deepcopy(identity['identities']), binding_sha256=identity['binding_sha256'],
        inputs_sha256=identity['inputs_sha256'], executable_sha256=identity['executable_sha256'],
        effects_sha256=digest(identity['effects']),
        parameters_sha256=identity['parameters_sha256'])


def _matches(grant, identity):
    if grant['mode'] == 'single':
        return grant['identity']['request_sha256'] == identity['request_sha256']
    scope = grant['scope']
    actual = _scope(identity, 'profile' if scope['project_id'] is None else 'project')
    return scope == actual


class PermissionStore:
    def __init__(self, projects):
        self.projects = projects

    def _read(self, fs) -> dict:
        try:
            value = fs.read(BASE + '/ledger.json')
        except FileNotFoundError:
            return dict(schema='motion/v1/consuming-permissions', revision=0,
                        candidates={}, grants={}, claims={}, evidence={})
        if (value.get('schema') != 'motion/v1/consuming-permissions'
                or not isinstance(value.get('revision'), int)
                or any(not isinstance(value.get(k), dict) for k in ('candidates', 'grants', 'claims', 'evidence'))):
            raise ContractError('HASH_MISMATCH', 'Invalid consuming permission ledger; fail closed.')
        return value

    def inspect(self, *, project_id=None):
        value = self._read(self.projects._filesystem())
        if project_id is None:
            return copy.deepcopy(value)
        # A project view includes explicit profile-wide grants, not other projects.
        value = copy.deepcopy(value)
        value['candidates'] = {k: v for k, v in value['candidates'].items()
            if v['identity']['project_id'] == project_id}
        value['grants'] = {k: v for k, v in value['grants'].items()
            if v['scope']['project_id'] in (None, project_id)}
        value['claims'] = {k: v for k, v in value['claims'].items() if v['project_id'] == project_id}
        value.pop('evidence', None)
        return value

    def _write(self, fs, value):
        value['revision'] += 1
        fs.write(BASE + '/ledger.json', value, replace=True)

    @staticmethod
    def _cas(value, revision):
        if value['revision'] != revision:
            raise ContractError('REVISION_CONFLICT', 'Permission ledger changed; inspect and retry the edit, not the consuming call.')

    def disclose(self, identity, *, mode='single', project_scope='project'):
        if mode not in ('single', 'saved') or project_scope not in ('project', 'profile'):
            raise ContractError('INVALID_ARGUMENT', 'Unknown permission mode or project scope.')
        if mode == 'single' and project_scope != 'project':
            raise ContractError('INVALID_ARGUMENT', 'Single-use permission is exact and project bound.')
        if not consuming(identity['effects']):
            raise ContractError('INVALID_ARGUMENT', 'Known free operations do not need spending permission.')
        candidate = dict(schema='motion/v1/consuming-disclosure', mode=mode,
            identity=copy.deepcopy(identity), scope=_scope(identity, project_scope))
        sha = digest(candidate)
        phrase = ('approve consuming request ' if mode == 'single' else 'save consuming permission ') + sha
        fs = self.projects._filesystem(write=True)
        with fs.lock(BASE + '/ledger.lock'):
            ledger = self._read(fs)
            if sha not in ledger['candidates']:
                ledger['candidates'][sha] = candidate
                self._write(fs, ledger)
            return dict(candidate_sha256=sha, disclosure=copy.deepcopy(candidate),
                approval_phrase=phrase, permission_revision=ledger['revision'],
                cost='unknown' if identity['effects'].get('estimate') is None else copy.deepcopy(identity['effects']['estimate']),
                host_authority=False, consuming_permission=False)

    def grant(self, candidate_sha256, *, session_id, message_id, expected_revision):
        # Read-only real host user evidence. A caller-authored approval flag,
        # authority_ref, assistant response or role label is never accepted.
        from .host_bridge import consuming_user_evidence
        evidence = consuming_user_evidence(session_id, message_id)
        fs = self.projects._filesystem(write=True)
        with fs.lock(BASE + '/ledger.lock'):
            ledger = self._read(fs)
            self._cas(ledger, expected_revision)
            candidate = ledger['candidates'].get(candidate_sha256)
            if not candidate or digest(candidate) != candidate_sha256:
                raise ContractError('PERMISSION_DENIED', 'Exact disclosure was not recorded.')
            phrase = ('approve consuming request ' if candidate['mode'] == 'single' else 'save consuming permission ') + candidate_sha256
            if not re.fullmatch(r'\s*' + re.escape(phrase) + r'[.!\s]*', evidence['content'], re.I):
                raise ContractError('PERMISSION_DENIED', 'User message must explicitly approve this exact consuming disclosure and scope.')
            evidence_key = digest({'session_id': session_id, 'message_id': str(message_id)})
            if evidence_key in ledger['evidence']:
                old = ledger['evidence'][evidence_key]
                if old['candidate_sha256'] != candidate_sha256:
                    raise ContractError('PERMISSION_DENIED', 'User approval was already bound to another disclosure.')
                return dict(grant=copy.deepcopy(ledger['grants'][old['grant_id']]), permission_revision=ledger['revision'])
            gid = _id('pmt')
            grant = dict(grant_id=gid, mode=candidate['mode'], identity=candidate['identity'],
                scope=candidate['scope'], candidate_sha256=candidate_sha256,
                evidence=dict(session_id=session_id, message_id=str(message_id),
                    message_sha256=digest(evidence['content'])), state='active',
                created_at=_now(), revoked_at=None)
            ledger['grants'][gid] = grant
            ledger['evidence'][evidence_key] = dict(candidate_sha256=candidate_sha256, grant_id=gid)
            self._write(fs, ledger)
            return dict(grant=copy.deepcopy(grant), permission_revision=ledger['revision'])

    def revoke(self, grant_id, *, expected_revision):
        fs = self.projects._filesystem(write=True)
        with fs.lock(BASE + '/ledger.lock'):
            ledger = self._read(fs)
            self._cas(ledger, expected_revision)
            grant = ledger['grants'].get(grant_id)
            if grant is None:
                raise ContractError('NOT_FOUND', 'Consuming permission grant not found.')
            if grant['state'] != 'revoked':
                grant.update(state='revoked', revoked_at=_now())
                self._write(fs, ledger)
            claims = [copy.deepcopy(c) for c in ledger['claims'].values() if c['grant_id'] == grant_id]
            return dict(grant=copy.deepcopy(grant), permission_revision=ledger['revision'],
                admitted_claims=claims, limitation='Revocation blocks future admission; it cannot undo an admitted or sent call. Unknown outcomes must reconcile that same call.')

    def admit(self, identity, attempt):
        if not consuming(identity['effects']):
            return None
        owner = {k: attempt[k] for k in ('job_id', 'attempt_id', 'node_id', 'provider_request_key')}
        key = digest(owner)
        fs = self.projects._filesystem(write=True)
        with fs.lock(BASE + '/ledger.lock'):
            ledger = self._read(fs)
            if key in ledger['claims']:
                raise ContractError('PERMISSION_DENIED', 'Attempt already admitted; reconcile the same call, never invoke it again.')
            if any((c['request_sha256'] == identity['request_sha256']
                    or c.get('effect_sha256') == identity['effect_sha256']) and c['outcome'] == 'unknown'
                   for c in ledger['claims'].values()):
                raise ContractError('SUBMISSION_UNCERTAIN', 'This exact request has an unresolved admitted call; reconcile it before any fresh invocation, including under saved permission.')
            used = {c['grant_id'] for c in ledger['claims'].values()}
            choices = [(gid, g) for gid, g in ledger['grants'].items()
                if g['state'] == 'active' and _matches(g, identity)
                and (g['mode'] == 'saved' or gid not in used)]
            # Prefer an exact single-use grant over a broader saved scope.
            choices.sort(key=lambda pair: (pair[1]['mode'] != 'single', pair[0]))
            if not choices:
                raise ContractError('PERMISSION_DENIED', 'No active explicit consuming permission covers this exact resolved request.')
            gid, _ = choices[0]
            claim = dict(claim_id=key, grant_id=gid, project_id=identity['project_id'],
                request_sha256=identity['request_sha256'], effect_sha256=identity['effect_sha256'], owner=owner,
                state='admitted', outcome='unknown', admitted_at=_now(), finished_at=None)
            ledger['claims'][key] = claim
            self._write(fs, ledger)  # durable before the only invocation
            return copy.deepcopy(claim)

    def settle(self, claim, outcome):
        if claim is None:
            return
        if outcome not in ('succeeded', 'failed', 'unknown'):
            raise ContractError('INVALID_ARGUMENT', 'Unknown consuming outcome.')
        fs = self.projects._filesystem(write=True)
        with fs.lock(BASE + '/ledger.lock'):
            ledger = self._read(fs)
            old = ledger['claims'].get(claim['claim_id'])
            if old is None or any(old[k] != claim[k] for k in ('grant_id', 'owner', 'request_sha256')):
                raise ContractError('PERMISSION_DENIED', 'Consuming claim identity changed.')
            if old['outcome'] != 'unknown' and old['outcome'] != outcome:
                raise ContractError('PERMISSION_DENIED', 'Terminal consuming outcome cannot be replaced.')
            old.update(state='settled' if outcome != 'unknown' else 'admitted',
                       outcome=outcome, finished_at=_now() if outcome != 'unknown' else None)
            self._write(fs, ledger)


def validate_invocation_selection(request, adapter, *, selection_validator=None):
    """Exact final option check, including free calls; never grants authority.

    Runtime-less injected adapters may use a trusted JobStore callback with
    signature ``validator(request) -> FrozenBinding``. Legacy requests without
    a selection do not require a runtime or that optional callback.
    """
    if 'selection' not in request:
        return
    runtime = getattr(adapter, 'runtime', None)
    if runtime is not None:
        from .options import validate_selection
        binding = validate_selection(runtime.registry, request['selection'],
            operation=request['operation'], parameters=request['parameters'],
            binding_parameters=request.get('binding_parameters'),
            required_features=request.get('required_features', []),
            bridge=getattr(runtime, 'host_bridge', None))
    elif selection_validator is not None:
        binding = selection_validator(copy.deepcopy(request))
    else:
        raise ContractError('DEPENDENCY_UNAVAILABLE',
            'Selected invocation needs the adapter runtime or a trusted selection_validator(request) callback; no unchecked fallback.')
    if binding != request['binding']:
        raise ContractError('ADAPTER_INCOMPATIBLE', 'Selected invocation differs from the frozen executable binding.')


def execute_with_permission(projects, request, attempt, adapter, invoke, *, selection_validator=None):
    """The actual owned-adapter boundary; a grant never skips host authority."""
    try:
        validate_invocation_selection(request, adapter, selection_validator=selection_validator)
    except ContractError as exc:
        raise PermissionAdmissionRefused(exc.code, exc.message) from exc
    if getattr(adapter, 'native_handoff', False):
        try:
            require_native_admission(request['effects'])
        except ContractError as exc:
            raise PermissionAdmissionRefused(exc.code, exc.message) from exc
        return invoke()
    if not consuming(request.get('effects')):
        return invoke()
    runtime = getattr(adapter, 'runtime', None)
    store = PermissionStore(projects)
    try:
        identity = request_identity(request, registry=getattr(runtime, 'registry', None))
        claim = store.admit(identity, attempt)
    except ContractError as exc:
        raise PermissionAdmissionRefused(exc.code, exc.message) from exc
    try:
        result = invoke()
    except BaseException:
        # Keep the committed claim unknown even when an exception or crash
        # prevents bookkeeping. Never mask the original engine failure.
        raise
    submission = result.get('submission_state') if isinstance(result, dict) else None
    state = result.get('state') if isinstance(result, dict) else None
    outcome = state if state in ('succeeded', 'failed') and submission in ('confirmed', 'not_sent') else 'unknown'
    store.settle(claim, outcome)
    return result


def schema_branches():
    """Closed branches to merge into motion_run, not a new public tool."""
    from .plans import DEFS
    plan = copy.deepcopy(DEFS['PlanRef'])
    return [
        obj(dict(action={'const': 'permission_disclose'}, project_id=ident('prj'),
            plan=plan, node_id=ident('nod'), mode=enum('single', 'saved'),
            project_scope=enum('project', 'profile'), job_id=ident('job')), ['job_id']),
        obj(dict(action={'const': 'permission_grant'}, candidate_sha256=DIGEST,
            message_id=TEXT, expected_revision=integer(0))),
        obj(dict(action={'const': 'permission_inspect'}, project_id=ident('prj')), ['project_id']),
        obj(dict(action={'const': 'permission_revoke'}, grant_id=ident('pmt'),
            expected_revision=integer(0))),
    ]


def dispatch(runtime, args, *, session_id=None):
    """Return motion_run data; shared runtime owns validation/error envelopes."""
    branch = next((b for b in schema_branches() if b['properties']['action']['const'] == args.get('action')), None)
    if branch is None:
        raise ContractError('UNSUPPORTED_OPERATION', 'Unknown consuming permission action.')
    validate(args, branch)
    store = PermissionStore(runtime.projects)
    action = args['action']
    if action == 'permission_inspect':
        return store.inspect(project_id=args.get('project_id'))
    if action == 'permission_revoke':
        return store.revoke(args['grant_id'], expected_revision=args['expected_revision'])
    if action == 'permission_grant':
        return store.grant(args['candidate_sha256'], session_id=session_id,
            message_id=args['message_id'], expected_revision=args['expected_revision'])
    plan = runtime.compiler.load(args['project_id'], args['plan'])
    fs = runtime.projects._filesystem()
    if runtime.projects._pointer(fs, args['project_id'])['revision'] != plan['project_revision']:
        raise ContractError('REVISION_CONFLICT', 'Frozen plan is stale; compile before disclosing consuming permission.')
    node = next((n for n in plan['nodes'] if n['node_id'] == args['node_id']), None)
    if node is None or node.get('reuse') is not None:
        raise ContractError('INVALID_ARGUMENT', 'Select a real executable, non-reused plan node.')
    jobs = runtime.jobs()
    bundle = None
    if args.get('job_id'):
        bundle = jobs.read(args['project_id'], args['job_id'])
        if bundle['job']['plan'] != args['plan']:
            raise ContractError('PERMISSION_DENIED', 'Producer job belongs to a different frozen plan.')
    if node['dependencies'] and bundle is None:
        raise ContractError('PERMISSION_DENIED', 'Select an existing job with resolved producer output pins; no placeholder authorization.')
    request = jobs._check_node(plan, node, bundle)
    if request is None:
        raise ContractError('PERMISSION_DENIED', 'Exact executable request is unavailable.')
    adapter = runtime.adapter_resolver(node['binding'])
    if getattr(adapter, 'native_handoff', False):
        require_native_admission(request['effects'])
    identity = request_identity(request, registry=runtime.registry)
    return store.disclose(identity, mode=args['mode'], project_scope=args['project_scope'])
