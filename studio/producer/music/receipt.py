"""Closed normalized Music receipt; requested seed is not effective-seed evidence."""
import hashlib
import json
import os
from typing import Literal
from pydantic import Field, ValidationError
from ...domain import Strict, Fault, MAX_BYTES
from ...persistence.primitives import canonical
from ...producer.local_sfx import unique_pairs


def digest(data): return hashlib.sha256(data).hexdigest()


class AudioIdentity(Strict):
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    bytes: int = Field(gt=0, le=MAX_BYTES)
    encoding: Literal['PCM', 'IEEE_FLOAT']
    bits: Literal[16, 24, 32, 64]
    channels: Literal[2]
    rate: Literal[48000]
    frames: int = Field(ge=480000, le=1440000)


class Receipt(Strict):
    schema_version: Literal[1]
    adapter: Literal['ace-step-local']
    operation: Literal['instrumental-cue-v1']
    plan: str = Field(pattern=r'^[a-f0-9]{64}$')
    request: str = Field(pattern=r'^[a-f0-9]{32}$')
    run: str = Field(pattern=r'^[a-f0-9]{32}$')
    allocation_dev: int = Field(ge=0)
    allocation_ino: int = Field(ge=1)
    binding: str = Field(pattern=r'^[a-f0-9]{64}$')
    seed_requested: int = Field(ge=0, le=4294967295)
    seed_effective: None
    seed_evidence: Literal['unverified-upstream-discarded']
    native: AudioIdentity
    derivative: AudioIdentity
    conversion: Literal['PCM16 encoding only; no resample/cut/stretch/normalization/fade']
    upstream: Literal['ACE inference peak normalization toward -1 dB; bridge adds none']


def identity(plan, output):
    directory = output.parent
    info = directory.stat(follow_symlinks=False)
    run = directory.parent.name.removeprefix('sfx-')
    return dict(plan=digest(canonical(plan).encode()), request=plan['request'], run=run,
        allocation_dev=info.st_dev, allocation_ino=info.st_ino, binding=plan['binding_digest'],
        seed_requested=plan['parameters']['seed'])


def make(plan, output, native, derivative, facts):
    return Receipt(schema_version=1, adapter='ace-step-local', operation='instrumental-cue-v1',
        **identity(plan, output), seed_effective=None, seed_evidence='unverified-upstream-discarded',
        native=AudioIdentity(sha256=digest(native), **facts),
        derivative=AudioIdentity(sha256=digest(derivative), bytes=len(derivative), encoding='PCM',
            bits=16, channels=2, rate=48000, frames=facts['frames']),
        conversion='PCM16 encoding only; no resample/cut/stretch/normalization/fade',
        upstream=plan['parameters']['upstream_processing']).model_dump()


def parse(raw, plan, output):
    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        receipt = Receipt.model_validate(value, strict=True)
        # Literal integers can otherwise accept bools/floats. Enforce canonical types recursively.
        normalized = receipt.model_dump()
        if canonical(normalized) != canonical(value): raise ValueError()
        for key, expected in identity(plan, output).items():
            if type(value[key]) is not type(expected) or value[key] != expected: raise ValueError()
        if receipt.native.frames != plan['parameters']['seconds'] * 48000: raise ValueError()
        return normalized
    except (ValueError, TypeError, KeyError, RecursionError, ValidationError):
        raise Fault('MUSIC_RECEIPT_INVALID') from None
