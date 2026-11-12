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
        self.secrets = {}
        self.secret_lookup = self.enterContext(patch.object(methods, '_get_secret',
            side_effect=lambda key: self.secrets.get(key)))
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
        self.assertEqual(self.inventory()['Image']['default'], 'missing')
        self.assertFalse(self.option(self.inventory(), 'Image', 'missing')['available'])

    def test_context_profile_selection(self):
        self.config = {'tts': {'provider': 'openai'}}
        self.inventory()
        with patch.object(methods, '_profile_home', return_value=self.home):
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
        self.secrets = {'FUTURE_API_KEY': secret}
        self.config = {'image_gen': {'future': {'api_key': secret, 'base_url': 'https://private.invalid'}}}
        result = self.inventory()
        self.assertTrue(self.option(result, 'Image', 'future')['available'])
        encoded = json.dumps(result)
        for value in (secret, str(self.base), 'private.invalid'):
            self.assertNotIn(value, encoded)

    def test_profile_disabled_even_with_credential(self):
        self.plugin('image_gen', 'fal')
        self.secrets = {'FAL_KEY': 'secret'}
        self.config = {'plugins': {'entries': {'fal': {'enabled': False}}}}
        option = self.option(self.inventory(), 'Image', 'fal')
        self.assertFalse(option['available'])
        self.assertEqual(option['reason'], 'Not enabled in this profile')

    def test_oauth_configuration_without_reading_token_store(self):
        for name in ('openai-codex', 'xai-oauth'):
            self.plugin('image_gen', name)
        (self.home / 'auth.json').write_text(json.dumps({'providers': {
            'openai-codex': {'tokens': {'access_token': 'PRIVATE-OAUTH-CANARY'}}}}))
        original_read = Path.read_text
        original_stat = Path.stat
        def guarded_read(path, *args, **kwargs):
            self.assertNotEqual(path.name, 'auth.json', 'Token store must never be read')
            return original_read(path, *args, **kwargs)
        def guarded_stat(path, *args, **kwargs):
            self.assertNotEqual(path.name, 'auth.json', 'Token store must never be probed')
            return original_stat(path, *args, **kwargs)
        with patch.object(Path, 'read_text', guarded_read), patch.object(Path, 'stat', guarded_stat):
            result = self.inventory()
            self.assertFalse(self.option(result, 'Image', 'openai-codex')['available'])
            for kind, section in (('Image', 'image_gen'), ('Video', 'video_gen'), ('Voice', 'tts')):
                for name in ('openai-codex', 'xai-oauth', 'xai'):
                    self.config = {section: {'provider': name}}
                    result = self.inventory()
                    option = self.option(result, kind, name)
                    self.assertTrue(option['available'])
                    self.assertIn('Configured in this profile', option['note'])
                    self.assertFalse(option['observed_ready'])
                    self.assertEqual(option['evidence_scope'], 'profile-configuration-only')
                    self.assertNotIn('PRIVATE-OAUTH-CANARY', json.dumps(result))

    def test_environment_keys_do_not_override_secret_scope(self):
        self.plugin('image_gen', 'fal')
        self.config = {'image_gen': {'provider': 'fal'}}
        self.env = {'FAL_KEY': 'INJECTED-KEY'}
        with patch.dict('os.environ', {'FAL_KEY': 'PROCESS-KEY'}):
            self.assertFalse(self.option(self.inventory(), 'Image', 'fal')['available'])
        self.secrets = {'FAL_KEY': 'PROFILE-KEY'}
        self.assertTrue(self.option(self.inventory(), 'Image', 'fal')['available'])
        self.secret_lookup.assert_any_call('FAL_KEY')

    def test_disabled_oauth_stays_disabled(self):
        self.config = {'image_gen': {'provider': 'openai-codex'},
                       'plugins': {'entries': {'openai-codex': {'enabled': False}}}}
        option = self.option(self.inventory(), 'Image', 'openai-codex')
        self.assertFalse(option['available'])
        self.assertEqual(option['reason'], 'Not enabled in this profile')

    def test_xai_scoped_key_is_distinct_from_configured_oauth(self):
        self.config = {'image_gen': {'provider': 'xai'}}
        self.secrets = {'XAI_API_KEY': 'PROFILE-KEY'}
        option = self.option(self.inventory(), 'Image', 'xai')
        self.secret_lookup.assert_any_call('XAI_API_KEY')
        self.assertTrue(option['available'])
        self.assertTrue(option['observed_ready'])
        self.assertEqual(option['evidence_scope'], 'passive-presence-only')

    def test_scope_errors_do_not_fall_back_to_process_keys(self):
        self.plugin('image_gen', 'fal')
        with patch.dict('os.environ', {'FAL_KEY': 'PROCESS-KEY'}), \
                patch.object(methods, '_get_secret', side_effect=RuntimeError('scope unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'scope unavailable'):
                self.inventory()
            with patch.object(methods, '_profile_home', return_value=self.home):
                self.assertEqual(methods.rpc_list({}), {'error': 'METHODS_UNAVAILABLE'})

    def test_sfx_and_music_plugin_discovery(self):
        self.plugin('music_gen', 'elevenlabs')
        self.plugin('sfx_gen', 'other', "get_secret('OTHER_API_KEY')")
        folder = self.desktop / 'elevenlabs-sound-effects'
        folder.mkdir(parents=True)
        (folder / 'plugin.js').touch()
        self.secrets = {'ELEVENLABS_API_KEY': 'secret'}
        result = self.inventory()
        self.assertTrue(self.option(result, 'Sound effects', 'elevenlabs')['available'])
        self.assertTrue(self.option(result, 'Music', 'elevenlabs')['available'])
        self.assertFalse(self.option(result, 'Sound effects', 'other')['available'])

    def test_standalone_music_manifest_discovery(self):
        folder = self.root.parent / 'plugins' / 'future-music'
        folder.mkdir(parents=True)
        (folder / 'plugin.yaml').write_text("provides_tools: [future_music]\nrequires_env: [{name: FUTURE_API_KEY}]")
        self.secrets = {'FUTURE_API_KEY': 'secret'}
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


class HostScopeIntegrationTests(unittest.TestCase):
    def test_real_host_scope_controls_profile_and_key_presence(self):
        try:
            from agent import secret_scope
            from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        except ImportError:
            self.skipTest('Hermes host modules are not available in this standalone checkout')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            profile_a, profile_b = base / 'a', base / 'b'
            for home, provider in ((profile_a, 'fal'), (profile_b, 'openai')):
                home.mkdir()
                (home / 'config.yaml').write_text(yaml.safe_dump({'image_gen': {'provider': provider}}))
            context = secret_scope.set_multiplex_context(True)
            try:
                with patch.dict('os.environ', {'FAL_KEY': 'PROCESS-CANARY', 'OPENAI_API_KEY': 'PROCESS-CANARY'}):
                    for home, provider, secrets in ((profile_a, 'fal', {'FAL_KEY': 'SCOPED-CANARY'}),
                                                     (profile_b, 'openai', {}),
                                                     (profile_a, 'fal', {})):
                        home_token = set_hermes_home_override(home)
                        scope_token = secret_scope.set_secret_scope(secrets, profile_home=str(home))
                        try:
                            result = methods.list_methods(provider_root=base / 'absent', desktop_root=base / 'desktop')
                            image = result['kinds']['Image']
                            self.assertEqual(image['default'], provider)
                            option = next(o for o in image['options'] if o['id'] == provider)
                            self.assertEqual(option['available'], bool(secrets))
                            self.assertNotIn('CANARY', json.dumps(result))
                        finally:
                            secret_scope.reset_secret_scope(scope_token)
                            reset_hermes_home_override(home_token)
                    home_token = set_hermes_home_override(profile_a)
                    scope_token = secret_scope.set_secret_scope(None)
                    try:
                        with self.assertRaises(secret_scope.UnscopedSecretError):
                            methods.list_methods(provider_root=base / 'absent', desktop_root=base / 'desktop')
                    finally:
                        secret_scope.reset_secret_scope(scope_token)
                        reset_hermes_home_override(home_token)
            finally:
                secret_scope.reset_multiplex_context(context)


if __name__ == '__main__':
    unittest.main()
