"""Explicit synthetic admission for tiny owned-process regression fixtures only.

Not cgroup enforcement, resource qualification, or a production fallback. Bind
only the supplied WorkerContext during one fixture spawn; never patch global
host safety or alter the environment. Ownership/cancellation remain real.
"""
from unittest.mock import patch


class SyntheticOwnedProcessLimits:
    def __init__(self, policy):
        self.policy = policy
        self.process = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # Exact fixture Popen only: no inferred PID/group and no kernel claim.
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
        return False

    def prepare_spawn(self, argv):
        return argv, {'pass_fds': ()}

    def measurements(self):
        return {'backend': 'synthetic-test-only', 'enforced': False,
                'qualified': False}


def synthetic_admission(*, paths, requirements):
    return {'backend': 'synthetic-test-only', 'enforced': False,
            'qualified': False, 'paths': list(paths), 'requirements': requirements}


def _fixture_process(worker, method, argv, **kwargs):
    """Run a real child with explicitly synthetic, instance-local admission."""
    def admit(fs, bundle, attempt, *, requirements=None):
        policy = synthetic_admission(paths=(str(fs.root),),
                                     requirements=requirements or {})
        limits = SyntheticOwnedProcessLimits(policy)
        limits.__enter__()
        worker.limits = limits
        bundle.setdefault('monitoring', {})['resources'] = policy
        worker.store._commit(fs, bundle)

    original_spawn = worker.spawn

    def spawn(*args, **spawn_kwargs):
        process = original_spawn(*args, **spawn_kwargs)
        worker.limits.process = process
        return process

    with patch.object(worker, '_admit_native', side_effect=admit), \
         patch.object(worker, 'spawn', side_effect=spawn):
        return getattr(worker, method)(argv, **kwargs)


def fixture_spawn(worker, argv, **kwargs):
    return _fixture_process(worker, 'spawn', argv, **kwargs)


def fixture_run(worker, argv, **kwargs):
    return _fixture_process(worker, 'run', argv, **kwargs)
