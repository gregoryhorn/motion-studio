"""Music-specific server scope; SFX/Production flags cannot grant this operation."""
from dataclasses import dataclass
from ...domain import Fault
from ...native.creation.policy import Scope, MusicAssociation
from ...producer.music.contract import SOURCE_PINS, OPERATION


@dataclass(frozen=True)
class MusicScope(Scope):
    music_revision: str = ''

    def key(self):
        from ...producer.bindings import digest
        return digest([self.instance, self.root, self.revision, self.music_revision, 'Music'])


def disabled_binding(runs):
    """Passive descriptive metadata; unknown runtime/model pins remain unknown."""
    from ...producer.bindings import digest
    from ...producer.music.adapter import AceStep
    adapter = AceStep()
    value = dict(adapter=adapter.id, adapter_version=1, interface_version=adapter.interface,
        executable='', file_digest='', pins=dict(source_evidence=SOURCE_PINS,
            runtime_qualification='unverified', checkpoint_identity=None,
            initialization_suppression='unverified', resource_envelope=None),
        fixture_only=False, enabled=False, qualification='Not checked', availability='Unavailable',
        reason='MUSIC_LIVE_UNQUALIFIED', action='Complete separately approved Music live qualification',
        capabilities=adapter.describe(), checked_at=None, evidence_scope='CF-MU1 source preflight only')
    key = digest(value)[:32]
    try: return runs.bindings.get(key)
    except Fault as error:
        if error.code != 'BINDING_NOT_FOUND': raise
        return runs.bindings.put(value, key)


def unsupported(model):
    if model.reference_requested: return 'MUSIC_REFERENCE_ROUTE_UNQUALIFIED'
    if not model.instrumental: return 'MUSIC_VOCAL_ROUTE_UNQUALIFIED'
    if not 10 <= model.seconds <= 30: return 'MUSIC_DURATION_ROUTE_UNQUALIFIED'
    return None


def scope(service, root, effect=False):
    base = service.runtime.access(root)
    policy = service.runtime.policy.music
    policy.access()
    with service.store.transaction() as db:
        row = db.execute('SELECT policy FROM music_roots WHERE root=?', (root,)).fetchone()
    if not row or row[0] != policy.revision:
        raise Fault('MUSIC_WORKFLOW_REVIEW_REQUIRED', 403)
    if effect and not policy.effects: raise Fault('MUSIC_EFFECT_REVIEW_REQUIRED', 403)
    return MusicScope(base.instance, base.root, base.revision, policy.revision)
