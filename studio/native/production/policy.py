"""Separate default-denied Production association; no generation authority."""
from dataclasses import dataclass
from ...domain import Fault


@dataclass(frozen=True)
class ProductionAssociation:
    profile: str = ''
    revision: str = ''
    production_management: bool = False
    direction_audio: bool = False
    canonical_roots: bool = False

    def access(self, profile):
        if not self.profile or self.profile != profile:
            raise Fault('PRODUCTION_ACCESS_UNAVAILABLE', 403)
        if not self.revision or not self.production_management:
            raise Fault('PRODUCTION_ACCESS_UNAVAILABLE', 403)
        if not self.direction_audio or not self.canonical_roots:
            raise Fault('PRODUCTION_WORKFLOW_REVIEW_REQUIRED', 403)
