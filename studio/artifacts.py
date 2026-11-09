"""Small core artifact catalog, not a second mutable index.

Originals are owned by committed asset transactions; outputs by validated job
bundles. Only ancillary JSON manifests/reports have their own immutable records.
All resolutions rehash bytes through AssetRegistry, including source closures.
"""
from __future__ import annotations

import copy
import uuid

from .assets import AssetRegistry, validate_asset
from .contracts import ContractError, canonical, digest, ident, validate
from .project import _now


def inherited_rights(records):
    """Carry declarations, not new grants. No inputs or any unknown stays unknown.

    Different licenses are retained in the input records, not combined into an
    invented compatible license. Restrictions and attribution are never dropped.
    """
    rights = [r['provenance']['rights'] for r in records]
    evidence, attribution = [], []
    for value in rights:
        for pin in value['evidence']:
            if pin not in evidence:
                evidence.append(copy.deepcopy(pin))
        if value['attribution'] and value['attribution'] not in attribution:
            attribution.append(value['attribution'])
    licenses = {r['license'] for r in rights if r['license']}
    unresolved = not rights or any(r['status'] == 'unknown' or
        (r['status'] == 'known' and not r['license']) for r in rights)
    status = ('unknown' if unresolved else 'restricted' if
        any(r['status'] == 'restricted' for r in rights) or len(licenses) != 1 else 'known')
    return {'status': status, 'license': next(iter(licenses)) if not unresolved and len(licenses) == 1 else None,
            'attribution': '\n'.join(attribution) or None, 'evidence': evidence}


