"""Closed child environments. No implicit reads or copies of the host environment.

Only explicit adapter values are admitted. Loader, proxy and provider credential
variables are intentionally absent, including unknown future provider names.
This limits credential inheritance; it is not a filesystem/process sandbox.
"""

BASE = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
COMMON = frozenset(('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR'))
CACHE = frozenset(('XDG_CACHE_HOME', 'PYTHONNOUSERSITE', 'DO_NOT_TRACK'))
OFFLINE = frozenset(('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'))
ALLOWLISTS = {
    'helper': frozenset(),
    'declarative-cli': CACHE,
    'stable-audio-local': CACHE | OFFLINE | {'CUDA_CACHE_PATH', 'CUDA_VISIBLE_DEVICES'},
    'music-bridge': CACHE,
    'ace-step-local': CACHE | OFFLINE | {
        'CUDA_VISIBLE_DEVICES', 'ACESTEP_PATH', 'ACE_STEP_UI_PATH', 'ACESTEP_PYTHON',
        'ACE_STEP_OUTPUT_DIR', 'ACE_STEP_MODEL_CONFIG'},
}
# The generic supervisor/bootstrap transports only the closed union of the
# shipped adapters. Adapter construction and LocalRuns apply the narrower set.
ALLOWLISTS['owned'] = frozenset().union(*ALLOWLISTS.values())


def child_environment(adapter='helper', values=None):
    """Build from fixed defaults plus named keys in an explicitly supplied mapping.

    No display or worker token variables are needed by the shipped adapters.
    Future engines must declare their own small allowlist before using them.
    Unknown adapter names receive only the common keys, never adapter extras.
    """
    allowed = COMMON | ALLOWLISTS.get(adapter, frozenset())
    result = dict(BASE)
    if values is not None:
        for name in allowed:
            value = values.get(name)
            if value is not None:
                if not isinstance(value, str) or '\x00' in value:
                    raise ValueError('Invalid child environment value')
                result[name] = value
    return result
