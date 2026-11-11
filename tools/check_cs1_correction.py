"""Focused CS1 correction gates; preserve every completed CS1 receipt byte-for-byte."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from tools.check_connector_ui import sha

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'docs/evidence/cs1'
FINAL = ROOT/'docs/evidence/cs1-correction/final'


def run(label, args):
    with (FINAL/(label+'.txt')).open('w') as output:
        result = subprocess.run(args, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=False)
    print(json.dumps(dict(check=label, exit=result.returncode)), flush=True)
    if result.returncode: raise SystemExit(result.returncode)


def main():
    FINAL.mkdir(parents=True, exist_ok=True)
    protected = {str(p.relative_to(OLD)):sha(p) for p in OLD.rglob('*') if p.is_file()}
    backup = Path(tempfile.mkdtemp(prefix='motion-cs1-correction-'))
    for name in protected:
        (backup/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OLD/name, backup/name)
    try:
        run('ui-sdk', ['node', '--test', 'tests/synthesis-correction.mjs'])
        run('affected', ['python', '-m', 'unittest', 'tests.test_synthesis_correction',
            'tests.test_connector_synthesis', 'tests.test_synthesis_boundaries', 'tests.test_synthesis_native_scope', '-v'])
        try:
            run('full-cs1', ['python', '-m', 'tools.check_cs1'])
        finally:
            for file in OLD.rglob('*'):
                if not file.is_file(): continue
                name = str(file.relative_to(OLD))
                fresh = name.startswith('final/') or name in ('browser.json', 'sdk.json', 'proposals.png', 'unknowns.png')
                if fresh or name not in protected or sha(file) != protected[name]:
                    target = FINAL/'cs1'/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
    finally:
        for name, expected in protected.items():
            shutil.copy2(backup/name, OLD/name)
            if sha(OLD/name) != expected: raise RuntimeError('Completed CS1 evidence changed')
        for file in OLD.rglob('*'):
            if file.is_file() and str(file.relative_to(OLD)) not in protected: file.unlink()
        for file in backup.rglob('*'):
            if file.is_file(): file.unlink()
        for directory in sorted((p for p in backup.rglob('*') if p.is_dir()), reverse=True): directory.rmdir()
        backup.rmdir()
    report = dict(kind='Offline correction; no deployed authentication or model qualification',
        prior_cs1_files_preserved=len(protected),
        source_entries=len(json.loads((ROOT/'docs/evidence/code-manifest.json').read_text())),
        input_entries=len(json.loads((ROOT/'docs/evidence/design-inputs.json').read_text())),
        source_manifest=sha(ROOT/'docs/evidence/code-manifest.json'),
        input_manifest=sha(ROOT/'docs/evidence/design-inputs.json'))
    (FINAL/'preservation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
