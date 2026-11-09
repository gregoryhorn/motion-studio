"""Authored acceptance/unit tests for the pure UI graph (NOT executed here).

Fixtures are intentionally synthetic pinned records, not observed media facts.
No renderer, filesystem store, provider or media binary is invoked by these tests.
"""
import copy
import unittest
import uuid

from studio.contracts import ContractError, D, empty_brief, validate
from studio.timeline import validate_timeline
from studio.ui_graph import (apply_operations, compile_graph, init_graph, public_hash as digest,
                             schema_catalog, validate_graph)


FPS = {'num': 30, 'den': 1}
FORMAT = {'fps': FPS, 'width': 1920, 'height': 1080,
          'sample_rate': 48000, 'channels': 2, 'duration_frames': 0}
HASH = 'a' * 64


def alias():
    return str(uuid.uuid4())


def mapping(first, last, rate=None, speed=None):
    return {'domain': 'frame', 'in_index': first, 'out_index': last,
            'rate': copy.deepcopy(rate or FPS), 'speed': speed or {'num': 1, 'den': 1}}


def track(graph, kind):
    return next(t for t in graph['tracks'] if t['kind'] == kind)


def scene_op(ref, duration=120):
    return {'op': 'scene.create', 'create_ref': ref, 'name': 'Scene',
            'duration_frames': duration, 'background': None}


def insert_op(ref, track_id, subject_id, first=0, last=30, source_first=0,
              subject_kind='scene', version=None, group=None):
    return {'op': 'clip.insert', 'create_ref': ref, 'track_id': track_id,
            'subject': {'kind': subject_kind, 'id': subject_id, 'version_id': version},
            'start_frame': first, 'end_frame': last,
            'source_mapping': mapping(source_first, source_first + last - first),
            'linked_group_id': group, 'enabled': True}


def edit(graph, *ops, ack=()):
    return apply_operations(graph, list(ops), ack)


def populated(duration=120, first=0, last=30):
    graph = init_graph(copy.deepcopy(FORMAT))
    sref, cref = alias(), alias()
    result = edit(graph, scene_op(sref, duration),
                  insert_op(cref, track(graph, 'video')['track_id'], sref, first, last))
    return result['graph'], result['created_ids'][sref], result['created_ids'][cref]


def update_track(t, **changes):
    return {'op': 'track.update', 'track_id': t['track_id'],
            **{k: copy.deepcopy(changes.get(k, t[k])) for k in
               ('name', 'order', 'locked', 'visible', 'muted')}}


def put(kind, value, ref=None, id_=None, expected=None):
    return {'op': 'document.put', 'kind': kind, 'create_ref': ref,
            'document_id': id_, 'schema_ref': schema_catalog()[kind]['schema_ref'],
            'value': value, 'expected_document_sha256': expected}


def hydrate(graph, kind='video', **facts):
    asset_id, version_id = 'asset_' + alias(), 'av_' + alias()
    artifact = {'artifact_id': 'art_' + alias(), 'sha256': 'sha256:' + HASH}
    record = {'asset_id': asset_id, 'asset_version_id': version_id,
              'sha256': HASH, 'kind': kind, 'artifact': artifact,
              'rate': copy.deepcopy(FPS), 'duration_frames': 10000}
    if kind == 'audio':
        record['sample_rate'] = 48000
    record.update(facts)
    graph['asset_refs'].append(record)
    return record


def audio_op(id_, **changes):
    return {'op': 'audio.set', 'target': {'kind': 'clip', 'id': id_},
            'gain_db_milli': changes.get('gain_db_milli', 0),
            'pan_milli': changes.get('pan_milli', 0),
            'muted': changes.get('muted', False), 'fades': changes.get('fades', []),
            'envelope': changes.get('envelope', [])}


def cue_op(ref, track_id, first=0, last=30, text='Hello / مرحبا', id_=None):
    return {'op': 'caption.upsert', 'cue_id': id_, 'create_ref': ref,
            'track_id': track_id, 'start_frame': first, 'end_frame': last,
            'text': text, 'language': 'ar', 'style_ref': None}


