"""Current, INACTIVE same-store Production package; no apply/install/grant mode."""
import argparse
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

from studio.native.setup_preparation import validate_new_output
from tools.build_native_package import check_content, encoded, host_contract, sha
from tools.prepare_production_upgrade import ENTRY, ENTRY_SHA256, HOST, ROOT, manifest, zipped

ARCHIVE = ROOT / 'dist/native/motion-studio-music-authority-r2-source.zip'
PACKAGE_SHA256 = 'ad9e27564b67490c565bd4c39214bf27643223bc6af96cd22f9638abf9dbe548'
BUNDLE_ID = 'motion-studio-production-workspace-r2'
HISTORICAL = ROOT / 'dist/setup/motion-studio-production-upgrade-r1-final'


def inspect(archive=ARCHIVE, checkout=ROOT, host=HOST):
    archive, checkout = Path(archive), Path(checkout)
    if archive.is_symlink() or sha(archive.read_bytes()) != PACKAGE_SHA256:
        raise ValueError('PACKAGE_PIN_MISMATCH')
    with zipfile.ZipFile(archive) as bundle:
        rows = bundle.infolist()
        names = [row.filename for row in rows]
        if len(names) != 98 or names != sorted(set(names)):
            raise ValueError('PACKAGE_CONTENTS_MISMATCH')
        for row in rows:
            path = PurePosixPath(row.filename)
            if (not row.filename.startswith('motion-studio/') or path.is_absolute()
                    or '..' in path.parts or '\\' in row.filename or row.external_attr >> 16 != 0o100644):
                raise ValueError('PACKAGE_ENTRY_UNSAFE')
        files = {name.removeprefix('motion-studio/'): bundle.read(name) for name in names}
    if json.loads(files['CONTENTS.json']) != manifest({k:v for k,v in files.items() if k != 'CONTENTS.json'}):
        raise ValueError('PACKAGE_CONTENTS_MISMATCH')
    check_content(files)
    for name, digest in json.loads(files['SOURCE.json']).items():
        source = checkout / name
        if source.is_symlink() or not source.resolve().is_relative_to(checkout.resolve()) or sha(source.read_bytes()) != digest:
            raise ValueError('PRODUCT_SOURCE_MISMATCH')
    if host_contract(host) != json.loads(files['HOST-CONTRACT.json']):
        raise ValueError('HOST_INTERFACE_MISMATCH')
    if files['__init__.py'] != (checkout/'native-package/__init__.py').read_bytes():
        raise ValueError('NORMAL_ENTRY_MISMATCH')
    return files


