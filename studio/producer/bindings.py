"""Private immutable CLI binding revisions in the existing app authority."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from ..domain import Fault, opaque
from ..persistence.store import canonical, identity
from ..producer.contracts import SetupCLI


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def inspect_location(location, permitted):
    path = Path(location)
    if not path.is_absolute() or '..' in path.parts or str(path) != location or location not in permitted:
        raise Fault('LOCATION_DENIED', 409)
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o022 or not info.st_mode & 0o100 or info.st_size > 1024 * 1024):
            raise Fault('LOCATION_DENIED', 409)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise Fault('LOCATION_DENIED', 409)
            data = os.read(fd, 1024 * 1024 + 1)
            after = os.fstat(fd)
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(data) != after.st_size:
                raise Fault('RUNTIME_DRIFT', 409)
        finally:
            os.close(fd)
        return hashlib.sha256(data).hexdigest()
    except OSError:
        raise Fault('APP_MISSING', 409) from None


class Bindings:
    def __init__(self, store, catalog, *, allow_fixtures=False):
        self.store, self.catalog = store, catalog
        self.allow_fixtures = allow_fixtures or catalog.test_only
        self.overrides = {}
        self.scopes = {}
        with store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS app_bindings(id TEXT, revision INTEGER, body TEXT, PRIMARY KEY(id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS app_methods(request TEXT PRIMARY KEY, binding TEXT, revision INTEGER, operation TEXT)')

    def get(self, binding, revision=None) -> dict:
        with self.store.transaction() as db:
            row = db.execute('SELECT body FROM app_bindings WHERE id=? ' +
                             ('ORDER BY revision DESC LIMIT 1' if revision is None else 'AND revision=?'),
                             (opaque(binding),) if revision is None else (opaque(binding), revision)).fetchone()
        if not row:
            raise Fault('BINDING_NOT_FOUND', 404)
        return json.loads(row['body'])

    def put(self, value, binding=None, expected=0) -> dict:
        binding = opaque(binding) if binding else identity()
        with self.store.transaction() as db:
            current = db.execute('SELECT max(revision) FROM app_bindings WHERE id=?', (binding,)).fetchone()[0] or 0
            if current != expected:
                raise Fault('BINDING_CONFLICT', 409)
            body = dict(value, id=binding, revision=current + 1, schema_version=1)
            if len(canonical(body).encode()) > 16384:
                raise Fault('BINDING_TOO_LARGE')
            db.execute('INSERT INTO app_bindings VALUES(?,?,?)', (binding, current + 1, canonical(body)))
        return body

    def seed(self, runtime):
        """Compatibility setup is trusted server metadata, never a probe or launch."""
        value = self.catalog.compatibility(runtime)
        key = digest(value)[:32]
        try:
            record = self.get(key)
        except Fault as error:
            if error.code != 'BINDING_NOT_FOUND':
                raise
            record = self.put(value, key)
        self.overrides[(record['id'], record['revision'])] = runtime
        return record

    def save(self, proposal, *, permitted, binding=None, expected=0, fixture_only=False):
        proposal = SetupCLI(**proposal)
        adapter = self.catalog.lookup(proposal.adapter, proposal.adapter_version)
        if fixture_only and not self.catalog.test_only:
            raise Fault('FIXTURE_DENIED', 409)
        file_digest = inspect_location(proposal.executable, permitted)
        pins = adapter.validate_setup(proposal, file_digest, fixture_only)
        value = dict(adapter=adapter.id, adapter_version=adapter.version,
                     interface_version=proposal.interface_version, executable=proposal.executable,
                     pins=pins, file_digest=file_digest, fixture_only=fixture_only, enabled=False,
                     qualification='Setup checked', availability='Unavailable', reason='NOT_QUALIFIED',
                     action='Complete offline and live qualification for this operation',
                     capabilities=adapter.describe(),
                     checked_at=time.time(), evidence_scope='Passive executable inspection only',
                     approved_scope=sorted(permitted))
        return self.put(value, binding, expected)

    def revise(self, binding, expected, **changes):
        """Trusted server evidence update only; no browser payload reaches this port."""
        allowed = {'enabled', 'qualification', 'availability', 'reason', 'action'}
        if not set(changes) <= allowed:
            raise Fault('INVALID_BINDING')
        if changes.get('availability', 'Unavailable') not in ('Setup needed', 'Unavailable', 'Restricted for this use', 'Unsupported'):
            raise Fault('INVALID_BINDING')
        if changes.get('qualification', 'Not checked') not in ('Not checked', 'Setup checked', 'Offline tested only'):
            raise Fault('INVALID_BINDING')
        old = self.get(binding, expected)
        if changes.get('enabled') and (not old['fixture_only'] or not self.catalog.test_only):
            raise Fault('FEATURE_DISABLED', 409)
        value = {key: val for key, val in old.items() if key not in ('id', 'revision', 'schema_version')}
        if 'qualification' in changes:
            value['checked_at'] = time.time()
            value['evidence_scope'] = ('Controlled fixture interface/input/use only; no real capability'
                                       if changes['qualification'] == 'Offline tested only' else 'Qualification not established')
            value['evidence_reference'] = 'tests/test_adapter_contract.py' if changes['qualification'] == 'Offline tested only' else None
        return self.put(dict(value, **changes), binding, expected)

    def runtime(self, plan):
        scope = self.scopes.get(digest(plan))
        if scope is not None:
            scope.check_plan(plan)
            return scope.runtime
        record = plan['binding']
        runtime = self.overrides.get((record['id'], record['revision']))
        return runtime or self.catalog.for_plan(plan).runtime(record)

    @staticmethod
    def validate(record):
        required = {'id', 'revision', 'schema_version', 'adapter', 'adapter_version', 'interface_version',
                    'executable', 'pins', 'file_digest', 'fixture_only', 'enabled', 'qualification',
                    'availability', 'reason', 'action'}
        optional = {'capabilities', 'checked_at', 'evidence_scope', 'approved_scope', 'evidence_reference', 'evaluation_scope'}
        if type(record.get('schema_version')) is not int or record['schema_version'] != 1:
            raise Fault('UNSUPPORTED_SCHEMA', 409)
        if not required <= set(record) or not set(record) <= required | optional:
            raise Fault('INVALID_BINDING', 409)

    def check(self, plan):
        if plan['schema'] == 1:
            return
        record = plan['binding']
        self.validate(record)
        if record['fixture_only'] and not self.allow_fixtures:
            raise Fault('FIXTURE_DENIED', 409)
        if (digest(record) != plan['binding_digest'] or self.get(record['id'], record['revision']) != record):
            raise Fault('BINDING_CONFLICT', 409)
        latest = self.get(record['id'])
        scope = self.scopes.get(digest(plan))
        if 'connector' in record['pins'] and record['pins'] != latest['pins']:
            raise Fault('CONNECTOR_DRIFT',409)
        if scope is not None:
            scope.check_plan(plan)
        if (not latest['enabled'] or not record['enabled']) and scope is None:
            raise Fault('FEATURE_DISABLED', 409)
        for value in (record, latest):
            if value['reason'] in ('RESOURCE_BUSY', 'USE_RESTRICTED', 'RUNTIME_DRIFT'):
                raise Fault(value['reason'], 409)

    def public(self, record) -> dict:
        descriptor = self.catalog.describe(record['adapter'], record['adapter_version'], record['interface_version'])
        if 'connector' in record['pins']:
            descriptor = dict(descriptor,**record['capabilities'])
        availability, reason, action = record['availability'], record['reason'], record['action']
        latest = self.get(record['id'])
        if 'connector' in record['pins'] and record['pins'] != latest['pins']:
            availability,reason,action = 'Unavailable','CONNECTOR_DRIFT','Review the new disabled connector revision; prior plans are not rebound.'
        if not latest['enabled'] and record['enabled']:
            availability, reason, action = 'Unavailable', 'BINDING_DISABLED', 'Choose another supported app'
        if latest['reason'] in ('RESOURCE_BUSY', 'USE_RESTRICTED', 'RUNTIME_DRIFT', 'APP_MISSING'):
            availability, reason, action = latest['availability'], latest['reason'], latest['action']
        if descriptor.get('availability') == 'Unsupported':
            availability, reason, action = 'Unsupported', descriptor['reason'], descriptor['action']
        return dict(binding=record['id'], revision=record['revision'], current_revision=latest['revision'], descriptor=descriptor,
                    availability=availability, qualification=record['qualification'],
                    reason=reason, action=action, enabled=bool(record.get('evaluation_scope') and
                        record['enabled'] and latest['enabled'] and reason == 'EVALUATION_ENABLED'),
                    fixture_only=record['fixture_only'], checked_at=record.get('checked_at'),
                    evidence_reference=record.get('evidence_reference'),
                    evidence_scope=record.get('evidence_scope', 'Disabled metadata or explicit offline harness only'))

    def check_setup(self, binding, expected):
        """Explicit passive action: one bounded pinned file read; no process or contact."""
        if self.get(binding)['revision'] != expected:
            raise Fault('BINDING_CONFLICT', 409)
        old = self.get(binding, expected)
        try:
            observed = inspect_location(old['executable'], old.get('approved_scope', [old['executable']]))
            if observed != old['file_digest']:
                raise Fault('RUNTIME_DRIFT', 409)
        except Fault as error:
            missing = error.code == 'APP_MISSING'
            return self.revise(binding, expected, enabled=False, qualification='Not checked',
                availability='Setup needed' if missing else 'Unavailable', reason=error.code,
                action='Choose the supported executable location' if missing else 'Re-pin the supported version and requalify')
        return old

    def rows(self):
        with self.store.transaction() as db:
            rows = db.execute('''SELECT body FROM app_bindings a WHERE
                revision=(SELECT max(revision) FROM app_bindings WHERE id=a.id) OR
                EXISTS(SELECT 1 FROM app_methods m WHERE m.binding=a.id AND m.revision=a.revision)''').fetchall()
        return [self.public(json.loads(row['body'])) for row in rows]

    def select(self, request, binding, revision, operation):
        record = self.get(binding, revision)
        descriptor = self.catalog.lookup(record['adapter'], record['adapter_version']).describe()
        if operation not in descriptor['operations']:
            raise Fault('UNSUPPORTED_OPERATION', 409)
        with self.store.transaction() as db:
            snapshot = self.store.request(db, request)
            if snapshot['kind'] not in descriptor['media']:
                raise Fault('UNSUPPORTED_OPERATION', 409)
            db.execute('INSERT OR REPLACE INTO app_methods VALUES(?,?,?,?)', (request, binding, revision, operation))
        return dict(request=request, binding=binding, revision=revision, operation=operation)

    def selections(self):
        with self.store.transaction() as db:
            return [dict(row) for row in db.execute('SELECT * FROM app_methods')]
