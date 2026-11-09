"""Owned replay of retained graphics and explicitly authorized authored HTML films.

Never executes archive argv, resolves live project inputs during replay, or reuses
packaged generated media. HTML source is executable trusted authored JavaScript,
not an OS sandbox. JobStore owns every process. Caption graphs remain excluded.
"""
import copy
import json
import hashlib
from pathlib import Path
from uuid import UUID, uuid5
from .contracts import ContractError, canonical, digest
from .adapters import ffmpeg, filmmaking

SCHEMA = 'motion/v1/native-reconstruction'
OPS = {'scene.render@1', 'audio.mix@1', 'edit.assemble@1', 'delivery.encode@1'}


def unsupported(message):
    raise ContractError('UNSUPPORTED_FEATURE', message)


def identity(include_film=False):
    r = ffmpeg.registration()
    result=dict(adapter_id=ffmpeg.ADAPTER_ID, implementation_sha256=r['implementation_sha256'],
        schema_sha256=digest(dict(schemas=r['schemas'], outputs=r['outputs'])))
    if include_film:result['filmmaking_sha256']=filmmaking.registration()['implementation_sha256']
    return result


def validate_recipe(recipe):
    if not isinstance(recipe, dict) or set(recipe) != {'schema', 'renderer', 'graphs', 'sources', 'documents', 'equivalence'}:
        unsupported('A closed frozen reconstruction recipe is required.')
    include_film=any(node.get('adapter_id')==filmmaking.ADAPTER_ID for graph in recipe.get('graphs',[]) for node in graph.get('nodes',[]))
    if recipe['schema'] != SCHEMA or recipe['equivalence'] != 'decoded_video_and_format' or recipe['renderer'] != identity(include_film):
        unsupported('Reconstruction renderer/schema/equivalence is unsupported or changed.')
    if not recipe['graphs'] or len(recipe['graphs']) > 16:
        unsupported('Bounded nonempty reconstruction graphs required.')
    for graph in recipe['graphs']:
        if set(graph) != {'master', 'plan', 'nodes', 'target'} or not 1 <= len(graph['nodes']) <= 64:
            unsupported('Invalid reconstruction graph.')
        seen = set()
        for node in graph['nodes']:
            required={'node_id','operation','inputs','parameters'}
            if not required<=set(node)<=required|{'adapter_id','outputs'} or node['operation'] not in OPS or node['node_id'] in seen:
                unsupported('Unsupported reconstruction node.')
            allowed={ffmpeg.ADAPTER_ID,filmmaking.ADAPTER_ID} if node['operation']=='scene.render@1' else {ffmpeg.ADAPTER_ID}
            if node.get('adapter_id',ffmpeg.ADAPTER_ID) not in allowed:
                unsupported('Unsupported reconstruction adapter.')
            for port,value in node['inputs'].items():
                for binding in value if isinstance(value, list) else [value]:
                    if port=='media' and node['operation'] in ('edit.assemble@1','delivery.encode@1') and binding.get('kind')!='node_output':
                        unsupported('Replayed picture must come from a rebuilt node, not archived media.')
                    if binding.get('kind') == 'node_output' and binding.get('node_id') not in seen:
                        unsupported('Reconstruction dependencies must be acyclic and ordered.')
                    if binding.get('kind') not in ('node_output', 'artifact', 'document'):
                        unsupported('Unsupported reconstruction input.')
                    if binding.get('kind') == 'artifact' and binding['artifact'] not in recipe['sources']:
                        unsupported('Only declared editable source roots may be external render inputs.')
            seen.add(node['node_id'])
        if graph['target'] not in seen or graph['nodes'][-1]['operation'] != 'delivery.encode@1':
            unsupported('Reconstruction must end at its requested encoded master.')
    return recipe


