"""Shared release contract; all release descriptors in tests are synthetic."""
import copy
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release_under_test', ROOT / 'studio/release.py')
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


SOURCE = 'https://example.invalid/test-only/studio.git'
REVISION = 'a' * 40


def fixture_release(root, qualified=True, optional=True):
    """Synthetic fixture ONLY, not published/qualified production metadata."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'studio').mkdir()
    (root / 'studio' / 'broken.py').write_text('raise RuntimeError("must never import installed code")\n')
    (root / '__init__.py').write_text('raise RuntimeError("must never import installed plugin")\n')
    (root / 'plugin.yaml').write_text('name: motion-studio\nversion: 0.0.0-test\npython_dependencies: []\n')
    manifest = release.development_manifest(root)
    if qualified:
        manifest['qualification'] = 'qualified'
        manifest['compatibility'] = dict(platforms=['linux'], architectures=['x86_64'], python='>=3.9,<4', hermes='test-only',
            tested_host_revisions=['b' * 40], adapter_abis=[1], project_schemas=[1], plan_schemas=[1])
        manifest['storage'] = dict(readable=[1], writable=[1], migration='none')
        manifest['packs'] = [dict(id='core', required=True, platforms=['linux'],
            operations=['fixture'], compatibility='test-only', dependencies=[])]
        if optional:
            manifest['packs'].append(dict(id='missing-test-engine', required=False,
                platforms=['linux'], operations=['fixture'], compatibility='test-only',
                dependencies=[dict(kind='executable', identifier='missing-test-engine', constraint=None,
                    source=None, sha256=None, size=None, verification='binding-discovery',
                    delivery='existing', notices=[])]))
    (root / release.MANIFEST).write_text(json.dumps(manifest, sort_keys=True) + '\n')
    descriptor = dict(schema='motion/studio-release/v1', source=SOURCE, commit=REVISION,
        version=manifest['version'], manifest_sha256=release.digest((root / release.MANIFEST).read_bytes()),
        payload_sha256=release.aggregate(root))
    return manifest, descriptor


class ManifestTests(unittest.TestCase):
    def test_inventory_binds_exact_bytes_size_and_mode(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            root = Path(tmp)
            (root / 'studio').mkdir()
            code = root / 'studio/main.py'
            code.write_bytes(b'fixture\n')
            code.chmod(0o755)
            self.assertEqual(release.inventory(root), [dict(path='studio/main.py', size=8,
                sha256=hashlib.sha256(b'fixture\n').hexdigest(), mode=0o755)])

    def fixture(self):
        temp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(temp.cleanup)
        root = Path(temp.name) / 'payload'
        manifest, descriptor = fixture_release(root)
        return root, manifest, descriptor

    def test_manifest_schema_snapshot_is_authoritative(self):
        self.assertEqual(json.loads((ROOT / 'schemas/studio-manifest.json').read_text()),
                         release.manifest_schema())

    def test_development_manifest_exact_but_never_install_ready(self):
        value = release.verify_tree(ROOT)
        self.assertEqual(value['qualification'], 'unqualified-development')
        with self.assertRaisesRegex(release.ValidationError, 'unqualified'):
            release.validate_manifest(value, install_ready=True)

    def test_manifest_self_hash_and_unknown_schema_rejected(self):
        _, manifest, _ = self.fixture()
        for path in ('../escape', '/absolute', 'studio/../escape', 'studio//x',
                     'studio/./x', 'studio\\x', 'studio-manifest.json', 'tools/x'):
            with self.subTest(path=path):
                value = copy.deepcopy(manifest)
                value['payload'][0]['path'] = path
                with self.assertRaises(release.ValidationError):
                    release.validate_manifest(value)
        manifest['schema'] = 'unknown'
        with self.assertRaises(release.ValidationError):
            release.validate_manifest(manifest)

    def test_duplicates_case_collision_and_bad_hashes_rejected(self):
        _, manifest, _ = self.fixture()
        for name, record in [('duplicate', dict(manifest['payload'][0])),
                             ('case', dict(manifest['payload'][0], path='__INIT__.py'))]:
            value = copy.deepcopy(manifest)
            value['payload'].append(record)
            value['payload'].sort(key=lambda row: row['path'])
            with self.subTest(name=name), self.assertRaises(release.ValidationError):
                release.validate_manifest(value)
        for hash_value in ('a' * 63, 'A' * 64, 'z' * 64):
            value = copy.deepcopy(manifest)
            value['payload'][0]['sha256'] = hash_value
            with self.assertRaises(release.ValidationError):
                release.validate_manifest(value)

    def test_tree_and_descriptor_bind_full_exact_bytes(self):
        root, manifest, descriptor = self.fixture()
        self.assertEqual(release.verify_descriptor(root, descriptor, SOURCE), descriptor)
        wrong = dict(descriptor, commit='A' * 40)
        with self.assertRaises(release.ValidationError):
            release.verify_descriptor(root, wrong, SOURCE)
        for field in ('manifest_sha256', 'payload_sha256', 'version'):
            wrong = dict(descriptor, **{field: '0' * 64 if field.endswith('sha256') else 'wrong'})
            with self.subTest(field=field), self.assertRaises(release.ValidationError):
                release.verify_descriptor(root, wrong, SOURCE)
        (root / 'studio/broken.py').write_text('tampered\n')
        with self.assertRaisesRegex(release.ValidationError, 'payload differs'):
            release.verify_tree(root, manifest)

    def test_development_builder_includes_shared_default_tool_packs(self):
        from unittest.mock import patch
        root, _, _ = self.fixture()
        (root / '.git').mkdir()
        (root / 'schemas').mkdir()
        builder_spec = importlib.util.spec_from_file_location('manifest_builder_under_test',
            ROOT / 'tools/build_studio_manifest.py')
        assert builder_spec is not None and builder_spec.loader is not None
        builder = importlib.util.module_from_spec(builder_spec)
        builder_spec.loader.exec_module(builder)
        defaults_spec = importlib.util.spec_from_file_location('default_tools_under_test',
            ROOT / 'studio/default_dependencies.py')
        assert defaults_spec is not None and defaults_spec.loader is not None
        defaults = importlib.util.module_from_spec(defaults_spec)
        defaults_spec.loader.exec_module(defaults)
        current = release.read_json(root / release.MANIFEST)
        current['qualification'] = 'unqualified-development'
        (root / release.MANIFEST).write_text(json.dumps(current) + '\n')
        with patch.object(builder, 'ROOT', root):
            self.assertEqual(builder.main(['--write-development']), 0)
        value = release.read_json(root / release.MANIFEST)
        self.assertEqual(value['packs'], defaults.DEFAULT_TOOL_PACKS)

    def test_required_python_pack_must_agree_with_native_declaration(self):
        root, manifest, _ = self.fixture()
        manifest['packs'][0]['dependencies'].append(dict(kind='python', identifier='test-only-python',
            constraint='>=1', source=None, sha256=None, size=None, verification='native-python',
            delivery='existing', notices=[]))
        with self.assertRaisesRegex(release.ValidationError, 'SHARED_DEPENDENCY_CHANGE'):
            release.verify_tree(root, manifest)

    def test_version_native_dependencies_and_unknown_fields_fail_closed(self):
        root, manifest, _ = self.fixture()
        for content in ('name: motion-studio\nversion: 9.9.9\npython_dependencies: []\n',
                        'name: motion-studio\nversion: 0.0.0-test\npython_dependencies:\n - bad\n'):
            (root / 'plugin.yaml').write_text(content)
            with self.assertRaises(release.ValidationError):
                release.verify_tree(root, manifest)
        manifest['unknown'] = 'not accepted'
        with self.assertRaises(release.ValidationError):
            release.validate_manifest(manifest)

    def test_symlinks_hardlinks_nonregular_and_case_collisions_rejected(self):
        for kind in ('symlink', 'hardlink', 'fifo', 'case'):
            with self.subTest(kind=kind):
                root, _, _ = self.fixture()
                target = root / 'studio/unsafe.py'
                if kind == 'symlink':
                    target.symlink_to(root / 'studio/broken.py')
                elif kind == 'hardlink':
                    os.link(root / 'studio/broken.py', target)
                elif kind == 'fifo':
                    os.mkfifo(target)
                else:
                    (root / 'studio/BROKEN.py').write_text('collision')
                with self.assertRaises(release.ValidationError):
                    release.inventory(root)

    def test_json_bounded_strict_and_diagnostic_does_not_echo_secrets(self):
        root, _, _ = self.fixture()
        for raw in (b'{"x":1,"x":2}', b'{"secret":"do-not-echo",', b'{"x":NaN}',
                    b'[' * 2000 + b']' * 2000):
            (root / 'bad.json').write_bytes(raw)
            with self.subTest(raw=raw[:20]), self.assertRaises(release.ValidationError) as caught:
                release.read_json(root / 'bad.json')
            self.assertNotIn('do-not-echo', str(caught.exception))
        (root / 'bad.json').write_bytes(b' ' * (release.MAX_JSON + 1))
        with self.assertRaisesRegex(release.ValidationError, 'size limit'):
            release.read_json(root / 'bad.json')

    def test_native_git_metadata_and_unmanaged_directories_are_never_read(self):
        from unittest.mock import patch
        root, manifest, _ = self.fixture()
        (root / '.git').mkdir()
        (root / '.git/config').write_text('private git credential')
        (root / 'settings').mkdir()
        (root / 'settings/secrets.json').write_text('private settings')
        original = release.read_bytes
        def guarded(path, *args, **kwargs):
            self.assertNotIn('.git', Path(path).parts)
            self.assertNotIn('settings', Path(path).parts)
            return original(path, *args, **kwargs)
        with patch.object(release, 'read_bytes', side_effect=guarded):
            rows = release.inventory(root, installed=True)
        self.assertFalse(any(row['path'].startswith('.git') for row in rows))
        self.assertTrue(any(row['path'] == 'settings/' for row in rows))

    def test_file_open_rejects_ancestor_swap_even_after_precheck(self):
        from unittest.mock import patch
        root, _, _ = self.fixture()
        alias = root.parent / 'swapped-directory'
        alias.symlink_to(root, target_is_directory=True)
        # Simulate an ancestor changing to a symlink after safe_path's lstat.
        with patch.object(release, 'safe_path', side_effect=lambda path: Path(path)):
            with self.assertRaises((release.ValidationError, OSError)):
                release.read_bytes(alias / 'studio/broken.py')

    def test_deep_payload_is_bounded(self):
        root, _, _ = self.fixture()
        cursor = root / 'studio'
        for _ in range(70):
            cursor /= 'nested'
            cursor.mkdir()
        with self.assertRaisesRegex(release.ValidationError, 'depth limit'):
            release.inventory(root)

    def test_inventory_limits_oversized_files_and_entry_counts(self):
        from unittest.mock import patch
        root, _, _ = self.fixture()
        with patch.object(release, 'MAX_ENTRIES', 1), self.assertRaises(release.ValidationError):
            release.inventory(root)
        with (root / 'studio/huge').open('wb') as file:
            file.truncate(release.MAX_FILE + 1)
        with self.assertRaisesRegex(release.ValidationError, 'size limit'):
            release.inventory(root)

    def test_pack_assets_require_hash_size_and_optional_is_not_core(self):
        _, manifest, _ = self.fixture()
        optional = manifest['packs'][1]
        self.assertFalse(optional['required'])
        optional['dependencies'][0]['delivery'] = 'download'
        with self.assertRaisesRegex(release.ValidationError, 'hash/size'):
            release.validate_manifest(manifest)
