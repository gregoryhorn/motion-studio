"""Offline CS1 gates over preserved TC1 UI/base gates; no real inference or install."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from tools.check_connector_ui import sha

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT/'docs/evidence'
FINAL = EVIDENCE/'cs1/final'


def run(label, command):
    with (FINAL/(label+'.txt')).open('w') as receipt:
        result = subprocess.run(command, cwd=ROOT, stdout=receipt, stderr=subprocess.STDOUT, check=False)
    print(json.dumps(dict(check=label, exit=result.returncode)), flush=True)
    if result.returncode: raise SystemExit(result.returncode)


def main():
    FINAL.mkdir(parents=True, exist_ok=True)
    # Existing files only, bounded known correction directory; no private state.
    old = EVIDENCE/'tc1-ui'
    backup = Path(tempfile.mkdtemp(prefix='motion-cs1-evidence-'))
    protected = {str(p.relative_to(old)):sha(p) for p in old.rglob('*') if p.is_file()}
    for name in protected:
        (backup/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old/name, backup/name)
    try:
        run('focused', ['python', '-m', 'unittest', 'tests.test_connector_synthesis',
            'tests.test_synthesis_boundaries', 'tests.test_synthesis_native_scope', '-v'])
        run('sdk', ['node', 'tests/synthesis-sdk.mjs'])
        run('browser', ['node', 'tests/browser-synthesis.mjs'])
        run('public-manual', ['python', '-m', 'tools.capture_sox_excerpt'])
        try:
            run('prior-gates', ['python', '-m', 'tools.check_connector_ui'])
        finally:
            for file in old.rglob('*'):
                if not file.is_file(): continue
                name = str(file.relative_to(old))
                fresh = name.startswith('final/') or name in ('final-browser.json', 'final-identity.png', 'final-first-failure.png')
                # Successful deterministic transcripts can equal the old bytes.
                # Still replace an earlier failed receipt in this NEW directory.
                if fresh or name not in protected or sha(file) != protected[name]:
                    target = FINAL/'prior-gates'/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
    finally:
        for name, expected in protected.items():
            shutil.copy2(backup/name, old/name)
            if sha(old/name) != expected: raise RuntimeError('Prior UI evidence changed')
        for file in backup.rglob('*'):
            if file.is_file(): file.unlink()
        for directory in sorted((p for p in backup.rglob('*') if p.is_dir()), reverse=True): directory.rmdir()
        backup.rmdir()
    # Prior wrappers already preserve base/legacy files and the immutable WAVs.
    for manifest in ('code-manifest.json', 'design-inputs.json'):
        for item in json.loads((EVIDENCE/manifest).read_text()):
            if sha(ROOT/item['path']) != item['sha256']: raise SystemExit('Final manifest mismatch')
    run('fixture-js-syntax', ['node', '--check', 'tests/synthesis-fixture.js'])
    report = dict(kind='Offline fake facade/SDK plus harmless prior fixture suites',
        prior_ui_files_preserved=len(protected), source_files=len(json.loads((EVIDENCE/'code-manifest.json').read_text())),
        input_files=len(json.loads((EVIDENCE/'design-inputs.json').read_text())),
        source_manifest=sha(EVIDENCE/'code-manifest.json'), input_manifest=sha(EVIDENCE/'design-inputs.json'))
    (FINAL/'preservation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
