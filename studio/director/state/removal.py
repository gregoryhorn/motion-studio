"""Persistent reversible list tombstones; originals/history are never deleted."""
import time
from ...domain import Fault


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS director_removed(take TEXT PRIMARY KEY,
        removed INTEGER, revision INTEGER, changed REAL)''')


def visible(db, take):
    row = db.execute('SELECT removed FROM director_removed WHERE take=?', (take,)).fetchone()
    return not row or not row[0]


def revision(db, take):
    row = db.execute('SELECT revision FROM director_removed WHERE take=?', (take,)).fetchone()
    return row[0] if row else 0


def in_use(db, row):
    if db.execute('SELECT 1 FROM requests WHERE selected=?', (row['id'],)).fetchone():
        raise Fault('DIRECTOR_TAKE_IN_USE', 409)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, field in (('production_asset_takes', 'take'), ('production_references', 'take'),
                         ('production_assets', 'selected_take')):
        if table in tables and db.execute(f'SELECT 1 FROM {table} WHERE {field}=?', (row['id'],)).fetchone():
            raise Fault('DIRECTOR_TAKE_IN_USE', 409)
    if 'creation_commands' in tables:
        for command in db.execute('SELECT * FROM creation_commands WHERE request=?', (row['request'],)):
            if command['run']:
                run = db.execute('SELECT status FROM local_runs WHERE id=?', (command['run'],)).fetchone()
                if not run or run[0] not in ('Ready for review', 'Failed', 'Cancelled'):
                    raise Fault('DIRECTOR_RUN_UNRESOLVED', 409)
            elif command['phase'] in ('Preparing', 'Started', 'Prepared'):
                raise Fault('DIRECTOR_RUN_UNRESOLVED', 409)
    if 'external_submissions' in tables:
        if db.execute("SELECT 1 FROM external_submissions WHERE request=? AND state NOT IN ('collected','abandoned')", (row['request'],)).fetchone():
            raise Fault('DIRECTOR_RUN_UNRESOLVED', 409)
        # Abandoning is not evidence that an external effect stopped.
        if db.execute("SELECT 1 FROM external_submissions WHERE request=? AND state='abandoned'", (row['request'],)).fetchone():
            raise Fault('DIRECTOR_RUN_UNRESOLVED', 409)
    if 'local_runs' in tables:
        if db.execute('''SELECT 1 FROM local_runs WHERE json_extract(plan,'$.request')=?
                AND status NOT IN ('Ready for review','Failed','Cancelled')''', (row['request'],)).fetchone():
            raise Fault('DIRECTOR_RUN_UNRESOLVED', 409)


def change(store, db, row, *, command, expected, restore=False, scope):
    payload = dict(operation='director.restore' if restore else 'director.remove',
                   scope=scope, take=row['id'], expected=expected)
    def apply():
        if revision(db, row['id']) != expected:
            raise Fault('DIRECTOR_STALE_REVISION', 409)
        if not restore:
            in_use(db, row)
        next_revision = expected + 1
        db.execute('INSERT OR REPLACE INTO director_removed VALUES(?,?,?,?)',
                   (row['id'], int(not restore), next_revision, time.time()))
        return dict(take=row['id'], removed=not restore, revision=next_revision)
    return store.command(db, command, payload, apply)
