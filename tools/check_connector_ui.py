"""R01/R02 gates over the existing TC1 harness; preserve completed TC1 evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from tools.check_template_slice import BROWSERS

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'docs/evidence'
FINAL=EVIDENCE/'tc1-ui/final'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command,path):
    with path.open('w') as receipt:
        result=subprocess.run(command,cwd=ROOT,stdout=receipt,stderr=subprocess.STDOUT,check=False)
    return result.returncode


def main():
    FINAL.mkdir(parents=True,exist_ok=True)
    backup=Path(tempfile.mkdtemp(prefix='motion-ui-evidence-'))
    protected={file.name:(sha(file),file.stat().st_mtime_ns) for file in EVIDENCE.glob('tc1-*') if file.is_file()}
    legacy={name:sha(EVIDENCE/name) for _,files in BROWSERS.values() for name in files}
    generated=['tc1-'+label+'.txt' for label in ('affected','unittest','compile','structure','browser-foundation',
        'browser-producer','browser-apps','browser-ordinary','browser','manifests')]
    generated += ['tc1-final-'+name for _,files in BROWSERS.values() for name in files]
    generated += ['tc1-browser-results.json','tc1-tool-flow.png']
    for name in protected: shutil.copy2(EVIDENCE/name,backup/name)
    code=1
    try:
        code=run(['python','-m','tools.check_template_slice'],FINAL/'gates.txt')
        if code==0:
            code=run(['node','tests/browser-connector-identity.mjs'],FINAL/'identity-browser.txt')
        for name in generated:
            file=EVIDENCE/name
            if file.exists() and (name not in protected or file.stat().st_mtime_ns!=protected[name][1]):
                shutil.copy2(file,FINAL/name)
    finally:
        for name,(expected,_) in protected.items():
            shutil.copy2(backup/name,EVIDENCE/name)
            if sha(EVIDENCE/name)!=expected: raise RuntimeError('TC1 evidence restoration failed')
            (backup/name).unlink()
        backup.rmdir()
    if code: raise SystemExit(code)
    if any(sha(EVIDENCE/name)!=expected for name,expected in legacy.items()):
        raise SystemExit('Earlier browser evidence changed')
    for manifest in ('code-manifest.json','design-inputs.json'):
        for item in json.loads((EVIDENCE/manifest).read_text()):
            if sha(ROOT/item['path'])!=item['sha256']: raise SystemExit('Final manifest mismatch')
    report=dict(scope='Harmless R01/R02 UI correction only',exit=0,prior_tc1_files_preserved=len(protected),
        prior_browser_files_preserved=len(legacy),source_manifest=sha(EVIDENCE/'code-manifest.json'),
        input_manifest=sha(EVIDENCE/'design-inputs.json'))
    (FINAL/'preservation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
