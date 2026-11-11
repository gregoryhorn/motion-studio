"""Finite INACTIVE Production review bundle; no install, backup, restore or grant action."""
import argparse
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

from studio.native.setup_preparation import validate_new_output
from tools.build_native_package import check_content, encoded, host_contract, sha

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SHA256 = '73b301973c949ab69c22c19c41a68979b645262228043f5e236627d47119cda9'
ENTRY_SHA256 = '0a885c066137e43ad5fcb1c92267ede41b44798019e7c37d2cff1d5e212dd80f'
ENTRY = ROOT / 'native-package/production-upgrade-entry.py'
ARCHIVE = ROOT / 'dist/native/motion-studio-production-review-20261111.zip'
HOST = Path.home() / '.hermes/hermes-agent-official'
BUNDLE_ID = 'motion-studio-production-upgrade-r1'


def manifest(files):
    return {name: dict(bytes=len(data), sha256=sha(data)) for name, data in sorted(files.items())}


def zipped(files, prefix=''):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return stream.getvalue()


def inspect(archive, checkout, host):
    if archive.is_symlink() or sha(archive.read_bytes()) != PACKAGE_SHA256:
        raise ValueError('PACKAGE_PIN_MISMATCH')
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [row.filename for row in infos]
        if len(names) != 84 or names != sorted(set(names)):
            raise ValueError('PACKAGE_CONTENTS_MISMATCH')
        for row in infos:
            path = PurePosixPath(row.filename)
            if (not row.filename.startswith('motion-studio/') or '..' in path.parts
                    or '\\' in row.filename or path.is_absolute() or row.external_attr >> 16 != 0o100644):
                raise ValueError('PACKAGE_ENTRY_UNSAFE')
        files = {name.removeprefix('motion-studio/'): bundle.read(name) for name in names}
    contents = json.loads(files['CONTENTS.json'])
    if contents != manifest({k: v for k, v in files.items() if k != 'CONTENTS.json'}):
        raise ValueError('PACKAGE_CONTENTS_MISMATCH')
    check_content(files)
    sources = json.loads(files['SOURCE.json'])
    if len(sources) != 69:
        raise ValueError('SOURCE_COUNT_MISMATCH')
    for name, digest in sources.items():
        source = checkout / name
        if source.is_symlink() or not source.resolve().is_relative_to(checkout.resolve()) or sha(source.read_bytes()) != digest:
            raise ValueError('PRODUCT_SOURCE_MISMATCH')
    if host_contract(host) != json.loads(files['HOST-CONTRACT.json']):
        raise ValueError('HOST_INTERFACE_MISMATCH')
    if files['__init__.py'] != (checkout / 'native-package/__init__.py').read_bytes():
        raise ValueError('NORMAL_ENTRY_MISMATCH')
    return files


def prepare(archive=ARCHIVE, checkout=ROOT, host=HOST, entry=ENTRY):
    files = inspect(Path(archive), Path(checkout), Path(host))
    if Path(entry).is_symlink():
        raise ValueError('UPGRADE_ENTRY_MISMATCH')
    overlay = Path(entry).read_bytes()
    if sha(overlay) != ENTRY_SHA256:
        raise ValueError('UPGRADE_ENTRY_MISMATCH')
    compile(overlay, 'production-upgrade-entry.py', 'exec')
    combined = dict(files, **{'__init__.py': overlay})
    desktop = {k.removeprefix('desktop/'): v for k, v in files.items() if k.startswith('desktop/')}
    if len(desktop) != 12:
        raise ValueError('DESKTOP_COUNT_MISMATCH')
    combined_manifest, desktop_manifest = manifest(combined), manifest(desktop)
    plan = dict(schema=BUNDLE_ID, status='INACTIVE', apply_implemented=False,
        approval_granted=False, package_sha256=PACKAGE_SHA256, package_entries=84, source_entries=69,
        entry_sha256=ENTRY_SHA256, only_replacement='__init__.py',
        combined_tree_sha256=sha(encoded(combined_manifest)), desktop_tree_sha256=sha(encoded(desktop_manifest)),
        creation=dict(record='creation-activation.json', create_store=False, bootstrap=False,
                      identity='Existing instance/binding/revision/root/store only; stop on mismatch'),
        production=dict(profile='motion-studio', revision='production-retained-reuse-activation-r1',
            policy='Candidate server association; loading requires separate explicit Production policy approval',
            root='No admission by preparation or entry; explicit native production.admit required'),
        backup=dict(location='~/.hermes/profiles/motion-studio/upgrade-backups/'+BUNDLE_ID,
            retention='Preserve until Gregory explicitly approves removal; no deletion implemented',
            names=['same-store-consistent-backup', 'creation-activation.json', 'python-before',
                   'desktop-before', 'python-failed', 'desktop-failed', 'private-reconciliation.json']),
        sequence=['U1 quiesce and reconcile exact private receipt, identities, no active/unknown workers or concurrent writers',
            'U1 consistent private backup at named location; stop if location exists; preserve record/media/store and prior toggles',
            'U2 stage combined-tree.zip outside discovery; verify combined-tree.json including unchanged original CONTENTS.json',
            'U3 disable only motion-studio plugin; verify host retirement and lease release before rename to python-before',
            'U4 publish same-path tree, enable --no-allow-tool-override; profile-wide reload/MCP collateral requires approval',
            'U5 reconcile unchanged SFX; replace Desktop tree exactly, save desktop-before; native UI disposal remains live-unverified',
            'U6 only with separate policy/access approval admit original canonical root; no generation'],
        rollback=['Quiesce, disable, verify retirement and released lease',
            'Preserve new trees as python-failed/desktop-failed and ALL committed state',
            'Restore only python-before/desktop-before and prior toggle state, enable old code, reconcile SAME SFX receipt/audio',
            'No schema downgrade, state deletion, bootstrap or automatic backup restoration; failed rollback leaves disabled'],
        limits=['No live reads, install, grant, generation or publication',
            'Production retained-SFX only; full five-media/Production scope remains open',
            'Backup consistency, native rendering/audio, actual gateway unload/reload and listening remain untested'])
    outputs = {'production-upgrade-entry.py': overlay, 'combined-tree.json': encoded(combined_manifest),
        'desktop-tree.json': encoded(desktop_manifest), 'upgrade-plan.json': encoded(plan),
        'combined-tree.zip': zipped(combined, 'motion-studio/')}
    outputs['review-source.json'] = encoded({name: sha((ROOT / name).read_bytes()) for name in (
        'native-package/production-upgrade-entry.py', 'tools/prepare_production_upgrade.py',
        'tests/test_production_upgrade.py')})
    outputs['review-manifest.json'] = encoded(manifest(outputs))
    return outputs


def write(output, allowed_root, **kwargs):
    target = validate_new_output(output, allowed_root)
    outputs = prepare(**kwargs)
    review = zipped(outputs)
    target.mkdir(parents=True)
    for name, data in outputs.items():
        (target / name).write_bytes(data)
    (target / (BUNDLE_ID + '-review.zip')).write_bytes(review)
    return dict(status='INACTIVE', output=str(target), review_sha256=sha(review), files=manifest(outputs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--host-source', type=Path, default=HOST)
    args = parser.parse_args()
    print(json.dumps(write(args.output.absolute(), ROOT / 'dist/setup', host=args.host_source), sort_keys=True))


if __name__ == '__main__':
    main()
