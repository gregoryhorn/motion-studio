"""Editorial selection metadata over the existing timeline, source pins and jobs.

Extracts are source-range recipes, not parallel mutable timelines or a publishing
service. Applying one changes the normal project timeline explicitly; ordinary
compilation, authority, rendering and output validation still own production.
"""
from __future__ import annotations

import copy
from fractions import Fraction
from typing import Any

from .contracts import (ContractError, D, KEY, UUID_PATTERN, arr, digest, ident,
                        integer, obj, ref, string, validate)
from .timeline import map_source_range, rate_fraction


def branches():
    common = {'project_id': ident('prj')}
    return [obj({'action': {'const': action}, **common}) for action in ('editorial_get', 'editorial_reconform')] + [
        obj({'action': {'const': 'editorial_update'}, **common,
             'expected_revision': integer(1), 'request_id': string(UUID_PATTERN), 'value': ref('Editorial')}),
        obj({'action': {'const': 'extract_inspect'}, **common, 'extract_id': KEY}),
        obj({'action': {'const': 'extract_apply'}, **common, 'extract_id': KEY,
             'expected_revision': integer(1), 'request_id': string(UUID_PATTERN)}),
        obj({'action': {'const': 'full_master_apply'}, **common,
             'expected_revision': integer(1), 'request_id': string(UUID_PATTERN)}),
        obj({'action': {'const': 'extract_bind'}, **common, 'extract_id': KEY, 'variant_id': KEY,
             'artifact': ref('ArtifactRef'), 'job_id': ident('job'),
             'expected_revision': integer(1), 'request_id': string(UUID_PATTERN)}),
        obj({'action': {'const': 'full_master_bind'}, **common, 'variant_id': KEY,
             'artifact': ref('ArtifactRef'), 'job_id': ident('job'),
             'expected_revision': integer(1), 'request_id': string(UUID_PATTERN)})]


def historical(projects, fs, pointer, pin):
    """Read a frozen document without runtime.document's ancillary publication."""
    validate(pin, ref('DocumentRef'))
    while pointer:
        _, docs = projects._load(fs, pointer)
        record = docs.get((pin['kind'], pin['id']))
        if record and record['revision'] == pin['revision'] and digest(record) == pin['sha256']:
            return record, docs
        pointer = projects._transaction(fs, pointer)['previous']
    raise ContractError('NOT_FOUND', 'Editorial parent document does not belong to project history.')


def validate_editorial(projects, fs, pid, docs, previous):
    value = docs['editorial', 'project']['value']
    validate(value, ref('Editorial'))
    pin = value['parent_timeline']
    if pin['kind'] != 'timeline' or pin['id'] != 'project' or previous is None:
        raise ContractError('INVALID_ARGUMENT', 'Editorial parent must be an existing committed project timeline.')
    parent, parent_docs = frozen_parent(projects, fs, previous, value)
    extracts = {e['extract_id']: e for e in value['extracts']}
    if len(extracts) != len(value['extracts']):
        raise ContractError('INVALID_ARGUMENT', 'Extract IDs must be unique.')
    variants = {v['variant_id'] for v in docs['variants', 'project']['value']}
    for extract in extracts.values():
        for span in extract['ranges']:
            if not 0 <= span['start_frame'] < span['end_frame'] <= parent['value']['duration_frames']:
                raise ContractError('TIMING_INVALID', 'Editorial range must lie within its pinned parent timeline.')
        if set(extract['variants']) - variants:
            raise ContractError('NOT_FOUND', 'Extract references an unconfigured variant.')
        if extract['caption']:
            if extract['caption']['kind'] != 'caption':
                raise ContractError('INVALID_ARGUMENT', 'Editorial caption pin must name a caption document.')
            historical(projects, fs, previous, extract['caption'])
        if not extract['caption_decision'].strip() or not extract['crop_decision'].strip():
            raise ContractError('INVALID_ARGUMENT', 'Retain explicit caption and crop decisions, including none.')
    ids = set()
    for item in value['deliverables']:
        if item['deliverable_id'] in ids or item['variant_id'] not in variants:
            raise ContractError('INVALID_ARGUMENT', 'Deliverable identity must be unique and variant configured.')
        ids.add(item['deliverable_id'])
        if item['kind'] == 'full_master' and item['extract_id'] is not None:
            raise ContractError('INVALID_ARGUMENT', 'Full master cannot be satisfied by an extract.')
        if item['kind'] == 'extract' and (item['extract_id'] not in extracts or
                item['variant_id'] not in extracts[item['extract_id']]['variants']):
            raise ContractError('INVALID_ARGUMENT', 'Deliverable must reference an extract/variant pair.')
    # Generic writes may preserve or remove old receipts, but cannot invent a
    # validated output binding. Only extract_bind's private internal route may add.
    old = projects._load(fs, previous)[1].get(('editorial', 'project'), {}).get('value', {})
    admitted = getattr(projects, '_editorial_output_admission', None)
    for output in value['outputs']:
        if output not in old.get('outputs', []) and output != admitted:
            raise ContractError('PERMISSION_DENIED', 'New extract outputs must be bound from a validated producing job.')