def freeze_recipe(runtime, pid, masters) -> tuple[dict, list]:
    """Freeze transitive producer ancestors, including reused scene/audio jobs."""
    graphs,sources,documents,dependencies=[],[],[],[]
    def source(pin):
        if pin not in sources:
            record=runtime.artifacts.resolve(pid,pin)
            if record['producer']['job_id'] is None:
                sources.append(copy.deepcopy(pin));dependencies.append(copy.deepcopy(pin))
    def document(pin):
        if any(d['document']==pin for d in documents):return
        record=runtime.document(pid,pin)
        artifact={k:record['artifact'][k] for k in ('artifact_id','sha256')}
        documents.append(dict(document=copy.deepcopy(pin),artifact=artifact));dependencies.append(artifact)
        scan(record['document']['value'])
    def scan(value):
        if isinstance(value,dict):
            if set(value)=={'kind','id','revision','sha256'}:document(value)
            elif set(value)=={'artifact_id','sha256'}:source(value)
            else:
                for v in value.values():scan(v)
        elif isinstance(value,list):
            for v in value:scan(v)
    for master in masters:
        record=runtime.artifacts.resolve(pid,master)
        jid=record['producer']['job_id']
        if not jid:unsupported('Master has no retained completed producer plan.')
        bundle=runtime.jobs().read(pid,jid)
        if bundle['job']['state']!='succeeded':unsupported('Producer job is not successful.')
        plan=bundle['plan_record'];by_id={n['node_id']:n for n in plan['nodes']}
        matches=[(n,p) for n,ports in bundle['output_ports'].items() for p,pin in ports.items() if pin==master]
        if len(matches)!=1 or matches[0][1]!='candidate':unsupported('Master must be an exact encoded candidate.')
        target=matches[0][0];nodes=[];visiting=set()
        def visit(nid,graph=by_id,owner=bundle):
            if any(n['node_id']==nid for n in nodes):return
            if nid in visiting:unsupported('Cyclic producer graph.')
            visiting.add(nid);node=graph[nid]
            adapter=node['binding']['adapter_id']
            allowed={ffmpeg.ADAPTER_ID,filmmaking.ADAPTER_ID} if node['operation']=='scene.render@1' else {ffmpeg.ADAPTER_ID}
            if node['operation'] not in OPS or adapter not in allowed:
                unsupported('Producer renderer/operation is not reconstructable.')
            frozen=copy.deepcopy(node['inputs'])
            for value in frozen.values():
                for binding in value if isinstance(value,list) else [value]:
                    if binding['kind']=='node_output':visit(binding['node_id'],graph,owner)
                    elif binding['kind']=='artifact':
                        pin=binding['artifact'];record=runtime.artifacts.resolve(pid,pin)
                        if record['producer']['job_id'] is None:source(pin)
                        else:
                            upstream=runtime.jobs().read(pid,record['producer']['job_id'])
                            if upstream['job']['state']!='succeeded':unsupported('Upstream producer is not successful.')
                            outputs=[(n,p) for n,ports in upstream['output_ports'].items() for p,v in ports.items() if v==pin]
                            if len(outputs)!=1:unsupported('Upstream output identity is ambiguous.')
                            parent,port=outputs[0]
                            visit(parent,{n['node_id']:n for n in upstream['plan_record']['nodes']},upstream)
                            binding.clear();binding.update(kind='node_output',node_id=parent,port=port)
                    elif binding['kind']=='document':document(binding['document'])
                    else:unsupported('Unknown producer input binding.')
            scan(node['parameters'])
            nodes.append(dict(node_id=nid,operation=node['operation'],inputs=frozen,
                parameters=copy.deepcopy(node['parameters']),adapter_id=adapter,
                outputs=copy.deepcopy(owner['output_ports'][nid])))
            visiting.remove(nid)
        visit(target)
        variant_doc=runtime.document(pid,by_id[target]['parameters']['variant_document'])['document']['value']
        variant=next(v for v in variant_doc if v['variant_id']==by_id[target]['parameters']['variant'])
        if variant['captions']!='none':unsupported('Caption reconstruction is not yet supported.')
        graphs.append(dict(master=copy.deepcopy(master),plan={k:plan[k] for k in ('plan_id','plan_revision','plan_sha256')},nodes=nodes,target=target))
    include_film=any(n['adapter_id']==filmmaking.ADAPTER_ID for g in graphs for n in g['nodes'])
    recipe=dict(schema=SCHEMA,renderer=identity(include_film),graphs=graphs,sources=sources,
        documents=documents,equivalence='decoded_video_and_format')
    validate_recipe(recipe)
    return recipe,dependencies


