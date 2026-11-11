"""Bounded Linux process metadata only: never adoption, signalling or command/env reads."""
import os
from pathlib import Path
import time
from typing import Any

MAX_PROCESSES = 65536


def snapshot(pin) -> dict[str, Any]:
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    members, errors, leader = [], [], None
    count = 0
    with os.scandir('/proc') as scan:
        for entry in scan:
            if not entry.name.isdigit():
                continue
            count += 1
            if count > MAX_PROCESSES:
                errors.append('PROCESS_SCAN_LIMIT')
                break
            try:
                tail = Path(entry.path, 'stat').read_text().rsplit(')', 1)[1].split()
                value = dict(pid=int(entry.name), state=tail[0], parent=int(tail[1]),
                             group=int(tail[2]), session=int(tail[3]), start=tail[19])
                if value['pid'] == pin['pid']:
                    leader = value
                if value['group'] == pin['group'] or value['session'] == pin['session']:
                    members.append(value)
            except FileNotFoundError:
                pass
            except (OSError, ValueError, IndexError) as error:
                errors.append(type(error).__name__)
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    elapsed = uptime - int(pin['start']) / os.sysconf('SC_CLK_TCK')
    retired = (boot == pin['boot'] and not errors and leader is None
               and not any(value['state'] not in ('Z', 'X') for value in members))
    return dict(boot=boot, leader=leader, members=members, errors=errors,
                elapsed=elapsed, retired=retired, monotonic=time.monotonic(), epoch=time.time())


def retirement(pin):
    # SIGKILL and leader reaping can precede a descendant's kernel retirement.
    # Require the same two consecutive clear scans, allowing a bounded settling
    # interval. A surviving group, reused PID, scan error or wrong boot stays denied.
    observations = [snapshot(pin)]
    for _ in range(9):
        time.sleep(0.025)
        observations.append(snapshot(pin))
        observations = observations[-2:]
        if all(value['retired'] for value in observations):
            return True, observations
    return False, observations
