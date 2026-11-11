"""Finite agent/RPC registration for default-denied Production management."""
import hashlib
import json
import logging
from pydantic import ValidationError
from ...domain import Fault
from ...native.creation.policy import context_id
from ...native.production.models import SCHEMAS, TOOL_OPERATIONS
from ...native.production.policy import ProductionAssociation
from ...native.production.service import Productions
from ...native.production.media import ProductionMedia, OPERATIONS as MEDIA_OPERATIONS


GUIDANCE = ('Use motion_studio_production to manage a brief, ordered five-media asset plan, reusable '
    'references and retained same-scope Quick Create takes. Create/update/select only through exact returned '
    'IDs, expected production revisions and unique command IDs. After any lost mutation reply, list/open the '
    'same root and reconcile the saved revision before acting; never repeat a mutation automatically. Linking '
    'keeps the SAME immutable take/artifact/request/review provenance and never generates or copies media. '
    'Brief/reference/asset revisions preserve selections and old pins; only affected selections and declared '
    'dependents become stale. Explicit current-revision select_take records current pins and clears only that '
    'asset. Native panel supports retained-media review, import and selected-output export. '
    'Generation uses separate creation/tool authority; Music remains unqualified. '
    'Range refinement and editor interchange are unavailable. Do not invent access or authority.')


class ProductionRuntime:
    def __init__(self, ctx, creation, association=None):
        self.ctx, self.creation = ctx, creation
        self.association = association or ProductionAssociation()

    def access(self):
        self.association.access(self.ctx.profile_name)

    def acquire(self):
        self.access()
        service = self.creation.acquire()
        if not hasattr(service, 'productions'):
            service.productions = Productions(self.creation, self.creation.store, service, self.association)
        service.productions.policy = self.association
        return service.productions


def resolved_model_schema(model) -> dict:
    source = model.model_json_schema()
    definitions = source.pop('$defs', {})
    def resolve(value):
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.pop('$ref', None)
        if reference is not None:
            target = reference.removeprefix('#/$defs/')
            if target not in definitions:
                raise Fault('PRODUCTION_CONTRACT_DRIFT', 409)
            value = {**definitions[target], **value}
        return {key: resolve(item) for key, item in value.items()}
    return resolve(source)


def schema():
    properties = dict(operation=dict(type='string', enum=list(TOOL_OPERATIONS)))
    for name in TOOL_OPERATIONS:
        if name in ('list', 'open'):
            continue
        for key, value in resolved_model_schema(SCHEMAS[name]).get('properties', {}).items():
            properties.setdefault(key, value)
    properties.update(resolved_model_schema(SCHEMAS['open'])['properties'])
    return dict(name='motion_studio_production', description=GUIDANCE,
                parameters=dict(type='object', properties=properties, required=['operation'],
                                additionalProperties=False))


def register(ctx, creation, *, association=None):
    if contract_digest() != CONTRACT_SHA256:
        raise Fault('PRODUCTION_CONTRACT_DRIFT', 409)
    runtime = ProductionRuntime(ctx, creation, association)
    media = ProductionMedia(runtime)
    ctx.on_unload(media.close)

    def execute(operation, payload, root):
        try:
            if operation in MEDIA_OPERATIONS:
                if not isinstance(payload, dict) or len(json.dumps(payload).encode()) > 270000:
                    raise Fault('INVALID_PRODUCTION_INPUT', 422)
                with creation.mutex:
                    runtime.access()
                    return media.execute(operation, payload, root)
            if operation not in SCHEMAS or not isinstance(payload, dict) or len(json.dumps(payload).encode()) > 32768:
                raise Fault('INVALID_PRODUCTION_INPUT', 422)
            model = SCHEMAS[operation].model_validate(payload, strict=True)
            with creation.mutex:
                runtime.access()
                service = runtime.acquire()
                if operation == 'admit':
                    return service.admit(root)
                if operation == 'create':
                    return service.create(root, model)
                if operation == 'list':
                    return service.listing(root)
                if operation == 'open':
                    return service.read(root, model.production)
                return getattr(service, operation)(root, model)
        except Fault as error:
            return dict(error=error.code)
        except (ValidationError, TypeError, ValueError):
            return dict(error='INVALID_PRODUCTION_INPUT')
        except Exception:
            return dict(error='PRODUCTION_OPERATION_UNAVAILABLE')

    def tool(args, *, session_id=None, conversation_id=None, task_id=None, user_task=None):
        try:
            context_id(session_id)
            root = context_id(conversation_id)
            if not isinstance(args, dict):
                raise Fault('INVALID_PRODUCTION_INPUT', 422)
            payload = dict(args)
            operation = payload.pop('operation', None)
            if operation not in TOOL_OPERATIONS:
                raise Fault('INVALID_PRODUCTION_INPUT', 422)
            result = execute(operation, payload, root)
        except Fault as error:
            result = dict(error=error.code)
        return json.dumps(result, separators=(',', ':'))

    def rpc(operation):
        def call(params, *, session_id=None):
            try:
                root = context_id(session_id)
                payload = dict(params)
                if payload.pop('session_id', root) != root:
                    raise Fault('PRODUCTION_SCOPE_DENIED', 403)
                if 'profile' in payload:
                    profile = payload.pop('profile')
                    if not isinstance(profile, str) or not profile.strip() or profile != ctx.profile_name:
                        raise Fault('PRODUCTION_SCOPE_DENIED', 403)
                return execute(operation, payload, root)
            except Fault as error:
                return dict(error=error.code)
            except Exception:
                return dict(error='INVALID_PRODUCTION_INPUT')
        return call

    handle = ctx.register_tool('motion_studio_production', 'motion-studio', schema(), tool,
                               description=GUIDANCE, override=False)
    # Hermes returns None when another tool already owns this name (it logs the
    # refusal and keeps the existing tool). Keep the panel RPCs, but do not add
    # guidance that would point the agent at a tool this plugin does not own.
    if handle is None:
        logging.getLogger(__name__).warning('PRODUCTION_TOOL_COLLISION: motion_studio_production is owned by another tool')
    else:
        ctx.register_system_prompt_section('motion-studio.production', GUIDANCE, max_chars=2048)
    for operation in (*SCHEMAS, *MEDIA_OPERATIONS):
        ctx.register_rpc('production.' + operation, rpc(operation))
    return runtime


CONTRACT_SHA256 = '3b2edd1addbf1f0119378c898cb095547900d7ff64a51df15256348d17f6c824'


def contract_digest():
    return hashlib.sha256(json.dumps(schema(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


if __name__ == '__main__':
    print(contract_digest())
