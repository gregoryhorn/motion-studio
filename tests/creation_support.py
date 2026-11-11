"""Synthetic native creation fixtures; never reachable from package registration."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from studio.native.creation.policy import Association, AUDIENCE
from studio.native.creation.registration import register
from studio.producer.evaluation import enable_evaluation
from tests.producer_support import fixture_binding, effects


class Context:
    profile_name = 'offline-fixture'
    def __init__(self, root):
        self.state = SimpleNamespace(data_dir=root)
        self.methods, self.tools, self.sections, self.callbacks = {}, {}, {}, []
    def register_rpc(self, name, handler): self.methods[name] = handler
    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = (schema, handler)
        return object()
    def register_system_prompt_section(self, name, content, **kwargs): self.sections[name] = content
    def on_unload(self, callback): self.callbacks.append(callback)


def setup(root, *, mode='good'):
    ctx = Context(root / 'owned-plugin-data')
    association = Association(profile=ctx.profile_name, revision='offline-v1', audience=AUDIENCE,
        direction_audio=True, canonical_roots=True, agent_starts=True, delegated_starts=True,
        local_generator=True, create_store=True)
    runtime = register(ctx, association=association)
    runtime.acquire()
    assert runtime.runs is not None
    binding = fixture_binding(root / 'fake-tool', mode=mode)
    runtime.runs.binding = binding
    runtime.runs.bindings.allow_fixtures = True
    seeded = runtime.runs.bindings.seed(binding)
    record = enable_evaluation(runtime.runs.bindings, seeded['id'], seeded['revision'])
    runtime.policy = replace(association, binding=record['id'], binding_revision=record['revision'])
    return ctx, runtime, binding


def settle(runtime):
    for _ in range(3):
        workers = list(runtime.runs.threads.values())
        for worker in workers: worker.join(10)
        if len(workers) == len(runtime.runs.threads) and all(not w.is_alive() for w in workers): return
    raise AssertionError('Synthetic worker did not settle')
