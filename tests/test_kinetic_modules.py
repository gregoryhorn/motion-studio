"""Kinetic module/source closure regressions, without browser or production authority."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from studio.adapters import filmmaking as film


class KineticModuleTests(unittest.TestCase):
    def test_core_component_contracts(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ['node', '--test', 'tests/test_kinetic_core.mjs'], cwd=root,
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_packaged_module_closure_and_source_notices(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as temporary:
            root = Path(temporary)
            (root / 'spec.js').write_text("export default {bpm:120,beats:4,scenes:[]};\n")
            package = film.package_kinetic_source(root, ['spec.js'])
            members = {row['relative_path']: row for row in package['members']}
            self.assertEqual(package['entry_member'], 'index.html')
            for name in ('timing', 'math', 'color', 'palette', 'dom', 'typography', 'overlays', 'effects'):
                relative = f'core/{name}.js'
                self.assertIn(relative, members)
                data = (root / relative).read_bytes()
                self.assertEqual(members[relative]['sha256'], 'sha256:' + hashlib.sha256(data).hexdigest())
            for name in ('core-source.txt', 'blocks-source.txt', 'LICENSE-Scenario-MIT.txt', 'NOTICE.md'):
                self.assertIn(name, members)
                self.assertEqual((root / name).read_bytes(), (film.RESOURCES / 'kinetic' / name).read_bytes())
            # Every relative static import/re-export resolves inside the copied closure.
            for name in members:
                if not name.endswith('.js'):
                    continue
                for dependency in re.findall(r"(?:from\s+|import\s*)['\"]([^'\"]+)['\"]", (root / name).read_text()):
                    if dependency.startswith('.'):
                        target = (root / name).parent / dependency
                        relative = target.resolve().relative_to(root).as_posix()
                        self.assertIn(relative, members, f'{name} imports missing {relative}')

    def test_compatibility_source_counter_is_preserved(self):
        engine = film.RESOURCES / 'kinetic'
        snapshot = (engine / 'core-source.txt').read_text()
        self.assertEqual(len(snapshot.rstrip().splitlines()), 410)
        main = (engine / 'main.js').read_text()
        self.assertIn("['blocks.js', 'core.js'].includes(u) ? u.replace('.js', '-source.txt') : u", main)
        self.assertEqual(len(main.rstrip().splitlines()), 59)
        self.assertNotIn('core-source.txt', (engine / 'core.js').read_text().split('\nexport ', 1)[-1])

    def test_garden_source_retains_core_dependency_closure(self):
        from examples.filmmaking.garden.source import source

        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as temporary:
            root = Path(temporary) / 'garden'
            manifest = source(root, 1920, 1080, {'title': 'Core module fixture'})
            members = {row['relative_path'] for row in json.loads(manifest.read_text())['members']}
            for name in ('core.js', 'core/math.js', 'core/timing.js', 'core/effects.js',
                         'LICENSE-Scenario-MIT.txt', 'NOTICE.md', 'UPSTREAM.json'):
                self.assertIn(name, members)
            # Import only the copied engine from this cold bundle, not the checkout.
            script = """const core=await import(process.argv[1]);
if(core.E.outCubic(.5)!==.875 || core.clamp(2)!==1 || core.lerp(2,4,.5)!==3)
  throw Error('Unexpected copied Kinetic helpers');"""
            result = subprocess.run(
                ['node', '--input-type=module', '-e', script, (root / 'core.js').as_uri()],
                cwd=root, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
