#!/usr/bin/python3
"""Ripple Forge documented harmless fixture CLI, version 2.4; distinct native contract."""
import argparse
import json
from pathlib import Path
import struct
import time
import wave

p = argparse.ArgumentParser()
p.add_argument('--description',required=True)
p.add_argument('--length',required=True,type=float)
p.add_argument('--seed-value',required=True,type=int)
p.add_argument('--destination',required=True)
p.add_argument('--manifest',required=True)
a = p.parse_args()
root = Path(__file__).parent
with (root/'effects.jsonl').open('a') as counter: counter.write('{"effect":true}\n')
mode = (root/'mode').read_text() if (root/'mode').exists() else 'good'
if mode=='sleep': time.sleep(20)
with wave.open(a.destination,'wb') as target:
    target.setparams((2,2,44100,0,'NONE','not compressed'))
    target.writeframes(struct.pack('<hh',-1300,1300)*round(a.length*44100))
if mode!='missing-receipt':
    Path(a.manifest).write_text(json.dumps(dict(file=a.destination,description=a.description,length=a.length,seed_value=a.seed_value,version='2.4')))
