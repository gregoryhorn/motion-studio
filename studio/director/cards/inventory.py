"""Passive scoped cached metadata and a fixed local presence list. Never executes tools."""
import platform
import re
import shutil
import time

CANDIDATES = ('ffmpeg', 'ffprobe', 'sox', 'magick', 'espeak', 'flite')
SAFE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _.+-]{0,119}$')


def inventory(profile, session, *, cached=None, which=shutil.which):
    items = []
    available = bool(session and isinstance(cached, dict) and cached.get('profile') == profile and cached.get('session') == session)
    if available:
        for entry in cached.get('items', []):
            if not isinstance(entry, dict) or not SAFE.fullmatch(str(entry.get('name', ''))):
                continue
            kind = entry.get('kind')
            if kind not in ('skill', 'mcp', 'tool'):
                continue
            items.append(dict(name=entry['name'], kind=kind,
                status='Instructions installed' if kind == 'skill' else 'Cached',
                evidence_date=cached.get('as_of'), price='Unknown', wait='Unknown',
                next_action='Learn this tool; cached presence is not execution authority'))
    if session:
        for name in CANDIDATES:
            if which(name):
                items.append(dict(name=name, kind='CLI', status='Discovered', price='Unknown', wait='Unknown',
                    evidence_date=time.time(), next_action='Learn this tool'))
    return dict(profile=profile, execution_location=platform.system()+' backend',
        status='Cached scoped inventory' if available else 'Profile-scoped inventory unavailable',
        items=items, effects='Presence only; no connect, help, install, model or media calls')
