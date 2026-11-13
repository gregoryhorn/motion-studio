"""Director safety/persistence regressions; fixtures are not native-host qualification."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from pydantic import ValidationError
from studio.domain import Fault, ImportIntent, SaveRequest, TakeAction
from studio.persistence.primitives import identity
from studio.director.cards.inventory import inventory
from studio.director.cards.schema import Mapping, Prepare
from studio.director.cards.learning import Cards
from studio.director.review import reports
from studio.director.state import removal
from tests.production_support import production_setup
from tests.media_import_fixtures import png

ROOT = 'canonical-root'


def checker(data, suffix, **options):
    return dict(status='WARN', counts=dict(PASS=1,WARN=1,FAIL=0,SKIP=2),
        not_checked_details=[dict(id='audio',summary='Not checked: Hear is disabled',skip_reason='not_requested')],
        not_checked=['hear','vision'], assets={'results/test/report.md':b'# Controlled report\nMissing hear and vision'})


def mapping():
    return Mapping(executable='magick', operation='Tiny blue square', arguments=['-size','32x32','xc:blue','{output}'],
                   format='png', version='documented-version', cost='zero', seconds=0, shape='32x32 blue square')


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='director-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.ctx, self.creation, self.production, _ = production_setup(self.home)
        self.addCleanup(self.creation.unload)
        self.service = self.creation.acquire()
        self.store = self.service.store
        self.checker_patch = patch('studio.director.review.crystal_ball.run', side_effect=checker)
        self.runner = self.checker_patch.start()
        self.addCleanup(self.checker_patch.stop)
        self.cards = Cards(self.service)

    def rpc(self, operation, payload=None, root=ROOT):
        return self.ctx.methods['director.'+operation](payload or {}, session_id=root)

    def draft(self, **options):
        values = dict(command=identity(),name='Controlled tool',documentation='https://imagemagick.org/script/command-line-processing.php',mapping=mapping())
        values.update(options)
        return self.cards.prepare(ROOT, Prepare(**values))

    def retained(self):
        out = io.BytesIO()
        with wave.open(out, 'wb') as target:
            target.setnchannels(1);target.setsampwidth(2);target.setframerate(44100)
            target.writeframes(b'\x01\x00'*22050)
        data = out.getvalue()
        request = self.store.save(SaveRequest(command=identity(),expected=0,text='Controlled',kind='Sound effects'))['id']
        with self.store.transaction() as db:
            db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                (request,ROOT,self.creation.policy.revision,identity(),json.dumps(dict(method='import')),None,'Import only',0))
        result = self.service.assets.intent(ImportIntent(command=identity(),request=request,revision=1,digest=hashlib.sha256(data).hexdigest(),size=len(data),name='controlled.wav'))
        self.service.assets.upload(result['id'],data)
        return dict(request=request,take=result['take']),data

    def test_inventory_scope_and_no_effects(self):
        cached=dict(profile='one',session='session',as_of='controlled',items=[dict(name='Reader',kind='mcp',secret='NEVER'),dict(name='Instructions',kind='skill')])
        which=lambda name:'/controlled/'+name if name=='sox' else None
        first=inventory('one','session',cached=cached,which=which)
        self.assertEqual([i['status'] for i in first['items']],['Cached','Instructions installed','Discovered'])
        self.assertNotIn('NEVER',json.dumps(first))
        second=inventory('two','session',cached=cached,which=which)
        self.assertEqual(len(second['items']),1)
        self.assertEqual(inventory('one',None,cached=cached,which=which)['items'],[])
        self.assertIn('backend',first['execution_location'])

    def test_report_exact_identity_restart_no_rerun(self):
        take,data=self.retained()
        report=self.rpc('status',take)
        self.assertEqual(report['status'],'WARN')
        count=self.runner.call_count
        for _ in range(2):
            opened=self.rpc('report',dict(**take,report=report['report']))
            self.assertTrue(opened['current'])
        self.assertEqual(self.runner.call_count,count)
        from studio.native.creation.runtime import MediaStore
        reopened=MediaStore(self.store.home)
        with reopened.transaction() as db:
            self.assertEqual(reports.status(db,reopened.take(db,take['take'])),report)
            row=dict(reopened.take(db,take['take']));row['digest']='0'*64
            self.assertEqual(reports.status(db,row)['status'],'Not checked')
        asset=opened['assets'][0]
        chunk=self.rpc('report',dict(**take,report=report['report'],asset=asset))
        self.assertIn(b'Controlled report',base64.b64decode(chunk['bytes']))
        self.assertEqual(self.service.assets.retrieve(take['take'])[0],data)
        denied=self.rpc('report',dict(**take,report=report['report']),root='other-root')
        self.assertIn('error',denied)

    def test_checker_failure_keeps_playable_output(self):
        self.runner.side_effect=RuntimeError('PRIVATE_PATH_SECRET')
        take,data=self.retained()
        report=self.rpc('status',take)
        self.assertEqual(report['status'],'Not checked')
        self.assertNotIn('PRIVATE',json.dumps(report))
        self.assertEqual(self.service.assets.retrieve(take['take'])[0],data)

    def test_remove_undo_restart_and_no_source_deletion(self):
        take,data=self.retained()
        count=self.runner.call_count
        payload=dict(**take,command=identity(),expected=0)
        removed=self.rpc('take.remove',payload)
        self.assertEqual(self.rpc('take.remove',payload),removed)
        self.assertEqual(len(self.rpc('take.removed')['takes']),1)
        self.assertFalse(self.service.read(ROOT,take['request'])['takes'])
        restored=self.rpc('take.restore',dict(**take,command=identity(),expected=removed['revision']))
        self.assertFalse(restored['removed'])
        self.assertEqual(self.service.read(ROOT,take['request'])['takes'][0]['id'],take['take'])
        self.assertEqual(self.service.assets.retrieve(take['take'])[0],data)
        self.assertEqual(self.runner.call_count,count)
        self.assertEqual(self.rpc('take.remove',dict(**take,command=identity(),expected=0))['error'],'DIRECTOR_STALE_REVISION')

    def test_selected_and_unresolved_removal_refused(self):
        take,_=self.retained()
        self.store.select(TakeAction(command=identity(),request=take['request'],expected=1,take=take['take']))
        self.assertEqual(self.rpc('take.remove',dict(**take,command=identity(),expected=0))['error'],'DIRECTOR_TAKE_IN_USE')
        with self.store.transaction() as db:
            db.execute('UPDATE requests SET selected=NULL WHERE id=?',(take['request'],))
            db.execute("UPDATE creation_commands SET phase='Preparing' WHERE request=?",(take['request'],))
        self.assertEqual(self.rpc('take.remove',dict(**take,command=identity(),expected=0))['error'],'DIRECTOR_RUN_UNRESOLVED')

    def test_missing_injected_session_and_spoofed_profile_refused(self):
        self.assertIn('error',self.ctx.methods['director.inventory']({}))
        self.assertEqual(self.rpc('inventory',dict(profile='other'))['error'],'DIRECTOR_SCOPE_DENIED')
        self.assertEqual(self.rpc('inventory',dict(session_id='other'))['error'],'DIRECTOR_SCOPE_DENIED')
        self.assertEqual(self.rpc('inventory',dict(secret='never'))['error'],'DIRECTOR_INVALID_INPUT')

    def test_mapping_rejects_paths_code_and_indirection(self):
        for token in ('/etc/passwd','@secrets','https://example.com','$(id)','--output=/outside','../secret','a;echo'):
            value=mapping().model_dump();value['arguments']=[token,'{output}']
            with self.assertRaises(ValidationError):Mapping(**value)

    def test_one_confirmed_test_replay_and_correction(self):
        card=self.draft()
        payload=dict(id=card['id'],expected=card['revision'],command=identity(),confirmed=True)
        with patch.object(Cards,'execute',return_value=(png(),dict(mime='image/png',width=1,height=1))),patch('studio.director.cards.learning.fingerprint',return_value=dict(path='controlled',sha256='0'*64)):
            first=self.rpc('card.test',payload)
            self.assertEqual(first['status'],'Tested')
            self.assertEqual(self.rpc('card.test',payload),first)
            self.assertEqual(len(first['evidence']),1)
            self.assertEqual(self.rpc('card.read')['cards'][0]['status'],'Tested')
        edited=self.draft(id=card['id'],expected=card['revision'])
        self.assertEqual(edited['status'],'Untested')
        self.assertEqual(edited['revision'],2)
        self.assertIn('error',self.rpc('card.test',payload,root='other'))

    def test_cancel_unknown_cost_two_failures_and_uncertainty(self):
        card=self.draft()
        self.assertEqual(self.rpc('card.test',dict(id=card['id'],expected=1,command=identity()))['error'],'DIRECTOR_CONFIRMATION_REQUIRED')
        unknown=mapping().model_dump();unknown['cost']='unknown'
        other=self.draft(mapping=Mapping(**unknown))
        self.assertEqual(self.rpc('card.test',dict(id=other['id'],expected=1,command=identity(),confirmed=True))['error'],'DIRECTOR_SPEND_AUTHORIZATION_REQUIRED')
        with patch('studio.director.cards.learning.fingerprint',return_value=dict(path='controlled',sha256='0'*64)),patch.object(Cards,'execute',side_effect=Fault('DIRECTOR_CONFIRMED_OUTPUT_FAILURE')):
            for number in range(2):
                result=self.rpc('card.test',dict(id=card['id'],expected=1,command=identity(),confirmed=True))
            self.assertEqual(result['status'],'Needs re-test')
            self.assertEqual(result['failures'],2)
        with patch('studio.director.cards.learning.fingerprint',return_value=dict(path='controlled',sha256='0'*64)),patch.object(Cards,'execute',side_effect=TimeoutError('private')):
            command=identity();payload=dict(id=card['id'],expected=1,command=command,confirmed=True)
            unknown=self.rpc('card.test',payload)
            self.assertEqual(unknown['status'],'Testing')
            self.assertEqual(self.rpc('card.test',payload)['status'],'Testing')
            self.assertEqual(self.rpc('card.test',dict(payload,command=identity()))['error'],'DIRECTOR_TEST_UNAVAILABLE')

    def test_fixed_ffmpeg_mapping_rejects_any_other_input(self):
        value=dict(executable='ffmpeg',operation='Tiny blue movie',format='mp4',version='fixture',cost='zero',seconds=.6,shape='160x90',
            arguments=['-v','error','-f','lavfi','-i','color=c=blue:s=160x90:d=0.6','-c:v','libx264','-pix_fmt','yuv420p','{output}'])
        self.assertEqual(Mapping(**value).format,'mp4')
        for arguments in (['-i','https://example.org','{output}'],['-i','input.mp4','{output}'],value['arguments']+['-y']):
            with self.assertRaises(ValidationError):Mapping(**dict(value,arguments=arguments))

    def test_qualified_card_uses_scoped_original_retrieval_and_appends_review_evidence(self):
        from studio.media_import import MediaImports
        from studio.media_import.contracts import RetrieveTake
        card=self.draft()
        with patch.object(Cards,'execute',return_value=(png(),dict(mime='image/png',width=1,height=1))),patch('studio.director.cards.learning.fingerprint',return_value=dict(path='controlled',sha256='0'*64)):
            result=self.rpc('card.test',dict(id=card['id'],expected=1,command=identity(),confirmed=True))
            take=result['evidence'][0]['take']
            imports=MediaImports(self.store,self.service.authorize_request,assets=self.service.assets)
            self.assertEqual(imports.retrieve(ROOT,RetrieveTake(take=take))[0],png())
            with self.assertRaises(Fault):imports.retrieve('other',RetrieveTake(take=take))
            with self.store.transaction() as db:db.execute("UPDATE takes SET review='Accepted' WHERE id=?",(take,))
            before=self.runner.call_count
            refreshed=self.cards.read(ROOT)['cards'][0]
            self.assertEqual(refreshed['evidence'][-1]['user_verdict'],'Accepted')
            self.assertEqual(len(self.cards.read(ROOT)['cards'][0]['evidence']),2)
            self.assertEqual(self.runner.call_count,before)

    def test_disable_forget_preserves_test_provenance(self):
        card=self.draft()
        disabled=self.rpc('card.disable',dict(id=card['id'],expected=1,command=identity()))
        self.assertEqual(disabled['status'],'Disabled')
        forgotten=self.rpc('card.forget',dict(id=card['id'],expected=2,command=identity()))
        self.assertEqual(forgotten['revision'],3)
        self.assertNotIn('mapping',forgotten)
        with self.store.transaction() as db:
            notes=[json.loads(row[0]) for row in db.execute('SELECT body FROM director_cards WHERE id=?',(card['id'],))]
        self.assertTrue(all(note['mapping'] is None and not note['documentation'] for note in notes))


if __name__=='__main__':unittest.main()
