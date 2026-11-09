"""Native registration checks; production effects remain explicit."""
import importlib.util
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'motion_project': ('create', 'list', 'open', 'status', 'update'),
    'motion_capabilities': ('discover', 'list', 'inspect', 'usage', 'host_readiness', 'task_overview', 'setup_report', 'topology_check', 'tool_readiness', 'options', 'voice_get', 'voice_resolve', 'voice_save', 'voice_remove', 'voice_source_disclose', 'voice_source_authorize', 'voice_source_revoke', 'voice_source_get'),
    'motion_asset': ('import', 'reference', 'list', 'get', 'probe'),
    'motion_asset_library': ('get', 'update', 'view'),
    'motion_storyboard': ('get', 'update', 'view'),
    'motion_plan': ('compile', 'list', 'inspect', 'creative_get', 'creative_update', 'creative_accept', 'eta', 'eta_calibrate', 'editorial_get', 'editorial_update', 'editorial_reconform', 'extract_inspect', 'extract_apply', 'extract_bind', 'full_master_apply', 'full_master_bind', 'interchange_import', 'interchange_export'),
    'motion_run': ('submit', 'list', 'status', 'cancel', 'reconcile', 'handoff_claim', 'collect', 'permission_disclose', 'permission_grant', 'permission_inspect', 'permission_revoke'),
    'motion_caption': ('transcribe', 'align', 'adopt', 'get', 'correct', 'style', 'timing_review', 'preview', 'export'),
    'motion_review': ('check', 'record', 'list', 'inspect', 'gates'),
    'motion_deliver': ('encode', 'status', 'validate', 'promote', 'package', 'package_validate', 'files'),
    'motion_ui_handoff': ('inspect', 'execute'),
}

class Context:
    def __init__(self):
        self.tools, self.skills, self.hooks = {}, {}, {}
    def register_tool(self, name, toolset, schema, handler, **kwargs):
        if name in self.tools:
            raise AssertionError('duplicate registration')
        self.tools[name] = dict(toolset=toolset, schema=schema, handler=handler, **kwargs)
    def register_hook(self, name, handler, **kwargs):
        self.hooks.setdefault(name, []).append(handler)
    def register_skill(self, name, path, **kwargs):
        self.skills[name] = dict(path=path, **kwargs)

