"""Passive GPU observations only; never model loading, signalling or eviction."""
import csv
from pathlib import PurePosixPath
import re
import subprocess
from ..domain import Fault
from ..runs.helper_environment import helper_environment


def observe(*, conflict_root=None):
    def query(field):
        result = subprocess.run(['/usr/bin/nvidia-smi', '-i', '0', field,
                                 '--format=csv,noheader,nounits'], check=True,
                                capture_output=True, text=True, timeout=5,
                                env=helper_environment(), stdin=subprocess.DEVNULL)
        return list(csv.reader(result.stdout.splitlines()))
    try:
        memory = query('--query-gpu=memory.free')
        if len(memory) != 1 or len(memory[0]) != 1:
            raise ValueError()
        free = int(memory[0][0].strip())
        if free < 0:
            raise ValueError()
        processes, conflict = [], False
        for row in query('--query-compute-apps=pid,process_name,used_memory'):
            if len(row) != 3:
                raise ValueError()
            pid, name, used = row
            conflict |= conflict_root is not None and str(conflict_root) in name
            # Never retain a path or command arguments from driver output.
            name = PurePosixPath(name.strip().replace('\\', '/')).name
            name = re.sub(r'[^A-Za-z0-9_.+-]', '_', name)[:64] or 'unknown'
            pid, used = int(pid.strip()), int(used.strip())
            if pid <= 0 or used < 0:
                raise ValueError()
            processes.append(dict(pid=pid, name=name, used_mib=used))
        return dict(free_mib=free, processes=processes, conflict=conflict)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise Fault('RESOURCE_OBSERVATION_UNAVAILABLE', 409) from None


def require_available(required_mib, *, conflict_root=None):
    observation = observe(conflict_root=conflict_root)
    if observation['free_mib'] < required_mib or observation['conflict']:
        error = Fault('LOCAL_GPU_BUSY', 409)
        error.gpu = dict(free_mib=observation['free_mib'], required_mib=required_mib,
                        processes=[dict(name=p['name'], used_mib=p['used_mib'])
                                   for p in observation['processes']])
        raise error
    return observation


def released(result):
    """One post-exit observation; no retries or changes to other GPU users."""
    try:
        observation = observe()
        gone = result.get('process_gone', False) and result['group_retired']
        absent = all(p['pid'] != result['process']['pid'] for p in observation['processes'])
        return dict(owned_process_gone=gone, released=bool(gone and absent))
    except Fault:
        return dict(owned_process_gone=result.get('process_gone', False), released=None,
                    error='RESOURCE_OBSERVATION_UNAVAILABLE')
