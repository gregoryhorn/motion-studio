"""Finite application inputs and safe domain errors."""
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

KINDS = ("Sound effects", "Music", "Voice", "Image", "Video")
MAX_BYTES = 16 * 1024 * 1024

class Fault(Exception):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class SaveRequest(Strict):
    command: str
    id: str | None = None
    expected: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=8000)
    kind: str
    purpose: str = Field(default="", max_length=2000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Request must not be blank")
        return value

    @field_validator("kind")
    @classmethod
    def media_kind(cls, value):
        if value not in KINDS:
            raise ValueError("Unknown media type")
        return value

class ImportIntent(Strict):
    command: str
    request: str
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(gt=0, le=MAX_BYTES)
    name: str = Field(min_length=1, max_length=240)

class TakeAction(Strict):
    command: str
    request: str
    expected: int = Field(ge=1)
    take: str

class ReviewAction(Strict):
    command: str
    take: str
    outcome: str

    @field_validator("outcome")
    @classmethod
    def review(cls, value):
        if value not in ("Matches request", "Needs work", "Not reviewed"):
            raise ValueError("Unknown listening outcome")
        return value

class Login(Strict):
    secret: str = Field(min_length=1, max_length=256)

def opaque(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise Fault("INVALID_ID")
    return value
