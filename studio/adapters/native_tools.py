"""Declarative native-tool bindings on the existing host handoff lifecycle.

Only trusted installed code can register semantic mappings. Schema resemblance
alone never authorizes an arbitrary tool or invents effects. Compatible bindings
share normal discovery, frozen identities, approvals, observed calls and collect.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import inspect
from pathlib import Path
from typing import Callable

from ..contracts import ContractError, digest, nullable, validate


@dataclass(frozen=True)
class NativeBinding:
    adapter_id: str
    tool_name: str
    operation: str
    label: str
    parameters: dict
    outputs: tuple
    extension: str
    arguments: Callable
    validate_parameters: Callable
    timing: Callable
    effects: dict
    result_output_field: str = 'output'
    input_port: str = 'media'
    max_bytes: int = 16777216
    constraints: dict | None = None
    validate_output: Callable | None = None
    dependencies: tuple = ()


BINDINGS = {}


def register_binding(binding):
    if not isinstance(binding, NativeBinding) or binding.adapter_id in BINDINGS:
        raise ValueError('Native bindings must be unique trusted code registrations.')
    if len(binding.outputs) != 1 or binding.extension not in ('png', 'wav', 'flac', 'mp4'):
        raise ValueError('This bounded native connector needs one supported media output.')
    if not 0 < binding.max_bytes <= 16777216:
        raise ValueError('Native collection bound must remain at most 16 MiB.')
    BINDINGS[binding.adapter_id] = binding


def tool_names():
    return {'lk_extract_frame'} | {b.tool_name for b in BINDINGS.values()}


def effects():
    return dict(writes_local=True, uploads=False, destinations=[], generates=False,
        launches_process=True, pricing='free', charging_basis=None, estimate=None)


def _audio_check(p):
    if p != dict(stream_index=0, format='wav', sample_rate=None):
        raise ContractError('UNSUPPORTED_FEATURE', 'Native audio extraction supports stream zero and WAV without rate conversion; the host tool has no sample-rate control.')


def _audio_args(source, output, p):
    return dict(input=str(source), output=str(output), format=p['format'],
        audio_track=p['stream_index'], overwrite=False, timeout_s=60)


def _audio_timing(request, *, resolve_artifact):
    _audio_check(request['parameters'])
    if set(request.get('inputs', {})) != {'media'}:
        raise ContractError('INVALID_ARGUMENT', 'Native extraction needs one media pin.')
    pin = request['inputs']['media']
    if pin.get('kind') != 'artifact':
        raise ContractError('UNSUPPORTED_FEATURE', 'Native timing requires an exact registered source artifact.')
    resolve_artifact(pin['artifact'])
    return []


def install_builtins():
    from ..capabilities import PARAMS, expanded
    if 'hermes.audio-extract' not in BINDINGS:
        register_binding(NativeBinding('hermes.audio-extract', 'lk_extract_audio',
            'media.extract_audio@1', 'Normal Hermes audio extraction',
            expanded(PARAMS['media.extract_audio@1']),
            (dict(port='audio', kind='audio', media_type='audio/wav'),),
            'wav', _audio_args, _audio_check, _audio_timing, effects()))
    from .native_video import bindings
    for binding in bindings():
        if binding.adapter_id not in BINDINGS:
            register_binding(binding)


def lookup_tool(name):
    return next((b for b in BINDINGS.values() if b.tool_name == name), None)


def implementation_identity(binding, schema):
    """Exact source/schema identity shared by registration and passive selection."""
    functions = [binding.arguments, binding.validate_parameters, binding.timing]
    if binding.validate_output is not None:
        functions.append(binding.validate_output)
    source_files = sorted({inspect.getfile(function) for function in functions})
    identity = dict(source=digest(Path(__file__).read_text()), host_schema=digest(schema) if schema else None,
        adapter=binding.adapter_id, operation=binding.operation,
        sources={Path(path).name: digest(Path(path).read_text()) for path in source_files},
        effects=binding.effects, parameters=binding.parameters, outputs=list(binding.outputs),
        constraints=binding.constraints, dependencies=list(binding.dependencies))
    return digest(identity)


def register_adapters(registry, bridge):
    from ..capabilities import builtin_ffmpeg
    from ..handoffs import HANDOFF
    from .media_probe import result_schema
    install_builtins()
    for binding in BINDINGS.values():
        declaration, _ = builtin_ffmpeg(None)
        declaration.update(adapter_id=binding.adapter_id, label=binding.label,
            transport='host_handoff', location='agent', implementation_version='1.0',
            effects=binding.effects)
        op = declaration['operations'][0]
        op.update(operation=binding.operation, request_schema='motion/v1/' + binding.adapter_id + '-request',
            result_schema='motion/v1/' + binding.adapter_id + '-result')
        op['supports']['collect'] = True
        if binding.constraints is not None:
            op['constraints'] = copy.deepcopy(binding.constraints)
        declaration['dependencies'] = [dict(name=binding.tool_name, kind='host_tool', version_constraint=None, required=True)]
        declaration['dependencies'].extend(copy.deepcopy(binding.dependencies))
        schema = None
        reason = 'No complete current-session tool schema.'
        if bridge:
            try:
                schema = bridge.inventory()[binding.tool_name]
                reason = 'Exact native schema observed; no execution acceptance claimed.'
            except (ContractError, KeyError):
                pass
        result = result_schema()
        result['properties']['handoff'] = nullable(HANDOFF)
        from ..permissions import consuming, NATIVE_BOUNDARY_MISSING
        admission_missing = consuming(binding.effects)
        if admission_missing:
            reason = NATIVE_BOUNDARY_MISSING
        registry.register(declaration, implementation_sha256=implementation_identity(binding, schema),
            schemas={op['request_schema']: binding.parameters, op['result_schema']: result},
            outputs={binding.operation: list(binding.outputs)},
            state='available' if schema and not admission_missing else 'unavailable',
            checks=[dict(name='exact-session-tool-schema', status='pass' if schema else 'fail', reason=reason),
                dict(name='consuming-final-admission', status='fail' if admission_missing else 'pass',
                    reason=NATIVE_BOUNDARY_MISSING if admission_missing else 'Known free operation; no spending grant required.')])


class NativeToolAdapter:
    native_handoff = True
    owned_local = False

    def __init__(self, runtime, frozen):
        self.runtime, self.binding = runtime, frozen
        self.recipe = BINDINGS[frozen['adapter_id']]

    def validate_request(self, request):
        b = self.recipe
        from ..permissions import require_native_admission
        require_native_admission(b.effects)
        from ..permissions import validate_invocation_selection
        validate_invocation_selection(request, self)
        if self.runtime.host_bridge is None:
            raise ContractError('PERMISSION_DENIED', 'Normal session bridge required.')
        expected = self.runtime.registry.binding(b.adapter_id, request['operation'],
            request['parameters'], request.get('binding_parameters'))
        if expected != self.binding or request.get('binding') != expected or request['operation'] != b.operation:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Native frozen semantic/schema binding changed.')
        from ..tool_integration import require_compatible_binding
        require_compatible_binding(self.runtime.registry, self.binding,
            operation=request['operation'], parameters=request['parameters'],
            binding_parameters=request.get('binding_parameters'), bridge=self.runtime.host_bridge)
        validate(request['parameters'], b.parameters)
        b.validate_parameters(request['parameters'])
        if set(request['inputs']) != {b.input_port}:
            raise ContractError('UNSUPPORTED_FEATURE', 'Native input mapping differs.')
        self.runtime.artifacts.resolve(request['project_id'], request['inputs'][b.input_port])
        return dict(valid=True, effects=b.effects)

    def execute(self, request, attempt):
        from ..project import _id
        self.validate_request(request)
        b = self.recipe
        inventory = self.runtime.host_bridge.inventory()
        from ..tool_integration import require_compatible_binding
        require_compatible_binding(self.runtime.registry, self.binding,
            operation=request['operation'], parameters=request['parameters'],
            binding_parameters=request.get('binding_parameters'), inventory=inventory)
        schema = inventory[b.tool_name]
        source = self.runtime.artifact_path(request['project_id'], request['inputs'][b.input_port])
        fs = self.runtime.projects._filesystem(write=True)
        with fs.directory(attempt['output_dir'], create=True):
            pass
        output = fs.root / attempt['output_dir'] / ('native-output.' + b.extension)
        args = b.arguments(source, output, request['parameters'])
        validate(args, schema)
        return dict(state='awaiting_external', submission_state='not_sent', external_handle=None,
            remote_state='none', progress=None, outputs=[], warnings=[], error=None,
            observed_cost=None, logs_ref=None, handoff=dict(handoff_id=_id('hnd'),
                job_id=attempt['job_id'], node_id=attempt['node_id'], attempt_id=attempt['attempt_id'],
                request_sha256=request['request_sha256'], kind='host_tool', tool_name=b.tool_name,
                tool_schema_sha256=digest(schema), arguments=args, expected_outputs=list(b.outputs),
                effects=b.effects, state='ready', claimed_by=None, host_call_ref=None,
                instructions='Claim through motion_run.handoff_claim; invoke exact native arguments once under normal host approval; collect observed results, not caller receipts.'))
