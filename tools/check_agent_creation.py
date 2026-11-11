"""Focused AFC offline gate; never installs, enables, contacts a host or runs models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile
from tools.build_native_package import build, sha, PINS

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = '17dde8bd66ba08e489cab38840592f5c72020355'
AFC = 'engineering/agent-first-creation-r1.md'


def run(destination, label, command):
    with (destination/(label+'.txt')).open('w') as receipt:
        result = subprocess.run(command, cwd=ROOT, stdout=receipt, stderr=subprocess.STDOUT)
    print(json.dumps(dict(check=label, exit=result.returncode)), flush=True)
    if result.returncode: raise SystemExit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    destination = args.evidence.absolute()
    if not destination.is_relative_to(ROOT/'docs/evidence/afc'): raise ValueError('Use AFC evidence directory')
    destination.mkdir(parents=True, exist_ok=False)
    for name in ('ESBUILD','HERMES_SOURCE','PLAYWRIGHT_PACKAGE','CHROME_EXECUTABLE','NODE_PATH'):
        if not os.environ.get(name): raise ValueError('Supply existing '+name)
    protected = {p:sha(p.read_bytes()) for p in (ROOT/'docs/evidence').rglob('*')
                 if p.is_file() and not p.is_relative_to(ROOT/'docs/evidence/afc')}
    wavs = [ROOT/'var/media'/(name+'.wav') for name in
            ('6c3c47e1b5464d7e83254097c6b33f8e','ba52e4b96cf74c378bcecc658d064c36')]
    media = [sha(p.read_bytes()) for p in wavs]  # Never printed/exported.
    original = json.loads(subprocess.check_output(['git','show',CHECKPOINT+':docs/evidence/design-inputs.json']))
    for item in original:
        if sha(Path(item['path']).read_bytes()) != item['sha256']: raise ValueError('Consumed input changed')
    design = Path(original[0]['path']).parents[1]
    additions = [design/AFC, design/'ux/journeys.md']
    inputs = original + [dict(path=str(p),sha256=sha(p.read_bytes())) for p in additions]
    if inputs[-2]['sha256'] != PINS[AFC]: raise ValueError('AFC revision mismatch')
    (destination/'design-inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    try:
        first = build(ROOT/'dist/native/motion-studio-afc-source.zip',Path(os.environ['ESBUILD']),Path(os.environ['HERMES_SOURCE']))
        second = build(ROOT/'dist/native/motion-studio-afc-reproduction.zip',Path(os.environ['ESBUILD']),Path(os.environ['HERMES_SOURCE']))
        if first['sha256'] != second['sha256']: raise ValueError('Reproduction mismatch')
        os.environ['NATIVE_BUNDLE'] = str(ROOT/first['bundle'])
        with zipfile.ZipFile(ROOT/first['bundle']) as archive:
            for entry in ('CONTENTS.json','SOURCE.json','HOST-CONTRACT.json','Dependencies.json'):
                (destination/('package-'+entry)).write_bytes(archive.read('motion-studio/'+entry))
        (destination/'reproducibility.json').write_text(json.dumps(dict(first=first,second=second,equal_bytes=True),indent=2)+'\n')
        modules = ['test_agent_creation','test_creation_host_roots','test_native_package','test_native_technical',
                   'test_quick_create','test_recovery_loop','test_collection_cancellation','test_service_cleanup',
                   'test_local_runs','test_producer_collection','test_runtime_workspace','test_app_bindings',
                   'test_adapter_contract','test_template_connectors','test_helper_environment']
        run(destination,'affected-python',['python','-m','unittest',*('tests.'+m for m in modules),'-v'])
        run(destination,'creation-sdk',['node','tests/agent-creation.mjs'])
        run(destination,'creation-browser',['node','tests/browser-agent-creation.mjs'])
        run(destination,'technical-sdk',['node','--test','tests/native-technical.mjs'])
        run(destination,'technical-browser',['node','tests/browser-native-package.mjs'])
        run(destination,'compile',['python','-m','compileall','-q','studio','tests','tools','native-package'])
        run(destination,'spans',['python','-m','tools.check_structure','--output',str(destination/'structure.json')])
    finally:
        if any(sha(p.read_bytes()) != expected for p,expected in protected.items()): raise ValueError('Protected evidence changed')
        if [sha(p.read_bytes()) for p in wavs] != media: raise ValueError('Protected media changed')
    python = re.search(r'Ran (\d+) tests', (destination/'affected-python.txt').read_text())
    if python is None: raise ValueError('Missing test count')
    summary = dict(kind='Source/offline fake effects only; no live install/access/generation',
        python_tests=int(python[1]), inputs=len(inputs), prior_inputs_unchanged=len(original),
        protected_evidence_files=len(protected), original_wavs_preserved=len(wavs),
        creation_sdk_checks=len(json.loads((destination/'creation-sdk.txt').read_text())['checks']),
        creation_browser_checks=len(json.loads((destination/'creation-browser.txt').read_text())['checks']),
        package=first, functions=json.loads((destination/'spans.txt').read_text()))
    (destination/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,sort_keys=True))


if __name__ == '__main__': main()
