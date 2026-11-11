"""Offline simulated structured results, not proof of model interpretation/authentication."""
import copy
from typing import Any
import json
from pathlib import Path
from types import SimpleNamespace
from studio.connectors.synthesis.host import Route, Scope, TASK
from studio.connectors.synthesis.evidence import template_ref
from tests.template_support import DOCUMENTS

HOME = Path(__file__).parent / 'fixtures/synthesis'


def selection(index=0) -> dict:
    leaf = ['lumen-reference.txt', 'ripple-reference.txt'][index]
    return dict(sources=[dict(id='source-0', source='Fixture technical manual '+leaf,
        version=DOCUMENTS[index]['tool_version'], kind='selected-technical-excerpt', excerpts=[
            dict(id='part-'+str(i), section='Selected technical reference', text=text)
            for i, text in enumerate((HOME/leaf).read_text().splitlines())])])


def envelope(index=0, selected=None) -> dict:
    selected = selected or selection(index)
    excerpts = selected['sources'][0]['excerpts']
    positions = dict(tool_version=0, operation=1, format=2, seconds_min=24, seconds_max=25, seconds_default=26, seed_default=27)
    for i in range(5):
        for field in ('flag', 'value'): positions[f'arguments.{i}.{field}'] = 3+i
    for i, field in enumerate(('output', 'direction', 'seconds', 'seed', 'version')): positions['receipt.'+field] = 8+i
    for i, field in enumerate(('destination', 'network', 'cost', 'model', 'credentials', 'use')): positions['effects.'+field] = 13+i
    for i, field in enumerate(('execution', 'exit', 'stop', 'idempotency', 'timeout_seconds')): positions['process.'+field] = 19+i
    refs = {field:[dict(source='source-0', excerpt=excerpts[pos]['id'], quote=excerpts[pos]['text'])] for field, pos in positions.items()}
    refs['format'].append(dict(source='source-0', excerpt=excerpts[28]['id'], quote=excerpts[28]['text']))
    return dict(schema_version=1, template_ref=template_ref(), tool_version=DOCUMENTS[index]['tool_version'],
                mapping=copy.deepcopy(DOCUMENTS[index]), evidence_map=refs, unknowns=[])


def route():
    return Route(revision='offline-policy-1', host_build='fake-host-only', task=TASK,
        destinations=('offline-stub',), retries='simulated-no-retry', data_policy='public-fixture-only',
        cost_policy='no-real-inference', locality_policy='no-network-fake', audience_policy='fake-local-owner', effective_verified=True)


class Facade:
    def __init__(self):
        self.calls = []
        self.reply: Any = None
        self.hook: Any = None

    def complete_structured(self, **packet):
        self.calls.append(copy.deepcopy(packet))
        if self.hook: self.hook()
        selected = json.loads(packet['input'][0]['text'])['selected_evidence']
        index = 0 if selected['sources'][0]['version'] == '1.0' else 1
        result = self.reply if self.reply is not None else envelope(index, selected)
        return SimpleNamespace(text=result if isinstance(result, str) else json.dumps(result),
                               parsed=None if isinstance(result, str) else result)


class Context:
    def __init__(self): self.methods = {}
    def register_rpc(self, name, handler): self.methods['plugin.motion-studio.'+name] = handler


class Ports:
    def __init__(self, service, scope=None):
        self.service, self.scope = service, scope or Scope('fixture-profile', 'fixture-session', 1)
        self.enabled = True

    def resolve(self, ctx, session):
        from studio.domain import Fault
        if not self.enabled or session != self.scope.session: raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        return self.scope, self.service

    def dispatch(self, ctx, operation, params, *, actor='owner', operator=False, session=None):
        # Separate fake gateway gate: operators are deliberately part of the
        # audience, not falsely reported as ordinary-owner denial.
        from studio.domain import Fault
        if actor != 'owner' and not operator: return dict(error='GATEWAY_DENIED')
        sid = session or self.scope.session
        if sid != self.scope.session: return dict(error='GATEWAY_DENIED')
        return ctx.methods['plugin.motion-studio.connector.'+operation](params, session_id=sid)
