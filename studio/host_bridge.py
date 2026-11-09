"""One narrow public-lifecycle bridge. Never dispatches tools or grants approval.

Only exact request schemas or observed same-turn tool descriptions are admitted.
Claims and call associations are durable; a second native call cannot reuse one.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

from .contracts import ContractError, digest, canonical
from .project import ProjectStore, _now

FRAME_TOOL = 'lk_extract_frame'
ADAPTER_ID = 'hermes.frame-extract'
OPERATION = 'media.extract_frame@1'


def native_tool_names():
    from .adapters.native_tools import install_builtins, tool_names
    install_builtins()
    return tool_names()


def _key(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _incomplete(value):
    if isinstance(value, str):
        return (value.startswith(('<max-depth:', '<truncated:', '<redacted:'))
                or value == '<redacted>' or '...[truncated ' in value
                or value.endswith(' depth limit>'))
    if isinstance(value, dict):
        return any(k.startswith('_truncated') or k.startswith('_omitted') or _incomplete(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_incomplete(v) for v in value)
    return False


# Conservative containment envelope, not a prediction or host qualification.
_COLLECTION_REQUIREMENTS = {'memory_bytes': 536870912, 'cpu_cores': 1.0,
                            'disk_bytes': 805306368, 'pids': 128, 'gpu': False}
_COLLECTION_STDOUT_LIMIT = 16777216
_COLLECTION_FILE_LIMIT = 805306368  # bounded decoded PCM redirected to a file
_COLLECTION_STDERR_LIMIT = 65536


def _capture_native(proc, *, input, timeout, stdout):
    """Nonblocking capped pipe IO; caller owns cancellation/reap/cgroup lifetime.

    Never communicate(): even a small compressed input can expand without bound.
    File-directed PCM is streamed without a RAM copy and has a separate byte cap.
    Keeping all IO in this thread also avoids stranded reader/writer threads.
    """
    import selectors
    import subprocess
    import time
    out, err = bytearray(), bytearray()
    sent, produced = 0, 0
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        for stream, mode, name in ((proc.stdin, selectors.EVENT_WRITE, 'stdin'),
                                   (proc.stdout, selectors.EVENT_READ, 'stdout'),
                                   (proc.stderr, selectors.EVENT_READ, 'stderr')):
            if stream is not None:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, mode, name)
        while selector.get_map() or proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired('owned native decoder', timeout,
                                                output=bytes(out), stderr=bytes(err))
            for key, _ in selector.select(min(remaining, 0.1)):
                # Only file objects registered above can occur here.
                from typing import Any, cast
                stream, name = cast(Any, key.fileobj), key.data
                if name == 'stdin':
                    try:
                        written = os.write(stream.fileno(), input[sent:sent + 65536])
                        sent += written
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        sent = len(input)
                    if sent == len(input):
                        selector.unregister(stream)
                        stream.close()
                    continue
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                if name == 'stderr':
                    err.extend(chunk)
                    del err[:-_COLLECTION_STDERR_LIMIT]
                else:
                    produced += len(chunk)
                    bound = (_COLLECTION_STDOUT_LIMIT if stdout == subprocess.PIPE
                             else _COLLECTION_FILE_LIMIT)
                    if produced > bound:
                        raise ContractError('OUTPUT_INVALID', 'Native decoder exceeded output capture bound.')
                    if stdout == subprocess.PIPE:
                        out.extend(chunk)
                    else:
                        stdout.write(chunk)
    return (bytes(out) if stdout == subprocess.PIPE else None), bytes(err)


class HostBridge:
    def __init__(self, projects, identity):
        self.projects, self.identity = projects, dict(identity)
        self.session = self.identity.get('session_id', '')
        self.base = 'host-bridge/' + _key(self.session)

    def _fs(self):
        return self.projects._filesystem(write=True)

    def _read(self, name):
        try:
            return self._fs().read(self.base + '/' + name)
        except FileNotFoundError:
            return None

    def _write(self, name, value, replace=False):
        self._fs().write(self.base + '/' + name, value, replace=replace)

    def inventory(self):
        return self.observed_inventory()

    def observed_inventory(self):
        """Read only the hook-observed current request; never create or refresh it."""
        rid = self.identity.get('api_request_id', '')
        try:
            record = self.projects._filesystem().read(self.base + '/requests/' + _key(rid) + '.json') if rid else None
        except FileNotFoundError:
            record = None
        if not record or record.get('api_request_id') != rid or record.get('session_id') != self.session:
            raise ContractError('HOST_SCHEMA_UNAVAILABLE', 'Exact current session/request observation unavailable.')
        if (self.session and record and record['session_id'] == self.session
                and record.get('native_complete') and isinstance(record.get('schemas'), dict)):
            return copy.deepcopy(record['schemas'])
        if not self.session or not record or record['session_id'] != self.session or not record['complete']:
            raise ContractError('HOST_SCHEMA_UNAVAILABLE', 'Exact complete session/request-bound frame schema unavailable; inspect host-bridge request diagnostic.')
        return {FRAME_TOOL: copy.deepcopy(record['schema'])}

    def actor(self):
        if not self.session:
            raise ContractError('PERMISSION_DENIED', 'Real host session identity required.')
        return {'kind': 'agent', 'actor_ref': 'hermes:session:' + self.session}

    def observe(self, call_ref):
        record = self._read('calls/' + _key(call_ref) + '.json')
        if not record or record.get('host_call_ref') != call_ref or record.get('session_id') != self.session:
            return None
        return record if 'outcome' in record else None

    def receipts(self, project_id, job_id):
        fs = self._fs()
        result = []
        for name in fs.names(self.base + '/calls'):
            call = self._read('calls/' + name)
            if call.get('project_id') == project_id and call.get('job_id') == job_id and 'outcome' not in call:
                # Recover only this pre-bound real call from the host's public,
                # read-only session store. Never accept caller-supplied results.
                from .runtime import SessionProvenance
                observed = SessionProvenance(self.session).observe_call(call['tool_call_id'])
                if (observed and observed['tool_name'] == call['tool_name']
                        and observed['arguments'] == call['arguments']):
                    _record_frame_result(self, call, observed['result'])
                    call = self._read('calls/' + name)
            if call.get('project_id') == project_id and call.get('job_id') == job_id and 'outcome' in call:
                result.append({k: call[k] for k in ('handoff_id', 'attempt_id', 'request_sha256', 'host_call_ref', 'outcome', 'outputs', 'evidence', 'reported_at')})
        return result

    def validate_staged(self, store, attempt, port, relative):
        """Own bounded decoder children for collection, separate from production.

        The caller holds the job transaction lock, so cancellation/collection
        cannot race admission. No generation command or caller-supplied argv.
        """
        import subprocess
        import stat
        from . import host_safety
        from .adapters.probe import LocalOutputProbe
        if not isinstance(store.output_probe, LocalOutputProbe) or port['media_type'] not in ('image/png', 'audio/wav', 'audio/flac', 'video/mp4'):
            raise ContractError('PERMISSION_DENIED', 'Owned bounded decoder required for native collection.')
        fs = self._fs()
        with fs.directory(attempt['output_dir']) as directory:
            fd = os.open(relative, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ContractError('PATH_UNSAFE', 'Collected frame is not a regular file.')
                payload = stream.read(16777217)
        proof_key = _key(attempt['attempt_id'] + digest_bytes(payload))
        commands = []
        def run(argv, *, input, stdout, stderr, timeout, check):
            if (not argv or input != payload or argv[0] not in ('ffmpeg', 'ffprobe')
                    or not 0 < timeout <= 7200 or stderr != subprocess.PIPE
                    or not (stdout == subprocess.PIPE or callable(getattr(stdout, 'write', None)))):
                raise ContractError('PERMISSION_DENIED', 'Decoder exceeded bounded collection contract.')
            # Collection remains a short, serial, CPU-only decoder route. No raw
            # Popen fallback when admission or kernel enforcement is unavailable.
            timeout = min(timeout, 30)
            policy = host_safety.admission(
                paths=(fs.root, fs.root / attempt['output_dir']),
                requirements=dict(_COLLECTION_REQUIREMENTS))
            with host_safety.OwnedProcessLimits(policy) as limits:
                with fs.directory(attempt['output_dir']) as directory:
                    wrapped, extra = limits.prepare_spawn(argv)
                    proc = subprocess.Popen(wrapped, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=f'/proc/self/fd/{directory}',
                        pass_fds=(directory, *extra['pass_fds']), start_new_session=True)
                owned = {'pid': proc.pid, 'argv': list(argv), 'input_sha256': digest_bytes(payload), 'state': 'running'}
                commands.append(owned)
                try:
                    self._write('decodes/' + proof_key + '.json', {'attempt_id': attempt['attempt_id'], 'commands': commands}, replace=True)
                    out, err = _capture_native(proc, input=input, timeout=timeout, stdout=stdout)
                except BaseException:
                    owned.update(state='failed')
                    raise
                finally:
                    # Signal only this exact Popen. The context kills only its
                    # own cgroup descendants; never infer a process-group owner.
                    try:
                        if proc.poll() is None:
                            proc.kill()
                        proc.wait(timeout=5)
                    except BaseException:
                        owned.update(state='failed')
                        raise
                    finally:
                        for name in ('stdin', 'stdout', 'stderr'):
                            stream = getattr(proc, name, None)
                            if stream is not None:
                                stream.close()
                        owned.update(returncode=proc.returncode)
                        if owned['state'] == 'running':
                            owned['state'] = 'finished'
                        self._write('decodes/' + proof_key + '.json', {'attempt_id': attempt['attempt_id'], 'commands': commands}, replace=True)
            result = subprocess.CompletedProcess(argv, proc.returncode, out, err)
            if check:
                result.check_returncode()
            return result
        receipt_id = store.output_probe.validate(payload, port, run_process=run)
        self._validate_native_output(attempt, port, store.output_probe.receipts[receipt_id])

    def _validate_native_output(self, attempt, port, receipt):
        if port.get('media_type') != 'video/mp4':
            return
        from .adapters.native_tools import lookup_tool
        calls = []
        for name in self._fs().names(self.base + '/calls'):
            call = self._read('calls/' + name)
            if (isinstance(call, dict) and call.get('attempt_id') == attempt['attempt_id'] and call.get('outcome') == 'succeeded'
                    and port in call.get('expected_outputs', [])):
                calls.append(call)
        if len(calls) != 1:
            raise ContractError('OUTPUT_UNAVAILABLE', 'Native collection needs one observed producing call.')
        call = calls[0]
        binding = lookup_tool(call['tool_name'])
        if binding is not None and binding.validate_output is not None:
            binding.validate_output(call['tool_name'], call['arguments'], receipt)

    def retrieve(self, locator, attempt, port):
        # Retrieve only a locator in an observed call, never caller-authored bytes.
        pins = []
        for name in self._fs().names(self.base + '/calls'):
            call = self._read('calls/' + name)
            if call.get('attempt_id') == attempt['attempt_id'] and call.get('outcome') == 'succeeded':
                pins.extend(p for p in call.get('output_pins', []) if p['locator'] == locator and p['port'] == port['port'])
        if len(pins) != 1:
            raise ContractError('OUTPUT_UNAVAILABLE', 'No unique observed output pin.')
        from .assets import _local_file, _identity
        with _local_file(locator['path']) as stream:
            before = _identity(stream)
            payload = stream.read(16777217)
            if before != _identity(stream) or len(payload) > 16777216 or digest_bytes(payload) != pins[0]['sha256'] or len(payload) != pins[0]['size_bytes']:
                raise ContractError('HASH_MISMATCH', 'Observed native output changed before collection.')
        media_type = port.get('media_type', 'image/png' if port['port'] == 'frame' else None)
        extension = {'image/png': 'png', 'audio/wav': 'wav', 'audio/flac': 'flac', 'video/mp4': 'mp4'}.get(media_type)
        if extension is None:
            raise ContractError('OUTPUT_INVALID', 'Unsupported native output media type.')
        prefix = 'native-frame-' if media_type == 'image/png' else 'native-output-'
        name = prefix + pins[0]['sha256'].split(':')[1] + '.' + extension
        with self._fs().directory(attempt['output_dir'], create=True) as directory:
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory)
            except FileExistsError:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(fd, 'rb') as stream:
                    if stream.read(16777217) != payload:
                        raise ContractError('HASH_MISMATCH', 'Owned staging pin differs.')
            else:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(directory)
        return name


def digest_bytes(payload):
    return 'sha256:' + hashlib.sha256(payload).hexdigest()


def consuming_user_evidence(session_id, message_id):
    """Resolve one active user row through the real read-only SessionDB API.

    session_id must come from handler_bridge/host kwargs, never tool arguments.
    Message content is transient; the permission store persists only its hash.
    This does not turn host-policy approval or an agent result into user consent.
    """
    if (not isinstance(session_id, str) or not session_id
            or not isinstance(message_id, str) or not message_id.isascii()
            or not message_id.isdecimal() or str(int(message_id)) != message_id
            or int(message_id) < 1):
        raise ContractError('PERMISSION_DENIED', 'Trusted current session and exact user message row ID are required.')
    try:
        from hermes_state import SessionDB
        db = SessionDB(read_only=True)
        try:
            rows = db.get_messages(session_id, after_id=int(message_id) - 1, limit=1)
        finally:
            db.close()
    except Exception:
        raise ContractError('PERMISSION_DENIED', 'Read-only host user-message evidence is unavailable.') from None
    row = rows[0] if len(rows) == 1 else None
    if (not isinstance(row, dict) or str(row.get('id')) != message_id
            or row.get('session_id', session_id) != session_id or row.get('role') != 'user'
            or row.get('_compressed_summary') or row.get('tool_call_id')
            or not isinstance(row.get('content'), str)):
        raise ContractError('PERMISSION_DENIED', 'No exact active user message in the current session.')
    return {'session_id': session_id, 'message_id': message_id, 'content': row['content']}


def observe_request(**event):
    sid, rid = event.get('session_id'), event.get('api_request_id')
    if not sid or not rid:
        return
    bridge = HostBridge(ProjectStore(), event)
    # The public immutable JSON snapshot is exact; diagnostic previews are never
    # schema authority, even when they happen to fit their current size limit.
    raw = event.get('selected_tool_schema_snapshot')
    try:
        snapshot = json.loads(raw) if isinstance(raw, str) else {}
    except (ValueError, TypeError):
        snapshot = {}
    valid = (isinstance(snapshot, dict) and snapshot.get('version') == 1
             and snapshot.get('complete') is True and snapshot.get('session_id') == sid
             and snapshot.get('api_request_id') == rid and isinstance(snapshot.get('tools'), list))
    tools = snapshot['tools'] if valid else []
    selected = []
    names = []
    native_schemas = {}
    for tool in tools if isinstance(tools, list) else []:
        if not isinstance(tool, dict):
            continue
        function = tool.get('function', tool)
        if isinstance(function, dict):
            names.append(function.get('name'))
            if function.get('name') in native_tool_names() and isinstance(function.get('parameters'), dict):
                native_schemas[function['name']] = function['parameters']
            if function.get('name') == FRAME_TOOL:
                selected.append(function.get('parameters'))
    # Deferred tools are intentionally absent from the provider request. Their
    # public description is scoped by Hermes; never consult a global registry.
    unique_native = all(names.count(name) <= 1 for name in native_tool_names() | {'motion_run'})
    turn = event.get('turn_id')
    if valid and not _incomplete(tools) and 'tool_call' in names and turn:
        described = bridge._read('described/' + _key(turn) + '.json') or {}
        if described.get('session_id') == sid and described.get('turn_id') == turn:
            schemas = described.get('schemas', {})
            native_schemas.update({name: value for name, value in schemas.items() if name in native_tool_names()})
            if not selected and FRAME_TOOL in schemas:
                selected.append(schemas[FRAME_TOOL])
                names.append(FRAME_TOOL)
            if 'motion_run' not in names and 'motion_run' in schemas:
                names.append('motion_run')
    reason = 'complete'
    if not valid or _incomplete(tools):
        reason = 'missing_incomplete_or_mismatched_exact_schema_snapshot'
    elif len(selected) != 1 or not isinstance(selected[0], dict):
        reason = 'selected_frame_schema_not_exposed'
    elif 'motion_run' not in names:
        reason = 'motion_run_not_exposed'
    complete = reason == 'complete'
    bridge._write('requests/' + _key(rid) + '.json', {
        'session_id': sid, 'api_request_id': rid, 'turn_id': event.get('turn_id'),
        'complete': complete, 'reason': reason, 'tool_names': names,
        'schema': selected[0] if complete else None,
        'schema_sha256': digest(selected[0]) if complete else None,
        'schemas': native_schemas if valid and unique_native and not _incomplete(tools) else {},
        'native_complete': bool(valid and unique_native and not _incomplete(tools) and 'motion_run' in names),
        'observed_at': _now()}, replace=True)


def pre_tool(**event):
    if (event.get('tool_name') in ('motion_capabilities', 'motion_plan', 'motion_run', 'motion_caption', 'motion_review', 'motion_deliver')
            and event.get('session_id') and event.get('tool_call_id')):
        bridge = HostBridge(ProjectStore(), event)
        key = _key(event['tool_call_id']) + '.json'
        record = {'session_id': event['session_id'], 'tool_call_id': event['tool_call_id'],
            'api_request_id': event.get('api_request_id', ''), 'turn_id': event.get('turn_id', ''),
            'task_id': event.get('task_id') or '', 'tool_name': event['tool_name'],
            'args_sha256': digest(event.get('args', {})), 'consumed': False}
        old = bridge._read('invocations/' + key)
        if old is None:
            bridge._write('invocations/' + key, record)
    if event.get('tool_name') not in native_tool_names() or not event.get('session_id') or not event.get('tool_call_id'):
        return
    bridge = HostBridge(ProjectStore(), event)
    fs = bridge._fs()
    with fs.lock(bridge.base + '/binding.lock'):
        matches = []
        for name in fs.names(bridge.base + '/claims'):
            claim = bridge._read('claims/' + name)
            if claim and claim['tool_name'] == event['tool_name'] and claim['arguments'] == event.get('args'):
                matches.append((name, claim))
        if not matches:
            return  # Unrelated native tool use is not captured or altered.
        if len(matches) != 1:
            return {'action': 'block', 'message': 'Motion Studio: ambiguous pending frame claim.'}
        name, claim = matches[0]
        from .permissions import require_native_admission
        try:
            require_native_admission(claim.get('effects'))
        except ContractError as exc:
            return {'action': 'block', 'message': exc.message}
        ref = 'hermes:' + bridge.session + ':' + event['tool_call_id']
        bound = bridge._read('bindings/' + name)
        if bound and bound['host_call_ref'] != ref:
            return {'action': 'block', 'message': 'Motion Studio: claim already bound; reconcile the same call, never resubmit.'}
        try:
            if digest(bridge.inventory()[event['tool_name']]) != claim['tool_schema_sha256']:
                raise ContractError('HANDOFF_MISMATCH', 'Actual exposed frame schema changed.')
        except (ContractError, KeyError) as exc:
            return {'action': 'block', 'message': getattr(exc, 'message', 'Native schema is no longer exposed.')}
        if not bound:
            bridge._write('bindings/' + name, {'host_call_ref': ref})
            bridge._write('calls/' + _key(ref) + '.json', claim | {
                'session_id': bridge.session, 'host_call_ref': ref,
                'tool_call_id': event['tool_call_id'], 'api_request_id': event.get('api_request_id'),
                'turn_id': event.get('turn_id'), 'actor': bridge.actor()})
            from .usage import UsageLedger
            UsageLedger(bridge.projects, bridge.session).begin(event, claim=claim)


def _observe_description(bridge, event, result):
    turn, rid = event.get('turn_id'), event.get('api_request_id')
    request = bridge._read('requests/' + _key(rid) + '.json') if rid else None
    if (not turn or not request or request.get('session_id') != bridge.session
            or request.get('turn_id') != turn
            or 'tool_describe' not in request.get('tool_names', [])):
        return
    names = (event.get('args') or {}).get('names', [])
    if not isinstance(names, list):
        return
    names = [name for name in names if name in native_tool_names() | {'motion_run'}]
    if not names:
        return
    path = 'described/' + _key(turn) + '.json'
    record = bridge._read(path) or dict(session_id=bridge.session, turn_id=turn, schemas={})
    tools = result.get('tools', {}) if isinstance(result, dict) else {}
    for name in names:
        record['schemas'].pop(name, None)
        descriptor = tools.get(name) if isinstance(tools, dict) else None
        schema = descriptor.get('parameters') if isinstance(descriptor, dict) else None
        if event.get('status') == 'ok' and isinstance(schema, dict) and not _incomplete(result):
            record['schemas'][name] = schema
    bridge._write(path, record, replace=True)


def post_tool(**event):
    if not event.get('session_id') or not event.get('tool_call_id'):
        return
    bridge = HostBridge(ProjectStore(), event)
    result = event.get('result')
    try:
        result = json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError):
        return
    if event.get('tool_name') == 'tool_describe':
        _observe_description(bridge, event, result)
        return
    if event.get('tool_name') == 'motion_run' and event.get('args', {}).get('action') == 'handoff_claim' and isinstance(result, dict) and result.get('ok') is True:
        handoff = result.get('data', {}).get('handoff')
        if not isinstance(handoff, dict) or handoff.get('tool_name') not in native_tool_names() or handoff.get('claimed_by') != bridge.actor():
            return
        name = _key(handoff['handoff_id']) + '.json'
        claim = copy.deepcopy(handoff) | {'project_id': event['args']['project_id'],
            'claim_tool_call_id': event['tool_call_id'], 'claim_api_request_id': event.get('api_request_id')}
        old = bridge._read('claims/' + name)
        if old is None:
            bridge._write('claims/' + name, claim)
        return
    if event.get('tool_name') not in native_tool_names():
        return
    ref = 'hermes:' + bridge.session + ':' + event['tool_call_id']
    name = 'calls/' + _key(ref) + '.json'
    call = bridge._read(name)
    if not call or call['arguments'] != event.get('args') or call['api_request_id'] != event.get('api_request_id'):
        return
    _record_frame_result(bridge, call, result)


def _record_frame_result(bridge, call, result):
    """Normalize host JSON without applying the project's no-float document ABI."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            return
    name = 'calls/' + _key(call['host_call_ref']) + '.json'
    if call.get('outcome') in ('succeeded', 'failed'):
        return  # Terminal result immutable; only the same uncertain call may reconcile.
    outcome, outputs, pins = 'uncertain', [], []
    if isinstance(result, dict) and result.get('ok') is False:
        outcome = 'failed'
    elif isinstance(result, dict) and result.get('ok') is True:
        from .adapters.native_tools import lookup_tool
        recipe = lookup_tool(call['tool_name'])
        path = result.get(recipe.result_output_field if recipe else 'output')
        try:
            if not isinstance(path, str) or path != call['arguments'].get('output') or not Path(path).is_absolute() or len(call['expected_outputs']) != 1:
                raise ValueError('Unexpected frame output location/port closure.')
            from .assets import _local_file, _identity
            with _local_file(path) as stream:
                before = _identity(stream)
                payload = stream.read(16777217)
                if before != _identity(stream) or not 0 < len(payload) <= 16777216:
                    raise ValueError('Unstable/oversized frame output.')
            locator = {'kind': 'local', 'path': path}
            port = call['expected_outputs'][0]['port']
            outputs = [{'port': port, 'locator': locator}]
            pins = [outputs[0] | {'sha256': digest_bytes(payload), 'size_bytes': len(payload)}]
            outcome = 'succeeded'
        except (OSError, ValueError, ContractError):
            pass
    bridge._write(name, call | {'outcome': outcome, 'outputs': outputs, 'output_pins': pins,
        'reported_at': _now(), 'evidence': [],
        'result_sha256': digest_bytes(json.dumps(result, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, allow_nan=False).encode('utf-8'))}, replace=True)


