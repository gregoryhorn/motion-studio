"""Adverse Music native/receipt bridge, all bytes synthetic, no audio runtime imports."""
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from studio.domain import Fault, MAX_BYTES
from studio.persistence.primitives import canonical
from studio.producer.music.adapter import AceStep
from studio.producer.music.audio import pcm16
from studio.producer.music.bridge import upstream_json, normalize
from studio.producer.music import receipt
from studio.assets.audio_profiles import validate_audio
from tests.music_support import setup, settle, effect_count
from tests import music_support as MusicTests


def native(frames=480000, *, encoding=3, bits=32, sample=None):
    if sample is None:
        unit=struct.pack('<ffff',0.125,-0.125,-0.25,0.25) if encoding==3 else struct.pack('<hhhh',4096,-4096,-8192,8192)
    else:unit=sample
    align=2*bits//8
    pcm=(unit*((frames*align+len(unit)-1)//len(unit)))[:frames*align]
    fmt=struct.pack('<HHIIHH',encoding,2,48000,48000*align,align,bits)
    return b'RIFF'+struct.pack('<I',36+len(pcm))+b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(pcm))+pcm


class BridgeTests(unittest.TestCase):
    def test_stdout_noise_false_empty_multiple_malformed_ambiguity(self):
        good=dict(success=True,audio_paths=['not-accessed.wav'],elapsed_seconds=0.2,output_dir='not-accessed')
        raw=json.dumps(good).encode()
        self.assertEqual(upstream_json(b'Plain library noise\n'+raw+b'\n'),good)
        invalid=[b'',b'{}',raw+b'\n'+raw,b'{bad}\n'+raw,b'[]\n'+raw,
            json.dumps(good|dict(success=False)).encode(),json.dumps(good|dict(success=1)).encode(),
            json.dumps(good|dict(audio_paths=[])).encode(),json.dumps(good|dict(audio_paths=['a','b'])).encode(),
            json.dumps(good|dict(elapsed_seconds=float('nan'))).encode(),
            b'{"success":false,'+raw[1:],b'x'*65537,b'prefix '+raw+b'\n'+raw]
        for value in invalid:
            with self.subTest(value=value[:50]):
                with self.assertRaises(Fault):upstream_json(value)

    def test_float_and_integer_native_exact_derivative_and_profiles(self):
        float_data=native();integer_data=native(encoding=1,bits=16)
        derivative,facts=pcm16(float_data,480000)
        self.assertEqual(facts['bits'],32);self.assertEqual(derivative,integer_data)
        self.assertEqual(pcm16(integer_data,480000)[0],integer_data)
        self.assertEqual(validate_audio(derivative,'stereo-48000-pcm16',480000)['duration'],10)
        with self.assertRaises(Fault):validate_audio(derivative,'stereo-44100-pcm16',480000)
        # Native 24/32-bit PCM and 64-bit float are explicit supported encodings too.
        for encoding,bits,unit in ((1,24,b'\x00\x00\x10\x00\x00\xf0'),
                (1,32,struct.pack('<ii',268435456,-268435456)),(3,64,struct.pack('<dd',0.125,-0.125))):
            output,info=pcm16(native(encoding=encoding,bits=bits,sample=unit),480000)
            self.assertEqual(info['frames'],480000)
            self.assertEqual(validate_audio(output,'stereo-48000-pcm16',480000)['rate'],48000)

    def test_nonfinite_clipped_truncated_duplicate_and_byte_limits(self):
        for unit in (struct.pack('<f',float('nan')),struct.pack('<f',float('inf')),
                     struct.pack('<f',1),struct.pack('<f',-1),struct.pack('<f',0.9999999)):
            with self.assertRaises(Fault):pcm16(native(sample=unit),480000)
        for unit in (struct.pack('<h',32767),struct.pack('<h',-32768)):
            with self.assertRaises(Fault):pcm16(native(encoding=1,bits=16,sample=unit),480000)
        data=native()
        for bad in (data[:-1],data+b'x',data[:40],data+b'data',b'x'*(MAX_BYTES+1)):
            with self.assertRaises(Fault):pcm16(bad,480000)
        # Derivative limit independently enforced; native 16 MiB remains fixed.
        with patch('studio.producer.music.audio.MAX_BYTES',len(data)):
            self.assertEqual(len(pcm16(data,480000)[0]),len(native(encoding=1,bits=16)))
        with patch('studio.producer.music.audio.MAX_BYTES',100):
            with self.assertRaises(Fault):pcm16(data,480000)
        class Oversized(io.BytesIO):
            def getvalue(self):return b'x'*101
        with patch('studio.producer.music.audio.MAX_BYTES',100), patch('studio.producer.music.audio.io.BytesIO',Oversized):
            with self.assertRaises(Fault) as limited:pcm16(native(frames=1),1)
            self.assertEqual(limited.exception.code,'FILE_TOO_LARGE')

    def test_passive_source_pin_drift_symlink_and_changed_bytes(self):
        from studio.producer.music.pins import verify
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source.py';path.write_bytes(b'Harmless source fixture');path.chmod(0o600)
            pins={str(path):receipt.digest(path.read_bytes())};verify(pins)
            path.write_bytes(b'Changed harmless source fixture')
            with self.assertRaises(Fault):verify(pins)
            other=Path(temp)/'link';other.symlink_to(path)
            with self.assertRaises(Fault):verify({str(other):receipt.digest(path.read_bytes())})


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.ctx,self.runtime,self.path=setup(Path(self.temp.name))
        self.addCleanup(self.runtime.unload)

    def tool(self,operation,payload=None):
        return json.loads(self.ctx.tools['motion_studio_creation'][1](dict(operation=operation,**(payload or {})),
            session_id='physical',conversation_id='canonical-root'))

    def prepare(self):
        row=self.tool('prepare',dict(schema_version=2,kind='Music',direction='Synthetic bridge cue',seconds=10))
        self.assertNotIn('error',row);return row

    def test_harmless_child_rejects_false_success_and_unsafe_native(self):
        parent=None
        for mode in ('empty','multiple','extra-audio','symlink','escape','truncated','nonfinite','clipped',
                     'native-size','malformed','ambiguous','duplicate-json','exit-failure','inner-noise'):
            with self.subTest(mode=mode):
                (self.path.parent/'mode').write_text(mode)
                args=dict(schema_version=2,kind='Music',direction='Synthetic '+mode,seconds=10,parent=parent)
                row=self.tool('prepare',args);self.assertNotIn('error',row,row)
                self.tool('start',MusicTests.command(row));settle(self.runtime)
                result=self.tool('status');self.assertEqual(result['state'],'Failed',result)
                self.assertEqual(result['takes'],[])
                recovery=self.runtime.runs.recovery.get(row['request'])
                self.assertIsNone(recovery['recipe']);self.assertIsNone(recovery['successor'])
                parent=row['request']
        self.assertEqual(effect_count(self.runtime),14)

    def test_receipt_exact_identity_typed_seed_and_changed_native_derivative(self):
        row=self.prepare();self.tool('start',MusicTests.command(row));settle(self.runtime)
        self.assertEqual(self.tool('status')['state'],'Ready for review')
        record=self.runtime.runs.records.get(row['run']);plan=record['plan']
        output=self.runtime.store.home/'staging'/('sfx-'+row['run'])/'outputs/candidate.wav'
        data=output.read_bytes();raw=output.with_suffix('.wav.json').read_bytes()
        value=json.loads(raw);adapter=AceStep()
        self.assertIsNone(value['seed_effective']);self.assertEqual(value['seed_requested'],42)
        changes=[dict(seed_effective=42),dict(seed_requested=True),dict(seed_requested=43),dict(run='0'*32),
            dict(allocation_ino=value['allocation_ino']+1),dict(binding='0'*64),dict(extra=True),
            dict(derivative=value['derivative']|dict(rate=48000.0)),
            dict(native=value['native']|dict(channels=True)),dict(plan='0'*64)]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(Fault):adapter.validate_native_output(data,canonical(value|change).encode(),plan,output)
        with self.assertRaises(Fault):adapter.validate_native_output(data,b'{"schema_version":1,'+raw[1:],plan,output)
        with self.assertRaises(Fault):adapter.validate_native_output(data[:-1],raw,plan,output)
        original=output.with_name('native.wav');saved=original.read_bytes()
        original.write_bytes(saved[:-1])
        with self.assertRaises(Fault):adapter.validate_native_output(data,raw,plan,output)
        original.write_bytes(saved)
        self.assertEqual(adapter.validate_native_output(data,raw,plan,output),480000)

    def test_collection_interruption_changed_bytes_cannot_recover_or_regenerate(self):
        def damage():
            row=self.runtime.runs.records.rows()[-1]
            native_path=self.runtime.store.home/'staging'/('sfx-'+row['id'])/'outputs/native.wav'
            native_path.write_bytes(b'Synthetic changed output')
            raise RuntimeError('Synthetic lost collection')
        self.runtime.runs.collection.after_finalize=damage
        row=self.prepare();self.tool('start',MusicTests.command(row));settle(self.runtime)
        self.assertNotEqual(self.tool('status')['state'],'Ready for review')
        self.tool('start',MusicTests.command(row));settle(self.runtime)
        self.assertEqual(effect_count(self.runtime),1)
        self.assertEqual(self.tool('status')['takes'],[])

    def test_timeout_staging_capture_and_unknown_retirement_no_rearm(self):
        parent=None
        for mode,reason in (('sleep','TIMEOUT'),('staging','STAGING_LIMIT'),('outer-noise','CHILD_FAILED')):
            (self.path.parent/'mode').write_text(mode)
            self.runtime.runs.worker.deadline=0.3 if mode=='sleep' else 5
            self.runtime.runs.worker.grace=0.1
            row=self.tool('prepare',dict(schema_version=2,kind='Music',direction='Synthetic '+mode,seconds=10,parent=parent))
            self.tool('start',MusicTests.command(row));settle(self.runtime)
            result=self.tool('status');self.assertEqual(result['state'],'Failed',result)
            self.assertEqual(result['failure'],reason,result)
            self.tool('start',MusicTests.command(row));settle(self.runtime)
            self.assertEqual(result['takes'],[]);parent=row['request']
        self.assertEqual(effect_count(self.runtime),3)

    def test_unknown_retirement_no_replay(self):
        row=self.prepare()
        worker=self.runtime.runs.worker.execute
        def uncertain(*args,**kwargs):return dict(worker(*args,**kwargs),group_retired=False)
        with patch.object(self.runtime.runs.worker,'execute',side_effect=uncertain):
            self.tool('start',MusicTests.command(row));settle(self.runtime)
        self.assertEqual(self.tool('status')['state'],'Outcome unknown')
        self.tool('start',MusicTests.command(row));settle(self.runtime)
        self.assertEqual(effect_count(self.runtime),1)
        self.assertEqual(self.tool('status')['takes'],[])


    def test_completion_can_win_stop_after_verified_exit(self):
        row=self.prepare()
        self.runtime.runs.after_exit=lambda:self.runtime.runs.stop(row['run'])
        self.tool('start',MusicTests.command(row));settle(self.runtime)
        result=self.tool('status')
        self.assertEqual(result['state'],'Ready for review',result)
        self.assertTrue(result['stop_requested'])
        self.assertEqual(effect_count(self.runtime),1)


if __name__=='__main__':unittest.main()
