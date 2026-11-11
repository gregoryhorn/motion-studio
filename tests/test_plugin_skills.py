"""Read-only skill discovery, executable examples and packaged source coverage."""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml

from studio.native.skills import SKILLS, register
from studio.native.creation import registration as creation
from studio.native.production import registration as production
from studio.native.production import media, models
from studio.native.creation.hermes import ROOTS as HERMES_TOOLS
from studio.native.technical import registration as technical
from tests.creation_support import Context
from tests.current_package import current_bundle


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / 'studio/native/skills'


def document(path):
    marker, frontmatter, body = path.read_text().split('---', 2)
    if marker:
        raise ValueError('Frontmatter must come first')
    return yaml.safe_load(frontmatter), body


class SkillContext(Context):
    def __init__(self, root):
        super().__init__(root)
        self.skills = {}

    def register_skill(self, name, path, description='', frontmatter=None):
        self.skills[name] = (Path(path), description, frontmatter)


class PluginSkillsTests(unittest.TestCase):
    def test_all_frontmatter_parses_and_matches_registration(self):
        paths = list(HOME.glob('*/SKILL.md'))
        self.assertEqual({path.parent.name for path in paths}, set(SKILLS))
        for path in paths:
            with self.subTest(skill=path.parent.name):
                metadata, body = document(path)
                self.assertEqual(metadata['name'], path.parent.name)
                self.assertEqual(metadata['description'], SKILLS[path.parent.name])
                self.assertTrue(body.strip())
                self.assertLessEqual(len(path.read_text().splitlines()), 120)

    def test_instruction_drift_is_detected_without_rebaselining(self):
        from studio.native import skills
        from studio.domain import Fault
        approved = skills.RELEASE_DIGEST
        with patch.object(skills, 'instruction_digest', return_value='0'*64):
            with self.assertRaises(Fault) as caught:
                register(SkillContext(Path('/unused')))
            self.assertEqual(caught.exception.code, 'SHIPPED_INSTRUCTION_CHANGED')
        self.assertEqual(skills.RELEASE_DIGEST, approved)
        skills.verify_integrity()

    def test_core_is_short_and_packaged_as_a_registered_skill(self):
        self.assertIn('core', SKILLS)
        path = HOME / 'core' / 'SKILL.md'
        self.assertLessEqual(len(path.read_text().splitlines()), 110)
        self.assertEqual(document(path)[0]['name'], 'core')

    def test_inventory_covers_all_67_roles_and_only_ports_ship(self):
        inventory = (ROOT / 'docs/skill-inventory.md').read_text()
        rows = re.findall(r'^\| ([a-z][a-z0-9-]+) \| (PORT|DEFER) \| ([^|]+) \| (.+) \|$',
                          inventory, re.M)
        self.assertEqual(len(rows), 67)
        self.assertEqual(len({row[0] for row in rows}), 67)
        ports = {name for name, decision, _, _ in rows if decision == 'PORT'}
        base = {'core', 'quick-create', 'refine-take', 'production', 'troubleshooting'}
        self.assertEqual(set(SKILLS), ports | base)
        core = document(HOME / 'core' / 'SKILL.md')[1]
        from tools.build_native_package import PYTHON
        for name, decision, qualified, reason in rows:
            with self.subTest(skill=name):
                self.assertTrue(reason.strip())
                path = f'studio/native/skills/{name}/SKILL.md'
                if decision == 'PORT':
                    self.assertEqual(qualified.strip(), 'motion-studio:' + name)
                    self.assertIn('motion-studio:' + name, core)
                    self.assertIn(path, PYTHON)
                else:
                    self.assertNotIn(name, SKILLS)
                    self.assertNotIn(path, PYTHON)

    def test_shipped_skills_never_reference_legacy_tools(self):
        legacy = {'motion_asset', 'motion_asset_library', 'motion_capabilities',
                  'motion_caption', 'motion_deliver', 'motion_plan', 'motion_project',
                  'motion_review', 'motion_run', 'motion_storyboard'}
        native = {'motion_studio_creation', 'motion_studio_production'} | set(HERMES_TOOLS)
        for name in SKILLS:
            text = (HOME / name / 'SKILL.md').read_text()
            with self.subTest(skill=name):
                mentions = set(re.findall(r'\b(?:motion_[a-z_]+|[a-z]+_generate|text_to_speech)\b', text))
                self.assertFalse(mentions & legacy)
                self.assertLessEqual(mentions, native)
                for sibling in re.findall(r'motion-studio:([a-z-]+)', text):
                    self.assertIn(sibling, SKILLS)

    def test_plugin_entry_registers_all_skills_without_effects(self):
        # Exercise the actual unified entry using its package-relative imports.
        with tempfile.TemporaryDirectory() as temp:
            ctx = SkillContext(Path(temp) / 'unopened-data')
            spec = importlib.util.spec_from_file_location('skill_entry', ROOT / 'native-package/__init__.py')
            entry = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(entry)
            modules = {
                '.studio.native.technical.registration': technical,
                '.studio.native.creation.registration': creation,
                '.studio.native.production.registration': production,
            }
            with patch.object(entry, 'import_module', side_effect=lambda name, _: modules[name]), \
                    patch('subprocess.Popen', side_effect=AssertionError('No effects')):
                runtime = entry.register(ctx)
            self.addCleanup(runtime.creation.unload)
            self.addCleanup(runtime.unload)
            self.assertEqual(set(ctx.skills), set(SKILLS))
            for name, (path, description, frontmatter) in ctx.skills.items():
                self.assertEqual(path, HOME / name / 'SKILL.md')
                self.assertTrue(path.is_file())
                self.assertEqual(frontmatter, document(path)[0])
                self.assertEqual(description, frontmatter['description'])
            self.assertFalse(ctx.state.data_dir.exists())

    def test_missing_or_noncallable_optional_registrar_is_quiet(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(Path(temp) / 'unopened-data')
            register(ctx)
            ctx.register_skill = None
            register(ctx)
            self.assertFalse(ctx.state.data_dir.exists())

    def test_current_package_includes_skill_bytes_and_helper(self):
        with zipfile.ZipFile(current_bundle()) as archive:
            for name in SKILLS:
                relative = f'studio/native/skills/{name}/SKILL.md'
                self.assertEqual(archive.read('motion-studio/' + relative), (ROOT / relative).read_bytes())
            helper = archive.read('motion-studio/studio/native/skills/__init__.py')
            self.assertIn(b'def register(ctx)', helper)

    def test_documented_operations_and_example_arguments_match_real_contracts(self):
        operations = set(creation.SCHEMAS) | set(production.SCHEMAS) | set(media.OPERATIONS)
        fields = (set(creation.schema()['parameters']['properties'])
                  | set(production.schema()['parameters']['properties']) | set(models.Brief.model_fields))
        # Validate every identifier-form code span, including native-only RPCs;
        # creative prose is not a second, hardcoded operation catalog.
        vocabulary = operations | fields | set(HERMES_TOOLS) | {'motion_studio_creation', 'motion_studio_production',
                                          'preparation_retryable', 'prelaunch_retryable', 'current.revision'}
        for name in SKILLS:
            _, body = document(HOME / name / 'SKILL.md')
            for token in re.findall(r'`([a-z][a-z_.]*)`', body):
                self.assertIn(token, vocabulary, f'{name}: unsupported identifier {token}')
            # Resolve illustrative opaque placeholders, then validate the exact
            # documented JSON payloads against the real operation-specific models.
            for example in re.findall(r'```json\n(.*?)\n```|`(\{"operation".*?\})`', body, re.S):
                text = next(value for value in example if value)
                text = re.sub(r'<[^>]+>', 'a' * 32, text)
                payload = json.loads(text)
                operation = payload.pop('operation')
                module = production if name == 'production' else creation
                self.assertIn(operation, module.TOOL_OPERATIONS)
                model = module.SCHEMAS[operation]
                if module is creation and operation == 'prepare' and payload.get('method') == 'hermes_tool':
                    model = creation.HermesPrepare
                model.model_validate(payload, strict=True)


if __name__ == '__main__':
    unittest.main()
