#!/usr/bin/env python3
"""Harmless deterministic producer + actual app bridge, never an ACE runtime."""
import json
import os
from pathlib import Path
import struct
import sys
import time


def producer(directory, frames, mode):
    with (directory.parent / 'fixture-effects').open('a') as log: log.write('one\n')
    if mode == 'sleep': time.sleep(30)
    if mode == 'outer-noise': print('x' * 70000, flush=True); time.sleep(2)
    if mode == 'staging':
        for index in range(5):
            with (directory / ('oversize-'+str(index))).open('wb') as stream:
                stream.truncate(14 * 1024 * 1024)
        time.sleep(2)
    pcm = struct.pack('<ffff', 0.125, -0.125, -0.25, 0.25) * (frames // 2)
    if mode == 'nonfinite': pcm = struct.pack('<f', float('nan')) + pcm[4:]
    if mode == 'clipped': pcm = struct.pack('<f', 1.0) + pcm[4:]
    fmt = struct.pack('<HHIIHH', 3, 2, 48000, 384000, 8, 32)
    data = b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<I',16) + fmt + b'data' + struct.pack('<I',len(pcm)) + pcm
    target = directory / 'producer-native.wav'
    target.write_bytes(data[:-1] if mode == 'truncated' else data)
    paths = [str(target)]
    if mode == 'empty': paths = []
    if mode == 'multiple':
        other = directory / 'extra.wav'; other.write_bytes(data); paths.append(str(other))
    if mode == 'extra-audio': (directory / 'extra.wav').write_bytes(data)
    if mode == 'symlink':
        target.unlink(); target.symlink_to(directory.parent / 'outside.wav')
    if mode == 'escape': paths = [str(directory.parent / 'outside.wav')]
    if mode == 'native-size':
        with target.open('r+b') as stream: stream.truncate(16 * 1024 * 1024 + 1)
    result = dict(success=True, audio_paths=paths, elapsed_seconds=0.1, output_dir=str(directory))
    print('Harmless library log', flush=True)
    if mode == 'malformed': print('{not json}')
    if mode == 'inner-noise': print('x' * 70000, flush=True)
    if mode == 'ambiguous': print(json.dumps(result))
    if mode == 'duplicate-json':
        print('{"success":false,' + json.dumps(result)[1:])
    else: print(json.dumps(result), flush=True)
    return 1 if mode == 'exit-failure' else 0


def main():
    if sys.argv[1] == '--producer':
        return producer(Path(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    if sys.argv[1] == '--prompt':
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--duration', type=int)
        parser.add_argument('--output-dir')
        args, _ = parser.parse_known_args()
        return producer(Path(args.output_dir), args.duration * 48000,
                        Path(__file__).with_name('mode').read_text().strip())
    # Injected source root belongs only to this test driver, not a shipped launcher.
    sys.path.insert(0, sys.argv[1])
    from studio.domain import Fault
    from studio.producer.music.adapter import Runtime
    from studio.producer.music.runner import run
    import hashlib
    plan, output = json.loads(sys.argv[2]), Path(sys.argv[3])
    class FixtureBridgeRuntime(Runtime):
        def admit(self, plan, output):
            for name, digest in self.record['pins']['files'].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
                    raise Fault('RUNTIME_DRIFT')
            if self.record['executable'] != __file__: raise Fault('FIXTURE_DENIED')

        def launcher(self): return Path(__file__)

        def verify_sources(self):
            for name, digest in self.record['pins']['files'].items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
                    raise Fault('RUNTIME_DRIFT')

        def producer_environment(self, output): return dict(os.environ)
    try:
        run(plan, output, runtime=FixtureBridgeRuntime(plan['binding']))
        return 0
    except (Fault, OSError):
        # Deliberately do not print raw private receipt, paths or producer errors.
        return 1


if __name__ == '__main__': sys.exit(main())
