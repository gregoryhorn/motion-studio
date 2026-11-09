"""Stdlib-only, read-only Studio manifest and release identity contract.

The schema producer here is authoritative; schemas/studio-manifest.json is its
snapshot. No manifest value is executable. No installed plugin code is imported.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit

MANIFEST = 'studio-manifest.json'
PAYLOAD = ('plugin.yaml', '__init__.py', 'studio', 'schemas', 'skills', 'desktop', 'dashboard')
MAX_JSON = 4 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_ENTRIES = 10000
SHA = r'^[0-9a-f]{64}$'
COMMIT = r'^[0-9a-f]{40}$'


class ValidationError(ValueError):
    """A bounded diagnostic, never a raw parser/OS error containing secret data."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def object_schema(properties, required=None):
    return dict(type='object', properties=properties, additionalProperties=False,
                required=list(properties) if required is None else required)


def manifest_schema():
    text = dict(type='string', minLength=1, maxLength=2048)
    texts = dict(type='array', items=text, maxItems=256, uniqueItems=True)
    versions = dict(type='array', items=dict(type='integer', minimum=1),
                    maxItems=32, uniqueItems=True)
    nullable_text = dict(type=['string', 'null'], minLength=1, maxLength=256)
    dependency = object_schema(dict(
        kind=dict(enum=['python', 'executable', 'resource', 'model']), identifier=text,
        constraint=nullable_text, source=nullable_text,
        sha256=dict(type=['string', 'null'], pattern=SHA),
        size=dict(type=['integer', 'null'], minimum=0, maximum=MAX_FILE),
        verification=dict(enum=['native-python', 'sha256', 'binding-discovery']),
        delivery=dict(enum=['bundled', 'existing', 'download']), notices=texts))
    pack = object_schema(dict(id=dict(type='string', pattern=r'^[a-z][a-z0-9-]{0,63}$'),
        required=dict(type='boolean'), platforms=texts, operations=texts,
        compatibility=nullable_text,
        dependencies=dict(type='array', items=dependency, maxItems=256)))
    record = object_schema(dict(path=text,
        size=dict(type='integer', minimum=0, maximum=MAX_FILE),
        sha256=dict(type='string', pattern=SHA),
        mode=dict(type='integer', minimum=0, maximum=0o777)))
    schema = object_schema(dict(schema=dict(const='motion/studio-manifest/v1'),
        plugin_id=dict(const='motion-studio'),
        version=dict(type='string', pattern=r'^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$'),
        qualification=dict(enum=['unqualified-development', 'qualified']),
        compatibility=object_schema(dict(platforms=texts, architectures=texts, python=nullable_text,
            hermes=nullable_text,
            tested_host_revisions=dict(type='array', items=dict(type='string', pattern=COMMIT),
                                       maxItems=256, uniqueItems=True),
            adapter_abis=versions, project_schemas=versions, plan_schemas=versions)),
        payload=dict(type='array', items=record, maxItems=MAX_ENTRIES),
        packs=dict(type='array', items=pack, maxItems=256),
        storage=object_schema(dict(readable=versions, writable=versions,
                                   migration=dict(const='none')))))
    return dict(schema, **{'$schema': 'https://json-schema.org/draft/2020-12/schema',
                          'title': 'Motion Studio shared release/pack manifest'})


def validate_shape(value, schema, at='$'):
    """The deliberately small JSON Schema vocabulary emitted above."""
    types = dict(object=dict, array=list, string=str, integer=int, boolean=bool,
                 null=type(None))
    if 'type' in schema:
        allowed = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        require(any(type(value) is types[k] for k in allowed), at + ': type')
    if 'const' in schema:
        require(value == schema['const'], at + ': constant')
    if 'enum' in schema:
        require(value in schema['enum'] and not isinstance(value, bool), at + ': enum')
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        require(all(k in value for k in schema.get('required', [])), at + ': required field')
        if schema.get('additionalProperties') is False:
            require(not set(value) - set(properties), at + ': unknown field')
        for k, v in value.items():
            if k in properties:
                validate_shape(v, properties[k], at + '.' + k)
    elif isinstance(value, list):
        require(len(value) <= schema.get('maxItems', MAX_ENTRIES), at + ': too many items')
        if schema.get('uniqueItems'):
            require(len({canonical(v) for v in value}) == len(value), at + ': duplicates')
        for i, v in enumerate(value):
            validate_shape(v, schema.get('items', {}), at + '[' + str(i) + ']')
    elif isinstance(value, str):
        require(schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', MAX_JSON),
                at + ': length')
        if 'pattern' in schema:
            require(re.fullmatch(schema['pattern'], value) is not None, at + ': format')
    elif type(value) is int:
        require(schema.get('minimum', value) <= value <= schema.get('maximum', value),
                at + ': range')


