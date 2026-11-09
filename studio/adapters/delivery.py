"""Owned local packaging and exact-candidate deterministic checks.

Reconstruction uses installed allowlisted runtimes. Authored HTML/JS runs only in
the explicitly authorized local filmmaking route; graphics JSON remains data only.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid5
from ..contracts import ContractError, canonical, digest
from . import ffmpeg

ADAPTER_ID = 'local.delivery'
OPERATIONS = ('review.check@1', 'delivery.package@1', 'caption.export@1')


def registration():
    from ..capabilities import PARAMS, expanded
    base = ffmpeg.registration()
    declaration = ffmpeg.declaration()
    declaration.update(adapter_id=ADAPTER_ID, label='Local exact-candidate checks and safe ZIP closure',
        dependencies=ffmpeg.declaration()['dependencies'], implementation_version='1.1.0')
    # Conservative across all operations: package reconstruction invokes owned children.
    declaration['effects'].update(generates=True, launches_process=True)
    prototype = declaration['operations'][0]
    declaration['operations'] = []
    schemas, outputs = {}, {}
    result = next(value for key, value in base['schemas'].items() if key.endswith('-result'))
    for op in OPERATIONS:
        item = copy.deepcopy(prototype)
        item.update(operation=op, request_schema=f'motion/v1/local-delivery/{op}-request',
            result_schema=f'motion/v1/local-delivery/{op}-result', features=['closure.hash_verified'])
        item['constraints'].update(media_types=['application/json', 'application/zip', 'video/mp4',
            'application/vnd.motion.source-bundle+json', 'text/plain', 'text/vtt', 'application/x-subrip'])
        schemas[item['request_schema']] = expanded(PARAMS[op])
        schemas[item['result_schema']] = result
        declaration['operations'].append(item)
        outputs[op] = [dict(port='report', kind='report', media_type='application/json')]
        if op == 'caption.export@1':
            outputs[op] = [dict(port='sidecar', kind='caption', media_type='text/plain'), dict(port='receipt', kind='report', media_type='application/json')]
        if op == 'delivery.package@1':
            # A package cold-replays multiple render/mix/encode nodes, not one
            # 120-second post-production operation. Keep one bounded overall job.
            item['default_timeout_seconds']=900
            outputs[op].insert(0, dict(port='archive', kind='archive', media_type='application/zip'))

    return dict(declaration=declaration, schemas=schemas, outputs=outputs,
        implementation_sha256='sha256:' + hashlib.sha256(Path(__file__).read_bytes() +
            Path(__file__).with_name('ffmpeg.py').read_bytes() +
            Path(__file__).with_name('limits.py').read_bytes() +
            Path(__file__).parents[1].joinpath('reconstruction.py').read_bytes() +
            Path(__file__).parents[1].joinpath('packaging.py').read_bytes()).hexdigest())


class DeliveryAdapter:
    owned_local = True
    # All effects are synchronous local files/owned children; this adapter never
    # starts provider work. Allows stopped, explicitly cancelled attempts to be
    # reconciled after an exception without weakening remote uncertainty rules.
    local_effects_only = True
    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, binding

    def validate_request(self, request):
        expected = self.runtime.registry.binding(ADAPTER_ID, request['operation'], request['parameters'], request.get('binding_parameters'))
        if expected != self.binding or request['binding'] != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen delivery binding changed.')
        if request['operation'] == 'delivery.package@1' and request['parameters']['format'] != 'zip':
            raise ContractError('UNSUPPORTED_FEATURE', 'Only safe stored ZIP packages are supported.')
        return dict(valid=True, effects=registration()['declaration']['effects'])

    def execute(self, request, attempt, context=None):
        try:
            return self._execute(request,attempt,context)
        except Exception as exc:
            # This adapter cannot leave a remote request running. JobStore still
            # owns/cleans any local child; failed local validation is not an
            # uncertain provider submission and must retain its concrete cause.
            error=dict(code=exc.code if isinstance(exc,ContractError) else 'OUTPUT_INVALID',
                message=str(exc) if isinstance(exc,ContractError) else 'Owned local delivery failed ('+type(exc).__name__+').',
                details={},retry='after_input_change',effect='partial')
            return dict(state='failed',submission_state='confirmed',external_handle=None,remote_state='none',
                progress=None,outputs=[],warnings=[],error=error,observed_cost=None,logs_ref=None,handoff=None)

    def _execute(self, request, attempt, context=None):
        self.validate_request(request)
        if context is None or not callable(getattr(context, 'run', None)) or not attempt.get('authority_evidence_ref'):
            raise ContractError('PERMISSION_DENIED', 'Owned JobStore worker context is required.')
        from ..project import ManagedFS
        fs = self.runtime.projects._filesystem(write=True)
        root = fs.root / attempt['output_dir']
        with fs.directory(attempt['output_dir'], create=True):
            pass
        pid = request['project_id']; outputs = []
        def save(port, name, payload, media_type):
            path = root / name
            with path.open('xb') as stream:
                stream.write(payload)
            if media_type in ('application/zip', 'text/plain'):
                self.runtime.output_probe.validate(payload, dict(kind='archive' if media_type == 'application/zip' else 'caption', media_type=media_type), run_process=context.run)
            outputs.append(dict(port=port, relative_path=name, media_type=media_type,
                claimed_sha256='sha256:' + hashlib.sha256(payload).hexdigest()))
        if request['operation'] == 'caption.export@1':
            from .caption_render import export_sidecar
            from ..native_delivery import DeliveryExecutor
            from ..delivery import NativeDeliveryService
            helper = NativeDeliveryService(self.runtime).executor
            caption = helper.read_json(pid, request['inputs']['caption'])
            if caption.get('kind') == 'caption':
                caption = caption['value']
            placement = helper.read_json(pid, request['inputs']['placement']) if 'placement' in request['inputs'] else None
            decisions = [helper.read_json(pid, pin) for pin in caption['timing_decisions']]
            payload, receipt = export_sidecar(caption, placement=placement, decisions=decisions, **request['parameters'])
            save('sidecar', 'captions.' + request['parameters']['format'], payload, 'text/plain')
            save('receipt', 'caption-receipt.json', canonical(receipt), 'application/json')
        elif request['operation'] == 'review.check@1':
            from ..delivery import NativeDeliveryService
            delivery = NativeDeliveryService(self.runtime)
            pointer = self.runtime.projects._pointer(fs, pid)
            pin = request['inputs']['candidate']; candidate = delivery.candidate(fs, pointer, pin)
            facts = delivery.context(fs, pointer, candidate)
            gate = request['parameters']['gate']
            _, payload = delivery._expected_check(candidate, gate)
            save('report', 'review.json', canonical(payload), 'application/json')
        else:
            from ..packaging import build_package, validate_package
            from ..reconstruction import NativeReconstructor
            inputs = request['inputs']
            recon = NativeReconstructor(context, request, attempt, root, self.runtime.registry)
            options: dict = dict(authorized=True, runtime_check=recon.runtime_check,
                reconstruct=recon.reconstruct, inspect=recon.inspect,
                on_verified=recon.repack) if request['parameters']['reconstruct'] else {}
            if request['parameters']['mode'] == 'build':
                manifest, records, paths = self.package_manifest(pid, inputs, context=context)
                path = root / 'build.zip'
                build = build_package(manifest, path, records=records,
                    resolver=lambda pin: paths[pin['artifact_id']], source_roots=inputs['sources'])
                report = validate_package(path, expected_archive_sha256=ffmpeg.digest(path), scratch_root=root, **options)
                report['build'] = build
                payload = path.read_bytes()
            else:
                path = self.runtime.artifact_path(pid, inputs['archive'])
                selected = json.loads(Path(self.runtime.artifact_path(pid, inputs['manifest'])).read_text())
                if not selected.get('manifest_sha256'):
                    raise ContractError('HASH_MISMATCH', 'Selected package report has no pinned manifest.')
                report = validate_package(path, expected_archive_sha256=inputs['archive']['sha256'], scratch_root=root,
                    expected_manifest_sha256=selected['manifest_sha256'], **options)
                payload = Path(path).read_bytes()
                # The referenced manifest is rehashed before generation, not merely retained.
                if selected.get('manifest_sha256') != report.get('input_manifest_sha256', report['manifest_sha256']):
                    raise ContractError('HASH_MISMATCH', 'Package manifest differs from the retained build report.')
            report.update(schema='motion/v1/package-job-report', source_inputs=inputs,
                project_id=pid, mode=request['parameters']['mode'],
                equivalence='decoded_video_and_format' if request['parameters']['reconstruct'] else None,
                rebuilt_members=recon.rebuilt_members,
                reconstruction_member='reconstruction/rebuilt.zip' if report.get('reconstruction') == 'pass' else None)
            if report.get('reconstruction') == 'pass':
                payload = (root / 'reconstructed-package.zip').read_bytes()
            save('report', 'package-report.json', canonical(report), 'application/json')
            save('archive', 'package.zip', payload, 'application/zip')
        return dict(state='succeeded', submission_state='confirmed', external_handle=None, remote_state='none',
            progress=None, outputs=outputs, warnings=[], error=None, observed_cost=None, logs_ref=None, handoff=None)

    def package_manifest(self, pid, inputs, context=None):
        from ..assets import _read_bundle, _local_file, _bundle_members
        from ..project import _now
        records, paths, locations, entry_members = {}, {}, {}, {}
        def walk(pin):
            if pin['artifact_id'] in records:
                return
            record = self.runtime.artifacts.resolve(pid, pin)
            records[pin['artifact_id']] = record
            paths[pin['artifact_id']] = self.runtime.artifact_path(pid, pin)
            for dependency in record['inputs']:
                walk(dependency)
        for pin in inputs['masters'] + inputs['sources'] + inputs['sidecars'] + [inputs['provenance']]:
            walk(pin)
        # Source-bundle members are exact explicit siblings, never discovered code.
        # They receive deterministic archive-local artifact identities and inherit
        # unresolved rights (not an authorship-based grant).
        for source in inputs['sources']:
            path = Path(paths[source['artifact_id']])
            with _local_file(str(path)) as stream:
                bundle = _read_bundle(stream, path.name)
            entry_members[source['artifact_id']]=bundle['entry_member']
            member_root = Path(str(path) + '.members') if Path(str(path) + '.members').is_dir() else path.parent
            with _bundle_members(bundle, member_root):
                pass
            locations[source['artifact_id']] = f"source/{source['artifact_id']}/manifest.json"
            for member in bundle['members']:
                member_path = member_root / member['relative_path']
                # Managed source siblings live under <artifact>.members.
                if not member_path.is_file():
                    member_path = Path(str(path) + '.members') / member['relative_path']
                sha = ffmpeg.digest(member_path)
                aid = 'art_' + str(uuid5(UUID(source['artifact_id'][4:]), member['relative_path']))
                record = copy.deepcopy(records[source['artifact_id']])
                record.update(artifact_id=aid, sha256=sha, size_bytes=member_path.stat().st_size,
                    inputs=[], media_type=member['media_type'])
                records[aid] = record; paths[aid] = member_path
                locations[aid] = f"source/{source['artifact_id']}/{member['relative_path']}"
        members = []
        for aid, record in records.items():
            pin = {k:record[k] for k in ('artifact_id','sha256')}
            role = 'master' if pin in inputs['masters'] else 'sidecar' if pin in inputs['sidecars'] else 'source' if pin in inputs['sources'] else 'provenance' if pin == inputs['provenance'] else 'asset'
            if pin == inputs['provenance']:
                role = 'instructions'
            members.append(dict(path=locations.get(aid, f'{role}/{aid}'), artifact=pin, role=role))
        selection = json.loads(Path(paths[inputs['provenance']['artifact_id']]).read_bytes())
        recipe = selection.get('reconstruction')
        requirements = []
        if recipe is not None:
            from ..reconstruction import validate_recipe, runtime_identity, film_runtime_identity
            validate_recipe(recipe)
            if context is None:
                raise ContractError('PERMISSION_DENIED', 'Owned context required to identify reconstruction runtime.')
            version = context.run(['ffmpeg', '-version'], timeout=10, check=True).stdout.decode().splitlines()[0]
            entry=entry_members[inputs['sources'][0]['artifact_id']]
            requirements = [runtime_identity(recipe['sources'], version, entry)]
            from . import filmmaking
            if any(n.get('adapter_id')==filmmaking.ADAPTER_ID for g in recipe['graphs'] for n in g['nodes']):
                found=filmmaking.discover()
                if not found['available']:raise ContractError('DEPENDENCY_UNAVAILABLE','Filmmaking reconstruction dependencies missing.')
                versions=filmmaking.runtime_versions(found,lambda argv:context.run(argv,timeout=10,check=True))
                requirements.append(film_runtime_identity(recipe['sources'],versions,entry))
        manifest = dict(schema='motion/v1/package-manifest', members=members, runtime_requirements=requirements,
            reproduction=dict(assembly_plan=inputs['provenance'], generation_boundary=(
                'Owned allowlisted local graphics/HTML replay, audio mix, assembly and encode. Explicit source manifests and frozen documents supply all inputs. HTML/JS is trusted authored executable source, not an OS sandbox; source closure is served locally with browser networking denied. No archive argv, installs or provider calls. Packaged rendered media are comparison references only.'
                if recipe else 'No archive code is executed. No supported frozen reconstruction recipe retained.'),
                expected_equivalence='content_and_format' if recipe else 'bytes'), exclusions=[])
        return manifest, records, paths
