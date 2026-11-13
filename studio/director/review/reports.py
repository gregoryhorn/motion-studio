"""Exact-byte report associations and retained report assets in Studio's SQLite store."""
import base64
import hashlib
import json
import time
from ...domain import Fault, opaque
from ...persistence.primitives import canonical, identity
from . import crystal_ball
from . import applicability

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS director_reports(id TEXT PRIMARY KEY, take TEXT,
       digest TEXT, revision INTEGER, options TEXT, summary TEXT, created REAL)''',
    '''CREATE TABLE IF NOT EXISTS director_report_assets(report TEXT, name TEXT,
       body BLOB, PRIMARY KEY(report,name))''',
    '''CREATE TABLE IF NOT EXISTS director_check_context(take TEXT PRIMARY KEY,
       digest TEXT, revision INTEGER, media_kind TEXT, settings TEXT)''',
)


def initialize(db):
    for statement in SCHEMA:
        db.execute(statement)


def context(db, row):
    found = db.execute('SELECT * FROM director_check_context WHERE take=? AND digest=? AND revision=?',
        (row['id'], row['digest'], row['revision'])).fetchone()
    return (found['media_kind'], json.loads(found['settings'])) if found else (None, applicability.settings())


def options_identity(db, row):
    kind, options = context(db, row)
    return applicability.identity(kind, options, crystal_ball.VERSION)


def status(db, row):
    found = db.execute('''SELECT summary FROM director_reports WHERE take=? AND digest=?
        AND revision=? AND options=? ORDER BY rowid DESC LIMIT 1''',
        (row['id'], row['digest'], row['revision'], options_identity(db, row))).fetchone()
    return json.loads(found[0]) if found else dict(status='Not checked', reason='No matching retained report')


def check(db, row, data, *, runner=None, retry=False, options=None):
    if hashlib.sha256(data).hexdigest() != row['digest'] or len(data) != row['size']:
        raise Fault('RETAINED_FILE_CORRUPT', 409)
    kind, previous = context(db, row)
    settings = applicability.settings(**(options if options is not None else previous))
    prior = status(db, row) if settings == previous else {}
    if prior.get('report') and (not retry or prior['status'] in ('PASS', 'WARN', 'FAIL')):
        return prior
    facts = row['facts'] if isinstance(row['facts'], dict) else json.loads(row['facts'])
    suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'video/mp4': '.mp4',
              'audio/wav': '.wav'}.get(facts.get('mime'), '.wav' if 'rate' in facts or 'sample_rate' in facts else '.bin')
    try:
        # Preserve the existing two-argument injected checker port for fixtures.
        result = runner(data, suffix) if runner else crystal_ball.run(data, suffix, **settings)
    except Exception:
        result = dict(reason='Checker could not complete')
    report = identity()
    kind = result.get('media_kind')
    options_key = applicability.identity(kind, settings, crystal_ball.VERSION)
    db.execute('INSERT OR REPLACE INTO director_check_context VALUES(?,?,?,?,?)',
        (row['id'], row['digest'], row['revision'], kind, canonical(settings)))
    summary = {key: result[key] for key in ('status', 'reason', 'counts', 'not_checked',
               'not_checked_details', 'not_checked_omitted_count', 'omitted_details', 'media_kind') if key in result}
    summary.setdefault('status', 'Not checked')
    summary.update(report=report, checker='Crystal Ball', version=crystal_ball.VERSION,
                   options=options_key, checked_at=time.time(), user_review='Not reviewed')
    db.execute('INSERT INTO director_reports VALUES(?,?,?,?,?,?,?)',
        (report, row['id'], row['digest'], row['revision'], options_key, canonical(summary), time.time()))
    for name, body in result.get('assets', {}).items():
        db.execute('INSERT INTO director_report_assets VALUES(?,?,?)', (report, name, body))
    return summary


def retained(store, db, take, data):
    """Finalize-time port: errors never turn a collected playable take into failure."""
    return check(db, store.take(db, take), data)


def report(db, row, identifier, asset=None, offset=0):
    found = db.execute('SELECT * FROM director_reports WHERE id=? AND take=?',
                       (opaque(identifier), row['id'])).fetchone()
    if not found:
        raise Fault('DIRECTOR_REPORT_SCOPE_DENIED', 403)
    # Historical reports remain accessible, but never acquire a current association.
    names = [r[0] for r in db.execute('SELECT name FROM director_report_assets WHERE report=? ORDER BY name', (identifier,))]
    result = dict(summary=json.loads(found['summary']), assets=names,
        current=found['digest'] == row['digest'] and found['revision'] == row['revision'] and found['options'] == options_identity(db, row))
    if asset is not None:
        body = db.execute('SELECT body FROM director_report_assets WHERE report=? AND name=?', (identifier, asset)).fetchone()
        if body is None or type(offset) is not int or not 0 <= offset < len(body[0]):
            raise Fault('DIRECTOR_REPORT_ASSET_INVALID', 422)
        result.update(bytes=base64.b64encode(body[0][offset:offset+49152]).decode(), total=len(body[0]), offset=offset)
    return result
