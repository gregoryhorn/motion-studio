"""Synthetic regressions for source authority across Creation and Production."""
import base64
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from studio.domain import Fault
from studio.persistence.primitives import identity
from tests.production_support import production_setup, make_take
from tests.music_support import attach, settle, effect_count


class MusicAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctx, self.creation, self.production, self.binding = production_setup(self.root)
        self.addCleanup(self.creation.unload)
        attach(self.creation, self.root/'music')
        self.ctx.methods['creation.admit_music']({}, session_id='canonical-root')
        self.original_policy = self.creation.policy
        self.source = self.tool('creation', 'prepare', dict(schema_version=2, kind='Music',
            direction='Synthetic private Music authority probe', seconds=10))
        self.assertNotIn('error', self.source, self.source)
        command = {k:self.source[k] for k in ('request','revision','command','run')}
        self.tool('creation', 'start', command); settle(self.creation)
        self.assertEqual(self.tool('creation','status')['state'], 'Ready for review')
        self.current = self.tool('production','create',dict(command=identity(), title='Synthetic Music reuse',
            kinds=['Music'], brief=dict(text='Synthetic review-only brief')))
        self.asset = self.current['current']['assets'][0]['id']
        self.link_payload = self.change(asset=self.asset, **self.ids())
        self.current = self.rpc('production','link_take',self.link_payload)
        self.current = self.rpc('production','select_take',self.change(asset=self.asset, **self.ids()))
        self.current = self.rpc('production','add_reference',self.change(label='Synthetic Music reference', **self.ids()))
        self.assertNotIn('error',self.current,self.current)
        self.reference = self.current['current']['references'][0]['id']
        self.service = self.production.acquire()
        self.bytes, _ = self.creation.service.assets.retrieve(self.source['candidate'])
        self.media = {p.name:p.read_bytes() for p in (self.creation.store.home/'media').iterdir()}

    def rpc(self, namespace, operation, payload=None):
        return self.ctx.methods[namespace+'.'+operation](payload or {}, session_id='canonical-root')

    def tool(self, namespace, operation, payload=None):
        handler = self.ctx.tools['motion_studio_'+namespace][1]
        return json.loads(handler(dict(operation=operation, **(payload or {})),
            session_id='synthetic-segment', conversation_id='canonical-root'))

    def ids(self): return dict(request=self.source['request'],take=self.source['candidate'])

    def change(self, **values):
        row = self.current['current']
        return dict(command=identity(), production=row['id'], expected=row['revision'], **values)

    def chunk(self):
        return dict(production=self.current['current']['id'],asset=self.asset,offset=0,**self.ids())

    def revoke(self):
        self.creation.policy = replace(self.original_policy,
            music=replace(self.original_policy.music, prepare=False,effects=False))

    def revise(self):
        self.creation.policy = replace(self.original_policy,
            music=replace(self.original_policy.music,revision='new-music-policy'))
        result = self.rpc('creation','admit_music')
        self.assertTrue(result['admitted'])

    def snapshot(self):
        with self.creation.store.transaction() as db:
            return list(db.iterdump())

    def unchanged(self, snapshot):
        self.assertEqual(self.snapshot(),snapshot)
        self.assertEqual({p.name:p.read_bytes() for p in (self.creation.store.home/'media').iterdir()},self.media)
        self.assertEqual(effect_count(self.creation),1)

    def test_p1_production_list_and_chunk_refuse_revoked_music(self):
        self.revoke(); before=self.snapshot()
        self.assertEqual(self.rpc('creation','list'),dict(error='MUSIC_SCOPE_REVIEW_REQUIRED'))
        self.assertEqual(self.rpc('production','list'),dict(error='MUSIC_SCOPE_REVIEW_REQUIRED'))
        self.assertEqual(self.rpc('production','chunk',self.chunk()),dict(error='MUSIC_SCOPE_REVIEW_REQUIRED'))
        self.unchanged(before)

    def test_p2_saved_revision_refuses_creation_chunk_review_select(self):
        self.revise(); before=self.snapshot()
        self.assertEqual(self.tool('creation','status'),dict(error='MUSIC_POLICY_CHANGED'))
        for operation,payload in (('chunk',dict(offset=0,**self.ids())),
                ('review',dict(command=identity(),outcome='Needs work',**self.ids())),
                ('select',dict(command=identity(),revision=1,**self.ids()))):
            with self.subTest(operation=operation):
                self.assertEqual(self.rpc('creation',operation,payload),dict(error='MUSIC_POLICY_CHANGED'))
        self.unchanged(before)

    def test_records_available_projection_and_take_share_music_authority(self):
        self.revoke()
        with self.creation.store.transaction() as db:
            operations = [lambda:self.service.records.available(db,'canonical-root'),
                lambda:self.service.records.projection(db,self.current['current']['id']),
                lambda:self.service.records.take(db,'canonical-root',**self.ids())]
            for operation in operations:
                with self.assertRaises(Fault) as denied: operation()
                self.assertEqual(denied.exception.code,'MUSIC_SCOPE_REVIEW_REQUIRED')

    def test_reference_link_selection_open_and_replay_reauthorize(self):
        for deny,code in ((self.revoke,'MUSIC_SCOPE_REVIEW_REQUIRED'),(self.revise,'MUSIC_POLICY_CHANGED')):
            deny();before=self.snapshot()
            operations = [('open',dict(production=self.current['current']['id'])),
                ('link_take',self.link_payload),
                ('link_take',self.change(asset=self.asset,**self.ids())),
                ('select_take',self.change(asset=self.asset,**self.ids())),
                ('add_reference',self.change(label='Must not add',**self.ids())),
                ('update_reference',self.change(reference=self.reference,label='Must not replace',**self.ids()))]
            for operation,payload in operations:
                with self.subTest(code=code,operation=operation):
                    self.assertEqual(self.rpc('production',operation,payload),dict(error=code))
            self.unchanged(before)
            self.creation.policy=self.original_policy;self.rpc('creation','admit_music')

    def test_creation_and_production_inflight_read_revocation_or_revision(self):
        retrieve=self.creation.service.assets.retrieve
        for namespace in ('creation','production'):
            for deny,code in ((self.revoke,'MUSIC_SCOPE_REVIEW_REQUIRED'),(self.revise,'MUSIC_POLICY_CHANGED')):
                def changed(take):
                    result=retrieve(take);deny();return result
                payload = dict(offset=0,**self.ids()) if namespace=='creation' else self.chunk()
                with patch.object(self.creation.service.assets,'retrieve',side_effect=changed):
                    self.assertEqual(self.rpc(namespace,'chunk',payload),dict(error=code))
                self.creation.policy=self.original_policy;self.rpc('creation','admit_music')
        self.assertEqual(effect_count(self.creation),1)

    def test_authorized_exact_bytes_and_effects_only_revocation_preserve_access(self):
        self.creation.policy=replace(self.original_policy,music=replace(self.original_policy.music,effects=False))
        for namespace,payload in (('creation',dict(offset=0,**self.ids())),('production',self.chunk())):
            data=bytearray()
            while len(data)<len(self.bytes):
                row=self.rpc(namespace,'chunk',dict(payload,offset=len(data)))
                self.assertNotIn('error',row,row)
                self.assertEqual(row['total'],len(self.bytes));data.extend(base64.b64decode(row['bytes']))
            self.assertEqual(bytes(data),self.bytes)
        self.assertEqual(self.rpc('production','open')['current'],self.current['current'])
        self.assertEqual(effect_count(self.creation),1)

    def test_revoked_reference_cannot_be_replaced_to_evade_source_authority(self):
        # A revoked reference must be checked BEFORE replacing it with another source.
        sfx=make_take(self.ctx,self.creation,'Synthetic SFX alternative',parent=self.source['request'])
        self.revoke();before=self.snapshot()
        payload=self.change(reference=self.reference,label='Must not erase revoked source',
            request=sfx['request'],take=sfx['candidate'])
        self.assertEqual(self.rpc('production','update_reference',payload),dict(error='MUSIC_SCOPE_REVIEW_REQUIRED'))
        self.assertEqual(self.snapshot(),before)

    def test_asset_only_and_reference_only_projections_reauthorize_sources(self):
        projects=[]
        for asset_only in (True,False):
            self.current=self.rpc('production','create',dict(command=identity(),title='Synthetic isolated source',
                kinds=['Music'],brief=dict(text='Synthetic projection probe')))
            payload=self.change(**self.ids())
            if asset_only: payload['asset']=self.current['current']['assets'][0]['id']
            else: payload['label']='Synthetic isolated reference'
            self.current=self.rpc('production','link_take' if asset_only else 'add_reference',payload)
            self.assertNotIn('error',self.current,self.current)
            projects.append(self.current['current']['id'])
        self.revoke()
        store=self.creation.store
        assert store is not None
        with store.transaction() as db:
            for project in projects:
                with self.assertRaises(Fault) as denied:self.service.records.projection(db,project)
                self.assertEqual(denied.exception.code,'MUSIC_SCOPE_REVIEW_REQUIRED')

    def test_revocation_before_record_revision_rolls_back_mutation_and_receipt(self):
        original=self.service.records.record_revision
        before=self.snapshot()
        def revoked(*args):
            self.revoke();return original(*args)
        with patch.object(self.service.records,'record_revision',side_effect=revoked):
            row=self.rpc('production','update_brief',self.change(title='Must roll back',brief=dict(text='Synthetic')))
        self.assertEqual(row,dict(error='MUSIC_SCOPE_REVIEW_REQUIRED'))
        self.unchanged(before)


if __name__ == '__main__': unittest.main()
