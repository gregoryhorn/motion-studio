"""Documentation checks use real Git/index snapshots, not commit-message claims."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'docs.py'


def load_script():
    spec = importlib.util.spec_from_file_location('motion_docs', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocumentationUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = load_script()

    def test_python_comments_and_docstrings_do_not_require_narrative_changes(self):
        before = b'"""Old help."""\ndef f():\n    """Old."""\n    return 1\n'
        after = b'"""New help."""\n# Comment\ndef f():\n    """New."""\n    return 1\n'
        self.assertFalse(self.docs.behavior_changed('studio/a.py', before, after))
        self.assertTrue(self.docs.behavior_changed('studio/a.py', before, after.replace(b'return 1', b'return 2')))
        self.assertTrue(self.docs.behavior_changed('studio/a.py', before, None))

    def test_json_formatting_is_not_behavior(self):
        self.assertFalse(self.docs.behavior_changed('schemas/a.json', b'{"a":1}', b'{\n "a": 1\n}'))
        self.assertTrue(self.docs.behavior_changed('schemas/a.json', b'{"a":1}', b'{"a":2}'))

    def test_generated_or_historical_docs_do_not_satisfy_policy(self):
        for path in ('docs/reference/tools.md', 'docs/evidence/a.md', 'docs/rca/a.md', 'tests/test_a.py'):
            self.assertFalse(self.docs.is_narrative(path), path)
        for path in ('README.md', 'CONTRIBUTING.md', 'docs/hermes.md', 'docs/specification/03-contracts.md', 'tools/forced-aligner/README.md'):
            self.assertTrue(self.docs.is_narrative(path), path)

    def test_client_source_requires_narrative_and_active_ui_docs_count(self):
        for path in ('desktop/plugin.js', 'dashboard/plugin_api.py', 'studio-manifest.json'):
            self.assertTrue(self.docs.is_functional(path), path)
        for path in ('docs/ui/README.md', 'docs/ui/05-data-and-api.md'):
            self.assertTrue(self.docs.is_narrative(path), path)
        for path in ('docs/ui/validation.json', 'docs/ui/design-book.html'):
            self.assertFalse(self.docs.is_narrative(path), path)

    def test_reference_matches_registered_catalogue(self):
        from studio.tools import ACTIONS, register_tools
        schemas = {}
        ctx = type('Catalogue', (), {'register_tool': lambda self, name, schema, **kw: schemas.update({name: schema}),
                                 'register_hook': lambda self, *args, **kwargs: None})()
        register_tools(ctx)
        rendered = self.docs.reference_files()
        self.assertEqual(json.loads(rendered['docs/reference/tool-schemas.json']), schemas)
        markdown = rendered['docs/reference/tools.md']
        for name in ACTIONS:
            self.assertIn('## ' + name, markdown)
            self.assertGreater(len(schemas[name]['description']), 80)
        self.assertEqual(rendered, self.docs.reference_files())

    def test_catalogue_is_stable_across_processes_and_hash_seeds(self):
        code = (
            'import json; from studio.tools import register_tools; schemas={}; '
            'ctx=type("Catalogue", (), {"register_tool":lambda self,name,schema,**kw:schemas.update({name:schema}), "register_hook":lambda self,*args,**kw:None})(); '
            'register_tools(ctx); print(json.dumps(schemas, sort_keys=True))'
        )
        outputs = [subprocess.check_output([sys.executable, '-S', '-c', code], cwd=ROOT,
                   env=dict(os.environ, PYTHONHASHSEED=seed)) for seed in ('1', '7', '42')]
        self.assertTrue(all(output == outputs[0] for output in outputs[1:]),
                        'Native schemas must not depend on randomized set iteration')


class DocumentationGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='motion-docs-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Docs test')
        self.git('config', 'user.email', 'docs@example.invalid')
        self.put('scripts/docs.py', SCRIPT.read_text())
        # This isolated Git fixture exercises reference freshness, not the real
        # product contracts. Include every module consumed by the generator so
        # an inherited PYTHONPATH cannot silently rescue incomplete fixtures.
        self.put('studio/__init__.py', '')
        self.put('studio/contracts.py', 'D = {}\nPROJECT_SCHEMA = {}\n')
        self.put('studio/captions.py', 'def schema_document(name):\n    return {"title": name}\n')
        self.put('studio/project.py', 'class ProjectStore:\n    @staticmethod\n    def _document_schema(kind):\n        return {"type": "object", "title": kind}\n')
        self.put('studio/tools.py', 'def register_tools(ctx):\n    pass\n')
        self.put('studio/engine.py', 'VALUE = 1\n')
        self.put('README.md', '# Test\n')
        self.put('docs/hermes.md', '# Fixture Hermes guide\n')
        self.put('docs/specification/03-contracts.md', '# Fixture contracts\n')
        self.run_script('reference')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='ascii')

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'scripts/docs.py'), *args], cwd=self.root, capture_output=True, text=True)

    def test_functional_change_requires_staged_narrative(self):
        self.put('studio/engine.py', 'VALUE = 2\n')
        self.git('add', 'studio/engine.py')
        self.put('README.md', '# Test\nNew functionality.\n')
        result = self.run_script('check', '--staged')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('human-written', result.stdout + result.stderr)
        self.git('add', 'README.md')
        result = self.run_script('check', '--staged')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_client_changes_require_docs_and_ui_docs_satisfy_staged_policy(self):
        self.put('desktop/plugin.js', 'const changed = true;\n')
        self.put('dashboard/plugin_api.py', 'VALUE = 2\n')
        self.git('add', 'desktop', 'dashboard')
        result = self.run_script('check', '--staged')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('human-written', result.stdout + result.stderr)
        self.put('docs/ui/README.md', '# UI\nClient behavior changed.\n')
        self.git('add', 'docs/ui/README.md')
        result = self.run_script('check', '--staged')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staged_reference_cannot_be_rescued_by_unstaged_generation(self):
        self.put('studio/tools.py', 'def register_tools(ctx):\n    ctx.register_tool(name="new_tool", schema={"name":"new_tool", "description":"Example", "parameters":{"type":"object","properties":{}}})\n')
        self.put('README.md', '# Test\nNew tool.\n')
        self.git('add', 'studio/tools.py', 'README.md')
        self.assertEqual(self.run_script('reference').returncode, 0)
        result = self.run_script('check', '--staged')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stale', result.stdout + result.stderr)
        self.git('add', 'docs/reference')
        result = self.run_script('check', '--staged')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_base_mode_covers_committed_changes_and_deletions(self):
        base = self.git('rev-parse', 'HEAD').decode().strip()
        (self.root / 'studio/engine.py').unlink()
        self.git('add', '-u')
        self.git('commit', '-qm', 'remove functionality')
        result = self.run_script('check', '--base', base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('studio/engine.py', result.stdout + result.stderr)
        self.put('README.md', '# Test\nRemoved engine.\n')
        self.assertEqual(self.run_script('check', '--base', base).returncode, 0)

    def test_comment_only_and_test_only_changes_pass(self):
        self.put('studio/engine.py', '# Comment\nVALUE = 1\n')
        self.put('tests/test_example.py', 'assert True\n')
        self.git('add', '.')
        result = self.run_script('check', '--staged')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_local_hook_runs_and_refuses_overwrite(self):
        result = self.run_script('install-hook')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        hook = self.root / '.git/hooks/pre-commit'
        self.assertTrue(os.access(hook, os.X_OK))
        self.put('studio/engine.py', 'VALUE = 2\n')
        self.git('add', 'studio/engine.py')
        result = subprocess.run(['git', 'commit', '-qm', 'must fail'], cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('human-written', result.stdout + result.stderr)
        hook.write_text('#!/bin/sh\n# Existing hook\n')
        self.assertNotEqual(self.run_script('install-hook').returncode, 0)
        self.assertIn('Existing hook', hook.read_text())

    def test_bad_reference_ascii_and_local_links_fail(self):
        self.put('README.md', '# Test\n[Missing](missing.md)\n')
        result = self.run_script('check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing.md', result.stdout + result.stderr)
        (self.root / 'README.md').write_text('# Test\n' + chr(233), encoding='utf-8')
        self.assertNotEqual(self.run_script('check').returncode, 0)

    def test_ascii_check_preserves_untouched_legacy_lines(self):
        legacy = '# Test\nLegacy ' + chr(233) + '\n'
        (self.root / 'README.md').write_text(legacy, encoding='utf-8')
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'legacy baseline')
        base = self.git('rev-parse', 'HEAD').decode().strip()
        self.put('studio/engine.py', 'VALUE = 2\n')
        (self.root / 'README.md').write_text(legacy + 'Documented new behavior.\n', encoding='utf-8')
        result = self.run_script('check', '--base', base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.git('add', 'README.md', 'studio/engine.py')
        result = self.run_script('check', '--staged')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.root / 'README.md').write_text(legacy + 'New ' + chr(233) + '\n', encoding='utf-8')
        result = self.run_script('check', '--base', base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ASCII', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
