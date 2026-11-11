"""Record nonprivate comparison source, design and frozen-artifact identities only."""
import argparse
import os
import hashlib
import json
import re
from pathlib import Path
import subprocess
import struct
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT/'docs/evidence/production-comparison-r1'
DESIGN = Path(os.environ.get('MOTION_STUDIO_DESIGN', Path.home() / '.hermes/profiles/app-design/workspace/design-documents/motion-studio'))
INPUTS = ('ux/workspace.md', 'ux/states.md', 'quality/acceptance.md',
          'engineering/production-reuse-authority-r1.md')
PROTECTED = ('native-package/activation-entry.py', 'native-package/production-upgrade-entry.py',
             'tools/prepare_production_upgrade.py', 'tools/prepare_motion_studio_activation.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE/name).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def check_summary(reuse_wide=None):
    result = {}
    names = ('controller-final.json', 'browser-review.json') if reuse_wide else (
        'controller-final.json', 'browser-review.json', 'production-controller-final.json',
        'production-browser-final.json', 'creation-controller-final.json', 'creation-browser-final.json')
    for name in names:
        value = json.loads((EVIDENCE/name).read_text())
        checks = value['checks']
        result[name] = len(checks) if isinstance(checks, list) else checks
        assert not value.get('errors')
    if reuse_wide:
        result['unchanged_wider_evidence'] = str(reuse_wide.relative_to(ROOT))
        prior = json.loads((reuse_wide/'identity.json').read_text())
        result['wider_exact_source_manifest_sha256'] = prior['source_manifest_sha256']
        result['prior_wider_results_not_rerun'] = json.loads((reuse_wide/'checks-summary.json').read_text())
        return result
    log = (EVIDENCE/'python-final.txt').read_text()
    assert re.search(r'^OK$', log, re.M) and not re.search(r'^FAILED', log, re.M)
    match = re.search(r'Ran (\d+) tests', log)
    assert match is not None
    result['python_tests'] = int(match.group(1))
    result['sqlite_resource_warnings'] = log.count('ResourceWarning: unclosed database')
    return result


def main():
    global EVIDENCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-preserved', action='store_true')
    parser.add_argument('--evidence', type=Path, default=EVIDENCE)
    parser.add_argument('--package-prefix', default='motion-studio-comparison-r1-review')
    parser.add_argument('--reuse-wide-evidence', type=Path)
    args = parser.parse_args()
    EVIDENCE = args.evidence.absolute()
    baseline = EVIDENCE/'preserved-before.json'
    if args.capture_preserved:
        if baseline.exists():
            raise FileExistsError('Preservation baseline already exists')
        paths = [p for p in (ROOT/'dist').rglob('*') if p.is_file()]
        paths += [ROOT/name for name in PROTECTED]
        save(baseline.name, {str(p.relative_to(ROOT)):sha(p) for p in paths})
        print('Captured protected artifacts; no artifact changed.')
        return
    preserved = json.loads(baseline.read_text())
    mismatches = [name for name, digest in preserved.items() if sha(ROOT/name) != digest]
    if mismatches:
        raise AssertionError(mismatches)
    inputs = {name:sha(DESIGN/name) for name in INPUTS}
    assert inputs[INPUTS[-1]] == '0d6a35d3ea295f71199476f7c76fae3a6e3483f56f29987004c54d2d5d578e6a'
    paths = [p for home in ('studio', 'tests', 'tools', 'native-package')
             for p in (ROOT/home).rglob('*') if p.suffix in ('.js', '.mjs', '.cjs', '.py', '.json', '.yaml')
             and '__pycache__' not in p.parts]
    source = {str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
    save('source.json', source)
    names = (args.package_prefix+'-source.zip', args.package_prefix+'-reproduction.zip')
    package_paths = [ROOT/'dist/native'/name for name in names]
    assert package_paths[0].read_bytes() == package_paths[1].read_bytes()
    packages = {str(p.relative_to(ROOT)):sha(p) for p in package_paths}
    with zipfile.ZipFile(package_paths[0]) as archive:
        sources = json.loads(archive.read('motion-studio/SOURCE.json'))
        assert all(sha(ROOT/name) == digest for name, digest in sources.items())
        contents = json.loads(archive.read('motion-studio/CONTENTS.json'))
        assert set(archive.namelist()) == {'motion-studio/'+name for name in contents} | {'motion-studio/CONTENTS.json'}
        for name, expected in contents.items():
            data = archive.read('motion-studio/'+name)
            assert hashlib.sha256(data).hexdigest() == expected['sha256'] and len(data) == expected['bytes']
        package_entries = len(archive.namelist())
        measured = subprocess.run(['node', 'tools/js-spans.cjs', '--stdin', 'desktop/plugin.js'],
            input=archive.read('motion-studio/desktop/plugin.js'), capture_output=True, check=True)
        bundled_maximum = max(row['span'] for row in json.loads(measured.stdout))
        assert bundled_maximum <= 300
    historical = json.loads((ROOT/'docs/evidence/production-corrections-20261111/identity.json').read_text())
    for name, digest in historical['source_files'].items():
        data = subprocess.check_output(['git', 'show', 'cd3d0fd:'+name], cwd=ROOT)
        assert hashlib.sha256(data).hexdigest() == digest
    assert all(sha(ROOT/name) == digest for name, digest in historical['frozen'].items())
    fixture_checks = []
    for name, seconds, frequency in (('controlled-a-220hz-1.4s.wav', 1.4, 220), ('controlled-b-660hz-0.8s.wav', 0.8, 660)):
        path = EVIDENCE/name
        with wave.open(str(path)) as audio:
            rate, channels, frames = audio.getframerate(), audio.getnchannels(), audio.getnframes()
            assert audio.getsampwidth() == 2 and channels == 2 and frames/rate == seconds
            samples = [values[0] for values in struct.iter_unpack('<hh', audio.readframes(frames))]
            crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
            measured_hz = crossings/seconds
            assert abs(measured_hz-frequency) <= 2
            fixture_checks.append(dict(file=name, sha256=sha(path), seconds=seconds, channels=channels,
                rate=rate, measured_positive_crossings_hz=measured_hz, listening='Not reviewed'))
    save('fixture-checks.json', fixture_checks)
    checks = check_summary(args.reuse_wide_evidence.absolute() if args.reuse_wide_evidence else None)
    save('checks-summary.json', checks)
    save('identity.json', dict(source_manifest_sha256=sha(EVIDENCE/'source.json'),
         base=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
         design_root=str(DESIGN), design=inputs, packages=packages,
         preserved_artifacts=len(preserved), preserved_git_sources=len(historical['source_files']),
         frozen_artifacts=len(historical['frozen']), package_entries=package_entries,
         bundled_maximum=bundled_maximum, mismatches=mismatches, live_qualified=False))
    print(json.dumps(dict(preserved_artifacts=len(preserved), packages=packages, checks=checks, mismatches=mismatches)))


if __name__ == '__main__':
    main()
