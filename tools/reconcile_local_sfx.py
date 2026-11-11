"""Read-only bounded reconciliation of the existing CF-LQ1 intent; no launch path."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
from studio.domain import Fault
from studio.runs.admission import plan_key
from studio.runs.owned_process import incarnation


def inspect_original(home):
    home = home.absolute()
    ledger = json.loads((home / 'state/lq1-intent.json').read_text())
    with sqlite3.connect((home / 'state/studio.db').as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        raw = db.execute('SELECT * FROM local_runs WHERE id=?', (ledger['run'],)).fetchone()
        if raw is None:
            raise Fault('RUN_NOT_FOUND', 404)
        row = dict(raw)
        for field in ('plan', 'process', 'collection'):
            row[field] = json.loads(row[field]) if row[field] else None
        scope = dict(db.execute('SELECT * FROM bounded_admission WHERE run=?', (row['id'],)).fetchone())
        real_runs = db.execute('SELECT count(*) FROM local_runs WHERE fixture=0').fetchone()[0]
        takes = db.execute('SELECT count(*) FROM takes WHERE id=? OR artifact=?', (row['candidate'], row['candidate'])).fetchone()[0]
        binding = json.loads(db.execute('SELECT body FROM app_bindings WHERE id=? ORDER BY revision DESC LIMIT 1',
                                       (ledger['binding'],)).fetchone()[0])
    directory = home / 'staging' / ('sfx-' + row['id'])
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        process = row['process'] or {}
        entries = [os.stat(name, dir_fd=fd, follow_symlinks=False) for name in os.listdir(fd)]
        recorded = process.get('incarnation') or {}
        current = incarnation(recorded['pid']) if isinstance(recorded.get('pid'), int) else None
        facts = dict(status=row['status'], certainty=row['certainty'], error=row['error'],
            original_candidate_matches=row['candidate'] == ledger['candidate'], generation=row['generation'],
            real_runs=real_runs, fixture=bool(row['fixture']), stop=bool(row['stop']),
            process_allocation_only=set(process) == {'allocation'},
            allocation_matches=process.get('allocation') == dict(dev=info.st_dev, ino=info.st_ino),
            private_allocation=stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077,
            staging_empty=not os.listdir(fd), scope_state=scope['state'],
            scope_plan_matches=scope['plan'] == row['plan_digest'] == plan_key(row['plan']),
            collection_absent=row['collection'] is None, takes_absent=takes == 0,
            media_absent=not os.path.lexists(home / 'media' / (row['candidate'] + '.wav')),
            intent_status=ledger.get('status'), intent_error=ledger.get('error'),
            intent_app_status=ledger.get('app_status'))
        facts.update(process_incarnation_recorded=bool(recorded), exit_recorded=bool(process.get('exited')),
            recorded_incarnation_still_present=current is not None and current == recorded,
            staging_directories=sum(stat.S_ISDIR(item.st_mode) for item in entries),
            staging_regular_files=sum(stat.S_ISREG(item.st_mode) for item in entries),
            wav_present=os.path.lexists(directory / 'candidate.wav'),
            receipt_present=os.path.lexists(directory / 'candidate.wav.json'),
            normal_binding_disabled=not binding['enabled'])
        resume = home / 'state/lq1-resume-intent.json'
        if resume.exists():
            resumed = json.loads(resume.read_text())
            facts.update(resume_status=resumed.get('status'), resume_error=resumed.get('error'),
                         original_intent_preserved=resumed.get('previous_attempt') == ledger)
    finally:
        os.close(fd)
    # Closed legacy scope alone is NOT evidence of non-consumption. The committed
    # Blocked/not-attempted/SCOPE_CONFLICT branch is only before launching()/Popen;
    # any possible launch records unknown/started instead. Require the entire proof.
    facts['proven_prelaunch_refusal'] = (
        facts['status'] == 'Blocked' and facts['certainty'] == 'not attempted'
        and facts['error'] == 'SCOPE_CONFLICT' and facts['generation'] == 1
        and facts['real_runs'] == 1 and not facts['fixture'] and not facts['stop']
        and all(facts[key] for key in ('original_candidate_matches', 'process_allocation_only',
            'allocation_matches', 'private_allocation', 'staging_empty', 'scope_plan_matches',
            'collection_absent', 'takes_absent', 'media_absent'))
        and facts['scope_state'] == 'closed' and facts['intent_status'] == 'stopped_no_retry'
        and facts['intent_error'] == 'SCOPE_CONFLICT' and facts['intent_app_status'] == 'Blocked')
    return facts, ledger, row, scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('var'))
    args = parser.parse_args()
    facts, _, _, _ = inspect_original(args.state)
    print(json.dumps(facts, indent=2))
    return 0 if facts['proven_prelaunch_refusal'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