def safe_path(path, existing=True):
    path = Path(path).expanduser()
    require(path.is_absolute() and '..' not in path.parts, 'absolute canonical path required')
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            require(not existing, 'path absent')
            continue
        require(not stat.S_ISLNK(info.st_mode), 'symlink/unsupported')
    if existing:
        require(path.resolve(strict=True) == path, 'noncanonical path')
    return path


def open_readonly(path, directory=False):
    # Walk directory descriptors with O_NOFOLLOW on EVERY component. A
    # preflight lstat alone would allow ancestor-swap reads outside the root.
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    parent = os.open(path.anchor, flags | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent)
            os.close(parent)
            parent = child
        if not path.parts[1:]:
            return os.dup(parent)
        return os.open(path.name, flags | (os.O_DIRECTORY if directory else 0), dir_fd=parent)
    finally:
        os.close(parent)


def children(path):
    fd = open_readonly(safe_path(path), directory=True)
    names = []
    try:
        with os.scandir(fd) as entries:
            for entry in entries:
                names.append(entry.name)
                require(len(names) <= MAX_ENTRIES, 'payload entry limit')
    finally:
        os.close(fd)
    return [path / name for name in sorted(names)]


def read_bytes(path, limit=MAX_FILE):
    path = safe_path(path)
    fd = open_readonly(path)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'nonregular/linked file')
        require(info.st_size <= limit, 'file size limit')
        chunks, length = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - length))
            if not chunk:
                break
            chunks.append(chunk)
            length += len(chunk)
            require(length <= limit, 'file size limit')
        after = os.fstat(fd)
        current = path.lstat()
        identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        require(identity(info) == identity(after) == identity(current), 'file changed during read')
        return b''.join(chunks), stat.S_IMODE(info.st_mode)
    finally:
        os.close(fd)


def parse_json(data):
    require(isinstance(data, bytes) and len(data) <= MAX_JSON, 'JSON size/type limit')
    def pairs(items):
        obj = {}
        for k, v in items:
            require(k not in obj, 'duplicate JSON key')
            obj[k] = v
        return obj
    try:
        # Bound nesting before the decoder, including on hosts/tests that raise
        # Python's recursion limit. Brackets inside JSON strings do not count.
        depth, quoted, escaped = 0, False, False
        for byte in data:
            if quoted:
                if escaped:
                    escaped = False
                elif byte == 92:
                    escaped = True
                elif byte == 34:
                    quoted = False
            elif byte == 34:
                quoted = True
            elif byte in (91, 123):
                depth += 1
                require(depth <= 32, 'JSON structure limit')
            elif byte in (93, 125):
                depth -= 1
                require(depth >= 0, 'invalid JSON')
        value = json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValidationError('nonfinite JSON')))
        pending, count = [(value, 0)], 0
        while pending:
            node, depth = pending.pop()
            count += 1
            require(depth <= 32 and count <= 100000, 'JSON structure limit')
            if isinstance(node, dict):
                pending.extend((child, depth + 1) for child in node.values())
            elif isinstance(node, list):
                pending.extend((child, depth + 1) for child in node)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError('invalid JSON') from None


def read_json(path):
    return parse_json(read_bytes(path, MAX_JSON)[0])


def payload_path(value):
    require(isinstance(value, str) and value.isascii() and len(value) <= 512,
            'payload path format')
    require('\\' not in value and ':' not in value and
            all(part not in ('', '.', '..') for part in value.split('/')) and
            not PurePosixPath(value).is_absolute() and
            all(ord(c) >= 32 and ord(c) != 127 for c in value), 'unsafe payload path')
    require(value != MANIFEST and (value in PAYLOAD[:2] or
            value.split('/')[0] in PAYLOAD[2:]), 'unmanaged/self-referential payload path')
    return value


