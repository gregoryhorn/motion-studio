"""Public delivery convenience compiler over the existing immutable plan/job store.

No authority is accepted from JSON: every submission goes through NativeRuntime.run.
Read/collect paths only reconcile committed outputs; they never spawn workers.
"""
from __future__ import annotations
import copy
import json
from uuid import UUID, uuid5
from .contracts import ContractError, digest


def child_id(request_id, key):
    return str(uuid5(UUID(request_id), key))


def artifact(pin):
    return dict(kind='artifact', artifact=pin)


class DeliveryExecutor:
    def __init__(self, delivery):
        self.delivery = delivery
        self.runtime = delivery.runtime

    def dispatch(self, tool, args):
        fs = self.runtime.projects._filesystem()
        pointer = self.runtime.projects._pointer(fs, args['project_id'])
        if pointer['revision'] != args['expected_revision']:
            raise ContractError('REVISION_CONFLICT', 'Delivery requires current content revision.')
        self.runtime.registry.inspect(args['adapter_id'])
        if args['action'] == 'encode':
            tasks = self.encode_tasks(args, fs, pointer)
        elif args['action'] in ('validate', 'check'):
            pins = args.get('candidates', [args.get('candidate')])
            tasks = []
            for index, pin in enumerate(pins):
                self.collect_candidate(args['project_id'], pin)
                candidate = self.delivery.candidate(fs, pointer, pin)
                context = self.delivery.context(fs, pointer, candidate)
                for gate in args.get('gates', ['technical', 'audio', 'delivery_profile']):
                    if gate not in ('technical', 'audio', 'delivery_profile'):
                        raise ContractError('UNSUPPORTED_FEATURE', 'Deterministic checks do not supply art/creative observations.')
                    tasks.append(dict(target_key=f'check_{index}_{gate}', operation='review.check@1',
                        adapter_id=args['adapter_id'], inputs=dict(candidate=artifact(pin), evidence=[]),
                        parameters=dict(gate=gate, policy=context.policy_pin, checks=[])))
        else:
            tasks = self.package_tasks(args, fs, pointer)
        return self.submit_tasks(args, tasks)

    def submit_tasks(self, args, tasks):
        compiled = self.runtime.plan(dict(action='compile', project_id=args['project_id'],
            request_id=child_id(args['request_id'], 'compile'), expected_revision=args['expected_revision'],
            requests=tasks, targets=[t['target_key'] for t in tasks], reuse_outputs=False))
        if not compiled.get('ok'):
            error = compiled['error']
            raise ContractError(error['code'], error['message'], effect=error['effect'])
        plan = compiled['data']['plan']['plan']
        submit = dict(action='submit', project_id=args['project_id'], request_id=child_id(args['request_id'], 'submit'),
            expected_revision=args['expected_revision'], plan=plan)
        if 'authority_ref' in args:
            submit['authority_ref'] = args['authority_ref']
        result = self.runtime.run(submit, session_id=self.delivery.session_id, task_id=self.delivery.task_id)
        if result.get('ok'):
            result['data']['plan'] = plan
        else:
            result['error']['effect'] = 'committed'
        if not result.get('ok'):
            error = result['error']
            raise ContractError(error['code'], error['message'], effect=error['effect'])
        return result['data']

    def caption_export(self, args):
        from .captions import validate_caption_request, check
        validate_caption_request(args)
        fs = self.runtime.projects._filesystem()
        pointer = self.runtime.projects._pointer(fs, args['project_id'])
        if pointer['revision'] != args['expected_revision']:
            raise ContractError('REVISION_CONFLICT', 'Caption export requires current project revision.')
        docs = self.runtime.projects._load(fs, pointer)[1]
        if 'timeline_item_ids' in args:
            args = self.caption_placement(args, docs)
        inputs = dict(caption=dict(kind='document', document=args['caption']))
        if 'placement' in args:
            placement = self.read_json(args['project_id'], args['placement'])
            check(placement, 'CaptionPlacement')
            docs = self.runtime.projects._load(fs, pointer)[1]
            variant = self.delivery._document_pin(docs['variants','project'])
            if (placement['caption'] != args['caption'] or placement['variant'] != variant
                    or args['variant_id'] not in [v['variant_id'] for v in docs['variants','project']['value']]):
                raise ContractError('HASH_MISMATCH', 'Export placement must bind exact caption and delivery variant.')
            inputs['placement'] = artifact(args['placement'])
        task = dict(target_key='caption_export', operation='caption.export@1', adapter_id=args['adapter_id'], inputs=inputs,
            parameters=dict(format=args['format'], rounding=args.get('rounding','nearest_even'), time_origin=args['time_origin']))
        return self.submit_tasks(args, [task])

    def caption_placement(self, args, docs):
        """Share the exact timeline selection compiler with export and burn."""
        from .captions import compile_placement
        caption = docs.get(('caption', args['caption']['id']))
        if caption is None or self.delivery._document_pin(caption) != args['caption']:
            raise ContractError('HASH_MISMATCH', 'Timeline selection requires the current owned caption pin.')
        variants = docs['variants', 'project']
        variant = next((v for v in variants['value'] if v['variant_id'] == args['variant_id']), None)
        if variant is None:
            raise ContractError('NOT_FOUND', 'Requested delivery variant does not exist.')
        placement = compile_placement(args['caption'], caption['value'],
            self.delivery._document_pin(docs['timeline', 'project']), docs['timeline', 'project']['value'],
            self.delivery._document_pin(variants), variant, docs['settings', 'project']['value']['rate'],
            args['timeline_item_ids'])
        return dict(args, placement=self.runtime.artifacts.publish_json(args['project_id'], placement,
            inputs=[caption['value']['source_audio']]))

    def caption_render_task(self, args, docs, key, frame) -> dict:
        from .captions import check, require_renderable
        from .adapters.caption_render import fingerprint
        if ('placement' in args) == ('timeline_item_ids' in args):
            raise ContractError('INVALID_ARGUMENT', 'Exactly one placement or timeline selection required.')
        for field, kind in (('caption', 'caption'), ('style', 'caption_style')):
            pin = args[field]
            document = docs.get((kind, pin['id']))
            if pin['kind'] != kind or document is None or self.delivery._document_pin(document) != pin:
                raise ContractError('HASH_MISMATCH', 'Caption rendering requires current owned caption/style pins.')
        caption = docs['caption', args['caption']['id']]['value']
        style = docs['caption_style', args['style']['id']]['value']
        check(caption, 'CaptionDocument'); check(style, 'CaptionStyle')
        require_renderable(caption, ())  # Existing renderer's supported timing contract, not a review bypass.
        if not style['fonts']:
            raise ContractError('INVALID_ARGUMENT', 'At least one pinned font face is required.')
        if 'timeline_item_ids' in args:
            args = self.caption_placement(args, docs)
        placement = self.read_json(args['project_id'], args['placement'])
        check(placement, 'CaptionPlacement')
        variant = next((v for v in docs['variants', 'project']['value'] if v['variant_id'] == args['variant_id']), None)
        if variant is None:
            raise ContractError('NOT_FOUND', 'Requested delivery variant does not exist.')
        if (placement['caption'] != args['caption'] or placement['source_audio'] != caption['source_audio']
                or placement['timeline'] != self.delivery._document_pin(docs['timeline', 'project'])
                or placement['variant'] != self.delivery._document_pin(docs['variants', 'project'])
                or placement['project_rate'] != docs['settings', 'project']['value']['rate']
                or placement['output_rate'] != variant['rate']):
            raise ContractError('HASH_MISMATCH', 'Render placement requires exact current caption/audio/timeline/variant/rates.')
        if type(frame) is not int or not 0 <= frame < variant['duration_frames']:
            raise ContractError('INVALID_ARGUMENT', 'Preview frame is outside the target variant.')
        return dict(target_key=key, operation='caption.render@1', adapter_id=args['adapter_id'],
            inputs=dict(caption=dict(kind='document', document=args['caption']),
                placement=artifact(args['placement']), style=dict(kind='document', document=args['style']),
                fonts=[artifact(f['face_artifact']) for f in style['fonts']], background=artifact(args['background'])),
            parameters=dict(variant=args['variant_id'], range=dict(start_frame=0, end_frame=variant['duration_frames']),
                frames=[frame], renderer_fingerprint=fingerprint()))

    def caption_preview(self, args):
        from .captions import validate_caption_request
        validate_caption_request(args)
        fs = self.runtime.projects._filesystem()
        pointer = self.runtime.projects._pointer(fs, args['project_id'])
        if pointer['revision'] != args['expected_revision']:
            raise ContractError('REVISION_CONFLICT', 'Caption preview requires current project revision.')
        docs = self.runtime.projects._load(fs, pointer)[1]
        # Existing owned render route emits one exact frame per node. Do not
        # advertise a new renderer/layout capability or run an engine here.
        tasks = [self.caption_render_task(args, docs, f'caption_preview_{index}', frame)
                 for index, frame in enumerate(args['frames'])]
        return self.submit_tasks(args, tasks)

    def encode_tasks(self, args, fs, pointer):
        docs = self.runtime.projects._load(fs, pointer)[1]
        variants = docs['variants', 'project']
        variant_pin = self.delivery._document_pin(variants)
        tasks = []
        for index, value in enumerate(args['inputs']):
            variant = next((v for v in variants['value'] if v['variant_id'] == value['variant_id']), None)
            if variant is None:
                raise ContractError('NOT_FOUND', 'Requested variant is not in current snapshot.')
            inputs = {key: artifact(value[key]) for key in ('media', 'audio') if key in value}
            placement = None
            caption_fields = {'captions', 'placement', 'timeline_item_ids', 'style'} & set(value)
            if variant['captions'] in ('burn', 'both'):
                if 'captions' not in value or 'style' not in value or 'audio' not in value:
                    raise ContractError('INVALID_ARGUMENT', 'Burn/both requires exact caption, style and audio bindings.')
                render_args = dict(project_id=args['project_id'], caption=value['captions'], style=value['style'],
                    variant_id=value['variant_id'], background=value['media'], adapter_id=args['adapter_id'],
                    **{k:value[k] for k in ('placement', 'timeline_item_ids') if k in value})
                render = self.caption_render_task(render_args, docs, f'caption_burn_{index}', 0)
                placement = self.read_json(args['project_id'], render['inputs']['placement']['artifact'])
                if placement['source_audio'] != value['audio']:
                    raise ContractError('HASH_MISMATCH', 'Burn timing audio differs from encoded audio.')
                tasks.append(render)
                inputs['media'] = dict(kind='node_output', target_key=render['target_key'], port='media')
                inputs['captions'] = dict(kind='document', document=value['captions'])
            elif caption_fields:
                raise ContractError('INVALID_ARGUMENT', 'Caption render bindings require a burn/both variant.')
            sidecars = value.get('sidecars', [])
            if sidecars:
                # Bound descriptor is a normal immutable input, never a hidden quality record.
                for sidecar in sidecars:
                    self.verify_sidecar(args['project_id'], sidecar, variant_pin)
                    if variant['captions'] == 'both' and (sidecar['caption'] != value['captions']
                            or self.read_json(args['project_id'], sidecar['placement']) != placement):
                        raise ContractError('HASH_MISMATCH', 'Both mode requires the same exact burn and sidecar caption placement.')
                descriptor = self.runtime.artifacts.publish_json(args['project_id'],
                    dict(schema='motion/v1/delivery-sidecars', sidecars=sidecars))
                inputs['sidecar_manifest'] = artifact(descriptor)
                inputs['sidecars'] = [artifact(s['artifact']) for s in sidecars]
            tasks.append(dict(target_key=f'encode_{index}', operation='delivery.encode@1',
                adapter_id=args['adapter_id'], inputs=inputs,
                parameters=dict(variant=value['variant_id'], variant_document=variant_pin,
                    encoder_options=dict(schema_id='motion/v1/local-ffmpeg/no-options',
                        schema_sha256=digest({"type":"object","properties":{},"required":[],"additionalProperties":False}), values=copy.deepcopy(args['encoder_options'])))))
        return tasks

    def collect_candidate(self, pid, pin):
        fs = self.runtime.projects._filesystem(); pointer = self.runtime.projects._pointer(fs, pid)
        try:
            return self.delivery.candidate(fs, pointer, pin)
        except ContractError as exc:
            if exc.code != 'NOT_FOUND':
                raise
        record = self.runtime.artifacts.resolve(pid, pin)
        jid = record['producer']['job_id']
        if jid is None:
            raise ContractError('OUTPUT_INVALID', 'Candidate must be a committed encode output.')
        self.delivery.collect_job(pid, jid, request_id=child_id(jid[4:], 'delivery-collect'))
        return self.delivery.candidate(fs, pointer, pin)

    @staticmethod
    def pin_for(bundle, binding):
        if binding['kind'] == 'artifact':
            return binding['artifact']
        if binding['kind'] == 'node_output':
            return bundle['output_ports'][binding['node_id']][binding['port']]
        raise ContractError('OUTPUT_INVALID', 'Expected exact artifact or committed output binding.')

    def read_json(self, pid, pin):
        record = self.runtime.artifacts.resolve(pid, pin)
        with self.runtime.artifacts.open_record(self.runtime.projects._filesystem(), record) as stream:
            return json.load(stream)

    def sidecars(self, pid, bundle, node):
        binding = node['inputs'].get('sidecar_manifest')
        if binding is None:
            return []
        if binding['kind'] != 'artifact':
            raise ContractError('OUTPUT_INVALID', 'Sidecar descriptor must be an immutable artifact.')
        value = self.read_json(pid, binding['artifact'])
        if set(value) != {'schema', 'sidecars'} or value['schema'] != 'motion/v1/delivery-sidecars':
            raise ContractError('OUTPUT_INVALID', 'Invalid sidecar input descriptor.')
        if [s['artifact'] for s in value['sidecars']] != [self.pin_for(bundle, p) for p in node['inputs'].get('sidecars', ())]:
            raise ContractError('HASH_MISMATCH', 'Sidecar descriptor differs from bound caption ports.')
        for sidecar in value['sidecars']:
            self.verify_sidecar(pid, sidecar, node['parameters']['variant_document'])
            caption = self.runtime.document(pid, sidecar['caption'])['document']['value']
            if 'audio' in node['inputs'] and caption['source_audio'] != self.pin_for(bundle, node['inputs']['audio']):
                raise ContractError('HASH_MISMATCH', 'Sidecar timing audio differs from encoded audio.')
        return value['sidecars']

    def verify_sidecar(self, pid, sidecar, variant):
        from .delivery import validate_delivery
        from .adapters.caption_render import export_sidecar
        from .captions import check, caption_pin
        validate_delivery(sidecar, 'SidecarRecord')
        if sidecar['variant'] != variant or sidecar['time_origin'] != 'delivery' or sidecar['placement'] is None:
            raise ContractError('OUTPUT_INVALID', 'Sidecar must bind the exact delivery variant/placement.')
        caption = self.runtime.document(pid, sidecar['caption'])['document']['value']
        placement = self.read_json(pid, sidecar['placement'])
        check(placement, 'CaptionPlacement')
        if (placement['caption'] != sidecar['caption'] or placement['variant'] != variant
                or placement['source_audio'] != caption['source_audio']):
            raise ContractError('HASH_MISMATCH', 'Sidecar placement document bindings differ.')
        receipt = self.read_json(pid, sidecar['timing_receipt'])
        # Export regenerates only text, under canonical approved timing. No decoder,
        # audition or agent judgement is synthesized by this exact-byte comparison.
        text, expected = export_sidecar(caption, format=sidecar['format'], time_origin='delivery',
            placement=placement, decisions=[self.read_json(pid, pin) for pin in caption['timing_decisions']],
            rounding=receipt.get('rounding', 'nearest_even'))
        if receipt != expected:
            raise ContractError('HASH_MISMATCH', 'Sidecar timing receipt differs from canonical export.')
        record = self.runtime.artifacts.resolve(pid, sidecar['artifact'])
        with self.runtime.artifacts.open_record(self.runtime.projects._filesystem(), record) as stream:
            if stream.read() != text:
                raise ContractError('HASH_MISMATCH', 'Sidecar bytes differ from canonical delivery export.')
        if sidecar['language'] != caption['language']:
            raise ContractError('OUTPUT_INVALID', 'Sidecar language differs from canonical caption.')
        return True

    def package_tasks(self, args, fs, pointer):
        from .adapters.delivery import ADAPTER_ID
        if args['adapter_id'] != ADAPTER_ID:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Select the advertised local delivery adapter.')
        if args['action'] == 'package_validate':
            records = [p for p in self.delivery._records(fs, args['project_id'], 'packages') if p['package_id'] == args['package_id']]
            if not records:
                raise ContractError('NOT_FOUND', 'Package does not exist.')
            package = max(records, key=lambda p:p['revision'])
            if package['revision'] != args['expected_package_revision']:
                raise ContractError('REVISION_CONFLICT', 'Package revision changed.')
            inputs = dict(archive=artifact(package['archive']), manifest=artifact(package['manifest']))
            # Public package_validate replays supported retained recipes. Legacy
            # archives without a recipe remain incomplete, never fabricated.
            params = dict(mode='validate_existing', format='zip', reconstruct=True)
        else:
            if args.get('format', 'zip') != 'zip':
                raise ContractError('UNSUPPORTED_FEATURE', 'Only safe stored ZIP packages are supported.')

            if args.get('include_sources', True) is not True:
                raise ContractError('UNSUPPORTED_FEATURE', 'Portable packages require their explicit source closure.')
            masters = [m for m in self.delivery._records(fs, args['project_id'], 'masters') if m['master_id'] in args['master_ids']]
            if len(masters) != len(args['master_ids']):
                raise ContractError('NOT_FOUND', 'Requested master does not exist.')
            sources, sidecars = [], []
            for master in masters:
                candidate = self.delivery.candidate(fs, pointer, master['candidate'])
                if not self.delivery.reviews.gates(fs, pointer, candidate)['promotion_eligible']:
                    raise ContractError('GATE_UNSATISFIED', 'Package requires fresh admitted masters.')
                for record in self.delivery._closure(fs, pointer, master['artifact']).values():
                    pin = {k: record[k] for k in ('artifact_id', 'sha256')}
                    if record['kind'] in ('scene_source', 'assembly_source') and pin not in sources:
                        sources.append(pin)
                sidecars.extend(master['sidecars'])
            if args.get('sidecars', sidecars) != sidecars:
                raise ContractError('OUTPUT_INVALID', 'Package sidecars must match promoted masters exactly.')
            if not sources:
                raise ContractError('PACKAGE_INCOMPLETE', 'Master closure has no editable source root.')
            selection: dict = dict(schema='motion/v1/package-selection', masters=masters, sidecars=sidecars)
            dependencies = []
            from .reconstruction import freeze_recipe
            try:
                recipe, dependencies = freeze_recipe(self.runtime, args['project_id'], [m['artifact'] for m in masters])
                selection['reconstruction'] = recipe
            except ContractError as exc:
                if args.get('reconstruct', False) or exc.code != 'UNSUPPORTED_FEATURE':
                    raise
                selection['reconstruction_limit'] = exc.code
            provenance = self.runtime.artifacts.publish_json(args['project_id'], selection, inputs=dependencies)
            inputs = dict(masters=[artifact(m['artifact']) for m in masters], sources=[artifact(p) for p in sources],
                sidecars=[artifact(s['artifact']) for s in sidecars], provenance=artifact(provenance))
            params = dict(mode='build', format='zip', reconstruct=args.get('reconstruct', False))
        return [dict(target_key='package', operation='delivery.package@1', adapter_id=args['adapter_id'], inputs=inputs, parameters=params)]

    def collect(self, pid, jid):
        """Reconcile real committed job ports, with stable per-node request IDs."""
        from .project import _now
        from .packaging import validate_package_record
        bundle = self.runtime.jobs().read(pid, jid)
        if bundle['job']['state'] != 'succeeded':
            raise ContractError('OUTPUT_UNAVAILABLE', 'Delivery collection requires a succeeded job.')
        fs = self.runtime.projects._filesystem(write=True)
        pointer = self.runtime.projects._pointer(fs, pid)
        result = dict(candidates=[], reviews=[], packages=[])
        nodes = bundle['plan_record']['nodes']
        if any(n['operation'] == 'delivery.encode@1' for n in nodes):
            result['candidates'] = self.delivery.collect_job(pid, jid, request_id=child_id(jid[4:], 'collect'))
        for node in nodes:
            ports = bundle.get('output_ports', {}).get(node['node_id'], {})
            operation = node['operation']
            if operation == 'review.check@1':
                pin = node['inputs']['candidate']['artifact']
                candidate = self.delivery.candidate(fs, pointer, pin)
                context = self.delivery.context(fs, pointer, candidate)
                report_pin = ports['report']; report = self.read_json(pid, report_pin)
                verdict, expected = self.delivery._expected_check(candidate, node['parameters']['gate'])
                if report != expected:
                    raise ContractError('HASH_MISMATCH', 'Check job evidence no longer matches candidate dependencies.')
                request = dict(action='record', project_id=pid, request_id=child_id(jid[4:], node['node_id']),
                    candidate=pin, expected_candidate_manifest_sha256=digest(candidate), gate=report['gate'],
                    result=verdict, method='deterministic', evidence=[report_pin],
                    coverage=dict(frame_ranges=[dict(start_frame=0, end_frame=context.duration_frames)],
                        sample_ranges=[dict(start_sample=0, end_sample=context.sample_count, sample_rate=context.sample_rate)] if context.sample_count else [],
                        scene_ids=[], transition_keys=[], whole_decode=True, playback='not_tested'),
                    findings=[], reason='Owned exact-candidate check job; technical evidence is not aesthetic or listening approval.')
                result['reviews'].append(self.delivery.reviews.record(request,
                    collected=dict(native_retained_probe=True, measurements=[])))
            elif operation == 'delivery.package@1':
                report = self.read_json(pid, ports['report'])
                if report.get('schema') != 'motion/v1/package-job-report' or report.get('project_id') != pid:
                    raise ContractError('OUTPUT_INVALID', 'Invalid package job report.')
                request = dict(request_id=child_id(jid[4:], node['node_id']), job_id=jid, node_id=node['node_id'])
                with fs.lock(self.runtime.projects._base(pid) + '/locks/content.lock'):
                    replay = self.delivery._replay(fs, pid, 'package', request)
                    if replay is not None:
                        result['packages'].append(replay)
                        continue
                    if node['parameters']['mode'] == 'build':
                        selection = self.read_json(pid, node['inputs']['provenance']['artifact'])
                        package_id = 'pkg_' + str(uuid5(UUID(jid[4:]), node['node_id']))
                        revision = 1; masters = [m['master_id'] for m in selection['masters']]
                    else:
                        prior = [p for p in self.delivery._records(fs, pid, 'packages')
                            if p['archive'] == node['inputs']['archive']['artifact'] and p['manifest'] == node['inputs']['manifest']['artifact']]
                        if not prior:
                            raise ContractError('NOT_FOUND', 'Validation job does not bind a retained package.')
                        previous = max(prior, key=lambda p:p['revision'])
                        package_id = previous['package_id']; revision = previous['revision'] + 1; masters = previous['masters']
                    package = dict(schema='motion/v1/package', package_id=package_id, revision=revision,
                        project_id=pid, state=report['state'], masters=masters, archive=ports['archive'],
                        manifest=ports['report'], verification_receipts=[ports['report']],
                        blockers=report['blockers'], created_at=_now())
                    validate_package_record(package)
                    self.delivery._commit(fs, pid, 'package', request, package, dict(packages=[package]))
                    result['packages'].append(package)
        return result
