"""Operator-only CF-LQ1 one-run qualification through authenticated ASGI app actions.

Reads an explicit private operation JSON; never called by normal launcher or browser.
No second candidate/retry is created when intent or any real run already exists.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import time
import wave
from fastapi.testclient import TestClient
from studio.domain import Fault, Strict
from studio.persistence.store import identity
from studio.producer import local_sfx as sfx
from studio.producer.live_sfx import ScopedRuntime, USE
from studio.runs.admission import OneCandidate
from studio.runs.helper_environment import helper_environment
from studio.assets.producer_files import allocation, read_leaf
from studio.server import create_app
from typing import Any, Literal
from pydantic import Field


class Evaluation(Strict):
    direction: str = Field(min_length=1, max_length=2000)
    use: Literal['noncommercial_local_technical_evaluation']
    seconds: float = Field(default=3.0, ge=3.0, le=3.0, allow_inf_nan=False)
    seed: Literal[42] = 42
    language: Literal['en'] = 'en'


def private_json(path, value):
    temporary = path.with_suffix('.new')
    with temporary.open('x') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def no_previous_test(home, intent):
    if intent.exists():
        raise Fault('EXISTING_TEST_INTENT_RECONCILE_SAME_RUN', 409)
    database = home / 'state' / 'studio.db'
    if database.exists():
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            table = db.execute("SELECT 1 FROM sqlite_master WHERE name='local_runs'").fetchone()
            if table and db.execute('SELECT 1 FROM local_runs WHERE fixture=0 LIMIT 1').fetchone():
                raise Fault('EXISTING_REAL_RUN_RECONCILE_SAME_RUN', 409)


def post(client, route, body):
    response = client.post(route, json=body)
    if response.status_code != 200:
        raise Fault(response.json().get('error', 'APP_ACTION_DENIED'), response.status_code)
    return response.json()


def verify_result(client, runs, item, ledger, home):
    row = runs.records.get(item['id'])

    # Existing collector already checked native model/input/seed/output association and PCM.
    data = client.get(f'/api/takes/{item["candidate"]}/media?download=true')
    if data.status_code != 200:
        raise Fault('RETRIEVAL_FAILED', 409)
    retained = home / 'media' / (item['candidate'] + '.wav')
    digest = hashlib.sha256(data.content).hexdigest()
    if data.content != retained.read_bytes() or data.headers['x-artifact-sha256'] != digest:
        raise Fault('RETRIEVAL_MISMATCH', 409)
    downloaded = home / 'state' / 'lq1-downloaded.wav'
    with downloaded.open('xb') as stream:
        stream.write(data.content)
    with wave.open(str(downloaded), 'rb') as wav:
        facts = dict(frames=wav.getnframes(), channels=wav.getnchannels(), rate=wav.getframerate(), width=wav.getsampwidth())
    if facts != dict(frames=132300, channels=2, rate=44100, width=2):
        raise Fault('PCM_MISMATCH', 409)
    decoded = subprocess.run(['/usr/bin/ffmpeg', '-v', 'error', '-i', str(downloaded),
                              '-f', 's16le', '-acodec', 'pcm_s16le', '-'],
                             capture_output=True, timeout=30, check=True,
                             env=helper_environment(), stdin=subprocess.DEVNULL)
    if len(decoded.stdout) != 529200:
        raise Fault('INDEPENDENT_DECODE_MISMATCH', 409)
    _, descriptor, _ = allocation(runs.store, row)
    try:
        receipt = json.loads(read_leaf(descriptor, 'candidate.wav.json', 16384))
    finally:
        os.close(descriptor)
    ledger.update(status='technically_verified', run=item['id'], candidate=item['candidate'],
                  bytes=len(data.content), sha256=digest, facts=facts, independent_decode_bytes=len(decoded.stdout),
                  plan_digest=row['plan_digest'], process=row['process'], native_receipt=receipt,
                  elapsed_seconds=receipt['elapsed_seconds'], gpu_peak_mib=receipt['gpu_peak_allocated_mib'],
                  origin=runs.records.public(item['id'])['origin'], listening='Not reviewed')
    if ledger['origin'] != 'producer_output' or row['generation'] != 1 or not row['process']['exited']:
        raise Fault('PROVENANCE_MISMATCH', 409)
    return digest, facts


def evaluate(home, operation, *, _resume=False, _recovery=False):
    home = home.absolute()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = home / 'state'
    state.mkdir(mode=0o700, exist_ok=True)
    intent = state / 'lq1-intent.json'
    with (state / 'lq1-operator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = None
        predecessor = None
        if _recovery:
            from tools.qualify_runtime_recovery import historical
            predecessor = historical(home)
            intent = state / 'rr1-intent.json'
            if intent.exists():
                raise Fault('RECOVERY_ALREADY_ATTEMPTED', 409)
        elif _resume:
            from tools.reconcile_local_sfx import inspect_original
            facts, original, _, _ = inspect_original(home)
            if not facts['proven_prelaunch_refusal']:
                raise Fault('RESUME_NOT_PROVEN_SAFE', 409)
            intent = state / 'lq1-resume-intent.json'
            if intent.exists():
                raise Fault('RESUME_ALREADY_ATTEMPTED', 409)
        else:
            no_previous_test(home, intent)
        value = Evaluation(**json.loads(operation.read_text()))
        secret = secrets.token_bytes(32).hex().encode()
        app = create_app(home, secret, 'http://testserver')
        runs = app.state.runs
        scope, captures = None, {}
        ledger: dict[str, Any] = dict(status='preparing', scope='CF-LQ1-r1', use=value.use)
        if predecessor is not None:
            ledger.update(scope='CF-RR1-r1', previous_run=predecessor['run'], previous_candidate=predecessor['candidate'])
        if original is not None:
            ledger.update(previous_attempt=original, run=original['run'], candidate=original['candidate'])
        private_json(intent, ledger)
        try:
            with TestClient(app) as client:
                client.headers.update({'origin': 'http://testserver'})
                login = post(client, '/api/login', {'secret': secret.decode()})
                client.headers.update({'origin': 'http://testserver', 'x-csrf-token': login['csrf']})
                if predecessor is not None:
                    from tools.qualify_runtime_recovery import prepare_successor
                    post(client, f'/api/sfx/runs/{predecessor["run"]}/reconcile', {})
                    item, body, record = prepare_successor(client, runs, predecessor, value)
                elif original is not None:
                    from tools.resume_local_sfx import resume_scope
                    item, body, record, scope = resume_scope(runs, login['csrf'], original, value)
                else:
                    record = runs.bindings.save(dict(adapter='stable-audio-local', adapter_version=1,
                        interface_version='stable-audio-cli-v1', executable=str(sfx.WRAPPER)), permitted={str(sfx.WRAPPER)})
                    saved = post(client, '/api/requests', dict(command=identity(), expected=0, kind='Sound effects',
                        text=value.direction, purpose='Local technical evaluation; no publication/distribution/commercial clearance'))
                    post(client, '/api/apps/method', dict(request=saved['id'], binding=record['id'], revision=record['revision'], operation='sfx'))
                    body = dict(command=identity(), request=saved['id'], revision=1, binding=record['id'],
                        binding_revision=record['revision'], operation='sfx', options=dict(seconds=value.seconds, seed=value.seed, language=value.language))
                    item = post(client, '/api/apps/plans', body)
                ledger.update(status='prepared', run=item['id'], candidate=item['candidate'], prepare=body,
                              binding=record['id'], binding_revision=record['revision'])
                private_json(intent, ledger)
                if scope is None:
                    if predecessor is not None:
                        from tools.qualify_runtime_recovery import RecoveryCandidate
                        scope = RecoveryCandidate(runs, item['id'], login['csrf'], USE)
                    else:
                        scope = OneCandidate(runs, item['id'], login['csrf'], USE)
                scope.install(ScopedRuntime(record=record, scope=scope))
                for name in ('stdout', 'stderr'):
                    prefix = 'rr1-' if _recovery else ('lq1-resume-' if _resume else 'lq1-')
                    captures[name] = (state / (prefix + name + '.bin')).open('xb')
                def capture(name, chunk):
                    captures[name].write(chunk)
                runs.worker.capture_chunk = capture
                print(json.dumps(dict(status='app_start_requested', candidates=1, real=True)), flush=True)
                post(client, f'/api/sfx/runs/{item["id"]}/start', {})
                deadline = time.monotonic() + 650
                observed = {'status': 'Outcome unknown', 'error': 'OBSERVATION_UNAVAILABLE'}
                while time.monotonic() < deadline:
                    observed = client.get(f'/api/sfx/runs/{item["id"]}').json()
                    if observed['status'] not in ('Starting', 'Running', 'Cancelling', 'Collecting'):
                        break
                    time.sleep(0.25)
                ledger.update(app_status=observed['status'], admission=scope.observation)
                private_json(intent, ledger)
                if observed['status'] != 'Ready for review':
                    raise Fault(observed.get('error') or 'EFFECT_NOT_VERIFIED', 409)
                digest, facts = verify_result(client, runs, item, ledger, home)
                scope.close()
                scope = None
                if post(client, '/api/apps/plans', body)['id'] != item['id']:
                    raise Fault('REPLAY_MISMATCH', 409)
                if post(client, f'/api/sfx/runs/{item["id"]}/start', {})['status'] != 'Ready for review':
                    raise Fault('REPLAY_MISMATCH', 409)
                post(client, '/api/logout', {})
                if client.get(f'/api/takes/{item["candidate"]}/media').status_code != 401:
                    raise Fault('RETRIEVAL_SCOPE_MISMATCH', 409)
            # New app instance uses only normal disabled bindings; no grant/runtime is restored.
            reopened = create_app(home, secret, 'http://testserver')
            try:
                with TestClient(reopened) as client:
                    auth = client.post('/api/login', json={'secret': secret.decode()}, headers={'origin':'http://testserver'}).json()
                    client.headers.update({'origin':'http://testserver', 'x-csrf-token':auth['csrf']})
                    receipt = client.get(f'/api/takes/{item["candidate"]}/media')
                    if hashlib.sha256(receipt.content).hexdigest() != digest or receipt.status_code != 200:
                        raise Fault('REOPEN_MISMATCH', 409)
                    if post(client, f'/api/sfx/runs/{item["id"]}/start', {})['status'] != 'Ready for review':
                        raise Fault('REOPEN_MISMATCH', 409)
                    if reopened.state.runs.scopes or reopened.state.runs.bindings.get(record['id'])['enabled']:
                        raise Fault('DISPATCH_NOT_DISABLED', 409)
            finally:
                reopened.state.runs.close()
            ledger.update(status='qualified_once_dispatch_disabled', reopened_same_artifact=True, generation=1)
            private_json(intent, ledger)
            print(json.dumps(dict(status=ledger['status'], bytes=ledger['bytes'], facts=facts,
                                  independent_decode=True, scoped_bytes_equal=True, reopened_same_artifact=True,
                                  origin=ledger['origin'], elapsed_seconds=ledger['elapsed_seconds'],
                                  gpu_peak_mib=ledger['gpu_peak_mib'], listening='Not reviewed')), flush=True)
        except BaseException as error:
            ledger.update(status='stopped_no_retry', error=error.code if isinstance(error, Fault) else type(error).__name__)
            private_json(intent, ledger)
            print(json.dumps(dict(status='stopped_no_retry', reason=ledger['error'])), flush=True)
            raise
        finally:
            if scope is not None:
                scope.close()
            runs.close()
            for stream in captures.values():
                stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation', type=Path, required=True)
    parser.add_argument('--state', type=Path, default=Path('var'))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        evaluate(args.state, args.operation)
    except BaseException as error:
        print(json.dumps(dict(status='no_retry', reason=error.code if isinstance(error, Fault) else type(error).__name__)), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
