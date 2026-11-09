"""Exact source-inspected Breeze CLI speech controls; no inference on import.

Supported flags are --instruction, --seed, --cfg-scale, and paired
--ref-audio/--ref-text. Reference conditioning is speech.synthesize@1, not a
provider clone-object/training service. No named style catalog is invented.
"""
from __future__ import annotations
import ast
from pathlib import Path
import shlex
import shutil
import hashlib
from ..contracts import D, TEXT, ContractError, digest, ident, nullable, obj, validate

BREEZE_ID = 'local.breeze-tts-2'
BREEZE_OPTIONS = 'motion/v1/local.breeze-tts-2/speech-options'
REFERENCE_SCHEMA = obj({'project_id': ident('prj'), 'audio': D['ArtifactRef'],
                        'transcript': D['ArtifactRef'], 'authorization_ref': TEXT})
BREEZE_OPTIONS_SCHEMA = obj({
    'style': nullable({'type': 'string', 'minLength': 1, 'maxLength': 4096}),
    'cfg_scale': {'type': 'string', 'maxLength': 32,
                  'pattern': r'(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)'},
    'reference': nullable(REFERENCE_SCHEMA)})


def breeze_cli_evidence():
    """Read public wrapper/argparse source only, never execute/import the engine.

    Unknown wrappers are unsupported rather than guessed. Hash both files so an
    installed mapping change invalidates the frozen binding before invocation.
    No absolute path or script contents are exposed in option metadata.
    """
    wrapper = shutil.which('breeze-tts')
    if wrapper is None:
        return None
    try:
        path = Path(wrapper)
        if path.stat().st_size > 65536:
            return None
        wrapper_bytes = path.read_bytes()
        source = path if path.suffix == '.py' else None
        if source is None:
            for line in wrapper_bytes.decode('utf-8').splitlines():
                if line.startswith('exec '):
                    candidates = [Path(token) for token in shlex.split(line) if token.startswith('/') and token.endswith('.py')]
                    if len(candidates) == 1:
                        source = candidates[0]
        if source is None or source.stat().st_size > 1048576:
            return None
        source_bytes = source.read_bytes()
        tree = ast.parse(source_bytes)
        flags = {arg.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument'
                 for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)}
        required = {'--text', '--instruction', '--seed', '--cfg-scale', '--ref-audio', '--ref-text', '--output'}
        if not required <= flags:
            return None
        return {'wrapper_sha256': 'sha256:' + hashlib.sha256(wrapper_bytes).hexdigest(),
                'source_sha256': 'sha256:' + hashlib.sha256(source_bytes).hexdigest(),
                'flags': sorted(required)}
    except (OSError, ValueError, SyntaxError, UnicodeError):
        return None


def registration_metadata(adapter_id):
    if adapter_id != BREEZE_ID:
        return {}, {'speech.synthesize@1': {'unsupported_controls': [
            'style', 'reference_cloning', 'provider_clone_objects']}}
    if breeze_cli_evidence() is None:
        return {}, {'speech.synthesize@1': {'unsupported_controls': [
            'style', 'reference_cloning', 'provider_clone_objects', 'clone_training']}}
    return {BREEZE_OPTIONS: BREEZE_OPTIONS_SCHEMA}, {'speech.synthesize@1': {
        'identities': {'provider': 'local', 'model': 'Breeze-TTS-2'},
        'schema_roles': {BREEZE_OPTIONS: 'binding_parameters'},
        'unsupported_controls': ['provider_clone_objects', 'clone_training']}}


def validate_options(adapter_id, envelope):
    if envelope is None:
        return None
    if adapter_id != BREEZE_ID:
        raise ContractError('SCHEMA_UNSUPPORTED', 'Selected speech binding has no style/reference options.')
    if breeze_cli_evidence() is None:
        raise ContractError('SCHEMA_UNSUPPORTED', 'Installed Breeze CLI controls cannot be source-verified; no options or clones are assumed.')
    validate(envelope, obj({'schema_id': {'const': BREEZE_OPTIONS},
        'schema_sha256': {'const': digest(BREEZE_OPTIONS_SCHEMA)},
        'values': BREEZE_OPTIONS_SCHEMA}))
    return envelope['values']


def require_reference_scope(reference, *, project_id, authorize_reference=None):
    """Callback(project_id, reference) must recheck pins and explicit consent.

    Strings saved in preferences never grant authority. Cross-project defaults
    require explicit re-selection/import into the destination project.
    """
    validate(reference, REFERENCE_SCHEMA)
    if reference['project_id'] != project_id:
        raise ContractError('PERMISSION_DENIED', 'Reference belongs to another project; explicitly reselect an authorized artifact.')
    if authorize_reference is None or authorize_reference(project_id, reference) is not True:
        raise ContractError('PERMISSION_DENIED', 'Reference-source authorization is absent, revoked or incompatible.')


def synthesis_controls(adapter_id, parameters, envelope):
    """Map voice + optional freeform style literally to --instruction."""
    options = validate_options(adapter_id, envelope)
    voice = parameters['voice']
    if adapter_id == BREEZE_ID:
        if not isinstance(voice, str) or not voice.strip() or len(voice.encode('utf-8')) > 4096:
            raise ContractError('INVALID_ARGUMENT', 'Breeze voice requires a bounded explicit instruction, not a clone identifier.')
        style = options['style'] if options else None
        instruction = voice + ('\n' + style if style else '')
        if any(ord(char) < 32 and char not in '\n\r\t' for char in instruction):
            raise ContractError('INVALID_ARGUMENT', 'Speech instruction contains control characters.')
        return {'instruction': instruction, 'seed': 42 if parameters['seed'] is None else parameters['seed'],
                'cfg_scale': options['cfg_scale'] if options else 4,
                'reference': options['reference'] if options else None}
    expected = {'local.espeak-ng': 'en-us', 'local.flite-kal': 'kal'}.get(adapter_id)
    if expected is None or voice != expected or parameters['seed'] is not None:
        raise ContractError('INVALID_ARGUMENT', 'Unsupported exact local voice/seed; no fallback is allowed.')
    return {'instruction': voice, 'seed': None, 'cfg_scale': None, 'reference': None}


def breeze_argv(text, controls, output, *, reference_audio=None, reference_text=None):
    """Pure argv construction after the caller's artifact/authority checks."""
    if (reference_audio is None) != (reference_text is None):
        raise ContractError('INVALID_ARGUMENT', 'Reference audio/transcript must be provided together.')
    argv = ['breeze-tts', '--text', text, '--instruction', controls['instruction'],
            '--cfg-scale', str(controls['cfg_scale']), '--seed', str(controls['seed']), '--output', str(output)]
    if reference_audio is not None:
        argv += ['--ref-audio', str(reference_audio), '--ref-text', reference_text]
    return argv
