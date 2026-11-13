"""Finite registered creation tool and independently authorized native RPCs."""
import json
import logging
import hashlib

from typing import Literal
from pydantic import Field, ValidationError, field_validator, model_validator
from ...domain import Strict, Fault
from ...native.creation.hermes import MAX_BASE64
from ...native.creation.policy import context_id
from ...native.creation.runtime import CreationRuntime


class Prepare(Strict):
    direction: str = Field(min_length=1, max_length=2000)
    seconds: float = Field(default=3.0, ge=0.1, le=10, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0, le=4294967295)
    parent: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')

    @field_validator('direction')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Empty direction')
        return value


class HermesPrepare(Strict):
    kind: Literal['Image', 'Voice', 'Video', 'Music']
    method: Literal['hermes_tool'] = 'hermes_tool'
    method_id: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$')
    direction: str = Field(min_length=1, max_length=2000)
    seconds: float | None = Field(default=None, ge=0.5, le=47, allow_inf_nan=False)
    parent: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')

    @field_validator('direction')
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or '\x00' in value: raise ValueError('Invalid direction')
        return value

    @model_validator(mode='after')
    def duration(self):
        if self.kind == 'Image':
            if self.seconds is not None:
                raise ValueError('Images have no duration')
            return self
        if self.seconds is None:
            self.seconds = 30.0 if self.kind == 'Music' else 5.0
        if self.kind == 'Video' and (not 1 <= self.seconds <= 15 or not self.seconds.is_integer()):
            raise ValueError('Video duration must be whole seconds from 1 to 15')
        return self


class CollectOutput(Strict):
    submission: str = Field(pattern=r'^[a-f0-9]{32}$')
    attempt: str = Field(pattern=r'^[a-f0-9]{32}$')
    conversion_ok: bool = False
    request: str = Field(pattern=r'^[a-f0-9]{32}$')
    path: str | None = Field(default=None, min_length=1, max_length=4096)
    url: str | None = Field(default=None, min_length=1, max_length=16384)
    data: str | None = Field(default=None, min_length=1, max_length=MAX_BASE64 + 32)
    tool: Literal['image_generate', 'text_to_speech', 'video_generate']

    @model_validator(mode='after')
    def one_source(self):
        if sum(value is not None for value in (self.path, self.url, self.data)) != 1:
            raise ValueError('Exactly one output source required')
        if self.data is not None and self.tool != 'image_generate':
            raise ValueError('Base64 is only supported for images')
        return self


class Status(Strict):
    request: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class MusicPrepare(Strict):
    schema_version: Literal[2]
    kind: Literal['Music']
    direction: str = Field(min_length=1, max_length=2000)
    seconds: int = Field(default=30, ge=1, le=600)
    seed: int = Field(default=42, ge=0, le=4294967295)
    instrumental: bool = True
    reference_requested: bool = False
    parent: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')

    @field_validator('direction')
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or '\x00' in value: raise ValueError('Invalid direction')
        return value


class Command(Strict):
    request: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)
    command: str = Field(pattern=r'^[a-f0-9]{32}$')
    run: str = Field(pattern=r'^[a-f0-9]{32}$')


class Take(Strict):
    request: str = Field(pattern=r'^[a-f0-9]{32}$')
    take: str = Field(pattern=r'^[a-f0-9]{32}$')


class Chunk(Take):
    offset: int = Field(ge=0, le=16*1024*1024)


class Selection(Take):
    command: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)


class Review(Take):
    command: str = Field(pattern=r'^[a-f0-9]{32}$')
    outcome: Literal['Matches request', 'Needs work', 'Not reviewed']


SCHEMAS = dict(collect_output=CollectOutput, prepare=Prepare, start=Command, status=Status, stop=Command, admit_music=Strict,
               list=Strict, admit=Strict, chunk=Chunk, select=Selection, review=Review)
