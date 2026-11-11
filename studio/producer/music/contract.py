"""CF-MU1 closed cue plan; no inference or installed runtime imports."""
from typing import Literal
from pydantic import Field
from ...domain import Strict, Fault

PROFILE = 'stereo-48000-pcm16'
OPERATION = 'instrumental-cue-v1'
FIXED = dict(task='text2music', model='acestep-v15-turbo', batch=1, steps=8,
             shift=3.0, guidance=10.0, lyrics='', tempo='auto', key='auto', meter='auto',
             thinking=False, cot=False, extra_lm=False, audio_format='wav',
             conversion='native-rate-pcm16-only', effective_seed='unverified',
             upstream_processing='ACE inference peak normalization toward -1 dB; bridge adds none',
             use='Music rights and intended use unqualified')
# Source evidence, NOT complete runtime/checkpoint qualification.
SOURCE_PINS = dict(launcher='e6870eb2aedb3ed606e75b6e1522936d4902d93398127aedda2b28d110dc631e',
    generator='c16cef4aa4fea4039e44d517753ca38409bbc3c07c7d344fab0a13b8dcc78d78',
    inference='2395a1e6340af075d3f9d2fad293a389beb61f0a11e1db79a5ad120f6d0ce9a2',
    ace_commit='dce621408bee8c31b4fcf4811682eb9359e1bc94',
    ui_commit='b9e24018e199f2a89976562e4f33213d67d25b9f')


class Options(Strict):
    seconds: int = Field(default=30, ge=10, le=30)
    seed: int = Field(default=42, ge=0, le=4294967295)
    instrumental: Literal[True] = True


def parameters(snapshot, options, operation):
    value = Options.model_validate(options, strict=True)
    # Literal True otherwise accepts integer 1 in Pydantic.
    if 'instrumental' in options and type(options['instrumental']) is not bool:
        raise Fault('ARGUMENT_INVALID', 422)
    if snapshot['kind'] != 'Music' or operation != OPERATION:
        raise Fault('UNSUPPORTED_OPERATION', 409)
    text = snapshot['text']
    if not isinstance(text, str) or not text.strip() or len(text) > 2000 or '\x00' in text:
        raise Fault('ARGUMENT_INVALID', 422)
    return dict(value.model_dump(), **FIXED)


def launcher_vector(launcher, plan, directory):
    p = plan['parameters']
    return [str(launcher), '--prompt', plan['direction'], '--lyrics', '', '--instrumental',
        '--duration', str(p['seconds']), '--bpm', '0', '--key-scale', '', '--time-signature', '',
        '--vocal-language', 'auto', '--infer-steps', '8', '--guidance-scale', '10.0',
        '--batch-size', '1', '--seed', str(p['seed']), '--audio-format', 'wav', '--shift', '3.0',
        '--task-type', 'text2music', '--model-config', 'acestep-v15-turbo',
        '--output-dir', str(directory), '--no-cot-metas', '--no-cot-caption', '--no-cot-language', '--json']
