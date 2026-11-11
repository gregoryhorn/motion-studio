"""Bounded synthetic same-session survivor; no signals, model or host changes."""
import os
from pathlib import Path
import sys
import time

root = Path(sys.argv[1])
child = os.fork()
if child == 0:
    deadline = time.monotonic() + 3
    while not (root / 'finish').exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    os._exit(0)
(root / 'ready').write_text('CONTROLLED')
deadline = time.monotonic() + 2
while not (root / 'release').exists() and time.monotonic() < deadline:
    time.sleep(0.005)
os._exit(0)
