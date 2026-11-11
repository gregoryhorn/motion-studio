#!/usr/bin/python3
"""Lumen Tone documented harmless fixture CLI, version 1.0; no model/network."""
import argparse
import json
from pathlib import Path
import struct
import time
import wave

p = argparse.ArgumentParser()
p.add_argument('--words',required=True)
p.add_argument('--duration',required=True,type=float)
p.add_argument('--random',required=True,type=int)
p.add_argument('--wave',required=True)
p.add_argument('--report',required=True)
a = p.parse_args()
root = Path(__file__).parent
with (root/'effects.jsonl').open('a') as counter: counter.write('{"effect":true}\n')
mode = (root/'mode').read_text() if (root/'mode').exists() else 'good'
if mode=='sleep': time.sleep(20)
with wave.open(a.wave,'wb') as target:
    target.setparams((2,2,44100,0,'NONE','not compressed'))
    target.writeframes(struct.pack('<hh',700,-700)*round(a.duration*44100))
if mode!='missing-receipt':
    Path(a.report).write_text(json.dumps(dict(wave=a.wave,words=a.words,duration=a.duration,random=a.random,build='1.0')))
