"""Disposable real native API/store fixture, with controlled imports and no generator.

The creation_commands insertion is TEST DATA, not a supported native import API.
No production registration or core is changed. Stdio mirrors native_package_fixture.
"""
import base64
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from unittest.mock import patch
import wave

from studio.domain import ImportIntent, SaveRequest
from studio.native.creation.policy import Association, AUDIENCE
from studio.native.creation.registration import register as register_creation
from studio.native.production.policy import ProductionAssociation
from studio.native.production.registration import register as register_production
from studio.persistence.primitives import identity
from tests.creation_support import Context

ROOT = 'session-a'


def controlled_wav(sample=700, frames=4800):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(48000)
        target.writeframes(b''.join(struct.pack('<h', sample if n % 2 else -sample)
                                   for n in range(frames)))
    return stream.getvalue()


class WorkspaceFixture:
    """Owns only a caller-supplied NEW test directory, never var or installed state."""
    def __init__(self, root):
        self.root = Path(root)
        self.ctx = Context(self.root / 'owned-plugin-data')
        self.generator_calls = 0
        self.policy = Association(profile=self.ctx.profile_name, revision='workspace-offline-r1',
            audience=AUDIENCE, direction_audio=True, canonical_roots=True, create_store=True)
        self.production_policy = ProductionAssociation(profile=self.ctx.profile_name,
            revision='workspace-offline-production-r1', production_management=True,
            direction_audio=True, canonical_roots=True)
        self.guards = []
        self.open()

    def open(self, instance=''):
        self.creation = register_creation(self.ctx, association=replace(self.policy, instance=instance))
        self.creation.acquire()
        assert self.creation.store is not None and self.creation.runs is not None
        assert self.creation.service is not None
        self.store = self.creation.store
        self.assets = self.creation.service.assets
        self.runs = self.creation.runs
        self.production = register_production(self.ctx, self.creation, association=self.production_policy)
        self.production.acquire()
        # A trap, not a fake generator: any attempted producer dispatch fails the test.
        for name in ('prepare', 'start'):
            guard = patch.object(self.creation.runs, name, side_effect=self.forbidden_generator)
            guard.start()
            self.guards.append(guard)
        self.ctx.methods['creation.admit']({}, session_id=ROOT)
        self.rpc('production.admit')

    def forbidden_generator(self, *args, **kwargs):
        self.generator_calls += 1
        raise AssertionError('WORKSPACE_GENERATOR_FORBIDDEN')

    def close(self):
        for guard in self.guards:
            guard.stop()
        self.guards.clear()
        self.creation.unload()

    def reopen(self):
        instance = self.creation.instance
        self.close()
        self.open(instance)

    def rpc(self, method, payload=None, root=ROOT):
        return self.ctx.methods[method](payload or {}, session_id=root)

    def seed(self, sample=700):
        """Actual existing Assets intent/upload; only native root association is seeded."""
        saved = self.store.save(SaveRequest(command=identity(), expected=0,
            text='Controlled workspace qualification audio', kind='Sound effects'))
        request = saved['id']
        with self.store.transaction() as db:
            db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                (request, ROOT, self.policy.revision, identity(), '{}', None, 'Imported', time.time()))
        data = controlled_wav(sample)
        # Use the supported media-import RPCs, as the workspace does, so the take has the
        # import scope record its scoped original reader (media_import.read_chunk) requires.
        intent = self.rpc('production.media_import.begin', dict(command=identity(), request=request,
            revision=1, digest=hashlib.sha256(data).hexdigest(), size=len(data), name='controlled.wav', format='wav'))
        assert 'error' not in intent, 'WORKSPACE_IMPORT_BEGIN'
        uploaded = self.rpc('production.media_import.chunk', dict(id=intent['id'], offset=0,
            data=base64.b64encode(data).decode()))
        assert uploaded.get('received') == len(data), 'WORKSPACE_IMPORT_CHUNK'
        assert self.rpc('production.media_import.commit', dict(id=intent['id'])).get('status') == 'Ready for review'
        return dict(request=request, take=intent['take'], bytes=base64.b64encode(data).decode())

    def seed_request(self, kind):
        """A saved same-kind request for this root so the workspace import control has a target. TEST DATA."""
        saved = self.store.save(SaveRequest(command=identity(), expected=0,
            text='Controlled workspace qualification ' + kind, kind=kind))
        with self.store.transaction() as db:
            db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                (saved['id'], ROOT, self.policy.revision, identity(), '{}', None, 'Imported', time.time()))
        return dict(request=saved['id'])

    def counts(self):
        with self.store.transaction() as db:
            result = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                      for table in ('requests', 'takes', 'local_runs', 'productions',
                                    'production_revisions', 'imports')}
        result.update(generator_calls=self.generator_calls,
                      media_files=len(list((self.store.home / 'media').iterdir())))
        return result

    def handle(self, message):
        op = message['op']
        if op == 'rpc':
            payload = dict(message.get('payload', {}))
            root = payload.pop('session_id', ROOT)
            return self.rpc(message['method'], payload, root)
        if op == 'seed': return self.seed(message.get('sample', 700))
        if op == 'seed-request': return self.seed_request(message['kind'])
        if op == 'counts': return self.counts()
        if op == 'reopen':
            self.reopen()
            return dict(reopened=True)
        raise ValueError('UNSUPPORTED_WORKSPACE_FIXTURE_OPERATION')


def main():
    with tempfile.TemporaryDirectory(prefix='workspace-e2e-', dir=os.environ.get('TMPDIR')) as temp:
        fixture = WorkspaceFixture(temp)
        try:
            for line in sys.stdin:
                message = json.loads(line)
                try:
                    result = dict(id=message['id'], result=fixture.handle(message))
                except Exception:
                    result = dict(id=message['id'], error='WORKSPACE_FIXTURE_FAILED')
                print(json.dumps(result), flush=True)
        finally:
            fixture.close()


if __name__ == '__main__':
    main()
