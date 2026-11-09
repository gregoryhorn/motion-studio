"""Default bounded public single-URL yt-dlp acquisition binding (Linux).

No installation, credentials, config/plugin loading, playlists, JS runtimes,
remote components, postprocessors or shell commands. No universal site claim.
"""
import copy
import ipaddress
import json
from pathlib import Path
import shutil
import socket
from urllib.parse import urlsplit

from ..contracts import ContractError, canonical, digest, validate
from . import alternative
from .cli_connector import OwnedCliConnector, OwnedCliAdapter, limited_run, owned_file, output

ADAPTER_ID = 'local.yt-dlp'
OP = 'asset.acquire@1'
MAX_BYTES = 16 * 1024 * 1024
METADATA_LIMIT = 1024 * 1024
from ..default_dependencies import DEFAULT_TOOL_PACKS
DEPENDENCIES = tuple(dep['identifier'] for dep in DEFAULT_TOOL_PACKS[0]['dependencies'])


def discover() -> dict:
    paths = {name: shutil.which(name) for name in DEPENDENCIES}
    return dict(paths=paths, missing=[name for name, path in paths.items() if path is None])


def validate_url(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 2048 or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('Expected one bounded public HTTP(S) URL')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Only credential-free HTTP(S) source URLs are supported')
    host = parsed.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('Local source URLs are unsupported')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
        if '.' not in host or all(c.isdigit() or c == '.' for c in host):
            raise ValueError('Public source host must be an unambiguous FQDN or global IP')
    if address is not None and not address.is_global:
        raise ValueError('Non-public IP source URLs are unsupported')
    # Validate port syntax here as well; no DNS/network in passive discovery.
    if parsed.port is not None and parsed.port not in (80, 443):
        raise ValueError('Only standard HTTP(S) source ports are supported')
    return url


def validate_public_address(url):
    """Execution-time DNS guard, not a general egress/redirect sandbox."""
    validate_url(url)
    parsed = urlsplit(url)
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80),
                                   type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Public source resolved to a non-public address')


def validate_parameters(params):
    validate_url(params['url'])


def base_argv(executable):
    return [executable, '--ignore-config', '--no-plugin-dirs', '--no-remote-components',
        '--no-js-runtimes', '--no-cookies', '--no-cookies-from-browser', '--no-exec',
        '--no-cache-dir', '--no-playlist', '--playlist-items', '1', '--no-write-playlist-metafiles',
        '--no-write-subs', '--no-write-auto-subs', '--no-write-thumbnail', '--no-write-comments',
        '--no-write-description', '--no-embed-metadata', '--no-embed-chapters', '--no-embed-info-json',
        '--no-progress', '--no-update', '--socket-timeout', '10', '--retries', '0',
        '--fragment-retries', '0', '--file-access-retries', '0', '--downloader', 'native',
        '--fixup', 'never',
        '--format', 'best[ext=mp4][protocol=https]/best[ext=mp4][protocol=http]']


def registration():
    from ..capabilities import PARAMS, expanded
    meta = alternative.registration()
    decl = copy.deepcopy(meta['declaration'])
    decl.update(adapter_id=ADAPTER_ID, label='yt-dlp bounded public MP4 acquisition',
                implementation_version='0.1.0', dependencies=[dict(name=name, kind='executable',
                version_constraint=None, required=True) for name in DEPENDENCIES])
    decl['operations'] = [dict(decl['operations'][0], operation=OP,
        request_schema='motion/v1/yt-dlp/acquire-request', result_schema='motion/v1/yt-dlp/acquire-result',
        default_timeout_seconds=120, constraints=dict(decl['operations'][0]['constraints'],
        media_types=['video/mp4', 'application/json'], codecs=[], languages=[]))]
    # HTTP requests disclose the selected public URL (and normal network request
    # metadata). No project artifact bytes or credential material are uploaded.
    decl['effects'] = dict(writes_local=True, uploads=True,
        destinations=['selected public source URL and extractor/CDN redirects'], generates=False,
        launches_process=True, pricing='free', charging_basis=None, estimate=None)
    return dict(declaration=decl, implementation_sha256=digest(dict(
        binding=alternative.file_digest(__file__), connector=alternative.file_digest(Path(__file__).with_name('cli_connector.py')),
        dependencies=DEFAULT_TOOL_PACKS)),
        schemas={'motion/v1/yt-dlp/acquire-request': expanded(PARAMS[OP]),
                 'motion/v1/yt-dlp/acquire-result': next(v for k, v in meta['schemas'].items() if k.endswith('-result'))},
        outputs={OP: [dict(port='media', kind='media', media_type='video/mp4'),
                      dict(port='report', kind='report', media_type='application/json')]})


