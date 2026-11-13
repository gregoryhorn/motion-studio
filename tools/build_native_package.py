"""Allowlisted deterministic source bundle. No install/enable/host launch/network."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile
from tools.native_dependencies import versions

ROOT = Path(__file__).resolve().parents[1]
HOST_COMMIT = '3b421578588243f920886e6fe79a6faa87ea026e'
HOST_FILES = ('hermes_cli/plugin_host_child.py', 'hermes_cli/plugin_rpc.py', 'hermes_cli/plugins_state.py',
    'hermes_cli/plugins_manifest.py', 'agent/plugin_llm.py', 'gateway/session_plugin_rpc.py',
    'apps/desktop/src/sdk/index.ts', 'apps/desktop/src/sdk/profile-request.ts', 'apps/desktop/src/contrib/plugin.ts',
    'apps/desktop/src/lib/storage.ts', 'hermes_cli/plugin_isolation.py',
    'agent/auxiliary_client.py', 'agent/auxiliary_profile_gates.py', 'agent/prompt_cache_scope.py',
    'agent/tool_executor.py', 'model_tools.py', 'tools/registry.py', 'tools/delegate_tool.py',
    'gateway/session_local.py', 'gateway/session_authority.py', 'hermes_cli/plugins_context.py', 'tools/schema_sanitizer.py')
PYTHON = ('studio/domain.py', 'studio/persistence/primitives.py', 'studio/connectors/integrity.py',
    'studio/connectors/schema.py', 'studio/connectors/synthesis/evidence.py', 'studio/connectors/synthesis/validation.py',
    'studio/connectors/synthesis/host.py', 'studio/connectors/synthesis/jobs.py', 'studio/connectors/synthesis/service.py',
    'studio/native/technical/storage.py', 'studio/native/technical/records.py', 'studio/native/technical/runtime.py',
    'studio/native/technical/registration.py', 'studio/native/methods.py', 'studio/native/skills/__init__.py',
    # Package-owned instructions share this source allowlist and snapshot path.
    'studio/native/skills/core/SKILL.md', 'studio/native/skills/quick-create/SKILL.md', 'studio/native/skills/refine-take/SKILL.md',
    'studio/native/skills/production/SKILL.md', 'studio/native/skills/troubleshooting/SKILL.md',
    'studio/native/skills/achievement-story/SKILL.md',
    'studio/native/skills/art-direction/SKILL.md',
    'studio/native/skills/asset-source/SKILL.md',
    'studio/native/skills/beat-plan/SKILL.md',
    'studio/native/skills/brand-discover/SKILL.md',
    'studio/native/skills/brand-system/SKILL.md',
    'studio/native/skills/brief-author/SKILL.md',
    'studio/native/skills/chart-story/SKILL.md',
    'studio/native/skills/continuity-guide/SKILL.md',
    'studio/native/skills/cut-paper-treatment/SKILL.md',
    'studio/native/skills/design-reference/SKILL.md',
    'studio/native/skills/edit-rhythm/SKILL.md',
    'studio/native/skills/editorial-promo/SKILL.md',
    'studio/native/skills/evidence-explainer/SKILL.md',
    'studio/native/skills/feature-focus/SKILL.md',
    'studio/native/skills/frame-safety/SKILL.md',
    'studio/native/skills/generated-media/SKILL.md',
    'studio/native/skills/glass-depth/SKILL.md',
    'studio/native/skills/industrial-treatment/SKILL.md',
    'studio/native/skills/interaction-timing/SKILL.md',
    'studio/native/skills/interface-art/SKILL.md',
    'studio/native/skills/interface-art-audit/SKILL.md',
    'studio/native/skills/launch-story/SKILL.md',
    'studio/native/skills/media-plan/SKILL.md',
    'studio/native/skills/minimal-treatment/SKILL.md',
    'studio/native/skills/motion-language/SKILL.md',
    'studio/native/skills/motion-math/SKILL.md',
    'studio/native/skills/motion-vocabulary/SKILL.md',
    'studio/native/skills/premium-product-film/SKILL.md',
    'studio/native/skills/procedural-audio/SKILL.md',
    'studio/native/skills/production-direct/SKILL.md',
    'studio/native/skills/reference-analysis/SKILL.md',
    'studio/native/skills/reference-rebuild/SKILL.md',
    'studio/native/skills/revision-review/SKILL.md',
    'studio/native/skills/route-comparison/SKILL.md',
    'studio/native/skills/seamless-loop/SKILL.md',
    'studio/native/skills/sound-cues/SKILL.md',
    'studio/native/skills/studio-produce/SKILL.md',
    'studio/native/skills/visual-critique/SKILL.md',
    'studio/native/skills/voice-produce/SKILL.md',
    'studio/native/creation/policy.py', 'studio/native/creation/admission.py', 'studio/native/creation/runtime.py',
    'studio/native/creation/hermes.py', 'studio/native/creation/service.py', 'studio/native/creation/registration.py', 'studio/native/creation/music.py',
    'studio/native/production/policy.py', 'studio/native/production/models.py',
    'studio/native/production/records.py', 'studio/native/production/service.py',
    'studio/native/production/registration.py', 'studio/native/production/media.py', 'studio/persistence/store.py',
    'studio/producer/catalog.py', 'studio/producer/local_sfx.py', 'studio/producer/stable_adapter.py',
    'studio/producer/local_gpu.py', 'studio/producer/live_sfx.py', 'studio/producer/bindings.py', 'studio/producer/contracts.py', 'studio/producer/evaluation.py',
    'studio/runs/service.py', 'studio/runs/persistence.py', 'studio/runs/normal_admission.py',
    'studio/runs/admission.py', 'studio/runs/recovery.py', 'studio/runs/recovery_recipes.py',
    'studio/runs/technical_knowledge.py', 'studio/runs/helper_environment.py', 'studio/runs/owned_process.py',
    'studio/runs/process_observation.py', 'studio/runs/child_entry.py', 'studio/assets/producer_files.py',
    'studio/assets/runtime_workspace.py', 'studio/assets/producer_collection.py', 'studio/assets/retention.py',
    'studio/assets/wav.py', 'studio/assets/audio_profiles.py',
    'studio/producer/music/adapter.py', 'studio/producer/music/admission.py', 'studio/producer/music/audio.py',
    'studio/producer/music/bridge.py', 'studio/producer/music/contract.py', 'studio/producer/music/receipt.py',
    'studio/producer/music/entry.py', 'studio/producer/music/runner.py', 'studio/producer/music/pins.py',
    'studio/child_env.py', 'studio/media_import/__init__.py', 'studio/media_import/contracts.py', 'studio/media_import/containers.py',
    'studio/media_import/operations.py', 'studio/media_import/service.py', 'studio/media_import/validation.py',
    'studio/production_export/__init__.py', 'studio/production_export/manifest.py', 'studio/production_export/service.py',
    'studio/director/registration.py', 'studio/director/process.py',
    'studio/director/cards/inventory.py', 'studio/director/cards/evidence.py', 'studio/director/cards/schema.py', 'studio/director/cards/learning.py',
    'studio/director/review/crystal_ball.py', 'studio/director/review/reports.py',
    'studio/director/review/applicability.py',
    'studio/director/state/repository.py', 'studio/director/state/removal.py', 'studio/director/state/projections.py')
STATIC = ('plugin.yaml', '__init__.py', 'README.md', 'LICENSE', 'dashboard/manifest.json', 'dashboard/dist/index.js', 'dashboard/plugin_api.py')
FRONTEND = tuple('studio/native/frontend/'+name+'.js' for name in ('entry', 'transport', 'controller', 'page',
    'creation-controller', 'creation-page', 'creation-style', 'workspace-copy', 'retained-bytes', 'production-controller', 'production-page', 'production-style', 'production-plan',
    'comparison-controller', 'production-comparison', 'production-review', 'media-review', 'media-review-controller',
    'media-review-style', 'production-export', 'production-export-controller', 'help', 'methods-ui',
    'director-controller', 'director-page', 'director-take'))
PINS = {
 'engineering/native-ui-remote-primary-addendum-r1.md':'6b523a1ded1781057bbdc889e0838aeee20e5122e86eead1b211247a0fce338f',
 'engineering/music-ace-step-preflight-r1.md':'74ec54370c4afaf5c7aaf828e4d0f4c9c11ad3cee0979edf668574abb67f6a8a',
 'ux/workspace.md':'e5b3873c4c56a0d7482a5982375903fcae0ed4a336ad537a4af96aa45dc22cd4',
 'ux/states.md':'a7c93e4c60d8fe9446d382b66a250c825c58ebfe3376c856a8c459a85c843cd6',
 'quality/acceptance.md':'f9dcc4a6cc24f07572a54dd100affe21a40afe26e5b8e507dc3e5ce7ab07fb78',
 'engineering/agent-first-creation-r1.md':'8fdb6faa61e032b3639382a812c7880b995933195beac3d60794cd56bd4d52b0',
 'engineering/production-reuse-authority-r1.md':'0d6a35d3ea295f71199476f7c76fae3a6e3483f56f29987004c54d2d5d578e6a',
 'engineering/public-technical-proposal-r1.md':'309276269c68ffbe902d817d91769fdf4624fc05f0848ee335dd80c7f3f74431',
 'engineering/native-hermes-plugin-r1.md':'bad707c8f50f0d09515338561d8bea62d8ffded7327a7731208151b419b335e3',
 'engineering/native-session-qualification-r1.md':'3a94cb2ab3fe2308dd0b48028922cf69b55aade146563e0d87301e1b82b293e8',
 'engineering/hermes-connector-synthesis-r1.md':'a4e88d364c383521992edc71e0bcb1a0d9aa2b27eddecbb854cc74bd329a774b',
 'quality/connector-synthesis-closure-r1.md':'66f72988c304e1056c44564621fbbed93dbc4ab352a3d0da5bf0ecbcd9f2fbbc',
 'engineering/native-quick-create-blockers-r1.md':'ee035ae4e78d492fe6b9ef1d9bb80bfc5387fd2b14ef8d1ae2544917544a3a0a',
 'engineering/hermes-v0231-qualification-r1.md':'59451e5407f4cc57715c5c7a0ee53e894c1a4ac8a962d505b6da6c7a18f72cb5'}


def sha(value): return hashlib.sha256(value).hexdigest()


def encoded(value): return (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()


def source(path):
    target = ROOT/path
    if target.is_symlink() or not target.resolve().is_relative_to(ROOT): raise ValueError('Source outside checkout')
    return target.read_bytes()


def relative_imports(path, value):
    text = value.decode()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import) and any(a.name.startswith('studio') for a in node.names):
            raise ValueError('Unexpected absolute package import')
    dots = '.'*len(PurePosixPath(path).parent.parts)
    return re.sub(r'^(\s*)from studio\.', r'\1from '+dots, text, flags=re.M).encode()


def host_contract(home):
    actual = subprocess.check_output(['git', '-C', str(home), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != HOST_COMMIT: raise ValueError('Host source revision mismatch')
    dirty = subprocess.check_output(['git', '-C', str(home), 'diff', 'HEAD', '--', *HOST_FILES])
    if dirty: raise ValueError('Reviewed host interface files changed')
    return dict(commit=actual, files={name:sha((home/name).read_bytes()) for name in HOST_FILES},
        qualification='Source interface inspection and offline fake ports only; no live installation/inference.')


def check_content(files):
    for name, value in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name: raise ValueError('Unsafe package path')
        if any(p in path.parts for p in ('var', 'tests', 'node_modules', '__pycache__', '.git')): raise ValueError('Excluded package path')
        # This exact generic rejection-regex fragment is not a user home path.
        inspected = value.replace(b'|/home/|/Users/|file://|', b'|rejected-path-prefixes|') if name == 'studio/connectors/synthesis/evidence.py' else value
        if any(marker in inspected for marker in (b'/home/', b'/tmp/', b'CONTROLLED_', b'BEGIN PRIVATE KEY', b'api_key=', b'var/media/')):
            raise ValueError('Excluded package content')
        if path.suffix == '.py': compile(value, name, 'exec')


def build(output, esbuild, host_source):
    if not output.resolve().is_relative_to(ROOT/'dist/native'): raise ValueError('Output must be under dist/native')
    compiler = subprocess.check_output([str(esbuild), '--version'], text=True).strip()
    if compiler != '0.28.2': raise ValueError('Reviewed compiler version required')
    original = {name:source(name) for name in (*PYTHON, *FRONTEND, 'studio/connectors/cli-template.json', 'studio/producer/stable_model_pins.json',
        *('native-package/'+name for name in STATIC), 'tools/build_native_package.py', 'tools/native_dependencies.py')}
    files = {name.removeprefix('native-package/'):original[name] for name in original if name.startswith('native-package/')}
    for name in PYTHON:
        files[name] = relative_imports(name, original[name]) if name.endswith('.py') else original[name]
        for parent in PurePosixPath(name).parents:
            if str(parent) != '.': files.setdefault(str(parent/'__init__.py'), b'')
    files['studio/connectors/cli-template.json'] = original['studio/connectors/cli-template.json']
    files['studio/producer/stable_model_pins.json'] = original['studio/producer/stable_model_pins.json']
    files.update({'desktop/source/'+name.removeprefix('studio/native/frontend/'):original[name] for name in FRONTEND})
    with tempfile.TemporaryDirectory(prefix='motion-native-build-') as temp:
        compiled = Path(temp)/'plugin.js'
        subprocess.run([str(esbuild), 'studio/native/frontend/entry.js', '--bundle', '--format=esm', '--platform=browser',
            '--external:react', '--external:@hermes/plugin-sdk', '--charset=ascii', '--legal-comments=none',
            '--log-level=error', '--outfile='+str(compiled)], cwd=ROOT, check=True)
        files['desktop/plugin.js'] = compiled.read_bytes()
    files['SOURCE.json'] = encoded({name:sha(value) for name,value in original.items()})
    files['DESIGN-INPUTS.json'] = encoded(PINS)
    files['HOST-CONTRACT.json'] = encoded(host_contract(host_source))
    files['Dependencies.json'] = encoded(dict(runtime_snapshot=versions(), build=dict(esbuild=compiler),
        direct_requirements=['pydantic>=2.14.1,<3', 'fastapi>=0.133.1,<1', 'PyYAML>=6.0.3,<7'],
        external_frontend=['react (host supplied)', '@hermes/plugin-sdk (host supplied)'],
        redistribution='No third-party implementation, wheels, tools or models bundled; Motion Studio is MIT licensed.'))
    check_content(files)
    files['CONTENTS.json'] = encoded({name:dict(bytes=len(value), sha256=sha(value)) for name,value in sorted(files.items())})
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name,value in sorted(files.items()):
            info = zipfile.ZipInfo('motion-studio/'+name, date_time=(1980,1,1,0,0,0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, value)
    return dict(bundle=str(output.relative_to(ROOT)), sha256=sha(output.read_bytes()), entries=len(files))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--esbuild', required=True, type=Path)
    parser.add_argument('--host-source', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output.absolute(), args.esbuild.absolute(), args.host_source.absolute()), sort_keys=True))


if __name__ == '__main__': main()
