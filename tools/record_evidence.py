"""Record actual input hashes, dependency versions, palette contrast and candidate files."""
import os
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DESIGN = Path(os.environ.get('MOTION_STUDIO_DESIGN', Path.home() / '.hermes/profiles/app-design/workspace/design-documents/motion-studio'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def luminance(value):
    channels = [int(value[n:n+2], 16) / 255 for n in (1, 3, 5)]
    linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in channels]
    return sum(x * weight for x, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def main():
    evidence = ROOT / 'docs/evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    inputs = ['planning/creation-kickoff-r1.md', 'planning/creation-contract-r1.md',
              'planning/creation-evidence-r1.md', 'planning/creation-alignment-r2.md',
              'quality/foundation-review-r1.md',
              'quality/local-sfx-offline-review-r1.md', 'quality/local-sfx-live-preparation-r1.md',
              'quality/local-sfx-corrections-review-r1.md', 'quality/user-app-flexibility-review-r1.md',
              'quality/template-connectors-review-r1.md',
              'quality/template-connectors-ui-closure-r1.md',
              'engineering/hermes-connector-synthesis-r1.md', 'engineering/native-hermes-plugin-r1.md',
              'engineering/native-session-qualification-r1.md', 'quality/connector-synthesis-review-r1.md',
              'engineering/public-technical-proposal-r1.md', 'quality/connector-synthesis-closure-r1.md',
              'engineering/native-quick-create-blockers-r1.md', 'engineering/hermes-v0231-qualification-r1.md',
              'engineering/sfx-boundary-local-r2.md', 'engineering/sfx-boundary-contract-r1.md',
              'engineering/user-app-flexibility-r1.md', 'engineering/local-runtime-recovery-r1.md',
              'engineering/quick-create-local-sfx-r1.md', 'engineering/quick-create-recovery-loop-r1.md',
              'engineering/template-connectors-r1.md','engineering/tool-research-knowledge-r1.md',
              'engineering/hermes-inventory-instruction-integrity-r1.md',
              'planning/creation-generation-r1.md', 'source/full-design-brief.md',
              'ux/workspace.md', 'engineering/architecture.md', 'README.md',
              'incoming/creation-first-2026-11-10/motion-studio-quick-create-concept.png']
    manifest = [dict(path=str(DESIGN / p), sha256=digest(DESIGN / p)) for p in inputs]
    current = {
        'public-technical-proposal-r1.md':'309276269c68ffbe902d817d91769fdf4624fc05f0848ee335dd80c7f3f74431',
        'connector-synthesis-closure-r1.md':'66f72988c304e1056c44564621fbbed93dbc4ab352a3d0da5bf0ecbcd9f2fbbc',
        'native-quick-create-blockers-r1.md':'ee035ae4e78d492fe6b9ef1d9bb80bfc5387fd2b14ef8d1ae2544917544a3a0a',
        'hermes-v0231-qualification-r1.md':'59451e5407f4cc57715c5c7a0ee53e894c1a4ac8a962d505b6da6c7a18f72cb5',
        'native-session-qualification-r1.md':'3a94cb2ab3fe2308dd0b48028922cf69b55aade146563e0d87301e1b82b293e8',
        'connector-synthesis-review-r1.md':'56caff035d28de80a3e1e84d5608dcb3564157a28106473bc0c6fde18ba84919',
        'template-connectors-ui-closure-r1.md':'05c089038e780096fa127852772c8dec8be0622cebf5412f1f1588a35a35f188',
        'hermes-connector-synthesis-r1.md':'a4e88d364c383521992edc71e0bcb1a0d9aa2b27eddecbb854cc74bd329a774b',
        'native-hermes-plugin-r1.md':'bad707c8f50f0d09515338561d8bea62d8ffded7327a7731208151b419b335e3',
        'template-connectors-review-r1.md':'26ba94ee2fed0292d9df891628e5d94b08a413c44ae8fd5c370f0b981d3df0ab',
        'template-connectors-r1.md':'ae908a63740240d5e7f07d264f4bfaf3f8944bb37464ad3e4ac0ebcc085106b1',
        'tool-research-knowledge-r1.md':'8c311dded0a4cd50ab132f5ccae571db4c2d74824ce5a14725e258462237af15',
        'hermes-inventory-instruction-integrity-r1.md':'bff5da8d2913263ce0c729b059944ae47f3dfef92420c98101d78978fd9be494'}
    for leaf,expected_pin in current.items():
        assert next(x['sha256'] for x in manifest if x['path'].endswith('/'+leaf))==expected_pin
    assert next(x['sha256'] for x in manifest if x['path'].endswith('quick-create-local-sfx-r1.md')) == (
        '43a4f0d4d29ba52180006f5c523552db1e0f6e22fad64db198f605b22372977e')
    assert next(x['sha256'] for x in manifest if x['path'].endswith('quick-create-recovery-loop-r1.md')) == (
        '4d2311810b210c50b91516d1ed2808d7d045ab20db649da5b77ef9a47b264caf')
    assert next(x['sha256'] for x in manifest if x['path'].endswith('local-runtime-recovery-r1.md')) == (
        'c4a559d724bd413b4e9a203332c9ddcf6b7b27722c4fc4f8ab82e08349f22331')
    expected = '122b1312f25bc9067584897394f3128ac7964978e91a1a6ab18c113314caa629'
    assert next(x['sha256'] for x in manifest if x['path'].endswith('creation-alignment-r2.md')) == expected
    assert next(x['sha256'] for x in manifest if x['path'].endswith('sfx-boundary-local-r2.md')) == (
        '6596e9ba3209eea99c192ae1e4217190b1e754f6fbe393c966e5f174c5f506d8')
    assert next(x['sha256'] for x in manifest if x['path'].endswith('user-app-flexibility-r1.md')) == (
        '52ab2549e3af0305691af59a78ef05bdc8c4836afff5cb62fcf0e00418087f97')
    assert next(x['sha256'] for x in manifest if x['path'].endswith('local-sfx-offline-review-r1.md')) == (
        '9251e4eac063c253f688f5a3d59d62317fe366ad5972d82bd3d9142b97765d63')
    assert next(x['sha256'] for x in manifest if x['path'].endswith('local-sfx-live-preparation-r1.md')) == (
        'f2705a18bc26f9bb745e46802c1951a34dbfcae690878cbb6d6f5ddd0865ced3')
    assert next(x['sha256'] for x in manifest if x['path'].endswith('local-sfx-corrections-review-r1.md')) == (
        '8f4b179532232759f7c2bb3fe407e8038314e86dd4bc8055630a309a8a8d656c')
    assert next(x['sha256'] for x in manifest if x['path'].endswith('user-app-flexibility-review-r1.md')) == (
        'f1949658365df0d44ec500dedb5c6aa20abd9d1b47a484d972657dba11fbb544')
    (evidence / 'design-inputs.json').write_text(json.dumps(manifest, indent=2) + '\n')
    css = (ROOT / 'studio/views/style.css').read_text()
    tokens = dict(re.findall(r'--([a-z]+):(#[0-9a-f]{6})', css))
    pairs = [('text','bg'),('text','panel'),('muted','bg'),('muted','panel'),
             ('mint','bg'),('mint','panel'),('border','bg'),('border','panel'),('error','bg')]
    contrast = []
    for a, b in pairs:
        high, low = sorted((luminance(tokens[a]), luminance(tokens[b])), reverse=True)
        contrast.append(dict(foreground=a, background=b, ratio=(high+0.05)/(low+0.05)))
    high, low = sorted((luminance('#10231d'), luminance(tokens['mint'])), reverse=True)
    contrast.append(dict(foreground='primary text #10231d', background='mint', ratio=(high+0.05)/(low+0.05)))
    (evidence / 'contrast.json').write_text(json.dumps(contrast, indent=2) + '\n')
    versions = {x:importlib.metadata.version(x) for x in ('fastapi','uvicorn','pydantic','starlette','httpx')}
    versions['python'] = platform.python_version()
    versions['node'] = subprocess.check_output(['node','--version'], text=True).strip()
    (evidence / 'environment.json').write_text(json.dumps(versions, indent=2) + '\n')
    candidate = []
    for home in ('studio','tests','tools','native-package'):
        for path in sorted((ROOT / home).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                candidate.append(dict(path=str(path.relative_to(ROOT)),sha256=digest(path)))
    (evidence / 'code-manifest.json').write_text(json.dumps(candidate, indent=2) + '\n')
    print(json.dumps(dict(inputs=len(manifest), code_files=len(candidate),
                         minimum_text_contrast=min(x['ratio'] for x in contrast if x['foreground'] != 'border'),
                         minimum_border_contrast=min(x['ratio'] for x in contrast if x['foreground'] == 'border'),
                         versions=versions), indent=2))


if __name__ == '__main__':
    main()
