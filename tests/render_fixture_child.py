#!/usr/bin/env python3
"""TEST render interface v1; independent CLI/native receipt, bounded synthetic PCM."""
import argparse
import hashlib
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
    parser.add_argument('action', choices=['render'])
    parser.add_argument('--description', required=True)
    parser.add_argument('--frame-count', type=int, required=True)
    parser.add_argument('--timbre', choices=['soft', 'bright'], required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    with (root / 'effects.jsonl').open('a') as log:
        log.write(json.dumps({'argv': sys.argv, 'env': dict(os.environ)}) + '\n')
    mode = (root / 'mode').read_text()
    if mode == 'sleep':
        (root / ('ready-' + str(os.getpid()))).write_text('READY')
        time.sleep(30)
    output = Path(args.target)
    pcm = b''.join(struct.pack('<hh', int(900 * math.sin(n / 9)), int(1100 * math.sin(n / 13)))
                   for n in range(args.frame_count))
    with wave.open(str(output), 'wb') as target:
        target.setparams((2, 2, 44100, args.frame_count, 'NONE', 'not compressed'))
        target.writeframes(pcm)
    if mode == 'bad-output':
        output.write_bytes(b'NOT_WAV')
    data = output.read_bytes()
    receipt: dict = dict(schema=1, asset=dict(leaf=output.name, length=len(data), sha256=hashlib.sha256(data).hexdigest()),
                   input=dict(description=args.description, frame_count=args.frame_count, timbre=args.timbre),
                   provenance='synthetic-not-generated')
    if mode == 'mismatch':
        receipt['asset']['sha256'] = '0' * 64
    output.with_suffix('.wav.json').write_text('{' if mode == 'corrupt-receipt' else json.dumps(receipt))


if __name__ == '__main__':
    main()
