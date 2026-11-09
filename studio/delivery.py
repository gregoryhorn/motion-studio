"""B11/B16 candidate manifests and atomic exact-byte master promotion.

Only core collected delivery.encode output may become a candidate. Large media
is never read into JSON or encoded here. A master retains the already managed,
rehash-verified immutable blob, as permitted by contract 03 section 9. Core owns
artifact publication and storage retention; no duplicate asset registry/queue.
"""
from __future__ import annotations

import copy
import hashlib

from .contracts import (ADAPTER, BOOL, DIGEST, KEY, STAMP, TEXT, UUID_PATTERN,
    ContractError, arr, canonical, digest, enum, ident, integer, nullable, obj, ref,
    string, validate)
from .project import _id, _now
from .assets import AssetRegistry
from .reviews import (DEFS as REVIEW_DEFS, COMMON, EXECUTION, MUTATION, PAGE,
    GateContext, expanded, schema_document as _schema_document)

DEFS = copy.deepcopy(REVIEW_DEFS)
DEFS['PlanRef'] = obj({'plan_id': ident('pln'), 'plan_revision': {'const': 1}, 'plan_sha256': DIGEST})
DEFS['SidecarRecord'] = obj({'artifact': ref('ArtifactRef'), 'role': {'const': 'subtitles'},
    'variant': ref('DocumentRef'), 'caption': ref('DocumentRef'), 'placement': nullable(ref('ArtifactRef')),
    'language': string(minimum=1), 'format': enum('srt', 'vtt', 'ass'), 'time_origin': enum('source', 'delivery'),
    'timing_receipt': ref('ArtifactRef')})
DEFS['CandidateRecord'] = obj({'schema': {'const': 'motion/v1/candidate'}, 'artifact': ref('ArtifactRef'),
    'project_id': ident('prj'), 'project_revision': integer(1), 'plan': ref('PlanRef'), 'variant_id': KEY,
    'variant': ref('DocumentRef'), 'sidecars': arr(ref('SidecarRecord')), 'dependencies_sha256': DIGEST,
    'gate_policy': ref('DocumentRef'), 'job_id': ident('job'), 'created_at': STAMP})
DEFS['MasterRecord'] = obj({'schema': {'const': 'motion/v1/master'}, 'master_id': ident('mst'),
    'revision': integer(1), 'project_id': ident('prj'), 'variant_id': KEY, 'artifact': ref('ArtifactRef'),
    'candidate': ref('ArtifactRef'), 'candidate_manifest_sha256': DIGEST, 'dependencies_sha256': DIGEST,
    'sidecars': arr(ref('SidecarRecord')), 'gate_summary_receipt': ref('ArtifactRef'),
    'review_ids': arr(ident('rev'), unique=True), 'promoted_at': STAMP, 'project_revision': integer(1)})
DEFS['VariantOutcome'] = obj({'variant_id': KEY, 'state': enum('not_requested', 'planned', 'running', 'candidate',
    'review_needed', 'blocked', 'failed', 'master'), 'candidate': nullable(ref('ArtifactRef')),
    'master_id': nullable(ident('mst')), 'job_id': nullable(ident('job')), 'reason': nullable(TEXT)})
DEFS['CandidateSummary'] = obj({'artifact': ref('ArtifactRef'), 'candidate_manifest_sha256': DIGEST,
    'variant_id': KEY, 'project_revision': integer(1), 'created_at': STAMP, 'gates': ref('GateSummary')})
DEFS['DeliveryFile'] = obj({'artifact': ref('ArtifactRef'), 'role': enum('master', 'sidecar', 'editable_package', 'media_package', 'report'),
    'filename': string(minimum=1, maximum=160), 'size_bytes': integer(), 'media_type': TEXT,
    'delivery_handle': TEXT, 'verification': enum('verified', 'draft', 'incomplete'), 'expires_at': nullable(STAMP)})
ENCODE_INPUT = obj({'variant_id': KEY, 'media': ref('ArtifactRef'), 'audio': ref('ArtifactRef'),
    'captions': ref('DocumentRef'), 'placement': ref('ArtifactRef'), 'timeline_item_ids': arr(KEY, 1, True),
    'style': ref('DocumentRef'), 'sidecars': arr(ref('SidecarRecord'))},
    ['audio', 'captions', 'placement', 'timeline_item_ids', 'style', 'sidecars'])
# RegisteredOptions must be supplied by the actual adapter registry. Empty is the
# only unregistered option set accepted by the standalone schema.
DEFS['RegisteredOptions'] = obj({})
DEFS['DeliveryRequest'] = {'oneOf': [
    obj({'action': {'const': 'encode'}, **EXECUTION, 'variant_ids': arr(KEY, 1, True),
         'inputs': arr(ENCODE_INPUT, 1), 'adapter_id': ADAPTER, 'encoder_options': ref('RegisteredOptions')}, ['authority_ref']),
    obj({'action': {'const': 'validate'}, **EXECUTION, 'candidates': arr(ref('ArtifactRef'), 1, True),
         'adapter_id': ADAPTER}, ['authority_ref']),
    obj({'action': {'const': 'promote'}, **MUTATION, 'expected_revision': integer(1),
         'candidates': arr(ref('ArtifactRef'), 1, True), 'expected_master_revision': integer()}),
    obj({'action': {'const': 'status'}, **COMMON, **PAGE,
         'section': enum('summary', 'candidates', 'masters', 'packages'), 'variant_id': KEY},
        [*PAGE, 'section', 'variant_id']),
    obj({'action': {'const': 'files'}, **COMMON, **PAGE, 'master_ids': arr(ident('mst'), 1, True),
         'package_id': ident('pkg')}, [*PAGE, 'master_ids', 'package_id']),
    obj({'action': {'const': 'package'}, **EXECUTION, 'master_ids': arr(ident('mst'), 1, True),
         'sidecars': arr(ref('SidecarRecord')), 'format': enum('zip', 'tar'), 'include_sources': BOOL,
         'reconstruct': BOOL, 'adapter_id': ADAPTER}, ['authority_ref', 'sidecars', 'format', 'include_sources', 'reconstruct']),
    obj({'action': {'const': 'package_validate'}, **EXECUTION, 'package_id': ident('pkg'),
         'expected_package_revision': integer(1), 'adapter_id': ADAPTER}, ['authority_ref'])]}


def schema_document(name, options_schema=None):
    definitions = {**DEFS, **({'RegisteredOptions': options_schema} if options_schema else {})}
    return _schema_document(name, definitions)


def validate_delivery(value, name, options_schema=None):
    definitions = {**DEFS, **({'RegisteredOptions': options_schema} if options_schema else {})}
    validate(value, expanded(definitions[name], definitions))
    if name == 'CandidateRecord':
        if value['variant']['kind'] != 'variants' or value['gate_policy']['kind'] != 'gate_policy':
            raise ContractError('INVALID_ARGUMENT', 'Candidate must pin variant and gate policy documents.')
        seen = set()
        for sidecar in value['sidecars']:
            if (sidecar['time_origin'] != 'delivery' or sidecar['placement'] is None
                    or sidecar['variant'] != value['variant'] or sidecar['caption']['kind'] != 'caption'):
                raise ContractError('OUTPUT_INVALID', 'Candidate sidecar must pin delivery placement, caption and exact variant.')
            key = (sidecar['language'], sidecar['format'])
            if key in seen:
                raise ContractError('OUTPUT_INVALID', 'Duplicate sidecar language/format.')
            seen.add(key)