class ArtifactCatalog:
    def __init__(self, projects, *, jobs=None):
        if jobs is None:
            from .jobs import JobStore
            jobs = JobStore(projects)
        self.projects, self.jobs = projects, jobs
        self.assets = AssetRegistry(projects)

    def _verify(self, fs, pid, pin, record, *, job=False):
        validate_asset(record, 'ArtifactRecord')
        if record['project_id'] != pid:
            raise ContractError('WRONG_PROJECT', 'Artifact owner differs from selected project.')
        if any(record[k] != pin[k] for k in ('artifact_id', 'sha256')):
            raise ContractError('HASH_MISMATCH', 'Artifact pin differs from committed record.')
        opened = copy.deepcopy(record)
        # B07 job manifests currently store root-relative paths; B04 records use
        # project-relative paths. Interpret only the validated owning job prefix.
        if job and opened['storage']['mode'] == 'managed':
            base = self.projects._base(pid) + '/'
            relative = opened['storage']['relative_path']
            if relative.startswith(base):
                opened['storage']['relative_path'] = relative[len(base):]
        with self.assets.open_artifact(fs, opened):
            pass
        return copy.deepcopy(record)

    def open_record(self, fs, record):
        """Open an already resolved record using its validated producer convention."""
        opened = copy.deepcopy(record)
        if opened['producer']['job_id'] is not None and opened['storage']['mode'] == 'managed':
            base = self.projects._base(opened['project_id']) + '/'
            path = opened['storage']['relative_path']
            if path.startswith(base):
                opened['storage']['relative_path'] = path[len(base):]
        return self.assets.open_artifact(fs, opened)

    def resolve(self, project_id, pin):
        fs = self.projects._filesystem()
        return self.resolve_at(fs, self.projects._pointer(fs, project_id), pin)

    def resolve_at(self, fs, pointer, pin):
        """Resolve under an explicit committed history, never a caller path."""
        validate_asset(pin, 'ArtifactRef')
        project_id = pointer['project_id']
        try:
            return self.assets._committed_artifact(fs, pointer, pin)
        except ContractError as exc:
            if exc.code != 'NOT_FOUND':
                raise
        base = self.projects._base(project_id)
        try:
            record = fs.read(base + '/ancillary/' + pin['artifact_id'] + '/record.json')
        except FileNotFoundError:
            record = None
        if record is not None:
            expected = 'ancillary/' + pin['artifact_id'] + '/payload.json'
            if record.get('storage') != {'mode': 'managed', 'relative_path': expected}:
                raise ContractError('PATH_UNSAFE', 'Ancillary artifact has an unexpected storage path.')
            return self._verify(fs, project_id, pin, record)
        if self.jobs is not None:
            matches, bundles = [], {}
            for name in fs.names(base + '/jobs'):
                if not name.endswith('.json'):
                    continue
                jid = name[:-5]
                validate(jid, ident('job'))
                bundle = bundles[jid] = self.jobs.read(project_id, jid)
                for item in bundle['artifacts']:
                    validate_asset(item, 'ArtifactRecord')
                    if item['artifact_id'] != pin['artifact_id']:
                        continue
                    if item['project_id'] != project_id:
                        raise ContractError('WRONG_PROJECT', 'Artifact owner differs from selected project.')
                    matches.append(item)
            if matches:
                # JobStore snapshots verified inputs as well as owned outputs.
                # Copies do not confer ownership: resolve their named producer,
                # then require every snapshot to agree, in either scan order.
                producer = matches[0]['producer']['job_id']
                bundle = bundles.get(producer)
                if bundle is None:
                    raise ContractError('OUTPUT_UNAVAILABLE', 'Artifact producing job is unavailable.')
                owned = [a for a in bundle['artifacts'] if a['artifact_id'] == pin['artifact_id']]
                if len(owned) != 1 or owned[0]['producer']['job_id'] != producer:
                    raise ContractError('WRONG_PROJECT', 'Artifact producer differs from owning job.')
                record = owned[0]
                if any(item != record for item in matches):
                    raise ContractError('HASH_MISMATCH', 'Copied artifact differs from authoritative producer record.')
                if any(record[k] != pin[k] for k in ('artifact_id', 'sha256')):
                    raise ContractError('HASH_MISMATCH', 'Artifact pin differs from committed record.')
                # Intermediate outputs belong to the named producing node, not
                # merely any node or the final target list in a copying job.
                node = next((n for n in bundle['job']['node_states']
                             if n['node_id'] == record['producer']['node_id']), None)
                if node is None or node['state'] != 'succeeded' or pin not in node['outputs']:
                    raise ContractError('OUTPUT_UNAVAILABLE', 'Artifact is not a committed producing-node output.')
                return self._verify(fs, project_id, pin, record, job=True)
        raise ContractError('NOT_FOUND', 'No committed artifact in selected project.')

    def publish_json(self, project_id, value, *, kind='json', media_type='application/json', inputs=()):
        """Trusted core publication with immutable, rehashed dependency lineage."""
        if kind == 'scene_source':
            # This is a typed, data-only canonical UI scene, not an arbitrary
            # executable source publication or a new general-purpose kind.
            from .adapters.ui_compositor import validate_source
            if media_type != 'application/json':
                raise ContractError('INVALID_ARGUMENT', 'Canonical UI scene sources require JSON media type.')
            validate_source(value)
            inputs = tuple(inputs)
            if list(inputs) != value['dependencies']:
                raise ContractError('HASH_MISMATCH', 'Canonical UI source dependencies differ from publication lineage.')
        elif kind not in ('json', 'report'):
            raise ContractError('INVALID_ARGUMENT', 'Ancillary publication supports JSON manifests/reports only.')
        lineage, records = [], []
        for pin in inputs:
            if pin not in lineage:
                records.append(self.resolve(project_id, pin))
                lineage.append(copy.deepcopy(pin))
        sha = digest(value)
        identity = kind + ':' + media_type + ':' + sha
        # Old publications remain immutable, including their unknown rights.
        # Same payload with newly bound dependencies has a distinct record id.
        if lineage:
            identity += ':inputs:' + digest(lineage)
        aid = 'art_' + str(uuid.uuid5(uuid.UUID(project_id[4:]), identity))
        pin = {'artifact_id': aid, 'sha256': sha}
        fs = self.projects._filesystem()
        self.projects._pointer(fs, project_id)
        base = self.projects._base(project_id)
        relative = 'ancillary/' + aid + '/payload.json'
        path = base + '/ancillary/' + aid + '/record.json'
        try:
            record = fs.read(path)
        except FileNotFoundError:
            record = None
        if record is not None:
            self._verify(fs, project_id, pin, record)
            return pin
        fs = self.projects._filesystem(write=True)
        with fs.lock(base + '/locks/ancillary.lock'):
            try:
                record = fs.read(path)
            except FileNotFoundError:
                now = _now()
                record = {'schema': 'motion/v1/artifact', 'artifact_id': aid, 'project_id': project_id,
                    'kind': kind, 'media_type': media_type, 'sha256': sha, 'size_bytes': len(canonical(value)),
                    'storage': {'mode': 'managed', 'relative_path': relative}, 'created_at': now,
                    'producer': {'job_id': None, 'node_id': None, 'attempt_id': None, 'adapter_id': None},
                    'inputs': lineage, 'probe_receipt_id': None,
                    'provenance': {'origin': 'derived' if lineage else 'authored', 'acquired_at': now, 'source_locator': None,
                        'provider': None, 'model': None, 'model_version': None, 'seed': None,
                        'deterministic': 'yes', 'rights': inherited_rights(records),
                        'notes': 'Core metadata publication; inherited declarations are not a new license or human review.'}}
                validate_asset(record, 'ArtifactRecord')
                # Payload first, atomic record last. Unpublished payloads confer
                # no handle. An interrupted matching payload can be recovered.
                try:
                    prior = fs.read(base + '/' + relative)
                except FileNotFoundError:
                    fs.write(base + '/' + relative, value, replace=True)
                else:
                    if digest(prior) != sha:
                        raise ContractError('HASH_MISMATCH', 'Interrupted ancillary payload differs.')
                self._verify(fs, project_id, pin, record)
                fs.write(path, record, replace=True)
        self._verify(fs, project_id, pin, record)
        return pin

    def publish_plan(self, project_id, plan):
        if plan['project_id'] != project_id:
            raise ContractError('WRONG_PROJECT', 'Plan owner differs.')
        return self.publish_json(project_id, plan)


