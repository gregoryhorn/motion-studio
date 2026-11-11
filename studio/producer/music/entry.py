"""Isolated app bridge bootstrap; works in source and namespaced native bundles."""
import importlib
from pathlib import Path
import sys
import types


def main():
    root = Path(__file__).resolve().parents[3]
    if (root / 'plugin.yaml').is_file():
        # Do not execute plugin registration/__init__ in the bridge child.
        name = '_motion_music_bridge'
        package = types.ModuleType(name)
        package.__path__ = [str(root)]
        sys.modules[name] = package
        runner = importlib.import_module(name + '.studio.producer.music.runner')
    else:
        sys.path.insert(0, str(root))
        runner = importlib.import_module('studio.producer.music.runner')
    return runner.main(sys.argv[1:])


if __name__ == '__main__': sys.exit(main())
