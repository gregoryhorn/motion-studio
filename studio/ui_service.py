"""Durable, closed ui.v1 facade.

Host integration contract
-------------------------
``UIService(root, native_registry, *, profile_id, backend_instance_id,
            connection_id='local', integrations=None)``
``handle(method, path, query=None, body=None, principal='host') -> (status, JSON)``

``integrations`` is a mapping of *exact OP-* names in ROUTES to trusted callables.
A callback is ``callback(context, input, preconditions) -> data`` or
``(http_status, data)``. No client-controlled callable/tool name is dispatched.
Context contains scope, principal, operation_id, command_id, idempotency_key,
request_sha256, public path parameters, composition/version (when present),
private_project_id, private_project_revision, project_store, and native_record.
The latter three objects are server-only. Callbacks MUST return public, redacted
ui.v1 projections, enforce target/entity/hash CAS and actual authority, use the
supplied frozen idempotency identity for owned submission, and never launch on
GET. A callback failure after an external effect MUST raise ContractError with
effect='pending' or 'unknown'. An unexpected exception is conservatively unknown.

Special trusted configuration keys: ``host_capabilities`` (plain dict),
``permissions`` (callable
(context, permission)->bool), ``templates`` (mapping schema hash -> graph), and
``settings_bindings`` (set of nonsecret binding IDs), and ``root_broker``
(parent-owned UIFileBroker with roots/browse methods), ``dependency_resolver``
((context, exact_dependency_hashes)->True only after actual closure validation).
They cannot be set by REST. Permission names are edit, policy_edit, promote,
human_review; absent policy/promote/human callbacks never grant authority.
A trusted OP-PROPOSALS callback supplies admitted proposals; renderer requests
cannot create proposals or report tool/approval/check results.

SQLite owns public versions/bindings/CAS, receipts, frozen command intents,
undo, snapshots and the event outbox. Connection is an assertion/transport label,
not storage ownership. A private ProjectStore is updated with compiled immutable
engine documents before the public head is published. A staged frozen graph and
deterministic ProjectStore request IDs make interrupted local publication
replayable. An external accepted intent is NEVER blindly submitted a second time;
its command status explicitly requires adapter reconciliation.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import unquote
import uuid
from typing import Any, NoReturn

from .contracts import ContractError, D, DIGEST, canonical, digest, empty_brief, validate
from .project import ProjectStore
from .ui_graph import init_graph, apply_operations, validate_graph, compile_graph, schema_catalog
from .build_identity import runtime_identity

API_VERSION = 'ui.v1'
MAX_SAFE = 9007199254740991
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
HASH_RE = re.compile(r'^[0-9a-f]{64}$')
PUBLIC_RE = re.compile(r'^[a-z][a-z0-9]*_[A-Za-z0-9_-]{8,96}$')
S = 'composition_revision version_id'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    # JCS property ordering is UTF-16 code units (not Python Unicode scalar
    # ordering). The supported numeric subset is integers, so no float printer.
    def ordered(item):
        if isinstance(item,dict):
            return {k:ordered(item[k]) for k in sorted(item,key=lambda k:k.encode('utf-16-be'))}
        if isinstance(item,list):
            return [ordered(v) for v in item]
        return item
    return hashlib.sha256(json.dumps(ordered(value),ensure_ascii=False,separators=(',', ':'),allow_nan=False).encode()).hexdigest()


def _public_data(value):
    """Keep immutable document bytes private to their authorized read route."""
    if isinstance(value,list):
        return [_public_data(item) for item in value]
    if not isinstance(value,dict):
        return value
    result = {key:_public_data(item) for key,item in value.items()}
    if value.get('schema_version') == 'composition.v1' and 'production_documents' in value:
        result['production_documents'] = [{key:item for key,item in doc.items() if key != 'value'}
                                          for doc in result['production_documents']]
        result['asset_refs'] = [{key:item for key,item in asset.items() if key != 'artifact'}
                                for asset in result.get('asset_refs',[])]
    return result


class _CommittedReplay(Exception):
    def __init__(self,status,response):
        self.status, self.response = status, response


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _later(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')


def _id(kind):
    return kind + '_' + uuid.uuid4().hex


def _fail(code, message, details=None, effect='none') -> NoReturn:
    raise ContractError(code, message, details or {}, effect=effect)


def _fields(value, required='', optional='', *, missing='INVALID_ARGUMENT'):
    if not isinstance(value, dict):
        _fail('INVALID_ARGUMENT', 'An object is required.')
    required, optional = set(required.split()), set(optional.split())
    absent = required - value.keys()
    if absent:
        _fail(missing, 'Required fields are missing.', {'fields': sorted(absent)})
    unknown = value.keys() - required - optional
    if unknown:
        _fail('INVALID_ARGUMENT', 'Unknown fields are not accepted.', {'fields': sorted(unknown)})


def _integer(value, minimum=1, maximum=MAX_SAFE):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail('INVALID_ARGUMENT', 'A bounded safe integer is required.')
    return value


def _bool(value):
    if type(value) is not bool:
        _fail('INVALID_ARGUMENT', 'An explicit boolean is required.')
    return value


def _name(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 120:
        _fail('NAME_INVALID', 'Name must be trimmed, nonempty and at most 120 characters.')
    return value


def _uuid(value):
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        _fail('INVALID_ARGUMENT', 'A lowercase UUID is required.')
    return value


def _safe_json(value):
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            _fail('INVALID_ARGUMENT', 'Object keys must be strings.')
        for item in value.values():
            _safe_json(item)
    elif isinstance(value, list):
        for item in value:
            _safe_json(item)
    elif type(value) is int:
        _integer(value, -MAX_SAFE)
    elif type(value) is str:
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            _fail('INVALID_ARGUMENT','Lone UTF-16 surrogates are not canonical JSON text.')
    elif value is not None and type(value) not in (str, bool):
        _fail('INVALID_ARGUMENT', 'JSON values must use safe integers, not floating point.')


# Finite adapter routes. Required preconditions and fields are deliberately
# declared here rather than forwarding arbitrary engine dispatch payloads.
# pattern, method, operation, preconditions, input fields / read query fields
ROUTES = []


def _route(method, pattern, operation, pre='', fields='', optional=''):
    ROUTES.append((method, re.compile('^' + pattern + '$'), operation, pre, fields, optional))


P = r'/projects/(?P<native_project_id>[^/]+)'
C = P + r'/compositions/(?P<composition_id>[^/]+)'
_route('GET', '/bootstrap', 'OP-BOOTSTRAP', fields='client_contract client_kind', optional='known_etag connection_id')
_route('GET', '/projects', 'OP-PROJECTS', fields='include_archived', optional='limit cursor')
_route('GET', P + '/context', 'OP-PROJECT-CONTEXT', optional='known_etag')
_route('GET', P + '/compositions', 'OP-COMPOSITIONS', fields='include_archived', optional='limit cursor')
_route('POST', P + '/compositions', 'OP-COMPOSITION-CREATE', 'catalog_revision', 'name format template_ref', 'render_recipe')
_route('GET', C, 'OP-COMPOSITION-GET', optional='version_id known_etag')
_route('GET', C + '/documents/(?P<document_id>[^/]+)', 'OP-DOCUMENT-GET', fields='version_id')
_route('POST', C + '/duplicate', 'OP-COMPOSITION-DUPLICATE', S + ' catalog_revision', 'source_version_id name include_rights_assertions')
_route('POST', C + '/metadata', 'OP-COMPOSITION-METADATA', 'metadata_revision', 'name')
_route('POST', C + '/archive', 'OP-COMPOSITION-ARCHIVE', 'metadata_revision catalog_revision', 'archived acknowledge_running_jobs')
_route('POST', C + '/transactions', 'OP-TRANSACTION', S, 'operations gesture_id summary dependency_policy acknowledged_dependency_ids', 'asset_refs render_recipe')
_route('POST', C + '/undo', 'OP-UNDO', S, 'undo_token direction')
_route('GET', C + '/recovery', 'OP-RECOVERY', fields='pending_command_ids known_version_id', optional='client_journal_sha256')
_route('POST', C + '/recover', 'OP-RECOVER-VERSION', S, 'source_version_id reason acknowledge_invalidations')
_route('POST', C + '/recovery-review', 'OP-RECOVERY-REVIEW', S + ' catalog_revision', 'review')
_route('POST', C + '/recover-as-new', 'OP-RECOVER-AS-NEW', S + ' catalog_revision', 'name review review_token')
_route('POST', C + '/assets/(?P<asset_id>[^/]+)/probe', 'OP-ASSET-PROBE', S + ' entity_revision', 'asset_version_id sha256 full_decode')
_route('POST', C + '/assets/(?P<asset_id>[^/]+)/bind', 'OP-ASSET-BIND', S + ' entity_revision', 'asset_version_id sha256 receipt_id stream_index')
_route('GET', P + '/roots/(?P<root_id>[^/]+)/entries', 'OP-ROOT-BROWSE', fields='parent_node_id expected_root_revision kind_filter', optional='limit cursor')
_route('POST', P + '/import-scans', 'OP-IMPORT-SCAN', 'root_revisions', 'selections recursive filters max_files max_bytes symlink_policy')
_route('POST', P + '/discovery', 'OP-DISCOVERY-SCAN', 'root_revisions', 'max_entries max_directories', 'cursor')
_route('GET', P + '/discovery', 'OP-DISCOVERY-STATUS', optional='limit cursor')
_route('GET', P + '/import-scans/(?P<scan_id>[^/]+)', 'OP-IMPORT-MANIFEST', fields='status_filter', optional='limit cursor')
_route('POST', P + '/imports', 'OP-IMPORT-COMMIT', 'manifest_sha256', 'manifest_id entry_ids copy_policy dedup_policy allow_partial_manifest rights_assertions target_composition_id')
_route('POST', P + '/uploads', 'OP-UPLOAD-CREATE', 'quota_revision', 'display_name byte_length declared_mime total_sha256 chunk_size source_kind relative_display_name')
_route('GET', P + '/uploads/(?P<upload_id>[^/]+)', 'OP-UPLOAD-STATUS')
_route('PUT', P + '/uploads/(?P<upload_id>[^/]+)/chunks/(?P<chunk_index>[^/]+)', 'OP-UPLOAD-CHUNK',
       'entity_revision', 'content_length content_range digest sha256')
_route('POST', P + '/uploads/(?P<upload_id>[^/]+)/commit', 'OP-UPLOAD-COMMIT', 'entity_revision', 'total_sha256 byte_length rights_assertions')
_route('POST', P + '/uploads/(?P<upload_id>[^/]+)/abort', 'OP-UPLOAD-ABORT', 'entity_revision', 'reason')
_route('GET', P + '/assets', 'OP-ASSETS', optional='composition_id kind readiness search limit cursor')
_route('GET', P + '/assets/(?P<asset_id>[^/]+)', 'OP-ASSET', optional='asset_version_id known_etag')
_route('POST', P + '/assets/(?P<asset_id>[^/]+)/rights', 'OP-ASSET-RIGHTS', 'entity_revision', 'assertions replace_assertion_ids')
_route('POST', P + '/assets/(?P<asset_id>[^/]+)/derivatives', 'OP-DERIVATIVE', 'asset_version_id asset_sha256', 'kind recipe_ref frame_range resolution tile_size')
_route('POST', P + '/media-access', 'OP-MEDIA-ACCESS', 'media_sha256', 'media_id purpose transport requested_ttl_seconds')
_route('GET', P + '/media-access/(?P<access_id>[^/]+)/chunks', 'OP-MEDIA-CHUNK', fields='offset length')
_route('GET', '/capabilities', 'OP-CAPABILITIES', fields='mode', optional='operation composition_id native_project_id version_id limit cursor')
_route('GET', '/settings', 'OP-SETTINGS-GET', optional='known_etag')
_route('POST', '/settings', 'OP-SETTINGS-SAVE', 'settings_revision', 'preferences')
_route('POST', C + '/handoffs', 'OP-HANDOFF-PREPARE', S, 'intent operation_schema_ref selected_entity_ids parameters expected_effects rationale')
_route('GET', C + '/handoffs/(?P<handoff_id>[^/]+)', 'OP-HANDOFF-STATUS')
_route('GET', C + '/proposals', 'OP-PROPOSALS', fields='state', optional='limit cursor')
_route('GET', C + '/proposals/(?P<proposal_id>[^/]+)', 'OP-PROPOSAL-GET')
_route('POST', C + '/proposals/(?P<proposal_id>[^/]+)/decision', 'OP-PROPOSAL-DECIDE', S + ' entity_revision', 'decision proposal_sha256 reason acknowledged_dependency_ids')
_route('POST', C + '/authority-requests', 'OP-AUTHORITY-REQUEST', S, 'kind subject_refs subject_sha256 purpose limits reason')
_route('GET', C + '/authority-requests/(?P<authority_request_id>[^/]+)', 'OP-AUTHORITY-STATUS')
_route('POST', C + '/preflights', 'OP-PREFLIGHT', S, 'action recipe_ref parameters dependency_hashes probe_policy acknowledged_effects')
_route('GET', C + '/preflights/(?P<preflight_id>[^/]+)', 'OP-PREFLIGHT-GET')
_route('POST', C + '/preflights/(?P<preflight_id>[^/]+)/approval-requests', 'OP-APPROVAL-REQUEST', 'preflight_sha256', 'plan_sha256 effects_sha256 approval_kind reason')
_route('GET', C + '/approval-requests/(?P<approval_request_id>[^/]+)', 'OP-APPROVAL-STATUS')
_route('POST', C + '/jobs', 'OP-JOB-LAUNCH', S, 'preflight_id plan_id plan_sha256 effects_sha256 approval_refs client_intent')
_route('GET', P + '/jobs', 'OP-JOBS', optional='composition_id state kind limit cursor')
_route('GET', P + '/jobs/(?P<job_id>[^/]+)', 'OP-JOB-GET', optional='known_entity_revision')
_route('POST', P + '/jobs/(?P<job_id>[^/]+)/cancel', 'OP-JOB-CANCEL', 'entity_revision', 'reason mode')
_route('GET', P + '/jobs/(?P<job_id>[^/]+)/checkpoints', 'OP-CHECKPOINTS', optional='limit cursor')
_route('POST', P + '/jobs/(?P<job_id>[^/]+)/recovery', 'OP-JOB-RECOVER', 'entity_revision', 'action checkpoint_id checkpoint_sha256 approval_refs acknowledge_unknown_effects')
_route('POST', C + '/render-snapshots', 'OP-RENDER-PREPARE', S, 'preflight_id recipe_ref deliverable_profiles range quality dependency_hashes')
_route('GET', C + '/render-snapshots/(?P<snapshot_id>[^/]+)', 'OP-RENDER-SNAPSHOT-GET')
_route('POST', C + '/renders', 'OP-RENDER-LAUNCH', 'snapshot_id snapshot_sha256', 'approval_refs acknowledge_older_head')
_route('GET', C + '/candidates', 'OP-CANDIDATES', optional='snapshot_id job_id limit cursor')
_route('GET', C + '/candidates/(?P<candidate_id>[^/]+)', 'OP-CANDIDATE-GET')
_route('GET', C + '/candidates/(?P<candidate_id>[^/]+)/reviews', 'OP-REVIEWS', optional='limit cursor')
_route('POST', C + '/candidates/(?P<candidate_id>[^/]+)/reviews', 'OP-REVIEW-RECORD', 'candidate_sha256 gate_revision', 'gate_ref review_kind coverage findings decision evidence_refs check_recipe_ref')
_route('POST', C + '/candidates/(?P<candidate_id>[^/]+)/checks', 'OP-CANDIDATE-CHECK', 'candidate_sha256 gate_revision', 'gate_refs recipe_ref parameters preflight_id approval_refs')
_route('POST', C + '/masters', 'OP-MASTER-PROMOTE', 'candidate_sha256 gate_revision expected_master_revision', 'candidate_id variant_id profile_ref selected_file_ids required_gate_refs review_refs')
_route('GET', C + '/masters', 'OP-MASTERS', optional='variant_id limit cursor')
_route('GET', C + '/masters/(?P<master_id>[^/]+)', 'OP-MASTER-GET', fields='master_revision')
_route('POST', C + '/packages', 'OP-PACKAGE-CREATE', S, 'master_refs sidecar_file_ids format include_source source_refs reconstruct recipe_ref preflight_id approval_refs')
_route('GET', C + '/packages', 'OP-PACKAGES', optional='state limit cursor')
_route('GET', C + '/packages/(?P<package_id>[^/]+)', 'OP-PACKAGE-GET')
_route('POST', C + '/packages/(?P<package_id>[^/]+)/checks', 'OP-PACKAGE-VALIDATE', 'entity_revision manifest_sha256', 'recipe_ref preflight_id approval_refs')
_route('POST', C + '/delivery-sets', 'OP-DELIVERY-SET-CREATE', 'candidate_sha256 gate_revision', 'candidate_id requested_items selected_file_ids required_gate_refs omissions destination_kind destination_id')
_route('GET', C + '/delivery-sets', 'OP-DELIVERY-SETS', optional='candidate_id state limit cursor')
_route('GET', C + '/delivery-sets/(?P<delivery_set_id>[^/]+)', 'OP-DELIVERY-SET-GET')
_route('POST', C + '/delivery-sets/(?P<delivery_set_id>[^/]+)/transfers', 'OP-DELIVERY-START', 'entity_revision manifest_sha256 gate_revision', 'file_ids approval_refs mode acknowledge_partial_set')
_route('POST', C + '/delivery-sets/(?P<delivery_set_id>[^/]+)/recovery', 'OP-DELIVERY-RECONCILE', 'entity_revision', 'action file_ids prior_transfer_ids approval_refs')
_route('GET', P + '/receipts/(?P<receipt_id>[^/]+)', 'OP-RECEIPT')
_route('GET', P + '/events', 'OP-EVENT-POLL', fields='after_cursor wait_ms', optional='limit composition_id')
_route('GET', '/commands/(?P<command_id>[^/]+)', 'OP-COMMAND-STATUS', fields='scope request_sha256')

LOCAL_COMMANDS = {'OP-COMPOSITION-CREATE', 'OP-COMPOSITION-DUPLICATE', 'OP-COMPOSITION-METADATA',
                  'OP-COMPOSITION-ARCHIVE', 'OP-TRANSACTION', 'OP-UNDO', 'OP-RECOVER-VERSION',
                  'OP-SETTINGS-SAVE', 'OP-PROPOSAL-DECIDE', 'OP-RECOVERY-REVIEW', 'OP-RECOVER-AS-NEW', 'OP-ASSET-BIND'}
COLLECTIONS = {'OP-ASSETS', 'OP-JOBS', 'OP-CANDIDATES', 'OP-MASTERS', 'OP-PACKAGES',
               'OP-DELIVERY-SETS', 'OP-REVIEWS', 'OP-CHECKPOINTS'}
BUILTIN_READS = {'OP-BOOTSTRAP','OP-PROJECTS','OP-PROJECT-CONTEXT','OP-COMPOSITIONS',
                 'OP-COMPOSITION-GET','OP-DOCUMENT-GET','OP-RECOVERY','OP-CAPABILITIES','OP-SETTINGS-GET',
                 'OP-PROPOSALS','OP-PROPOSAL-GET','OP-JOBS','OP-JOB-GET','OP-CHECKPOINTS',
                 'OP-RECEIPT','OP-EVENT-POLL','OP-COMMAND-STATUS'}


class UIService:
    def __init__(self, root, native_registry, *, profile_id, backend_instance_id,
                 connection_id='local', integrations=None):
        if not callable(native_registry):
            raise ValueError('native_registry must be callable')
        for value in (profile_id, backend_instance_id, connection_id):
            if not isinstance(value, str) or not value:
                raise ValueError('host identity must be resolved')
        self.root = Path(root)
        self.native_registry = native_registry
        self.profile_id, self.backend_instance_id = profile_id, backend_instance_id
        self.connection_id = connection_id
        self.integrations = dict(integrations or {})
        media = self.integrations.get('_media_store')
        if media is not None:
            from .ui_sqlite import database_backend
            media.bind_database(database_backend)
        # Root may be shared by several authenticated profiles. Never allow an
        # assertion or connection alias to choose another profile's store.
        self.owner = _hash([backend_instance_id, profile_id])
        self.directory = self.root / 'ui-v1' / self.owner
        self.database = self.directory / 'metadata.sqlite3'
        self.store = ProjectStore(root=self.directory / 'engine')
        execution = self.integrations.get('_execution_adapter')
        if execution is not None:
            execution.bind_graph_renderer(self._build_graph_plan)

    def _connect(self):
        from .ui_sqlite import open_owned
        db = open_owned(self.directory, 'metadata.sqlite3')
        try:
            return self._initialize_database(db)
        except BaseException:
            db.close()
            raise

    @staticmethod
    def _initialize_database(db):
        db.executescript('''
        CREATE TABLE IF NOT EXISTS catalogs(native TEXT PRIMARY KEY,revision INTEGER NOT NULL,epoch TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS compositions(id TEXT PRIMARY KEY,native TEXT NOT NULL,name TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,metadata_revision INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL,head TEXT NOT NULL,private_id TEXT NOT NULL UNIQUE,private_revision INTEGER NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,composition TEXT NOT NULL,revision INTEGER NOT NULL,parent TEXT,sha TEXT NOT NULL,value TEXT NOT NULL,private_revision INTEGER NOT NULL,compiled_sha TEXT NOT NULL,UNIQUE(composition,revision));
        CREATE TABLE IF NOT EXISTS commands(command_id TEXT NOT NULL,principal TEXT NOT NULL,native TEXT NOT NULL,operation TEXT NOT NULL,idem TEXT NOT NULL,request_sha TEXT NOT NULL,scope TEXT NOT NULL,path TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL,effect TEXT NOT NULL,receipt TEXT,response TEXT,http_status INTEGER,work TEXT,created TEXT NOT NULL,expires TEXT NOT NULL,PRIMARY KEY(principal,native,command_id),UNIQUE(principal,native,operation,idem));
        CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,native TEXT NOT NULL,principal TEXT NOT NULL,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,native TEXT NOT NULL,value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_native ON events(native,sequence);
        CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,principal TEXT NOT NULL,native TEXT NOT NULL,binding TEXT NOT NULL,value TEXT NOT NULL,expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cursors(id TEXT PRIMARY KEY,principal TEXT NOT NULL,native TEXT NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL,expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS undo(id TEXT PRIMARY KEY,native TEXT NOT NULL,composition TEXT NOT NULL,principal TEXT NOT NULL,base TEXT NOT NULL,target TEXT NOT NULL,direction TEXT NOT NULL,expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,native TEXT NOT NULL,composition TEXT NOT NULL,value TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS resources(kind TEXT NOT NULL,id TEXT NOT NULL,native TEXT NOT NULL,composition TEXT NOT NULL,principal TEXT NOT NULL,value TEXT NOT NULL,observed TEXT NOT NULL,PRIMARY KEY(kind,id,native,composition));
        CREATE TABLE IF NOT EXISTS recovery_reviews(id TEXT PRIMARY KEY,principal TEXT NOT NULL,native TEXT NOT NULL,composition TEXT NOT NULL,scope TEXT NOT NULL,review_sha TEXT NOT NULL,review TEXT NOT NULL,catalog_revision INTEGER NOT NULL,expires TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS canonical_sources(version TEXT PRIMARY KEY,artifact TEXT NOT NULL,closure TEXT NOT NULL,private_revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS retained_documents(composition TEXT NOT NULL,pin_sha TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(composition,pin_sha));
        ''')
        return db

    @staticmethod
    def request_hash(operation_id, path, body):
        """Normative frozen-intent digest; transport/command/key IDs excluded."""
        return _hash(dict(operation_id=operation_id,route=path,scope=body['scope'],
                          preconditions=body['preconditions'],input=body['input']))

    def resolve_binding(self, native_project_id, composition_id, *, version_id=None, principal='host') -> dict[str, Any]:
        """Server-only exact ownership/version lookup; never expose as JSON.

        This method accepts no profile/storage/credential override. Host code
        may use it to wire real plan/job/media/review services to this saved
        composition. Returns the actual ProjectStore instance and its immutable
        pinned revision, not the currently mutated engine head.
        """
        self._native(native_project_id)
        if not isinstance(principal,str) or not principal:
            _fail('AUTH_REQUIRED','Authenticated host principal is required.')
        db = self._connect()
        try:
            comp = self._composition(db,native_project_id,composition_id)
            version = self._version(db,comp,version_id)
            row = db.execute('SELECT private_revision,compiled_sha FROM versions WHERE id=?',(version['version_id'],)).fetchone()
            context = dict(scope=self._scope(native_project_id),principal=principal,params=dict(native_project_id=native_project_id,composition_id=composition_id))
            if not self._permission(context,'edit'):
                _fail('PERMISSION_DENIED','The host principal cannot resolve this production binding.')
            return dict(scope=context['scope'],composition_id=composition_id,version_id=version['version_id'],
                        version=version,composition=self._summary(db,comp),project_store=self.store,
                        private_project_id=comp['private_id'],source_private_project_revision=row['private_revision'],
                        private_project_revision=self._authoritative_revision(comp['private_id'],row['private_revision']),
                        compiled_sha256=row['compiled_sha'])
        finally:
            db.close()

    def _scope(self, native=None):
        result = dict(backend_instance_id=self.backend_instance_id, connection_id=self.connection_id,
                      profile_id=self.profile_id)
        if native is not None:
            result['native_project_id'] = native
        return result

    def _assert_scope(self, scope, native=None):
        if not isinstance(scope, dict) or scope != self._scope(native):
            _fail('SCOPE_MISMATCH', 'The asserted scope does not match authenticated host context.')

    def _registry(self):
        try:
            records = self.native_registry()
        except Exception:
            _fail('NATIVE_REGISTRY_UNAVAILABLE', 'The authenticated native registry is unavailable.')
        if not isinstance(records, list):
            _fail('NATIVE_REGISTRY_UNAVAILABLE', 'Native registry returned no authoritative list.')
        result = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not record['id'] or not isinstance(record.get('name'), str) or type(record.get('archived')) is not bool or not isinstance(record.get('folders'), list):
                _fail('NATIVE_REGISTRY_UNAVAILABLE', 'Native immutable identity or folder metadata is incomplete.')
            if record['id'] in result:
                _fail('NATIVE_REGISTRY_UNAVAILABLE', 'Native immutable identities are not unique.')
            result[record['id']] = record
        return result

    def _native(self, native):
        records = self._registry()
        if native not in records:
            _fail('NOT_FOUND', 'Project not found in authenticated native registry.')
        return records[native]

    def _roots(self, record):
        broker = self.integrations.get('root_broker')
        if broker is not None:
            payload = broker.roots(record['id'])
            return [dict(root_id=r['root_id'],label=r.get('label',r.get('name','Project folder')),
                         primary=r['primary'],root_revision=r['root_revision'],available=r['available'],reason=r['reason'])
                    for r in payload['items']]
        result = []
        for index, folder in enumerate(record['folders']):
            # Folder identity and revision pin exact host membership; never
            # expose or accept its path as an API capability.
            token = _hash([record['id'], folder])
            label = folder.get('label', folder.get('name')) if isinstance(folder, dict) else None
            result.append(dict(root_id='root_' + token[:32], label=label or ('Project folder ' + str(index + 1)),
                               primary=index == 0, root_revision=token, available=False, reason='ROOT_ADAPTER_UNAVAILABLE'))
        return result

    def _native_public(self, record):
        return dict(native_project_id=record['id'], name=record['name'], slug=record.get('slug'),
                    archived=record['archived'], native_revision=_hash(record), roots=self._roots(record))

    def _catalog(self, db, native) -> dict[str, Any]:
        row = db.execute('SELECT * FROM catalogs WHERE native=?', (native,)).fetchone()
        return dict(row) if row else dict(native=native, revision=1, epoch='epoch_' + _hash([self.owner, native])[:32])

    def _bump_catalog(self, db, native):
        cat = self._catalog(db, native)
        db.execute('INSERT INTO catalogs(native,revision,epoch) VALUES(?,?,?) ON CONFLICT(native) DO UPDATE SET revision=excluded.revision', (native, cat['revision'] + 1, cat['epoch']))
        return cat['revision'] + 1

    def _composition(self, db, native, cid):
        row = db.execute('SELECT * FROM compositions WHERE id=? AND native=?', (cid, native)).fetchone()
        if not row:
            _fail('NOT_FOUND', 'Composition not found.')
        return dict(row)

    def _version(self, db, composition, vid=None):
        row = db.execute('SELECT * FROM versions WHERE id=? AND composition=?', (vid or composition['head'], composition['id'])).fetchone()
        if not row:
            _fail('NOT_FOUND', 'Saved version not found.')
        return json.loads(row['value'])

    def _summary(self, db, composition):
        version = self._version(db, composition)
        return dict(composition_id=composition['id'], native_project_id=composition['native'],
                    name=composition['name'], archived=bool(composition['archived']),
                    metadata_revision=composition['metadata_revision'], composition_revision=composition['revision'],
                    head_version_id=composition['head'], head_sha256=version['sha256'], format=version['format'],
                    created_at=composition['created'], updated_at=composition['updated'])

    def _fresh(self, scope, data, db, command=None):
        observed = _now()
        envelope: dict[str, Any] = dict(api_version=API_VERSION, request_id=_id('req'), scope=scope, data=_public_data(data),
                        meta=dict(observed_at=observed, event_cursor=self._event_cursor(db, scope.get('native_project_id')),
                                  freshness=dict(kind='live', observed_at=observed, expires_at=None), warnings=[]))
        if command:
            envelope['command'] = command
        if isinstance(data,dict) and data.get('observation',{}).get('kind')=='cached':
            envelope['meta']['freshness'] = dict(kind='cached',observed_at=data['observation']['observed_at'],expires_at=None)
        return envelope

    def _error(self, scope, error):
        codes = {'AUTH_REQUIRED':401, 'PERMISSION_DENIED':403, 'PROJECT_ARCHIVED':403,
                 'NOT_FOUND':404, 'PRECONDITION_REQUIRED':428, 'LIMIT_EXCEEDED':413,
                 'STORAGE_FULL':507, 'INVALID_ARGUMENT':400, 'SCOPE_MISMATCH':400,
                 'CONTRACT_INCOMPATIBLE':409, 'REVISION_CONFLICT':409,
                 'RANGE_INVALID':416, 'CHUNK_MISMATCH':409, 'UPLOAD_SEALED':409,
                 'UPLOAD_EXPIRED':410, 'DIGEST_MISMATCH':422,
                 'IDEMPOTENCY_MISMATCH':409, 'COMMAND_HASH_MISMATCH':409,
                 'UNDO_CONFLICT':409, 'ACTIVE_JOBS':409, 'PROPOSAL_STALE':409,
                 'PROPOSAL_ALREADY_DECIDED':409, 'INVALIDATIONS_NOT_ACKNOWLEDGED':409,
                 'BACKEND_UNAVAILABLE':503, 'NATIVE_REGISTRY_UNAVAILABLE':503,
                 'APPROVAL_BRIDGE_UNAVAILABLE':503, 'INTEGRATION_UNAVAILABLE':503,
                 'HOST_TRANSPORT_REQUIRED':503, 'EVENT_GAP':410,
                 'RECOVERY_SOURCE_UNAVAILABLE':422,'SOURCE_UNAVAILABLE':422,
                 'FONT_UNAVAILABLE':422,'TEMPLATE_UNAVAILABLE':422,
                 'SOURCE_CHANGED':409,'PREFLIGHT_STALE':409,'AUTHORITY_REQUIRED':409,
                 'DEPENDENCY_CHANGED':409,'ROOT_CHANGED':409,'GATES_STALE':409,
                 'MASTER_CONFLICT':409,'PROPOSAL_EXPIRED':410}
        code = error.code
        status = codes.get(code, 410 if code.endswith(('EXPIRED', 'UNAVAILABLE')) else 422)
        details = error.details if isinstance(error.details, dict) else {}
        # Errors produced by engine modules are not safe public projections.
        details = {k:v for k,v in details.items() if k in {'fields','field','entity_id','frame_range','expected','current','composition_revision','version_id','conflict_token','operation_id','blockers','recovery_actions','retry_after_ms','earliest_cursor','stream_epoch','actual_revision','expected_revision','reason'}}
        effect = error.effect if error.effect in ('none','committed','pending','unknown') else 'unknown'
        return status, dict(api_version=API_VERSION, request_id=_id('req'), scope=scope,
                            error=dict(code=code, message=error.message, retryable=status in (429,503),
                                       effect_state=effect, details=details, recovery_actions=details.pop('recovery_actions', [])))

    def _validate_values(self, operation, value, *, read=False):
        """Closed route shapes plus common scalar/enum/nested data constraints.

        Adapter-specific recipes, schema pins and actual dependency closure are
        validated by that finite adapter before it writes/submits anything.
        """
        if 'limit' in value:
            _integer(value['limit'],1,200)
        if 'cursor' in value and (not isinstance(value['cursor'],str) or not value['cursor']):
            _fail('INVALID_ARGUMENT','Cursor must be a nonempty opaque string.')
        if 'search' in value and (not isinstance(value['search'],str) or len(value['search'])>200):
            _fail('INVALID_ARGUMENT','Search is literal display text of at most 200 characters.')
        boolean_fields = {'include_archived','archived','acknowledge_running_jobs','include_rights_assertions',
                          'recursive','allow_partial_manifest','acknowledge_invalidations','acknowledge_unknown_effects',
                          'acknowledge_older_head','include_source','reconstruct','acknowledge_partial_set'}
        array_fields = {'operations','acknowledged_dependency_ids','pending_command_ids','selections','entry_ids',
                        'rights_assertions','assertions','replace_assertion_ids','selected_entity_ids','expected_effects',
                        'subject_refs','dependency_hashes','acknowledged_effects','approval_refs','deliverable_profiles',
                        'coverage','findings','evidence_refs','gate_refs','selected_file_ids','required_gate_refs',
                        'review_refs','master_refs','sidecar_file_ids','source_refs','requested_items','omissions',
                        'file_ids','prior_transfer_ids'}
        for key in boolean_fields.intersection(value):
            _bool(value[key])
        for key in array_fields.intersection(value):
            if not isinstance(value[key],list) or len(value[key])>10000:
                _fail('INVALID_ARGUMENT','A bounded explicit array is required.',{'field':key})
        for key,item in value.items():
            if key.endswith('sha256') and item is not None and (not isinstance(item,str) or not HASH_RE.fullmatch(item)):
                _fail('INVALID_ARGUMENT','A lowercase SHA-256 is required.',{'field':key})
        enums = {
            ('OP-ROOT-BROWSE','kind_filter'):{'all','media','directory'},
            ('OP-IMPORT-MANIFEST','status_filter'):{'all','eligible','excluded','failed'},
            ('OP-IMPORT-SCAN','symlink_policy'):{'deny'},
            ('OP-IMPORT-COMMIT','copy_policy'):{'managed_immutable_copy'},
            ('OP-IMPORT-COMMIT','dedup_policy'):{'reuse_authorized_hash'},
            ('OP-UPLOAD-CREATE','source_kind'):{'client_file'},
            ('OP-DERIVATIVE','kind'):{'thumbnail','waveform','proxy'},
            ('OP-MEDIA-ACCESS','purpose'):{'preview','review','download'},
            ('OP-MEDIA-ACCESS','transport'):{'host_stream','same_origin_cookie','authenticated_blob'},
            ('OP-HANDOFF-PREPARE','intent'):{'scene_generate','caption_generate','audio_process','capability_setup','diagnose','acquire_media'},
            ('OP-AUTHORITY-REQUEST','kind'):{'creative_acceptance','run_permission','reference_voice_use'},
            ('OP-APPROVAL-REQUEST','approval_kind'):{'host_policy'},
            ('OP-PREFLIGHT','action'):{'render','analyze','caption','audio_process','candidate_check','package','package_check'},
            ('OP-PREFLIGHT','probe_policy'):{'cached_only','explicit_bounded_probe'},
            ('OP-JOB-LAUNCH','client_intent'):{'launch_exact_saved_version'},
            ('OP-JOB-CANCEL','mode'):{'best_effort_owned'},
            ('OP-JOB-RECOVER','action'):{'reconcile','resume_checkpoint','collect','abandon'},
            ('OP-RENDER-PREPARE','quality'):{'preview','master'},
            ('OP-REVIEW-RECORD','review_kind'):{'human_editorial','measured_check'},
            ('OP-REVIEW-RECORD','decision'):{'pass','fail','needs_changes'},
            ('OP-PACKAGE-CREATE','format'):{'zip','tar'},
            ('OP-DELIVERY-SET-CREATE','destination_kind'):{'client_download','approved_destination'},
            ('OP-DELIVERY-START','mode'):{'download','external_transfer'},
            ('OP-DELIVERY-RECONCILE','action'):{'reconcile','retry_unresolved'},
            ('OP-PROPOSALS','state'):{'pending','applied','rejected','stale','all'},
        }
        for (op,key),allowed in enums.items():
            if operation==op and key in value and (not isinstance(value[key],str) or value[key] not in allowed):
                _fail('INVALID_ARGUMENT','Unsupported finite option.',{'field':key})
        if operation=='OP-AUTHORITY-REQUEST':
            _fields(value['limits'],'operation_schema_ref asset_ids destination_ids expires_at')
        if operation=='OP-IMPORT-SCAN':
            _fields(value['filters'],'kinds extensions include_hidden')
            _bool(value['filters']['include_hidden'])
            for row in value['selections']:
                _fields(row,'root_id node_id')
        if operation=='OP-RENDER-PREPARE':
            _fields(value['range'],'start_frame end_frame')
            start = _integer(value['range']['start_frame'],0)
            end = _integer(value['range']['end_frame'],1)
            if start>=end:
                _fail('TIMING_INVALID','Render range must have positive exclusive duration.')
        if operation == 'OP-MEDIA-CHUNK':
            _integer(value['offset'], 0)
            _integer(value['length'], 1, 262144)
        if operation == 'OP-UPLOAD-CHUNK':
            _integer(value['content_length'], 1, 4 * 1024 * 1024)
            if not isinstance(value['content_range'], str) or not re.fullmatch(
                    r'bytes [0-9]{1,16}-[0-9]{1,16}/[0-9]{1,16}', value['content_range']):
                _fail('INVALID_ARGUMENT', 'A bounded explicit content range is required.')
            if not isinstance(value['digest'], str) or not re.fullmatch(r'[A-Za-z0-9+/]{43}=', value['digest']):
                _fail('INVALID_ARGUMENT', 'A base64 SHA-256 digest without an algorithm prefix is required.')
        for key in ('byte_length','chunk_size','requested_ttl_seconds','max_files','max_bytes'):
            if key in value:
                _integer(value[key])

    def handle(self, method, path, query=None, body=None, principal='host', *, host_context=None):
        """Resolve one finite route. Authentication/identity comes only from host."""
        db = None
        scope = self._scope()
        try:
            if not isinstance(principal, str) or not principal:
                _fail('AUTH_REQUIRED', 'An authenticated host principal is required.')
            if not isinstance(path, str) or '?' in path or not path.startswith('/'):
                _fail('INVALID_ARGUMENT', 'A relative facade path without query string is required.')
            method = method.upper()
            route = next(((match, op, pre, fields, optional) for verb, pattern, op, pre, fields, optional in ROUTES
                          if verb == method and (match := pattern.fullmatch(path))), None)
            if route is None:
                # Binary bytes never travel through a JSON facade.
                if '/chunks/' in path or path.endswith('/bytes'):
                    _fail('HOST_TRANSPORT_REQUIRED', 'Use the authenticated host binary/range transport, not JSON REST.')
                _fail('NOT_FOUND', 'No such ui.v1 operation.')
            match, op, pre, fields, optional = route
            params: dict[str, Any] = {k: unquote(v) for k,v in match.groupdict().items()}
            for key, value in params.items():
                if key == 'chunk_index':
                    if not re.fullmatch(r'(?:0|[1-9][0-9]{0,15})', value):
                        _fail('INVALID_ARGUMENT', 'Chunk index must be a bounded canonical nonnegative integer.')
                    _integer(int(value), 0)
                elif key not in ('native_project_id','command_id') and not PUBLIC_RE.fullmatch(value):
                    _fail('NOT_FOUND', 'Resource not found.')
            native = params.get('native_project_id')
            scope = self._scope(native)
            query = {} if query is None else query
            _safe_json(query)
            if method == 'GET':
                _fields(query, fields, optional)
                self._validate_values(op,query,read=True)
                if body is not None:
                    _fail('INVALID_ARGUMENT', 'Read requests have no JSON body.')
                if op == 'OP-CAPABILITIES' and query.get('native_project_id') is not None:
                    native = query['native_project_id']
                    scope = self._scope(native)
                if op == 'OP-COMMAND-STATUS':
                    candidate_scope = query['scope']
                    native = candidate_scope.get('native_project_id') if isinstance(candidate_scope, dict) else None
                    self._assert_scope(candidate_scope, native)
                    scope = self._scope(native)
            else:
                if query:
                    _fail('INVALID_ARGUMENT', 'Commands do not accept query fields.')
                _fields(body, 'scope command_id idempotency_key preconditions input')
                _safe_json(body)
                self._assert_scope(body['scope'], native)
                _uuid(body['command_id']); _uuid(body['idempotency_key'])
                _fields(body['preconditions'], pre, missing='PRECONDITION_REQUIRED')
                _fields(body['input'], fields, optional)
                self._validate_values(op,body['input'])
                for key, value in body['preconditions'].items():
                    if key.endswith('revision'):
                        _integer(value, 0 if key == 'expected_master_revision' else 1)
                    if key.endswith('sha256') and (not isinstance(value, str) or not HASH_RE.fullmatch(value)):
                        _fail('INVALID_ARGUMENT', 'A lowercase SHA-256 is required.', {'field': key})
                if len(_json(body).encode()) > 1048576:
                    _fail('LIMIT_EXCEEDED', 'Transaction request exceeds one MiB.')
            binary_chunk = None
            if op == 'OP-UPLOAD-CHUNK':
                if not isinstance(body, dict):
                    _fail('INVALID_ARGUMENT', 'Binary upload intent metadata is required.')
                binary_chunk = host_context.get('binary_upload_chunk') if isinstance(host_context, dict) else None
                if not isinstance(binary_chunk, bytes):
                    _fail('AUTHORITY_REQUIRED', 'An authenticated host binary body is required.')
                if not 1 <= len(binary_chunk) <= 4 * 1024 * 1024:
                    _fail('LIMIT_EXCEEDED', 'Binary upload chunks must be at most four MiB.')
                actual = hashlib.sha256(binary_chunk).digest()
                if (len(binary_chunk) != body['input']['content_length'] or
                        actual.hex() != body['input']['sha256'] or
                        base64.b64encode(actual).decode('ascii') != body['input']['digest']):
                    _fail('DIGEST_MISMATCH', 'Binary upload bytes differ from the frozen metadata.')
            native_record = self._native(native) if native is not None else None
            db = self._connect()
            context = dict(scope=scope, principal=principal, operation_id=op, params=params,
                           native_record=copy.deepcopy(native_record), project_store=self.store)
            # Only a trusted host call may qualify browser transports. Renderer
            # body/query values never enter this context; ignore other fields.
            qualified = host_context.get('qualified_media_transports', ()) if isinstance(host_context, dict) else ()
            context['qualified_media_transports'] = tuple(
                value for value in qualified if isinstance(value, str) and value in {'same_origin_cookie', 'authenticated_blob'}
            ) if isinstance(qualified, (tuple, list)) else ()
            if binary_chunk is not None:
                context['binary_upload_chunk'] = binary_chunk
            if 'composition_id' in params:
                comp = self._composition(db, native, params['composition_id'])
                context.update(composition=self._summary(db, comp), version=self._version(db, comp),
                               private_project_id=comp['private_id'], source_private_project_revision=comp['private_revision'],
                               private_project_revision=self._authoritative_revision(comp['private_id'],comp['private_revision']))
            elif method == 'GET' and query.get('composition_id'):
                if native is None:
                    _fail('SCOPE_MISMATCH','Contextual reads require an exact native Project scope.')
                comp = self._composition(db,native,query['composition_id'])
                context.update(composition=self._summary(db,comp),version=self._version(db,comp,query.get('version_id')),
                               private_project_id=comp['private_id'],source_private_project_revision=comp['private_revision'],
                               private_project_revision=self._authoritative_revision(comp['private_id'],comp['private_revision']))
            if method == 'GET':
                status, data = self._read(db, op, context, query)
                result = self._fresh(scope, data, db)
                db.commit()
                return status, result
            return self._command(db, op, path, context, body)
        except ContractError as exc:
            if db:
                db.rollback()
            return self._error(scope, exc)
        except (OSError, sqlite3.Error):
            if db:
                db.rollback()
            return self._error(scope, ContractError('BACKEND_UNAVAILABLE', 'Durable metadata or engine storage is unavailable.', effect='unknown' if method != 'GET' else 'none'))
        except Exception:
            if db:
                db.rollback()
            return self._error(scope, ContractError('BACKEND_UNAVAILABLE', 'The facade could not complete this request; reconcile its command before retrying.', effect='unknown' if method != 'GET' else 'none'))
        finally:
            if db:
                db.close()

    def _cas(self, db, context, pre):
        native, params = context['scope'].get('native_project_id'), context['params']
        comp = self._composition(db, native, params['composition_id']) if 'composition_id' in params else None
        current = {}
        if 'catalog_revision' in pre:
            current['catalog_revision'] = self._catalog(db, native)['revision']
        if comp:
            for key, column in (('composition_revision','revision'), ('version_id','head'), ('metadata_revision','metadata_revision')):
                if key in pre:
                    current[key] = comp[column]
        if 'settings_revision' in pre:
            current['settings_revision'] = self._settings(db)['settings_revision']
        if any(pre[k] != v for k,v in current.items()):
            _fail('REVISION_CONFLICT', 'The saved scope changed. Preserve the draft and refresh.',
                  dict(expected={k:pre[k] for k in current}, current=current, conflict_token=_id('conflict')))
        return comp

    def _permission(self, context, permission):
        checker = self.integrations.get('permissions')
        # Host authentication permits normal local editing. Policy changes,
        # authority, review/promote and execution are never implicit grants.
        return checker(context, permission) is True if callable(checker) else permission == 'edit'

    def _command(self, db, op, path, context, body):
        native = context['scope'].get('native_project_id', '')
        principal = context['principal']
        request_sha = self.request_hash(op,path,body)
        context.update(command_id=body['command_id'], idempotency_key=body['idempotency_key'], request_sha256=request_sha)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM commands WHERE principal=? AND native=? AND (command_id=? OR (operation=? AND idem=?))',
                         (principal,native,body['command_id'],op,body['idempotency_key'])).fetchall()
        if row:
            if len(row) != 1 or row[0]['request_sha'] != request_sha or row[0]['command_id'] != body['command_id'] or row[0]['idem'] != body['idempotency_key']:
                _fail('IDEMPOTENCY_MISMATCH', 'The command identity was already used for different frozen intent.')
            old = dict(row[0])
            if old['expires'] < _now() and old['status'] in ('committed','failed'):
                _fail('COMMAND_EXPIRED', 'The command is retained as a non-reusable tombstone.')
            if old['response']:
                result = json.loads(old['response'])
                if 'command' in result:
                    result['command']['replayed'] = True
                db.commit()
                return old['http_status'], result
            if op not in LOCAL_COMMANDS:
                data = self._command_projection(old)
                result = self._fresh(context['scope'], data, db, dict(command_id=body['command_id'],status=old['status'],receipt_id=old['receipt'],replayed=True))
                db.commit()
                return 202, result
        else:
            db.execute('INSERT INTO commands(command_id,principal,native,operation,idem,request_sha,scope,path,body,status,effect,created,expires) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (body['command_id'],principal,native,op,body['idempotency_key'],request_sha,_json(context['scope']),path,_json(body),'accepted','none',_now(),_later(30*86400)))
        db.commit()  # durable frozen intent precedes any engine/external effect
        try:
            db.execute('BEGIN IMMEDIATE')
            # Another identical request may have completed while we waited.
            existing = db.execute('SELECT * FROM commands WHERE principal=? AND native=? AND command_id=?', (principal,native,body['command_id'])).fetchone()
            if existing['response']:
                result = json.loads(existing['response'])
                if 'command' in result:
                    result['command']['replayed'] = True
                db.commit()
                return existing['http_status'], result
            comp = self._cas(db, context, body['preconditions'])
            if (context.get('native_record') or {}).get('archived'):
                _fail('PROJECT_ARCHIVED', 'Archived native Projects are read-only.')
            if comp and comp['archived'] and op not in ('OP-COMPOSITION-ARCHIVE','OP-JOB-CANCEL','OP-JOB-RECOVER','OP-DELIVERY-START','OP-DELIVERY-RECONCILE'):
                _fail('PROJECT_ARCHIVED', 'Restore this archived composition before editing or producing.')
            if (op in LOCAL_COMMANDS or op in ('OP-UPLOAD-CHUNK', 'OP-DISCOVERY-SCAN')) and not self._permission(context, 'edit'):
                _fail('PERMISSION_DENIED', 'The authenticated principal cannot edit this Project or composition.')
            if op=='OP-MASTER-PROMOTE' and not self._permission(context,'promote'):
                _fail('PERMISSION_DENIED','Master promotion requires authenticated promotion authority.')
            if op=='OP-REVIEW-RECORD' and body['input']['review_kind']=='human_editorial' and not self._permission(context,'human_review'):
                _fail('PERMISSION_DENIED','A human editorial review requires a trusted authenticated human-review context.')
            receipt_id = 'receipt_' + uuid.uuid5(uuid.NAMESPACE_URL, _hash([self.owner,principal,native,body['command_id']])).hex
            context['receipt_id'] = receipt_id
            if op in LOCAL_COMMANDS:
                status, data = self._local(db, op, context, body['input'], body['preconditions'], comp)
            else:
                # Accepted intent is durable. A process loss during this call
                # leaves an uncertain intent, never an automatic resubmission.
                db.execute("UPDATE commands SET effect='unknown',status='pending' WHERE principal=? AND native=? AND command_id=?", (principal,native,body['command_id']))
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                status, data = self._adapter(db, op, context, body['input'], body['preconditions'])
            effect = 'pending' if status == 202 else 'committed'
            state = 'pending' if status == 202 else 'committed'
            data = _public_data(data)
            self._retain_adapter_result(db,context,data)
            receipt = dict(receipt_id=receipt_id,kind=op,command_id=body['command_id'],scope=context['scope'],
                           subject_refs=self._refs(data),request_sha256=request_sha,result_sha256=_hash(data),
                           actor=dict(kind='authenticated_host',actor_ref=principal),created_at=_now(),effect_state=effect,evidence_refs=[])
            db.execute('INSERT INTO receipts VALUES(?,?,?,?)', (receipt_id,native,principal,_json(receipt)))
            if native:
                self._emit(db, context, data)
            result = self._fresh(context['scope'], data, db, dict(command_id=body['command_id'],status=state,receipt_id=receipt_id,replayed=False))
            db.execute('UPDATE commands SET status=?,effect=?,receipt=?,response=?,http_status=?,expires=? WHERE principal=? AND native=? AND command_id=?',
                       (state,effect,receipt_id,_json(result),status,_later(30*86400),principal,native,body['command_id']))
            db.commit()
            return status, result
        except _CommittedReplay as replay:
            db.rollback()
            result = replay.response
            result['command']['replayed'] = True
            return replay.status,result
        except ContractError as exc:
            db.rollback()
            status, result = self._error(context['scope'], exc)
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE commands SET status=?,effect=?,response=?,http_status=?,expires=? WHERE principal=? AND native=? AND command_id=?',
                       ('failed' if exc.effect == 'none' else 'unknown',exc.effect,_json(result),status,_later(30*86400),principal,native,body['command_id']))
            db.commit()
            return status, result
        except Exception:
            db.rollback()
            db.execute("UPDATE commands SET status='unknown',effect='unknown' WHERE principal=? AND native=? AND command_id=?", (principal,native,body['command_id']))
            db.commit()
            raise

    @staticmethod
    def _refs(data):
        refs = [{ 'kind':key[:-3], 'id':value } for key,value in data.items()
                if key.endswith('_id') and isinstance(value,str) and PUBLIC_RE.fullmatch(value)]
        for family,key in (('composition','composition_id'),('version','version_id')):
            value = data.get(family,{})
            identity = value.get(key) if isinstance(value,dict) else None
            ref = dict(kind=family,id=identity)
            if isinstance(identity,str) and PUBLIC_RE.fullmatch(identity) and ref not in refs:
                refs.append(ref)
        return refs

    def _emit(self, db, context, data):
        native = context['scope']['native_project_id']
        cid = context['params'].get('composition_id')
        summary = data.get('composition', data.get('summary', {}))
        cid = summary.get('composition_id', cid)
        version = data.get('version', {})
        entity_id = cid or next((r['id'] for r in self._refs(data)), context['receipt_id'])
        value = dict(event_id=_id('event'),stream_epoch=self._catalog(db,native)['epoch'],scope=context['scope'],
                     kind=context['operation_id'],entity=dict(type='composition' if cid else 'operation',id=entity_id,
                     revision=summary.get('composition_revision',data.get('entity_revision',1))),
                     command_id=context['command_id'],receipt_id=context['receipt_id'],committed_at=_now(),payload=dict(result_refs=self._refs(data)))
        if cid:
            value['composition_id'] = cid
        if version.get('version_id'):
            value['version_id'] = version['version_id']
        cursor = db.execute('INSERT INTO events(native,value) VALUES(?,?)', (native,_json(value)))
        value['sequence'] = str(cursor.lastrowid)
        db.execute('UPDATE events SET value=? WHERE sequence=?', (_json(value),cursor.lastrowid))


    def _graph_call(self, function, *args, context):
        # Policy editing is an authenticated permission, never an editable
        # declaration in the graph. The pure graph module has no host identity.
        if function is apply_operations:
            for op in args[1]:
                if op.get('op') == 'document.put' and op.get('kind') in ('execution_policy','bindings','gate_policy'):
                    if not self._permission(context,'policy_edit'):
                        _fail('PERMISSION_DENIED','Policy and binding edits require authenticated policy-edit permission.')
                if op.get('op') == 'document.remove':
                    old = next((d for d in args[0]['production_documents'] if d['document_id']==op.get('document_id')),None)
                    if old and old['kind'] in ('execution_policy','bindings','gate_policy') and not self._permission(context,'policy_edit'):
                        _fail('PERMISSION_DENIED','Policy removal requires authenticated policy-edit permission.')
            return function(*args,acknowledged_dependency_ids=context.get('acknowledged_dependency_ids',[]))
        return function(*args)

    def _compile(self, graph, context):
        recipe = context.get('render_recipe')
        if recipe is not None and graph['format']['duration_frames'] > 0:
            return compile_graph(graph, backend='canonical_graph_render_v1', recipe=recipe)
        result = self._graph_call(compile_graph,graph,context=context)
        if not isinstance(result,dict) or set(result) != {'settings','timeline','scenes','format','production_documents'}:
            _fail('UNREPRESENTABLE_GRAPH','Compiler returned no exact canonical engine document set.')
        if result['format'] != graph['format']:
            _fail('UNREPRESENTABLE_GRAPH','Compiler format sidecar differs from the frozen Composition format.')
        # Normalize tuple-keyed compiler output into a frozen JSON journal.
        values = {('settings','project'):result['settings'],('timeline','project'):result['timeline']}
        values.update({('scene',sid):value for sid,value in result['scenes'].items()})
        values.update(result['production_documents'])
        public = {}
        for doc in graph['production_documents']:
            kind, value = doc['kind'], doc['value']
            if kind in ('execution_policy','stage','voice_preferences'):
                continue  # these are represented in Settings, not separate docs
            identity = value['profile_id'] if kind == 'delivery_profile' else value['policy_id'] if kind == 'gate_policy' else 'project'
            public[kind,identity] = {key:copy.deepcopy(doc[key]) for key in ('kind','document_id','document_version_id','sha256')}
        # Immutable public asset pins can only resolve through the exact frozen
        # graph hydration; ProjectStore subsequently verifies registry ownership.
        assets = {(a['asset_id'],a['asset_version_id'],a['sha256']):a['artifact'] for a in graph['asset_refs']}
        def asset_pins(value,schema) -> Any:
            if '$ref' in schema:
                definition = schema['$ref'].rsplit('/',1)[-1]
                if definition == 'ArtifactRef':
                    artifact = assets.get((value['asset_id'],value['asset_version_id'],value['sha256']))
                    if artifact is None:
                        _fail('ASSETS_UNRESOLVED','Production document asset pin is absent from the frozen asset closure.')
                    return copy.deepcopy(artifact)
                if definition == 'DocumentRef':
                    return copy.deepcopy(value)  # resolved from real envelopes under lock
                return asset_pins(value,D[definition])
            union = schema.get('oneOf',schema.get('anyOf'))
            if union is not None:
                branches = [branch for branch in union if (value is None) == (branch.get('type') == 'null')]
                if len(branches) != 1:
                    _fail('UNREPRESENTABLE_GRAPH','No exact production schema branch.')
                return asset_pins(value,branches[0])
            if schema.get('type') == 'array':
                return [asset_pins(item,schema['items']) for item in value]
            if schema.get('type') == 'object':
                fields = schema.get('properties',{})
                extra = schema.get('additionalProperties',{})
                return {name:asset_pins(item,fields.get(name,extra) if isinstance(fields.get(name,extra),dict) else {})
                        for name,item in value.items()}
            return copy.deepcopy(value)
        return [dict(kind=kind,id=identity,
                     value=copy.deepcopy(value) if kind in ('scene','timeline') else asset_pins(value,self.store._document_schema(kind)['properties']['value']),
                     public_ref=public.get((kind,identity))) for (kind,identity),value in sorted(values.items())]

    def _render_recipe(self, context):

        recipe = context.get('render_recipe', context.get('version', {}).get('render_recipe',
                              self.integrations.get('_graph_recipe')))
        if recipe is not None:
            from .adapters.ui_compositor import RECIPE_SCHEMA
            validate(recipe, RECIPE_SCHEMA)
        return copy.deepcopy(recipe)

    def _build_graph_plan(self, runtime, context, graph, frames):
        from .ui_rendering import make_plan_builder
        recipe = context['version'].get('render_recipe')
        if recipe is None:
            _fail('RECIPE_REQUIRED', 'Save an explicit canonical render recipe before planning.')
        frozen = context.get('_canonical_source')
        if frozen is None:
            _fail('SOURCE_UNAVAILABLE','Selected version has no detached committed canonical render closure.')
        closure = json.loads(frozen['closure'])
        if closure['graph'] != graph or closure['recipe'] != recipe or closure['schemas'] != schema_catalog():
            _fail('STALE_DEPENDENCY','Selected graph, recipe or schema differs from its immutable canonical closure.')
        pin = json.loads(frozen['artifact'])
        if digest(closure) != pin['sha256']:
            _fail('HASH_MISMATCH','Frozen canonical render closure changed.')
        runtime.artifacts.resolve(context['private_project_id'],pin)
        source_revision = context.get('source_private_project_revision',frozen['private_revision'])
        if source_revision != frozen['private_revision']:
            _fail('PLAN_STALE','Historical native source revision differs from its immutable binding.')
        resolved = context.get('_resolved_asset_sources',{})
        def resolve_asset(owner,pin):
            source = resolved.get(_hash(pin))
            if source is None or any(source.get(k)!=v for k,v in pin.items()):
                _fail('ASSET_UNRESOLVED','Exact trusted source was not hydrated before entering the execution adapter.')
            return copy.deepcopy(source)
        return make_plan_builder(recipe, resolve_document=self._resolve_public_document,
            resolve_asset=resolve_asset)(runtime, context, graph, frames)

    def _render_context(self, db, context, *, assets=False):
        """Detach bytes before entering adapters; never nest owned SQLite locks."""
        result = dict(context)
        comp_id = context.get('composition',{}).get('composition_id')
        if comp_id is None:
            return result
        records = {}
        rows = db.execute('SELECT v.value FROM versions v JOIN compositions c ON c.id=v.composition WHERE c.native=? AND c.id=? ORDER BY v.revision',
            (context['scope']['native_project_id'],comp_id)).fetchall()
        documents = [doc for row in rows for doc in json.loads(row['value'])['production_documents']]
        documents.extend(json.loads(row['value']) for row in db.execute('SELECT value FROM retained_documents WHERE composition=?',(comp_id,)).fetchall())
        for doc in documents:
            pin = {key:doc[key] for key in ('kind','document_id','document_version_id','sha256')}
            key = _hash(pin)
            if _hash(doc['value']) != pin['sha256'] or (key in records and records[key] != doc):
                _fail('HASH_MISMATCH','Retained document identity differs from immutable bytes.')
            records[key] = doc
        result['_public_document_records'] = records
        version = context.get('version',{})
        frozen = db.execute('SELECT artifact,closure,private_revision FROM canonical_sources WHERE version=?',(version.get('version_id'),)).fetchone()
        result['_canonical_source'] = dict(frozen) if frozen else None
        if assets:
            resolved = {}
            resolver = self.integrations.get('_asset_source_resolver')
            for asset in version.get('asset_refs',[]):
                if not callable(resolver):
                    _fail('INTEGRATION_UNAVAILABLE','An authoritative asset resolver is required.')
                pin = {key:asset[key] for key in ('asset_id','asset_version_id','sha256')}
                value = resolver(context,copy.deepcopy(pin))
                if value != asset:
                    _fail('STALE_DEPENDENCY','Saved immutable asset facts differ from their source binding.')
                resolved[_hash(pin)] = copy.deepcopy(value)
            result['_resolved_asset_sources'] = resolved
        return result

    def _resolve_public_document(self, runtime, context, pin):
        """Exact retained public bytes, never current-head substitution."""
        _fields(pin,'kind document_id document_version_id sha256')
        records = context.get('_public_document_records')
        if records is None:
            db = self._connect()
            try:
                records = self._render_context(db,context)['_public_document_records']
            finally:
                db.close()
        doc = records.get(_hash(pin))
        if doc is None:
            _fail('STALE_DEPENDENCY','Exact public document is outside retained composition history.')
        if any(doc.get(k)!=v for k,v in pin.items()) or _hash(doc['value']) != pin['sha256']:
            _fail('HASH_MISMATCH','Public document differs from its immutable identity.')
        return copy.deepcopy(doc)

    def _hydrate_assets(self, graph, context, public_refs=()):
        """Only exact public pins enter the trusted source resolver."""
        graph = copy.deepcopy(graph)
        refs = list(public_refs)
        existing = graph['asset_refs']
        refs += [{key: a[key] for key in ('asset_id','asset_version_id','sha256')} for a in existing]
        resolver = self.integrations.get('_asset_source_resolver')
        hydrated = {}
        for pin in refs:
            _fields(pin, 'asset_id asset_version_id sha256')
            if not isinstance(pin['sha256'], str) or not HASH_RE.fullmatch(pin['sha256']):
                _fail('INVALID_ARGUMENT', 'An exact public source hash is required.')
            if not callable(resolver):
                _fail('INTEGRATION_UNAVAILABLE', 'Public sources require an authoritative asset resolver.')
            asset = resolver(context, copy.deepcopy(pin))
            if not isinstance(asset, dict) or any(asset.get(k) != v for k, v in pin.items()):
                _fail('ASSET_UNRESOLVED', 'Asset resolver returned a different public source.')
            key = (pin['asset_id'], pin['asset_version_id'])
            prior = next((a for a in existing if (a['asset_id'], a['asset_version_id']) == key), None)
            if prior is not None and prior != asset:
                _fail('STALE_DEPENDENCY', 'Saved source facts differ from their immutable binding.')
            if key in hydrated and hydrated[key] != asset:
                _fail('STALE_DEPENDENCY', 'Conflicting source pins in one transaction.')
            hydrated[key] = copy.deepcopy(asset)
        graph['asset_refs'] = list(hydrated.values())
        return graph

    def _authoritative_revision(self, private_id, source_revision):
        """Admit an advancing native head only when the frozen source is its ancestor."""
        fs = self.store._filesystem()
        pointer = self.store._pointer(fs, private_id)
        if pointer is None:
            _fail('NOT_FOUND', 'Native composition binding is unavailable.')
        current = pointer['revision']
        while pointer and pointer['revision'] >= source_revision:
            if pointer['revision'] == source_revision:
                return current
            transaction = self.store._transaction(fs, pointer)
            previous = transaction.get('previous') if transaction else None
            if previous and previous['revision'] >= pointer['revision']:
                _fail('PLAN_STALE', 'Native transaction ancestry is invalid.')
            pointer = previous
        _fail('PLAN_STALE', 'Saved composition is not an ancestor of the authoritative native head.')

    def _historical_profile_pins(self,db,comp,graph):
        """Resolve only exact authorized public profile versions, never latest."""
        current = [{key:doc[key] for key in ('kind','document_id','document_version_id','sha256')}
                   for doc in graph['production_documents']]
        requested = [variant['profile'] for doc in graph['production_documents'] if doc['kind']=='variants'
                     for variant in doc['value'] if variant['profile'] not in current]
        if not requested:
            return []
        if comp is None:
            _fail('STALE_DEPENDENCY','New composition cannot resolve an unowned historical profile pin.')
        fs = self.store._filesystem()
        pointer = self.store._pointer(fs,comp['private_id'])
        pointers = {}
        while pointer:
            pointers[pointer['revision']] = pointer
            transaction = self.store._transaction(fs,pointer)
            if not isinstance(transaction,dict):
                _fail('STALE_DEPENDENCY','Historical backend transaction is unavailable.')
            previous = transaction['previous']
            if previous and previous['revision'] >= pointer['revision']:
                _fail('STALE_DEPENDENCY','Historical backend revisions do not decrease.')
            pointer = previous
        resolved = []
        history = db.execute('SELECT value,private_revision FROM versions WHERE composition=? ORDER BY revision DESC',(comp['id'],)).fetchall()
        for pin in requested:
            if any(item['public_ref']==pin for item in resolved):
                continue
            for row in history:
                version = json.loads(row['value'])
                doc = next((doc for doc in version['production_documents']
                            if {key:doc[key] for key in ('kind','document_id','document_version_id','sha256')}==pin),None)
                if doc is None:
                    continue
                if doc['kind']!='delivery_profile' or _hash(doc['value'])!=doc['sha256'] or row['private_revision'] not in pointers:
                    _fail('STALE_DEPENDENCY','Historical profile closure is not intact.')
                _,records = self.store._load(fs,pointers[row['private_revision']])
                record = records.get(('delivery_profile',doc['value']['profile_id']))
                if record is None or record['value'] != doc['value']:
                    _fail('STALE_DEPENDENCY','Historical profile has no matching committed backend envelope.')
                resolved.append(dict(public_ref=copy.deepcopy(pin),backend_ref=dict(kind=record['kind'],id=record['id'],revision=record['revision'],sha256=digest(record))))
                break
            else:
                _fail('STALE_DEPENDENCY','Profile pin is not in this composition\'s authorized history.')
        return resolved

    def _commit_compiled(self, private_id, expected_revision, request_id, documents):
        """Use ProjectStore's real immutable preparation/publication protocol.

        Its public update API cannot atomically replace canonical Settings or
        allocate server-created scene IDs. This narrowly-scoped store adapter
        supplies only compiler-produced documents, validates the complete core
        closure, and invokes the same immutable transaction writer/commit point
        as ProjectStore._update. It does not create a parallel engine store.
        """
        fs = self.store._filesystem(write=True)
        base = self.store._base(private_id)
        args = dict(action='update',project_id=private_id,expected_revision=expected_revision,
                    request_id=request_id,compiled_documents=documents)
        with fs.lock(base + '/locks/content.lock'):
            pointer = self.store._pointer(fs,private_id)
            replay = self.store._replay(fs,pointer,args)
            if replay is not None:
                return replay['project']['revision']
            if pointer['revision'] != expected_revision:
                _fail('REVISION_CONFLICT','The private compiled binding changed.',dict(expected_revision=expected_revision,actual_revision=pointer['revision']))
            _, original = self.store._load(fs,pointer)
            if isinstance(documents, dict) and documents.get('schema') == 'motion/ui/canonical-graph-closure/v1':
                from .artifacts import ArtifactCatalog
                catalog = ArtifactCatalog(self.store)
                dependencies = []
                for asset in documents['graph']['asset_refs']:
                    if asset['artifact'] not in dependencies:
                        dependencies.append(copy.deepcopy(asset['artifact']))
                pin = catalog.publish_json(private_id, documents, inputs=dependencies)
                record = catalog.resolve(private_id, pin)
                if fs.read(base + '/' + record['storage']['relative_path']) != documents:
                    _fail('HASH_MISMATCH', 'Canonical persistence closure differs from frozen bytes.')
                # This is native bookkeeping, NOT a projected B03 render source.
                # Native request_sha256 commits the complete closure bytes;
                # ancillary identity is deterministic from bytes and lineage.
                allocated = [int(n) for n in fs.names(base + '/revisions') if n.isascii() and n.isdigit()]
                revision = max(allocated + [pointer['revision']]) + 1
                timestamp = _now()
                new = {**pointer, 'revision': revision, 'updated_at': timestamp,
                       'manifest_path': f'revisions/{revision}/snapshot.json'}
                self.store._validate_content(fs, private_id, original, pointer)
                self.store._prepare(fs, new, original, args, pointer, set())
                fs.write(base + '/project.json', new, replace=True)
                committed = self.store._transaction(fs, new)
                if committed is None or committed['request_sha256'] != self.store._request_hash(args):
                    _fail('HASH_MISMATCH', 'Native transaction did not bind the exact canonical closure.', effect='unknown')
                return revision
            timestamp = _now()
            desired = {(row['kind'],row['id']):copy.deepcopy(row['value']) for row in documents}
            # Gate policy is versioned in the engine envelope as well as settings.
            gate = desired['settings','project']['gate_policy']
            old_gate = original['settings','project']['value']['gate_policy']
            gate_key = ('gate_policy',gate['policy_id'])
            if {k:v for k,v in gate.items() if k!='revision'} == {k:v for k,v in old_gate.items() if k!='revision'}:
                gate['revision'] = old_gate['revision']
            else:
                gate['revision'] = original.get(gate_key,{}).get('revision',0) + 1
            desired[gate_key] = copy.deepcopy(gate)
            # Canonical compiler owns these families; retaining obsolete scenes
            # or deleted docs would disconnect public head from actual execution.
            owned = {'settings','timeline','scene','brief','brand','variants','bindings','asset_library','storyboard','creative_plan','editorial','delivery_profile','gate_policy'}
            docs = {key:copy.deepcopy(value) for key,value in original.items() if key[0] not in owned}
            changed = set(original) - set(docs) - set(desired)
            public = {key:row['public_ref'] for row in documents
                      if row.get('public_ref') for key in [(row['kind'],row['id'])]}
            historical_refs = [item for row in documents for item in row.get('historical_refs',[])]
            resolving = set()

            def adapt(value, schema) -> Any:
                if '$ref' in schema:
                    definition = schema['$ref'].rsplit('/',1)[-1]
                    if definition == 'DocumentRef':
                        target = next((key for key,ref in public.items() if ref == value),None)
                        if target is None:
                            historical = next((item['backend_ref'] for item in historical_refs if item['public_ref']==value),None)
                            if historical is None:
                                _fail('STALE_DEPENDENCY','Document pin does not match the frozen production-document closure.')
                            from .editorial import historical as read_historical
                            read_historical(self.store,fs,pointer,historical)
                            return copy.deepcopy(historical)
                        record = build(target)
                        return dict(kind=record['kind'],id=record['id'],revision=record['revision'],sha256=digest(record))
                    if definition == 'ArtifactRef':
                        # _compile resolved this exact public asset/version/hash;
                        # the core validator checks real registry ownership.
                        validate(value,D['ArtifactRef'])
                        return copy.deepcopy(value)
                    return adapt(value,D[definition])
                union = schema.get('oneOf',schema.get('anyOf'))
                if union is not None:
                    # Production document unions are nullable values. Keep all
                    # other unions explicit rather than guessing a branch.
                    candidates = [branch for branch in union if (value is None) == (branch.get('type') == 'null')]
                    if len(candidates) != 1:
                        _fail('UNREPRESENTABLE_GRAPH','No exact backend schema branch for a production value.')
                    return adapt(value,candidates[0])
                if schema == DIGEST:
                    return value if value.startswith('sha256:') else 'sha256:' + value
                if schema.get('type') == 'array':
                    return [adapt(item,schema['items']) for item in value]
                if schema.get('type') == 'object':
                    fields = schema.get('properties',{})
                    extra = schema.get('additionalProperties',{})
                    return {name:adapt(item,fields.get(name,extra) if isinstance(fields.get(name,extra),dict) else {})
                            for name,item in value.items()}
                return copy.deepcopy(value)

            def build(key):
                if key in docs:
                    return docs[key]
                if key in resolving:
                    _fail('INVALID_GRAPH','Production document references contain a cycle.')
                resolving.add(key)
                schema = self.store._document_schema(key[0])['properties']['value']
                value = copy.deepcopy(desired[key]) if key[0] in ('scene','timeline') else adapt(desired[key],schema)
                if key == ('storyboard','project'):
                    library = build(('asset_library','project'))
                    value['asset_library_sha256'] = digest(library)
                previous = original.get(key)
                if previous and previous['value'] == value:
                    docs[key] = copy.deepcopy(previous)
                else:
                    changed.add(key)
                    docs[key] = dict(schema='motion/v1/document',project_id=private_id,kind=key[0],id=key[1],
                                     revision=(previous['revision'] if previous else 0)+1,created_at=timestamp,value=value)
                self.store._safe_document_identity(*key)
                validate(docs[key],self.store._document_schema(key[0]))
                resolving.remove(key)
                return docs[key]

            for key in desired:
                build(key)
            self.store._validate_content(fs,private_id,docs,pointer,storyboard_submitted=('storyboard','project') in desired)
            if not changed:
                # Still create an immutable core transaction, so this public
                # content version always has a unique exact engine revision.
                # No document envelope revision is fabricated for equal values.
                pass
            allocated = [int(n) for n in fs.names(base + '/revisions') if n.isascii() and n.isdigit()]
            revision = max(allocated + [pointer['revision']]) + 1
            _integer(revision)
            new = {**pointer,'revision':revision,'updated_at':timestamp,'manifest_path':f'revisions/{revision}/snapshot.json'}
            self.store._prepare(fs,new,docs,args,pointer,changed)
            fs.write(base + '/project.json',new,replace=True)
            return revision

    def _store_dispatch(self, args):
        result = self.store.dispatch(args)
        if not result.get('ok'):
            error = result.get('error', {})
            # Never forward the engine message/details, which may contain a
            # private record ID, root, path or plugin policy internals.
            code = error.get('code','UNREPRESENTABLE_GRAPH')
            if code == 'IDEMPOTENCY_CONFLICT':
                code = 'IDEMPOTENCY_MISMATCH'
            _fail(code, 'The canonical engine document commit was rejected.', {'reason':'compiled_document_rejected'},effect=error.get('effect','unknown'))
        return result

    def _freeze_work(self, db, context, work):
        native = context['scope'].get('native_project_id','')
        key = (context['principal'],native,context['command_id'])
        row = db.execute('SELECT work FROM commands WHERE principal=? AND native=? AND command_id=?',key).fetchone()
        if row['work']:
            return json.loads(row['work'])
        db.execute("UPDATE commands SET work=?,effect='unknown' WHERE principal=? AND native=? AND command_id=?",(_json(work),*key))
        # Freeze graph and IDs BEFORE ProjectStore publication. Its idempotent
        # receipts can then recover a crash between file commit and SQLite head.
        db.commit()
        db.execute('BEGIN IMMEDIATE')
        completed = db.execute('SELECT response,http_status FROM commands WHERE principal=? AND native=? AND command_id=?',key).fetchone()
        if completed['response']:
            raise _CommittedReplay(completed['http_status'],json.loads(completed['response']))
        return work

    def _relocate_graph_assets(self, db, context, graph, cid, request_seed, name):
        """Copy admitted bytes as native metadata; never run a probe/decoder."""
        fmt = graph['format']
        made = self._store_dispatch(dict(action='create',request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,request_seed+':create')),
            name=name,rate=fmt['fps'],sample_rate=fmt['sample_rate'],brief=empty_brief()))
        target = {**context,'composition':dict(composition_id=cid),'private_project_id':made['project_id']}
        media = self.integrations.get('_media_store')
        if media is None:
            _fail('INTEGRATION_UNAVAILABLE','An owned asset relocation adapter is required.')
        relocated = []
        with media.database(context,write=True) as (catalog,_):
            for asset in graph['asset_refs']:
                record = media.get(catalog,'asset',asset['asset_id'])
                if record['asset_version_id'] != asset['asset_version_id'] or record['sha256'] != asset['sha256']:
                    _fail('STALE_DEPENDENCY','Recovery source asset changed.')
                association = media.associate(catalog,target,record,
                    str(uuid.uuid5(uuid.NAMESPACE_URL,request_seed+':copy:'+asset['asset_id']+':'+asset['asset_version_id'])))
                facts = {**copy.deepcopy(asset),'artifact':copy.deepcopy(association['pin'])}
                if association.get('graph_asset') not in (None,facts):
                    _fail('HASH_MISMATCH','Recovered asset association conflicts with frozen source facts.')
                association['graph_asset'] = facts
                association['source_binding'] = dict(composition_id=context['composition']['composition_id'],
                    asset_id=asset['asset_id'],asset_version_id=asset['asset_version_id'],sha256=asset['sha256'])
                media.save(catalog,'composition-asset',association['id'],association)
                if cid not in record['usages']:
                    record['usages'].append(cid)
                    record['entity_revision'] += 1
                    media.save(catalog,'asset',record['asset_id'],record)
                relocated.append(facts)
        graph = copy.deepcopy(graph)
        graph['asset_refs'] = relocated
        pointer = self.store._pointer(self.store._filesystem(),made['project_id'])
        if pointer is None:
            _fail('NOT_FOUND','Recovered native project has no committed pointer.')
        return graph,target,pointer['revision']

    def _retain_recovery_documents(self, db, context, cid):
        source = context.get('composition',{}).get('composition_id')
        if source is None or source == cid:
            return
        rows = db.execute('SELECT value FROM versions WHERE composition=?',(source,)).fetchall()
        documents = []
        for row in rows:
            documents.extend(json.loads(row['value'])['production_documents'])
        documents.extend(json.loads(row['value']) for row in db.execute('SELECT value FROM retained_documents WHERE composition=?',(source,)).fetchall())
        unique = {}
        for doc in documents:
            pin = {key:doc[key] for key in ('kind','document_id','document_version_id','sha256')}
            key = _hash(pin)
            if key in unique and unique[key] != doc:
                _fail('HASH_MISMATCH','Inherited document pin has conflicting immutable bytes.')
            unique[key] = doc
        if len(unique)>1000:
            _fail('LIMIT_EXCEEDED','Recovery historical document closure exceeds its finite bound.')
        for key,doc in unique.items():
            prior = db.execute('SELECT value FROM retained_documents WHERE composition=? AND pin_sha=?',(cid,key)).fetchone()
            if prior is not None and json.loads(prior['value']) != doc:
                _fail('HASH_MISMATCH','Recovered document closure changed during replay.')
            db.execute('INSERT OR IGNORE INTO retained_documents VALUES(?,?,?)',(cid,key,_json(doc)))

    def _publish(self, db, context, graph, comp=None, name=None, affected=None, created_ids=None) -> dict[str, Any]:
        native = context['scope']['native_project_id']
        request_seed = _hash([self.owner,context['principal'],native,context['command_id']])
        cid = comp['id'] if comp else 'comp_' + str(uuid.uuid5(uuid.NAMESPACE_URL,request_seed+':composition'))
        old_version = self._version(db,comp) if comp else None
        graph = copy.deepcopy(graph)
        recipe_context = dict(context)
        if old_version is not None:
            recipe_context['version'] = old_version
        recipe = self._render_recipe(recipe_context)
        context = {**context, 'render_recipe':recipe}
        graph = self._hydrate_assets(graph,context)
        new_private_revision = None
        if comp is None:
            self._retain_recovery_documents(db,context,cid)
            if graph['asset_refs']:
                graph,context,new_private_revision = self._relocate_graph_assets(db,context,graph,cid,request_seed,name)
        for family,identity in (('tracks','track_id'),('clips','clip_id'),('scenes','scene_id'),('layers','layer_id'),('captions','cue_id'),('audio_buses','bus_id'),('effects','effect_id')):
            graph[family].sort(key=lambda row:row[identity])
        graph['production_documents'].sort(key=lambda row:(row['kind'],row['document_id']))
        self._graph_call(validate_graph, graph, context=context)
        changes = self._compile(graph, context)
        historical_refs = self._historical_profile_pins(db,comp,graph) if isinstance(changes,list) else []
        if historical_refs:
            changes[0]['historical_refs'] = historical_refs
        work = self._freeze_work(db,context,dict(graph=graph,changes=changes,cid=cid,
                                                vid=_id('version'),name=name,created=_now(),affected=affected or [],created_ids=created_ids or {},
                                                recovery=context.get('_recovery'),recovery_guard=context.get('_recovery_guard'),
                                                render_recipe=recipe,expected_head=comp['head'] if comp else None,
                                                private_revision=self._authoritative_revision(comp['private_id'],comp['private_revision']) if comp else new_private_revision))
        graph, changes = work['graph'], work['changes']
        cid, vid, timestamp = work['cid'], work['vid'], work['created']
        if work.get('recovery_guard'):
            guard = work['recovery_guard']
            self._recovery_source(db,context,guard['review'],guard['catalog_revision'])
        revision = comp['revision'] + 1 if comp else 1
        # A second concurrent identical command might have completed while the
        # freeze journal released the SQLite lock.
        published = db.execute('SELECT composition FROM versions WHERE id=?',(vid,)).fetchone()
        if published:
            current = self._composition(db,native,cid)
            return dict(composition=self._summary(db,current),version=self._version(db,current),created_ids=work['created_ids'])
        request_seed = _hash([self.owner,context['principal'],native,context['command_id']])
        if comp:
            private_id = comp['private_id']
            private_revision = work['private_revision']
        else:
            fmt = graph['format']
            made = self._store_dispatch(dict(action='create',request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,request_seed + ':create')),
                                            name=work['name'],rate=fmt['fps'],sample_rate=fmt['sample_rate'],brief=empty_brief()))
            private_id = made['project_id']
            private_revision = work['private_revision'] if work.get('private_revision') is not None else made['project_revision']
        # The freeze journal committed no head change. Recheck after reacquiring
        # the SQLite lock; a different command could have won that narrow gap.
        if comp:
            latest = self._composition(db,native,cid)
            if latest['head'] != work['expected_head']:
                _fail('REVISION_CONFLICT','Composition changed while the frozen compiler journal was prepared.')
        try:
            private_revision = self._commit_compiled(private_id,private_revision,
                                                    str(uuid.uuid5(uuid.NAMESPACE_URL,request_seed + ':compile')),changes)
        except ContractError as exc:
            # Core validators may mention private IDs or filesystem details.
            raise ContractError(exc.code,'Canonical engine content validation rejected the saved graph.',effect=exc.effect) from None
        content_fields = ('format','tracks','clips','scenes','layers','effects','audio_buses','captions','asset_refs','settings','production_documents')
        content = {key:copy.deepcopy(graph[key]) for key in content_fields}
        identities = dict(tracks='track_id',clips='clip_id',scenes='scene_id',layers='layer_id',effects='effect_id',audio_buses='bus_id',captions='cue_id',asset_refs='asset_id',production_documents='document_id')
        for family,identity in identities.items():
            content[family].sort(key=lambda row:row[identity])
        content['production_documents'].sort(key=lambda row:(row['kind'],row['document_id']))
        content['schema_version'] = 'composition.v1'
        if work.get('render_recipe') is not None:
            content['render_recipe'] = copy.deepcopy(work['render_recipe'])
        version = {**content,'sha256':_hash(_public_data(content))}
        version.update(version_id=vid,composition_id=cid,composition_revision=revision,
                       parent_version_id=comp['head'] if comp else None)
        version.update(created_at=timestamp,actor_ref=context['principal'],transaction_receipt_id=context['receipt_id'])
        if work.get('recovery_guard'):
            guard = work['recovery_guard']
            self._recovery_source(db,context,guard['review'],guard['catalog_revision'])
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)',(vid,cid,revision,version['parent_version_id'],version['sha256'],_json(version),private_revision,_hash(changes)))
        if isinstance(changes,dict) and changes.get('schema') == 'motion/ui/canonical-graph-closure/v1':
            from .artifacts import ArtifactCatalog
            dependencies = list({canonical(a['artifact']):a['artifact'] for a in changes['graph']['asset_refs']}.values())
            pin = ArtifactCatalog(self.store).publish_json(private_id,changes,inputs=dependencies)
            db.execute('INSERT INTO canonical_sources VALUES(?,?,?,?)',(vid,_json(pin),_json(changes),private_revision))
        if comp:
            db.execute('UPDATE compositions SET revision=?,head=?,private_revision=?,updated=? WHERE id=? AND revision=?',
                       (revision,vid,private_revision,timestamp,cid,comp['revision']))
        else:
            db.execute('INSERT INTO compositions(id,native,name,revision,head,private_id,private_revision,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                       (cid,native,work['name'],revision,vid,private_id,private_revision,timestamp,timestamp))
        current = self._composition(db,native,cid)
        data = dict(composition=self._summary(db,current),version=version,sha256=version['sha256'],
                    affected_entities=work['affected'],affected_frame_ranges=[],invalidated_refs=[],created_ids=work['created_ids'])
        if old_version:
            token = _id('undo')
            db.execute('INSERT INTO undo VALUES(?,?,?,?,?,?,?,?)',(token,native,cid,context['principal'],vid,old_version['version_id'],'undo',_later(30*86400)))
            data['undo_token'] = token
        return data

    @staticmethod
    def _graph(version):
        return {key:copy.deepcopy(version[key]) for key in ('schema_version','format','tracks','clips','scenes','layers','effects','audio_buses','captions','asset_refs','settings','production_documents')}

    def _recovery_source(self, db, context, review, catalog_revision):
        _fields(review, 'source current_head base_graph_sha256 schema_catalog_sha256 transaction')
        native = context['scope']['native_project_id']
        comp = self._composition(db,native,context['params']['composition_id'])
        _fields(review['source'], 'composition_id version_id composition_revision sha256')
        if review['source']['composition_id'] != comp['id']:
            _fail('SCOPE_MISMATCH','Recovery source must belong to this composition.')
        base = self._version(db,comp,review['source']['version_id'])
        head = self._version(db,comp)
        def pin(version):
            return {key:version[key] for key in ('composition_id','version_id','composition_revision','sha256')}
        if pin(base) != review['source'] or pin(head) != review['current_head']:
            _fail('SOURCE_CHANGED','Retained source or reviewed current head changed.')
        if self._catalog(db,native)['revision'] != catalog_revision:
            _fail('REVISION_CONFLICT','Recovery catalog changed; review again.')
        unresolved = db.execute("SELECT command_id,path,operation FROM commands WHERE principal=? AND native=? AND command_id<>? AND status IN ('accepted','pending','unknown')",
            (context['principal'],native,context['command_id'])).fetchall()
        for command in unresolved:
            if command['operation'] in ('OP-TRANSACTION','OP-RECOVER-VERSION','OP-RECOVER-AS-NEW','OP-ASSET-BIND') and '/compositions/' + comp['id'] + '/' in command['path']:
                _fail('COMMAND_UNRESOLVED','Reconcile original submissions before preparing recovery.')
        return comp,base,head

    def _prepare_recovery(self, db, context, review, reviewed_sha256, catalog_revision):
        from .ui_recovery import prepare_recovery
        context = self._render_context(db,context)
        comp,base,head = self._recovery_source(db,context,review,catalog_revision)
        graph = self._graph(base)
        # Validate ownership before typed replay, including sources already in
        # the retained base. Never hydrate a client ArtifactRef.
        self._hydrate_assets(graph,context)
        def authorize(kind, pin):
            if kind == 'asset':
                resolver = self.integrations.get('_asset_source_resolver')
                if not callable(resolver):
                    return False
                value = resolver(context,copy.deepcopy(pin))
                return isinstance(value,dict) and all(value.get(k)==v for k,v in pin.items())
            if kind == 'document':
                self._resolve_public_document(None,context,pin)
                return True
            return False
        tx = review['transaction']
        # Enforce the service's authenticated policy boundary even though the
        # pure helper correctly has no host permissions of its own.
        if isinstance(tx,dict) and isinstance(tx.get('operations'),list):
            for operation in tx['operations']:
                if operation.get('op')=='document.put' and operation.get('kind') in ('execution_policy','bindings','gate_policy') and not self._permission(context,'policy_edit'):
                    _fail('PERMISSION_DENIED','Recovery policy edits require authenticated authority.')
        result = prepare_recovery(graph, source=review['source'],current_head=review['current_head'],
            review=review,reviewed_sha256=reviewed_sha256,authorize_reference=authorize)
        recipe = self._render_recipe({**context,'version':base})
        self._compile(result['graph'],{**context,'render_recipe':recipe})
        return result,recipe

    def _bind_asset_version(self, db, context, input, pre, comp):
        execution = self.integrations.get('_execution_adapter')
        media = self.integrations.get('_media_store')
        if execution is None or media is None:
            _fail('INTEGRATION_UNAVAILABLE','Trusted source binding adapter is unavailable.')
        # This route binds only an already committed native probe. It never
        # manufactures approval/session authority or starts decoder work.
        with media.database(context,write=True) as (catalog,_):
            record = media.get(catalog,'asset',context['params']['asset_id'])
            association = media.get(catalog,'composition-asset',media.association_id(context,record))
            existing = association.get('graph_asset')
            receipt = association.get('probe')
            exact = existing is not None and receipt is not None and receipt.get('receipt_id')==input['receipt_id']
            if exact:
                from .ui_execution import unwrap
                runtime = execution.runtime(context)
                observed = unwrap(runtime.asset(dict(action='get',project_id=context['private_project_id'],asset_id=association['native_asset_id'])))
                if observed['asset']['artifact'] != association['pin'] or observed['latest_probe'] != receipt:
                    _fail('REVISION_CONFLICT','Native source probe changed before binding.')
                facts = execution.source_facts(record,association['pin'],receipt,input['stream_index'])
                if facts != existing or record['asset_version_id'] != input['asset_version_id'] or record['sha256'] != input['sha256']:
                    _fail('REVISION_CONFLICT','Exact source stream binding changed.')
                # A metadata-only bind may have survived a publication crash.
                # Reuse it, never increment metadata or rerun the probe.
                if record['entity_revision'] not in (pre['entity_revision'],pre['entity_revision']+1):
                    _fail('REVISION_CONFLICT','Source metadata changed independently.')
                bound = dict(asset_id=record['asset_id'],asset_version_id=record['asset_version_id'],
                    entity_revision=record['entity_revision'],source_facts={k:v for k,v in facts.items() if k!='artifact'})
            else:
                bound = execution.asset_bind(catalog,context,input,pre)
        pin = {key:input[key] for key in ('asset_version_id','sha256')}
        pin['asset_id'] = context['params']['asset_id']
        graph = self._hydrate_assets(self._graph(self._version(db,comp)),context,[pin])
        data = self._publish(db,context,graph,comp,affected=[pin['asset_id']])
        saved = self._version(db,self._composition(db,context['scope']['native_project_id'],comp['id']),data['version']['version_id'])
        if not any(all(asset.get(k)==v for k,v in pin.items()) for asset in saved['asset_refs']):
            _fail('HASH_MISMATCH','Source binding publication was not observed.',effect='unknown')
        data.update(bound)
        data['readiness'] = 'bound'
        return 200,data

    def _local(self, db, op, context, input, pre, comp):
        native = context['scope'].get('native_project_id')
        if 'render_recipe' in input:
            if input['render_recipe'] is None:
                _fail('RECIPE_REQUIRED','An explicitly supplied render recipe cannot be null.')
            context['render_recipe'] = self._render_recipe({'render_recipe':input['render_recipe']})
        if op == 'OP-SETTINGS-SAVE':
            return 200, self._save_settings(db,input)
        if op == 'OP-ASSET-BIND':
            return self._bind_asset_version(db,context,input,pre,comp)
        if op == 'OP-RECOVERY-REVIEW':
            review_sha = _hash(input['review'])
            prepared,recipe = self._prepare_recovery(db,context,input['review'],review_sha,pre['catalog_revision'])
            token,expires = _id('recoveryreview'),_later(900)
            db.execute('INSERT INTO recovery_reviews VALUES(?,?,?,?,?,?,?,?,?)',
                (token,context['principal'],native,comp['id'],_json(context['scope']),review_sha,_json(input['review']),pre['catalog_revision'],expires))
            receipt = prepared['recovery_receipt']
            return 200,dict(review_token=token,review_sha256=review_sha,expires_at=expires,
                source=receipt['source'],current_head=receipt['observed_head'],catalog_revision=pre['catalog_revision'],
                affected_entities=receipt['original_affected_entities'],blockers=[])
        if op == 'OP-RECOVER-AS-NEW':
            _name(input['name'])
            token = db.execute('SELECT * FROM recovery_reviews WHERE id=? AND principal=? AND native=? AND composition=?',
                (input['review_token'],context['principal'],native,comp['id'])).fetchone()
            if not token or token['scope'] != _json(context['scope']):
                _fail('RECOVERY_REVIEW_REQUIRED','An exact scoped recovery review is required.')
            if token['expires'] < _now():
                _fail('RECOVERY_REVIEW_EXPIRED','Recovery review expired; review again.')
            if token['review_sha'] != _hash(input['review']) or token['review'] != _json(input['review']) or token['catalog_revision'] != pre['catalog_revision']:
                _fail('RECOVERY_REVIEW_CHANGED','Recovery differs from the exact reviewed transaction.')
            self._recovery_source(db,context,input['review'],pre['catalog_revision'])
            frozen = db.execute('SELECT work FROM commands WHERE principal=? AND native=? AND command_id=?',
                (context['principal'],native,context['command_id'])).fetchone()
            work = json.loads(frozen['work']) if frozen and frozen['work'] else None
            if work is not None and 'recovery' in work:
                prepared,recipe = work['recovery'],work.get('render_recipe')
            else:
                prepared,recipe = self._prepare_recovery(db,context,input['review'],token['review_sha'],pre['catalog_revision'])
            context = {**context,'render_recipe':recipe,'_recovery':prepared,
                       '_recovery_guard':dict(review=input['review'],catalog_revision=pre['catalog_revision'])}
            # The helper already remapped typed editorial identities. This is
            # create publication, never duplicate/remap or source-head mutation.
            data = self._publish(db,context,prepared['graph'],comp=None,name=input['name'],
                affected=prepared['recovery_receipt']['original_affected_entities'],created_ids=prepared['created_ids'])
            observed = self._version(db,self._composition(db,native,data['composition']['composition_id']),data['version']['version_id'])
            if observed != data['version']:
                _fail('HASH_MISMATCH','Recovered version did not read back exactly.',effect='unknown')
            data['recovery_receipt'] = {**prepared['recovery_receipt'],'state':'committed',
                'composition_id':observed['composition_id'],'version_id':observed['version_id'],'sha256':observed['sha256']}
            data['entity_id_mapping'] = prepared['id_remap']
            data['catalog_revision'] = self._bump_catalog(db,native)
            return 201,data
        if op == 'OP-COMPOSITION-CREATE':
            _name(input['name'])
            graph = self._graph_call(init_graph,input['format'],context=context)
            if input['template_ref'] is not None:
                ref = input['template_ref']
                template = self.integrations.get('templates',{}).get(_hash(ref))
                if template is None:
                    _fail('TEMPLATE_UNAVAILABLE','Only already-authorized immutable templates are supported.')
                graph = copy.deepcopy(template)
                if graph.get('format') != input['format']:
                    _fail('FORMAT_UNSUPPORTED','The selected template has a different pinned format.')
            data = self._publish(db,context,graph,name=input['name'])
            data['catalog_revision'] = self._bump_catalog(db,native)
            return 201,data
        if op == 'OP-COMPOSITION-DUPLICATE':
            _name(input['name']); _bool(input['include_rights_assertions'])
            if input['source_version_id'] != pre['version_id']:
                _fail('SOURCE_CHANGED','Duplicate source must equal the exact pinned version.')
            graph = self._graph(self._version(db,comp,pre['version_id']))
            # Remap owned editorial identities recursively, preserving immutable
            # asset/version/schema references and their provenance.
            mapping = {}
            for family, identity in (('tracks','track_id'),('clips','clip_id'),('scenes','scene_id'),('layers','layer_id'),('effects','effect_id'),('audio_buses','bus_id'),('captions','cue_id'),('production_documents','document_id')):
                for item in graph.get(family,[]):
                    if isinstance(item,dict) and identity in item:
                        mapping[item[identity]] = item[identity].split('_',1)[0] + '_' + str(uuid.uuid4())
                    if family == 'production_documents':
                        mapping[item['document_version_id']] = 'dvr_' + str(uuid.uuid4())
            def remap(value) -> Any:
                if isinstance(value,str):
                    return mapping.get(value,value)
                if isinstance(value,list):
                    return [remap(v) for v in value]
                if isinstance(value,dict):
                    return {k:remap(v) for k,v in value.items() if input['include_rights_assertions'] or k != 'rights_assertions'}
                return value
            graph = remap(graph)
            docs = {doc['document_id']:doc for doc in graph['production_documents']}
            active,finished = set(),set()
            def refresh_document(identity) -> dict[str, Any]:
                doc = docs[identity]
                if identity in finished:
                    return doc
                if identity in active:
                    _fail('INVALID_GRAPH','Duplicated production documents contain a reference cycle.')
                active.add(identity)
                def pins(value) -> Any:
                    if isinstance(value,dict):
                        if set(value) == {'kind','document_id','document_version_id','sha256'} and value['document_id'] in docs:
                            target = refresh_document(value['document_id'])
                            if value['kind'] != target['kind'] or value['document_version_id'] != target['document_version_id']:
                                _fail('STALE_DEPENDENCY','Duplicate cannot rewrite a historical document pin as current.')
                            return {key:target[key] for key in ('kind','document_id','document_version_id','sha256')}
                        return {key:pins(item) for key,item in value.items()}
                    if isinstance(value,list):
                        return [pins(item) for item in value]
                    return value
                doc['value'] = pins(doc['value'])
                if doc['kind'] == 'storyboard':
                    library = next(item for item in docs.values() if item['kind']=='asset_library')
                    doc['value']['asset_library_sha256'] = refresh_document(library['document_id'])['sha256']
                doc['sha256'] = _hash(doc['value'])
                active.remove(identity)
                finished.add(identity)
                return doc
            for identity in docs:
                refresh_document(identity)
            data = self._publish(db,context,graph,name=input['name'],created_ids=mapping)
            data.update(entity_id_mapping=data['created_ids'],catalog_revision=self._bump_catalog(db,native))
            return 201,data
        if op == 'OP-COMPOSITION-METADATA':
            _name(input['name'])
            db.execute('UPDATE compositions SET name=?,metadata_revision=metadata_revision+1,updated=? WHERE id=?',(input['name'],_now(),comp['id']))
            return 200,dict(composition=self._summary(db,self._composition(db,native,comp['id'])))
        if op == 'OP-COMPOSITION-ARCHIVE':
            _bool(input['archived']); _bool(input['acknowledge_running_jobs'])
            query = dict(composition_id=comp['id'])
            jobs = self._jobs(db,context,query) + self._resource_items(db,context,query,'job')
            if callable(self.integrations.get('OP-JOBS')):
                read_context = {**context,'operation_id':'OP-JOBS'}
                query['limit'] = 200
                jobs,seen = [],set()
                while True:
                    _,page = self._adapter(db,'OP-JOBS',read_context,query,{})
                    jobs.extend(page['items'])
                    cursor = page.get('next_cursor')
                    if cursor is None:
                        break
                    if cursor in seen:
                        _fail('BACKEND_UNAVAILABLE','Job observation adapter repeated a collection cursor.')
                    seen.add(cursor)
                    query['cursor'] = cursor
            running = sorted({job['job_id'] for job in jobs if job['state'] not in ('succeeded','failed','cancelled','interrupted')})
            if running and not input['acknowledge_running_jobs']:
                _fail('ACTIVE_JOBS','Acknowledge the owned jobs that will continue running.')
            db.execute('UPDATE compositions SET archived=?,metadata_revision=metadata_revision+1,updated=? WHERE id=?',(int(input['archived']),_now(),comp['id']))
            return 200,dict(composition=self._summary(db,self._composition(db,native,comp['id'])),catalog_revision=self._bump_catalog(db,native),continuing_job_ids=running)
        if op == 'OP-TRANSACTION':
            if not isinstance(input['operations'],list) or not 1 <= len(input['operations']) <= 1000:
                _fail('LIMIT_EXCEEDED','Use between one and 1000 typed edit operations.')
            _uuid(input['gesture_id'])
            if not isinstance(input['summary'],str) or len(input['summary']) > 1000 or input['dependency_policy'] != 'reject_unlisted' or not isinstance(input['acknowledged_dependency_ids'],list):
                _fail('INVALID_ARGUMENT','Transaction metadata or dependency policy is invalid.')
            graph = self._hydrate_assets(self._graph(self._version(db,comp)),context,input.get('asset_refs',[]))
            context['acknowledged_dependency_ids'] = input['acknowledged_dependency_ids']
            result = self._graph_call(apply_operations,graph,input['operations'],context=context)
            if isinstance(result,tuple):
                graph, info = result
            elif isinstance(result,dict) and 'graph' in result:
                graph, info = result['graph'],result
            else:
                graph, info = result,{}
            data = self._publish(db,context,graph,comp,affected=info.get('affected_entities',[]),created_ids=info.get('created_ids',{}))
            data.update(affected_frame_ranges=info.get('affected_frame_ranges',[]),invalidated_refs=info.get('invalidated_refs',[]))
            return 200,data
        if op == 'OP-UNDO':
            if input['direction'] not in ('undo','redo'):
                _fail('INVALID_ARGUMENT','Undo direction is invalid.')
            token = db.execute('SELECT * FROM undo WHERE id=? AND native=? AND composition=? AND principal=?',
                               (input['undo_token'],native,comp['id'],context['principal'])).fetchone()
            if not token:
                _fail('NOT_FOUND','Undo capability not found.')
            if token['expires'] < _now():
                _fail('UNDO_EXPIRED','Undo token expired.')
            if token['base'] != comp['head'] or token['direction'] != input['direction']:
                _fail('UNDO_CONFLICT','Intervening edits make this undo token incompatible.')
            target = self._version(db,comp,token['target'])
            data = self._publish(db,context,self._graph(target),comp)
            opposite = 'redo' if input['direction'] == 'undo' else 'undo'
            db.execute('UPDATE undo SET direction=? WHERE id=?',(opposite,data['undo_token']))
            return 200,data
        if op == 'OP-RECOVER-VERSION':
            _bool(input['acknowledge_invalidations'])
            if not input['acknowledge_invalidations']:
                _fail('INVALIDATIONS_NOT_ACKNOWLEDGED','Explicit invalidation acknowledgement is required.')
            allowed = db.execute('SELECT 1 FROM undo WHERE native=? AND composition=? AND principal=? AND target=? AND expires>=?',
                                 (native,comp['id'],context['principal'],input['source_version_id'],_now())).fetchone()
            if not allowed:
                _fail('RECOVERY_SOURCE_UNAVAILABLE','Source is not referenced by an authorized recovery context.')
            return 200,self._publish(db,context,self._graph(self._version(db,comp,input['source_version_id'])),comp)
        if op == 'OP-PROPOSAL-DECIDE':
            return self._proposal_decide(db,context,input,pre,comp)
        _fail('NOT_FOUND','No such metadata command.')

    def _settings(self, db) -> dict[str, Any]:
        row = db.execute('SELECT * FROM settings WHERE id=1').fetchone()
        defaults = dict(adapter_preferences=[],output_profile_refs=[],font_binding_refs=[],model_binding_refs=[],
                        default_sample_rate=48000,default_fps=dict(num=30,den=1))
        return dict(settings_revision=row['revision'] if row else 1,preferences=json.loads(row['value']) if row else defaults,
                    credential_bindings=[],platform=dict(backend='host'),readiness=dict(state='unknown',launch_effects=[]))

    def _save_settings(self, db, input):
        prefs = input['preferences']
        _fields(prefs,'adapter_preferences output_profile_refs font_binding_refs model_binding_refs default_sample_rate default_fps')
        _integer(prefs['default_sample_rate'],8000,384000)
        from math import gcd
        fps = prefs['default_fps']; _fields(fps,'num den')
        _integer(fps['num']); _integer(fps['den'])
        if gcd(fps['num'],fps['den']) != 1:
            _fail('SETTING_UNSUPPORTED','Default fps must be a reduced positive rational.')
        available = set(self.integrations.get('settings_bindings',()))
        for key in ('adapter_preferences','output_profile_refs','font_binding_refs','model_binding_refs'):
            if not isinstance(prefs[key],list):
                _fail('SETTING_UNSUPPORTED','Preference selections must be lists.')
            for binding in prefs[key]:
                if isinstance(binding,dict):
                    _fields(binding,'binding_id')
                identity = binding if isinstance(binding,str) else binding.get('binding_id') if isinstance(binding,dict) else None
                if identity not in available:
                    _fail('BINDING_UNKNOWN','Preference references an unadvertised host binding.')
        revision = self._settings(db)['settings_revision'] + 1
        db.execute('INSERT INTO settings VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,value=excluded.value',(revision,_json(prefs)))
        return {**self._settings(db),'invalidated_readiness_ids':[]}

    def _supported(self):
        result = LOCAL_COMMANDS | BUILTIN_READS | {'OP-JOB-CANCEL'}
        result |= {op for _,_,op,_,_,_ in ROUTES if callable(self.integrations.get(op))}
        if self.integrations.get('root_broker') is not None:
            result.add('OP-ROOT-BROWSE')
        return sorted(result)

    def _read(self, db, op, context, query):
        native = context['scope'].get('native_project_id')
        if op == 'OP-ROOT-BROWSE' and op not in self.integrations:
            broker = self.integrations.get('root_broker')
            if broker is None:
                self._blocked(op)
            broker_query = copy.deepcopy(query)
            binding = _hash(dict(scope=context['scope'],params=context['params'],filters={k:v for k,v in query.items() if k not in ('limit','cursor')}))
            if query.get('cursor'):
                cursor = db.execute("SELECT * FROM cursors WHERE id=? AND principal=? AND kind='root_browse'",(query['cursor'],context['principal'])).fetchone()
                if not cursor:
                    _fail('CURSOR_SCOPE_MISMATCH','Folder cursor is not valid in this authenticated scope.')
                state = json.loads(cursor['value'])
                if cursor['expires']<_now():
                    _fail('CURSOR_EXPIRED','Folder snapshot cursor expired.')
                if state['binding']!=binding:
                    _fail('CURSOR_SCOPE_MISMATCH','Folder cursor scope or filters changed.')
                broker_query['cursor'] = state['broker_cursor']
            data = broker.browse(native,context['params']['root_id'],**broker_query)
            if data.get('next_cursor'):
                opaque = _id('cursor')
                state = dict(binding=binding,broker_cursor=data['next_cursor'])
                db.execute('INSERT INTO cursors VALUES(?,?,?,?,?,?)',(opaque,context['principal'],native,'root_browse',_json(state),_later(900)))
                data['next_cursor'] = opaque
            return 200,data
        if op == 'OP-BOOTSTRAP':
            if query['client_contract'] != API_VERSION:
                _fail('CONTRACT_INCOMPATIBLE','Only ui.v1 is supported.')
            if query['client_kind'] not in ('desktop','web') or query.get('connection_id',self.connection_id) != self.connection_id:
                _fail('SCOPE_MISMATCH','Client or connection assertion is invalid.')
            host = copy.deepcopy(self.integrations.get('host_capabilities',{}))
            qualified = context.get('qualified_media_transports', ())
            host['media_transports'] = [transport for transport in ('same_origin_cookie', 'authenticated_blob')
                                        if transport in qualified and
                                        (transport != 'authenticated_blob' or callable(self.integrations.get('OP-MEDIA-CHUNK')))]
            host['range_media'] = 'same_origin_cookie' in host['media_transports']
            host['authenticated_blob'] = 'authenticated_blob' in host['media_transports']
            return 200,dict(scope=context['scope'],api_schemas=[API_VERSION],content_schemas=['composition.v1'],
                            runtime_identity=runtime_identity(),
                            canonicalizer='jcs-sha256.v1',compiler_schema='motion-project-documents.v1',
                            transport_capabilities=dict(socket=bool(host.get('socket')),poll=True,binary_upload=bool(host.get('binary_upload')),
                                                        range_media=host['range_media'],authenticated_blob=host['authenticated_blob'],
                                                        client_download=bool(host.get('client_download')),scope_pinning=True),
                            host_seams=host,limits=dict(page_default=50,page_max=200,transaction_bytes=1048576,transaction_operations=1000,cursor_ttl_seconds=900,
                                                       command_retention_days=30,idempotency_tombstone_days=90,poll_wait_ms_max=25000,media_blob_bytes=64*1024*1024),
                            settings_revision=self._settings(db)['settings_revision'],quota_revision=1,
                            registry_revision=_hash([self._native_public(v) for v in self._registry().values()]),schemas=schema_catalog(),
                            supported_operations=self._supported(),
                            auth_mode='host_authenticated',blockers=self._host_blockers(host))
        if op == 'OP-PROJECTS':
            _bool(query['include_archived'])
            records = self._registry()
            items = [self._native_public(v) for v in records.values() if query['include_archived'] or not v['archived']]
            return 200,{**self._page(db,context,query,items),'active_native_project_id':None,'registry_snapshot_token':_hash(items)}
        if op == 'OP-PROJECT-CONTEXT':
            record = self._native_public(context['native_record'])
            return 200,dict(project=record,catalog_revision=self._catalog(db,native)['revision'],quota_revision=1,roots=record['roots'],
                            supported_operations=self._supported(),denial_reasons=['PROJECT_ARCHIVED'] if record['archived'] else [])
        if op == 'OP-COMPOSITIONS':
            _bool(query['include_archived'])
            rows = db.execute('SELECT * FROM compositions WHERE native=? ORDER BY created,id',(native,)).fetchall()
            items = [self._summary(db,dict(row)) for row in rows if query['include_archived'] or not row['archived']]
            return 200,{**self._page(db,context,query,items),'catalog_revision':self._catalog(db,native)['revision']}
        if op == 'OP-COMPOSITION-GET':
            comp = self._composition(db,native,context['params']['composition_id'])
            version = self._version(db,comp,query.get('version_id'))
            etag = _hash(dict(composition=self._summary(db,comp),version_sha256=version['sha256']))
            return 200,dict(composition=self._summary(db,comp),version=version,is_head=version['version_id']==comp['head'],etag=etag,
                            constraints=dict(read_only=bool(comp['archived'] or context['native_record']['archived'] or not self._permission(context,'edit'))),
                            not_modified=query.get('known_etag')==etag)
        if op == 'OP-DOCUMENT-GET':
            comp = self._composition(db,native,context['params']['composition_id'])
            version = self._version(db,comp,query['version_id'])
            document = next((item for item in version['production_documents']
                             if item['document_id'] == context['params']['document_id']),None)
            if document is None:
                _fail('NOT_FOUND','Document is not referenced by the authorized saved version.')
            return 200,copy.deepcopy(document)
        if op == 'OP-SETTINGS-GET':
            return 200,self._settings(db)
        if op == 'OP-COMMAND-STATUS':
            return 200,self._status(db,context,context['params']['command_id'],query['request_sha256'])
        if op == 'OP-RECEIPT':
            row = db.execute('SELECT value FROM receipts WHERE id=? AND native=?',(context['params']['receipt_id'],native)).fetchone()
            if not row:
                _fail('NOT_FOUND','Receipt not found.')
            return 200,json.loads(row['value'])
        if op == 'OP-EVENT-POLL':
            return 200,self._events(db,context,query)
        if op == 'OP-RECOVERY':
            if not isinstance(query['pending_command_ids'],list) or len(query['pending_command_ids']) > 200:
                _fail('INVALID_ARGUMENT','Provide at most 200 exact pending command IDs.')
            comp = self._composition(db,native,context['params']['composition_id'])
            statuses = []
            for cid in query['pending_command_ids']:
                _uuid(cid)
                row = db.execute('SELECT * FROM commands WHERE command_id=? AND native=? AND principal=?',(cid,native,context['principal'])).fetchone()
                statuses.append(self._command_projection(dict(row)) if row else dict(command_id=cid,status='not_found'))
            undo = db.execute('SELECT target FROM undo WHERE native=? AND composition=? AND principal=? AND expires>=?',(native,comp['id'],context['principal'],_now())).fetchall()
            return 200,dict(composition=self._summary(db,comp),version=self._version(db,comp),commands=statuses,
                            checkpoint_refs=[dict(version_id=r['target'],kind='undo_context') for r in undo],recovery_actions=['refresh','preserve_draft','query_command','explicit_reapply'])
        if op == 'OP-CAPABILITIES':
            if query['mode'] != 'cached':
                _fail('PASSIVE_MODE_REQUIRED','Capabilities are passive cached facts only.')
            if op in self.integrations:
                return self._adapter(db,op,context,query,{})
            schemas = schema_catalog()
            items = [dict(kind=kind,**record) for kind,record in schemas.items()]
            return 200,dict(**self._page(db,context,query,items),launch_effects=[],
                            readiness='unknown',blockers=[dict(code='CAPABILITY_REGISTRY_UNAVAILABLE')],supported_operations=sorted(LOCAL_COMMANDS))
        if op in ('OP-PROPOSALS','OP-PROPOSAL-GET'):
            return 200,self._proposals(db,context,query,op)
        if op in self.integrations:
            return self._adapter(db,op,context,query,{})
        retained = self._retained_resource(db,op,context,query)
        if retained is not None:
            return 200,retained
        if op == 'OP-JOBS':
            actual = self._jobs(db,context,query)
            cached = self._resource_items(db,context,query,'job')
            combined = {row['job_id']:row for row in cached}
            combined.update({row['job_id']:row for row in actual})
            page = self._page(db,context,query,list(combined.values()))
            if cached:
                page['observation'] = dict(kind='cached',observed_at=_now(),live_observation_available=False)
            return 200,page
        if op == 'OP-JOB-GET':
            return 200,self._job_get(db,context,query)
        if op == 'OP-CHECKPOINTS':
            # Current JobStore retains real attempts/results but does not
            # advertise resumable checkpoints. An empty retained collection is
            # truthful; synthesizing one from attempt state would not be.
            self._find_job(db,context)
            return 200,self._page(db,context,query,[])
        if op in COLLECTIONS:
            resource_kind = {'OP-MASTERS':'master','OP-PACKAGES':'package','OP-DELIVERY-SETS':'delivery_set'}.get(op)
            if resource_kind:
                retained_items = self._resource_items(db,context,query,resource_kind)
                if retained_items:
                    page = self._page(db,context,query,retained_items)
                    page['observation'] = dict(kind='cached',observed_at=_now(),live_observation_available=False)
                    return 200,page
            # For a freshly-owned private composition these collections really
            # are empty. Existing engine records require the explicit public
            # projection adapter; never hide them behind a fake empty list.
            if op == 'OP-ASSETS':
                items = self._assets(db,context,query)
                return 200,self._page(db,context,query,items)
            if self._has_engine_records(db,context,op):
                self._blocked(op)
            return 200,self._page(db,context,query,[])
        self._blocked(op)

    @staticmethod
    def _host_blockers(host):
        return [dict(code='HOST_SEAM_UNAVAILABLE',seam=key) for key in ('native_project_selection','right_dock','bottom_timeline','composer','approval_bridge') if not host.get(key)]

    def _blocked(self, op):
        code = 'APPROVAL_BRIDGE_UNAVAILABLE' if op in ('OP-APPROVAL-REQUEST','OP-AUTHORITY-REQUEST','OP-APPROVAL-STATUS','OP-AUTHORITY-STATUS') else 'INTEGRATION_UNAVAILABLE'
        _fail(code,'This operation requires a qualified trusted host/engine adapter.',dict(operation_id=op,blockers=[dict(code=code,operation_id=op)]))

    def _resource_items(self, db, context, query, kind):
        cid = query.get('composition_id',context['params'].get('composition_id',''))
        rows = db.execute('SELECT * FROM resources WHERE kind=? AND native=? AND (composition=? OR ?=\'\') ORDER BY observed,id',
                          (kind,context['scope']['native_project_id'],cid,cid)).fetchall()
        items = []
        for row in rows:
            item = json.loads(row['value'])
            if any(key in query and query[key]!=item.get(key) for key in ('state','kind','variant_id','candidate_id')):
                continue
            item['observation'] = dict(kind='cached',observed_at=row['observed'],live_observation_available=False)
            items.append(item)
        if kind=='master':
            current = {}
            for item in items:
                if item['master_revision']>current.get(item['master_id'],{}).get('master_revision',0):
                    current[item['master_id']] = item
            items = list(current.values())
        return items

    def _retain_adapter_result(self, db, context, data):
        # Retain only named public resources actually returned by an accepted
        # adapter, never invent a future manifest/check/result from intent.
        resources = {
            'OP-UPLOAD-CREATE':('upload','upload_id'),
            'OP-UPLOAD-CHUNK':('upload','upload_id'),
            'OP-UPLOAD-COMMIT':('upload','upload_id'),
            'OP-UPLOAD-ABORT':('upload','upload_id'),
            'OP-HANDOFF-PREPARE':('handoff','handoff_id'),
            'OP-AUTHORITY-REQUEST':('authority_request','authority_request_id'),
            'OP-PREFLIGHT':('preflight','preflight_id'),
            'OP-APPROVAL-REQUEST':('approval_request','approval_request_id'),
            'OP-JOB-LAUNCH':('job','job_id'),'OP-JOB-CANCEL':('job','job_id'),
            'OP-JOB-RECOVER':('job','job_id'),
            'OP-RENDER-PREPARE':('render_snapshot','snapshot_id'),
            'OP-RENDER-LAUNCH':('job','job_id'),
            'OP-CANDIDATE-CHECK':('job','job_id'),
            'OP-MASTER-PROMOTE':('master','master_id'),
            'OP-PACKAGE-CREATE':('package','package_id'),
            'OP-PACKAGE-VALIDATE':('package','package_id'),
            'OP-DELIVERY-SET-CREATE':('delivery_set','delivery_set_id'),
            'OP-DELIVERY-START':('delivery_set','delivery_set_id'),
            'OP-DELIVERY-RECONCILE':('delivery_set','delivery_set_id'),
        }
        spec = resources.get(context['operation_id'])
        if spec is None:
            return
        kind,identity = spec
        payload = data.get(kind,data)
        if not isinstance(payload,dict) or not isinstance(payload.get(identity),str) or not PUBLIC_RE.fullmatch(payload[identity]):
            return  # The callback may return only a different owned operation.
        cid = payload.get('composition_id',context['params'].get('composition_id',''))
        native = context['scope'].get('native_project_id','')
        if cid:
            self._composition(db,native,cid)
            payload = {**payload,'composition_id':cid}
        if context['operation_id']=='OP-JOB-LAUNCH' and context.get('version'):
            if payload.get('version_id',context['version']['version_id'])!=context['version']['version_id']:
                _fail('STALE_DEPENDENCY','Accepted job is not pinned to the requested saved version.',effect='unknown')
            payload = {**payload,'version_id':context['version']['version_id']}
        record_id = payload[identity] + (':' + str(payload['master_revision']) if kind=='master' else '')
        existing = db.execute('SELECT value FROM resources WHERE kind=? AND id=? AND native=? AND composition=?',
                              (kind,record_id,native,cid)).fetchone()
        if existing:
            previous = json.loads(existing['value'])
            # A partial observation cannot erase retained immutable evidence.
            for key in ('version_id','snapshot_id','snapshot_sha256','preflight_sha256','manifest_sha256','plan_sha256','effects_sha256'):
                if key in previous and key in payload and previous[key]!=payload[key]:
                    _fail('HASH_MISMATCH','Adapter observation changes a retained frozen identity.',effect='unknown')
            payload = {**previous,**payload}
        db.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?) ON CONFLICT(kind,id,native,composition) DO UPDATE SET value=excluded.value,observed=excluded.observed',
                   (kind,record_id,native,cid,context['principal'],_json(payload),_now()))

    def _retained_resource(self, db, op, context, query):
        resources = {
            'OP-UPLOAD-STATUS':('upload','upload_id'),
            'OP-HANDOFF-STATUS':('handoff','handoff_id'),
            'OP-AUTHORITY-STATUS':('authority_request','authority_request_id'),
            'OP-PREFLIGHT-GET':('preflight','preflight_id'),
            'OP-APPROVAL-STATUS':('approval_request','approval_request_id'),
            'OP-JOB-GET':('job','job_id'),
            'OP-RENDER-SNAPSHOT-GET':('render_snapshot','snapshot_id'),
            'OP-MASTER-GET':('master','master_id'),
            'OP-PACKAGE-GET':('package','package_id'),
            'OP-DELIVERY-SET-GET':('delivery_set','delivery_set_id'),
        }
        spec = resources.get(op)
        if spec is None:
            return None
        kind,identity = spec
        if kind=='job':
            try:
                self._find_job(db,context)
                return None  # Prefer an actual owned JobStore observation.
            except ContractError as exc:
                if exc.code!='NOT_FOUND':
                    raise
        cid = context['params'].get('composition_id','')
        record_id = context['params'][identity] + (':' + str(query['master_revision']) if kind=='master' else '')
        row = db.execute('SELECT * FROM resources WHERE kind=? AND id=? AND native=? AND (composition=? OR ?=\'\')',
                         (kind,record_id,context['scope'].get('native_project_id',''),cid,cid)).fetchone()
        if not row:
            return None
        # Approval/authority observations are scoped to their actual requesting
        # principal; another caller's request is not a reusable grant.
        if kind in ('authority_request','approval_request','upload') and row['principal']!=context['principal']:
            _fail('NOT_FOUND','Resource is not owned by this authenticated principal.')
        data = json.loads(row['value'])
        data['observation'] = dict(kind='cached',observed_at=row['observed'],live_observation_available=False)
        if kind in ('preflight','render_snapshot'):
            data['launchable'] = False
            data['launch_blockers'] = [dict(code='LIVE_DEPENDENCY_RECHECK_REQUIRED')]
        if kind=='handoff' and data.get('state')=='prepared':
            data['observation_gap'] = 'Trusted host send/result correlation is unavailable; preparation is not execution.'
        return data

    def _adapter(self, db, op, context, input, pre) -> tuple[int, dict[str, Any]]:
        callback = self.integrations.get(op)
        if not callable(callback):
            if op == 'OP-JOB-CANCEL':
                return self._cancel_job(db,context,input,pre)
            self._blocked(op)
        # Detached trusted context; private objects never enter a response.
        trusted = {k:copy.deepcopy(v) if k != 'project_store' else v for k,v in context.items()}
        trusted = self._render_context(db,trusted,assets=op in ('OP-PREFLIGHT','OP-RENDER-PREPARE'))
        result = callback(trusted,copy.deepcopy(input),copy.deepcopy(pre))
        status, data = result if isinstance(result,tuple) and len(result)==2 else (200,result)
        if status not in (200,201,202) or not isinstance(data,dict):
            _fail('BACKEND_UNAVAILABLE','Adapter returned no valid public result.',effect='unknown' if context.get('command_id') else 'none')
        _safe_json(data)
        self._assert_public(data,context)
        if status == 202 and not any(key in data for key in ('job_id','job','operation_id','approval_request_id','authority_request_id','transfer_id','package_id')):
            _fail('BACKEND_UNAVAILABLE','Asynchronous adapter acceptance lacks a durable operation identity.',effect='unknown')
        return status,data

    def _assert_public(self, data, context):
        forbidden = {'private_project_id','project_id','storage','absolute_path','relative_path','local_path','delivery_handle','password','token','api_key','credentials','environment'}
        private_id = context.get('private_project_id')
        def visit(value):
            if isinstance(value,dict):
                if forbidden.intersection(value):
                    _fail('BACKEND_UNAVAILABLE','Adapter attempted to expose private engine state.',effect='unknown' if context.get('command_id') else 'none')
                for item in value.values():
                    visit(item)
            elif isinstance(value,list):
                for item in value:
                    visit(item)
            elif isinstance(value,str) and ((private_id and private_id in value) or str(self.directory) in value):
                _fail('BACKEND_UNAVAILABLE','Adapter attempted to expose a private binding.',effect='unknown' if context.get('command_id') else 'none')
        visit(data)

    def _page(self, db, context, query, items):
        limit = _integer(query.get('limit',50),1,200)
        native = context['scope'].get('native_project_id','')
        binding = _hash(dict(scope=context['scope'],operation=context['operation_id'],params=context['params'],filters={k:v for k,v in query.items() if k not in ('cursor','limit')}))
        offset = 0
        if query.get('cursor'):
            cursor = db.execute('SELECT * FROM cursors WHERE id=? AND principal=?',(query['cursor'],context['principal'])).fetchone()
            if not cursor:
                _fail('CURSOR_SCOPE_MISMATCH','Cursor is not valid for this authenticated scope.')
            if cursor['expires'] < _now():
                _fail('CURSOR_EXPIRED','Start a fresh collection snapshot.')
            state = json.loads(cursor['value'])
            if state['binding'] != binding:
                _fail('CURSOR_SCOPE_MISMATCH','Cursor filters or scope changed.')
            snapshot_id, offset = state['snapshot_id'],state['offset']
            snapshot = db.execute('SELECT * FROM snapshots WHERE id=? AND principal=? AND native=?',(snapshot_id,context['principal'],native)).fetchone()
            if not snapshot or snapshot['expires'] < _now():
                _fail('CURSOR_EXPIRED','Collection snapshot expired.')
            items = json.loads(snapshot['value'])
        else:
            snapshot_id = _id('page')
            items = sorted(copy.deepcopy(items),key=lambda item:(item.get('created_at',''),next((str(item[k]) for k in sorted(item) if k.endswith('_id')), _json(item))))
            db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?)',(snapshot_id,context['principal'],native,binding,_json(items),_later(900)))
        page = items[offset:offset+limit]
        next_cursor = None
        if offset+limit < len(items):
            next_cursor = _id('cursor')
            state = dict(binding=binding,snapshot_id=snapshot_id,offset=offset+limit)
            db.execute('INSERT INTO cursors VALUES(?,?,?,?,?,?)',(next_cursor,context['principal'],native,'page',_json(state),_later(900)))
        return dict(items=page,next_cursor=next_cursor,has_more=next_cursor is not None,snapshot_id=snapshot_id,total=len(items))

    def _event_cursor(self, db, native, sequence=None):
        if native is None:
            return None
        if sequence is None:
            sequence = db.execute('SELECT COALESCE(MAX(sequence),0) FROM events WHERE native=?',(native,)).fetchone()[0]
        # Persist opaque cursor, rather than encoding native identity as a token.
        cursor = 'eventcursor_' + _hash([self.owner,self.connection_id,native,self._catalog(db,native)['epoch'],sequence])[:40]
        value = dict(sequence=sequence,scope=self._scope(native),epoch=self._catalog(db,native)['epoch'])
        db.execute('INSERT OR IGNORE INTO cursors VALUES(?,?,?,?,?,?)',(cursor,'',native,'event',_json(value),_later(120*86400)))
        return cursor

    def _events(self, db, context, query):
        native = context['scope']['native_project_id']
        _integer(query['wait_ms'],0,25000)
        limit = _integer(query.get('limit',50),1,200)
        after = query['after_cursor']
        sequence = 0
        if after is not None:
            row = db.execute("SELECT * FROM cursors WHERE id=? AND kind='event'",(after,)).fetchone()
            if not row:
                _fail('EVENT_GAP','The event cursor is no longer retained.',dict(earliest_cursor=self._event_cursor(db,native,0),stream_epoch=self._catalog(db,native)['epoch']))
            state = json.loads(row['value'])
            if state['scope'] != context['scope'] or state['epoch'] != self._catalog(db,native)['epoch']:
                _fail('CURSOR_SCOPE_MISMATCH','Event cursor belongs to another scope or epoch.')
            sequence = state['sequence']
        examined = db.execute('SELECT * FROM events WHERE native=? AND sequence>? ORDER BY sequence LIMIT ?',(native,sequence,limit+1)).fetchall()
        selected = examined[:limit]
        items = []
        for row in selected:
            value = json.loads(row['value'])
            # Stored connection is provenance; subscription scope is the current
            # authenticated alias for the same backend/profile/native owner.
            value['scope'] = context['scope']
            if not query.get('composition_id') or value.get('composition_id') == query['composition_id']:
                items.append(value)
        last = selected[-1]['sequence'] if selected else sequence
        return dict(items=items,next_cursor=self._event_cursor(db,native,last),stream_epoch=self._catalog(db,native)['epoch'],
                    earliest_cursor=self._event_cursor(db,native,0),has_more=len(examined)>limit)

    def _status(self, db, context, cid, expected_hash):
        _uuid(cid)
        if not isinstance(expected_hash,str) or not HASH_RE.fullmatch(expected_hash):
            _fail('INVALID_ARGUMENT','A frozen request SHA-256 is required.')
        row = db.execute('SELECT * FROM commands WHERE principal=? AND native=? AND command_id=?',
                         (context['principal'],context['scope'].get('native_project_id',''),cid)).fetchone()
        if not row or json.loads(row['scope']) != context['scope']:
            _fail('NOT_FOUND','Command not found in this authenticated scope.')
        if row['request_sha'] != expected_hash:
            _fail('COMMAND_HASH_MISMATCH','Command hash differs from frozen intent.')
        if row['expires'] < _now() and row['status'] in ('committed','failed'):
            _fail('COMMAND_EXPIRED','Command result expired; its key remains non-reusable.')
        return self._command_projection(dict(row))

    @staticmethod
    def _command_projection(row):
        response = json.loads(row['response']) if row.get('response') else {}
        return dict(command_id=row['command_id'],operation_id=row['operation'],status=row['status'],effect_state=row['effect'],
                    receipt_id=row['receipt'],result_refs=UIService._refs(response.get('data',{})),request_sha256=row['request_sha'],
                    retention_expires_at=row['expires'],recovery_actions=['query_receipt','refresh'] if row['status']=='committed' else ['reconcile_frozen_intent'])

    def _proposals(self, db, context, query, op):
        native, cid = context['scope']['native_project_id'],context['params']['composition_id']
        if op in self.integrations:
            # Trusted admission validates actual host/tool correlation. Persist
            # that immutable admitted proposal; no browser admission endpoint.
            _, payload = self._adapter(db,op,context,query,{})
            records = payload.get('items',[]) if op == 'OP-PROPOSALS' else [payload]
            for proposal in records:
                required = 'proposal_id entity_revision base_version_id base_composition_revision operations dependency_hashes expected_effects source_evidence expires_at validity diff'
                _fields(proposal,required,'sha256 state')
                if not proposal['source_evidence'] or not PUBLIC_RE.fullmatch(proposal['proposal_id']):
                    _fail('EVIDENCE_MISSING','A proposal requires trusted captured source evidence.')
                self._version(db,self._composition(db,native,cid),proposal['base_version_id'])
                proposal = copy.deepcopy(proposal)
                actual_sha = _hash({k:v for k,v in proposal.items() if k not in ('sha256','state')})
                if proposal.get('sha256',actual_sha) != actual_sha:
                    _fail('HASH_MISMATCH','Admitted proposal bytes differ from the immutable digest.')
                proposal['sha256'] = actual_sha
                db.execute('INSERT OR IGNORE INTO proposals VALUES(?,?,?,?,?,?)',(proposal['proposal_id'],native,cid,_json(proposal),'pending',proposal['entity_revision']))
        if op == 'OP-PROPOSAL-GET':
            row = db.execute('SELECT * FROM proposals WHERE id=? AND native=? AND composition=?',(context['params']['proposal_id'],native,cid)).fetchone()
            if not row:
                _fail('NOT_FOUND','Admitted proposal not found.')
            return {**json.loads(row['value']),'state':row['state'],'entity_revision':row['revision']}
        if query['state'] not in ('pending','applied','rejected','stale','all'):
            _fail('INVALID_ARGUMENT','Proposal state filter is invalid.')
        rows = db.execute('SELECT * FROM proposals WHERE native=? AND composition=? ORDER BY id',(native,cid)).fetchall()
        head = self._composition(db,native,cid)['head']
        items = []
        for row in rows:
            value = json.loads(row['value'])
            state = 'stale' if row['state']=='pending' and value['base_version_id'] != head else row['state']
            if query['state'] in ('all',state):
                items.append({**value,'state':state,'entity_revision':row['revision']})
        return self._page(db,context,query,items)

    def _proposal_decide(self, db, context, input, pre, comp):
        row = db.execute('SELECT * FROM proposals WHERE id=? AND native=? AND composition=?',
                         (context['params']['proposal_id'],comp['native'],comp['id'])).fetchone()
        if not row:
            _fail('NOT_FOUND','Admitted proposal not found.')
        value = json.loads(row['value'])
        if row['revision'] != pre['entity_revision']:
            _fail('REVISION_CONFLICT','Proposal revision changed.')
        if row['state'] != 'pending':
            _fail('PROPOSAL_ALREADY_DECIDED','Proposal already has an editorial decision.')
        if value['expires_at'] < _now():
            _fail('PROPOSAL_EXPIRED','Proposal expired.')
        if input['proposal_sha256'] != value['sha256']:
            _fail('PROPOSAL_STALE','Proposal digest changed.')
        decision = input['decision']
        if decision not in ('apply','reject'):
            _fail('INVALID_ARGUMENT','An explicit apply or reject decision is required.')
        if decision == 'apply':
            if value['base_version_id'] != comp['head'] or value['base_composition_revision'] != comp['revision']:
                _fail('PROPOSAL_STALE','Proposal is based on another saved head.')
            if value['dependency_hashes']:
                resolver = self.integrations.get('dependency_resolver')
                if not callable(resolver) or resolver(copy.deepcopy(context),copy.deepcopy(value['dependency_hashes'])) is not True:
                    _fail('PROPOSAL_STALE','Exact proposal dependency availability could not be re-established.')
            graph = self._graph(self._version(db,comp))
            context['acknowledged_dependency_ids'] = input['acknowledged_dependency_ids']
            result = self._graph_call(apply_operations,graph,value['operations'],context=context)
            graph = result[0] if isinstance(result,tuple) else result.get('graph',result)
            data = self._publish(db,context,graph,comp)
        else:
            data = dict(composition=self._summary(db,comp))
        db.execute('UPDATE proposals SET state=?,revision=revision+1 WHERE id=?',('applied' if decision=='apply' else 'rejected',row['id']))
        return 200,{**data,'proposal_id':row['id'],'decision':decision,'entity_revision':row['revision']+1}

    def _owned_compositions(self, db, context, query) -> list[dict[str, Any]]:
        native = context['scope']['native_project_id']
        cid = query.get('composition_id',context['params'].get('composition_id'))
        if cid:
            return [self._composition(db,native,cid)]
        return [dict(r) for r in db.execute('SELECT * FROM compositions WHERE native=?',(native,))]

    def _jobs(self, db, context, query):
        from .jobs import JobStore
        items = []
        fs = self.store._filesystem()
        for comp in self._owned_compositions(db,context,query):
            if fs is None:
                continue
            base = self.store._base(comp['private_id'])
            for filename in fs.names(base + '/jobs'):
                if not filename.endswith('.json'):
                    continue
                bundle = JobStore(self.store).read(comp['private_id'],filename[:-5])
                job = bundle['job']
                # IDs are public-safe opaque backend-generated job IDs. The
                # internal owner/revision/plan refs are translated, never leaked.
                pin = db.execute('SELECT id FROM versions WHERE composition=? AND private_revision=? ORDER BY revision LIMIT 1',
                                 (comp['id'],job['project_revision'])).fetchone()
                if not pin:
                    _fail('INTEGRATION_UNAVAILABLE','Job has no retained public saved-version binding.')
                state = job['state']
                if query.get('state') and state != query['state']:
                    continue
                kind = bundle.get('plan_record',{}).get('operation','production')
                if query.get('kind') and kind != query['kind']:
                    continue
                items.append(dict(job_id=job['job_id'],entity_revision=job['job_revision'],kind=kind,
                                  composition_id=comp['id'],version_id=pin['id'],plan_id=None,state=state,attempts=[],
                                  progress=dict(phase=state,completed=sum(n['state']=='succeeded' for n in job.get('node_states',[])),total=len(job.get('node_states',[])),percent_milli=None,source='owned_job_store',observed_at=job.get('updated_at',_now())),
                                  eta=None,effect_state='committed' if state=='succeeded' else 'unknown' if state=='reconciliation_required' else 'pending',
                                  cancel=dict(requested=bool(job.get('cancel',{}).get('requested')),outcome=job.get('cancel',{}).get('disposition')),checkpoint_ids=[],result_refs=[],error=None,
                                  evidence_gaps=['attempt/checkpoint/output projection requires qualified job adapter']))
        return items

    def _find_job(self, db, context) -> tuple[dict[str, Any], dict[str, Any]]:
        from .jobs import JobStore
        jid = context['params']['job_id']
        fs = self.store._filesystem()
        for comp in self._owned_compositions(db,context,{}):
            if fs is not None and jid + '.json' in fs.names(self.store._base(comp['private_id']) + '/jobs'):
                return comp,JobStore(self.store).read(comp['private_id'],jid)
        _fail('NOT_FOUND','Owned job not found.')

    def _job_get(self, db, context, query):
        comp,bundle = self._find_job(db,context)
        items = self._jobs(db,context,dict(composition_id=comp['id']))
        value = next(item for item in items if item['job_id']==context['params']['job_id'])
        if query.get('known_entity_revision') == value['entity_revision']:
            return dict(job_id=value['job_id'],entity_revision=value['entity_revision'],not_modified=True)
        value['attempts'] = [{k:attempt.get(k) for k in ('attempt_id','node_id','attempt_number','submission_state','remote_state','started_at','ended_at')}
                             for attempt in bundle.get('attempts',{}).values()]
        value['nodes'] = [{k:node.get(k) for k in ('node_id','state','attempt_id')} for node in bundle['job'].get('node_states',[])]
        error = bundle['job'].get('error')
        value['error'] = dict(code=error['code'],message='Owned job reported an engine error.',effect_state=error.get('effect','unknown')) if error else None
        value['recovery_actions'] = ['explicit_reconcile'] if bundle['job']['state']=='interrupted' or bundle['job'].get('submission_state')=='uncertain' else []
        return value

    def _cancel_job(self, db, context, input, pre):
        from .jobs import JobStore
        if input['mode'] != 'best_effort_owned' or not isinstance(input['reason'],str):
            _fail('INVALID_ARGUMENT','Only explicit best-effort owned cancellation is allowed.')
        if not self._permission(context,'edit'):
            _fail('PERMISSION_DENIED','The authenticated principal cannot cancel this job.')
        comp,bundle = self._find_job(db,context)
        result = JobStore(self.store).dispatch(dict(action='cancel',project_id=comp['private_id'],job_id=context['params']['job_id'],
                    request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,_hash([self.owner,context['principal'],context['scope']['native_project_id'],context['command_id']]))),
                    expected_job_revision=pre['entity_revision'],reason=input['reason']))
        if not result.get('ok'):
            error = result.get('error',{})
            _fail(error.get('code','BACKEND_UNAVAILABLE'),'The owned job cancellation request was rejected.')
        value = self._job_get(db,context,{})
        terminal = value['state'] in ('succeeded','failed','cancelled','interrupted')
        return (200 if terminal else 202),dict(job=value,job_id=value['job_id'],cancel=value['cancel'])

    def _assets(self, db, context, query):
        from .assets import AssetRegistry
        fs = self.store._filesystem()
        for comp in self._owned_compositions(db,context,query):
            if fs is not None:
                pointer = self.store._pointer(fs,comp['private_id'])
                if any(True for _ in AssetRegistry(self.store).records(fs,pointer)):
                    self._blocked('OP-ASSETS')
        return []

    def _has_engine_records(self, db, context, op):
        fs = self.store._filesystem()
        if fs is None:
            return False
        for comp in self._owned_compositions(db,context,{}):
            base = self.store._base(comp['private_id'])
            for section in ('jobs','delivery','reviews'):
                if fs.names(base + '/' + section):
                    return True
        return False
