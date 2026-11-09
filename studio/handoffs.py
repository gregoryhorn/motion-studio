"""B08 typed handoffs; never invokes a host tool or imports private dispatchers.

host_bridge is an explicit trusted integration, not user JSON: inventory() ->
{name: parameter_schema}, actor() -> runtime-verified Actor, observe(call_ref) ->
observed exact call {tool_name,arguments,actor,outcome,outputs}, retrieve(locator,
attempt,port) -> attempt-relative staged path. No bridge means unknown provenance
and refused claim/collection. Context correlation IDs alone are not approvals.
"""
from __future__ import annotations

import copy
from .contracts import (ContractError, D, obj, arr, enum, integer, ident, nullable,
                        TEXT, DIGEST, STAMP, BOOL, validate, digest, safe_relative)
from .project import _id, _now

ACTOR = obj({'kind': enum('system', 'agent', 'user'), 'actor_ref': TEXT})
EFFECTS = obj({'writes_local': BOOL, 'uploads': BOOL, 'destinations': arr(TEXT), 'generates': BOOL, 'launches_process': BOOL, 'pricing': enum('free', 'metered', 'subscription', 'unknown'), 'charging_basis': nullable(TEXT), 'estimate': nullable(obj({'amount': TEXT, 'currency': TEXT, 'source': TEXT}))})
PORT = obj({'port': TEXT, 'kind': enum('media', 'image', 'audio', 'frame', 'caption', 'caption_style', 'scene_source', 'assembly_source', 'json', 'report', 'archive', 'font'), 'media_type': TEXT})
LOCATOR = {'oneOf': [obj({'kind': {'const': 'local'}, 'path': TEXT}), obj({'kind': {'const': 'remote'}, 'url': TEXT})]}
HANDOFF = obj({'handoff_id': ident('hnd'), 'job_id': ident('job'), 'node_id': ident('nod'), 'attempt_id': ident('att'), 'request_sha256': DIGEST, 'kind': enum('host_tool', 'gui'), 'tool_name': TEXT, 'tool_schema_sha256': DIGEST, 'arguments': {'type': 'object', 'additionalProperties': {}}, 'expected_outputs': arr(PORT), 'effects': EFFECTS, 'state': enum('ready', 'claimed', 'reported', 'validated', 'uncertain'), 'claimed_by': nullable(ACTOR), 'host_call_ref': nullable(TEXT), 'instructions': TEXT})
RECEIPT = obj({'handoff_id': ident('hnd'), 'attempt_id': ident('att'), 'request_sha256': DIGEST, 'host_call_ref': TEXT, 'outcome': enum('succeeded', 'failed', 'uncertain'), 'outputs': arr(obj({'port': TEXT, 'locator': LOCATOR})), 'evidence': arr(D['ArtifactRef']), 'reported_at': STAMP})


def _bridge(store):
    if store.host_bridge is None:
        raise ContractError('PERMISSION_DENIED', 'Verified runtime actor/call provenance bridge unavailable; correlation ID is not authority.')
    return store.host_bridge


def _inventory(handoff, bridge):
    inventory = bridge.inventory()
    schema = inventory.get(handoff['tool_name'])
    if schema is None or digest(schema) != handoff['tool_schema_sha256']:
        raise ContractError('HANDOFF_MISMATCH', 'Exact current host tool schema is absent or changed.')
    validate(handoff['arguments'], schema)


def prepare_handoff(candidate, bundle, attempt, node, bridge):
    """Typed adapter event -> durable pending intent, never an output artifact."""
    validate(candidate, HANDOFF)
    from .permissions import require_native_admission
    require_native_admission(candidate['effects'])
    if bridge is None:
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Cannot verify current host tool inventory.')
    expected = {'job_id': bundle['job']['job_id'], 'attempt_id': attempt['attempt_id'],
                'node_id': node['node_id'], 'request_sha256': attempt['request_sha256'],
                'expected_outputs': node['expected_outputs'], 'state': 'ready',
                'claimed_by': None, 'host_call_ref': None}
    if any(candidate[k] != v for k, v in expected.items()):
        raise ContractError('HANDOFF_MISMATCH', 'Handoff differs from exact frozen job/attempt/request.')
    index = next((i for i, frozen in enumerate(bundle['plan_record']['nodes'])
                  if frozen['node_id'] == node['node_id']), None)
    frozen_effects = bundle['plan_record']['effects']
    if index is None or index >= len(frozen_effects) or candidate['effects'] != frozen_effects[index]:
        raise ContractError('HANDOFF_MISMATCH', 'Handoff effects were not disclosed in frozen plan.')
    _inventory(candidate, bridge)
    return copy.deepcopy(candidate)


