"""Shared shipped-template integrity; no private runtime/producer dependencies."""
import hashlib
from pathlib import Path
from ..domain import Fault

ASSET = Path(__file__).with_name('cli-template.json')
APPROVED = 'd0cdd8f69f39fc67df2491711f7e7ed5cb5ddc0a7c8a40830a0c7f19b87b68b5'


def integrity():
    try:
        if hashlib.sha256(ASSET.read_bytes()).hexdigest() != APPROVED:
            raise Fault('INSTRUCTION_CHANGED', 409)
    except OSError:
        raise Fault('INSTRUCTION_CHANGED', 409) from None
    return APPROVED
