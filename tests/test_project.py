"""B03 controlled filesystem fixtures; no active-profile writes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import concurrent.futures

from studio.contracts import default_gate_policy, empty_brief, project_tool_schema, digest
from studio.project import ManagedFS

from studio.project import ProjectStore


def rid():
    return str(uuid.uuid4())


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'], prefix='motion-b03-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'profile' / 'plugin-data' / 'motion-studio'
        self.store = ProjectStore(root=self.root)

    def call(self, **args):
        return self.store.dispatch(args)

    def create(self, **kw):
        return self.call(action='create', request_id=rid(), name='A production', **kw)

    def test_noop_documents_do_not_advance_and_action_scoped_requests(self):
        request = rid()
        created = self.call(action='create', request_id=request, name='Scoped requests')
        pid = created['project_id']
        brief_pin = next(p for p in created['data']['documents'] if p['kind'] == 'brief')
        result = self.update(pid, request_id=request, changes=[{'op': 'set_stage', 'value': 'concept'}, {'op': 'set_brief', 'value': empty_brief()}])
        self.assertTrue(result['ok'], result)
        self.assertEqual([p['kind'] for p in result['data']['changed']], ['settings'])
        opened = self.call(action='open', project_id=pid)
        self.assertIn(brief_pin, opened['data']['documents'])
        noop_request = rid()
        noop = self.update(pid, 2, request_id=noop_request)
        self.assertTrue(noop['ok'], noop)
        self.assertEqual(noop['project_revision'], 2)
        self.assertEqual(noop['data']['changed'], [])
        self.assertTrue(self.update(pid, 2, changes=[{'op': 'set_stage', 'value': 'review'}])['ok'])
        replay = self.update(pid, 2, request_id=noop_request)
        self.assertEqual(replay['data'], noop['data'])
        changed = self.update(pid, 2, request_id=noop_request, changes=[{'op': 'set_stage', 'value': 'delivery'}])
        self.assertEqual(changed['error']['code'], 'IDEMPOTENCY_CONFLICT')

    def test_create_restart_and_read_only_open(self):
        result = self.create()
        self.assertTrue(result['ok'], result)
        project = result['data']['project']
        self.assertEqual(project['revision'], 1)
        self.assertEqual(project['rate'], {'num': 30, 'den': 1})
        self.assertEqual(project['sample_rate'], 48000)
        self.assertEqual(len(result['data']['documents']), 7)
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        reopened = ProjectStore(root=self.root).dispatch({'action': 'open', 'project_id': project['project_id']})
        self.assertEqual(reopened['data']['project'], project)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_empty_reads_do_not_create_root(self):
        result = self.call(action='list')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['items'], [])
        self.assertFalse(self.root.exists())

    def update(self, pid, revision=1, request_id=None, changes=None):
        return self.call(action='update', project_id=pid, expected_revision=revision,
                         request_id=request_id or rid(), changes=changes or [{'op': 'set_stage', 'value': 'concept'}])

    def test_cas_replay_and_immutable_history(self):
        created = self.create()['data']['project']
        pid = created['project_id']
        before = {str(p): p.read_bytes() for p in (self.root / 'projects' / pid / 'revisions' / '1').rglob('*') if p.is_file()}
        request = rid()
        committed = self.update(pid, request_id=request)
        self.assertTrue(committed['ok'], committed)
        self.assertEqual(committed['project_revision'], 2)
        self.assertEqual(self.update(pid, request_id=request)['data'], committed['data'])
        self.assertEqual(self.update(pid)['error']['code'], 'REVISION_CONFLICT')
        conflict = self.update(pid, request_id=request, changes=[{'op': 'set_stage', 'value': 'review'}])
        self.assertEqual(conflict['error']['code'], 'IDEMPOTENCY_CONFLICT')
        old = self.call(action='open', project_id=pid, revision=1)
        self.assertEqual(old['data']['project'], created)
        self.assertEqual(before, {str(p): p.read_bytes() for p in (self.root / 'projects' / pid / 'revisions' / '1').rglob('*') if p.is_file()})

    def test_create_defaults_replay_after_restart_and_index_loss(self):
        request = rid()
        args = {'action': 'create', 'request_id': request, 'name': 'Unicode \u03b1'}
        original = self.store.dispatch(args)
        pid = original['project_id']
        (self.root / 'projects' / pid / 'project.json').unlink()
        replay = ProjectStore(root=self.root).dispatch({**args, 'rate': {'num': 30, 'den': 1}, 'sample_rate': 48000, 'brief': empty_brief()})
        self.assertEqual(replay['data'], original['data'])
        self.assertTrue(self.call(action='open', project_id=pid)['ok'])
        self.assertEqual(self.call(action='list')['data']['total'], 1)
        self.assertEqual(self.store.dispatch({**args, 'name': 'different'})['error']['code'], 'IDEMPOTENCY_CONFLICT')

    def test_strict_request_validation_before_storage(self):
        samples = [
            {'action': 'bad'}, {'action': 'create', 'request_id': rid(), 'name': 'x', 'approved': True},
            {'action': 'create', 'request_id': rid().upper(), 'name': 'x'},
            {'action': 'create', 'request_id': rid(), 'name': ''},
            {'action': 'create', 'request_id': rid(), 'name': 'x', 'sample_rate': True},
            {'action': 'create', 'request_id': rid(), 'name': 'x', 'rate': {'num': 60, 'den': 2}},
            {'action': 'create', 'request_id': rid(), 'name': 'x', 'brief': {'message': 'incomplete'}},
            {'action': 'create', 'request_id': rid(), 'name': 'x', 'rate': {'num': 1.0, 'den': 1}},
            {'action': 'open', 'project_id': 'prj_../../escape'},
            {'action': 'list', 'limit': 101}, {'action': 'list', 'name_contains': None},
            {'action': 'create', 'request_id': rid(), 'name': 'x', 'sample_rate': 9007199254740992},
        ]
        for args in samples:
            with self.subTest(args=args):
                result = self.store.dispatch(args)
                self.assertFalse(result['ok'], result)
                self.assertFalse(self.root.exists())
        schema = project_tool_schema()['parameters']
        self.assertTrue(all(s.get('additionalProperties') is False for s in schema['oneOf']))

    def test_scene_transaction_linking_removal_and_duplicate_writes(self):
        pid = self.create()['project_id']
        scene = {'new_scene_key': 'opening', 'label': 'Opening', 'duration_frames': 60, 'canvas': {'width_px': 1920, 'height_px': 1080}, 'assets': [], 'layout': [], 'safe_zones': [], 'motion_intent': 'slide', 'camera_intent': '', 'authored_source': None, 'source_format': None, 'source_runtime': None}
        timeline = {'duration_frames': 60, 'tracks': [{'track_id': 'main', 'kind': 'video', 'items': [{'item_id': 'first', 'start_frame': 0, 'end_frame': 60, 'subject': {'kind': 'scene', 'new_scene_key': 'opening'}}]}]}
        result = self.update(pid, changes=[{'op': 'set_timeline', 'value': timeline}, {'op': 'put_scene', 'value': scene}])
        self.assertTrue(result['ok'], result)
        sid = next(p['id'] for p in result['data']['changed'] if p['kind'] == 'scene')
        removed = self.update(pid, 2, changes=[{'op': 'remove_scene', 'scene_id': sid}])
        self.assertEqual(removed['error']['code'], 'INVALID_GRAPH')
        dup = self.update(pid, 2, changes=[{'op': 'set_stage', 'value': 'review'}, {'op': 'set_stage', 'value': 'delivery'}])
        self.assertEqual(dup['error']['code'], 'INVALID_ARGUMENT')
        removed = self.update(pid, 2, changes=[{'op': 'remove_scene', 'scene_id': sid}, {'op': 'set_timeline', 'value': {'duration_frames': 0, 'tracks': []}}])
        self.assertTrue(removed['ok'], removed)
        self.assertEqual(self.call(action='status', project_id=pid)['data']['counts']['scenes'], 0)

    def test_atomic_failed_pointer_replace_and_orphan_revision(self):
        pid = self.create()['project_id']
        real = os.replace
        def interrupt(src, dst, **kw):
            if dst == 'project.json':
                raise OSError(28, 'controlled disk full')
            return real(src, dst, **kw)
        with patch('studio.project.os.replace', side_effect=interrupt):
            result = self.update(pid)
        self.assertEqual(result['error']['code'], 'DISK_FULL')
        self.assertEqual(self.call(action='open', project_id=pid)['project_revision'], 1)
        self.assertEqual(self.call(action='open', project_id=pid, revision=2)['error']['code'], 'NOT_FOUND')
        next_result = self.update(pid)
        self.assertTrue(next_result['ok'], next_result)
        self.assertEqual(next_result['project_revision'], 3)

    def test_frozen_pagination_and_scope_binding(self):
        for _ in range(3):
            self.create()
        first = self.call(action='list', limit=1, name_contains='production')['data']
        self.create()
        second = self.call(action='list', cursor=first['next_cursor'])['data']
        self.assertEqual(second['total'], 3)
        self.assertNotEqual(first['items'][0]['project_id'], second['items'][0]['project_id'])
        bad = self.call(action='list', cursor=first['next_cursor'], limit=2)
        self.assertEqual(bad['error']['code'], 'CURSOR_MISMATCH')
        other = ProjectStore(root=Path(self.tmp.name) / 'other')
        self.assertEqual(other.dispatch({'action': 'list', 'cursor': first['next_cursor']})['error']['code'], 'CURSOR_MISMATCH')
        bounded = ProjectStore(root=self.root, snapshot_limit=1)
        bounded.dispatch({'action': 'list'})
        self.assertEqual(self.call(action='list', cursor=first['next_cursor'])['error']['code'], 'CURSOR_EXPIRED')

    def test_symlink_file_and_directory_escape_rejected(self):
        pid = self.create()['project_id']
        sentinel = Path(self.tmp.name) / 'sentinel'
        sentinel.write_text('unchanged')
        pointer = self.root / 'projects' / pid / 'project.json'
        pointer.unlink()
        pointer.symlink_to(sentinel)
        self.assertEqual(self.call(action='open', project_id=pid)['error']['code'], 'PATH_UNSAFE')
        self.assertEqual(sentinel.read_text(), 'unchanged')
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        link = Path(self.tmp.name) / 'alias'
        link.symlink_to(outside, target_is_directory=True)
        self.assertEqual(ProjectStore(root=link / 'child').dispatch({'action': 'create', 'request_id': rid(), 'name': 'x'})['error']['code'], 'PATH_UNSAFE')
        self.assertFalse((outside / 'child').exists())

    def test_two_writers_do_not_lose_update(self):
        pid = self.create()['project_id']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.update(pid), range(2)))
        self.assertEqual(sum(r['ok'] for r in results), 1, results)
        self.assertIn(next(r['error']['code'] for r in results if not r['ok']), ['LOCK_BUSY', 'REVISION_CONFLICT'])
        self.assertEqual(self.call(action='open', project_id=pid)['project_revision'], 2)

    def test_profile_resolver_is_lazy_and_follows_switch(self):
        homes = [Path(self.tmp.name) / 'first', Path(self.tmp.name) / 'second']
        current = [homes[0]]
        from types import ModuleType
        import sys
        constants = ModuleType('hermes_constants')
        setattr(constants, 'get_hermes_home', lambda: current[0])
        plugins = ModuleType('plugins')
        storage = ModuleType('plugins.plugin_storage')
        calls = []
        def sdk(name):
            calls.append((current[0], name))
            root = current[0] / 'plugin-data' / name
            root.mkdir(parents=True, exist_ok=True)
            return root
        setattr(storage, 'plugin_data_dir', sdk)
        with patch.dict(sys.modules, {'hermes_constants': constants, 'plugins': plugins, 'plugins.plugin_storage': storage}):
            store = ProjectStore()
            self.assertTrue(store.dispatch({'action': 'list'})['ok'])
            self.assertEqual(calls, [])
            first = store.dispatch({'action': 'create', 'request_id': rid(), 'name': 'same'})
            self.assertTrue(first['ok'], first)
            current[0] = homes[1]
            self.assertEqual(store.dispatch({'action': 'open', 'project_id': first['project_id']})['error']['code'], 'NOT_FOUND')
            self.assertFalse(homes[1].exists())
            second = store.dispatch({'action': 'create', 'request_id': rid(), 'name': 'same'})
            self.assertTrue(second['ok'], second)
            self.assertNotEqual(first['project_id'], second['project_id'])
            self.assertEqual(len(calls), 2)

    def test_new_major_and_corrupt_document_rejected_without_rewriting(self):
        pid = self.create()['project_id']
        pointer = self.root / 'projects' / pid / 'project.json'
        data = json.loads(pointer.read_text())
        data['schema'] = 'motion/v2/project'
        pointer.write_text(json.dumps(data))
        before = pointer.read_bytes()
        self.assertEqual(self.call(action='open', project_id=pid)['error']['code'], 'SCHEMA_UNSUPPORTED')
        self.assertEqual(pointer.read_bytes(), before)

    def test_actual_process_interruption_and_restart(self):
        import subprocess
        import sys
        pid = self.create()['project_id']
        script = '''import json, os, sys
from studio.project import ProjectStore, ManagedFS
real = ManagedFS.write
def crash(self, relative, value, replace=False):
    real(self, relative, value, replace)
    if relative.endswith('/transaction.json'):
        os._exit(97)
ManagedFS.write = crash
ProjectStore(root=sys.argv[1]).dispatch(json.loads(sys.argv[2]))
'''
        args = {'action': 'update', 'project_id': pid, 'expected_revision': 1, 'request_id': rid(), 'changes': [{'op': 'set_stage', 'value': 'concept'}]}
        child = subprocess.run([sys.executable, '-B', '-c', script, str(self.root), json.dumps(args)], capture_output=True, timeout=30)
        self.assertEqual(child.returncode, 97, child.stderr)
        result = self.call(action='open', project_id=pid)
        self.assertEqual(result['project_revision'], 1)
        self.assertEqual(result['data']['project']['stage'], 'intake')
        rerun = subprocess.run([sys.executable, '-B', '-c', 'import json,sys; from studio.project import ProjectStore; print(json.dumps(ProjectStore(root=sys.argv[1]).dispatch(json.loads(sys.argv[2]))))', str(self.root), json.dumps(args)], capture_output=True, text=True, timeout=30)
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        updated = json.loads(rerun.stdout)
        self.assertTrue(updated['ok'], updated)
        self.assertEqual(updated['project_revision'], 3)
        replay = self.store.dispatch(args)
        self.assertEqual(replay['data'], updated['data'])

    def test_create_response_loss_after_receipt_commit(self):
        request = rid()
        args = {'action': 'create', 'request_id': request, 'name': 'Committed once'}
        real = ManagedFS.write
        def fail_index(fs, relative, value, replace=False):
            if relative.endswith('/project.json') and '/documents/' not in relative:
                raise OSError(28, 'controlled lost response')
            return real(fs, relative, value, replace)
        with patch.object(ManagedFS, 'write', fail_index), self.assertLogs('studio.project', level='ERROR'):
            result = self.store.dispatch(args)
        self.assertFalse(result['ok'])
        self.assertEqual(self.call(action='list')['data']['total'], 1)
        replay = self.store.dispatch(args)
        self.assertTrue(replay['ok'], replay)
        self.assertEqual(self.call(action='list')['data']['items'][0], replay['data']['project'])

    def test_remaining_update_types_and_fail_closed_references(self):
        pid = self.create()['project_id']
        brief = empty_brief()
        brief['message'] = 'A real message'
        brand = {'colors': {'accent': '#FA1020'}, 'fonts': [], 'spacing_px': {'small': 8}, 'motion_tokens': {'fast': {'duration_frames': 8, 'easing': 'ease_out'}}, 'logo_assets': [], 'reference_assets': []}
        policy = {'remote': 'selected_only', 'allowed_destinations': ['https://example.invalid'], 'paid': 'explicit', 'max_concurrent_nodes': 2, 'retain_generated_assets': True, 'budget': {'currency': 'USD', 'amount': '1.25'}}
        bindings = {'selected_adapter_ids': ['local.renderer'], 'preferences': {'scene.render': ['local.renderer']}, 'pins': {'opening': 'local.renderer'}}
        revision = 1
        for op, value in [('set_brief', brief), ('set_brand', brand), ('set_bindings', bindings), ('set_execution_policy', policy)]:
            with self.subTest(op=op):
                result = self.update(pid, revision, changes=[{'op': op, 'value': value}])
                self.assertTrue(result['ok'], result)
                revision = result['project_revision']
        bad = self.update(pid, revision, changes=[{'op': 'set_sample_rate', 'value': 44100}])
        self.assertFalse(bad['ok'])
        bad = self.update(pid, revision, changes=[{'op': 'set_bindings', 'value': {'selected_adapter_ids': [], 'preferences': {}, 'pins': {'scene': 'not.selected'}}}])
        self.assertFalse(bad['ok'])
        brief['reference_assets'] = [{'artifact_id': 'art_' + rid(), 'sha256': 'sha256:' + '0' * 64}]
        bad = self.update(pid, revision, changes=[{'op': 'set_brief', 'value': brief}])
        self.assertEqual(bad['error']['code'], 'NOT_FOUND')
        self.assertEqual(self.call(action='open', project_id=pid)['project_revision'], revision)

    def test_cursor_expiration_and_snapshot_restart(self):
        now = [1000]
        store = ProjectStore(root=self.root, snapshot_ttl=1, clock=lambda: now[0])
        self.create()
        self.create()
        page = store.dispatch({'action': 'list', 'limit': 1})['data']
        self.assertEqual(page['expires_at'], '1970-01-01T00:16:41.000000Z')
        mismatch = store.dispatch({'action': 'status', 'project_id': page['items'][0]['project_id'], 'section': 'scenes', 'cursor': page['next_cursor']})
        self.assertEqual(mismatch['error']['code'], 'CURSOR_MISMATCH')
        now[0] = 1002
        self.assertEqual(store.dispatch({'action': 'list', 'cursor': page['next_cursor']})['error']['code'], 'CURSOR_EXPIRED')

    def test_corrupt_hash_and_wrong_project_document_rejected(self):
        from studio.contracts import canonical
        result = self.create()
        pid = result['project_id']
        path = self.root / 'projects' / pid / 'revisions' / '1' / 'documents' / 'brief' / 'project.json'
        original = path.read_bytes()
        record = json.loads(original)
        record['value']['message'] = 'Changed without a commit'
        path.write_bytes(canonical(record))
        self.assertEqual(self.call(action='open', project_id=pid)['error']['code'], 'HASH_MISMATCH')
        record['project_id'] = 'prj_' + rid()
        path.write_bytes(canonical(record))
        self.assertEqual(self.call(action='open', project_id=pid)['error']['code'], 'WRONG_PROJECT')
        path.write_bytes(original)
        self.assertTrue(self.call(action='open', project_id=pid)['ok'])
        self.assertEqual(canonical({'\U0001f600': 1, '\ue000': 2}), '{"\U0001f600":1,"\ue000":2}'.encode())

    def test_timestamp_calendar_and_relative_bundle_path(self):
        from studio.contracts import ContractError, STAMP, safe_relative, validate
        with self.assertRaises(ContractError):
            validate('2026-13-01T00:00:00Z', STAMP)
        for path in ['../secret', '/etc/passwd', 'C:/secret', 'a//b', 'a/./b', 'a\\b']:
            with self.subTest(path=path), self.assertRaises(ContractError):
                safe_relative(path)
        validate('2026-11-05T17:00:00.123456Z', STAMP)

    def test_disk_schema_matches_handler_schema(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas' / 'project-request.json').read_text())
        self.assertEqual(schema, project_tool_schema()['parameters'])

    def test_profile_document_pin_and_variant(self):
        pid = self.create()['project_id']
        constraints = {'allowed_containers': ['mp4'], 'allowed_video_codecs': ['h264'], 'allowed_audio_codecs': [], 'width_px': 1920, 'height_px': 1080, 'rate': {'num': 30, 'den': 1}, 'max_duration_frames': None, 'max_bytes': None, 'alpha': 'forbidden', 'caption_modes': ['none'], 'loudness_lufs': None, 'loudness_tolerance_lu': None, 'true_peak_dbtp': None}
        profile = {'profile_id': 'web', 'version': '1', 'label': 'User supplied', 'sources': [], 'constraints': constraints, 'valid_until': None}
        result = self.update(pid, changes=[{'op': 'put_delivery_profile', 'value': profile}])
        self.assertTrue(result['ok'], result)
        pin = result['data']['changed'][0]
        variant = {'variant_id': 'landscape', 'label': 'Landscape', 'width_px': 1920, 'height_px': 1080, 'rate': {'num': 30, 'den': 1}, 'duration_frames': 60, 'container': 'mp4', 'video_codec': 'h264', 'pixel_format': 'yuv420p', 'color': {'primaries': 'bt709', 'transfer': 'bt709', 'matrix': 'bt709', 'range': 'limited'}, 'alpha': 'none', 'audio': {'mode': 'none', 'sample_rate': None, 'channels': None, 'codec': None, 'loudness_lufs': None, 'true_peak_dbtp': None}, 'captions': 'none', 'profile': pin, 'overrides': {'reason': ''}}
        result = self.update(pid, 2, changes=[{'op': 'set_variants', 'value': [variant]}])
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.call(action='status', project_id=pid, section='variants')['data']['items'], [variant])
        profile['label'] = 'Revised profile'
        result = self.update(pid, 3, changes=[{'op': 'put_delivery_profile', 'value': profile}])
        self.assertTrue(result['ok'], result)

    def test_gate_policy_separate_document_and_core_revision(self):
        result = self.create()
        pid = result['project_id']
        pins = [p for p in result['data']['documents'] if p['kind'] == 'gate_policy']
        self.assertEqual(len(pins), 1)
        policy = default_gate_policy()
        policy['caption_parity'] = {'metric': 'mae', 'tolerance': '2', 'require_visual': True}
        result = self.update(pid, changes=[{'op': 'set_gate_policy', 'value': policy}])
        self.assertTrue(result['ok'], result)
        pins = [p for p in result['data']['changed'] if p['kind'] == 'gate_policy']
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]['revision'], 2)
        alternate = default_gate_policy()
        alternate['policy_id'] = 'alternate'
        result = self.update(pid, 2, changes=[{'op': 'set_gate_policy', 'value': alternate}])
        self.assertTrue(result['ok'], result)
        pin = next(p for p in result['data']['changed'] if p['kind'] == 'gate_policy')
        self.assertEqual(pin['id'], 'alternate')
        self.assertEqual(pin['revision'], 1)