TOOL_OPERATIONS = ('prepare', 'start', 'status', 'stop', 'collect_output')
GUIDANCE = ('Use motion_studio_creation for saved requests and review in the Motion Studio panel. '
    'Sound effects: omit kind/method; prepare direction with defaults 3 seconds, seed42,100 steps; '
    'start exact returned request/revision/command/run only under admitted scope. '
    'Image/Voice/Video: prepare kind,direction,method_id from methods.list,method=hermes_tool, then use Hermes image_generate/'
    'text_to_speech/video_generate and collect_output with request,submission,attempt,tool and exactly one of path,url,data. '
    'Prefer the returned profile-cache path when present; otherwise pass the URL/data the tool returned to collect_output. '
    'URLs require HTTPS provider CDN hosts; data is base64 PNG/JPEG for Image only. Import size limits apply. Collect does not generate. '
    'Use methods.list cost: paid/unknown requires provider/cost basis and explicit user OK before calling; '
    'free/subscription proceeds with one bounded candidate; say which method was used. Music method=hermes_tool saves import-only intent; local ACE-Step remains '
    'MUSIC_LIVE_UNQUALIFIED. Legacy Music schema_version=2 retains separate denied-by-default scope. '
    'Prepare durably records submission/attempt awaiting_output. After lost replies use status without ID; '
    'collect the same output with those IDs, never regenerate. MP3/OGG conversion needs conversion_ok after disclosure. '
    'Only preparation_retryable '
    'or prelaunch_retryable permits deliberate identical retry. Refinement uses parent=request. '
    'Never invent permissions, paths, listening or selection. Always ask user to review in panel.')


def schema():
    # Hermes strips top-level combinators before presenting selected tools.
    # Publish the whole argument vocabulary directly; validate each operation
    # independently in execute(), including forbidden/irrelevant fields.
    properties = dict(operation=dict(type='string',enum=list(TOOL_OPERATIONS)))
    properties.update(Prepare.model_json_schema()['properties'])
    properties.update(MusicPrepare.model_json_schema()['properties'])
    properties.update(HermesPrepare.model_json_schema()['properties'])
    properties.update(CollectOutput.model_json_schema()['properties'])
    properties['kind'] = dict(type='string', enum=['Music', 'Image', 'Voice', 'Video'])
    properties['seconds'] = dict(type='number', description='Duration in SECONDS. SFX 0.1-10 default3; xAI Video integer1-15 default5 (references max10); Voice/import-only Music 0.5-47 default5/30; legacy Music integer10-30 qualified, other durations unqualified.')
    properties.update(Command.model_json_schema()['properties'])
    descriptions = {
        'seconds': properties['seconds']['description'],
        'path': 'Only collect_output: exact local file path returned by the built-in tool.',
        'url': 'Only collect_output: HTTPS provider CDN URL returned by the tool; exactly one of path,url,data.',
        'data': 'Only collect_output: base64 PNG/JPEG image returned by the tool, at most 16 MiB decoded.',
        'tool': 'Only collect_output: tool that produced this media, matching the saved kind.',
        'submission': 'Exact durable submission ID returned by prepare/status; required for collect_output.',
        'attempt': 'Exact saved attempt ID; collection never creates another generation attempt.',
        'method_id': 'Selected methods.list ID; use import for import-only Music.',
        'conversion_ok': 'Only collect_output: user authorized mono 44.1 kHz PCM16 conversion of compressed Voice.',
        'request': 'Saved request ID for collect_output/start/stop or optional status lookup.',
        'kind': 'Only prepare: Image, Voice, Video or Music; omit for Sound effects.',
        'method': 'Only prepare: hermes_tool saves external-output or Music import intent; never generates.',
    }
    for key, value in properties.items():
        if key != 'operation':
            value['description'] = descriptions.get(key, ('Only prepare: ' if key in Prepare.model_fields
                or key in MusicPrepare.model_fields else 'Exact saved reference for start/stop: ') + key)
    return dict(name='motion_studio_creation', description=GUIDANCE,
                parameters=dict(type='object',properties=properties,required=['operation'],additionalProperties=False))


