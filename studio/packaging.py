"""B17 exact source closure archives; no discovery, installation or generation.

This module is a delivery-adapter primitive, not a job/authority implementation.
Callers supply immutable artifact records, an explicit resolver and source-bundle
root handles. Verification is independent extraction plus an explicitly authorized
trusted reconstruction adapter and inspector. Hash closure alone is never verified
reproduction. Import has no filesystem or shared-contract mutation effects.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import NoReturn
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import uuid
import zipfile

from .contracts import (D, DIGEST, STAMP, TEXT, ContractError, arr, canonical,
                        enum, ident, integer, nullable, obj, ref, string, validate)
from .assets import (_local_file, _hash, _read_bundle, _bundle_members,
                     validate_asset, schema_document as asset_schema_document,
                     DEFS as ASSET_DEFS)
from .project import ManagedFS

DEFS = copy.deepcopy(D)
DEFS['Provenance'] = copy.deepcopy(ASSET_DEFS['Provenance'])
DEFS['PackageMember'] = obj({'path': string(minimum=1), 'artifact': ref('ArtifactRef'),
    'role': enum('master', 'sidecar', 'source', 'asset', 'font', 'provenance', 'instructions')})
DEFS['PackageManifest'] = obj({'schema': {'const': 'motion/v1/package-manifest'},
    'members': arr(ref('PackageMember'), 1),
    'runtime_requirements': arr(ref('RuntimeIdentity')),
    'reproduction': obj({'assembly_plan': ref('ArtifactRef'), 'generation_boundary': TEXT,
                         'expected_equivalence': enum('bytes', 'content_and_format')}),
    'exclusions': arr(obj({'reason': TEXT, 'artifact_id': ident('art')}))})
DEFS['PackageRecord'] = obj({'schema': {'const': 'motion/v1/package'},
    'package_id': ident('pkg'), 'revision': integer(1), 'project_id': ident('prj'),
    'state': enum('draft', 'verified', 'incomplete', 'failed'), 'masters': arr(ident('mst')),
    'archive': nullable(ref('ArtifactRef')), 'manifest': ref('ArtifactRef'),
    'verification_receipts': arr(ref('ArtifactRef')), 'blockers': arr(TEXT), 'created_at': STAMP})
DEFS['PackageClosure'] = obj({'schema': {'const': 'motion/v1/package-closure'},
    'project_id': ident('prj'), 'source_roots': arr(ref('ArtifactRef'), 1),
    'artifacts': arr(obj({'artifact': ref('ArtifactRef'), 'size_bytes': integer(),
        'media_type': TEXT, 'inputs': arr(ref('ArtifactRef')), 'provenance': ref('Provenance')}), 1)})
SCHEMA_MEMBERS = {'schemas/package-manifest.json', 'schemas/package-closure.json',
                  'schemas/source-bundle.json'}
RESERVED = {'manifest.json', 'closure.json'} | SCHEMA_MEMBERS
MAX_METADATA = 4 * 1024 * 1024
DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024
# Bounded leak guard over the explicitly selected closure, not a workspace scanner.
LEAK = re.compile(rb'''(?ix)
    -----BEGIN[ ](?:RSA[ ]|EC[ ]|OPENSSH[ ])?PRIVATE[ ]KEY----- |
    (?:api[_-]?key|access[_-]?token|auth[_-]?token|password|client[_-]?secret)
        [\"']?\s*[:=]\s*[\"']?[^\s\"',;}]{6,} |
    authorization[\"']?\s*[:=]\s*[\"']?(?:bearer|basic)\s+\S+ |
    (?:sk-[a-zA-Z0-9_-]{20,}|gh[pousr]_[a-zA-Z0-9_]{20,}) |
    https?://[^\s/]+:[^\s/]+@ |
    /(?:home|Users|root)/[^\s\"']+ | [A-Za-z]:\\[^\s\"']+
''')


def schema_document(name):
    """Return a closed standalone schema without extending contracts.D."""
    if name not in ('PackageRecord', 'PackageManifest', 'PackageClosure'):
        raise ValueError('Unknown package schema')
    definitions = {}
    def visit(value):
        if isinstance(value, dict):
            if '$ref' in value:
                target = value['$ref'].rsplit('/', 1)[-1]
                if target not in definitions:
                    definitions[target] = copy.deepcopy(DEFS[target])
                    visit(definitions[target])
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(DEFS[name])
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'motion/v1/' + name, **copy.deepcopy(DEFS[name]), '$defs': definitions}


def _schema_snapshots():
    return {'schemas/package-manifest.json': canonical(schema_document('PackageManifest')),
            'schemas/package-closure.json': canonical(schema_document('PackageClosure')),
            'schemas/source-bundle.json': canonical(asset_schema_document('SourceBundle'))}


def validate_package_record(value, name='PackageRecord'):
    def expand(schema):
        if isinstance(schema, dict):
            if '$ref' in schema:
                return expand(DEFS[schema['$ref'].rsplit('/', 1)[-1]])
            return {k: expand(v) for k, v in schema.items()}
        if isinstance(schema, list):
            return [expand(v) for v in schema]
        return schema
    validate(value, expand(DEFS[name]))


def _unsafe(message='Package contains unsafe member data.') -> NoReturn:
    raise ContractError('PACKAGE_UNSAFE', message)


@contextmanager
def _file(path):
    try:
        with _local_file(path) as stream:
            yield stream
    except OSError:
        _unsafe('Package requires an accessible regular file without symbolic links.')


def _path(value):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or '\\' in value or ':' in value or '\x00' in value
            or value.startswith('/') or any(ord(c) < 32 for c in value)
            or any(p in ('', '.', '..') for p in value.split('/'))):
        _unsafe('Package paths must be canonical relative POSIX paths.')
    forbidden = {'.git', '__pycache__', '.cache', 'cache', 'caches', 'credentials',
                 '.ssh', '.aws', '.gnupg', 'node_modules'}
    if any(p.casefold() in forbidden or p.casefold().startswith('.env')
           or p.casefold() in ('credentials.json', 'secrets.json', 'id_rsa', 'id_ed25519')
           for p in value.split('/')):
        _unsafe('Caches and credential paths are not deliverable sources.')
    return value


def _paths(values):
    names = [_path(p) for p in values]
    folded = {p.casefold() for p in names}
    if len(folded) != len(names):
        _unsafe('Archive members collide.')
    for name in folded:
        if any('/'.join(name.split('/')[:i]) in folded for i in range(1, len(name.split('/')))):
            _unsafe('Archive members overlap directories.')
    return names


def _scan(data):
    for match in LEAK.finditer(data):
        candidate = match.group()
        if len(candidate) >= 3 and candidate[1:3] == bytes((58, 92)):
            # A binary codec may emit drive-colon-backslash by chance. Require
            # an actual printable path, but still catch NUL-terminated metadata.
            try:
                path = candidate.split(b'\x00', 1)[0].decode('utf-8')
            except UnicodeDecodeError:
                continue
            if len(path) <= 3 or not path.isprintable():
                continue
        _unsafe('Credential-like data or private absolute paths cannot be packaged.')


def _json(raw):
    if len(raw) > MAX_METADATA:
        raise ContractError('LIMIT_EXCEEDED', 'Package metadata exceeds the bound.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _unsafe('Duplicate metadata keys are forbidden.')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: _unsafe())
    except (ValueError, UnicodeError):
        _unsafe('Package metadata is not strict JSON.')


def _stream(source, target=None, *, limit=DEFAULT_MAX_BYTES):
    sha, size, tail = hashlib.sha256(), 0, b''
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise ContractError('LIMIT_EXCEEDED', 'Package exceeds the byte bound.')
        _scan(tail + chunk)
        tail = chunk[-4096:]
        sha.update(chunk)
        if target is not None:
            target.write(chunk)
    return 'sha256:' + sha.hexdigest(), size


def _ref_key(value):
    return value['artifact_id'], value['sha256']


def _closure_check(manifest, closure):
    validate_package_record(manifest, 'PackageManifest')
    validate_package_record(closure, 'PackageClosure')
    _scan(canonical(manifest))
    _scan(canonical(closure))
    _paths([*RESERVED, *(m['path'] for m in manifest['members'])])
    by_id = {}
    for member in manifest['members']:
        aid = member['artifact']['artifact_id']
        if aid in by_id:
            _unsafe('An artifact must have exactly one package location.')
        by_id[aid] = member
    metadata = {a['artifact']['artifact_id']: a for a in closure['artifacts']}
    if len(metadata) != len(closure['artifacts']) or set(metadata) != set(by_id):
        _unsafe('Closure metadata must describe exactly the included artifacts.')
    def resolve(pin):
        member = by_id.get(pin['artifact_id'])
        if member is None or member['artifact'] != pin:
            raise ContractError('PACKAGE_INCOMPLETE', 'An exact required dependency is missing.')
        return member
    blockers = set()
    for item in closure['artifacts']:
        resolve(item['artifact'])
        for pin in item['inputs'] + item['provenance']['rights']['evidence']:
            resolve(pin)
        # Preserve declarations without making licenses a reconstruction prerequisite.
    resolve(manifest['reproduction']['assembly_plan'])
    if not any(m['role'] == 'master' for m in manifest['members']):
        raise ContractError('PACKAGE_INCOMPLETE', 'Requested final output pins are required.')
    if not any(m['role'] == 'instructions' for m in manifest['members']):
        raise ContractError('PACKAGE_INCOMPLETE', 'Portable reproduction instructions are required.')
    for root in closure['source_roots']:
        if resolve(root)['role'] != 'source':
            _unsafe('Source roots must identify included source manifests.')
    if len({_ref_key(r) for r in closure['source_roots']}) != len(closure['source_roots']):
        _unsafe('Source roots must be unique.')
    for runtime in manifest['runtime_requirements']:
        _path(runtime['entry_member'])
        for dependency in runtime['dependencies']:
            resolve(dependency)
        if not runtime['engine_version'] or not runtime['implementation_version']:
            blockers.add('BINDING_CHANGED')
    if not manifest['runtime_requirements']:
        blockers.add('DEPENDENCY_UNAVAILABLE')
    if not manifest['reproduction']['generation_boundary']:
        blockers.add('PACKAGE_INCOMPLETE')
    excluded = [entry['artifact_id'] for entry in manifest['exclusions']]
    if len(excluded) != len(set(excluded)) or any(aid in by_id for aid in excluded):
        _unsafe('Exclusions cannot contradict included dependencies.')
    # Reject dependency cycles, rather than hiding an impossible reconstruction order.
    visiting, seen = set(), set()
    def walk(aid):
        if aid in visiting:
            raise ContractError('PACKAGE_INCOMPLETE', 'Artifact dependencies contain a cycle.')
        if aid in seen:
            return
        visiting.add(aid)
        for dep in metadata[aid]['inputs']:
            walk(dep['artifact_id'])
        visiting.remove(aid)
        seen.add(aid)
    for aid in metadata:
        walk(aid)
    return by_id, metadata, sorted(blockers)


def _bundles(manifest, closure, by_id, metadata, locate):
    entries = {}
    for pin in closure['source_roots']:
        member = by_id[pin['artifact_id']]
        location = Path(locate(pin))
        with _file(str(location)) as stream:
            bundle = _read_bundle(stream, location.name)
        parent = PurePosixPath(member['path']).parent
        entries[_ref_key(pin)] = bundle['entry_member']
        for item in bundle['members']:
            target = str(parent / item['relative_path'])
            match = next((m for m in manifest['members'] if m['path'] == target), None)
            if match is None:
                raise ContractError('PACKAGE_INCOMPLETE', 'A declared source member is missing.')
            record = metadata[match['artifact']['artifact_id']]
            if (item['sha256'], item['size_bytes'], item['media_type']) != (
                    match['artifact']['sha256'], record['size_bytes'], record['media_type']):
                raise ContractError('HASH_MISMATCH', 'Source member pins disagree with the closure.')
        with _bundle_members(bundle, location.parent):
            pass
    for runtime in manifest['runtime_requirements']:
        if not any(entries.get(_ref_key(pin)) == runtime['entry_member']
                   for pin in runtime['dependencies']):
            raise ContractError('PACKAGE_INCOMPLETE', 'Selected runtime must pin its matching source root dependency.')


def _entry(name):
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | 0o600) << 16
    entry.compress_type = zipfile.ZIP_STORED
    return entry


def build_package(manifest, archive_path, *, resolver, records, source_roots,
                  max_bytes=DEFAULT_MAX_BYTES):
    """Write one new deterministic ZIP from an explicit exact dependency closure.

    records maps artifact IDs to ArtifactRecords; resolver(ArtifactRef) returns a
    canonical absolute regular-file path. No workspace walk, implicit inclusion,
    generation, publication, jobs or PackageRecord commit occurs here. Existing
    destinations are never overwritten. Source member paths are relative to their
    declared bundle manifest, both on disk and inside the archive.
    """
    manifest = copy.deepcopy(manifest)
    validate_package_record(manifest, 'PackageManifest')
    artifacts, project_ids = [], set()
    for member in manifest['members']:
        record = records.get(member['artifact']['artifact_id'])
        if record is None:
            raise ContractError('PACKAGE_INCOMPLETE', 'Artifact metadata is missing.')
        validate_asset(record, 'ArtifactRecord')
        if (record['artifact_id'], record['sha256']) != _ref_key(member['artifact']):
            raise ContractError('HASH_MISMATCH', 'Artifact record does not match its pin.')
        project_ids.add(record['project_id'])
        provenance = copy.deepcopy(record['provenance'])
        # Original storage paths are deliberately not portable package metadata.
        # A source locator with userinfo/secrets is still refused, not laundered.
        locator = provenance['source_locator']
        if locator and not locator.startswith('/'):
            _scan(locator.encode('utf-8'))
        if locator and (locator.startswith('/') or re.match(r'^[A-Za-z]:', locator)):
            provenance['source_locator'] = None
        artifacts.append({'artifact': copy.deepcopy(member['artifact']),
            'size_bytes': record['size_bytes'], 'media_type': record['media_type'],
            'inputs': copy.deepcopy(record['inputs']), 'provenance': provenance})
    if len(project_ids) != 1:
        raise ContractError('WRONG_PROJECT', 'Package artifacts must belong to one project.')
    closure = {'schema': 'motion/v1/package-closure', 'project_id': next(iter(project_ids)),
               'source_roots': copy.deepcopy(source_roots),
               'artifacts': sorted(artifacts, key=lambda a: a['artifact']['artifact_id'])}
    manifest['members'].sort(key=lambda m: m['path'])
    by_id, metadata, blockers = _closure_check(manifest, closure)
    if sum(a['size_bytes'] for a in artifacts) > max_bytes:
        raise ContractError('LIMIT_EXCEEDED', 'Package exceeds the total byte bound.')
    # Snapshot every exact pin to task-owned staging before archiving, preventing
    # source changes or resolver races from publishing mixed old/new bytes.
    destination = Path(archive_path)
    if not destination.is_absolute():
        _unsafe('Archive destination must be explicitly absolute.')
    fs = ManagedFS(destination.parent)
    with fs.directory() as directory:
        temp_name = '.package-' + uuid.uuid4().hex
        fd = os.open(temp_name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'w+b') as target:
                with zipfile.ZipFile(target, 'w', allowZip64=True) as archive:
                    archive.writestr(_entry('manifest.json'), canonical(manifest))
                    archive.writestr(_entry('closure.json'), canonical(closure))
                    for name, data in sorted(_schema_snapshots().items()):
                        archive.writestr(_entry(name), data)
                    for member in manifest['members']:
                        expected = metadata[member['artifact']['artifact_id']]
                        with _file(str(resolver(member['artifact']))) as source:
                            with archive.open(_entry(member['path']), 'w', force_zip64=True) as output:
                                actual = _stream(source, output, limit=max_bytes)
                        if actual != (member['artifact']['sha256'], expected['size_bytes']):
                            raise ContractError('HASH_MISMATCH', 'Package input bytes changed.')
                target.flush()
                os.fsync(target.fileno())
                target.seek(0)
                archive_sha, archive_size, _ = _hash(target)
            # Reopen the staged archive and verify source bundle closure from its
            # copied bytes, independent of the caller's potentially mutable paths.
            staged = destination.parent / temp_name
            report = validate_package(staged, expected_archive_sha256=archive_sha,
                                      scratch_root=destination.parent, max_bytes=max_bytes)
            if not report['closure_verified']:
                raise ContractError('PACKAGE_INCOMPLETE', 'Source closure could not be validated.')
            # Link is exclusive/atomic and descriptor-relative; never replace.
            os.link(temp_name, destination.name, src_dir_fd=directory,
                    dst_dir_fd=directory, follow_symlinks=False)
            os.fsync(directory)
        finally:
            os.unlink(temp_name, dir_fd=directory)
    return {'state': 'incomplete', 'archive_sha256': archive_sha, 'size_bytes': archive_size,
            'manifest_sha256': 'sha256:' + hashlib.sha256(canonical(manifest)).hexdigest(),
            'closure_verified': True, 'reconstruction': 'not_run',
            'blockers': sorted(set(blockers + ['RECONSTRUCTION_BLOCKED']))}


@dataclass(frozen=True)
class ReconstructionContext:
    """Only extracted files are exposed; no original resolver/provider credentials."""
    input_root: Path
    output_root: Path
    manifest: dict
    closure: dict

    def resolve(self, pin):
        for member in self.manifest['members']:
            if member['artifact'] == pin:
                return self.input_root / member['path']
        raise ContractError('PACKAGE_INCOMPLETE', 'Reconstruction requested an unpinned input.')


def validate_package(archive_path, *, expected_archive_sha256, scratch_root,
                     authorized=False, runtime_check=None, reconstruct=None, inspect=None,
                     on_verified=None, expected_manifest_sha256=None, max_bytes=DEFAULT_MAX_BYTES):
    """Rehash/extract the exact archive, then optionally reconstruct and inspect.

    All callbacks are trusted adapter code supplied by the delivery job owner,
    never executable content loaded from an archive. runtime_check(requirements)
    must observe selected installed runtime identities and return literal True.
    reconstruct(context) returns {expected_master_artifact_id: output_path}.
    inspect(context, outputs) probes/inspects exact rebuilt media and returns
    pass/fail/review_needed under the declared bytes/content_and_format policy.
    It is not permissible to pass an always-True fixture checker for production.
    Missing callbacks/authority remain incomplete; no automatic tool fallback.
    Scratch extraction is removed on return; persist the returned report as a
    receipt in the caller's normal artifact store, not the temporary file paths.
    """
    validate(expected_archive_sha256, DIGEST)
    scratch = Path(scratch_root)
    with ManagedFS(scratch).directory():
        pass
    with _file(str(archive_path)) as source:
        archive_sha, _, _ = _hash(source)
        if archive_sha != expected_archive_sha256:
            raise ContractError('HASH_MISMATCH', 'Archive bytes do not match the pinned archive.')
        source.seek(0)
        def finish(report):
            source.seek(0)
            final_hash, _, _ = _hash(source)
            if final_hash != expected_archive_sha256:
                raise ContractError('HASH_MISMATCH', 'Archive changed during validation.')
            return report
        with tempfile.TemporaryDirectory(prefix='motion-package-', dir=scratch) as temp:
            root = Path(temp)
            inputs, outputs = root / 'inputs', root / 'outputs'
            inputs.mkdir(mode=0o700)
            outputs.mkdir(mode=0o700)
            try:
                archive = zipfile.ZipFile(source)
            except zipfile.BadZipFile:
                _unsafe('Package is not a readable ZIP archive.')
            with archive:
                infos = archive.infolist()
                if len(infos) > 1000 + len(RESERVED):
                    raise ContractError('LIMIT_EXCEEDED', 'Package member count exceeds the bound.')
                _paths([i.filename for i in infos])
                for info in infos:
                    mode = info.external_attr >> 16
                    if (info.is_dir() or info.flag_bits & 1 or info.compress_type != zipfile.ZIP_STORED
                            or stat.S_IFMT(mode) != stat.S_IFREG):
                        _unsafe('Only unencrypted stored regular files are allowed.')
                indexed = {i.filename: i for i in infos}
                if not RESERVED <= indexed.keys():
                    _unsafe('Package metadata is missing.')
                if any(indexed[n].file_size > MAX_METADATA for n in RESERVED):
                    raise ContractError('LIMIT_EXCEEDED', 'Package metadata exceeds the bound.')
                manifest = _json(archive.read('manifest.json'))
                closure = _json(archive.read('closure.json'))
                for name, data in _schema_snapshots().items():
                    if archive.read(name) != data:
                        raise ContractError('SCHEMA_UNSUPPORTED', 'Package schema snapshot is unsupported.')
                by_id, metadata, blockers = _closure_check(manifest, closure)
                if expected_manifest_sha256 is not None:
                    validate(expected_manifest_sha256, DIGEST)
                    actual_manifest = 'sha256:' + hashlib.sha256(canonical(manifest)).hexdigest()
                    if actual_manifest != expected_manifest_sha256:
                        raise ContractError('HASH_MISMATCH', 'Package manifest differs from selected report.')
                if sum(a['size_bytes'] for a in metadata.values()) > max_bytes:
                    raise ContractError('LIMIT_EXCEEDED', 'Package exceeds the content byte bound.')
                wanted = RESERVED | {m['path'] for m in manifest['members']}
                if wanted != indexed.keys():
                    _unsafe('Archive contains undeclared or missing members.')
                total = sum(info.file_size for info in infos)
                if total > max_bytes + len(RESERVED) * MAX_METADATA:
                    raise ContractError('LIMIT_EXCEEDED', 'Package exceeds the total byte bound.')
                for member in manifest['members']:
                    name, pin = member['path'], member['artifact']
                    expected = metadata[pin['artifact_id']]
                    if indexed[name].file_size != expected['size_bytes']:
                        raise ContractError('HASH_MISMATCH', 'Archive member size is incorrect.')
                    path = inputs / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as entry, path.open('xb') as output:
                        actual = _stream(entry, output, limit=max_bytes)
                    if actual != (pin['sha256'], expected['size_bytes']):
                        raise ContractError('HASH_MISMATCH', 'Archive member bytes do not match their pin.')
            context = ReconstructionContext(inputs, outputs, manifest, closure)
            _bundles(manifest, closure, by_id, metadata, context.resolve)
            frozen_metadata = canonical([manifest, closure])
            report = {'state': 'incomplete', 'archive_sha256': archive_sha,
                'manifest_sha256': 'sha256:' + hashlib.sha256(canonical(manifest)).hexdigest(),
                'closure_verified': True, 'reconstruction': 'blocked', 'output_sha256': {},
                'blockers': blockers}
            if blockers:
                return finish(report)
            if (authorized is not True or runtime_check is None or reconstruct is None or inspect is None):
                report['blockers'] = ['RECONSTRUCTION_BLOCKED']
                return finish(report)
            try:
                if runtime_check(copy.deepcopy(manifest['runtime_requirements'])) is not True:
                    report['blockers'] = ['DEPENDENCY_UNAVAILABLE']
                    return finish(report)
                rebuilt = reconstruct(context)
                expected_outputs = {m['artifact']['artifact_id']: m['artifact']
                                    for m in manifest['members'] if m['role'] == 'master'}
                if not isinstance(rebuilt, dict) or rebuilt.keys() != expected_outputs.keys():
                    raise ContractError('OUTPUT_INVALID', 'Reconstruction must return every exact requested output.')
                for aid, path in rebuilt.items():
                    path = Path(path)
                    if not path.is_absolute() or not path.is_relative_to(outputs):
                        _unsafe('Reconstructed outputs must remain in task-owned output storage.')
                    with _file(str(path)) as stream:
                        actual, _, _ = _hash(stream)
                    report['output_sha256'][aid] = actual
                    if manifest['reproduction']['expected_equivalence'] == 'bytes' and actual != expected_outputs[aid]['sha256']:
                        raise ContractError('HASH_MISMATCH', 'Reconstructed output is not byte-equivalent.')
                verdict = inspect(context, rebuilt)
                if canonical([manifest, closure]) != frozen_metadata:
                    raise ContractError('HASH_MISMATCH', 'Reconstruction changed pinned metadata.')
                if verdict not in ('pass', 'fail', 'review_needed'):
                    raise ContractError('OUTPUT_INVALID', 'Inspector must supply an explicit equivalence verdict.')
                # A callback cannot silently mutate its pinned inputs after closure verification.
                for member in manifest['members']:
                    with _file(str(context.resolve(member['artifact']))) as stream:
                        actual, _, _ = _hash(stream)
                    if actual != member['artifact']['sha256']:
                        raise ContractError('HASH_MISMATCH', 'Reconstruction altered a pinned input.')
                # Inspector must observe the same bytes subsequently reported.
                for aid, path in rebuilt.items():
                    with _file(str(path)) as stream:
                        actual, _, _ = _hash(stream)
                    if actual != report['output_sha256'][aid]:
                        raise ContractError('HASH_MISMATCH', 'Inspected output changed during inspection.')
                report['reconstruction'] = verdict
                report['state'] = {'pass': 'verified', 'fail': 'failed', 'review_needed': 'incomplete'}[verdict]
                report['blockers'] = [] if verdict == 'pass' else ['GATE_REVIEW_NEEDED' if verdict == 'review_needed' else 'GATE_FAILED']
                if verdict == 'pass' and on_verified is not None:
                    on_verified(context, rebuilt, report)
                    if canonical([manifest, closure]) != frozen_metadata:
                        raise ContractError('HASH_MISMATCH', 'Retention changed pinned metadata.')
                    for member in manifest['members']:
                        with _file(str(context.resolve(member['artifact']))) as stream:
                            actual, _, _ = _hash(stream)
                        if actual != member['artifact']['sha256']:
                            raise ContractError('HASH_MISMATCH', 'Retention altered a pinned input.')
                    for aid, path in rebuilt.items():
                        with _file(str(path)) as stream:
                            actual, _, _ = _hash(stream)
                        if actual != report['output_sha256'][aid]:
                            raise ContractError('HASH_MISMATCH', 'Retention altered an inspected output.')
            except Exception as error:
                # Never dump arbitrary adapter exceptions/paths/secrets in a public receipt.
                report.update(state='failed', reconstruction='fail',
                              blockers=[error.code if isinstance(error, ContractError) else 'PROCESS_FAILURE'])
            return finish(report)