def delivery_tool_schema(options_schema=None):
    return {'name': 'motion_deliver', 'description': 'Inspect candidates/masters, promote already checked exact bytes, or request explicit delivery jobs.',
            'parameters': schema_document('DeliveryRequest', options_schema)}


class DeliveryService:
    """Source quality slice. Dependencies are INTERNAL core capabilities.

    context_resolver(fs,pointer,candidate)->GateContext must independently resolve
    the current exact dependency closure, frozen checks and final stream
    facts, caption/profile constraints; it must never mark missing checks passed.
    collect_validator(fs,pointer,candidate)->True verifies genuine successful
    collected delivery.encode output including plan/job/variant/sidecar closure.
    publish_receipt(fs,pointer,payload_bytes,inputs)->ArtifactRef publishes a
    core-issued managed report reachable by this same AssetRegistry under this
    pointer. It must NOT acquire content.lock or increment content revision.
    execute(tool,request) uses B06/B07; no subprocess or private queue here.
    """
    def __init__(self, store, *, registry=None, context_resolver=None, collect_validator=None,
                 publish_receipt=None, execute=None, options_schema=None):
        self.store = store; self.registry = registry or AssetRegistry(store)
        self.context_resolver, self.collect_validator = context_resolver, collect_validator
        self.publish_receipt, self.execute = publish_receipt, execute
        self.options_schema = options_schema
        self.reviews = None

    def _root(self, pid):
        return self.store._base(pid) + '/quality'

    def _commits(self, fs, pid):
        for filename in fs.names(self._root(pid) + '/commits'):
            if not filename.endswith('.json'):
                continue
            envelope = fs.read(self._root(pid) + '/commits/' + filename)
            if set(envelope) != {'sha256', 'value'} or digest(envelope['value']) != envelope['sha256']:
                raise ContractError('HASH_MISMATCH', 'Quality commit integrity differs.')
            commit = envelope['value']
            if (commit.get('schema') != 'motion/v1/quality-commit' or commit.get('project_id') != pid
                    or commit.get('request_id') + '.json' != filename):
                raise ContractError('OUTPUT_INVALID', 'Quality commit identity differs.')
            yield commit

    def _records(self, fs, pid, kind):
        records = [copy.deepcopy(record) for commit in self._commits(fs, pid)
                   for record in commit['records'].get(kind, [])]
        return sorted(records, key=lambda r: (r.get('created_at', r.get('promoted_at', '')), r.get('review_id', r.get('master_id', ''))))

    def _replay(self, fs, pid, operation, args):
        commit = next((c for c in self._commits(fs, pid) if c['request_id'] == args['request_id']), None)
        if commit is None:
            return None
        if commit['operation'] != operation or commit['request_sha256'] != digest(args):
            raise ContractError('IDEMPOTENCY_CONFLICT', 'Quality request already accepted with different content.')
        return copy.deepcopy(commit['result'])

    def _commit(self, fs, pid, operation, args, result, records):
        commit = {'schema': 'motion/v1/quality-commit', 'project_id': pid, 'operation': operation,
                  'request_id': args['request_id'], 'request_sha256': digest(args), 'records': records, 'result': result}
        # One rename publishes the ENTIRE set. Orphaned receipt blobs are not masters.
        path = self._root(pid) + '/commits/' + args['request_id'] + '.json'
        fs.write(path, {'sha256': digest(commit), 'value': commit}, replace=True)

    def context(self, fs, pointer, candidate):
        if self.context_resolver is None:
            raise ContractError('CAPABILITY_MISSING', 'Current dependency/policy/final-facts resolver is not wired.')
        context = self.context_resolver(fs, pointer, copy.deepcopy(candidate))
        if not isinstance(context, GateContext):
            raise ContractError('OUTPUT_INVALID', 'Core resolver must return GateContext.')
        validate(context.policy, expanded(DEFS['GatePolicy'], DEFS))
        for value in (context.policy_pin, context.variant):
            validate(value, expanded(DEFS['DocumentRef'], DEFS))
        validate(context.dependencies_sha256, DIGEST)
        validate(context.duration_frames, integer(1)); validate(context.sample_count, integer())
        validate(context.sample_rate, integer(1)); validate(context.no_audio, BOOL)
        if context.no_audio and context.sample_count:
            raise ContractError('OUTPUT_INVALID', 'Silent context cannot have audio samples.')
        if any(type(frame) is not int or frame < 0 or frame >= context.duration_frames for frame in context.requested_frames):
            raise ContractError('OUTPUT_INVALID', 'Review frame targets must belong to final candidate.')
        return context

    def _validate_bytes(self, fs, pointer, candidate):
        artifact = self.registry.artifact(fs, pointer, candidate['artifact'])
        if artifact['project_id'] != pointer['project_id'] or artifact['kind'] != 'media':
            raise ContractError('OUTPUT_INVALID', 'Candidate must be project-owned final encoded media.')
        if artifact['storage']['mode'] != 'managed':
            raise ContractError('OUTPUT_INVALID', 'Candidate/master must retain an immutable managed blob, not an external file.')
        for sidecar in candidate['sidecars']:
            for key in ('artifact', 'placement', 'timing_receipt'):
                if sidecar[key] is not None:
                    self.registry.artifact(fs, pointer, sidecar[key])
        return artifact

    def candidate(self, fs, pointer, pin):
        validate_delivery(pin, 'ArtifactRef')
        record = next((c for c in self._records(fs, pointer['project_id'], 'candidates') if c['artifact'] == pin), None)
        if record is None:
            raise ContractError('NOT_FOUND', 'No core-collected final candidate for exact pin.')
        validate_delivery(record, 'CandidateRecord')
        self._validate_bytes(fs, pointer, record)
        return record

    def register_candidate(self, record, *, request_id):
        """Internal collection API. Not exposed as a caller-controlled action."""
        validate_delivery(record, 'CandidateRecord'); validate(request_id, string(UUID_PATTERN))
        pid = record['project_id']; fs = self.store._filesystem(write=True)
        self.store._pointer(fs, pid)
        args = {'request_id': request_id, 'candidate': record}
        with fs.lock(self.store._base(pid) + '/locks/content.lock'):
            pointer = self.store._pointer(fs, pid)
            replay = self._replay(fs, pid, 'candidate', args)
            if replay is not None:
                return replay
            metadata = self._validate_bytes(fs, pointer, record)
            if metadata['producer']['job_id'] != record['job_id']:
                raise ContractError('OUTPUT_INVALID', 'Candidate producer does not match collected job.')
            if record['project_revision'] > pointer['revision']:
                raise ContractError('REVISION_CONFLICT', 'Candidate is from a future project revision.')
            if self.collect_validator is None or self.collect_validator(fs, pointer, copy.deepcopy(record)) is not True:
                raise ContractError('OUTPUT_INVALID', 'Genuine typed delivery.encode collection is not verified.')
            existing = [c for c in self._records(fs, pid, 'candidates') if c['artifact']['artifact_id'] == record['artifact']['artifact_id']]
            if existing:
                if existing[0] != record:
                    raise ContractError('HASH_MISMATCH', 'An artifact identity already has a different candidate manifest.')
                return existing[0]
            # Historical/stale collected output is retained, never silently current.
            self.context(fs, pointer, record)
            self._commit(fs, pid, 'candidate', args, record, {'candidates': [record]})
            return copy.deepcopy(record)

    def _receipt(self, fs, pointer, value, inputs):
        if self.publish_receipt is None:
            raise ContractError('CAPABILITY_MISSING', 'Core report artifact publisher is not wired.')
        payload = canonical(value)
        pin = self.publish_receipt(fs, pointer, payload, copy.deepcopy(inputs))
        validate_delivery(pin, 'ArtifactRef')
        if pin['sha256'] != 'sha256:' + hashlib.sha256(payload).hexdigest():
            raise ContractError('HASH_MISMATCH', 'Published receipt bytes differ.')
        record = self.registry.artifact(fs, pointer, pin)
        if record['storage']['mode'] != 'managed' or record['kind'] not in ('report', 'json'):
            raise ContractError('OUTPUT_INVALID', 'Receipt must be a managed core report.')
        return pin

    def promote(self, args):
        pid = args['project_id']; fs = self.store._filesystem(write=True)
        initial = self.store._pointer(fs, pid)
        replay = self._replay(fs, pid, 'promote', args)
        if replay is not None:
            return replay
        # Perform initial potentially large byte/sidecar validation outside the
        # project lock. No copies/encodes are necessary for retained managed blobs.
        prepared = [self.candidate(fs, initial, pin) for pin in args['candidates']]
        with fs.lock(self.store._base(pid) + '/locks/content.lock'):
            pointer = self.store._pointer(fs, pid)
            replay = self._replay(fs, pid, 'promote', args)
            if replay is not None:
                return replay
            if pointer['revision'] != args['expected_revision']:
                raise ContractError('REVISION_CONFLICT', 'Project content revision changed.')
            prior = self._records(fs, pid, 'masters')
            revision = max([r['revision'] for r in prior] + [0])
            if args['expected_master_revision'] != revision:
                raise ContractError('REVISION_CONFLICT', 'Master set revision changed.')
            if self.reviews is None:
                raise ContractError('GATE_UNSATISFIED', 'Review service is not wired.')
            candidates = [self.candidate(fs, pointer, pin) for pin in args['candidates']]
            if candidates != prepared:
                raise ContractError('PLAN_STALE', 'Candidate manifest changed after preparation.')
            if len({c['variant_id'] for c in candidates}) != len(candidates):
                raise ContractError('INVALID_ARGUMENT', 'A promotion set cannot contain two candidates for one variant.')
            summaries = [self.reviews.gates(fs, pointer, c) for c in candidates]
            if any(not s['promotion_eligible'] for s in summaries):
                raise ContractError('GATE_UNSATISFIED', 'Required gates are failed, stale, unverifiable or review_needed.')
            timestamp = _now(); masters = []
            for candidate, summary in zip(candidates, summaries):
                receipt = self._receipt(fs, pointer, summary, [candidate['artifact']])
                master = {'schema': 'motion/v1/master', 'master_id': _id('mst'), 'revision': revision + 1,
                    'project_id': pid, 'variant_id': candidate['variant_id'], 'artifact': copy.deepcopy(candidate['artifact']),
                    'candidate': copy.deepcopy(candidate['artifact']), 'candidate_manifest_sha256': digest(candidate),
                    'dependencies_sha256': candidate['dependencies_sha256'], 'sidecars': copy.deepcopy(candidate['sidecars']),
                    'gate_summary_receipt': receipt, 'review_ids': sorted({rid for g in summary['gates'] for rid in g['review_ids']}),
                    'promoted_at': timestamp, 'project_revision': pointer['revision']}
                validate_delivery(master, 'MasterRecord'); masters.append(master)
            promotion = self._receipt(fs, pointer, {'schema': 'motion/v1/promotion', 'masters': masters,
                'master_set_revision': revision + 1, 'request_id': args['request_id']}, [c['artifact'] for c in candidates])
            # Recheck actual media, all evidence, sidecars, policy and closure after
            # staging receipts, immediately before the single publication rename.
            for candidate, old in zip(candidates, summaries):
                self._validate_bytes(fs, pointer, candidate)
                if self.reviews.gates(fs, pointer, candidate) != old:
                    raise ContractError('PLAN_STALE', 'Candidate evidence changed while preparing promotion.')
            for receipt in [promotion] + [m['gate_summary_receipt'] for m in masters]:
                self.registry.artifact(fs, pointer, receipt)
            if self.store._pointer(fs, pid) != pointer:
                raise ContractError('REVISION_CONFLICT', 'Content pointer changed while preparing promotion.')
            result = {'masters': masters, 'master_set_revision': revision + 1, 'promotion_receipt': promotion}
            self._commit(fs, pid, 'promote', args, result, {'masters': masters})
            return result

    def master_count(self, project_id, *, fs=None, current_variants_only=False):
        """Native project.status count; metadata read only, never launches gates.

        Default counts all durable historical MasterRecords. Set
        current_variants_only=True to count the latest promoted set by variant.
        Neither number claims those historical outputs are current-policy valid.
        """
        fs = fs or self.store._filesystem()
        self.store._pointer(fs, project_id)
        records = self._records(fs, project_id, 'masters')
        for record in records:
            validate_delivery(record, 'MasterRecord')
            if record['project_id'] != project_id:
                raise ContractError('WRONG_PROJECT', 'Master record belongs to another project.')
        return len({r['variant_id'] for r in records}) if current_variants_only else len(records)

    def dispatch(self, args):
        validate_delivery(args, 'DeliveryRequest', self.options_schema)
        action = args['action']
        if action == 'promote':
            return self.promote(args)
        if action in ('encode', 'validate', 'package', 'package_validate'):
            if self.execute is None:
                raise ContractError('CAPABILITY_MISSING', 'B06/B07 delivery convenience compiler is not wired.')
            if action == 'encode':
                requested = args['variant_ids']; inputs = args['inputs']
                if sorted(requested) != sorted(i['variant_id'] for i in inputs):
                    raise ContractError('INVALID_ARGUMENT', 'Encode inputs must match exactly the requested variants.')
                if any('placement' in i and 'timeline_item_ids' in i for i in inputs):
                    raise ContractError('INVALID_ARGUMENT', 'Use placement or timeline_item_ids, never both.')
            return self.execute('motion_deliver', copy.deepcopy(args))
        fs = self.store._filesystem(); pointer = self.store._pointer(fs, args['project_id'])
        pid = pointer['project_id']; masters = self._records(fs, pid, 'masters')
        for master in masters:
            validate_delivery(master, 'MasterRecord')
        if action == 'files':
            if not args.get('master_ids') and not args.get('package_id'):
                raise ContractError('INVALID_ARGUMENT', 'Files requires master_ids or package_id.')
            if args.get('package_id'):
                package = max((p for p in self._records(fs, pid, 'packages')
                               if p['package_id'] == args['package_id']),
                              key=lambda p:p['revision'], default=None)
                if package is None:
                    raise ContractError('NOT_FOUND', 'Package does not exist in this project.')
                from .packaging import validate_package_record
                validate_package_record(package)
                files = []
                for pin, role in [(package['archive'], 'editable_package'), (package['manifest'], 'report')]:
                    if pin is None:
                        continue
                    metadata = self.registry.artifact(fs, pointer, pin)
                    if metadata['storage']['mode'] != 'managed':
                        raise ContractError('OUTPUT_INVALID', 'Package files must be managed.')
                    relative = metadata['storage']['relative_path']; base = self.store._base(pid)
                    files.append(dict(artifact=pin, role=role, filename=pin['artifact_id'],
                        size_bytes=metadata['size_bytes'], media_type=metadata['media_type'],
                        delivery_handle=str(fs.root / (relative if relative.startswith(base + '/') else base + '/' + relative)),
                        verification=package['state'] if package['state'] in ('verified', 'draft') else 'incomplete', expires_at=None))
                return self.store._page(fs, {**args, '_tool': 'motion_deliver'},
                    None if args.get('cursor') or args.get('snapshot_id') else files)
            selected = [m for m in masters if m['master_id'] in args['master_ids']]
            if len(selected) != len(args['master_ids']):
                raise ContractError('NOT_FOUND', 'Requested master does not exist in this project.')
            files = []
            for master in selected:
                candidate = self.candidate(fs, pointer, master['candidate'])
                if self.reviews is None or not self.reviews.gates(fs, pointer, candidate)['promotion_eligible']:
                    raise ContractError('GATE_UNSATISFIED', 'Historical master is stale or no longer passes required gates.')
                for pin, role in [(master['artifact'], 'master')] + [(s['artifact'], 'sidecar') for s in master['sidecars']]:
                    metadata = self.registry.artifact(fs, pointer, pin)
                    if metadata['storage']['mode'] != 'managed':
                        raise ContractError('OUTPUT_INVALID', 'Delivery files must be managed.')
                    relative = metadata['storage']['relative_path']
                    base = self.store._base(pid)
                    path = str(fs.root / (relative if relative.startswith(base + '/') else base + '/' + relative))
                    files.append({'artifact': pin, 'role': role, 'filename': master['master_id'] if role == 'master' else pin['artifact_id'],
                        'size_bytes': metadata['size_bytes'], 'media_type': metadata['media_type'], 'delivery_handle': path,
                        'verification': 'verified', 'expires_at': None})
            return self.store._page(fs, {**args, '_tool': 'motion_deliver'},
                None if args.get('cursor') or args.get('snapshot_id') else files)
        section = args.get('section', 'summary')
        if section == 'packages':
            from .packaging import validate_package_record
            packages = self._records(fs, pid, 'packages')
            latest = {}
            for package in packages:
                validate_package_record(package)
                previous = latest.get(package['package_id'])
                if previous is None or package['revision'] > previous['revision']:
                    latest[package['package_id']] = package
            return self.store._page(fs, {**args, '_tool': 'motion_deliver'},
                None if args.get('cursor') or args.get('snapshot_id') else list(latest.values()))
        candidates = self._records(fs, pid, 'candidates')
        if args.get('variant_id'):
            candidates = [c for c in candidates if c['variant_id'] == args['variant_id']]
            masters = [m for m in masters if m['variant_id'] == args['variant_id']]
        if section == 'masters':
            return self.store._page(fs, {**args, '_tool': 'motion_deliver'},
                None if args.get('cursor') or args.get('snapshot_id') else masters)
        summaries = []
        for candidate in candidates:
            self.candidate(fs, pointer, candidate['artifact'])
            if self.reviews is None:
                raise ContractError('CAPABILITY_MISSING', 'Review service is not wired.')
            summary = {'artifact': candidate['artifact'], 'candidate_manifest_sha256': digest(candidate),
                'variant_id': candidate['variant_id'], 'project_revision': candidate['project_revision'],
                'created_at': candidate['created_at'], 'gates': self.reviews.gates(fs, pointer, candidate)}
            summaries.append(summary)
        if section == 'candidates':
            return self.store._page(fs, {**args, '_tool': 'motion_deliver'},
                None if args.get('cursor') or args.get('snapshot_id') else summaries)
        ids = sorted({c['variant_id'] for c in candidates} | {m['variant_id'] for m in masters})
        if len(ids) > 20:
            raise ContractError('LIMIT_EXCEEDED', 'Use paginated candidates/masters sections for more than 20 variants.')
        outcomes = []
        for variant_id in ids:
            candidate = next((c for c in reversed(candidates) if c['variant_id'] == variant_id), None)
            master = next((m for m in sorted(masters, key=lambda m: m['revision'], reverse=True) if m['variant_id'] == variant_id), None)
            summary = next((s for s in summaries if candidate and s['artifact'] == candidate['artifact']), None)
            if master and (not summary or master['candidate'] != summary['artifact'] or not summary['gates']['promotion_eligible']):
                master = None
            outcomes.append({'variant_id': variant_id, 'state': 'master' if master else 'candidate' if summary and summary['gates']['promotion_eligible'] else 'review_needed',
                'candidate': candidate['artifact'] if candidate else None, 'master_id': master['master_id'] if master else None,
                'job_id': candidate['job_id'] if candidate else None, 'reason': None if master else '; '.join(summary['gates']['missing']) if summary else 'No candidate.'})
        return {'variants': outcomes}


