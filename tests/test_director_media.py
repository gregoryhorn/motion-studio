"""MA-r1 real CLI/adapter and Studio retention/export regressions (no installs)."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from studio.director.review import applicability, crystal_ball, reports
from studio.domain import SaveRequest
from studio.media_import import BeginImport, ImportChunk, ImportID, MediaImports, RetrieveTake
from studio.native.production.models import Brief, Create, LinkTake
from studio.persistence.primitives import identity
from studio.production_export import ProductionExport
from tests.director_media_support import AVAILABLE, still, audio, movie, source_checker, full
from tests.production_support import production_setup


class SummaryTests(unittest.TestCase):
    def test_fail_precedes_missing_decode_and_omissions_survive_pass(self):
        missing = dict(id='audio', status='SKIP', summary='Not checked: still image has no audio', skip_reason='not_applicable')
        result = applicability.summarize([dict(id='decode', status='FAIL'), missing], {}, None)
        self.assertEqual(result['status'], 'FAIL')
        result = applicability.summarize([dict(id='decode', status='PASS'), missing], {}, 'image')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['not_checked_details'][0]['summary'], missing['summary'])
        self.assertIn('no completed applicable decode', applicability.summarize([missing], {}, None)['reason'])

    def test_missing_binary_version_timeout_are_not_pass(self):
        with patch.object(crystal_ball.importlib.metadata, 'version', return_value=crystal_ball.VERSION), patch.object(crystal_ball.shutil, 'which', return_value=None):
            self.assertNotIn('status', crystal_ball.run(still(), '.png'))
        with patch.object(crystal_ball.importlib.metadata, 'version', return_value='old'):
            self.assertNotIn('status', crystal_ball.run(still(), '.png'))
        with patch.object(crystal_ball.importlib.metadata, 'version', return_value=crystal_ball.VERSION), patch('studio.director.process.call', side_effect=subprocess.TimeoutExpired('ffprobe', 30)):
            self.assertNotIn('status', crystal_ball.run(still(), '.png'))


@unittest.skipUnless(AVAILABLE, 'Sibling checker source and installed FFmpeg required; no install attempted')
class RealMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = [('png', 'Image', 'image', still()), ('wav', 'Voice', 'audio-only', audio()),
                     ('mp4', 'Video', 'video', movie(True)), ('mp4', 'Video', 'video-without-audio', movie(False))]

    def test_actual_bytes_routing_shapes_platform_and_corrupt_inputs(self):
        with source_checker() as calls:
            for suffix, _, kind, data in self.media:
                with self.subTest(kind=kind):
                    result = crystal_ball.run(data, '.'+suffix)
                    self.assertIn(result.get('status'), ('PASS', 'WARN'), result.get('reason'))
                    doc = full(result)
                    self.assertEqual(doc['media_kind'], kind)
                    self.assertEqual(doc['platform'], 'custom')
                    self.assertTrue(result['not_checked_details'])
                    self.assertTrue(all(item['summary'].startswith('Not checked: ') for item in result['not_checked_details']))
                    if kind == 'audio-only':
                        self.assertFalse({'review', 'ocr', 'vision', 'editing'} & doc['stages'].keys())
                        measured = {item['id'] for item in doc['checks'] if item['status'] != 'SKIP'}
                        self.assertTrue({'duration', 'silence', 'clipping', 'loudness measurement', 'true peak'} <= measured)
                        self.assertFalse({'aspect', 'fps', 'black', 'frozen', 'A/V drift'} & measured)
                    if kind == 'image':
                        self.assertNotIn('editing', doc['stages'])
                    if kind in ('image', 'video-without-audio'):
                        self.assertEqual(doc['stages']['audio']['checks'][0]['status'], 'SKIP')
            # Disguised bytes and stale video settings cannot select the video route.
            disguised = crystal_ball.run(still(), '.mp4', platform='youtube')
            self.assertEqual(full(disguised)['media_kind'], 'image')
            self.assertEqual(full(disguised)['platform'], 'custom')
            match = crystal_ball.run(still(), '.png', shape='1:1')
            mismatch = crystal_ball.run(still(), '.png', shape='9:16')
            self.assertEqual(next(c['status'] for c in full(match)['checks'] if c['id'] == 'aspect'), 'PASS')
            self.assertEqual(mismatch['status'], 'FAIL')
            platform = crystal_ball.run(self.media[2][3], '.mp4', platform='youtube')
            self.assertEqual(full(platform)['platform'], 'youtube')
            self.assertEqual(platform['status'], 'FAIL')
            for suffix in ('.png', '.wav', '.mp4'):
                self.assertEqual(crystal_ball.run(b'corrupt', suffix)['status'], 'FAIL')
            unsupported = crystal_ball.run(b'not media', '.bin')
            self.assertNotIn('status', unsupported)
            self.assertIn('no completed applicable decode', unsupported['reason'])
            silent = crystal_ball.run(audio(silent=True), '.wav')
            self.assertEqual(silent['status'], 'FAIL')
            clipped = crystal_ball.run(audio(clipped=True), '.wav')
            self.assertEqual(next(c['status'] for c in full(clipped)['checks'] if c['id'] == 'clipping'), 'FAIL')
        cli = [argv for argv in calls if 'crystal_ball' in argv]
        self.assertTrue(cli)
        self.assertTrue(all(argv[argv.index('--mode')+1] == 'quick' for argv in cli))

    def test_take_report_zip_restart_historical_options_and_originals(self):
        from studio.native.creation.runtime import MediaStore
        with tempfile.TemporaryDirectory(prefix='director-ma-integration-') as temporary, source_checker() as calls:
            ctx, creation, production, _ = production_setup(Path(temporary))
            self.addCleanup(creation.unload)
            service = creation.acquire()
            imports = MediaImports(service.store, service.authorize_request, assets=service.assets)
            for suffix, kind, media_kind, data in self.media:
                with self.subTest(media_kind=media_kind):
                    request = service.store.save(SaveRequest(command=identity(), expected=0, text='Controlled MA fixture', kind=kind))
                    with service.store.transaction() as db:
                        db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                            (request['id'], 'canonical-root', creation.policy.revision, identity(), json.dumps(dict(method='import')), None, 'Import only', 0))
                    intent = imports.begin('canonical-root', BeginImport(command=identity(), request=request['id'], revision=1,
                        digest=hashlib.sha256(data).hexdigest(), size=len(data), name='fixture.'+suffix, format=suffix))
                    for offset in range(0, len(data), 49152):
                        imports.chunk('canonical-root', ImportChunk(id=intent['id'], offset=offset, data=base64.b64encode(data[offset:offset+49152]).decode()))
                    imports.commit('canonical-root', ImportID(id=intent['id']))
                    payload = dict(request=request['id'], take=intent['take'])
                    rpc = lambda operation, value: ctx.methods['director.'+operation](value, session_id='canonical-root')
                    checked = rpc('status', payload)
                    self.assertIn(checked['status'], ('PASS', 'WARN'), checked)
                    self.assertEqual(checked['media_kind'], media_kind)
                    self.assertEqual(imports.retrieve('canonical-root', RetrieveTake(take=intent['take']))[0], data)
                    # Report open/status/restart are read-only; no new checker calls.
                    count = len(calls)
                    reopened = MediaStore(service.store.home)
                    with reopened.transaction() as db:
                        self.assertEqual(reports.status(db, reopened.take(db, intent['take'])), checked)
                    opened = rpc('report', dict(payload, report=checked['report']))
                    self.assertTrue(opened['current'])
                    asset = next(name for name in opened['assets'] if name.endswith('/full.json'))
                    doc = json.loads(base64.b64decode(rpc('report', dict(payload, report=checked['report'], asset=asset))['bytes']))
                    self.assertEqual(doc['media_kind'], media_kind)
                    prod = production.acquire()
                    current = prod.create('canonical-root', Create(command=identity(), title='MA fixture', brief=Brief(text='Controlled'), kinds=[kind]))['current']
                    asset_id = current['assets'][0]['id']
                    for action in (prod.link_take, prod.select_take):
                        current = action('canonical-root', LinkTake(command=identity(), production=current['id'], expected=current['revision'],
                            asset=asset_id, request=request['id'], take=intent['take']))['current']
                    export = ProductionExport(prod, media_imports=imports).prepare('canonical-root', current, [asset_id])
                    try:
                        archive = b''.join(base64.b64decode(export.chunk(offset)['bytes']) for offset in range(0, export.size, 49152))
                        with zipfile.ZipFile(io.BytesIO(archive)) as contents:
                            selected = json.loads(contents.read('manifest.json'))['outputs'][0]
                            self.assertEqual(contents.read(selected['filename']), data)
                            self.assertEqual(selected['crystal_ball'], checked)
                    finally:
                        export.close()
                    self.assertEqual(len(calls), count)
                    if media_kind == 'image':
                        updated = rpc('check', dict(payload, command=identity(), revision=1, shape='9:16', mode='full'))
                        self.assertEqual(updated['status'], 'FAIL')
                        self.assertNotEqual(updated['options'], checked['options'])
                        self.assertFalse(rpc('report', dict(payload, report=checked['report']))['current'])
                        self.assertEqual(rpc('report', dict(payload, report=checked['report']))['summary'], checked)
                        with service.store.transaction() as db:
                            row = service.store.take(db, intent['take'])
                            # Old constant-options report is historical, never reused.
                            db.execute('UPDATE director_reports SET options=? WHERE id=?', ('crystal-ball-core-v1/youtube/quick', updated['report']))
                            self.assertEqual(reports.status(db, row)['status'], 'Not checked')
                        self.assertEqual(imports.retrieve('canonical-root', RetrieveTake(take=intent['take']))[0], data)


if __name__ == '__main__':
    unittest.main()
