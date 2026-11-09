"""Durable B07 jobs. No startup/poll/read path launches work.

Integration boundaries are injected, not invented Hermes APIs: plan_reader(pid,
pin), authority.authorize(plan,args), adapter_resolver(frozen_binding). Authority
must supply an auditable evidence reference bound to the exact plan and effects.
Default native execution is denied until a real host approval bridge is wired.
One atomic ManagedFS job manifest owns attempts, handoffs, artifacts and request
receipts; no independent best-effort dedup index or second transaction engine.
"""
from __future__ import annotations

import copy
from contextvars import copy_context
from functools import partial
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import threading
import uuid
import socket

from .contracts import (ContractError, D, canonical, digest, validate, safe_relative,
                        obj, arr, enum, integer, nullable, ident, TEXT, DIGEST, STAMP, BOOL)
from .project import ProjectStore, _id, _now
from .monitoring import project_monitor, retain_error, sanitize, native_work_fence

STATES = ('planned', 'queued', 'running', 'awaiting_external', 'review_needed', 'succeeded', 'failed', 'cancelled', 'interrupted')
TERMINAL = frozenset(('succeeded', 'failed', 'cancelled', 'interrupted'))
SUBMISSION = enum('not_sent', 'intent_recorded', 'confirmed', 'uncertain')
REMOTE = enum('none', 'running', 'succeeded', 'failed', 'cancelled', 'unknown')
PLAN_REF = obj({'plan_id': ident('pln'), 'plan_revision': integer(1), 'plan_sha256': DIGEST})
CANCEL = obj({'requested': BOOL, 'requested_at': nullable(STAMP), 'disposition': enum('not_requested', 'pending', 'confirmed', 'unsupported', 'too_late', 'unknown'), 'external_may_continue': BOOL})
# Error remains a closed core schema from the shared contracts registry.
ERROR = nullable(obj({'code': TEXT, 'message': TEXT, 'details': {'type': 'object', 'additionalProperties': {}}, 'retry': enum('never', 'after_input_change', 'after_authority', 'after_dependency', 'after_reconcile', 'same_request'), 'effect': enum('none', 'committed', 'partial', 'unknown'), 'logs_ref': D['ArtifactRef']}, optional=['logs_ref']))
NODE_STATE = obj({'node_id': ident('nod'), 'state': enum(*STATES), 'attempt_id': nullable(ident('att')), 'reused': arr(D['ArtifactRef']), 'outputs': arr(D['ArtifactRef']), 'blocked_reason': nullable(TEXT)})
JOB_RECORD = obj({'schema': {'const': 'motion/v1/job'}, 'job_id': ident('job'), 'project_id': ident('prj'), 'project_revision': integer(1), 'job_revision': integer(1), 'plan': PLAN_REF, 'request_id': TEXT, 'request_sha256': DIGEST, 'created_at': STAMP, 'updated_at': STAMP, 'state': enum(*STATES), 'node_states': arr(NODE_STATE), 'attempt_ids': arr(ident('att')), 'outputs': arr(D['ArtifactRef']), 'stale': BOOL, 'stale_reasons': arr(TEXT), 'cancel': CANCEL, 'submission_state': SUBMISSION, 'remote_state': REMOTE, 'authority_evidence_ref': TEXT, 'error': ERROR})
OWNER = obj({'worker_token': TEXT, 'pid': nullable(integer(1)), 'process_started_at': nullable(TEXT), 'boot_id': nullable(TEXT), 'lease_expires_at': STAMP})
ATTEMPT_RECORD = obj({'schema': {'const': 'motion/v1/attempt'}, 'attempt_id': ident('att'), 'job_id': ident('job'), 'node_id': ident('nod'), 'attempt_number': integer(1), 'request_sha256': DIGEST, 'started_at': nullable(STAMP), 'ended_at': nullable(STAMP), 'owner': OWNER, 'submission_state': SUBMISSION, 'provider_request_key': TEXT, 'external_handle': nullable(TEXT), 'remote_state': REMOTE, 'output_dir': TEXT, 'error': ERROR})


def _error(code, message, effect='unknown'):
    # Adapter diagnostics use the same structured Error shape as core.
    return {'code': code, 'message': sanitize(message), 'details': {}, 'retry': 'after_reconcile', 'effect': effect}


def _hash_args(args):
    return digest({'tool': 'motion_run', **{k: v for k, v in args.items() if k != 'request_id'}})