def inventory(root, installed=False):
    """Exact deterministic bytes/modes, excluding manifest and bytecode caches.

    Installed mode detects extra top-level members WITHOUT reading their data.
    Native .git directories are not payload and are never read. Source mode
    selects managed roots. Links are refused, even in caches/native metadata.
    """
    root = safe_path(root)
    require(root.is_dir(), 'payload root not a directory')
    records, total, count, seen = [], 0, 0, set()

    def visit(path):
        nonlocal count, total
        count += 1
        require(count <= MAX_ENTRIES, 'payload entry limit')
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'symlink/unsupported')
        relative = path.relative_to(root).as_posix()
        require(len(path.relative_to(root).parts) <= 64, 'payload depth limit')
        key = relative.casefold()
        require(key not in seen, 'case-colliding payload')
        seen.add(key)
        if stat.S_ISDIR(info.st_mode):
            for child in children(path):
                visit(child)
        else:
            require(stat.S_ISREG(info.st_mode), 'nonregular/unsupported payload')
            # Only bytecode inside conventional Python cache directories is ignored.
            if '__pycache__' in path.relative_to(root).parts and path.suffix == '.pyc':
                return
            data, mode = read_bytes(path)
            total += len(data)
            require(total <= MAX_TOTAL, 'payload total size limit')
            records.append(dict(path=relative, size=len(data), sha256=digest(data), mode=mode))

    for path in children(root):
        if path.name == MANIFEST:
            require(not path.is_symlink(), 'symlink/unsupported')
            continue
        if path.name in PAYLOAD:
            visit(path)
        elif installed:
            info = path.lstat()
            require(not stat.S_ISLNK(info.st_mode), 'symlink/unsupported')
            if path.name == '.git' and stat.S_ISDIR(info.st_mode):
                continue
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),
                    'nonregular/unsupported payload')
            records.append(dict(path=path.name + ('/' if path.is_dir() else ''),
                size=info.st_size if stat.S_ISREG(info.st_mode) else 0,
                sha256=None, mode=stat.S_IMODE(info.st_mode)))
    return sorted(records, key=lambda row: row['path'])


def validate_manifest(value, install_ready=False):
    validate_shape(value, manifest_schema())
    paths = [payload_path(record['path']) for record in value['payload']]
    require(paths == sorted(paths) and len(set(p.casefold() for p in paths)) == len(paths),
            'unsorted/duplicate/case-colliding payload')
    require(sum(row['size'] for row in value['payload']) <= MAX_TOTAL, 'payload total size limit')
    ids = [pack['id'] for pack in value['packs']]
    require(len(set(ids)) == len(ids), 'duplicate pack id')
    for pack in value['packs']:
        for dep in pack['dependencies']:
            if dep['delivery'] in ('download', 'bundled') and dep['kind'] != 'python':
                require(dep['sha256'] is not None and dep['size'] is not None,
                        'distributed dependency missing hash/size')
            if dep['source'] is not None:
                source_url(dep['source'])
    if install_ready:
        comp = value['compatibility']
        require(value['qualification'] == 'qualified', 'unqualified development release')
        require(all(comp[k] for k in comp) and value['payload'] and value['packs'] and
                value['storage']['readable'] and value['storage']['writable'],
                'release qualification incomplete')
        require(any(pack['required'] for pack in value['packs']), 'required core pack absent')
    return value


def plugin_declaration(root):
    """Fail closed outside the simple native declaration subset supported by P01.

    This is NOT a YAML interpreter. Dependency declarations other than [] are
    diagnosed as unsupported, never silently treated as empty.
    """
    data = read_bytes(Path(root) / 'plugin.yaml', MAX_JSON)[0].decode('utf-8')
    fields = {}
    for key in ('name', 'version', 'python_dependencies'):
        matches = re.findall(r'^' + key + r':\s*([^\n]*)$', data, flags=re.MULTILINE)
        require(len(matches) == 1, 'native declaration ambiguous: ' + key)
        fields[key] = matches[0].strip()
    require(fields['python_dependencies'] == '[]', 'SHARED_DEPENDENCY_CHANGE: nonempty/unknown native dependencies')
    return fields


