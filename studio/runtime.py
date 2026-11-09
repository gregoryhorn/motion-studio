"""Lazy native service boundary. No models, workers or processes at registration."""
from __future__ import annotations

import copy
import json
import shutil

from .contracts import ContractError, digest
from .project import ProjectStore, _fs_error


def _failure(tool, args, exc):
    return {'ok': False, 'tool': tool, 'action': args.get('action', '') if isinstance(args, dict) else '',
            'status': 'error' if exc.code in ('VALIDATION_ERROR', 'INVALID_ARGUMENT') else 'blocked',
            'summary': exc.message, 'error': {'code': exc.code, 'message': exc.message,
            'details': exc.details, 'retry': 'after_input_change' if exc.code in ('INVALID_ARGUMENT', 'VALIDATION_ERROR') else 'after_dependency', 'effect': exc.effect}}


class NativeRuntime:
    def __init__(self, projects=None, *, registry=None, adapter_resolver=None,
                 output_probe=None, host_bridge=None):
        self.projects = projects or ProjectStore()
        self._registry = registry
        self._compiler = self._artifacts = None
        self._adapter_resolver = adapter_resolver
        from .adapters.probe import LocalOutputProbe
        self.output_probe = LocalOutputProbe() if output_probe is None else output_probe
        self.host_bridge = host_bridge

    @property
    def artifacts(self):
        if self._artifacts is None:
            from .artifacts import ArtifactCatalog
            from .jobs import JobStore
            self._artifacts = ArtifactCatalog(self.projects, jobs=JobStore(self.projects))
        return self._artifacts

    @property
    def compiler(self):
        if self._compiler is None:
            from .plans import PlanCompiler
            from .adapters import ffmpeg
            from .engine_identity import local_engine_identity
            self._compiler = PlanCompiler.from_core(self.projects, self.registry,
                artifact_resolver=self.artifacts.resolve, manifest_resolver=self.artifacts.publish_plan,
                timing_validator=self._validate_timing,reuse_lookup=self._reuse_outputs,
                engine_identity=local_engine_identity, host_bridge=self.host_bridge)
        return self._compiler

    def _reuse_outputs(self,project_id,fingerprint,expected_outputs):
        """Find exact committed ports; admission revalidates the producer again.

        Prefer the oldest valid producer so an unchanged scene keeps its original
        artifact identity even if an earlier caller unnecessarily rerendered it.
        """
        fs=self.projects._filesystem();jobs=self.jobs()
        bundles=[jobs.read(project_id,name[:-5]) for name in fs.names(self.projects._base(project_id)+'/jobs')
            if name.endswith('.json')]
        for bundle in sorted(bundles,key=lambda value:(value['job']['created_at'],value['job']['job_id'])):
            for node in bundle['plan_record']['nodes']:
                if node['fingerprint']!=fingerprint or node['expected_outputs']!=expected_outputs:continue
                state=next(value for value in bundle['job']['node_states'] if value['node_id']==node['node_id'])
                if state['state']!='succeeded':continue
                ports=bundle.get('output_ports',{}).get(node['node_id'],{})
                pins=[ports.get(spec['port']) for spec in expected_outputs]
                if (any(pin is None for pin in pins) or state['outputs'] != pins
                        or len({pin['artifact_id'] for pin in pins}) != len(pins)):
                    continue
                try:
                    records=[self.artifacts.resolve(project_id,pin) for pin in pins]
                except ContractError:
                    continue
                if all(record['kind']==spec['kind'] and record['media_type']==spec['media_type']
                        and record['producer']['job_id'] == bundle['job']['job_id']
                        and record['producer']['node_id'] == node['node_id']
                        for record,spec in zip(records,expected_outputs)):
                    return pins
        return None

    def _validate_timing(self, project_id, request, metadata, documents):
        from .adapters import ui_compositor
        if request.get('adapter_id') == ui_compositor.ADAPTER_ID:
            def resolve_source(pin):
                # Ownership and byte integrity are checked by ArtifactCatalog;
                # only this bounded JSON source is decoded, never media.
                from .contracts import canonical
                record = self.artifacts.resolve(project_id, pin)
                with self.artifacts.open_record(self.projects._filesystem(), record) as source:
                    raw = source.read(ui_compositor.MAX_SOURCE_BYTES + 1)
                if len(raw) > ui_compositor.MAX_SOURCE_BYTES:
                    raise ContractError('LIMIT_EXCEEDED', 'Canonical graph source exceeds the byte bound.')
                try:
                    value = json.loads(raw.decode('utf-8'))
                except (ValueError, RecursionError) as exc:
                    raise ContractError('INVALID_ARGUMENT', 'Canonical graph source is not bounded UTF-8 JSON.') from exc
                if canonical(value) != raw or digest(value) != pin['sha256']:
                    raise ContractError('HASH_MISMATCH', 'Canonical graph source bytes differ from the frozen pin.')
                return value
            return ui_compositor.validate_timing(project_id, request, metadata, documents,
                                                resolve_source=resolve_source)
        from .adapters import blender, alignment
        if request.get('adapter_id') in (blender.ADAPTER_ID, alignment.ADAPTER_ID):
            selected = blender if request['adapter_id'] == blender.ADAPTER_ID else alignment
            return selected.validate_timing(project_id, request, metadata, documents,
                resolve_artifact=lambda pin: self.artifact_path(project_id, pin))
        from .adapters import ytdlp
        if request.get('adapter_id') == ytdlp.ADAPTER_ID:
            try:
                ytdlp.validate_parameters(request['parameters'])
            except ValueError as exc:
                raise ContractError('INVALID_ARGUMENT', str(exc)) from exc
            return []
        from .adapters import local_audio
        if request.get('adapter_id') in local_audio.BINDINGS:
            return local_audio.validate_timing(project_id, request, metadata, documents,
                resolve_artifact=lambda pin: self.artifact_path(project_id, pin))
        from .adapters import filmmaking
        if request.get('adapter_id') == filmmaking.ADAPTER_ID:
            return filmmaking.validate_timing(project_id, request, metadata, documents,
                resolve_artifact=lambda pin: self.artifact_path(project_id, pin), projects=self.projects)
        from .host_bridge import ADAPTER_ID as FRAME_ADAPTER_ID, validate_frame_timing
        if request.get('adapter_id') == FRAME_ADAPTER_ID:
            return validate_frame_timing(request,
                resolve_artifact=lambda pin: self.artifact_path(project_id, pin))
        from .adapters import ffmpeg, speech, conform, finishing, reframe
        from .adapters.native_tools import BINDINGS, install_builtins
        install_builtins()
        if request.get('adapter_id') in BINDINGS:
            return BINDINGS[request['adapter_id']].timing(request,
                resolve_artifact=lambda pin: self.artifact_path(project_id, pin))
        from .adapters.delivery import ADAPTER_ID as DELIVERY_ID
        if request.get('adapter_id') == DELIVERY_ID:
            return []
        adapter = {speech.ADAPTER_ID: speech, conform.ADAPTER_ID: conform, finishing.ADAPTER_ID: finishing,
                   reframe.ADAPTER_ID: reframe}.get(
            request.get("adapter_id"), ffmpeg)
        return adapter.validate_timing(project_id, request, metadata, documents,
            resolve_artifact=lambda pin: self.artifact_path(project_id, pin))

    def asset(self, args, *, session_id=None, task_id=None):
        from .assets import AssetStore
        result = AssetStore(self.projects.root, probe=lambda request: self._asset_probe(
            request, session_id=session_id, task_id=task_id)).dispatch(args)
        if result.get('ok') and args.get('action') == 'get':
            try:
                result['data']['latest_probe'] = self._latest_probe(
                    args['project_id'], result['data']['asset']['artifact'])
            except ContractError as exc:
                return _failure('motion_asset', args, exc)
        return result

    def _asset_probe(self, args, *, session_id=None, task_id=None):
        pid = args['project_id']
        compiled = self.plan(dict(action='compile', project_id=pid,
            expected_revision=args['expected_revision'], request_id=args['request_id'],
            targets=['probe'], requests=[dict(target_key='probe', operation='media.probe@1',
                adapter_id=args['adapter_id'], inputs=dict(media=dict(kind='artifact', artifact=args['artifact'])),
                parameters=dict(full_decode=args['full_decode']))]))
        if not compiled.get('ok'):
            return {**compiled, 'tool':'motion_asset', 'action':'probe'}
        plan = compiled['data']['plan']['plan']
        submit = dict(action='submit', project_id=pid, expected_revision=args['expected_revision'],
                      request_id=args['request_id'], plan=plan)
        if 'authority_ref' in args:
            submit['authority_ref'] = args['authority_ref']
        result = self.run(submit, session_id=session_id, task_id=task_id)
        result = copy.deepcopy(result)
        result.update(tool='motion_asset', action='probe')
        if result.get('ok'):
            result['data']['plan'] = plan
        else:
            result['error']['effect'] = 'committed'
        return result

    def _latest_probe(self, project_id, artifact):
        fs = self.projects._filesystem()
        jobs = self.jobs()
        receipts = []
        for name in fs.names(self.projects._base(project_id) + '/jobs'):
            if not name.endswith('.json'):
                continue
            bundle = jobs.read(project_id, name[:-5])
            for record in bundle['artifacts']:
                if (record['producer']['adapter_id'] != 'ffmpeg.probe' or
                        record['kind'] != 'report' or artifact not in record['inputs']):
                    continue
                pin = {key:record[key] for key in ('artifact_id','sha256')}
                record = self.artifacts.resolve(project_id, pin)
                with self.artifacts.open_record(fs, record) as stream:
                    receipt = json.loads(stream.read())
                if receipt.get('schema') != 'motion/v1/probe-receipt' or receipt.get('artifact') != artifact:
                    raise ContractError('HASH_MISMATCH','Committed probe report does not bind its source.')
                receipts.append(receipt)
        return max(receipts, key=lambda r:(r['observed_at'], r['receipt_id'])) if receipts else None

    def caption(self, args, *, session_id=None, task_id=None):
        from .artifacts import CaptionArtifacts
        from .captions import CaptionStore
        if isinstance(args, dict) and args.get('action') in ('export', 'preview'):
            from .delivery import NativeDeliveryService
            try:
                executor = NativeDeliveryService(self, session_id=session_id, task_id=task_id).executor
                value = (executor.caption_preview(args) if args['action'] == 'preview'
                         else executor.caption_export(args))
                return {'ok': True, 'data': value, 'warnings': []}
            except (ContractError, KeyError, ValueError) as exc:
                return {'ok': False, 'error': {'code': getattr(exc, 'code', 'INVALID_ARGUMENT'), 'message': str(exc), 'effect': getattr(exc, 'effect', 'none')}}
        # Host correlation identifies the acting agent, never a human reviewer.
        actor = ({"kind": "agent", "actor_ref": "hermes-session:" + session_id}
                 if isinstance(session_id, str) and session_id.strip() else None)
        return CaptionStore(self.projects.root, artifacts=CaptionArtifacts(self.projects),
                            actor=actor, execute=lambda request: self._caption_execute(
                                request, session_id=session_id, task_id=task_id)).dispatch(args)

    def _caption_execute(self, args, *, session_id=None, task_id=None):
        """Compile corrected-text alignment through the existing authority/job path."""
        from .adapters import alignment
        from .delivery import NativeDeliveryService
        if args['action'] != 'align' or args['adapter_id'] != alignment.ADAPTER_ID:
            raise ContractError('UNSUPPORTED_OPERATION', 'Select the explicit local corrected-text alignment adapter.')
        document = self.document(args['project_id'], args['caption'])['document']
        caption = document['value']
        schema = alignment.registration()['schemas'][alignment.MODEL_OPTIONS]
        task = dict(target_key='corrected_text_alignment', operation='speech.align@1',
            adapter_id=alignment.ADAPTER_ID,
            inputs=dict(audio=dict(kind='artifact',artifact=args['audio']),
                        caption=dict(kind='document',document=args['caption'])),
            parameters=dict(language=caption['language'],granularity=caption['granularity']),
            binding_parameters=dict(schema_id=alignment.MODEL_OPTIONS,schema_sha256=digest(schema),values=args['model']))
        executor = NativeDeliveryService(self,session_id=session_id,task_id=task_id).executor
        return executor.submit_tasks(args,[task])

    def document(self, project_id, pin):
        from .contracts import D, validate
        validate(pin, D['DocumentRef'])
        fs = self.projects._filesystem()
        pointer = self.projects._pointer(fs, project_id)
        matched = None
        while pointer:
            _, docs = self.projects._load(fs, pointer)
            doc = docs.get((pin['kind'], pin['id']))
            if doc and doc['revision'] == pin['revision'] and digest(doc) == pin['sha256']:
                matched = (doc, docs)
            elif matched is not None:
                break
            pointer = self.projects._transaction(fs, pointer)['previous']
        if matched is None:
            raise ContractError('NOT_FOUND', 'Frozen document does not belong to project history.')
        doc, docs = matched
        inputs, scenes = [], set()
        def collect(value):
            if isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                if set(value) == {'artifact_id', 'sha256'}:
                    if value not in inputs:
                        inputs.append(copy.deepcopy(value))
                elif value.get('kind') == 'scene' and 'scene_id' in value:
                    sid = value['scene_id']
                    if sid not in scenes:
                        scenes.add(sid)
                        scene = docs.get(('scene', sid))
                        if scene is None:
                            raise ContractError('NOT_FOUND', 'Frozen document scene dependency is missing.')
                        collect(scene['value'])
                else:
                    for item in value.values():
                        collect(item)
        collect(doc['value'])
        artifact = self.artifacts.publish_json(project_id, doc, inputs=inputs)
        return {'document': copy.deepcopy(doc), 'artifact': self.artifacts.resolve(project_id, artifact)}

    def artifact_path(self, project_id, pin):
        if 'artifact_id' in pin:
            record = self.artifacts.resolve(project_id, pin)
        else:
            record = self.document(project_id, pin)['artifact']
        fs = self.projects._filesystem()
        storage = record['storage']
        if storage['mode'] == 'external':
            return storage['source']['path']
        base = self.projects._base(project_id)
        relative = storage['relative_path']
        return fs.root / (relative if relative.startswith(base + '/') else base + '/' + relative)

    def adapter_resolver(self, binding):
        if self._adapter_resolver is not None:
            return self._adapter_resolver(binding)
        from .adapters import ui_compositor
        if binding.get('adapter_id') == ui_compositor.ADAPTER_ID:
            return ui_compositor.LocalUICompositorAdapter(self, copy.deepcopy(binding))
        from .adapters import ytdlp
        if binding.get('adapter_id') == ytdlp.ADAPTER_ID:
            return ytdlp.YtDlpAdapter(self, copy.deepcopy(binding))
        from .adapters.native_tools import BINDINGS, NativeToolAdapter, install_builtins
        install_builtins()
        if binding.get('adapter_id') in BINDINGS:
            return NativeToolAdapter(self, copy.deepcopy(binding))
        from .adapters import local_audio
        if binding.get('adapter_id') in local_audio.BINDINGS:
            return local_audio.LocalAudioAdapter(self, copy.deepcopy(binding))
        from .adapters import filmmaking
        if binding.get('adapter_id') == filmmaking.ADAPTER_ID:
            return filmmaking.FilmmakingAdapter(self, binding)
        from .host_bridge import ADAPTER_ID as FRAME_ADAPTER_ID, FrameAdapter
        from .adapters.delivery import ADAPTER_ID as DELIVERY_ID, DeliveryAdapter
        if binding.get('adapter_id') == DELIVERY_ID:
            return DeliveryAdapter(self, copy.deepcopy(binding))
        if binding.get('adapter_id') == FRAME_ADAPTER_ID:
            return FrameAdapter(self, binding)
        from .adapters import ffmpeg, alternative, speech, conform, finishing, blender, alignment, reframe
        if binding.get('adapter_id') == reframe.ADAPTER_ID:
            return reframe.LocalReframeAdapter(self, binding)
        if binding.get('adapter_id') == blender.ADAPTER_ID:
            return blender.BlenderAdapter(self, binding)
        if binding.get('adapter_id') == alignment.ADAPTER_ID:
            return alignment.LocalAlignmentAdapter(self, binding)
        if binding.get('adapter_id') == finishing.ADAPTER_ID:
            return finishing.LocalFinishingAdapter(self, binding)
        if binding.get("adapter_id") == conform.ADAPTER_ID:
            return conform.LocalConformAdapter(self, copy.deepcopy(binding))
        if binding.get("adapter_id") == speech.ADAPTER_ID:
            return speech.LocalSpeechAdapter(self, copy.deepcopy(binding))
        if binding.get("adapter_id") == "ffmpeg.probe":
            from .adapters.media_probe import MediaProbeAdapter
            return MediaProbeAdapter(self, binding)
        if binding.get('adapter_id') in alternative.ADAPTER_IDS:
            return LocalAlternativeAdapter(self, copy.deepcopy(binding))
        if binding.get('adapter_id') != ffmpeg.ADAPTER_ID:
            raise ContractError('UNSUPPORTED_OPERATION', 'No executable binding for this registered declaration.')
        return LocalFFmpegAdapter(self, copy.deepcopy(binding))

    def _check_engine_plan(self, plan):
        """Recompute frozen semantic bindings before *either* reuse or effects.

        Read the producing snapshot, not the mutable latest project. This also
        works after runtime restart; no in-memory identity receipt is trusted.
        Engine discovery is passive and reuse lookup is deliberately disabled.
        """
        from .plans import PlanCompiler
        from .contracts import ContractError
        compiler = self.compiler
        if compiler.engine_identity is None:
            return
        fs = self.projects._filesystem()
        pointer = self.projects._pointer(fs, plan['project_id'])
        while pointer['revision'] > plan['project_revision']:
            pointer = self.projects._transaction(fs, pointer)['previous']
        if (pointer['revision'] != plan['project_revision'] or
                pointer['snapshot_sha256'] != plan['snapshot_sha256']):
            raise ContractError('HASH_MISMATCH', 'Frozen engine-check snapshot differs from the producing plan.')
        snapshot, documents = self.projects._load(fs, pointer)
        checker = PlanCompiler.from_core(self.projects, self.registry,
            artifact_resolver=compiler.artifact_resolver,
            manifest_resolver=compiler.manifest_resolver,
            timing_validator=compiler.timing_validator,
            engine_identity=compiler.engine_identity, host_bridge=self.host_bridge)
        args = {'project_id': plan['project_id'], 'requests': copy.deepcopy(plan['requests']),
                'targets': plan['targets'], 'reuse_outputs': False}
        observed = checker._graph(args, pointer, snapshot, documents, plan['plan_id'])
        expected = {node['node_id']: node['fingerprint'] for node in plan['nodes']}
        actual = {node['node_id']: node['fingerprint'] for node in observed['nodes']}
        if observed['status'] != 'ready' or actual != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE',
                'Engine/dependency identity changed after compilation; explicitly recompile before reuse or execution.')

    def jobs(self, *, authority=None):
        from .jobs import JobStore
        runtime = self

        class EngineCheckedJobStore(JobStore):
            def _reuse_outputs(self, plan, node):
                # Worker reuse bypasses _check_node; guard that exact path too.
                runtime._check_engine_plan(plan)
                return super()._reuse_outputs(plan, node)

            def _check_node(self, plan, node, bundle=None, *, admission=False):
                # This precedes JobStore's early reuse return and is repeated at
                # the execution boundary, not only at queue admission.
                runtime._check_engine_plan(plan)
                return super()._check_node(plan, node, bundle, admission=admission)

        def validate_selected_request(request):
            from .options import validate_selection
            return validate_selection(self.registry, request['selection'],
                operation=request['operation'], parameters=request['parameters'],
                binding_parameters=request.get('binding_parameters'),
                required_features=request.get('required_features', []), bridge=self.host_bridge)

        return EngineCheckedJobStore(self.projects, plan_reader=self.compiler.load, authority=authority,
            adapter_resolver=self.adapter_resolver, artifact_resolver=self.artifacts.resolve,
            document_resolver=self.document, output_probe=self.output_probe, host_bridge=self.host_bridge,
            selection_validator=validate_selected_request)

    @property
    def registry(self):
        if self._registry is None:
            from .capabilities import installed_registry
            self._registry = installed_registry()
            from .adapters import ytdlp
            found_ytdlp = ytdlp.discover()
            self._registry.register(**ytdlp.registration(),
                state='available' if not found_ytdlp['missing'] else 'unavailable', checks=[{
                    'name': 'local-acquisition-cli', 'status': 'pass' if not found_ytdlp['missing'] else 'fail',
                    'reason': json.dumps(found_ytdlp, sort_keys=True) + '; Passive PATH presence only; no network or production qualification.'}])
            from .host_bridge import register_frame_adapter
            register_frame_adapter(self._registry, self.host_bridge)
            from .adapters.native_tools import register_adapters
            register_adapters(self._registry, self.host_bridge)
            from .adapters import local_audio
            for aid in local_audio.BINDINGS:
                observed_audio = local_audio.discover(aid)
                self._registry.register(**local_audio.registration(aid),
                    state='available' if observed_audio['available'] else 'unavailable', checks=[{
                        'name': 'local-runtime-files', 'status': 'pass' if observed_audio['available'] else 'fail',
                        'reason': json.dumps(observed_audio, sort_keys=True) +
                            '; Passive file presence only; no model load, GPU test or generation.'}])
            from .adapters import speech
            observed = speech.discover()
            self._registry.register(**speech.registration(),
                state="available" if observed["installed"] else "unavailable", checks=[{
                    "name":"engine-presence", "status":"pass" if observed["installed"] else "fail",
                    "reason":"Metadata-only engine presence. Every execution requires an explicit local model path/hash; no model was selected or loaded."}])
            from .adapters import ffmpeg
            metadata = ffmpeg.registration()
            available = all(shutil.which(n) for n in ('ffmpeg', 'ffprobe'))
            metadata.update(state='available' if available else 'unavailable', checks=[{
                'name': 'executables', 'status': 'pass' if available else 'fail',
                'reason': 'Read-only PATH presence; no process or media validation performed.'}])
            self._registry.register(**metadata)
            from .adapters import ui_compositor
            from importlib.metadata import PackageNotFoundError, distribution
            missing_compositor = [name for name in ('ffmpeg', 'ffprobe') if shutil.which(name) is None]
            for name in ('Pillow', 'av'):
                try:
                    distribution(name)
                except PackageNotFoundError:
                    missing_compositor.append(name)
            self._registry.register(**ui_compositor.registration(),
                state='unavailable' if missing_compositor else 'available', checks=[{
                    'name': 'canonical-compositor-dependencies',
                    'status': 'fail' if missing_compositor else 'pass',
                    'reason': 'Passive PATH/distribution metadata only; no rendering qualification. Missing: ' + ', '.join(missing_compositor)}])
            from .adapters import filmmaking
            from .adapters import finishing, reframe
            reframing = reframe.discover()
            self._registry.register(**reframe.registration(), state=reframing['status'], checks=[{
                'name': 'local-reframe-dependencies', 'status': 'pass' if reframing['status'] == 'available' else 'fail',
                'reason': reframing['reason']}])
            finish = finishing.discover()
            self._registry.register(**finishing.registration(), state=finish['status'], checks=[{
                'name': 'local-finishing-dependencies', 'status': 'pass' if finish['status'] == 'available' else 'fail',
                'reason': finish['reason']}])
            from .adapters import blender, alignment
            physical = blender.discover()
            self._registry.register(**blender.registration(),
                state='available' if physical['available'] else 'unavailable', checks=[{
                    'name':'blender-path', 'status':'pass' if physical['available'] else 'fail',
                    'reason':'Passive PATH presence only; native scenes have not been rendered.'}])
            aligner = alignment.discover()
            self._registry.register(**alignment.registration(),
                state='available' if aligner['installed'] else 'unavailable', checks=[{
                    'name':'whisperx-package', 'status':'pass' if aligner['installed'] else 'fail',
                    'reason':'Package metadata only; explicit pinned local model required at execution.'}])
            host = filmmaking.discover()
            self._registry.register(**filmmaking.registration(),
                state='available' if host['available'] else 'unavailable', checks=[{
                    'name': 'local-film-dependencies', 'status': 'pass' if host['available'] else 'fail',
                    'reason': 'Passive local discovery; missing: ' + ', '.join(host['missing'])}])
            from .adapters import delivery
            self._registry.register(**delivery.registration(), state='available', checks=[{
                'name':'local-delivery', 'status':'pass' if available else 'fail', 'reason':'Safe ZIP closure; legacy chart reconstruction is unsupported after renderer removal.'}])
            from .adapters import conform
            self._registry.register(**conform.registration(),
                state='available' if available else 'unavailable', checks=[{
                    'name':'executables', 'status':'pass' if available else 'fail',
                    'reason':'Read-only ffmpeg/ffprobe PATH presence; explicit bounded audio sample and video frame conform.'}])
            from .adapters import alternative
            found = alternative.discover()
            available_by_id = {
                alternative.BREEZE_ID: bool(found['breeze']),
                alternative.ESPEAK_ID: bool(found['espeak_ng']),
                alternative.FLITE_ID: bool(found['flite'] and found['flite_voice'])}
            for adapter_id in alternative.ADAPTER_IDS:
                metadata = alternative.registration(adapter_id)
                available = available_by_id[adapter_id]
                metadata.update(state='available' if available else 'unavailable', checks=[{
                    'name':'installed_dependencies','status':'pass' if available else 'fail',
                    'reason':'Read-only dependency presence; no engine startup or qualification implied.'}])
                self._registry.register(**metadata)
        return self._registry

    def _call(self, tool, args, operation):
        try:
            data = operation()
            result = {'ok': True, 'tool': tool, 'action': args.get('action', '') if isinstance(args, dict) else '', 'status': 'ok',
                      'summary': 'Read or metadata action accepted; no execution authorized.', 'data': data}
            if isinstance(args, dict) and 'project_id' in args:
                result['project_id'] = args['project_id']
            return result
        except ContractError as exc:
            return _failure(tool, args, exc)
        except FileNotFoundError:
            return _failure(tool, args, ContractError('NOT_FOUND', 'Project or service record unavailable.'))
        except OSError as exc:
            return _failure(tool, args, _fs_error(exc))
        except (KeyError, ValueError, TypeError):
            return _failure(tool, args, ContractError('HASH_MISMATCH', 'Stored service record is invalid.'))

    def project(self, args):
        """The public project transaction plus current voice identity admission."""
        def admission():
            from .contracts import validate_request
            validate_request(args)
            if args['action'] == 'update':
                from .voice_preferences import validate_voice_preferences
                for change in args['changes']:
                    if change['op'] == 'set_voice_preferences':
                        validate_voice_preferences(change['value'], self.registry,
                            project_id=args['project_id'], authorize_reference=self.authorize_voice_reference)
            return {}
        admitted = self._call('motion_project', args, admission)
        return self.projects.dispatch(args) if admitted.get('ok') else admitted

    def authorize_voice_reference(self, project_id, reference):
        from .voice_runtime import authorize_reference
        return authorize_reference(self, project_id, reference)

    def voice(self, args, *, session_id=None):
        from .voice_runtime import dispatch
        return self._call('motion_capabilities', args,
            lambda: dispatch(self, args, session_id=session_id))

    def _compile_request(self, args):
        """Freeze chosen voice defaults before ordinary compile/permission hashing."""
        from .plans import PLAN_REQUEST_SCHEMA
        self.compiler._checked(args, PLAN_REQUEST_SCHEMA)
        if args.get('action') != 'compile':
            return self.compiler.dispatch(args)
        prepared = copy.deepcopy(args)
        voice_tasks = [task for task in prepared['requests']
            if task['operation'] == 'speech.synthesize@1' and
            (task.get('use_voice_defaults') or 'voice_preferences' in task or not task['parameters'])]
        if voice_tasks:
            from .voice_runtime import resolve_compile_voice
            fs = self.projects._filesystem()
            pointer = self.projects._pointer(fs, args['project_id'])
            if pointer['revision'] != args['expected_revision']:
                raise ContractError('REVISION_CONFLICT', 'Project changed before resolving voice defaults.')
            _, documents = self.projects._load(fs, pointer)
            settings = documents['settings', 'project']['value']
            prepared['requests'] = [resolve_compile_voice(self, args['project_id'], task, settings)
                if task in voice_tasks else task for task in prepared['requests']]
        return self.compiler.dispatch(prepared)

    def plan(self, args, *, session_id=None):
        if isinstance(args, dict) and args.get('action') in ('interchange_import', 'interchange_export'):
            from .interchange import dispatch, branches
            from .capabilities import checked
            def interchange_call():
                checked(args, {'oneOf': branches()})
                return dispatch(self, args)
            return self._call('motion_plan', args, interchange_call)
        if isinstance(args, dict) and args.get('action') in ('eta', 'eta_calibrate'):
            from .eta import dispatch, branches
            from .capabilities import checked
            def eta_call():
                checked(args, {'oneOf': branches()})
                return dispatch(self, args)
            return self._call('motion_plan', args, eta_call)
        if isinstance(args, dict) and args.get('action') in ('editorial_get', 'editorial_update',
                'editorial_reconform', 'extract_inspect', 'extract_apply', 'extract_bind', 'full_master_apply', 'full_master_bind'):
            from .editorial import dispatch, branches
            from .capabilities import checked
            def editorial_call():
                checked(args, {'oneOf': branches()})
                return dispatch(self, args)
            return self._call('motion_plan', args, editorial_call)
        if isinstance(args, dict) and args.get('action') in ('creative_get', 'creative_update', 'creative_accept'):
            from .creative import dispatch, schema_branches
            from .capabilities import checked
            def creative_call():
                checked(args, {'oneOf': schema_branches()})
                return dispatch(self, args, session_id=session_id)
            return self._call('motion_plan', args, creative_call)
        result = self._call('motion_plan', args, lambda: self._compile_request(args))
        if result.get('ok') and args['action'] == 'compile' and result['data']['gaps']:
            result.update(ok=False, status='blocked', summary='Blocked plan committed; resolve gaps before execution.')
            result['error'] = {'code': 'PLAN_BLOCKED', 'message': result['summary'],
                'details': {'gaps': result['data']['gaps']}, 'retry': 'after_dependency', 'effect': 'committed'}
        return result

    def run(self, args, *, session_id=None, task_id=None):
        from .permissions import ACTIONS, dispatch
        if isinstance(args, dict) and args.get('action') in ACTIONS:
            return self._call('motion_run', args, lambda: dispatch(self, args, session_id=session_id))
        authority = HermesApprovalAuthority(session_id=session_id, task_id=task_id)
        return self._run_dispatch(args, authority)

    def _run_dispatch(self, args, authority):
        def dispatch():
            jobs = self.jobs(authority=authority)
            accepted = jobs.dispatch(args)
            if accepted.get('ok') and args.get('action') == 'collect':
                bundle = jobs.read(args['project_id'], args['job_id'])
                if bundle['job']['state'] == 'succeeded' and any(n['operation'] in
                        ('delivery.encode@1', 'review.check@1', 'delivery.package@1') for n in bundle['plan_record']['nodes']):
                    from .delivery import NativeDeliveryService
                    accepted['data']['delivery'] = NativeDeliveryService(self).executor.collect(args['project_id'], args['job_id'])
            # A fresh public approval grant stays in this exact worker instance.
            # Replay/read paths cannot manufacture it from a serialized receipt.
            if (accepted.get('ok') and args.get('action') == 'submit'
                    and isinstance(authority, HermesApprovalAuthority) and authority._grant
                    and accepted['data']['job']['state'] == 'queued'):
                jobs.start_worker(args['project_id'], accepted['data']['job']['job_id'])
            return accepted
        result = self._call('motion_run', args, dispatch)
        return result['data'] if result.get('ok') else result

    def capability(self, args, *, session_id=None):
        if isinstance(args, dict) and args.get('action') == 'options':
            from .options import branches, dispatch
            from .capabilities import checked
            # This explicit conversation request loads only passive installed
            # declarations. The projector itself never refreshes/probes engines.
            def options_call():
                checked(args, branches()[0])
                _ = self.registry
                return dispatch(self, args)
            return self._call('motion_capabilities', args, options_call)
        from .voice_runtime import branches as voice_branches
        if isinstance(args, dict) and isinstance(args.get('action'), str) and args['action'] in {
                branch['properties']['action']['const'] for branch in voice_branches()}:
            return self.voice(args, session_id=session_id)
        if isinstance(args, dict) and args.get('action') in ('host_readiness', 'task_overview', 'setup_report', 'topology_check', 'tool_readiness'):
            from .diagnostics import branches, dispatch
            from .capabilities import checked
            def readiness_call():
                checked(args, {'oneOf': branches()})
                return dispatch(self, args)
            return self._call('motion_capabilities', args, readiness_call)
        if isinstance(args, dict) and args.get('action') == 'usage':
            from .usage import UsageLedger
            from .capabilities import checked
            def usage_call():
                checked(args, usage_request_schema())
                return UsageLedger(self.projects, session_id).summary(args.get('project_id'), args.get('task_id'))
            return self._call('motion_capabilities', args, usage_call)
        return self._call('motion_capabilities', args, lambda: self.registry.dispatch(args, self.projects))


