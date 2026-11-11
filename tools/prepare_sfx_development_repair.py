"""Three-file development repair from immutable AFC/SFX bytes. No installer/archive."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile
from tools.build_native_package import check_content, encoded, sha
from studio.native.setup_preparation import validate_new_output

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT/'dist/native/motion-studio-afc-source.zip'
BASE_SHA = 'e54740e5331693c99dc5238dbba32ff83e55eb3bd8e3202e39f0305577cacd11'
CHANGED = ('studio/native/creation/registration.py','desktop/source/transport.js','desktop/plugin.js')


def baseline():
    if sha(ARCHIVE.read_bytes()) != BASE_SHA:
        raise ValueError('BASELINE_PIN_MISMATCH')
    with zipfile.ZipFile(ARCHIVE) as bundle:
        rows = bundle.infolist()
        if len(rows) != 73 or len({r.filename for r in rows}) != 73:
            raise ValueError('BASELINE_CONTENTS_MISMATCH')
        if any(not r.filename.startswith('motion-studio/') or r.external_attr >> 16 != 0o100644 for r in rows):
            raise ValueError('BASELINE_ENTRY_UNSAFE')
        files = {r.filename.removeprefix('motion-studio/'):bundle.read(r) for r in rows}
    check_content(files)
    for name,facts in json.loads(files['CONTENTS.json']).items():
        if sha(files[name]) != facts['sha256'] or len(files[name]) != facts['bytes']:
            raise ValueError('BASELINE_CONTENTS_MISMATCH')
    return files


def replace_once(data, old, new):
    if data.count(old) != 1:
        raise ValueError('BASELINE_DELTA_CONTEXT_MISMATCH')
    return data.replace(old,new,1)


def delta(esbuild):
    files = baseline()
    registration = files[CHANGED[0]]
    needle = b"                if payload.pop('session_id', root) != root: raise Fault('CREATION_SCOPE_DENIED', 403)\n"
    envelope = b"                if 'profile' in payload:\n                    profile = payload.pop('profile')\n                    if not isinstance(profile, str) or not profile.strip() or profile != ctx.profile_name:\n                        raise Fault('CREATION_SCOPE_DENIED', 403)\n"
    after = {CHANGED[0]:replace_once(registration,needle,needle+envelope)}
    original = files[CHANGED[1]]
    needle = b"  const methods=options.methods||technicalMethods,namespace=options.namespace||'technical';\n"
    scope = b"  const workspace=namespace==='creation';\n  const unavailable=()=>workspace?Object.assign(new Error('WORKSPACE_PRIMARY_UNAVAILABLE'),\n    {code:'CREATION_PRIMARY_UNAVAILABLE'}):technicalUnavailable();\n"
    transport = replace_once(original,needle,needle+scope)
    transport = transport.replace(b'throw technicalUnavailable()',b'throw unavailable()')
    transport = replace_once(transport,b"r.mode==='local'",b"(r.mode==='local'||workspace&&r.mode==='remote')")
    after[CHANGED[1]] = transport
    if subprocess.check_output([str(esbuild),'--version'],text=True).strip() != '0.28.2':
        raise ValueError('COMPILER_PIN_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='afc-sfx-development-repair-') as temp:
        stage = Path(temp)
        for name,data in files.items():
            path = stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(after.get(name,data))
        subprocess.run([str(esbuild),str(stage/'desktop/source/entry.js'),'--bundle','--format=esm','--platform=browser',
            '--external:react','--external:@hermes/plugin-sdk','--charset=ascii','--legal-comments=none',
            '--log-level=error','--outfile='+str(stage/'desktop/plugin.js')],check=True)
        after[CHANGED[2]] = (stage/'desktop/plugin.js').read_bytes()
    check_content(after)
    return files,after


def prepare(output,esbuild):
    target = validate_new_output(Path(output),ROOT/'dist/development')
    files,after = delta(Path(esbuild))
    # Immutable prior artifacts/evidence only; no live/profile/private paths.
    preserved = {str(p.relative_to(ROOT)):sha(p.read_bytes()) for folder in ('dist','docs/evidence')
        for p in sorted((ROOT/folder).rglob('*')) if p.is_file()
        and not p.is_relative_to(ROOT/'docs/evidence/native-remote-primary-r1')}
    for prefix,values in (('before',{n:files[n] for n in CHANGED}),('after',after)):
        for name,data in values.items():
            path = target/prefix/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    receipt = dict(status='DEVELOPMENT_REPAIR_NOT_INSTALLED',baseline_sha256=BASE_SHA,
        files={n:dict(before=sha(files[n]),after=sha(after[n])) for n in CHANGED},
        desktop_files=7,desktop_sources=6,unchanged_package_entries=len(files)-len(after),
        entry_unchanged=True,association_unchanged=True,production_grant=False,music_grant=False,
        targets=dict(backend='~/.hermes/profiles/motion-studio/plugins/motion-studio/studio/native/creation/registration.py',
            desktop=r'%LOCALAPPDATA%\hermes\desktop-plugins\motion-studio'),
        rollback='Restore exact three saved code files only, preserve activation record/database/media and all committed state',
        preserved=preserved)
    (target/'identity.json').write_bytes(encoded(receipt))
    return receipt


def verify(output):
    target = Path(output);receipt = json.loads((target/'identity.json').read_text())
    if receipt['baseline_sha256'] != BASE_SHA:
        raise ValueError('BASELINE_PIN_MISMATCH')
    for name,facts in receipt['files'].items():
        for prefix in ('before','after'):
            if sha((target/prefix/name).read_bytes()) != facts[prefix]:
                raise ValueError('DELTA_MISMATCH')
    for name,digest in receipt['preserved'].items():
        if sha((ROOT/name).read_bytes()) != digest:
            raise ValueError('PRESERVATION_MISMATCH: '+name)
    return dict(exact=True,changed_files=list(receipt['files']),preserved_paths=len(receipt['preserved']),
                production_grant=False,music_grant=False,baseline_sha256=BASE_SHA)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output',type=Path);group.add_argument('--verify',type=Path)
    parser.add_argument('--esbuild',type=Path)
    args = parser.parse_args()
    result = verify(args.verify) if args.verify else prepare(args.output.absolute(),args.esbuild.absolute())
    if not args.verify:
        result = {k:v for k,v in result.items() if k != 'preserved'}
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