class NativeReconstructor:
    def __init__(self, worker, request, attempt, output_root, registry):
        self.registry = registry
        self.worker, self.request, self.attempt = worker, request, attempt
        self.output_root = Path(output_root)
        self.rebuilt_members = []

    def runtime_check(self, requirements):
        # The executable runner is the same owned JobStore capability as rendering.
        if not callable(getattr(self.worker, 'run', None)) or not self.attempt.get('authority_evidence_ref'):
            raise ContractError('PERMISSION_DENIED', 'Owned authorized reconstruction context required.')
        if not requirements or len(requirements)>2:
            return False
        expected = dict(requirements[0])
        version = self.worker.run(['ffmpeg', '-version'], timeout=10, check=True).stdout.decode().splitlines()[0]
        if expected != runtime_identity(expected['dependencies'], version, expected['entry_member']):return False
        if len(requirements)==2:
            found=filmmaking.discover()
            if not found['available']:return False
            versions=filmmaking.runtime_versions(found,lambda argv:self.worker.run(argv,timeout=10,check=True))
            return requirements[1]==film_runtime_identity(requirements[1]['dependencies'],versions,requirements[1]['entry_member'])
        return True

    def reconstruct(self, context):
        selection = json.loads(context.resolve(context.manifest['reproduction']['assembly_plan']).read_bytes())
        recipe = validate_recipe(selection.get('reconstruction'))
        expected = [m['artifact'] for m in context.manifest['members'] if m['role'] == 'master']
        if len(expected) != len(recipe['graphs']) or {digest(p) for p in expected} != {digest(g['master']) for g in recipe['graphs']}:
            raise ContractError('HASH_MISMATCH', 'Recipe master set differs from archive.')
        if context.manifest['reproduction']['expected_equivalence'] != 'content_and_format':
            unsupported('Recipe requires explicit decoded content and format equivalence.')
        result = {}; trusted_paths = {}; rebuilt_refs = {}
        def rebind(value):
            if isinstance(value,dict):
                if set(value)=={'artifact_id','sha256'}:
                    return copy.deepcopy(rebuilt_refs.get(digest(value),value))
                return {key:rebind(child) for key,child in value.items()}
            if isinstance(value,list):return [rebind(child) for child in value]
            return value
        metadata={digest(item['artifact']):item for item in context.closure['artifacts']}
        declared_roots={digest(pin) for pin in context.closure['source_roots']}
        for pin in recipe['sources']:
            path=context.resolve(pin); key=digest(pin)
            media_type=metadata[key]['media_type']
            if key not in declared_roots:
                # Auxiliary leaves are image/font assets, PCM audio or JSON cue
                # data. Packaged rendered video is never a replay source.
                if not (media_type.startswith(('image/','font/')) or media_type in
                        ('audio/wav','audio/x-wav','application/json','application/font-woff','application/vnd.ms-opentype')):
                    unsupported('Unsupported nongenerated reconstruction source type.')
                if media_type=='application/json':json.loads(path.read_bytes())
            trusted_paths[key] = path
        # SourceBundle is JSON plus explicit verified sibling members, not ZIP.
        for graph in recipe['graphs']:
            for node in graph['nodes']:
                if node['operation']=='scene.render@1':
                    source=node['inputs']['source']
                    if source['kind']!='artifact':unsupported('Render requires an editable source root.')
                    if digest(source['artifact']) not in declared_roots:
                        unsupported('Editable render root must be declared in the package source roots.')
                    path=context.resolve(source['artifact'])
                    if node.get('adapter_id')==filmmaking.ADAPTER_ID:filmmaking.source_entry(path)
                    else:ffmpeg._bundle_entry(path)
        for doc in recipe['documents']:
            path = context.resolve(doc['artifact']); value = json.loads(path.read_bytes())
            if digest(value) != doc['document']['sha256'] or any(value[k] != doc['document'][k] for k in ('kind','id','revision')):
                raise ContractError('HASH_MISMATCH', 'Frozen document differs from recipe pin.')
            trusted_paths[digest(doc['document'])] = path
            trusted_paths[digest(doc['artifact'])] = path
        for gi, graph in enumerate(recipe['graphs']):
            ports = {}
            for ni, node in enumerate(graph['nodes']):
                def bind(value):
                    if isinstance(value, list): return [bind(v) for v in value]
                    if value['kind'] == 'node_output': return ports[value['node_id']][value['port']]
                    if value['kind'] == 'artifact': return value['artifact']
                    doc = next(d for d in recipe['documents'] if d['document'] == value['document'])
                    if doc['document']['kind'] == 'timeline':
                        # Baseline accepts raw Timeline or a DocumentRecord. Verify
                        # the wrapper above, then materialize its exact value only.
                        raw = rebind(json.loads(trusted_paths[digest(doc['artifact'])].read_bytes())['value'])
                        path = context.output_root / f'timeline-{gi}-{ni}.json'
                        path.write_bytes(canonical(raw))
                        pin = dict(artifact_id='art_' + str(uuid5(UUID(node['node_id'][4:]), 'timeline')), sha256=digest(raw))
                        trusted_paths[digest(pin)] = path
                        return pin
                    return doc['artifact']
                def resolve(pin):
                    path = trusted_paths.get(digest(pin))
                    if path is None: unsupported('Replay attempted to read rendered archive media or undeclared dependency.')
                    return path
                # Rebind only the installed allowlisted implementation, never archive code.
                # The exact current native binding is supplied by the job's runtime.
                adapter_id=node.get('adapter_id',ffmpeg.ADAPTER_ID)
                binding = self.binding(node['operation'], node['parameters'],adapter_id)
                request = dict(self.request, operation=node['operation'], node_id=node['node_id'],
                    adapter_id=adapter_id,binding=binding, parameters=node['parameters'], inputs={k:bind(v) for k,v in node['inputs'].items()},
                    required_features=[], binding_parameters=None, effects=ffmpeg.EFFECTS)
                attempt = dict(self.attempt, node_id=node['node_id'], output_dir=f'g{gi}-n{ni}')
                if adapter_id==filmmaking.ADAPTER_ID:
                    from types import SimpleNamespace
                    from .adapters.probe import LocalOutputProbe
                    facade=SimpleNamespace(registry=self.registry,output_probe=LocalOutputProbe(),
                        document=lambda pid,ref:dict(document=json.loads(trusted_paths[digest(ref)].read_bytes())),
                        projects=SimpleNamespace(_filesystem=lambda:SimpleNamespace(root=context.output_root)),
                        artifact_path=lambda pid,pin:resolve(pin))
                    adapter=filmmaking.FilmmakingAdapter(facade,binding)
                    # Replay is a serial node inside the existing owned job,
                    # not a generic GPU request from the archive. Revalidate the
                    # exact installed adapter and frozen node binding, admit its
                    # actual GPU needs for each child, then restore outer policy.
                    with self.worker.resource_scope(adapter,request):
                        response=adapter.execute(request,attempt,self.worker)
                else:
                    response = ffmpeg.execute(request, attempt, project_root=context.output_root,
                        resolve_artifact=resolve, run_process=self.worker.run)
                if response['state'] != 'succeeded':
                    raise ContractError('OUTPUT_INVALID', 'Native reconstruction failed: '+str(response.get('error')))
                ports[node['node_id']] = {}
                for out in response['outputs']:
                    path = context.output_root / attempt['output_dir'] / out['relative_path']
                    # Rebuilt containers can have new bytes despite equal decoded
                    # content. Never label them with an original artifact hash.
                    pin = dict(artifact_id='art_' + str(uuid5(UUID(node['node_id'][4:]), 'rebuilt:'+out['port'])),sha256=ffmpeg.digest(path))
                    original=node.get('outputs',{}).get(out['port'])
                    if original is not None:rebuilt_refs[digest(original)]=pin
                    trusted_paths[digest(pin)] = path
                    ports[node['node_id']][out['port']] = pin
            pin = ports[graph['target']]['candidate']
            result[graph['master']['artifact_id']] = trusted_paths[digest(pin)]
        return result

    def repack(self, context, rebuilt, report):
        """Retain actual inspected rebuilt bytes in a declared data-only member.

        Fixed public package ports remain archive/report. This final safe ZIP
        build runs no generation; its independently verified manifest declares
        the freshly generated nested archive and preserves source closure.
        """
        from .packaging import build_package
        from .project import _now
        manifest = copy.deepcopy(context.manifest)
        old = next((m for m in manifest['members'] if m['path'] == 'reconstruction/rebuilt.zip'), None)
        if old:
            manifest['members'].remove(old)
        records, paths = {}, {}
        now = _now()
        for item in context.closure['artifacts']:
            pin = item['artifact']
            if old and pin == old['artifact']: continue
            aid = pin['artifact_id']
            records[aid] = dict(schema='motion/v1/artifact', artifact_id=aid,
                project_id=context.closure['project_id'], kind='archive' if item['media_type'] == 'application/zip' else 'json',
                sha256=pin['sha256'], size_bytes=item['size_bytes'], media_type=item['media_type'],
                inputs=item['inputs'], provenance=item['provenance'], created_at=now,
                producer=dict(job_id=None,node_id=None,attempt_id=None,adapter_id=None),
                probe_receipt_id=None, storage=dict(mode='managed',relative_path='package-data'))
            paths[aid] = context.resolve(pin)
        payload = self.output_root / 'reconstruction.zip'
        sha = ffmpeg.digest(payload)
        aid = 'art_' + str(uuid5(UUID(context.closure['project_id'][4:]), 'rebuilt:' + sha))
        pin = dict(artifact_id=aid, sha256=sha)
        template = copy.deepcopy(next(iter(records.values())))
        template.update(artifact_id=aid, sha256=sha, size_bytes=payload.stat().st_size,
            media_type='application/zip', kind='archive', inputs=[copy.deepcopy(manifest['reproduction']['assembly_plan'])])
        from .artifacts import inherited_rights
        template['provenance'].update(origin='derived', acquired_at=now, source_locator=None,
            provider=None, model=None, model_version=None, seed=None, deterministic='unknown',
            rights=inherited_rights([records[p['artifact_id']] for p in template['inputs']]),
            notes='Owned local reconstruction output; exact decoded comparison recorded separately. Inherited rights metadata is not a license grant.')
        records[aid] = template; paths[aid] = payload
        manifest['members'].append(dict(path='reconstruction/rebuilt.zip', artifact=pin, role='asset'))
        final = build_package(manifest, self.output_root / 'reconstructed-package.zip',
            records=records, resolver=lambda p:paths[p['artifact_id']], source_roots=context.closure['source_roots'])
        report['input_archive_sha256'] = report['archive_sha256']
        report['input_manifest_sha256'] = report['manifest_sha256']
        report['archive_sha256'] = final['archive_sha256']
        report['manifest_sha256'] = final['manifest_sha256']
        report['reconstruction_archive'] = pin

    def binding(self, operation, parameters, adapter_id=ffmpeg.ADAPTER_ID):
        return self.registry.binding(adapter_id, operation, parameters, None)

    def inspect(self, context, rebuilt):
        import zipfile
        token = ffmpeg._PROCESS_RUNNER.set(self.worker.run)
        try:
            with zipfile.ZipFile(self.output_root / 'reconstruction.zip', 'x', compression=zipfile.ZIP_STORED) as archive:
                for aid, path in rebuilt.items():
                    master = next(m['artifact'] for m in context.manifest['members'] if m['artifact']['artifact_id'] == aid)
                    def signature(p):
                        facts = ffmpeg.probe(p)
                        video=[s for s in facts['streams'] if s['codec_type']=='video']
                        audio=[s for s in facts['streams'] if s['codec_type']=='audio']
                        if len(video)!=1 or len(audio)>1 or len(video)+len(audio)!=len(facts['streams']):
                            unsupported('Expected one video and optional soundtrack.')
                        s = video[0]
                        fields = ('codec_name','width','height','pix_fmt','r_frame_rate','color_range','color_space','color_transfer','color_primaries')
                        raw = ffmpeg._run(['ffmpeg','-v','error','-xerror','-i',str(p),'-map','0:v:0','-an','-f','framemd5','-'],30).stdout
                        value=dict(format={k:s.get(k) for k in fields}, decoded_sha256='sha256:'+hashlib.sha256(raw).hexdigest())
                        if audio:
                            pcm=ffmpeg._run(['ffmpeg','-v','error','-xerror','-i',str(p),'-map','0:a:0','-vn','-f','s16le','-'],30).stdout
                            value['audio']={k:audio[0].get(k) for k in ('codec_name','sample_rate','channels')}
                            value['audio']['decoded_sha256']='sha256:'+hashlib.sha256(pcm).hexdigest()
                        return value
                    actual, expected = signature(path), signature(context.resolve(master))
                    if actual != expected:
                        raise ContractError('HASH_MISMATCH', 'Rebuilt video content/format differs from master.')
                    name = aid + '.mp4'; archive.write(path, name)
                    self.rebuilt_members.append(dict(path=name, master=master, sha256=ffmpeg.digest(path), signature=actual))
            return 'pass'
        finally:
            ffmpeg._PROCESS_RUNNER.reset(token)


def runtime_identity(sources, engine_version, entry_member='graphics.json'):
    return dict(adapter_id=ffmpeg.ADAPTER_ID, implementation_version=ffmpeg.VERSION,
        engine='ffmpeg', engine_version=engine_version, dependencies=copy.deepcopy(sources), entry_member=entry_member)


def film_runtime_identity(sources, versions, entry_member='index.html'):
    return dict(adapter_id=filmmaking.ADAPTER_ID,implementation_version=filmmaking.VERSION,
        engine='Chromium/Node',engine_version=json.dumps(versions,sort_keys=True),
        dependencies=copy.deepcopy(sources),entry_member=entry_member)
