"""Deferred recovery acceptance tests. Authored only; do not run before activation gate."""
import copy
import unittest
import uuid

from studio.contracts import ContractError
from studio.ui_graph import apply_operations, init_graph, public_hash, schema_catalog, validate_graph
from studio.ui_recovery import prepare_recovery


def fixture():
    graph = init_graph({'fps': {'num': 30, 'den': 1}, 'width': 1920, 'height': 1080,
                        'sample_rate': 48000, 'channels': 2, 'duration_frames': 0})
    scene, clip = str(uuid.uuid4()), str(uuid.uuid4())
    track = graph['tracks'][0]['track_id']
    out = apply_operations(graph, [
        {'op': 'scene.create', 'create_ref': scene, 'name': 'Scene',
         'duration_frames': 60, 'background': None},
        {'op': 'clip.insert', 'create_ref': clip, 'track_id': track,
         'subject': {'kind': 'scene', 'id': scene, 'version_id': None},
         'start_frame': 0, 'end_frame': 30,
         'source_mapping': {'domain': 'frame', 'in_index': 0, 'out_index': 30,
                            'rate': {'num': 30, 'den': 1}, 'speed': {'num': 1, 'den': 1}},
         'linked_group_id': None, 'enabled': True}])
    graph = out['graph']
    return graph, out['created_ids'][scene], out['created_ids'][clip]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.graph, self.scene, self.clip = fixture()
        self.source = {'composition_id': 'comp_retained', 'version_id': 'version_retained',
                       'composition_revision': 3, 'sha256': 'a' * 64}
        self.head = {**self.source, 'version_id': 'version_current', 'composition_revision': 4,
                     'sha256': 'b' * 64}
        self.review = {'source': copy.deepcopy(self.source), 'current_head': copy.deepcopy(self.head),
                       'base_graph_sha256': public_hash(self.graph),
                       'schema_catalog_sha256': public_hash(schema_catalog()),
                       'transaction': {'operations': [{'op': 'clip.enable', 'clip_id': self.clip,
                                                      'enabled': False}],
                                       'dependency_policy': 'reject_unlisted',
                                       'acknowledged_dependency_ids': [], 'document_rebind_ids': []}}
        self.counter = 0

    def new_id(self, prefix):
        self.counter += 1
        return prefix + '_' + str(uuid.UUID(int=self.counter))

    def prepare(self, **changes):
        args = dict(source=self.source, current_head=self.head, review=self.review,
                    reviewed_sha256=public_hash(self.review),
                    authorize_reference=lambda kind, pin: True, id_factory=self.new_id)
        args.update(changes)
        return prepare_recovery(self.graph, **args)

    def fails(self, code, **kwargs):
        before = copy.deepcopy((self.graph, self.source, self.head, self.review))
        with self.assertRaises(ContractError) as caught:
            self.prepare(**kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual((self.graph, self.source, self.head, self.review), before)

    def test_replay_then_fresh_ids_and_source_and_journal_preserved(self):
        before = copy.deepcopy((self.graph, self.review))
        result = self.prepare()
        recovered = result['graph']
        validate_graph(recovered)
        self.assertFalse(recovered['clips'][0]['enabled'])
        self.assertEqual(recovered['clips'][0]['subject']['id'], result['id_remap'][self.scene])
        self.assertEqual(recovered['tracks'][0]['clip_ids'], [result['id_remap'][self.clip]])
        self.assertNotEqual(result['id_remap'][self.clip], self.clip)
        self.assertEqual((self.graph, self.review), before)
        self.assertEqual(result['recovery_receipt']['state'], 'prepared')
        self.assertNotIn('composition_id', result['recovery_receipt'])

    def test_typed_create_alias_is_authoritatively_remapped_not_text(self):
        alias = str(uuid.uuid4())
        self.review['transaction']['operations'] = [
            {'op': 'scene.create', 'create_ref': alias, 'name': self.scene,
             'duration_frames': 40, 'background': None}]
        result = self.prepare()
        new_scene = next(s for s in result['graph']['scenes'] if s['name'] == self.scene)
        self.assertEqual(new_scene['scene_id'], result['created_ids'][alias])
        self.assertNotEqual(new_scene['scene_id'], alias)
        self.assertEqual(new_scene['name'], self.scene)

    def test_invalid_operation_and_foreign_target_reject_atomically(self):
        self.review['transaction']['operations'][0]['op'] = 'dict.patch'
        self.fails('UNSUPPORTED_OPERATION')
        self.review['transaction']['operations'][0]['op'] = 'clip.enable'
        self.review['transaction']['operations'][0]['clip_id'] = 'clp_foreign'
        self.fails('ENTITY_NOT_FOUND')

    def test_exact_base_version_schema_head_and_review_required(self):
        self.fails('RECOVERY_REVIEW_CHANGED', reviewed_sha256='0' * 64)
        self.fails('SOURCE_CHANGED', source={**self.source, 'version_id': 'version_other'})
        self.fails('SOURCE_CHANGED', current_head={**self.head, 'composition_revision': 5})
        self.review['base_graph_sha256'] = '0' * 64
        self.fails('SOURCE_CHANGED')
        self.review['base_graph_sha256'] = public_hash(self.graph)
        self.review['schema_catalog_sha256'] = '0' * 64
        self.fails('SCHEMA_CHANGED')

    def test_late_invalid_edit_has_no_partial_success(self):
        self.review['transaction']['operations'].append(
            {'op': 'clip.enable', 'clip_id': 'clp_foreign', 'enabled': True})
        self.fails('ENTITY_NOT_FOUND')

    def test_locks_are_not_bypassed(self):
        self.graph['tracks'][0]['locked'] = True
        self.review['base_graph_sha256'] = public_hash(self.graph)
        self.fails('TRACK_LOCKED')

    def test_server_generator_cannot_collide_with_original_or_itself(self):
        self.fails('RECOVERY_ID_INVALID', id_factory=lambda prefix: self.scene)
        self.fails('RECOVERY_ID_INVALID', id_factory=lambda prefix: prefix + '_' + str(uuid.UUID(int=1)))

    def test_dependency_delete_requires_exact_acknowledgement(self):
        self.review['transaction']['operations'] = [
            {'op': 'entity.delete', 'targets': [{'kind': 'scene', 'id': self.scene}],
             'expected_dependency_ids': []}]
        self.fails('AFFECTED_SET_MISMATCH')

    def test_link_group_ids_remap_and_partial_link_edit_fails(self):
        other = copy.deepcopy(self.graph['clips'][0])
        other.update(clip_id='clp_' + str(uuid.uuid4()), start_frame=30, end_frame=60)
        group = 'lnk_' + str(uuid.uuid4())
        self.graph['clips'][0]['linked_group_id'] = group
        other['linked_group_id'] = group
        self.graph['clips'].append(other)
        self.graph['tracks'][0]['clip_ids'].append(other['clip_id'])
        self.graph['format']['duration_frames'] = 60
        self.review['base_graph_sha256'] = public_hash(self.graph)
        result = self.prepare()
        self.assertEqual({c['linked_group_id'] for c in result['graph']['clips']},
                         {result['id_remap'][group]})
        self.review['transaction']['operations'] = [
            {'op': 'clip.move', 'placements': [{'clip_id': self.clip,
             'target_track_id': self.graph['tracks'][0]['track_id'], 'start_frame': 1}],
             'link_policy': 'preserve'}]
        self.fails('LINKED_CLOSURE_REQUIRED')

    def test_preserves_immutable_document_value_and_refreshes_record_identity(self):
        ref = str(uuid.uuid4())
        self.review['transaction']['operations'] = [
            {'op': 'document.put', 'kind': 'stage', 'document_id': None, 'create_ref': ref,
             'schema_ref': schema_catalog()['stage']['schema_ref'], 'value': 'intake',
             'expected_document_sha256': None}]
        result = self.prepare()
        doc = result['graph']['production_documents'][0]
        self.assertEqual(doc['value'], 'intake')
        self.assertEqual(doc['sha256'], public_hash('intake'))
        self.assertEqual(doc['document_id'], result['created_ids'][ref])
        self.assertRegex(doc['document_version_id'], '^dvr_')

    def test_foreign_asset_pin_in_typed_document_is_not_a_grant(self):
        pin = {'asset_id': 'asset_foreign', 'asset_version_id': 'av_foreign', 'sha256': 'c' * 64}
        value = {'audience': '', 'objective': '', 'message': '', 'treatment': '',
                 'constraints': [], 'claims': [], 'reference_assets': [pin]}
        self.review['transaction']['operations'] = [
            {'op': 'document.put', 'kind': 'brief', 'document_id': None,
             'create_ref': str(uuid.uuid4()), 'schema_ref': schema_catalog()['brief']['schema_ref'],
             'value': value, 'expected_document_sha256': None}]
        self.fails('RECOVERY_REFERENCE_UNAUTHORIZED', authorize_reference=lambda kind, ref: False)
        result = self.prepare()
        self.assertEqual(result['graph']['production_documents'][0]['value']['reference_assets'], [pin])
        self.assertEqual(result['recovery_receipt']['preserved_refs']['asset'], [pin])

    def test_creative_scene_rebinding_is_explicit_and_text_is_literal(self):
        plan = {'title': self.scene, 'involvement': 'guided',
                'delegation': {area: 'discuss' for area in ('script', 'direction', 'storyboard', 'audio', 'timing')},
                'objective': '', 'audience': '', 'message': '', 'duration_frames': 60,
                'assumptions': [], 'open_questions': [], 'storyboard_choice': 'declined',
                'beats': [{'beat_id': 'opening', 'title': 'Opening', 'start_frame': 0,
                           'duration_frames': 60, 'narration': '', 'on_screen_text': '',
                           'visual_direction': '', 'asset_requirements': [], 'panel_id': None,
                           'scene_id': self.scene}],
                'tasks': [{'task_id': 'prepare', 'title': 'Prepare', 'beat_ids': ['opening'],
                           'dependencies': [], 'adapter_id': None, 'operation': None, 'missing_inputs': []}],
                'feedback': []}
        alias = str(uuid.uuid4())
        self.review['transaction']['operations'] = [
            {'op': 'document.put', 'kind': 'creative_plan', 'document_id': None, 'create_ref': alias,
             'schema_ref': schema_catalog()['creative_plan']['schema_ref'], 'value': plan,
             'expected_document_sha256': None}]
        self.fails('RECOVERY_REBIND_REQUIRED')
        self.review['transaction']['document_rebind_ids'] = [alias]
        result = self.prepare()
        recovered = result['graph']['production_documents'][0]
        self.assertEqual(recovered['value']['beats'][0]['scene_id'], result['id_remap'][self.scene])
        self.assertEqual(recovered['value']['title'], self.scene)
        self.assertEqual(recovered['sha256'], public_hash(recovered['value']))
        self.assertEqual(plan['beats'][0]['scene_id'], self.scene)

    def test_exact_local_document_pin_preserved_or_explicitly_rebound(self):
        profile = {'profile_id': 'web', 'version': '1', 'label': 'Web', 'sources': [],
                   'valid_until': None,
                   'constraints': {'allowed_containers': [], 'allowed_video_codecs': [],
                    'allowed_audio_codecs': [], 'width_px': None, 'height_px': None, 'rate': None,
                    'max_duration_frames': None, 'max_bytes': None, 'alpha': 'optional',
                    'caption_modes': [], 'loudness_lufs': None, 'loudness_tolerance_lu': None,
                    'true_peak_dbtp': None}}
        def put(kind, value):
            return {'op': 'document.put', 'kind': kind, 'document_id': None,
                    'create_ref': str(uuid.uuid4()), 'schema_ref': schema_catalog()[kind]['schema_ref'],
                    'value': value, 'expected_document_sha256': None}
        self.graph = apply_operations(self.graph, [put('delivery_profile', profile)])['graph']
        target = self.graph['production_documents'][0]
        pin = {key: target[key] for key in ('kind', 'document_id', 'document_version_id', 'sha256')}
        variant = {'variant_id': 'master', 'label': 'Master', 'width_px': 1920, 'height_px': 1080,
                   'rate': {'num': 30, 'den': 1}, 'duration_frames': 30, 'container': 'mp4',
                   'video_codec': 'h264', 'pixel_format': 'yuv420p',
                   'color': {'primaries': 'bt709', 'transfer': 'bt709', 'matrix': 'bt709', 'range': 'limited'},
                   'alpha': 'none', 'audio': {'mode': 'none', 'sample_rate': None, 'channels': None,
                   'codec': None, 'loudness_lufs': None, 'true_peak_dbtp': None}, 'captions': 'none',
                   'profile': pin, 'overrides': {'reason': ''}}
        self.graph = apply_operations(self.graph, [put('variants', [variant])])['graph']
        self.review['base_graph_sha256'] = public_hash(self.graph)
        result = self.prepare()
        recovered = {d['kind']: d for d in result['graph']['production_documents']}
        self.assertEqual(recovered['variants']['value'][0]['profile'], pin)
        self.assertIn(pin, result['recovery_receipt']['preserved_refs']['document'])
        variants_id = next(d['document_id'] for d in self.graph['production_documents'] if d['kind'] == 'variants')
        self.review['transaction']['document_rebind_ids'] = [variants_id]
        result = self.prepare()
        recovered = {d['kind']: d for d in result['graph']['production_documents']}
        self.assertEqual(recovered['variants']['value'][0]['profile'],
                         {key: recovered['delivery_profile'][key] for key in pin})
        self.assertNotEqual(recovered['variants']['value'][0]['profile']['document_id'], pin['document_id'])
        self.assertEqual(recovered['variants']['sha256'], public_hash(recovered['variants']['value']))
        self.review['transaction']['document_rebind_ids'] = []
        self.fails('RECOVERY_REFERENCE_UNAUTHORIZED', authorize_reference=lambda kind, ref: False)

    def test_unknown_fields_and_client_new_ids_are_rejected(self):
        self.review['new_ids'] = {self.clip: 'clp_client'}
        self.fails('INVALID_ARGUMENT')


if __name__ == '__main__':
    unittest.main()
