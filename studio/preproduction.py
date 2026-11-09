"""Asset library and storyboard authoring on the existing immutable project store.

No renderer, remote source, model, browser or service is started by these tools.
Visual views are self-contained, escaped snapshots of real registered assets.
"""
from __future__ import annotations

import base64
import copy
import html
import json
import os
from pathlib import Path
import stat

from .contracts import (ContractError, D, UUID_PATTERN, digest, enum, ident,
                        integer, obj, ref, string, validate)

TOOLS = {'motion_asset_library': ('asset_library', 'AssetLibrary'),
         'motion_storyboard': ('storyboard', 'Storyboard')}


def production_tool_schema(tool):
    kind, definition = TOOLS[tool]
    common = {'project_id': ident('prj')}
    reads = [obj({'action': {'const': action}, **common, 'revision': integer(1)},
                 optional=['revision']) for action in ('get', 'view')]
    update = obj({'action': {'const': 'update'}, **common,
                  'expected_revision': integer(1), 'request_id': string(UUID_PATTERN),
                  'value': ref(definition)})
    return {'name': tool, 'description': (
        'Inspect registered project assets, record requirements and assessments, and export a visual inventory.'
        if kind == 'asset_library' else
        'Author ordered visual storyboard panels linked to assessed assets; preserve feedback and revisions. '
        'Requires a committed assessed asset library and registered image for every panel. '
        'Ready is agent readiness, never user approval.'),
        'parameters': {'oneOf': [*reads, update], '$defs': {
            name: copy.deepcopy(D[name]) for name in (
                ('ArtifactRef', 'AssetRequirement', 'AssetLibrary') if kind == 'asset_library'
                else ('ArtifactRef', 'StoryboardPanel', 'Storyboard'))}}}


def missing_required(library):
    return [item['requirement_id'] for item in library['requirements']
            if item['required'] and item['status'] != 'ready']


def validate_content(projects, fs, pid, docs, previous, *, storyboard_submitted=False):
    """Validate under ProjectStore's content lock, including generic update calls."""
    from .assets import AssetRegistry
    library_doc = docs.get(('asset_library', 'project'))
    board_doc = docs.get(('storyboard', 'project'))
    if library_doc is None and board_doc is None:
        return  # Older projects remain readable; no implicit migration.
    library = library_doc['value'] if library_doc else None
    if library is not None:
        requirements = library['requirements']
        if len({r['requirement_id'] for r in requirements}) != len(requirements):
            raise ContractError('INVALID_ARGUMENT', 'Asset requirement IDs must be unique.')
        for item in requirements:
            if item['status'] == 'ready' and ('asset' not in item or not item['assessment'].strip()):
                raise ContractError('ASSETS_UNRESOLVED', 'Ready assets require a registered asset and assessment.')
            if item['status'] != 'ready' and not item['acquisition'].strip():
                raise ContractError('ASSETS_UNRESOLVED', 'Missing/planned assets need an explicit acquisition approach.')
            if 'asset' in item and previous:
                record = AssetRegistry(projects).artifact(fs, previous, item['asset'])
                if item['kind'] != 'other' and record['kind'] != item['kind']:
                    raise ContractError('INVALID_ARGUMENT', 'Asset kind does not match its requirement.')
        if library['assessed'] and (missing_required(library) or not library['notes'].strip()):
            raise ContractError('ASSETS_UNRESOLVED', 'Assessment requires notes and all required assets ready.')
    if board_doc is None:
        return
    before = projects._load(fs, previous)[1].get(('storyboard', 'project')) if previous else None
    # Asset changes retain the previous storyboard as explicitly stale, not deleted.
    if before and before['value'] == board_doc['value'] and not storyboard_submitted:
        return
    if not library or not library['assessed'] or missing_required(library):
        raise ContractError('ASSETS_UNRESOLVED', 'Assess assets before authoring a storyboard.')
    board = board_doc['value']
    if board['asset_library_sha256'] != digest(library_doc):
        raise ContractError('ASSETS_UNRESOLVED', 'Storyboard must bind the current assessed asset library.')
    panels = board['panels']
    if len({p['panel_id'] for p in panels}) != len(panels):
        raise ContractError('INVALID_ARGUMENT', 'Storyboard panel IDs must be unique.')
    requirements = {r['requirement_id']: r for r in library['requirements']}
    for panel in panels:
        if not any(r['status'] == 'ready' and r.get('asset') == panel['visual']
                   for r in requirements.values()):
            raise ContractError('ASSETS_UNRESOLVED', 'Panel visual needs an asset-library assessment.')
        if len(set(panel['asset_requirements'])) != len(panel['asset_requirements']):
            raise ContractError('INVALID_ARGUMENT', 'Panel asset requirements must be unique.')
        for key in panel['asset_requirements']:
            if key not in requirements or requirements[key]['status'] != 'ready':
                raise ContractError('ASSETS_UNRESOLVED', 'Panel refers to an unknown or unresolved asset requirement.')
        if previous is None:
            raise ContractError('ASSETS_UNRESOLVED', 'Panel visual must already be registered.')
        record = AssetRegistry(projects).artifact(fs, previous, panel['visual'])
        if record['kind'] not in ('image', 'frame'):
            raise ContractError('INVALID_ARGUMENT', 'Storyboard visual must be a registered image/frame, not text or footage.')


