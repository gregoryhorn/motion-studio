"""Tiny closed technical namespace. Claims are advisory, never executable authority."""
from datetime import date
import json
from typing import Literal
from pydantic import ValidationError
from ..domain import Strict, Fault
from ..persistence.store import canonical, identity


class TechnicalClaim(Strict):
    namespace: Literal['quick-create-technical-v1'] = 'quick-create-technical-v1'
    recipe: Literal['isolated-layout', 'original-collection']
    recipe_version: Literal[1] = 1
    interface: Literal['stable-audio-cli-v1'] = 'stable-audio-cli-v1'
    interface_version: Literal[1] = 1
    layout: Literal[2] = 2
    error_class: Literal['OUTPUT_UNSAFE', 'COLLECTION_INTERRUPTED']
    condition: Literal['shared-runtime-outputs', 'verified-original-pair']
    result: Literal['verified', 'contradicted']
    confidence: Literal['fixture-tested', 'evidence-supported', 'hypothesis']
    verified_on: date
    summary: Literal['isolated-runtime-strict-outputs', 'same-original-bytes-retained']
    revalidate_on: Literal['recipe-interface-layout-change'] = 'recipe-interface-layout-change'


class TechnicalKnowledge:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS technical_claims(id TEXT PRIMARY KEY, body TEXT)')

    def remember(self, value):
        # Reject extra/free-form fields, future versions and untyped identifiers before storage.
        claim = TechnicalClaim.model_validate_json(canonical(value))
        if claim.verified_on > date.today():
            raise Fault('INVALID_TECHNICAL_CLAIM')
        with self.store.transaction() as db:
            if db.execute('SELECT count(*) FROM technical_claims').fetchone()[0] >= 256:
                return  # Bounded advisory store; never make generation depend on learning.
            encoded = canonical(claim.model_dump(mode='json'))
            if not db.execute('SELECT 1 FROM technical_claims WHERE body=?', (encoded,)).fetchone():
                db.execute('INSERT INTO technical_claims VALUES(?,?)', (identity(),encoded))

    def applicable(self):
        with self.store.transaction() as db:
            rows = db.execute('SELECT body FROM technical_claims ORDER BY rowid LIMIT 256').fetchall()
        claims, stale = [], 0
        for row in rows:
            try:
                claim = TechnicalClaim.model_validate_json(row[0])
                paired = (claim.recipe == 'isolated-layout' and claim.error_class == 'OUTPUT_UNSAFE'
                          and claim.condition == 'shared-runtime-outputs' and claim.summary == 'isolated-runtime-strict-outputs')
                collected = (claim.recipe == 'original-collection' and claim.error_class == 'COLLECTION_INTERRUPTED'
                             and claim.condition == 'verified-original-pair' and claim.summary == 'same-original-bytes-retained')
                if not (paired or collected) or claim.verified_on > date.today():
                    stale += 1
                    continue
                claims.append(claim.model_dump(mode='json'))
            except (ValueError, TypeError, ValidationError):
                stale += 1
        for claim in claims:
            disputed = any(other['recipe'] == claim['recipe'] and other['result'] != claim['result'] for other in claims)
            claim['applicability'] = 'disputed' if disputed else 'matching-version-advisory-only'
        # Invalid stored text is never reflected into UI/logs/export.
        return dict(claims=claims, stale_or_invalid=stale, authority='none')
