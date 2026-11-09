"""Editable creative planning, stored in the existing project revision closure.

Readiness is not user consent. Consent references an actual current-session user
message and the exact presented candidate; it grants no execution/spend access.
"""
from __future__ import annotations

import copy
import html
import json
import re

from .contracts import (ContractError, D, TEXT, UUID_PATTERN, digest, enum, ident,
                        integer, obj, ref, string, validate)
from .project import _now


def schema_branches():
    common = {'project_id': ident('prj')}
    return [obj({'action': {'const': 'creative_get'}, **common, 'revision': integer(1)}, ['revision']),
        obj({'action': {'const': 'creative_update'}, **common, 'expected_revision': integer(1),
             'request_id': string(UUID_PATTERN), 'value': ref('CreativePlan')}),
        obj({'action': {'const': 'creative_accept'}, **common, 'candidate_sha256': TEXT,
             'message_id': TEXT, 'mode': enum('accepted', 'delegated')})]


def validate_plan(value, docs):
    validate(value, ref('CreativePlan'))
    beats = {b['beat_id']: b for b in value['beats']}
    tasks = {t['task_id']: t for t in value['tasks']}
    if len(beats) != len(value['beats']) or len(tasks) != len(value['tasks']):
        raise ContractError('INVALID_ARGUMENT', 'Beat and task IDs must be unique.')
    end = 0
    library = docs.get(('asset_library', 'project'), {}).get('value', {})
    requirements = {r['requirement_id'] for r in library.get('requirements', [])}
    board = docs.get(('storyboard', 'project'), {}).get('value', {})
    panels = {p['panel_id']: p for p in board.get('panels', [])}
    for beat in value['beats']:
        if beat['start_frame'] != end:
            raise ContractError('INVALID_ARGUMENT', 'Creative beats must be contiguous and ordered from frame zero.')
        end += beat['duration_frames']
        if set(beat['asset_requirements']) - requirements:
            raise ContractError('ASSETS_UNRESOLVED', 'Creative beat references unknown asset requirements.')
        if beat['panel_id'] is not None:
            panel = panels.get(beat['panel_id'])
            if not panel or any(panel[k] != beat[k] for k in ('duration_frames', 'narration', 'on_screen_text')):
                raise ContractError('ASSETS_UNRESOLVED', 'Linked panel timing/copy differs; revise both in one project update.')
        if beat['scene_id'] is not None and ('scene', beat['scene_id']) not in docs:
            raise ContractError('NOT_FOUND', 'Creative beat references a missing scene.')
    if end != value['duration_frames']:
        raise ContractError('INVALID_ARGUMENT', 'Creative duration must equal the beat outline.')
    pending = set(tasks)
    done = set()
    for task in tasks.values():
        if set(task['beat_ids']) - set(beats) or set(task['dependencies']) - set(tasks):
            raise ContractError('INVALID_ARGUMENT', 'Task references an unknown beat or dependency.')
        if (task['adapter_id'] is None) != (task['operation'] is None):
            raise ContractError('INVALID_ARGUMENT', 'Select both adapter and operation, or leave both unresolved.')
    while pending:
        ready = {key for key in pending if set(tasks[key]['dependencies']) <= done}
        if not ready:
            raise ContractError('INVALID_ARGUMENT', 'Creative task dependencies contain a cycle.')
        done.update(ready)
        pending -= ready


def candidate(docs):
    # Involvement and feedback edits do not erase agreed substantive choices.
    plan = copy.deepcopy(docs['creative_plan', 'project']['value'])
    for key in ('involvement', 'feedback'):
        plan.pop(key)
    return digest({'plan': plan, 'brief': docs['brief', 'project']['value'],
        'storyboard': docs.get(('storyboard', 'project'), {}).get('value'),
        'asset_library': docs.get(('asset_library', 'project'), {}).get('value')})


