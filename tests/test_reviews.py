"""Focused byte-bound policy tests; fixtures are not media quality evidence."""
import copy
import pytest
from studio.contracts import default_gate_policy, digest, ContractError
from studio.reviews import GateContext, evaluate_gates, invalidated_descendants, validate_review


def ident(prefix, n=1):
    return prefix + '_00000000-0000-0000-0000-' + f'{n:012d}'


def pin(n=1):
    return {'artifact_id': ident('art', n), 'sha256': digest({'bytes': n})}


def fixture():
    policy = default_gate_policy()
    policy_pin = {'kind': 'gate_policy', 'id': 'default', 'revision': 1, 'sha256': digest(policy)}
    candidate = {'schema': 'motion/v1/candidate', 'artifact': pin(), 'project_id': ident('prj'),
                 'project_revision': 1, 'plan': {'plan_id': ident('pln'), 'plan_revision': 1, 'plan_sha256': digest({})},
                 'variant_id': 'main', 'variant': {'kind': 'variants', 'id': 'project', 'revision': 1, 'sha256': digest([])},
                 'sidecars': [], 'dependencies_sha256': digest(['source']), 'gate_policy': policy_pin,
                 'job_id': ident('job'), 'created_at': '2026-11-05T00:00:00Z'}
    context = GateContext(policy=policy, policy_pin=policy_pin, dependencies_sha256=candidate['dependencies_sha256'],
                          variant=candidate['variant'], duration_frames=12, sample_count=0, sample_rate=48000,
                          scene_ids=(), transition_keys=(), requested_frames=(0, 11), no_audio=True)
    reviews = []
    for gate, methods in {'creative': ['agent_visual'], 'technical': ['deterministic', 'playback'],
                          'art': ['agent_visual'], 'audio': ['deterministic'], 'delivery_profile': ['deterministic']}.items():
        for method in methods:
            reviews.append({'schema': 'motion/v1/review', 'review_id': ident('rev', len(reviews)+1),
                'project_id': candidate['project_id'], 'created_at': candidate['created_at'], 'subject': pin(),
                'candidate_manifest_sha256': digest(candidate), 'subject_dependencies': candidate['dependencies_sha256'],
                'policy': policy_pin, 'gate': gate, 'result': 'not_applicable' if gate == 'audio' else 'pass',
                'method': method, 'author': {'kind': 'system' if method == 'deterministic' else 'agent', 'actor_ref': 'runtime:fixture'},
                'tool': 'fixture', 'tool_version': None, 'evidence': [pin(2)], 'measurements': [],
                'coverage': {'frame_ranges': [{'start_frame': 0, 'end_frame': 12}], 'sample_ranges': [],
                             'scene_ids': [], 'transition_keys': [], 'whole_decode': method == 'deterministic',
                             'playback': 'pass' if method == 'playback' else 'not_tested'},
                'findings': [], 'reason': 'Contract fixture only', 'supersedes': None})
    return candidate, context, reviews


def evaluate(candidate, context, reviews):
    return evaluate_gates(candidate, context, reviews, verified_review_ids={r['review_id'] for r in reviews})


def test_current_stale_failure_and_audio_na():
    candidate, context, reviews = fixture()
    assert evaluate(candidate, context, reviews)['promotion_eligible']
    stale = copy.deepcopy(reviews)
    stale[0]['subject_dependencies'] = digest(['changed'])
    assert not evaluate(candidate, context, stale)['promotion_eligible']
    reviews[0]['result'] = 'fail'
    assert evaluate(candidate, context, reviews)['gates'][0]['result'] == 'fail'
    reviews[0]['result'] = 'pass'
    reviews[4]['result'] = 'pass'  # Audio cannot vanish without a proven N/A decision.
    assert not evaluate(candidate, context, reviews)['promotion_eligible']


def test_provenance_methods_and_supersession_are_not_interchangeable():
    candidate, context, reviews = fixture()
    assert not evaluate_gates(candidate, context, reviews)['promotion_eligible']
    bad = copy.deepcopy(reviews)
    bad[1]['method'] = 'agent_visual'
    assert not evaluate(candidate, context, bad)['promotion_eligible']
    failed = copy.deepcopy(reviews[1]); failed['review_id'] = ident('rev', 22); failed['result'] = 'fail'
    reviews.append(failed)
    assert not evaluate(candidate, context, reviews)['promotion_eligible']
    reviews[1]['supersedes'] = failed['review_id']
    assert evaluate(candidate, context, reviews)['promotion_eligible']
    reviews[1]['supersedes'] = reviews[0]['review_id']
    with pytest.raises(ContractError):
        evaluate(candidate, context, reviews)


def test_strict_records_and_selective_descendants():
    _, _, reviews = fixture()
    validate_review(reviews[0], 'ReviewRecord')
    reviews[0]['approved_by_user'] = True
    with pytest.raises(ContractError):
        validate_review(reviews[0], 'ReviewRecord')
    graph = {'speech': [], 'caption': ['speech'], 'style': [], 'burn': ['caption', 'style'],
             'scene': [], 'encode': ['burn', 'scene'], 'gates': ['encode']}
    assert invalidated_descendants(graph, {'style'}) == ['burn', 'encode', 'gates', 'style']


def test_b06_document_consumers_policy_stage_and_unrelated_nodes():
    from studio.reviews import affected_plan_nodes
    def doc(kind, key, value):
        return {'kind': kind, 'id': key, 'revision': 1, 'value': value}
    settings = doc('settings', 'project', {'stage': 'brief', 'policy': {'paid': 'deny'}, 'gate_policy': {'revision': 1}})
    style = doc('caption_style', 'main', {'color': 'white'})
    before = {('settings', 'project'): settings, ('caption_style', 'main'): style}
    style_pin = {'kind': 'caption_style', 'id': 'main', 'revision': 1, 'sha256': digest(style)}
    settings_pin = {'kind': 'settings', 'id': 'project', 'revision': 1, 'sha256': digest(settings)}
    nodes = [
        {'node_id': ident('nod', 1), 'dependencies': [], 'operation': 'caption.render@1',
         'inputs': {'style': {'kind': 'document', 'document': style_pin}}, 'parameters': {}, 'binding': {}},
        {'node_id': ident('nod', 2), 'dependencies': [ident('nod', 1)], 'operation': 'delivery.encode@1',
         'inputs': {'media': {'kind': 'node_output', 'node_id': ident('nod', 1), 'port': 'media'}}, 'parameters': {}, 'binding': {}},
        {'node_id': ident('nod', 3), 'dependencies': [], 'operation': 'scene.render@1',
         'inputs': {'settings': {'kind': 'document', 'document': settings_pin}}, 'parameters': {}, 'binding': {}}]
    after = copy.deepcopy(before); after['caption_style', 'main']['value']['color'] = 'yellow'
    assert {r['node_id'] for r in affected_plan_nodes(nodes, before, after)} == {ident('nod', 1), ident('nod', 2)}
    after = copy.deepcopy(before); after['settings', 'project']['value']['stage'] = 'delivery'
    assert affected_plan_nodes(nodes, before, after) == []
    after['settings', 'project']['value']['policy']['paid'] = 'explicit'
    assert len(affected_plan_nodes(nodes, before, after)) == 3
    after = copy.deepcopy(before); after['settings', 'project']['value']['gate_policy']['revision'] = 2
    assert [r['node_id'] for r in affected_plan_nodes(nodes, before, after)] == [ident('nod', 2)]
