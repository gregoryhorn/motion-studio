"""Materialize only manifest-listed historical source files for archive tests."""
import json
from pathlib import Path
import subprocess
import zipfile
import unittest
from tools.build_native_package import sha


def require_history(commit):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['git', '-C', str(root), 'cat-file', '-e', commit + '^{commit}'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        raise unittest.SkipTest('Internal historical regression requires Git object ' + commit)


def require_baselines(*paths):
    for path in paths:
        if not Path(path).exists():
            raise unittest.SkipTest('Internal historical regression requires baseline ' + Path(path).name)


def materialize(archive, destination, commit='67f649f'):
    require_baselines(archive)
    require_history(commit)
    root = Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(archive) as bundle:
        sources = json.loads(bundle.read('motion-studio/SOURCE.json'))
    for name, digest in sources.items():
        data = subprocess.check_output(['git', '-C', str(root), 'show', commit + ':' + name])
        if sha(data) != digest:
            raise AssertionError('Historical source does not match archive: ' + name)
        target = Path(destination) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return Path(destination)