def panel_projection(documents, panel_id):
    """Stable panel and exact assessed-asset closure, excluding review metadata."""
    board = documents.get(('storyboard', 'project'), {}).get('value', {})
    library = documents.get(('asset_library', 'project'), {}).get('value', {})
    panel = next((p for p in board.get('panels', []) if p['panel_id'] == panel_id), None)
    if panel is None:
        raise ContractError('ASSETS_UNRESOLVED', 'Bound storyboard panel is missing.')
    requirements = {r['requirement_id']: r for r in library.get('requirements', [])}
    keys = set(panel['asset_requirements'])
    visual_keys = {k for k, r in requirements.items() if r.get('asset') == panel['visual']}
    keys.update(visual_keys)
    if not library.get('assessed') or not visual_keys:
        raise ContractError('ASSETS_UNRESOLVED', 'Bound visual needs a current asset assessment.')
    for key in keys:
        if key not in requirements or requirements[key]['status'] != 'ready' or not requirements[key].get('asset') or not requirements[key]['assessment'].strip():
            raise ContractError('ASSETS_UNRESOLVED', 'Bound panel asset assessment is unresolved.')
    value = copy.deepcopy(panel)
    value.pop('notes', None)
    return {'panel': value, 'requirements': {k: requirements[k] for k in sorted(keys)}}


def validate_stored_scene_binding(projects, fs, pointer, scene, documents):
    """Resolve both pins from a real committed ancestor, never caller claims.

    Store writes/compiler calls use this adapter to preserve an unaffected scene
    across unrelated board edits without silently rebinding changed content.
    """
    binding = scene.get('storyboard_binding')
    if binding is None:
        return
    if all((record := documents.get((kind, 'project'))) is not None
           and binding[kind]['revision'] == record['revision']
           and binding[kind]['sha256'] == digest(record)
           for kind in ('storyboard', 'asset_library')):
        return validate_scene_binding(scene, documents)
    cursor = pointer
    seen = set()
    while cursor is not None:
        identity = (cursor['revision'], cursor['snapshot_sha256'])
        if identity in seen:
            raise ContractError('HASH_MISMATCH', 'Project ancestry contains a cycle.')
        seen.add(identity)
        _, source = projects._load(fs, cursor)
        if all((record := source.get((kind, 'project'))) is not None
               and binding[kind]['revision'] == record['revision']
               and binding[kind]['sha256'] == digest(record)
               for kind in ('storyboard', 'asset_library')):
            return validate_scene_binding(scene, documents, source_documents=source)
        cursor = projects._transaction(fs, cursor).get('previous')
    raise ContractError('ASSETS_UNRESOLVED', 'Storyboard binding pins are not from a committed project ancestor.')


