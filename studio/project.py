"""B03 immutable project transactions and profile-lazy native handler.

Only the commit pointer publishes content. Each immutable revision retains a
complete document closure, prior pointer and accepted request/result. Create's
root receipt publishes its initial pointer; project.json is a repairable index
until the first content update. No filesystem access occurs on import.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import datetime, timedelta, timezone
import errno
import fcntl
import json
import logging
import os
from pathlib import Path
import secrets
import stat
import threading
import time
import uuid

from .contracts import (ContractError, D, GATES, MAX_INT, canonical, default_gate_policy,
                        digest, domain, invalid, safe_relative, validate, validate_request)

LOG = logging.getLogger(__name__)
_SNAPSHOTS = {}
_SNAPSHOT_LOCK = threading.RLock()
SINGLETONS = ['brief', 'brand', 'timeline', 'settings', 'variants', 'bindings']


def _id(prefix):
    return prefix + '_' + str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _fs_error(exc):
    if exc.errno in [errno.ELOOP, errno.ENOTDIR]:
        return ContractError('PATH_UNSAFE', 'Managed path is not a safe regular file/directory.')
    if exc.errno == errno.ENOSPC:
        return ContractError('DISK_FULL', 'Project storage is full.', effect='unknown')
    if exc.errno in [errno.EACCES, errno.EPERM]:
        return ContractError('PERMISSION_DENIED', 'Project storage access denied.')
    return ContractError('STORAGE_UNSUPPORTED', 'Project storage operation failed.', effect='unknown')


class ManagedFS:
    """Descriptor-relative traversal; never follow symlinks, including ancestors."""
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_absolute() or any(part in ['.', '..'] for part in self.root.parts):
            raise ContractError('PATH_UNSAFE', 'Storage root must be absolute.')

    @contextmanager
    def directory(self, relative='', create=False):
        parts = list(self.root.parts[1:]) + (safe_relative(relative).split('/') if relative else [])
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts:
                if part in ['.', '..']:
                    raise ContractError('PATH_UNSAFE', 'Noncanonical storage path.')
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass  # Another writer created it; nofollow open below verifies it.
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def read(self, relative):
        safe_relative(relative)
        parent, _, name = relative.rpartition('/')
        with self.directory(parent) as directory:
            for retry in range(3):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(fd, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise ContractError('PATH_UNSAFE', 'Managed record must be a regular file.')
                    limit = 16777216
                    if before.st_size > limit:
                        raise ContractError('LIMIT_EXCEEDED', 'Managed record exceeds read bound.')
                    payload = stream.read(limit + 1)
                    if len(payload) > limit:
                        raise ContractError('LIMIT_EXCEEDED', 'Managed record exceeds read bound.')
                    after = os.fstat(stream.fileno())
                    identity = lambda value: (value.st_dev,value.st_ino,value.st_size,
                                              value.st_mtime_ns,value.st_ctime_ns)
                    if identity(before) != identity(after) or len(payload) != before.st_size:
                        # Atomic replacement can unlink the still-open inode,
                        # changing ctime without mutating its bytes. Discard
                        # this snapshot; never weaken its integrity checks.
                        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                        if (retry < 2 and stat.S_ISREG(current.st_mode)
                                and (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)):
                            continue
                        raise ContractError('ASSET_CHANGED', 'Managed record changed during read.')
                    return json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))

    def names(self, relative):
        try:
            with self.directory(relative) as fd:
                return sorted(os.listdir(fd))
        except FileNotFoundError:
            return []

    def write(self, relative, value, replace=False):
        safe_relative(relative)
        payload = canonical(value)
        if len(payload) > 16777216:
            raise ContractError('LIMIT_EXCEEDED', 'Managed record exceeds 16 MiB storage/read bound.')
        parent, _, name = relative.rpartition('/')
        with self.directory(parent, create=True) as directory:
            temporary = '.staging-' + secrets.token_hex(16) if replace else name
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                if replace:
                    os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                if replace:
                    try:
                        os.unlink(temporary, dir_fd=directory)
                    except FileNotFoundError:
                        pass

    @contextmanager
    def lock(self, relative):
        parent, _, name = safe_relative(relative).rpartition('/')
        with self.directory(parent, create=True) as directory:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ContractError('PATH_UNSAFE', 'Lock must be a regular file.')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ContractError('LOCK_BUSY', 'Project writer lock is held.') from None
                yield
            finally:
                os.close(fd)


def _read_root():
    # plugin_data_dir creates directories; reads must use its verified derivation
    # with the same live SDK profile resolver, without invoking that mutation.
    from hermes_constants import get_hermes_home
    return get_hermes_home() / 'plugin-data' / 'motion-studio'


def _write_root():
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir('motion-studio')


class ProjectStore:
    def __init__(self, root=None, *, snapshot_ttl=1800, snapshot_limit=100, clock=time.time):
        self.root = Path(root) if root is not None else None
        if not 1 <= snapshot_ttl <= 1800 or not 1 <= snapshot_limit <= 100:
            raise ValueError('Invalid snapshot bounds')
        self.snapshot_ttl, self.snapshot_limit, self.clock = snapshot_ttl, snapshot_limit, clock

    def _filesystem(self, write=False):
        root = self.root if self.root is not None else _read_root()
        fs = ManagedFS(root)
        # Check existing ancestors without following links before SDK mkdir.
        try:
            with fs.directory():
                pass
        except FileNotFoundError:
            self._check_ancestors(root)
        if write:
            self._check_filesystem(root)
            if self.root is None:
                actual = _write_root()
                if actual != root:
                    raise ContractError('STORAGE_UNSUPPORTED', 'Active profile changed during root resolution.')
            else:
                with fs.directory(create=True):
                    pass
        return fs

    @staticmethod
    def _check_ancestors(root):
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in root.parts[1:]:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    break
                os.close(fd)
                fd = child
        finally:
            os.close(fd)

    @staticmethod
    def _check_filesystem(root):
        # First release requires local POSIX lock/rename semantics. Do not
        # quietly accept known remote or pseudo filesystems.
        if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
            raise ContractError('STORAGE_UNSUPPORTED', 'Local POSIX storage is required.')
        try:
            mounts = []
            with open('/proc/self/mountinfo', encoding='utf-8') as stream:
                for line in stream:
                    left, right = line.rstrip().split(' - ', 1)
                    mount = left.split()[4].replace('\\040', ' ')
                    if str(root) == mount or str(root).startswith(mount.rstrip('/') + '/'):
                        mounts.append((len(mount), right.split()[0]))
            filesystem = max(mounts)[1]
        except (OSError, ValueError, IndexError):
            raise ContractError('STORAGE_UNSUPPORTED', 'Cannot verify local filesystem semantics.') from None
        if filesystem not in ['ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'tmpfs', 'overlay', 'zfs']:
            raise ContractError('STORAGE_UNSUPPORTED', 'Filesystem semantics are not supported.')

    def dispatch(self, args):
        action = args.get('action', '') if isinstance(args, dict) else ''
        if not isinstance(action, str):
            action = ''
        try:
            args = validate_request(args)
            fs = self._filesystem(write=args['action'] in ['create', 'update'])
            data, context = getattr(self, '_' + args['action'])(fs, args)
            return {'ok': True, 'tool': 'motion_project', 'action': action, 'status': 'ok',
                    'summary': {'create': 'Project created.', 'list': 'Project listing.', 'open': 'Project content opened read-only.', 'status': 'Project status.', 'update': 'Project update accepted.'}[action], **context, 'data': data}
        except ContractError as exc:
            return self._error(action, exc)
        except FileNotFoundError:
            return self._error(action, ContractError('NOT_FOUND', 'Requested managed record does not exist.'))
        except OSError as exc:
            LOG.exception('Project filesystem failure')
            return self._error(action, _fs_error(exc))
        except Exception:
            handle = secrets.token_hex(12)
            LOG.exception('Project diagnostic %s', handle)
            return self._error(action, ContractError('INTERNAL_ERROR', 'Unexpected project failure; diagnostic ' + handle, effect='unknown'))

    @staticmethod
    def _error(action, exc):
        retry = {'LOCK_BUSY': 'same_request', 'DISK_FULL': 'after_dependency', 'STORAGE_UNSUPPORTED': 'after_dependency', 'PERMISSION_DENIED': 'after_authority', 'INTERNAL_ERROR': 'after_reconcile'}.get(exc.code, 'after_input_change')
        return {'ok': False, 'tool': 'motion_project', 'action': action, 'status': 'error', 'summary': exc.message,
                'error': {'code': exc.code, 'message': exc.message, 'retry': retry, 'effect': exc.effect, 'details': exc.details}}

    @staticmethod
    def _context(pointer):
        return {'project_id': pointer['project_id'], 'project_revision': pointer['revision']}

    @staticmethod
    def _base(pid):
        validate(pid, D['ProjectRecord']['properties']['project_id'])
        return 'projects/' + pid

    def _receipts(self, fs):
        for name in fs.names('requests'):
            if name.endswith('.json'):
                validate(name[:-5], {'type': 'string', 'pattern': DUMMY_UUID})
                receipt = fs.read('requests/' + name)
                if receipt.get('schema') != 'motion/v1/create-commit':
                    raise ContractError('SCHEMA_UNSUPPORTED', 'Unsupported create receipt schema.')
                validate(receipt, D['CreateCommit'])
                if receipt['request_id'] != name[:-5]:
                    raise ContractError('HASH_MISMATCH', 'Create receipt identity differs from its canonical key.')
                yield receipt

    def _pointer(self, fs, pid):
        base = self._base(pid)
        # A receipt is the create commit, not an uncommitted project directory.
        initial = next((r['pointer'] for r in self._receipts(fs) if r['pointer']['project_id'] == pid), None)
        if initial is None:
            raise ContractError('NOT_FOUND', 'Project is not committed in this profile.', {'resource': pid, 'reason': 'No committed create receipt in this active profile.'})
        try:
            pointer = fs.read(base + '/project.json')
        except FileNotFoundError:
            pointer = initial
        self._validate_pointer(pointer, pid)
        return pointer

    @staticmethod
    def _validate_pointer(pointer, pid):
        if pointer.get('schema') != 'motion/v1/project':
            raise ContractError('SCHEMA_UNSUPPORTED', 'Unsupported project schema; explicit migration required.')
        validate(pointer, D['ProjectRecord'])
        if pointer['project_id'] != pid:
            raise ContractError('WRONG_PROJECT', 'Pointer belongs to a different project.')
        expected = f"revisions/{pointer['revision']}/snapshot.json"
        if pointer['manifest_path'] != expected:
            raise ContractError('PATH_UNSAFE', 'Pointer must reference its canonical immutable snapshot.')

    def _load(self, fs, pointer):
        pid = pointer['project_id']
        self._validate_pointer(pointer, pid)
        base = self._base(pid)
        snapshot = fs.read(base + '/' + pointer['manifest_path'])
        if snapshot.get('schema') != 'motion/v1/project-snapshot':
            raise ContractError('SCHEMA_UNSUPPORTED', 'Unsupported content snapshot schema.')
        validate(snapshot, D['ProjectSnapshot'])
        if digest(snapshot) != pointer['snapshot_sha256']:
            raise ContractError('HASH_MISMATCH', 'Snapshot content digest changed.')
        if snapshot['project_id'] != pid or snapshot['revision'] != pointer['revision']:
            raise ContractError('WRONG_PROJECT', 'Snapshot identity does not match pointer.')
        documents = {}
        for pin in snapshot['documents']:
            self._safe_document_identity(pin['kind'], pin['id'])
            record = fs.read(f"{base}/revisions/{pointer['revision']}/documents/{pin['kind']}/{pin['id']}.json")
            if record.get('schema') != 'motion/v1/document':
                raise ContractError('SCHEMA_UNSUPPORTED', 'Unsupported document schema.')
            validate(record, self._document_schema(pin['kind']))
            if record['project_id'] != pid or any(record[k] != pin[k] for k in ['kind', 'id', 'revision']):
                raise ContractError('WRONG_PROJECT', 'Document identity does not match reference.')
            if digest(record) != pin['sha256']:
                raise ContractError('HASH_MISMATCH', 'Document bytes/content changed.')
            key = (pin['kind'], pin['id'])
            if key in documents:
                invalid('$.documents', 'unique document identities', snapshot['documents'])
            documents[key] = record
        if any((kind, 'project') not in documents for kind in SINGLETONS):
            invalid('$.documents', 'six required singleton documents', snapshot['documents'])
        from .captions import validate_caption_snapshot
        validate_caption_snapshot(self, fs, pointer, snapshot, documents)
        return snapshot, documents

    @staticmethod
    def _safe_document_identity(kind, key):
        if kind in SINGLETONS or kind in ('asset_library', 'storyboard', 'creative_plan', 'editorial'):
            if key != 'project':
                raise ContractError('WRONG_PROJECT', 'Singleton document id must be project.')
        elif kind in ('caption', 'caption_style'):
            from .captions import CaptionStore
            CaptionStore._safe_document_identity(kind, key)
        elif kind == 'scene':
            validate(key, D['Scene']['properties']['scene_id'])
        elif kind in ['delivery_profile', 'gate_policy']:
            validate(key, D['DeliveryProfile']['properties']['profile_id'])
        else:
            raise ContractError('UNSUPPORTED_FEATURE', 'Document kind is outside B03 project content.')

    @staticmethod
    def _document_schema(kind):
        if kind in ('caption', 'caption_style'):
            from .captions import CaptionStore
            return CaptionStore._document_schema(kind)
        name = {'brief': 'Brief', 'brand': 'Brand', 'settings': 'Settings', 'bindings': 'Bindings', 'timeline': 'Timeline', 'scene': 'Scene', 'delivery_profile': 'DeliveryProfile', 'gate_policy': 'GatePolicy', 'asset_library': 'AssetLibrary', 'storyboard': 'Storyboard', 'creative_plan': 'CreativePlan', 'editorial': 'Editorial'}.get(kind)
        if kind != 'variants' and name is None:
            raise ContractError('UNSUPPORTED_FEATURE', 'Unknown B03 document kind.')
        value = {'type': 'array', 'items': {'$ref': '#/$defs/Variant'}, 'maxItems': 1000} if kind == 'variants' else {'$ref': '#/$defs/' + str(name)}
        from .contracts import obj, TEXT, STAMP, integer, enum, ident
        return obj({'schema': {'const': 'motion/v1/document'}, 'project_id': ident('prj'), 'kind': enum(kind), 'id': TEXT, 'revision': integer(1), 'created_at': STAMP, 'value': value})

    def _summary(self, pointer, documents):
        settings = documents['settings', 'project']['value']
        return {k: copy.deepcopy(pointer[k]) for k in ['project_id', 'name', 'revision', 'snapshot_sha256', 'created_at', 'updated_at']} | {k: copy.deepcopy(settings[k]) for k in ['stage', 'rate', 'sample_rate']}

    @staticmethod
    def _request_hash(args):
        return digest({'tool': 'motion_project', **{k: v for k, v in args.items() if k != 'request_id'}})

    def _transaction(self, fs, pointer):
        path = f"{self._base(pointer['project_id'])}/revisions/{pointer['revision']}/transaction.json"
        tx = fs.read(path)
        if tx.get('schema') == 'motion/v1/asset-transaction':
            from .assets import validate_asset_transaction
            validate_asset_transaction(tx, pointer)
            self._load(fs, pointer)
            return tx
        if tx.get('schema') == 'motion/v1/caption-transaction':
            from .captions import validate_caption_transaction
            validate_caption_transaction(tx, pointer)
            _, docs = self._load(fs, pointer)
            document = docs.get(('caption', tx['caption_id']))
            if document is None or document['revision'] != tx['caption_revision'] or tx['result']['data']['caption'] != {k: document[k] for k in ('kind', 'id', 'revision')} | {'sha256': digest(document)} or tx['document']['sha256'] != digest(document['value']):
                raise ContractError('HASH_MISMATCH', 'Caption transaction document/artifact closure differs.')
            return tx
        if tx.get('schema') != 'motion/v1/project-transaction' or tx.get('pointer') != pointer:
            raise ContractError('HASH_MISMATCH', 'Commit descriptor does not match published pointer.')
        validate(tx, D['ProjectTransaction'])
        # Revalidate the entire closure before replaying an accepted identity.
        self._load(fs, pointer)
        return tx

    def _replay(self, fs, pointer, args):
        seen = set()
        while pointer:
            if pointer['revision'] in seen:
                raise ContractError('INVALID_GRAPH', 'Commit history cycle.')
            seen.add(pointer['revision'])
            tx = self._transaction(fs, pointer)
            if tx['request_id'] == args['request_id'] and not (tx.get('tool', 'motion_project') == 'motion_project' and tx['action'] == 'create'):
                if tx.get('tool', 'motion_project') != 'motion_project' or tx['request_sha256'] != self._request_hash(args):
                    raise ContractError('IDEMPOTENCY_CONFLICT', 'Request id already committed with different content/action.')
                return copy.deepcopy(tx['result'])
            previous = tx['previous']
            if previous and previous['revision'] >= pointer['revision']:
                raise ContractError('INVALID_GRAPH', 'Commit history must decrease monotonically.')
            pointer = previous
        return None

    def _affected_nodes(self, fs, pointer, before_documents, after_documents):
        """Report exact affected frozen-plan descendants; preserve all old outputs."""
        from .plans import PlanCompiler
        from .capabilities import CapabilityRegistry
        from .reviews import affected_plan_nodes
        compiler = PlanCompiler(self, CapabilityRegistry())
        affected = {}
        for plan_id in fs.names(self._base(pointer['project_id']) + '/plans'):
            commit = fs.read(f"{self._base(pointer['project_id'])}/plans/{plan_id}/plan.json")
            raw = commit.get('plan')
            if not isinstance(raw, dict) or raw.get('plan_id') != plan_id:
                raise ContractError('HASH_MISMATCH', 'Frozen plan directory/identity differs.')
            plan = compiler.load(pointer['project_id'], compiler.plan_ref(raw), fs=fs)
            for item in affected_plan_nodes(plan['nodes'], before_documents, after_documents):
                affected[item['node_id']] = item
        return [affected[key] for key in sorted(affected)]

    def _prepare(self, fs, pointer, documents, args, previous, changed):
        snapshot = {'schema': 'motion/v1/project-snapshot', 'project_id': pointer['project_id'], 'revision': pointer['revision'], 'documents': [{'kind': d['kind'], 'id': d['id'], 'revision': d['revision'], 'sha256': digest(d)} for _, d in sorted(documents.items())], 'caption_slots': copy.deepcopy(self._load(fs, previous)[0]['caption_slots']) if previous else {}}
        pointer['snapshot_sha256'] = digest(snapshot)
        validate(snapshot, D['ProjectSnapshot'])
        validate(pointer, D['ProjectRecord'])
        pins = {(p['kind'], p['id']): p for p in snapshot['documents']}
        result = {'project': self._summary(pointer, documents)}
        if args['action'] == 'create':
            result['documents'] = snapshot['documents']
        else:
            result |= {'changed': [pins[k] for k in sorted(changed) if k in pins], 'invalidated': self._affected_nodes(fs, previous, self._load(fs, previous)[1], documents)}
        base = f"{self._base(pointer['project_id'])}/revisions/{pointer['revision']}"
        for record in documents.values():
            validate(record, self._document_schema(record['kind']))
            fs.write(f"{base}/documents/{record['kind']}/{record['id']}.json", record)
        fs.write(base + '/snapshot.json', snapshot)
        tx = {'schema': 'motion/v1/project-transaction', 'action': args['action'], 'request_id': args['request_id'], 'request_sha256': self._request_hash(args), 'previous': previous, 'pointer': pointer, 'result': result}
        validate(tx, D['ProjectTransaction'])
        fs.write(base + '/transaction.json', tx)
        # Directory creation and every immutable payload is fsynced by write.
        return result

    def _create(self, fs, args):
        with fs.lock('requests/create.lock'):
            try:
                receipt = fs.read('requests/' + args['request_id'] + '.json')
            except FileNotFoundError:
                receipt = None
            if receipt:
                if receipt.get('schema') != 'motion/v1/create-commit':
                    raise ContractError('SCHEMA_UNSUPPORTED', 'Unsupported create receipt schema.')
                validate(receipt, D['CreateCommit'])
                if receipt['request_id'] != args['request_id']:
                    raise ContractError('HASH_MISMATCH', 'Create receipt identity differs from request.')
                if receipt['request_sha256'] != self._request_hash(args):
                    raise ContractError('IDEMPOTENCY_CONFLICT', 'Create request id already committed with a different payload.')
                tx = self._transaction(fs, receipt['pointer'])
                return tx['result'], self._context(receipt['pointer'])
            pid, timestamp = _id('prj'), _now()
            policy = {'remote': 'deny', 'allowed_destinations': [], 'paid': 'deny', 'max_concurrent_nodes': 1, 'retain_generated_assets': True}
            values = {'brief': args['brief'], 'brand': {'colors': {}, 'fonts': [], 'spacing_px': {}, 'motion_tokens': {}, 'logo_assets': [], 'reference_assets': []}, 'timeline': {'duration_frames': 0, 'tracks': []}, 'variants': [], 'bindings': {'selected_adapter_ids': [], 'preferences': {}, 'pins': {}}, 'settings': {'rate': args['rate'], 'sample_rate': args['sample_rate'], 'audio_mode': 'silent', 'stage': 'intake', 'policy': policy, 'gate_policy': default_gate_policy()}}
            documents = {(kind, 'project'): {'schema': 'motion/v1/document', 'project_id': pid, 'kind': kind, 'id': 'project', 'revision': 1, 'created_at': timestamp, 'value': value} for kind, value in values.items()}
            documents['gate_policy', 'default'] = {'schema': 'motion/v1/document', 'project_id': pid, 'kind': 'gate_policy', 'id': 'default', 'revision': 1, 'created_at': timestamp, 'value': copy.deepcopy(values['settings']['gate_policy'])}
            self._validate_content(fs, pid, documents)
            pointer = {'schema': 'motion/v1/project', 'project_id': pid, 'name': args['name'], 'revision': 1, 'created_at': timestamp, 'updated_at': timestamp, 'manifest_path': 'revisions/1/snapshot.json'}
            result = self._prepare(fs, pointer, documents, args, None, set(documents))
            # Root receipt is create's single commit point. Its embedded pointer
            # permits read/replay even if response/index publication is lost.
            receipt = {'schema': 'motion/v1/create-commit', 'request_id': args['request_id'], 'request_sha256': self._request_hash(args), 'pointer': pointer}
            validate(receipt, D['CreateCommit'])
            fs.write('requests/' + args['request_id'] + '.json', receipt, replace=True)
            fs.write(self._base(pid) + '/project.json', pointer, replace=True)
            return result, self._context(pointer)

    def _open(self, fs, args):
        pointer = self._pointer(fs, args['project_id'])
        revision = args.get('revision', pointer['revision'])
        while pointer['revision'] != revision:
            tx = self._transaction(fs, pointer)
            pointer = tx['previous']
            if pointer is None or pointer['revision'] < revision:
                raise ContractError('NOT_FOUND', 'Revision is not in committed project history.')
        snapshot, documents = self._load(fs, pointer)
        return {'project': self._summary(pointer, documents), 'documents': snapshot['documents'], 'available_sections': ['summary', 'scenes', 'variants', 'jobs', 'assets']}, self._context(pointer)

    def _list(self, fs, args):
        if 'cursor' in args or 'snapshot_id' in args:
            return self._page(fs, args, None), {}
        items = []
        for receipt in self._receipts(fs):
            pointer = self._pointer(fs, receipt['pointer']['project_id'])
            _, docs = self._load(fs, pointer)
            summary = self._summary(pointer, docs)
            if args.get('name_contains', '').casefold() in summary['name'].casefold():
                items.append(summary)
        items.sort(key=lambda p: (p['created_at'], p['project_id']))
        return self._page(fs, args, items), {}

    def _status(self, fs, args):
        if 'cursor' in args or 'snapshot_id' in args:
            return self._page(fs, args, None), {'project_id': args['project_id']}
        pointer = self._pointer(fs, args['project_id'])
        _, docs = self._load(fs, pointer)
        section = args['section']
        scenes = [{'scene_id': r['id'], 'label': r['value']['label'], 'duration_frames': r['value']['duration_frames'], 'source_available': r['value']['authored_source'] is not None, 'document': {'kind': 'scene', 'id': r['id'], 'revision': r['revision'], 'sha256': digest(r)}} for (kind, _), r in docs.items() if kind == 'scene']
        scenes.sort(key=lambda p: (docs['scene', p['scene_id']]['created_at'], p['scene_id']))
        from .assets import AssetRegistry
        assets = [AssetRegistry.summary(asset) for asset, _ in AssetRegistry(self).records(fs, pointer)]
        from .jobs import JobStore, TERMINAL
        job_store = JobStore(self)
        job_rows = []
        for filename in fs.names(self._base(args['project_id']) + '/jobs'):
            if filename.endswith('.json'):
                job_id = filename[:-5]
                bundle = job_store.read(args['project_id'], job_id)
                job_rows.append((bundle['job']['created_at'], job_id,
                                 job_store.status(args['project_id'], job_id)))
        job_rows.sort(key=lambda row: (row[0], row[1]))
        jobs = [row[2] for row in job_rows]
        if section == 'summary':
            from .delivery import DeliveryService
            master_count = DeliveryService(self).master_count(args['project_id'], fs=fs)
            return {'project': self._summary(pointer, docs), 'counts': {'scenes': len(scenes), 'assets': len(assets), 'jobs': len(jobs), 'masters': master_count},
                    'active_jobs': sum(job['state'] not in TERMINAL for job in jobs),
                    'blocked_reasons': sorted({job['blocking_reason'] for job in jobs if job['blocking_reason']})}, self._context(pointer)
        items = scenes if section == 'scenes' else docs['variants', 'project']['value'] if section == 'variants' else assets if section == 'assets' else jobs if section == 'jobs' else []
        return self._page(fs, args, items), self._context(pointer)

    def _page(self, fs, args, items):
        # Read/list snapshots are bounded in-memory server state. No runtime
        # directory or SDK data root is created by a read. Restart expires tokens.
        scope = str(fs.root)
        now = self.clock()
        with _SNAPSHOT_LOCK:
            for sid, snap in list(_SNAPSHOTS.items()):
                if snap['idle_until'] <= now:
                    del _SNAPSHOTS[sid]
            if items is None:
                sid = args.get('snapshot_id')
                token = args.get('cursor')
                if token:
                    match = next(((key, snap) for key, snap in _SNAPSHOTS.items() if token in snap['tokens']), None)
                    if match is None:
                        raise ContractError('CURSOR_EXPIRED', 'Listing cursor expired or is unavailable after restart.')
                    actual_sid, snap = match
                    if sid and sid != actual_sid:
                        raise ContractError('CURSOR_MISMATCH', 'Cursor and snapshot differ.')
                    sid = actual_sid
                    offset = snap['tokens'][token]
                else:
                    snap = _SNAPSHOTS.get(sid)
                    if snap is None:
                        raise ContractError('CURSOR_EXPIRED', 'Listing snapshot expired.')
                    offset = 0
                binding = snap['binding']
                supplied = {k: v for k, v in args.items() if k not in ['cursor', 'snapshot_id']}
                if snap['scope'] != scope or any(binding.get(k) != v for k, v in supplied.items()):
                    raise ContractError('CURSOR_MISMATCH', 'Listing scope, filter, section or limit changed.')
            else:
                owned = [(key, snap) for key, snap in _SNAPSHOTS.items() if snap['scope'] == scope]
                if len(owned) >= self.snapshot_limit:
                    del _SNAPSHOTS[min(owned, key=lambda pair: pair[1]['last_used'])[0]]
                sid, offset = _id('snp'), 0
                binding = {k: v for k, v in args.items() if k not in ['cursor', 'snapshot_id']}
                binding.setdefault('limit', 20)
                snap = {'scope': scope, 'binding': binding, 'items': copy.deepcopy(items), 'tokens': {}, 'last_used': now}
                _SNAPSHOTS[sid] = snap
            snap['last_used'], snap['idle_until'] = now, now + self.snapshot_ttl
            limit, items = snap['binding']['limit'], snap['items']
            end = min(offset + limit, len(items))
            token = None
            if end < len(items):
                token = next((t for t, off in snap['tokens'].items() if off == end), None)
                if token is None:
                    token = secrets.token_urlsafe(32)
                    snap['tokens'][token] = end
            expires = datetime.fromtimestamp(snap['idle_until'], timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
            return {'items': copy.deepcopy(items[offset:end]), 'total': len(items), 'has_more': end < len(items), 'next_cursor': token, 'snapshot_id': sid, 'expires_at': expires}

    def _update(self, fs, args):
        pid, base = args['project_id'], self._base(args['project_id'])
        # Missing projects must not create ghost project lock directories.
        self._pointer(fs, pid)
        with fs.lock(base + '/locks/content.lock'):
            pointer = self._pointer(fs, pid)
            noop_path = base + '/requests/' + args['request_id'] + '.json'
            try:
                noop = fs.read(noop_path)
            except FileNotFoundError:
                noop = None
            if noop is not None:
                if noop.get('schema') != 'motion/v1/project-noop' or noop.get('project_id') != pid:
                    raise ContractError('SCHEMA_UNSUPPORTED', 'Invalid no-op acceptance record.')
                validate(noop, D['ProjectNoop'])
                if noop['request_id'] != args['request_id']:
                    raise ContractError('HASH_MISMATCH', 'No-op receipt identity differs from request.')
                if noop['request_sha256'] != self._request_hash(args):
                    raise ContractError('IDEMPOTENCY_CONFLICT', 'Request id already accepted with different content.')
                self._load(fs, noop['pointer'])
                return noop['result'], self._context(noop['pointer'])
            replay = self._replay(fs, pointer, args)
            if replay is not None:
                return replay, {'project_id': pid, 'project_revision': replay['project']['revision']}
            if pointer['revision'] != args['expected_revision']:
                raise ContractError('REVISION_CONFLICT', 'Project content revision changed.', {'expected_revision': args['expected_revision'], 'actual_revision': pointer['revision'], 'owner_kind': 'project', 'owner_id': pid})
            _, docs = self._load(fs, pointer)
            docs = copy.deepcopy(docs)
            changed = self._apply_changes(docs, args['changes'])
            original_docs = self._load(fs, pointer)[1]
            changed = {key for key in changed if key not in docs or key not in original_docs or docs[key]['value'] != original_docs[key]['value']}
            if not changed:
                from .preproduction import validate_content
                validate_content(self, fs, pid, docs, pointer, storyboard_submitted=any(
                    change['op'] == 'set_storyboard' for change in args['changes']))
                from .preproduction import validate_stored_scene_binding
                for change in args['changes']:
                    if change['op'] == 'put_scene':
                        validate_stored_scene_binding(self, fs, pointer, change['value'], docs)
                result = {'project': self._summary(pointer, original_docs), 'changed': [], 'invalidated': []}
                # A semantic no-op accepts an identity but advances no content or
                # document revision. Its single immutable receipt is atomic.
                noop = {'schema': 'motion/v1/project-noop', 'project_id': pid, 'request_id': args['request_id'], 'request_sha256': self._request_hash(args), 'pointer': pointer, 'result': result}
                validate(noop, D['ProjectNoop'])
                fs.write(noop_path, noop, replace=True)
                return result, self._context(pointer)
            # Never reuse an orphaned prepared revision number.
            allocated = [int(n) for n in fs.names(base + '/revisions') if n.isascii() and n.isdigit()]
            revision = max(allocated + [pointer['revision']]) + 1
            if revision > MAX_INT:
                raise ContractError('LIMIT_EXCEEDED', 'Project revision exhausted.')
            timestamp = _now()
            for key in list(changed):
                if key not in docs:
                    continue
                record = docs[key]
                if record['revision'] >= MAX_INT:
                    raise ContractError('LIMIT_EXCEEDED', 'Document revision exhausted.')
                record['revision'] += 1
                record['created_at'] = timestamp
                if key == ('settings', 'project'):
                    old = original_docs[key]['value']['gate_policy']
                    gate = record['value']['gate_policy']
                    if gate != old:
                        policy_key = ('gate_policy', gate['policy_id'])
                        prior_policy = docs.get(policy_key)
                        prior_revision = prior_policy['revision'] if prior_policy else 0
                        if prior_revision >= MAX_INT:
                            raise ContractError('LIMIT_EXCEEDED', 'Gate policy revision exhausted.')
                        gate['revision'] = prior_revision + 1
                        policy_record = {'schema': 'motion/v1/document', 'project_id': pid, 'kind': 'gate_policy', 'id': gate['policy_id'], 'revision': gate['revision'], 'created_at': timestamp, 'value': copy.deepcopy(gate)}
                        docs[policy_key] = policy_record
                        changed.add(policy_key)
            self._validate_content(fs, pid, docs, pointer, storyboard_submitted=any(
                change['op'] == 'set_storyboard' for change in args['changes']))
            from .preproduction import validate_stored_scene_binding
            for change in args['changes']:
                if change['op']=='put_scene':
                    key=change['value'].get('scene_id')
                    if key:validate_stored_scene_binding(self, fs, pointer, docs['scene',key]['value'], docs)
            new = {**pointer, 'revision': revision, 'updated_at': timestamp, 'manifest_path': f'revisions/{revision}/snapshot.json'}
            result = self._prepare(fs, new, docs, args, pointer, changed)
            fs.write(base + '/project.json', new, replace=True)
            return result, self._context(new)

    def _apply_changes(self, docs, changes):
        changed, writes, new_keys = set(), set(), {}
        # Resolve caller-local scene keys before processing timeline (order independent).
        for change in changes:
            if change['op'] == 'put_scene' and 'scene_id' not in change['value']:
                key = change['value'].get('new_scene_key')
                if key is not None:
                    if key in new_keys:
                        invalid('$.changes', 'unique new_scene_key', change)
                    new_keys[key] = _id('scn')
        for change in changes:
            op = change['op']
            value = copy.deepcopy(change.get('value'))
            if op == 'put_scene':
                sid = value.pop('new_scene_key', None)
                if sid is not None:
                    value['scene_id'] = new_keys[sid]
                elif 'scene_id' not in value:
                    value['scene_id'] = _id('scn')
                elif ('scene', value['scene_id']) not in docs:
                    raise ContractError('NOT_FOUND', 'Caller-supplied scene id is not owned by this project.')
                key = ('scene', value['scene_id'])
            elif op == 'remove_scene':
                key = ('scene', change['scene_id'])
                if key not in docs:
                    raise ContractError('NOT_FOUND', 'Scene is not owned by this project.')
            elif op == 'put_delivery_profile':
                key = ('delivery_profile', value['profile_id'])
            else:
                target = {'set_execution_policy': 'settings', 'set_gate_policy': 'settings', 'set_stage': 'settings', 'set_voice_preferences': 'settings'}.get(op, op.removeprefix('set_'))
                key = (target, 'project')
            # Settings is one authoritative document even when several fields differ.
            if key in writes:
                invalid('$.changes', 'one write per document/key', change)
            writes.add(key)
            changed.add(key)
            if op == 'remove_scene':
                del docs[key]
                continue
            if op == 'set_timeline':
                for track in value['tracks']:
                    for item in track['items']:
                        subject = item['subject']
                        if 'new_scene_key' in subject:
                            local = subject.pop('new_scene_key')
                            if local not in new_keys:
                                invalid('$.changes', 'new scene key defined in this transaction', subject)
                            subject['scene_id'] = new_keys[local]
            if op in ['set_execution_policy', 'set_gate_policy', 'set_stage', 'set_voice_preferences']:
                field = {'set_execution_policy': 'policy', 'set_gate_policy': 'gate_policy', 'set_stage': 'stage', 'set_voice_preferences': 'voice_preferences'}[op]
                if op == 'set_gate_policy':
                    policy_record = docs.get(('gate_policy', value['policy_id']))
                    expected = policy_record['revision'] if policy_record else 1
                    if value['revision'] != expected:
                        invalid('$.changes.value', 'owned policy revision or 1 for a new policy; core assigns next revision', value)
                docs[key]['value'][field] = value
            elif key in docs:
                docs[key]['value'] = value
            else:
                docs[key] = {'schema': 'motion/v1/document', 'project_id': docs['settings', 'project']['project_id'], 'kind': key[0], 'id': key[1], 'revision': 0, 'created_at': _now(), 'value': value}
        return changed

    def _validate_content(self, fs, pid, docs, previous=None, *, storyboard_submitted=False):
        from .editorial import validate_editorial
        if ('editorial', 'project') in docs:
            validate_editorial(self, fs, pid, docs, previous)
        from .creative import validate_plan
        if ('creative_plan', 'project') in docs:
            validate_plan(docs['creative_plan', 'project']['value'], docs)
        from .preproduction import validate_content
        validate_content(self, fs, pid, docs, previous, storyboard_submitted=storyboard_submitted)
        for record in docs.values():
            domain(record['value'])
        settings = docs['settings', 'project']['value']
        bindings = docs['bindings', 'project']['value']
        # Canonicalize the set without mutating a caller-shared preference list.
        # Preference order is semantic; selection order is not.
        bindings['selected_adapter_ids'] = sorted(bindings['selected_adapter_ids'])
        selected = set(bindings['selected_adapter_ids'])
        if any(v not in selected for values in bindings['preferences'].values() for v in values) or any(v not in selected for v in bindings['pins'].values()):
            invalid('$.bindings', 'preferences/pins must select a selected adapter', bindings)
        timeline = docs['timeline', 'project']['value']
        from .timeline import validate_timeline
        scenes={id_:doc['value'] for (kind,id_),doc in docs.items() if kind=='scene'}
        validate_timeline(timeline, settings['rate'], settings['sample_rate'], scenes=scenes)
        from .preproduction import validate_stored_scene_binding
        old_docs=self._load(fs, previous)[1] if previous else {}
        for scene_id,scene in scenes.items():
            old=old_docs.get(('scene',scene_id),{}).get('value')
            if old and old.get('storyboard_binding') and not scene.get('storyboard_binding'):
                raise ContractError('ASSETS_UNRESOLVED','Cannot remove a bound scene storyboard link.')
            if old != scene:
                validate_stored_scene_binding(self, fs, previous, scene, docs)
        seen_tracks, seen_items = set(), set()
        for track in timeline['tracks']:
            if track['track_id'] in seen_tracks:
                invalid('$.timeline.tracks', 'unique track IDs', track)
            seen_tracks.add(track['track_id'])
            intervals = []
            for item in track['items']:
                if item['item_id'] in seen_items:
                    invalid('$.timeline.items', 'globally unique item IDs', item)
                seen_items.add(item['item_id'])
                if not item['start_frame'] < item['end_frame'] <= timeline['duration_frames']:
                    raise ContractError('TIMING_INVALID', 'Timeline item must be nonempty and within duration.')
                if any(item['start_frame'] < end and start < item['end_frame'] for start, end in intervals):
                    raise ContractError('TIMING_INVALID', 'Overlapping track items require explicit composite/mixing support, outside B03.')
                intervals.append((item['start_frame'], item['end_frame']))
                if 'gain_db' in item and track['kind'] != 'audio':
                    invalid('$.timeline.items.gain_db', 'audio track only', item)
                subject = item['subject']
                if subject['kind'] == 'scene':
                    if track['kind'] != 'video' or ('scene', subject['scene_id']) not in docs:
                        raise ContractError('INVALID_GRAPH', 'Timeline scene must exist in this project on a video track.')
                    scene = docs['scene', subject['scene_id']]['value']
                    if item['end_frame'] - item['start_frame'] > scene['duration_frames']:
                        raise ContractError('TIMING_INVALID', 'Scene placement exceeds scene duration.')
                elif subject['kind'] == 'caption':
                    pin = subject['caption']
                    owned = docs.get(('caption', pin['id']))
                    found = owned is not None and owned['revision'] == pin['revision'] and digest(owned) == pin['sha256']
                    historical = previous
                    while not found and historical:
                        _, historical_docs = self._load(fs, historical)
                        owned = historical_docs.get(('caption', pin['id']))
                        found = owned is not None and owned['revision'] == pin['revision'] and digest(owned) == pin['sha256']
                        historical = self._transaction(fs, historical)['previous']
                    if track['kind'] != 'caption' or pin['kind'] != 'caption' or not found:
                        raise ContractError('INVALID_GRAPH', 'Timeline caption must pin an owned immutable caption on a caption track.')
                source = item.get('source_in')
                if source and source['origin'] == 'project':
                    expected = settings['rate'] if source['domain'] == 'frame' else {'num': settings['sample_rate'], 'den': 1}
                    if source['domain'] == 'source_tick' or source['rate'] != expected:
                        raise ContractError('TIMING_INVALID', 'Project time point rate/domain differs from settings.')
        variants = docs['variants', 'project']['value']
        if len({v['variant_id'] for v in variants}) != len(variants):
            invalid('$.variants', 'unique variant IDs', variants)
        for variant in variants:
            pin = variant['profile']
            key = ('delivery_profile', pin['id'])
            if pin['kind'] != 'delivery_profile' or key not in docs:
                raise ContractError('PROFILE_UNRESOLVED', 'Variant requires an owned delivery profile pin.')
            profile = docs[key]
            if profile['revision'] != pin['revision'] or digest(profile) != pin['sha256']:
                historical = previous
                found = False
                while historical:
                    _, historical_docs = self._load(fs, historical)
                    candidate = historical_docs.get(key)
                    if candidate and candidate['revision'] == pin['revision'] and digest(candidate) == pin['sha256']:
                        found = True
                        break
                    historical = self._transaction(fs, historical)['previous']
                if not found:
                    raise ContractError('PROFILE_UNRESOLVED', 'Variant delivery profile pin does not match committed immutable content.')
        # B04 owns artifact staging. Do not accept fabricated handles or turn a
        # caller artifact id into an arbitrary filename lookup.
        def check_refs(value):
            if isinstance(value, dict):
                if set(value) == {'artifact_id', 'sha256'}:
                    if previous is None:
                        raise ContractError('NOT_FOUND', 'No prior committed project can own this artifact pin.')
                    from .assets import AssetRegistry
                    AssetRegistry(self).artifact(fs, previous, value)
                    return
                for child in value.values():
                    check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)
        for record in docs.values():
            check_refs(record['value'])


# Exact UUID validation for receipt filenames, never a caller path.
from .contracts import UUID_PATTERN
DUMMY_UUID = '^' + UUID_PATTERN + '$'


def project_handler(args, **_host_context):
    """Native synchronous integration API: args mapping -> JSON result text."""
    runtime = _host_context.get('_runtime')
    result = runtime.project(args) if runtime is not None else ProjectStore().dispatch(args)
    return json.dumps(result, ensure_ascii=True, allow_nan=False)
