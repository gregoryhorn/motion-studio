import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from studio.assets.retention import Assets
from studio.assets.wav import inspect_wav
from studio.domain import Fault, SaveRequest, ImportIntent
from studio.persistence.store import Store, identity
from tests.fixtures import wav, intent_payload


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / 'var'
        self.store = Store(self.home)
        self.assets = Assets(self.store)
        self.request = self.store.save(SaveRequest(command=identity(), expected=0, text='Non-private fixture', kind='Sound effects'))
        self.data = wav()
        self.payload = intent_payload(self.request, self.data)
        self.intent = self.assets.intent(ImportIntent(**self.payload))

    def tearDown(self):
        self.temp.cleanup()

    def test_receiving_restart_same_identity_exact_bytes(self):
        self.assets = Assets(Store(self.home))
        state = self.store.snapshot()
        self.assertEqual(state['imports'][0]['status'], 'Interrupted')
        with self.assertRaisesRegex(Fault, 'IMPORT_BYTES_CONFLICT'):
            self.assets.upload(self.intent['id'], self.data[:-1])
        self.assets.upload(self.intent['id'], self.data)
        self.assertEqual(self.store.snapshot()['takes'][0]['id'], self.intent['take'])
        self.assertEqual(len(self.store.snapshot()['takes']), 1)

    def test_finalized_before_metadata_crash_reconciles_original_take(self):
        def crash():
            raise SystemExit('isolated crash failpoint')
        self.assets.after_finalize = crash
        with self.assertRaises(SystemExit):
            self.assets.upload(self.intent['id'], self.data)
        self.assertEqual(self.store.snapshot()['takes'], [])
        self.assertTrue((self.home / 'media' / (self.intent['id'] + '.wav')).exists())
        Assets(Store(self.home))
        state = self.store.snapshot()
        self.assertEqual(state['takes'][0]['id'], self.intent['take'])
        self.assertEqual(state['imports'][0]['status'], 'Ready for review')
        self.assertEqual(len(state['takes']), 1)
        Assets(Store(self.home))
        self.assertEqual(len(self.store.snapshot()['takes']), 1)

    def test_complete_staging_recovers_and_cancel_race_orders(self):
        complete = self.home / 'staging' / (self.intent['id'] + '.complete')
        complete.write_bytes(self.data)
        Assets(Store(self.home))
        self.assertEqual(self.assets.cancel(self.intent['id'])['status'], 'Ready for review')
        second = self.assets.intent(ImportIntent(**{**self.payload, 'command': identity()}))
        self.assertEqual(self.assets.cancel(second['id'])['status'], 'Cancelled')
        with self.assertRaisesRegex(Fault, 'IMPORT_CANCELLED'):
            self.assets.upload(second['id'], self.data)
        self.assertEqual(len(self.store.snapshot()['takes']), 1)

    def test_multiple_take_retention_and_changed_command_rejected(self):
        self.assets.upload(self.intent['id'], self.data)
        second = self.assets.intent(ImportIntent(**{**self.payload, 'command': identity()}))
        self.assets.upload(second['id'], self.data)
        self.assertNotEqual(self.intent['take'], second['take'])
        self.assertEqual(len(self.store.snapshot()['takes']), 2)
        with self.assertRaisesRegex(Fault, 'COMMAND_CONFLICT'):
            self.assets.intent(ImportIntent(**{**self.payload, 'name': 'changed.wav'}))

    def test_missing_corrupt_and_symlink_retained_media_denied(self):
        self.assets.upload(self.intent['id'], self.data)
        final = self.home / 'media' / (self.intent['id'] + '.wav')
        final.chmod(0o600)
        final.write_bytes(b'corrupt')
        with self.assertRaisesRegex(Fault, 'RETAINED_FILE_CORRUPT'):
            self.assets.retrieve(self.intent['take'])
        final.unlink()
        with self.assertRaisesRegex(Fault, 'RETAINED_FILE_MISSING'):
            self.assets.retrieve(self.intent['take'])
        outside = Path(self.temp.name) / 'original.wav'
        outside.write_bytes(self.data)
        final.symlink_to(outside)
        with self.assertRaisesRegex(Fault, 'RETAINED_FILE_MISSING'):
            self.assets.retrieve(self.intent['take'])
        self.assertEqual(outside.read_bytes(), self.data)

    def test_disk_refusal_finalize_not_exposed_ready(self):
        with patch('studio.assets.retention.sync_directory', side_effect=OSError('test disk refusal')):
            with self.assertRaises(OSError):
                self.assets.upload(self.intent['id'], self.data)
        self.assertEqual(self.store.snapshot()['takes'], [])
        # Complete durable-looking staged fixture can be checked under original identity.
        Assets(Store(self.home))
        self.assertEqual(self.store.snapshot()['takes'][0]['id'], self.intent['take'])


class WaveValidation(unittest.TestCase):
    def test_supported_formats_and_bounded_validation(self):
        for rate in (44100, 48000):
            for channels in (1, 2):
                facts = inspect_wav(wav(rate, channels))
                self.assertEqual(facts['rate'], rate)
                self.assertEqual(facts['channels'], channels)
        original = bytearray(wav())
        cases = [b'RF64' + bytes(original[4:]), bytes(original[:-1]), bytes(original) + b'x', b'x' * (16*1024*1024+1)]
        for offset, fmt, value in ((20, '<H', 3), (22, '<H', 3), (24, '<I', 22050), (34, '<H', 24), (32, '<H', 3)):
            damaged = bytearray(original)
            struct.pack_into(fmt, damaged, offset, value)
            cases.append(bytes(damaged))
        for data in cases:
            with self.assertRaises(Fault):
                inspect_wav(data)

    def test_harness_detects_wrong_expectation(self):
        # A representative known-wrong assertion must fail; do not alter production.
        with self.assertRaises(AssertionError):
            self.assertEqual(inspect_wav(wav())['channels'], 2)
        self.assertEqual(inspect_wav(wav())['channels'], 1)


if __name__ == '__main__':
    unittest.main()