def handler_bridge(projects, tool_name, args, host_context):
    """Join public handler session/task kwargs to exactly one real pre-call.

    Lifecycle callbacks may execute in another context; contextvar propagation
    is not assumed. Ambiguous or consumed associations fail closed.
    """
    sid = host_context.get('session_id')
    if not isinstance(sid, str) or not sid:
        return None
    bridge = HostBridge(projects, {'session_id': sid})
    fs = bridge._fs()
    with fs.lock(bridge.base + '/handler-association.lock'):
        matching = []
        for name in fs.names(bridge.base + '/invocations'):
            call = bridge._read('invocations/' + name)
            if (not call['consumed'] and call['tool_name'] == tool_name
                    and call['task_id'] == (host_context.get('task_id') or '')
                    and call['args_sha256'] == digest(args) and call['session_id'] == sid):
                matching.append((name, call))
        if len(matching) != 1:
            return None
        name, call = matching[0]
        bridge._write('invocations/' + name, call | {'consumed': True}, replace=True)
        return HostBridge(projects, call)


def register_hooks(ctx):
    from .usage import pre_call, post_call, post_api, pre_api
    ctx.register_hook('pre_api_request', observe_request)
    ctx.register_hook('pre_api_request', pre_api)
    ctx.register_hook('pre_tool_call', pre_tool)
    ctx.register_hook('post_tool_call', post_tool)
    ctx.register_hook('pre_tool_call', pre_call)
    ctx.register_hook('post_tool_call', post_call)
    ctx.register_hook('post_api_request', post_api)


