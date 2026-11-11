"""Closed tool-supplied evidence and generated candidate data; never executable code."""
from typing import Literal
from pydantic import Field, model_validator
from ..domain import Strict


class Argument(Strict):
    flag: str = Field(pattern=r'^--[a-z][a-z0-9-]{0,30}$')
    value: Literal['direction','seconds','seed','output','receipt']


class Receipt(Strict):
    output: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')
    direction: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')
    seconds: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')
    seed: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')
    version: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,31}$')


class Effects(Strict):
    destination: Literal['local-workspace']
    network: Literal['none']
    cost: Literal['zero']
    model: Literal['none']
    credentials: Literal['none']
    use: Literal['noncommercial_local_technical_evaluation']


class Process(Strict):
    execution: Literal['synchronous-no-detach']
    exit: Literal['zero-success-nonzero-failure']
    stop: Literal['process-group-term-kill']
    idempotency: Literal['no-replay']
    timeout_seconds: int = Field(ge=1, le=60)


class Evidence(Strict):
    schema_version: Literal['motion-cli-evidence-v1']
    tool_version: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')
    operation: Literal['sfx']
    format: Literal['stereo-44100-pcm16']
    arguments: list[Argument] = Field(min_length=5, max_length=5)
    receipt: Receipt
    effects: Effects
    process: Process
    seconds_min: float = Field(ge=0.1, le=10, allow_inf_nan=False)
    seconds_max: float = Field(ge=0.1, le=10, allow_inf_nan=False)
    seconds_default: float = Field(ge=0.1, le=10, allow_inf_nan=False)
    seed_default: int = Field(ge=0, le=4294967295)

    @model_validator(mode='after')
    def finite_mapping(self):
        if {a.value for a in self.arguments} != {'direction','seconds','seed','output','receipt'}:
            raise ValueError('Required value mapping incomplete')
        if len({a.flag for a in self.arguments}) != 5 or len(set(self.receipt.model_dump().values())) != 5:
            raise ValueError('Mappings must be distinct')
        if not self.seconds_min <= self.seconds_default <= self.seconds_max:
            raise ValueError('Documented default outside bounds')
        return self


class Candidate(Strict):
    schema_version: Literal[1]
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)
    name: str = Field(min_length=1,max_length=120)
    template: Literal['documented-cli-wav']
    template_version: Literal[1]
    template_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    synthesizer: Literal['deterministic-schema-v1']
    evidence_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    evidence_source: Literal['tool-supplied-schema','selected-documentation']
    target: str = Field(min_length=1,max_length=4096)
    target_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    dependencies: dict[str,str] = Field(max_length=4)
    documented: Evidence


class Intake(Strict):
    name: str = Field(min_length=1,max_length=120)
    target: str = Field(max_length=4096)
    source: Literal['tool-supplied-schema','selected-documentation']
    evidence: str = Field(max_length=12000)
    id: str | None = None
    expected: int = Field(default=0,ge=0)


class RevisionAction(Strict):
    id: str
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class Activate(RevisionAction):
    binding_revision: int = Field(ge=1)
    scope: Literal['noncommercial_local_technical_evaluation']
