"""B11/B16 byte-bound reviews. No execution, profile access or I/O on import.

The evaluator is pure. GateContext is supplied by core's current dependency/
policy resolver, never by tool arguments. Runtime evidence verification is an
injected capability, not an approval boolean accepted from the caller.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from collections.abc import Iterator

from .contracts import (D, GATES, METHODS, BOOL, DECIMAL, DIGEST, KEY, STAMP, TEXT,
    UUID_PATTERN, ContractError, arr, digest, enum, ident, integer, nullable,
    obj, ref, string, validate)
from .project import _id, _now

DEFS = copy.deepcopy(D)
DEFS['Actor'] = obj({'kind': enum('system', 'agent', 'user'), 'actor_ref': TEXT})
DEFS['Measurement'] = obj({'name': TEXT, 'value': DECIMAL, 'unit': TEXT, 'method': TEXT, 'scope': TEXT})
DEFS['Coverage'] = obj({
    'frame_ranges': arr(obj({'start_frame': integer(), 'end_frame': integer(1)})),
    'sample_ranges': arr(obj({'start_sample': integer(), 'end_sample': integer(1), 'sample_rate': integer(1)})),
    'scene_ids': arr(ident('scn'), unique=True), 'transition_keys': arr(KEY, unique=True),
    'whole_decode': BOOL, 'playback': enum('not_tested', 'pass', 'fail')})
DEFS['Finding'] = obj({'finding_id': KEY, 'severity': enum('info', 'minor', 'blocking'),
    'description': TEXT, 'frame': nullable(integer()), 'sample': nullable(integer()),
    'required_change': nullable(TEXT), 'resolution_receipt': nullable(ref('ArtifactRef'))})
DEFS['ReviewRecord'] = obj({'schema': {'const': 'motion/v1/review'}, 'review_id': ident('rev'),
    'project_id': ident('prj'), 'created_at': STAMP, 'subject': ref('ArtifactRef'),
    'candidate_manifest_sha256': DIGEST, 'subject_dependencies': DIGEST, 'policy': ref('DocumentRef'),
    'gate': enum(*GATES), 'result': enum('pass', 'fail', 'review_needed', 'not_applicable'),
    'method': enum(*METHODS), 'author': ref('Actor'), 'tool': TEXT, 'tool_version': nullable(TEXT),
    'evidence': arr(ref('ArtifactRef')), 'measurements': arr(ref('Measurement')),
    'coverage': ref('Coverage'), 'findings': arr(ref('Finding')), 'reason': TEXT,
    'supersedes': nullable(ident('rev'))})
DEFS['GateResult'] = obj({'gate': enum(*GATES), 'result': enum('pass', 'fail', 'review_needed', 'not_applicable'),
    'freshness': enum('current', 'stale'), 'review_ids': arr(ident('rev'), unique=True), 'reason': TEXT})
DEFS['GateSummary'] = obj({'candidate': ref('ArtifactRef'), 'candidate_manifest_sha256': DIGEST,
    'policy': ref('DocumentRef'), 'gates': arr(ref('GateResult'), 5), 'promotion_eligible': BOOL, 'missing': arr(TEXT)})
PAGE = {'limit': integer(1, 100), 'cursor': TEXT, 'snapshot_id': ident('snp')}
COMMON = {'project_id': ident('prj')}
MUTATION = {**COMMON, 'request_id': string(UUID_PATTERN)}
EXECUTION = {**MUTATION, 'expected_revision': integer(1), 'authority_ref': TEXT}
DEFS['ReviewRequest'] = {'oneOf': [
    obj({'action': {'const': 'record'}, **MUTATION, 'candidate': ref('ArtifactRef'),
         'expected_candidate_manifest_sha256': DIGEST, 'gate': enum(*GATES),
         'result': enum('pass', 'fail', 'review_needed', 'not_applicable'),
         'method': enum('agent_visual', 'agent_audio', 'user', 'playback'),
         'evidence': arr(ref('ArtifactRef')), 'coverage': ref('Coverage'),
         'findings': arr(ref('Finding')), 'reason': TEXT, 'supersedes': ident('rev')}, ['supersedes']),
    obj({'action': {'const': 'check'}, **EXECUTION, 'candidate': ref('ArtifactRef'),
         'gates': arr(enum(*GATES), 1, True), 'adapter_id': DEFS.get('AdapterID', string(minimum=1))}, ['authority_ref']),
    obj({'action': {'const': 'gates'}, **COMMON, 'candidate': ref('ArtifactRef')}),
    obj({'action': {'const': 'inspect'}, **COMMON, 'review_id': ident('rev')}),
    obj({'action': {'const': 'list'}, **COMMON, **PAGE, 'candidate': ref('ArtifactRef'),
         'gate': enum(*GATES), 'result': enum('pass', 'fail', 'review_needed', 'not_applicable')},
        [*PAGE, 'candidate', 'gate', 'result'])]}


def expanded(schema, definitions=None):
    definitions = DEFS if definitions is None else definitions
    if isinstance(schema, dict):
        if '$ref' in schema:
            return expanded(definitions[schema['$ref'].rsplit('/', 1)[-1]], definitions)
        return {k: expanded(v, definitions) for k, v in schema.items()}
    if isinstance(schema, list):
        return [expanded(v, definitions) for v in schema]
    return schema


def schema_document(name, definitions=None):
    definitions = DEFS if definitions is None else definitions
    reached = {}
    def visit(value):
        if isinstance(value, dict):
            if '$ref' in value:
                key = value['$ref'].rsplit('/', 1)[-1]
                if key not in reached:
                    reached[key] = copy.deepcopy(definitions[key]); visit(reached[key])
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(definitions[name])
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'motion/v1/' + name, **copy.deepcopy(definitions[name]), '$defs': reached}


def validate_review(value, name):
    validate(value, expanded(DEFS[name]))
    if name == 'ReviewRecord':
        for span in value['coverage']['frame_ranges']:
            if span['end_frame'] <= span['start_frame']:
                raise ContractError('INVALID_ARGUMENT', 'Review frame ranges must be nonempty half-open intervals.')
        for span in value['coverage']['sample_ranges']:
            if span['end_sample'] <= span['start_sample']:
                raise ContractError('INVALID_ARGUMENT', 'Review sample ranges must be nonempty half-open intervals.')


def review_tool_schema():
    return {'name': 'motion_review', 'description': 'Record exact-byte runtime-attributed reviews, inspect gates, or explicitly request deterministic checks.',
            'parameters': schema_document('ReviewRequest')}


@dataclass(frozen=True)
class GateContext:
    policy: dict
    policy_pin: dict
    dependencies_sha256: str
    variant: dict
    duration_frames: int
    sample_count: int
    sample_rate: int
    scene_ids: tuple = ()
    transition_keys: tuple = ()
    requested_frames: tuple = ()
    no_audio: bool = False
    # Proven by current core closure/rights/sidecar checks, not caller assertions.
    blockers: tuple = ()
    # Registered deterministic checks already verified from collected report evidence.
    checked_names: frozenset = frozenset()


def stale_reasons(review, candidate, context):
    pairs = [('subject', candidate['artifact']), ('candidate_manifest_sha256', digest(candidate)),
             ('subject_dependencies', candidate['dependencies_sha256']), ('policy', candidate['gate_policy'])]
    reasons = [key + ' differs' for key, value in pairs if review[key] != value]
    if candidate['dependencies_sha256'] != context.dependencies_sha256:
        reasons.append('dependency closure changed')
    if candidate['gate_policy'] != context.policy_pin:
        reasons.append('gate policy changed')
    if candidate['variant'] != context.variant:
        reasons.append('variant changed')
    return reasons


def _covers(spans, start, end):
    cursor = start
    for left, right in sorted(spans):
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = right
        if cursor >= end:
            return True
    return cursor >= end


def _coverage(reviews, rule, context):
    if not reviews:
        return False
    frames = [(s['start_frame'], s['end_frame']) for r in reviews for s in r['coverage']['frame_ranges']]
    samples = [(s['start_sample'], s['end_sample']) for r in reviews for s in r['coverage']['sample_ranges']
               if s['sample_rate'] == context.sample_rate]
    methods = {r['method'] for r in reviews}
    if 'playback' in methods and not any(r['coverage']['playback'] == 'pass' for r in reviews):
        return False
    if rule['coverage'] == 'whole_file':
        if methods == {'deterministic'}:
            return any(r['coverage']['whole_decode'] for r in reviews)
        if rule['gate'] == 'audio':
            return context.sample_count > 0 and _covers(samples, 0, context.sample_count)
        return _covers(frames, 0, context.duration_frames)
    if not context.requested_frames:
        return False  # Missing sample oracle is not complete visual inspection.
    if not all(_covers(frames, frame, frame + 1) for frame in context.requested_frames):
        return False
    if rule['coverage'] == 'every_scene_and_transition':
        scenes = {s for r in reviews for s in r['coverage']['scene_ids']}
        transitions = {s for r in reviews for s in r['coverage']['transition_keys']}
        return set(context.scene_ids) <= scenes and set(context.transition_keys) <= transitions
    return True


def _same_supersession(old, new):
    return all(old[k] == new[k] for k in ('subject', 'candidate_manifest_sha256',
        'subject_dependencies', 'policy', 'gate', 'method', 'project_id'))


def evaluate_gates(candidate, context, reviews, *, verified_review_ids: set | frozenset = frozenset(),
                   verified_caption_review_ids: set | frozenset = frozenset()):
    """Aggregate immutable evidence, never execute a check or trust record authors.

    verified_review_ids is an INTERNAL runtime verification result, not a field
    in a tool request/record. Without a verifier every judgement remains pending.
    """
    validate(context.policy, expanded(DEFS['GatePolicy']))
    rules = context.policy['gates']
    if len(rules) != 5 or {r['gate'] for r in rules} != set(GATES):
        raise ContractError('INVALID_ARGUMENT', 'Policy must contain exactly the five required gates.')
    if any(r['gate'] != 'audio' and r['not_applicable_when'] != 'never' for r in rules):
        raise ContractError('INVALID_ARGUMENT', 'Only audio may be not applicable.')
    minimum_groups = {'creative': [['agent_visual', 'user']], 'art': [['agent_visual', 'user']],
                      'technical': [['deterministic'], ['playback']],
                      'audio': [['deterministic'], ['agent_audio', 'user']],
                      'delivery_profile': [['deterministic']]}
    for rule in rules:
        # A stricter group is allowed, but callers cannot dilute a required
        # deterministic group into deterministic-OR-agent judgement.
        if any(not any(set(group) <= set(minimum) for group in rule['method_groups'])
               for minimum in minimum_groups[rule['gate']]):
            raise ContractError('INVALID_ARGUMENT', 'Gate policy weakens mandatory method groups.')
    by_id = {}
    for review in reviews:
        validate_review(review, 'ReviewRecord')
        if review['review_id'] in by_id:
            raise ContractError('INVALID_ARGUMENT', 'Duplicate review identity.')
        by_id[review['review_id']] = review
    fresh = {key: not stale_reasons(r, candidate, context) for key, r in by_id.items()}
    suppressed = set()
    for key, review in by_id.items():
        previous = review['supersedes']
        if previous:
            if previous not in by_id or not _same_supersession(by_id[previous], review):
                raise ContractError('INVALID_ARGUMENT', 'Supersession must bind same subject/policy/gate/method.')
            seen, cursor = {key}, previous
            while cursor:
                if cursor in seen:
                    raise ContractError('INVALID_GRAPH', 'Review supersession cycle.')
                seen.add(cursor); cursor = by_id[cursor]['supersedes']
            if key in verified_review_ids and fresh[key]:
                suppressed.add(previous)
    results, missing = [], list(context.blockers)
    caption_visual = []
    for gate in GATES:
        rule = next(r for r in rules if r['gate'] == gate)
        matching = [r for r in reviews if r['gate'] == gate and r['review_id'] not in suppressed]
        current = [r for r in matching if fresh[r['review_id']] and r['review_id'] in verified_review_ids
                   and r['author']['kind'] in rule['allowed_authors'] and r['evidence']
                   and ((r['method'] == 'user' and r['author']['kind'] == 'user')
                        or (r['method'] in ('agent_visual', 'agent_audio') and r['author']['kind'] == 'agent')
                        or (r['method'] == 'deterministic' and r['author']['kind'] == 'system')
                        or r['method'] == 'playback')]
        failed = [r for r in current if r['result'] == 'fail' or r['coverage']['playback'] == 'fail'
                  or any(f['severity'] == 'blocking' and f['resolution_receipt'] is None for f in r['findings'])]
        pending = any(r['result'] == 'review_needed' for r in current)
        passed = [r for r in current if r['result'] == 'pass']
        groups = rule['method_groups'] + ([['user']] if rule['require_user_acceptance'] else [])
        reason, result = 'Missing current method, coverage, author or evidence.', 'review_needed'
        if failed:
            result, reason = 'fail', 'Current failed check or unresolved blocking finding.'
        elif pending:
            reason = 'Current evidence explicitly requires further review.'
        elif gate == 'audio' and context.no_audio and rule['not_applicable_when'] == 'no_audio':
            user_acceptance = (not rule['require_user_acceptance'] or any(
                r['method'] == 'user' and r['result'] in ('pass', 'not_applicable')
                and _covers([(s['start_frame'], s['end_frame']) for s in r['coverage']['frame_ranges']],
                            0, context.duration_frames) for r in current))
            if user_acceptance and any(r['result'] == 'not_applicable' and r['method'] == 'deterministic' and r['reason'] for r in current):
                result, reason = 'not_applicable', 'Intentional silence and final-file no-audio evidence verified.'
        elif (all(_coverage([r for r in passed if r['method'] in group], rule, context) for group in groups)
              and set(rule['checks']) <= set(context.checked_names)):
            result, reason = 'pass', 'All required method groups, author provenance, coverage and checks verified.'
        if result not in ('pass', 'not_applicable'):
            missing.append(gate + ': ' + reason)
        if result == 'pass' and gate in ('art', 'creative'):
            caption_visual.extend(r for r in passed if r['method'] == 'agent_visual'
                and r['review_id'] in verified_caption_review_ids)
        results.append({'gate': gate, 'result': result,
            'freshness': 'stale' if matching and not any(fresh[r['review_id']] for r in matching) else 'current',
            'review_ids': [r['review_id'] for r in current], 'reason': reason})
    # Burn verification is an explicit final-pixels claim, separate from a
    # generic art pass. Require complete final-frame coverage (unions allowed).
    if _covers([(s['start_frame'], s['end_frame']) for r in caption_visual
                for s in r['coverage']['frame_ranges']], 0, context.duration_frames):
        missing = [m for m in missing if m != 'CAPTION_BURN_VISUAL_REVIEW_REQUIRED']
    summary = {'candidate': candidate['artifact'], 'candidate_manifest_sha256': digest(candidate),
        'policy': candidate['gate_policy'], 'gates': results, 'promotion_eligible': not missing, 'missing': missing}
    validate_review(summary, 'GateSummary')
    return summary


def invalidated_descendants(dependencies, changed):
    """Return changed nodes and their consumers only; no jobs are started."""
    nodes = set(dependencies)
    if any(set(inputs) - nodes for inputs in dependencies.values()):
        raise ContractError('INVALID_GRAPH', 'Dependency graph contains missing nodes.')
    done, visiting = set(), set()
    def visit(node):
        if node in visiting:
            raise ContractError('INVALID_GRAPH', 'Dependency cycle.')
        if node not in done:
            visiting.add(node)
            for parent in dependencies[node]:
                visit(parent)
            visiting.remove(node); done.add(node)
    for node in nodes:
        visit(node)
    invalid = set(changed) & nodes
    while True:
        more = {node for node, inputs in dependencies.items() if set(inputs) & invalid}
        if more <= invalid:
            return sorted(invalid)
        invalid |= more


def affected_plan_nodes(nodes, before_documents, after_documents):
    """Pure B06 node invalidation -> [{node_id, reason}], sorted by node_id.

    documents use ProjectStore._load's {(kind,id): DocumentRecord} mapping.
    For a project update pass its actual before/after documents. For job status
    pass the plan's loaded historical snapshot documents and current documents.
    Nodes are actual PlanNode dicts; inputs include scalar/array document and
    node_output bindings. DocumentRefs nested in parameters are also consumed.
    No comparison of project revision numbers, and no record mutation or jobs.
    """
    graph = {node['node_id']: list(node['dependencies']) for node in nodes}
    if len(graph) != len(nodes):
        raise ContractError('INVALID_GRAPH', 'Duplicate plan node identity.')
    invalidated_descendants(graph, set())  # Validate closure and cycles first.
    reasons = {}
    before_settings = before_documents.get(('settings', 'project'), {}).get('value', {})
    after_settings = after_documents.get(('settings', 'project'), {}).get('value', {})
    execution_changed = before_settings.get('policy') != after_settings.get('policy')
    gates_changed = before_settings.get('gate_policy') != after_settings.get('gate_policy')

    def pins(value) -> Iterator[dict]:
        # Explicit generator return type is kept local to avoid importing B06.
        if isinstance(value, dict):
            if set(value) == {'kind', 'id', 'revision', 'sha256'}:
                validate(value, expanded(DEFS['DocumentRef']))
                yield value
            else:
                for child in value.values():
                    yield from pins(child)
        elif isinstance(value, list):
            for child in value:
                yield from pins(child)

    def semantic(record, kind, node):
        if record is None:
            return None
        value = copy.deepcopy(record['value'])
        if kind == 'settings':
            # Stage is nonproduction metadata. Policy is handled separately
            # because B06 explicitly fingerprints it for EVERY node.
            value.pop('stage', None)
            value.pop('policy', None)
            value.pop('gate_policy', None)
        if kind == 'variants' and isinstance(value, list) and node['parameters'].get('variant'):
            target = node['parameters']['variant']
            return next((v for v in value if v['variant_id'] == target), None)
        return value

    before_bindings = before_documents.get(('bindings', 'project'), {}).get('value', {})
    after_bindings = after_documents.get(('bindings', 'project'), {}).get('value', {})
    for node in nodes:
        nid, operation = node['node_id'], node['operation']
        validate(nid, ident('nod'))
        if execution_changed:
            reasons[nid] = 'Execution policy changed; B06 node fingerprint/authority is no longer applicable.'
        elif gates_changed and operation.startswith(('review.', 'inspection.', 'delivery.')):
            reasons[nid] = 'Frozen gate policy changed for this review/delivery consumer.'
        adapter = node.get('binding', {}).get('adapter_id')
        if before_bindings != after_bindings and adapter:
            selected = after_bindings.get('selected_adapter_ids', [])
            old_pin = before_bindings.get('pins', {}).get(operation)
            new_pin = after_bindings.get('pins', {}).get(operation)
            if adapter not in selected or (old_pin != new_pin and new_pin and adapter != new_pin):
                reasons[nid] = 'This node frozen adapter selection/operation pin changed.'
        for pin in pins([node['inputs'], node['parameters']]):
            key = (pin['kind'], pin['id'])
            if semantic(before_documents.get(key), pin['kind'], node) != semantic(after_documents.get(key), pin['kind'], node):
                reasons[nid] = 'Consumed document changed: ' + pin['kind'] + '/' + pin['id'] + '.'
            if pin['kind']=='scene':
                scene=before_documents.get(key,{}).get('value',{})
                for linked in pins(scene.get('storyboard_binding',{})):
                    linked_key=(linked['kind'],linked['id'])
                    if before_documents.get(linked_key)!=after_documents.get(linked_key):
                        reasons[nid]='Bound scene preproduction changed: '+linked['kind']+'.'
    affected = invalidated_descendants(graph, set(reasons))
    return [{'node_id': node_id, 'reason': reasons.get(node_id, 'Upstream consumed node is stale.')}
            for node_id in affected]


class ReviewService:
    """Durable reviews using ProjectStore/AssetRegistry, with no second queue.

    delivery supplies candidate/context resolution and common atomic metadata.
    attribution(request) resolves verified runtime author/tool identity.
    verify_review(review, candidate, context) verifies the actual host/adapter
    evidence and registered check semantics. Missing callbacks fail closed.
    execute(tool, request) MUST be the parent's B06/B07 convenience compiler.
    """
    def __init__(self, delivery, *, attribution=None, verify_review=None, execute=None):
        self.delivery = delivery
        self.store, self.registry = delivery.store, delivery.registry
        self.attribution, self.verify_review, self.execute = attribution, verify_review, execute
        delivery.reviews = self

    def _all(self, fs, pid):
        records = self.delivery._records(fs, pid, 'reviews')
        for record in records:
            validate_review(record, 'ReviewRecord')
        return records

    def _verified(self, fs, pointer, candidate, context, reviews):
        valid = set()
        for review in reviews:
            if stale_reasons(review, candidate, context):
                continue
            # Every receipt and finding resolution is rehashed, never trusted by name.
            for pin in review['evidence'] + [f['resolution_receipt'] for f in review['findings'] if f['resolution_receipt']]:
                self.registry.artifact(fs, pointer, pin)
            if self.verify_review is not None and self.verify_review(review, candidate, context) is True:
                valid.add(review['review_id'])
        return valid

    def gates(self, fs, pointer, candidate):
        context = self.delivery.context(fs, pointer, candidate)
        reviews = [r for r in self._all(fs, pointer['project_id']) if r['subject'] == candidate['artifact']]
        verified = self._verified(fs, pointer, candidate, context, reviews)
        return self._evaluate_verified(candidate, context, reviews, verified)

    def _evaluate_verified(self, candidate, context, reviews, verified):
        caption_verifier = getattr(self.delivery, 'caption_visual_verified', None)
        captions = {r['review_id'] for r in reviews if r['review_id'] in verified
            and caption_verifier is not None and caption_verifier(r, candidate, context)}
        return evaluate_gates(candidate, context, reviews, verified_review_ids=verified,
            verified_caption_review_ids=captions)

    def record(self, args, *, collected=None):
        """collected is internal typed deterministic collection, never tool input."""
        pid = args['project_id']; fs = self.store._filesystem(write=True)
        self.store._pointer(fs, pid)
        with fs.lock(self.store._base(pid) + '/locks/content.lock'):
            pointer = self.store._pointer(fs, pid)
            replay = self.delivery._replay(fs, pid, 'review', args)
            if replay is not None:
                return replay
            candidate = self.delivery.candidate(fs, pointer, args['candidate'])
            if digest(candidate) != args['expected_candidate_manifest_sha256']:
                raise ContractError('HASH_MISMATCH', 'Candidate manifest changed.')
            if self.attribution is None or self.verify_review is None:
                raise ContractError('REVIEW_AUTHOR_UNVERIFIED', 'Runtime review attribution/evidence verifier is not wired.')
            context = self.delivery.context(fs, pointer, candidate)
            author = self.attribution(args if collected is None else collected)
            if not isinstance(author, dict) or set(author) != {'author', 'tool', 'tool_version'}:
                raise ContractError('REVIEW_AUTHOR_UNVERIFIED', 'Missing runtime attribution.')
            fields = {k: copy.deepcopy(args[k]) for k in ('gate', 'result', 'method', 'evidence', 'coverage', 'findings', 'reason')}
            if (fields['method'] == 'deterministic') != (collected is not None):
                raise ContractError('REVIEW_AUTHOR_UNVERIFIED', 'Deterministic evidence requires core collection.')
            record = {'schema': 'motion/v1/review', 'review_id': _id('rev'), 'project_id': pid,
                'created_at': _now(), 'subject': candidate['artifact'], 'candidate_manifest_sha256': digest(candidate),
                'subject_dependencies': candidate['dependencies_sha256'], 'policy': candidate['gate_policy'],
                **fields, **copy.deepcopy(author), 'measurements': copy.deepcopy(collected['measurements']) if collected else [],
                'supersedes': args.get('supersedes')}
            validate_review(record, 'ReviewRecord')
            required_author = {'deterministic': 'system', 'agent_visual': 'agent',
                               'agent_audio': 'agent', 'user': 'user'}.get(record['method'])
            if required_author is not None and record['author']['kind'] != required_author:
                raise ContractError('REVIEW_AUTHOR_UNVERIFIED', 'Review method is incompatible with verified runtime actor.')
            if not record['author']['actor_ref'] or not record['tool']:
                raise ContractError('REVIEW_AUTHOR_UNVERIFIED', 'Runtime actor/tool identity must be nonempty.')
            all_reviews = self._all(fs, pid) + [record]
            scoped = [r for r in all_reviews if r['subject'] == candidate['artifact']]
            verified = self._verified(fs, pointer, candidate, context, scoped)
            if record['review_id'] not in verified:
                raise ContractError('REVIEW_AUTHOR_UNVERIFIED', 'Runtime could not verify review evidence and author.')
            summary = self._evaluate_verified(candidate, context, scoped, verified)
            result = {'review': record, 'gates': summary}
            self.delivery._commit(fs, pid, 'review', args, result, {'reviews': [record]})
            return result

    def dispatch(self, args):
        validate_review(args, 'ReviewRequest')
        if args['action'] == 'record':
            return self.record(args)
        if args['action'] == 'check':
            if self.execute is None:
                raise ContractError('CAPABILITY_MISSING', 'B06/B07 review.check compiler is not wired.')
            return self.execute('motion_review', copy.deepcopy(args))
        fs = self.store._filesystem(); pointer = self.store._pointer(fs, args['project_id'])
        if args['action'] == 'gates':
            candidate = self.delivery.candidate(fs, pointer, args['candidate'])
            return self.gates(fs, pointer, candidate)
        reviews = self._all(fs, args['project_id'])
        if args['action'] == 'inspect':
            review = next((r for r in reviews if r['review_id'] == args['review_id']), None)
            if review is None:
                raise ContractError('NOT_FOUND', 'Review does not exist in this project.')
            candidate = self.delivery.candidate(fs, pointer, review['subject'])
            reasons = stale_reasons(review, candidate, self.delivery.context(fs, pointer, candidate))
            return {'review': review, 'freshness': 'stale' if reasons else 'current', 'stale_reasons': reasons}
        summaries = []
        for review in reviews:
            if any(key in args and review[field] != args[key] for key, field in
                   [('candidate', 'subject'), ('gate', 'gate'), ('result', 'result')]):
                continue
            candidate = self.delivery.candidate(fs, pointer, review['subject'])
            context = self.delivery.context(fs, pointer, candidate)
            summaries.append({k: review[k] for k in ('review_id', 'subject', 'gate', 'result', 'method', 'author', 'created_at')}
                | {'freshness': 'stale' if stale_reasons(review, candidate, context) else 'current'})
        return self.store._page(fs, {**args, '_tool': 'motion_review'},
            None if args.get('cursor') or args.get('snapshot_id') else summaries)
