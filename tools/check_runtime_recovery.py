"""Bounded CF-RR1 observer; optional authenticated retirement commit, never launch."""
import argparse
import json
from pathlib import Path
import secrets
from fastapi.testclient import TestClient
from studio.domain import Fault
from studio.producer.live_sfx import resources
from studio.runs.reconciliation import observe
from studio.server import create_app
from tools.qualify_local_sfx import post
from tools.qualify_runtime_recovery import historical


def inspect(home, *, commit=False):
    home = home.absolute()
    prior = historical(home)
    secret = secrets.token_bytes(32).hex().encode()
    app = create_app(home, secret, 'http://testserver')
    runs = app.state.runs
    try:
        row = runs.records.get(prior['run'])
        if row['candidate'] != prior['candidate']:
            raise Fault('RECONCILIATION_NOT_APPLICABLE', 409)
        if not (row['process'] or {}).get('retirement_reconciled'):
            evidence = observe(runs, prior['run'])
            if commit:
                with TestClient(app) as client:
                    client.headers['origin'] = 'http://testserver'
                    login = post(client, '/api/login', {'secret':secret.decode()})
                    client.headers['x-csrf-token'] = login['csrf']
                    post(client, f'/api/sfx/runs/{prior["run"]}/reconcile', {})
        else:
            with runs.store.transaction() as db:
                evidence = json.loads(db.execute('SELECT record FROM run_reconciliations WHERE run=?', (prior['run'],)).fetchone()[0])
        row = runs.records.get(prior['run'])
        free, conflict = resources()
        with runs.store.transaction() as db:
            scopes = [v[0] for v in db.execute('SELECT state FROM bounded_admission WHERE run=?', (prior['run'],))]
        result = dict(status=row['status'], certainty=row['certainty'], reason=row['error'],
            retirement_sufficient=True, exit_code_observed=bool((row['process'] or {}).get('exited')),
            output_collection_absent=row['collection'] is None, original_scope_states=scopes,
            elapsed_seconds_min=min(v['elapsed'] for v in evidence['observations']),
            retirement_reconciled=bool((row['process'] or {}).get('retirement_reconciled')),
            gpu_free_mib=free, known_wrapper_conflict=conflict,
            selected_binding_enabled=runs.bindings.get(row['plan']['binding']['id'])['enabled'])
        print(json.dumps(result, indent=2))
        return result
    finally:
        runs.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--commit', action='store_true')
    args = parser.parse_args()
    try:
        inspect(args.state, commit=args.commit)
    except BaseException as error:
        print(json.dumps(dict(status='blocked_no_launch', reason=error.code if isinstance(error, Fault) else type(error).__name__)))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