def register_frame_adapter(registry, bridge):
    """Declare only the bounded zero-source-origin PNG operation, not other tools."""
    from .capabilities import builtin_ffmpeg, PARAMS, expanded
    from .adapters.media_probe import result_schema
    from .handoffs import HANDOFF
    from .contracts import nullable
    declaration, _ = builtin_ffmpeg(None)
    declaration.update(adapter_id=ADAPTER_ID, label='Normal Hermes frame extraction',
        transport='host_handoff', location='agent', implementation_version='1.0')
    op = declaration['operations'][0]
    op.update(operation=OPERATION, request_schema='motion/v1/hermes-frame-request',
        result_schema='motion/v1/hermes-frame-result')
    op['supports']['collect'] = True
    declaration['dependencies'] = [{'name': FRAME_TOOL, 'kind': 'host_tool', 'version_constraint': None, 'required': True}]
    schema = None
    reason = 'No normal session-bound frame schema observed.'
    if bridge is not None:
        try:
            schema = bridge.inventory()[FRAME_TOOL]
            reason = 'Exact current normal-session frame tool schema observed; execution is not yet evidence.'
        except (ContractError, KeyError) as exc:
            reason = getattr(exc, 'message', 'Exact frame tool is absent from this request.')
    native_result = result_schema()
    native_result['properties']['handoff'] = nullable(HANDOFF)
    hashes = {'bridge_source': digest_bytes(Path(__file__).read_bytes()), 'host_schema': digest(schema) if schema else None}
    registry.register(declaration, implementation_sha256=digest(hashes),
        schemas={op['request_schema']: expanded(PARAMS[OPERATION]), op['result_schema']: native_result},
        outputs={OPERATION: [{'port': 'frame', 'kind': 'frame', 'media_type': 'image/png'}]},
        state='available' if schema else 'unavailable',
        checks=[{'name': 'exact-session-tool-schema', 'status': 'pass' if schema else 'fail', 'reason': reason}])


