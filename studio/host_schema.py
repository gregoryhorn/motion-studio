"""Request-scoped schema projection and lossless local-reference factoring.

Canonical schemas and handler validation deliberately do not use this module.
Only schema positions are visited: examples, enum values and defaults are data.
Unused root definitions are removed conservatively; generated single-use
indirections are inlined after enclosing-subtree sharing has been resolved.
"""
from collections import Counter
import copy
import hashlib
import json
from urllib.parse import unquote

_MAPS = frozenset(('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'))
_SINGLE = frozenset(('items', 'additionalProperties', 'additionalItems', 'contains',
                     'not', 'if', 'then', 'else', 'propertyNames', 'unevaluatedProperties',
                     'unevaluatedItems', 'contentSchema'))
_LISTS = frozenset(('oneOf', 'anyOf', 'allOf', 'prefixItems'))


def _key(node):
    return json.dumps(node, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _children(node, visit):
    result = {}
    for key, value in node.items():
        if key in _MAPS and isinstance(value, dict):
            result[key] = {name: visit(child) if isinstance(child, dict) else copy.deepcopy(child)
                           for name, child in value.items()}
        elif key in _SINGLE and isinstance(value, dict):
            result[key] = visit(value)
        elif key in _LISTS and isinstance(value, list):
            result[key] = [visit(child) if isinstance(child, dict) else copy.deepcopy(child) for child in value]
        elif key == 'items' and isinstance(value, list):
            result[key] = [visit(child) if isinstance(child, dict) else copy.deepcopy(child) for child in value]
        else:
            result[key] = copy.deepcopy(value)
    return result


def _schema_nodes(node):
    """Yield schema objects only; JSON-looking examples/defaults remain data."""
    if not isinstance(node, dict):
        return
    yield node
    for key, value in node.items():
        if key in _MAPS and isinstance(value, dict):
            for child in value.values():
                yield from _schema_nodes(child)
        elif key in _SINGLE and isinstance(value, dict):
            yield from _schema_nodes(value)
        elif (key in _LISTS or key == 'items') and isinstance(value, list):
            for child in value:
                yield from _schema_nodes(child)


def _request_definitions(parameters):
    """Prune root definitions only when local reference scope is unambiguous.

    Keep the shared canonical registries unchanged. Unknown reference forms,
    legacy registries, dynamic references or nested IDs conservatively disable
    pruning rather than guessing which definition an engine might resolve.
    """
    result = copy.deepcopy(parameters)
    definitions = result.get('$defs')
    if not isinstance(definitions, dict):
        return result
    nodes = list(_schema_nodes(result))
    if any('definitions' in node or '$dynamicRef' in node or '$recursiveRef' in node
           or (node is not result and '$id' in node) for node in nodes):
        return result

    def targets(schema):
        found = set()
        for node in _schema_nodes(schema):
            if '$ref' not in node:
                continue
            reference = node['$ref']
            if not isinstance(reference, str) or not reference.startswith('#/$defs/'):
                raise ValueError('Unresolved reference scope')
            token = unquote(reference[len('#/$defs/'):]).split('/')[0]
            name = token.replace('~1', '/').replace('~0', '~')
            if name not in definitions:
                raise ValueError('Unresolved definition')
            found.add(name)
        return found

    try:
        pending = targets({key: value for key, value in result.items() if key != '$defs'})
        reachable = set()
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            pending.update(targets(definitions[name]) - reachable)
    except ValueError:
        return result
    result['$defs'] = {name: value for name, value in definitions.items() if name in reachable}
    return result


def _inline_single_use(result, generated):
    """Undo generated indirection made redundant by enclosing-subtree factoring.

    Original named definitions are never inlined, even if named like our hashes.
    Generated references form an acyclic graph of strictly smaller subtrees.
    """
    counts = Counter(node.get('$ref') for node in _schema_nodes(result) if '$ref' in node)
    singles = {name for name in generated if counts['#/$defs/' + name] == 1}
    if not singles:
        return result

    def inline(node):
        if len(node) == 1 and '$ref' in node:
            name = node['$ref'].removeprefix('#/$defs/')
            if name in singles:
                return inline(generated[name])
        return _children(node, inline)

    root = {key: value for key, value in result.items() if key != '$defs'}
    rewritten = inline(root)
    rewritten['$defs'] = {name: inline(value) for name, value in result['$defs'].items()
                          if name not in singles}
    return rewritten


def compact_parameters(parameters):
    """Factor identical repeated schema subtrees, retaining exact validation meaning.

    Names derive from content, never catalogue iteration or Python's random hash.
    Definitions are emitted lazily so descendants of a factored subtree do not
    leave unused definitions. Existing local references retain their root scope.
    """
    if not isinstance(parameters, dict):
        return copy.deepcopy(parameters)
    parameters = _request_definitions(parameters)
    # Relocating a subtree must not change base URIs, anchor identity, or a
    # descendant JSON Pointer target. All current tool schemas use root-local
    # whole-definition references; unfamiliar scopes retain their representation.
    for node in _schema_nodes(parameters):
        if ((node is not parameters and '$id' in node)
                or any(key in node for key in ('$anchor', '$dynamicAnchor', '$dynamicRef', '$recursiveRef'))):
            return parameters
        if '$ref' in node:
            reference = node['$ref']
            if (not isinstance(reference, str) or not reference.startswith('#/$defs/')
                    or '/' in unquote(reference[len('#/$defs/'):])):
                return parameters
    counts = Counter()

    def count(node):
        counts[_key(node)] += 1
        return _children(node, count)

    count(parameters)
    candidates = {key for key, count_ in counts.items() if count_ > 1 and len(key) >= 192}
    reserved = set(parameters.get('$defs', {}))
    names = {}
    for key in sorted(candidates):
        base = 's_' + hashlib.sha256(key.encode('ascii')).hexdigest()[:16]
        name = base
        while name in reserved:
            name += '_'
        reserved.add(name)
        names[key] = name
    definitions = {}

    def factor(node):
        key = _key(node)
        if key not in names:
            return _children(node, factor)
        name = names[key]
        if name not in definitions:
            # A JSON tree cannot contain itself; descendants are strictly smaller.
            definitions[name] = _children(node, factor)
        return {'$ref': '#/$defs/' + name}

    result = _children(parameters, factor)
    if definitions:
        result['$defs'] = {**result.get('$defs', {}), **{k: definitions[k] for k in sorted(definitions)}}
    return _inline_single_use(result, definitions)
