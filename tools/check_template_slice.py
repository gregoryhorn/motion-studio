"""Run harmless final gates, preserving earlier browser evidence byte-for-byte."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'docs/evidence'
BROWSERS={
    'foundation':('browser.mjs',['desktop-empty.png','desktop-imported.png','narrow-imported.png','text-200.png','browser-results.json']),
    'producer':('browser-producer.mjs',['offline-producer.png','offline-browser-results.json']),
    'apps':('browser-apps.mjs',['f1-catalog.png','setup-narrow.png','f1-method-narrow.png','f1-browser-results.json']),
    'ordinary':('browser-quick-create.mjs',['qs1-ordinary.png','qs1-recovery.png','qs1-browser-results.json'])}


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name,command):
    with (EVIDENCE/f'tc1-{name}.txt').open('w') as receipt:
        result=subprocess.run(command,cwd=ROOT,stdout=receipt,stderr=subprocess.STDOUT,check=False)
    print(json.dumps(dict(check=name,exit=result.returncode)),flush=True)
    if result.returncode: raise SystemExit(result.returncode)


def main():
    for key in ('PLAYWRIGHT_PACKAGE','CHROME_EXECUTABLE','NODE_PATH'):
        if not os.environ.get(key): raise SystemExit('Supply existing '+key+'; no installation performed')
    run('affected',['python','-m','unittest','tests.test_template_connectors','tests.test_app_bindings',
        'tests.test_adapter_contract','tests.test_quick_create','tests.test_recovery_loop','tests.test_collection_cancellation',
        'tests.test_service_cleanup','tests.test_local_runs','tests.test_runtime_workspace','-v'])
    run('unittest',['python','-m','unittest','discover','-s','tests','-v'])
    run('compile',['python','-m','compileall','-q','studio','tests','tools'])
    for file in sorted((ROOT/'studio/views').glob('*.js')):
        with file.open() as source:
            result=subprocess.run(['node','--input-type=module','--check'],stdin=source,cwd=ROOT,capture_output=True,check=False)
        if result.returncode: raise SystemExit('JS syntax failed: '+file.name)
    for file in sorted((ROOT/'tests').glob('*.mjs')):
        result=subprocess.run(['node','--check',str(file)],cwd=ROOT,capture_output=True,check=False)
        if result.returncode: raise SystemExit('Browser syntax failed: '+file.name)
    print('JavaScript/browser syntax passed',flush=True)
    run('structure',['python','tools/check_structure.py'])
    backup=Path(tempfile.mkdtemp(prefix='motion-template-evidence-'))
    protected={}
    try:
        for _,files in BROWSERS.values():
            for name in files:
                source=EVIDENCE/name
                if source.exists():
                    protected[name]=sha(source)
                    shutil.copy2(source,backup/name)
        for label,(script,files) in BROWSERS.items():
            run('browser-'+label,['node','tests/'+script])
            for name in files: shutil.copy2(EVIDENCE/name,EVIDENCE/('tc1-final-'+name))
        run('browser',['node','tests/browser-connectors.mjs'])
    finally:
        for name,expected in protected.items():
            shutil.copy2(backup/name,EVIDENCE/name)
            if sha(EVIDENCE/name)!=expected: raise RuntimeError('Evidence restoration failed')
            (backup/name).unlink()
        backup.rmdir()
    run('manifests',['python','tools/record_evidence.py'])
    manifest=json.loads((EVIDENCE/'code-manifest.json').read_text())
    inputs=json.loads((EVIDENCE/'design-inputs.json').read_text())
    for item in manifest+inputs:
        if sha(ROOT/item['path'])!=item['sha256']: raise SystemExit('Manifest mismatch')
    for name in ('6c3c47e1b5464d7e83254097c6b33f8e','ba52e4b96cf74c378bcecc658d064c36'):
        if sha(ROOT/'var/media'/(name+'.wav'))!='5f3a7c8fac0a1971d759e24a4347baf7ebe0933d29b33f6cb9787adc024fbec2':
            raise SystemExit('Preserved media mismatch')
    print(json.dumps(dict(source_files=len(manifest),source_manifest=sha(EVIDENCE/'code-manifest.json'),
                         inputs=len(inputs),input_manifest=sha(EVIDENCE/'design-inputs.json'),
                         historical_browser_files_preserved=len(protected),immutable_wavs_preserved=2)),flush=True)


if __name__=='__main__': main()
