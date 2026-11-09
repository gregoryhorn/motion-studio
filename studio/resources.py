"""Shared kernel admission and capability-gated service ownership.

Providers are trusted code, not project commands. A provider must reserve the
actual service/device before preparation, and must atomically enforce its own
consumers/ownership when consuming an unload authorization. Studio never kills a
service, guesses readiness from file presence, or unloads on lease exit.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import copy
import fcntl
import math
import os
import stat
from pathlib import Path
import time
import uuid
from typing import Any

from .contracts import ContractError, digest
from .project import ManagedFS, _now

_PROVIDERS = {}


def register_provider(resource, provider):
    """Register supported trusted service code; no connections occur here.

    acquire(model, owner=..., lifecycle=...) must reserve this owner at the
    service/device without loading; return model/owner/lifecycle/acquired=True
    and a nonempty service_id. release removes only that reservation. prepare
    must refuse replacing another consumer's model, even outside Studio.
    """
    if not isinstance(resource, str) or not resource or resource in _PROVIDERS:
        raise ValueError('Resource must be a unique nonempty identity.')
    if not all(callable(getattr(provider, name, None)) for name in ('status', 'acquire', 'prepare', 'release')):
        raise TypeError('Lifecycle provider needs status, acquire, prepare and release methods.')
    _PROVIDERS[resource] = provider


def provider_capabilities(resource):
    """Passive code capability report, never a resident-readiness claim."""
    provider = _PROVIDERS.get(resource)
    supported = provider is not None and all(callable(getattr(provider, n, None))
        for n in ('status', 'acquire', 'prepare', 'release'))
    return dict(provider_configured=provider is not None, ownership_supported=supported,
        unload_supported=supported and all(callable(getattr(provider, n, None))
            for n in ('authorize_unload', 'unload')), readiness='not_observed' if supported else 'unknown')


def _identity(resource):
    if not isinstance(resource, str) or not resource.strip():
        raise ContractError('INVALID_ARGUMENT', 'Resource must be an exact nonempty string identity.')


def _open_lock(directory, *, create=False):
    fd = os.open('admission.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK |
        (os.O_CREAT if create else 0), 0o600, dir_fd=directory)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ContractError('PATH_UNSAFE', 'Admission lock must be a regular single-link file.')
    os.set_inheritable(fd, False)
    return fd


def _exact_status(observed, model, service_id):
    return (isinstance(observed, dict) and observed.get('model') == model
            and observed.get('service_id') == service_id)


def _requires_recovery(record):
    return bool(record and (
        record.get('release_error_code') is not None
        or record.get('service_ownership') in ('release_failed', 'reservation_unconfirmed')
        or (record.get('state') in ('active', 'preparing', 'interrupted')
            and record.get('model') is not None)))


class OwnedProcessModelLifecycle:
    """Concrete one-shot CLI lifecycle, bound to the existing attempt worker.

    WorkerContext owns admission, spawning and cgroup cleanup. This object does
    not load models or signal PIDs: it keeps that cleanup inside the shared lease
    and requires exact-child wait plus the worker's successful tree-release receipt.
    It is NOT a resident provider and never claims persistent model readiness.
    """
    def __init__(self, worker, model):
        if not all(callable(getattr(worker, name, None)) for name in ('run', 'cleanup')):
            raise ContractError('PERMISSION_DENIED', 'Process-scoped model requires an owned worker.')
        self.worker, self.model = worker, model
        self.closed = False
        self.release_error = None
        self.termination: dict[str, Any] = dict(state='not_started', basis='no_owned_child_observed')
        self.children = []
        self._last_process = None

    def _finish(self):
        if self.release_error is not None:
            raise self.release_error
        try:
            self.worker.cleanup()
            process = self.worker.process
            if process is None:
                return dict(state='not_started', basis='no_owned_child_observed')
            # This is the exact Popen held by WorkerContext, never a PID recovered
            # from disk. Waiting alone proves only the leader; released_at is
            # published only after successful owned-tree cleanup in WorkerContext.
            returncode = process.wait(timeout=5)
            snapshot = self.worker.resource_snapshot
            if (self.worker.limits is not None or not isinstance(snapshot, dict)
                    or not snapshot.get('released_at') or type(returncode) is not int):
                raise ContractError('DEPENDENCY_UNAVAILABLE', 'Owned process tree release was not verified.')
            child = dict(pid=process.pid, returncode=returncode,
                released_at=snapshot['released_at'],
                basis='worker_owned_tree_cleanup_and_child_wait')
            if process is not self._last_process:
                self.children.append(child)
                self._last_process = process
            self.termination = dict(state='verified', **child,
                children=copy.deepcopy(self.children))
            return copy.deepcopy(self.termination)
        except BaseException as exc:
            self.release_error = exc
            self.termination = dict(state='unverified', basis='owned_process_cleanup_failed')
            raise

    def run(self, argv, **kwargs):
        if self.closed:
            raise ContractError('PERMISSION_DENIED', 'Owned model lifecycle is closed.')
        if self.release_error is not None:
            raise self.release_error
        if len(self.children) >= 32:
            raise ContractError('LIMIT_EXCEEDED', 'Owned audio lifecycle child bound exceeded.')
        # Each serial engine/decoder child needs fresh evidence. Never accept a
        # previous child's successful snapshot after a later cleanup failure.
        previous_process = self.worker.process
        previous_snapshot = copy.deepcopy(self.worker.resource_snapshot)
        self.worker.resource_snapshot = None
        primary_error = None
        try:
            return self.worker.run(argv, **kwargs)
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                # A refusal before a new child starts does not invalidate the
                # exact previous child's verified release. Reuse evidence only
                # for that unchanged Popen, with no new context or snapshot.
                # A new child or cleanup failure still needs fresh evidence.
                if (isinstance(primary_error, ContractError)
                        and getattr(self.worker, 'admission_failure', False) is True
                        and previous_process is self._last_process
                        and previous_process is not None
                        and self.worker.process is previous_process
                        and self.worker.limits is None
                        and self.worker.resource_snapshot is None
                        and self.termination.get('state') == 'verified'):
                    self.worker.resource_snapshot = previous_snapshot
                self._finish()
            except BaseException:
                if primary_error is None:
                    raise

    def release(self):
        try:
            return self._finish()
        finally:
            self.closed = True


class ResourceCoordinator:
    def __init__(self, root=None):
        # Deliberately outside HERMES_HOME/profile directories: profiles for the
        # same OS user must use this one host resource namespace.
        self.fs = ManagedFS(Path(root) if root else Path.home() / '.local/state/motion-studio/resources')

    @staticmethod
    def _path(resource):
        _identity(resource)
        return digest(resource).split(':', 1)[1]

    def _record(self, path) -> dict[str, Any] | None:
        try:
            value = self.fs.read(path + '/state.json')
        except FileNotFoundError:
            return None
        except (ValueError, UnicodeError):
            raise ContractError('OUTPUT_INVALID',
                'Shared resource receipt is unreadable; admission remains closed.') from None
        if not isinstance(value, dict) or not isinstance(value.get('state'), str):
            raise ContractError('OUTPUT_INVALID',
                'Shared resource receipt is invalid; admission remains closed.')
        return value

    @contextmanager
    def lease(self, resource, *, owner, worker=None, timeout=300, model=None, lifecycle=None):
        if not resource:
            yield None
            return
        path = self._path(resource)
        if not owner or (model is not None and (not isinstance(model, str) or not model)):
            raise ContractError('INVALID_ARGUMENT', 'Lease requires an owner and exact model identity.')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ContractError('INVALID_ARGUMENT', 'Lease timeout must be finite and nonnegative.')
        provider = _PROVIDERS.get(resource)
        lifecycle = lifecycle or ('resident' if model is not None or provider is not None else 'process_scoped')
        if lifecycle not in ('resident', 'process_scoped') or (lifecycle == 'resident' and model is None):
            raise ContractError('INVALID_ARGUMENT', 'Resident lifecycle needs an exact model identity.')
        owner = copy.deepcopy(owner)
        started = time.monotonic()
        with self.fs.directory(path, create=True) as directory:
            fd = _open_lock(directory, create=True)
            try:
                while True:
                    if worker is not None:
                        worker.heartbeat()
                        current = worker.store.read(worker.pid, worker.jid)
                        if current['job']['cancel']['requested']:
                            raise ContractError('PERMISSION_DENIED', 'Resource wait cancelled.')
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        remaining = timeout - (time.monotonic() - started)
                        if remaining <= 0:
                            raise ContractError('RESOURCE_BUSY', 'Shared resource remains in use; no competing load was started.')
                        time.sleep(min(0.1, remaining))
                previous = self._record(path)
                # Releasing the OS lock is not proof that a failed process tree
                # or provider reservation disappeared. Preserve its durable
                # quarantine instead of allowing the next worker to overwrite
                # the only recovery evidence and start a competing model.
                if _requires_recovery(previous):
                    raise ContractError('RESOURCE_BUSY',
                        'Previous model ownership or cleanup is unresolved; '
                        'explicit owner-qualified recovery is required.')
                receipt: dict[str, Any] = dict(schema='motion/v1/resource-lease', resource=resource,
                    lease_id='lease-' + uuid.uuid4().hex, owner=owner, model=model,
                    acquired_at=_now(), released_at=None, state='preparing',
                    active_lease_count=1, reused=False,
                    previous_owner_interrupted=bool(previous and previous.get('state') in ('active', 'preparing')),
                    lifecycle=lifecycle, provider_configured=provider is not None,
                    readiness='unknown' if lifecycle == 'resident' else 'not_applicable',
                    service_id=None, service_ownership='not_configured' if provider is None else 'not_confirmed',
                    readiness_observed_at=None, readiness_basis='not_observed',
                    error_code=None, release_error_code=None)
                self.fs.write(path + '/state.json', receipt, replace=True)
                ownership_attempted = False
                ownership_confirmed = False
                primary_error = None
                process_lifecycle = None
                try:
                    if provider is None and lifecycle == 'resident':
                        raise ContractError('DEPENDENCY_UNAVAILABLE', 'Resident provider not configured; readiness is unknown.')
                    if provider is not None:
                        if not provider_capabilities(resource)['ownership_supported']:
                            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Provider has no supported service ownership interface.')
                        ownership_attempted = True
                        reservation = provider.acquire(model, owner=copy.deepcopy(owner), lifecycle=lifecycle)
                        if (not isinstance(reservation, dict) or reservation.get('model') != model
                                or reservation.get('owner') != owner or reservation.get('lifecycle') != lifecycle
                                or reservation.get('acquired') is not True
                                or not isinstance(reservation.get('service_id'), str) or not reservation['service_id']):
                            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Provider did not confirm exact owner/service reservation.')
                        ownership_confirmed = True
                        receipt['service_id'] = reservation['service_id']
                        receipt['service_ownership'] = 'owner_reserved'
                        if lifecycle == 'resident':
                            observed = provider.status(model)
                            if (not _exact_status(observed, model, receipt['service_id'])
                                    or type(observed.get('ready')) is not bool
                                    or type(observed.get('loaded')) is not bool
                                    or (observed['ready'] and not observed['loaded'])):
                                raise ContractError('DEPENDENCY_UNAVAILABLE', 'Provider returned no exact model/service evidence.')
                            if observed.get('ready') is True:
                                receipt['reused'] = True
                            else:
                                provider.prepare(model, owner=copy.deepcopy(owner))
                            observed = provider.status(model)
                            if (not _exact_status(observed, model, receipt['service_id'])
                                    or observed.get('ready') is not True or observed.get('loaded') is not True):
                                raise ContractError('DEPENDENCY_UNAVAILABLE', 'Model did not reach verified readiness.')
                            receipt.update(readiness='verified', readiness_observed_at=_now(),
                                readiness_basis='provider_evidence_at_lease_admission_not_live_probe')
                    receipt['state'] = 'active'
                    if lifecycle == 'process_scoped' and model is not None and worker is not None:
                        if getattr(worker, 'model_process_lifecycle', None) is not None:
                            raise ContractError('PERMISSION_DENIED', 'Worker already has a model lifecycle lease.')
                        process_lifecycle = OwnedProcessModelLifecycle(worker, model)
                        worker.model_process_lifecycle = process_lifecycle
                        receipt['process_termination'] = dict(state='pending', basis='lease_active')
                    self.fs.write(path + '/state.json', receipt, replace=True)
                    yield copy.deepcopy(receipt)
                except BaseException as exc:
                    primary_error = exc
                    receipt.update(state='failed', error_code=getattr(exc, 'code', 'EXECUTION_FAILED'))
                    raise
                finally:
                    # Retain the primary engine/cancellation error if owner-only
                    # cleanup also fails. No exception strings or service tokens
                    # enter the passive diagnostics record.
                    release_error = None
                    try:
                        # The shared lease and any optional service reservation
                        # must outlive the actual CLI tree, including exceptions.
                        if process_lifecycle is not None:
                            receipt['process_termination'] = process_lifecycle.release()
                        if ownership_confirmed:
                            provider.release(model, owner=copy.deepcopy(owner))
                    except BaseException as exc:
                        release_error = exc
                        if process_lifecycle is not None:
                            receipt['process_termination'] = copy.deepcopy(process_lifecycle.termination)
                        receipt.update(state='failed', release_error_code=getattr(exc, 'code', 'EXECUTION_FAILED'))
                        if primary_error is None:
                            receipt['error_code'] = receipt['release_error_code']
                    finally:
                        if process_lifecycle is not None and worker is not None:
                            worker.model_process_lifecycle = None
                        if receipt['state'] != 'failed':
                            receipt['state'] = 'idle'
                        receipt.update(released_at=_now(), active_lease_count=0)
                        if ownership_confirmed:
                            receipt['service_ownership'] = 'release_failed' if release_error is not None else 'owner_released'
                        elif ownership_attempted:
                            receipt['service_ownership'] = 'reservation_unconfirmed'
                        # Cached readiness is historical evidence, not a live probe.
                        if receipt['readiness'] == 'verified':
                            receipt['last_readiness'] = 'verified'
                            receipt['readiness'] = 'not_observed'
                        self.fs.write(path + '/state.json', receipt, replace=True)
                    if release_error is not None and primary_error is None:
                        raise release_error
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def status(self, resource) -> dict[str, Any]:
        """Read-only lock/receipt projection; never calls a provider or repairs state."""
        path = self._path(resource)
        record: dict[str, Any] | None = self._record(path)
        capabilities = provider_capabilities(resource)
        if record is None:
            return dict(resource=resource, state='unknown', active_lease_count=None,
                        lock_held=None, **capabilities)
        with self.fs.directory(path) as directory:
            fd = _open_lock(directory)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    record['lock_held'] = True
                    record['active_lease_count'] = 1
                    # Lock may have changed owner since the first record read.
                    record = dict(self._record(path) or record, lock_held=True, active_lease_count=1)
                else:
                    record = self._record(path) or record
                    record.update(lock_held=False, active_lease_count=0)
                    if record['state'] in ('active', 'preparing'):
                        record['state'] = 'interrupted'
                    if record.get('readiness') == 'verified':
                        record.update(last_readiness='verified', readiness='not_observed')
            finally:
                os.close(fd)
        record.update(provider_configured=capabilities['provider_configured'],
            ownership_supported=capabilities['ownership_supported'], unload_supported=capabilities['unload_supported'])
        record['recovery_required'] = not record['lock_held'] and _requires_recovery(record)
        record['admission_blocker'] = ('RESOURCE_RECOVERY_REQUIRED'
            if record['recovery_required'] else None)
        return record

    def unload(self, resource, *, model, owner):
        _identity(resource)
        if not isinstance(model, str) or not model or not owner:
            raise ContractError('INVALID_ARGUMENT', 'Unload needs exact model and owner identity.')
        provider = _PROVIDERS.get(resource)
        if not provider_capabilities(resource)['unload_supported']:
            raise ContractError('UNSUPPORTED_OPERATION', 'No supported service-level unload authorization; shared services are untouched.')
        path = self._path(resource)
        with self.fs.directory(path, create=True) as directory:
            fd = _open_lock(directory, create=True)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ContractError('RESOURCE_BUSY', 'Active lease prevents model unload.') from None
                authorization = provider.authorize_unload(model, owner=copy.deepcopy(owner))
                if (not isinstance(authorization, dict) or authorization.get('model') != model
                        or authorization.get('owner') != owner or authorization.get('owned') is not True
                        or type(authorization.get('active_consumer_count')) is not int
                        or authorization['active_consumer_count'] != 0
                        or authorization.get('safe_to_unload') is not True
                        or not isinstance(authorization.get('service_id'), str) or not authorization['service_id']
                        or not isinstance(authorization.get('authorization'), str) or not authorization['authorization']):
                    raise ContractError('PERMISSION_DENIED', 'No exact service-level ownership/no-consumers authorization.')
                # The provider MUST consume this authorization atomically with its
                # native service consumer registry/CAS; a passive check is not enough.
                provider.unload(model, owner=copy.deepcopy(owner), authorization=copy.deepcopy(authorization))
                observed = provider.status(model)
                if not _exact_status(observed, model, authorization['service_id']) or observed.get('loaded') is not False:
                    raise ContractError('DEPENDENCY_UNAVAILABLE', 'Provider did not confirm exact model/service unload.')
                self.fs.write(path + '/state.json', dict(resource=resource, model=model,
                    state='unloaded', readiness='not_observed', provider_configured=True,
                    service_id=authorization['service_id'], active_lease_count=0, unloaded_at=_now()), replace=True)
                return observed
            finally:
                os.close(fd)


def adapter_lease(adapter, worker, request):
    needs = getattr(adapter, 'resource_requirements', None)
    lifecycle = None
    if not callable(needs):
        runtime = getattr(adapter, 'runtime', None)
        if runtime is None:
            return nullcontext()
        entry = runtime.registry.inspect(request['binding']['adapter_id'])
        resource = entry['declaration']['resource_needs']['exclusive_resource']
        model = None
    else:
        value = needs(request)
        if not isinstance(value, dict) or set(value) - {'resource', 'model', 'lifecycle'}:
            raise ContractError('INVALID_ARGUMENT', 'Adapter resource declaration must contain only resource/model/lifecycle.')
        resource, model, lifecycle = value.get('resource'), value.get('model'), value.get('lifecycle')
    if not resource:
        return nullcontext()
    options = dict(model=model, worker=worker,
        owner=dict(project_id=worker.pid, job_id=worker.jid, attempt_id=worker.aid))
    if lifecycle is not None:
        options['lifecycle'] = lifecycle
    return ResourceCoordinator().lease(resource, **options)
