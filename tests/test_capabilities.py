import copy
import unittest
from unittest.mock import patch
from studio.capabilities import CapabilityRegistry, builtin_ffmpeg, EFFECTS_SCHEMA, PARAMS
from studio.contracts import ContractError, digest, obj, ref


def registry(state='available', features=()):
    r = CapabilityRegistry()
    declaration = builtin_ffmpeg(None)[0]
    declaration['adapter_id'] = 'fixture.probe'
    declaration['operations'] = declaration['operations'][:1]
    declaration['operations'][0]['features'] = list(features)
    op = declaration['operations'][0]
    r.register(declaration, implementation_sha256=digest('fixture'),
               schemas={op['request_schema']: PARAMS['media.probe@1'],
                        op['result_schema']: obj({'report': ref('ArtifactRef')})},
               outputs={'media.probe@1': [{'port': 'report', 'kind': 'report', 'media_type': 'application/json'}]},
               state=state)
    return r


class CapabilityTests(unittest.TestCase):
    def test_discovery_is_cached_and_exact(self):
        r = registry(features=['speech.segments'])
        with patch('subprocess.run', side_effect=AssertionError('execution')):
            self.assertEqual(r.discover(operation='media.probe@1', required_features=['speech.words']), [])
            self.assertEqual(len(r.discover(operation='media.probe@1')), 1)
            self.assertEqual(r.inspect('fixture.probe')['availability']['state'], 'available')
        original = r.inspect('fixture.probe')
        original['declaration']['label'] = 'changed'
        self.assertNotEqual(r.inspect('fixture.probe')['declaration']['label'], 'changed')

    def test_closed_declarations_and_request_schemas(self):
        r = registry()
        with self.assertRaises(ContractError):
            r.dispatch({'action': 'discover', 'command': 'ffmpeg'})
        with self.assertRaises(ContractError):
            r.dispatch({'action': 'list', 'selected_only': True})
        with self.assertRaises(ContractError):
            r.validate_parameters('media.probe@1', {'argv': ['-y']})
        d = r.inspect('fixture.probe')['declaration']
        d['operations'][0]['request_schema'] = 'missing'
        with self.assertRaises(ContractError):
            CapabilityRegistry().register(d, implementation_sha256=digest('x'), schemas={}, outputs={})

    def test_matching_filters_exact_registered_parameter_schema(self):
        r = registry()
        declaration = r.inspect('fixture.probe')['declaration']
        declaration['adapter_id'] = 'fixture.decode-only'
        op = declaration['operations'][0]
        r.register(declaration, implementation_sha256=digest('decode-only'),
            schemas={op['request_schema']: obj({'full_decode': {'const': True}}),
                     op['result_schema']: obj({'report': ref('ArtifactRef')})},
            outputs=r.schema_bundle('fixture.probe')['outputs'], state='available')
        selected = ['fixture.probe', 'fixture.decode-only']
        self.assertEqual(r.match('media.probe@1', [], selected, {'full_decode': False}), ['fixture.probe'])
        self.assertEqual(r.match('media.probe@1', [], selected, {'full_decode': True}),
                         ['fixture.decode-only', 'fixture.probe'])
        # Without a request, match remains a declaration/constraint query.
        self.assertEqual(r.match('media.probe@1', [], selected), ['fixture.decode-only', 'fixture.probe'])

    def test_disabled_and_unavailable_are_not_matches(self):
        for state in ['unknown', 'unavailable', 'disabled']:
            self.assertEqual(registry(state).match('media.probe@1', [], ['fixture.probe']), [])
        self.assertEqual(registry().match('media.probe@1', [], []), [])


if __name__ == '__main__':
    unittest.main()