def verify_tree(root, manifest=None, installed=False):
    value = validate_manifest(manifest if manifest is not None else read_json(Path(root) / MANIFEST))
    declaration = plugin_declaration(root)
    require(declaration['name'] == value['plugin_id'] and declaration['version'] == value['version'],
            'plugin declaration/manifest disagreement')
    require(not any(dep['kind'] == 'python' for pack in value['packs'] if pack['required']
                    for dep in pack['dependencies']),
            'SHARED_DEPENDENCY_CHANGE: required pack Python dependencies disagree with native []')
    actual = inventory(root, installed=installed)
    require(actual == value['payload'], 'payload differs from manifest')
    return value


def aggregate(root, manifest=None):
    value = verify_tree(root, manifest, installed=True)
    data, mode = read_bytes(Path(root) / MANIFEST, MAX_JSON)
    return inventory_aggregate(value, data, mode)


def inventory_aggregate(manifest, manifest_bytes, manifest_mode):
    records = list(manifest['payload']) + [dict(path=MANIFEST, size=len(manifest_bytes),
        sha256=digest(manifest_bytes), mode=manifest_mode)]
    return digest(canonical(sorted(records, key=lambda row: row['path'])))


def source_url(value):
    require(isinstance(value, str) and len(value) <= 2048 and not any(c.isspace() for c in value),
            'source URL invalid')
    url = urlsplit(value)
    require(url.scheme == 'https' and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment and url.path not in ('', '/'), 'source URL must be credential-free HTTPS')
    return value


def validate_descriptor(value):
    validate_shape(value, object_schema(dict(schema=dict(const='motion/studio-release/v1'),
        source=dict(type='string', minLength=1, maxLength=2048),
        commit=dict(type='string', pattern=COMMIT),
        version=dict(type='string', minLength=1, maxLength=128),
        manifest_sha256=dict(type='string', pattern=SHA),
        payload_sha256=dict(type='string', pattern=SHA))))
    source_url(value['source'])
    return value


def immutable_update_pair(baseline, target, approved_source):
    """Validate and detach approved immutable transaction identities.

    This is input validation, not native trust, CAS or activation evidence.
    """
    baseline = validate_descriptor(parse_json(canonical(baseline)))
    target = validate_descriptor(parse_json(canonical(target)))
    require(baseline['source'] == target['source'] == source_url(approved_source),
            'SOURCE_UNTRUSTED: source change refused')
    require(baseline != target, 'ALREADY_AT_TARGET: use identity status, not reinstall')
    require(baseline['version'] != target['version'], 'PUBLICATION_CONFLICT: reused version')
    require(baseline['commit'] != target['commit'], 'PUBLICATION_CONFLICT: reused immutable commit')
    return baseline, target


def verify_descriptor(root, descriptor, approved_source):
    descriptor = validate_descriptor(descriptor)
    require(descriptor['source'] == source_url(approved_source), 'SOURCE_UNTRUSTED: source differs')
    manifest = verify_tree(root, installed=True)
    validate_manifest(manifest, install_ready=True)
    require(descriptor['version'] == manifest['version'], 'release/manifest version disagreement')
    require(descriptor['manifest_sha256'] == digest(read_bytes(Path(root) / MANIFEST, MAX_JSON)[0]),
            'manifest hash mismatch')
    require(descriptor['payload_sha256'] == aggregate(root, manifest), 'aggregate hash mismatch')
    return descriptor


def development_manifest(root):
    declaration = plugin_declaration(root)
    return dict(schema='motion/studio-manifest/v1', plugin_id=declaration['name'],
        version=declaration['version'], qualification='unqualified-development',
        compatibility=dict(platforms=[], architectures=[], python=None, hermes=None, tested_host_revisions=[],
                           adapter_abis=[], project_schemas=[], plan_schemas=[]),
        payload=inventory(root), packs=[], storage=dict(readable=[], writable=[], migration='none'))
