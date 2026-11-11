"""Synthetic Production fixtures over the real native store and fake SFX child."""
import json
from studio.native.production.policy import ProductionAssociation
from studio.native.production.registration import register
from tests.creation_support import setup, settle


def production_setup(root):
    ctx, creation, binding = setup(root)
    association = ProductionAssociation(profile=ctx.profile_name, revision='production-offline-v1',
                                        production_management=True, direction_audio=True, canonical_roots=True)
    production = register(ctx, creation, association=association)
    production.acquire()
    ctx.methods['creation.admit']({}, session_id='canonical-root')
    ctx.methods['production.admit']({}, session_id='canonical-root')
    return ctx, creation, production, binding


def make_take(ctx, runtime, direction, parent=None):
    handler = ctx.tools['motion_studio_creation'][1]
    def tool(operation, payload):
        return json.loads(handler(dict(operation=operation, **payload), session_id='compressed',
                                  conversation_id='canonical-root'))
    payload = dict(direction=direction, seconds=0.1)
    if parent is not None:
        payload['parent'] = parent
    row = tool('prepare', payload)
    assert 'error' not in row, row
    command = {key: row[key] for key in ('request', 'revision', 'command', 'run')}
    started = tool('start', command)
    assert 'error' not in started, started
    settle(runtime)
    return tool('status', {})
