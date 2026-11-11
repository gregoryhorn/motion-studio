"""CF-NRP1 RPC envelope: transport consistency, not new backend authority."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.production_support import production_setup
from tests.producer_support import effects


class ProfileEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx,self.creation,self.production,self.binding = production_setup(Path(self.temp.name))
        self.addCleanup(self.creation.unload)

    def snapshot(self):
        assert self.creation.store is not None
        with self.creation.store.transaction() as db:
            return list(db.iterdump())

    def test_matching_and_absent_envelope_list_same_authorized_state_no_effects(self):
        before = self.snapshot()
        for namespace in ('creation','production'):
            handler = self.ctx.methods[namespace+'.list']
            ordinary = handler({},session_id='canonical-root')
            self.assertNotIn('error',ordinary)
            self.assertEqual(handler(dict(profile=self.ctx.profile_name,session_id='canonical-root'),
                session_id='canonical-root'),ordinary)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(effects(self.binding),[])

    def test_bad_envelope_and_session_refuse_before_service_acquisition(self):
        for namespace,runtime in (('creation',self.creation),('production',self.production)):
            handler = self.ctx.methods[namespace+'.list']
            for profile in ('other','', ' ',None,False,123,[],{}):
                with self.subTest(namespace=namespace,profile_type=type(profile).__name__), \
                        patch.object(runtime,'acquire',side_effect=AssertionError('Must reject before service')) as acquire:
                    self.assertEqual(handler(dict(profile=profile),session_id='canonical-root'),
                                     dict(error=namespace.upper()+'_SCOPE_DENIED'))
                    acquire.assert_not_called()
            for payload,session in ((dict(profile=self.ctx.profile_name,session_id='forged'),'canonical-root'),
                                    (dict(profile=self.ctx.profile_name),None)):
                with patch.object(runtime,'acquire',side_effect=AssertionError('No service')) as acquire:
                    self.assertIn('error',handler(payload,session_id=session));acquire.assert_not_called()
        self.assertEqual(effects(self.binding),[])

    def test_strict_operations_tools_and_root_authority_remain_closed(self):
        before = self.snapshot()
        for namespace in ('creation','production'):
            handler = self.ctx.methods[namespace+'.list']
            self.assertEqual(handler(dict(profile=self.ctx.profile_name,extra='refuse'),session_id='canonical-root'),
                dict(error='INVALID_'+namespace.upper()+'_INPUT'))
            self.assertIn('error',handler(dict(profile=self.ctx.profile_name),session_id='other-root'))
            tool = self.ctx.tools['motion_studio_'+namespace][1]
            self.assertIn('error',json.loads(tool(dict(operation='status' if namespace=='creation' else 'list',
                profile=self.ctx.profile_name),session_id='physical',conversation_id='canonical-root')))
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(effects(self.binding),[])


if __name__ == '__main__':
    unittest.main()