def fraction_json(value):
    return dict(num=value.numerator, den=value.denominator)


def frozen_parent(projects, fs, pointer, value):
    while pointer and pointer['revision'] > value['parent_project_revision']:
        pointer = projects._transaction(fs, pointer)['previous']
    if not pointer or pointer['revision'] != value['parent_project_revision']:
        raise ContractError('NOT_FOUND', 'Editorial parent project revision is not committed.')
    _, docs = projects._load(fs, pointer)
    parent = docs['timeline', 'project']
    if document_pin(parent) != value['parent_timeline']:
        raise ContractError('HASH_MISMATCH', 'Editorial timeline pin differs from the selected parent project revision.')
    return parent, docs


def document_pin(record):
    return dict(kind=record['kind'], id=record['id'], revision=record['revision'], sha256=digest(record))


def selected_profiles(documents, variant_ids, duration):
    """Freeze selected definitions; applied timeline duration is not profile drift."""
    configured = {v['variant_id']: v for v in documents['variants', 'project']['value']}
    if set(variant_ids) - configured.keys():
        raise ContractError('NOT_FOUND', 'Selected editorial variant is no longer configured.')
    return [dict(copy.deepcopy(configured[vid]), duration_frames=duration) for vid in sorted(set(variant_ids))]


def matching_profiles(documents, profiles):
    configured = {v['variant_id']: v for v in documents['variants', 'project']['value']}
    return {v['variant_id'] for v in profiles if v['variant_id'] in configured and
            dict(configured[v['variant_id']], duration_frames=v['duration_frames']) == v}