def load_plugin():
    prefix = 'motion_studio_b01_test'
    for key in list(sys.modules):
        if key == prefix or key.startswith(prefix + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(prefix, ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[prefix] = module
    spec.loader.exec_module(module)
    return module

class RegistrationTests(unittest.TestCase):
    def registered(self):
        ctx = Context()
        load_plugin().register(ctx)
        self.assertEqual(set(ctx.tools), set(EXPECTED))
        return ctx
    def test_exact_native_inventory_and_no_override(self):
        for name, tool in self.registered().tools.items():
            self.assertEqual(tool['toolset'], 'motion_studio')
            self.assertFalse(tool.get('override', False))
            self.assertEqual(tool['schema']['name'], name)
            params = tool['schema']['parameters']
            if name == 'motion_ui_handoff':
                self.assertEqual(params['type'], 'object')
                self.assertFalse(params['additionalProperties'])
                self.assertEqual(set(params['properties']), {'action', 'handoff_id'})
                self.assertEqual(set(params['required']), {'action', 'handoff_id'})
                self.assertEqual(set(params['properties']['action']['enum']), set(EXPECTED[name]))
                self.assertEqual(params['properties']['handoff_id']['pattern'], r'^handoff_[0-9a-f]{32}$')
                continue
            actions = []
            for branch in params['oneOf']:
                action_schema = branch['properties']['action']
                actions.extend(action_schema['enum'] if 'enum' in action_schema else [action_schema['const']])
            self.assertEqual(set(actions), set(EXPECTED[name]))
            self.assertTrue(all(b['additionalProperties'] is False for b in params['oneOf']))
    def test_native_review_and_delivery_validate_real_envelopes(self):
        for name in ('motion_review', 'motion_deliver'):
            tool = self.registered().tools[name]
            result = json.loads(tool['handler']({'action': 'status'}))
            self.assertFalse(result['ok'])
            self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')
            self.assertEqual(result['error']['effect'], 'none')
    def test_invalid_envelopes_rejected_without_echoing_payload(self):
        for name, tool in self.registered().tools.items():
            for args in ({}, None, [], {'action': 'typo'}, {'action': 1}, {'action': []},
                         {'action': 'list', 'command': 'private-canary'}):
                raw = tool['handler'](args)
                result = json.loads(raw)
                self.assertFalse(result['ok'])
                expected_code = 'VALIDATION_ERROR'
                if name in ('motion_asset', 'motion_capabilities', 'motion_plan', 'motion_run', 'motion_caption', 'motion_review', 'motion_deliver', 'motion_asset_library', 'motion_storyboard', 'motion_ui_handoff'):
                    expected_code = 'INVALID_ARGUMENT'
                if name == 'motion_project':
                    expected_code = 'UNKNOWN_ACTION' if args == {'action': 'typo'} else ('UNKNOWN_FIELD' if isinstance(args, dict) and 'command' in args else 'INVALID_ARGUMENT')
                self.assertEqual(result['error']['code'], expected_code)
                self.assertEqual(result['error']['effect'], 'none')
                self.assertNotIn('private-canary', raw)
    def test_registration_is_effect_free_and_initial_skill_is_registered(self):
        with ExitStack() as stack:
            for target in ('pathlib.Path.mkdir', 'pathlib.Path.write_text', 'pathlib.Path.write_bytes',
                           'subprocess.Popen', 'subprocess.run', 'socket.create_connection', 'socket.socket.connect'):
                stack.enter_context(patch(target, side_effect=AssertionError('forbidden effect: ' + target)))
            ctx = self.registered()
        self.assertEqual({name: [handler.__name__ for handler in handlers]
                          for name, handlers in ctx.hooks.items()}, {
            'pre_api_request': ['observe_request', 'pre_api'],
            'pre_tool_call': ['pre_tool', 'pre_call', 'observe_handoff_call'],
            'post_tool_call': ['post_tool', 'post_call'],
            'post_api_request': ['post_api'],
        })
        expected_skills = {row['target_name'] for row in json.loads((ROOT / 'skills/catalog.json').read_text())['skills']}
        self.assertEqual(set(ctx.skills), expected_skills)
        self.assertEqual(ctx.skills['studio-produce']['path'], ROOT / 'skills/studio-produce/SKILL.md')
        self.assertIn('## Procedure', ctx.skills['studio-produce']['path'].read_text())

class SkillMetadataTests(unittest.TestCase):
    def test_all_metadata_matches_authored_yaml(self):
        import yaml
        ctx = Context()
        load_plugin().register(ctx)
        self.assertEqual(len(ctx.skills), 67)
        nested = 0
        for name, skill in ctx.skills.items():
            text = skill['path'].read_text(encoding='ascii')
            expected = yaml.safe_load(text[4:].split('\n---\n', 1)[0])
            self.assertEqual(skill['frontmatter'], expected, name)
            self.assertEqual(skill['description'], expected['description'], name)
            nested += 'metadata' in expected
        self.assertEqual(nested, 25)

    def test_registration_without_site_packages(self):
        import subprocess
        program = """
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
assert importlib.util.find_spec('yaml') is None
spec = importlib.util.spec_from_file_location('isolated_motion', root / '__init__.py',
                                            submodule_search_locations=[str(root)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
class Context:
    def __init__(self): self.skills = {}
    def register_tool(self, *args, **kwargs): pass
    def register_hook(self, *args, **kwargs): pass
    def register_skill(self, name, path, **kwargs): self.skills[name] = kwargs
ctx = Context()
plugin.register(ctx)
expected = json.loads((root / 'skills/registration.json').read_text())['skills']
assert len(ctx.skills) == 67
for row in expected:
    meta = row['frontmatter']
    assert ctx.skills[meta['name']] == {'frontmatter': meta, 'description': meta['description']}
assert 'yaml' not in sys.modules
"""
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', program, str(ROOT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_invalid_before_registration(self, path, replacement):
        original = Path.read_text
        def read(source, *args, **kwargs):
            return replacement if source == path else original(source, *args, **kwargs)
        ctx = Context()
        with patch.object(Path, 'read_text', read):
            with self.assertRaises(ValueError):
                load_plugin().register(ctx)
        self.assertEqual((ctx.skills, ctx.tools, ctx.hooks), ({}, {}, {}))

    def test_stale_source_fails_before_any_registration(self):
        rows = json.loads((ROOT / 'skills/registration.json').read_text())['skills']
        path = ROOT / rows[-1]['path']
        self.assert_invalid_before_registration(path, path.read_text().replace('description:', 'description: changed', 1))

    def test_invalid_inventory_paths_and_metadata_fail_closed(self):
        import copy
        path = ROOT / 'skills/registration.json'
        original = json.loads(path.read_text())
        for case in ('missing', 'duplicate', 'extra', 'renamed', 'path', 'hash', 'description'):
            index = copy.deepcopy(original)
            if case == 'missing': index['skills'].pop()
            elif case == 'duplicate': index['skills'][-1] = index['skills'][0]
            elif case == 'extra': index['skills'].append(index['skills'][0])
            elif case == 'renamed': index['skills'][-1]['frontmatter']['name'] = 'different'
            elif case == 'path': index['skills'][-1]['path'] = '../outside/SKILL.md'
            elif case == 'hash': index['skills'][-1]['frontmatter_sha256'] = '0' * 64
            elif case == 'description': index['skills'][-1]['frontmatter']['description'] = None
            with self.subTest(case=case):
                self.assert_invalid_before_registration(path, json.dumps(index))

    def test_duplicate_catalog_rejected(self):
        path = ROOT / 'skills/catalog.json'
        catalog = json.loads(path.read_text())
        catalog['skills'][-1] = catalog['skills'][0]
        self.assert_invalid_before_registration(path, json.dumps(catalog))

    def test_generated_index_is_current(self):
        spec = importlib.util.spec_from_file_location('skill_registration_generator', ROOT / 'scripts/skill_registration.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        self.assertEqual((ROOT / 'skills/registration.json').read_text(), generator.render(ROOT))


if __name__ == '__main__':
    unittest.main()
