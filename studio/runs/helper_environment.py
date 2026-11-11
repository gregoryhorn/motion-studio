"""Fixed environments for passive driver observation and independent media decoding."""
from ..child_env import child_environment


def helper_environment():
    # Deliberately do not copy/filter os.environ: unknown provider/loader variables
    # must be absent too. Fixed absolute executables need no user search path.
    return child_environment('helper')
