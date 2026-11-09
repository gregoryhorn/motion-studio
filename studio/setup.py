"""Portable diagnostics and explicit bounded native disabled staging.

No import-time probes, subprocesses, network, writes, native private imports or
manifest commands. Diagnostics are read-only. Explicit stage_native_disabled
invokes the public host installer. Presence is not version/provenance qualification.
"""
import importlib.metadata
import importlib.util
import os
import subprocess
from pathlib import Path
import platform
import re
import shutil
from typing import Any

# Also usable by the standalone helper without importing an installed plugin.
_SPEC = importlib.util.spec_from_file_location('_studio_setup_release', Path(__file__).with_name('release.py'))
assert _SPEC is not None and _SPEC.loader is not None
release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release)

NATIVE_REQUIREMENTS = [
    'supported public selected-pack installation interface',
    'exact approved immutable release and source verification',
    'native scanner receipt and explicit finding review',
    'native dependency consent and shared-environment conflict refusal',
    'recoverable native publication and activation readback',
]


def constraint_status(version, constraint):
    """Conservative numeric comparator subset; unsupported syntax stays unknown.

    This is diagnostic only, never a substitute for the native resolver/PEP 440.
    """
    if not version or not constraint or not re.fullmatch(r'\d+(?:\.\d+)*', version):
        return 'unknown'
    clauses = []
    for clause in constraint.split(','):
        match = re.fullmatch(r'\s*(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)\s*', clause)
        if not match:
            return 'unknown'
        clauses.append(match.groups())
    for op, target in clauses:
        left, right = tuple(map(int, version.split('.'))), tuple(map(int, target.split('.')))
        width = max(len(left), len(right))
        left += (0,) * (width - len(left))
        right += (0,) * (width - len(right))
        if not {'>=': left >= right, '<=': left <= right, '==': left == right,
                '>': left > right, '<': left < right}[op]:
            return 'incompatible'
    return 'compatible'


def host_snapshot():
    """Passive standard-library observation; never execute a host CLI."""
    return dict(platform=platform.system().lower(), architecture=platform.machine().lower(),
                python=platform.python_version(), hermes_version=None, hermes_revision=None,
                evidence='platform module; Hermes runtime identity not observed')


def host_compatibility(manifest, host):
    comp = manifest['compatibility']
    result = {}
    for key, field in [('platform', 'platforms'), ('architecture', 'architectures')]:
        result[key] = ('unknown' if not comp[field] or not host.get(key) else
                       'supported' if host[key] in comp[field] else 'unsupported')
    result['python'] = constraint_status(host.get('python'), comp['python'])
    result['hermes'] = constraint_status(host.get('hermes_version'), comp['hermes'])
    revision = host.get('hermes_revision')
    result['tested_host_revision'] = ('unknown' if not revision or not comp['tested_host_revisions'] else
        'listed' if revision in comp['tested_host_revisions'] else 'not-listed')
    result['qualification'] = manifest['qualification']
    result['status'] = ('declared-compatible-not-runtime-qualified' if
        result['platform'] == result['architecture'] == 'supported' and
        result['python'] == result['hermes'] == 'compatible' and
        result['tested_host_revision'] == 'listed' and manifest['qualification'] == 'qualified'
        else 'blocked')
    return result


def inspect_dependency(root, dep):
    result: dict[str, Any] = dict(dep, status='unknown', observed_version=None, version_status='unknown',
                  provenance_status='unknown', evidence=[])
    if dep['delivery'] == 'bundled':
        try:
            relative = release.payload_path(dep['identifier'])
            data, _ = release.read_bytes(root / relative)
            valid = dep['size'] == len(data) and dep['sha256'] == release.digest(data)
            result.update(status='verified-bytes' if valid else 'invalid',
                          evidence=['bounded bundled file size and SHA-256 comparison'],
                          provenance_status='manifest-hash-match' if valid else 'hash-mismatch')
        except (release.ValidationError, OSError):
            result.update(status='invalid', evidence=['bundled path missing, unsafe or unreadable'])
    elif dep['kind'] == 'executable':
        # Never accept a manifest path as executable discovery or run --version.
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}', dep['identifier']):
            path = shutil.which(dep['identifier'])
            if path:
                result.update(status='present-unqualified', evidence=['PATH executable located; not executed'])
            else:
                result.update(status='missing', evidence=['PATH executable not found'])
        else:
            result.update(status='unknown', evidence=['identifier is not a bare executable name'])
    elif dep['kind'] == 'python':
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', dep['identifier']):
            try:
                version = importlib.metadata.version(dep['identifier'])
                result.update(status='present-unqualified', observed_version=version,
                              version_status=constraint_status(version, dep['constraint']),
                              evidence=['installed distribution metadata only; module not imported'])
            except importlib.metadata.PackageNotFoundError:
                result.update(status='missing', evidence=['installed distribution metadata absent'])
            except (ValueError, OSError):
                result['evidence'] = ['installed distribution metadata unreadable']
    elif dep['delivery'] == 'download':
        result.update(status='not-downloaded', evidence=['manifest download declaration only; no network used'])
    else:
        result['evidence'] = ['no passive locator for this existing resource/model; explicit native binding required']
    if dep['constraint'] is None:
        result['version_status'] = 'unspecified'
    return result


