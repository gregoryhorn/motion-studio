"""Finite public technical RPCs. Gateway session authorization is external, not invented."""
import json
from pydantic import Field, model_validator
from ...domain import Strict, Fault
from ...connectors.synthesis.evidence import Selection, admit
from ...connectors.synthesis.validation import TemplateRef
from ...native.technical.runtime import TechnicalRuntime
from ...native.skills import register as register_skills
from ...native.methods import rpc_list


class Select(Strict):
    expected: int = Field(ge=0)
    selection: Selection


class EvidenceRead(Strict):
    evidence: str = Field(pattern=r'^[a-f0-9]{32}$')


class Prepare(EvidenceRead):
    command: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)
    template: TemplateRef


class Job(Strict):
    job: str = Field(pattern=r'^[a-f0-9]{32}$')


class Status(Strict):
    job: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    command: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')

    @model_validator(mode='after')
    def one_or_none(self):
        if self.job and self.command: raise ValueError()
        return self


SCHEMAS = {'evidence.select': Select, 'evidence.read': EvidenceRead, 'prepare': Prepare,
           'status': Status, 'result': Job, 'abandon': Job}
# Only exact returned Prepare failures known to precede job insertion are marked.
PRE_ADMISSION = {'SYNTHESIS_PACKET_TOO_LARGE', 'SYNTHESIS_UNAVAILABLE', 'SYNTHESIS_SLOT_BLOCKED',
                 'SYNTHESIS_STALE', 'TECHNICAL_ACCESS_UNAVAILABLE', 'TECHNICAL_STORE_BUSY',
                 'TECHNICAL_STORE_REVIEW_REQUIRED'}


def register(ctx, *, policy=None):
    register_skills(ctx)
    ctx.register_rpc('methods.list', rpc_list)
    runtime = TechnicalRuntime(ctx, policy)
    ctx.on_unload(runtime.unload)
    def handler(operation):
        def call(params, *, session_id=None, **_ignored):
            try:
                if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
                    raise Fault('TECHNICAL_SESSION_REQUIRED', 403)
                limit = 26*1024 if operation == 'evidence.select' else 16384
                if not isinstance(params, dict) or len(json.dumps(params).encode()) > limit:
                    raise Fault('INVALID_TECHNICAL_INPUT', 422)
                payload = dict(params)
                if payload.pop('session_id', session_id) != session_id:
                    raise Fault('TECHNICAL_SESSION_REQUIRED', 403)
                model = SCHEMAS[operation].model_validate(payload, strict=True)
                if isinstance(model, Select): admit(model.selection.model_dump())
                with runtime.mutex:
                    scope = runtime.acquire(session_id)
                    service, jobs = runtime.service, runtime.jobs
                    if service is None or jobs is None: raise Fault('TECHNICAL_ACCESS_UNAVAILABLE', 409)
                    if isinstance(model, Select): return jobs.select_revision(scope, model.selection.model_dump(), model.expected)
                    if operation == 'evidence.read':
                        with jobs.store.transaction() as db: return jobs.evidence(db, scope, model.evidence)
                    if isinstance(model, Prepare):
                        return service.prepare(scope, model.command, model.evidence, model.revision, model.template.model_dump())
                    if isinstance(model, Status): return runtime.status(scope, job=model.job, command=model.command)
                    if operation == 'abandon': return service.abandon(scope, model.job)
                    return service.read(scope, model.job, result=True)
            except Fault as error:
                code = 'TECHNICAL_PREPARATION_ACTIVE' if error.code == 'SYNTHESIS_SLOT_BLOCKED' else error.code
                return dict(error=code, pre_admission=operation == 'prepare' and error.code in PRE_ADMISSION)
            except Exception:
                return dict(error='TECHNICAL_OPERATION_UNAVAILABLE', pre_admission=False)
        return call
    for operation in SCHEMAS: ctx.register_rpc('technical.'+operation, handler(operation))
    return runtime