def _lease():
    return (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _proc_identity(pid):
    """Linux start ticks + boot identity; PID alone is never sufficient."""
    raw = Path(f'/proc/{pid}/stat').read_text()
    fields = raw[raw.rfind(')') + 2:].split()
    return fields[19], Path('/proc/sys/kernel/random/boot_id').read_text().strip(), fields[0]


def _pulse_worker(worker, stop, *, interval: float=5):
    """Retry transient renewals, but close child admission after bounded failure."""
    failures = 0
    while not stop.wait(interval):
        try:
            worker.heartbeat()
            failures = 0
        except (ContractError, OSError) as exc:
            code = getattr(exc, 'code', 'STORAGE_UNSUPPORTED')
            failures += 1
            worker.record_failure(code)
            if code == 'PERMISSION_DENIED' or failures >= 3:
                worker.failure = code
                return


class WorkerContext:
    """Private registered-adapter capability. Never exposed as shell RPC."""
    def __init__(self, store, pid, jid, aid):
        self.store, self.pid, self.jid, self.aid = store, pid, jid, aid
        self.process = None
        self.failure = None
        self.limits = None
        self.resource_snapshot = None
        self.admission_failure = False
        self.native_requirements = {}
        self.gpu_route = None
        self.resource_paths = []
        self._limits_lock = threading.RLock()

    @contextmanager
    def resource_scope(self, adapter, request):
        """Use a validated installed adapter for one serial reconstruction node.

        This is internal worker plumbing, not caller-selected resource authority.
        Every child still obtains fresh locked admission and its normal kernel
        fence. Never replace the resource identity of an active owned child.
        """
        with self._limits_lock:
            live_child = self.process is not None and self.process.poll() is None
            if live_child or self.limits is not None:
                raise ContractError('PERMISSION_DENIED', 'Active owned execution cannot switch resource identity.')
            previous = (copy.deepcopy(self.native_requirements), self.gpu_route,
                        list(self.resource_paths))
        try:
            self.configure_resources(adapter, request)
            yield
        finally:
            # Revoke the scoped identity only after all owned children are gone.
            self.cleanup()
            with self._limits_lock:
                self.native_requirements, self.gpu_route, self.resource_paths = previous

    def configure_resources(self, adapter, request):
        """Use already-validated runtime metadata, not caller-selected budgets."""
        runtime = getattr(adapter, 'runtime', None)
        if runtime is None:
            return  # Injected non-native adapters still cannot bypass spawn admission.
        from .diagnostics import host_requirements
        declaration = runtime.registry.inspect(request['binding']['adapter_id'])['declaration']
        self.native_requirements = host_requirements(declaration['resource_needs'])
        from .gpu_route import for_adapter
        self.gpu_route = for_adapter(adapter, request)
        def inputs(value):
            if isinstance(value, dict):
                if set(value) == {'artifact_id', 'sha256'}:
                    self.resource_paths.append(str(runtime.artifact_path(self.pid, value)))
                else:
                    for child in value.values():
                        inputs(child)
            elif isinstance(value, list):
                for child in value:
                    inputs(child)
        inputs(request['inputs'])

    def phase(self, phase, **metadata):
        fs = self.store.projects._filesystem(write=True)
        with self.store._worker_lock(fs, self.pid):
            bundle = self.store.read(self.pid, self.jid)
            monitor = bundle.setdefault('monitoring', {})
            monitor['phase'] = phase
            # No new measurement must not erase the last admission evidence.
            if 'resources' in metadata and metadata['resources'] is None:
                metadata.pop('resources')
            monitor.update(sanitize(metadata))
            self.store._commit(fs, bundle)

    def cleanup(self):
        with self._limits_lock:
            return self._cleanup_limits()

    def _cleanup_limits(self):
        """Only the kernel-enforced owned tree, never a recovered arbitrary PID."""
        if self.limits is not None:
            limits, self.limits = self.limits, None
            try:
                measured = sanitize(limits.measurements())
                if not isinstance(measured, dict):
                    raise ContractError('OUTPUT_INVALID', 'Owned resource measurements must be an object.')
                measured['observed_at'] = _now()
            finally:
                limits.__exit__(None, None, None)
            measured['released_at'] = _now()
            self.resource_snapshot = measured

    def spawn(self, argv, *, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, requirements=None):
        if self.failure:
            raise ContractError('PERMISSION_DENIED', 'Worker renewal failed; child admission closed.',
                                details={'heartbeat_error': self.failure})
        if self.process is not None and self.process.poll() is None:
            raise ContractError('UNSUPPORTED_OPERATION', 'Only one live owned child per attempt.')
        fs = self.store.projects._filesystem(write=True)
        # Cancel intent and each serial child's admission share the job lock:
        # cancellation cannot slip between its check and ownership publication.
        with self.store._worker_lock(fs, self.pid):
            bundle = self.store.read(self.pid, self.jid)
            if bundle['job']['cancel']['requested'] or bundle['job']['state'] != 'running':
                raise ContractError('PERMISSION_DENIED', 'Cancelled/non-running attempt cannot spawn.')
            attempt = bundle['attempts'][self.aid]
            env = dict(os.environ, MOTION_WORKER_TOKEN=attempt['owner']['worker_token'])
            # No raw Popen fallback: unknown enforcement refuses native execution.
            # Synthetic, non-spawning adapters need no host admission.
            # One enforced context per serial subprocess tree.
            self.cleanup()
            try:
                self._admit_native(fs, bundle, attempt, requirements=requirements)
            except ContractError:
                self.admission_failure = True
                raise
            if self.limits is None:
                raise ContractError('DEPENDENCY_UNAVAILABLE', 'Native process limits were not established.')
            try:
                with fs.directory(attempt['output_dir'], create=True) as fd:
                    wrapped, extra = self.limits.prepare_spawn(argv)
                    proc = subprocess.Popen(wrapped, cwd=f'/proc/self/fd/{fd}',
                                            pass_fds=(fd, *extra['pass_fds']), env=env,
                                            start_new_session=True, stdin=stdin, stdout=stdout, stderr=stderr)
            except BaseException:
                self.cleanup()
                raise
            self.process = proc
            try:
                start, boot, _ = _proc_identity(proc.pid)
                attempt['owner'].update(pid=proc.pid, process_started_at=start, boot_id=boot)
                self.store._commit(fs, bundle)
            except BaseException:
                self.cleanup()
                raise
        return proc

    def _admit_native(self, fs, bundle, attempt, *, requirements=None):
        try:
            from .host_safety import admission, OwnedProcessLimits
        except ImportError:
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Kernel-enforced native execution boundary is unavailable.') from None
        # Enter refreshes advisory measurements under the kernel admission lock.
        paths = list(dict.fromkeys([str(fs.root), str(fs.root / attempt['output_dir']),
                                   *self.resource_paths, os.environ.get('TMPDIR', str(fs.root))]))
        if self.native_requirements.get('gpu') and (requirements or {}).get('gpu') is False:
            raise ContractError('PERMISSION_DENIED', 'Frozen native GPU requirements cannot be downgraded.')
        route_args = {'gpu_route': self.gpu_route} if self.gpu_route is not None else {}
        policy = admission(paths=tuple(paths), requirements=dict(self.native_requirements, **(requirements or {})),
                           **route_args)
        bundle.setdefault('monitoring', {})['resources'] = sanitize(policy)
        self.store._commit(fs, bundle)
        try:
            # Publish only a successfully entered context; failed __enter__ must
            # not be mistaken for owned resources by heartbeat/final cleanup.
            limits = OwnedProcessLimits(policy, **route_args)
            limits.__enter__()
            self.limits = limits
            bundle['monitoring']['resources'] = sanitize(self.limits.policy)
            self.store._commit(fs, bundle)
        except BaseException as exc:
            self.cleanup()
            # __enter__ refreshes admission under its lock. On refusal its
            # structured policy is newer than the advisory snapshot above.
            if (isinstance(exc, ContractError) and exc.code == 'RESOURCE_BUSY'
                    and exc.details.get('allowed') is False):
                bundle['monitoring']['resources'] = sanitize(exc.details)
                self.store._commit(fs, bundle)
            raise

    def run(self, argv, *, input=None, timeout=None, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, requirements=None):
        """Trusted adapter subprocess.run equivalent with serial owned children."""
        proc = self.spawn(argv, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                          stdout=stdout, stderr=stderr, requirements=requirements)
        out, err, overflow = self._capture(proc, input=input, timeout=timeout)
        result = subprocess.CompletedProcess(argv, proc.returncode, out, err)
        if result.returncode:
            self._engine_failure('ENGINE_EXIT', 'Engine exited with code ' + str(result.returncode) + '.',
                                 stderr=err, returncode=result.returncode)
        if overflow:
            raise ContractError('LIMIT_EXCEEDED', 'Engine stdout exceeded the 1 MiB capture bound; output was not accepted.')
        if check:
            result.check_returncode()
        return result

    def _engine_failure(self, code, message, *, stderr=None, **details):
        fs = self.store.projects._filesystem(write=True)
        with self.store._worker_lock(fs, self.pid):
            bundle = self.store.read(self.pid, self.jid)
            error = _error(code, message)
            tail = stderr[-4096:].decode('utf-8', 'replace') if isinstance(stderr, bytes) else stderr
            error['details'] = sanitize(dict(details, stderr=tail))
            retain_error(bundle, error, attempt_id=self.aid, source='engine')
            self.store._commit(fs, bundle)

    def _capture(self, proc, *, input, timeout):
        """Drain pipes without allowing an engine to grow worker RAM unbounded.

        stdout is machine output: overflow is an explicit failure, not silently
        parsed truncation. stderr retains its last 64 KiB for bounded diagnostics.
        Resource cleanup closes descendant pipe writers before joining readers.
        """
        values = {'stdout': bytearray(), 'stderr': bytearray()}
        overflow = threading.Event()
        readers = []
        failures = []

        def drain(name, stream, bound):
            try:
                with stream:
                    while True:
                        chunk = stream.read(65536)
                        if not chunk:
                            break
                        target = values[name]
                        if name == 'stdout':
                            if len(target) + len(chunk) > bound:
                                overflow.set()
                            target.extend(chunk[:max(0, bound - len(target))])
                        else:
                            target.extend(chunk)
                            del target[:-bound]
            except Exception:
                failures.append(name)

        for name, bound in (('stdout', 1048576), ('stderr', 65536)):
            stream = getattr(proc, name)
            if stream is not None:
                thread = threading.Thread(target=drain, args=(name, stream, bound), daemon=True)
                thread.start()
                readers.append(thread)

        def send():
            try:
                with proc.stdin:
                    proc.stdin.write(input)
            except BrokenPipeError:
                pass
            except Exception:
                failures.append('stdin')

        if proc.stdin is not None:
            writer = threading.Thread(target=send, daemon=True)
            writer.start()
            readers.append(writer)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            self.cleanup()
        # Kernel owned-tree cleanup is bounded and must precede final pipe EOF.
        proc.wait(timeout=5)
        for thread in readers:
            thread.join(timeout=1)
        out = bytes(values['stdout']) if proc.stdout is not None else None
        err = bytes(values['stderr']) if proc.stderr is not None else None
        if timed_out:
            self._engine_failure('ENGINE_TIMEOUT', 'Owned engine exceeded its execution timeout.',
                                 stderr=err, timeout_seconds=timeout)
            raise subprocess.TimeoutExpired('owned engine', timeout, output=out, stderr=err)
        if failures or any(thread.is_alive() for thread in readers):
            raise ContractError('OUTPUT_INVALID', 'Owned engine stream capture did not complete safely.')
        return out, err, overflow.is_set()

    def heartbeat(self):
        fs = self.store.projects._filesystem(write=True)
        with self.store._worker_lock(fs, self.pid):
            bundle = self.store.read(self.pid, self.jid)
            node = next(n for n in bundle['job']['node_states'] if n['attempt_id'] == self.aid)
            if (bundle['job']['state'] != 'running' or bundle['job']['cancel']['requested']
                    or node['state'] != 'running'):
                raise ContractError('PERMISSION_DENIED', 'Worker no longer owns a running attempt.')
            bundle['attempts'][self.aid]['owner']['lease_expires_at'] = _lease()
            bundle.setdefault('monitoring', {})['last_heartbeat_at'] = _now()
            limits = self.limits
            if limits is not None:
                with self._limits_lock:
                    if self.limits is limits:
                        from .host_safety import snapshot
                        measured = snapshot(paths=limits.policy['paths'])
                        disks = measured['disks']
                        low_disk = not disks or any(
                            disk['available_bytes'] is None or disk['total_bytes'] is None or
                            disk['available_bytes'] < max(1073741824, disk['total_bytes'] // 10)
                            for disk in disks)
                        bundle['monitoring']['resources'] = sanitize(dict(
                            owned_tree=limits.measurements(), disk_observed_at=_now(), disks=disks))
                        if low_disk:
                            self.failure = 'DISK_HEADROOM'
                            error = _error('DISK_HEADROOM', 'Execution volume lost required headroom; owned work stopped.', 'partial')
                            retain_error(bundle, error, attempt_id=self.aid, source='resource_monitor')
                            self.cleanup()
            self.store._commit(fs, bundle)

    def record_failure(self, code):
        import logging
        logging.getLogger(__name__).warning('Motion worker renewal failed: %s job=%s attempt=%s', code, self.jid, self.aid)
        try:
            fs = self.store.projects._filesystem(write=True)
            with self.store._worker_lock(fs, self.pid):
                bundle = self.store.read(self.pid, self.jid)
                errors = bundle.setdefault('worker_diagnostics', [])
                errors.append({'at': _now(), 'code': code, 'attempt_id': self.aid})
                del errors[:-8]
                self.store._commit(fs, bundle)
        except (ContractError, OSError):
            logging.getLogger(__name__).error('Cannot persist worker renewal diagnostic job=%s', self.jid)


class JobStore:
    def __init__(self, projects=None, *, plan_reader=None, authority=None,
                 adapter_resolver=None, input_validator=None, output_probe=None,
                 host_bridge=None, artifact_resolver=None, document_resolver=None,
                 selection_validator=None):
        self.projects = projects or ProjectStore()
        self.plan_reader, self.authority = plan_reader, authority
        self.adapter_resolver, self.input_validator = adapter_resolver, input_validator
        self.output_probe, self.host_bridge = output_probe, host_bridge
        self.artifact_resolver, self.document_resolver = artifact_resolver, document_resolver
        self.selection_validator = selection_validator
        self._workers = {}

    @contextmanager
    def _worker_lock(self, fs, pid):
        # A worker completion/cancel race is lock contention, not an unknown
        # adapter effect. Bounded acquisition retry never retries execution.
        lock = fs.lock(self.lock_path(pid))
        for retry in range(101):
            try:
                lock.__enter__()
                break
            except ContractError as exc:
                if exc.code != 'LOCK_BUSY' or retry == 100:
                    raise
                threading.Event().wait(.01)
                lock = fs.lock(self.lock_path(pid))
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def lock_path(self, pid):
        return self.projects._base(pid) + '/jobs.lock'

    def path(self, pid, jid):
        validate(jid, ident('job'))
        return self.projects._base(pid) + '/jobs/' + jid + '.json'

    def read(self, pid, jid):
        bundle = self.projects._filesystem().read(self.path(pid, jid))
        validate(bundle['job'], JOB_RECORD)
        if bundle['job']['project_id'] != pid or bundle['job']['job_id'] != jid:
            raise ContractError('HASH_MISMATCH', 'Job owner differs from path.')
        for attempt in bundle['attempts'].values():
            validate(attempt, ATTEMPT_RECORD)
        return bundle

    @staticmethod
    def _prepare_monitor(bundle):
        job = bundle['job']
        monitor = bundle.setdefault('monitoring', {})
        if job['state'] in TERMINAL:
            monitor.setdefault('ended_at', _now())
            monitor['phase'] = job['state']
        elif job['state'] not in ('running', 'queued'):
            monitor['phase'] = job['state']

    def _commit(self, fs, bundle, *, initial=False):
        job = bundle['job']
        self._prepare_monitor(bundle)
        if job['state'] != 'running':
            # Publish terminal state and release its owner in ONE revision.
            # A cleanup-only follow-up revision races native collect's CAS.
            bundle.pop('worker_owner', None)
        if not initial:
            job['job_revision'] += 1
        job['updated_at'] = _now()
        validate(job, JOB_RECORD)
        for attempt in bundle['attempts'].values():
            validate(attempt, ATTEMPT_RECORD)
        from .assets import validate_asset
        for artifact in bundle['artifacts']:
            validate_asset(artifact, 'ArtifactRecord')
        fs.write(self.path(job['project_id'], job['job_id']), bundle, replace=not initial)

    def summary(self, bundle):
        job = bundle['job']
        result = {k: copy.deepcopy(job[k]) for k in ('job_id', 'job_revision', 'state', 'project_revision', 'plan', 'stale', 'submission_state', 'remote_state', 'cancel')}
        result.update(progress=None, completed_nodes=sum(n['state'] == 'succeeded' for n in job['node_states']),
                      total_nodes=len(job['node_states']), outputs=job['outputs'][:20], output_count=len(job['outputs']),
                      outputs_next_cursor=None, blocking_reason=next((n['blocked_reason'] for n in job['node_states'] if n['blocked_reason']), None), observed_cost=bundle.get('observed_cost'))
        result['monitoring'] = project_monitor(bundle)
        result['error'] = result['monitoring']['first_error']
        result['blocking_reason'] = sanitize(result['blocking_reason'])
        # Larger output sets must go through bounded section snapshots, not a fake cursor.
        if len(job['outputs']) > 20:
            records = [a for a in bundle['artifacts'] if any(r['artifact_id'] == a['artifact_id'] for r in job['outputs'])]
            page = self.projects._page(self.projects._filesystem(), {'action': 'status', 'project_id': job['project_id'], 'job_id': job['job_id'], 'section': 'outputs', 'limit': 20}, records)
            result['outputs'] = [{'artifact_id': a['artifact_id'], 'sha256': a['sha256']} for a in page['items']]
            result['outputs_next_cursor'] = page['next_cursor']
        return result

    def status(self, pid, jid):
        # Observation only; never lease writes, reconcile, spawning or adapter calls.
        bundle = self.read(pid, jid)
        result = self.summary(bundle)
        fs = self.projects._filesystem()
        pointer = self.projects._pointer(fs, pid)
        snapshot, current_documents = self.projects._load(fs, pointer)
        historical = pointer
        frozen_revision = bundle['plan_record']['project_revision']
        while historical['revision'] > frozen_revision:
            historical = self.projects._transaction(fs, historical)['previous']
            if historical is None:
                raise ContractError('HASH_MISMATCH', 'Frozen job project revision is not committed history.')
        if historical['revision'] != frozen_revision:
            raise ContractError('HASH_MISMATCH', 'Frozen job project revision is not committed history.')
        _, frozen_documents = self.projects._load(fs, historical)
        from .reviews import affected_plan_nodes
        affected = {item['node_id'] for item in affected_plan_nodes(
            bundle['plan_record']['nodes'], frozen_documents, current_documents)}
        def changed(value):
            if isinstance(value, dict):
                if set(value) == {'kind', 'id', 'revision', 'sha256'}:
                    # Semantic document changes are handled above, including
                    # frozen execution policy and nonproduction stage metadata.
                    return False
                if set(value) == {'artifact_id', 'sha256'}:
                    try:
                        self._artifact(pid, value, bundle)
                    except (ContractError, OSError):
                        return True
                    return False
                return any(changed(v) for v in value.values())
            return isinstance(value, list) and any(changed(v) for v in value)
        for node in self._ordered_nodes(bundle['plan_record']):
            if changed(node['inputs']) or changed(node['parameters']) or any(d in affected for d in node['dependencies']):
                affected.add(node['node_id'])
        result['stale'] = bool(affected)
        result['stale_node_ids'] = sorted(affected)
        result['monitoring']['stale_reasons'] = list(dict.fromkeys(
            result['monitoring']['stale_reasons'] +
            (['Frozen project inputs or dependencies changed.'] if affected else [])))
        if result['monitoring']['lease_expired']:
            result['blocking_reason'] = 'Observation lease expired; explicit reconcile required.'
        return result

    def _replay(self, bundle, args):
        # Receipts in all owning job manifests share one project namespace.
        pid, rid = bundle['job']['project_id'], args['request_id']
        fs = self.projects._filesystem()
        owners = [bundle]
        for name in fs.names(self.projects._base(pid) + '/jobs'):
            if name.endswith('.json') and name[:-5] != bundle['job']['job_id']:
                owners.append(self.read(pid, name[:-5]))
        for owner in owners:
            for key, receipt in owner['requests'].items():
                if key != rid and not key.endswith(':' + rid):
                    continue
                if receipt['request_sha256'] != _hash_args(args):
                    raise ContractError('IDEMPOTENCY_CONFLICT', 'Request identity reused with different action or payload.')
                result = copy.deepcopy(receipt['result'])
                # A live timer advancing is not a durable job change. Preserve
                # the exact receipt until a new canonical revision is committed;
                # callers wanting a fresh timer use the read-only status action.
                if result.get('job', {}).get('job_revision') != owner['job']['job_revision']:
                    result['job'] = self.summary(owner)
                    result['refreshed_status'] = True
                return result
        return None

    def _finish_request(self, fs, bundle, args, result):
        # Build response for the revision being atomically published.
        self._prepare_monitor(bundle)
        bundle['job']['job_revision'] += 1
        result['job'] = self.summary(bundle)
        bundle['job']['job_revision'] -= 1
        bundle['requests'][args['action'] + ':' + args['request_id']] = {'request_sha256': _hash_args(args), 'result': copy.deepcopy(result)}
        self._commit(fs, bundle)
        return result

    @staticmethod
    def _cas(bundle, args):
        if bundle['job']['job_revision'] != args['expected_job_revision']:
            raise ContractError('REVISION_CONFLICT', 'Job revision differs from expected revision.')

    def submit(self, args):
        fs = self.projects._filesystem(write=True)
        with native_work_fence(fs.root):
            return self._submit(args)

    def _submit(self, args):
        validate(args['request_id'], {'type': 'string', 'pattern': DUMMY_UUID})
        validate(args['plan'], PLAN_REF)
        pid = args['project_id']
        fs = self.projects._filesystem(write=True)
        with self._worker_lock(fs, pid):
            # The authoritative request ledger lives in committed JobRecords. Scan
            # these before CAS/current-plan/authority checks, including after restart.
            for name in fs.names(self.projects._base(pid) + '/jobs'):
                if name.endswith('.json'):
                    existing = self.read(pid, name[:-5])
                    result = self._replay(existing, args)
                    if result is not None:
                        return result
                    break  # _replay already inspected every owning job manifest.
            with fs.lock(self.projects._base(pid) + '/locks/content.lock'):
                pointer = self.projects._pointer(fs, pid)
                if pointer['revision'] != args['expected_revision']:
                    raise ContractError('REVISION_CONFLICT', 'Project snapshot changed before submission.')
                from .creative import require_consent
                _, creative_documents = self.projects._load(fs, pointer)

                if self.plan_reader is None:
                    raise ContractError('DEPENDENCY_UNAVAILABLE', 'Immutable B06 plan reader is not bound.')
                plan = copy.deepcopy(self.plan_reader(pid, args['plan']))
                require_consent(self.projects, fs, pid, creative_documents, plan)
                if {k: plan[k] for k in ('plan_id', 'plan_revision', 'plan_sha256')} != args['plan'] or plan['project_id'] != pid or plan['project_revision'] != pointer['revision']:
                    raise ContractError('PLAN_STALE', 'Plan identity or snapshot differs.')
                expected = digest({k: v for k, v in plan.items() if k not in ('created_at', 'plan_sha256')})
                if plan['plan_sha256'] != expected:
                    raise ContractError('HASH_MISMATCH', 'Immutable plan digest differs.')
                if plan['status'] != 'ready' or plan['gaps']:
                    raise ContractError('PLAN_BLOCKED', 'Plan has unresolved capability gaps.')
                if self.authority is None:
                    raise ContractError('PERMISSION_DENIED', 'No verified Hermes authority bridge for exact plan/effects.')
                evidence = self.authority.authorize(copy.deepcopy(plan), copy.deepcopy(args))
                if not isinstance(evidence, dict) or not evidence.get('evidence_ref') or evidence.get('plan_sha256') != plan['plan_sha256'] or evidence.get('effects_sha256') != digest(plan['effects']):
                    raise ContractError('PERMISSION_DENIED', 'Authority evidence does not bind exact plan and effects.')
                for node in self._ordered_nodes(plan):
                    self._check_node(plan, node, admission=True)
                if args.get('retry_of_job_id'):
                    prior = self.read(pid, args['retry_of_job_id'])
                    if prior['job']['state'] not in TERMINAL or prior['job']['submission_state'] == 'uncertain':
                        raise ContractError('SUBMISSION_UNCERTAIN', 'Prior execution cannot be blindly retried.')
                jid = _id('job')
                now = _now()
                job = dict(schema='motion/v1/job', job_id=jid, project_id=pid, project_revision=plan['project_revision'], job_revision=1, plan=args['plan'], request_id=args['request_id'], request_sha256=_hash_args(args), created_at=now, updated_at=now, state='queued', node_states=[dict(node_id=n['node_id'], state='queued', attempt_id=None, reused=[], outputs=[], blocked_reason=None) for n in plan['nodes']], attempt_ids=[], outputs=[], stale=False, stale_reasons=[], cancel=dict(requested=False, requested_at=None, disposition='not_requested', external_may_continue=False), submission_state='not_sent', remote_state='none', authority_evidence_ref=evidence['evidence_ref'], error=None)
                bundle = {'job': job, 'plan_record': plan, 'attempts': {}, 'handoffs': {}, 'artifacts': [], 'requests': {}, 'authority': evidence, 'observed_cost': None, 'retry_of_job_id': args.get('retry_of_job_id')}
                result = {'job': self.summary(bundle), 'handoffs': []}
                bundle['requests']['submit:' + args['request_id']] = {'request_sha256': _hash_args(args), 'result': result}
                self._commit(fs, bundle, initial=True)
                return copy.deepcopy(result)

    def _adapter(self, node):
        if self.adapter_resolver is None:
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'No executable registered adapter binding.')
        return self.adapter_resolver(copy.deepcopy(node['binding']))

    @staticmethod
    def _ordered_nodes(plan):
        nodes = {n['node_id']: n for n in plan['nodes']}
        if len(nodes) != len(plan['nodes']):
            raise ContractError('PLAN_BLOCKED', 'Duplicate node identity.')
        ordered, visiting, visited = [], set(), set()
        def visit(node):
            nid = node['node_id']
            if nid in visiting:
                raise ContractError('PLAN_BLOCKED', 'Dependency graph contains a cycle.')
            if nid in visited:
                return
            visiting.add(nid)
            for dep in node['dependencies']:
                if dep not in nodes:
                    raise ContractError('PLAN_BLOCKED', 'Dependency node is missing.')
                visit(nodes[dep])
            for value in node['inputs'].values():
                for binding in value if isinstance(value, list) else [value]:
                    if binding['kind'] == 'node_output':
                        parent = nodes.get(binding['node_id'])
                        if parent is None or parent['node_id'] not in node['dependencies'] or binding['port'] not in {p['port'] for p in parent['expected_outputs']}:
                            raise ContractError('PLAN_BLOCKED', 'Node-output binding is not an exact declared dependency/port.')
            visiting.remove(nid)
            visited.add(nid)
            ordered.append(node)
        for node in plan['nodes']:
            visit(node)
        return ordered

    def _artifact(self, pid, pin, bundle=None):
        """Resolve committed metadata and independently rehash actual storage."""
        from .assets import AssetRegistry, validate_asset
        record = next((a for a in (bundle or {}).get('artifacts', []) if a['artifact_id'] == pin['artifact_id']), None)
        if record is None:
            if self.artifact_resolver is not None:
                record = self.artifact_resolver(pid, copy.deepcopy(pin))
            else:
                registry = AssetRegistry(self.projects)
                fs = self.projects._filesystem()
                record = registry.artifact(fs, self.projects._pointer(fs, pid), pin)
        validate_asset(record, 'ArtifactRecord')
        if record['project_id'] != pid or any(record[k] != pin[k] for k in ('artifact_id', 'sha256')):
            raise ContractError('HASH_MISMATCH', 'Input artifact ownership or exact pin differs.')
        verification_record = copy.deepcopy(record)
        # Existing job manifests use plugin-root-relative paths; AssetRegistry
        # uses project-relative paths. Normalize only this known owning prefix.
        prefix = self.projects._base(pid) + '/'
        storage = verification_record['storage']
        if storage['mode'] == 'managed' and storage['relative_path'].startswith(prefix):
            storage['relative_path'] = storage['relative_path'][len(prefix):]
        with AssetRegistry(self.projects).open_artifact(self.projects._filesystem(), verification_record):
            pass
        return record

    def _inputs(self, plan, node, bundle=None):
        def resolve(binding):
            if binding['kind'] == 'artifact':
                pin = binding['artifact']
            elif binding['kind'] == 'node_output':
                if bundle is None:
                    raise ContractError('DEPENDENCY_UNAVAILABLE', 'Dependency has not committed outputs.')
                ns = next(n for n in bundle['job']['node_states'] if n['node_id'] == binding['node_id'])
                if ns['state'] != 'succeeded':
                    raise ContractError('DEPENDENCY_UNAVAILABLE', 'Dependency has not succeeded.')
                ports = bundle.get('output_ports', {}).get(binding['node_id'], {})
                if binding['port'] not in ports:
                    raise ContractError('OUTPUT_INVALID', 'Committed dependency output port is unavailable.')
                pin = ports[binding['port']]
            elif binding['kind'] == 'document':
                if self.document_resolver is None:
                    raise ContractError('DEPENDENCY_UNAVAILABLE', 'Frozen document materializer is not bound.')
                doc_pin = binding['document']
                material = self.document_resolver(plan['project_id'], copy.deepcopy(doc_pin))
                if not isinstance(material, dict) or set(material) != {'document', 'artifact'}:
                    raise ContractError('OUTPUT_INVALID', 'Document resolver must return document and real artifact records.')
                doc, artifact = material['document'], material['artifact']
                validate(doc, self.projects._document_schema(doc_pin['kind']))
                if doc['project_id'] != plan['project_id'] or any(doc[k] != doc_pin[k] for k in ('kind', 'id', 'revision')) or digest(doc) != doc_pin['sha256']:
                    raise ContractError('HASH_MISMATCH', 'Materialized document differs from frozen pin.')
                pin = {k: artifact[k] for k in ('artifact_id', 'sha256')}
                # Resolver metadata alone cannot stand in for a real byte payload.
                self._artifact(plan['project_id'], pin, {'artifacts': [artifact]})
                # Persist the exact verified core materialization with its owning
                # job before execute; do not synthesize source references here.
                if bundle is not None and not any(a['artifact_id'] == pin['artifact_id'] for a in bundle['artifacts']):
                    bundle['artifacts'].append(copy.deepcopy(artifact))
                return pin
            else:
                raise ContractError('OUTPUT_INVALID', 'Unknown input binding.')
            record = self._artifact(plan['project_id'], pin, bundle)
            if bundle is not None and not any(a['artifact_id'] == pin['artifact_id'] for a in bundle['artifacts']):
                bundle['artifacts'].append(copy.deepcopy(record))
            return copy.deepcopy(pin)
        return {port: [resolve(b) for b in value] if isinstance(value, list) else resolve(value)
                for port, value in node['inputs'].items()}

    def _request(self, plan, node, bundle=None):
        task = next((t for t in plan['requests'] if t['target_key'] == node['target_key']), {})
        index = next(i for i, n in enumerate(plan['nodes']) if n['node_id'] == node['node_id'])
        effects = plan['effects'][index] if plan['effects'] else {}
        inputs = self._inputs(plan, node, bundle)
        request = dict(operation=node['operation'], parameters=copy.deepcopy(node['parameters']), inputs=inputs, required_features=copy.deepcopy(task.get('required_features', [])), binding_parameters=copy.deepcopy(task.get('binding_parameters')), binding=copy.deepcopy(node['binding']), project_id=plan['project_id'], project_revision=plan['project_revision'], plan={k: plan[k] for k in ('plan_id', 'plan_revision', 'plan_sha256')}, node_id=node['node_id'], request_sha256=node['fingerprint'], effects=copy.deepcopy(effects))
        if 'selection' in node or 'selection' in task:
            if node.get('selection') != task.get('selection'):
                raise ContractError('HASH_MISMATCH', 'Frozen node selection differs from its compile request.')
            request['selection'] = copy.deepcopy(node['selection'])
        return request

    def _reuse_outputs(self, plan, node):
        pins = node['reuse']
        if len(pins) != len(node['expected_outputs']) or len({p['artifact_id'] for p in pins}) != len(pins):
            raise ContractError('OUTPUT_INVALID', 'Reuse requires the complete unique output set.')
        fs = self.projects._filesystem()
        for name in fs.names(self.projects._base(plan['project_id']) + '/jobs'):
            if not name.endswith('.json'):
                continue
            owner = self.read(plan['project_id'], name[:-5])
            for prior in owner['plan_record']['nodes']:
                if prior['fingerprint'] != node['fingerprint']:
                    continue
                ns = next(n for n in owner['job']['node_states'] if n['node_id'] == prior['node_id'])
                ports = owner.get('output_ports', {}).get(prior['node_id'], {})
                expected = node['expected_outputs']
                if ns['state'] != 'succeeded' or prior['expected_outputs'] != expected or prior['binding'] != node['binding'] or prior['operation'] != node['operation']:
                    continue
                ordered = [ports.get(p['port']) for p in expected]
                if None in ordered or ordered != pins or ns['outputs'] != ordered:
                    continue
                # Rehash through the catalog and recheck the original producer
                # commit; copied input metadata is not evidence of production.
                from .artifacts import ArtifactCatalog
                catalog = ArtifactCatalog(self.projects, jobs=self)
                records = [catalog.resolve(plan['project_id'], pin) for pin in ordered]
                if any(r['producer']['job_id'] != owner['job']['job_id']
                        or r['producer']['node_id'] != prior['node_id'] for r in records):
                    continue
                if any(r['kind'] != p['kind'] or r['media_type'] != p['media_type'] for r, p in zip(records, expected)):
                    raise ContractError('OUTPUT_INVALID', 'Reused output kind/media type differs.')
                return records
        raise ContractError('OUTPUT_INVALID', 'No successful committed producer matches reuse fingerprint and all exact ports.')

    def _check_node(self, plan, node, bundle=None, *, admission=False):
        # Graph inputs cannot be materialized until their producers commit. Pure
        # adapter validation is repeated with exact ArtifactRefs before effects.
        if node.get('reuse') is not None:
            self._reuse_outputs(plan, node)
            return
        if admission and (node['dependencies'] or any(b['kind'] == 'document'
                for v in node['inputs'].values() for b in (v if isinstance(v, list) else [v]))):
            return
        if node['inputs'] and self.input_validator is not None:
            direct = {p: v for p, v in node['inputs'].items()
                      if all(b['kind'] == 'artifact' for b in (v if isinstance(v, list) else [v]))}
            if direct:
                self.input_validator(plan['project_id'], copy.deepcopy(direct))
        request = self._request(plan, node, bundle)
        result = self._adapter(node).validate_request(request)
        if not result.get('valid') or result.get('effects') != request['effects']:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Adapter validation/effects differ from frozen plan.')
        return request

    def start_worker(self, pid, jid):
        """Explicit admission-only launch. Never called by status/reconcile/open."""
        # Preserve the installed profile-scoping behavior when integrating code.
        context = copy_context()
        thread = threading.Thread(target=context.run, args=(self.run_queued, pid, jid), daemon=True, name='motion-' + jid)
        self._workers[jid] = thread
        thread.start()
        return thread

    def run_queued(self, pid, jid):
        fs = self.projects._filesystem(write=True)
        try:
            with native_work_fence(fs.root):
                return self._run_owned_worker(pid, jid)
        except ContractError as exc:
            with self._worker_lock(fs, pid):
                bundle = self.read(pid, jid)
                if bundle['job']['state'] != 'queued':
                    raise
                error = _error(exc.code, exc.message, 'none')
                retain_error(bundle, error, source='admission')
                bundle['job']['error'] = bundle['job']['error'] or error
                bundle.setdefault('monitoring', {})['phase'] = 'admission'
                for node in bundle['job']['node_states']:
                    node['blocked_reason'] = error['message']
                self._commit(fs, bundle)
                return self.summary(bundle)

    def _run_owned_worker(self, pid, jid):
        # Durable process AND native-thread identity survives fresh handlers and
        # plugin reloads without a cross-profile cache or lease-only liveness.
        tid = threading.get_native_id()
        start, boot, _ = _proc_identity(os.getpid())
        raw = Path(f'/proc/{os.getpid()}/task/{tid}/stat').read_text()
        owner = dict(pid=os.getpid(), process_started_at=start, boot_id=boot,
                     tid=tid, thread_started_at=raw[raw.rfind(')') + 2:].split()[19],
                     token=uuid.uuid4().hex, storage_root=str(self.projects._filesystem().root.resolve()),
                     project_id=pid, job_id=jid)
        try:
            return self._run_queued(pid, jid, owner)
        except Exception as exc:
            # Admission/authority failures previously escaped a daemon silently.
            fs = self.projects._filesystem(write=True)
            with self._worker_lock(fs, pid):
                bundle = self.read(pid, jid)
                error = _error(getattr(exc, 'code', 'WORKER_FAILED'), str(exc), 'none' if not bundle['attempts'] else 'unknown')
                retain_error(bundle, error, source='worker')
                bundle['job']['error'] = bundle['job']['error'] or error
                if bundle['job']['state'] == 'queued':
                    bundle['job']['state'] = 'failed'
                elif bundle['job']['state'] == 'running':
                    bundle['job'].update(state='awaiting_external', submission_state='uncertain', remote_state='unknown')
                self._commit(fs, bundle)
            return self.summary(bundle)
        finally:
            fs = self.projects._filesystem(write=True)
            with self._worker_lock(fs, pid):
                bundle = self.read(pid, jid)
                if bundle.get('worker_owner', {}).get('token') == owner['token']:
                    bundle.pop('worker_owner')
                    self._commit(fs, bundle)

    def worker_alive(self, bundle):
        owner = bundle.get('worker_owner', {})
        try:
            if (owner['storage_root'] != str(self.projects._filesystem().root.resolve())
                    or owner['project_id'] != bundle['job']['project_id']
                    or owner['job_id'] != bundle['job']['job_id']):
                return False
            start, boot, state = _proc_identity(owner['pid'])
            raw = Path(f"/proc/{owner['pid']}/task/{owner['tid']}/stat").read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            return (state not in ('Z', 'X') and fields[0] not in ('Z', 'X')
                    and start == owner['process_started_at'] and boot == owner['boot_id']
                    and fields[19] == owner['thread_started_at'])
        except (OSError, KeyError, ValueError, TypeError):
            return False

    def _run_queued(self, pid, jid, owner):
        fs = self.projects._filesystem(write=True)
        with self._worker_lock(fs, pid):
            bundle = self.read(pid, jid)
            if bundle['job']['state'] != 'queued':
                return self.summary(bundle)  # Already claimed is never another execute.
            pointer = self.projects._pointer(fs, pid)
            if pointer['revision'] != bundle['job']['project_revision']:
                bundle['job'].update(state='interrupted', stale=True, stale_reasons=['Project changed before execution.'])
                self._commit(fs, bundle)
                return self.summary(bundle)
            if self.authority is None:
                raise ContractError('PERMISSION_DENIED', 'Worker has no current authority evaluator.')
            evidence = self.authority.authorize(copy.deepcopy(bundle['plan_record']), {'action': 'execute', 'project_id': pid, 'job_id': jid, 'authority_ref': bundle['job']['authority_evidence_ref']})
            if not isinstance(evidence, dict) or evidence.get('plan_sha256') != bundle['job']['plan']['plan_sha256'] or evidence.get('effects_sha256') != digest(bundle['plan_record']['effects']) or not evidence.get('evidence_ref'):
                raise ContractError('PERMISSION_DENIED', 'Current execution authority is unavailable or expired.')
            bundle['job']['state'] = 'running'
            bundle['worker_owner'] = owner
            bundle.setdefault('monitoring', {}).update(started_at=_now(), phase='validating_inputs',
                host={'hostname': socket.gethostname(), 'pid': os.getpid(), 'boot_id': owner['boot_id']})
            self._commit(fs, bundle)
        for node in self._ordered_nodes(bundle['plan_record']):
            with self._worker_lock(fs, pid):
                bundle = self.read(pid, jid)
                if bundle['job']['cancel']['requested']:
                    return self.summary(bundle)
                ns = next(n for n in bundle['job']['node_states'] if n['node_id'] == node['node_id'])
                if ns['state'] == 'succeeded':
                    continue
                states = {n['node_id']: n['state'] for n in bundle['job']['node_states']}
                if any(states[dep] != 'succeeded' for dep in node['dependencies']):
                    ns.update(state='failed', blocked_reason='Dependency did not succeed; no attempt admitted.')
                    self._commit(fs, bundle)
                    continue
                try:
                    if node.get('reuse') is not None:
                        self._inputs(bundle['plan_record'], node, bundle)
                        records = self._reuse_outputs(bundle['plan_record'], node)
                        pins = [{k: r[k] for k in ('artifact_id', 'sha256')} for r in records]
                        ns.update(state='succeeded', reused=pins, outputs=pins, blocked_reason=None)
                        existing = {a['artifact_id'] for a in bundle['artifacts']}
                        bundle['artifacts'].extend(copy.deepcopy(r) for r in records if r['artifact_id'] not in existing)
                        bundle['job']['outputs'].extend(p for p in pins if p not in bundle['job']['outputs'])
                        bundle.setdefault('output_ports', {})[node['node_id']] = {p['port']: pin for p, pin in zip(node['expected_outputs'], pins)}
                        self._commit(fs, bundle)
                        continue
                    request = self._check_node(bundle['plan_record'], node, bundle)
                except (ContractError, OSError) as exc:
                    ns.update(state='failed', blocked_reason=sanitize(str(exc)))
                    bundle['job']['error'] = _error(getattr(exc, 'code', 'INPUT_INVALID'), str(exc), 'none')
                    retain_error(bundle, bundle['job']['error'], source='input_validation')
                    self._commit(fs, bundle)
                    continue
                if request is None:
                    raise ContractError('OUTPUT_INVALID', 'Executable node lacks a resolved adapter request.')
                bundle.setdefault('resolved_inputs', {})[node['node_id']] = copy.deepcopy(request['inputs'])
                aid = _id('att')
                output_dir = self.projects._base(pid) + '/jobs/' + jid + '/attempts/' + aid
                attempt = dict(schema='motion/v1/attempt', attempt_id=aid, job_id=jid, node_id=node['node_id'], attempt_number=1, request_sha256=node['fingerprint'], started_at=_now(), ended_at=None, owner=dict(worker_token=uuid.uuid4().hex, pid=None, process_started_at=None, boot_id=None, lease_expires_at=_lease()), submission_state='intent_recorded', provider_request_key=jid + ':' + aid, external_handle=None, remote_state='none', output_dir=output_dir, error=None)
                bundle['attempts'][aid] = attempt
                bundle['job']['attempt_ids'].append(aid)
                ns = next(n for n in bundle['job']['node_states'] if n['node_id'] == node['node_id'])
                ns.update(state='running', attempt_id=aid)
                bundle['job']['submission_state'] = 'intent_recorded'
                self._commit(fs, bundle)  # intent, output ownership, provider key BEFORE execute
            worker = WorkerContext(self, pid, jid, aid)
            stop = threading.Event()
            heartbeat_context = copy_context()
            heartbeat = threading.Thread(target=heartbeat_context.run, args=(_pulse_worker, worker, stop), daemon=True)
            heartbeat.start()
            adapter = None
            try:
                adapter = self._adapter(node)
                worker.configure_resources(adapter, request)
                # Ownership renewal is not the operation's execution budget.
                # Native adapters resolve the already-validated frozen binding.
                runtime = getattr(adapter, 'runtime', None)
                timeout = 30  # Legacy injected adapters without a registry.
                if runtime is not None:
                    declaration = runtime.registry.inspect(node['binding']['adapter_id'])['declaration']
                    operation = next(op for op in declaration['operations'] if op['operation'] == node['operation'])
                    timeout = operation['default_timeout_seconds']
                deadline = (datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat(timespec='microseconds').replace('+00:00', 'Z')
                context = {'job_id': jid, 'attempt_id': aid, 'node_id': node['node_id'], 'output_dir': output_dir, 'deadline_at': deadline, 'provider_request_key': attempt['provider_request_key'], 'authority_evidence_ref': bundle['job']['authority_evidence_ref']}
                # Only our optional owned-local adapter extension receives spawn.
                if getattr(adapter, 'owned_local', False):
                    from .resources import adapter_lease
                    worker.phase('resource_admission')
                    with adapter_lease(adapter, worker, request):
                        context['deadline_at'] = (datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat(timespec='microseconds').replace('+00:00', 'Z')
                        worker.phase('executing')
                        from .permissions import execute_with_permission
                        result = execute_with_permission(self.projects, request, context, adapter,
                            partial(adapter.execute, request, context, worker),
                            selection_validator=self.selection_validator)
                else:
                    worker.phase('executing')
                    from .permissions import execute_with_permission
                    result = execute_with_permission(self.projects, request, context, adapter,
                        partial(adapter.execute, request, context),
                        selection_validator=self.selection_validator)
                if worker.failure:
                    raise ContractError('PERMISSION_DENIED', 'Worker renewal failed; output publication closed.')
                worker.cleanup()
                worker.phase('validating_outputs', resources=worker.resource_snapshot)
                self._accept_result(pid, jid, aid, node, result)
            except Exception as exc:
                with self._worker_lock(fs, pid):
                    bundle = self.read(pid, jid)
                    error = (_error('WORKER_RENEWAL_FAILED', 'Worker renewal failed; inspect retained diagnostics.')
                             if worker.failure else _error('SUBMISSION_UNCERTAIN', 'Execution outcome requires observed readback.'))
                    actual = _error(getattr(exc, 'code', type(exc).__name__), str(exc))
                    from .permissions import PermissionAdmissionRefused
                    refused = isinstance(exc, PermissionAdmissionRefused) or (worker.admission_failure and worker.process is None
                               and (getattr(adapter, 'local_effects_only', False) is True or
                                    (getattr(adapter, 'owned_local', False) is True and
                                     request['effects'].get('uploads') is False)))
                    if refused:
                        actual['effect'] = 'none'
                        bundle['attempts'][aid].update(submission_state='not_sent', remote_state='none',
                                                       error=actual, ended_at=_now())
                        ns = next(n for n in bundle['job']['node_states'] if n['node_id'] == node['node_id'])
                        ns.update(state='failed', blocked_reason=actual['message'])
                        bundle['job'].update(state='failed', submission_state='not_sent', remote_state='none')
                    else:
                        bundle['attempts'][aid].update(submission_state='uncertain', remote_state='unknown', error=error)
                        bundle['job'].update(state='awaiting_external', submission_state='uncertain', remote_state='unknown')
                    retain_error(bundle, actual, attempt_id=aid, source='execution')
                    bundle['job']['error'] = bundle['job']['error'] or actual
                    self._commit(fs, bundle)
            finally:
                stop.set()
                heartbeat.join(timeout=1)
                worker.cleanup()
            bundle = self.read(pid, jid)
            if bundle['job']['state'] != 'running':
                return self.summary(bundle)
        with self._worker_lock(fs, pid):
            bundle = self.read(pid, jid)
            if bundle['job']['state'] == 'running':
                bundle['job']['state'] = 'succeeded' if all(n['state'] == 'succeeded' for n in bundle['job']['node_states']) else 'failed'
                self._commit(fs, bundle)
            return self.summary(bundle)

    def _accept_result(self, pid, jid, aid, node, result):
        fs = self.projects._filesystem(write=True)
        with self._worker_lock(fs, pid):
            bundle = self.read(pid, jid)
            attempt = bundle['attempts'][aid]
            if result.get('error'):
                retain_error(bundle, result['error'], attempt_id=aid, source='engine')
                result = dict(result, error=sanitize(result['error']))
                bundle['job']['error'] = bundle['job']['error'] or copy.deepcopy(result['error'])
                # Keep the engine's first failure even if downstream output
                # validation raises before the result can be committed.
                self._commit(fs, bundle)
            attempt.update({k: result[k] for k in ('submission_state', 'external_handle', 'remote_state', 'error')})
            bundle['job'].update(submission_state=result['submission_state'], remote_state=result['remote_state'])
            ns = next(n for n in bundle['job']['node_states'] if n['node_id'] == node['node_id'])
            if bundle['job']['cancel']['requested']:
                ns['blocked_reason'] = 'Late output quarantined after cancellation intent; explicit reconcile required.'
                bundle['job']['state'] = 'awaiting_external'
            elif result.get('handoff'):
                from .handoffs import prepare_handoff
                handoff = prepare_handoff(result['handoff'], bundle, attempt, node, self.host_bridge)
                bundle['handoffs'][handoff['handoff_id']] = handoff
                bundle['job']['state'] = ns['state'] = 'awaiting_external'
            elif result['state'] == 'succeeded':
                records = self.validate_outputs(bundle, attempt, node, result['outputs'])
                bundle['artifacts'].extend(records)
                refs = [{'artifact_id': a['artifact_id'], 'sha256': a['sha256']} for a in records]
                ns.update(state='succeeded', outputs=refs)
                bundle['job']['outputs'].extend(refs)
                attempt['ended_at'] = _now()
            else:
                ns['state'] = result['state']
                if result['state'] == 'failed' and result['submission_state'] != 'uncertain':
                    attempt['ended_at'] = _now()
                else:
                    bundle['job']['state'] = result['state']
                if result['state'] in TERMINAL:
                    attempt['ended_at'] = _now()
            bundle['observed_cost'] = result.get('observed_cost')
            self._commit(fs, bundle)

    @staticmethod
    def _validate_conversion_record(record, node, source_pin, output_pin):
        """Closed B03 record bound to the exact native sample/frame request."""
        from math import gcd
        from .contracts import MAX_INT
        signed = obj({'num': integer(-MAX_INT), 'den': integer(1)})
        from .adapters.conform import registration
        video = node['parameters']['kind'] == 'rate_conform'
        validate(record, obj({
            'kind': {'const': 'frame_rate' if video else 'sample_rate'}, 'input': D['ArtifactRef'],
            'output': D['ArtifactRef'],
            'parameters': registration()['schemas']['motion/v1/ffmpeg.conform/request'],
            'rounding': {'const': 'nearest_even'}, 'offset_seconds': signed,
            'error_seconds': signed, 'losses': arr(TEXT)}))
        if (node['binding']['adapter_id'] != 'ffmpeg.conform'
                or node['operation'] != 'media.transform@1'
                or node['expected_outputs'] != [dict(port='media', kind='media', media_type='video/quicktime' if video else 'audio/wav')]
                or record['input'] != source_pin or record['output'] != output_pin
                or record['parameters'] != node['parameters']):
            raise ContractError('HASH_MISMATCH', 'Conversion differs from frozen source, output or operation.')
        for name in ('offset_seconds', 'error_seconds'):
            value = record[name]
            if gcd(value['num'], value['den']) != 1:
                raise ContractError('OUTPUT_INVALID', 'Conversion timing must be reduced exact rational values.')

    def _collect_conversion(self, bundle, attempt, node, records):
        """Post-assignment B05 seam; the existing manifest commit publishes it.

        No plugin callback or separate ancillary publication: uncommitted bytes
        and attempt observations confer no canonical record. Legacy jobs are not
        backfilled by reads. Only the explicit native conform binding opts in.
        """
        if node['binding']['adapter_id'] != 'ffmpeg.conform':
            return
        from .adapters.conform import finalize_conversion
        pid, jid = bundle['job']['project_id'], bundle['job']['job_id']
        expected_dir = (self.projects._base(pid) + '/jobs/' + jid + '/attempts/'
                        + attempt['attempt_id'])
        if attempt['output_dir'] != expected_dir:
            raise ContractError('PATH_UNSAFE', 'Conversion observation is outside owning attempt.')
        fs = self.projects._filesystem()
        try:
            observation = fs.read(expected_dir + '/conform-observation.json')
            if not isinstance(observation, dict) or len(records) != 1:
                raise ContractError('OUTPUT_INVALID', 'One native conform observation/output required.')
            source_pin = bundle.get('resolved_inputs', {}).get(node['node_id'], {}).get('media')
            output_pin = {k: records[0][k] for k in ('artifact_id', 'sha256')}
            if observation.get('source') != source_pin:
                raise ContractError('HASH_MISMATCH', 'Conversion observation differs from actual source pin/hash.')
            # Reopen/re-hash the actual source at collection, not just its metadata.
            self._artifact(pid, source_pin, bundle)
            record = finalize_conversion(observation, output_pin)
            self._validate_conversion_record(record, node, source_pin, output_pin)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise ContractError('OUTPUT_INVALID', 'Native conform observation is unavailable or malformed.') from exc
        bundle.setdefault('conversion_records', {})[output_pin['artifact_id']] = {
            'record': record, 'sha256': digest(record)}

    def resolve_conversion_record(self, project_id, output_pin):
        """Read the canonical B05 ConversionRecord for a committed output pin.

        Parent hook: jobs.resolve_conversion_record(project_id, output_pin).
        Collection installs conversion_records[artifact_id]={record,sha256} in
        the SAME owning job manifest transaction as node/artifact publication.
        This private manifest extension leaves the closed ArtifactRecord intact.
        Rehashes output and source, verifies frozen operation/pins and integrity;
        never executes, hydrates, backfills legacy observations or writes files.
        Missing legacy/nonconform records fail NOT_FOUND, never imply no losses.
        """
        from .artifacts import ArtifactCatalog
        output = ArtifactCatalog(self.projects, jobs=self).resolve(project_id, output_pin)
        jid = output['producer']['job_id']
        if jid is None:
            raise ContractError('NOT_FOUND', 'Artifact has no collected conversion record.')
        bundle = self.read(project_id, jid)
        entry = bundle.get('conversion_records', {}).get(output_pin['artifact_id'])
        if entry is None:
            raise ContractError('NOT_FOUND', 'No canonical conversion record was published.')
        if (not isinstance(entry, dict) or set(entry) != {'record', 'sha256'}
                or digest(entry['record']) != entry['sha256']):
            raise ContractError('HASH_MISMATCH', 'Committed conversion integrity differs.')
        node = next((n for n in bundle['plan_record']['nodes']
                     if n['node_id'] == output['producer']['node_id']), None)
        if node is None:
            raise ContractError('HASH_MISMATCH', 'Conversion has no owning frozen node.')
        source = bundle.get('resolved_inputs', {}).get(node['node_id'], {}).get('media')
        record = entry['record']
        self._validate_conversion_record(record, node, source, output_pin)
        self._artifact(project_id, record['input'], bundle)
        return copy.deepcopy(record)

    def _probe_receipt_path(self, pid, jid, receipt_id):
        validate(receipt_id, ident('rcp'))
        return self.projects._base(pid) + '/jobs/' + jid + '/probe-receipts/' + receipt_id + '.json'

    def resolve_probe_receipt(self, project_id, artifact):
        """Read exact committed output evidence, rehashing media and receipt.

        No cache hydration, process launch, authorization, or state mutation.
        Old opaque fixture IDs and legacy dangling IDs remain unavailable.
        """
        from .artifacts import ArtifactCatalog
        from .adapters.probe import LocalOutputProbe
        record = ArtifactCatalog(self.projects, jobs=self).resolve(project_id, artifact)
        jid = record['producer']['job_id']
        if jid is None or record['probe_receipt_id'] is None:
            raise ContractError('NOT_FOUND', 'Artifact has no local output probe evidence.')
        bundle = self.read(project_id, jid)
        binding = bundle.get('probe_receipts', {}).get(record['artifact_id'])
        if binding is None:
            raise ContractError('NOT_FOUND', 'No durable local output probe evidence was published.')
        rid = record['probe_receipt_id']
        if binding.get('receipt_id') != rid:
            raise ContractError('HASH_MISMATCH', 'Committed probe receipt binding differs.')
        try:
            receipt = self.projects._filesystem().read(self._probe_receipt_path(project_id, jid, rid))
        except FileNotFoundError as exc:
            raise ContractError('NOT_FOUND', 'Committed local output probe evidence is missing.') from exc
        if digest(receipt) != binding.get('sha256'):
            raise ContractError('HASH_MISMATCH', 'Committed local output probe evidence changed.')
        return LocalOutputProbe.verify_receipt(rid, receipt, **{
            k: record[k] for k in ('sha256', 'kind', 'media_type', 'size_bytes')})

    def validate_outputs(self, bundle, attempt, node, outputs):
        from contextlib import ExitStack
        with ExitStack() as resources:
            return self._validate_outputs(bundle, attempt, node, outputs, resources)

    def _validate_outputs(self, bundle, attempt, node, outputs, resources):
        expected = {p['port']: p for p in node['expected_outputs']}
        if len(outputs) != len(expected) or {o['port'] for o in outputs} != set(expected):
            raise ContractError('OUTPUT_INVALID', 'Required output port set differs from frozen plan.')
        fs = self.projects._filesystem(write=True)
        records = []
        lineage = []
        for value in bundle.get('resolved_inputs', {}).get(node['node_id'], {}).values():
            for pin in value if isinstance(value, list) else [value]:
                if pin not in lineage:
                    lineage.append(copy.deepcopy(pin))
        # Input metadata is resolved and bytes rehashed, never supplied by the
        # adapter's output descriptor. Preserve unknowns and restrictions.
        from .artifacts import inherited_rights
        from .adapters.limits import output_payload
        preserving_operations = {
            'scene.render@1', 'scene.frame@1', 'edit.assemble@1', 'delivery.encode@1',
            'delivery.package@1', 'media.transform@1', 'media.extract_audio@1',
            'media.extract_frame@1', 'media.probe@1', 'media.matte@1', 'audio.mix@1',
            'audio.measure@1', 'caption.layout@1', 'caption.render@1', 'caption.export@1',
            'speech.align@1', 'speech.transcribe@1', 'review.check@1',
            'inspection.visual@1', 'inspection.audio@1', 'inspection.playback@1'}
        # Prompt/reference licenses cannot grant rights to newly generated work.
        rights = inherited_rights([self._artifact(bundle['job']['project_id'], pin, bundle)
                                   for pin in lineage] if node['operation'] in preserving_operations else [])
        by_port = {o['port']: o for o in outputs}
        for spec in node['expected_outputs']:
            output = by_port[spec['port']]
            port = expected[output['port']]
            if output['media_type'] != port['media_type']:
                raise ContractError('OUTPUT_INVALID', 'Media type differs from expected output.')
            relative = attempt['output_dir'] + '/' + safe_relative(output['relative_path'])
            parent, _, name = relative.rpartition('/')
            with fs.directory(parent) as directory:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                source = resources.enter_context(os.fdopen(fd, 'rb'))
                payload = resources.enter_context(output_payload(source, port)).data
            sha = 'sha256:' + hashlib.sha256(payload).hexdigest()
            if output.get('claimed_sha256') not in (None, sha):
                raise ContractError('HASH_MISMATCH', 'Adapter output digest differs from actual bytes.')
            probe_id = None
            probe_receipt = None
            if port['media_type'] == 'application/json' or port['kind'] in ('scene_source', 'assembly_source'):
                json.loads(payload)
            elif self.output_probe is None:
                raise ContractError('DEPENDENCY_UNAVAILABLE', 'Media probe/decode validator not bound; descriptor is not an artifact.')
            else:
                probe_id = self.output_probe(payload, copy.deepcopy(port))
                if not probe_id:
                    raise ContractError('OUTPUT_INVALID', 'Output structural probe did not produce evidence.')
                # Legacy fixture callbacks return only an opaque ID. The native
                # probe additionally exposes its actual observation for storage.
                from .adapters.probe import LocalOutputProbe
                if isinstance(self.output_probe, LocalOutputProbe):
                    probe_receipt = self.output_probe.receipt(probe_id, payload, port)
            aid = _id('art')
            target = self.projects._base(bundle['job']['project_id']) + '/jobs/' + bundle['job']['job_id'] + '/artifacts/' + aid
            # Descriptor-relative, immutable bytes; owning job manifest is publication.
            # Authored source outputs are indivisible manifest + sibling member
            # closure. Reuse the descriptor-safe core validator/copier, never
            # publish a manifest whose declared members were not rehashed.
            if port['kind'] in ('scene_source', 'assembly_source'):
                from .assets import _read_bundle, _bundle_members, _local_file
                source_path = fs.root / relative
                with _local_file(str(source_path)) as source_stream:
                    source_bundle = _read_bundle(source_stream, source_path.name)
                    if source_stream.read() != payload:
                        raise ContractError('HASH_MISMATCH', 'Source manifest changed during closure staging.')
                    with _bundle_members(source_bundle, source_path.parent,
                                         copy_to=(fs, target + '.members')):
                        pass
            if probe_receipt is not None:
                receipt_path = self._probe_receipt_path(bundle['job']['project_id'],
                    bundle['job']['job_id'], probe_id)
                try:
                    prior = fs.read(receipt_path)
                except FileNotFoundError:
                    fs.write(receipt_path, probe_receipt, replace=False)
                else:
                    if prior != probe_receipt:
                        raise ContractError('HASH_MISMATCH', 'Immutable probe evidence differs.')
                bundle.setdefault('probe_receipts', {})[aid] = {
                    'receipt_id': probe_id, 'sha256': digest(probe_receipt)}
            parent, _, name = target.rpartition('/')
            with fs.directory(parent, create=True) as directory:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(directory)
            records.append(dict(schema='motion/v1/artifact', artifact_id=aid, project_id=bundle['job']['project_id'], kind=port['kind'], media_type=port['media_type'], sha256=sha, size_bytes=len(payload), storage={'mode': 'managed', 'relative_path': target}, created_at=_now(), producer={'job_id': bundle['job']['job_id'], 'node_id': node['node_id'], 'attempt_id': attempt['attempt_id'], 'adapter_id': node['binding']['adapter_id']}, inputs=lineage, provenance={'origin': 'derived', 'acquired_at': _now(), 'source_locator': None, 'provider': None, 'model': None, 'model_version': None, 'seed': None, 'deterministic': 'unknown', 'rights': copy.deepcopy(rights), 'notes': 'Core rehashed and structurally validated; inherited rights declarations are not a new license or creative/final review.'}, probe_receipt_id=probe_id))
        if node['operation'] == 'asset.acquire@1':
            # A source URL is provenance, never an inherited/generated license.
            # Keep this semantic for all acquisition adapters, not CLI-specific.
            for record in records:
                record['provenance'].update(source_locator=node['parameters']['url'],
                    provider=node['binding']['adapter_id'],
                    rights=dict(status='unknown', license=None, attribution=None, evidence=[]),
                    notes='Acquired source bytes and metadata; source facts are retained in the acquisition report. No rights clearance or creative acceptance implied.')
        self._collect_conversion(bundle, attempt, node, records)
        bundle.setdefault('output_ports', {})[node['node_id']] = {
            spec['port']: {'artifact_id': record['artifact_id'], 'sha256': record['sha256']}
            for spec, record in zip(node['expected_outputs'], records)}
        return records

    @staticmethod
    def process_alive(owner):
        try:
            start, boot, state = _proc_identity(owner['pid'])
            if state == 'Z' or start != owner['process_started_at'] or boot != owner['boot_id']:
                return False
            if os.getpgid(owner['pid']) != owner['pid']:
                return False
            env = Path(f"/proc/{owner['pid']}/environ").read_bytes().split(b'\0')
            return ('MOTION_WORKER_TOKEN=' + owner['worker_token']).encode() in env
        except (OSError, TypeError, ValueError, KeyError):
            return False

    def _signal_owned(self, owner):
        if not self.process_alive(owner):
            return False
        # Linux pidfd pins exact process against PID reuse across final read/signal.
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            return False
        fd = os.pidfd_open(owner['pid'])
        try:
            if not self.process_alive(owner):
                return False
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            return True
        finally:
            os.close(fd)

    def _stopped_local_attempt(self, bundle, attempt):
        # Caller has already observed that no owned process is live. A local
        # adapter declaration may explain an unknown outcome, never override
        # an observed provider state, handle, or delegated handoff.
        if (attempt['owner']['pid'] is None or attempt['external_handle'] is not None
                or bundle['handoffs']):
            return False
        if attempt['remote_state'] == 'none':
            return True
        if attempt['remote_state'] != 'unknown':
            return False
        node = next((n for n in bundle['plan_record']['nodes']
                     if n['node_id'] == attempt['node_id']), None)
        if node is None:
            return False
        try:
            return getattr(self._adapter(node), 'local_effects_only', False) is True
        except ContractError:
            # Missing/incompatible frozen adapters leave uncertainty intact.
            return False

    def reconcile(self, args):
        fs = self.projects._filesystem(write=True)
        with fs.lock(self.lock_path(args['project_id'])):
            bundle = self.read(args['project_id'], args['job_id'])
            replay = self._replay(bundle, args)
            if replay is not None:
                return replay
            self._cas(bundle, args)
            job = bundle['job']
            observed, unresolved = [], []
            if job['state'] not in TERMINAL:
                live = self.worker_alive(bundle) or any(self.process_alive(a['owner']) for a in bundle['attempts'].values())
                live = live or bool(self._workers.get(job['job_id']) and self._workers[job['job_id']].is_alive())
                uncertain = job['submission_state'] in ('intent_recorded', 'uncertain') or any(h['state'] in ('claimed', 'uncertain') for h in bundle['handoffs'].values())
                if live:
                    observed.append('Verified owned worker remains live; no execution requested.')
                elif job['cancel']['requested'] and bundle['attempts'] and all(
                    self._stopped_local_attempt(bundle, a) for a in bundle['attempts'].values()):
                    job.update(state='cancelled', submission_state='confirmed', remote_state='none')
                    job['cancel'].update(disposition='confirmed', external_may_continue=False)
                    for attempt in bundle['attempts'].values():
                        attempt.update(submission_state='confirmed', remote_state='none',
                                       ended_at=attempt['ended_at'] or _now())
                    for node in job['node_states']:
                        if node['state'] != 'succeeded':
                            node['state'] = 'cancelled'
                    observed.append('Owned local process and worker are stopped; cancellation reconciled.')
                elif uncertain:
                    job.update(state='awaiting_external', submission_state='uncertain', remote_state='unknown')
                    for handoff in bundle['handoffs'].values():
                        if handoff['state'] == 'claimed':
                            handoff['state'] = 'uncertain'
                    unresolved.append('Possible effects without verified completion; no blind retry.')
                else:
                    job['state'] = 'interrupted'
                    observed.append('No live owned worker; unstarted work requires explicit new submission.')
            return self._finish_request(fs, bundle, args, {'reconciled': observed, 'unresolved': unresolved})

    def cancel(self, args):
        fs = self.projects._filesystem(write=True)
        # Cancellation shares the worker's bounded acquisition policy: a short
        # owner/completion write must not immediately discard cancel intent.
        with self._worker_lock(fs, args['project_id']):
            bundle = self.read(args['project_id'], args['job_id'])
            replay = self._replay(bundle, args)
            if replay is not None:
                return replay
            self._cas(bundle, args)
            job = bundle['job']
            cancel = job['cancel']
            cancel.update(requested=True, requested_at=_now())
            if job['state'] in TERMINAL:
                cancel['disposition'] = 'too_late'
            elif job['state'] == 'queued':
                job['state'] = 'cancelled'
                cancel['disposition'] = 'confirmed'
                for node in job['node_states']:
                    node['state'] = 'cancelled'
            else:
                # Persist intent before any signal. No false terminal acknowledgement.
                cancel.update(disposition='pending', external_may_continue=True)
                self._commit(fs, bundle)
                owners = [a['owner'] for a in bundle['attempts'].values()]
                signalled = [self._signal_owned(o) for o in owners]
                if not any(signalled):
                    cancel['disposition'] = 'unsupported'
                for node in job['node_states']:
                    if node['state'] == 'queued':
                        node['state'] = 'cancelled'
            return self._finish_request(fs, bundle, args, {'cancel': copy.deepcopy(cancel)})

    def handoff_claim(self, args):
        from .handoffs import claim
        return claim(self, args)

    def collect(self, args):
        from .handoffs import collect
        return collect(self, args)

    def dispatch(self, args):
        action = args.get('action') if isinstance(args, dict) else None
        try:
            validate(args, RUN_REQUEST)
            if action in ('status', 'list'):
                fs = self.projects._filesystem()
                if action == 'status' and args.get('section', 'summary') == 'summary':
                    data = {'job': self.status(args['project_id'], args['job_id'])}
                else:
                    items = None
                    if not args.get('cursor') and not args.get('snapshot_id'):
                        if action == 'list':
                            items = []
                            for name in fs.names(self.projects._base(args['project_id']) + '/jobs'):
                                if name.endswith('.json'):
                                    bundle = self.read(args['project_id'], name[:-5])
                                    job = bundle['job']
                                    if ('state' not in args or job['state'] == args['state']) and ('plan_id' not in args or job['plan']['plan_id'] == args['plan_id']):
                                        items.append(self.summary(bundle))
                            items.sort(key=lambda j: j['job_id'])
                        else:
                            bundle = self.read(args['project_id'], args['job_id'])
                            section = args['section']
                            attempts = [{k: a[k] for k in ('attempt_id', 'node_id', 'attempt_number', 'submission_state', 'remote_state', 'started_at', 'ended_at', 'error')} for a in bundle['attempts'].values()]
                            outputs = [a for a in bundle['artifacts'] if any(r['artifact_id'] == a['artifact_id'] for r in bundle['job']['outputs'])]
                            items = {'nodes': bundle['job']['node_states'], 'attempts': attempts, 'handoffs': list(bundle['handoffs'].values()), 'outputs': outputs}[section]
                    data = self.projects._page(fs, args, items)
            else:
                data = getattr(self, str(action))(args)
            summary = 'Durable job action accepted; inspect actual job state.'
            if action == 'status' and 'job' in data:
                observed = data['job']
                monitor = observed['monitoring']
                if monitor['first_error']:
                    summary = 'Job ' + observed['state'] + ': ' + monitor['first_error']['message']
                elif observed.get('blocking_reason'):
                    summary = 'Job ' + observed['state'] + ': ' + sanitize(observed['blocking_reason'])
                else:
                    summary = 'Job ' + observed['state'] + '; phase ' + monitor['phase'] + '.'
            return {'ok': True, 'tool': 'motion_run', 'action': action, 'status': 'ok', 'summary': summary, 'project_id': args['project_id'], 'data': data}
        except ContractError as exc:
            error = _error(exc.code, exc.message, exc.effect)
            error['details'] = copy.deepcopy(exc.details)
            return {'ok': False, 'tool': 'motion_run', 'action': action, 'status': 'blocked', 'summary': exc.message, 'error': error}
        except (FileNotFoundError, KeyError):
            return {'ok': False, 'tool': 'motion_run', 'action': action, 'status': 'error', 'summary': 'Job/dependency record unavailable.', 'error': _error('NOT_FOUND', 'Job/dependency record unavailable.', 'none')}


DUMMY_UUID = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
BASE = {'project_id': ident('prj'), 'request_id': {'type': 'string', 'pattern': DUMMY_UUID}}
_mutations = []
for action in ('cancel', 'reconcile', 'handoff_claim', 'collect'):
    props = {'action': {'const': action}, **BASE, 'job_id': ident('job'), 'expected_job_revision': integer(1)}
    optional = []
    if action == 'cancel':
        props['reason'] = TEXT
    if action == 'handoff_claim':
        props.update(handoff_id=ident('hnd'), attempt_id=ident('att'))
    if action == 'collect':
        # Exact HandoffReceipt schema is inserted lazily by run_tool_schema().
        from .handoffs import RECEIPT
        props.update(receipts=arr(RECEIPT), decision_review_ids=arr(ident('rev')))
        optional = ['receipts', 'decision_review_ids']
    _mutations.append(obj(props, optional=optional))
RUN_REQUEST = {'oneOf': [obj({'action': {'const': 'submit'}, **BASE, 'expected_revision': integer(1), 'plan': PLAN_REF, 'authority_ref': TEXT, 'retry_of_job_id': ident('job')}, optional=['authority_ref', 'retry_of_job_id']), obj({'action': {'const': 'status'}, 'project_id': ident('prj'), 'job_id': ident('job'), 'section': enum('summary', 'nodes', 'attempts', 'handoffs', 'outputs'), 'limit': integer(1, 100), 'cursor': TEXT, 'snapshot_id': ident('snp')}, optional=['section', 'limit', 'cursor', 'snapshot_id']), obj({'action': {'const': 'list'}, 'project_id': ident('prj'), 'state': enum(*STATES), 'plan_id': ident('pln'), 'limit': integer(1, 100), 'cursor': TEXT, 'snapshot_id': ident('snp')}, optional=['state', 'plan_id', 'limit', 'cursor', 'snapshot_id'])] + _mutations}


def run_tool_schema():
    return {'name': 'motion_run', 'description': 'Durable queued jobs and typed claim/collection; unknown native authority fails closed.', 'parameters': copy.deepcopy(RUN_REQUEST)}


def run_handler(args, **_host_context):
    return json.dumps(JobStore().dispatch(args), separators=(',', ':'))