class _NativeRegistry:
    """Production bridge to the single core artifact catalog, not a fixture registry."""
    def __init__(self, catalog):
        self.catalog = catalog

    def artifact(self, fs, pointer, pin):
        return self.catalog.resolve_at(fs, pointer, pin)


class NativeDeliveryService(DeliveryService):
    """Native retained-job collection and conservative silent technical review.

    Uses committed B06/B07 records and durable output-probe receipts. It never
    launches a decoder during status/read, invents agent/human observations or
    converts an unknown license into a rights grant. Unsupported caption/audio
    checks stay blocked. Full promotion still uses the unchanged five-gate policy.
    """
    def __init__(self, runtime=None, *, session_id=None, task_id=None):
        if runtime is None:
            from .runtime import NativeRuntime
            runtime = NativeRuntime()
        self.runtime = runtime
        self.session_id, self.task_id = session_id, task_id
        from .native_delivery import DeliveryExecutor
        self.executor = DeliveryExecutor(self)
        super().__init__(runtime.projects, registry=_NativeRegistry(runtime.artifacts),
            context_resolver=self._native_context, collect_validator=self._native_collected,
            publish_receipt=self._native_publish, execute=self.executor.dispatch)
        from .reviews import ReviewService
        ReviewService(self, attribution=self._native_attribution, verify_review=self._native_verify,
                      execute=self.executor.dispatch)

    def _native_publish(self, fs, pointer, payload, inputs):
        import json
        # Ancillary records are core publications; references remain in the
        # canonical receipt payload and are verified again by the gate resolver.
        return self.runtime.artifacts.publish_json(pointer['project_id'], json.loads(payload), kind='report')

    def _job(self, candidate):
        bundle = self.runtime.jobs().read(candidate['project_id'], candidate['job_id'])
        job, plan = bundle['job'], bundle['plan_record']
        nodes = [n for n in plan['nodes'] if n['operation'] == 'delivery.encode@1'
                 and bundle['output_ports'].get(n['node_id'], {}).get('candidate') == candidate['artifact']]
        if job['state'] != 'succeeded' or job['plan'] != candidate['plan'] or len(nodes) != 1:
            raise ContractError('OUTPUT_INVALID', 'Candidate lacks a successful committed encode node.')
        node = nodes[0]
        state = next(s for s in job['node_states'] if s['node_id'] == node['node_id'])
        if state['state'] != 'succeeded' or candidate['artifact'] not in state['outputs']:
            raise ContractError('OUTPUT_INVALID', 'Encode node has no committed candidate output.')
        record = self.runtime.artifacts.resolve(candidate['project_id'], candidate['artifact'])
        if record['producer']['node_id'] != node['node_id']:
            raise ContractError('OUTPUT_INVALID', 'Candidate producer differs from committed encode node.')
        return bundle, node, record

    def _snapshot(self, fs, pointer, revision):
        while pointer and pointer['revision'] != revision:
            pointer = self.store._transaction(fs, pointer)['previous']
        if pointer is None:
            raise ContractError('NOT_FOUND', 'Candidate snapshot is not in project history.')
        return self.store._load(fs, pointer)[1]

    @staticmethod
    def _document_pin(document):
        return {k: document[k] for k in ('kind', 'id', 'revision')} | {'sha256': digest(document)}

    def _closure(self, fs, pointer, pin):
        records, visiting = {}, set()
        def walk(ref):
            aid = ref['artifact_id']
            if aid in visiting:
                raise ContractError('INVALID_GRAPH', 'Candidate artifact closure contains a cycle.')
            if aid in records:
                if records[aid]['sha256'] != ref['sha256']:
                    raise ContractError('HASH_MISMATCH', 'Closure contains conflicting artifact pins.')
                return
            visiting.add(aid)
            record = self.registry.artifact(fs, pointer, ref)
            for child in record['inputs'] + record['provenance']['rights']['evidence']:
                walk(child)
            visiting.remove(aid); records[aid] = record
        walk(pin)
        return records

    def _dependencies(self, candidate, bundle, records, before, after):
        from .reviews import affected_plan_nodes
        stale = affected_plan_nodes(bundle['plan_record']['nodes'], before, after)
        value = {'plan': candidate['plan'], 'closure': sorted(
            [(r['artifact_id'], r['sha256']) for r in records.values()]),
            'sidecars': candidate['sidecars']}
        # Unrelated document edits don't invalidate an encoded dependency graph.
        if stale:
            value['changed_consumers'] = stale
            value['current_documents'] = sorted((k, digest(v)) for k, v in after.items())
        return digest(value)

    def _probe(self, bundle, record):
        from .adapters.probe import LocalOutputProbe
        rid = record['probe_receipt_id']
        receipt = bundle.get('probe_receipts', {}).get(record['artifact_id'])
        if isinstance(receipt, dict) and receipt.get('schema') != 'motion/v1/local-output-probe-evidence':
            # Older jobs retained a receipt hash, with the actual observation
            # exported separately. Explicit import below preserves that binding.
            try:
                return self.runtime.jobs().resolve_probe_receipt(record['project_id'],
                    {k:record[k] for k in ('artifact_id','sha256')})
            except ContractError as exc:
                if exc.code != 'NOT_FOUND':
                    raise
            path = self.store._base(record['project_id']) + '/quality/probe-evidence/' + rid + '.json'
            retained = self.store._filesystem().read(path)
            if digest(retained) != receipt.get('sha256') or receipt.get('receipt_id') != rid:
                raise ContractError('HASH_MISMATCH', 'Imported legacy probe differs from committed receipt hash.')
            receipt = retained
        return LocalOutputProbe.verify_receipt(rid, receipt,
            **{k: record[k] for k in ('sha256', 'kind', 'media_type', 'size_bytes')})

    def _native_collected(self, fs, pointer, candidate):
        bundle, node, record = self._job(candidate)
        before = self._snapshot(fs, pointer, bundle['job']['project_revision'])
        params = node['parameters']
        settings = before['settings', 'project']['value']
        policy = before['gate_policy', settings['gate_policy']['policy_id']]
        if (candidate['project_revision'] != bundle['job']['project_revision']
                or candidate['variant_id'] != params['variant']
                or candidate['variant'] != params['variant_document']
                or candidate['gate_policy'] != self._document_pin(policy)):
            return False
        if candidate['sidecars'] != self.executor.sidecars(candidate['project_id'], bundle, node):
            raise ContractError('HASH_MISMATCH', 'Candidate sidecars differ from exact encode input descriptor.')
        records = self._closure(fs, pointer, candidate['artifact'])
        self._probe(bundle, record)
        return candidate['dependencies_sha256'] == self._dependencies(candidate, bundle, records, before, before)

    def retain_probe_evidence(self, project_id, job_id, pin, receipt):
        """Import old exported observations only against the committed receipt hash."""
        from .adapters.probe import LocalOutputProbe
        bundle = self.runtime.jobs().read(project_id, job_id)
        record = self.runtime.artifacts.resolve(project_id, pin)
        if record['producer']['job_id'] != job_id:
            raise ContractError('WRONG_PROJECT', 'Probe artifact does not belong to selected job.')
        rid = record['probe_receipt_id']
        LocalOutputProbe.verify_receipt(rid, receipt,
            **{k: record[k] for k in ('sha256', 'kind', 'media_type', 'size_bytes')})
        committed = bundle['probe_receipts'].get(pin['artifact_id'])
        if committed != receipt and committed != dict(receipt_id=rid, sha256=digest(receipt)):
            raise ContractError('HASH_MISMATCH', 'Receipt is not bound to committed job output.')
        fs = self.store._filesystem(write=True)
        path = self.store._base(project_id) + '/quality/probe-evidence/' + rid + '.json'
        with fs.lock(self.store._base(project_id) + '/locks/quality.lock'):
            try:
                prior = fs.read(path)
            except FileNotFoundError:
                fs.write(path, receipt, replace=False)
            else:
                if prior != receipt:
                    raise ContractError('HASH_MISMATCH', 'Retained observation cannot be replaced.')
        if fs.read(path) != receipt:
            raise ContractError('HASH_MISMATCH', 'Probe evidence retention failed.')
        return rid

    def collect_job(self, project_id, job_id, *, request_id):
        """Explicitly register real collected encodes; never re-encode on reads."""
        fs = self.store._filesystem(); pointer = self.store._pointer(fs, project_id)
        bundle = self.runtime.jobs().read(project_id, job_id)
        before = self._snapshot(fs, pointer, bundle['job']['project_revision'])
        settings = before['settings', 'project']['value']
        policy = before['gate_policy', settings['gate_policy']['policy_id']]
        records = []
        nodes = [n for n in bundle['plan_record']['nodes'] if n['operation'] == 'delivery.encode@1']
        if not nodes:
            raise ContractError('UNSUPPORTED_FEATURE', 'No committed encode outputs in selected job.')
        for node in nodes:
            pin = bundle['output_ports'].get(node['node_id'], {}).get('candidate')
            if pin is None:
                raise ContractError('OUTPUT_UNAVAILABLE', 'Encode output is not committed.')
            candidate = dict(schema='motion/v1/candidate', artifact=pin, project_id=project_id,
                project_revision=bundle['job']['project_revision'], plan=bundle['job']['plan'],
                variant_id=node['parameters']['variant'], variant=node['parameters']['variant_document'],
                sidecars=self.executor.sidecars(project_id, bundle, node), gate_policy=self._document_pin(policy), job_id=job_id,
                created_at=bundle['job']['updated_at'])
            closure = self._closure(fs, pointer, pin)
            candidate['dependencies_sha256'] = self._dependencies(candidate, bundle, closure, before, before)
            from .native_delivery import child_id
            records.append(self.register_candidate(candidate, request_id=child_id(request_id, node['node_id'])))
        return records

    def _native_context(self, fs, pointer, candidate):
        from fractions import Fraction
        bundle, node, record = self._job(candidate)
        before = self._snapshot(fs, pointer, candidate['project_revision'])
        after = self.store._load(fs, pointer)[1]
        settings = after['settings', 'project']['value']
        policy = after['gate_policy', settings['gate_policy']['policy_id']]
        variants = after['variants', 'project']
        variant = next((v for v in variants['value'] if v['variant_id'] == candidate['variant_id']), None)
        if variant is None:
            raise ContractError('PLAN_STALE', 'Candidate variant no longer exists.')
        records = self._closure(fs, pointer, candidate['artifact'])
        probe = self._probe(bundle, record)
        streams = probe['probe']['streams']
        video = [s for s in streams if s['codec_type'] == 'video']
        if len(video) != 1:
            raise ContractError('OUTPUT_INVALID', 'Candidate must have exactly one video stream.')
        stream = video[0]
        frames = probe.get('decoded_frames', 0)
        no_audio = not any(s['codec_type'] == 'audio' for s in streams)
        blockers = []
        # Rights declarations remain provenance metadata, not release gates.
        audio = [s for s in streams if s['codec_type'] == 'audio']
        sample_count = probe.get('presentation_samples', 0)
        audio_ok = (not no_audio and len(audio) == 1 and sample_count > 0
            and variant['audio']['mode'] == 'required'
            and audio[0]['codec_name'] == variant['audio']['codec']
            and probe.get('sample_rate_hz') == variant['audio']['sample_rate']
            and probe.get('channels') == variant['audio']['channels'])
        if not ((no_audio and settings['audio_mode'] == 'silent' and variant['audio']['mode'] == 'none') or audio_ok):
            blockers.append('AUDIO_FORMAT_MISMATCH')
        if variant['captions'] in ('sidecar', 'both') and not candidate['sidecars']:
            blockers.append('CAPTION_SIDECAR_MISSING')
        if variant['captions'] in ('burn', 'both'):
            blockers.append('CAPTION_BURN_VISUAL_REVIEW_REQUIRED')
        for sidecar in candidate['sidecars']:
            self.executor.verify_sidecar(candidate['project_id'], sidecar, candidate['variant'])
        profile = after.get(('delivery_profile', variant['profile']['id']))
        if profile is None or self._document_pin(profile) != variant['profile']:
            blockers.append('DELIVERY_PROFILE_STALE')
        # These named facts are established from a rehashed candidate and its
        # independently retained whole-decode receipt, never source-file facts.
        checks = {'whole_decode'} if frames else set()
        if no_audio:
            checks.add('no_audio')
        if audio_ok:
            checks.update(('audio_format', 'audio_decode'))
        if candidate['sidecars']:
            checks.update(('caption_export_parity', 'caption_timing'))
        alpha_ok = (variant['alpha'] == 'straight' and probe.get('alpha_mode') == 'straight'
            and probe.get('decoded_alpha_frames') == frames and frames > 0
            and isinstance(probe.get('alpha_min'), int) and isinstance(probe.get('alpha_max'), int))
        if alpha_ok:
            checks.add('alpha_decode')
        elif variant['alpha'] != 'none':
            blockers.append('ALPHA_EVIDENCE_MISSING')
        if (frames == variant['duration_frames'] and stream['width'] == variant['width_px']
                and stream['height'] == variant['height_px'] and stream['codec_name'] == variant['video_codec']
                and stream['pix_fmt'] == variant['pixel_format']
                and Fraction(stream['r_frame_rate']) == Fraction(variant['rate']['num'], variant['rate']['den'])
                and variant['container'] in probe['probe']['format']['format_name'].split(',')):
            checks.add('variant_format')
        if 'variant_format' not in checks:
            blockers.append('VARIANT_FORMAT_MISMATCH')
        if profile:
            c = profile['value']['constraints']
            audio_profile_ok = (no_audio or (audio_ok and variant['audio']['codec'] in c['allowed_audio_codecs']))
            from .final_quality import audio_targets_met
            measured_targets = audio_targets_met(probe, c, variant['audio'])
            if measured_targets and audio_ok:
                checks.add('audio_targets')
            if measured_targets and not no_audio:
                if c['loudness_lufs'] is not None or variant['audio']['loudness_lufs'] is not None:
                    checks.add('loudness')
                if c['true_peak_dbtp'] is not None or variant['audio']['true_peak_dbtp'] is not None:
                    checks.add('true_peak')
            if (audio_profile_ok and measured_targets
                    and variant['container'] in c['allowed_containers'] and variant['video_codec'] in c['allowed_video_codecs']
                    and variant['captions'] in c['caption_modes'] and variant['width_px'] == c['width_px']
                    and variant['height_px'] == c['height_px'] and variant['rate'] == c['rate']
                    and (c['max_bytes'] is None or record['size_bytes'] <= c['max_bytes'])
                    and (c['max_duration_frames'] is None or frames <= c['max_duration_frames'])
                    and ((c['alpha'] in ('optional','required') and alpha_ok)
                         or (c['alpha'] != 'required' and variant['alpha'] == 'none'))):
                checks.add('delivery_profile')
            else:
                blockers.append('DELIVERY_PROFILE_MISMATCH')
        scenes = tuple(d['id'] for d in after.values() if d['kind'] == 'scene')
        return GateContext(policy=policy['value'], policy_pin=self._document_pin(policy),
            dependencies_sha256=self._dependencies(candidate, bundle, records, before, after),
            variant=self._document_pin(variants), duration_frames=max(1, frames), sample_count=sample_count,
            sample_rate=probe.get('sample_rate_hz', settings['sample_rate']), no_audio=no_audio, scene_ids=scenes,
            requested_frames=(0, max(0, frames - 1)), blockers=tuple(sorted(set(blockers))),
            checked_names=frozenset(checks))

    def _native_attribution(self, collected):
        if collected.get('native_retained_probe') is True:
            return dict(author=dict(kind='system', actor_ref='core:retained-output-probe'),
                        tool='native-retained-probe', tool_version='1')
        bridge = self.runtime.host_bridge
        if (bridge is None or bridge.identity.get('tool_name') != 'motion_review'
                or bridge.identity.get('args_sha256') != digest(collected)
                or collected.get('method') not in ('agent_visual', 'agent_audio', 'playback')
                or collected.get('result') not in ('pass', 'fail', 'review_needed')):
            raise ContractError('REVIEW_AUTHOR_UNVERIFIED', 'No native human/agent observation bridge was supplied.')
        import copy
        self._native_review_request = copy.deepcopy(collected)
        return dict(author=bridge.actor(), tool='motion_review', tool_version='1')

    def _native_agent_verify(self, review, candidate, context):
        """Admit conservative agent claims once; cold reads use the durable admission.

        Host pre-call association authenticates the agent, not a human and not
        the truth of an agent judgment. Final pass/fail requires exact method,
        gate, result and bounded coverage in a durably joined observation.
        Evidence publication alone never confers actor authority.
        """
        if (review['method'] not in ('agent_visual', 'agent_audio', 'playback')
                or review['result'] not in ('pass', 'fail', 'review_needed') or review['author']['kind'] != 'agent'
                or review['tool'] != 'motion_review' or review['tool_version'] != '1'
                or len(review['evidence']) != 1):
            return False
        coverage = review['coverage']
        method = review['method']
        if (coverage['whole_decode']
                or any(s['end_frame'] > context.duration_frames for s in coverage['frame_ranges'])
                or any(s['end_sample'] > context.sample_count or s['sample_rate'] != context.sample_rate for s in coverage['sample_ranges'])
                or set(coverage['scene_ids']) - set(context.scene_ids)
                or set(coverage['transition_keys']) - set(context.transition_keys)
                or (method == 'agent_visual' and (review['gate'] not in ('art', 'creative') or not coverage['frame_ranges'] or coverage['sample_ranges'] or coverage['playback'] != 'not_tested'))
                or (method == 'agent_audio' and (review['gate'] != 'audio' or not coverage['sample_ranges'] or coverage['frame_ranges'] or coverage['playback'] != 'not_tested'))
                or (method == 'playback' and coverage['playback'] not in ('pass', 'fail'))):
            return False
        record = self.runtime.artifacts.resolve(candidate['project_id'], review['evidence'][0])
        import json
        try:
            with self.runtime.artifacts.open_record(self.store._filesystem(), record) as stream:
                observation = json.load(stream)
        except (ValueError, UnicodeError):
            return False
        expected: dict = dict(schema='motion/v1/agent-observation', author=review['author'],
            candidate=candidate['artifact'], candidate_manifest_sha256=digest(candidate),
            dependencies_sha256=candidate['dependencies_sha256'], coverage=coverage)
        if review['result'] != 'review_needed' or review['method'] != 'agent_visual':
            expected.update(method=review['method'], gate=review['gate'], result=review['result'])
        if isinstance(observation, dict) and 'checks' in observation:
            if (review['method'] != 'agent_visual' or review['gate'] not in ('art', 'creative')
                    or observation['checks'] != ['caption_burn_visual']):
                return False
            expected['checks'] = ['caption_burn_visual']
        if (not isinstance(observation, dict) or set(observation) != set(expected) | {'observed'}
                or any(observation.get(k) != v for k, v in expected.items())
                or not isinstance(observation['observed'], str) or not observation['observed'].strip()):
            return False
        from .host_bridge import HostBridge
        prefix = 'hermes:session:'
        actor_ref = review['author']['actor_ref']
        if not actor_ref.startswith(prefix) or not actor_ref[len(prefix):]:
            return False
        admitted = HostBridge(self.store, {'session_id': actor_ref[len(prefix):]})
        key = 'reviews/' + digest(review).split(':', 1)[1] + '.json'
        saved = admitted._read(key)
        bridge = self.runtime.host_bridge
        from .host_bridge import _key
        if saved is None:
            if bridge is None or bridge.actor() != review['author']:
                return False
            invocation = bridge._read('invocations/' + _key(bridge.identity.get('tool_call_id', '')) + '.json')
            if invocation != bridge.identity | {'consumed': True}:
                return False
            saved = dict(review_sha256=digest(review), actor=review['author'],
                invocation=invocation, request=getattr(self, '_native_review_request', None))
            persist = True
        else:
            persist = False
        # A receipt is a durable host-call/request join, not authority from two
        # self-asserted fields. Legacy incomplete receipts fail closed.
        if (not isinstance(saved, dict) or set(saved) != {'review_sha256', 'actor', 'invocation', 'request'}
                or saved['review_sha256'] != digest(review) or saved['actor'] != review['author']):
            return False
        invocation, request = saved['invocation'], saved['request']
        fields = {'session_id', 'tool_call_id', 'api_request_id', 'turn_id',
                  'task_id', 'tool_name', 'args_sha256', 'consumed'}
        if (not isinstance(invocation, dict) or set(invocation) != fields
                or invocation['consumed'] is not True
                or any(not isinstance(invocation[k], str) for k in fields - {'consumed'})
                or invocation['session_id'] != admitted.session or not invocation['tool_call_id']
                or invocation['tool_name'] != 'motion_review'
                or admitted._read('invocations/' + _key(invocation['tool_call_id']) + '.json') != invocation
                or not isinstance(request, dict) or digest(request) != invocation['args_sha256']):
            return False
        from .reviews import validate_review
        try:
            validate_review(request, 'ReviewRequest')
        except ContractError:
            return False
        if (request.get('action') != 'record' or request.get('project_id') != review['project_id']
                or request.get('candidate') != review['subject']
                or request.get('expected_candidate_manifest_sha256') != review['candidate_manifest_sha256']
                or request.get('supersedes') != review['supersedes']
                or any(request.get(k) != review[k] for k in
                       ('gate', 'result', 'method', 'evidence', 'coverage', 'findings', 'reason'))
                or review['measurements'] != [] or review['policy'] != candidate['gate_policy']):
            return False
        if persist:
            if bridge is None:
                return False
            bridge._write(key, saved)
        return True

    def caption_visual_verified(self, review, candidate, context):
        """Explicit caption-pixels claim from a rehashed, host-attributed review.

        This is called only after ordinary review verification; re-verify to
        fail closed for standalone internal callers too. No process is started.
        """
        if (review['method'] != 'agent_visual' or review['gate'] not in ('art', 'creative')
                or review['result'] != 'pass' or not self._native_agent_verify(review, candidate, context)):
            return False
        import json
        record = self.runtime.artifacts.resolve(candidate['project_id'], review['evidence'][0])
        with self.runtime.artifacts.open_record(self.store._filesystem(), record) as stream:
            observation = json.load(stream)
        return observation.get('checks') == ['caption_burn_visual']

    def _expected_check(self, candidate, gate):
        fs = self.store._filesystem(); pointer = self.store._pointer(fs, candidate['project_id'])
        context = self.context(fs, pointer, candidate)
        bundle, _, record = self._job(candidate)
        probe = self._probe(bundle, record)
        if gate == 'audio':
            if context.no_audio and 'AUDIO_FORMAT_MISMATCH' not in context.blockers:
                result = 'not_applicable'
            else:
                result = 'pass' if {'audio_format', 'audio_decode', 'audio_targets'} <= context.checked_names else 'fail'
        elif gate == 'delivery_profile':
            result = 'pass' if {'variant_format', 'delivery_profile'} <= context.checked_names else 'fail'
        elif gate == 'technical':
            result = 'pass' if {'whole_decode', 'variant_format'} <= context.checked_names else 'fail'
        else:
            raise ContractError('UNSUPPORTED_FEATURE', 'Only retained deterministic technical/audio/profile checks are supported.')
        evidence = {'schema': 'motion/v1/native-retained-check', 'candidate': candidate['artifact'],
            'candidate_manifest_sha256': digest(candidate), 'dependencies_sha256': candidate['dependencies_sha256'],
            'probe_receipt_id': record['probe_receipt_id'], 'probe': probe, 'gate': gate, 'result': result}
        return result, evidence

    def _native_verify(self, review, candidate, context):
        if review['method'] in ('agent_visual', 'agent_audio', 'playback'):
            return self._native_agent_verify(review, candidate, context)
        if (review['method'] != 'deterministic' or review['author'] != dict(kind='system', actor_ref='core:retained-output-probe')
                or review['tool'] != 'native-retained-probe' or review['tool_version'] != '1'):
            return False
        result, evidence = self._expected_check(candidate, review['gate'])
        if review['result'] != result or len(review['evidence']) != 1:
            return False
        pin = review['evidence'][0]
        record = self.runtime.artifacts.resolve(candidate['project_id'], pin)
        import json
        with self.runtime.artifacts.open_record(self.store._filesystem(), record) as stream:
            actual = json.load(stream)
        return actual == evidence and pin['sha256'] == digest(evidence)

    def export_candidate_files(self, project_id, pin, *, destination, filename, sidecar_names=None):
        """Export exact requested bytes for inspection, explicitly NOT a master.

        No encode, policy bypass, promotion or missing-sidecar substitution occurs.
        destination must already be an explicitly selected absolute directory.
        """
        import hashlib
        import os
        import uuid
        from pathlib import Path
        from .project import ManagedFS
        fs = self.store._filesystem(); pointer = self.store._pointer(fs, project_id)
        candidate = self.candidate(fs, pointer, pin)
        sidecar_names = {} if sidecar_names is None else sidecar_names
        expected = {s['artifact']['artifact_id'] for s in candidate['sidecars']}
        if set(sidecar_names) != expected:
            raise ContractError('OUTPUT_UNAVAILABLE', 'Requested sidecars must match candidate bindings exactly.')
        requested = [(pin, filename, 'candidate')] + [
            (s['artifact'], sidecar_names[s['artifact']['artifact_id']], 'sidecar') for s in candidate['sidecars']]
        names = [name for _, name, _ in requested]
        if (any(not isinstance(n, str) or not n or Path(n).name != n or n in ('.', '..')
                or '\\' in n or ':' in n or any(ord(c) < 32 for c in n) for n in names)
                or len(set(n.casefold() for n in names)) != len(names)):
            raise ContractError('PATH_UNSAFE', 'Requested filenames must be unique plain filenames.')
        target = ManagedFS(Path(destination))
        result = []
        with target.directory() as directory:
            for artifact, name, role in requested:
                record = self.registry.artifact(fs, pointer, artifact)
                temporary = '.delivery-' + uuid.uuid4().hex
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                try:
                    sha, size = hashlib.sha256(), 0
                    with os.fdopen(fd, 'wb') as output, self.runtime.artifacts.open_record(fs, record) as source:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk); sha.update(chunk); size += len(chunk)
                        output.flush(); os.fsync(output.fileno())
                    if ('sha256:' + sha.hexdigest(), size) != (artifact['sha256'], record['size_bytes']):
                        raise ContractError('HASH_MISMATCH', 'Candidate changed during delivery copy.')
                    os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                    os.fsync(directory)
                    # Independent exact-target readback, not metadata-only indexing.
                    read_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                    with os.fdopen(read_fd, 'rb') as retained:
                        actual = hashlib.file_digest(retained, 'sha256').hexdigest()
                    if 'sha256:' + actual != artifact['sha256']:
                        raise ContractError('HASH_MISMATCH', 'Delivered candidate readback differs.')
                    result.append(dict(filename=name, artifact=artifact, size_bytes=size,
                        media_type=record['media_type'], role=role, verification='verified',
                        path=str(Path(destination) / name)))
                finally:
                    os.unlink(temporary, dir_fd=directory)
        return dict(status='unpromoted_candidate', variant_id=candidate['variant_id'],
            candidate_manifest_sha256=digest(candidate), files=result,
            approved_master=False, sidecars_requested=len(sidecar_names))

    def collect_checks(self, project_id, pin):
        """Collect deterministic observations only; playback/creative/art remain pending."""
        import uuid
        fs = self.store._filesystem(); pointer = self.store._pointer(fs, project_id)
        candidate = self.candidate(fs, pointer, pin)
        context = self.context(fs, pointer, candidate)
        results = []
        for gate in ('technical', 'audio', 'delivery_profile'):
            result, evidence = self._expected_check(candidate, gate)
            evidence_pin = self.runtime.artifacts.publish_json(project_id, evidence, kind='report')
            args = dict(action='record', project_id=project_id, request_id=str(uuid.uuid4()), candidate=pin,
                expected_candidate_manifest_sha256=digest(candidate), gate=gate, result=result, method='deterministic',
                evidence=[evidence_pin], coverage=dict(frame_ranges=[dict(start_frame=0, end_frame=context.duration_frames)],
                sample_ranges=[], scene_ids=[], transition_keys=[], whole_decode=True, playback='not_tested'),
                findings=[], reason='Rehashed exact candidate and durable owned whole-decode probe; no playback/human judgement.')
            results.append(self.reviews.record(args, collected=dict(native_retained_probe=True, measurements=[])))
        return results
