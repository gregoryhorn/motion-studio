"""Explicit trusted binding revision for the shipped local evaluation operation only.

Not an HTTP enable switch. No test-scope reuse, producer dispatch or automatic startup.
"""
import time
from ..domain import Fault
from ..producer import local_sfx as sfx
from ..runs.normal_admission import POLICY


def enable_evaluation(bindings, binding, expected):
    old = bindings.get(binding, expected)
    if old['adapter'] != 'stable-audio-local' or old['interface_version'] != 'stable-audio-cli-v1':
        raise Fault('UNSUPPORTED_OPERATION', 409)
    if old['fixture_only']:
        if not bindings.allow_fixtures:
            raise Fault('FIXTURE_DENIED', 409)
        files = {old['executable']: old['file_digest']}
    else:
        if old['executable'] != str(sfx.WRAPPER) or old['file_digest'] != sfx.FILE_PINS[str(sfx.WRAPPER)]:
            raise Fault('RUNTIME_DRIFT', 409)
        files = {**sfx.FILE_PINS, **sfx.model_pins()}
    sfx.check_pins(files)
    value = {key: val for key, val in old.items() if key not in ('id','revision','schema_version')}
    value['pins'] = dict(value['pins'], files=files)
    value.update(enabled=True, evaluation_scope=dict(POLICY), availability='Available for evaluation',
                 qualification='Offline tested only' if old['fixture_only'] else 'Route technically tested once',
                 reason='EVALUATION_ENABLED', action='Review then Create one sound effect', checked_at=time.time(),
                 evidence_reference='tests/test_quick_create.py' if old['fixture_only'] else 'docs/as-built/runtime-recovery-r1.md',
                 evidence_scope='Noncommercial local technical evaluation only; each output Not reviewed; no commercial clearance')
    return bindings.put(value, binding, expected)
