"""Asset-first authoring through registered tools and durable project revisions."""
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from studio.project import ProjectStore
from studio.runtime import NativeRuntime
from studio.preproduction import ProductionTools


class PreproductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.tmp.cleanup)
        self.projects = ProjectStore(Path(self.tmp.name) / 'store')
        self.runtime = NativeRuntime(self.projects)
        self.tools = ProductionTools(self.runtime)
        self.pid = self.projects.dispatch({'action': 'create', 'name': 'Asset first',
            'request_id': str(uuid.uuid4())})['project_id']

    def call(self, tool, action='get', **kwargs):
        return self.tools.dispatch(tool, {'action': action, 'project_id': self.pid, **kwargs})

    def update(self, tool, value):
        revision = self.projects.dispatch({'action': 'open', 'project_id': self.pid})['project_revision']
        return self.call(tool, 'update', expected_revision=revision,
                         request_id=str(uuid.uuid4()), value=value)

    def library(self):
        return {'assessed': True, 'notes': 'No external media required.', 'requirements': []}

    def board(self):
        library = self.call('motion_asset_library')['data']['document']
        return {'title': 'Opening', 'asset_library_sha256': library['sha256'],
                'panels': [], 'review': {'status': 'draft', 'notes': ''}}

    def test_storyboard_requires_assessed_assets_and_real_panels(self):
        result = self.update('motion_storyboard', {'title': 'Premature',
            'asset_library_sha256': 'sha256:' + '0' * 64, 'panels': [],
            'review': {'status': 'draft', 'notes': ''}})
        self.assertFalse(result['ok'])
        self.assertIn(result['error']['code'], ('ASSETS_UNRESOLVED', 'LIMIT_EXCEEDED'))
        self.assertTrue(self.update('motion_asset_library', self.library())['ok'])
        board = self.board()
        self.assertFalse(self.update('motion_storyboard', board)['ok'])

    def test_library_missing_assets_cannot_be_marked_assessed(self):
        value = self.library()
        value['requirements'] = [{'requirement_id': 'hero', 'role': 'Hero image',
            'kind': 'image', 'required': True, 'status': 'missing',
            'assessment': '', 'acquisition': 'Source from supplied files.'}]
        self.assertFalse(self.update('motion_asset_library', value)['ok'])
        value['assessed'] = False
        self.assertTrue(self.update('motion_asset_library', value)['ok'])
        got = self.call('motion_asset_library')
        self.assertEqual(got['data']['missing_required'], ['hero'])

    def import_still(self):
        from test_assets import provenance
        from PIL import Image
        source = Path(self.tmp.name) / 'hero.png'
        Image.new('RGB', (320, 180), '#18354f').save(source)
        result = self.runtime.asset({'action': 'import', 'project_id': self.pid,
            'expected_revision': 1, 'request_id': str(uuid.uuid4()),
            'source': {'kind': 'local', 'path': str(source)}, 'label': 'Hero',
            'kind': 'image', 'provenance': provenance()})
        self.assertTrue(result['ok'], result)
        return result['data']['asset']['artifact']

    def test_full_workflow_revisions_visual_view_and_stale_board(self):
        pin = self.import_still()
        library = self.library()
        library['requirements'] = [{'requirement_id': 'hero', 'role': 'Opening image',
            'kind': 'image', 'required': True, 'status': 'ready', 'asset': pin,
            'assessment': '320x180 supplied still, inspected for opening layout.',
            'acquisition': 'Supplied local file'}]
        self.assertTrue(self.update('motion_asset_library', library)['ok'])
        board = self.board()
        panel = {'panel_id': 'opening', 'title': 'Opening', 'duration_frames': 90,
            'visual': pin, 'asset_requirements': ['hero'], 'narration': 'Hello',
            'on_screen_text': '<script>bad</script>', 'motion': 'Hold then fade',
            'transition': 'Cut', 'notes': 'Review spacing'}
        board['panels'] = [panel]
        accepted = self.update('motion_storyboard', board)
        self.assertTrue(accepted['ok'], accepted)
        revision = accepted['project_revision']
        reopened = ProductionTools(NativeRuntime(self.projects))
        got = reopened.dispatch('motion_storyboard', {'action': 'get', 'project_id': self.pid})
        self.assertEqual(got['data']['value']['panels'], [panel])
        view = self.call('motion_storyboard', 'view')
        self.assertTrue(view['ok'], view)
        html = Path(view['data']['path']).read_text()
        self.assertIn('data:image/png;base64,', html)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', html)
        self.assertNotIn('<script>bad', html)
        self.assertTrue(self.call('motion_asset_library', 'view')['ok'])
        library['notes'] = 'Asset selection assessment revised.'
        self.assertTrue(self.update('motion_asset_library', library)['ok'])
        self.assertTrue(self.call('motion_storyboard')['data']['stale'])
        self.assertEqual(self.call('motion_storyboard', revision=revision)['data']['value'], board)
        # Explicit unchanged resubmission is still an authoring action.
        self.assertFalse(self.update('motion_storyboard', board)['ok'])
        board['panels'][0]['motion'] = 'Revised motion on stale assets'
        self.assertFalse(self.update('motion_storyboard', board)['ok'])

    def test_registered_visual_without_library_assessment_is_rejected(self):
        pin = self.import_still()
        self.assertTrue(self.update('motion_asset_library', self.library())['ok'])
        board = self.board()
        board['panels'] = [{'panel_id': 'unassessed', 'title': 'Unassessed',
            'duration_frames': 30, 'visual': pin, 'asset_requirements': [],
            'narration': '', 'on_screen_text': '', 'motion': '', 'transition': '', 'notes': ''}]
        result = self.update('motion_storyboard', board)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['error']['code'], 'ASSETS_UNRESOLVED')

    def test_invalid_envelopes_no_effect_and_compare_and_swap(self):
        for args in (None, {}, {'action': 'get', 'project_id': self.pid, 'command': 'secret'}):
            result = self.tools.dispatch('motion_asset_library', args)
            self.assertFalse(result['ok'])
            self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')
        request = {'action': 'update', 'project_id': self.pid, 'expected_revision': 1,
                   'request_id': str(uuid.uuid4()), 'value': self.library()}
        first = self.tools.dispatch('motion_asset_library', request)
        self.assertTrue(first['ok'], first)
        self.assertEqual(first, self.tools.dispatch('motion_asset_library', request))
        request['request_id'] = str(uuid.uuid4())
        self.assertEqual(self.tools.dispatch('motion_asset_library', request)['error']['code'], 'REVISION_CONFLICT')

    def test_generic_project_update_cannot_bypass_asset_assessment(self):
        pin = self.import_still()
        panel = {'panel_id': 'opening', 'title': 'Opening', 'duration_frames': 30,
            'visual': pin, 'asset_requirements': [], 'narration': '',
            'on_screen_text': '', 'motion': 'Hold', 'transition': 'Cut', 'notes': ''}
        result = self.projects.dispatch({'action': 'update', 'project_id': self.pid,
            'expected_revision': 2, 'request_id': str(uuid.uuid4()),
            'changes': [{'op': 'set_storyboard', 'value': {
                'title': 'Unassessed', 'asset_library_sha256': 'sha256:' + '0' * 64,
                'panels': [panel], 'review': {'status': 'draft', 'notes': ''}}}]})
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['error']['code'], 'ASSETS_UNRESOLVED')
        self.assertEqual(self.call('motion_storyboard')['project_revision'], 2)
        self.assertIsNone(self.call('motion_storyboard')['data']['value'])

    def test_registered_host_handlers_save_and_read_both_tools(self):
        from unittest.mock import patch
        from test_registration import Context
        from studio.tools import register_tools
        pin = self.import_still()
        context = Context()
        register_tools(context)
        with patch('studio.project.ProjectStore', return_value=self.projects):
            asset_tool = context.tools['motion_asset_library']['handler']
            library = self.library()
            library['requirements'] = [{'requirement_id': 'hero', 'role': 'Opening',
                'kind': 'image', 'required': True, 'status': 'ready', 'asset': pin,
                'assessment': 'Inspected opening still.', 'acquisition': 'Local fixture'}]
            result = json.loads(asset_tool({'action': 'update', 'project_id': self.pid,
                'expected_revision': 2, 'request_id': str(uuid.uuid4()),
                'value': library}))
            self.assertTrue(result['ok'], result)
            got = json.loads(asset_tool({'action': 'get', 'project_id': self.pid}))
            self.assertTrue(got['data']['ready'])
            board = {'title': 'Registered path',
                'asset_library_sha256': got['data']['document']['sha256'],
                'panels': [{'panel_id': 'opening', 'title': 'Opening',
                    'duration_frames': 30, 'visual': pin, 'asset_requirements': [],
                    'narration': '', 'on_screen_text': '', 'motion': 'Hold',
                    'transition': 'Cut', 'notes': ''}],
                'review': {'status': 'feedback', 'notes': 'Saved host feedback'}}
            board_tool = context.tools['motion_storyboard']['handler']
            result = json.loads(board_tool({'action': 'update', 'project_id': self.pid,
                'expected_revision': result['project_revision'],
                'request_id': str(uuid.uuid4()), 'value': board}))
            self.assertTrue(result['ok'], result)
            got = json.loads(board_tool({'action': 'view', 'project_id': self.pid}))
            self.assertTrue(got['ok'], got)
            self.assertEqual(got['data']['value'], board)
            self.assertTrue(Path(got['data']['path']).is_file())

    def test_asset_library_rejects_unregistered_and_mismatched_artifacts(self):
        pin = self.import_still()
        requirement = {'requirement_id': 'hero', 'role': 'Opening', 'kind': 'audio',
            'required': True, 'status': 'ready', 'asset': pin,
            'assessment': 'Inspected', 'acquisition': 'Supplied'}
        library = self.library()
        library['requirements'] = [requirement]
        result = self.update('motion_asset_library', library)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['error']['code'], 'INVALID_ARGUMENT')
        requirement['kind'] = 'image'
        requirement['asset'] = dict(pin, artifact_id='art_' + str(uuid.uuid4()))
        result = self.update('motion_asset_library', library)
        self.assertFalse(result['ok'], result)
        self.assertEqual(self.call('motion_asset_library')['project_revision'], 2)


if __name__ == '__main__':
    unittest.main()
