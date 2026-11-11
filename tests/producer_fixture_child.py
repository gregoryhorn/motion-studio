#!/usr/bin/env python3
"""TEST ONLY: argv-native non-private fixture child; never a model or real generator."""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import struct
import sys
import time
import wave


def main():
    root = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['generate'])
    for flag in ('prompt', 'negative', 'seconds', 'steps', 'seed', 'out'):
        parser.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    # Controlled offline-only receipt of actual argv and scrubbed environment.
    with (root / 'effects.jsonl').open('a') as log:
        log.write(json.dumps({'argv': sys.argv, 'env': dict(os.environ), 'cwd': os.getcwd()}) + '\n')
    mode = (root / 'mode').read_text()
    if mode == 'closed-pipes-sleep':
        os.close(1)
        os.close(2)
        time.sleep(30)
    if mode in ('sleep', 'ignore-term'):
        if mode == 'ignore-term':
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            (root / ('ready-' + str(os.getpid()))).write_text('READY')
        time.sleep(30)
    if mode.startswith('flood-'):
        fd = 1 if mode == 'flood-stdout' else 2
        while True:
            os.write(fd, b'NON_PRIVATE_TEST_CAPTURE' * 4096)
    output = Path(args.out)
    if mode == 'cache-layout-mismatch':
        cache = Path(os.environ['HOME']) / '.nv' / 'ComputeCache'
        cache.mkdir(parents=True, exist_ok=True)
        (cache / 'controlled-cache').write_bytes(b'NON_PRIVATE_CACHE')
        if Path(os.environ['HOME']) == output.parent:
            time.sleep(30)  # Strict output monitor must reject the shared-layout directory.
    if mode == 'runtime-good':
        for variable in ('HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'CUDA_CACHE_PATH'):
            location = Path(os.environ[variable]) / 'controlled-nested'
            location.mkdir(parents=True, exist_ok=True)
            (location / 'controlled-state').write_bytes(b'NON_PRIVATE_RUNTIME')
    if mode == 'runtime-budget':
        (Path(os.environ['XDG_CACHE_HOME']) / 'controlled-budget').write_bytes(b'x' * 60000)
    if mode in ('output-directory', 'runtime-link', 'runtime-special'):
        if mode == 'output-directory':
            (output.parent / 'controlled-invalid-directory').mkdir()
        elif mode == 'runtime-link':
            (Path(os.environ['TMPDIR']) / 'controlled-link').symlink_to(root / 'mode')
        else:
            os.mkfifo(Path(os.environ['TMPDIR']) / 'controlled-fifo', 0o600)
        time.sleep(30)
        return
    if mode == 'file-limit':
        with output.open('xb') as target:
            for _ in range(20):
                target.write(b'x' * 1024 * 1024)
        return
    if mode == 'staging-limit':
        for n in range(20):
            (output.parent / f'fixture-{n}').write_bytes(b'x' * 8 * 1024 * 1024)
        time.sleep(30)
        return
    frames = round(float(args.seconds) * 44100)
    pcm = b''.join(struct.pack('<hh', int(1200 * math.sin(n / 12)), int(1000 * math.sin(n / 10)))
                   for n in range(frames))
    if mode == 'comparison':
        # Deliberately distinct controlled tones, never model or private audio.
        frequency = int(args.seed)
        pcm = b''.join(struct.pack('<hh', *([int(5000 * math.sin(2 * math.pi * frequency * n / 44100))] * 2))
                       for n in range(frames))
    with wave.open(str(output), 'wb') as target:
        target.setparams((2, 2, 44100, frames, 'NONE', 'not compressed'))
        target.writeframes(pcm)
    if mode == 'bad-output':
        output.write_bytes(b'NOT_WAV')
    if mode == 'missing-receipt':
        return
    receipt = dict(model='stabilityai/stable-audio-open-1.0',
                   revision='f21265c1e2710b3bd2386596943f0007f55f802e', prompt=args.prompt,
                   negative_prompt=args.negative, seconds=frames / 44100, sample_rate=44100,
                   channels=2, steps=int(args.steps), seed=int(args.seed), output=str(output),
                   elapsed_seconds=0.1, peak_before_gain=0.1, gain=1.0, rms_before_gain=0.01,
                   gpu_peak_allocated_mib=0, perceptual_review='not performed',
                   commercial_clearance='not established; see bundled LICENSE.md')
    if mode == 'mismatch':
        receipt['seed'] = int(args.seed) + 1
    raw = json.dumps(receipt)
    if mode == 'corrupt-receipt':
        raw = '{'
    output.with_suffix('.wav.json').write_text(raw)
    if mode == 'unresolved-descendant':
        ready_read, ready_write = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(ready_read)
            os.setpgid(0, 0)  # Different group, same original session: retirement must fail.
            os.write(ready_write, b'READY')
            os.close(ready_write)
            os.close(1)
            os.close(2)
            time.sleep(0.6)  # Bounded harmless survivor; no signal/adoption needed.
            os._exit(0)
        os.close(ready_write)
        os.read(ready_read, 5)
        os.close(ready_read)


if __name__ == '__main__':
    main()
