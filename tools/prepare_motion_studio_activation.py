"""Write an inactive, deterministic activation plan; never install or enable anything."""
import argparse
import hashlib
import json
from pathlib import Path

from studio.native.setup_preparation import prepare, validate_new_output, write_preparation

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ROOT / 'dist/native/motion-studio-afc-source.zip')
    parser.add_argument('--host-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output_root = ROOT / 'dist' / 'setup'
    output = validate_new_output(args.output, output_root)
    entry = ROOT / 'native-package/activation-entry.py'
    plan = prepare(args.archive.absolute(), ROOT, args.host_source.absolute(), entry)
    write_preparation(plan, entry, output, output_root)
    result = dict(status=plan['status'], ready=plan['ready'], output=str(output),
                  files={path.name: sha(path) for path in sorted(output.iterdir())})
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