def prepare(archive=ARCHIVE, checkout=ROOT, host=HOST, entry=ENTRY):
    files = inspect(archive, checkout, host)
    entry = Path(entry)
    if entry.is_symlink() or sha(entry.read_bytes()) != ENTRY_SHA256:
        raise ValueError('UPGRADE_ENTRY_MISMATCH')
    overlay = entry.read_bytes()
    compile(overlay, 'production-upgrade-entry.py', 'exec')
    combined = dict(files, **{'__init__.py':overlay})
    desktop = {k.removeprefix('desktop/'):v for k,v in files.items() if k.startswith('desktop/')}
    if len(desktop) != 15:
        raise ValueError('DESKTOP_COUNT_MISMATCH')
    # Reuse the reviewed finite sequence/rollback, never repin or rewrite its files.
    plan = json.loads((HISTORICAL/'upgrade-plan.json').read_text())
    plan.update(schema=BUNDLE_ID, status='INACTIVE', apply_implemented=False, approval_granted=False,
        package_sha256=PACKAGE_SHA256, package_entries=len(files),
        source_entries=len(json.loads(files['SOURCE.json'])), entry_sha256=ENTRY_SHA256,
        combined_tree_sha256=sha(encoded(manifest(combined))),
        desktop_tree_sha256=sha(encoded(manifest(desktop))),
        music=dict(prepare=False, effects=False, binding='', admission=False),
        targets=dict(python='~/.hermes/profiles/motion-studio/plugins/motion-studio',
            desktop='Existing Windows Hermes Desktop HERMES_HOME/desktop-plugins/motion-studio; resolve actual client home at action time',
            desktop_scope='App-wide on Windows client, not Linux backend; no second discovery door'),
        limits=['Source/package preparation only; not installation or a live grant',
            'Existing SFX identity/record/binding/store/root and retained output must remain unchanged',
            'Music denied; no new generator integration or activation',
            'Windows home/client version/toggle/render/audio and live backend lifecycle unverified'])
    plan['backup'] = dict(plan['backup'], location='~/.hermes/profiles/motion-studio/upgrade-backups/'+BUNDLE_ID)
    outputs = {'production-upgrade-entry.py':overlay, 'upgrade-plan.json':encoded(plan),
        'combined-tree.json':encoded(manifest(combined)), 'desktop-tree.json':encoded(manifest(desktop)),
        'combined-tree.zip':zipped(combined, 'motion-studio/'),
        'desktop-tree.zip':zipped(desktop, 'motion-studio/'),
        'source-package.zip':Path(archive).read_bytes()}
    outputs['review-source.json'] = encoded({name:sha((ROOT/name).read_bytes()) for name in (
        'tools/prepare_production_workspace.py', 'tests/test_production_workspace.py',
        'native-package/production-upgrade-entry.py', 'tools/prepare_production_upgrade.py')})
    outputs['review-manifest.json'] = encoded(manifest(outputs))
    return outputs


def write(output, allowed_root=ROOT/'dist/setup', **kwargs):
    target = validate_new_output(Path(output), allowed_root)
    outputs = prepare(**kwargs)
    review = zipped(outputs)
    target.mkdir(parents=True)
    for name, data in outputs.items():
        (target/name).write_bytes(data)
    (target/(BUNDLE_ID+'-review.zip')).write_bytes(review)
    return dict(status='INACTIVE', review_sha256=sha(review), files=manifest(outputs))


def verify(directory):
    directory = Path(directory)
    expected = prepare()
    actual = {p.name:p.read_bytes() for p in directory.iterdir() if p.is_file()}
    review_name = BUNDLE_ID+'-review.zip'
    if actual.pop(review_name) != zipped(expected) or actual != expected:
        raise ValueError('CANDIDATE_MISMATCH')
    with zipfile.ZipFile(io.BytesIO(expected['combined-tree.zip'])) as bundle:
        combined = {n.removeprefix('motion-studio/'):bundle.read(n) for n in bundle.namelist()}
    if [k for k,v in inspect().items() if combined[k] != v] != ['__init__.py']:
        raise ValueError('OVERLAY_DIFF_MISMATCH')
    # Validate stopped WIP identity without overwriting its final receipts.
    evidence = ROOT/'docs/evidence/music-authority-r2'
    identity = json.loads((evidence/'identity.json').read_text())
    if sha((evidence/'source.json').read_bytes()) != identity['source_manifest_sha256']:
        raise ValueError('AUTHORITY_MANIFEST_MISMATCH')
    for name, digest in json.loads((evidence/'source.json').read_text()).items():
        if sha((ROOT/name).read_bytes()) != digest:
            raise ValueError('AUTHORITY_SOURCE_MISMATCH')
    for name, digest in json.loads((evidence/'preserved-before.json').read_text()).items():
        if sha((ROOT/name).read_bytes()) != digest:
            raise ValueError('HISTORICAL_PRESERVATION_MISMATCH')
    return dict(status='INACTIVE', exact=True, overlay_only=True,
        files=manifest(expected), review_sha256=sha(zipped(expected)),
        historical_preserved=890, authority_runtime_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--verify', type=Path)
    group.add_argument('--install-current', type=Path,
                       help='Install only a current integrated backend into the existing motion-studio profile')
    args = parser.parse_args()
    if args.install_current:
        from tools.install_current_production_backend import install
        result = install(args.install_current.absolute())
    else:
        result = verify(args.verify) if args.verify else write(args.output.absolute())
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
