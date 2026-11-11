"""Real passive admission for the one authorized, plan-scoped local SFX evaluation."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any
import shutil
import stat
import subprocess
import time
from ..domain import Fault
from ..producer import local_sfx as sfx, local_gpu
from ..producer.stable_adapter import RevisionRuntime

USE = 'noncommercial_local_technical_evaluation'


def resources():
    """Keep the existing tuple interface; busy observations carry safe details."""
    observation = local_gpu.require_available(8192, conflict_root=sfx.ROOT)
    return observation['free_mib'], False


@dataclass(frozen=True)
class ScopedRuntime(RevisionRuntime):
    scope: Any = field(default=None)

    def final(self, plan, output, argv):
        # Preserve the immutable v2 envelope for scope admission. The legacy view is
        # only for the concrete parameter/vector decoder, never the authorization key.
        self.scope.check_plan(plan)
        sfx.validate_plan(sfx.legacy_view(plan))
        if plan['binding'] != self.record or argv != sfx.vector(self.executable(), plan, output):
            raise Fault('ARGUMENT_INVALID', 409)
        self.admit(plan, output)

    def admit(self, plan, output):
        self.scope.check_plan(plan)
        view = sfx.legacy_view(plan)
        if self.scope.use != USE:
            raise Fault('USE_RESTRICTED', 409)
        if (self.fixture_only or self.record['fixture_only'] or plan['adapter'] != 'stable-audio-local'
                or plan['operation'] != 'sfx' or self.executable() != sfx.WRAPPER):
            raise Fault('SCOPE_CONFLICT', 409)
        if (view['seconds'], view['steps'], view['seed'], view['language'], view['model_revision']) != (
                3.0, 100, 42, 'en', sfx.REVISION):
            raise Fault('SCOPE_CONFLICT', 409)
        self.admit_installed(output)

    def admit_installed(self, output):
        expected = {**sfx.FILE_PINS, **sfx.model_pins()}
        if self.record['pins']['files'] != expected:
            raise Fault('RUNTIME_DRIFT', 409)
        sfx.check_pins(expected)
        info = output.parent.stat()
        if (output.name != 'candidate.wav' or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o077
                or not os.access(output.parent, os.W_OK)):
            raise Fault('ALLOCATION_CONFLICT', 409)
        if os.path.lexists(output) or os.path.lexists(output.with_suffix('.wav.json')):
            raise Fault('OUTPUT_EXISTS', 409)
        disk = shutil.disk_usage(output.parent).free
        free, conflict = resources()  # Last mutable check, repeated at final argv boundary.
        sfx.eligible_resources(free, self.scope.use == USE, disk, conflict)
        self.scope.observation = dict(observed_at=time.time(), free_mib=free, conflict=conflict, free_disk_bytes=disk,
                                      model_files_checked=len(sfx.model_pins()), use=USE)


@dataclass(frozen=True)
class OrdinaryRuntime(ScopedRuntime):
    """Same pinned adapter/use/resources; normal immutable parameter bounds, no test grant."""
    def admit(self, plan, output):
        self.scope.check_plan(plan)
        sfx.validate_plan(sfx.legacy_view(plan))
        if self.scope.use != USE:
            raise Fault('USE_RESTRICTED', 409)
        if plan['adapter'] != 'stable-audio-local' or plan['operation'] != 'sfx':
            raise Fault('UNSUPPORTED_OPERATION', 409)
        if self.fixture_only:
            # Only a server-injected, explicitly labelled synthetic binding can reach this.
            sfx.check_pins({str(self.executable()): self.record['file_digest']})
            return
        if self.executable() != sfx.WRAPPER:
            raise Fault('RUNTIME_DRIFT', 409)
        self.admit_installed(output)
