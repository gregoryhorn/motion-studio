"""Server-only association, never populated from tool/model/renderer arguments."""
from dataclasses import dataclass, field
import hashlib
from ...domain import Fault
from ...persistence.primitives import canonical

AUDIENCE = 'Gateway-authorized session controllers/operators, including multiple clients'


@dataclass(frozen=True)
class MusicAssociation:
    revision: str = ''
    prepare: bool = False
    effects: bool = False
    binding: str = ''
    binding_revision: int = 0

    def access(self):
        if not self.prepare or not self.revision:
            raise Fault('MUSIC_SCOPE_REVIEW_REQUIRED', 403)


@dataclass(frozen=True)
class Association:
    profile: str = ''
    revision: str = ''
    audience: str = ''
    direction_audio: bool = False
    canonical_roots: bool = False
    agent_starts: bool = False
    delegated_starts: bool = False
    local_generator: bool = False
    create_store: bool = False
    instance: str = ''
    binding: str = ''
    binding_revision: int = 0
    music: MusicAssociation = field(default_factory=MusicAssociation)

    def access(self, profile):
        if (not self.profile or self.profile != profile or not self.revision or
                self.audience != AUDIENCE or not self.direction_audio or not self.canonical_roots):
            raise Fault('CREATION_ACCESS_UNAVAILABLE', 403)


@dataclass(frozen=True)
class Scope:
    instance: str
    root: str
    revision: str

    def key(self):
        # Private authority fingerprint, not a bearer token or logged identifier.
        return hashlib.sha256(canonical([self.instance, self.root, self.revision]).encode()).hexdigest()


def context_id(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise Fault('CREATION_CONTEXT_REQUIRED', 403)
    return value
