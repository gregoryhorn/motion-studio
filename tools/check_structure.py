"""Measure complete function spans and file sizes, with installed Acorn for JS."""
import ast
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    functions, files = [], []
    for home in ('studio', 'tests', 'tools', 'native-package'):
        for path in sorted((root / home).rglob('*')):
            if path.suffix not in ('.py', '.js', '.mjs', '.cjs', '.html', '.css'):
                continue
            source = path.read_text()
            relative = str(path.relative_to(root))
            files.append(dict(path=relative, lines=len(source.splitlines()), bytes=path.stat().st_size))
            if path.suffix == '.py':
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        start = min([node.lineno] + [x.lineno for x in node.decorator_list])
                        assert node.end_lineno is not None
                        functions.append(dict(path=relative, name=node.name, start=start,
                                              end=node.end_lineno, span=node.end_lineno-start+1))
    javascript = subprocess.run(['node', 'tools/js-spans.cjs'], cwd=root,
                                capture_output=True, text=True, check=True)
    functions.extend(json.loads(javascript.stdout))
    report = dict(files=files, functions=functions, maximum=max(x['span'] for x in functions),
                  violations=[x for x in functions if x['span'] > 300])
    destination = args.output or root / 'docs/evidence/structure.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(functions=len(functions), maximum=report['maximum'],
                         violations=report['violations'], files=len(files)), indent=2))
    return bool(report['violations'])


if __name__ == '__main__':
    sys.exit(main())