def recipe(projects, fs, pointer, value, extract, *, parent_override=None, docs_override=None) -> dict[str, Any]:
    parent, parent_docs = frozen_parent(projects, fs, pointer, value)
    if parent_override is not None:
        if docs_override is None:
            raise ContractError('INVALID_ARGUMENT', 'Revised parent requires its actual document closure.')
        parent = parent_override
        parent_docs = docs_override
    rate = parent_docs['settings', 'project']['value']['rate']
    fps = rate_fraction(rate)
    tracks, mapping, closure = {}, [], []
    output_offset = 0
    unsupported = []
    for cut_index, span in enumerate(extract['ranges']):
        if span['end_frame'] > parent['value']['duration_frames']:
            raise ContractError('TIMING_INVALID', 'Revised parent is shorter than an explicit extract range.')
        for track in parent['value']['tracks']:
            target = tracks.setdefault(track['track_id'], dict(track_id=track['track_id'], kind=track['kind'], items=[]))
            for item in track['items']:
                a, b = max(span['start_frame'], item['start_frame']), min(span['end_frame'], item['end_frame'])
                if a >= b:
                    continue
                subject = item['subject']
                if subject['kind'] == 'scene':
                    record = parent_docs.get(('scene', subject['scene_id']))
                    if not record:
                        raise ContractError('NOT_FOUND', 'Editorial source scene is missing from parent closure.')
                    source_pin = document_pin(record)
                    semantic = record['value']
                    origin: dict[str, Any] | None = dict(domain='frame', index=0, rate=rate, origin='project')
                    # Use the current document value only for the selected parent
                    # closure, not unrelated scenes elsewhere in the project.
                elif subject['kind'] == 'artifact':
                    source_pin = subject['artifact']
                    semantic = source_pin
                    origin = None
                else:
                    source_pin = subject['caption']
                    record, _ = historical(projects, fs, pointer, source_pin)
                    semantic = record['value']
                    origin = dict(domain='sample', index=0,
                        rate={'num': parent_docs['settings', 'project']['value']['sample_rate'], 'den': 1},
                        origin='source', source_artifact=semantic['source_audio'])
                point: Any = copy.deepcopy(item.get('source_in') or origin)
                if point is None:
                    unsupported.append(dict(item_id=item['item_id'], reason='Explicit source_in required for source-linked artifact trims.'))
                    continue
                if point['domain'] == 'source_tick':
                    # Raw nonzero PTS needs its retained probe/start_pts; do not
                    # mistake ticks for samples or silently reset source origin.
                    unsupported.append(dict(item_id=item['item_id'], reason='Raw source ticks require explicit existing conform evidence before extraction.'))
                    continue
                units_per_second = rate_fraction(point['rate'])
                source_start = Fraction(point['index']) + Fraction(a - item['start_frame']) / fps * units_per_second
                source_end = Fraction(point['index']) + Fraction(b - item['start_frame']) / fps * units_per_second
                if source_start.denominator != 1 or source_end.denominator != 1:
                    unsupported.append(dict(item_id=item['item_id'], reason='Source endpoint is not an exact native frame/sample; explicit conform required.'))
                    continue
                output_start = output_offset + a - span['start_frame']
                output_end = output_offset + b - span['start_frame']
                # Reuse the existing exact source mapper. Scale a rational native
                # rate into integer ticks rather than convert through floats.
                scale = units_per_second.denominator
                mapped = map_source_range(source_start.numerator * scale, source_end.numerator * scale,
                    source_start=source_start.numerator * scale, source_end=source_end.numerator * scale,
                    source_rate=units_per_second.numerator,
                    output_start=Fraction(output_start) / fps, output_end=Fraction(output_end) / fps,
                    speed={'num': 1, 'den': 1})
                if mapped is None:
                    raise ContractError('TIMING_INVALID', 'Editorial source map unexpectedly has no overlap.')
                placement = copy.deepcopy(item)
                # Stable bounded keys even when long original IDs repeat in cuts.
                placement['item_id'] = 'cut_' + digest(dict(cut=cut_index, track=track['track_id'], item=item['item_id'])).split(':')[1][:32]
                placement.update(start_frame=output_start, end_frame=output_end,
                    source_in=dict(point, index=source_start.numerator))
                target['items'].append(placement)
                row = dict(cut_index=cut_index, track_id=track['track_id'], item_id=item['item_id'],
                    source=source_pin, source_start=dict(point, index=source_start.numerator),
                    source_end=dict(point, index=source_end.numerator),
                    parent_start_frame=a, parent_end_frame=b, output_start_frame=output_start, output_end_frame=output_end,
                    output_start_seconds=fraction_json(mapped[0]), output_end_seconds=fraction_json(mapped[1]))
                mapping.append(row)
                closure.append(dict(mapping=row, subject=semantic,
                    gain_db=item.get('gain_db'), transform=item.get('transform'), crop=item.get('crop')))
        output_offset += span['end_frame'] - span['start_frame']
    timeline = dict(duration_frames=output_offset, tracks=[tracks[k] for k in sorted(tracks)])
    caption_doc = None
    if extract['caption']:
        caption_doc, _ = historical(projects, fs, pointer, extract['caption'])
    from .editorial_production import apply_decisions
    apply_decisions(extract, timeline, caption_doc, unsupported)
    semantic = dict(hook=extract['hook'], ranges=extract['ranges'], rate=rate,
        mapped_closure=closure, caption=caption_doc, caption_decision=extract['caption_decision'],
        crop=extract['crop'], crop_decision=extract['crop_decision'])
    source_sha = digest(semantic)
    variants = selected_profiles(parent_docs, extract['variants'], output_offset)
    semantic['variants'] = variants
    # Parent document/revision is provenance, deliberately NOT the reuse key.
    # Thus an unrelated scene change does not invalidate every extract.
    return dict(schema='motion/v1/editorial-extract', extract_id=extract['extract_id'],
        variants=variants, source_recipe_sha256=source_sha,
        parent_timeline=document_pin(parent), recipe_sha256=digest(semantic), rate=rate,
        timeline=timeline, source_map=mapping, caption=extract['caption'], crop=extract['crop'],
        scene_closure=[dict(scene_id=sid, value=parent_docs['scene', sid]['value'])
            for sid in sorted({i['subject']['scene_id'] for t in timeline['tracks']
                for i in t['items'] if i['subject']['kind'] == 'scene'})],
        unsupported=unsupported, source_scope_complete=not unsupported,
        claim='Executable source-linked timeline recipe; encoded production requires ordinary owned jobs.')


def state(runtime, pid):
    fs = runtime.projects._filesystem()
    pointer = runtime.projects._pointer(fs, pid)
    _, docs = runtime.projects._load(fs, pointer)
    record = docs.get(('editorial', 'project'))
    return fs, pointer, docs, record