def validate_scene_binding(scene, documents, *, source_documents=None):
    """One validator for the helper, public store writes and render compiler.

    Legacy authored scenes remain valid; a declared binding is never advisory.
    Only current production is checked here, not historical document reads.
    """
    binding=scene.get('storyboard_binding')
    if binding is None:return
    source = source_documents if source_documents is not None else documents
    for name in ('storyboard','asset_library'):
        pin=binding[name]
        record=source.get((name,'project'))
        if (pin['kind']!=name or pin['id']!='project' or record is None or
                pin['revision']!=record['revision'] or pin['sha256']!=digest(record)):
            raise ContractError('ASSETS_UNRESOLVED','Scene binding requires exact pinned '+name+'.')
    if panel_projection(source, binding['panel_id']) != panel_projection(documents, binding['panel_id']):
        raise ContractError('ASSETS_UNRESOLVED', 'Bound panel or assessed asset closure changed; revise this scene.')
    board=documents['storyboard','project']['value']
    library_doc=documents['asset_library','project']
    library=library_doc['value']
    if not library['assessed'] or missing_required(library) or board['asset_library_sha256']!=digest(library_doc):
        raise ContractError('ASSETS_UNRESOLVED','Scene storyboard/library is stale or unassessed.')
    panels=[p for p in board['panels'] if p['panel_id']==binding['panel_id']]
    if len(panels)!=1:raise ContractError('ASSETS_UNRESOLVED','Bound storyboard panel is missing.')
    panel=panels[0]
    variant=next((v for v in documents['variants','project']['value'] if v['variant_id']==binding['variant_id']),None)
    if variant is None or scene['canvas']!={'width_px':variant['width_px'],'height_px':variant['height_px']}:
        raise ContractError('ASSETS_UNRESOLVED','Scene canvas must match its explicit storyboard variant.')
    requirements={r['requirement_id']:r for r in library['requirements']}
    assets=[panel['visual']]
    for key in panel['asset_requirements']:
        requirement=requirements.get(key)
        if not requirement or requirement['status']!='ready' or not requirement.get('asset'):
            raise ContractError('ASSETS_UNRESOLVED','Bound panel asset is unresolved.')
        if requirement['asset'] not in assets:assets.append(requirement['asset'])
    if scene['assets']!=assets or scene['duration_frames']!=panel['duration_frames']:
        raise ContractError('ASSETS_UNRESOLVED','Scene differs from bound panel duration/asset closure.')
    if not scene['authored_source'] or not scene['source_runtime'] or not scene['source_format']:
        raise ContractError('ASSETS_UNRESOLVED','Bound scene requires editable authored source.')
    return panel


