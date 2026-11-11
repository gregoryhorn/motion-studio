"""Music-only offline identity recorder. Reads no live state or installed media."""
import os
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / 'docs/evidence/music-source-r1'
DESIGN = Path(os.environ.get('MOTION_STUDIO_DESIGN', Path.home() / '.hermes/profiles/app-design/workspace/design-documents/motion-studio'))


def sha(data): return hashlib.sha256(data).hexdigest()


def save(name, value):
    (HOME/name).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def main():
    baseline = json.loads((HOME/'preserved-before.json').read_text())
    assert all(sha((ROOT/name).read_bytes()) == digest for name,digest in baseline.items())
    historical = json.loads((ROOT/'docs/evidence/production-corrections-20261111/identity.json').read_text())
    for name,digest in historical['source_files'].items():
        assert sha(subprocess.check_output(['git','show','cd3d0fd:'+name],cwd=ROOT)) == digest
    assert all(sha((ROOT/name).read_bytes()) == digest for name,digest in historical['frozen'].items())
    # Frozen SFX implementation bytes are additionally unchanged against this task's base.
    sfx = ('studio/producer/local_sfx.py','studio/producer/stable_adapter.py',
           'studio/producer/stable_model_pins.json','studio/producer/live_sfx.py','studio/producer/evaluation.py')
    for name in sfx:
        assert (ROOT/name).read_bytes() == subprocess.check_output(['git','show','1701dfb:'+name],cwd=ROOT)
    from tools.build_native_package import PINS
    designs = {name:sha((DESIGN/name).read_bytes()) for name in PINS}
    assert designs == PINS
    source = {str(path.relative_to(ROOT)):sha(path.read_bytes())
        for folder in ('studio','tests','tools','native-package')
        for path in sorted((ROOT/folder).rglob('*'))
        if path.suffix in ('.py','.js','.mjs','.cjs','.json','.yaml') and '__pycache__' not in path.parts}
    save('source.json',source)
    names = [ROOT/'dist/native'/('motion-studio-music-source-r1-'+suffix+'.zip')
             for suffix in ('source','reproduction')]
    assert names[0].read_bytes() == names[1].read_bytes()
    with zipfile.ZipFile(names[0]) as archive:
        sources = json.loads(archive.read('motion-studio/SOURCE.json'))
        assert all(sha((ROOT/name).read_bytes()) == digest for name,digest in sources.items())
        contents = json.loads(archive.read('motion-studio/CONTENTS.json'))
        assert set(archive.namelist()) == {'motion-studio/'+name for name in contents} | {'motion-studio/CONTENTS.json'}
        for name,facts in contents.items():
            data = archive.read('motion-studio/'+name)
            assert sha(data) == facts['sha256'] and len(data) == facts['bytes']
        spans = json.loads(subprocess.check_output(['node','tools/js-spans.cjs','--stdin','desktop/plugin.js'],
                           input=archive.read('motion-studio/desktop/plugin.js'),cwd=ROOT))
        maximum = max(row['span'] for row in spans)
        assert maximum <= 300
        entries = len(archive.namelist())
    checks = {}
    for name in ('controller-creation-final','controller-production-final','controller-comparison-final',
                 'browser-music-checkpoint','browser-creation-checkpoint','browser-production-checkpoint','browser-comparison-checkpoint'):
        value = json.loads((HOME/(name+'.json')).read_text())
        assert not value.get('errors') and not value.get('page_errors')
        checks[name] = value['checks'] if type(value['checks']) is int else len(value['checks'])
    log = (HOME/'python-final.txt').read_text()
    assert re.search(r'^OK$',log,re.M) and not re.search(r'^FAILED',log,re.M)
    count = re.search(r'Ran (\d+) tests',log)
    assert count is not None
    checks.update(python_tests=int(count.group(1)),
                  sqlite_resource_warnings=log.count('ResourceWarning: unclosed database'))
    structure = json.loads((HOME/'structure-final.json').read_text())
    assert not structure['violations'] and structure['maximum'] <= 300
    checks.update(source_functions=len(structure['functions']),source_maximum=structure['maximum'],bundled_maximum=maximum)
    save('checks-summary.json',checks)
    save('identity.json',dict(base='1701dfb5a06ce9f7bd01db883c5c38e90841a726',
        source_manifest_sha256=sha((HOME/'source.json').read_bytes()), source_files=len(source),
        design_root=str(DESIGN),design=designs,
        packages={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in names},package_entries=entries,
        preserved_paths=len(baseline),preserved_git_sources=len(historical['source_files']),
        frozen_artifacts=len(historical['frozen']),unchanged_sfx_sources=list(sfx),
        live_qualified=False,installed=False,submitted=False,
        real_recipe='Inactive fixed bridge/launcher construction exists; real admission remains blocked, not fixture-qualified',
        checks=checks))
    print(json.dumps(dict(packages={p.name:sha(p.read_bytes()) for p in names},preserved_paths=len(baseline),checks=checks)))


if __name__ == '__main__': main()
