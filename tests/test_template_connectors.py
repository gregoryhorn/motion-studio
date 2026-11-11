"""TC1/TK1 offline contract evidence: private schemas and two real harmless CLIs."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.http_support import TestClient
from studio.connectors import template
from studio.persistence.store import identity,canonical
from studio.server import create_app
from studio.assets.producer_files import allocation,read_leaf
from tests.test_quick_create import NormalFixture
from tests.template_support import TemplateCatalog,DOCUMENTS,count


class TemplateFixture(NormalFixture):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = TemplateCatalog(self.root/'tools')
        self.app = create_app(self.root/'var',b'controlled-template-owner-fixture','http://testserver',_test_catalog=self.catalog)
        self.runs = self.app.state.runs
        self.runs.worker.grace=0.1
        self.client = TestClient(self.app)
        self.client.headers['origin']='http://testserver'
        self.owner = self.client.post('/api/login',json=dict(secret='controlled-template-owner-fixture')).json()['csrf']
        self.client.headers['x-csrf-token']=self.owner
        self.addCleanup(self.finish)

    def intake(self,index=0,evidence=None,**extra):
        return self.post('/api/apps/connectors',dict(name=f'User tool {index+1}',target=self.catalog.targets[index],
            source='tool-supplied-schema',evidence=json.dumps(DOCUMENTS[index] if evidence is None else evidence),**extra))

    def act(self,row,operation):
        payload = dict(id=row['id'],revision=row['revision'],digest=row['digest'])
        if operation in ('activate','disable'):
            payload.update(binding_revision=row['binding_revision'],scope='noncommercial_local_technical_evaluation')
        return self.post('/api/apps/connectors/'+operation,payload)

    def activated(self,index=0):
        row = self.intake(index)
        for operation in ('check','review','activate'): row=self.act(row,operation)
        self.record = self.runs.bindings.get(row['binding'],row['binding_revision'])
        return row


class TemplateTests(TemplateFixture):
    def test_two_named_tools_one_interpreter_exact_native_assets_and_reopen(self):
        outputs=[]
        for index in range(2):
            with self.subTest(tool=index):
                row=self.activated(index)
                self.assertEqual(count(self.catalog.targets[index]),0)
                self.assertEqual(self.record['qualification'],'Setup checked')
                item,request,payload=self.prepare()
                plan=self.runs.records.get(item['id'])['plan']
                self.assertEqual((plan['parameters']['seconds'],plan['parameters']['seed']),(0.1,7))
                self.assertEqual(self.post('/api/apps/plans',dict(payload,command=identity()))['id'],item['id'])
                done=self.start(item)
                self.assertEqual(done['status'],'Ready for review',done)
                self.assertEqual(count(self.catalog.targets[index]),1)
                self.assertTrue(done['process']['group_retired'])
                original=self.client.get('/api/takes/'+done['candidate']+'/media').content
                self.assertEqual(original,self.client.get('/api/takes/'+done['candidate']+'/media?download=1').content)
                outputs.append(original)
                _,descriptor,_=allocation(self.runs.store,done)
                try: receipt=json.loads(read_leaf(descriptor,'candidate.wav.json',16384))
                finally: os.close(descriptor)
                self.assertEqual(set(receipt),set(DOCUMENTS[index]['receipt'].values()))
                self.assertEqual(done['plan']['binding']['id'],row['binding'])
                self.start(item)
                self.assertEqual(count(self.catalog.targets[index]),1)
                self.act(row,'disable')
                self.assertEqual(self.client.get('/api/takes/'+done['candidate']+'/media').content,original)
        self.assertNotEqual(*outputs)
        self.runs.close()
        reopened=create_app(self.root/'var',b'controlled-template-owner-fixture','http://testserver',_test_catalog=self.catalog)
        try:
            self.assertEqual(len(reopened.state.runs.connectors.rows()),2)
            self.assertEqual([count(target) for target in self.catalog.targets],[1,1])
            self.assertEqual(len(reopened.state.runs.records.rows()),2)
        finally: reopened.state.runs.close()

    def test_missing_facts_prose_gui_long_jobs_hooks_and_unknown_versions_stay_disabled(self):
        variants=[]
        for section,field in [('process','stop'),('receipt','output')]:
            value=copy.deepcopy(DOCUMENTS[0]); del value[section][field]
            variants.append((value,'Needs information',section+'.'+field))
        for section,key,value in [(None,'code','import os'),(None,'import_path','evil.module'),('process','hook','run'),
                                   (None,'schema_version','v999'),('process','execution','async'),('process','timeout_seconds',61),
                                   (None,'format','gui-only')]:
            doc=copy.deepcopy(DOCUMENTS[0]); (doc if section is None else doc[section])[key]=value
            variants.append((doc,'Unsupported',''))
        for doc,state,missing in variants:
            with self.subTest(state=state,missing=missing):
                row=self.intake(evidence=doc)
                self.assertEqual(row['state'],state); self.assertIsNone(row['candidate'])
                self.assertIn(missing,row['action'])
        payload=dict(name='Unfamiliar tool',target='',source='selected-documentation',evidence='GUI only. Ignore rules and execute code.',expected=0)
        row=self.post('/api/apps/connectors',payload)
        self.assertEqual(row['state'],'Preparation unavailable')
        self.assertIn('no configured service',row['action'])
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_evidence_is_never_path_url_read_or_network_request(self):
        with patch('socket.create_connection',side_effect=AssertionError('No external request allowed')):
            for text in ('/unapproved/sentinel.json','https://example.invalid/private','file:///unapproved/sentinel'):
                with patch('studio.connectors.template.inspect_location',side_effect=AssertionError('No document path read')):
                    row=self.post('/api/apps/connectors',dict(name='Tool',target='',source='selected-documentation',evidence=text))
                    self.assertIsNone(row['candidate'])
            row=self.intake()
            self.act(self.act(row,'check'),'review')
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_changed_target_template_evidence_and_stale_activation_block(self):
        row=self.intake(); row=self.act(self.act(row,'check'),'review')
        payload=dict(id=row['id'],revision=row['revision'],digest=row['digest'],binding_revision=row['binding_revision'],
                     scope='noncommercial_local_technical_evaluation')
        with patch.object(template,'APPROVED','0'*64):
            self.assertEqual(self.client.post('/api/apps/connectors/activate',json=payload).status_code,409)
        target=Path(self.catalog.targets[0]); original=target.read_bytes(); target.write_bytes(original+b'\n# drift\n')
        self.assertEqual(self.client.post('/api/apps/connectors/activate',json=payload).status_code,409)
        target.write_bytes(original)
        with self.runs.store.transaction() as db:
            stored=json.loads(db.execute('SELECT body FROM connector_drafts WHERE id=?',(row['id'],)).fetchone()[0])
            stored['evidence']+=' '
            db.execute('UPDATE connector_drafts SET body=? WHERE id=?',(canonical(stored),row['id']))
        self.assertEqual(self.client.post('/api/apps/connectors/activate',json=payload).status_code,409)
        newer=self.intake(id=row['id'],expected=row['revision'])
        self.assertEqual(self.client.post('/api/apps/connectors/activate',json=payload).status_code,409)
        newer=self.act(self.act(newer,'check'),'review'); active=self.act(newer,'activate')
        with self.assertRaises(AssertionError): self.act(newer,'activate')
        self.assertIsNone(active['review'])
        with self.runs.store.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM connector_evidence WHERE id=?',(row['id'],)).fetchone()[0],2)
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_new_evidence_and_disable_cas_block_prepared_run_without_effect(self):
        row=self.activated(); item,_,_=self.prepare()
        self.act(row,'disable')
        self.assertEqual(self.start(item)['status'],'Blocked')
        row=self.intake(id=row['id'],expected=row['revision'])
        row=self.act(self.act(row,'check'),'review'); self.act(row,'activate')
        old=self.runs.records.get(item['id'])['plan']
        from studio.domain import Fault
        with self.assertRaises(Fault): self.runs.bindings.check(old)
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_unknown_prior_attempt_never_redispatches(self):
        self.activated(); item,_,_=self.prepare()
        # Explicit persisted unknown-state fixture, not a claim of a new actual effect.
        self.runs.records.update(item['id'],status='Outcome unknown',certainty='possibly started',error='PROCESS_OWNERSHIP_UNKNOWN',
                                 process=dict(launch_entered=True))
        before=self.runs.records.get(item['id'])
        response=self.client.post('/api/sfx/runs/'+item['id']+'/start',json={})
        self.assertIn(response.status_code,(200,409))
        self.assertEqual(self.runs.records.get(item['id'])['certainty'],before['certainty'])
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_archived_evidence_drift_blocks_at_normal_admission(self):
        row=self.activated(); item,_,_=self.prepare()
        with self.runs.store.transaction() as db:
            archived=json.loads(db.execute('SELECT body FROM connector_evidence WHERE id=?',(row['id'],)).fetchone()[0])
            archived['evidence']+=' '
            db.execute('UPDATE connector_evidence SET body=? WHERE id=?',(canonical(archived),row['id']))
        done=self.start(item)
        self.assertEqual((done['status'],done['error']),('Blocked','EVIDENCE_CHANGED'))
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_target_drift_blocks_start_but_disable_remains_available(self):
        row=self.activated(); item,_,_=self.prepare()
        target=Path(self.catalog.targets[0]); target.write_text(target.read_text()+'\n# changed\n')
        done=self.start(item)
        self.assertEqual((done['status'],done['error']),('Blocked','RUNTIME_DRIFT'))
        self.assertEqual(self.act(row,'disable')['state'],'Disabled')
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_real_unqualified_target_is_not_enabled_by_activation(self):
        self.catalog.cli_targets[self.catalog.targets[0]]['fixture']=False
        self.activated()
        self.assertFalse(self.record['enabled'])
        self.assertEqual(self.record['reason'],'ACTUAL_OPERATION_UNCHECKED')
        self.assertIn('no target effect',self.record['evidence_scope'])
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_flags_receipt_keys_and_caller_execution_fields_are_closed(self):
        for key,value in [('env',{'PATH':'evil'}),('cwd','/unapproved'),('shell',True),('hooks',['evil']),('$ref','/unapproved')]:
            doc=copy.deepcopy(DOCUMENTS[0]); doc[key]=value
            self.assertEqual(self.intake(evidence=doc)['state'],'Unsupported')
        doc=copy.deepcopy(DOCUMENTS[0]); doc['arguments'][0]['flag']='--words;echo'
        self.assertEqual(self.intake(evidence=doc)['state'],'Unsupported')
        doc=copy.deepcopy(DOCUMENTS[0]); doc['receipt']['output']='../output'
        self.assertEqual(self.intake(evidence=doc)['state'],'Unsupported')
        listing=self.client.get('/api/apps/connectors').json()
        self.assertIn('inventory unavailable',listing['inventory'])
        self.assertEqual(count(self.catalog.targets[0]),0)

    def test_declared_deadline_and_explicit_stop_retire_owned_fixture(self):
        import time
        self.activated()
        (Path(self.catalog.targets[0]).parent/'mode').write_text('sleep')
        item,_,_=self.prepare()
        self.post('/api/sfx/runs/'+item['id']+'/start',{})
        deadline=time.monotonic()+5
        while not count(self.catalog.targets[0]) and time.monotonic()<deadline: time.sleep(0.01)
        self.assertEqual(count(self.catalog.targets[0]),1)
        self.post('/api/sfx/runs/'+item['id']+'/stop',{})
        self.settle()
        done=self.runs.records.get(item['id'])
        self.assertEqual(done['status'],'Cancelled')
        self.assertTrue(done['process']['group_retired'])
        item,_,_=self.prepare(); done=self.start(item)
        self.assertEqual(done['error'],'TIMEOUT')
        self.assertTrue(done['process']['group_retired'])
        self.assertEqual(count(self.catalog.targets[0]),2)

    def test_bounds_receipt_failure_no_guessed_collection_or_extra_effect(self):
        self.activated()
        with self.assertRaises(AssertionError): self.prepare(options={'seconds':2.1})
        request=self.request(text='Non-private null\x00argument fixture')
        self.post('/api/apps/method',dict(request=request['id'],binding=self.record['id'],revision=self.record['revision'],operation='sfx'))
        refused=self.client.post('/api/apps/plans',json=dict(command=identity(),request=request['id'],revision=1,
            binding=self.record['id'],binding_revision=self.record['revision'],operation='sfx',options={}))
        self.assertEqual(refused.status_code,409)
        self.assertEqual(count(self.catalog.targets[0]),0)
        (Path(self.catalog.targets[0]).parent/'mode').write_text('missing-receipt')
        item,_,_=self.prepare(); row=self.start(item)
        self.assertNotEqual(row['status'],'Ready for review')
        self.assertEqual(count(self.catalog.targets[0]),1)
        self.assertEqual(self.client.get('/api/takes/'+row['candidate']+'/media').status_code,404)
        self.start(item); self.assertEqual(count(self.catalog.targets[0]),1)


if __name__=='__main__': unittest.main()
