"""Pinned, core-only Crystal Ball CLI port. No provider/model or host configuration."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import applicability

VERSION = '1.2.0'
# Release pin stays unchanged until the coordinator qualifies a new release.


def run(data, suffix, *, mode='quick', platform='custom', shape=None):
    options = applicability.settings(mode=mode, platform=platform, shape=shape)
    try:
        version = importlib.metadata.version('crystal-ball-media')
    except importlib.metadata.PackageNotFoundError:
        return dict(reason='Pinned checker is not installed')
    if version != VERSION:
        return dict(reason='Checker version does not match the pinned release')
    if not all(shutil.which(name) for name in ('ffmpeg', 'ffprobe')):
        return dict(reason='FFmpeg and ffprobe are required')
    with tempfile.TemporaryDirectory(prefix='director-check-') as temporary:
        root = Path(temporary)
        source = root / ('take' + suffix)
        source.write_bytes(data)
        # An explicit config and minimal environment exclude user provider/rules
        # settings. Missing optional engines are deliberate, disclosed omissions.
        missing = str(root / 'optional-engine-not-enabled')
        config = 'cache_dir = ' + json.dumps(str(root / 'cache')) + '\n'
        for section in ('hear', 'see', 'rhythm', 'scenes'):
            config += '[' + section + ']\npython = ' + json.dumps(missing) + '\n'
        config += '[read]\ntessdata = ' + json.dumps(missing) + '\n'
        config += '[judge]\nbackend = "off"\n'
        path = root / 'core.toml'
        path.write_text(config)
        env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TMPDIR', 'TMP', 'TEMP') if key in os.environ}
        env.update(HOME=str(root), CRYSTAL_BALL_CONFIG=str(path), PYTHONUTF8='1')
        # PYTHONPATH is never inherited. The accepted dependency belongs to this
        # interpreter, not an arbitrary command found on PATH.
        try:
            from ...director.process import call
            kind = applicability.classify(source, call=call, env=env, cwd=root)
            options = applicability.effective(kind, options)
            command = [sys.executable, '-m', 'crystal_ball', 'check', str(source),
                '--platform', options['platform'], '--mode', options['mode'], '--json']
            if options['shape']:
                command += ['--shape', options['shape']]
            result = call(command, cwd=root, env=env, timeout=60)
            if result.returncode not in (0, 1) or len(result.stdout) > 65536:
                return dict(reason='Checker could not complete')
            compact = json.loads(result.stdout)
            report = Path(compact['report'])
            cache = root / 'cache'
            if not report.resolve().is_relative_to(cache.resolve()) or report.is_symlink():
                return dict(reason='Checker report location was invalid')
            full_path = report.parent / 'full.json'
            full = json.loads(full_path.read_bytes())
            if full.get('version') != VERSION or Path(full.get('file', '')).resolve() != source.resolve():
                return dict(reason='Checker report identity did not match')
            # Collect only generated regular files in this private call's cache.
            assets, size = {}, 0
            for leaf in sorted(cache.rglob('*')):
                if leaf.is_symlink():
                    return dict(reason='Checker report contained an unsafe asset')
                if not leaf.is_file():
                    continue
                size += leaf.stat().st_size
                if size > 32 * 1024 * 1024:
                    return dict(reason='Checker report exceeded retention limit')
                body = leaf.read_bytes()
                if leaf.suffix in ('.json', '.md', '.html', '.log', '.csv', '.txt'):
                    body = body.replace(str(root).encode(), b'[private-check]')
                assets[str(leaf.relative_to(cache))] = body
            checks = full.get('checks', [])
            if not isinstance(checks, list):
                return dict(reason='Checker report was invalid')
            if kind is not None and full.get('media_kind') != kind:
                return dict(reason='Checker does not support this media applicability revision', assets=assets)
            summary = applicability.summarize(checks, compact, kind)
            return dict(summary, assets=assets)
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
            return dict(reason='Checker unavailable, timed out or returned an invalid report')