class CaptionArtifacts:
    """Trusted local staging. Only a committed caption tx publishes records.

    Never installs a stand-alone record file: an interrupted/orphan payload is
    intentionally unresolvable through either registry. The content lock belongs
    to CaptionStore; this service cannot advance the project pointer.
    """
    def __init__(self, projects, *, catalog=None):
        self.projects = projects
        self.catalog = catalog or ArtifactCatalog(projects)
        self._staged = {}

    def verify(self, fs, pointer, pin):
        return self.catalog.resolve_at(fs, pointer, pin)

    def read_json(self, fs, pointer, pin):
        record = self.verify(fs, pointer, pin)
        with self.catalog.open_record(fs, record) as stream:
            return read_bounded_json(stream)

    def publish_json(self, fs, pointer, value, kind):
        if kind not in ('caption', 'report'):
            raise ContractError('INVALID_ARGUMENT', 'Caption staging supports captions and reports only.')
        if kind == 'caption':
            from .captions import validate_caption
            validate_caption(value)
        else:
            from .captions import check
            check(value, 'CaptionTimingDecision')
        payload = canonical(value)
        if len(payload) > 1024 * 1024:
            raise ContractError('LIMIT_EXCEEDED', 'Caption JSON exceeds 1 MiB.')
        aid, now = 'art_' + str(uuid.uuid4()), _now()
        relative = 'caption-outputs/' + aid + '/payload.json'
        inputs = []
        dependencies = ([value['source_audio'], value['source_transcript'], *value['timing_evidence'], *value['timing_decisions']]
                        if kind == 'caption' else [value['source_audio'], *value['evidence']])
        for dependency in dependencies:
            if dependency not in inputs:
                inputs.append(copy.deepcopy(dependency))
        record = {'schema':'motion/v1/artifact','artifact_id':aid,'project_id':pointer['project_id'],
                  'kind':kind,'media_type':'application/json','sha256':digest(value),'size_bytes':len(payload),
                  'storage':{'mode':'managed','relative_path':relative},'created_at':now,
                  'producer':{'job_id':None,'node_id':None,'attempt_id':None,'adapter_id':None},
                  'inputs':inputs, 'probe_receipt_id':None,
                  'provenance':{'origin':'authored','acquired_at':now,'source_locator':None,
                                'provider':None,'model':None,'model_version':None,'seed':None,
                                'deterministic':'yes','rights':{'status':'unknown','license':None,'attribution':None,'evidence':[]},
                                'notes':'Canonical caption metadata publication; no ASR, audition or timing approval asserted.'}}
        validate_asset(record, 'ArtifactRecord')
        fs.write(self.projects._base(pointer['project_id']) + '/' + relative, value)
        with self.catalog.assets.open_artifact(fs, record):
            pass
        self._staged[pointer['project_id'], aid] = copy.deepcopy(record)
        return {k:record[k] for k in ('artifact_id','sha256')}

    def staged_records(self, fs, pointer, pins):
        records = []
        for pin in pins:
            record = self._staged.get((pointer['project_id'],pin['artifact_id']))
            if record is None:
                raise ContractError('OUTPUT_UNAVAILABLE', 'Caption output has no trusted staged record.')
            self.catalog._verify(fs, pointer['project_id'], pin, record)
            records.append(copy.deepcopy(record))
        return records


def read_bounded_json(stream):
    """Shared strict decoder, including duplicate-key and nonfinite rejection."""
    import json
    raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ContractError('LIMIT_EXCEEDED', 'Artifact JSON exceeds 1 MiB.')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    def constant(value):
        raise ValueError('nonfinite JSON number')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ContractError('INVALID_ARGUMENT', 'Artifact must contain bounded strict UTF-8 JSON.') from None