def scope_hashes(docs):
    """Content identities for selective acceptance in the existing receipt store.

    Document revisions, feedback, review flags and unrelated inventory are not
    creative choices. Task scopes include their transitive prerequisite closure.
    """
    plan = docs['creative_plan', 'project']['value']
    library = docs.get(('asset_library', 'project'), {}).get('value', {})
    requirements = {r['requirement_id']: r for r in library.get('requirements', [])}
    board = docs.get(('storyboard', 'project'), {}).get('value', {})
    panels = {p['panel_id']: p for p in board.get('panels', [])}
    global_value = {k: v for k, v in plan.items() if k not in
                    ('involvement', 'feedback', 'beats', 'tasks', 'duration_frames')}
    global_sha = digest({'plan': global_value, 'brief': docs['brief', 'project']['value']})
    beats = {}
    for beat in plan['beats']:
        panel = copy.deepcopy(panels.get(beat['panel_id']))
        if panel:
            panel.pop('notes', None)
        keys = set(beat['asset_requirements'])
        if panel:
            keys.update(panel['asset_requirements'])
            keys.update(k for k, r in requirements.items() if r.get('asset') == panel['visual'])
        beats[beat['beat_id']] = digest({'global': global_sha, 'beat': beat,
            'panel': panel, 'requirements': {k: requirements.get(k) for k in sorted(keys)}})
    tasks = {t['task_id']: t for t in plan['tasks']}
    resolved = {}
    pending = set(tasks)
    while pending:
        ready = sorted(k for k in pending if set(tasks[k]['dependencies']) <= resolved.keys())
        if not ready:
            raise ContractError('PLAN_BLOCKED', 'Creative task dependencies contain a cycle or missing task.')
        for key in ready:
            task = tasks[key]
            resolved[key] = digest({'global': global_sha, 'task': task,
                'beats': {k: beats[k] for k in task['beat_ids']},
                'dependencies': {k: resolved[k] for k in task['dependencies']}})
        pending.difference_update(ready)
    return {'global': global_sha, 'beats': beats, 'tasks': resolved}


def _valid_receipt(receipt, pid, sha):
    return (isinstance(receipt, dict) and receipt.get('project_id') == pid
        and receipt.get('candidate_sha256') == sha
        and receipt.get('creative_authority') is True
        and receipt.get('mode') in ('accepted', 'delegated')
        and bool(receipt.get('session_id')) and bool(receipt.get('message_id')))


def acceptance_state(projects, fs, pid, docs):
    """Read, never manufacture, authority from retained user-evidence receipts."""
    sha = candidate(docs)
    scopes = scope_hashes(docs)
    exact = None
    accepted = {'beats': set(), 'tasks': set()}
    base = projects._base(pid) + '/creative-consent'
    for name in fs.names(base):
        if not re.fullmatch(r'sha256:[0-9a-f]{64}\.json', name):
            continue
        receipt = fs.read(base + '/' + name)
        if not _valid_receipt(receipt, pid, name[:-5]):
            continue
        if receipt['candidate_sha256'] == sha:
            exact = receipt
            for kind in accepted:
                accepted[kind].update(scopes[kind])
        previous = receipt.get('scopes', {})
        for kind in accepted:
            accepted[kind].update(k for k, v in scopes[kind].items()
                                  if previous.get(kind, {}).get(k) == v)
    return exact, {kind: sorted(keys) for kind, keys in accepted.items()}


def consent_path(projects, pid, sha):
    return projects._base(pid) + '/creative-consent/' + sha + '.json'


def require_consent(projects, fs, pid, docs, execution_plan=None):
    if ('creative_plan', 'project') not in docs:
        return  # Legacy authored projects are not silently migrated.
    plan = docs['creative_plan', 'project']['value']
    if plan['open_questions'] or any(t['missing_inputs'] for t in plan['tasks']):
        raise ContractError('PLAN_BLOCKED', 'Creative plan has unresolved questions or production inputs.')
    if plan['storyboard_choice'] == 'discuss':
        raise ContractError('PLAN_BLOCKED', 'Discuss or explicitly delegate/decline the storyboard first.')
    if plan['storyboard_choice'] in ('requested', 'delegated'):
        board = docs.get(('storyboard', 'project'))
        if not board or any(b['panel_id'] is None for b in plan['beats']):
            raise ContractError('PLAN_BLOCKED', 'Requested storyboard needs actual visual panels linked to every beat.')
        library = docs.get(('asset_library', 'project'))
        if not library or board['value']['asset_library_sha256'] != digest(library):
            raise ContractError('PLAN_BLOCKED', 'Storyboard asset assessment changed.')
    receipt, accepted = acceptance_state(projects, fs, pid, docs)
    tasks = {task['task_id']: task for task in plan['tasks']}
    if execution_plan is None:
        if (not receipt and (set(accepted['beats']) != {b['beat_id'] for b in plan['beats']}
                or set(accepted['tasks']) != set(tasks))):
            raise ContractError('PERMISSION_DENIED', 'Creative candidate has no matching agreement or delegation for all changed scopes.')
    else:
        for node in execution_plan['nodes']:
            task = tasks.get(node['target_key'])
            if not task or task['adapter_id'] != node['binding']['adapter_id'] or task['operation'] != node['operation']:
                raise ContractError('PLAN_BLOCKED', 'Execution node differs from the agreed creative task/tool selection.')
            if task['task_id'] not in accepted['tasks']:
                raise ContractError('PERMISSION_DENIED', 'Creative task or its dependencies changed; obtain matching acceptance or delegation.')


