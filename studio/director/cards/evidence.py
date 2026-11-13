"""Append operation-scoped retained check/user-verdict observations, never rules."""
from ...director.review import reports


def refresh(db, card):
    latest = {item['take']: item for item in card['evidence']}
    changed = False
    for take, previous in latest.items():
        row = db.execute('SELECT * FROM takes WHERE id=?', (take,)).fetchone()
        if row is None:
            continue
        coverage = reports.status(db, row)
        current = dict(previous, report=coverage.get('report'), check=coverage['status'],
            user_verdict=row['review'], not_checked=coverage.get('not_checked', []),
            counts=coverage.get('counts', {}))
        if any(current.get(key) != previous.get(key) for key in ('report', 'check', 'user_verdict')):
            card['evidence'].append(current)
            changed = True
    return changed