def claim(store, args):
    fs = store.projects._filesystem(write=True)
    with fs.lock(store.lock_path(args['project_id'])):
        bundle = store.read(args['project_id'], args['job_id'])
        replay = store._replay(bundle, args)
        if replay is not None:
            return replay  # Same exact request survives revision/identity changes.
        handoff = bundle['handoffs'].get(args['handoff_id'])
        if handoff is None or handoff['attempt_id'] != args['attempt_id']:
            raise ContractError('HANDOFF_MISMATCH', 'No matching pending handoff/attempt.')
        if handoff['state'] != 'ready':
            raise ContractError('HANDOFF_ALREADY_CLAIMED', 'Claim cannot be reused to execute a second call; reconcile uncertainty.')
        store._cas(bundle, args)
        if bundle['job']['state'] in ('succeeded', 'failed', 'cancelled', 'interrupted') or bundle['job']['cancel']['requested']:
            raise ContractError('HANDOFF_MISMATCH', 'Terminal/cancelling job cannot launch external work.')
        bridge = _bridge(store)
        from .permissions import require_native_admission
        require_native_admission(handoff['effects'])
        _inventory(handoff, bridge)
        actor = bridge.actor()
        validate(actor, ACTOR)
        if not actor['actor_ref']:
            raise ContractError('PERMISSION_DENIED', 'Runtime actor provenance is unknown.')
        handoff.update(state='claimed', claimed_by=actor)
        bundle['attempts'][args['attempt_id']]['submission_state'] = 'intent_recorded'
        bundle['job']['submission_state'] = 'intent_recorded'
        return store._finish_request(fs, bundle, args, {'handoff': copy.deepcopy(handoff)})


