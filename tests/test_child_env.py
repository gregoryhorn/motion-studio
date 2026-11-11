"""Synthetic secrets only; no real producer, credentials or private media reads."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from studio.child_env import ALLOWLISTS, child_environment
from studio.assets.retention import Assets
from studio.domain import Fault
from studio.media_import.contracts import BeginImport
from studio.media_import.operations import invoke
from studio.media_import.service import MediaImports
from studio.producer.cli_family import FamilyRuntime
from studio.producer.local_sfx import Binding
from studio.producer.music.adapter import Runtime
from studio.producer.music.bridge import foreground
from studio.producer.stable_adapter import StableAudio
from studio.runs.helper_environment import helper_environment
from studio.runs.owned_process import BOOTSTRAP, OwnedProcess

SECRETS = {name: 'synthetic-secret' for name in (
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'HERMES_API_TOKEN', 'HERMES_WORKER_TOKEN',
    'UNKNOWN_PROVIDER_KEY', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD', 'LD_LIBRARY_PATH',
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'BASH_ENV')}


class ChildEnvironmentTests(unittest.TestCase):
    def test_every_profile_is_closed_even_with_explicit_contaminated_input(self):
        source = dict(SECRETS, HOME='/controlled/home', TMPDIR='/controlled/tmp',
                      CUDA_VISIBLE_DEVICES='0', DISPLAY=':99', MOTION_WORKER_TOKEN='unused')
        for adapter in ALLOWLISTS:
            with self.subTest(adapter=adapter), patch.dict(os.environ, source, clear=True):
                self.assertEqual(child_environment(adapter), helper_environment())
                env = child_environment(adapter, source)
                self.assertTrue(SECRETS.keys().isdisjoint(env))
                self.assertEqual(env['HOME'], source['HOME'])
                self.assertNotIn('DISPLAY', env)
                self.assertNotIn('MOTION_WORKER_TOKEN', env)
                self.assertEqual('CUDA_VISIBLE_DEVICES' in env,
                                 adapter in ('owned', 'stable-audio-local', 'ace-step-local'))
        self.assertEqual(set(child_environment('unknown-engine', source)),
                         {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR'})
        with self.assertRaises(ValueError):
            child_environment('helper', {'HOME': 'invalid\x00value'})

    def test_adapter_builders_never_read_ambient_secrets(self):
        with patch.dict(os.environ, SECRETS, clear=True):
            directory = Path('/controlled/runtime')
            environments = [Binding().environment(directory),
                FamilyRuntime(None, {'fixture_only': True}).environment(directory),
                Runtime({'fixture_only': True}).producer_environment(directory / 'candidate.wav'),
                StableAudio().runtime_environment(dict(SECRETS, HOME=str(directory)), directory),
                helper_environment()]
        for env in environments:
            self.assertTrue(SECRETS.keys().isdisjoint(env))
        self.assertEqual(environments[0]['HF_HUB_OFFLINE'], '1')
        self.assertIn('ACESTEP_PYTHON', environments[2])
        self.assertEqual(environments[3]['CUDA_CACHE_PATH'], str(directory / 'cache/cuda'))

    def test_owned_spawn_and_bootstrap_exec_strip_explicit_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, fd)
            worker = OwnedProcess(deadline=3, grace=0.1)
            captured = bytearray()
            worker.capture_chunk = lambda name, data: captured.extend(data) if name == 'stdout' else None
            code = 'import os,json; print(json.dumps(sorted(os.environ)))'
            argv = [sys.executable, '-I', '-c', code]
            result = worker.execute(argv, dict(SECRETS, HOME=temp), directory, fd,
                                    lambda _: None, lambda _: None, lambda: None)
            self.assertEqual(result['code'], 0)
            self.assertTrue(result['group_retired'])
            self.assertTrue(SECRETS.keys().isdisjoint(json.loads(captured)))
            # Independently exercise execve with a deliberately contaminated
            # bootstrap environment, so Popen filtering cannot mask a regression.
            digest = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
            child = subprocess.run([sys.executable, '-I', str(BOOTSTRAP), digest, '3', *argv],
                env=dict(SECRETS, PATH='/usr/bin:/bin'), capture_output=True, timeout=5)
            self.assertEqual(child.returncode, 0)
            self.assertTrue(SECRETS.keys().isdisjoint(json.loads(child.stdout)))

    def test_music_foreground_strips_explicit_and_ambient_secrets(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, SECRETS):
            code, stdout, errors = foreground(
                [sys.executable, '-I', '-c', 'import os,json; print(json.dumps(sorted(os.environ)))'],
                dict(SECRETS, HOME=temp, ACE_STEP_MODEL_CONFIG='controlled'), temp)
        self.assertEqual((code, errors), (0, 0))
        names = json.loads(stdout)
        self.assertTrue(SECRETS.keys().isdisjoint(names))
        self.assertIn('ACE_STEP_MODEL_CONFIG', names)

    def test_path_import_is_unavailable_and_secret_paths_cannot_be_ids(self):
        # Existing imports accept bytes/opaque IDs, never a caller-selected path.
        payload = dict(command='a'*32, request='b'*32, revision=1, digest='0'*64,
                       size=1, name='controlled.wav', format='wav')
        secrets = ('/controlled/.hermes/.env', '/controlled/.hermes/auth.json',
                   '/controlled/.hermes/profiles/video/.env', '/controlled/.ssh/id_ed25519')
        service = MediaImports.__new__(MediaImports)
        service.assets = Assets.__new__(Assets)
        service.assets.store = SimpleNamespace(home=Path('/controlled/store'))
        for path in secrets:
            with self.subTest(path=path):
                with self.assertRaises(ValidationError):
                    BeginImport.model_validate(dict(payload, path=path))
                with self.assertRaises(Fault):
                    service.path(path)
                with self.assertRaises(Fault) as error:
                    invoke(None, 'controlled', 'import_path', {'path': path})
                self.assertEqual(error.exception.code, 'UNKNOWN_MEDIA_OPERATION')


if __name__ == '__main__':
    unittest.main()
