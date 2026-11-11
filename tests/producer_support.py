"""Explicit test-only binding and helpers; never imported by normal app launch."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from studio.domain import Fault, SaveRequest
from studio.persistence.store import identity
from studio.producer.local_sfx import Binding, check_pins, eligible_resources, PrepareSFX


@dataclass(frozen=True)
class FixtureBinding(Binding):
    path: Path = Path('/nonexistent-test-only')
    fixture_only: bool = True
    digest: str = ''
    free_mib: int = 8192
    use_allowed: bool = True
    conflict: bool = False
    disk_bytes: int = 128 * 1024 * 1024

    def executable(self):
        return self.path

    def pins(self):
        return {'route': 'TEST_ONLY_ARGV_FIXTURE', 'executable': str(self.path), 'sha256': self.digest}

    def admit(self, plan, output):
        check_pins({str(self.path): self.digest})
        eligible_resources(self.free_mib, self.use_allowed, self.disk_bytes, self.conflict)


def fixture_binding(root, mode='good', **options):
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'fixture-worker'
    source = Path(__file__).with_name('producer_fixture_child.py').read_text()
    # Absolute app Python avoids environment-dependent interpreter discovery.
    target.write_text('#!' + sys.executable + '\n' + source.split('\n', 1)[1])
    target.chmod(0o700)
    (root / 'mode').write_text(mode)
    return FixtureBinding(path=target, digest=hashlib.sha256(target.read_bytes()).hexdigest(), **options)


def prepare(runs, text='Non-private English SFX fixture', seconds=0.1):
    request = runs.store.save(SaveRequest(command=identity(), expected=0, text=text,
                                         kind='Sound effects', purpose='Non-private test'))
    model = PrepareSFX(command=identity(), request=request['id'], revision=1, seconds=seconds, seed=42)
    return runs.prepare(model), model


def wait_run(runs, run, statuses=None):
    statuses = statuses or {'Ready for review', 'Collection blocked', 'Failed', 'Cancelled', 'Outcome unknown', 'Blocked'}
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        row = runs.records.get(run)
        if row['status'] in statuses:
            return row
        time.sleep(0.01)
    row = runs.records.get(run)
    raise AssertionError(f"Offline run did not reach expected state: {row['status']} / {row['error']}")


def effects(binding):
    path = binding.path.parent / 'effects.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
