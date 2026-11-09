"""Deferred native registration integration tests; no execution during build."""
import io
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from studio.adapters import ui_compositor
from studio.artifacts import ArtifactCatalog
from studio.capabilities import PARAMS, CapabilityRegistry
from studio.contracts import ContractError, canonical, digest
from studio.engine_identity import local_engine_identity
from studio.plans import EXPECTED_PORTS, PORTS, _kind_allowed
from studio.runtime import NativeRuntime


class PinnedSourceFixture:
    def __init__(self, payload, pin):
        self.payload, self.pin = payload, pin
        self.closed = False

    def resolve(self, project_id, pin):
        if project_id != 'project_fixture' or pin != self.pin:
            raise AssertionError('Unexpected source owner or pin')
        return {'fixture': 'record'}

    @contextmanager
    def open_record(self, filesystem, record):
        if record != {'fixture': 'record'}:
            raise AssertionError('Unknown fixture record')
        try:
            with io.BytesIO(self.payload) as stream:
                yield stream
        finally:
            self.closed = True


class ProjectFixture:
    def _filesystem(self):
        return 'fixture_filesystem'


class NativeUIRegistrationTests(unittest.TestCase):
    def test_operation_parameter_and_port_contracts_are_declared(self):
        for operation, primary in (('ui.compose@1', 'media'), ('ui.frame@1', 'frame')):
            with self.subTest(operation=operation):
                self.assertEqual(PARAMS[operation], ui_compositor.PARAMS)
                self.assertEqual(PORTS[operation], ('source assets', '', 'assets'))
                self.assertEqual(EXPECTED_PORTS[operation].split(), [primary, 'source', 'report'])

    def test_registration_does_not_require_optional_engine_identity(self):
        with patch.object(ui_compositor, 'engine_identity', side_effect=AssertionError('Passive registration cannot fingerprint optional engines')):
            registered = ui_compositor.registration()
        self.assertEqual(registered['declaration']['adapter_id'], ui_compositor.ADAPTER_ID)
        implementation = registered['implementation_sha256']
        assert isinstance(implementation, str)
        self.assertTrue(implementation.startswith('sha256:'))
        registry = CapabilityRegistry()
        registry.register(**registered, state='unavailable', checks=[{
            'name': 'fixture-only', 'status': 'fail', 'reason': 'Explicit unqualified fixture.'}])

    def test_source_port_does_not_accept_untyped_json(self):
        self.assertTrue(_kind_allowed('source', 'scene_source', 'application/json'))
        self.assertFalse(_kind_allowed('source', 'json', 'application/json'))

    def test_source_publication_rejects_arbitrary_json_and_media_types(self):
        catalog = ArtifactCatalog(ProjectFixture())
        with self.assertRaises(ContractError):
            catalog.publish_json('project_fixture', {'fixture': 'not canonical graph source'}, kind='scene_source')
        with self.assertRaises(ContractError):
            catalog.publish_json('project_fixture', {}, kind='scene_source', media_type='text/html')

    def test_native_adapter_resolver_selects_owned_compositor(self):
        runtime = NativeRuntime(projects=ProjectFixture())
        adapter = runtime.adapter_resolver({'adapter_id': ui_compositor.ADAPTER_ID})
        self.assertIsInstance(adapter, ui_compositor.LocalUICompositorAdapter)
        self.assertIs(adapter.runtime, runtime)

    def test_plan_engine_identity_uses_current_renderer_bytes(self):
        sentinel = {'fixture': 'byte_identity'}
        with patch.object(ui_compositor, 'engine_identity', return_value=sentinel) as identity:
            result = local_engine_identity({'operation': 'ui.frame@1'}, {'adapter_id': ui_compositor.ADAPTER_ID})
        self.assertEqual(result, sentinel)
        identity.assert_called_once_with()

    def test_timing_resolver_reads_and_closes_pinned_descriptor(self):
        value = {'fixture': 'canonical source'}
        pin = {'artifact_id': 'artifact_fixture', 'sha256': digest(value)}
        catalog = PinnedSourceFixture(canonical(value), pin)
        runtime = NativeRuntime(projects=ProjectFixture())

        def validate_source(project_id, request, metadata, documents, *, resolve_source):
            self.assertEqual(project_id, 'project_fixture')
            self.assertEqual(resolve_source(pin), value)
            return []

        with patch.object(runtime, '_artifacts', catalog), patch.object(ui_compositor, 'validate_timing', side_effect=validate_source):
            result = runtime._validate_timing('project_fixture', {'adapter_id': ui_compositor.ADAPTER_ID}, {}, {})
        self.assertEqual(result, [])
        self.assertTrue(catalog.closed)

    def test_timing_resolver_rejects_noncanonical_bytes(self):
        value = {'fixture': 'canonical source'}
        pin = {'artifact_id': 'artifact_fixture', 'sha256': digest(value)}
        catalog = PinnedSourceFixture(canonical(value) + b'\n', pin)
        runtime = NativeRuntime(projects=ProjectFixture())

        def validate_source(project_id, request, metadata, documents, *, resolve_source):
            return resolve_source(pin)

        with patch.object(runtime, '_artifacts', catalog), patch.object(ui_compositor, 'validate_timing', side_effect=validate_source):
            with self.assertRaises(ContractError) as caught:
                runtime._validate_timing('project_fixture', {'adapter_id': ui_compositor.ADAPTER_ID}, {}, {})
        self.assertEqual(caught.exception.code, 'HASH_MISMATCH')
        self.assertTrue(catalog.closed)