class ProductionTools:
    def __init__(self, runtime):
        self.runtime = runtime
        self.projects = runtime.projects

    def dispatch(self, tool, args):
        action = args.get('action', '') if isinstance(args, dict) else ''
        action = action if isinstance(action, str) else ''
        try:
            validate(args, production_tool_schema(tool)['parameters'])
            kind, _ = TOOLS[tool]
            if action == 'update':
                result = self.projects.dispatch({'action': 'update',
                    'project_id': args['project_id'], 'expected_revision': args['expected_revision'],
                    'request_id': args['request_id'],
                    'changes': [{'op': 'set_' + kind, 'value': args['value']}]})
                result['tool'], result['action'] = tool, action
                return result
            fs = self.projects._filesystem()
            pointer = self.projects._pointer(fs, args['project_id'])
            if 'revision' in args:
                while pointer['revision'] > args['revision']:
                    pointer = self.projects._transaction(fs, pointer)['previous']
                if pointer['revision'] != args['revision']:
                    raise ContractError('NOT_FOUND', 'Requested project revision is not committed.')
            _, docs = self.projects._load(fs, pointer)
            document = docs.get((kind, 'project'))
            library_doc = docs.get(('asset_library', 'project'))
            value = copy.deepcopy(document['value']) if document else None
            data = {'value': value, 'document': None if not document else {
                'kind': kind, 'id': 'project', 'revision': document['revision'], 'sha256': digest(document)}}
            from .assets import AssetRegistry
            registry = AssetRegistry(self.projects)
            if kind == 'asset_library':
                if value:
                    for requirement in value['requirements']:
                        if 'asset' in requirement:
                            registry.artifact(fs, pointer, requirement['asset'])
                data['inventory'] = [registry.summary(asset) | {
                    'kind': artifact['kind'], 'media_type': artifact['media_type'],
                    'size_bytes': artifact['size_bytes'], 'provenance': asset['provenance']}
                    for asset, artifact in registry.records(fs, pointer)]
                data['missing_required'] = missing_required(value) if value else []
                data['ready'] = bool(value and value['assessed'] and not data['missing_required'])
            else:
                if value:
                    for panel in value['panels']:
                        registry.artifact(fs, pointer, panel['visual'])
                data['stale'] = bool(value and (not library_doc or
                    value['asset_library_sha256'] != digest(library_doc)))
                data['ready'] = bool(value and not data['stale'] and value['review']['status'] == 'ready')
                data['rate'] = docs['settings', 'project']['value']['rate']
            if action == 'view':
                data.update(self._view(tool, pointer, data))
            return {'ok': True, 'tool': tool, 'action': action, 'status': 'ok',
                    'summary': 'Project ' + kind + ' ' + action + '.',
                    'project_id': pointer['project_id'], 'project_revision': pointer['revision'], 'data': data}
        except ContractError as exc:
            result = self.projects._error(action, exc)
        except FileNotFoundError:
            result = self.projects._error(action, ContractError('NOT_FOUND', 'Project or asset is unavailable.'))
        except OSError as exc:
            from .project import _fs_error
            result = self.projects._error(action, _fs_error(exc))
        result['tool'] = tool
        return result

    def _media(self, pid, pin, budget, image_only=False):
        """Resolve exact owned bytes; no external links, SVG, scripts or path URLs."""
        if not pin:
            return '<div class="empty">No selected asset</div>'
        path = Path(self.runtime.artifact_path(pid, pin))
        with path.open('rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ContractError('PATH_UNSAFE', 'Preview requires a regular asset file.')
            raw = source.read(min(budget[0] + 1, 8 * 1024 * 1024 + 1))
        if len(raw) > budget[0] or len(raw) > 8 * 1024 * 1024:
            if image_only:
                raise ContractError('LIMIT_EXCEEDED', 'Panel image exceeds view budget; register a smaller storyboard still.')
            return '<div class="empty">Large asset: inspect with the media tools</div>'
        import hashlib
        if 'sha256:' + hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ContractError('HASH_MISMATCH', 'Preview source differs from the selected asset.')
        budget[0] -= len(raw)
        if raw.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif raw.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif raw.startswith((b'GIF87a', b'GIF89a')):
            mime = 'image/gif'
        elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            mime = 'image/webp'
        else:
            if image_only:
                raise ContractError('UNSUPPORTED_FEATURE', 'Panel view supports PNG, JPEG, GIF or WebP stills; register a raster preview.')
            return '<div class="empty">Non-image asset: inspect with the media tools</div>'
        encoded = base64.b64encode(raw).decode('ascii')
        return '<img alt="Registered project visual" src="data:' + mime + ';base64,' + encoded + '">'

    def _view(self, tool, pointer, data):
        esc = lambda text: html.escape(str(text), quote=True)
        value = data['value']
        pid = pointer['project_id']
        budget = [12 * 1024 * 1024]
        cards = []
        inventory = ''
        if tool == 'motion_storyboard':
            if not value:
                raise ContractError('NOT_FOUND', 'No storyboard has been authored.')
            title = value['title']
            rate = data['rate']
            cursor = 0
            for index, panel in enumerate(value['panels'], 1):
                duration = panel['duration_frames']
                image = self._media(pid, panel['visual'], budget, image_only=True)
                fields = ''.join('<dt>' + esc(label) + '</dt><dd>' + esc(panel[field]) + '</dd>'
                    for label, field in [('Narration', 'narration'), ('On-screen text', 'on_screen_text'),
                        ('Motion', 'motion'), ('Transition', 'transition'), ('Notes', 'notes')])
                assets = ', '.join(panel['asset_requirements']) or 'No scene asset requirements'
                cards.append(f'<article>{image}<div class="body"><div class="meta">PANEL {index:02d} / '
                    f'{duration * rate["den"] / rate["num"]:.2f}s / frames {cursor}-{cursor + duration - 1}</div>'
                    f'<h2>{esc(panel["title"])}</h2><p class="assets">Assets: {esc(assets)}</p><dl>{fields}</dl></div></article>')
                cursor += duration
            note = ('STALE - asset assessment changed. Reconcile before production. ' if data['stale'] else '')
            note += 'Review: ' + value['review']['status'] + '. ' + value['review']['notes']
        else:
            title = 'Project asset library'
            requirements = value['requirements'] if value else []
            for item in requirements:
                cards.append('<article>' + self._media(pid, item.get('asset'), budget) + '<div class="body">'
                    '<div class="meta">' + esc(item['status'].upper() + ' / ' + item['kind']) + '</div><h2>' + esc(item['role']) +
                    '</h2><p>' + esc(item['requirement_id']) + (' / required' if item['required'] else ' / optional') +
                    '</p><dl><dt>Assessment</dt><dd>' + esc(item['assessment']) + '</dd><dt>Acquisition</dt><dd>' +
                    esc(item['acquisition']) + '</dd></dl></div></article>')
            note = ('Assessed. ' if data['ready'] else 'Not ready. ') + (value['notes'] if value else 'No assessment recorded.')
            # Unassigned imports remain visible; requirements never hide the real inventory.
            imported = []
            for item in data['inventory']:
                imported.append('<article>' + self._media(pid, item['artifact'], budget) +
                    '<div class="body"><div class="meta">' + esc(item['kind']) + '</div><h2>' +
                    esc(item['label']) + '</h2><p>' + esc(item['media_type']) + ' / ' +
                    str(item['size_bytes']) + ' bytes</p><p class="assets">' +
                    esc(item['artifact']['sha256']) + '</p><p>' +
                    esc(item['provenance']['origin']) + ' / ' + esc(item['rights_status']) +
                    '</p></div></article>')
            inventory = '<section><h2>Registered inventory</h2><div class="grid">' + ''.join(imported) + '</div></section>'
        document = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        document += '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
        document += '<title>' + esc(title) + '</title><style>'
        document += 'body{margin:0;background:#101923;color:#eef3f7;font:16px/1.5 system-ui}main{max-width:1320px;margin:auto;padding:32px}h1{font-size:32px;margin:0 0 8px}h2{font-size:21px;margin:6px 0 14px}header{margin-bottom:28px}header p{max-width:85ch;color:#b8c9d9}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,350px),1fr));gap:24px}article{background:#1c2a38;border:1px solid #3c5064;border-radius:12px;overflow:hidden}img,.empty{width:100%;aspect-ratio:16/9;object-fit:contain;background:#0b121b;display:block}.empty{display:grid;place-content:center;color:#b8c9d9}.body{padding:20px}.meta{font-size:12px;letter-spacing:.08em;color:#81d9cf}dt{color:#99b1c8;font-size:12px;text-transform:uppercase;margin-top:12px}dd{margin:3px 0;white-space:pre-wrap;overflow-wrap:anywhere}.assets{font-size:13px;color:#b8c9d9}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{margin-top:30px}@media(max-width:600px){main{padding:18px}h1{font-size:26px}}'
        document += 'h1,h2,p{overflow-wrap:anywhere}'
        document += '</style><main><header><h1>' + esc(title) + '</h1><p>Project revision ' + str(pointer['revision']) + ' / ' + esc(note) + '</p></header><div class="grid">' + ''.join(cards) + '</div>'
        if tool == 'motion_asset_library':
            document += inventory
        document += '</main></html>'
        raw = document.encode('utf-8')
        import hashlib
        sha = hashlib.sha256(raw).hexdigest()
        relative = self.projects._base(pid) + '/views/' + tool + '-' + sha + '.html'
        fs = self.projects._filesystem(write=True)
        parent, _, name = relative.rpartition('/')
        with fs.directory(parent, create=True) as directory:
            # Atomic publish; concurrent identical views replace identical bytes only.
            import secrets
            temporary = '.view-' + secrets.token_hex(12)
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        return {'path': str(self.projects.root / relative), 'sha256': 'sha256:' + sha,
                'view_type': 'self_contained_html', 'editable_with': tool + ' update'}


def production_handler(tool, args, **host_context):
    from .runtime import NativeRuntime
    runtime = host_context.pop('_runtime', None) or NativeRuntime()
    return json.dumps(ProductionTools(runtime).dispatch(tool, args), ensure_ascii=True, allow_nan=False)
