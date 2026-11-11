"""Read installed build/runtime dependency metadata only; never install anything."""
import importlib.metadata
import json
import platform

RUNTIME = ('pydantic', 'pydantic_core', 'annotated-types', 'typing_extensions', 'typing-inspection',
           'fastapi', 'starlette', 'anyio', 'idna', 'annotated-doc', 'PyYAML')


def versions():
    return dict(python=platform.python_version(), distributions={name:importlib.metadata.version(name) for name in RUNTIME})


if __name__ == '__main__':
    print(json.dumps(versions(), sort_keys=True, indent=2))
