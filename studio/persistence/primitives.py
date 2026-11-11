"""Portable canonical control identities shared by standalone and native records."""
import hashlib
import json
import uuid


def identity():
    return uuid.uuid4().hex


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