def checked_update(runtime, args, changes):
    result = runtime.projects.dispatch(dict(action='update', project_id=args['project_id'],
        expected_revision=args['expected_revision'], request_id=args['request_id'], changes=changes))
    if not result.get('ok'):
        error = result.get('error', {})
        raise ContractError(error.get('code', 'INVALID_ARGUMENT'), error.get('message', 'Editorial update failed.'))
    return result['data']


def dispatch(runtime, args):
    pid, action = args['project_id'], args['action']
    if action == 'editorial_update':
        return checked_update(runtime, args, [dict(op='set_editorial', value=args['value'])])
    fs, pointer, docs, record = state(runtime, pid)
    if record is None:
        if action == 'editorial_get':
            return dict(value=None, production_started=False)
        raise ContractError('NOT_FOUND', 'No editorial selections have been saved.')
    value = record['value']
    from .editorial_production import master_recipe, verify_output
    frozen, frozen_docs = frozen_parent(runtime.projects, fs, pointer, value)
    master_sha = master_recipe(frozen, frozen_docs)
    recipes = {extract['extract_id']: recipe(runtime.projects, fs, pointer, value, extract) for extract in value['extracts']}
    for prepared in recipes.values():
        for row in prepared['source_map']:
            if 'artifact_id' in row['source']:
                runtime.artifacts.resolve(pid, row['source'])
    if action == 'editorial_get':
        matrix = []
        for requested in value['deliverables']:
            expected_sha = master_sha if requested['kind'] == 'full_master' else recipes[requested['extract_id']]['recipe_sha256']
            profiles = (selected_profiles(frozen_docs, [requested['variant_id']], frozen['value']['duration_frames'])
                        if requested['kind'] == 'full_master' else recipes[requested['extract_id']]['variants'])
            profile_matches = matching_profiles(docs, profiles)
            found = [o for o in value['outputs'] if
                o['extract_id'] == requested['extract_id'] and o['variant_id'] == requested['variant_id'] and
                o['recipe_sha256'] == expected_sha and o['variant_id'] in profile_matches]
            for output in found:
                runtime.artifacts.resolve(pid, output['artifact'])
            retained = 'retained_master_output' if requested['kind'] == 'full_master' else 'retained_extract_output'
            matrix.append(dict(requested, state=retained if found else 'missing',
                artifacts=[o['artifact'] for o in found]))
        return dict(value=copy.deepcopy(value), project_revision=pointer['revision'],
            recipes=list(recipes.values()), deliverable_matrix=matrix,
            package_membership=[p for row in matrix for p in row['artifacts']],
            missing_required=[r['deliverable_id'] for r in matrix if r['required'] and r['state'] == 'missing'],
            production_started=False)
    if action == 'editorial_reconform':
        parent = docs['timeline', 'project']
        # extract_apply selects an existing recipe, not a newly authored parent.
        # Still read current scene/profile values to detect real semantic edits.
        if any(parent['value'] == r['timeline'] for r in recipes.values()):
            parent = frozen
        rows = []
        for extract in value['extracts']:
            old = recipes[extract['extract_id']]
            reusable = set()
            try:
                new = recipe(runtime.projects, fs, pointer, value, extract, parent_override=parent, docs_override=docs)
                changed = old['recipe_sha256'] != new['recipe_sha256'] or not new['source_scope_complete']
                reason = None if not changed else 'selected_picture_dialogue_timing_or_decisions_changed'
                if old['source_recipe_sha256'] == new['source_recipe_sha256'] and new['source_scope_complete']:
                    reusable = matching_profiles(docs, old['variants'])
            except ContractError as exc:
                new, changed, reason = None, True, exc.code
            retained = [o['artifact'] for o in value['outputs'] if o['extract_id'] == extract['extract_id']
                and o['variant_id'] in reusable and o['recipe_sha256'] == old['recipe_sha256']]
            for pin in retained:
                runtime.artifacts.resolve(pid, pin)
            rows.append(dict(extract_id=extract['extract_id'], affected=changed, reason=reason,
                previous_recipe_sha256=old['recipe_sha256'],
                candidate_recipe_sha256=None if new is None else new['recipe_sha256'], retained_outputs=retained))
        return dict(parent_timeline=document_pin(parent), extracts=rows,
            affected_extracts=[r['extract_id'] for r in rows if r['affected']],
            recompile_only=[r['extract_id'] for r in rows if r['affected']], production_started=False)
    if action == 'full_master_apply':
        for track in frozen['value']['tracks']:
            for item in track['items']:
                subject = item['subject']
                key = ('scene', subject['scene_id']) if subject['kind'] == 'scene' else (
                    ('caption', subject['caption']['id']) if subject['kind'] == 'caption' else None)
                if key and (key not in docs or docs[key]['value'] != frozen_docs[key]['value']):
                    raise ContractError('PLAN_STALE', 'Frozen master source changed; revise the parent pin first.')
        return checked_update(runtime, args, [dict(op='set_timeline', value=frozen['value']),
            dict(op='set_variants', value=frozen_docs['variants', 'project']['value'])])
    if action == 'full_master_bind':
        if not any(d['kind'] == 'full_master' and d['variant_id'] == args['variant_id'] for d in value['deliverables']):
            raise ContractError('INVALID_ARGUMENT', 'Full master variant is not requested.')
        selected_master = dict(timeline=frozen['value'],
            variants=selected_profiles(frozen_docs, [args['variant_id']], frozen['value']['duration_frames']), scene_closure=[
            dict(scene_id=sid, value=frozen_docs['scene', sid]['value'])
            for sid in sorted({i['subject']['scene_id'] for t in frozen['value']['tracks']
                for i in t['items'] if i['subject']['kind'] == 'scene'})])
        producing_docs = verify_output(runtime, pid, pointer, selected_master, args)
        if master_recipe(producing_docs['timeline', 'project'], producing_docs) != master_sha:
            raise ContractError('HASH_MISMATCH', 'Producing master semantic closure differs from frozen parent.')
        output = dict(extract_id=None, variant_id=args['variant_id'], recipe_sha256=master_sha,
            artifact=args['artifact'], job_id=args['job_id'])
        return admit_output(runtime, args, value, output)
    selected = recipes.get(args['extract_id'])
    if not selected:
        raise ContractError('NOT_FOUND', 'Unknown extract ID.')
    if action == 'extract_inspect':
        return selected
    if not selected['source_scope_complete']:
        raise ContractError('UNSUPPORTED_FEATURE', 'Selected source intervals need explicit conform before timeline application.', details={'unsupported': selected['unsupported']})
    if action == 'extract_apply':
        if selected['caption']:
            current = docs.get(('caption', selected['caption']['id']))
            if current is None or document_pin(current) != selected['caption']:
                raise ContractError('HASH_MISMATCH', 'Restore the selected caption revision explicitly before applying this extract.')
        # Existing scene IDs must still match the frozen closure. Applying old
        # source to changed scenes by ID alone would silently alter the extract.
        _, frozen_docs = frozen_parent(runtime.projects, fs, pointer, value)
        for track in selected['timeline']['tracks']:
            for item in track['items']:
                if item['subject']['kind'] == 'scene':
                    key = ('scene', item['subject']['scene_id'])
                    if key not in docs or docs[key]['value'] != frozen_docs[key]['value']:
                        raise ContractError('PLAN_STALE', 'Selected source scene changed; reconform/revise the parent pin first.')
        variants = copy.deepcopy(docs['variants', 'project']['value'])
        for variant in variants:
            variant['duration_frames'] = selected['timeline']['duration_frames']
        result = checked_update(runtime, args, [dict(op='set_timeline', value=selected['timeline']), dict(op='set_variants', value=variants)])
        return dict(result, extract_id=args['extract_id'], recipe_sha256=selected['recipe_sha256'],
            production_started=False, note='Normal project timeline selected; compile and execute through existing authority.')
    extract = next(e for e in value['extracts'] if e['extract_id'] == args['extract_id'])
    if args['variant_id'] not in extract['variants']:
        raise ContractError('INVALID_ARGUMENT', 'Variant is not requested for this extract.')
    verify_output(runtime, pid, pointer, selected, args, caption=selected['caption'])
    output = dict(extract_id=args['extract_id'], variant_id=args['variant_id'], recipe_sha256=selected['recipe_sha256'],
        artifact=args['artifact'], job_id=args['job_id'])
    return admit_output(runtime, args, value, output)


def admit_output(runtime, args, value, output):
    updated = copy.deepcopy(value)
    updated['outputs'] = [o for o in updated['outputs'] if not (o['extract_id'] == output['extract_id'] and o['variant_id'] == output['variant_id'])] + [output]
    # Trusted one-call admission is private to this ProjectStore instance and is
    # cleared even on transaction failure; it is never a caller schema field.
    runtime.projects._editorial_output_admission = output
    try:
        return checked_update(runtime, args, [dict(op='set_editorial', value=updated)])
    finally:
        runtime.projects._editorial_output_admission = None