def register(ctx, *, association=None):
    if contract_digest() != CONTRACT_SHA256:
        raise Fault('CREATION_CONTRACT_DRIFT', 409)
    runtime = CreationRuntime(ctx, association)
    ctx.on_unload(runtime.unload)

    def execute(operation, payload, root):
        try:
            limit = MAX_BASE64 + 32768 if operation == 'collect_output' else 8192
            if operation not in SCHEMAS or not isinstance(payload, dict) or len(json.dumps(payload).encode()) > limit:
                raise Fault('INVALID_CREATION_INPUT', 422)
            selected = SCHEMAS[operation]
            if operation == 'prepare' and payload.get('kind'):
                selected = (MusicPrepare if payload.get('kind') == 'Music' and payload.get('schema_version') == 2
                            and payload.get('method') != 'hermes_tool' else HermesPrepare)
            if selected is MusicPrepare and type(payload.get('schema_version')) is not int:
                raise Fault('INVALID_CREATION_INPUT', 422)
            model = selected.model_validate(payload, strict=True)
            with runtime.mutex:
                service = runtime.acquire()
                if operation == 'admit': return service.admit(root)
                if operation == 'admit_music': return service.admit_music(root)
                if operation == 'prepare': return service.prepare(root, model)
                if operation == 'collect_output': return service.collect_output(root, model)
                if operation == 'status':
                    assert isinstance(model, Status)
                    return service.read(root, model.request)
                if operation == 'start': return service.start(root, model)
                if operation == 'stop': return service.stop(root, model)
                if operation == 'list': return service.listing(root)
                if operation == 'chunk': return service.chunk(root, model)
                return service.action(root, model, operation)
        except Fault as error: return dict(error=error.code)
        except (ValidationError, TypeError, ValueError): return dict(error='INVALID_CREATION_INPUT')
        except Exception: return dict(error='CREATION_OPERATION_UNAVAILABLE')

    def tool(args, *, session_id=None, conversation_id=None, task_id=None, user_task=None):
        # Context ONLY comes from supported host-injected kwargs. Never consult
        # user_task, task_id, model scope overrides, private resolver or aliases.
        try:
            context_id(session_id)
            root = context_id(conversation_id)
            if not isinstance(args, dict): raise Fault('INVALID_CREATION_INPUT', 422)
            payload = dict(args)
            operation = payload.pop('operation', None)
            if operation not in TOOL_OPERATIONS: raise Fault('INVALID_CREATION_INPUT', 422)
            result = execute(operation, payload, root)
        except Fault as error: result = dict(error=error.code)
        return json.dumps(result, separators=(',', ':'))

    def rpc(operation):
        def call(params, *, session_id=None):
            try:
                root = context_id(session_id)  # Gateway already independently authorizes this ID.
                payload = dict(params)
                if payload.pop('session_id', root) != root: raise Fault('CREATION_SCOPE_DENIED', 403)
                if 'profile' in payload:
                    profile = payload.pop('profile')
                    if not isinstance(profile, str) or not profile.strip() or profile != ctx.profile_name:
                        raise Fault('CREATION_SCOPE_DENIED', 403)
                return execute(operation, payload, root)
            except Fault as error: return dict(error=error.code)
            except Exception: return dict(error='INVALID_CREATION_INPUT')
        return call

    handle = ctx.register_tool('motion_studio_creation', 'motion-studio', schema(), tool,
                               description=GUIDANCE, override=False)
    # Hermes returns None when another tool already owns this name (it logs the
    # refusal and keeps the existing tool). Keep the panel RPCs, but do not add
    # guidance that would point the agent at a tool this plugin does not own.
    if handle is None:
        logging.getLogger(__name__).warning('CREATION_TOOL_COLLISION: motion_studio_creation is owned by another tool')
    else:
        ctx.register_system_prompt_section('motion-studio.creation', GUIDANCE, max_chars=2048)
    for operation in SCHEMAS: ctx.register_rpc('creation.'+operation, rpc(operation))
    from ...native.methods import rpc_list
    def methods_rpc(params, **context):
        if isinstance(params, dict) and 'profile' in params and params['profile'] != ctx.profile_name:
            return dict(error='INVALID_METHODS_INPUT')
        return rpc_list(params, **context)
    ctx.register_rpc('creation.methods', methods_rpc)  # read-only method/cost discovery for the composer
    from ...director.registration import register as register_director
    runtime.director = register_director(ctx, runtime)
    return runtime


CONTRACT_SHA256 = '90bcd983488718ba8e926d41e0b4456e3aa9dc9195635782a8758ce0dcd2c6a2'


def contract_digest():
    return hashlib.sha256(json.dumps(schema(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


if __name__ == '__main__': print(contract_digest())
