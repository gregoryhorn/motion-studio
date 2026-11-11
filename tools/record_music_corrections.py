"""Offline Music authority-correction preservation and candidate evidence."""
import os
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / 'docs/evidence/music-authority-r2'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME/name).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def capture():
    if (HOME/'preserved-before.json').exists(): raise RuntimeError('Baseline already exists')
    old = json.loads((ROOT/'docs/evidence/music-source-r1/preserved-before.json').read_text())
    paths = set(old)
    tracked = subprocess.check_output(['git','ls-files','docs/evidence'],cwd=ROOT).decode().splitlines()
    paths.update(name for name in tracked if not name.startswith('docs/evidence/music-authority-r2/'))
    paths.update(str(p.relative_to(ROOT)) for p in (ROOT/'dist').rglob('*.zip'))
    paths.add('tools/record_music_evidence.py')
    save('preserved-before.json',{name:sha(ROOT/name) for name in sorted(paths)})
    print('Captured prior package/evidence/helper bytes; no previous artifact written.')


def verify():
    baseline = json.loads((HOME/'preserved-before.json').read_text())
    for name,digest in baseline.items():
        if sha(ROOT/name) != digest: raise RuntimeError('Preservation mismatch: '+name)
    print('Verified preserved paths:',len(baseline))
    return baseline


def record():
    baseline=verify()
    from tools.build_native_package import PINS, check_content
    design=Path(os.environ.get('MOTION_STUDIO_DESIGN', Path.home() / '.hermes/profiles/app-design/workspace/design-documents/motion-studio'))
    assert {name:sha(design/name) for name in PINS} == PINS
    historical=json.loads((ROOT/'docs/evidence/production-corrections-20261111/identity.json').read_text())
    for name,digest in historical['source_files'].items():
        data=subprocess.check_output(['git','show','cd3d0fd:'+name],cwd=ROOT)
        assert hashlib.sha256(data).hexdigest()==digest
    for name,digest in historical['frozen'].items(): assert sha(ROOT/name)==digest
    sfx=('studio/producer/local_sfx.py','studio/producer/stable_adapter.py','studio/producer/stable_model_pins.json',
         'studio/producer/live_sfx.py','studio/producer/evaluation.py')
    for name in sfx: assert (ROOT/name).read_bytes()==subprocess.check_output(['git','show','1701dfb:'+name],cwd=ROOT)
    names=[ROOT/'dist/native'/('motion-studio-music-authority-r2-'+suffix+'.zip') for suffix in ('source','reproduction')]
    assert names[0].read_bytes()==names[1].read_bytes()
    with zipfile.ZipFile(names[0]) as archive:
        files={name.removeprefix('motion-studio/'):archive.read(name) for name in archive.namelist()}
        check_content(files)
        contents=json.loads(files['CONTENTS.json'])
        assert set(files)==set(contents)|{'CONTENTS.json'}
        for name,facts in contents.items():
            assert hashlib.sha256(files[name]).hexdigest()==facts['sha256'] and len(files[name])==facts['bytes']
        for name,digest in json.loads(files['SOURCE.json']).items(): assert sha(ROOT/name)==digest
        spans=json.loads(subprocess.check_output(['node','tools/js-spans.cjs','--stdin','desktop/plugin.js'],
            input=files['desktop/plugin.js'],cwd=ROOT))
        bundled=max(row['span'] for row in spans);assert bundled<=300
        entries=len(files)
    source={str(p.relative_to(ROOT)):sha(p) for folder in ('studio','tests','tools','native-package')
        for p in sorted((ROOT/folder).rglob('*'))
        if p.suffix in ('.py','.js','.mjs','.cjs','.json','.yaml') and '__pycache__' not in p.parts}
    save('source.json',source)
    checks={}
    for name in ('controller-creation-final','controller-production-final','controller-comparison-final',
        'browser-authority-final','browser-music-final','browser-creation-final','browser-production-final','browser-comparison-final'):
        value=json.loads((HOME/(name+'.json')).read_text())
        assert not value.get('errors') and not value.get('page_errors')
        checks[name]=value['checks'] if type(value['checks']) is int else len(value['checks'])
    for name in ('python-final','affected-final'):
        log=(HOME/(name+'.txt')).read_text()
        assert re.search(r'^OK$',log,re.M) and not re.search(r'^FAILED',log,re.M)
        count=re.search(r'Ran (\d+) tests',log)
        assert count is not None
        checks[name]=int(count[1])
        checks[name+'-sqlite-warnings']=log.count('ResourceWarning: unclosed database')
    structure=json.loads((HOME/'structure-final.json').read_text())
    assert not structure['violations'] and structure['maximum']<=300
    checks.update(source_functions=len(structure['functions']),source_maximum=structure['maximum'],bundled_maximum=bundled)
    save('identity.json',dict(base='c5531dd9796c9453ad21c6e14b84a03504fa27f6',
        source_manifest_sha256=sha(HOME/'source.json'),source_files=len(source),design=PINS,
        packages={str(p.relative_to(ROOT)):sha(p) for p in names},package_entries=entries,
        preserved_paths=len(baseline),preserved_git_sources=len(historical['source_files']),
        frozen_artifacts=len(historical['frozen']),unchanged_sfx_sources=list(sfx),checks=checks,
        runtime_files={name:source[name] for name in ('studio/native/creation/service.py',
            'studio/native/production/records.py','studio/native/production/service.py',
            'studio/native/frontend/production-controller.js')},
        independent_review='Coordinator reports focused recheck passed; final artifact/hash/commit closure pending',
        live_qualified=False,installed=False,submitted=False))
    print(json.dumps(dict(packages={p.name:sha(p) for p in names},source_manifest_sha256=sha(HOME/'source.json'),checks=checks)))


if __name__ == '__main__':
    if sys.argv[1:] == ['--capture']: capture()
    elif sys.argv[1:]==['--record']: record()
    else: verify()
