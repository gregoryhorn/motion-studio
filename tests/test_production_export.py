"""Selected-output export over real disposable Production SQLite/retained WAVs.

No model/child runs. All fixtures and outputs live in a unique scratch directory.
"""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile
from studio.domain import Fault, ImportIntent, SaveRequest
from studio.native.production.models import AddAsset, Brief, Create, LinkTake
from studio.media_import import BeginImport, ImportChunk, ImportID, MediaImports
from studio.persistence.primitives import identity
from studio.production_export import ProductionExport
from studio.production_export.manifest import select
from tests.production_support import production_setup
from tests.media_import_fixtures import encoded, png

ROOT = 'canonical-root'
SENTINEL = 'PRIVATE_PROMPT_PATH_CHAT_TOKEN_SENTINEL'


def wav(samples=b'\x01\x00' * 100):
    out = io.BytesIO()
    with wave.open(out, 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(44100)
        target.writeframes(samples)
    return out.getvalue()


def collect(artifact):
    parts = []
    for offset in range(0, artifact.size, 49152):
        value = artifact.chunk(offset)
        data = base64.b64decode(value['bytes'])
        assert hashlib.sha256(data).hexdigest() == value['chunk_sha256']
        assert value['take'] == artifact.take
        parts.append(data)
    return b''.join(parts)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='production-export-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.ctx, self.creation, self.runtime, self.binding = production_setup(self.home)
        self.addCleanup(self.creation.unload)
        self.productions = self.runtime.acquire()
        self.export = ProductionExport(self.productions)
        self.data = wav()
        self.take = self.import_take()
        self.current = self.productions.create(ROOT, Create(command=identity(), title=SENTINEL,
            brief=Brief(text=SENTINEL), kinds=['Sound effects', 'Sound effects']))['current']
        for asset in self.current['assets']:
            self.current = self.productions.link_take(ROOT, LinkTake(command=identity(),
                production=self.current['id'], expected=self.current['revision'], asset=asset['id'],
                request=self.take['request'], take=self.take['id']))['current']
            self.current = self.productions.select_take(ROOT, LinkTake(command=identity(),
                production=self.current['id'], expected=self.current['revision'], asset=asset['id'],
                request=self.take['request'], take=self.take['id']))['current']
        self.ids = [asset['id'] for asset in self.current['assets']]

    def import_take(self):
        store = self.creation.store
        request = store.save(SaveRequest(command=identity(), expected=0, text=SENTINEL,
                                        kind='Sound effects', purpose=SENTINEL))['id']
        with store.transaction() as db:
            db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                (request, ROOT, self.creation.policy.revision, identity(), '{}', None, 'test_import', 0))
        assets = self.productions.assets
        model = ImportIntent(command=identity(), request=request, revision=1,
            digest=hashlib.sha256(self.data).hexdigest(), size=len(self.data), name=SENTINEL + '.wav')
        receipt = assets.intent(model)
        assets.upload(receipt['id'], self.data)
        with store.transaction() as db:
            return dict(store.take(db, receipt['take']))

    def prepare(self, **kwargs):
        return self.export.prepare(ROOT, self.current, self.ids, **kwargs)

    def import_media(self, format='png'):
        data = {'png': png, 'wav': wav}.get(format, lambda: encoded(format))()
        kind = {'png': 'Image', 'jpeg': 'Image', 'mp4': 'Video', 'wav': 'Sound effects'}[format]
        store = self.creation.store
        request = store.save(SaveRequest(command=identity(), expected=0, text=SENTINEL, kind=kind))['id']
        with store.transaction() as db:
            db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                (request, ROOT, self.creation.policy.revision, identity(), '{}', None, 'test_import', 0))
        imports = MediaImports(store, self.productions.creations.authorize_request,
                               assets=self.productions.assets)
        receipt = imports.begin(ROOT, BeginImport(command=identity(), request=request, revision=1,
            digest=hashlib.sha256(data).hexdigest(), size=len(data), name=SENTINEL + '.' + format,
            format=format))
        imports.chunk(ROOT, ImportChunk(id=receipt['id'], offset=0, data=base64.b64encode(data).decode()))
        imports.commit(ROOT, ImportID(id=receipt['id']))
        self.current = self.productions.add_asset(ROOT, AddAsset(command=identity(),
            production=self.current['id'], expected=self.current['revision'], kind=kind))['current']
        asset = self.current['assets'][-1]['id']
        for operation in (self.productions.link_take, self.productions.select_take):
            self.current = operation(ROOT, LinkTake(command=identity(), production=self.current['id'],
                expected=self.current['revision'], asset=asset, request=request, take=receipt['take']))['current']
        self.ids.append(asset)
        self.export = ProductionExport(self.productions, media_imports=imports)
        return data, asset, receipt, imports

    def fails(self, code, action):
        with self.assertRaises(Fault) as raised:
            action()
        self.assertEqual(raised.exception.code, code)

    def state(self):
        with self.creation.store.transaction() as db:
            rows = list(db.iterdump())
        media = {path.name: path.read_bytes() for path in self.creation.store.home.joinpath('media').iterdir()}
        return rows, media

    def test_deterministic_zip_exact_names_bytes_metadata_privacy_and_preservation(self):
        before = self.state()
        first, second = self.prepare(), self.export.prepare(ROOT, self.current, self.ids[::-1])
        payload = collect(first)
        self.assertEqual(payload, collect(second))
        self.assertEqual(first.descriptor()['mime'], 'application/zip')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            expected_names = [f"media/{self.ids.index(asset) + 1:02d}-sound-effects-take-01.wav"
                              for asset in sorted(self.ids)]
            self.assertEqual(archive.namelist(), expected_names + ['manifest.json'])
            for name in expected_names:
                self.assertEqual(archive.read(name), self.data)
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(set(manifest), {'schema_version', 'production', 'revision', 'outputs'})
            self.assertEqual(manifest['revision'], self.current['revision'])
            for item in manifest['outputs']:
                self.assertEqual(item['filename'],
                    f"media/{self.ids.index(item['asset']) + 1:02d}-sound-effects-take-01.wav")
                self.assertEqual(item['take'], self.take['id'])
                self.assertEqual(item['sha256'], self.take['digest'])
                self.assertEqual(item['mime'], 'audio/wav')
                self.assertEqual(item['measured']['frames'], 100)
                self.assertEqual(item['request_revision'], 1)
                self.assertEqual(item['lineage']['artifact'], self.take['artifact'])
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
        self.assertNotIn(SENTINEL.encode(), payload)
        self.assertNotIn(str(self.home).encode(), payload)
        self.assertEqual(before, self.state())
        first.close()
        second.close()

    def test_single_file_keeps_exact_original_and_extension(self):
        artifact = self.export.prepare(ROOT, self.current, self.ids[:1], mode='file')
        self.assertEqual(collect(artifact), self.data)
        self.assertEqual(artifact.filename, '01-sound-effects-take-01.wav')
        self.assertEqual(artifact.mime, 'audio/wav')
        artifact.close()
        self.fails('EXPORT_CLOSED', lambda: artifact.chunk(0))
        self.assertEqual(artifact._data, b'')

    def test_subset_keeps_asset_position_and_matches_zip_entry(self):
        selected = [self.ids[1]]
        artifact = self.export.prepare(ROOT, self.current, selected, mode='file')
        package = self.export.prepare(ROOT, self.current, selected)
        self.addCleanup(artifact.close)
        self.addCleanup(package.close)
        self.assertEqual(artifact.filename, '02-sound-effects-take-01.wav')
        with zipfile.ZipFile(io.BytesIO(collect(package))) as archive:
            self.assertEqual(archive.namelist(), ['media/' + artifact.filename, 'manifest.json'])
            item, = json.loads(archive.read('manifest.json'))['outputs']
            self.assertEqual((item['asset'], item['take']), (selected[0], self.take['id']))

    def test_audio_kind_slugs_and_two_digit_numbers(self):
        snapshot = copy.deepcopy(self.current)
        asset = snapshot['assets'][0]
        asset['position'] = 9
        asset['takes'].insert(0, dict(asset['takes'][0], id=identity()))
        for kind, slug in [('Sound effects', 'sound-effects'), ('Music', 'music'), ('Voice', 'voice')]:
            with self.subTest(kind=kind):
                asset['kind'] = kind
                pin, = select(snapshot, [asset['id']])
                self.assertEqual(pin['filename'], f'media/10-{slug}-take-02.wav')

    def test_cancel_before_and_during_retrieval_writes_nothing(self):
        before = self.state()
        self.fails('EXPORT_CANCELLED', lambda: self.prepare(cancelled=lambda: True))
        cancelled = [False]
        original = self.productions.assets.retrieve
        def retrieve(take):
            result = original(take)
            cancelled[0] = True
            return result
        with patch.object(self.productions.assets, 'retrieve', retrieve):
            self.fails('EXPORT_CANCELLED', lambda: self.prepare(cancelled=lambda: cancelled[0]))
        self.assertEqual(before, self.state())

    def test_scope_denied_cross_root_before_retrieval(self):
        with patch.object(self.productions.assets, 'retrieve', side_effect=AssertionError('must not retrieve')):
            self.fails('CREATION_WORKFLOW_REVIEW_REQUIRED',
                       lambda: self.export.prepare('other-root', self.current, self.ids))

    def test_reauthorization_after_retrieval_rejects_revocation(self):
        original = self.productions.assets.retrieve
        def retrieve(take):
            result = original(take)
            with self.creation.store.transaction() as db:
                db.execute('DELETE FROM production_roots WHERE root=?', (ROOT,))
            return result
        with patch.object(self.productions.assets, 'retrieve', retrieve):
            self.fails('PRODUCTION_WORKFLOW_REVIEW_REQUIRED', self.prepare)

    def test_revision_conflict_before_and_after_retrieval(self):
        old = copy.deepcopy(self.current)
        old['revision'] -= 1
        self.fails('EXPORT_REVISION_CONFLICT', lambda: self.export.prepare(ROOT, old, self.ids))
        original = self.productions.assets.retrieve
        def retrieve(take):
            result = original(take)
            with self.creation.store.transaction() as db:
                db.execute('UPDATE productions SET revision=revision+1 WHERE id=?', (self.current['id'],))
            return result
        with patch.object(self.productions.assets, 'retrieve', retrieve):
            self.fails('EXPORT_REVISION_CONFLICT', self.prepare)

    def test_chunks_reauthorize_revision_and_cancellation(self):
        cancelled = [False]
        artifact = self.prepare(cancelled=lambda: cancelled[0])
        cancelled[0] = True
        self.fails('EXPORT_CANCELLED', lambda: artifact.chunk(0))
        cancelled[0] = False
        with self.creation.store.transaction() as db:
            db.execute('UPDATE productions SET revision=revision+1 WHERE id=?', (self.current['id'],))
        self.fails('EXPORT_REVISION_CONFLICT', lambda: artifact.chunk(0))
        artifact.close()

    def test_missing_stale_duplicate_and_unsupported_selection(self):
        self.fails('EXPORT_SELECTED_TAKE_MISSING', lambda: self.export.prepare(ROOT, self.current, ['0' * 32]))
        self.fails('EXPORT_SELECTION_INVALID', lambda: self.export.prepare(ROOT, self.current, self.ids * 2))
        self.fails('EXPORT_SELECTION_INVALID', lambda: self.export.prepare(ROOT, self.current, []))
        for field, value, code in [('stale', True, 'EXPORT_SELECTION_STALE'),
            ('selected_take', None, 'EXPORT_SELECTED_TAKE_MISSING'), ('kind', 'Image', 'EXPORT_FORMAT_UNSUPPORTED')]:
            current = copy.deepcopy(self.current)
            current['assets'][0][field] = value
            self.fails(code, lambda: self.export.prepare(ROOT, current, self.ids))
        self.fails('EXPORT_MODE_UNSUPPORTED', lambda: self.prepare(mode='file'))
        self.fails('EXPORT_MODE_UNSUPPORTED', lambda: self.prepare(mode='convert'))

    def test_corrupt_and_missing_retained_files_are_not_regenerated(self):
        path = self.productions.assets.path('media', self.take['artifact'], '.wav')
        path.chmod(0o600)
        path.write_bytes(b'broken')
        self.fails('RETAINED_FILE_CORRUPT', self.prepare)
        path.unlink()
        self.fails('RETAINED_FILE_MISSING', self.prepare)

    def test_self_consistent_retrieval_must_match_selected_snapshot(self):
        with patch.object(self.productions.assets, 'retrieve', return_value=(wav(b'\x02\x00' * 100), self.take)):
            self.fails('EXPORT_INTEGRITY_FAILED', self.prepare)

    def test_size_bound_checked_before_retrieval_and_includes_zip_overhead(self):
        with patch('studio.production_export.service.LIMIT', len(self.data) * 2 - 1):
            with patch.object(self.productions.assets, 'retrieve', side_effect=AssertionError('not allowed')):
                self.fails('EXPORT_SIZE_UNSUPPORTED', self.prepare)
        with patch('studio.production_export.service.LIMIT', len(self.data) * 2):
            self.fails('EXPORT_SIZE_UNSUPPORTED', self.prepare)

    def test_offsets_and_multi_chunk_transport(self):
        self.data = wav(b'\x01\x00' * 30000)
        take = self.import_take()
        current = self.productions.link_take(ROOT, LinkTake(command=identity(), production=self.current['id'],
            expected=self.current['revision'], asset=self.ids[0], request=take['request'], take=take['id']))['current']
        self.current = self.productions.select_take(ROOT, LinkTake(command=identity(), production=current['id'],
            expected=current['revision'], asset=self.ids[0], request=take['request'], take=take['id']))['current']
        artifact = self.export.prepare(ROOT, self.current, self.ids[:1], mode='file')
        self.assertEqual(artifact.filename, '01-sound-effects-take-02.wav')
        self.assertEqual(collect(artifact), self.data)
        for offset in (-1, True, artifact.size, 1.2):
            self.fails('EXPORT_OFFSET_INVALID', lambda: artifact.chunk(offset))
        artifact.close()

    def test_mixed_import_formats_zip_and_original_file_bytes(self):
        media = []
        for format in ('png', 'jpeg', 'wav', 'mp4'):
            data, asset, receipt, _ = self.import_media(format)
            media.append((format, data, asset, receipt['take']))
        before = self.state()
        first, second = self.prepare(), self.export.prepare(ROOT, self.current, self.ids[::-1])
        payload = collect(first)
        self.assertEqual(payload, collect(second))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            for format, data, asset, take in media:
                position = self.ids.index(asset) + 1
                kind = {'png': 'image', 'jpeg': 'image', 'wav': 'sound-effects', 'mp4': 'video'}[format]
                filename = f'media/{position:02d}-{kind}-take-01.{format}'
                self.assertEqual(archive.read(filename), data)
                item = next(item for item in manifest['outputs'] if item['asset'] == asset)
                self.assertEqual(item['filename'], filename)
                self.assertEqual(item['take'], take)
                self.assertEqual(item['format'], format)
                self.assertEqual(item['sha256'], hashlib.sha256(data).hexdigest())
                self.assertNotIn('storage', item)
                self.assertEqual(item['lineage']['role'], 'retained-original')
                self.assertEqual(item['review_status'], 'Not reviewed')
                self.assertEqual(item['qa']['userApproval'], 'Not recorded')
                if format == 'mp4':
                    self.assertRegex(item['measured']['frame_rate'], r'^[1-9][0-9]*/[1-9][0-9]*$')
                    self.assertIsInstance(item['measured']['audio'], bool)
                    self.assertIn(item['measured']['codec'], ('h264', 'mpeg4'))
                if format != 'wav':
                    self.assertGreater(item['measured']['width'], 0)
        for format, data, asset, take in media:
            artifact = self.export.prepare(ROOT, self.current, [asset], mode='file')
            kind = {'png': 'image', 'jpeg': 'image', 'wav': 'sound-effects', 'mp4': 'video'}[format]
            self.assertEqual(artifact.filename, f'{self.ids.index(asset) + 1:02d}-{kind}-take-01.{format}')
            self.assertEqual(collect(artifact), data)
            artifact.close()
        self.assertNotIn(SENTINEL.encode(), payload)
        self.assertNotIn(str(self.home).encode(), payload)
        self.assertEqual(before, self.state())
        first.close()
        second.close()

    def test_import_scope_rechecked_before_read_after_read_and_on_chunks(self):
        _, _, receipt, imports = self.import_media()
        artifact = self.prepare()
        original = imports.assets.retrieve
        def revoke(take):
            result = original(take)
            if take == receipt['take']:
                with self.creation.store.transaction() as db:
                    db.execute('UPDATE media_import_scopes SET scope=? WHERE id=?', ('other-root', receipt['id']))
            return result
        with patch.object(imports.assets, 'retrieve', revoke):
            self.fails('MEDIA_SCOPE_DENIED', self.prepare)
        self.fails('MEDIA_SCOPE_DENIED', lambda: artifact.chunk(0))
        self.fails('MEDIA_SCOPE_DENIED', artifact.descriptor)
        with patch.object(imports.assets, 'retrieve', side_effect=AssertionError('must not read')):
            self.fails('MEDIA_SCOPE_DENIED', self.prepare)
        artifact.close()

    def test_import_route_missing_is_explicit_and_reads_nothing(self):
        self.import_media()
        self.export = ProductionExport(self.productions)
        with patch.object(self.productions.assets, 'retrieve', side_effect=AssertionError('must not read')):
            self.fails('EXPORT_IMPORT_UNAVAILABLE', self.prepare)

    def test_import_retrieval_integrity_kind_and_fact_whitelist(self):
        _, asset, receipt, _ = self.import_media()
        with self.creation.store.transaction() as db:
            row = self.creation.store.take(db, receipt['take'])
            facts = json.loads(row['facts'])
            facts.update(prompt=SENTINEL, private_path=SENTINEL, codec=SENTINEL, width=SENTINEL)
            db.execute('UPDATE takes SET facts=? WHERE id=?', (json.dumps(facts), receipt['take']))
        self.current = self.productions.read(ROOT, self.current['id'])['current']
        self.fails('EXPORT_INTEGRITY_FAILED', self.prepare)
        facts['width'] = 16
        with self.creation.store.transaction() as db:
            db.execute('UPDATE takes SET facts=? WHERE id=?', (json.dumps(facts), receipt['take']))
        self.current = self.productions.read(ROOT, self.current['id'])['current']
        artifact = self.prepare()
        self.assertNotIn(SENTINEL.encode(), collect(artifact))
        artifact.close()
        current = copy.deepcopy(self.current)
        next(item for item in current['assets'] if item['id'] == asset)['kind'] = 'Video'
        self.fails('EXPORT_FORMAT_UNSUPPORTED', lambda: self.export.prepare(ROOT, current, self.ids))

    def test_import_corruption_missing_and_no_conversion(self):
        data, _, receipt, imports = self.import_media()
        path = imports.path(receipt['id'], True)
        path.chmod(0o600)
        path.write_bytes(data + b'corrupt')
        self.fails('RETAINED_FILE_CORRUPT', self.prepare)
        path.unlink()
        self.fails('RETAINED_FILE_MISSING', self.prepare)

    def test_prepared_artifact_pins_snapshot_and_rechecks_request_authority(self):
        snapshot = copy.deepcopy(self.current)
        artifact = self.export.prepare(ROOT, snapshot, self.ids)
        payload = collect(artifact)
        snapshot['revision'] += 1
        snapshot['assets'].clear()
        self.assertEqual(collect(artifact), payload)
        with self.creation.store.transaction() as db:
            db.execute('UPDATE creation_commands SET root=? WHERE request=?', ('other-root', self.take['request']))
        with self.assertRaises(Fault):
            artifact.chunk(0)
        with self.assertRaises(Fault):
            artifact.descriptor()
        artifact.close()


if __name__ == '__main__':
    unittest.main()
