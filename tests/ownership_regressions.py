"""Actual offline-child reproduction of lost ownership BEFORE persist(pin)."""
import json
import os
import subprocess
import time
from unittest.mock import patch
from studio.domain import Fault
from studio.runs.owned_process import incarnation


def initial_ownership_loss(case, failure):
    (case.location.parent / 'mode').write_text('sleep')
    item, model = case.prepare()
    original = case.runs.records.get(item['id'])
    children = []
    real_popen = subprocess.Popen

    def spawn(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        deadline = time.monotonic() + 1
        while not case.effects() and time.monotonic() < deadline:
            time.sleep(0.005)
        # Only let Popen return to the app after the actual fake child has effected.
        case.assertEqual(len(case.effects()), 1)
        if failure == 'popen-fault':
            raise Fault('PROCESS_OWNERSHIP_UNKNOWN', 409)
        return child

    def inspect(pid):
        return incarnation(pid) if pid == os.getpid() or failure != 'no-incarnation' else None

    def owned(*_):
        if failure == 'ownership-fault':
            raise Fault('PROCESS_OWNERSHIP_UNKNOWN', 409)
        return False

    try:
        with patch('studio.runs.owned_process.subprocess.Popen', side_effect=spawn), \
             patch('studio.runs.owned_process.incarnation', side_effect=inspect), \
             patch('studio.runs.owned_process.is_owned', side_effect=owned), \
             patch('studio.runs.owned_process.os.killpg') as signals:
            row = case.start(item)
            case.runs.threads[item['id']].join(3)
            case.assertEqual(len(children), 1)
            case.assertEqual(len(case.effects()), 1)
            signals.assert_not_called()
            case.assertIsNone(case.runs.records.get(item['id'])['process'].get('incarnation'))
            print(json.dumps(dict(adapter=case.adapter.id, failure=failure, status=row['status'],
                                  certainty=row['certainty'], fake_child_effects=1, signals=signals.call_count)))
            case.assertEqual(row['status'], 'Outcome unknown')
            case.assertEqual(row['certainty'], 'possibly started')
            case.assertEqual(row['error'], 'PROCESS_OWNERSHIP_UNKNOWN')
            case.assertIsNone(children[0].poll())
            case.assertEqual(case.start(item)['status'], 'Outcome unknown')
            case.reopen()
            case.assertEqual(case.runs.prepare_app(model), item)
            case.assertEqual(case.start(item)['status'], 'Outcome unknown')
            reopened = case.runs.records.get(item['id'])
            for field in ('id', 'candidate', 'plan', 'plan_digest', 'generation'):
                case.assertEqual(reopened[field], original[field])
            other, _ = case.prepare()
            with case.assertRaises(Fault) as blocked:
                case.runs.start(other['id'], lambda: True)
            case.assertEqual(blocked.exception.code, 'RESOURCE_BUSY')
            case.assertEqual(len(case.effects()), 1)
            case.assertEqual(len(children), 1)
            signals.assert_not_called()
        # Even proven eventual child exit / absent output must not clear uncertainty.
        children[0].wait(timeout=4)
        case.reopen()
        case.assertEqual(case.start(item)['status'], 'Outcome unknown')
        with case.assertRaises(Fault):
            case.runs.start(other['id'], lambda: True)
        case.assertEqual(len(case.effects()), 1)
    finally:
        # The fixed test bootstrap's own kernel deadline ends the synthetic sleeper.
        # No signal is sent using an unverified PID, including in test cleanup.
        for child in children:
            child.wait(timeout=4)
            child.stdout.close()
            child.stderr.close()