def scanner_findings(value, manifest_sha256):
    """Keep externally supplied scanner observations separate from our evidence.

    Binding to manifest bytes is necessary but does not authenticate the caller or
    prove a native scan ran. The native installer must obtain its own receipt.
    """
    result: dict[str, Any] = dict(status='not_run', scanner=None, findings=[],
                  evidence_status='no scanner evidence', protection_bypass_allowed=False)
    if value is None:
        return result
    result['evidence_status'] = 'caller-supplied-not-independently-verified'
    if not isinstance(value, dict):
        result['status'] = 'invalid'
        return result
    statuses = ('passed', 'failed', 'disabled', 'not_run', 'review_required')
    rows = value.get('findings')
    scanner = value.get('scanner')
    if (value.get('status') not in statuses or value.get('manifest_sha256') != manifest_sha256
            or not isinstance(scanner, str) or not 0 < len(scanner) <= 256
            or not isinstance(rows, list) or len(rows) > 256):
        result['status'] = 'invalid'
        return result
    for row in rows:
        if (not isinstance(row, dict) or row.get('classification') not in ('observed', 'heuristic')
                or row.get('severity') not in ('info', 'warning', 'error')
                or any(not isinstance(row.get(key), str) or not 0 < len(row[key]) <= 2048
                       for key in ('code', 'evidence'))):
            result['status'] = 'invalid'
            result['findings'] = []
            return result
        result['findings'].append({key: row[key] for key in ('classification', 'severity', 'code', 'evidence')})
    status = value['status']
    if status == 'passed' and rows:
        status = 'review_required'
    result.update(status=status, scanner=scanner)
    return result


def inspect_setup(root, *, selected_packs=None, host=None, scanner=None,
                  descriptor=None, approved_source=None):
    """Inspect only explicitly supplied root and manifest packs; never install.

    Required packs are always selected; optional omissions remain in the report.
    A descriptor/source pair enables shared release verification, not activation.
    """
    result: dict[str, Any] = dict(schema='motion/studio-setup-report/v1', read_only=True,
        manifest_status='invalid', manifest_sha256=None, version=None,
        payload=dict(status='not_checked'), release=dict(status='unverified'),
        host=host_snapshot() if host is None else dict(host), host_compatibility=None,
        packs=[], selected_packs=[], missing_optional_packs=[], findings=[],
        expected_download_bytes=dict(known=0, unknown_dependencies=0),
        scanner=scanner_findings(None, None), install_ready=False,
        native_installation=dict(status='unavailable', requirements=list(NATIVE_REQUIREMENTS),
            evidence='No supported public Hermes selected-pack installation adapter is bound.'))
    try:
        root = release.safe_path(root)
        raw, _ = release.read_bytes(root / release.MANIFEST, release.MAX_JSON)
        manifest = release.validate_manifest(release.parse_json(raw))
    except (release.ValidationError, OSError, ValueError):
        result['findings'].append(dict(code='MANIFEST_INVALID', status='observed',
            evidence='Shared bounded manifest/path validator refused the input.'))
        return result
    result.update(manifest_status='valid', manifest_sha256=release.digest(raw), version=manifest['version'])
    result['bundled_payload'] = dict(
        file_count=len(manifest['payload']),
        expected_bytes=sum(row['size'] for row in manifest['payload']),
        notice_members=[dict(row) for row in manifest['payload']
                        if any(word in Path(row['path']).name.lower()
                               for word in ('license', 'licence', 'notice', 'copying'))],
        evidence='Manifest inventory declarations; notice filename classification is heuristic, not legal review')
    try:
        release.verify_tree(root, manifest)
        result['payload'] = dict(status='verified', evidence='Shared exact inventory/native declaration validator')
    except (release.ValidationError, OSError):
        result['payload'] = dict(status='invalid', evidence='Shared payload/native declaration validation failed')
        result['findings'].append(dict(code='PAYLOAD_INVALID', status='observed',
            evidence='Payload differs, is unsafe, or disagrees with native declaration.'))
    if descriptor is not None and approved_source is not None:
        try:
            verified = release.verify_descriptor(root, descriptor, approved_source)
            result['release'] = dict(status='verified', descriptor=verified,
                                     evidence='Shared immutable descriptor and explicitly approved source verification')
        except (release.ValidationError, OSError):
            result['release'] = dict(status='invalid')
    result['host_compatibility'] = host_compatibility(manifest, result['host'])
    ids = {pack['id'] for pack in manifest['packs']}
    requested = [] if selected_packs is None else selected_packs
    release.require(isinstance(requested, (list, tuple)) and all(isinstance(x, str) for x in requested),
                    'selected packs must be a list of identifiers')
    release.require(len(set(requested)) == len(requested) and set(requested) <= ids, 'unknown/duplicate selected pack')
    selected = set(requested) | {pack['id'] for pack in manifest['packs'] if pack['required']}
    result['selected_packs'] = sorted(selected)
    for pack in manifest['packs']:
        dependencies = [inspect_dependency(root, dep) for dep in pack['dependencies']]
        supported = ('unknown' if not pack['platforms'] or not result['host'].get('platform') else
                     'supported' if result['host']['platform'] in pack['platforms'] else 'unsupported')
        missing = any(dep['status'] in ('missing', 'not-downloaded', 'invalid', 'unknown') for dep in dependencies)
        qualified = all(dep['status'] == 'verified-bytes' and dep['version_status'] in ('compatible', 'unspecified')
                        for dep in dependencies)
        result['packs'].append(dict(id=pack['id'], required=pack['required'], selected=pack['id'] in selected,
            platform_status=supported, compatibility=pack['compatibility'], operations=pack['operations'],
            status='missing-or-unresolved' if missing else 'bytes-verified' if qualified else 'present-unqualified',
            dependencies=dependencies))
        if not pack['required'] and missing:
            result['missing_optional_packs'].append(pack['id'])
        if pack['id'] in selected:
            for dep in dependencies:
                if dep['delivery'] == 'download':
                    key = 'unknown_dependencies' if dep['size'] is None else 'known'
                    result['expected_download_bytes'][key] += 1 if dep['size'] is None else dep['size']
    result['scanner'] = scanner_findings(scanner, result['manifest_sha256'])
    return result