def _metadata(path, params):
    raw = json.loads(owned_file(path, path.parent, METADATA_LIMIT).read_bytes())
    if not isinstance(raw, dict) or raw.get('_type', 'video') != 'video' or any(raw.get(k) for k in ('entries', 'requested_formats')):
        raise ValueError('Playlists, multi-format merges and non-video metadata are unsupported')
    if raw.get('is_live') or raw.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        raise ValueError('Live/upcoming sources are unsupported')
    if raw.get('ext') != 'mp4' or raw.get('protocol') not in ('http', 'https'):
        raise ValueError('Only single-file native HTTP(S) MP4 formats are supported')
    validate_url(raw.get('url'))
    duration = raw.get('duration')
    # Unknown duration may still be a small direct MP4: it is verified by actual
    # probe/full decode before collection, not invented or called known here.
    if duration is not None and (not isinstance(duration, (int, float)) or not 0 < duration <= params['max_duration_seconds']):
        raise ValueError('Source duration exceeds selected bound')
    size = raw.get('filesize')
    if size is not None and (not isinstance(size, int) or not 0 < size <= params['max_bytes']):
        raise ValueError('Source filesize exceeds selected bound')
    return raw


def perform(request, out, run, output_probe):
    params = request['parameters']
    validate_public_address(params['url'])
    executable = discover()['paths']['yt-dlp']
    base = base_argv(executable)
    version = out/'version.txt'
    limited_run(run, [executable, '--ignore-config', '--no-plugin-dirs', '--no-remote-components', '--version'],
                limit=4096, stdout_path=version, stderr_path=out/'version.log')
    metadata = out/'source-info.json'
    limited_run(run, [*base, '--max-filesize', str(params['max_bytes']), '--dump-single-json',
        '--skip-download', '--', params['url']], limit=METADATA_LIMIT,
        stdout_path=metadata, stderr_path=out/'metadata.log')
    raw = _metadata(metadata, params)
    validate_public_address(raw['url'])
    media = out/'media.mp4'
    # Reuse exact extracted metadata; do not silently select a changed source or
    # a different format on a second extraction. Fixed stdout target prevents
    # metadata-controlled filenames/path traversal and disables merging/PPs.
    limited_run(run, [*base, '--load-info-json', str(metadata), '--max-filesize', str(params['max_bytes']),
        '--no-part', '--no-mtime', '--no-write-info-json', '--no-simulate', '--output', '-'],
        limit=params['max_bytes'], stdout_path=media, stderr_path=out/'download.log')
    owned_file(media, out, params['max_bytes'])
    probe_ref = output_probe.validate_acquired_mp4(media.read_bytes(),
        registration()['outputs'][OP][0], max_duration_seconds=params['max_duration_seconds'], run_process=run)
    # Extractor metadata contains floating point facts; preserve it verbatim in
    # a JSON string inside Studio's integer-only canonical JSON contract.
    report = dict(schema='motion/v1/acquisition-provenance', source_url=params['url'],
        webpage_url=raw.get('webpage_url'), selected_media_url=raw['url'],
        format_id=raw.get('format_id'), extractor=raw.get('extractor'), source_id=raw.get('id'),
        title=raw.get('title'), uploader=raw.get('uploader'), license=raw.get('license'),
        rights_status='unknown; source metadata is not rights clearance',
        metadata_json=metadata.read_text(), metadata_sha256=alternative.file_digest(metadata),
        yt_dlp_version=owned_file(version, out, 4096).read_text().strip(),
        parameters=params, media_sha256=alternative.file_digest(media), size_bytes=media.stat().st_size,
        probe_receipt_id=probe_ref, binding=request['binding'],
        limitations=['single public URL; native HTTP(S) MP4 only',
                     'no playlists, separate streams, subtitles, authentication, JS challenges or postprocessing',
                     'not all sites are supported; network requests can follow extractor/CDN redirects'])
    report_path = out/'acquisition.json'
    report_path.write_bytes(canonical(report))
    owned_file(report_path, out, 2*METADATA_LIMIT)
    return [output('media', media, 'video/mp4'), output('report', report_path, 'application/json')]


CONNECTOR = OwnedCliConnector(registration, discover, validate_parameters, perform)


class YtDlpAdapter(OwnedCliAdapter):
    connector = CONNECTOR
