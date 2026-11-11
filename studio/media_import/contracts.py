"""Canonical media descriptor v1 and finite import payloads.

``describe_take(row, kind=..., production=None, asset=None)`` returns JSON:
{identity: {production: str|null, asset: str|null, request: str,
 requestRevision: int, take: str, artifact: str}, kind: one of the five
 application kinds, format: png|jpeg|wav|mp4, mime: str, byteLength: int,
 sha256: str, width: int|null, height: int|null, duration: float|null,
 reviewStatus: str, qualityRole: str}.
Production/asset identities are supplied ONLY after the host authorizes their
association; null means an unattached Creation take. Request revision is the
immutable source revision, not the current request revision. Measurements come
from validated retained facts; absent dimensions/duration are null. No filename,
path, prompt or authority token is included. Existing pre-import takes are WAV.
Review/export consumers must authorize associations and original-byte reads;
a descriptor alone grants no access or approval. This v1 shape is stable.

invoke(service, trusted_scope, operation, payload) accepts only the models below.
begin -> {id,take}; chunk -> {id,received,status}; status ->
{id,take,status,error,received}; commit/cancel -> {id,take,status,error};
describe -> the descriptor above; read_chunk ->
{take,offset,total,bytes,sha256,chunk_sha256,mime}, with base64 bytes in chunks
of READ_CHUNK_BYTES. retrieve is an internal (bytes,take_row) return value.
Trusted scope is never part of a client payload.
"""
import json
from typing import Literal
from pydantic import Field, field_validator
from ..domain import Strict, MAX_BYTES, Fault, opaque

CHUNK_BYTES = 192 * 1024
READ_CHUNK_BYTES = 49152
FORMATS = ('png', 'jpeg', 'wav', 'mp4')
MIME = {'png': 'image/png', 'jpeg': 'image/jpeg', 'wav': 'audio/wav', 'mp4': 'video/mp4'}


class MediaIdentity(Strict):
    production: str | None = None
    asset: str | None = None
    request: str
    requestRevision: int = Field(ge=1)
    take: str
    artifact: str

    @field_validator('production', 'asset', 'request', 'take', 'artifact')
    @classmethod
    def identifier(cls, value):
        return opaque(value) if value is not None else None


class QualityStatus(Strict):
    technical: Literal['Validated retained format'] = 'Validated retained format'
    perceptual: Literal['Not reviewed', 'Matches request', 'Needs work']
    useEligibility: Literal['Not assessed'] = 'Not assessed'
    userApproval: Literal['Not recorded'] = 'Not recorded'
    outstanding: list[str]


class MediaDescriptor(Strict):
    identity: MediaIdentity
    kind: Literal['Sound effects', 'Music', 'Voice', 'Image', 'Video']
    format: Literal['png', 'jpeg', 'wav', 'mp4']
    mime: str
    byteLength: int = Field(gt=0, le=MAX_BYTES)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    width: int | None = Field(default=None, gt=0, le=4096)
    height: int | None = Field(default=None, gt=0, le=4096)
    duration: float | None = Field(default=None, gt=0, le=47, allow_inf_nan=False)
    reviewStatus: Literal['Not reviewed', 'Matches request', 'Needs work']
    qa: QualityStatus
    qualityRole: str = Field(default='Not recorded', min_length=1, max_length=80)


def describe_take(row, *, kind, production=None, asset=None, quality_role='Not recorded'):
    """Project an already authorized retained take, including legacy WAV rows."""
    row = dict(row)
    facts = row['facts'] if isinstance(row['facts'], dict) else json.loads(row['facts'])
    format = facts.get('format', 'wav')
    expected = {'png': ('Image',), 'jpeg': ('Image',), 'mp4': ('Video',),
                'wav': ('Sound effects', 'Music', 'Voice')}
    if format not in MIME or kind not in expected[format] or facts.get('mime', MIME[format]) != MIME[format]:
        raise Fault('MEDIA_KIND_MISMATCH', 409)
    if facts.get('lineage') or facts.get('voice_lineage'):
        quality_role = 'Retained derivative; source retained'
    revision = row.get('source_request_revision', row.get('revision', row.get('request_revision')))
    return MediaDescriptor(identity=MediaIdentity(production=production, asset=asset,
        request=row['request'], requestRevision=revision, take=row['id'], artifact=row['artifact']),
        kind=kind, format=format, mime=MIME[format], byteLength=row['size'], sha256=row['digest'],
        width=facts.get('width'), height=facts.get('height'), duration=facts.get('duration'),
        reviewStatus=row['review'], qualityRole=quality_role,
        qa=QualityStatus(perceptual=row['review'], outstanding=
            ([] if row['review'] == 'Matches request' else ['Perceptual review against request']) +
            ['Intended-use eligibility and rights', 'Explicit user approval'])).model_dump()


class BeginImport(Strict):
    command: str
    request: str
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    size: int = Field(gt=0, le=MAX_BYTES)
    name: str = Field(min_length=1, max_length=240)
    format: Literal['png', 'jpeg', 'wav', 'mp4']

    @field_validator('command', 'request')
    @classmethod
    def identifier(cls, value):
        return opaque(value)


class ImportID(Strict):
    id: str

    @field_validator('id')
    @classmethod
    def identifier(cls, value):
        return opaque(value)


class ImportChunk(ImportID):
    offset: int = Field(ge=0, le=MAX_BYTES)
    data: str = Field(min_length=4, max_length=4 * ((CHUNK_BYTES + 2) // 3))


class RetrieveTake(Strict):
    take: str

    @field_validator('take')
    @classmethod
    def identifier(cls, value):
        return opaque(value)


class ReadChunk(RetrieveTake):
    offset: int = Field(ge=0, lt=MAX_BYTES)