def stage_native_disabled(home, source, ref, *, hermes_cli):
    """Opt-in fresh immutable plugin download through the PUBLIC Hermes CLI.

    This is not apply, rollback, selected-pack installation, or activation. Native
    install owns cloning, scanning and publication. No force, policy bypass,
    dependency approval or enable is allowed. Invocation can publish even if its
    reply is lost: never infer rollback or retry automatically after uncertainty.
    Only an explicitly trusted executable and approved HTTPS source are accepted.
    """
    release.source_url(source)
    release.require(isinstance(ref, str) and re.fullmatch(r'[0-9a-f]{40}', ref),
                    'native install requires an exact lowercase 40-character SHA')
    home = release.safe_path(home)
    release.require(home.is_dir(), 'existing explicit profile home required')
    cli = Path(hermes_cli)
    release.require(cli.is_absolute() and cli.is_file() and os.access(cli, os.X_OK),
                    'explicit trusted absolute Hermes executable required')
    target = home / 'plugins' / 'motion-studio'
    release.safe_path(target, existing=False)
    release.require(not target.exists(), 'fresh disabled staging only; existing slot refused')
    metadata = home / 'plugins' / '.install-metadata.json'
    release.safe_path(metadata, existing=False)
    before = release.read_json(metadata) if metadata.exists() else {}
    release.require(isinstance(before, dict) and 'motion-studio' not in before,
                    'existing native provenance slot refused')
    env = dict(os.environ)
    # The caller already selected the exact home. Do not inherit another profile.
    env.pop('HERMES_PROFILE', None)
    env.pop('HERMES_PROFILE_NAME', None)
    env['HERMES_HOME'] = str(home)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    command = [str(cli), 'plugins', 'install', source, '--ref', ref,
               '--no-deps', '--no-enable']
    result: dict[str, Any] = dict(schema='motion/studio-native-disabled-stage/v1',
        status='unverified', installed=None, read_only=False,
        profile_home=str(home), source=source, ref=ref,
        scope='fresh-disabled-plugin-only', selected_packs_installed=False,
        activation='not-requested', rollback='unavailable',
        scanner='native-policy; no reusable scanner receipt',
        environment='no plugin dependency consent; CLI bootstrap remains host-owned',
        recovery='inspect native installed state; no automatic retry or removal')
    try:
        # No shell, terminal, or stdin: caution/secret/capability prompts cannot
        # obtain approval. Discard host logs: they can contain secrets or markup.
        done = subprocess.run(command, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
            cwd=str(home), timeout=300, check=False)
        result['native_exit_code'] = done.returncode
        if done.returncode != 0:
            result['status'] = 'native-refused-or-unverified'
            return result
    except (OSError, subprocess.TimeoutExpired):
        result['status'] = 'native-outcome-unknown'
        return result
    try:
        after = release.read_json(metadata)
        row = after.get('motion-studio') if isinstance(after, dict) else None
        release.require(isinstance(row, dict) and row.get('source') == source and
            row.get('revision') == ref and row.get('pinned') is True,
            'native provenance readback mismatch')
        # Native Git installs retain repository docs/tools beside plugin files.
        # Verify the declared managed payload, not the stronger publication-only
        # installed-root allowlist (which intentionally rejects those extras).
        manifest = release.verify_tree(target, installed=False)
        release.require(manifest['plugin_id'] == 'motion-studio', 'wrong staged plugin')
        result.update(status='staged-disk-verified', installed=True,
            manifest_sha256=release.digest(release.read_bytes(target / release.MANIFEST, release.MAX_JSON)[0]),
            disabled='native --no-deps contract; not a loaded-process observation',
            qualification=manifest['qualification'])
    except (release.ValidationError, OSError, ValueError, TypeError, KeyError):
        result['status'] = 'published-but-readback-unverified'
    return result


