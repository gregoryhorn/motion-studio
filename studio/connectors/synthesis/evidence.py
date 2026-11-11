"""Admit selected technical excerpts only; never fetch, execute or sanitize externally."""
import json
import re
from typing import Literal
from pydantic import Field
from ...domain import Strict, Fault
from ...persistence.primitives import digest
from ...connectors.integrity import integrity


class Excerpt(Strict):
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,31}$')
    section: str = Field(pattern=r'^[A-Za-z0-9 ._-]{1,80}$')
    text: str = Field(min_length=1, max_length=4096)


class Source(Strict):
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,31}$')
    source: str = Field(min_length=1, max_length=200)
    version: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
    kind: Literal['public-documentation', 'selected-technical-excerpt']
    excerpts: list[Excerpt] = Field(min_length=1, max_length=48)


class Selection(Strict):
    sources: list[Source] = Field(min_length=1, max_length=3)


# Additional defense, NOT proof that arbitrary prose contains no personal data.
FORBIDDEN = re.compile(r'(?i)(private|personal|sensitive|secret|credential|password|api[_ -]?key|bearer|token=|'
    r'prompt|chat history|identity|config|environment|/home/|/Users/|file://|'
    r'ignore .*instructions|system message|install|execute shell|import os|'
    r'localhost|127\.0\.0\.1|\b10\.\d+\.\d+\.\d+|\b192\.168\.|@|\x00)')


def admit(value):
    """Called by an owned evidence reader, never by a model or a policy boolean."""
    try:
        model = Selection.model_validate(value, strict=True)
        encoded = json.dumps(model.model_dump(), ensure_ascii=False)
        inspected_body = model.model_dump()
        for source in inspected_body['sources']:
            for excerpt in source['excerpts']:
                if re.fullmatch(r'Argument [1-9][0-9]* uses --prompt for direction\.', excerpt['text']):
                    # Exempt only the complete technical declaration; immutable
                    # evidence and all other inspected strings stay unchanged.
                    excerpt['text'] = excerpt['text'].replace('--prompt', '--direction')
        inspected = json.dumps(inspected_body, ensure_ascii=False).replace('Credential use is none.', '').replace('Credential use: none.', '')
        if len(encoded.encode()) > 24 * 1024 or FORBIDDEN.search(inspected):
            raise ValueError()
        ids = [s.id for s in model.sources]
        if len(set(ids)) != len(ids):
            raise ValueError()
        for source in model.sources:
            # Provenance is a public string, not an automatic fetch instruction.
            if not re.fullmatch(r'[A-Za-z0-9 ._:/#-]+', source.source):
                raise ValueError()
            if len({e.id for e in source.excerpts}) != len(source.excerpts):
                raise ValueError()
        return model.model_dump()
    except (ValueError, TypeError):
        raise Fault('TECHNICAL_EVIDENCE_EXCLUDED', 422) from None


def template_ref():
    return dict(id='documented-cli-wav', revision=1, digest=integrity())


def snapshot(value):
    body = admit(value)
    return dict(body=body, digest=digest(body), template=template_ref())
