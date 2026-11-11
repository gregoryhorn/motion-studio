"""Offline native candidate gate, preserving completed evidence and exact media bytes."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
from tools.build_native_package import build, sha

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT/'docs/evidence'
GLOBALS = {'code-manifest.json','design-inputs.json','environment.json','structure.json','contrast.json'}


def run(destination, label, command):
    with (destination/(label+'.txt')).open('w') as receipt:
        result = subprocess.run(command, cwd=ROOT, stdout=receipt, stderr=subprocess.STDOUT, check=False)
    print(json.dumps(dict(check=label, exit=result.returncode)), flush=True)
    if result.returncode: raise SystemExit(result.returncode)


def validate_manifests():
    reports = {}
    for name in ('code-manifest.json','design-inputs.json'):
        data = json.loads((EVIDENCE/name).read_text())
        for item in data:
            if sha((ROOT/item['path']).read_bytes()) != item['sha256']: raise ValueError('Candidate manifest mismatch')
        reports[name] = dict(entries=len(data), sha256=sha((EVIDENCE/name).read_bytes()))
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='docs/evidence/native-package/final')
    args = parser.parse_args()
    destination = ROOT/args.evidence
    if not destination.resolve().is_relative_to(EVIDENCE/'native-package'): raise ValueError('Receipt directory outside native evidence')
    destination.mkdir(parents=True, exist_ok=False)
    for key in ('ESBUILD','HERMES_SOURCE','PLAYWRIGHT_PACKAGE','CHROME_EXECUTABLE','NODE_PATH'):
        if not os.environ.get(key): raise ValueError('Supply existing '+key)
    protected = {str(p.relative_to(EVIDENCE)):sha(p.read_bytes()) for p in EVIDENCE.rglob('*')
        if p.is_file() and not p.is_relative_to(EVIDENCE/'native-package') and str(p.relative_to(EVIDENCE)) not in GLOBALS}
    media = [ROOT/'var/media'/(name+'.wav') for name in ('6c3c47e1b5464d7e83254097c6b33f8e','ba52e4b96cf74c378bcecc658d064c36')]
    preserved_media = [sha(path.read_bytes()) for path in media]
    with tempfile.TemporaryDirectory(prefix='motion-native-evidence-') as temp:
        backup = Path(temp)
        for name in protected:
            (backup/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(EVIDENCE/name, backup/name)
        try:
            first = build(ROOT/'dist/native/motion-studio-0.1.0-source.zip', Path(os.environ['ESBUILD']), Path(os.environ['HERMES_SOURCE']))
            second = build(ROOT/'dist/native/reproduction.zip', Path(os.environ['ESBUILD']), Path(os.environ['HERMES_SOURCE']))
            if first['sha256'] != second['sha256']: raise ValueError('Bundle reproduction differs')
            with zipfile.ZipFile(ROOT/str(first['bundle'])) as one, zipfile.ZipFile(ROOT/str(second['bundle'])) as two:
                if one.namelist() != two.namelist() or any(one.read(name) != two.read(name) for name in one.namelist()):
                    raise ValueError('Bundle contents differ')
                for entry in ('CONTENTS.json','SOURCE.json','HOST-CONTRACT.json','Dependencies.json','DESIGN-INPUTS.json'):
                    (destination/('package-'+entry)).write_bytes(one.read('motion-studio/'+entry))
            (destination/'reproducibility.json').write_text(json.dumps(dict(first=first, second=second,
                equal_archive_bytes=True, equal_entry_bytes=True), indent=2)+'\n')
            run(destination, 'native-core-loader', ['python','-m','unittest','tests.test_native_technical','tests.test_native_package','-v'])
            run(destination, 'native-sdk', ['node','--test','tests/native-technical.mjs'])
            run(destination, 'native-browser', ['node','tests/browser-native-package.mjs'])
            run(destination, 'prior-correction-sdk', ['node','--test','tests/synthesis-correction.mjs'])
            run(destination, 'prior-sdk', ['node','tests/synthesis-sdk.mjs'])
            # Existing wrappers are harmless controlled tool/browser fixtures, not live generators.
            # Deliberately do NOT call check_cs1: it fetches a public manual from the network.
            run(destination, 'prior-full-gates', ['python','-m','tools.check_connector_ui'])
            run(destination, 'prior-synthesis-browser', ['node','tests/browser-synthesis.mjs'])
            for name in ('tc1-ui/final/tc1-unittest.txt','tc1-ui/final/tc1-affected.txt',
                         'tc1-ui/final/tc1-structure.txt','tc1-ui/final/identity-browser.txt'):
                shutil.copy2(EVIDENCE/name, destination/Path(name).name)
            run(destination, 'package-compile', ['python','-m','compileall','-q','native-package'])
        finally:
            for name, expected in protected.items():
                shutil.copy2(backup/name, EVIDENCE/name)
                if sha((EVIDENCE/name).read_bytes()) != expected: raise ValueError('Completed evidence restoration failed')
            for path in EVIDENCE.rglob('*'):
                if path.is_file() and not path.is_relative_to(EVIDENCE/'native-package'):
                    name = str(path.relative_to(EVIDENCE))
                    if name not in protected and name not in GLOBALS: path.unlink()
            if [sha(path.read_bytes()) for path in media] != preserved_media: raise ValueError('Preserved WAV bytes changed')
    manifests = validate_manifests()
    aggregate = (destination/'tc1-unittest.txt').read_text()
    count = re.search(r'Ran (\d+) tests', aggregate)
    # Controlled legacy tests write diagnostic JSON to stdout after unittest's
    # stderr summary. A passing summary need not be the last physical line.
    if not count or not re.search(r'^OK$', aggregate, re.M): raise ValueError('Aggregate receipt is not passing')
    report = dict(kind='Offline only; no installed/native live or inference qualification',
        manifests=manifests, aggregate_python_tests=int(count[1]), completed_evidence_preserved=len(protected),
        immutable_wavs_preserved=len(media), bundle=first)
    (destination/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__': main()
