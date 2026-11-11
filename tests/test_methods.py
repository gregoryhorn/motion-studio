"""Passive method catalog contracts: no credentials, paths, network or inference."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import yaml
from studio.native import methods


class MethodsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home, self.root, self.desktop = [self.base / x for x in ('profile', 'hermes', 'desktop')]
        self.home.mkdir()
        defaults = self.root / 'hermes_cli/config_defaults.py'
        defaults.parent.mkdir(parents=True)
        defaults.write_text("DEFAULT_CONFIG = {'tts': {'provider': 'edge', 'edge': {}, "
                            "'openai': {}, 'piper': {}, 'neutts': {}, 'kittentts': {}, 'streaming': {}}}")
        self.env = {}
        self.config = {}

    def plugin(self, family, name, source=''):
        folder = self.root / 'plugins' / family / name
        folder.mkdir(parents=True)
        (folder / '__init__.py').write_text(source)

    def inventory(self):
        (self.home / 'config.yaml').write_text(yaml.safe_dump(self.config))
        return methods.list_methods(home=self.home, provider_root=self.root,
                                    desktop_root=self.desktop, env=self.env)['kinds']

    def option(self, catalog, kind, name):
        return next(o for o in catalog[kind]['options'] if o['id'] == name)

    def test_all_provider_directories_and_configured_voices(self):
        for name in ('deepinfra', 'fal', 'krea', 'meta-ai', 'openai', 'openai-codex', 'openrouter', 'xai', 'future'):
            self.plugin('image_gen', name)
        for name in ('deepinfra', 'fal', 'openrouter', 'xai'):
            self.plugin('video_gen', name)
        self.config = {'tts': {'providers': {'voicebox-kokoro': {'type': 'command', 'command': '/missing/tts'}}}}
        result = self.inventory()
        self.assertEqual(len(result['Image']['options']), 10)
        self.assertEqual(len(result['Video']['options']), 5)
        self.assertFalse(self.option(result, 'Voice', 'voicebox-kokoro')['available'])
        self.assertNotIn('streaming', [o['id'] for o in result['Voice']['options']])

    def test_defaults_follow_active_profile(self):
        self.plugin('image_gen', 'fal')
        self.config = {'image_gen': {'provider': 'fal'}, 'tts': {'provider': 'piper'}}
        self.assertEqual(self.inventory()['Image']['default'], 'fal')
        self.assertEqual(self.inventory()['Voice']['default'], 'piper')
        self.config['image_gen']['provider'] = 'missing'
        self.assertIsNone(self.inventory()['Image']['default'])

    def test_environment_profile_selection(self):
        self.config = {'tts': {'provider': 'openai'}}
        self.inventory()
        with patch.dict('os.environ', {'HERMES_HOME': str(self.home)}, clear=True):
            result = methods.list_methods(provider_root=self.root, desktop_root=self.desktop)
        self.assertEqual(result['kinds']['Voice']['default'], 'openai')

    def test_costs_and_missing_reasons(self):
        for name in ('openai-codex', 'xai', 'openai'):
            self.plugin('image_gen', name)
        self.plugin('video_gen', 'xai')
        result = self.inventory()
        for kind, name in (('Image', 'openai-codex'), ('Image', 'xai'), ('Video', 'xai')):
            self.assertEqual(self.option(result, kind, name)['cost'], 'subscription')
        self.assertEqual(self.option(result, 'Image', 'openai')['cost'], 'paid')
        self.assertEqual(self.option(result, 'Voice', 'edge')['cost'], 'free')
        self.assertEqual(self.option(result, 'Image', 'openai')['reason'], 'No API key set')
        self.assertEqual(self.option(result, 'Music', 'ace-local')['reason'], 'Local music engine not qualified yet')
        for kind in methods.KINDS:
            self.assertTrue(self.option(result, kind, 'import')['available'])

    def test_no_secret_values_or_paths_and_new_provider_key(self):
        secret = 'CANARY-SECRET-DO-NOT-RETURN-123'
        self.plugin('image_gen', 'future', "key = get_secret('FUTURE_API_KEY')")
        self.env = {'FUTURE_API_KEY': secret}
        self.config = {'image_gen': {'future': {'api_key': secret, 'base_url': 'https://private.invalid'}}}
        result = self.inventory()
        self.assertTrue(self.option(result, 'Image', 'future')['available'])
        encoded = json.dumps(result)
        for value in (secret, str(self.base), 'private.invalid'):
            self.assertNotIn(value, encoded)

    def test_profile_disabled_even_with_credential(self):
        self.plugin('image_gen', 'fal')
        self.env = {'FAL_KEY': 'secret'}
        self.config = {'plugins': {'entries': {'fal': {'enabled': False}}}}
        option = self.option(self.inventory(), 'Image', 'fal')
        self.assertFalse(option['available'])
        self.assertEqual(option['reason'], 'Not enabled in this profile')

    def test_oauth_presence_without_resolution(self):
        self.plugin('image_gen', 'openai-codex')
        (self.home / 'auth.json').write_text(json.dumps({'providers': {
            'openai-codex': {'tokens': {'access_token': 'PRIVATE-OAUTH-CANARY'}}}}))
        result = self.inventory()
        self.assertTrue(self.option(result, 'Image', 'openai-codex')['available'])
        self.assertNotIn('PRIVATE-OAUTH-CANARY', json.dumps(result))

    def test_sfx_and_music_plugin_discovery(self):
        self.plugin('music_gen', 'elevenlabs')
        self.plugin('sfx_gen', 'other', "get_secret('OTHER_API_KEY')")
        folder = self.desktop / 'elevenlabs-sound-effects'
        folder.mkdir(parents=True)
        (folder / 'plugin.js').touch()
        self.env = {'ELEVENLABS_API_KEY': 'secret'}
        result = self.inventory()
        self.assertTrue(self.option(result, 'Sound effects', 'elevenlabs')['available'])
        self.assertTrue(self.option(result, 'Music', 'elevenlabs')['available'])
        self.assertFalse(self.option(result, 'Sound effects', 'other')['available'])

    def test_standalone_music_manifest_discovery(self):
        folder = self.root.parent / 'plugins' / 'future-music'
        folder.mkdir(parents=True)
        (folder / 'plugin.yaml').write_text("provides_tools: [future_music]\nrequires_env: [{name: FUTURE_API_KEY}]")
        self.env = {'FUTURE_API_KEY': 'secret'}
        self.assertTrue(self.option(self.inventory(), 'Music', 'future-music')['available'])

    def test_editor_music_mixing_is_not_a_generator(self):
        folder = self.root.parent / 'plugins' / 'video-editor'
        folder.mkdir(parents=True)
        (folder / 'plugin.yaml').write_text("provides_tools: [lk_mix_music]")
        self.assertEqual([o['id'] for o in self.inventory()['Music']['options']], ['ace-local', 'import'])

    def test_local_voice_needs_model_and_runtime(self):
        self.config = {'tts': {'piper': {'voice': str(self.base / 'voice.onnx')}}}
        with patch.object(methods, '_installed', return_value=True):
            self.assertFalse(self.option(self.inventory(), 'Voice', 'piper')['available'])
            (self.base / 'voice.onnx').write_bytes(b'model')
            (self.base / 'voice.onnx.json').write_text('{}')
            self.assertTrue(self.option(self.inventory(), 'Voice', 'piper')['available'])
        with patch.object(methods, '_installed', return_value=False):
            self.assertFalse(self.option(self.inventory(), 'Voice', 'piper')['available'])

    def test_stable_audio_requires_installed_runtime_and_model(self):
        from studio.producer import local_sfx
        wrapper = self.base / 'stable-audio'
        runtime = self.base / 'venv/bin/python'
        runtime.parent.mkdir(parents=True)
        model = self.base / 'model.bin'
        for path in (wrapper, runtime, self.base / 'audio.py'):
            path.write_bytes(b'installed')
        wrapper.chmod(0o700)
        with patch.object(local_sfx, 'ROOT', self.base), patch.object(local_sfx, 'WRAPPER', wrapper), \
                patch.object(local_sfx, 'model_pins', return_value={str(model): 'unused'}):
            self.assertFalse(methods._stable_audio()['available'])
            model.write_bytes(b'model')
            self.assertTrue(methods._stable_audio()['available'])

    def test_supported_envelope_and_observation_distinction(self):
        with patch.object(methods, 'list_methods', return_value={'kinds': {}}):
            self.assertEqual(methods.rpc_list({'session_id': 'root', 'profile': 'fixture'}), {'kinds': {}})
        option = self.option(self.inventory(), 'Voice', 'edge')
        self.assertEqual(option['operation_qualified'], 'unknown')
        self.assertEqual(option['evidence_scope'], 'passive-presence-only')
        self.assertEqual(self.option(self.inventory(), 'Image', 'import')['action'], 'import')

    def test_rpc_strict_and_sanitized_failure(self):
        for payload in (None, [], {'key': 'secret'}, {'session_id': ''}):
            self.assertEqual(methods.rpc_list(payload), {'error': 'INVALID_METHODS_INPUT'})
        with patch.object(methods, 'list_methods', side_effect=RuntimeError('private')):
            self.assertEqual(methods.rpc_list({}), {'error': 'METHODS_UNAVAILABLE'})

    def test_passive_budget_and_exact_shape(self):
        self.plugin('image_gen', 'openai')
        with patch('subprocess.run', side_effect=AssertionError('must not spawn')):
            start = time.perf_counter()
            result = self.inventory()
            self.assertLess(time.perf_counter() - start, .2)
        for kind in result.values():
            self.assertEqual(set(kind), {'default', 'options'})
            for option in kind['options']:
                self.assertEqual(set(option), {'id', 'label', 'engine', 'cost', 'available', 'reason', 'note',
                    'observed_ready', 'operation_qualified', 'permitted_for_use', 'evidence_scope', 'next_action', 'action'})
                self.assertIsInstance(option['available'], bool)
                if not option['available']:
                    self.assertTrue(option['reason'])


if __name__ == '__main__':
    unittest.main()
