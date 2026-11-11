"""Real SQLite/native Production reuse behavior with controlled synthetic SFX."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from studio.domain import KINDS
from studio.persistence.primitives import identity
from studio.native.creation.registration import register as register_creation
from studio.native.production.registration import register
from tests.creation_support import Context
from tests.producer_support import effects
from tests.production_support import production_setup, make_take


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctx, self.creation, self.runtime, self.binding = production_setup(self.root)
        self.addCleanup(self.creation.unload)

    def rpc(self, operation, payload=None, root='canonical-root'):
        return self.ctx.methods['production.' + operation](payload or {}, session_id=root)

    def tool(self, operation, payload=None, root='canonical-root'):
        handler = self.ctx.tools['motion_studio_production'][1]
        return json.loads(handler(dict(operation=operation, **(payload or {})),
                                  session_id='physical-segment', conversation_id=root,
                                  task_id='not-scope', user_task='not-read'))

    def revision(self, result):
        current = result['current']
        return dict(command=identity(), production=current['id'], expected=current['revision'])

    def create(self, kinds=None):
        result = self.tool('create', dict(command=identity(), title='Synthetic production',
            brief=dict(text='Connected synthetic brief', purpose='Offline contract check'),
            kinds=list(kinds or KINDS)))
        self.assertNotIn('error', result, result)
        return result

    def test_default_denied_and_unsupported_operations_have_no_store_or_effect(self):
        ctx = Context(self.root / 'default-denied')
        creation = register_creation(ctx)
        self.addCleanup(creation.unload)
        production = register(ctx, creation)
        denied = ctx.methods['production.list']({}, session_id='other')
        self.assertEqual(denied['error'], 'PRODUCTION_ACCESS_UNAVAILABLE')
        self.assertFalse(ctx.state.data_dir.exists())
        unknown = ctx.tools['motion_studio_production'][1](dict(operation='generate'),
            session_id='physical', conversation_id='canonical-root')
        self.assertEqual(json.loads(unknown)['error'], 'INVALID_PRODUCTION_INPUT')
        self.assertTrue(production.association.revision == '')

    def test_multi_asset_reuse_reference_staleness_selection_and_byte_identity(self):
        first = make_take(self.ctx, self.creation, 'Synthetic first retained sound')
        second = make_take(self.ctx, self.creation, 'Synthetic alternative retained sound',
                           parent=first['request'])
        before_effects = len(effects(self.binding))
        with self.creation.store.transaction() as db:
            before_takes = db.execute('SELECT COUNT(*) FROM takes').fetchone()[0]
        before_media = sorted(path.name for path in (self.creation.store.home / 'media').iterdir())
        created = self.create()
        production = created['current']
        self.assertEqual([asset['kind'] for asset in production['assets']], list(KINDS))
        sfx = production['assets'][0]
        linked = self.rpc('link_take', dict(self.revision(created), asset=sfx['id'],
            request=first['request'], take=first['candidate']))
        linked = self.rpc('link_take', dict(self.revision(linked), asset=sfx['id'],
            request=second['request'], take=second['candidate']))
        self.assertEqual(len(linked['current']['assets'][0]['takes']), 2)
        self.assertIsNone(linked['current']['assets'][0]['selected_take'])
        chosen = self.rpc('select_take', dict(self.revision(linked), asset=sfx['id'],
            request=first['request'], take=first['candidate']))
        self.assertEqual(chosen['current']['assets'][0]['selected_take'], first['candidate'])
        reference = self.rpc('add_reference', dict(self.revision(chosen),
            request=first['request'], take=first['candidate'], label='Original sound reference'))
        reference_id = reference['current']['references'][0]['id']
        pinned = self.rpc('update_asset', dict(self.revision(reference), asset=sfx['id'],
            kind='Sound effects', intent='Retain the selected original sound',
            depends_on=[], references=[reference_id]))
        self.assertTrue(pinned['current']['assets'][0]['stale'])
        pinned = self.rpc('select_take', dict(self.revision(pinned), asset=sfx['id'],
            request=first['request'], take=first['candidate']))
        self.assertEqual(pinned['current']['assets'][0]['selection_references'],
                         [dict(id=reference_id, revision=1)])
        revised = self.rpc('update_reference', dict(self.revision(pinned), reference=reference_id,
            request=second['request'], take=second['candidate'], label='Alternative reference'))
        current = revised['current']
        self.assertTrue(current['assets'][0]['stale'])
        self.assertFalse(current['assets'][1]['stale'])
        self.assertEqual(current['assets'][0]['selected_take'], first['candidate'])
        self.assertEqual(current['assets'][0]['references'], [dict(id=reference_id, revision=1)])
        stale = self.rpc('select_take', dict(self.revision(pinned), asset=sfx['id'],
            request=second['request'], take=second['candidate']))
        self.assertEqual(stale['error'], 'PRODUCTION_STALE_REVISION')
        selected = self.rpc('select_take', dict(self.revision(revised), asset=sfx['id'],
            request=second['request'], take=second['candidate']))
        self.assertEqual(selected['current']['assets'][0]['selected_take'], second['candidate'])
        self.assertFalse(selected['current']['assets'][0]['stale'])
        self.assertEqual(len(selected['current']['assets'][0]['takes']), 2)
        accepted = self.rpc('update_asset', dict(self.revision(selected), asset=sfx['id'],
            kind='Sound effects', intent='Retain the selected original sound', depends_on=[],
            references=[reference_id]))
        self.assertTrue(accepted['current']['assets'][0]['stale'])
        self.assertEqual(accepted['current']['assets'][0]['references'], [dict(id=reference_id, revision=2)])
        accepted = self.rpc('select_take', dict(self.revision(accepted), asset=sfx['id'],
            request=second['request'], take=second['candidate']))
        self.assertFalse(accepted['current']['assets'][0]['stale'])
        self.assertEqual(accepted['current']['assets'][0]['selection_references'],
                         [dict(id=reference_id, revision=2)])
        brief = self.rpc('update_brief', dict(self.revision(accepted), title='Revised synthetic production',
            brief=dict(text='Changed brief', purpose='Offline contract check')))
        self.assertTrue(brief['current']['assets'][0]['stale'])
        self.assertFalse(brief['current']['assets'][1]['stale'])
        self.assertEqual(brief['current']['assets'][0]['selected_take'], second['candidate'])
        self.assertEqual(len(effects(self.binding)), before_effects)
        with self.creation.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM takes').fetchone()[0], before_takes)
            history = db.execute('SELECT COUNT(*) FROM production_reference_history').fetchone()[0]
            revisions = db.execute('SELECT COUNT(*) FROM production_revisions WHERE production=?',
                                   (production['id'],)).fetchone()[0]
        self.assertEqual(history, 2)
        self.assertEqual(revisions, brief['current']['revision'])
        self.assertEqual(sorted(path.name for path in (self.creation.store.home / 'media').iterdir()), before_media)

    def test_idempotent_lost_reply_reopen_and_command_conflict(self):
        command = identity()
        payload = dict(command=command, title='Lost create reply', kinds=['Sound effects', 'Image'])
        created = self.tool('create', payload)  # Deliberately discard delivered reply.
        recovered = self.tool('create', payload)
        self.assertEqual(recovered['current']['id'], created['current']['id'])
        self.assertEqual(recovered['current']['revision'], 1)
        listed = self.tool('list')
        self.assertEqual(listed['productions'][0]['command'], command)
        opened = self.tool('open', {})
        self.assertEqual(opened['current']['id'], created['current']['id'])
        conflict = self.tool('create', dict(payload, title='Changed payload'))
        self.assertEqual(conflict['error'], 'COMMAND_CONFLICT')
        selected = self.rpc('update_brief', dict(self.revision(opened), title='Lost brief reply',
            brief=dict(text='Persisted despite discarded reply')))  # Discard this reply too.
        reopened = self.rpc('open', dict(production=created['current']['id']))
        self.assertEqual(reopened['current']['title'], 'Lost brief reply')
        self.assertGreater(reopened['current']['revision'], selected['current']['revision'] - 1)
        self.assertEqual(len(effects(self.binding)), 0)

    def test_cycles_roll_back_and_selection_stales_only_declared_dependents(self):
        source = make_take(self.ctx, self.creation, 'Synthetic shared dependency sound')
        created = self.create(['Sound effects'] * 4)
        assets = created['current']['assets']
        current = created
        for asset in assets[:3]:
            current = self.rpc('link_take', dict(self.revision(current), asset=asset['id'],
                request=source['request'], take=source['candidate']))
            current = self.rpc('select_take', dict(self.revision(current), asset=asset['id'],
                request=source['request'], take=source['candidate']))
        current = self.rpc('update_asset', dict(self.revision(current), asset=assets[1]['id'],
            kind='Sound effects', intent='Middle', depends_on=[assets[0]['id']], references=[]))
        current = self.rpc('update_asset', dict(self.revision(current), asset=assets[2]['id'],
            kind='Sound effects', intent='Downstream', depends_on=[assets[1]['id']], references=[]))
        before = self.rpc('open', dict(production=created['current']['id']))
        with self.creation.store.transaction() as db:
            receipts = db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]
            original_pointer = self.creation.store.request(db, source['request'])['selected']
        cycle = self.rpc('update_asset', dict(self.revision(current), asset=assets[0]['id'],
            kind='Sound effects', intent='Cycle must roll back', depends_on=[assets[2]['id']],
            references=[], position=0))
        self.assertEqual(cycle['error'], 'PRODUCTION_DEPENDENCY_CYCLE')
        after = self.rpc('open', dict(production=created['current']['id']))
        self.assertEqual(after['current'], before['current'])
        with self.creation.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0], receipts)
            self.assertEqual(self.creation.store.request(db, source['request'])['selected'], original_pointer)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM takes').fetchone()[0], 1)
        selected = self.rpc('select_take', dict(self.revision(current), asset=assets[0]['id'],
            request=source['request'], take=source['candidate']))
        states = {asset['id']: asset['stale'] for asset in selected['current']['assets']}
        self.assertFalse(states[assets[0]['id']])
        self.assertTrue(states[assets[1]['id']])
        self.assertTrue(states[assets[2]['id']])
        self.assertFalse(states[assets[3]['id']])
        self.assertEqual(len(effects(self.binding)), 1)

    def test_two_node_cycle_rejected_without_partial_mutation(self):
        created = self.create(['Sound effects', 'Sound effects'])
        first, second = created['current']['assets']
        current = self.rpc('update_asset', dict(self.revision(created), asset=second['id'],
            kind='Sound effects', intent='Depends on first', depends_on=[first['id']], references=[]))
        before = self.rpc('open', dict(production=created['current']['id']))
        cycle = self.rpc('update_asset', dict(self.revision(current), asset=first['id'],
            kind='Sound effects', intent='Invalid cycle', depends_on=[second['id']], references=[]))
        self.assertEqual(cycle['error'], 'PRODUCTION_DEPENDENCY_CYCLE')
        self.assertEqual(self.rpc('open', dict(production=created['current']['id']))['current'], before['current'])

    def test_original_receipt_replay_after_head_advances(self):
        source = make_take(self.ctx, self.creation, 'Synthetic replay sound')
        created = self.create(['Sound effects'])
        asset = created['current']['assets'][0]
        linked = self.rpc('link_take', dict(self.revision(created), asset=asset['id'],
            request=source['request'], take=source['candidate']))
        selection = dict(self.revision(linked), asset=asset['id'],
                         request=source['request'], take=source['candidate'])
        selected = self.rpc('select_take', selection)
        advanced = self.rpc('update_brief', dict(self.revision(selected), title='Later head',
            brief=dict(text='Advanced after original selection')))
        replay = self.rpc('select_take', selection)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['receipt'], selected['receipt'])
        self.assertEqual(replay['receipt']['revision'], selected['current']['revision'])
        self.assertEqual(replay['current']['revision'], advanced['current']['revision'])
        self.assertEqual(replay['current']['title'], 'Later head')
        self.assertEqual(replay['current']['assets'][0]['selected_take'], source['candidate'])

    def test_wrong_root_store_kind_and_unlinked_chunk_denied(self):
        first = make_take(self.ctx, self.creation, 'Synthetic scoped sound')
        created = self.create(['Sound effects', 'Image'])
        sfx, image = created['current']['assets'][:2]
        mismatch = self.rpc('link_take', dict(self.revision(created), asset=image['id'],
            request=first['request'], take=first['candidate']))
        self.assertEqual(mismatch['error'], 'PRODUCTION_MEDIA_KIND_MISMATCH')
        linked = self.rpc('link_take', dict(self.revision(created), asset=sfx['id'],
            request=first['request'], take=first['candidate']))
        chunk = self.rpc('chunk', dict(production=created['current']['id'], asset=sfx['id'],
            request=first['request'], take=first['candidate'], offset=0))
        data = base64.b64decode(chunk['bytes'])
        self.assertEqual(hashlib.sha256(data).hexdigest(), chunk['chunk_sha256'])
        denied = self.rpc('chunk', dict(production=created['current']['id'], asset=image['id'],
            request=first['request'], take=first['candidate'], offset=0))
        self.assertEqual(denied['error'], 'PRODUCTION_TAKE_NOT_LINKED')
        self.ctx.methods['creation.admit']({}, session_id='foreign')
        self.rpc('admit', root='foreign')
        foreign = self.rpc('open', dict(production=created['current']['id']), root='foreign')
        self.assertEqual(foreign['error'], 'PRODUCTION_SCOPE_DENIED')
        other_ctx, other_creation, other_runtime, _ = production_setup(self.root / 'other-store')
        try:
            result = other_ctx.methods['production.open'](dict(production=created['current']['id']),
                                                          session_id='canonical-root')
            self.assertEqual(result['error'], 'PRODUCTION_SCOPE_DENIED')
        finally:
            other_creation.unload()
        self.assertNotIn('error', linked)
        self.assertEqual(len(effects(self.binding)), 1)


if __name__ == '__main__':
    unittest.main()
