"""Unified isolated entry: callbacks only; no live association or inference grant."""
from importlib import import_module


def register(ctx):
    runtime = import_module('.studio.native.technical.registration', __package__).register(ctx)
    runtime.creation = import_module('.studio.native.creation.registration', __package__).register(ctx)
    runtime.production = import_module('.studio.native.production.registration', __package__).register(
        ctx, runtime.creation)
    return runtime
