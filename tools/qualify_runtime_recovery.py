"""One explicit CF-RR1 successor to a reconciled original; never an automatic retry."""
import argparse
import json
import os
from pathlib import Path
from studio.domain import Fault
from studio.persistence.store import identity
from studio.runs.admission import OneCandidate
from studio.producer.live_sfx import USE


class RecoveryCandidate(OneCandidate):
    scope = 'bounded-runtime-recovery-r1'


def historical(home):
    original = json.loads((home / 'state/lq1-resume-intent.json').read_text())
    if original.get('status') != 'stopped_no_retry' or original.get('error') != 'OUTPUT_UNSAFE':
        raise Fault('RECOVERY_NOT_APPLICABLE', 409)
    return original


def prepare_successor(client, runs, previous, value):
    from tools.qualify_local_sfx import post
    old = runs.records.get(previous['run'])
    if (old['status'] != 'Failed' or old['certainty'] != 'started'
            or not (old['process'] or {}).get('retirement_reconciled') or old['error'] != 'OUTPUT_UNSAFE'
            or old['candidate'] != previous['candidate'] or old['fixture']):
        raise Fault('RECOVERY_UNRESOLVED', 409)
    plan = old['plan']
    if ({key: plan['parameters'][key] for key in ('seconds','steps','seed','language')} !=
            dict(seconds=value.seconds, steps=100, seed=value.seed, language=value.language)
            or plan['direction'] != value.direction):
        raise Fault('RECOVERY_SPEC_MISMATCH', 409)
    record = runs.bindings.get(plan['binding']['id'])
    if record != plan['binding']:
        raise Fault('BINDING_CONFLICT', 409)
    with runs.store.transaction() as db:
        db.execute('CREATE TABLE IF NOT EXISTS run_successors(prior TEXT PRIMARY KEY, successor TEXT UNIQUE)')
        if db.execute('SELECT 1 FROM run_successors').fetchone():
            raise Fault('RECOVERY_ALREADY_ATTEMPTED', 409)
        if db.execute("SELECT 1 FROM local_runs WHERE status IN ('Starting','Running','Cancelling','Outcome unknown')").fetchone():
            raise Fault('RECOVERY_UNRESOLVED', 409)
    body = dict(command=identity(), request=plan['request'], revision=plan['revision'], binding=record['id'],
                binding_revision=record['revision'], operation=plan['operation'],
                options=dict(seconds=value.seconds, seed=value.seed, language=value.language))
    item = post(client, '/api/apps/plans', body)
    with runs.store.transaction() as db:
        current = db.execute('SELECT status,updated FROM local_runs WHERE id=?', (old['id'],)).fetchone()
        if current['status'] != old['status'] or current['updated'] != old['updated']:
            raise Fault('RECONCILIATION_STATE_CHANGED', 409)
        db.execute('INSERT INTO run_successors VALUES(?,?)', (old['id'], item['id']))
    return item, body, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation', type=Path, required=True)
    parser.add_argument('--state', type=Path, default=Path('var'))
    args = parser.parse_args()
    os.umask(0o077)
    from tools.qualify_local_sfx import evaluate
    try:
        evaluate(args.state, args.operation, _recovery=True)
    except BaseException as error:
        print(json.dumps(dict(status='no_further_effect', reason=error.code if isinstance(error, Fault) else type(error).__name__)), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
