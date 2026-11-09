"""Source-authored regressions; execution is deliberately deferred to the host."""
import copy
import unittest
from unittest.mock import Mock, patch

from studio.contracts import ContractError, digest
from studio.ui_graph import init_graph, compile_graph, apply_operations
from studio.ui_rendering import (RECIPE_ID, compile_canonical_graph,
                                 make_plan_builder, document_closure)


FORMAT = dict(fps=dict(num=30, den=1), width=640, height=360,
              sample_rate=48000, channels=2, duration_frames=0)


RECIPE = dict(id='ui-rgb-lossless-v1', color='srgb-rgb-full-unmanaged-v1',
              background=[0, 0, 0, 255], caption_style=None)


def graph():
    g = init_graph(copy.deepcopy(FORMAT))
    sid = '11111111-1111-4111-8111-111111111111'
    cid = '22222222-2222-4222-8222-222222222222'
    return apply_operations(g, [
        dict(op='scene.create', create_ref=sid, name='Scene', duration_frames=30, background=None),
        dict(op='clip.insert', create_ref=cid, track_id=g['tracks'][0]['track_id'],
             subject=dict(kind='scene', id=sid, version_id=None), start_frame=0, end_frame=30,
             source_mapping=dict(domain='frame', in_index=0, out_index=30,
                                 rate=dict(num=30, den=1), speed=dict(num=1, den=1)),
             linked_group_id=None, enabled=True)], [])['graph']


class RenderingTests(unittest.TestCase):
    def test_recipe_identity_and_no_implicit_legacy_replacement(self):
        self.assertEqual(RECIPE_ID, 'canonical_graph_render_v1')
        self.assertEqual(set(compile_graph(graph())),
                         {'settings', 'timeline', 'scenes', 'format', 'production_documents'})

    def test_canonical_compilation_is_exact_detached_and_schema_closed(self):
        g = graph()
        original = copy.deepcopy(g)
        result = compile_canonical_graph(g, RECIPE)
        self.assertEqual(result['graph'], original)
        self.assertEqual(result['graph_sha256'], digest(original))
        self.assertEqual(result['recipe_id'], RECIPE_ID)
        self.assertTrue(result['schemas'])
        g['format']['width'] = 100
        self.assertEqual(result['graph'], original)

    def test_explicit_canonical_target_uses_actual_source_validation(self):
        from studio.adapters import ui_compositor
        g = graph()
        with patch.object(ui_compositor, 'validate_graph', return_value={}) as validate:
            result = compile_graph(g, backend=RECIPE_ID, recipe=RECIPE)
        validate.assert_called_once_with(g, RECIPE)
        self.assertEqual(result['graph'], g)

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ContractError):
            compile_graph(graph(), backend='invented')

    def test_builder_returns_native_envelope_without_job_submission(self):
        runtime, context = Mock(), {'version': graph()}
        frozen = graph()
        envelope = {'ok': True, 'data': {'plan': 'native-plan'}}
        owned_builder = Mock(return_value=envelope)
        recipe = copy.deepcopy(RECIPE)
        with patch('studio.ui_rendering.compositor.make_plan_builder', return_value=owned_builder) as factory:
            builder = make_plan_builder(recipe)
            recipe['id'] = 'mutated'
            result = builder(runtime, context, frozen, dict(start_frame=0, end_frame=30))
        self.assertIs(result, envelope)
        self.assertEqual(factory.call_args.args[0], RECIPE)
        self.assertEqual(factory.call_args.kwargs['mode'], 'composition')
        owned_builder.assert_called_once_with(runtime, context, frozen, dict(start_frame=0, end_frame=30))
        runtime.run.assert_not_called()

    def test_frame_builder_uses_owned_frame_mode(self):
        with patch('studio.ui_rendering.compositor.make_plan_builder') as factory:
            make_plan_builder({}, mode='frame')
        self.assertEqual(factory.call_args.kwargs['mode'], 'frame')

    def test_empty_document_closure_has_no_publication(self):
        runtime = Mock()
        self.assertEqual(document_closure(runtime, {}, graph()), [])
        runtime.artifacts.publish_json.assert_not_called()

    def test_auto_mode_routes_partial_one_frame_to_owned_frame_builder(self):
        runtime, context, frozen = Mock(), {}, graph()
        render, frame = Mock(), Mock(return_value={'ok': True, 'data': {}})
        with patch('studio.ui_rendering.compositor.make_plan_builder', side_effect=[render, frame]) as factory:
            builder = make_plan_builder(RECIPE)
            builder(runtime, context, frozen, dict(start_frame=4, end_frame=5))
        self.assertEqual(factory.call_args.kwargs['mode'], 'frame')
        render.assert_not_called()
        frame.assert_called_once()

    def test_private_streamfacts_must_match_trusted_resolver_exactly(self):
        frozen = graph()
        asset = dict(asset_id='asset-fixture', asset_version_id='version-fixture',
                     sha256='a' * 64, kind='image',
                     artifact=dict(artifact_id='art_11111111-1111-4111-8111-111111111111',
                                   sha256='sha256:' + 'a' * 64))
        frozen['asset_refs'].append(asset)
        resolver = Mock(return_value={**asset, 'kind': 'video'})
        with patch('studio.ui_rendering.compositor.make_plan_builder') as factory:
            builder = make_plan_builder(RECIPE, resolve_asset=resolver)
            with self.assertRaises(ContractError):
                builder(Mock(), {}, frozen, dict(start_frame=0, end_frame=30))
        factory.return_value.assert_not_called()
        resolver.assert_called_once_with({}, {key: asset[key] for key in
                                             ('asset_id', 'asset_version_id', 'sha256')})

    def test_document_closure_preserves_public_hash_schema_and_bytes(self):
        from studio.contracts import empty_brief
        from studio.ui_graph import schema_catalog
        frozen = graph()
        value = empty_brief()
        document = dict(kind='brief', document_id='doc-fixture',
                        document_version_id='dvr_11111111-1111-4111-8111-111111111111',
                        schema_ref=schema_catalog()['brief']['schema_ref'],
                        sha256=digest(value).removeprefix('sha256:'), value=value)
        frozen['production_documents'].append(document)
        runtime = Mock()
        published = []

        def publish(pid, value, *, inputs):
            published.append(copy.deepcopy(value))
            return dict(artifact_id='art_22222222-2222-4222-8222-222222222222', sha256=digest(value))

        runtime.artifacts.publish_json.side_effect = publish
        runtime.artifact_path.return_value = '/not-accessed/mock-document.json'
        with patch('studio.ui_rendering.Path') as path:
            from studio.contracts import canonical
            path.return_value.is_symlink.return_value = False
            path.return_value.is_file.return_value = True
            path.return_value.read_bytes.side_effect = lambda: canonical(published[-1])
            result = document_closure(runtime, {'private_project_id': 'native-project-fixture'}, frozen)
        self.assertEqual(len(result), 1)
        self.assertEqual(published[0]['public_ref']['sha256'], document['sha256'])
        self.assertEqual(published[0]['schema_ref'], document['schema_ref'])
        self.assertEqual(published[0]['value'], value)
        self.assertEqual(result[0]['sha256'], digest(published[0]))
        runtime.artifacts.resolve.assert_called_once()

    def test_bad_recipe_mode_fails_before_runtime_access(self):
        with self.assertRaises(ContractError):
            make_plan_builder({}, mode='background')
