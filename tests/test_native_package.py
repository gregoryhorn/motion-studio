"""Offline archive + actual v0.23.1 loader/RemotePluginContext; never start a host."""
import builtins
import contextlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from typing import Any
from unittest.mock import patch
import zipfile
from tools.build_native_package import check_content, HOST_COMMIT, sha
from studio.native.production.media import OPERATIONS as MEDIA_OPERATIONS
from tests.synthesis_support import Facade, route, selection

ROOT = Path(__file__).resolve().parents[1]
from tests.current_package import current_bundle, current_sources
BUNDLE = Path(os.environ['NATIVE_BUNDLE']) if os.environ.get('NATIVE_BUNDLE') else current_bundle()
HOST = Path(os.environ.get('HERMES_SOURCE', Path.home()/'.hermes/hermes-agent-official'))


class FakeRemoteRuntime:
    def __init__(self, root):
        self.root, self.methods, self.unload_callbacks, self.facade_reads = root, {}, {}, []
        self.facade = Facade()
        self.tools, self.sections = {}, {}

    def ctx_call(self, _key, operation, *args, **kwargs):
        if operation == 'register_rpc': self.methods[args[0]] = args[1]
        elif operation == 'register_tool':
            self.tools[args[0]] = dict(schema=args[2], handler=args[3])
            return True
        elif operation == 'register_system_prompt_section': self.sections[args[0]] = args[1]
        else: raise AssertionError('Unexpected context method')

    def facade_call(self, _key, name, attr, *args, _probe=False, **kwargs):
        self.facade_reads.append((name, attr, _probe))
        if name == 'state' and attr == 'data_dir': return str(self.root)
        if name == 'llm' and attr == 'complete_structured':
            return {'__method__':True} if _probe else self.facade.complete_structured(**kwargs)
        raise AssertionError('Unexpected facade access')


