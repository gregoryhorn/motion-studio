"""Passive method inventory. Never import providers, resolve tokens, or start engines."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil

import yaml

KINDS = ('Sound effects', 'Music', 'Voice', 'Image', 'Video')
LOCAL_TTS = {'neutts', 'kittentts', 'piper'}
KEYS = {
    'deepinfra': ('DEEPINFRA_API_KEY',), 'fal': ('FAL_KEY',),
    'krea': ('KREA_API_KEY',), 'meta-ai': ('MODEL_API_KEY', 'META_API_KEY', 'META_MODEL_API_KEY'),
    'openai': ('OPENAI_API_KEY',), 'openrouter': ('OPENROUTER_API_KEY',),
    'xai': ('XAI_API_KEY',), 'elevenlabs': ('ELEVENLABS_API_KEY',),
    'minimax': ('MINIMAX_API_KEY', 'MINIMAX_CN_API_KEY'),
    'mistral': ('MISTRAL_API_KEY',), 'gemini': ('GEMINI_API_KEY', 'GOOGLE_API_KEY'),
}
LABELS = {'openai': 'OpenAI', 'openai-codex': 'OpenAI (Codex)', 'xai': 'xAI',
          'meta-ai': 'Meta AI', 'fal': 'FAL', 'deepinfra': 'DeepInfra',
          'elevenlabs': 'ElevenLabs', 'edge': 'Edge TTS'}
ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$')


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _read(path, *, json_only=False):
    try:
        if path.stat().st_size > 1024 * 1024:
            return {}
        value = json.loads(path.read_text()) if json_only else yaml.safe_load(path.read_text())
        return _mapping(value)
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def _source(path):
    try:
        return path.read_text() if path.stat().st_size < 512 * 1024 else ''
    except OSError:
        return ''


def _directories(root):
    try:
        return sorted(p for p in root.iterdir() if p.is_dir() and ID.fullmatch(p.name)
                      and not p.name.startswith('_'))
    except OSError:
        return []


def _installed(module):
    # Top-level module only: find_spec does not import any model/runtime.
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _option(name, *, engine='cloud', cost='paid', reason=None, note=None, label=None):
    return dict(observed_ready=reason is None, operation_qualified='unknown',
                permitted_for_use='checked-at-dispatch', action='import' if name == 'import' else 'generate',
                evidence_scope='passive-presence-only', next_action='Import an existing file' if name == 'import' else
                'Resolve supported route and current admission before calling', id=name, label=label or LABELS.get(name, name.replace('-', ' ').title()),
                engine=engine, cost=cost, available=reason is None, reason=reason, note=note)


def _tts_defaults(root):
    """Extract only the TTS literal from source; DEFAULT_CONFIG contains executable expressions."""
    try:
        tree = ast.parse(_source(root / 'hermes_cli/config_defaults.py'))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            if not any(isinstance(t, ast.Name) and t.id == 'DEFAULT_CONFIG' for t in node.targets):
                continue
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == 'tts':
                    return _mapping(ast.literal_eval(value))
    except (SyntaxError, ValueError):
        pass
    return {}


def _credential_present(name, env, auth, source, config):
    names = set(KEYS.get(name, ()))
    # Include new provider credentials without executing its discovery hooks.
    names.update(re.findall(r'[\'\"]([A-Z][A-Z0-9_]*(?:API_KEY|_TOKEN|_KEY))[\'\"]', source))
    key_env = config.get('api_key_env')
    if isinstance(key_env, str):
        names.add(key_env)
    if any(isinstance(env.get(key), str) and env[key].strip() for key in names):
        return True
    entry = _mapping(_mapping(auth.get('providers')).get(
        'xai-oauth' if name == 'xai' else name))
    # Only credential presence; never call refresh/resolution (which can use the network).
    tokens = _mapping(entry.get('tokens'))
    return bool(tokens.get('access_token') or entry.get('access_token') or entry.get('api_key'))


def _cloud(name, source, config, env, auth, kind):
    cost, note = 'paid', 'Provider readiness only; generation requires a supported Studio route.'
    if name == 'openai-codex' and kind == 'Image':
        cost, note = 'subscription', 'Included with your ChatGPT/Codex plan'
    elif name == 'xai' and kind in ('Image', 'Video'):
        # Owner-declared coverage; not inferred from credential or provider presence.
        cost, note = 'subscription', 'Owner-declared: covered by the profile owner’s xAI subscription'
    elif name == 'edge':
        cost, note = 'free', 'Online speech service; network required when used.'
    reason = None
    if config.get('enabled') is False:
        reason = 'Not enabled in this profile'
    elif name == 'edge':
        if not _installed('edge_tts'):
            reason = 'Not installed'
    elif not _credential_present(name, env, auth, source, config):
        reason = 'No OAuth credential observed' if name == 'openai-codex' else 'No API key set'
    if name not in KEYS and name not in ('edge', 'openai-codex'):
        cost = 'unknown'
    return _option(name, cost=cost, reason=reason, note=note)


def _local_voice(name, config, home, env):
    reason = 'Local runtime or model not installed'
    module = {'piper': 'piper', 'neutts': 'neutts', 'kittentts': 'kittentts'}[name]
    if _installed(module):
        if name == 'piper':
            voice = str(config.get('voice') or 'en_US-lessac-medium')
            model = Path(voice).expanduser() if voice.endswith('.onnx') else (
                Path(config.get('voices_dir') or home / 'cache/piper-voices') / (voice + '.onnx'))
            if model.is_file() and model.with_suffix('.onnx.json').is_file():
                reason = None
        else:
            model_id = config.get('model') or {'neutts': 'neuphonic/neutts-air-q4-gguf',
                'kittentts': 'KittenML/kitten-tts-nano-0.8-int8'}[name]
            cache = Path(env.get('HF_HUB_CACHE') or Path(env.get('HF_HOME') or Path.home() / '.cache/huggingface') / 'hub')
            model = cache / ('models--' + str(model_id).replace('/', '--')) / 'snapshots'
            if any(p.is_file() and p.stat().st_size for p in model.glob('*/*')
                   if p.suffix in ('.gguf', '.onnx', '.safetensors', '.bin')):
                reason = None
    if config.get('enabled') is False:
        reason = 'Not enabled in this profile'
    return _option(name, engine='local', cost='free', reason=reason,
                   note='Model presence checked only; no engine loaded.')


def _command_voice(name, config):
    reason = 'Local runtime and model presence not verified'
    try:
        args = shlex.split(config.get('command', ''))
        binary = shutil.which(args[0]) if args else None
        if not binary:
            reason = 'Not installed'
    except (ValueError, TypeError):
        reason = 'Not installed'
    if config.get('enabled') is False:
        reason = 'Not enabled in this profile'
    # Arbitrary commands may call paid services: do not infer free/local from their name.
    return _option(name, engine='local', cost='free' if name.startswith('voicebox-') else 'unknown', reason=reason,
                   note='Configured command bridge; runtime, model and cost need verification.')


def _stable_audio():
    from ..producer import local_sfx
    paths = [local_sfx.WRAPPER, local_sfx.ROOT / 'venv/bin/python', local_sfx.ROOT / 'audio.py']
    paths += [Path(p) for p in local_sfx.model_pins()]
    ready = all(p.is_file() for p in paths) and os.access(local_sfx.WRAPPER, os.X_OK)
    return _option('stable-audio-local', label='Local Stable Audio', engine='local', cost='free',
                   reason=None if ready else 'Local runtime or model not installed',
                   note='Installed-file check only; live_sfx rechecks GPU resources and admission before work.')


def _plugin_options(root, section):
    """Enumerate provider plugins, including extra installed SFX/music families."""
    families = {'sfx': ('sfx', 'sfx_gen', 'sound_effects'),
                'music': ('music', 'music_gen')}.get(section, (section,))
    found = {}
    for family in families:
        for path in _directories(root / 'plugins' / family):
            if (path / '__init__.py').is_file():
                found[path.name] = _source(path / '__init__.py')
    return sorted(found.items())



def _extra_audio_plugins(kinds, root, config, env, auth):
    for path in _directories(root.parent / 'plugins'):
        manifest = _read(path / 'plugin.yaml')
        tools = manifest.get('provides_tools', [])
        if not isinstance(tools, list):
            continue
        capabilities = ' '.join(t for t in tools if isinstance(t, str)).lower()
        music = ('music' in path.name.lower() and 'music' in capabilities) or bool(
            re.search(r'(generate|compose|create|synthesize)[_ .-]*music|music[_ .-]*(generate|compose|create|synthesize)', capabilities))
        kind = ('Music' if music else
                'Sound effects' if re.search(r'sound[_-]?effects?|(?:^|_)sfx(?:_|$)', capabilities) else None)
        if kind is None:
            continue
        name = 'elevenlabs' if path.name.startswith('elevenlabs-') else path.name
        if any(o['id'] == name for o in kinds[kind]['options']):
            continue
        settings = _mapping(_mapping(_mapping(config.get('plugins')).get('entries')).get(path.name))
        source = _source(path / '__init__.py')
        requires = manifest.get('requires_env', [])
        if isinstance(requires, list):
            source += repr([r.get('name') for r in requires if isinstance(r, dict)])
        kinds[kind]['options'].append(_cloud(name, source, settings, env, auth, kind))


def list_methods(*, home=None, provider_root=None, desktop_root=None, env=None):
    """Return public metadata only. All discovery is filesystem/PATH observation."""
    env = os.environ if env is None else env
    home = Path(home or env.get('HERMES_HOME') or Path.home() / '.hermes')
    root = Path(provider_root or Path.home() / '.hermes/hermes-agent-official')
    desktop = Path(desktop_root or Path.home() / '.hermes/desktop-plugins')
    config, auth = _read(home / 'config.yaml'), _read(home / 'auth.json', json_only=True)
    kinds = {kind: dict(default=None, options=[]) for kind in KINDS}
    for kind, section in (('Image', 'image_gen'), ('Video', 'video_gen'),
                          ('Sound effects', 'sfx'), ('Music', 'music')):
        settings = _mapping(config.get(section))
        for name, source in _plugin_options(root, section):
            entry = _mapping(_mapping(_mapping(config.get('plugins')).get('entries')).get(name))
            options = {**_mapping(settings.get(name)), **({'enabled': False} if entry.get('enabled') is False else {})}
            kinds[kind]['options'].append(_cloud(name, source, options, env, auth, kind))
        kinds[kind]['default'] = settings.get('provider')
    defaults = _tts_defaults(root)
    tts = _mapping(config.get('tts'))
    names = {key for key, value in defaults.items() if isinstance(value, dict)
             and key not in ('streaming', 'providers')}
    # Read the authoritative built-in set too, so future non-dict provider defaults are included.
    source = _source(root / 'tools/tts_command_provider.py')
    match = re.search(r'BUILTIN_TTS_PROVIDERS\s*=\s*frozenset\((\{.*?\})\)', source, re.S)
    if match:
        try:
            names.update(ast.literal_eval(match[1]))
        except (SyntaxError, ValueError):
            pass
    for name in sorted(names):
        if not isinstance(name, str) or not ID.fullmatch(name):
            continue
        settings = {**_mapping(defaults.get(name)), **_mapping(tts.get(name))}
        option = (_local_voice(name, settings, home, env) if name in LOCAL_TTS else
                  _cloud(name, '', settings, env, auth, 'Voice'))
        kinds['Voice']['options'].append(option)
    for name, settings in sorted(_mapping(tts.get('providers')).items()):
        if isinstance(name, str) and ID.fullmatch(name) and name not in names:
            kinds['Voice']['options'].append(_command_voice(name, _mapping(settings)))
    kinds['Voice']['default'] = tts.get('provider', defaults.get('provider'))
    kinds['Sound effects']['options'].insert(0, _stable_audio())
    kinds['Music']['options'].insert(0, _option('ace-local', label='Local ACE bridge',
        engine='local', cost='free', reason='Local music engine not qualified yet'))
    _extra_audio_plugins(kinds, root, config, env, auth)
    # Desktop SFX integration is independent of the Hermes provider-plugin families.
    if ((desktop / 'elevenlabs-sound-effects/plugin.js').is_file()
            and not any(o['id'] == 'elevenlabs' for o in kinds['Sound effects']['options'])):
        kinds['Sound effects']['options'].append(_cloud('elevenlabs', '', _mapping(_mapping(_mapping(config.get('plugins')).get('entries')).get('elevenlabs-sound-effects')), env, auth, 'Sound effects'))
    for kind, value in kinds.items():
        value['options'].append(_option('import', label='Import', engine='local', cost='free'))
        known = {o['id'] for o in value['options']}
        if value['default'] not in known:
            value['default'] = None
        # Hermes injects provider credentials into the gateway (e.g. from a secrets
        # manager), so the plugin cannot see them. The provider this profile is
        # configured to use is treated as ready; Hermes reports a real failure.
        for option in value['options']:
            if option['id'] == value['default'] and option['reason'] in ('No API key set', 'No OAuth credential observed', 'Not installed'):
                option.update(available=True, observed_ready=True, reason=None,
                              note=(option.get('note') or '') + ' Configured in this profile; key managed by Hermes.')
    return dict(kinds=kinds)


def rpc_list(params, **_context):
    if not isinstance(params, dict):
        return dict(error='INVALID_METHODS_INPUT')
    params = dict(params)
    session = params.pop('session_id', None)
    if session is not None and (not isinstance(session, str) or not session.strip() or len(session) > 256):
        return dict(error='INVALID_METHODS_INPUT')
    if _context.get('session_id') is not None and session is not None and session != _context['session_id']:
        return dict(error='INVALID_METHODS_INPUT')
    profile = params.pop('profile', None)
    if profile is not None and (not isinstance(profile, str) or not profile.strip()):
        return dict(error='INVALID_METHODS_INPUT')
    if params:
        return dict(error='INVALID_METHODS_INPUT')
    try:
        return list_methods()
    except Exception:
        # No filesystem, configuration, credential or exception text crosses the RPC.
        return dict(error='METHODS_UNAVAILABLE')