class GraphTests(unittest.TestCase):
    def test_public_document_schemas_strip_internal_pins_and_hash_prefix(self):
        catalog = schema_catalog()
        asset = catalog['brief']['schema']['properties']['reference_assets']['items']
        self.assertEqual(set(asset['properties']),{'asset_id','asset_version_id','sha256'})
        profile = catalog['variants']['schema']['items']['properties']['profile']
        self.assertEqual(set(profile['properties']),{'kind','document_id','document_version_id','sha256'})
        for record in catalog.values():
            self.assertNotIn('$defs',record['schema'])
            self.assertRegex(record['schema_ref']['sha256'],r'^[0-9a-f]{64}$')
            self.assertEqual(record['schema_ref']['sha256'],digest(record['schema']))

    def test_bindings_pins_are_single_adapter_ids_not_character_sets(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        value = dict(selected_adapter_ids=['engine.test'],preferences={'render':['engine.test']},pins={'render':'engine.test'})
        result = edit(graph,put('bindings',value,ref=alias()))
        self.assertEqual(compile_graph(result['graph'])['production_documents']['bindings','project'],value)
        self.assert_code('INVALID_GRAPH',lambda: edit(graph,put('bindings',{**value,'pins':{'render':'unselected.adapter'}},ref=alias())))

    def test_scalar_and_array_document_values_keep_exact_public_shapes(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        result = edit(graph,put('stage','concept',ref=alias()),put('variants',[],ref=alias()),put('voice_preferences',None,ref=alias()))
        values = {doc['kind']:doc['value'] for doc in result['graph']['production_documents']}
        self.assertEqual(values,dict(stage='concept',variants=[],voice_preferences=None))
        for doc in result['graph']['production_documents']:
            self.assertEqual(doc['sha256'],digest(doc['value']))
        compiled = compile_graph(result['graph'])
        self.assertEqual(compiled['settings']['stage'],'concept')
        self.assertIsNone(compiled['settings']['voice_preferences'])

    def assert_code(self, code, callback):
        with self.assertRaises(ContractError) as caught:
            callback()
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_seed_four_tracks_zero_duration_unique_server_ids(self):
        supplied = copy.deepcopy(FORMAT)
        graph = init_graph(supplied)
        self.assertEqual(['V1', 'A1', 'Captions', 'Overlay'], [t['name'] for t in graph['tracks']])
        self.assertEqual(['video', 'audio', 'caption', 'overlay'], [t['kind'] for t in graph['tracks']])
        self.assertEqual([0, 1, 2, 3], [t['order'] for t in graph['tracks']])
        self.assertEqual(0, graph['format']['duration_frames'])
        self.assertTrue(all(not t['clip_ids'] for t in graph['tracks']))
        self.assertEqual(4, len({t['track_id'] for t in graph['tracks']}))
        validate_graph(graph)
        graph['format']['fps']['num'] = 60
        self.assertEqual(30, supplied['fps']['num'])

    def test_new_graph_rejects_nonzero_tail_and_unreduced_rate(self):
        value = copy.deepcopy(FORMAT)
        value['duration_frames'] = 30
        self.assert_code('TIMING_INVALID', lambda: init_graph(value))
        value['duration_frames'] = 0
        value['fps'] = {'num': 60, 'den': 2}
        self.assert_code('TIMING_INVALID', lambda: init_graph(value))

    def test_seed_compile_matches_real_contracts(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        compiled = compile_graph(graph)
        validate(compiled['settings'], D['Settings'])
        validate(compiled['timeline'], D['Timeline'])
        validate_timeline(compiled['timeline'], FPS, 48000, scenes=compiled['scenes'])
        self.assertEqual(4, len(compiled['timeline']['tracks']))
        self.assertEqual(0, compiled['timeline']['duration_frames'])
        self.assertEqual(FORMAT, compiled['format'])
        self.assertEqual('deny', compiled['settings']['policy']['remote'])

    def test_alias_resolution_scene_clip_and_duration(self):
        graph, sid, cid = populated(first=12, last=42)
        self.assertTrue(sid.startswith('scn_'))
        self.assertTrue(cid.startswith('clp_'))
        self.assertEqual(sid, graph['clips'][0]['subject']['id'])
        self.assertEqual(42, graph['format']['duration_frames'])
        self.assertEqual([cid], track(graph, 'video')['clip_ids'])
        compiled = compile_graph(graph)
        validate(compiled['scenes'][sid], D['Scene'])
        self.assertEqual(sid, compiled['timeline']['tracks'][0]['items'][0]['subject']['scene_id'])

    def test_transaction_success_and_failure_never_mutate_inputs(self):
        graph, sid, _ = populated()
        original = copy.deepcopy(graph)
        op = insert_op(alias(), track(graph, 'video')['track_id'], sid, 30, 60)
        original_op = copy.deepcopy(op)
        result = edit(graph, op)
        self.assertEqual(original, graph)
        self.assertEqual(original_op, op)
        result['graph']['scenes'][0]['name'] = 'Changed only in result'
        self.assertEqual(original, graph)
        bad = insert_op(alias(), track(graph, 'video')['track_id'], sid, 20, 50)
        self.assert_code('TIMING_INVALID', lambda: edit(graph, op, bad))
        self.assertEqual(original, graph)

    def test_alias_reuse_unknown_and_forward_references_fail(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        ref = alias()
        self.assert_code('INVALID_ARGUMENT', lambda: edit(graph, scene_op(ref), scene_op(ref)))
        self.assert_code('ENTITY_NOT_FOUND', lambda: edit(graph,
            insert_op(alias(), track(graph, 'video')['track_id'], ref), scene_op(ref)))

    def test_create_ref_must_be_uuid_not_chosen_durable_id(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        with self.assertRaises(ContractError):
            edit(graph, scene_op('scn_' + alias()))

    def test_literal_alias_text_not_substituted(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        ref = alias()
        op = scene_op(ref)
        op['name'] = ref
        result = edit(graph, op)
        self.assertEqual(ref, result['graph']['scenes'][0]['name'])

    def test_no_arbitrary_json_patch_unknown_fields_or_variant(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        self.assert_code('UNSUPPORTED_OPERATION', lambda: edit(graph, {'op': 'patch', 'path': '/format'}))
        self.assert_code('UNSUPPORTED_OPERATION', lambda: edit(graph, {'op': ['not-a-string']}))
        op = scene_op(alias())
        op['executable'] = 'anything'
        self.assert_code('UNKNOWN_FIELD', lambda: edit(graph, op))

    def test_float_bool_nan_and_python_objects_rejected(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        for bad in (1.5, float('nan'), float('inf'), True, {'x'}, None):
            with self.subTest(bad=repr(bad)):
                op = scene_op(alias())
                op['duration_frames'] = bad
                with self.assertRaises(ContractError):
                    edit(graph, op)

    def test_transaction_limits_and_hundred_operations(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        self.assert_code('INVALID_ARGUMENT', lambda: apply_operations(graph, []))
        ops = [scene_op(alias()) for _ in range(100)]
        result = apply_operations(graph, ops)
        self.assertEqual(100, len(result['graph']['scenes']))
        self.assertEqual(0, result['graph']['format']['duration_frames'])
        self.assert_code('INVALID_ARGUMENT', lambda: apply_operations(graph, ops * 11))
        self.assert_code('INVALID_ARGUMENT', lambda: apply_operations(graph, ops, 'not-an-array'))

    def test_track_create_alias_insert_update_order(self):
        graph, sid, _ = populated()
        tref, cref = alias(), alias()
        result = edit(graph, {'op': 'track.create', 'create_ref': tref, 'kind': 'video',
                             'name': 'V2', 'order': 1, 'overlap_policy': 'exclusive'},
                      insert_op(cref, tref, sid, 30, 60))
        new_graph = result['graph']
        t = next(t for t in new_graph['tracks'] if t['track_id'] == result['created_ids'][tref])
        changed = edit(new_graph, update_track(t, name='Renamed', order=4))['graph']
        self.assertEqual('Renamed', changed['tracks'][4]['name'])
        self.assertEqual(list(range(5)), [t['order'] for t in changed['tracks']])

    def test_locked_track_explicit_unlock_only(self):
        graph, sid, cid = populated()
        t = track(graph, 'video')
        graph = edit(graph, update_track(t, locked=True))['graph']
        t = track(graph, 'video')
        self.assert_code('TRACK_LOCKED', lambda: edit(graph, {'op': 'clip.enable', 'clip_id': cid, 'enabled': False}))
        self.assert_code('TRACK_LOCKED', lambda: edit(graph, update_track(t, name='Bad', locked=False)))
        result = edit(graph, update_track(t, locked=False), {'op': 'clip.enable', 'clip_id': cid, 'enabled': False})
        self.assertFalse(result['graph']['clips'][0]['enabled'])

    def test_exclusive_overlap_and_source_bounds(self):
        graph, sid, cid = populated(duration=30)
        self.assert_code('TIMING_INVALID', lambda: edit(graph,
            insert_op(alias(), track(graph, 'video')['track_id'], sid, 29, 59)))
        self.assert_code('TIMING_INVALID', lambda: edit(graph, {'op': 'clip.trim', 'clip_id': cid,
            'start_frame': 0, 'end_frame': 31, 'source_mapping': mapping(0, 31), 'link_policy': 'preserve'}))

    def test_half_open_touching_is_not_overlap(self):
        graph, sid, _ = populated()
        graph = edit(graph, insert_op(alias(), track(graph, 'video')['track_id'], sid, 30, 60))['graph']
        self.assertEqual(2, len(graph['clips']))
        self.assertEqual(60, graph['format']['duration_frames'])

    def test_move_preserves_duration_source_and_reports_ranges(self):
        graph, _, cid = populated()
        original_mapping = copy.deepcopy(graph['clips'][0]['source_mapping'])
        result = edit(graph, {'op': 'clip.move', 'placements': [{'clip_id': cid,
            'target_track_id': track(graph, 'video')['track_id'], 'start_frame': 40}], 'link_policy': 'preserve'})
        self.assertEqual((40, 70), (result['graph']['clips'][0]['start_frame'], result['graph']['clips'][0]['end_frame']))
        self.assertEqual(original_mapping, result['graph']['clips'][0]['source_mapping'])
        self.assertIn({'kind': 'clip', 'id': cid}, result['affected_entities'])
        self.assertTrue(result['affected_frame_ranges'])
        self.assertTrue(all('job_id' not in r for r in result['invalidated_refs']))

    def test_trim_slip_and_split_source_offsets(self):
        graph, _, cid = populated()
        graph = edit(graph, {'op': 'clip.trim', 'clip_id': cid, 'start_frame': 10,
            'end_frame': 40, 'source_mapping': mapping(20, 50), 'link_policy': 'preserve'})['graph']
        ref = alias()
        result = edit(graph, {'op': 'clip.split', 'clip_id': cid, 'at_frame': 25,
                             'right_create_ref': ref, 'link_policy': 'preserve'})
        clips = sorted(result['graph']['clips'], key=lambda c: c['start_frame'])
        self.assertEqual(cid, clips[0]['clip_id'])
        self.assertEqual(result['created_ids'][ref], clips[1]['clip_id'])
        self.assertEqual(mapping(20, 35), clips[0]['source_mapping'])
        self.assertEqual(mapping(35, 50), clips[1]['source_mapping'])

    def test_split_endpoint_and_fractional_source_index_rejected(self):
        graph, _, cid = populated()
        for at in (0, 30, 31):
            self.assert_code('TIMING_INVALID', lambda at=at: edit(graph,
                {'op': 'clip.split', 'clip_id': cid, 'at_frame': at,
                 'right_create_ref': alias(), 'link_policy': 'preserve'}))
        graph['clips'][0]['source_mapping'] = mapping(0, 15, speed={'num': 1, 'den': 2})
        validate_graph(graph)
        self.assert_code('TIMING_INVALID', lambda: edit(graph,
            {'op': 'clip.split', 'clip_id': cid, 'at_frame': 1,
             'right_create_ref': alias(), 'link_policy': 'preserve'}))
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(graph))

    def linked(self):
        graph, sid, cid = populated()
        asset = hydrate(graph, 'audio')
        ref = alias()
        graph = edit(graph, insert_op(ref, track(graph, 'audio')['track_id'], asset['asset_id'],
            subject_kind='asset', version=asset['asset_version_id']))['graph']
        aid = graph['clips'][1]['clip_id']
        graph = edit(graph, {'op': 'link.set', 'clip_ids': [cid, aid], 'group_id': alias()})['graph']
        return graph, cid, aid

    def test_linked_move_requires_complete_closure_and_equal_delta(self):
        graph, cid, aid = self.linked()
        move = {'op': 'clip.move', 'link_policy': 'preserve', 'placements': [
            {'clip_id': cid, 'target_track_id': track(graph, 'video')['track_id'], 'start_frame': 10}]}
        self.assert_code('LINKED_CLOSURE_REQUIRED', lambda: edit(graph, move))
        move['placements'].append({'clip_id': aid, 'target_track_id': track(graph, 'audio')['track_id'], 'start_frame': 11})
        self.assert_code('LINKED_OFFSET_CONFLICT', lambda: edit(graph, move))
        move['placements'][1]['start_frame'] = 10
        result = edit(graph, move)
        self.assertEqual([10, 10], [c['start_frame'] for c in result['graph']['clips']])

    def test_linked_trim_explicit_companions_and_equal_edges(self):
        graph, cid, aid = self.linked()
        a = {'op': 'clip.trim', 'clip_id': cid, 'start_frame': 5, 'end_frame': 25,
             'source_mapping': mapping(5, 25), 'link_policy': 'preserve'}
        self.assert_code('LINKED_CLOSURE_REQUIRED', lambda: edit(graph, a))
        b = {**a, 'clip_id': aid}
        result = edit(graph, a, b)
        self.assertEqual([5, 5], [c['start_frame'] for c in result['graph']['clips']])
        b = {**b, 'start_frame': 6, 'source_mapping': mapping(6, 25)}
        self.assert_code('LINKED_OFFSET_CONFLICT', lambda: edit(graph, a, b))

    def test_linked_split_companion_ids_and_new_right_group(self):
        graph, cid, aid = self.linked()
        ref = alias()
        result = edit(graph, {'op': 'clip.split', 'clip_id': cid, 'at_frame': 15,
                             'right_create_ref': ref, 'link_policy': 'preserve'})
        self.assertIn(ref + ':' + aid, result['created_ids'])
        self.assertEqual(4, len(result['graph']['clips']))
        left = [c for c in result['graph']['clips'] if c['start_frame'] == 0]
        right = [c for c in result['graph']['clips'] if c['start_frame'] == 15]
        self.assertEqual(1, len({c['linked_group_id'] for c in right}))
        self.assertNotEqual(left[0]['linked_group_id'], right[0]['linked_group_id'])

    def test_unlink_requires_previous_and_destination_closure(self):
        graph, cid, aid = self.linked()
        self.assert_code('LINKED_CLOSURE_REQUIRED', lambda: edit(graph,
            {'op': 'link.set', 'clip_ids': [cid], 'group_id': None}))
        graph = edit(graph, {'op': 'link.set', 'clip_ids': [cid, aid], 'group_id': None})['graph']
        self.assertTrue(all(c['linked_group_id'] is None for c in graph['clips']))

    def ripple(self, action, start, end, delta, ids, tracks):
        return {'op': 'timeline.ripple', 'track_ids': tracks,
                'range': {'start_frame': start, 'end_frame': end}, 'action': action,
                'delta_frames': delta, 'link_policy': 'preserve', 'expected_affected_ids': ids}

    def test_ripple_insert_gap_and_close_gap(self):
        graph, _, cid = populated(first=30, last=60)
        tid = track(graph, 'video')['track_id']
        graph = edit(graph, self.ripple('insert_gap', 30, 30, 10, [cid], [tid]))['graph']
        self.assertEqual(40, graph['clips'][0]['start_frame'])
        graph = edit(graph, self.ripple('close_gap', 0, 40, -40, [cid], [tid]))['graph']
        self.assertEqual(0, graph['clips'][0]['start_frame'])

    def test_ripple_delete_and_derived_empty_duration(self):
        graph, _, cid = populated()
        result = edit(graph, self.ripple('delete', 0, 30, -30, [cid], [track(graph, 'video')['track_id']]))
        self.assertEqual([], result['graph']['clips'])
        self.assertEqual(0, result['graph']['format']['duration_frames'])
        self.assertTrue(result['graph']['scenes'])

    def test_ripple_rejects_stale_set_crossing_and_nonempty_gap(self):
        graph, _, cid = populated()
        tid = track(graph, 'video')['track_id']
        self.assert_code('AFFECTED_SET_MISMATCH', lambda: edit(graph, self.ripple('insert_gap', 0, 0, 10, [], [tid])))
        self.assert_code('TIMING_INVALID', lambda: edit(graph, self.ripple('delete', 5, 15, -10, [cid], [tid])))
        self.assert_code('TIMING_INVALID', lambda: edit(graph, self.ripple('close_gap', 0, 30, -30, [cid], [tid])))
        self.assert_code('TIMING_INVALID', lambda: edit(graph, self.ripple('delete', 0, 30, -29, [cid], [tid])))

    def test_split_then_ripple_intermediate_affected_set(self):
        graph, _, cid = populated()
        ref = alias()
        result = edit(graph, {'op': 'clip.split', 'clip_id': cid, 'at_frame': 15,
                             'right_create_ref': ref, 'link_policy': 'preserve'},
                      self.ripple('delete', 0, 15, -15, [cid, ref], [track(graph, 'video')['track_id']]))
        self.assertEqual(1, len(result['graph']['clips']))
        self.assertEqual((0, 15), (result['graph']['clips'][0]['start_frame'], result['graph']['clips'][0]['end_frame']))

    def test_delete_scene_requires_exact_closure_and_transaction_ack(self):
        graph, sid, cid = populated()
        op = {'op': 'entity.delete', 'targets': [{'kind': 'scene', 'id': sid}], 'expected_dependency_ids': []}
        self.assert_code('AFFECTED_SET_MISMATCH', lambda: edit(graph, op))
        op['expected_dependency_ids'] = [cid]
        self.assert_code('DEPENDENCY_ACKNOWLEDGEMENT_REQUIRED', lambda: edit(graph, op))
        result = edit(graph, op, ack=[cid])
        self.assertEqual([], result['graph']['scenes'])
        self.assertEqual([], result['graph']['clips'])
        self.assertEqual(0, result['graph']['format']['duration_frames'])

    def test_delete_track_acknowledges_cues_and_clips(self):
        graph, _, cid = populated()
        tid = track(graph, 'video')['track_id']
        result = edit(graph, {'op': 'entity.delete', 'targets': [{'kind': 'track', 'id': tid}],
                             'expected_dependency_ids': [cid]}, ack=[cid])
        self.assertEqual(3, len(result['graph']['tracks']))
        self.assertEqual([], result['graph']['clips'])

    def test_scene_duration_coupled_trim_validated_on_final_graph(self):
        graph, sid, cid = populated()
        op = {'op': 'scene.update', 'scene_id': sid, 'name': 'Short', 'duration_frames': 15, 'background': None}
        self.assert_code('TIMING_INVALID', lambda: edit(graph, op))
        result = edit(graph, op, {'op': 'clip.trim', 'clip_id': cid, 'start_frame': 0,
                     'end_frame': 15, 'source_mapping': mapping(0, 15), 'link_policy': 'preserve'})
        self.assertEqual(15, result['graph']['format']['duration_frames'])

    def test_caption_create_update_unicode_provenance_and_compile_blocker(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        ref = alias()
        result = edit(graph, cue_op(ref, track(graph, 'caption')['track_id']))
        graph = result['graph']
        cid = result['created_ids'][ref]
        graph['captions'][0]['source'] = {'kind': 'asr', 'job_id': 'job-retained', 'confidence_milli': 720}
        before = copy.deepcopy(graph['captions'][0]['source'])
        graph = edit(graph, cue_op(None, track(graph, 'caption')['track_id'], text='Corrected نص', id_=cid))['graph']
        self.assertEqual(before, graph['captions'][0]['source'])
        self.assertEqual(2, graph['captions'][0]['editorial_revision'])
        self.assertEqual(30, graph['format']['duration_frames'])
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(graph))

    def test_caption_upsert_xor_overlap_track_type_and_duration(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        tid = track(graph, 'caption')['track_id']
        self.assert_code('INVALID_ARGUMENT', lambda: edit(graph, cue_op(None, tid)))
        self.assert_code('INVALID_GRAPH', lambda: edit(graph, cue_op(alias(), track(graph, 'video')['track_id'])))
        self.assert_code('TIMING_INVALID', lambda: edit(graph, cue_op(alias(), tid, 10, 10)))
        self.assert_code('TIMING_INVALID', lambda: edit(graph, cue_op(alias(), tid), cue_op(alias(), tid, 20, 40)))

    def test_asset_frame_insert_real_backend_artifact_mapping(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        a = hydrate(graph)
        graph = edit(graph, insert_op(alias(), track(graph, 'video')['track_id'], a['asset_id'],
             0, 30, source_first=100, subject_kind='asset', version=a['asset_version_id']))['graph']
        item = compile_graph(graph)['timeline']['tracks'][0]['items'][0]
        self.assertEqual(a['artifact'], item['subject']['artifact'])
        self.assertEqual(100, item['source_in']['index'])
        self.assertEqual('source', item['source_in']['origin'])

    def test_missing_asset_unknown_bounds_hash_and_track_kind(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        a = hydrate(graph)
        op = insert_op(alias(), track(graph, 'video')['track_id'], a['asset_id'],
                       subject_kind='asset', version=a['asset_version_id'])
        unknown = copy.deepcopy(graph)
        unknown['asset_refs'][0].pop('duration_frames')
        self.assert_code('SOURCE_BOUNDS_UNKNOWN', lambda: edit(unknown, op))
        bad_hash = copy.deepcopy(graph)
        bad_hash['asset_refs'][0]['sha256'] = 'sha256:' + 'b' * 64
        # Public hashes are bare hex; engine-prefixed strings fail shape validation.
        self.assert_code('INVALID_ARGUMENT', lambda: validate_graph(bad_hash))
        op['track_id'] = track(graph, 'audio')['track_id']
        self.assert_code('INVALID_GRAPH', lambda: edit(graph, op))

    def test_signed_source_tick_mapping_exact_bounds_and_compile(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        a = hydrate(graph, time_base={'num': 1, 'den': 90000}, start_pts=-90000, duration_ticks=180000)
        op = insert_op(alias(), track(graph, 'video')['track_id'], a['asset_id'],
                       subject_kind='asset', version=a['asset_version_id'])
        op['source_mapping'] = {'domain': 'source_tick', 'in_pts': -90000, 'out_pts': 0,
                                'start_pts': -90000, 'time_base': {'num': 1, 'den': 90000}, 'conform_ref': None}
        graph = edit(graph, op)['graph']
        point = compile_graph(graph)['timeline']['tracks'][0]['items'][0]['source_in']
        self.assertEqual(-90000, point['index'])
        self.assertEqual({'num': 90000, 'den': 1}, point['rate'])
        broken = copy.deepcopy(graph)
        broken['clips'][0]['source_mapping']['in_pts'] = -90001
        self.assert_code('TIMING_INVALID', lambda: validate_graph(broken))

    def test_audio_gain_milli_precision_mute_and_rejected_automation(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        a = hydrate(graph, 'audio')
        ref = alias()
        result = edit(graph, insert_op(ref, track(graph, 'audio')['track_id'], a['asset_id'],
                      subject_kind='asset', version=a['asset_version_id']),
                      audio_op(ref, gain_db_milli=-3250))
        graph, cid = result['graph'], result['created_ids'][ref]
        compiled = compile_graph(graph)
        audio_track = next(t for t in compiled['timeline']['tracks'] if t['kind'] == 'audio')
        self.assertEqual('-3.25', audio_track['items'][0]['gain_db'])
        self.assertEqual('recorded', compiled['settings']['audio_mode'])
        panned = edit(graph, audio_op(cid, pan_milli=1))['graph']
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(panned))
        graph = edit(graph, audio_op(cid, muted=True))['graph']
        compiled = compile_graph(graph)
        self.assertEqual('silent', compiled['settings']['audio_mode'])
        self.assertFalse(next(t for t in compiled['timeline']['tracks'] if t['kind'] == 'audio')['items'])

    def test_audio_unknown_or_different_sample_rate_rejected(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        a = hydrate(graph, 'audio', sample_rate=44100)
        self.assert_code('UNSUPPORTED_OPERATION', lambda: edit(graph,
            insert_op(alias(), track(graph, 'audio')['track_id'], a['asset_id'],
                      subject_kind='asset', version=a['asset_version_id'])))

    def test_bus_cycle_is_rejected_without_fake_mixer(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        bid = 'bus_' + alias()
        graph['audio_buses'] = [{'bus_id': bid, 'name': 'Master', 'gain_db_milli': 0,
                                'pan_milli': 0, 'muted': False, 'routing_ids': [bid]}]
        self.assert_code('INVALID_GRAPH', lambda: validate_graph(graph))
        graph['audio_buses'][0]['routing_ids'] = []
        validate_graph(graph)
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(graph))

    def test_document_create_replace_hash_cas_and_remove(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        ref = alias()
        result = edit(graph, put('brief', empty_brief(), ref=ref))
        graph = result['graph']
        row = graph['production_documents'][0]
        value = empty_brief()
        value['message'] = 'Literal supplied message'
        stale = put('brief', value, id_=row['document_id'], expected=HASH)
        self.assert_code('STALE_DEPENDENCY', lambda: edit(graph, stale))
        op = put('brief', value, id_=row['document_id'], expected=row['sha256'])
        result = edit(graph, op)
        new_row = result['graph']['production_documents'][0]
        self.assertNotEqual(row['document_version_id'], new_row['document_version_id'])
        self.assertEqual(digest(value), new_row['sha256'])
        self.assertEqual(value, compile_graph(result['graph'])['production_documents'][('brief', 'project')])
        result = edit(result['graph'], {'op': 'document.remove', 'document_id': row['document_id'],
            'expected_document_sha256': new_row['sha256'], 'expected_dependency_ids': []})
        self.assertFalse(result['graph']['production_documents'])

    def test_document_singleton_unknown_schema_and_forged_hash(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        self.assert_code('INVALID_GRAPH', lambda: edit(graph, put('brief', empty_brief(), ref=alias()),
                                                      put('brief', empty_brief(), ref=alias())))
        op = put('brief', empty_brief(), ref=alias())
        op['schema_ref']['sha256'] = HASH
        self.assert_code('UNSUPPORTED_OPERATION', lambda: edit(graph, op))
        graph = edit(graph, put('brief', empty_brief(), ref=alias()))['graph']
        graph['production_documents'][0]['sha256'] = HASH
        self.assert_code('INVALID_GRAPH', lambda: validate_graph(graph))

    def test_catalog_pin_matches_full_schema_bytes_and_is_detached(self):
        catalog = schema_catalog()
        for entry in catalog.values():
            self.assertEqual(digest(entry['schema']), entry['schema_ref']['sha256'])
        catalog['brief']['schema_ref']['version'] = 99
        self.assertEqual(1, schema_catalog()['brief']['schema_ref']['version'])

    def test_execution_policy_is_content_not_authority_or_launch(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        value = {'remote': 'selected_only', 'allowed_destinations': ['example'],
                 'paid': 'explicit', 'max_concurrent_nodes': 2, 'retain_generated_assets': True}
        result = edit(graph, put('execution_policy', value, ref=alias()))
        self.assertEqual(value, compile_graph(result['graph'])['settings']['policy'])
        self.assertNotIn('authority', result)
        self.assertNotIn('job', result)

    def test_binding_selection_validation(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        bad = {'selected_adapter_ids': [], 'preferences': {'voice': ['example.voice']}, 'pins': {}}
        self.assert_code('INVALID_GRAPH', lambda: edit(graph, put('bindings', bad, ref=alias())))

    def test_settings_preserve_frames_and_time_scene_conform(self):
        graph, _, _ = populated()
        fmt = copy.deepcopy(graph['format'])
        fmt['fps'] = {'num': 60, 'den': 1}
        base = {'op': 'settings.set', 'format': fmt, 'color_profile_ref': None,
                'output_profile_refs': [], 'font_fallback_policy': 'reject'}
        frame_graph = edit(graph, {**base, 'retime_policy': 'preserve_frames'})['graph']
        self.assertEqual(30, frame_graph['clips'][0]['end_frame'])
        time_graph = edit(graph, {**base, 'retime_policy': 'preserve_time_nearest_even'})['graph']
        self.assertEqual(60, time_graph['clips'][0]['end_frame'])
        self.assertEqual(240, time_graph['scenes'][0]['duration_frames'])
        self.assertEqual({'num': 60, 'den': 1}, compile_graph(time_graph)['settings']['rate'])

    def test_settings_cannot_author_blank_tail(self):
        graph, _, _ = populated()
        fmt = copy.deepcopy(graph['format'])
        fmt['duration_frames'] += 10
        self.assert_code('TIMING_INVALID', lambda: edit(graph, {'op': 'settings.set', 'format': fmt,
            'retime_policy': 'preserve_frames', 'color_profile_ref': None,
            'output_profile_refs': [], 'font_fallback_policy': 'reject'}))

    def test_unsupported_layers_effects_and_background_not_silently_dropped(self):
        graph, sid, cid = populated()
        pin = {'id': 'unknown.text', 'version': 1, 'sha256': HASH}
        layer = {'op': 'layer.create', 'create_ref': alias(), 'scene_id': sid, 'type': 'text',
                 'schema_ref': pin, 'order': 0, 'start_frame': 0, 'end_frame': 30,
                 'parameters': {'text': 'Not a rendered title'}, 'keyframes': []}
        self.assert_code('UNSUPPORTED_OPERATION', lambda: edit(graph, layer))
        effect = {'op': 'effect.create', 'create_ref': alias(), 'target': {'kind': 'clip', 'id': cid},
                  'schema_ref': pin, 'enabled': True, 'parameters': {}, 'keyframes': []}
        self.assert_code('UNSUPPORTED_OPERATION', lambda: edit(graph, effect))
        graph = edit(graph, {'op': 'scene.update', 'scene_id': sid, 'name': 'Paint',
                            'duration_frames': 120, 'background': [0, 0, 0, 255]})['graph']
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(graph))

    def test_static_owned_image_layout_compiles_without_flattening(self):
        graph, sid, _ = populated()
        a = hydrate(graph, 'image')
        layer_ref = alias()
        result = edit(graph, {'op': 'layer.create', 'create_ref': layer_ref, 'scene_id': sid,
            'type': 'image', 'schema_ref': schema_catalog()['layer.layout']['schema_ref'],
            'order': 0, 'start_frame': 0, 'end_frame': 120,
            'parameters': {'element_key': 'photo', 'rect': {'x_px': 0, 'y_px': 0,
                'width_px': 1920, 'height_px': 1080}, 'z': 0, 'opacity': '1',
                'asset': {key:a[key] for key in ('asset_id','asset_version_id','sha256')}},
            'keyframes': []})
        graph = result['graph']
        compiled = compile_graph(graph)
        self.assertEqual(a['artifact'], compiled['scenes'][sid]['layout'][0]['asset'])
        self.assertIsNone(compiled['scenes'][sid]['authored_source'])
        layer = graph['layers'][0]
        graph = edit(graph, {'op': 'layer.update', 'layer_id': layer['layer_id'],
            'schema_ref': layer['schema_ref'], 'parameters': layer['parameters'], 'keyframes': [],
            'start_frame': 1, 'end_frame': 120, 'order': 0})['graph']
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(graph))

    def test_compile_respects_visibility_enabled_and_mute_without_mutating(self):
        graph, _, cid = populated()
        original = copy.deepcopy(graph)
        graph = edit(graph, update_track(track(graph, 'video'), visible=False))['graph']
        compiled = compile_graph(graph)
        self.assertFalse(compiled['timeline']['tracks'][0]['items'])
        self.assertEqual(30, compiled['timeline']['duration_frames'])
        self.assertEqual(1, len(original['clips']))
        self.assertNotEqual(original, graph)
        before = copy.deepcopy(graph)
        compiled['settings']['rate']['num'] = 100
        self.assertEqual(before, graph)

    def test_compile_explicitly_rejects_composite_overlay_and_cross_track_picture(self):
        graph, sid, _ = populated()
        ref = alias()
        graph = edit(graph, {'op': 'track.create', 'create_ref': ref, 'kind': 'video',
            'name': 'V2', 'order': 4, 'overlap_policy': 'exclusive'},
            insert_op(alias(), ref, sid))['graph']
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(graph))
        graph = init_graph(copy.deepcopy(FORMAT))
        sref = alias()
        graph = edit(graph, scene_op(sref), insert_op(alias(), track(graph, 'overlay')['track_id'], sref))['graph']
        self.assert_code('UNSUPPORTED_OPERATION', lambda: compile_graph(graph))

    def test_validate_rejects_corrupt_projection_missing_fields_and_duplicate_ids(self):
        graph, _, cid = populated()
        for mutate in (lambda g: g['tracks'][0]['clip_ids'].clear(),
                       lambda g: g['clips'][0].pop('subject'),
                       lambda g: g['clips'].append(copy.deepcopy(g['clips'][0])),
                       lambda g: g['format'].update(duration_frames=29)):
            broken = copy.deepcopy(graph)
            mutate(broken)
            with self.assertRaises(ContractError):
                validate_graph(broken)

    def test_storyboard_library_coupling_and_dependency_closure(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        asset = hydrate(graph, 'image')
        asset_pin = {key:asset[key] for key in ('asset_id','asset_version_id','sha256')}
        library = {'assessed': True, 'notes': 'Fixture assessment', 'requirements': [
            {'requirement_id': 'hero', 'role': 'Hero', 'kind': 'image', 'required': True,
             'status': 'ready', 'asset': asset_pin, 'assessment': 'Fixture pin reviewed', 'acquisition': ''}]}
        board = {'title': 'Board', 'asset_library_sha256': digest(library), 'panels': [
            {'panel_id': 'opening', 'title': 'Opening', 'duration_frames': 30,
             'visual': asset_pin, 'asset_requirements': ['hero'],
             'narration': '', 'on_screen_text': '', 'motion': '', 'transition': '', 'notes': ''}],
            'review': {'status': 'draft', 'notes': ''}}
        lref, bref = alias(), alias()
        result = edit(graph, put('storyboard', board, ref=bref), put('asset_library', library, ref=lref))
        graph = result['graph']
        compiled = compile_graph(graph)
        self.assertEqual(board,compiled['production_documents']['storyboard','project'])
        lid, bid = result['created_ids'][lref], result['created_ids'][bref]
        self.assert_code('AFFECTED_SET_MISMATCH', lambda: edit(graph,
            {'op': 'document.remove', 'document_id': lid, 'expected_document_sha256': digest(library),
             'expected_dependency_ids': []}))
        removed = edit(graph, {'op': 'document.remove', 'document_id': lid,
             'expected_document_sha256': digest(library), 'expected_dependency_ids': [bid]}, ack=[bid])
        self.assertEqual([], removed['graph']['production_documents'])
        changed_library = copy.deepcopy(library)
        changed_library['notes'] = 'New content, so old board pin is stale'
        self.assert_code('STALE_DEPENDENCY', lambda: edit(graph,
            put('asset_library', changed_library, id_=lid, expected=digest(library))))

    def test_creative_plan_uses_existing_contiguity_and_dag_contract(self):
        graph = init_graph(copy.deepcopy(FORMAT))
        plan = {'title': 'Plan', 'involvement': 'guided',
                'delegation': {area: 'discuss' for area in ('script', 'direction', 'storyboard', 'audio', 'timing')},
                'objective': '', 'audience': '', 'message': '', 'duration_frames': 30,
                'assumptions': [], 'open_questions': [], 'storyboard_choice': 'declined',
                'beats': [{'beat_id': 'opening', 'title': 'Opening', 'start_frame': 0, 'duration_frames': 30,
                           'narration': '', 'on_screen_text': '', 'visual_direction': '', 'asset_requirements': [],
                           'panel_id': None, 'scene_id': None}],
                'tasks': [{'task_id': 'prepare', 'title': 'Prepare', 'beat_ids': ['opening'],
                           'dependencies': [], 'adapter_id': None, 'operation': None, 'missing_inputs': []}],
                'feedback': []}
        result = edit(graph, put('creative_plan', plan, ref=alias()))
        self.assertEqual(plan, compile_graph(result['graph'])['production_documents'][('creative_plan', 'project')])
        bad = copy.deepcopy(plan)
        bad['beats'][0]['start_frame'] = 1
        with self.assertRaises(ContractError):
            edit(graph, put('creative_plan', bad, ref=alias()))
        bad = copy.deepcopy(plan)
        bad['tasks'][0]['dependencies'] = ['prepare']
        with self.assertRaises(ContractError):
            edit(graph, put('creative_plan', bad, ref=alias()))

    def test_rational_fps_and_exact_duration_no_float_approximation(self):
        fmt = copy.deepcopy(FORMAT)
        fmt['fps'] = {'num': 30000, 'den': 1001}
        graph = init_graph(fmt)
        sid, cid = alias(), alias()
        op = insert_op(cid, track(graph, 'video')['track_id'], sid)
        op['source_mapping']['rate'] = fmt['fps']
        graph = edit(graph, scene_op(sid), op)['graph']
        compiled = compile_graph(graph)
        self.assertEqual(fmt['fps'], compiled['settings']['rate'])
        self.assertEqual(fmt['fps'], compiled['timeline']['tracks'][0]['items'][0]['source_in']['rate'])

    def test_linked_locked_companion_prevents_split_and_enable(self):
        graph, cid, aid = self.linked()
        graph = edit(graph, update_track(track(graph, 'audio'), locked=True))['graph']
        self.assert_code('TRACK_LOCKED', lambda: edit(graph,
            {'op': 'clip.split', 'clip_id': cid, 'at_frame': 15,
             'right_create_ref': alias(), 'link_policy': 'preserve'}))
        self.assert_code('TRACK_LOCKED', lambda: edit(graph,
            {'op': 'clip.enable', 'clip_id': cid, 'enabled': False}))

    def test_new_link_group_gets_server_id_and_alias_resolution(self):
        graph, cid, aid = self.linked()
        graph = edit(graph, {'op': 'link.set', 'clip_ids': [cid, aid], 'group_id': None})['graph']
        ref = alias()
        result = edit(graph, {'op': 'link.set', 'clip_ids': [cid, aid], 'group_id': ref})
        group_id = result['created_ids'][ref]
        self.assertTrue(group_id.startswith('lnk_'))
        self.assertNotEqual(ref, group_id)
        self.assertTrue(all(c['linked_group_id'] == group_id for c in result['graph']['clips']))

    def test_noop_update_has_no_manufactured_invalidations(self):
        graph, _, _ = populated()
        result = edit(graph, update_track(track(graph, 'video')))
        self.assertEqual(graph, result['graph'])
        self.assertEqual([], result['affected_entities'])
        self.assertEqual([], result['affected_frame_ranges'])
        self.assertEqual([], result['invalidated_refs'])


class CanonicalGraphTests(unittest.TestCase):
    RECIPE = dict(id='ui-rgb-lossless-v1', color='srgb-rgb-full-unmanaged-v1',
                  background=[0, 0, 0, 255], caption_style=None)

    def shape_graph(self):
        graph, sid, _ = populated()
        ref = alias()
        p = dict(shape='rectangle', color=[255, 0, 0, 255],
                 transform=dict(x=0, y=0, width=100, height=50,
                                rotation_mdeg=0, opacity_milli=1000, crop=None))
        graph = edit(graph, dict(op='layer.create', create_ref=ref, scene_id=sid,
                     type='shape', schema_ref=schema_catalog()['layer.shape']['schema_ref'],
                     order=0, start_frame=1, end_frame=25, parameters=p,
                     keyframes=[dict(property='x', frame=1, value=10,
                                     easing_ref=schema_catalog()['easing.linear']['schema_ref'])]))['graph']
        return graph

    def test_owned_schema_pins_are_not_rewrapped_or_rehashed(self):
        from studio.adapters.ui_compositor import schema_catalog as owned_catalog
        catalog = schema_catalog()
        for key, value in owned_catalog().items():
            self.assertEqual(catalog[key], value)
            self.assertEqual(digest(value['schema']), value['schema_ref']['sha256'])

    def test_shape_visibility_and_keyframes_survive_exact_canonical_compilation(self):
        graph = self.shape_graph()
        before = copy.deepcopy(graph)
        result = compile_graph(graph, backend='canonical_graph_render_v1', recipe=self.RECIPE)
        self.assertEqual(result['graph'], before)
        self.assertEqual(result['graph']['layers'][0]['start_frame'], 1)
        self.assertEqual(result['graph']['layers'][0]['keyframes'][0]['value'], 10)
        self.assertEqual(graph, before)
        with self.assertRaises(ContractError):
            compile_graph(graph)  # Never misrepresent a shape as B03 Layout.

    def test_canonical_background_is_preserved_without_legacy_flattening(self):
        graph, sid, _ = populated()
        graph = edit(graph, dict(op='scene.update', scene_id=sid, name='Paint',
                               duration_frames=120, background=[12, 34, 56, 255]))['graph']
        result = compile_graph(graph, backend='canonical_graph_render_v1', recipe=self.RECIPE)
        self.assertEqual(result['graph']['scenes'][0]['background'], [12, 34, 56, 255])
        with self.assertRaises(ContractError):
            compile_graph(graph)

    def test_canonical_does_not_drop_unplaced_unsupported_intent(self):
        graph = self.shape_graph()
        graph['layers'][0]['keyframes'][0]['easing_ref']['sha256'] = '0' * 64
        with self.assertRaises(ContractError):
            compile_graph(graph, backend='canonical_graph_render_v1', recipe=self.RECIPE)


if __name__ == '__main__':
    unittest.main()