def validate_frame_timing(request, *, resolve_artifact):
    """Source frame zero has no rate conversion; never authorize other timing."""
    p = request['parameters']
    at = p['at']
    media = request.get('inputs', {}).get('media', {})
    if (request.get('adapter_id') != ADAPTER_ID or request.get('operation') != OPERATION
            or set(request.get('inputs', {})) != {'media'} or media.get('kind') != 'artifact'
            or p['format'] != 'png' or p['apply_rotation'] is not True
            or at['domain'] != 'frame' or at['origin'] != 'source' or at['index'] != 0):
        raise ContractError('UNSUPPORTED_FEATURE', 'Native handoff timing is restricted to source frame zero PNG.')
    pin = media['artifact']
    if at.get('source_artifact', pin) != pin:
        raise ContractError('HASH_MISMATCH', 'Frame time origin differs from exact media pin.')
    resolve_artifact(pin)  # Core resolver verifies ownership and unchanged source bytes.
    return []


class FrameAdapter:
    owned_local = False

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, copy.deepcopy(binding)

    def validate_request(self, request):
        if self.runtime.host_bridge is None:
            raise ContractError('PERMISSION_DENIED', 'Normal host bridge required.')
        expected = self.runtime.registry.binding(ADAPTER_ID, request['operation'], request['parameters'], request.get('binding_parameters'))
        if request.get('operation') != OPERATION or expected != self.binding or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen frame adapter/schema binding changed.')
        from .tool_integration import require_compatible_binding
        require_compatible_binding(self.runtime.registry, self.binding,
            operation=request['operation'], parameters=request['parameters'],
            binding_parameters=request.get('binding_parameters'), bridge=self.runtime.host_bridge)
        p = request['parameters']
        at = p['at']
        if (p['format'] != 'png' or p['apply_rotation'] is not True or at['index'] != 0
                or at['domain'] != 'frame' or at['origin'] != 'source'
                or set(request['inputs']) != {'media'}):
            raise ContractError('UNSUPPORTED_FEATURE', 'Bounded bridge supports source frame zero, PNG, native rotation, one media pin only.')
        pin = request['inputs']['media']
        if at.get('source_artifact', pin) != pin:
            raise ContractError('HASH_MISMATCH', 'Frame time origin differs from exact media pin.')
        # resolve verifies exact input hash; no caller path is passed through.
        self.runtime.artifacts.resolve(request['project_id'], pin)
        return {'valid': True, 'effects': self.runtime.registry.effects(ADAPTER_ID)}

    def execute(self, request, attempt):
        from .project import _id
        from .contracts import validate
        self.validate_request(request)
        inventory = self.runtime.host_bridge.inventory()
        from .tool_integration import require_compatible_binding
        require_compatible_binding(self.runtime.registry, self.binding,
            operation=request['operation'], parameters=request['parameters'],
            binding_parameters=request.get('binding_parameters'), inventory=inventory)
        schema = inventory[FRAME_TOOL]
        source = self.runtime.artifact_path(request['project_id'], request['inputs']['media'])
        fs = self.runtime.projects._filesystem(write=True)
        with fs.directory(attempt['output_dir'], create=True):
            pass
        output = str(fs.root / attempt['output_dir'] / 'host-extracted-frame.png')
        arguments = {'input': str(source), 'output': output, 'time': 0, 'format': 'png', 'overwrite': False, 'timeout_s': 60}
        validate(arguments, schema)
        return {'state': 'awaiting_external', 'submission_state': 'not_sent',
            'external_handle': None, 'remote_state': 'none', 'progress': None, 'outputs': [],
            'warnings': [], 'error': None, 'observed_cost': None, 'logs_ref': None,
            'handoff': {'handoff_id': _id('hnd'), 'job_id': attempt['job_id'],
                'node_id': attempt['node_id'], 'attempt_id': attempt['attempt_id'],
                'request_sha256': request['request_sha256'], 'kind': 'host_tool',
                'tool_name': FRAME_TOOL, 'tool_schema_sha256': digest(schema),
                'arguments': arguments, 'expected_outputs': [{'port': 'frame', 'kind': 'frame', 'media_type': 'image/png'}],
                'effects': self.runtime.registry.effects(ADAPTER_ID), 'state': 'ready',
                'claimed_by': None, 'host_call_ref': None,
                'instructions': 'Claim with motion_run.handoff_claim; invoke exact lk_extract_frame arguments once through normal approval; collect with receipts omitted to use only the trusted observed result.'}}
