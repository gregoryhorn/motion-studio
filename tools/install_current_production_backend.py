"""Backend-only current-package placement using the reviewed same-store entry.

Invoked by prepare_production_workspace --install-current. No Desktop writes,
configuration changes, reload, credentials, media copy or generation.
"""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import os
import shutil
import zipfile
from tools.build_native_package import check_content


PROFILE = Path(os.environ.get('MOTION_STUDIO_PROFILE', Path.home() / '.hermes/profiles/motion-studio'))
ROOT = Path(__file__).resolve().parents[1]


def install(archive, *, profile=PROFILE):
    profile = Path(profile)
    target = profile / 'plugins/motion-studio'
    if target.is_symlink() or not target.is_dir():
        raise ValueError('EXISTING_PLUGIN_REQUIRED')
    files = {}
    with zipfile.ZipFile(archive) as bundle:
        for row in bundle.infolist():
            path = PurePosixPath(row.filename)
            if (not row.filename.startswith('motion-studio/') or path.is_absolute()
                    or '..' in path.parts or '\\' in row.filename):
                raise ValueError('PACKAGE_ENTRY_UNSAFE')
            name = row.filename.removeprefix('motion-studio/')
            if name.startswith('studio/') or name == 'plugin.yaml':
                if name in files:
                    raise ValueError('PACKAGE_DUPLICATE')
                files[name] = bundle.read(row)
    check_content(files)
    required = ('studio/native/production/media.py', 'studio/native/production/registration.py',
                'studio/media_import/service.py', 'studio/production_export/service.py')
    if not all(name in files for name in required):
        raise ValueError('INTEGRATED_BACKEND_REQUIRED')
    entry = (ROOT / 'native-package/production-upgrade-entry.py').read_text()
    entry = entry.replace('Inactive same-store Production candidate. Loading requires separate live approval.',
                          'Current same-store Production backend; authorized existing SFX audience only.')
    entry = entry.replace('production-retained-reuse-activation-r1', 'production-integrated-backend-r1')
    files['__init__.py'] = entry.encode()
    compile(entry, '__init__.py', 'exec')
    # Check every destination before the first write; runtime data is elsewhere
    # and never enumerated or copied. Existing Desktop code is deliberately held.
    for name in files:
        destination = target / name
        if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
            raise ValueError('INSTALL_SYMLINK_DENIED')
    backup = profile / 'development-backups' / ('production-integrated-' +
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True, exist_ok=False)
    for source in target.rglob('*'):
        relative = source.relative_to(target)
        if source.is_symlink():
            raise ValueError('BACKUP_SYMLINK_DENIED')
        if source.is_file() and '__pycache__' not in relative.parts and (
                relative.parts[0] in ('studio', 'dashboard', 'desktop') or source.name in (
                    '__init__.py', 'plugin.yaml', 'README.md', 'CONTENTS.json', 'SOURCE.json',
                    'DESIGN-INPUTS.json', 'HOST-CONTRACT.json', 'Dependencies.json')):
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for name, data in files.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    # Verify exact installed code, without a private-state or hash manifest.
    if any((target / name).read_bytes() != data for name, data in files.items()):
        raise ValueError('INSTALLED_CODE_MISMATCH')
    return dict(installed=True, backend_files=len(files), backup=str(backup),
                production_revision='production-integrated-backend-r1',
                desktop_changed=False, runtime_state_copied=False)