class HermesApprovalAuthority:
    """Host policy authorization, explicitly NOT identified human acceptance.

    Only trusted handler kwargs establish agent/session context. An execution
    recheck can reuse this instance's exact grant, never a caller authority_ref.
    """
    def __init__(self, *, session_id=None, task_id=None):
        self.session_id, self.task_id = session_id, task_id
        self._grant = None

    def authorize(self, plan, args):
        effects_sha = digest(plan['effects'])
        if args.get('action') == 'execute':
            if self._grant and self._grant['plan_sha256'] == plan['plan_sha256'] and self._grant['effects_sha256'] == effects_sha and args.get('authority_ref') == self._grant['evidence_ref']:
                return copy.deepcopy(self._grant)
            raise ContractError('PERMISSION_DENIED', 'No exact in-process host-policy grant for worker.')
        try:
            from hermes_cli.plugin_session import session_key, session_surface
            key, surface = session_key(), session_surface()
            session = self.session_id or key
            if not isinstance(session, str) or not session:
                raise ContractError('PERMISSION_DENIED', 'Trusted Hermes session context is unavailable.')
            from tools.approval import request_tool_approval
            reason = 'Execute immutable Motion Studio plan ' + json.dumps({
                'project_id': plan['project_id'], 'plan_id': plan['plan_id'],
                'plan_revision': plan['plan_revision'], 'plan_sha256': plan['plan_sha256'],
                'effects': plan['effects'], 'nodes': plan['nodes']}, sort_keys=True, ensure_ascii=True)
            decision = request_tool_approval('motion_run', reason,
                rule_key='motion_run:' + digest({'plan': plan['plan_sha256'], 'effects': effects_sha}))
        except ContractError:
            raise
        except Exception:
            raise ContractError('PERMISSION_DENIED', 'Hermes approval bridge is unavailable.',
                                details={'approval_outcome': 'bridge_unavailable'}) from None
        if not isinstance(decision, dict) or decision.get('approved') is not True:
            raw = decision.get('outcome') if isinstance(decision, dict) else None
            outcome = raw if raw in ('denied', 'timeout', 'cancelled', 'notify_failed', 'blocked') else 'unavailable'
            raise ContractError('PERMISSION_DENIED', 'Hermes host-policy approval: ' + outcome + '.',
                                details={'approval_outcome': outcome})
        identity = {'session': session, 'task': self.task_id, 'surface': surface,
                    'plan': plan['plan_sha256'], 'effects': effects_sha}
        self._grant = {'evidence_ref': 'motion:host-policy:' + digest(identity),
            'plan_sha256': plan['plan_sha256'], 'effects_sha256': effects_sha,
            'authority_kind': 'host_policy', 'actor': {'kind': 'agent', 'actor_ref': 'hermes:session:' + session},
            'human_acceptance': False}
        return copy.deepcopy(self._grant)