def collect(store, args):
    # Only the trusted bridge can fill receipts omitted by the agent. Correlation
    # identities and result locators come from actual post_tool_call, not JSON.
    if 'receipts' not in args and callable(getattr(store.host_bridge, 'receipts', None)):
        args = copy.deepcopy(args)
        args['receipts'] = store.host_bridge.receipts(args['project_id'], args['job_id'])
        if not args['receipts']:
            raise ContractError('OUTPUT_UNAVAILABLE', 'No observed native result is ready to collect.')
    fs = store.projects._filesystem(write=True)
    with fs.lock(store.lock_path(args['project_id'])):
        bundle = store.read(args['project_id'], args['job_id'])
        replay = store._replay(bundle, args)
        if replay is not None:
            return replay
        store._cas(bundle, args)
        if args.get('decision_review_ids'):
            raise ContractError('UNSUPPORTED_OPERATION', 'Decision review verifier is not bound.')
        new_records = []
        for receipt in args.get('receipts', []):
            validate(receipt, RECEIPT)
            handoff = bundle['handoffs'].get(receipt['handoff_id'])
            if handoff is None or any(receipt[k] != handoff[k] for k in ('attempt_id', 'request_sha256')):
                raise ContractError('HANDOFF_MISMATCH', 'Receipt not bound to exact pending attempt/request.')
            old = bundle.setdefault('handoff_receipts', {}).get(handoff['handoff_id'])
            if old:
                if digest(old) == digest(receipt):
                    continue
                # An uncertain observation is not a terminal result. Reconcile
                # only that same call, never turn uncertainty into a retry grant.
                # Original reports remain in immutable collection artifacts.
                if (old['outcome'] != 'uncertain'
                        or receipt['outcome'] not in ('succeeded', 'failed')
                        or old['host_call_ref'] != receipt['host_call_ref']):
                    raise ContractError('IDEMPOTENCY_CONFLICT', 'Different report for previously collected handoff.')
            if handoff['state'] not in ('claimed', 'uncertain'):
                raise ContractError('HANDOFF_MISMATCH', 'Claim-before-call is required.')
            bridge = _bridge(store)
            observed = bridge.observe(receipt['host_call_ref'])
            if not observed or any(observed.get(k) != handoff[k] for k in ('tool_name', 'arguments', 'handoff_id', 'job_id', 'node_id', 'attempt_id', 'request_sha256')) or observed.get('actor') != handoff['claimed_by']:
                raise ContractError('OUTPUT_UNAVAILABLE', 'No independently observed exact host call for this claim.')
            if observed.get('outcome') != receipt['outcome'] or observed.get('outputs') != receipt['outputs']:
                raise ContractError('HANDOFF_MISMATCH', 'Report differs from observed host outcome/output locators.')
            if any(h.get('host_call_ref') == receipt['host_call_ref'] and h['handoff_id'] != handoff['handoff_id'] for h in bundle['handoffs'].values()):
                raise ContractError('HANDOFF_MISMATCH', 'Host call already consumed by a different handoff.')
            handoff.update(state='reported', host_call_ref=receipt['host_call_ref'])
            attempt = bundle['attempts'][receipt['attempt_id']]
            terminal = bundle['job']['state'] in ('succeeded', 'failed', 'cancelled', 'interrupted')
            if receipt['outcome'] == 'uncertain':
                handoff['state'] = 'uncertain'
                attempt.update(submission_state='uncertain', remote_state='unknown')
                bundle['job'].update(submission_state='uncertain', remote_state='unknown')
                if not terminal:
                    bundle['job']['state'] = 'awaiting_external'
            elif receipt['outcome'] == 'failed':
                attempt.update(submission_state='confirmed', remote_state='failed', ended_at=_now())
                if bundle['job']['state'] not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                    bundle['job']['state'] = 'failed'
            else:
                ports = {p['port']: p for p in handoff['expected_outputs']}
                if len(receipt['outputs']) != len(ports) or {o['port'] for o in receipt['outputs']} != set(ports):
                    raise ContractError('OUTPUT_INVALID', 'Host output port closure differs from frozen handoff.')
                descriptors = []
                try:
                    for output in receipt['outputs']:
                        # Bridge may retrieve only the already-observed locator; no generate.
                        relative = bridge.retrieve(copy.deepcopy(output['locator']), copy.deepcopy(attempt), copy.deepcopy(ports[output['port']]))
                        safe_relative(relative)
                        if callable(getattr(bridge, 'validate_staged', None)):
                            bridge.validate_staged(store, copy.deepcopy(attempt), copy.deepcopy(ports[output['port']]), relative)
                        descriptors.append({'port': output['port'], 'relative_path': relative, 'media_type': ports[output['port']]['media_type'], 'claimed_sha256': None})
                    node = next(n for n in bundle['plan_record']['nodes'] if n['node_id'] == handoff['node_id'])
                    records = store.validate_outputs(bundle, attempt, node, descriptors)
                except OSError as exc:
                    # A returned locator is not proof of bytes. Keep retrieval/
                    # staging failures inside the typed collect error boundary.
                    raise ContractError('OUTPUT_UNAVAILABLE', 'Observed host output could not be retrieved or opened in owned staging.') from exc
                new_records.extend(records)
                bundle['artifacts'].extend(records)
                refs = [{'artifact_id': a['artifact_id'], 'sha256': a['sha256']} for a in records]
                # Terminal jobs remain terminal; late outputs are preserved evidence,
                # not a reopened execution or silently promoted deliverable.
                if not terminal and not bundle['job']['cancel']['requested']:
                    bundle['job']['outputs'].extend(refs)
                    ns = next(n for n in bundle['job']['node_states'] if n['node_id'] == handoff['node_id'])
                    ns.update(outputs=refs, state='succeeded')
                attempt.update(submission_state='confirmed', remote_state='succeeded', ended_at=_now())
                handoff['state'] = 'validated'
                if bundle['job']['state'] not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                    all_done = all(n['state'] == 'succeeded' for n in bundle['job']['node_states'])
                    bundle['job']['state'] = 'succeeded' if all_done and not bundle['job']['cancel']['requested'] else 'interrupted'
                bundle['job'].update(submission_state='confirmed', remote_state='succeeded')
            bundle['handoff_receipts'][handoff['handoff_id']] = copy.deepcopy(receipt)
        # The collection receipt is itself core-authored, immutable, hashed bytes.
        from .contracts import canonical
        import os
        import hashlib
        receipt_id = _id('art')
        relative = store.projects._base(args['project_id']) + '/jobs/' + args['job_id'] + '/collections/' + receipt_id + '.json'
        payload = canonical({'schema': 'motion/v1/collection-receipt', 'job_id': args['job_id'], 'request_id': args['request_id'], 'receipts': args.get('receipts', []), 'artifacts': [{'artifact_id': a['artifact_id'], 'sha256': a['sha256']} for a in new_records]})
        parent, _, name = relative.rpartition('/')
        with fs.directory(parent, create=True) as directory:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory)
        receipt_ref = {'artifact_id': receipt_id, 'sha256': 'sha256:' + hashlib.sha256(payload).hexdigest()}
        bundle.setdefault('collections', []).append({'artifact': receipt_ref, 'relative_path': relative})
        bundle['artifacts'].append({'schema': 'motion/v1/artifact', 'artifact_id': receipt_id,
            'project_id': args['project_id'], 'kind': 'report', 'media_type': 'application/json',
            'sha256': receipt_ref['sha256'], 'size_bytes': len(payload), 'storage': {'mode': 'managed', 'relative_path': relative},
            'created_at': _now(), 'producer': {'job_id': args['job_id'], 'node_id': None, 'attempt_id': None, 'adapter_id': None},
            'inputs': [{'artifact_id': a['artifact_id'], 'sha256': a['sha256']} for a in new_records],
            'provenance': {'origin': 'derived', 'acquired_at': _now(), 'source_locator': None, 'provider': None,
                'model': None, 'model_version': None, 'seed': None, 'deterministic': 'unknown',
                'rights': {'status': 'known', 'license': None, 'attribution': None, 'evidence': []},
                'notes': 'Core collection receipt; external execution provenance is accepted only through the configured observed-call bridge.'},
            'probe_receipt_id': None})
        return store._finish_request(fs, bundle, args, {'artifacts': new_records, 'collection_receipt': receipt_ref})
