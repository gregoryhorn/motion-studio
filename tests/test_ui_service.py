"""ui.v1 durable facade contract tests.

Authored during the implementation-only phase. Do not run this module until
all UI owners have completed the accepted build and the parent lifts that gate.
No fixture uses active profiles, engines, media, network or native UI mutation.
"""
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from typing import Any
from unittest.mock import Mock, patch

from studio.contracts import ContractError, digest as engine_digest, empty_brief
from studio.ui_service import UIService, _hash
from studio.ui_graph import schema_catalog


def uid():
    return str(uuid.uuid4())


class UIServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'],prefix='ui-service-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'studio'
        self.records = [dict(id='native-A',name='Native A',archived=False,folders=[]),
                        dict(id='native-B',name='Native B',archived=False,folders=[])]
        self.integrations = {}
        self.service = self.make_service()
        self.scope = dict(backend_instance_id='backend-test',connection_id='local',profile_id='profile-test',native_project_id='native-A')
        self.project = '/projects/native-A'
        self.format = dict(fps=dict(num=30,den=1),width=1920,height=1080,sample_rate=48000,channels=2,duration_frames=0)

    def make_service(self, **changes):
        values = dict(profile_id='profile-test',backend_instance_id='backend-test',connection_id='local',integrations=self.integrations)
        values.update(changes)
        return UIService(self.root,lambda:copy.deepcopy(self.records),**values)

    def get(self, path, query=None, service=None, principal='host'):
        return (service or self.service).handle('GET',path,query=query,principal=principal)

    def command(self, path, pre, input, *, service=None, principal='host', body=None, scope=None):
        frozen = body or dict(scope=copy.deepcopy(scope or self.scope),command_id=uid(),idempotency_key=uid(),preconditions=pre,input=input)
        status,envelope = (service or self.service).handle('POST',path,body=frozen,principal=principal)
        return status,envelope,frozen

    def create(self, name='Composition', catalog=1):
        status,envelope,body = self.command(self.project+'/compositions',dict(catalog_revision=catalog),dict(name=name,format=copy.deepcopy(self.format),template_ref=None))
        self.assertEqual(status,201,envelope)
        return envelope['data'],body

    def cpath(self, data):
        return self.project+'/compositions/'+data['composition']['composition_id']

    def pin(self, data):
        return dict(composition_revision=data['composition']['composition_revision'],version_id=data['version']['version_id'])

    def rename_track(self, data, name='Edited'):
        track = data['version']['tracks'][0]
        return dict(op='track.update',track_id=track['track_id'],name=name,order=track['order'],locked=False,visible=True,muted=False)

    def transact(self, data, ops=None, body=None):
        return self.command(self.cpath(data)+'/transactions',self.pin(data),
                            dict(operations=ops or [self.rename_track(data)],gesture_id=uid(),summary='Typed edit',dependency_policy='reject_unlisted',acknowledged_dependency_ids=[]),body=body)

    def test_bootstrap_reads_no_production_and_requires_contract(self):
        before = copy.deepcopy(self.records)
        status,out = self.get('/bootstrap',dict(client_contract='ui.v1',client_kind='desktop'))
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['canonicalizer'],'jcs-sha256.v1')
        self.assertFalse(out['data']['transport_capabilities']['range_media'])
        self.assertFalse(out['data']['transport_capabilities']['binary_upload'])
        self.assertEqual(out['data']['limits']['transaction_bytes'],1048576)
        self.assertGreaterEqual(out['data']['limits']['transaction_operations'],100)
        self.assertEqual(self.records,before)
        self.assertFalse((self.service.directory/'engine').exists())
        self.assertEqual(self.get('/bootstrap',dict(client_contract='future',client_kind='web'))[0],409)

    def test_native_registry_exact_ids_no_creation_on_read(self):
        status,out = self.get('/projects',dict(include_archived=False))
        self.assertEqual(status,200,out)
        self.assertEqual({p['native_project_id'] for p in out['data']['items']},{'native-A','native-B'})
        self.assertIsNone(out['data']['active_native_project_id'])
        status,out = self.get(self.project+'/context')
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['catalog_revision'],1)
        self.assertEqual(self.get('/projects/Native%20A/context')[0],404)
        self.assertFalse((self.service.directory/'engine').exists())

    def test_create_real_compiled_store_binding_and_exact_initial_tracks(self):
        data,_ = self.create()
        version = data['version']
        self.assertEqual(version['composition_revision'],1)
        self.assertEqual(version['format']['duration_frames'],0)
        self.assertEqual({t['name'] for t in version['tracks']},{'V1','A1','Captions','Overlay'})
        binding = self.service.resolve_binding('native-A',data['composition']['composition_id'])
        self.assertNotIn(binding['private_project_id'],json.dumps(data))
        opened = binding['project_store'].dispatch(dict(action='open',project_id=binding['private_project_id'],revision=binding['private_project_revision']))
        self.assertTrue(opened['ok'],opened)
        self.assertIn('timeline',{p['kind'] for p in opened['data']['documents']})
        fs = binding['project_store']._filesystem()
        pointer = binding['project_store']._pointer(fs,binding['private_project_id'])
        _,docs = binding['project_store']._load(fs,pointer)
        self.assertEqual(len(docs['timeline','project']['value']['tracks']),4)
        self.assertEqual(data['catalog_revision'],2)

    def test_content_hash_ignores_observation_and_version_identity(self):
        data,_ = self.create()
        version = data['version']
        content = {k:copy.deepcopy(version[k]) for k in ('schema_version','format','tracks','clips','scenes','layers','effects','audio_buses','captions','asset_refs','settings','production_documents')}
        self.assertEqual(version['sha256'],_hash(content))
        second = copy.deepcopy(version)
        second.update(version_id='version_otheridentity',parent_version_id='version_oldidentity',created_at='2099-01-01T00:00:00Z')
        self.assertEqual(_hash({k:second[k] for k in content}),version['sha256'])

    def test_nonzero_create_rejects_without_catalog_or_store_publication(self):
        status,out,_ = self.command(self.project+'/compositions',dict(catalog_revision=1),
            dict(name='No blank tail',format={**self.format,'duration_frames':30},template_ref=None))
        self.assertEqual(status,422,out)
        self.assertEqual(out['error']['code'],'TIMING_INVALID')
        self.assertEqual(out['error']['effect_state'],'none')
        listing = self.get(self.project+'/compositions',dict(include_archived=False))[1]['data']
        self.assertEqual(listing['total'],0)
        self.assertEqual(listing['catalog_revision'],1)
        self.assertFalse((self.service.directory/'engine').exists())
        self.create(catalog=1)

    def test_document_refs_values_historical_read_and_receipt_hash_are_distinct(self):
        data,_ = self.create()
        value = {**empty_brief(),'objective':'Preserve literal sha256: text and العربية'}
        def put(value,doc=None):
            return dict(op='document.put',kind='brief',document_id=doc['document_id'] if doc else None,
                        create_ref=None if doc else uid(),schema_ref=schema_catalog()['brief']['schema_ref'],
                        value=value,expected_document_sha256=doc['sha256'] if doc else None)
        status,out,body = self.transact(data,[put(value)])
        self.assertEqual(status,200,out)
        saved = out['data']
        ref = saved['version']['production_documents'][0]
        self.assertEqual(set(ref),{'kind','document_id','document_version_id','schema_ref','sha256'})
        self.assertEqual(ref['sha256'],_hash(value))
        self.assertRegex(ref['schema_ref']['sha256'],r'^[0-9a-f]{64}$')
        content = {k:saved['version'][k] for k in ('schema_version','format','tracks','clips','scenes','layers','effects','audio_buses','captions','asset_refs','settings','production_documents')}
        self.assertEqual(saved['version']['sha256'],_hash(content))
        path = self.cpath(saved)+'/documents/'+ref['document_id']
        status,document = self.get(path,dict(version_id=saved['version']['version_id']))
        self.assertEqual(status,200,document)
        self.assertEqual(document['data'],{**ref,'value':value})
        receipt_path = self.project+'/receipts/'+out['command']['receipt_id']
        status,receipt = self.get(receipt_path)
        self.assertEqual(status,200,receipt)
        self.assertEqual(receipt['data']['result_sha256'],_hash(saved))
        status,changed,_ = self.transact(saved,[put({**value,'objective':'Second immutable revision'},ref)])
        self.assertEqual(status,200,changed)
        self.assertEqual(self.get(path,dict(version_id=saved['version']['version_id']))[1]['data']['value'],value)
        self.assertEqual(self.get(receipt_path)[1]['data'],receipt['data'])
        status,replayed,_ = self.transact(data,body=body)
        self.assertEqual(status,200,replayed)
        self.assertEqual(replayed['data'],saved)
        self.assertEqual(self.get(path,dict(version_id=data['version']['version_id']))[0],404)
        other,_ = self.create('Other',catalog=2)
        self.assertEqual(self.get(path,dict(version_id=other['version']['version_id']))[0],404)

    def test_variant_profile_public_pin_resolves_real_immutable_engine_envelope(self):
        data,_ = self.create()
        profile = dict(profile_id='web',version='1',label='Web',sources=[],valid_until=None,
            constraints=dict(allowed_containers=['mp4'],allowed_video_codecs=['h264'],allowed_audio_codecs=[],
                width_px=1920,height_px=1080,rate=dict(num=30,den=1),max_duration_frames=None,max_bytes=None,
                alpha='forbidden',caption_modes=['none'],loudness_lufs=None,loudness_tolerance_lu=None,true_peak_dbtp=None))
        def put(kind,value):
            return dict(op='document.put',kind=kind,document_id=None,create_ref=uid(),
                schema_ref=schema_catalog()[kind]['schema_ref'],value=value,expected_document_sha256=None)
        status,out,_ = self.transact(data,[put('delivery_profile',profile)])
        self.assertEqual(status,200,out)
        saved = out['data']
        public = saved['version']['production_documents'][0]
        pin = {key:public[key] for key in ('kind','document_id','document_version_id','sha256')}
        variant = dict(variant_id='web',label='Web',width_px=1920,height_px=1080,rate=dict(num=30,den=1),duration_frames=30,
            container='mp4',video_codec='h264',pixel_format='yuv420p',color=dict(primaries='bt709',transfer='bt709',matrix='bt709',range='limited'),
            alpha='none',audio=dict(mode='none',sample_rate=None,channels=None,codec=None,loudness_lufs=None,true_peak_dbtp=None),
            captions='none',profile=pin,overrides=dict(reason='No overrides'))
        status,out,_ = self.transact(saved,[put('variants',[variant])])
        self.assertEqual(status,200,out)
        final = out['data']
        binding = self.service.resolve_binding('native-A',final['composition']['composition_id'])
        store = binding['project_store']
        fs = store._filesystem()
        _,docs = store._load(fs,store._pointer(fs,binding['private_project_id']))
        backend_profile = docs['delivery_profile','web']
        backend_pin = docs['variants','project']['value'][0]['profile']
        self.assertEqual(backend_pin,dict(kind='delivery_profile',id='web',revision=backend_profile['revision'],sha256=engine_digest(backend_profile)))
        ref = next(doc for doc in final['version']['production_documents'] if doc['kind']=='variants')
        status,document = self.get(self.cpath(final)+'/documents/'+ref['document_id'],dict(version_id=final['version']['version_id']))
        self.assertEqual(status,200,document)
        self.assertEqual(document['data']['value'],[variant])
        replacement = put('delivery_profile',{**profile,'label':'Updated profile'})
        replacement.update(document_id=public['document_id'],create_ref=None,expected_document_sha256=public['sha256'])
        status,out,_ = self.transact(final,[replacement])
        self.assertEqual(status,200,out)
        # A second save must still resolve the original pin even though the
        # immediately preceding public version carries the newer profile ref.
        status,out,_ = self.transact(out['data'])
        self.assertEqual(status,200,out)
        binding = self.service.resolve_binding('native-A',out['data']['composition']['composition_id'])
        _,docs = store._load(fs,store._pointer(fs,binding['private_project_id']))
        self.assertEqual(docs['variants','project']['value'][0]['profile'],backend_pin)
        self.assertGreater(docs['delivery_profile','web']['revision'],backend_pin['revision'])

    def test_frozen_retry_precedes_stale_cas_and_survives_restart(self):
        data,body = self.create()
        status,out,_ = self.command(self.project+'/compositions',{}, {},body=body,service=self.make_service())
        self.assertEqual(status,201,out)
        self.assertTrue(out['command']['replayed'])
        self.assertEqual(out['data'],data)
        changed = copy.deepcopy(body)
        changed['input']['name'] = 'Different'
        self.assertEqual(self.command(self.project+'/compositions',{}, {},body=changed)[0],409)
        status,out = self.get(self.project+'/compositions',dict(include_archived=False))
        self.assertEqual(out['data']['total'],1)

    def test_key_route_and_command_identity_conflicts(self):
        data,body = self.create()
        changed = copy.deepcopy(body)
        changed['command_id'] = uid()
        status,out,_ = self.command(self.project+'/compositions',{}, {},body=changed)
        self.assertEqual(status,409,out)
        self.assertEqual(out['error']['code'],'IDEMPOTENCY_MISMATCH')
        different = copy.deepcopy(body)
        different['idempotency_key'] = uid()
        self.assertEqual(self.command(self.project+'/compositions',{}, {},body=different)[0],409)

    def test_atomic_cas_transaction_and_immutable_old_version(self):
        data,_ = self.create()
        original = copy.deepcopy(data['version'])
        status,out,body = self.transact(data)
        self.assertEqual(status,200,out)
        new = out['data']
        self.assertEqual(new['composition']['composition_revision'],2)
        self.assertEqual(new['version']['parent_version_id'],original['version_id'])
        status,old = self.get(self.cpath(data),dict(version_id=original['version_id']))
        self.assertEqual(status,200,old)
        self.assertEqual(old['data']['version'],original)
        self.assertFalse(old['data']['is_head'])
        conflict = self.transact(data)
        self.assertEqual(conflict[0],409,conflict)
        replay = self.transact(data,body=body)
        self.assertEqual(replay[0],200,replay)
        self.assertEqual(replay[1]['data'],new)
        self.assertTrue(replay[1]['command']['replayed'])

    def test_full_batch_failure_has_no_public_or_private_partial_change(self):
        data,_ = self.create()
        cid = data['composition']['composition_id']
        before = self.service.resolve_binding('native-A',cid)
        status,out,_ = self.transact(data,[self.rename_track(data),dict(op='not.allowed')])
        self.assertEqual(status,422,out)
        after = self.service.resolve_binding('native-A',cid)
        self.assertEqual(before['version'],after['version'])
        self.assertEqual(before['private_project_revision'],after['private_project_revision'])

    def test_metadata_does_not_advance_content_or_native_registry(self):
        data,_ = self.create()
        before = copy.deepcopy(self.records)
        status,out,_ = self.command(self.cpath(data)+'/metadata',dict(metadata_revision=1),dict(name='Renamed'))
        self.assertEqual(status,200,out)
        summary = out['data']['composition']
        self.assertEqual(summary['metadata_revision'],2)
        self.assertEqual(summary['composition_revision'],1)
        self.assertEqual(summary['head_version_id'],data['version']['version_id'])
        self.assertEqual(self.records,before)

    def test_duplicate_gets_distinct_store_and_editorial_ids(self):
        original,_ = self.create()
        status,out,_ = self.command(self.cpath(original)+'/duplicate',{**self.pin(original),'catalog_revision':2},
                                  dict(source_version_id=original['version']['version_id'],name='Copy',include_rights_assertions=False))
        self.assertEqual(status,201,out)
        duplicate = out['data']
        a = self.service.resolve_binding('native-A',original['composition']['composition_id'])
        b = self.service.resolve_binding('native-A',duplicate['composition']['composition_id'])
        self.assertNotEqual(a['private_project_id'],b['private_project_id'])
        self.assertFalse({t['track_id'] for t in original['version']['tracks']} & {t['track_id'] for t in duplicate['version']['tracks']})
        self.assertEqual(duplicate['version']['composition_revision'],1)

    def test_archive_readable_but_edit_denied_restore_keeps_content(self):
        data,_ = self.create()
        path = self.cpath(data)
        status,out,_ = self.command(path+'/archive',dict(metadata_revision=1,catalog_revision=2),dict(archived=True,acknowledge_running_jobs=False))
        self.assertEqual(status,200,out)
        self.assertTrue(self.get(path)[1]['data']['constraints']['read_only'])
        self.assertEqual(self.transact(data)[0],403)
        self.assertEqual(self.get(self.project+'/compositions',dict(include_archived=False))[1]['data']['total'],0)
        status,out,_ = self.command(path+'/archive',dict(metadata_revision=2,catalog_revision=3),dict(archived=False,acknowledge_running_jobs=False))
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['composition']['composition_revision'],1)

    def test_undo_redo_append_new_heads(self):
        original,_ = self.create()
        status,out,_ = self.transact(original)
        self.assertEqual(status,200,out)
        edited = out['data']
        status,out,_ = self.command(self.cpath(original)+'/undo',self.pin(edited),dict(undo_token=edited['undo_token'],direction='undo'))
        self.assertEqual(status,200,out)
        undone = out['data']
        self.assertEqual(undone['version']['sha256'],original['version']['sha256'])
        self.assertEqual(undone['composition']['composition_revision'],3)
        status,out,_ = self.command(self.cpath(original)+'/undo',self.pin(undone),dict(undo_token=undone['undo_token'],direction='redo'))
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['version']['sha256'],edited['version']['sha256'])
        self.assertEqual(out['data']['composition']['composition_revision'],4)

    def test_stale_undo_conflict_and_recovery_requires_authorized_context(self):
        original,_ = self.create()
        _,first,_ = self.transact(original)
        edited = first['data']
        _,second,_ = self.transact(edited,[self.rename_track(edited,'Another')])
        head = second['data']
        status,out,_ = self.command(self.cpath(head)+'/undo',self.pin(head),dict(undo_token=edited['undo_token'],direction='undo'))
        self.assertEqual(status,409,out)
        status,out,_ = self.command(self.cpath(head)+'/recover',self.pin(head),dict(source_version_id='version_notreferenced',reason='Recovery',acknowledge_invalidations=True))
        self.assertEqual(status,422,out)

    def test_scope_assertions_do_not_choose_storage_or_authority(self):
        for key in ('profile_id','backend_instance_id','connection_id','native_project_id'):
            bad = copy.deepcopy(self.scope); bad[key] = 'foreign'
            status,out,_ = self.command(self.project+'/compositions',dict(catalog_revision=1),dict(name='No',format=self.format,template_ref=None),scope=bad)
            self.assertEqual(status,400,(key,out))
            self.assertEqual(out['error']['code'],'SCOPE_MISMATCH')
        self.assertFalse(self.root.exists())

    def test_connection_alias_changes_do_not_change_storage_ownership(self):
        data,_ = self.create()
        other = self.make_service(connection_id='remote-sdk-route')
        status,out = self.get(self.cpath(data),service=other)
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['version'],data['version'])
        self.assertEqual(other.database,self.service.database)
        self.assertEqual(out['scope']['connection_id'],'remote-sdk-route')
        foreign = self.make_service(profile_id='other-profile')
        self.assertEqual(self.get(self.cpath(data),service=foreign)[0],404)

    def test_principal_separation_and_command_status_hash(self):
        data,body = self.create()
        path = self.project+'/compositions'
        sha = UIService.request_hash('OP-COMPOSITION-CREATE',path,body)
        query = dict(scope=self.scope,request_sha256=sha)
        status,out = self.get('/commands/'+body['command_id'],query)
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['status'],'committed')
        self.assertEqual(self.get('/commands/'+body['command_id'],query,principal='other-principal')[0],404)
        bad = dict(query,request_sha256='0'*64)
        self.assertEqual(self.get('/commands/'+body['command_id'],bad)[0],409)
        self.assertEqual(sha,UIService.request_hash('OP-COMPOSITION-CREATE',path,{**body,'command_id':uid(),'idempotency_key':uid()}))

    def test_cross_native_composition_version_and_receipt_are_not_found(self):
        data,body = self.create()
        cid = data['composition']['composition_id']
        self.assertEqual(self.get('/projects/native-B/compositions/'+cid)[0],404)
        status,out = self.get('/commands/'+body['command_id'],dict(scope={**self.scope,'native_project_id':'native-B'},request_sha256='0'*64))
        self.assertEqual(status,404,out)

    def test_cursor_snapshot_stable_across_new_creates_and_filters(self):
        self.create('A',1); self.create('B',2)
        status,first = self.get(self.project+'/compositions',dict(include_archived=False,limit=1))
        self.assertEqual(status,200,first)
        self.assertEqual(first['data']['total'],2)
        self.assertTrue(first['data']['has_more'])
        self.create('C',3)
        cursor = first['data']['next_cursor']
        status,second = self.get(self.project+'/compositions',dict(include_archived=False,limit=1,cursor=cursor),service=self.make_service())
        self.assertEqual(status,200,second)
        self.assertEqual(second['data']['total'],2)
        self.assertFalse(second['data']['has_more'])
        self.assertNotEqual(first['data']['items'][0]['composition_id'],second['data']['items'][0]['composition_id'])
        self.assertEqual(self.get(self.project+'/compositions',dict(include_archived=True,limit=1,cursor=cursor))[0],422)

    def test_event_outbox_receipt_and_filtered_cursor_advancement(self):
        first,_ = self.create('A',1)
        self.create('B',2)
        query = dict(after_cursor=None,wait_ms=0,limit=1,composition_id=first['composition']['composition_id'])
        status,one = self.get(self.project+'/events',query)
        self.assertEqual(status,200,one)
        self.assertEqual(len(one['data']['items']),1)
        event = one['data']['items'][0]
        self.assertTrue(event['sequence'].isdigit())
        receipt = self.get(self.project+'/receipts/'+event['receipt_id'])
        self.assertEqual(receipt[0],200,receipt)
        self.assertEqual(receipt[1]['data']['command_id'],event['command_id'])
        query['after_cursor'] = one['data']['next_cursor']
        _,two = self.get(self.project+'/events',query)
        self.assertEqual(two['data']['items'],[])
        self.assertNotEqual(two['data']['next_cursor'],one['data']['next_cursor'])
        foreign = dict(query,after_cursor=one['data']['next_cursor'])
        # A foreign composition filter is an inaccessible resource, not a
        # cursor-validation error. Test the cursor independently below.
        status,out = self.get('/projects/native-B/events',foreign)
        self.assertEqual(status,404,out)
        self.assertEqual(out['error']['code'],'NOT_FOUND')

    def test_foreign_event_cursor_is_rejected_without_composition_filter(self):
        self.create()
        query = dict(after_cursor=None,wait_ms=0,limit=1)
        status,out = self.get(self.project+'/events',query)
        self.assertEqual(status,200,out)
        foreign = {**query,'after_cursor':out['data']['next_cursor']}
        status,out = self.get('/projects/native-B/events',foreign)
        self.assertEqual(status,422,out)
        self.assertEqual(out['error']['code'],'CURSOR_SCOPE_MISMATCH')
        self.assertNotIn('data',out)
        status,out = self.get('/projects/native-B/events',query)
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['items'],[])

    def test_settings_cas_nonsecret_defaults_and_no_execution(self):
        status,out = self.get('/settings')
        self.assertEqual(status,200,out)
        prefs = out['data']['preferences']
        prefs['default_sample_rate'] = 44100
        scope = {k:v for k,v in self.scope.items() if k!='native_project_id'}
        status,out,body = self.command('/settings',dict(settings_revision=1),dict(preferences=prefs),scope=scope)
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['settings_revision'],2)
        self.assertIsNone(out['meta']['event_cursor'])
        replay = self.command('/settings',{}, {},body=body,service=self.make_service())
        self.assertEqual(replay[0],200,replay)
        self.assertFalse((self.service.directory/'engine').exists())

    def test_adapter_receives_trusted_frozen_context_once_on_retry(self):
        callback = Mock(return_value=(202,dict(job_id='job_12345678',state='queued')))
        self.integrations['OP-JOB-LAUNCH'] = callback
        self.service = self.make_service()
        data,_ = self.create()
        input = dict(preflight_id='preflight_12345678',plan_id='plan_12345678',plan_sha256='a'*64,effects_sha256='b'*64,approval_refs=[],client_intent='launch_exact_saved_version')
        status,out,body = self.command(self.cpath(data)+'/jobs',self.pin(data),input)
        self.assertEqual(status,202,out)
        trusted,actual,pre = callback.call_args.args
        self.assertEqual(trusted['principal'],'host')
        self.assertEqual(trusted['version']['version_id'],data['version']['version_id'])
        self.assertIn('private_project_id',trusted)
        self.assertNotIn(trusted['private_project_id'],json.dumps(out))
        status,replay,_ = self.command(self.cpath(data)+'/jobs',{}, {},body=body)
        self.assertEqual(status,202,replay)
        self.assertEqual(callback.call_count,1)
        self.assertEqual(replay['command']['receipt_id'],out['command']['receipt_id'])

    def test_uncertain_external_submission_is_not_blindly_retried(self):
        callback = Mock(side_effect=RuntimeError('lost after submit'))
        self.integrations['OP-AUTHORITY-REQUEST'] = callback
        self.service = self.make_service()
        data,_ = self.create()
        input = dict(kind='run_permission',subject_refs=[],subject_sha256='a'*64,purpose='test',limits=dict(operation_schema_ref=None,asset_ids=[],destination_ids=[],expires_at=None),reason='Bound request')
        path = self.cpath(data)+'/authority-requests'
        status,out,body = self.command(path,self.pin(data),input)
        self.assertEqual(status,503,out)
        self.assertEqual(out['error']['effect_state'],'unknown')
        status,replay,_ = self.command(path,{}, {},body=body,service=self.make_service())
        self.assertEqual(status,202,replay)
        self.assertEqual(callback.call_count,1)
        self.assertEqual(replay['data']['status'],'unknown')

    def test_missing_approval_bridge_and_binary_transport_are_explicit(self):
        data,_ = self.create()
        input = dict(kind='creative_acceptance',subject_refs=[],subject_sha256='a'*64,purpose='No forged grant',limits=dict(operation_schema_ref=None,asset_ids=[],destination_ids=[],expires_at=None),reason='Request')
        status,out,_ = self.command(self.cpath(data)+'/authority-requests',self.pin(data),input)
        self.assertEqual(status,503,out)
        self.assertEqual(out['error']['code'],'APPROVAL_BRIDGE_UNAVAILABLE')
        self.assertEqual(self.get(self.project+'/media-access/access_12345678/bytes')[1]['error']['code'],'HOST_TRANSPORT_REQUIRED')

    def test_arbitrary_dispatch_and_private_adapter_output_are_rejected(self):
        data,_ = self.create()
        self.assertEqual(self.service.handle('POST',self.cpath(data)+'/execute',body={})[0],404)
        bad = Mock(return_value=dict(project_id='prj_private',password='not-a-secret-fixture'))
        service = self.make_service(integrations={'OP-ASSET':bad})
        status,out = self.get(self.project+'/assets/asset_12345678',service=service)
        self.assertEqual(status,503,out)
        self.assertNotIn('prj_private',json.dumps(out))

    def test_policy_documents_need_host_permission_not_renderer_claim(self):
        data,_ = self.create()
        catalog = schema_catalog()
        op = dict(op='document.put',kind='execution_policy',document_id=None,create_ref=uid(),schema_ref=catalog['execution_policy']['schema_ref'],
                  value=dict(remote='deny',allowed_destinations=[],paid='deny',max_concurrent_nodes=1,retain_generated_assets=True),expected_document_sha256=None)
        status,out,_ = self.transact(data,[op])
        self.assertEqual(status,403,out)
        self.assertEqual(out['error']['code'],'PERMISSION_DENIED')

    def test_root_broker_uses_exact_advertised_opaque_roots(self):
        broker = Mock()
        broker.roots.return_value = dict(items=[dict(root_id='root_12345678',name='Media',root_revision='r1',primary=True,available=True,reason=None)])
        broker.browse.return_value = dict(items=[],next_cursor=None,has_more=False,total=0,snapshot_id='page_12345678')
        service = self.make_service(integrations={'root_broker':broker})
        status,out = self.get(self.project+'/context',service=service)
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['roots'][0]['root_id'],'root_12345678')
        query = dict(parent_node_id=None,expected_root_revision='r1',kind_filter='all')
        status,out = self.get(self.project+'/roots/root_12345678/entries',query,service=service)
        self.assertEqual(status,200,out)
        broker.browse.assert_called_once_with('native-A','root_12345678',**query)

    def test_missing_preconditions_unknown_fields_and_unsafe_numbers(self):
        input = dict(name='Composition',format=self.format,template_ref=None)
        self.assertEqual(self.command(self.project+'/compositions',{},input)[0],428)
        self.assertEqual(self.command(self.project+'/compositions',dict(catalog_revision=1),{**input,'approved':True})[0],400)
        self.assertEqual(self.command(self.project+'/compositions',dict(catalog_revision=True),input)[0],400)
        self.assertEqual(self.get('/projects',dict(include_archived=False,limit=201))[0],400)
        self.assertEqual(self.get('/projects',dict(include_archived='false'))[0],400)

    def test_local_publication_crash_replays_real_core_receipt(self):
        original = self.service._commit_compiled
        calls = []
        def commit_then_disconnect(*args):
            value = original(*args)
            calls.append(value)
            raise RuntimeError('Disconnect after durable core publication')
        with patch.object(self.service,'_commit_compiled',side_effect=commit_then_disconnect):
            status,out,body = self.command(self.project+'/compositions',dict(catalog_revision=1),dict(name='Recover',format=self.format,template_ref=None))
        self.assertEqual(status,503,out)
        self.assertEqual(out['error']['effect_state'],'unknown')
        status,out,_ = self.command(self.project+'/compositions',{}, {},body=body,service=self.make_service())
        self.assertEqual(status,201,out)
        binding = self.service.resolve_binding('native-A',out['data']['composition']['composition_id'])
        self.assertEqual(binding['private_project_revision'],calls[0])
        self.assertEqual(self.get(self.project+'/compositions',dict(include_archived=False))[1]['data']['total'],1)

    def test_admitted_proposal_apply_is_one_content_transaction(self):
        original,_ = self.create()
        proposal_id = 'proposal_12345678'
        proposal = dict(proposal_id=proposal_id,entity_revision=1,base_version_id=original['version']['version_id'],
                        base_composition_revision=1,operations=[self.rename_track(original,'Proposal edit')],
                        dependency_hashes=[],expected_effects=[],source_evidence=[dict(kind='trusted_tool_result',id='evidence_12345678')],
                        expires_at='2099-01-01T00:00:00Z',validity=dict(state='valid'),diff=[])
        self.service = self.make_service(integrations={'OP-PROPOSALS':lambda context,input,pre:dict(items=[copy.deepcopy(proposal)])})
        status,out = self.get(self.cpath(original)+'/proposals',dict(state='pending'))
        self.assertEqual(status,200,out)
        admitted = out['data']['items'][0]
        status,out,body = self.command(self.cpath(original)+'/proposals/'+proposal_id+'/decision',
                       {**self.pin(original),'entity_revision':1},dict(decision='apply',proposal_sha256=admitted['sha256'],reason='Reviewed exact diff',acknowledged_dependency_ids=[]))
        self.assertEqual(status,200,out)
        self.assertEqual(out['data']['composition']['composition_revision'],2)
        self.assertEqual(out['data']['decision'],'apply')
        status,stored = self.get(self.cpath(original)+'/proposals/'+proposal_id)
        self.assertEqual(status,200,stored)
        self.assertEqual(stored['data']['state'],'applied')
        self.assertEqual(stored['data']['entity_revision'],2)

    def test_cached_adapter_resource_survives_restart_without_fake_live_observation(self):
        data,_ = self.create()
        callback = Mock(return_value=(201,dict(preflight_id='preflight_12345678',preflight_sha256='a'*64,
                         version_id=data['version']['version_id'],plan_id='plan_12345678',plan_sha256='b'*64,effects_sha256='c'*64,
                         readiness='blocked',blockers=[dict(code='ENGINE_UNAVAILABLE')],required_approvals=[],expires_at='2099-01-01T00:00:00Z')))
        service = self.make_service(integrations={'OP-PREFLIGHT':callback})
        status,out,_ = self.command(self.cpath(data)+'/preflights',self.pin(data),
                         dict(action='render',recipe_ref=dict(id='recipe',version=1,sha256='d'*64),parameters={},dependency_hashes=[],probe_policy='cached_only',acknowledged_effects=[]),service=service)
        self.assertEqual(status,201,out)
        status,out = self.get(self.cpath(data)+'/preflights/preflight_12345678',service=self.make_service())
        self.assertEqual(status,200,out)
        self.assertEqual(out['meta']['freshness']['kind'],'cached')
        self.assertFalse(out['data']['launchable'])
        self.assertEqual(callback.call_count,1)

    def test_archive_requires_acknowledgement_for_retained_accepted_job(self):
        data,_ = self.create()
        service = self.make_service(integrations={'OP-JOB-LAUNCH':lambda context,input,pre:(202,dict(job_id='job_12345678',state='queued'))})
        status,out,_ = self.command(self.cpath(data)+'/jobs',self.pin(data),dict(preflight_id='preflight_12345678',plan_id='plan_12345678',
                       plan_sha256='a'*64,effects_sha256='b'*64,approval_refs=[],client_intent='launch_exact_saved_version'),service=service)
        self.assertEqual(status,202,out)
        status,out,_ = self.command(self.cpath(data)+'/archive',dict(metadata_revision=1,catalog_revision=2),
                                   dict(archived=True,acknowledge_running_jobs=False),service=self.make_service())
        self.assertEqual(status,409,out)
        self.assertEqual(out['error']['code'],'ACTIVE_JOBS')


    def canonical_create(self):
        recipe = dict(id='ui-rgb-lossless-v1',color='srgb-rgb-full-unmanaged-v1',background=[3,5,7,255],caption_style=None)
        fmt = {**self.format,'width':320,'height':180}
        status,out,_ = self.command(self.project+'/compositions',dict(catalog_revision=1),
            dict(name='Canonical',format=fmt,template_ref=None,render_recipe=recipe))
        self.assertEqual(status,201,out)
        return out['data'],recipe

    def recovery_review(self,data,head=None) -> dict[str,Any]:
        base = data['version']
        current = (head or data)['version']
        return dict(source={k:base[k] for k in ('composition_id','version_id','composition_revision','sha256')},
            current_head={k:current[k] for k in ('composition_id','version_id','composition_revision','sha256')},
            base_graph_sha256=_hash(self.service._graph(base)),schema_catalog_sha256=_hash(schema_catalog()),
            transaction=dict(operations=[self.rename_track(data,'Recovered draft')],
                dependency_policy='reject_unlisted',acknowledged_dependency_ids=[],document_rebind_ids=[]))

    def test_canonical_closure_persisted_without_fake_native_scene_projection(self):
        data,recipe = self.canonical_create()
        sref,lref = uid(),uid()
        operations = [dict(op='scene.create',create_ref=sref,name='Paint',duration_frames=30,background=[10,20,30,255]),
            dict(op='layer.create',create_ref=lref,scene_id=sref,type='shape',schema_ref=schema_catalog()['layer.shape']['schema_ref'],
                order=0,start_frame=0,end_frame=30,parameters=dict(shape='rectangle',color=[255,0,0,255],
                    transform=dict(x=0,y=0,width=100,height=50,rotation_mdeg=0,opacity_milli=1000,crop=None)),keyframes=[]),
            self.scene_placement(data,sref)]
        status,out,body = self.transact(data,operations)
        self.assertEqual(status,200,out)
        version = out['data']['version']
        self.assertEqual(version['render_recipe'],recipe)
        self.assertEqual(len(version['layers']),1)
        self.assertEqual(version['scenes'][0]['background'],[10,20,30,255])
        db = self.service._connect()
        try:
            comp = self.service._composition(db,'native-A',data['composition']['composition_id'])
            frozen = db.execute('SELECT * FROM canonical_sources WHERE version=?',(version['version_id'],)).fetchone()
            work = json.loads(db.execute('SELECT work FROM commands WHERE command_id=?',(body['command_id'],)).fetchone()['work'])
            closure,pin = json.loads(frozen['closure']),json.loads(frozen['artifact'])
            self.assertEqual(closure['graph'],self.service._graph(version))
            self.assertEqual(closure['recipe'],recipe)
            self.assertEqual(closure['schemas'],schema_catalog())
            self.assertEqual(pin['sha256'],engine_digest(closure))
            fs = self.service.store._filesystem()
            pointer = self.service.store._pointer(fs,comp['private_id'])
            _,documents = self.service.store._load(fs,pointer)
            self.assertFalse(any(kind=='scene' for kind,_ in documents))
            tx = self.service.store._transaction(fs,pointer)
            expected = dict(action='update',project_id=comp['private_id'],expected_revision=work['private_revision'],
                request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,_hash([self.service.owner,'host','native-A',body['command_id']])+':compile')),
                compiled_documents=closure)
            self.assertEqual(tx['request_sha256'],self.service.store._request_hash(expected))
        finally:
            db.close()
        self.assertEqual(self.transact(data,body=body)[1]['data']['version'],version)

    def scene_placement(self,data,scene_ref):
        return dict(op='clip.insert',create_ref=uid(),
            track_id=next(t['track_id'] for t in data['version']['tracks'] if t['kind']=='video'),
            subject=dict(kind='scene',id=scene_ref,version_id=None),start_frame=0,end_frame=30,
            source_mapping=dict(domain='frame',in_index=0,out_index=30,rate=copy.deepcopy(self.format['fps']),speed=dict(num=1,den=1)),
            linked_group_id=None,enabled=True)

    def test_historical_identity_stays_frozen_when_authoritative_native_head_advances(self):
        data,_ = self.canonical_create()
        sref = uid()
        status,out,_ = self.transact(data,[
            dict(op='scene.create',create_ref=sref,name='Paint',duration_frames=30,background=[10,20,30,255]),
            self.scene_placement(data,sref)])
        self.assertEqual(status,200,out)
        data = out['data']
        cid = data['composition']['composition_id']
        before = self.service.resolve_binding('native-A',cid,version_id=data['version']['version_id'])
        db = self.service._connect()
        try:
            closure = json.loads(db.execute('SELECT closure FROM canonical_sources WHERE version=?',(data['version']['version_id'],)).fetchone()['closure'])
        finally:
            db.close()
        newer = self.service._commit_compiled(before['private_project_id'],before['private_project_revision'],uid(),closure)
        after = self.service.resolve_binding('native-A',cid,version_id=data['version']['version_id'])
        self.assertEqual(after['version'],before['version'])
        self.assertEqual(after['source_private_project_revision'],before['source_private_project_revision'])
        self.assertEqual(after['private_project_revision'],newer)
        status,out,_ = self.transact(data)
        self.assertEqual(status,200,out)

    def test_recovery_review_and_recover_as_new_use_exact_helper_without_duplicate(self):
        data,_ = self.create()
        review = self.recovery_review(data)
        pre = {**self.pin(data),'catalog_revision':2}
        status,out,review_body = self.command(self.cpath(data)+'/recovery-review',pre,dict(review=review))
        self.assertEqual(status,200,out)
        token = out['data']
        self.assertEqual(token['review_sha256'],_hash(review))
        self.assertEqual(token['blockers'],[])
        from studio.ui_recovery import prepare_recovery
        with patch('studio.ui_recovery.prepare_recovery',wraps=prepare_recovery) as prepare:
            status,out,body = self.command(self.cpath(data)+'/recover-as-new',pre,
                dict(name='Recovered',review=review,review_token=token['review_token']))
        self.assertEqual(prepare.call_count,1)
        self.assertEqual(status,201,out)
        recovered = out['data']
        self.assertNotEqual(recovered['composition']['composition_id'],data['composition']['composition_id'])
        self.assertIsNone(recovered['version']['parent_version_id'])
        self.assertEqual(recovered['recovery_receipt']['state'],'committed')
        mapping = recovered['entity_id_mapping']
        self.assertEqual({mapping[t['track_id']] for t in data['version']['tracks']},
                         {t['track_id'] for t in recovered['version']['tracks']})
        self.assertIn('Recovered draft',{t['name'] for t in recovered['version']['tracks']})
        self.assertEqual(self.get(self.cpath(recovered))[1]['data']['version'],recovered['version'])
        self.assertEqual(self.get(self.cpath(data))[1]['data']['version'],data['version'])
        self.assertEqual(self.get('/commands/'+review_body['command_id'],dict(scope=self.scope,
            request_sha256=self.service.request_hash('OP-RECOVERY-REVIEW',self.cpath(data)+'/recovery-review',review_body)))[1]['data']['status'],'committed')
        status,replayed,_ = self.command(self.cpath(data)+'/recover-as-new',pre,body['input'],body=body)
        self.assertEqual(status,201,replayed)
        self.assertEqual(replayed['data'],recovered)

    def test_recovery_review_rejects_transaction_envelope_fields_and_missing_rebinds(self):
        data,_ = self.create()
        review = self.recovery_review(data)
        pre = {**self.pin(data),'catalog_revision':2}
        invalid = []
        for field,value in (('gesture_id',uid()),('summary','Not a recovery field')):
            changed = copy.deepcopy(review)
            changed['transaction'][field] = value
            invalid.append(changed)
        changed = copy.deepcopy(review)
        del changed['transaction']['document_rebind_ids']
        invalid.append(changed)
        for value in invalid:
            with self.subTest(transaction=value['transaction']):
                status,out,_ = self.command(self.cpath(data)+'/recovery-review',pre,dict(review=value))
                self.assertEqual(status,400,out)
                self.assertEqual(out['error']['code'],'INVALID_ARGUMENT')
                self.assertEqual(out['error']['effect_state'],'none')
        db = self.service._connect()
        try:
            self.assertEqual(db.execute('SELECT count(*) FROM recovery_reviews').fetchone()[0],0)
        finally:
            db.close()
        self.assertEqual(self.get(self.cpath(data))[1]['data']['version'],data['version'])
        self.assertEqual(self.get(self.project+'/compositions',dict(include_archived=False))[1]['data']['total'],1)

    def test_recovery_token_rejects_modified_review_and_other_principal(self):
        data,_ = self.create()
        review = self.recovery_review(data)
        pre = {**self.pin(data),'catalog_revision':2}
        status,out,_ = self.command(self.cpath(data)+'/recovery-review',pre,dict(review=review))
        self.assertEqual(status,200,out)
        modified = copy.deepcopy(review)
        modified['transaction']['operations'][0]['name'] = 'Changed after review'
        for value,principal,code in ((modified,'host','RECOVERY_REVIEW_CHANGED'),
                                     (review,'other-principal','RECOVERY_REVIEW_REQUIRED')):
            status,failed,_ = self.command(self.cpath(data)+'/recover-as-new',pre,
                dict(name='Must not exist',review=value,review_token=out['data']['review_token']),principal=principal)
            self.assertGreaterEqual(status,400,failed)
            self.assertEqual(failed['error']['code'],code)
        self.assertEqual(self.get(self.project+'/compositions',dict(include_archived=False))[1]['data']['total'],1)

    def test_source_hydration_never_accepts_browser_private_refs(self):
        data,_ = self.create()
        pin = dict(asset_id='asset_'+uid(),asset_version_id='av_'+uid(),sha256='a'*64)
        source = {**pin,'artifact':dict(artifact_id='art_'+uid(),sha256='sha256:'+'a'*64),'kind':'video','rate':self.format['fps'],'duration_frames':30}
        resolver = Mock(return_value=source)
        service = self.make_service(integrations={'_asset_source_resolver':resolver})
        graph = service._graph(data['version'])
        context = dict(scope=self.scope,principal='host',composition=data['composition'])
        hydrated = service._hydrate_assets(graph,context,[pin])
        self.assertEqual(hydrated['asset_refs'],[source])
        self.assertEqual(graph['asset_refs'],[])
        self.assertEqual(resolver.call_args.args[1],pin)
        with self.assertRaises(ContractError):
            service._hydrate_assets(graph,context,[source])
        self.assertEqual(resolver.call_count,1)

    def test_import_bound_source_atomic_insert_save_reopen_and_cas(self):
        """Real immutable import/association/hydration, synthetic probe facts only.

        No decoder or execution grant: the native receipt read is a fixture.
        """
        import io
        from types import SimpleNamespace
        from studio.ui_files import UIFileBroker
        from studio.ui_media import UIMedia
        from studio.ui_execution import UIExecution
        data,_ = self.create()
        context = {**self.service.resolve_binding('native-A',data['composition']['composition_id']),
                   'principal':'host','params':{}}
        media = UIMedia(self.root/'test-media',lambda:self.records,
                        UIFileBroker(self.root/'test-handles',lambda:self.records))
        execution = UIExecution(media)
        body = b'\x89PNG\r\n\x1a\nunit bytes, not decoded media'
        with media.database(context,write=True) as (db,fs):
            blob,fingerprint,length = media._copy(fs,io.BytesIO(body),'fixture.png',len(body))
            asset = media._admit(db,fs,context,blob,'fixture.png',fingerprint,length,uid(),[])
            association = media.associate(db,context,asset,uid())
        self.assertEqual(asset['usages'],[])
        native = dict(asset={'artifact':association['pin']},latest_probe=None)
        execution.runtime = lambda ctx: SimpleNamespace(asset=lambda args:{'ok':True,'data':copy.deepcopy(native)})
        self.integrations.update({'OP-ASSET-BIND':execution.callback,'_asset_source_resolver':media.resolve_source,
                                 '_execution_adapter':execution,'_media_store':media})
        self.service = self.make_service()
        bind_input = dict(asset_version_id=asset['asset_version_id'],sha256=asset['sha256'],receipt_id='rcp_'+uid(),stream_index=0)
        bind_pre = {**self.pin(data),'entity_revision':asset['entity_revision']}
        bind_path = self.cpath(data)+'/assets/'+asset['asset_id']+'/bind'
        status,out,_ = self.command(bind_path,bind_pre,bind_input)
        self.assertEqual(out['error']['code'],'PROBE_REQUIRED',out)
        native['latest_probe'] = dict(schema='motion/v1/probe-receipt',artifact=association['pin'],
            receipt_id=bind_input['receipt_id'],full_decode='not_tested',vfr='no',
            streams=[dict(index=0,type='video',rate=self.format['fps'],frame_count=30)])
        status,bound,bind_body = self.command(bind_path,bind_pre,bind_input)
        self.assertEqual(status,200,bound)
        self.assertEqual(bound['data']['readiness'],'bound')
        self.assertNotIn('artifact',bound['data']['source_facts'])
        self.assertEqual(self.command(bind_path,bind_pre,bind_input,body=bind_body)[1]['data'],bound['data'])
        self.assertEqual(self.get(self.cpath(data))[1]['data']['version']['asset_refs'],[bound['data']['source_facts']])
        data = bound['data']
        placement = self.scene_placement(data,uid())
        placement['subject'] = dict(kind='asset',id=asset['asset_id'],version_id=asset['asset_version_id'])
        pin = {k:asset[k] for k in ('asset_id','asset_version_id','sha256')}
        # Match saveDraft: a saved source pin needs no new asset_refs payload.
        payload = dict(operations=[placement],gesture_id=uid(),summary='Reviewed insertion',dependency_policy='reject_unlisted',acknowledged_dependency_ids=[])
        status,saved,frozen = self.command(self.cpath(data)+'/transactions',self.pin(data),payload)
        self.assertEqual(status,200,saved)
        saved_data = saved['data']
        self.assertEqual(saved_data['version']['asset_refs'],[bound['data']['source_facts']])
        self.assertEqual(len(saved_data['version']['clips']),1)
        reopened = self.make_service()
        self.assertEqual(self.get(self.cpath(data),service=reopened)[1]['data']['version'],saved_data['version'])
        self.assertEqual(self.command(self.cpath(data)+'/transactions',self.pin(data),payload,body=frozen,service=reopened)[1]['data'],saved_data)
        status,stale,_ = self.command(self.cpath(data)+'/transactions',self.pin(data),payload)
        self.assertEqual(stale['error']['code'],'REVISION_CONFLICT',stale)
        changed = copy.deepcopy(payload)
        changed['asset_refs'] = [{**pin,'sha256':'f'*64}]
        status,failed,_ = self.command(self.cpath(data)+'/transactions',self.pin(saved_data),changed)
        self.assertEqual(failed['error']['code'],'ASSET_UNRESOLVED',failed)
        changed['asset_refs'] = [{**pin,'asset_version_id':'assetversion_'+uid()}]
        status,failed,_ = self.command(self.cpath(data)+'/transactions',self.pin(saved_data),changed)
        self.assertEqual(failed['error']['code'],'ASSET_UNRESOLVED',failed)
        other,_ = self.create(name='Other',catalog=2)
        status,failed,_ = self.command(self.cpath(other)+'/transactions',self.pin(other),payload)
        self.assertGreaterEqual(status,400,failed)
        status,failed,_ = self.command(self.cpath(data)+'/transactions',self.pin(saved_data),payload,principal='other')
        self.assertGreaterEqual(status,400,failed)
        self.assertEqual(self.get(self.cpath(data))[1]['data']['version'],saved_data['version'])

    def test_finite_source_routes_are_registered_with_exact_docstring_fields(self):
        from studio.ui_service import ROUTES,LOCAL_COMMANDS
        routes = {op:(verb,pre,fields) for verb,pattern,op,pre,fields,optional in ROUTES}
        for op in ('OP-ASSET-PROBE','OP-ASSET-BIND'):
            self.assertEqual(routes[op][0],'POST')
            self.assertEqual(set(routes[op][1].split()),{'entity_revision','composition_revision','version_id'})
        self.assertEqual(set(routes['OP-ASSET-PROBE'][2].split()),{'asset_version_id','sha256','full_decode'})
        self.assertEqual(set(routes['OP-ASSET-BIND'][2].split()),{'asset_version_id','sha256','receipt_id','stream_index'})
        self.assertIn('OP-ASSET-BIND',LOCAL_COMMANDS)


if __name__ == '__main__':
    unittest.main()
