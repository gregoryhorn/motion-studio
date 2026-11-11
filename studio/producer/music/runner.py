"""Inactive real bridge orchestration. No probe, fallback, import or runtime repair."""
import argparse
import json
from pathlib import Path
from ...domain import Fault
from ...producer.catalog import Catalog
from ...producer.music.adapter import Runtime
from ...producer.music.bridge import foreground, normalize
from ...producer.music.contract import launcher_vector


def run(plan, output, *, runtime=None):
    Catalog(declarative=False).for_plan(plan)
    runtime = runtime or Runtime(plan['binding'])
    # Defense in depth: direct bridge execution cannot bypass unresolved live gates.
    runtime.admit(plan, output)
    runtime.verify_sources()
    argv = launcher_vector(runtime.launcher(), plan, output.parent)
    code, stdout, stderr = foreground(argv, runtime.producer_environment(output), output.parent)
    normalize(plan, output, code, stdout, stderr)


def main(arguments):
    parser = argparse.ArgumentParser(description='Private owned Music bridge')
    parser.add_argument('--plan', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(arguments)
    try:
        run(json.loads(args.plan), Path(args.output))
        return 0
    except Exception:
        # Never expose producer errors, creative inputs, paths or media digests.
        return 1