def dispatch(runtime, args, *, session_id=None):
    projects = runtime.projects
    if args['action'] == 'creative_update':
        # Same transaction/replay/concurrency semantics as every project edit.
        result = projects.dispatch(dict(action='update', project_id=args['project_id'],
            expected_revision=args['expected_revision'], request_id=args['request_id'],
            changes=[dict(op='set_creative_plan', value=args['value'])]))
        if not result.get('ok'):
            error = result.get('error', {})
            raise ContractError(error.get('code', 'INVALID_ARGUMENT'), error.get('message', 'Creative update failed.'))
        return result['data']
    fs = projects._filesystem(write=args['action'] == 'creative_accept')
    pid = args['project_id']
    with fs.lock(projects._base(pid) + '/locks/content.lock'):
        pointer = projects._pointer(fs, pid)
        if 'revision' in args:
            while pointer and pointer['revision'] > args['revision']:
                pointer = projects._transaction(fs, pointer)['previous']
            if not pointer or pointer['revision'] != args['revision']:
                raise ContractError('NOT_FOUND', 'Creative revision not found.')
        _, docs = projects._load(fs, pointer)
        record = docs.get(('creative_plan', 'project'))
        if record is None:
            return {'value': None, 'candidate_sha256': None, 'human_acceptance': False}
        sha = candidate(docs)
        if args['action'] == 'creative_accept':
            if args['candidate_sha256'] != sha:
                raise ContractError('HASH_MISMATCH', 'Creative candidate changed; present the current revision.')
            message, presented = user_message(session_id, args['message_id'], sha)
            phrase = ('approve' if args['mode'] == 'accepted' else 'delegate') + ' creative plan ' + sha
            explicit = re.fullmatch(r'\s*' + re.escape(phrase) + r'[.!\s]*', message, re.I)
            # A normal conversational yes is sufficient after presentation. No
            # hash-typing ceremony is required. Delegation may precede authoring.
            accepted = args['mode'] == 'accepted' and presented and re.fullmatch(r'\s*(?:yes|approved?|looks good|go ahead|proceed|that works)[.!\s]*', message, re.I)
            delegated = (args['mode'] == 'delegated'
                and not re.search(r"\b(?:not|never|no|don['’]t|do\s+not|cannot|can['’]t)\b", message, re.I)
                and re.search(
                r'\b(?:delegate|you decide|your (?:judgment|judgement))\b', message, re.I)
                and re.search(r'\b(?:proceed|produce|create|make|build|go ahead)\b', message, re.I))
            if not (explicit or accepted or delegated):
                raise ContractError('PERMISSION_DENIED', 'No explicit agreement after candidate presentation or creative delegation in that user message.')
            receipt = dict(schema='motion/v1/creative-consent', project_id=pid,
                candidate_sha256=sha, mode=args['mode'], session_id=session_id,
                message_id=args['message_id'], message_sha256=digest(message),
                human_acceptance=args['mode'] == 'accepted', creative_authority=True,
                execution_authority=False, scopes=scope_hashes(docs), recorded_at=_now())
            path = consent_path(projects, pid, sha)
            try:
                previous = fs.read(path)
            except FileNotFoundError:
                fs.write(path, receipt)
            else:
                receipt = previous
            return {'consent': receipt}
        consent, accepted_scopes = acceptance_state(projects, fs, pid, docs)
        old = None
        before = {}
        transaction = projects._transaction(fs, pointer)
        if transaction.get('previous'):
            _, before = projects._load(fs, transaction['previous'])
            old = before.get(('creative_plan', 'project'), {}).get('value')
        current_scopes = scope_hashes(docs)
        before_scopes = scope_hashes(before) if old else {'beats': {}, 'tasks': {}}
        changed = [key for key, value in current_scopes['beats'].items()
                   if before_scopes['beats'].get(key) != value]
        changed_tasks = [key for key, value in current_scopes['tasks'].items()
                         if before_scopes['tasks'].get(key) != value]
        removed = sorted(set(before_scopes['beats']) - set(current_scopes['beats']))
        value = copy.deepcopy(record['value'])
        # Link exact registered raster bytes, using the same bounded view path as
        # the storyboard; a text-only table must not masquerade as a visual board.
        from .preproduction import ProductionTools
        panels = {p['panel_id']: p for p in docs.get(('storyboard', 'project'), {}).get('value', {}).get('panels', [])}
        media = ProductionTools(runtime)
        budget = [12 * 1024 * 1024]
        rows = []
        for beat in value['beats']:
            panel = panels.get(beat['panel_id'])
            visual = media._media(pid, panel['visual'], budget, image_only=True) if panel else ''
            rows.append('<tr data-beat-id="' + html.escape(beat['beat_id'], quote=True) + '"><td>'
                + visual + '</td><td>' + '</td><td>'.join(html.escape(str(beat[k])) for k in
                ('title', 'start_frame', 'duration_frames', 'narration', 'on_screen_text', 'visual_direction', 'panel_id')) + '</td></tr>')
        view = '<!doctype html><meta charset="utf-8"><h1>' + html.escape(value['title']) + '</h1><table>' + ''.join(rows) + '</table>'
        discussion = discussion_outline(value)
        return dict(value=value, project_revision=pointer['revision'], candidate_sha256=sha,
            consent=consent, human_acceptance=bool(consent and consent.get('human_acceptance')),
            creative_authority=bool(consent and consent.get('creative_authority')), affected_beats=changed,
            affected_tasks=changed_tasks, accepted_beats=accepted_scopes['beats'],
            accepted_tasks=accepted_scopes['tasks'],
            pending_acceptance_beats=sorted(set(current_scopes['beats']) - set(accepted_scopes['beats'])),
            pending_acceptance_tasks=sorted(set(current_scopes['tasks']) - set(accepted_scopes['tasks'])),
            discussion=discussion, removed_beats=removed, html=view, production_started=False)


