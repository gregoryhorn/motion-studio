"""Reusable one-shot trusted CLI connector on the existing owned Adapter ABI.

Bindings are installed Python code, never project-supplied programs/imports. Core
still owns authority, process groups, deadlines, cancellation and collection.
"""
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from ..contracts import ContractError
from .alternative import _relative, _result, file_digest


class OwnedCliConnector:
    def __init__(self, registration, discover, validate_parameters, perform):
        self.registration = registration
        self.discover = discover
        self.validate_parameters = validate_parameters
        self.perform = perform

    def validate_request(self, registry, binding, request):
        from ..contracts import validate
        meta = self.registration()
        expected = registry.binding(binding['adapter_id'], request['operation'],
                                    request['parameters'], request.get('binding_parameters'))
        if binding != expected or meta['implementation_sha256'] != expected['implementation_sha256']:
            raise ContractError('HASH_MISMATCH', 'Frozen CLI/schema/config identity changed')
        if request.get('binding_parameters') is not None or request.get('inputs'):
            raise ContractError('UNSUPPORTED_OPERATION', 'This binding accepts only its closed parameters')
        if request.get('effects', meta['declaration']['effects']) != meta['declaration']['effects']:
            raise ContractError('PERMISSION_DENIED', 'Disclosed effects differ from binding')
        validate(request['parameters'], meta['schemas'][binding['request_schema']])
        self.validate_parameters(request['parameters'])
        if self.discover()['missing']:
            raise ContractError('DEPENDENCY_UNAVAILABLE', 'Missing local CLI dependencies: ' + ', '.join(self.discover()['missing']))

    def execute(self, request, attempt, *, project_root, registry, context, output_probe):
        started = False
        try:
            if not callable(getattr(context, 'run', None)):
                raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run required')
            if not attempt.get('authority_evidence_ref') or attempt['node_id'] != request['node_id']:
                raise ContractError('PERMISSION_DENIED', 'Authorized matching attempt required')
            self.validate_request(registry, request['binding'], request)
            root = Path(project_root).resolve(strict=True)
            out = _relative(root, attempt['output_dir'])
            if out.exists():
                raise ValueError('Preexisting attempt output refused')
            out.mkdir(parents=True, exist_ok=False)
            deadline = datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00'))
            def run(argv, **kwargs):
                nonlocal started
                seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
                if seconds <= 0:
                    raise TimeoutError('Owned CLI attempt deadline exceeded')
                # WorkerContext retains the exact last Popen, including after
                # capture/cleanup failure. Calling run is not proof of spawn.
                observed_process = hasattr(context, 'process')
                if not observed_process:
                    started = True  # Unobservable runners remain conservative.
                try:
                    return context.run(argv, timeout=seconds, check=True, **kwargs)
                finally:
                    if observed_process:
                        started = started or context.process is not None
            outputs = self.perform(request, out, run, output_probe)
            return _result(outputs, started=started)
        except Exception as exc:
            return _result(error=exc, started=started)


class OwnedCliAdapter:
    owned_local = True
    connector: OwnedCliConnector

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, binding

    def validate_request(self, request):
        if request.get('binding') != self.binding:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Request differs from frozen CLI binding')
        self.connector.validate_request(self.runtime.registry, self.binding, request)
        return dict(valid=True, effects=self.connector.registration()['declaration']['effects'])

    def execute(self, request, attempt, context=None):
        if not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run required')
        self.validate_request(request)
        return self.connector.execute(request, attempt, project_root=self.runtime.projects._filesystem().root,
                                      registry=self.runtime.registry, context=context,
                                      output_probe=self.runtime.output_probe)


def owned_file(path, root, limit):
    path = _relative(root, str(Path(path).relative_to(root)))
    if not path.is_file() or path.stat().st_nlink != 1 or not 0 < path.stat().st_size <= limit:
        raise ValueError('CLI output missing, empty, hardlinked or exceeds bound')
    return path


def output(port, path, mime):
    return dict(port=port, relative_path=path.name, media_type=mime, claimed_sha256=file_digest(path))


def limited_run(run, argv, *, limit, stdout_path, stderr_path):
    """OS per-file hard bound covers unknown-length downloads and CLI logs too.

    No shell/preexec_fn and no alternate process lifecycle. prlimit execs the
    trusted CLI within the very same core-owned child process group.
    """
    import shutil
    with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
        return run([shutil.which('prlimit'), f'--fsize={limit}:{limit}', '--', *argv],
                   stdout=stdout, stderr=stderr)
