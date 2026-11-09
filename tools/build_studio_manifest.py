"""Build/check ONLY the unqualified development manifest and schema snapshot.

This developer utility writes only the checkout's schema and manifest when
--write-development is explicit. It never creates a release descriptor or
qualifies compatibility. Re-run after any managed payload edit, then --check.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('_studio_release_builder', ROOT / 'studio/release.py')
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

DEFAULTS_SPEC = importlib.util.spec_from_file_location('_studio_default_tools',
    ROOT / 'studio/default_dependencies.py')
assert DEFAULTS_SPEC is not None and DEFAULTS_SPEC.loader is not None
default_tools = importlib.util.module_from_spec(DEFAULTS_SPEC)
DEFAULTS_SPEC.loader.exec_module(default_tools)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write-development', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    release.safe_path(ROOT)
    release.require((ROOT / '.git').is_dir(), 'developer primary checkout required')
    schema_path = ROOT / 'schemas/studio-manifest.json'
    manifest_path = ROOT / release.MANIFEST
    release.safe_path(schema_path, existing=False)
    release.safe_path(manifest_path, existing=False)
    if args.write_development:
        if manifest_path.exists():
            current = release.validate_manifest(release.read_json(manifest_path))
            release.require(current['qualification'] == 'unqualified-development',
                            'refuse to overwrite a qualified manifest')
        schema_path.write_text(json.dumps(release.manifest_schema(), indent=2, sort_keys=True) + '\n')
        value = release.development_manifest(ROOT)
        value['packs'] = default_tools.DEFAULT_TOOL_PACKS
        release.validate_manifest(value)
        manifest_path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    release.require(release.read_json(schema_path) == release.manifest_schema(), 'schema snapshot differs')
    value = release.verify_tree(ROOT)
    release.require(value['packs'] == default_tools.DEFAULT_TOOL_PACKS,
                    'default tool packs differ; regenerate development manifest')
    print(json.dumps(dict(verified=True, qualification=value['qualification'],
        managed_files=len(value['payload']), manifest_sha256=release.digest(release.read_bytes(manifest_path)[0])),
        sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