def prepare_installation(report, selected_packs, *, approval=None):
    """Prepare a data-only request, not an installer or executable command.

    Even apparently clean scanner input is not native receipt evidence. No current
    host adapter is claimed; a future supported native owner must revalidate all
    bytes/host/scan/consent and read back publication. Never fall back to shell.
    """
    blockers = ['NATIVE_INSTALL_INTERFACE_UNAVAILABLE']
    ids = {pack['id'] for pack in report['packs']}
    valid = (isinstance(selected_packs, (list, tuple)) and bool(selected_packs)
             and all(isinstance(x, str) for x in selected_packs)
             and len(set(selected_packs)) == len(selected_packs) and set(selected_packs) <= ids)
    selection = sorted(selected_packs) if valid else []
    if not valid:
        blockers.append('UNKNOWN_PACK')
    if not {pack['id'] for pack in report['packs'] if pack['required']} <= set(selection):
        blockers.append('REQUIRED_PACK_APPROVAL_MISSING')
    approved = (valid and isinstance(approval, dict) and
        approval.get('manifest_sha256') == report['manifest_sha256'] and
        approval.get('packs') == selection and report['manifest_sha256'] is not None)
    if not approved:
        blockers.append('EXPLICIT_APPROVAL_REQUIRED')
    if report['manifest_status'] != 'valid' or report['payload']['status'] != 'verified':
        blockers.append('MANIFEST_OR_PAYLOAD_INVALID')
    if report['release']['status'] != 'verified':
        blockers.append('IMMUTABLE_APPROVED_RELEASE_REQUIRED')
    if not report['host_compatibility'] or report['host_compatibility']['status'] == 'blocked':
        blockers.append('HOST_UNQUALIFIED')
    if report['scanner']['status'] != 'passed':
        blockers.append('SCANNER_NOT_CLEAN')
    blockers.append('NATIVE_SCANNER_RECEIPT_REQUIRED')
    for pack in report['packs']:
        if pack['id'] in selection:
            if pack['platform_status'] != 'supported' or pack['compatibility'] is None:
                blockers.append('PACK_COMPATIBILITY_UNQUALIFIED')
            if any(dep['source'] is None for dep in pack['dependencies'] if dep['delivery'] == 'download'):
                blockers.append('DEPENDENCY_PROVENANCE_UNKNOWN')
            if any(dep['version_status'] == 'incompatible' for dep in pack['dependencies']):
                blockers.append('DEPENDENCY_VERSION_INCOMPATIBLE')
            if any(dep['status'] == 'invalid' for dep in pack['dependencies']):
                blockers.append('DEPENDENCY_INVALID')
            if any(dep['status'] == 'present-unqualified' for dep in pack['dependencies']):
                blockers.append('EXISTING_DEPENDENCY_NATIVE_QUALIFICATION_REQUIRED')
    return dict(status='blocked', installed=False, blockers=sorted(set(blockers)),
        request=dict(schema='motion/studio-native-pack-request/v1',
            manifest_sha256=report['manifest_sha256'], packs=selection,
            required_packs=sorted(pack['id'] for pack in report['packs'] if pack['required']),
            release=report['release'].get('descriptor'), approval_matched=approved,
            requirements=list(NATIVE_REQUIREMENTS), protection_bypass_allowed=False))
