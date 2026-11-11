"""Versioned finite adapter envelopes; no user code, callbacks or transport plugins."""
from dataclasses import dataclass
from typing import Literal
from pydantic import Field
from ..domain import Strict, Fault


class PrepareApp(Strict):
    schema_version: Literal[2] = 2
    command: str
    request: str
    revision: int = Field(ge=1)
    binding: str
    binding_revision: int = Field(ge=1)
    operation: str = Field(max_length=64)
    options: dict = Field(max_length=8)


class SetupCLI(Strict):
    schema_version: Literal[1] = 1
    adapter: str = Field(max_length=64)
    adapter_version: Literal[1] = 1
    interface_version: str = Field(max_length=64)
    executable: str = Field(max_length=4096)


@dataclass(frozen=True)
class DispatchSpec:
    argv: tuple[str, ...]
    environment: dict
    artifact: str = 'candidate.wav'
    receipt: str = 'candidate.wav.json'
    validation_profile: str = 'stereo-44100-pcm16'
    transport: str = 'owned_local_argv'
    deadline_seconds: int = 600

    def validate(self):
        if type(self.deadline_seconds) is not int or not 1 <= self.deadline_seconds <= 600:
            raise Fault('ARGUMENT_INVALID',409)
        if (self.transport != 'owned_local_argv' or self.artifact != 'candidate.wav' or
                self.receipt != 'candidate.wav.json' or self.validation_profile not in
                ('stereo-44100-pcm16', 'stereo-48000-pcm16')):
            raise Fault('UNSUPPORTED_INTERFACE', 409)
        return self


def normalize_exit(result):
    """Owned CLI observations only; a stop request does not fabricate stopped output."""
    if result['code'] == 0 and not result['reason']:
        return 'Collecting', None
    reason = result['reason'] or 'CHILD_FAILED'
    return ('Cancelled' if reason in ('STOP_REQUESTED', 'AUTH_REVOKED') else 'Failed'), reason
