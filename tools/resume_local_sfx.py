"""One explicit resume of the original proven pre-Popen CF-LQ1 refusal. No new plan."""
import argparse
import json
import os
from pathlib import Path
import time
from studio.domain import Fault
from studio.persistence.store import canonical
from studio.producer.live_sfx import USE
from studio.runs.admission import OneCandidate
from tools.reconcile_local_sfx import inspect_original


def resume_scope(runs, owner, original, value):
    facts, ledger, row, previous = inspect_original(runs.store.home)
    if not facts['proven_prelaunch_refusal'] or ledger != original:
        raise Fault('RESUME_NOT_PROVEN_SAFE', 409)
    plan = row['plan']
    body = ledger['prepare']
    if (ledger.get('scope') != 'CF-LQ1-r1' or ledger.get('use') != USE
            or value.direction != plan['direction'] or value.use != USE
            or ledger['binding'] != plan['binding']['id']
            or ledger['binding_revision'] != plan['binding']['revision']
            or body['request'] != plan['request'] or body['revision'] != plan['revision']
            or body['binding'] != ledger['binding'] or body['binding_revision'] != ledger['binding_revision']
            or body['operation'] != 'sfx' or plan['adapter'] != 'stable-audio-local'
            or body['options'] != dict(seconds=3.0, seed=42, language='en')
            or runs.bindings.get(ledger['binding']) != plan['binding']):
        raise Fault('RESUME_PLAN_CONFLICT', 409)
    scope = object.__new__(OneCandidate)
    scope.runs, scope.run, scope.use = runs, row['id'], USE
    scope.owner = scope.owner_key(owner)
    scope.plan, scope.key = plan, row['plan_digest']
    scope.runtime, scope.observation = None, {}
    with runs.store.transaction() as db:
        current = dict(db.execute('SELECT * FROM local_runs WHERE id=?', (row['id'],)).fetchone())
        for field in ('plan', 'process', 'collection'):
            current[field] = json.loads(current[field]) if current[field] else None
        saved = dict(db.execute('SELECT * FROM bounded_admission WHERE scope=?', (scope.scope,)).fetchone())
        if current != row or saved != previous:
            raise Fault('RESUME_STATE_CHANGED', 409)
        db.execute('CREATE TABLE IF NOT EXISTS bounded_resume(scope TEXT PRIMARY KEY, prior TEXT)')
        if db.execute('SELECT 1 FROM bounded_resume WHERE scope=?', (scope.scope,)).fetchone():
            raise Fault('RESUME_ALREADY_ATTEMPTED', 409)
        # Preserve the old owner/scope and proof. Never erase a consumed/unknown state.
        db.execute('INSERT INTO bounded_resume VALUES(?,?)',
                   (scope.scope, canonical(dict(scope=previous, proof=facts, nonce=row['nonce']))))
        changed = db.execute("""UPDATE bounded_admission SET owner=?,expires=?,state='armed'
                             WHERE scope=? AND state='closed' AND run=? AND plan=?""",
                             (scope.owner, time.time() + 900, scope.scope, scope.run, scope.key)).rowcount
        if changed != 1:
            raise Fault('RESUME_STATE_CHANGED', 409)
    return runs.records.public(row['id']), body, plan['binding'], scope


def main():
    from tools.qualify_local_sfx import evaluate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('var'))
    parser.add_argument('--operation', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        evaluate(args.state, args.operation, _resume=True)
    except BaseException as error:
        print(json.dumps(dict(status='no_retry', reason=error.code if isinstance(error, Fault) else type(error).__name__)), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
