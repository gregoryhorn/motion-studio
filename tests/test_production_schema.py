"""Published Production schema through the actual pinned Hermes sanitizer."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from studio.native.production.registration import schema


HOST = Path(os.environ.get('HERMES_SOURCE', Path.home() / '.hermes/hermes-agent-official'))


class ProductionSchemaTests(unittest.TestCase):
    def test_nested_brief_is_resolved_and_usable_after_pinned_sanitizer(self):
        spec = importlib.util.spec_from_file_location('production_host_schema_sanitizer',
                                                       HOST / 'tools/schema_sanitizer.py')
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        sanitizer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sanitizer)
        shipped = dict(type='function', function=schema())
        visible = sanitizer.sanitize_tool_schemas([shipped])[0]['function']['parameters']
        brief = visible['properties']['brief']
        self.assertEqual(brief['type'], 'object')
        self.assertEqual(set(brief['properties']), {'text', 'purpose', 'audience', 'usage'})
        self.assertEqual(brief['properties']['text']['type'], 'string')
        self.assertEqual(brief['properties']['text']['maxLength'], 8000)
        self.assertFalse(brief['additionalProperties'])
        self.assertNotIn('$ref', json.dumps(visible))
        self.assertNotIn('$defs', json.dumps(visible))
        self.assertEqual(visible['required'], ['operation'])
        self.assertFalse(visible['additionalProperties'])
        self.assertEqual(visible['properties']['depends_on']['items']['pattern'], '^[a-f0-9]{32}$')


if __name__ == '__main__':
    unittest.main()
