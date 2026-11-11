"""Synthetic Hermes-cache files only; no generator or paid provider calls."""
import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from studio.child_env import child_environment
from studio.domain import MAX_BYTES
from studio.media_import.service import MediaImports
from studio.media_import.contracts import BeginImport, ImportChunk, ImportID
from tests.creation_support import setup, effects
from tests.media_import_fixtures import png
from tests.duration_fixtures import wav, encoded


class CollectOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / '.hermes' / 'profile'
        self.home.mkdir(parents=True)
        self.environment = patch.dict(os.environ, HERMES_HOME=str(self.home))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.ctx, self.runtime, self.binding = setup(Path(self.temp.name))
        self.addCleanup(self.runtime.unload)
        self.rpc('admit')

    def rpc(self, operation, payload=None, root='root'):
        return self.ctx.methods['creation.' + operation](payload or {}, session_id=root)

    def tool(self, operation, **payload):
        handler = self.ctx.tools['motion_studio_creation'][1]
        return json.loads(handler(dict(operation=operation, **payload), session_id='physical', conversation_id='root'))

    def prepare(self, kind='Image', **kwargs):
        kwargs.setdefault('method_id', 'fixture-method')
        result = self.tool('prepare', kind=kind, method='hermes_tool', direction='Controlled fixture', **kwargs)
        self.assertNotIn('error', result)
        self.assertEqual(result['method'], 'hermes_tool')
        self.assertIsNone(result['run'])
        return result

    def output(self, directory, suffix, data):
        path = self.home / directory / ('output' + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def collect(self, row, path, tool='image_generate', root='root'):
        return self.rpc('collect_output', dict(request=row['request'], submission=row['submission'], attempt=row['attempt'],
            conversion_ok=True, path=str(path), tool=tool), root)

    def test_durable_submission_reconciliation_and_abandonment(self):
        from studio.native.creation.service import Creations
        self.assertEqual(self.rpc('status')['submission_state'], 'not_started')
        row = self.prepare(method_id='openai-codex')
        self.assertEqual(row['submission_state'], 'awaiting_output')
        self.assertEqual(row['method_id'], 'openai-codex')
        self.runtime.service = Creations(self.runtime, self.runtime.store, self.runtime.runs)
        self.assertEqual(self.rpc('status')['submission'], row['submission'])
        same = self.prepare(method_id='openai-codex')
        self.assertEqual(same['attempt'], row['attempt'])
        path = self.output('image_cache', '.png', png())
        bad = self.rpc('collect_output', dict(request=row['request'], submission='0'*32,
            attempt=row['attempt'], path=str(path), tool='image_generate'))
        self.assertEqual(bad['error'], 'HERMES_SUBMISSION_MISMATCH')
        collected = self.collect(row, path)
        self.assertEqual(self.rpc('status')['submission_state'], 'collected')
        self.assertEqual(self.collect(row, path), collected)
        descriptor = self.rpc('status')['takes'][0]['descriptor']
        self.assertEqual(descriptor['mime'], 'image/png')
        self.assertEqual(descriptor['qa']['useEligibility'], 'Not assessed')
        pending = self.prepare(parent=row['request'])
        self.prepare('Voice', parent=pending['request'])
        self.assertEqual(self.rpc('status', dict(request=pending['request']))['submission_state'], 'abandoned')
        self.assertEqual(self.collect(pending, path)['error'], 'HERMES_SUBMISSION_ABANDONED')
        self.assertEqual(effects(self.binding), [])

    def test_compressed_voice_requires_consent_before_conversion(self):
        row = self.prepare('Voice')
        path = self.output('audio_cache', '.mp3', b'controlled placeholder')
        with patch('studio.native.creation.hermes.speech_wav', side_effect=AssertionError('No conversion')):
            result = self.rpc('collect_output', dict(request=row['request'], submission=row['submission'],
                attempt=row['attempt'], path=str(path), tool='text_to_speech'))
        self.assertEqual(result['error'], 'VOICE_CONVERSION_APPROVAL_REQUIRED')

    def test_image_voice_video_happy_path_review_selection_and_retrieval(self):
        for kind, tool, directory, suffix, data in (
            ('Image', 'image_generate', 'cache/generated/images', '.png', png()),
            ('Image', 'image_generate', 'image_cache', '.jpg', encoded('jpeg')),
            ('Voice', 'text_to_speech', 'audio_cache', '.wav', wav()),
            ('Video', 'video_generate', 'cache/generated/videos', '.mp4', encoded('mp4')),
        ):
            with self.subTest(kind=kind, suffix=suffix):
                parent = self.rpc('status').get('request')
                row = self.prepare(kind, **({'parent': parent} if parent else {}))
                data_path = self.output(directory, suffix, data)
                result = self.collect(row, data_path, tool)
                self.assertNotIn('error', result)
                self.assertEqual(result['status'], 'Ready for review')
                retained, take = self.runtime.service.assets.retrieve(result['take'])
                self.assertEqual(retained, data)
                self.assertEqual(take['origin'], 'hermes_tool:' + tool)
                status = self.rpc('status', {'request': row['request']})
                self.assertEqual(status['takes'][0]['id'], result['take'])
                self.assertEqual(status['state'], 'Ready for review')
                self.assertNotIn('error', self.rpc('review', dict(request=row['request'], take=result['take'], command=hashlib.md5(b'review'+kind.encode()+suffix.encode()).hexdigest(), outcome='Matches request')))
                self.assertNotIn('error', self.rpc('select', dict(request=row['request'], take=result['take'], command=hashlib.md5(kind.encode()+suffix.encode()).hexdigest(), revision=row['revision'])))
                self.assertEqual(self.collect(row, data_path, tool)['take'], result['take'])
        self.assertEqual(effects(self.binding), [])

    def test_same_bytes_idempotent_across_paths(self):
        row = self.prepare()
        path = self.output('cache/generated/images', '.png', png())
        first = self.collect(row, path)
        second = self.tool('collect_output', request=row['request'], submission=row['submission'],
            attempt=row['attempt'], conversion_ok=True, path=str(path), tool='image_generate')
        self.assertEqual(first, second)
        alternate = path.with_name('other.png')
        alternate.write_bytes(path.read_bytes())
        self.assertEqual(first, self.collect(row, alternate))
        with self.runtime.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM takes').fetchone()[0], 1)

    def test_path_confinement_secrets_symlinks_and_hardlinks(self):
        row = self.prepare()
        outside = Path(self.temp.name) / 'outside.png'
        outside.write_bytes(png())
        inside = self.output('cache/generated/images', '.png', png())
        link = inside.with_name('link.png')
        link.symlink_to(outside)
        hardlink = inside.with_name('hard.png')
        os.link(outside, hardlink)
        directory = inside.parent / 'redirect'
        directory.symlink_to(outside.parent, target_is_directory=True)
        for path in (outside, link, hardlink, directory / outside.name, inside.parent / '..' / 'images' / inside.name,
                     Path('relative.png'), self.home / 'auth.json', self.home / '.env', Path.home() / '.ssh/id_rsa'):
            with self.subTest(case=path.name):
                self.assertEqual(self.collect(row, path)['error'], 'HERMES_OUTPUT_PATH_DENIED')
        for name in ('auth.json', '.env', 'config.yaml', 'credentials.json'):
            secret = inside.with_name(name)
            secret.write_bytes(png())
            self.assertEqual(self.collect(row, secret)['error'], 'HERMES_OUTPUT_PATH_DENIED')
        # Even a configured cache root cannot redirect to another profile.
        redirected = self.home / 'image_cache'
        redirected.symlink_to(outside.parent, target_is_directory=True)
        self.assertEqual(self.collect(row, redirected / outside.name)['error'], 'HERMES_OUTPUT_PATH_DENIED')

    def test_kind_scope_validation_and_size(self):
        row = self.prepare()
        path = self.output('cache/generated/images', '.wav', wav())
        self.assertEqual(self.collect(row, path)['error'], 'MEDIA_KIND_MISMATCH')
        self.assertEqual(self.collect(row, path, 'text_to_speech')['error'], 'MEDIA_KIND_MISMATCH')
        self.assertIn('error', self.collect(row, path, root='foreign'))
        self.rpc('admit', root='foreign')
        self.assertEqual(self.collect(row, path, root='foreign')['error'], 'CREATION_SCOPE_DENIED')
        path.write_bytes(b'not media')
        self.assertIn('error', self.collect(row, path))
        with path.open('wb') as target:
            target.truncate(MAX_BYTES + 1)
        self.assertEqual(self.collect(row, path)['error'], 'FILE_TOO_LARGE')
        self.runtime.policy = replace(self.runtime.policy, revision='revoked')
        self.assertIn('error', self.collect(row, path))

    def test_external_request_never_launches_plugin_engine(self):
        row = self.prepare('Video')
        self.assertEqual(self.rpc('start', dict(request=row['request'], revision=1, command=row['command'], run='a'*32))['error'], 'HERMES_TOOL_GENERATION_EXTERNAL')
        with self.runtime.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM local_runs').fetchone()[0], 0)
        self.assertEqual(effects(self.binding), [])

    def test_music_saved_import_only_without_live_music_scope(self):
        row = self.prepare('Music')
        self.assertEqual(self.rpc('status', {'request': row['request']})['kind'], 'Music')
        imports = MediaImports(self.runtime.store, self.runtime.service.authorize_request)
        data = wav()
        receipt = imports.begin('root', BeginImport(command='b'*32, request=row['request'], revision=1,
            digest=hashlib.sha256(data).hexdigest(), size=len(data), name='Controlled.wav', format='wav'))
        imports.chunk('root', ImportChunk(id=receipt['id'], offset=0, data=base64.b64encode(data).decode()))
        self.assertEqual(imports.commit('root', ImportID(id=receipt['id']))['status'], 'Ready for review')
        self.assertEqual(effects(self.binding), [])

    def test_reload_idempotency_and_invalid_image_content(self):
        from studio.native.creation.service import Creations
        row = self.prepare()
        path = self.output('cache/generated/images', '.png', png())
        first = self.collect(row, path)
        self.runtime.service = Creations(self.runtime, self.runtime.store, self.runtime.runs)
        self.assertEqual(first, self.collect(row, path))
        path.write_bytes(b'not an image')
        self.assertEqual(self.collect(row, path)['error'], 'HERMES_OUTPUT_CONFLICT')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.collect(row, path)['error'], 'HERMES_OUTPUT_ROOT_UNAVAILABLE')

    def test_collected_kinds_link_select_and_export_through_production(self):
        from studio.native.production.policy import ProductionAssociation
        from studio.native.production.registration import register
        from studio.persistence.primitives import identity
        runtime = register(self.ctx, self.runtime, association=ProductionAssociation(
            profile=self.ctx.profile_name, revision='production-fixture', production_management=True,
            direction_audio=True, canonical_roots=True))
        self.addCleanup(self.ctx.callbacks[-1])
        def production(operation, **payload):
            result = self.ctx.methods['production.' + operation](payload, session_id='root')
            self.assertNotIn('error', result, result)
            return result
        production('admit')
        parent = None
        for kind, tool, directory, suffix, data in (
            ('Image', 'image_generate', 'cache/generated/images', '.png', png()),
            ('Voice', 'text_to_speech', 'cache/audio', '.wav', wav()),
            ('Video', 'video_generate', 'cache/generated/videos', '.mp4', encoded('mp4')),
        ):
            with self.subTest(kind=kind):
                row = self.prepare(kind, **({'parent': parent} if parent else {}))
                parent = row['request']
                collected = self.collect(row, self.output(directory, suffix, data), tool)
                self.assertNotIn('error', collected)
                current = production('create', command=identity(), kinds=[kind])['current']
                for operation in ('link_take', 'select_take'):
                    current = production(operation, command=identity(), production=current['id'],
                        expected=current['revision'], asset=current['assets'][0]['id'],
                        request=row['request'], take=collected['take'])['current']
                descriptor = production('media_import.describe', take=collected['take'])
                self.assertEqual(descriptor['kind'], kind)
                prepared = production('export.prepare', production=current['id'],
                    expected=current['revision'], assets=[current['assets'][0]['id']], mode='file')
                chunk = production('export.chunk', take=prepared['take'], offset=0)
                self.assertEqual(base64.b64decode(chunk['bytes']), data)
                production('export.close', take=prepared['take'])

    def test_speech_mp3_ogg_conversion_uses_installed_helper(self):
        for suffix, format in (('.mp3', 'mp3'), ('.ogg', 'ogg')):
            with self.subTest(format=format):
                parent = self.rpc('status').get('request')
                row = self.prepare('Voice', **({'parent': parent} if parent else {}))
                result = subprocess.run([shutil.which('ffmpeg'), '-hide_banner', '-v', 'error',
                    '-f', 'wav', '-i', 'pipe:0', '-f', format, 'pipe:1'], input=wav(0.6),
                    capture_output=True, check=True, timeout=10, env=child_environment('helper'))
                path = self.output('cache/audio', suffix, result.stdout)
                collected = self.collect(row, path, 'text_to_speech')
                self.assertNotIn('error', collected)
                self.assertTrue(collected['converted_to_wav'])
                data, take = self.runtime.service.assets.retrieve(collected['take'])
                facts = json.loads(take['facts'])
                self.assertEqual(facts['voice_lineage']['native']['sha256'], hashlib.sha256(result.stdout).hexdigest())
                retained_source = self.runtime.service.assets.path('media', take['artifact'], '.voice-source')
                self.assertEqual(retained_source.read_bytes(), result.stdout)
                from studio.production_export.manifest import lineage
                projected = lineage(facts)
                self.assertEqual(projected['role'], 'retained-derivative')
                self.assertEqual(projected['native']['format'], format)
                self.assertEqual(projected['derivative']['rate'], 44100)
                self.assertEqual(data[:4], b'RIFF')
                self.assertEqual(path.read_bytes(), result.stdout)
                self.assertEqual(collected, self.collect(row, path, 'text_to_speech'))


if __name__ == '__main__':
    unittest.main()
