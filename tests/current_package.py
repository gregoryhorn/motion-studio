"""Build the current source package in disposable test space, never dist or runtime."""
import atexit
from functools import lru_cache
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import tools.build_native_package as builder


@lru_cache(maxsize=1)
def current_sources():
    names = (*builder.PYTHON, *builder.FRONTEND,
             'studio/connectors/cli-template.json', 'studio/producer/stable_model_pins.json',
             *('native-package/' + name for name in builder.STATIC),
             'tools/build_native_package.py', 'tools/native_dependencies.py')
    return {name: (builder.ROOT / name).read_bytes() for name in names}


@lru_cache(maxsize=1)
def current_bundle():
    sources = current_sources()
    temporary = tempfile.TemporaryDirectory(prefix='motion-current-package-')
    atexit.register(temporary.cleanup)
    root = Path(temporary.name)
    # Snapshot frontend inputs so esbuild's source comments remain relative.
    for name in builder.FRONTEND:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sources[name])
    compiler = Path(os.environ.get('ESBUILD', Path.home() /
        'projects/gregory-cv/projects/Exomorphic-Particle/node_modules/@esbuild/linux-x64/bin/esbuild'))
    host = Path(os.environ.get('HERMES_SOURCE', Path.home() / '.hermes/hermes-agent-official'))
    output = root / 'dist/native/current-source.zip'
    with patch.object(builder, 'ROOT', root), patch.object(builder, 'source',
            side_effect=lambda name: sources[name]):
        builder.build(output, compiler, host)
    return output
