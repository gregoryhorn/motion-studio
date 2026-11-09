"""B17 package protocol fixtures, not production media acceptance."""
import copy
import hashlib

import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
import zipfile

from studio.contracts import ContractError
from studio.packaging import build_package, validate_package, schema_document, validate_package_record, RESERVED


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'], prefix='motion-b17-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.records, self.paths = {}, {}
        self.project_id = 'prj_' + str(uuid.uuid4())
        # Retained stochastic bytes are consumed directly; no generation callback exists.
        retained = self.add('asset', 'source/retained.bin', b'retained generated fixture\n', generated=True)
        source = self.add('source', 'source/entry.txt', b'uppercase retained bytes\n', inputs=[retained])
        bundle = {'schema': 'motion/v1/source-bundle', 'entry_member': 'entry.txt',
                  'members': [{'relative_path': Path(m['path']).name,
                               'sha256': m['artifact']['sha256'],
                               'size_bytes': self.records[m['artifact']['artifact_id']]['size_bytes'],
                               'media_type': 'text/plain'} for m in [source, retained]]}
        source_root = self.add('source', 'source/bundle.json', json.dumps(bundle).encode(), inputs=[source, retained])
        plan = self.add('source', 'assembly.json', b'{"operation":"uppercase"}', inputs=[source_root])
        master = self.add('master', 'master.txt', b'RETAINED GENERATED FIXTURE\n', inputs=[plan, retained])
        instructions = self.add('instructions', 'REPRODUCE.txt', b'Fixture adapter uppercases retained bytes.')
        self.members = [retained, source, source_root, plan, master, instructions]
        self.roots = [source_root['artifact']]
        self.manifest = {'schema': 'motion/v1/package-manifest', 'members': self.members,
                         'runtime_requirements': [{'adapter_id': 'fixture.uppercase',
                            'implementation_version': '1', 'engine': 'python-fixture',
                            'engine_version': 'fixture-only', 'dependencies': [source_root['artifact']],
                            'entry_member': 'entry.txt'}],
                         'reproduction': {'assembly_plan': plan['artifact'],
                            'generation_boundary': 'Retained fixture generation bytes; never regenerate.',
                            'expected_equivalence': 'bytes'}, 'exclusions': []}
        self.archive = self.root / 'delivery.zip'

    def add(self, role, path, data, inputs=(), generated=False):
        aid = 'art_' + str(uuid.uuid4())
        location = self.root / 'inputs' / path
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(data)
        artifact = {'artifact_id': aid, 'sha256': sha(data)}
        self.paths[aid] = location
        self.records[aid] = {'schema': 'motion/v1/artifact', 'artifact_id': aid,
            'project_id': self.project_id, 'kind': 'json' if path.endswith('.json') else 'media',
            'media_type': 'application/json' if path.endswith('.json') else 'text/plain',
            'sha256': sha(data), 'size_bytes': len(data),
            'storage': {'mode': 'managed', 'relative_path': path},
            'created_at': '2026-11-05T00:00:00Z',
            'producer': dict.fromkeys(['job_id', 'node_id', 'attempt_id', 'adapter_id']),
            'inputs': [i['artifact'] if 'artifact' in i else i for i in inputs], 'probe_receipt_id': None,
            'provenance': {'origin': 'generated' if generated else 'authored',
                'acquired_at': '2026-11-05T00:00:00Z', 'source_locator': None,
                'provider': 'fixture-only' if generated else None, 'model': None,
                'model_version': None, 'seed': None, 'deterministic': 'no' if generated else 'yes',
                'rights': {'status': 'known', 'license': 'fixture-owned', 'attribution': None,
                           'evidence': []}, 'notes': 'Fixture, not a real generation receipt.'}}
        return {'path': path, 'artifact': artifact, 'role': role}

    def build(self, **kwargs):
        return build_package(self.manifest, self.archive, resolver=lambda ref: self.paths[ref['artifact_id']],
                             records=self.records, source_roots=self.roots, **kwargs)

    def verify(self, built, **kwargs):
        return validate_package(self.archive, expected_archive_sha256=built['archive_sha256'],
                                scratch_root=self.root, **kwargs)

    def test_deterministic_archive_exact_closure_and_missing_runtime(self):
        built = self.build()
        first = self.archive.read_bytes()
        second = self.root / 'other.zip'
        build_package(self.manifest, second, resolver=lambda ref: self.paths[ref['artifact_id']],
                      records=self.records, source_roots=self.roots)
        self.assertEqual(first, second.read_bytes())
        report = self.verify(built)
        self.assertTrue(report['closure_verified'])
        self.assertEqual(report['state'], 'incomplete')
        self.assertEqual(report['reconstruction'], 'blocked')
        self.assertEqual(report['archive_sha256'], sha(first))
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(set(archive.namelist()), RESERVED | {m['path'] for m in self.members})

    def test_actual_tiny_reconstruction_from_extracted_retained_bytes(self):
        built = self.build()
        original = self.paths[self.members[0]['artifact']['artifact_id']]
        original.unlink()  # Proves callback cannot accidentally read original resolver data.
        calls = []
        def reconstruct(context):
            self.assertNotEqual(context.input_root, original.parent)
            out = context.output_root / 'rebuilt.txt'
            retained = context.resolve(self.members[0]['artifact'])
            out.write_bytes(retained.read_bytes().upper())
            calls.append('assembly')
            return {self.members[4]['artifact']['artifact_id']: out}
        def inspect(context, outputs):
            return 'pass' if next(iter(outputs.values())).read_bytes().endswith(b'FIXTURE\n') else 'fail'
        report = self.verify(built, authorized=True, runtime_check=lambda requirements: True,
                             reconstruct=reconstruct, inspect=inspect)
        self.assertEqual(report['state'], 'verified', report)
        self.assertEqual(report['reconstruction'], 'pass')
        self.assertEqual(calls, ['assembly'])
        self.assertEqual(report['output_sha256'][self.members[4]['artifact']['artifact_id']], self.members[4]['artifact']['sha256'])

    def test_rights_metadata_does_not_block_reconstruction(self):
        for status in ('unknown', 'restricted', 'known'):
            with self.subTest(status=status):
                self.archive = self.archive.with_name(status + '.zip')
                declaration = self.records[self.members[0]['artifact']['artifact_id']]['provenance']['rights']
                declaration.update(status=status, license=None)
                expected = copy.deepcopy(declaration)
                built = self.build()
                self.assertNotIn('RIGHTS_UNRESOLVED', built['blockers'])
                self.assertEqual(declaration, expected)
                def reconstruct(context):
                    out = context.output_root / 'rebuilt.txt'
                    out.write_bytes(context.resolve(self.members[0]['artifact']).read_bytes().upper())
                    return {self.members[4]['artifact']['artifact_id']: out}
                result = self.verify(built, authorized=True, runtime_check=lambda _: True,
                    reconstruct=reconstruct, inspect=lambda context, outputs: 'pass')
                self.assertEqual(result['state'], 'verified', result)
                self.assertEqual(result['reconstruction'], 'pass')
                self.assertEqual(declaration, expected)
                denied = self.verify(built)
                self.assertEqual(denied['blockers'], ['RECONSTRUCTION_BLOCKED'])

    def test_missing_dependency_and_source_member_rejected(self):
        self.manifest['members'] = self.members[1:]
        with self.assertRaises(ContractError) as error:
            self.build()
        self.assertEqual(error.exception.code, 'PACKAGE_INCOMPLETE')
        self.assertFalse(self.archive.exists())

    def test_changed_input_does_not_publish_archive(self):
        self.paths[self.members[0]['artifact']['artifact_id']].write_bytes(b'changed')
        with self.assertRaises(ContractError) as error:
            self.build()
        self.assertEqual(error.exception.code, 'HASH_MISMATCH')
        self.assertFalse(self.archive.exists())

    def test_unsafe_paths_links_credentials_and_absolute_path_rejected(self):
        original = self.manifest['members'][0]['path']
        for path in ['../escape', '/absolute', 'C:/absolute', 'source\\escape', 'source/.env', 'source/cache/data']:
            with self.subTest(path=path):
                self.manifest['members'][0]['path'] = path
                with self.assertRaises(ContractError):
                    self.build()
        self.manifest['members'][0]['path'] = original
        victim = self.paths[self.members[0]['artifact']['artifact_id']]
        victim.unlink()
        victim.symlink_to(self.paths[self.members[1]['artifact']['artifact_id']])
        with self.assertRaises(ContractError):
            self.build()
        victim.unlink()
        for data in [b'api_key = "synthetic-secret-canary"', b'private /home/example/workspace/file']:
            victim.write_bytes(data)
            self.members[0]['artifact']['sha256'] = sha(data)
            self.records[self.members[0]['artifact']['artifact_id']]['sha256'] = sha(data)
            self.records[self.members[0]['artifact']['artifact_id']]['size_bytes'] = len(data)
            with self.assertRaises(ContractError) as error:
                self.build()
            self.assertEqual(error.exception.code, 'PACKAGE_UNSAFE')

    def test_binary_path_lookalikes_do_not_reject_package(self):
        # Compressed media can contain drive-colon-backslash followed by arbitrary
        # non-text bytes. That is not a textual private filesystem path.
        media=self.add('asset','media.bin',b'\x00V:\\\x91\x02\xffbinary\x00')
        self.members.append(media)
        built=self.build()
        self.assertTrue(self.verify(built)['closure_verified'])

    def test_binary_envelope_does_not_hide_textual_leaks(self):
        from studio.packaging import _scan
        for text in (b'C:\\Users\\example\\private.txt',b'/home/example/private.txt',
                     b'api_key="synthetic-secret-canary"'):
            with self.subTest(text=text):
                with self.assertRaises(ContractError):
                    _scan(b'\x00\xff'+text+b'\x00\xff')

    def test_archive_hash_and_unexpected_member_fail(self):
        built = self.build()
        with zipfile.ZipFile(self.archive, 'a') as archive:
            archive.writestr('../outside', b'bad')
        with self.assertRaises(ContractError) as error:
            self.verify(built)
        self.assertEqual(error.exception.code, 'HASH_MISMATCH')
        built['archive_sha256'] = sha(self.archive.read_bytes())
        with self.assertRaises(ContractError) as error:
            self.verify(built)
        self.assertEqual(error.exception.code, 'PACKAGE_UNSAFE')
        self.assertFalse((self.root / 'outside').exists())

    def test_failed_rebuild_and_review_needed_never_verified(self):
        built = self.build()
        def rebuild(context):
            path = context.output_root / 'wrong.txt'
            path.write_bytes(b'not equivalent')
            return {self.members[4]['artifact']['artifact_id']: path}
        result = self.verify(built, authorized=True, runtime_check=lambda _: True,
                             reconstruct=rebuild, inspect=lambda *_: 'pass')
        self.assertEqual(result['state'], 'failed')
        self.manifest['reproduction']['expected_equivalence'] = 'content_and_format'
        other = self.root / 'content.zip'
        self.archive = other
        built = self.build()
        result = self.verify(built, authorized=True, runtime_check=lambda _: True,
                             reconstruct=rebuild, inspect=lambda *_: 'review_needed')
        self.assertEqual(result['state'], 'incomplete')
        self.assertEqual(result['reconstruction'], 'review_needed')

    def test_authority_and_missing_runtime_never_execute(self):
        built = self.build()
        def never(*args):
            self.fail('No reconstruction authorized/available')
        report = self.verify(built, runtime_check=never, reconstruct=never, inspect=never)
        self.assertEqual(report['blockers'], ['RECONSTRUCTION_BLOCKED'])
        report = self.verify(built, authorized=True, runtime_check=lambda _: False,
                             reconstruct=never, inspect=never)
        self.assertEqual(report['blockers'], ['DEPENDENCY_UNAVAILABLE'])

    def test_duplicate_and_symlink_archive_members_are_rejected(self):
        built = self.build()
        for name, mode in [('master.txt', 0o100600), ('link.txt', 0o120777)]:
            changed = self.root / ('malicious-' + name + '.zip')
            changed.write_bytes(self.archive.read_bytes())
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = mode << 16
            with zipfile.ZipFile(changed, 'a') as archive:
                archive.writestr(entry, b'untrusted')
            with self.assertRaises(ContractError) as error:
                validate_package(changed, expected_archive_sha256=sha(changed.read_bytes()), scratch_root=self.root)
            self.assertEqual(error.exception.code, 'PACKAGE_UNSAFE')

    def test_output_escape_and_mutated_inputs_never_verified(self):
        built = self.build()
        def escaped(context):
            return {self.members[4]['artifact']['artifact_id']: context.input_root / 'master.txt'}
        report = self.verify(built, authorized=True, runtime_check=lambda _: True,
                             reconstruct=escaped, inspect=lambda *_: 'pass')
        self.assertEqual(report['state'], 'failed')
        def mutation(context):
            context.resolve(self.members[0]['artifact']).write_bytes(b'mutated')
            output = context.output_root / 'master.txt'
            output.write_bytes(b'RETAINED GENERATED FIXTURE\n')
            return {self.members[4]['artifact']['artifact_id']: output}
        report = self.verify(built, authorized=True, runtime_check=lambda _: True,
                             reconstruct=mutation, inspect=lambda *_: 'pass')
        self.assertEqual(report['blockers'], ['HASH_MISMATCH'])
        self.assertFalse(any(p.name.startswith('motion-package-') for p in self.root.iterdir()))

    def test_existing_archive_never_overwritten_and_metadata_private_paths_removed(self):
        record = self.records[self.members[0]['artifact']['artifact_id']]
        record['provenance']['source_locator'] = '/home/fixture/private-input.bin'
        built = self.build()
        with zipfile.ZipFile(self.archive) as archive:
            self.assertNotIn(b'/home/fixture', archive.read('closure.json'))
        original = self.archive.read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(original, self.archive.read_bytes())
        self.assertEqual(built['state'], 'incomplete')

    def test_schema_closed_and_no_shared_definition_mutation(self):
        from studio.contracts import D
        before = copy.deepcopy(D)
        self.assertFalse(schema_document('PackageRecord')['additionalProperties'])
        schema_root = Path(__file__).resolve().parents[1] / 'schemas'
        for name, filename in [('PackageRecord', 'package.json'),
                               ('PackageManifest', 'package-manifest.json'),
                               ('PackageClosure', 'package-closure.json')]:
            self.assertEqual(schema_document(name), json.loads((schema_root / filename).read_text()))
        with self.assertRaises(ContractError):
            validate_package_record({'schema': 'motion/v1/package', 'extra': True}, 'PackageRecord')
        self.assertEqual(before, D)


if __name__ == '__main__':
    unittest.main()
