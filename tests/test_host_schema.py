"""Host schema compression is a lossless projection, never runtime validation."""
import copy
import json
import unittest
from unittest.mock import patch
from typing import Any

from studio.host_schema import compact_parameters
from studio.tools import register_tools


class Catalogue:
    def __init__(self):
        self.tools = {}
        self.hooks = {}

    def register_tool(self, name, schema, **kwargs):
        self.tools[name] = schema

    def register_hook(self, name, handler, **kwargs):
        # Capture lifecycle registration without invoking any host behavior.
        self.hooks.setdefault(name, []).append(handler)


def expand(node, root) -> Any:
    if isinstance(node, list):
        return [expand(value, root) for value in node]
    if not isinstance(node, dict):
        return node
    if '$ref' in node:
        target = root
        for token in node['$ref'][2:].split('/'):
            target = target[token.replace('~1', '/').replace('~0', '~')]
        return {**expand(target, root), **expand({k:v for k,v in node.items() if k!='$ref'}, root)}
    return {key: expand(value, root) for key, value in node.items() if key != '$defs'}


class HostSchemaTests(unittest.TestCase):
    def test_complete_catalogue_is_lossless_stable_and_smaller(self):
        baseline = Catalogue()
        with patch('studio.host_schema.compact_parameters', side_effect=copy.deepcopy):
            register_tools(baseline)
        compact = Catalogue()
        register_tools(compact)
        again = Catalogue()
        register_tools(again)
        self.assertEqual(compact.tools, again.tools)
        self.assertEqual(set(compact.tools), set(baseline.tools))
        for name, old in baseline.tools.items():
            new = compact.tools[name]
            with self.subTest(tool=name):
                self.assertEqual(expand(new['parameters'], new['parameters']),
                                 expand(old['parameters'], old['parameters']))
                if len(json.dumps(old)) > 20000:
                    self.assertLess(len(json.dumps(new)), len(json.dumps(old)))
        self.assertLess(len(json.dumps(compact.tools['motion_plan'])),
                        len(json.dumps(baseline.tools['motion_plan'])))

    def test_actual_hermes_sanitizer_and_codex_conversion_keep_local_refs(self):
        from tools.schema_sanitizer import sanitize_tool_schemas
        from agent.codex_responses_adapter import _responses_tools
        catalogue = Catalogue()
        register_tools(catalogue)
        raw = [{'type':'function','function':schema} for schema in catalogue.tools.values()]
        sanitized = sanitize_tool_schemas(raw)
        converted = _responses_tools(sanitized)
        assert converted is not None
        self.assertEqual(len(converted),len(raw))
        for tool in converted:
            params=tool['parameters']
            self.assertEqual(params['type'],'object')
            self.assertFalse(params['additionalProperties'])
            self.assertIn('action',params['properties'])
            self.assertIn('action',params['required'])
            expand(params,params)  # raises for any dangling local reference
            self.assertLessEqual(len(json.dumps(params)),len(json.dumps(catalogue.tools[tool['name']]['parameters'])))

    def test_data_objects_are_not_treated_as_schema_positions(self):
        sample = {'type':'object','properties':{'description':{'type':'string','minLength':192}},
                  'required':['description'],'additionalProperties':False}
        schema = {'type':'object','properties':{'a':sample,'b':copy.deepcopy(sample)},
                  'default':{'a':sample,'b':sample},'examples':[sample], 'const':{'x':sample}}
        before = copy.deepcopy(schema)
        result = compact_parameters(schema)
        self.assertEqual(before, schema)
        for key in ('default','examples','const'):
            self.assertEqual(result[key], schema[key])
        self.assertEqual(expand(result, result), schema)

    def test_existing_definitions_and_escaped_refs_survive(self):
        repeated = {'type':'object','description':'A' * 256,'properties':{'value':{'type':'integer'}}}
        schema = {'type':'object','properties':{'a':repeated,'b':copy.deepcopy(repeated),
                  'c':{'$ref':'#/$defs/old~1name'}},'$defs':{'old/name':{'type':'string'}}}
        result = compact_parameters(schema)
        self.assertEqual(expand(result,result), expand(schema,schema))


if __name__ == '__main__':
    unittest.main()
