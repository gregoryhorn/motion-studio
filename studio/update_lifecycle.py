"""Capability-gated update coordinator; no private Hermes imports or installer.

This module defines a Studio-owned adapter contract, NOT an existing Hermes API.
The default adapter refuses before creating even a lock/journal directory. A real
adapter must implement every atomicity/identity guarantee documented alongside it.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Protocol, cast

from . import release

SUPPORTED_NATIVE_BOUNDARY = {
    'fresh_disabled_stage': 'hermes plugins install HTTPS_SOURCE --ref SHA40 --no-deps --no-enable',
    'binding': 'studio.setup.stage_native_disabled',
    'full_apply': 'unavailable: no public early-baseline all-generation CAS/activation receipt',
    'rollback': 'unavailable: no public retained checkpoint/transaction-owned restore command',
    'selected_pack_install': 'unavailable: Studio packs are not Hermes plugin-set packs',
}

REQUIRED_CAPABILITIES = frozenset({
    'immutable-stage-v1', 'early-baseline-cas-v1', 'retained-checkpoint-v1',
    'shared-environment-cas-v1', 'profile-activation-identity-v1',
    'isolated-scan-consent-v1', 'durable-native-recovery-v1',
    'studio-job-fence-v1',
})
TERMINAL = frozenset({'verified', 'rolled_back', 'failed_prepublication'})
TOKEN = r'^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,255}$'


class UpdateBlocked(RuntimeError):
    """A stable public reason, never a raw native exception/log."""


def need(ok, code):
    if not ok:
        raise UpdateBlocked(code)


@dataclass(frozen=True)
class Snapshot:
    """Native atomic observation of code AND shared environment generations."""
    identity: dict
    code_generation: str
    environment_generation: str
    metadata_generation: str
    clean: bool
    provenance_verified: bool


@dataclass(frozen=True)
class Prepared:
    token: str
    root: Path
    identity: dict
    scan_passed: bool
    compatibility_verified: bool
    no_pending_grants: bool
    dependencies_unchanged: bool
    capacity_verified: bool


@dataclass(frozen=True)
class RecoveryEvidence:
    """Durable native receipts, not inferred from matching filesystem bytes."""
    profile: str
    transaction: str
    published: Snapshot | None
    restored: Snapshot | None


@dataclass(frozen=True)
class Activation:
    profile: str
    process_instance: str
    identity: dict
    fresh_entrypoint_verified: bool
    public_capabilities_verified: bool
    failed_or_deferred: bool


class NativeTransactions(Protocol):
    """Implement only using a supported host boundary; never a shell copier.

    All calls must be bounded by the adapter. Tokens are durable opaque native
    references. inspect returns one consistent observation, not independently
    raced generations. prepare is isolated and enforces native trust/scan policy.
    checkpoint captures the exact expected code/environment and metadata; verify
    reads that retained checkpoint back. publish/restore atomically CAS ALL three
    generations and root identity against expected; inspect readback is mandatory.
    Restore must refuse unrelated/newer shared-environment changes. Every mutation
    is idempotent by transaction ID, recoverable after lost replies, and scoped to
    one profile. reconcile resolves any interrupted native publication first.
    activate verifies fresh installed entrypoint AND public capability identity.
    No host currently shipped with Studio is asserted to implement this protocol.
    """
    def capabilities(self) -> frozenset[str]: ...
    def inspect(self, profile: Path) -> Snapshot: ...
    def prepare(self, profile: Path, target: dict, transaction: str) -> Prepared: ...
    def checkpoint(self, profile: Path, expected: Snapshot, transaction: str) -> str: ...
    def verify_checkpoint(self, profile: Path, token: str, expected: Snapshot) -> bool: ...
    def publish(self, profile: Path, prepared: Prepared, expected: Snapshot,
                checkpoint: str, transaction: str) -> None: ...
    def reconcile(self, profile: Path, transaction: str) -> RecoveryEvidence: ...
    def restore(self, profile: Path, checkpoint: str, expected: Snapshot,
                transaction: str) -> None: ...
    def activate(self, profile: Path, identity: dict, transaction: str) -> Activation: ...


class UnavailableNative:
    def capabilities(self):
        return frozenset()


def descriptor(value):
    # Detach caller-owned mutable dictionaries; reject extra/invalid fields.
    return release.validate_descriptor(release.parse_json(release.canonical(value)))


def snapshot_value(value):
    need(isinstance(value, Snapshot), 'NATIVE_SNAPSHOT_INVALID')
    identity = descriptor(value.identity)
    for token in (value.code_generation, value.environment_generation, value.metadata_generation):
        need(isinstance(token, str) and re.fullmatch(TOKEN, token), 'NATIVE_GENERATION_INVALID')
    need(value.clean is True and value.provenance_verified is True, 'BASELINE_UNTRUSTED_OR_DIRTY')
    return dict(identity=identity, code_generation=value.code_generation,
                environment_generation=value.environment_generation,
                metadata_generation=value.metadata_generation, clean=True, provenance_verified=True)


def snapshot_from(value):
    result = Snapshot(**value)
    snapshot_value(result)
    return result


def activation_value(value, profile, identity):
    need(isinstance(value, Activation) and value.profile == str(profile) and
         isinstance(value.process_instance, str) and re.fullmatch(TOKEN, value.process_instance) and
         descriptor(value.identity) == identity and value.fresh_entrypoint_verified is True and
         value.public_capabilities_verified is True and value.failed_or_deferred is False,
         'ACTIVATION_IDENTITY_UNVERIFIED')
    return dict(profile=value.profile, process_instance=value.process_instance,
                identity=identity, verified=True)


class MaintenanceFence:
    """Journal directory paired with the canonical native update/work fence.

    Shared admission covers submission or the complete in-process worker, not
    queue residence. Workers reacquire and revalidate before effects. No detached
    executor/FD handoff is implemented. Status never acquires or creates locks.
    """
    def __init__(self, profile):
        self.profile = release.safe_path(profile)
        self.root = self.profile / 'plugin-data' / 'motion-studio'
        self.path = self.root / 'maintenance'

    def _directory(self):
        # Anchor each operation to descriptors; never follow swapped ancestors.
        fd = release.open_readonly(self.profile, directory=True)
        try:
            for name in ('plugin-data', 'motion-studio', 'maintenance'):
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                info = os.fstat(fd)
                need(info.st_uid == os.getuid() and not info.st_mode & 0o022,
                     'MAINTENANCE_DIRECTORY_UNSAFE')
            return fd
        except BaseException:
            os.close(fd)
            raise

    @contextmanager
    def hold(self, exclusive=False, recovery=False):
        # Lazy relative imports support both the plugin and the standalone
        # updater's private bundle package, without importing installed code.
        from .contracts import ContractError
        from .monitoring import native_work_fence
        try:
            # recovery bypasses only the durable pending marker, never the idle
            # ledger or kernel exclusion. It is exclusive-only at this boundary.
            need(not recovery or exclusive, 'RECOVERY_REQUIRES_EXCLUSIVE')
            with native_work_fence(self.root, exclusive=exclusive, recovery=recovery) as fd:
                directory = self._directory()
                try:
                    yield directory, fd
                finally:
                    os.close(directory)
        except ContractError as exc:
            code = {'LOCK_BUSY': 'UPDATE_OR_JOBS_BUSY',
                    'RECOVERY_REQUIRED': 'RECOVERY_REQUIRED'}.get(exc.code, exc.code)
            raise UpdateBlocked(code) from None

    @contextmanager
    def admission(self):
        with self.hold() as (_, fd):
            yield fd


def _read(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
             info.st_uid == os.getuid() and not info.st_mode & 0o077 and
             info.st_size <= release.MAX_JSON, 'JOURNAL_UNSAFE')
        data = bytearray()
        while len(data) <= release.MAX_JSON:
            part = os.read(fd, min(65536, release.MAX_JSON + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        return release.parse_json(bytes(data))
    finally:
        os.close(fd)


def _write(directory, name, value):
    # Bounded atomic replacement plus file AND directory durability.
    import secrets
    data = release.canonical(value)
    need(len(data) <= release.MAX_JSON, 'JOURNAL_TOO_LARGE')
    temporary = '.journal-' + secrets.token_hex(16)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            need(written > 0, 'JOURNAL_WRITE_FAILED')
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


class UpdateLifecycle:
    def __init__(self, profile, native=None):
        self.profile = release.safe_path(profile)
        self.native = cast(NativeTransactions, native if native is not None else UnavailableNative())
        self.fence = MaintenanceFence(self.profile)

    def _gate(self):
        need(os.name == 'posix', 'HOST_PLATFORM_UNSUPPORTED')
        need(REQUIRED_CAPABILITIES <= self.native.capabilities(), 'NATIVE_TRANSACTION_UNAVAILABLE')

    def _record(self, directory, journal, phase, **fields):
        journal.update(fields, phase=phase)
        _write(directory, journal['transaction'] + '.json', journal)
        # Markers point at journals, never embed raw host logs/settings/secrets.
        _write(directory, 'pending.json', dict(transaction=journal['transaction'], phase=phase))

    def _clear(self, directory):
        os.unlink('pending.json', dir_fd=directory)
        os.fsync(directory)

    def apply(self, target, baseline, approved_source):
        self._gate()  # Absolutely no writes (even locks) before native capability gate.
        baseline, target = release.immutable_update_pair(baseline, target, approved_source)
        transaction = release.digest(release.canonical(dict(profile=str(self.profile),
                                                            baseline=baseline, target=target)))
        with self.fence.hold(exclusive=True) as (directory, _):
            try:
                existing = _read(directory, transaction + '.json')
            except FileNotFoundError:
                existing = None
            if existing is not None:
                need(existing.get('phase') in TERMINAL, 'RECOVERY_REQUIRED')
                # Historical success must not masquerade as current activation.
                if existing['phase'] in ('verified', 'rolled_back'):
                    terminal_phase = existing['phase']
                    expected = existing['installed'] if terminal_phase == 'verified' else existing['restored']
                    current = self.native.inspect(self.profile)
                    need(snapshot_value(current) == expected, 'INSTALL_CHANGED')
                    self._record(directory, existing, 'activating')
                    try:
                        active = activation_value(self.native.activate(self.profile, expected['identity'], transaction),
                                                  self.profile, expected['identity'])
                        self._record(directory, existing, terminal_phase, active=active)
                        self._clear(directory)
                    except Exception:
                        self._record(directory, existing, 'recovery_required', error='ACTIVATION_IDENTITY_UNVERIFIED')
                        raise UpdateBlocked('RECOVERY_REQUIRED') from None
                return existing
            before = self.native.inspect(self.profile)
            baseline_snapshot = snapshot_value(before)
            need(baseline_snapshot['identity'] == baseline, 'BASELINE_CHANGED')
            journal = dict(schema='motion/studio-update-journal/v1', transaction=transaction,
                           profile=str(self.profile), baseline=baseline_snapshot, target=target,
                           checkpoint=None, installed=None, active=None, chat=None,
                           chat_action='fresh discovery/recompile required; frozen plans unchanged')
            self._record(directory, journal, 'preparing')
            try:
                prepared = self.native.prepare(self.profile, target, transaction)
                need(isinstance(prepared, Prepared) and isinstance(prepared.token, str) and
                     re.fullmatch(TOKEN, prepared.token) and descriptor(prepared.identity) == target,
                     'NATIVE_PREPARED_IDENTITY_INVALID')
                need(all(flag is True for flag in (prepared.scan_passed, prepared.compatibility_verified,
                     prepared.no_pending_grants, prepared.dependencies_unchanged, prepared.capacity_verified)),
                     'NATIVE_PREPARATION_BLOCKED')
                root = release.safe_path(prepared.root)
                live = self.profile / 'plugins' / 'motion-studio'
                need(root != live and live not in root.parents and root not in live.parents,
                     'STAGE_OVERLAPS_LIVE_TREE')
                release.verify_descriptor(root, target, approved_source)
                checkpoint = self.native.checkpoint(self.profile, before, transaction)
                need(isinstance(checkpoint, str) and re.fullmatch(TOKEN, checkpoint), 'CHECKPOINT_INVALID')
                need(self.native.verify_checkpoint(self.profile, checkpoint, before) is True,
                     'CHECKPOINT_UNVERIFIED')
                self._record(directory, journal, 'prepared', checkpoint=checkpoint)
            except Exception:
                self._record(directory, journal, 'failed_prepublication', error='PREPARATION_FAILED')
                self._clear(directory)
                raise UpdateBlocked('PREPARATION_FAILED') from None
            # Persist intent BEFORE native publication. Even a lost reply requires recovery.
            self._record(directory, journal, 'publishing')
            try:
                self.native.publish(self.profile, prepared, before, checkpoint, transaction)
                installed = self.native.inspect(self.profile)
                value = snapshot_value(installed)
                need(value['identity'] == target and
                     installed.environment_generation == before.environment_generation,
                     'PUBLISHED_IDENTITY_OR_ENVIRONMENT_MISMATCH')
                self._record(directory, journal, 'activating', installed=value)
                active = activation_value(self.native.activate(self.profile, target, transaction), self.profile, target)
                self._record(directory, journal, 'verified', active=active)
                self._clear(directory)
                return journal
            except Exception:
                self._record(directory, journal, 'rollback_pending', error='PUBLICATION_OR_ACTIVATION_FAILED')
                return self._restore(directory, journal)

    def _restore(self, directory, journal):
        transaction = journal['transaction']
        try:
            receipt = self.native.reconcile(self.profile, transaction)
            need(isinstance(receipt, RecoveryEvidence) and receipt.profile == str(self.profile) and
                 receipt.transaction == transaction, 'NATIVE_RECOVERY_RECEIPT_INVALID')
            before = snapshot_from(journal['baseline'])
            current = self.native.inspect(self.profile)
            current_value = snapshot_value(current)
            if receipt.published is not None:
                published = snapshot_value(receipt.published)
                need(published['identity'] == journal['target'] and
                     published['environment_generation'] == before.environment_generation,
                     'NATIVE_PUBLICATION_RECEIPT_INVALID')
                need(journal['installed'] is None or journal['installed'] == published,
                     'NATIVE_PUBLICATION_RECEIPT_CONFLICT')
                journal['installed'] = published
            if receipt.restored is not None:
                restored_receipt = snapshot_value(receipt.restored)
                need(restored_receipt['identity'] == before.identity and
                     restored_receipt['environment_generation'] == before.environment_generation and
                     restored_receipt == current_value, 'NATIVE_RESTORE_RECEIPT_CONFLICT')
                journal['restored'] = restored_receipt
            if journal.get('checkpoint') is None:
                need(current_value == journal['baseline'], 'UNEXPECTED_PREPUBLICATION_CHANGE')
                self._record(directory, journal, 'failed_prepublication', error='INTERRUPTED_PREPARATION')
                self._clear(directory)
                return journal
            if current_value != journal['baseline'] and current_value != journal.get('restored'):
                # No blind restore of local edits, newer releases or shared env.
                need(current_value['identity'] == journal['target'] and
                     current.environment_generation == before.environment_generation,
                     'ROLLBACK_CONFLICT')
                need(journal['installed'] is not None, 'PUBLICATION_OWNERSHIP_UNVERIFIED')
                need(current_value == journal['installed'], 'ROLLBACK_GENERATION_CONFLICT')
                # For interrupted publication, native reconcile/restore must bind
                # txn ownership too, not merely accept matching target bytes.
                need(self.native.verify_checkpoint(self.profile, journal['checkpoint'], before) is True,
                     'CHECKPOINT_UNVERIFIED')
                self._record(directory, journal, 'rolling_back')
                self.native.restore(self.profile, journal['checkpoint'], current, transaction)
            restored = snapshot_value(self.native.inspect(self.profile))
            need(restored['identity'] == before.identity and
                 restored['environment_generation'] == before.environment_generation,
                 'RESTORE_UNVERIFIED')
            active = activation_value(self.native.activate(self.profile, before.identity, transaction),
                                      self.profile, before.identity)
            self._record(directory, journal, 'rolled_back', restored=restored, active=active)
            self._clear(directory)
            return journal
        except Exception:
            self._record(directory, journal, 'recovery_required', error='NATIVE_RECOVERY_REQUIRED')
            raise UpdateBlocked('RECOVERY_REQUIRED') from None

    def rollback(self, transaction):
        self._gate()
        need(isinstance(transaction, str) and re.fullmatch(release.SHA, transaction), 'TRANSACTION_INVALID')
        with self.fence.hold(exclusive=True, recovery=True) as (directory, _):
            try:
                pending = _read(directory, 'pending.json')
            except FileNotFoundError:
                pending = None
            need(pending is None or pending.get('transaction') == transaction, 'OTHER_RECOVERY_PENDING')
            journal = _read(directory, transaction + '.json')
            need(journal.get('schema') == 'motion/studio-update-journal/v1' and
                 journal.get('transaction') == transaction and journal.get('profile') == str(self.profile),
                 'JOURNAL_IDENTITY_INVALID')
            need(journal.get('checkpoint') is not None or journal.get('phase') in
                 ('preparing', 'failed_prepublication', 'recovery_required'), 'NO_RETAINED_CHECKPOINT')
            self._record(directory, journal, 'rollback_pending')
            return self._restore(directory, journal)

    def status(self, transaction):
        """Read-only journal observation; never reconcile, activate or create paths."""
        need(isinstance(transaction, str) and re.fullmatch(release.SHA, transaction), 'TRANSACTION_INVALID')
        path = release.safe_path(self.fence.path)
        directory = release.open_readonly(path, directory=True)
        try:
            return _read(directory, transaction + '.json')
        finally:
            os.close(directory)
