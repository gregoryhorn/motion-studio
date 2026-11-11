"""CF-B2 offline original-pair corruption, retention and crash recovery checks."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import wave
from studio.assets.retention import Assets
from studio.domain import Fault
from studio.persistence.store import Store
from studio.runs.service import LocalRuns
from studio.runs.owned_process import OwnedProcess
from tests.producer_support import fixture_binding, prepare, wait_run, effects


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binding = fixture_binding(self.root / 'tool')
        self.store = Store(self.root / 'var')
        self.runs = LocalRuns(self.store, self.binding, OwnedProcess(grace=0.1))

    def tearDown(self):
        self.runs.close()
        self.temp.cleanup()

    def uncollected(self):
        self.runs.after_exit = lambda: (_ for _ in ()).throw(SystemExit())
        item, _ = prepare(self.runs)
        self.runs.start(item['id'], lambda: True)
        row = wait_run(self.runs, item['id'], {'Collecting'})
        self.runs.threads[item['id']].join(3)
        self.assertTrue(row['process']['exited'])
        directory = self.store.home / 'staging' / ('sfx-' + item['id']) / 'outputs'
        return item, directory, directory / 'candidate.wav', directory / 'candidate.wav.json'

    def test_missing_partial_corrupt_mismatched_oversize_escape_duplicate_receipt(self):
        mismatch_fields = ('model', 'revision', 'prompt', 'negative_prompt', 'seconds', 'sample_rate', 'channels', 'steps')
        modes = ('missing', 'partial', 'mismatch', 'oversize', 'escaped', 'duplicate', 'nan', 'unknown', *mismatch_fields)
        for mode in modes:
            with self.subTest(mode=mode):
                item, directory, wav, receipt = self.uncollected()
                value = json.loads(receipt.read_text())
                if mode == 'missing':
                    receipt.unlink()
                elif mode == 'partial':
                    receipt.write_text('{')
                elif mode == 'mismatch':
                    value['seed'] += 1
                    receipt.write_text(json.dumps(value))
                elif mode == 'oversize':
                    receipt.write_bytes(b' ' * 16385)
                elif mode == 'escaped':
                    value['output'] = '/non-private-fixture-outside-allocation.wav'
                    receipt.write_text(json.dumps(value))
                elif mode == 'duplicate':
                    receipt.write_text(receipt.read_text().replace('{', '{"seed":1,', 1))
                elif mode == 'nan':
                    value['gain'] = float('nan')
                    receipt.write_text(json.dumps(value))
                elif mode in mismatch_fields:
                    value[mode] = 'mismatched-fixture' if isinstance(value[mode], str) else value[mode] + 1
                    receipt.write_text(json.dumps(value))
                else:
                    value['authority'] = 'caller-authored-success'
                    receipt.write_text(json.dumps(value))
                with self.assertRaises(Fault):
                    self.runs.collection.collect(item['id'])
                self.assertEqual(self.runs.records.get(item['id'])['status'], 'Collection blocked')
                self.assertEqual(len(self.store.snapshot()['takes']), 0)
                self.runs.start(item['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), len(modes))

    def test_symlink_hardlink_allocation_escape_wav_corruption_and_silence(self):
        modes = ('wav-symlink', 'receipt-symlink', 'hardlink', 'allocation-symlink',
                 'truncated', 'silence', 'wav-oversize', 'mono', 'rate', 'short')
        for mode in modes:
            with self.subTest(mode=mode):
                item, directory, wav, receipt = self.uncollected()
                if mode in ('wav-symlink', 'receipt-symlink', 'hardlink'):
                    target = receipt if mode == 'receipt-symlink' else wav
                    outside = self.root / ('outside-' + item['id'])
                    target.rename(outside)
                    if mode == 'hardlink':
                        os.link(outside, target)
                    else:
                        target.symlink_to(outside)
                elif mode == 'allocation-symlink':
                    outside = self.root / ('outside-' + item['id'])
                    directory.rename(outside)
                    directory.symlink_to(outside, target_is_directory=True)
                elif mode == 'truncated':
                    wav.write_bytes(wav.read_bytes()[:-1])
                elif mode == 'silence':
                    data = bytearray(wav.read_bytes())
                    data[44:] = b'\0' * (len(data) - 44)
                    wav.write_bytes(data)
                elif mode in ('mono', 'rate', 'short'):
                    with wave.open(str(wav), 'rb') as source:
                        pcm = source.readframes(source.getnframes())
                    if mode == 'mono':
                        pcm = b''.join(pcm[n:n+2] for n in range(0, len(pcm), 4))
                    elif mode == 'short':
                        pcm = pcm[:-4]
                    with wave.open(str(wav), 'wb') as target:
                        target.setparams((1 if mode == 'mono' else 2, 2, 48000 if mode == 'rate' else 44100,
                                          0, 'NONE', 'not compressed'))
                        target.writeframes(pcm)
                else:
                    wav.write_bytes(b'x' * (16 * 1024 * 1024 + 1))
                with self.assertRaises(Fault):
                    self.runs.collection.collect(item['id'])
                self.assertEqual(self.runs.records.get(item['id'])['status'], 'Collection blocked')
        self.assertEqual(self.store.snapshot()['takes'], [])
        self.assertEqual(len(effects(self.binding)), len(modes))

    def test_retained_before_metadata_crash_recovers_same_artifact_and_exact_bytes(self):
        self.runs.after_exit = lambda: None
        self.runs.collection.after_finalize = lambda: (_ for _ in ()).throw(SystemExit())
        item, model = prepare(self.runs)
        self.runs.start(item['id'], lambda: True)
        wait_run(self.runs, item['id'], {'Collecting'})
        self.runs.threads[item['id']].join(3)
        row = self.runs.records.get(item['id'])
        final = self.store.home / 'media' / (item['candidate'] + '.wav')
        self.assertTrue(final.exists())
        self.assertEqual(self.store.snapshot()['takes'], [])
        original = final.read_bytes()
        self.runs.close()
        self.runs = LocalRuns(Store(self.store.home), self.binding)
        self.assertEqual(self.runs.records.get(item['id'])['status'], 'Ready for review')
        self.assertEqual(self.runs.prepare(model), item)
        data, take = Assets(self.store).retrieve(item['candidate'])
        self.assertEqual(data, original)
        self.assertEqual(hashlib.sha256(data).hexdigest(), take['digest'])
        self.assertEqual(take['origin'], 'test_fixture')
        self.assertIsNone(self.store.snapshot()['requests'][0]['selected'])
        # Independent stdlib decoder checks actual PCM frames, not header alone.
        with wave.open(io.BytesIO(data), 'rb') as decoder:
            self.assertEqual(decoder.getparams()[:4], (2, 2, 44100, 4410))
            self.assertEqual(len(decoder.readframes(4410)), 17640)
        self.runs.start(item['id'], lambda: True)
        self.assertEqual(len(effects(self.binding)), 1)
        final.chmod(0o600)
        final.write_bytes(b'broken')
        with self.assertRaises(Fault):
            Assets(self.store).retrieve(item['candidate'])
        self.assertEqual(len(effects(self.binding)), 1)

    def test_child_exit_before_collection_recovery_and_private_pair_retained(self):
        item, directory, wav, receipt = self.uncollected()
        original = wav.read_bytes()
        self.runs.close()
        self.runs = LocalRuns(Store(self.store.home), self.binding)
        self.assertEqual(self.runs.records.get(item['id'])['status'], 'Ready for review')
        self.assertEqual(Assets(self.store).retrieve(item['candidate'])[0], original)
        self.assertTrue(receipt.exists())
        self.assertEqual([x.suffix for x in (self.store.home / 'media').iterdir()], ['.wav'])
        self.assertEqual(len(effects(self.binding)), 1)


if __name__ == '__main__':
    unittest.main()
