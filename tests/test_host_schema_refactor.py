"""Host request schemas retain contracts without dead or single-use baggage."""
import copy
import json
import unittest
from collections import Counter

from studio.host_schema import compact_parameters
from studio.tools import register_tools
from test_host_schema import Catalogue, expand


def reference_counts(node):
    counts = Counter()
    if isinstance(node, dict):
        if isinstance(node.get('$ref'), str):
            counts[node['$ref']] += 1
        for child in node.values():
            counts.update(reference_counts(child))
    elif isinstance(node, list):
        for child in node:
            counts.update(reference_counts(child))
    return counts


class HostSchemaRefactorTests(unittest.TestCase):
    def test_request_keeps_transitive_defs_not_response_or_storage_types(self):
        source = {'type': 'object', 'properties': {'input': {'$ref': '#/$defs/Input'}},
                  '$defs': {'Input': {'$ref': '#/$defs/Scalar'},
                            'Scalar': {'type': 'string'},
                            'Response': {'type': 'object'},
                            'DeadCycle': {'$ref': '#/$defs/DeadCycle'}}}
        before = copy.deepcopy(source)
        result = compact_parameters(source)
        self.assertEqual(set(result['$defs']), {'Input', 'Scalar'})
        self.assertEqual(expand(result, result), expand(source, source))
        self.assertEqual(source, before)

    def test_escaped_and_nested_pointer_keeps_whole_target_definition(self):
        source = {'$ref': '#/$defs/a~1b/properties/x', '$defs': {
            'a/b': {'properties': {'x': {'type': 'string'}}}, 'unused': {'type': 'null'}}}
        self.assertEqual(set(compact_parameters(source)['$defs']), {'a/b'})

    def test_percent_encoded_pointer_resolves_before_token_unescaping(self):
        source = {'$ref': '#/$defs/a%20b', '$defs': {
            'a b': {'type': 'string'}, 'unused': {'type': 'null'}}}
        self.assertEqual(set(compact_parameters(source)['$defs']), {'a b'})

    def test_missing_or_root_reference_preserves_defs_for_diagnostics(self):
        for reference in ('#/$defs/missing', '#', '#/properties/value'):
            source = {'$ref': reference, '$defs': {'Keep': {'type': 'string'}}}
            with self.subTest(reference=reference):
                self.assertIn('Keep', compact_parameters(source)['$defs'])

    def test_legacy_definitions_preserve_reference_scope(self):
        source = {'$ref': '#/definitions/Legacy',
                  'definitions': {'Legacy': {'type': 'string'}},
                  '$defs': {'Keep': {'type': 'null'}}}
        self.assertEqual(compact_parameters(source), source)

    def test_nested_reference_scope_is_not_factored(self):
        scoped = {'$id': 'nested', 'type': 'string', 'description': 'scoped ' * 60}
        source = {'type': 'object', 'properties': {'a': scoped, 'b': copy.deepcopy(scoped)}}
        self.assertEqual(compact_parameters(source), source)

    def test_descendant_pointer_target_remains_at_its_original_location(self):
        shared = {'type': 'object', 'properties': {'value': {
            'type': 'string', 'description': 'payload ' * 60}}}
        source = {'type': 'object', 'properties': {
            'selected': {'$ref': '#/$defs/Target/properties/value'},
            'copy': copy.deepcopy(shared)}, '$defs': {'Target': shared}}
        result = compact_parameters(source)
        self.assertIn('properties', result['$defs']['Target'])
        self.assertEqual(expand(result, result), expand(source, source))

    def test_active_cycle_is_kept_without_recursive_traversal(self):
        source = {'$ref': '#/$defs/A', '$defs': {
            'A': {'$ref': '#/$defs/B'}, 'B': {'$ref': '#/$defs/A'},
            'Unused': {'type': 'null'}}}
        self.assertEqual(set(compact_parameters(source)['$defs']), {'A', 'B'})

    def test_uncertain_reference_scope_preserves_definitions(self):
        for extra in ({'$ref': '#anchor'}, {'$ref': 'https://example.test/schema'},
                      {'$dynamicRef': '#node'}, {'$recursiveRef': '#'},
                      {'properties': {'nested': {'$id': 'other', 'type': 'string'}}}):
            source = {'type': 'object', '$defs': {'Keep': {'type': 'string'}}, **extra}
            with self.subTest(extra=extra):
                self.assertIn('Keep', compact_parameters(source)['$defs'])

    def test_ref_looking_example_is_data_not_reachability(self):
        source = {'type': 'object', 'examples': [{'$ref': '#/$defs/Unused'}],
                  '$defs': {'Unused': {'type': 'null'}}}
        result = compact_parameters(source)
        self.assertNotIn('Unused', result.get('$defs', {}))
        self.assertEqual(result['examples'], source['examples'])

    def test_nested_factoring_does_not_leave_single_use_generated_defs(self):
        leaf = {'type': 'string', 'description': 'leaf ' * 60}
        parent = {'type': 'object', 'properties': {'leaf': leaf}, 'additionalProperties': False}
        source = {'type': 'object', 'properties': {'a': parent, 'b': copy.deepcopy(parent)}}
        result = compact_parameters(source)
        counts = reference_counts(result)
        self.assertTrue(result.get('$defs'))
        for key in result['$defs']:
            self.assertGreaterEqual(counts['#/$defs/' + key], 2)
        self.assertEqual(expand(result, result), source)

    def test_existing_single_use_definition_is_not_inlined(self):
        source = {'$ref': '#/$defs/s_owned', '$defs': {'s_owned': {'type': 'string'}}}
        self.assertEqual(compact_parameters(source), source)

    def test_all_eleven_published_schemas_have_no_single_use_generated_defs(self):
        catalogue = Catalogue()
        register_tools(catalogue)
        self.assertEqual(len(catalogue.tools), 11)
        self.assertIn('motion_ui_handoff', catalogue.tools)
        self.assertEqual(set(catalogue.hooks), {'pre_tool_call'})
        self.assertEqual([handler.__name__ for handler in catalogue.hooks['pre_tool_call']],
                         ['observe_handoff_call'])
        for name, schema in catalogue.tools.items():
            params = schema['parameters']
            counts = reference_counts(params)
            for key in params.get('$defs', {}):
                if key.startswith('s_'):
                    with self.subTest(tool=name, definition=key):
                        self.assertGreaterEqual(counts['#/$defs/' + key], 2)
        project_defs = catalogue.tools['motion_project']['parameters'].get('$defs', {})
        self.assertNotIn('ProjectCreateResult', project_defs)


if __name__ == '__main__':
    unittest.main()
