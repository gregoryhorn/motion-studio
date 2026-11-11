#!/usr/bin/env python
"""Focused workspace qualification, isolated outputs, no shared build or full suite."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run_check(name, command, output, env=None):
    """Preserve actual focused output and propagate nonzero status (including timeout)."""
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
        text, code = result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        text, code = 'WORKSPACE_CHECK_TIMEOUT\n', 124
    (output / (name + '.txt')).write_text(text)
    return dict(name=name, command=command, exit_code=code)


def source_manifest():
    paths = sorted((ROOT / 'tests/workspace_e2e').glob('*.py'))
    paths += sorted((ROOT / 'tests/workspace_e2e').glob('*.mjs'))
    paths += sorted((ROOT / 'tests/workspace_e2e').glob('*.js'))
    paths += [Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def spans():
    maximum = 0
    for path in [*(ROOT / 'tests/workspace_e2e').glob('*.py'), Path(__file__).resolve()]:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                maximum = max(maximum, (node.end_lineno or node.lineno) - node.lineno + 1)
    return maximum


def runtime_manifest():
    """Source bytes only; never inspect var, media, credentials or installed state."""
    paths = [ROOT / 'studio/domain.py', ROOT / 'tests/creation_support.py']
    for directory in ('native/creation', 'native/production', 'assets', 'persistence', 'runs', 'producer'):
        paths.extend((ROOT / 'studio' / directory).rglob('*.py'))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='NEW output directory; never overwrites evidence')
    parser.add_argument('--browser', action='store_true', help='Use an existing NATIVE_BUNDLE, never build it')
    parser.add_argument('--adapter', type=Path, help='Coordinator-owned module exporting createHarness()')
    parser.add_argument('--require-hooks', action='store_true', help='Exit 2 if any emerging UI hooks are missing')
    args = parser.parse_args(argv)
    if (args.adapter or args.require_hooks) and not args.browser:
        parser.error('--adapter/--require-hooks require --browser')
    if args.output:
        output = args.output.resolve()
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix='workspace-qualification-', dir=os.environ.get('TMPDIR')))
    runtime_before = runtime_manifest()
    checks: list[dict] = [run_check('api', [sys.executable, '-m', 'unittest', 'discover',
        '-s', 'tests/workspace_e2e', '-p', 'test_*.py', '-v'], output)]
    maximum = spans()
    checks.append(dict(name='python_function_spans', maximum=maximum, exit_code=0 if maximum <= 300 else 1))
    if args.browser:
        env = dict(os.environ, PYTHON=sys.executable, WORKSPACE_E2E_RECEIPT=str(output / 'browser.json'),
                   WORKSPACE_E2E_REQUIRE_HOOKS='1' if args.require_hooks else '0')
        if args.adapter:
            env['WORKSPACE_E2E_ADAPTER'] = str(args.adapter.resolve())
        checks.append(run_check('javascript_structure', ['node', 'tests/workspace_e2e/structure.mjs'], output, env))
        checks.append(run_check('browser', ['node', 'tests/workspace_e2e/browser.mjs'], output, env))
    runtime_after = runtime_manifest()
    checks.append(dict(name='runtime_source_stable', exit_code=0 if runtime_after == runtime_before else 1))
    code = next((check['exit_code'] for check in checks if check['exit_code']), 0)
    receipt = dict(mode='offline-focused-qualification', real_windows_qualified=False,
                   checks=checks, source=source_manifest(), exit_code=code,
                   browser_requested=args.browser, runtime_source=runtime_before)
    if args.browser and os.environ.get('NATIVE_BUNDLE'):
        receipt['package_sha256'] = hashlib.sha256(Path(os.environ['NATIVE_BUNDLE']).read_bytes()).hexdigest()
    (output / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Workspace qualification output: ' + str(output))
    for check in checks:
        print(check['name'] + ': exit ' + str(check['exit_code']))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
