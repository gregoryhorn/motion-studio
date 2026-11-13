"""Revisioned card repository in the existing transactional authority."""
import json
from ...domain import Fault, opaque
from ...persistence.primitives import canonical


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS director_cards(id TEXT, revision INTEGER,
        scope TEXT, body TEXT, PRIMARY KEY(id,revision))''')
    db.execute('''CREATE TABLE IF NOT EXISTS director_tests(command TEXT PRIMARY KEY,
        scope TEXT, payload TEXT, card TEXT, revision INTEGER, request TEXT,
        take TEXT, artifact TEXT, state TEXT, result TEXT)''')


def get(db, scope, identifier, expected=None):
    row = db.execute('SELECT body FROM director_cards WHERE id=? AND scope=? ORDER BY revision DESC LIMIT 1',
                     (opaque(identifier), scope)).fetchone()
    if not row:
        raise Fault('DIRECTOR_CARD_SCOPE_DENIED', 403)
    card = json.loads(row[0])
    if expected is not None and card['revision'] != expected:
        raise Fault('DIRECTOR_STALE_REVISION', 409)
    return card


def save(db, scope, card):
    db.execute('INSERT OR REPLACE INTO director_cards VALUES(?,?,?,?)',
               (card['id'], card['revision'], scope, canonical(card)))


def listing(db, scope):
    rows = db.execute('''SELECT body FROM director_cards a WHERE scope=? AND revision=
        (SELECT max(revision) FROM director_cards b WHERE a.id=b.id AND a.scope=b.scope)
        ORDER BY rowid''', (scope,))
    return [json.loads(row[0]) for row in rows]


def public(card):
    # Invocation details, executable paths and intake documents are private.
    return {key: value for key, value in card.items() if key not in ('mapping', 'help', 'documentation', 'fingerprint')}
