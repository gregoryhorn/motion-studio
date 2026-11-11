"""Focused real storage/codec tests; every store is uniquely allocated."""
import base64
import hashlib
import json
import os

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from studio.assets.retention import Assets
from studio.domain import Fault, ImportIntent, MAX_BYTES, SaveRequest
from studio.media_import import BeginImport, ImportChunk, ImportID, MediaImports, RetrieveTake
from studio.media_import import invoke
from studio.media_import.contracts import CHUNK_BYTES, MediaDescriptor, describe_take
from studio.media_import.validation import inspect_media
from studio.persistence.store import Store, identity
from tests.media_import_fixtures import encoded, png, wav, seekable_mp4


class MediaImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='motion-media-import-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.store = Store(self.home)
        self.owners = {}
        self.assets = Assets(self.store)
        self.service = MediaImports(self.store, self.authorize, assets=self.assets)

    def authorize(self, db, scope, request):
        if self.owners.get(request) != scope:
            raise Fault('TEST_SCOPE_DENIED', 403)

    def request(self, kind='Image', scope='root-a'):
        saved = self.store.save(SaveRequest(command=identity(), expected=0, text='Controlled fixture', kind=kind))
        self.owners[saved['id']] = scope
        return saved

    def begin(self, data, format='png', request=None):
        request = request or self.request({'wav': 'Sound effects', 'mp4': 'Video'}.get(format, 'Image'))
        model = BeginImport.model_validate(dict(command=identity(), request=request['id'], revision=request['revision'],
                            digest=hashlib.sha256(data).hexdigest(), size=len(data), name='fixture.' + format,
                            format=format))
        return self.service.begin('root-a', model), model

    def upload(self, intent, data):
        for offset in range(0, len(data), CHUNK_BYTES):
            chunk = ImportChunk(id=intent['id'], offset=offset,
                                data=base64.b64encode(data[offset:offset + CHUNK_BYTES]).decode())
            self.service.chunk('root-a', chunk)

    def assert_fault(self, code, function, *args):
        with self.assertRaises(Fault) as failure:
            function(*args)
        self.assertEqual(failure.exception.code, code)

    def test_real_formats_exact_retrieval_reopen_and_lineage(self):
        formats = {'png': png(), 'wav': wav()}
        if shutil.which('ffmpeg') and shutil.which('ffprobe'):
            formats.update(jpeg=encoded('jpeg'), mp4=encoded('mp4'))
        for format, data in formats.items():
            with self.subTest(format=format):
                intent, model = self.begin(data, format)
                self.upload(intent, data)
                target = ImportID(id=intent['id'])
                first = self.service.commit('root-a', target)
                self.assertEqual(first, self.service.commit('root-a', target))
                self.assertEqual(intent, self.service.begin('root-a', model))
                # Existing retrieval is reused, not an incompatible parallel media store.
                actual, take = Assets(Store(self.home)).retrieve(intent['take'])
                self.assertEqual(actual, data)
                self.assertEqual(take['request'], model.request)
                self.assertEqual(take['revision'], 1)
                self.assertEqual(take['artifact'], intent['id'])
                self.assertEqual(take['origin'], 'user_import')
                self.assertEqual(take['review'], 'Not reviewed')
                self.assertEqual(json.loads(take['facts'])['storage'], 'original-v1')
                descriptor = invoke(self.service, 'root-a', 'describe', dict(take=intent['take']))
                self.assertEqual(descriptor['format'], format)
                self.assertEqual(descriptor['byteLength'], len(data))
                self.assertEqual(descriptor['sha256'], model.digest)
                self.assertEqual(descriptor['identity'], dict(production=None, asset=None,
                    request=model.request, requestRevision=1, take=intent['take'], artifact=intent['id']))
                self.assertEqual(descriptor['reviewStatus'], 'Not reviewed')
                self.assertNotIn('name', descriptor)
                self.assertEqual(MediaDescriptor.model_validate(descriptor).model_dump(), descriptor)
                self.assertEqual(self.store.snapshot()['requests'][0]['selected'], None)
                reopened = MediaImports(Store(self.home), self.authorize)
                self.assertEqual(reopened.retrieve('root-a', RetrieveTake(take=intent['take']))[0], data)
        self.assertEqual(len(self.store.snapshot()['takes']), len(formats))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Installed codecs required')
    def test_ordinary_seekable_mp4(self):
        data = seekable_mp4()
        self.assertGreater(data.index(b'moov'), data.index(b'mdat'))
        intent, _ = self.begin(data, 'mp4')
        self.upload(intent, data)
        self.service.commit('root-a', ImportID(id=intent['id']))
        self.assertEqual(self.service.retrieve('root-a', RetrieveTake(take=intent['take']))[0], data)

    def test_descriptor_source_kind_and_legacy_projection(self):
        data = wav()
        for kind in ('Sound effects', 'Music', 'Voice'):
            request = self.request(kind)
            intent, model = self.begin(data, 'wav', request)
            self.upload(intent, data)
            self.store.save(SaveRequest(command=identity(), id=model.request, expected=1,
                                        text='Different current request', kind='Video'))
            invoke(self.service, 'root-a', 'commit', dict(id=intent['id']))
            value = invoke(self.service, 'root-a', 'describe', dict(take=intent['take']))
            self.assertEqual(value['kind'], kind)
            self.assertEqual(value['identity']['requestRevision'], 1)
            self.assertIsNone(value['width'])
            self.assertAlmostEqual(value['duration'], 0.1)
            self.assert_fault('MEDIA_SCOPE_DENIED', invoke, self.service, 'root-b',
                              'describe', dict(take=intent['take']))
        legacy = self.request('Sound effects')
        intent = self.assets.intent(ImportIntent(command=identity(), request=legacy['id'], revision=1,
            digest=hashlib.sha256(data).hexdigest(), size=len(data), name='private-original.wav'))
        self.assets.upload(intent['id'], data)
        _, take = self.assets.retrieve(intent['take'])
        descriptor = describe_take(take, kind='Sound effects', production='a' * 32, asset='b' * 32)
        self.assertEqual(descriptor['mime'], 'audio/wav')
        self.assertEqual(descriptor['format'], 'wav')
        self.assertEqual(descriptor['identity']['production'], 'a' * 32)
        self.assertNotIn('private-original', json.dumps(descriptor))
        self.assert_fault('MEDIA_KIND_MISMATCH', lambda: describe_take(take, kind='Image'))

    def test_revocation_during_validation_prevents_finalization(self):
        data = png()
        intent, model = self.begin(data)
        self.upload(intent, data)
        def revoke(data, format):
            facts = inspect_media(data, format)
            self.owners[model.request] = 'root-b'
            return facts
        with patch('studio.media_import.service.inspect_media', side_effect=revoke):
            self.assert_fault('TEST_SCOPE_DENIED', self.service.commit, 'root-a', ImportID(id=intent['id']))
        self.assertEqual(self.store.snapshot()['takes'], [])
        self.assertFalse(self.service.path(intent['id'], True).exists())

    def test_earlier_wip_scope_schema_migrates_without_inventing_source_kind(self):
        with self.store.transaction() as db:
            db.execute('DROP TABLE media_import_scopes')
            db.execute('CREATE TABLE media_import_scopes(id TEXT PRIMARY KEY,scope TEXT,format TEXT)')
        self.service = MediaImports(self.store, self.authorize)
        intent, model = self.begin(wav(), 'wav')
        self.upload(intent, wav())
        self.service.commit('root-a', ImportID(id=intent['id']))
        with self.store.transaction() as db:
            db.execute('UPDATE media_import_scopes SET kind=NULL')
        payload = dict(take=intent['take'])
        self.assertEqual(invoke(self.service, 'root-a', 'describe', payload)['kind'], 'Sound effects')
        self.store.save(SaveRequest(command=identity(), id=model.request, expected=1,
                                   text='Later request', kind='Video'))
        self.assert_fault('MEDIA_DESCRIPTOR_UNAVAILABLE', invoke, self.service, 'root-a', 'describe', payload)
        self.assertEqual(self.service.retrieve('root-a', RetrieveTake(**payload))[0], wav())

    def test_nonregular_staging_and_retained_files_are_bounded(self):
        intent, _ = self.begin(png())
        os.mkfifo(self.service.path(intent['id']))
        self.assert_fault('UNSAFE_MEDIA_FILE', self.upload, intent, png())
        self.assert_fault('STORAGE_UNAVAILABLE', self.service.commit, 'root-a', ImportID(id=intent['id']))
        self.service.path(intent['id']).unlink()
        self.upload(intent, png())
        self.service.commit('root-a', ImportID(id=intent['id']))
        path = self.service.path(intent['id'], True)
        path.unlink()
        os.mkfifo(path)
        self.assert_fault('RETAINED_FILE_MISSING', self.service.retrieve, 'root-a', RetrieveTake(take=intent['take']))

    def test_scope_and_strict_payloads(self):
        intent, model = self.begin(png())
        for method, payload in [(self.service.status, ImportID(id=intent['id'])),
                                (self.service.cancel, ImportID(id=intent['id'])),
                                (self.service.commit, ImportID(id=intent['id']))]:
            self.assert_fault('MEDIA_SCOPE_DENIED', method, 'root-b', payload)
        self.assert_fault('TEST_SCOPE_DENIED', self.service.begin, 'root-b', model)
        for extra in ('path', 'root', 'client_root', 'owner', 'url'):
            with self.assertRaises(ValidationError):
                BeginImport.model_validate({**model.model_dump(), extra: '/forbidden'})
        self.assert_fault('INVALID_ID', lambda: ImportID(id='../escape'))
        self.upload(intent, png())
        self.service.commit('root-a', ImportID(id=intent['id']))
        self.assert_fault('MEDIA_SCOPE_DENIED', self.service.retrieve, 'root-b', RetrieveTake(take=intent['take']))
        self.owners[model.request] = 'root-b'
        self.assert_fault('TEST_SCOPE_DENIED', self.service.begin, 'root-a', model)

    def test_replay_chunk_resume_and_conflicts(self):
        data = wav()
        intent, model = self.begin(data, 'wav')
        first = ImportChunk(id=intent['id'], offset=0, data=base64.b64encode(data[:40]).decode())
        self.service.chunk('root-a', first)
        self.assertEqual(self.service.chunk('root-a', first)['received'], 40)
        self.service = MediaImports(Store(self.home), self.authorize)
        self.assertEqual(self.service.status('root-a', ImportID(id=intent['id']))['received'], 40)
        self.service.chunk('root-a', ImportChunk(id=intent['id'], offset=40, data=base64.b64encode(data[40:]).decode()))
        self.assert_fault('COMMAND_CONFLICT', self.service.begin, 'root-a', model.model_copy(update={'name': 'different'}))
        bad = first.model_copy(update={'data': base64.b64encode(b'X' * 40).decode()})
        self.assert_fault('IMPORT_BYTES_CONFLICT', self.service.chunk, 'root-a', bad)
        self.service.commit('root-a', ImportID(id=intent['id']))
        self.assertEqual(self.service.chunk('root-a', first)['received'], len(data))
        self.assertEqual(len(self.store.snapshot()['takes']), 1)

    def test_cancel_and_uncertain_finalize_recovery(self):
        data = png()
        intent, _ = self.begin(data)
        self.upload(intent, data)
        target = ImportID(id=intent['id'])
        def crash():
            raise RuntimeError('controlled crash after final file')
        self.service.after_finalize = crash
        with self.assertRaises(RuntimeError):
            self.service.commit('root-a', target)
        self.assertEqual(self.store.snapshot()['takes'], [])
        reopened = MediaImports(Store(self.home), self.authorize)
        self.assertEqual(reopened.cancel('root-a', target)['status'], 'Ready for review')
        self.assertEqual(len(self.store.snapshot()['takes']), 1)
        self.assertEqual(reopened.retrieve('root-a', RetrieveTake(take=intent['take']))[0], data)
        second, _ = self.begin(data)
        cancelled = ImportID(id=second['id'])
        self.assertEqual(reopened.cancel('root-a', cancelled)['status'], 'Cancelled')
        self.assert_fault('IMPORT_CANCELLED', reopened.commit, 'root-a', cancelled)
        self.assertEqual(reopened.cancel('root-a', target)['status'], 'Ready for review')

    def test_malformed_oversize_and_no_overwrite(self):
        for format, data in [('png', b'not png'), ('jpeg', b'not jpeg'), ('mp4', b'not mp4'), ('wav', b'not wav')]:
            with self.subTest(format=format):
                intent, _ = self.begin(data, format)
                self.upload(intent, data)
                with self.assertRaises(Fault):
                    self.service.commit('root-a', ImportID(id=intent['id']))
        self.assertEqual(self.store.snapshot()['takes'], [])
        intent, model = self.begin(png())
        with self.assertRaises(ValidationError):
            BeginImport.model_validate({**model.model_dump(), 'size': MAX_BYTES + 1})
        chunk = ImportChunk(id=intent['id'], offset=0, data=base64.b64encode(b'X' * (len(png()) + 1)).decode())
        self.assert_fault('IMPORT_BYTES_CONFLICT', self.service.chunk, 'root-a', chunk)
        self.service.path(intent['id'], True).write_bytes(b'existing unrelated bytes')
        self.assert_fault('IMPORT_BYTES_CONFLICT', self.upload, intent, png())
        self.assert_fault('IMPORT_BYTES_CONFLICT', self.service.commit, 'root-a', ImportID(id=intent['id']))
        self.assertEqual(self.service.path(intent['id'], True).read_bytes(), b'existing unrelated bytes')

    def test_missing_corrupt_and_symlink_preserve_record(self):
        data = png()
        intent, _ = self.begin(data)
        self.upload(intent, data)
        self.service.commit('root-a', ImportID(id=intent['id']))
        path = self.service.path(intent['id'], True)
        path.chmod(0o600)
        path.write_bytes(b'corrupt')
        self.assert_fault('RETAINED_FILE_CORRUPT', self.service.retrieve, 'root-a', RetrieveTake(take=intent['take']))
        path.unlink()
        self.assert_fault('RETAINED_FILE_MISSING', self.service.retrieve, 'root-a', RetrieveTake(take=intent['take']))
        self.assertEqual(len(self.store.snapshot()['takes']), 1)
        second, _ = self.begin(data)
        sentinel = self.home / 'sentinel'
        sentinel.write_bytes(b'unchanged')
        self.service.path(second['id']).symlink_to(sentinel)
        with self.assertRaises(Fault):
            self.upload(second, data)
        self.assertEqual(sentinel.read_bytes(), b'unchanged')

    def test_legacy_wav_unchanged_and_validator_absence(self):
        data, request = wav(), self.request('Sound effects')
        model = ImportIntent(command=identity(), request=request['id'], revision=1,
                             digest=hashlib.sha256(data).hexdigest(), size=len(data), name='legacy.wav')
        intent = self.assets.intent(model)
        self.assets.upload(intent['id'], data)
        self.assertEqual(self.assets.retrieve(intent['take'])[0], data)
        with patch('studio.media_import.validation.shutil.which', return_value=None):
            self.assert_fault('MEDIA_VALIDATOR_UNAVAILABLE', inspect_media, png(), 'png')
        self.assertEqual(self.assets.retrieve(intent['take'])[0], data)

    def test_strict_dispatch_and_chunk_boundaries(self):
        intent, _ = self.begin(png())
        self.assert_fault('UNKNOWN_MEDIA_OPERATION', invoke, self.service, 'root-a', 'path', {})
        self.assert_fault('INVALID_MEDIA_PAYLOAD', invoke, self.service, 'root-a', 'status',
                          dict(id=intent['id'], root='forged'))
        self.assert_fault('INVALID_MEDIA_PAYLOAD', invoke, self.service, 'root-a', 'chunk',
                          dict(id=intent['id'], offset=True, data='AAAA'))
        self.assert_fault('INVALID_MEDIA_CHUNK', invoke, self.service, 'root-a', 'chunk',
                          dict(id=intent['id'], offset=0, data='!!!!'))
        self.assert_fault('IMPORT_OFFSET_CONFLICT', invoke, self.service, 'root-a', 'chunk',
                          dict(id=intent['id'], offset=1, data='AAAA'))
        with self.assertRaises(ValidationError):
            ImportChunk(id=intent['id'], offset=0, data='A' * (4 * (CHUNK_BYTES // 3) + 4))

    def test_large_multichunk_file_and_partial_commit_resume(self):
        import io
        import wave
        output = io.BytesIO()
        with wave.open(output, 'wb') as target:
            target.setnchannels(2)
            target.setsampwidth(2)
            target.setframerate(48000)
            target.writeframes(b'\x00' * (48000 * 4 * 2))
        data = output.getvalue()
        intent, _ = self.begin(data, 'wav')
        payload = dict(id=intent['id'], offset=0, data=base64.b64encode(data[:CHUNK_BYTES]).decode())
        invoke(self.service, 'root-a', 'chunk', payload)
        self.assert_fault('IMPORT_BYTES_CONFLICT', invoke, self.service, 'root-a', 'commit', dict(id=intent['id']))
        self.assertEqual(invoke(self.service, 'root-a', 'status', dict(id=intent['id']))['status'], 'Media failed')
        for offset in range(CHUNK_BYTES, len(data), CHUNK_BYTES):
            invoke(self.service, 'root-a', 'chunk', dict(id=intent['id'], offset=offset,
                   data=base64.b64encode(data[offset:offset + CHUNK_BYTES]).decode()))
        invoke(self.service, 'root-a', 'commit', dict(id=intent['id']))
        self.assertEqual(self.assets.retrieve(intent['take'])[0], data)
        assembled = bytearray()
        for offset in range(0, len(data), 49152):
            part = invoke(self.service, 'root-a', 'read_chunk', dict(take=intent['take'], offset=offset))
            decoded = base64.b64decode(part['bytes'])
            self.assertEqual(part['mime'], 'audio/wav')
            self.assertEqual(part['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(part['chunk_sha256'], hashlib.sha256(decoded).hexdigest())
            assembled.extend(decoded)
        self.assertEqual(bytes(assembled), data)
        self.assert_fault('MEDIA_CHUNK_INVALID', invoke, self.service, 'root-a', 'read_chunk',
                          dict(take=intent['take'], offset=len(data)))

    def test_truncated_media_and_dimension_limits(self):
        cases = [('png', png()[:-5]), ('png', png(4097, 1)), ('wav', wav()[:-1])]
        if shutil.which('ffmpeg') and shutil.which('ffprobe'):
            cases += [('jpeg', encoded('jpeg')[:-3]), ('mp4', encoded('mp4')[:-5])]
        for format, data in cases:
            with self.subTest(format=format, size=len(data)):
                with self.assertRaises(Fault):
                    inspect_media(data, format)
        corrupt = bytearray(png())
        corrupt[45] ^= 1
        self.assert_fault('MALFORMED_MEDIA', inspect_media, bytes(corrupt), 'png')

    def test_disk_refusal_and_cancelled_upload(self):
        intent, _ = self.begin(png())
        with patch('studio.media_import.service.os.open', side_effect=OSError('controlled disk refusal')):
            self.assert_fault('STORAGE_UNAVAILABLE', self.upload, intent, png())
        self.assertEqual(self.store.snapshot()['takes'], [])
        self.service.cancel('root-a', ImportID(id=intent['id']))
        self.assert_fault('IMPORT_CANCELLED', self.upload, intent, png())

    def test_old_revision_preserved_after_edit(self):
        data = png()
        intent, model = self.begin(data)
        self.upload(intent, data)
        self.store.save(SaveRequest(command=identity(), id=model.request, expected=1,
                                    text='New direction', kind='Video'))
        self.assertEqual(self.service.begin('root-a', model), intent)
        self.service.commit('root-a', ImportID(id=intent['id']))
        _, take = self.assets.retrieve(intent['take'])
        self.assertEqual(take['revision'], 1)
        self.assertEqual(json.loads(take['facts'])['kind'], 'image')

    def test_two_service_commits_and_scope_recheck_after_read(self):
        from concurrent.futures import ThreadPoolExecutor
        data = png()
        intent, model = self.begin(data)
        self.upload(intent, data)
        other = MediaImports(Store(self.home), self.authorize)
        target = ImportID(id=intent['id'])
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda service: service.commit('root-a', target), [self.service, other]))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.store.snapshot()['takes']), 1)
        original = self.assets.retrieve
        def revoke(take):
            result = original(take)
            self.owners[model.request] = 'root-b'
            return result
        with patch.object(self.assets, 'retrieve', side_effect=revoke):
            self.assert_fault('TEST_SCOPE_DENIED', self.service.retrieve, 'root-a', RetrieveTake(take=intent['take']))


if __name__ == '__main__':
    unittest.main()
