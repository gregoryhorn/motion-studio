"""B04 local byte staging and committed asset registry; no probe execution.

AssetStore is a separable ProjectStore extension. Asset transactions publish
through the same project pointer/lock and keep their records in that immutable
transaction closure. Parent integration must let ProjectStore._transaction read
these descriptors too (see docs/b04-evidence.md). Importing this module has no
filesystem, subprocess, provider, or shared-schema mutation effects.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import copy
import functools
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from .contracts import (D, MAX_INT, UUID_PATTERN, TEXT, LABEL, STAMP, DIGEST,
                        ADAPTER, ContractError, arr, obj, enum, ident, integer,
                        nullable, ref, string, validate, digest, safe_relative)
from .project import ProjectStore, ManagedFS, _fs_error, _id, _now

LOG = logging.getLogger(__name__)
KINDS = ('media', 'image', 'audio', 'frame', 'caption', 'caption_style',
         'scene_source', 'assembly_source', 'json', 'report', 'archive', 'font')
LOCAL_SOURCE = obj({'kind': {'const': 'local'}, 'path': string(minimum=1)})
DEFS = copy.deepcopy(D)
DEFS['SourceLocator'] = {'oneOf': [LOCAL_SOURCE, obj({'kind': {'const': 'remote'}, 'url': TEXT})]}
DEFS['Provenance'] = obj({
    'origin': enum('user_import', 'authored', 'stock', 'generated', 'derived'),
    'acquired_at': STAMP, 'source_locator': nullable(TEXT),
    'provider': nullable(TEXT), 'model': nullable(TEXT), 'model_version': nullable(TEXT),
    'seed': nullable(integer(-MAX_INT)), 'deterministic': enum('yes', 'no', 'unknown'),
    'rights': obj({'status': enum('known', 'unknown', 'restricted'),
                   'license': nullable(TEXT), 'attribution': nullable(TEXT),
                   'evidence': arr(ref('ArtifactRef'))}), 'notes': TEXT})
DEFS['SourceBundle'] = obj({'schema': {'const': 'motion/v1/source-bundle'},
    'entry_member': string(minimum=1),
    'members': arr(obj({'relative_path': string(minimum=1), 'sha256': DIGEST,
                         'size_bytes': integer(), 'media_type': TEXT}), minimum=1)})
DEFS['ArtifactRecord'] = obj({
    'schema': {'const': 'motion/v1/artifact'}, 'artifact_id': ident('art'),
    'project_id': ident('prj'), 'kind': enum(*KINDS), 'media_type': TEXT,
    'sha256': DIGEST, 'size_bytes': integer(),
    'storage': {'oneOf': [obj({'mode': {'const': 'managed'}, 'relative_path': string(minimum=1)}),
                          obj({'mode': {'const': 'external'}, 'source': LOCAL_SOURCE})]},
    'created_at': STAMP,
    'producer': obj({'job_id': nullable(ident('job')), 'node_id': nullable(ident('nod')),
                     'attempt_id': nullable(ident('att')), 'adapter_id': nullable(ADAPTER)}),
    'inputs': arr(ref('ArtifactRef')), 'provenance': ref('Provenance'),
    'probe_receipt_id': nullable(ident('rcp'))})
DEFS['AssetRecord'] = obj({
    'schema': {'const': 'motion/v1/asset'}, 'asset_id': ident('ast'),
    'project_id': ident('prj'), 'label': LABEL, 'mode': enum('copy', 'reference'),
    'source_locator': ref('SourceLocator'), 'artifact': ref('ArtifactRef'),
    'source_fingerprint': obj({'sha256': DIGEST, 'size_bytes': integer(), 'observed_at': STAMP}),
    'provenance': ref('Provenance'), 'created_at': STAMP})
DEFS['AssetSummary'] = obj({'asset_id': ident('ast'), 'label': LABEL,
    'artifact': ref('ArtifactRef'), 'mode': enum('copy', 'reference'),
    'rights_status': enum('known', 'unknown', 'restricted'), 'created_at': STAMP})
DEFS['AssetMutationResult'] = obj({'asset': ref('AssetRecord'), 'project_revision': integer(1)})
DEFS['AssetTransaction'] = obj({
    'schema': {'const': 'motion/v1/asset-transaction'}, 'tool': {'const': 'motion_asset'},
    'action': enum('import', 'reference'), 'request_id': string(UUID_PATTERN),
    'request_sha256': DIGEST, 'previous': ref('ProjectRecord'),
    'pointer': ref('ProjectRecord'), 'asset': ref('AssetRecord'),
    'artifact': ref('ArtifactRecord'), 'result': ref('AssetMutationResult')})
common = {'project_id': ident('prj')}
mutation = {**common, 'expected_revision': integer(1), 'request_id': string(UUID_PATTERN),
            'source': LOCAL_SOURCE, 'label': LABEL, 'provenance': ref('Provenance'), 'kind': enum(*KINDS)}
page = {'limit': integer(1, 100), 'cursor': TEXT, 'snapshot_id': ident('snp')}
DEFS['AssetRequest'] = {'oneOf': [
    obj({'action': enum('import', 'reference'), **mutation}),
    obj({'action': {'const': 'list'}, **common, **page, 'kind': enum(*KINDS),
         'rights_status': enum('known', 'unknown', 'restricted')}, optional=[*page, 'kind', 'rights_status']),
    obj({'action': {'const': 'get'}, **common, 'asset_id': ident('ast')}),
    obj({'action': {'const': 'probe'}, **common, 'expected_revision': integer(1),
         'request_id': string(UUID_PATTERN), 'authority_ref': TEXT,
         'artifact': ref('ArtifactRef'), 'adapter_id': ADAPTER, 'full_decode': {'type': 'boolean'}},
        optional=['authority_ref', 'full_decode'])]}


@functools.lru_cache(None)
def _expanded(name):
    def expand(schema):
        if isinstance(schema, dict):
            if '$ref' in schema:
                return expand(DEFS[schema['$ref'].rsplit('/', 1)[-1]])
            return {k: expand(v) for k, v in schema.items()}
        if isinstance(schema, list):
            return [expand(v) for v in schema]
        return schema
    return expand(DEFS[name])


def validate_asset(value, name):
    validate(value, _expanded(name))


def schema_document(name):
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


def asset_tool_schema():
    return {'name': 'motion_asset',
            'description': 'Import/reference exact local file bytes, list/get assets. Probe execution is blocked pending B06/B07.',
            'parameters': schema_document('AssetRequest')}


def _absolute(path):
    if (not path.startswith('/') or '\\' in path or '\x00' in path
            or any(p in ('', '.', '..') for p in path.split('/')[1:])):
        raise ContractError('PATH_UNSAFE', 'Source must be a canonical absolute local regular-file path.')
    return Path(path)


@contextmanager
def _local_file(path):
    path = _absolute(path)
    fs = ManagedFS(path.parent)
    with fs.directory() as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ContractError('PATH_UNSAFE', 'Source must be a regular file.')
            yield stream


def _identity(stream):
    st = os.fstat(stream.fileno())
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _hash(stream, output=None):
    before = _identity(stream)
    if before[2] > MAX_INT:
        raise ContractError('LIMIT_EXCEEDED', 'Source size exceeds interoperable integer bound.')
    sha, size = hashlib.sha256(), 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_INT:
            raise ContractError('LIMIT_EXCEEDED', 'Source exceeds size bound.')
        sha.update(chunk)
        if output is not None:
            output.write(chunk)
    if _identity(stream) != before or size != before[2]:
        raise ContractError('ASSET_CHANGED', 'Source changed while being read.')
    return 'sha256:' + sha.hexdigest(), size, before


def _read_bundle(stream, manifest_name):
    """Parse the closed local representation, never import or execute members."""
    stream.seek(0)
    raw = stream.read(1024 * 1024 + 1)
    stream.seek(0)
    if len(raw) > 1024 * 1024:
        raise ContractError('LIMIT_EXCEEDED', 'Source manifest exceeds 1 MiB.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    try:
        bundle = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise ContractError('INVALID_ARGUMENT', 'Source manifest must be strict JSON.') from None
    validate_asset(bundle, 'SourceBundle')
    paths = [safe_relative(m['relative_path']) for m in bundle['members']]
    entry = safe_relative(bundle['entry_member'])
    if len(set(paths)) != len(paths) or manifest_name in paths or entry not in paths:
        raise ContractError('INVALID_ARGUMENT', 'Bundle needs unique non-self members and a declared entry.')
    # A regular file cannot also be a parent directory of another member.
    if any('/'.join(p.split('/')[:i]) in paths for p in paths for i in range(1, len(p.split('/')))):
        raise ContractError('PATH_UNSAFE', 'Bundle members cannot overlap directory paths.')
    return bundle


@contextmanager
def _bundle_members(bundle, root, code='HASH_MISMATCH', copy_to=None):
    """Hold verified regular-file descriptors for the complete declared closure."""
    with ExitStack() as stack:
        streams, identities = {}, {}
        for member in bundle['members']:
            name = member['relative_path']
            stream = stack.enter_context(_local_file(str(root / name)))
            sha, size, identity = _hash(stream)
            if (sha, size) != (member['sha256'], member['size_bytes']):
                raise ContractError(code, 'Source bundle member hash/size changed.')
            if copy_to is not None:
                fs, prefix = copy_to
                parent, _, leaf = (prefix + '/' + name).rpartition('/')
                with fs.directory(parent, create=True) as directory:
                    fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                    stream.seek(0)
                    with os.fdopen(fd, 'wb') as output:
                        copied_sha, copied_size, _ = _hash(stream, output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.fsync(directory)
                if (copied_sha, copied_size) != (sha, size):
                    raise ContractError('ASSET_CHANGED', 'Bundle member changed during staging.')
            stream.seek(0)
            streams[name], identities[name] = stream, identity
        def recheck():
            for name, stream in streams.items():
                if _identity(stream) != identities[name]:
                    raise ContractError(code, 'Source bundle member changed during use.')
        recheck()
        yield streams
        recheck()


def validate_asset_transaction(tx, pointer):
    """Parent core transaction reader calls this for asset-transaction schemas."""
    validate_asset(tx, 'AssetTransaction')
    if tx['pointer'] != pointer:
        raise ContractError('HASH_MISMATCH', 'Asset transaction does not match committed pointer.')
    asset, artifact = tx['asset'], tx['artifact']
    pid = pointer['project_id']
    if any(r['project_id'] != pid for r in (asset, artifact, tx['previous'])):
        raise ContractError('WRONG_PROJECT', 'Asset transaction closure crosses projects.')
    if (asset['artifact'] != {'artifact_id': artifact['artifact_id'], 'sha256': artifact['sha256']}
            or asset['source_fingerprint']['sha256'] != artifact['sha256']
            or asset['source_fingerprint']['size_bytes'] != artifact['size_bytes']
            or tx['result'] != {'asset': asset, 'project_revision': pointer['revision']}
            or tx['previous']['revision'] >= pointer['revision']
            or asset['provenance'] != artifact['provenance']):
        raise ContractError('HASH_MISMATCH', 'Asset transaction closure is inconsistent.')
    if asset['source_locator']['kind'] != 'local':
        raise ContractError('PATH_UNSAFE', 'Asset imports/references must retain local locators.')
    _absolute(asset['source_locator']['path'])
    storage = artifact['storage']
    expected_mode = 'managed' if asset['mode'] == 'copy' else 'external'
    if storage['mode'] != expected_mode:
        raise ContractError('HASH_MISMATCH', 'Asset storage differs from import mode.')
    if expected_mode == 'managed':
        expected = 'assets/originals/' + artifact['artifact_id'] + '/payload'
        if safe_relative(storage['relative_path']) != expected:
            raise ContractError('PATH_UNSAFE', 'Managed original path must be core assigned.')
    elif storage['source'] != asset['source_locator']:
        raise ContractError('HASH_MISMATCH', 'External locator differs from asset source.')
    return tx


class AssetRegistry:
    """Resolve only records reachable through committed project history."""
    def __init__(self, store):
        self.store = store

    def records(self, fs, pointer, *, _verify_caption=True):
        head = pointer
        records, seen = [], set()
        while pointer is not None:
            if pointer['revision'] in seen:
                raise ContractError('INVALID_GRAPH', 'Asset history contains a cycle.')
            seen.add(pointer['revision'])
            # Read identity closure without recursively loading project documents;
            # core document pin validation may itself call this resolver.
            path = f"{self.store._base(pointer['project_id'])}/revisions/{pointer['revision']}/transaction.json"
            tx = fs.read(path)
            if tx.get('schema') == 'motion/v1/asset-transaction':
                validate_asset_transaction(tx, pointer)
                records.append((copy.deepcopy(tx['asset']), copy.deepcopy(tx['artifact'])))
            elif tx.get('schema') == 'motion/v1/caption-transaction':
                from .captions import validate_caption_transaction
                validate_caption_transaction(tx, pointer)
            else:
                validate(tx, D['ProjectTransaction'])
                if tx['pointer'] != pointer:
                    raise ContractError('HASH_MISMATCH', 'History descriptor differs from committed pointer.')
            previous = tx['previous']
            if previous and previous['revision'] >= pointer['revision']:
                raise ContractError('INVALID_GRAPH', 'Asset history must decrease monotonically.')
            pointer = previous
        if _verify_caption and head is not None:
            from .captions import validate_caption_snapshot
            snapshot, documents = self.store._load(fs, head)
            validate_caption_snapshot(self.store, fs, head, snapshot, documents)
        records.sort(key=lambda pair: (pair[0]['created_at'], pair[0]['asset_id']))
        return records

    @staticmethod
    def summary(asset):
        return {k: copy.deepcopy(asset[k]) for k in ('asset_id', 'label', 'artifact', 'mode', 'created_at')} | {'rights_status': asset['provenance']['rights']['status']}

    def artifact(self, fs, pointer, pin):
        # One resolver for imports, caption outputs, ancillary records and jobs.
        from .artifacts import ArtifactCatalog
        return ArtifactCatalog(self.store).resolve_at(fs, pointer, pin)

    def _committed_artifact(self, fs, pointer, pin):
        validate_asset(pin, 'ArtifactRef')
        records = [artifact for _, artifact in self.records(fs, pointer, _verify_caption=False)]
        selected = pointer
        while selected is not None:
            tx = fs.read(f"{self.store._base(selected['project_id'])}/revisions/{selected['revision']}/transaction.json")
            if tx.get('schema') == 'motion/v1/caption-transaction':
                # records() already checked every descriptor in this chain.
                records.extend(tx['artifacts'])
            selected = tx['previous']
        record = next((artifact for artifact in records
                       if artifact['artifact_id'] == pin['artifact_id']), None)
        if record is None:
            raise ContractError('NOT_FOUND', 'Artifact is not committed in this project.')
        if record['sha256'] != pin['sha256']:
            raise ContractError('HASH_MISMATCH', 'Artifact pin differs from immutable identity.')
        with self.open_artifact(fs, record):
            pass
        return record

    @contextmanager
    def open_artifact(self, fs, record):
        """Yield manifest/payload only after validating its entire source closure."""
        with self._open_record(fs, record) as (stream, _members):
            yield stream

    @contextmanager
    def open_source_members(self, fs, record):
        """Yield {relative_path: verified binary descriptor}; valid only in context.

        The manifest's entry_member selects the runtime entry. This API performs
        no code execution and never hands an adapter an unverified pathname.
        """
        if record['kind'] not in ('scene_source', 'assembly_source'):
            raise ContractError('INVALID_ARGUMENT', 'Artifact is not an authored source bundle.')
        with self._open_record(fs, record) as (_manifest, members):
            yield members

    @contextmanager
    def _open_record(self, fs, record):
        validate_asset(record, 'ArtifactRecord')
        managed = record['storage']['mode'] == 'managed'
        if managed:
            relative = safe_relative(record['storage']['relative_path'])
            path = str(fs.root / self.store._base(record['project_id']) / relative)
            code = 'HASH_MISMATCH'
        else:
            path = record['storage']['source']['path']
            code = 'ASSET_CHANGED'
        with ExitStack() as stack:
            try:
                stream = stack.enter_context(_local_file(path))
                sha, size, identity = _hash(stream)
                if sha != record['sha256'] or size != record['size_bytes']:
                    raise ContractError(code, 'Pinned artifact bytes changed.')
                members = {}
                if record['kind'] in ('scene_source', 'assembly_source'):
                    # Managed manifest retains original bytes; its member paths
                    # are mapped into the core-assigned sibling closure root.
                    bundle = _read_bundle(stream, Path(path).name if not managed else '')
                    root = Path(path + '.members') if managed else Path(path).parent
                    members = stack.enter_context(_bundle_members(bundle, root, code))
                if _identity(stream) != identity:
                    raise ContractError(code, 'Artifact changed during closure validation.')
                stream.seek(0)
            except (OSError, ContractError) as exc:
                if isinstance(exc, ContractError) and exc.code == code:
                    raise
                raise ContractError(code, 'Pinned artifact closure is missing, unsafe or changed.') from None
            # A caller's refusal is not evidence that these verified bytes changed.
            # Keep consumer exceptions outside the acquisition-error translation.
            yield stream, members
            try:
                if _identity(stream) != identity:
                    raise ContractError(code, 'Artifact changed during use.')
            except OSError:
                raise ContractError(code, 'Pinned artifact closure is missing, unsafe or changed.') from None


class AssetStore(ProjectStore):
    """Native asset entry point, sharing core project transactions and paging."""
    def __init__(self, root=None, *, probe=None, **kwargs):
        super().__init__(root, **kwargs)
        self.probe = probe
    def _load(self, fs, pointer):
        snapshot, documents = super()._load(fs, pointer)
        from .captions import validate_caption_snapshot
        validate_caption_snapshot(self, fs, pointer, snapshot, documents)
        return snapshot, documents

    def _transaction(self, fs, pointer):
        path = f"{self._base(pointer['project_id'])}/revisions/{pointer['revision']}/transaction.json"
        tx = fs.read(path)
        if tx.get('schema') == 'motion/v1/asset-transaction':
            validate_asset_transaction(tx, pointer)
            self._load(fs, pointer)
            return tx
        return super()._transaction(fs, pointer)

    @staticmethod
    def request_hash(args):
        return digest({'tool': 'motion_asset', **{k: v for k, v in args.items() if k != 'request_id'}})

    def _accepted(self, fs, pointer, args):
        # Cross-action/tool namespace, before CAS and before reopening source.
        noop_path = self._base(pointer['project_id']) + '/requests/' + args['request_id'] + '.json'
        try:
            fs.read(noop_path)
        except FileNotFoundError:
            pass
        else:
            raise ContractError('IDEMPOTENCY_CONFLICT', 'Request id already accepted by project content update.')
        seen = set()
        while pointer:
            if pointer['revision'] in seen:
                raise ContractError('INVALID_GRAPH', 'Commit history cycle.')
            seen.add(pointer['revision'])
            tx = self._transaction(fs, pointer)
            if (tx['request_id'] == args['request_id']
                    and not (tx.get('tool', 'motion_project') == 'motion_project' and tx['action'] == 'create')):
                if tx.get('tool') != 'motion_asset' or tx['request_sha256'] != self.request_hash(args):
                    raise ContractError('IDEMPOTENCY_CONFLICT', 'Request id already committed with different tool/action/content.')
                return copy.deepcopy(tx['result'])
            pointer = tx['previous']
        return None

    @staticmethod
    def _cas(pointer, args):
        if pointer['revision'] != args['expected_revision']:
            raise ContractError('REVISION_CONFLICT', 'Project content revision changed.',
                {'expected_revision': args['expected_revision'], 'actual_revision': pointer['revision'],
                 'owner_kind': 'project', 'owner_id': pointer['project_id']})

    def _stage(self, fs, pointer, args):
        path = args['source']['path']
        _absolute(path)
        is_bundle = args['kind'] in ('scene_source', 'assembly_source')
        provenance = args['provenance']
        locator = provenance['source_locator']
        if locator and '://' in locator:
            url = urlsplit(locator)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ContractError('PATH_UNSAFE', 'Provenance locator must not persist retrieval secrets.')
        registry = AssetRegistry(self)
        for evidence in provenance['rights']['evidence']:
            registry.artifact(fs, pointer, evidence)
        timestamp, aid, artid = _now(), _id('ast'), _id('art')
        relative = 'assets/originals/' + artid + '/payload'
        copied = args['action'] == 'import'
        with _local_file(path) as source:
            if copied:
                parent, _, name = (self._base(pointer['project_id']) + '/' + relative).rpartition('/')
                with fs.directory(parent, create=True) as directory:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                    with os.fdopen(fd, 'wb') as output:
                        sha, size, identity = _hash(source, output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.fsync(directory)
                with _local_file(str(fs.root / self._base(pointer['project_id']) / relative)) as staged:
                    staged_sha, staged_size, _ = _hash(staged)
                if (sha, size) != (staged_sha, staged_size):
                    raise ContractError('HASH_MISMATCH', 'Staged bytes differ from source.')
            else:
                sha, size, identity = _hash(source)
            if args['kind'] == 'caption':
                # Canonical bounded JSON only; no sidecar parser or ASR fallback.
                from .captions import validate_imported_caption
                from .artifacts import read_bounded_json
                source.seek(0)
                caption = validate_imported_caption(read_bounded_json(source))
                for dependency in [caption['source_audio'], caption['source_transcript'],
                                   *caption['timing_evidence'], *caption['timing_decisions']]:
                    registry.artifact(fs, pointer, dependency)
                source.seek(0)
            if is_bundle:
                bundle = _read_bundle(source, Path(path).name)
                copy_to = (fs, self._base(pointer['project_id']) + '/' + relative + '.members') if copied else None
                with _bundle_members(bundle, Path(path).parent, 'ASSET_CHANGED', copy_to):
                    pass
        fingerprint = {'sha256': sha, 'size_bytes': size, 'observed_at': timestamp}
        asset = {'schema': 'motion/v1/asset', 'asset_id': aid, 'project_id': pointer['project_id'],
                 'label': args['label'], 'mode': 'copy' if copied else 'reference',
                 'source_locator': copy.deepcopy(args['source']),
                 'artifact': {'artifact_id': artid, 'sha256': sha}, 'source_fingerprint': fingerprint,
                 'provenance': copy.deepcopy(provenance), 'created_at': timestamp}
        artifact = {'schema': 'motion/v1/artifact', 'artifact_id': artid, 'project_id': pointer['project_id'],
                    'kind': args['kind'], 'media_type': mimetypes.guess_type(path)[0] or 'application/octet-stream',
                    'sha256': sha, 'size_bytes': size,
                    'storage': {'mode': 'managed', 'relative_path': relative} if copied else {'mode': 'external', 'source': copy.deepcopy(args['source'])},
                    'created_at': timestamp, 'producer': {k: None for k in ('job_id', 'node_id', 'attempt_id', 'adapter_id')},
                    'inputs': [], 'provenance': copy.deepcopy(provenance), 'probe_receipt_id': None}
        validate_asset(asset, 'AssetRecord')
        validate_asset(artifact, 'ArtifactRecord')
        return asset, artifact, identity

    def _mutate(self, fs, args):
        pid = args['project_id']
        base = self._base(pid)
        pointer = self._pointer(fs, pid)
        # Fast preflight does not reserve the identity; authoritative repeat below.
        replay = self._accepted(fs, pointer, args)
        if replay is not None:
            return replay, {'project_id': pid, 'project_revision': replay['project_revision']}
        self._cas(pointer, args)
        asset, artifact, identity = self._stage(fs, pointer, args)  # Hash/copy outside writer lock.
        with fs.lock(base + '/locks/content.lock'), ExitStack() as verified:
            pointer = self._pointer(fs, pid)
            replay = self._accepted(fs, pointer, args)
            if replay is not None:
                return replay, {'project_id': pid, 'project_revision': replay['project_revision']}
            self._cas(pointer, args)
            with _local_file(args['source']['path']) as source:
                if _identity(source) != identity:
                    raise ContractError('ASSET_CHANGED', 'Source identity changed before publication.')
            registry = AssetRegistry(self)
            source_record = {**artifact, 'storage': {'mode': 'external', 'source': args['source']}}
            verified.enter_context(registry.open_artifact(fs, source_record))
            if artifact['storage']['mode'] == 'managed':
                verified.enter_context(registry.open_artifact(fs, artifact))
            old_snapshot, documents = self._load(fs, pointer)
            allocated = [int(n) for n in fs.names(base + '/revisions') if n.isascii() and n.isdigit()]
            revision = max(allocated + [pointer['revision']]) + 1
            if revision > MAX_INT:
                raise ContractError('LIMIT_EXCEEDED', 'Project revision exhausted.')
            new = {**pointer, 'revision': revision, 'updated_at': _now(), 'manifest_path': f'revisions/{revision}/snapshot.json'}
            snapshot = {**copy.deepcopy(old_snapshot), 'revision': revision}
            new['snapshot_sha256'] = digest(snapshot)
            result = {'asset': asset, 'project_revision': revision}
            tx = {'schema': 'motion/v1/asset-transaction', 'tool': 'motion_asset', 'action': args['action'],
                  'request_id': args['request_id'], 'request_sha256': self.request_hash(args),
                  'previous': pointer, 'pointer': new, 'asset': asset, 'artifact': artifact, 'result': result}
            validate_asset_transaction(tx, new)
            target = base + '/revisions/' + str(revision)
            for record in documents.values():
                fs.write(f"{target}/documents/{record['kind']}/{record['id']}.json", record)
            fs.write(target + '/snapshot.json', snapshot)
            fs.write(target + '/transaction.json', tx)
            # Finish descriptor identity checks before the pointer's commit point;
            # a changed closure must not publish and then report effect=none.
            verified.close()
            fs.write(base + '/project.json', new, replace=True)
            return result, self._context(new)

    def dispatch(self, args):
        action = args.get('action', '') if isinstance(args, dict) else ''
        action = action if isinstance(action, str) else ''
        try:
            validate_asset(args, 'AssetRequest')
            args = copy.deepcopy(args)
            if action == 'probe':
                args.setdefault('full_decode', False)
            fs = self._filesystem(write=action in ('import', 'reference'))
            if action in ('import', 'reference'):
                data, context = self._mutate(fs, args)
            else:
                pointer = self._pointer(fs, args['project_id'])
                registry = AssetRegistry(self)
                context = self._context(pointer)
                if action == 'list':
                    scoped = {**args, '_tool': 'motion_asset'}
                    if 'cursor' in args or 'snapshot_id' in args:
                        data = self._page(fs, scoped, None)
                    else:
                        items = [registry.summary(asset) for asset, artifact in registry.records(fs, pointer)
                                 if ('kind' not in args or artifact['kind'] == args['kind'])
                                 and ('rights_status' not in args or asset['provenance']['rights']['status'] == args['rights_status'])]
                        data = self._page(fs, scoped, items)
                elif action == 'get':
                    record = next((pair for pair in registry.records(fs, pointer) if pair[0]['asset_id'] == args['asset_id']), None)
                    if record is None:
                        raise ContractError('NOT_FOUND', 'Asset is not committed in this project.')
                    asset, artifact = record
                    registry.artifact(fs, pointer, asset['artifact'])
                    data = {'asset': asset, 'artifact': artifact, 'latest_probe': None}
                else:
                    if self.probe is not None:
                        return self.probe(args)
                    self._cas(pointer, args)
                    registry.artifact(fs, pointer, args['artifact'])
                    raise ContractError('UNSUPPORTED_FEATURE', 'Probe requires selected adapter, immutable media.probe plan and owned job execution (B06/B07); no probe was run.')
            result = {'ok': True, 'tool': 'motion_asset', 'action': action, 'status': 'ok',
                      'summary': 'Asset ' + action + ' accepted.', **context, 'data': data}
            return result
        except ContractError as exc:
            result = self._error(action, exc)
            result['tool'] = 'motion_asset'
            if exc.code == 'UNSUPPORTED_FEATURE':
                result['status'] = 'blocked'
                result['error']['retry'] = 'after_dependency'
            return result
        except FileNotFoundError:
            return self._asset_error(action, ContractError('NOT_FOUND', 'Requested local file/project is unavailable.'))
        except OSError as exc:
            return self._asset_error(action, _fs_error(exc))
        except Exception:
            LOG.exception('Unexpected asset failure')
            return self._asset_error(action, ContractError('INTERNAL_ERROR', 'Unexpected asset failure.', effect='unknown'))

    def _asset_error(self, action, exc):
        result = self._error(action, exc)
        result['tool'] = 'motion_asset'
        return result


def asset_handler(args, **host_context):
    from .runtime import NativeRuntime
    runtime = host_context.pop("_runtime", None) or NativeRuntime()
    return json.dumps(runtime.asset(args, session_id=host_context.get("session_id"),
                                   task_id=host_context.get("task_id")),
                      ensure_ascii=True, allow_nan=False)