def discussion_outline(plan):
    """Discussion presentation only; never changes or delegates creative choices."""
    level = plan.get('involvement', 'guided')
    common = {'involvement': level, 'objective': plan['objective'],
        'audience': plan['audience'], 'message': plan['message'],
        'duration_frames': plan['duration_frames'], 'assumptions': list(plan['assumptions']),
        'open_questions': list(plan['open_questions']),
        'storyboard_choice': plan['storyboard_choice'],
        'delegation': copy.deepcopy(plan['delegation']), 'grants_authority': False}
    if level == 'automatic':
        common['review_items'] = [{'area': 'overview', 'beat_count': len(plan['beats']),
            'task_count': len(plan['tasks'])}]
    elif level == 'guided':
        common['review_items'] = [{'beat_id': b['beat_id'], 'title': b['title'],
            'narration': b['narration'], 'visual_direction': b['visual_direction'],
            'duration_frames': b['duration_frames']} for b in plan['beats']]
    else:
        common['review_items'] = copy.deepcopy(plan['beats'])
        common['task_breakdown'] = copy.deepcopy(plan['tasks'])
    return common


def user_message(session_id, message_id, sha):
    if not session_id:
        raise ContractError('PERMISSION_DENIED', 'Trusted current session is required for user evidence.')
    from hermes_state import SessionDB
    db = SessionDB(read_only=True)
    try:
        rows = db.get_messages(session_id, limit=200, latest=True)
    finally:
        db.close()
    presented = False
    for row in rows:
        if str(row.get('id')) == message_id and row.get('role') == 'user' and isinstance(row.get('content'), str):
            return row['content'], presented
        if row.get('role') == 'assistant' and sha in str(row.get('content', '')):
            presented = True
    raise ContractError('PERMISSION_DENIED', 'No matching user message in the current session.')
