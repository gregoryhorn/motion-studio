"""Bounded actual decode evidence; only an explicitly owned runner may spawn.

Call validate(payload, port, run_process=worker.run) while the attempt is live.
The JobStore-compatible __call__(payload, port) only retrieves exact cached
proof, never starts an unowned subprocess. No import/constructor side effects.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import threading
from typing import Any, Callable

from ..contracts import ContractError, digest
from .limits import MAX_WIDTH, MAX_HEIGHT, MAX_FRAMES, output_byte_limit


def _spoken_audio_receipt(audio, pcm, duration):
    """Distinguish MP4 presentation samples from AAC decoder frame padding.

    No trimming/resampling is performed. ALAC must remain sample-exact; AAC's
    fully decoded suffix is measured, bounded to less than one 1024-sample LC
    frame, and never claimed to be part of the source-domain timeline.
    """
    import io
    from .stream_evidence import pcm_facts
    from fractions import Fraction
    try:
        rate=int(audio['sample_rate']); codec=audio['codec_name']
        channels = audio['channels']
        if channels not in (1, 2) or not 0<rate<=48000 or codec not in ('alac','aac'):
            raise ValueError('Only bounded mono/stereo ALAC/AAC audio supported.')
        if codec=='aac' and (audio.get('profile')!='LC' or rate not in
                (7350,8000,11025,12000,16000,22050,24000,32000,44100,48000)):
            raise ValueError('Only explicit-rate AAC LC supported.')
        duration=Fraction(duration); expected=duration*rate
        if (expected.denominator!=1 or expected<=0 or duration>3600 or
                Fraction(audio['duration_ts'])*Fraction(audio['time_base'])!=duration or
                int(audio['start_pts'])!=0):
            raise ValueError('Audio presentation timing differs from exact video frames.')
        observed = pcm_facts(io.BytesIO(pcm) if isinstance(pcm, bytes) else pcm, channels)
        actual=int(observed['decoded_samples']); padding=actual-int(expected)
        if (padding!=0 if codec=='alac' else not 0<=padding<1024):
            raise ValueError('Decoded audio sample count outside exact/lossy frame bound.')
        return dict(audio_codec=codec,**observed,presentation_samples=int(expected),
            decoder_padding_samples=padding,sample_rate_hz=rate,channels=channels,
            )
    except (ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
        raise ContractError('OUTPUT_INVALID','Local spoken audio probe/decode failed: '+str(exc)) from exc


class LocalOutputProbe:
    def __init__(self):
        self.receipts = {}
        self._proofs = {}
        self._lock = threading.Lock()

    def validate_acquired_mp4(self, payload, port, *, max_duration_seconds, run_process: Callable[..., Any]):
        """Source acquisition evidence, not baseline render/delivery conformance.

        Kept separate so broader source rates/stereo do not relax final encodes.
        Decode only the bounded in-memory MOV/MP4; external protocols forbidden.
        """
        from fractions import Fraction
        import uuid
        if (not callable(run_process) or port != dict(port='media', kind='media', media_type='video/mp4')
                or not isinstance(payload, bytes) or not 0 < len(payload) <= 16777216):
            raise ContractError('OUTPUT_INVALID', 'Invalid bounded acquisition media/runner')
        flags = ['-protocol_whitelist', 'pipe', '-format_whitelist', 'mov',
                 '-max_alloc', '67108864', '-probesize', '16777216', '-analyzeduration', '10000000']
        def run(argv):
            return run_process(argv, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        try:
            facts = json.loads(run(['ffprobe', '-v', 'error', *flags,
                                   '-show_streams', '-show_format', '-of', 'json', 'pipe:0']))
            streams = facts.get('streams', [])
            videos = [s for s in streams if s.get('codec_type') == 'video']
            audios = [s for s in streams if s.get('codec_type') == 'audio']
            duration = Fraction(facts['format']['duration'])
            if not 0 < duration <= max_duration_seconds or len(videos) != 1 or len(audios) > 1 or len(streams) != len(videos)+len(audios):
                raise ValueError('Acquisition duration/stream layout exceeds bound')
            video = videos[0]
            rate = Fraction(video['avg_frame_rate'])
            if not (0 < video['width'] <= 1920 and 0 < video['height'] <= 1080 and 0 < rate <= 60):
                raise ValueError('Acquisition video exceeds 1080p/60fps bound')
            if video.get('codec_name') not in ('h264', 'mpeg4', 'av1', 'vp9'):
                raise ValueError('Unsupported acquisition video codec')
            if audios and (audios[0].get('codec_name') not in ('aac', 'mp3', 'alac')
                           or not 0 < audios[0].get('channels', 0) <= 2
                           or not 0 < int(audios[0].get('sample_rate', 0)) <= 48000):
                raise ValueError('Acquisition audio exceeds codec/stereo/48kHz bound')
            decoded = run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', *flags,
                           '-threads', '1', '-i', 'pipe:0', '-map', '0', '-f', 'framemd5', '-'])
            rows = [line for line in decoded.splitlines() if line and not line.startswith(b'#')]
            frames = sum(1 for row in rows if int(row.split(b',', 1)[0]) == video['index'])
            if not 0 < frames <= max_duration_seconds*60 or len(decoded) > 2097152:
                raise ValueError('Acquisition decoded frame count/receipt exceeds bound')
        except (KeyError, ValueError, subprocess.SubprocessError, ZeroDivisionError) as exc:
            raise ContractError('OUTPUT_INVALID', 'Acquisition source probe/decode failed: ' + str(exc)) from exc
        key = self._key(payload, port)
        receipt = dict(schema='motion/v1/local-output-probe-evidence', sha256=key[0],
            kind=key[1], media_type=key[2], size_bytes=len(payload), probe=facts,
            decoded_frames=frames, decode_sha256='sha256:' + hashlib.sha256(decoded).hexdigest(),
            authority='owned source acquisition decode; not delivery conformance or human acceptance')
        rid = 'rcp_' + str(uuid.uuid5(uuid.NAMESPACE_URL, digest(receipt)))
        with self._lock:
            self.receipts[rid] = receipt
            self._proofs[key] = rid
        return rid

    @staticmethod
    def _key(payload, port):
        return ('sha256:' + hashlib.sha256(payload).hexdigest(), port['kind'], port['media_type'])

    def validate(self, payload, port, *, run_process):
        return self._validate(payload, port, run_process=run_process)

    def validate_file(self, path, port, *, run_process):
        """Decode an owned file without a gigabyte-sized Python byte copy.

        The existing bytes API remains bounded; only FFV1 Matroska can use the
        larger file-backed allowance. Exact-byte proofs are cached as before.
        """
        import os
        from .limits import output_payload
        if not callable(run_process):
            raise ContractError('PERMISSION_DENIED', 'Media validation requires an owned process runner.')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        pending = LocalOutputProbe()
        with os.fdopen(fd, 'rb') as source, output_payload(source, port) as observed:
            rid = pending._validate(observed.data, port, run_process=run_process,
                                    file_backed=True, input_path=observed.input_path)
        # Only publish proofs after the source's final identity check succeeds.
        with self._lock:
            self.receipts.update(pending.receipts)
            self._proofs.update(pending._proofs)
        return rid

    def _validate(self, payload, port, *, run_process: Callable[..., Any], file_backed=False, input_path=None):
        import mmap
        from .limits import output_file_limit
        if not callable(run_process):
            raise ContractError('PERMISSION_DENIED', 'Media validation requires an owned process runner.')
        limit = output_file_limit(port) if file_backed else output_byte_limit(port)
        if not isinstance(payload, (bytes, mmap.mmap) if file_backed else bytes) or not 0 < len(payload) <= limit:
            raise ContractError('OUTPUT_INVALID', 'Media exceeds bounded local validator input.')
        if port['kind'] == 'archive' and port['media_type'] == 'application/zip':
            import io, zipfile, uuid
            from ..packaging import _paths, _json, _closure_check, RESERVED, _schema_snapshots
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    infos = archive.infolist()
                    if len(infos) > 1000 + len(RESERVED):
                        raise ContractError('OUTPUT_INVALID', 'Package member bound exceeded.')
                    _paths([i.filename for i in infos])
                    if any(i.file_size > output_byte_limit(port) or i.compress_type != zipfile.ZIP_STORED or i.flag_bits & 1 or i.is_dir() for i in infos):
                        raise ContractError('OUTPUT_INVALID', 'Only bounded unencrypted stored files are supported.')
                    manifest = _json(archive.read('manifest.json')); closure = _json(archive.read('closure.json'))
                    _, metadata, _ = _closure_check(manifest, closure)
                    if set(archive.namelist()) != RESERVED | {m['path'] for m in manifest['members']}:
                        raise ContractError('OUTPUT_INVALID', 'Package member set differs.')
                    for name, value in _schema_snapshots().items():
                        if archive.read(name) != value:
                            raise ContractError('HASH_MISMATCH', 'Package schema differs.')
                    for member in manifest['members']:
                        pin=member['artifact']; item=metadata[pin['artifact_id']]
                        kind='archive' if item['media_type']=='application/zip' else 'media'
                        if item['size_bytes']>output_byte_limit(dict(kind=kind,media_type=item['media_type'])):
                            raise ContractError('OUTPUT_INVALID','Typed package member byte bound exceeded.')
                        data = archive.read(member['path'])
                        if 'sha256:' + hashlib.sha256(data).hexdigest() != pin['sha256'] or len(data) != metadata[pin['artifact_id']]['size_bytes']:
                            raise ContractError('HASH_MISMATCH', 'Package member bytes differ.')
            except (KeyError, ValueError, zipfile.BadZipFile) as exc:
                raise ContractError('OUTPUT_INVALID', 'Unreadable safe ZIP package.') from exc
            key = self._key(payload, port)
            receipt = dict(schema='motion/v1/local-output-probe-evidence', sha256=key[0],
                kind=key[1], media_type=key[2], size_bytes=len(payload), closure_verified=True,
                reconstruction='not_tested', authority='owned worker exact ZIP closure; not reconstruction')
            rid = 'rcp_' + str(uuid.uuid5(uuid.NAMESPACE_URL, digest(receipt)))
            with self._lock:
                self.receipts[rid] = receipt; self._proofs[key] = rid
            return rid
        if port['kind'] == 'caption' and port['media_type'] == 'text/plain':
            import re, uuid
            try:
                text = bytes(payload).decode('utf-8')
                if '\x00' in text or (text and '-->' not in text and text.strip() != 'WEBVTT'):
                    raise ValueError('Unsupported caption text')
                if any(len(line) > 16384 for line in text.splitlines()):
                    raise ValueError('Caption line bound exceeded')
            except (UnicodeDecodeError, ValueError) as exc:
                raise ContractError('OUTPUT_INVALID', 'Invalid UTF-8 caption output.') from exc
            key = self._key(payload, port)
            receipt = dict(schema='motion/v1/local-output-probe-evidence', sha256=key[0], kind=key[1], media_type=key[2],
                size_bytes=len(payload), encoding='UTF-8', authority='owned canonical caption export; no audition asserted')
            rid = 'rcp_' + str(uuid.uuid5(uuid.NAMESPACE_URL, digest(receipt)))
            with self._lock:
                self.receipts[rid] = receipt; self._proofs[key] = rid
            return rid
        if port['media_type'] == 'audio/wav':
            return self._validate_wav(payload, port, run_process=run_process, input_path=input_path)
        if port['media_type'] not in ('video/mp4', 'video/x-matroska', 'image/png', 'video/quicktime'):
            raise ContractError('UNSUPPORTED_FEATURE', 'No actual decoder for this output type.')
        def run(args):
            if input_path is not None:
                args = [input_path if arg == 'pipe:0' else arg for arg in args]
            return run_process(args, input=None if input_path else payload, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=7200 if file_backed else 300, check=True).stdout
        try:
            facts = json.loads(run(['ffprobe', '-v', 'error', '-count_frames',
                '-show_streams', '-show_format', '-of', 'json', 'pipe:0']))
            streams = facts.get('streams', [])
            audio = None
            if len(streams) == 2 and port['media_type'] == 'video/mp4':
                audio = streams[1]
                if (streams[0].get('codec_type') != 'video' or streams[0].get('codec_name')!='h264'
                        or streams[0].get('pix_fmt')!='yuv420p' or audio.get('codec_type') != 'audio'
                        or audio.get('codec_name') not in ('alac','aac') or audio.get('channels') not in (1, 2)
                        or not 0 < int(audio.get('sample_rate', 0)) <= 48000):
                    raise ValueError('Only bounded H.264/mono-stereo ALAC or AAC MP4 layout supported.')
            elif len(streams) != 1 or streams[0].get('codec_type') != 'video':
                raise ValueError('Exactly one video stream, optionally bounded ALAC speech, required.')
            stream = streams[0]
            if not file_backed and len(payload) > 16777216 and stream.get('codec_name') != 'ffv1':
                raise ValueError('Expanded intermediate byte bound requires lossless FFV1.')
            if not (0 < stream['width'] <= MAX_WIDTH and 0 < stream['height'] <= MAX_HEIGHT):
                raise ValueError('Output canvas exceeds local baseline bounds.')
            count = int(stream['nb_read_frames'])
            if not 0 < count <= MAX_FRAMES:
                raise ValueError('Output frame count exceeds local baseline bounds.')
            if port['media_type'] == 'video/quicktime':
                from fractions import Fraction
                rate = Fraction(stream['avg_frame_rate'])
                if (port['kind'] != 'media' or (stream.get('codec_name'),stream.get('pix_fmt')) not in (
                        ('png','rgb24'), ('prores','yuva444p10le'), ('prores','yuva444p12le')) or not 0 < rate <= 120
                        or Fraction(stream['r_frame_rate']) != rate or int(stream['start_pts']) != 0
                        or Fraction(stream['duration_ts'])*Fraction(stream['time_base']) != count/rate):
                    raise ValueError('MOV differs from bounded zero-origin RGB frame conform.')
            elif port['media_type'] != 'image/png':
                from .rates import bounds, observed
                bounds(stream['width'], stream['height'], count, observed(stream))
            decoded = run(['ffmpeg', '-v', 'error', '-xerror', '-i', 'pipe:0',
                '-map', '0:v:0', '-an', '-f', 'framemd5', '-'])
            actual = sum(1 for line in decoded.splitlines() if line and not line.startswith(b'#'))
            if actual != count:
                raise ValueError('Probe frame count differs from actual full decode.')
            audio_evidence = {}
            if port['media_type'] == 'video/x-matroska':
                from .rates import timestamp_evidence
                audio_evidence['rate_observation'] = timestamp_evidence(stream,actual,run)
            if stream.get('codec_name') == 'prores':
                from types import SimpleNamespace
                from .mastering import alpha_statistics
                def alpha_run(args, **kwargs):
                    args = [input_path if input_path and arg == 'pipe:0' else arg for arg in args]
                    return run_process(args, input=None if input_path else payload, timeout=7200, **kwargs)
                alpha = alpha_statistics(SimpleNamespace(run=alpha_run), 'pipe:0')
                if alpha['decoded_alpha_frames'] != actual:
                    raise ValueError('Encoded master has incomplete decoded alpha planes')
                audio_evidence.update(alpha, alpha_mode='straight')
            if audio is not None:
                from fractions import Fraction
                import os
                import tempfile
                with tempfile.TemporaryFile(dir=os.environ.get('TMPDIR')) as pcm:
                    run_process(['ffmpeg','-v','error','-xerror','-i',input_path or 'pipe:0','-map','0:a:0',
                        '-vn','-c:a','pcm_s16le','-f','s16le','-'], input=None if input_path else payload,
                        stdout=pcm,stderr=subprocess.PIPE,timeout=7200,check=True)
                    pcm.seek(0)
                    audio_evidence = _spoken_audio_receipt(audio,pcm,Fraction(count,1)/Fraction(stream['r_frame_rate']))
                from ..final_quality import measure_final_audio
                audio_evidence['audio_measurement'] = measure_final_audio(
                    payload, audio_evidence, run_process=run_process, input_path=input_path)
        except (ValueError, KeyError, subprocess.SubprocessError) as exc:
            raise ContractError('OUTPUT_INVALID', 'Local media probe/decode failed: ' + str(exc)) from exc
        key = self._key(payload, port)
        receipt = {'schema': 'motion/v1/local-output-probe-evidence',
            'sha256': key[0], 'kind': key[1], 'media_type': key[2],
            'size_bytes': len(payload), 'probe': facts, 'decoded_frames': actual,
            'framemd5_sha256': 'sha256:' + hashlib.sha256(decoded).hexdigest(),
            'authority': 'owned worker execution; not human creative acceptance', **audio_evidence}
        import uuid
        rid = 'rcp_' + str(uuid.uuid5(uuid.NAMESPACE_URL, digest(receipt)))
        with self._lock:
            self.receipts[rid] = receipt
            self._proofs[key] = rid
        return rid

    def _validate_wav(self, payload, port, *, run_process, input_path=None):
        """Bounded PCM16 speech or conformed-media WAV; not listening claims."""
        import wave
        from typing import BinaryIO, cast
        from .stream_evidence import BufferReader
        if port['kind'] not in ('audio', 'media'):
            raise ContractError('OUTPUT_INVALID', 'PCM WAV requires an audio or media output kind.')
        def run(args):
            args = [input_path if input_path and arg == 'pipe:0' else arg for arg in args]
            return run_process(args, input=None if input_path else payload, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=7200 if input_path else 300, check=True).stdout
        try:
            # Reject oversized/unsupported declared audio before starting a decoder.
            pcm_hash, pcm_length = hashlib.sha256(), 0
            with wave.open(cast(BinaryIO, BufferReader(payload)), 'rb') as wav:
                channels, width, rate, samples, compression, _ = wav.getparams()
                if (compression != 'NONE' or width != 2 or channels not in (1, 2)
                        or not 0 < rate <= 48000 or not 0 < samples <= 3600 * rate):
                    raise ValueError('WAV exceeds PCM16, stereo, 48kHz, one-hour bounds.')
                while True:
                    chunk = wav.readframes(65536)
                    if not chunk:
                        break
                    pcm_hash.update(chunk)
                    pcm_length += len(chunk)
                if pcm_length != samples * channels * width:
                    raise ValueError('WAV sample declaration exceeds available bytes.')
            facts = json.loads(run(['ffprobe', '-v', 'error', '-show_streams',
                '-show_format', '-of', 'json', 'pipe:0']))
            streams = facts.get('streams', [])
            if (facts.get('format', {}).get('format_name') != 'wav' or len(streams) != 1
                    or streams[0].get('codec_type') != 'audio'
                    or streams[0].get('codec_name') != 'pcm_s16le'
                    or int(streams[0]['sample_rate']) != rate
                    or streams[0]['channels'] != channels):
                raise ValueError('Probe differs from bounded speech WAV header.')
            decoded = run(['ffmpeg', '-v', 'error', '-xerror', '-i', 'pipe:0',
                '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', '-f', 'hash', '-hash', 'sha256', '-'])
            if decoded.decode('ascii').strip().lower() != 'sha256=' + pcm_hash.hexdigest():
                raise ValueError('Full audio decode differs from exact declared PCM samples.')
        except (ValueError, KeyError, EOFError, wave.Error, subprocess.SubprocessError) as exc:
            raise ContractError('OUTPUT_INVALID', 'Local WAV probe/decode failed: ' + str(exc)) from exc
        key = self._key(payload, port)
        receipt = {'schema': 'motion/v1/local-output-probe-evidence',
            'sha256': key[0], 'kind': key[1], 'media_type': key[2],
            'size_bytes': len(payload), 'probe': facts, 'decoded_samples': samples,
            'sample_rate_hz': rate, 'channels': channels,
            'pcm_sha256': 'sha256:' + pcm_hash.hexdigest(),
            'authority': 'owned worker execution; not human creative acceptance'}
        import uuid
        rid = 'rcp_' + str(uuid.uuid5(uuid.NAMESPACE_URL, digest(receipt)))
        with self._lock:
            self.receipts[rid] = receipt
            self._proofs[key] = rid
        return rid

    @staticmethod
    def verify_receipt(receipt_id, receipt, *, sha256, kind, media_type, size_bytes):
        """Verify retained observation identity; never execute or grant authority."""
        import uuid
        if (not isinstance(receipt, dict) or
                receipt.get('schema') != 'motion/v1/local-output-probe-evidence' or
                any(receipt.get(k) != v for k, v in dict(sha256=sha256,
                    kind=kind, media_type=media_type, size_bytes=size_bytes).items()) or
                receipt_id != 'rcp_' + str(uuid.uuid5(uuid.NAMESPACE_URL, digest(receipt)))):
            raise ContractError('HASH_MISMATCH', 'Local probe receipt identity or artifact binding differs.')
        return copy.deepcopy(receipt)

    def receipt(self, receipt_id, payload, port):
        """Snapshot the actual exact-byte observation for atomic job publication."""
        with self._lock:
            receipt = copy.deepcopy(self.receipts.get(receipt_id))
        key = self._key(payload, port)
        return self.verify_receipt(receipt_id, receipt, sha256=key[0], kind=key[1],
            media_type=key[2], size_bytes=len(payload))

    def __call__(self, payload, port):
        with self._lock:
            rid = self._proofs.get(self._key(payload, port))
        if rid is None:
            raise ContractError('DEPENDENCY_UNAVAILABLE',
                'Exact output bytes lack an owned probe/decode receipt.')
        return rid
