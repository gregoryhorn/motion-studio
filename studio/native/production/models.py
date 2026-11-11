"""Finite Production management inputs. IDs stay opaque to the visual user."""
from typing import Annotated, Literal
from pydantic import Field
from ...domain import KINDS, Strict


ID = r'^[a-f0-9]{32}$'
MediaKind = Literal['Sound effects', 'Music', 'Voice', 'Image', 'Video']
Opaque = Annotated[str, Field(pattern=ID)]


class Brief(Strict):
    text: str = Field(default='', max_length=8000)
    purpose: str = Field(default='', max_length=2000)
    audience: str = Field(default='', max_length=1000)
    usage: str = Field(default='', max_length=2000)


class Create(Strict):
    command: str = Field(pattern=ID)
    title: str = Field(default='', max_length=200)
    brief: Brief = Brief()
    kinds: list[MediaKind] = Field(default_factory=list, max_length=64)


class Open(Strict):
    production: str | None = Field(default=None, pattern=ID)


class Revision(Strict):
    command: str = Field(pattern=ID)
    production: str = Field(pattern=ID)
    expected: int = Field(ge=1)


class UpdateBrief(Revision):
    title: str = Field(default='', max_length=200)
    brief: Brief


class AddAsset(Revision):
    kind: MediaKind
    intent: str = Field(default='', max_length=2000)
    position: int | None = Field(default=None, ge=0, le=63)
    depends_on: list[Opaque] = Field(default_factory=list, max_length=16)
    references: list[Opaque] = Field(default_factory=list, max_length=16)


class UpdateAsset(AddAsset):
    asset: str = Field(pattern=ID)


class AddReference(Revision):
    request: str = Field(pattern=ID)
    take: str = Field(pattern=ID)
    label: str = Field(default='', max_length=200)


class UpdateReference(AddReference):
    reference: str = Field(pattern=ID)


class LinkTake(Revision):
    asset: str = Field(pattern=ID)
    request: str = Field(pattern=ID)
    take: str = Field(pattern=ID)


class Chunk(Strict):
    production: str = Field(pattern=ID)
    asset: str = Field(pattern=ID)
    request: str = Field(pattern=ID)
    take: str = Field(pattern=ID)
    offset: int = Field(ge=0, le=16 * 1024 * 1024)


SCHEMAS = dict(create=Create, open=Open, list=Strict, admit=Strict,
               update_brief=UpdateBrief, add_asset=AddAsset, update_asset=UpdateAsset,
               add_reference=AddReference, update_reference=UpdateReference,
               link_take=LinkTake, select_take=LinkTake, chunk=Chunk)
TOOL_OPERATIONS = ('create', 'list', 'open', 'update_brief', 'add_asset', 'update_asset',
                   'add_reference', 'update_reference', 'link_take', 'select_take')
assert set(KINDS) == set(MediaKind.__args__)