class PackageTests(unittest.TestCase):
    context_type: Any
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(HOST))
        from hermes_cli.plugin_host_child import _import_plugin, RemotePluginContext
        from hermes_cli.plugins_manifest import parse_manifest_file
        cls.import_plugin = staticmethod(_import_plugin)
        cls.context_type = RemotePluginContext
        cls.parse_manifest = staticmethod(parse_manifest_file)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with zipfile.ZipFile(BUNDLE) as archive: archive.extractall(self.temp.name)
        self.home = Path(self.temp.name)/'motion-studio'
        self.key = 'offline_native_'+Path(self.temp.name).name.replace('-', '_')
        self.remote = FakeRemoteRuntime(Path(self.temp.name)/'test-owned-data')
        self.ctx = self.context_type(self.remote, self.key, dict(plugin_id='motion-studio', profile_name='same-label',
            ctx_methods=['register_rpc','register_tool','register_system_prompt_section'], manifest=dict(name='motion-studio')))
        self.addCleanup(self.unload)

    def unload(self):
        for callback in self.remote.unload_callbacks.get(self.key, []): callback()
        for name in list(sys.modules):
            if name == self.key or name.startswith(self.key+'.'): sys.modules.pop(name)

    def load(self):
        original = builtins.__import__
        def isolated(name, *args, **kwargs):
            if name == 'studio' or name.startswith('studio.'): raise AssertionError('Ambient application import')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=isolated):
            module = self.import_plugin(dict(path=str(self.home), module_name=self.key))
            runtime = module.register(self.ctx)
        return module, runtime

    def rpc(self, operation, params=None, session='session-a'):
        return self.remote.methods['technical.'+operation](params or {}, session_id=session)

    def test_actual_manifest_loader_register_open_unload_has_no_effects(self):
        manifest = self.parse_manifest(self.home/'plugin.yaml', self.home, 'project', '')
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual((manifest.name, manifest.kind, manifest.manifest_version), ('motion-studio', 'standalone', 2))
        self.assertEqual(manifest.requires_hermes, '>=0.23.1')
        self.assertEqual(manifest.capabilities, [])
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch('subprocess.Popen', side_effect=AssertionError('No child')):
            _, runtime = self.load()
            self.assertEqual(set(self.remote.methods), {
                'technical.'+op for op in ('evidence.select','evidence.read','prepare','status','result','abandon')
            } | {'methods.list'} | {'creation.'+op for op in ('admit','admit_music','prepare','start','status','stop','chunk','select','review','list','collect_output','methods')
            } | {'production.'+op for op in ('list','open','admit','create','update_brief','add_asset','update_asset',
                                           'add_reference','update_reference','link_take','select_take','chunk')}
              | {'production.' + op for op in MEDIA_OPERATIONS})
            self.assertEqual(self.rpc('status')['error'], 'TECHNICAL_ACCESS_UNAVAILABLE')
            self.assertEqual(self.rpc('status', {'authorized':True})['error'], 'TECHNICAL_OPERATION_UNAVAILABLE')
            runtime.unload(); runtime.unload()
        self.assertFalse(self.remote.facade_reads)
        self.assertFalse(self.remote.facade.calls)
        self.assertFalse(self.remote.root.exists())
        self.assertEqual(stdout.getvalue()+stderr.getvalue(), '')
        self.assertFalse(hasattr(self.ctx, '_manager'))

    def test_normal_creation_entry_remains_default_denied(self):
        _, runtime = self.load()
        handler = self.remote.tools['motion_studio_creation']['handler']
        result = json.loads(handler(dict(operation='status'), session_id='session-a', conversation_id='root-a'))
        self.assertEqual(result['error'], 'CREATION_ACCESS_UNAVAILABLE')
        self.assertIsNone(runtime.creation.runs)
        self.assertFalse(self.remote.root.exists())
        self.assertFalse(self.remote.facade_reads)

    def test_normal_production_entry_remains_separately_default_denied(self):
        _, runtime = self.load()
        handler = self.remote.tools['motion_studio_production']['handler']
        result = json.loads(handler(dict(operation='list'), session_id='session-a', conversation_id='root-a'))
        self.assertEqual(result['error'], 'PRODUCTION_ACCESS_UNAVAILABLE')
        self.assertIsNone(runtime.creation.store)
        self.assertFalse(self.remote.root.exists())
        self.assertFalse(self.remote.facade_reads)

    def test_packaged_relative_imports_and_public_facade_prepare_are_real(self):
        _, runtime = self.load()
        policy_type = importlib.import_module(self.key+'.studio.native.technical.runtime').TechnicalPolicy
        runtime.policy = policy_type(audience_accepted=True, revision='offline-only', create_store=True, route=route())
        selected = self.rpc('evidence.select', dict(expected=0, selection=selection()))
        self.assertFalse(self.remote.facade.calls)
        params = dict(command='a'*32, evidence=selected['id'], revision=1, template=selected['template'])
        row = self.rpc('prepare', params)
        for worker in runtime.service.workers: worker.join(5)
        result = self.rpc('result', dict(job=row['id']))
        self.assertEqual(result['state'], 'Proposal ready')
        self.assertFalse(result['result']['enabled'])
        self.assertFalse(result['result']['qualified'])
        self.assertEqual(self.rpc('prepare', params)['id'], row['id'])
        self.assertEqual(len(self.remote.facade.calls), 1)
        self.assertEqual(self.rpc('status', {'command':'a'*32})['id'], row['id'])
        self.assertIn('error', self.rpc('result', dict(job=row['id']), 'session-b'))
        self.assertFalse(any('.producer' in name or '.native.backend' in name for name in sys.modules if name.startswith(self.key+'.')))

    def test_metadata_api_is_separate_and_only_reports_unavailable(self):
        spec = importlib.util.spec_from_file_location('offline_dashboard', self.home/'dashboard/plugin_api.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from fastapi import FastAPI
        from tests.http_support import TestClient
        app = FastAPI();app.include_router(module.router, prefix='/api/plugins/motion-studio')
        with TestClient(app) as client:
            data = client.get('/api/plugins/motion-studio/capabilities').json()
            self.assertEqual(data['inference'], 'unverified-unavailable')
            self.assertEqual(data['private_media'], 'unavailable')
            self.assertEqual(client.post('/api/plugins/motion-studio/prepare', json={}).status_code, 404)
        self.assertFalse(self.remote.root.exists())

    def test_exact_contents_sources_dependencies_and_no_private_runtime(self):
        with zipfile.ZipFile(BUNDLE) as archive:
            names = archive.namelist();self.assertEqual(names, sorted(set(names)))
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, (1980,1,1,0,0,0))
                self.assertEqual(entry.external_attr >> 16, 0o100644)
            files = {name.removeprefix('motion-studio/'):archive.read(name) for name in names}
        content = json.loads(files.pop('CONTENTS.json'))
        self.assertEqual(set(content), set(files));check_content(files)
        for name, data in files.items(): self.assertEqual(content[name], dict(bytes=len(data), sha256=sha(data)))
        # Compare against the captured build inputs; the UI lane may edit the
        # checkout while this suite runs. Explicit external bundles use the checkout.
        sources = current_sources() if not os.environ.get('NATIVE_BUNDLE') else None
        for name, digest in json.loads(files['SOURCE.json']).items():
            data = sources[name] if sources is not None else (ROOT/name).read_bytes()
            self.assertEqual(sha(data), digest, name)
        self.assertEqual(json.loads(files['HOST-CONTRACT.json'])['commit'], HOST_COMMIT)
        deps = json.loads(files['Dependencies.json']);self.assertEqual(deps['build']['esbuild'], '0.28.2')
        self.assertIn('LICENSE', files)
        self.assertTrue({'plugin.yaml','__init__.py','desktop/plugin.js','dashboard/manifest.json','dashboard/plugin_api.py'} <= files.keys())
        self.assertFalse(any(name.startswith('studio/native/backend/') for name in files))
        self.assertIn('studio/runs/service.py', files)
        self.assertEqual([name for name in files if name.endswith('/audio.py')], ['studio/producer/music/audio.py'])
        measured = subprocess.run(['node','tools/js-spans.cjs','--stdin','desktop/plugin.js'], input=files['desktop/plugin.js'], capture_output=True, check=True,
            env=dict(os.environ, NODE_PATH=os.environ.get('NODE_PATH',
                str(Path.home()/'.local/lib/node_modules/xactions/node_modules'))))
        spans = json.loads(measured.stdout)
        self.assertTrue(spans)
        self.assertLessEqual(max(row['span'] for row in spans), 300)

    def test_content_gate_detects_representative_excluded_paths_and_sentinels(self):
        for files in ({'../outside':b''}, {'var/state/db':b''}, {'README.md':b'/home/example/private'},
                      {'studio/domain.py':b'CONTROLLED_TEST_SECRET'}, {'README.md':b'BEGIN PRIVATE KEY'}):
            with self.assertRaises(ValueError): check_content(files)
        check_content({'README.md':b'Public technical metadata only.'})
