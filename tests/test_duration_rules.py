"""Requested seconds and actual-output boundaries; no provider calls."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from studio.domain import Fault
from studio.native.creation.hermes import validate_output_duration
from studio.native.creation.registration import Prepare, HermesPrepare, MusicPrepare, schema
from tests import test_collect_output as collection_tests
from tests.duration_fixtures import wav, encoded


class DurationRulesTests(unittest.TestCase):
    setUp = collection_tests.CollectOutputTests.setUp
    rpc = collection_tests.CollectOutputTests.rpc
    tool = collection_tests.CollectOutputTests.tool
    prepare = collection_tests.CollectOutputTests.prepare
    output = collection_tests.CollectOutputTests.output
    collect = collection_tests.CollectOutputTests.collect

    def test_prepare_video_default_boundaries_and_durable_seconds(self):
        row = self.prepare('Video')
        self.assertEqual(row['defaults']['seconds'], 5)
        self.assertEqual(self.rpc('status')['defaults']['seconds'], 5)
        for seconds in (1, 15):
            row = self.prepare('Video', seconds=seconds, parent=row['request'])
            self.assertEqual(row['defaults']['seconds'], seconds)
        for seconds in (0, 0.003825534018687904, 0.5, 1.5, 16, True, '5', float('inf'), float('nan')):
            result = self.tool('prepare', kind='Video', method='hermes_tool', method_id='fixture-method',
                               direction='Controlled', seconds=seconds)
            self.assertEqual(result['error'], 'INVALID_CREATION_INPUT', repr(seconds))

    def test_each_method_duration_contract(self):
        self.assertEqual(Prepare(direction='Controlled').seconds, 3)
        for value in (0.1, 10):
            self.assertEqual(Prepare(direction='Controlled', seconds=value).seconds, value)
        for value in (0, 10.1, True, '3', float('nan')):
            with self.assertRaises(ValueError):
                Prepare.model_validate(dict(direction='Controlled', seconds=value), strict=True)
        for kind, default in (('Voice', 5), ('Music', 30)):
            self.assertEqual(HermesPrepare(kind=kind, direction='Controlled', method_id='import').seconds, default)
            for value in (0.5, 47):
                self.assertEqual(HermesPrepare(kind=kind, direction='Controlled', method_id='import', seconds=value).seconds, value)
            for value in (0, 0.49, 48, True, '5', float('nan')):
                with self.assertRaises(ValueError):
                    HermesPrepare.model_validate(dict(kind=kind, direction='Controlled', method_id='import', seconds=value), strict=True)
        self.assertIsNone(HermesPrepare(kind='Image', direction='Controlled', method_id='import').seconds)
        with self.assertRaises(ValueError):
            HermesPrepare(kind='Image', direction='Controlled', method_id='import', seconds=5)
        # Existing legacy Music contract preserves unsupported intent without a run.
        from studio.native.creation.music import unsupported
        for value in (10, 30):
            self.assertIsNone(unsupported(MusicPrepare(kind='Music', schema_version=2, direction='Controlled', seconds=value)))
        self.assertEqual(unsupported(MusicPrepare(kind='Music', schema_version=2, direction='Controlled', seconds=60)),
                         'MUSIC_DURATION_ROUTE_UNQUALIFIED')
        self.assertIn('SECONDS', schema()['parameters']['properties']['seconds']['description'])

    def test_short_actual_voice_and_video_make_no_take(self):
        parent = None
        for kind, tool, directory, suffix, data in (
            ('Voice', 'text_to_speech', 'audio_cache', '.wav', wav(0.49)),
            ('Video', 'video_generate', 'video_cache', '.mp4', encoded('mp4', 0.1))):
            row = self.prepare(kind, **({'parent': parent} if parent else {}))
            parent = row['request']
            result = self.collect(row, self.output(directory, suffix, data), tool)
            self.assertEqual(result['error'], 'OUTPUT_DURATION_TOO_SHORT')
            self.assertEqual(self.rpc('status')['takes'], [])
            self.assertEqual(self.rpc('status')['submission_state'], 'awaiting_output')
        with self.runtime.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM takes').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM imports').fetchone()[0], 0)

    def test_zero_or_missing_decoded_video_frames_make_no_take(self):
        row = self.prepare('Video')
        data = encoded('mp4')
        path = self.output('video_cache', '.mp4', data)
        from studio.media_import import validation
        actual = validation.codec_call
        for count in ('0', 'N/A', None):
            def probe(tool, arguments, data):
                if '-count_frames' in arguments:
                    return json.dumps(dict(streams=[dict(nb_read_frames=count)])).encode()
                return actual(tool, arguments, data)
            with patch.object(validation, 'codec_call', side_effect=probe):
                self.assertEqual(self.collect(row, path, 'video_generate')['error'], 'OUTPUT_HAS_NO_FRAMES')
            self.assertEqual(self.rpc('status')['takes'], [])

    def test_output_floor_and_skill_contracts(self):
        validate_output_duration(wav(0.5), 'wav')
        validate_output_duration(encoded('mp4', 0.5), 'mp4')
        for name in ('quick-create', 'production', 'refine-take', 'core'):
            body = (Path('studio/native/skills') / name / 'SKILL.md').read_text()
            for text in ('SECONDS', '1–15', 'max 10', '0.1–10', '10–30', '0.5–47',
                         'video_generate(duration=5)', 'text_to_speech', 'NO duration parameter', 'instructions'):
                self.assertIn(text, body, (name, text))
