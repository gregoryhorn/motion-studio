"""Strict original-text decoding and conservative, source-backed semantic admission."""
import json
from typing import Literal
from pydantic import Field, ValidationError
from ...domain import Strict, Fault
from ...connectors.schema import Evidence
from ...connectors.synthesis.evidence import template_ref


class TemplateRef(Strict):
    id: Literal['documented-cli-wav']
    revision: Literal[1]
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class Reference(Strict):
    source: str = Field(max_length=32)
    excerpt: str = Field(max_length=32)
    quote: str = Field(min_length=1, max_length=4096)


class Unknown(Strict):
    field: str = Field(pattern=r'^[a-z0-9_.]{1,80}$')
    reason: Literal['missing', 'contradictory', 'outside-family']


class Envelope(Strict):
    schema_version: Literal[1]
    template_ref: TemplateRef
    tool_version: str = Field(max_length=64)
    mapping: Evidence
    evidence_map: dict[str, list[Reference]] = Field(max_length=64)
    unknowns: list[Unknown] = Field(max_length=3)


def decode(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError()
            result[key] = value
        return result
    def constant(_): raise ValueError()
    if not isinstance(text, str) or len(text.encode()) > 16384:
        raise Fault('INVALID_PROPOSAL', 422)
    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        if not isinstance(result, dict): raise ValueError()
        pending = [(result, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 16: raise ValueError()
            if isinstance(value, (dict, list)):
                pending.extend((child, depth+1) for child in (value.values() if isinstance(value, dict) else value))
            elif type(value) is bool: raise ValueError()
        return result
    except (ValueError, RecursionError):
        raise Fault('INVALID_PROPOSAL', 422) from None


def leaves(value, prefix=''):
    result = {}
    items = enumerate(value) if isinstance(value, list) else value.items() if isinstance(value, dict) else None
    if items is None: return {prefix: value}
    for key, child in items:
        result.update(leaves(child, f'{prefix}.{key}' if prefix else str(key)))
    return result


def statements(mapping):
    """Finite proof vocabulary. Unrecognized prose stays unresolved, never guessed.

    These technical sentences are not schema/code authored by a user. Each names
    an assertion plainly. Two wordings are recognized; no app-name dispatch.
    """
    flat = leaves(mapping)
    result = {}
    labels = {'tool_version': 'Tool version', 'operation': 'Operation', 'format': 'Audio format',
        'seconds_min': 'Minimum duration', 'seconds_max': 'Maximum duration',
        'seconds_default': 'Default duration', 'seed_default': 'Default seed',
        'effects.destination': 'Output destination', 'effects.network': 'Network access',
        'effects.cost': 'Operation cost', 'effects.model': 'Model use',
        'effects.credentials': 'Credential use', 'effects.use': 'Permitted use',
        'process.execution': 'Execution', 'process.exit': 'Exit semantics',
        'process.stop': 'Stop semantics', 'process.idempotency': 'Replay policy',
        'process.timeout_seconds': 'Deadline seconds'}
    for field, value in flat.items():
        if field == 'schema_version': continue  # App-owned schema constant, not a tool claim.
        if field.startswith('arguments.'):
            index = int(field.split('.')[1])
            arg = mapping['arguments'][index]
            text = f"Argument {index + 1} uses {arg['flag']} for {arg['value']}"
        elif field.startswith('receipt.'):
            text = f"Receipt {field.split('.')[1]} field is {value}"
        else:
            text = f'{labels[field]} is {value}'
        # Exact sentence or colon-style technical reference; arbitrary paraphrase
        # cannot be established by a second LLM/confidence score.
        result[field] = {text + '.', text.replace(' is ', ': ', 1) + '.'}
    return result


def validate(response, selection) -> dict:
    raw = decode(response.text)
    # Absence of optional host jsonschema does not bypass our mandatory gate.
    if response.parsed is not None:
        try:
            if json.dumps(response.parsed, sort_keys=True, allow_nan=False) != json.dumps(raw, sort_keys=True, allow_nan=False):
                raise ValueError()
        except (ValueError, TypeError):
            raise Fault('INVALID_PROPOSAL', 422) from None
    try:
        if type(raw.get('schema_version')) is not int: raise ValueError()
        envelope = Envelope.model_validate(raw, strict=True)
        if envelope.template_ref.model_dump() != template_ref(): raise ValueError()
        mapping = envelope.mapping.model_dump()
        if envelope.tool_version != mapping['tool_version']: raise ValueError()
        assertions = statements(mapping)
        if set(envelope.evidence_map) != set(assertions): raise ValueError()
        if any(u.field not in assertions for u in envelope.unknowns): raise ValueError()
    except (ValueError, ValidationError, KeyError, TypeError):
        raise Fault('INVALID_PROPOSAL', 422) from None
    versions = {source['version'] for source in selection['sources']}
    if versions != {envelope.tool_version}:
        return dict(state='Needs information', questions=['Which documented version should this integration use?'])
    excerpts = {(s['id'], e['id']): e['text'] for s in selection['sources'] for e in s['excerpts']}
    # All open reference strings must equal admitted excerpts below. Other
    # strings are closed TC1 primitives, pins, enums or validated field names.
    missing = []
    for field, accepted in assertions.items():
        refs = envelope.evidence_map[field]
        if not 1 <= len(refs) <= 3: raise Fault('INVALID_PROPOSAL', 422)
        for ref in refs:
            if excerpts.get((ref.source, ref.excerpt)) != ref.quote:
                raise Fault('INVALID_PROPOSAL', 422)
        supported = any(ref.quote in accepted for ref in refs)
        allowed_quotes = accepted | ({'Audio output is the originally allocated WAV and flat JSON receipt pair.'} if field == 'format' else set())
        if any(ref.quote not in allowed_quotes for ref in refs): supported = False
        if field == 'format':
            supported = supported and any(ref.quote == 'Audio output is the originally allocated WAV and flat JSON receipt pair.' for ref in refs)
        # Contradiction in any selected excerpt defeats a supporting citation.
        sentence = sorted(accepted)[0]
        if field.startswith('arguments.'):
            prefixes = (f"Argument {int(field.split('.')[1])+1} uses ",)
        else:
            stem = sentence.split(' is ')[0].split(': ')[0]
            prefixes = (stem + ' is ', stem + ': ')
        contradictory = any(text.startswith(prefixes) and text not in accepted for text in excerpts.values())
        if not supported or contradictory: missing.append(field)
    missing += [u.field for u in envelope.unknowns]
    if any(u.reason == 'outside-family' for u in envelope.unknowns):
        return dict(state='Unsupported', questions=['This interface does not fit the shipped local sound-effect CLI family. Provide supported interface documentation or request support; no tool is enabled.'])
    if missing:
        return dict(state='Needs information', questions=[question(field) for field in dict.fromkeys(missing)][:3])
    return dict(state='Proposal ready', proposal=raw, questions=[], enabled=False, qualified=False)


def question(field: str) -> str:
    labels: dict[str, str] = {'tool_version':'the exact tool version', 'operation':'the supported sound-effect action',
              'format':'the original WAV and receipt format', 'process.stop':'how the running process is stopped',
              'process.idempotency':'whether repeating an uncertain operation is safe',
              'process.exit':'what completion and failure mean', 'process.execution':'whether the process can detach'}
    if field.startswith('arguments.'):
        detail = 'input option '+str(int(field.split('.')[1])+1)+' and its documented meaning'
    else:
        detail = labels.get(field, field.replace('.', ' ').replace('_', ' '))
    return 'Provide unambiguous technical documentation for '+detail+'.'
