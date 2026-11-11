"""Stdio-only test bridge: packaged core, actual remote context, fake model, temp DB."""
import importlib
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import zipfile
from typing import Any, cast
from tests.test_native_package import FakeRemoteRuntime, HOST, BUNDLE
from tests.synthesis_support import route, selection
from tests.producer_support import fixture_binding, effects
from studio.producer.evaluation import enable_evaluation


def main():
    sys.path.insert(0, str(HOST))
    from hermes_cli.plugin_host_child import _import_plugin, RemotePluginContext
    with tempfile.TemporaryDirectory(prefix='motion-native-fixture-') as temp:
        with zipfile.ZipFile(BUNDLE) as archive: archive.extractall(temp)
        if os.environ.get('SFX_REPAIR_DELTA'):
            from tools.prepare_sfx_development_repair import CHANGED, verify
            delta = Path(os.environ['SFX_REPAIR_DELTA'])
            verify(delta)
            for name in CHANGED:
                (Path(temp)/'motion-studio'/name).write_bytes((delta/'after'/name).read_bytes())
        remote = FakeRemoteRuntime(Path(temp)/'owned-data')
        key = 'offline_motion_browser'
        ctx = RemotePluginContext(cast(Any, remote), key, dict(plugin_id='motion-studio', profile_name='fixture', ctx_methods=['register_rpc','register_tool','register_system_prompt_section']))
        module = _import_plugin(dict(path=str(Path(temp)/'motion-studio'), module_name=key))
        runtime = module.register(ctx)
        entered, release = threading.Event(), threading.Event()
        remote.facade.hook = lambda:(entered.set(), release.wait(30))
        prepares = 0
        starts = 0
        lost_prepare = None
        lost_start = None
        creation_binding = None
        try:
            for line in sys.stdin:
                message = json.loads(line)
                try:
                    operation = message['op']
                    if operation == 'admit-creation-fixture':
                        creation = runtime.creation
                        creation.policy = replace(creation.policy, profile='fixture', revision='offline-fixture',
                            audience='Gateway-authorized session controllers/operators, including multiple clients',
                            direction_audio=True, canonical_roots=True, agent_starts=True, delegated_starts=True,
                            local_generator=True, create_store=True)
                        creation.acquire()
                        fixture_mode = message.get('fixture_mode', 'good')
                        if fixture_mode not in ('good', 'comparison'):
                            raise ValueError('Unsupported fixture mode')
                        creation_binding = fixture_binding(Path(temp)/'fake-generator', mode=fixture_mode)
                        creation.runs.binding = creation_binding
                        creation.runs.bindings.allow_fixtures = True
                        seeded = creation.runs.bindings.seed(creation_binding)
                        binding = enable_evaluation(creation.runs.bindings, seeded['id'], seeded['revision'])
                        creation.policy = replace(creation.policy,binding=binding['id'],binding_revision=binding['revision'])
                        result = remote.methods['creation.admit']({},session_id='session-a')
                    elif operation == 'admit-production-fixture':
                        policy_type = importlib.import_module(key+'.studio.native.production.policy').ProductionAssociation
                        runtime.production.association = policy_type(profile='fixture',
                            revision='offline-production-fixture', production_management=True,
                            direction_audio=True, canonical_roots=True)
                        runtime.production.acquire()
                        result = remote.methods['production.admit']({},session_id='session-a')
                    elif operation == 'admit-music-fixture':
                        from tests.music_support import attach
                        attach(runtime.creation, Path(temp)/'music-test')
                        result = remote.methods['creation.admit_music']({},session_id='session-a')
                    elif operation == 'revoke-music-fixture':
                        runtime.creation.policy = replace(runtime.creation.policy,
                            music=replace(runtime.creation.policy.music,prepare=False,effects=False))
                        result = dict(revoked=True)
                    elif operation == 'revoke-production-fixture':
                        runtime.production.association = replace(runtime.production.association,
                                                                 production_management=False)
                        result = dict(revoked=True)
                    elif operation == 'production-tool':
                        result = json.loads(remote.tools['motion_studio_production']['handler'](message['args'],
                            session_id=message.get('session','physical-compressed'),conversation_id=message.get('root','session-a')))
                        if message.get('discard_reply'):
                            result = {'delivered':False}
                    elif operation == 'tool':
                        if message['args']['operation'] == 'prepare':
                            prepares += 1
                        elif message['args']['operation'] == 'start':
                            starts += 1
                        result = json.loads(remote.tools['motion_studio_creation']['handler'](message['args'],
                            session_id=message.get('session','physical-compressed'),conversation_id=message.get('root','session-a')))
                        if message.get('discard_prepare_reply'):
                            if message['args']['operation'] != 'prepare':
                                raise ValueError('Only a Prepare reply can be discarded by this fixture')
                            lost_prepare = {key:result[key] for key in ('request','revision','command','run')}
                            result = {'delivered':False}
                        if message.get('discard_start_reply'):
                            if message['args']['operation'] != 'start':
                                raise ValueError('Only a Start reply can be discarded by this fixture')
                            lost_start = {key:result[key] for key in ('request','revision','command','run')}
                            result = {'delivered':False}
                    elif operation == 'lost-prepare-identity':
                        result = dict(lost_prepare) if lost_prepare else None
                    elif operation == 'lost-start-identity':
                        result = dict(lost_start) if lost_start else None
                    elif operation == 'settle-creation':
                        for worker in runtime.creation.runs.threads.values(): worker.join(10)
                        result = dict(settled=True)
                    elif operation == 'admit-fixture':
                        policy = importlib.import_module(key+'.studio.native.technical.runtime').TechnicalPolicy
                        runtime.policy = policy(audience_accepted=True, revision='offline-only', create_store=True, route=route())
                        result = {'fixture_only':True}
                    elif operation == 'docs': result = selection()
                    elif operation == 'entered': result = {'entered':entered.wait(5)}
                    elif operation == 'release':
                        release.set()
                        for worker in runtime.service.workers: worker.join(5)
                        result = {'settled':all(not w.is_alive() for w in runtime.service.workers)}
                    elif operation == 'counts':
                        counts = dict(takes=0, runs=0, requests=0, media_files=0, production_revisions=0)
                        if runtime.creation.store:
                            with runtime.creation.store.transaction() as db:
                                for table, count_key in (('takes','takes'),('local_runs','runs'),('requests','requests'),
                                                   ('production_revisions','production_revisions')):
                                    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                                        (table,)).fetchone()
                                    if exists:
                                        counts[count_key] = db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                            counts['media_files'] = len(list((runtime.creation.store.home/'media').iterdir()))
                        result = dict(model_calls=len(remote.facade.calls), prepare_dispatches=prepares,
                            start_dispatches=starts, state_created=remote.root.exists(),
                            creation_effects=len(effects(creation_binding)) if creation_binding else 0,
                            music_effects=(__import__('tests.music_support',fromlist=['effect_count']).effect_count(runtime.creation)
                                           if runtime.creation.store else 0), **counts)
                    elif operation == 'connection-roots':
                        # Controlled fixture identities only; never opens a live store.
                        with runtime.creation.store.transaction() as db:
                            result = {name: [row[0] for row in db.execute('SELECT root FROM '+name+'_roots ORDER BY root')]
                                      for name in ('creation', 'production')}
                    elif operation == 'rpc':
                        method = message['method']
                        if method == 'prepare': prepares += 1
                        payload = dict(message['payload']);session = payload.pop('session_id', None)
                        name = method if method.startswith(('creation.','production.')) else 'technical.'+method
                        result = remote.methods[name](payload, session_id=session)
                    else: raise ValueError('Unsupported fixture operation')
                    print(json.dumps(dict(id=message['id'], result=result)), flush=True)
                except Exception:
                    print(json.dumps(dict(id=message['id'], error='FIXTURE_OPERATION_FAILED')), flush=True)
        finally:
            release.set()
            if runtime.service:
                for worker in runtime.service.workers: worker.join(5)
            runtime.unload()
            runtime.creation.unload()
            if runtime.retirement: runtime.retirement.join(5)


if __name__ == '__main__': main()