class SessionProvenance:
    """Bounded independent call observation, not a handoff/actor authority bridge."""
    def __init__(self, session_id):
        self.session_id = session_id

    def observe_call(self, call_id):
        if not self.session_id or not isinstance(call_id, str) or not call_id:
            return None
        try:
            from hermes_state import SessionDB
            db = SessionDB(read_only=True)
            try:
                rows = db.get_messages(self.session_id, limit=200, latest=True)
            finally:
                db.close()
            calls = {}
            for row in rows:
                if row.get('role') == 'assistant':
                    for call in row.get('tool_calls') or []:
                        if call.get('id') == call_id:
                            function = call.get('function', {})
                            arguments = function.get('arguments')
                            if isinstance(arguments, str):
                                arguments = json.loads(arguments)
                            if isinstance(arguments, dict):
                                calls[call_id] = {'tool_call_id': call_id, 'tool_name': function.get('name'), 'arguments': arguments}
                if row.get('role') == 'tool' and row.get('tool_call_id') == call_id and call_id in calls:
                    return {**calls[call_id], 'result': row.get('content')}
        except Exception:
            return None
        return None


class LocalFFmpegAdapter:
    """B09 ABI facade. Only owned WorkerContext.run may execute processes."""
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, binding

    def validate_request(self, request):
        from .adapters import ffmpeg
        if request.get('operation') not in ffmpeg.OPERATIONS:
            raise ContractError('UNSUPPORTED_OPERATION', 'Local adapter does not implement this operation.')
        expected = self.runtime.registry.binding(ffmpeg.ADAPTER_ID, request['operation'],
            request['parameters'], request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen binding differs from current executable/schema identity.')
        return {'valid': True, 'effects': copy.deepcopy(ffmpeg.EFFECTS)}

    def execute(self, request, attempt, context=None):
        self.validate_request(request)
        if context is None or not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run is required for local processes.')
        from .adapters import ffmpeg
        return ffmpeg.execute(request, attempt, project_root=self.runtime.projects._filesystem().root,
            resolve_artifact=lambda pin: self.runtime.artifact_path(request['project_id'], pin),
            run_process=context.run, output_probe=self.runtime.output_probe)


class LocalAlternativeAdapter(LocalFFmpegAdapter):
    """B12 facade; executable effects require the same owned process capability."""
    def validate_request(self, request):
        from .adapters import alternative
        adapter_id = self.binding['adapter_id']
        declaration = alternative.declaration(adapter_id)
        if request.get('operation') not in {op['operation'] for op in declaration['operations']}:
            raise ContractError('UNSUPPORTED_OPERATION', 'Alternative binding does not implement this operation.')
        expected = self.runtime.registry.binding(adapter_id, request['operation'],
            request['parameters'], request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen alternative implementation/schema differs.')
        if request.get('operation') == 'speech.synthesize@1':
            from .voice_preferences import validate_voice_request
            validate_voice_request(request, self.runtime.registry,
                authorize_reference=self.runtime.authorize_voice_reference)
        return {'valid':True,'effects':copy.deepcopy(declaration['effects'])}

    def execute(self, request, attempt, context=None):
        self.validate_request(request)
        if context is None or not callable(getattr(context,'run',None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run is required for local processes.')
        from .adapters import alternative
        return alternative.execute(request,attempt,project_root=self.runtime.projects._filesystem().root,
            resolve_artifact=lambda pin:self.runtime.artifact_path(request['project_id'],pin),
            run_process=context.run, output_probe=self.runtime.output_probe,
            authorize_reference=self.runtime.authorize_voice_reference)


def caption_tool_schema():
    from .captions import expanded
    return {"name": "motion_caption",
            "description": "Adopt/read/correct/style canonical captions. Timing approval needs verified audition; unconnected execution routes fail closed.",
            "parameters": copy.deepcopy(expanded("CaptionRequest"))}


def caption_handler(args, **host_context):
    runtime = host_context.pop("_runtime", None) or NativeRuntime()
    return json.dumps(runtime.caption(args, session_id=host_context.get("session_id"), task_id=host_context.get("task_id")),
                      ensure_ascii=True, allow_nan=False)


def usage_request_schema():
    from .contracts import obj, ident, TEXT
    return obj({'action': {'const': 'usage'}, 'project_id': ident('prj'), 'task_id': TEXT},
               ['project_id', 'task_id'])


def capability_tool_schema():
    from .capabilities import capability_tool_schema as parameters
    value = parameters()
    if not isinstance(value, dict):
        raise TypeError('Capability schema must be an object.')
    alternatives = value.get('oneOf')
    if not isinstance(alternatives, list):
        raise TypeError('Capability alternatives must be an array.')
    alternatives.append(usage_request_schema())
    from .diagnostics import branches
    from .capabilities import expanded
    alternatives.extend(expanded(branch) for branch in branches())
    from .options import branches as option_branches
    from .voice_runtime import branches as voice_branches
    alternatives.extend(expanded(branch) for branch in option_branches() + voice_branches())
    return {'name': 'motion_capabilities', 'description': 'Read installed declarations; no engine/model execution.',
            'parameters': value}


def plan_tool_schema(registry=None):
    from .plans import plan_tool_schema as parameters
    from .creative import schema_branches
    from .capabilities import expanded
    value = parameters(registry)
    if not isinstance(value, dict):
        raise TypeError('Plan schema must be an object.')
    value['oneOf'].extend(expanded(branch) for branch in schema_branches())
    from .eta import branches as eta_branches
    from .editorial import branches as editorial_branches
    from .interchange import branches as interchange_branches
    value['oneOf'].extend(expanded(branch) for branch in eta_branches() + editorial_branches() + interchange_branches())
    return {'name': 'motion_plan', 'description': 'Compile immutable plans and inspect verified core manifest handles.',
            'parameters': value}


def run_tool_schema():
    from .jobs import run_tool_schema as schema
    from .permissions import schema_branches
    from .capabilities import expanded
    value = schema()
    value['parameters']['oneOf'].extend(expanded(branch) for branch in schema_branches())
    return value


def capability_handler(args, **host_context):
    runtime = host_context.pop('_runtime', None) or NativeRuntime()
    return json.dumps(runtime.capability(args, session_id=host_context.get('session_id')), ensure_ascii=True, allow_nan=False)


def plan_handler(args, **host_context):
    runtime = host_context.pop('_runtime', None) or NativeRuntime()
    return json.dumps(runtime.plan(args, session_id=host_context.get('session_id')), ensure_ascii=True, allow_nan=False)


def run_handler(args, **host_context):
    runtime = host_context.pop('_runtime', None) or NativeRuntime()
    return json.dumps(runtime.run(args, session_id=host_context.get('session_id'),
        task_id=host_context.get('task_id')), ensure_ascii=True, allow_nan=False)
