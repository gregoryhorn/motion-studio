"""Applied extract decisions and exact succeeded-output admission helpers."""
from __future__ import annotations

import copy

from .contracts import ContractError, digest


def apply_decisions(extract, timeline, caption_doc, unsupported):
    """Attach executable crop/caption placements, never infer caption origin."""
    crop = extract['crop']
    if crop:
        if crop['x_px'] < 0 or crop['y_px'] < 0:
            unsupported.append(dict(item_id='crop', reason='Crop coordinates must be nonnegative.'))
        for track in timeline['tracks']:
            if track['kind'] == 'video':
                for item in track['items']:
                    if 'transform' in item:
                        unsupported.append(dict(item_id=item['item_id'], reason='Crop with a layout transform requires explicit conform.'))
                    item['crop'] = copy.deepcopy(crop)
    if not caption_doc:
        return
    pin = extract['caption']
    # Keep only the selected caption. Existing audio placements remain the source
    # of truth for timings when there is no explicit caption track.
    for track in timeline['tracks']:
        if track['kind'] == 'caption':
            track['items'] = [i for i in track['items'] if i['subject'].get('caption') == pin]
    selected = [i for t in timeline['tracks'] if t['kind'] == 'caption' for i in t['items']]
    if selected:
        return
    audio = caption_doc['value']['source_audio']
    items = []
    for track in timeline['tracks']:
        if track['kind'] != 'audio':
            continue
        for item in track['items']:
            if item['subject'] != dict(kind='artifact', artifact=audio):
                continue
            point = item.get('source_in', {})
            if point.get('domain') != 'sample' or point.get('origin') != 'source' or point.get('source_artifact') != audio:
                unsupported.append(dict(item_id=item['item_id'], reason='Caption source requires exact audio sample provenance.'))
                continue
            copied = copy.deepcopy(item)
            copied.pop('gain_db', None)
            copied['item_id'] = 'caption_' + digest(item['item_id']).split(':')[1][:24]
            copied['subject'] = dict(kind='caption', caption=copy.deepcopy(pin))
            items.append(copied)
    if not items:
        unsupported.append(dict(item_id='caption', reason='Selected caption has no explicit parent caption/audio placement.'))
    else:
        timeline['tracks'].append(dict(track_id='editorial_captions', kind='caption', items=items))


def master_recipe(parent, documents):
    """Semantic parent closure; unrelated unplaced scenes do not invalidate it."""
    closure = []
    for track in parent['value']['tracks']:
        for item in track['items']:
            subject = item['subject']
            if subject['kind'] == 'scene':
                key = ('scene', subject['scene_id'])
            elif subject['kind'] == 'caption':
                key = ('caption', subject['caption']['id'])
            else:
                continue
            if key not in documents:
                raise ContractError('NOT_FOUND', 'Parent master source document missing.')
            closure.append(documents[key]['value'])
    return digest(dict(timeline=parent['value'], closure=closure,
                       settings=documents['settings', 'project']['value'],
                       variants=documents['variants', 'project']['value']))


def verify_output(runtime, pid, pointer, selected, args, *, caption=None):
    """Bind only exact successful delivery nodes, not caller-authored receipts."""
    fs = runtime.projects._filesystem()
    bundle = runtime.jobs().read(pid, args['job_id'])
    if bundle['job']['state'] != 'succeeded' or args['artifact'] not in bundle['job']['outputs']:
        raise ContractError('OUTPUT_UNAVAILABLE', 'Output must be a validated successful job output.')
    producer = runtime.artifacts.resolve(pid, args['artifact'])
    if producer['producer']['job_id'] != args['job_id']:
        raise ContractError('WRONG_PROJECT', 'Artifact producer differs from selected job.')
    producing = pointer
    while producing and producing['revision'] > bundle['job']['project_revision']:
        producing = runtime.projects._transaction(fs, producing)['previous']
    if not producing or producing['revision'] != bundle['job']['project_revision']:
        raise ContractError('NOT_FOUND', 'Producing project revision is missing.')
    _, documents = runtime.projects._load(fs, producing)
    if documents['timeline', 'project']['value'] != selected['timeline']:
        raise ContractError('HASH_MISMATCH', 'Producing timeline does not match this recipe.')
    # Scene document IDs alone are insufficient: scenes may have changed since
    # extraction. Compare the actual semantic closure at the producer revision.
    for row in selected.get('scene_closure', []):
        current = documents.get(('scene', row['scene_id']))
        if current is None or current['value'] != row['value']:
            raise ContractError('HASH_MISMATCH', 'Producing scene closure differs from selected recipe.')
    if caption is None:
        placed = [i['subject']['caption'] for t in selected['timeline']['tracks'] if t['kind'] == 'caption'
                  for i in t['items'] if i['subject']['kind'] == 'caption']
        distinct = {digest(p): p for p in placed}
        if len(distinct) > 1:
            raise ContractError('UNSUPPORTED_FEATURE', 'Editorial admission requires one explicit selected caption.')
        caption = next(iter(distinct.values()), None)
    if caption:
        current = documents.get(('caption', caption['id']))
        if current is None or digest(current) != caption['sha256']:
            raise ContractError('HASH_MISMATCH', 'Producing caption differs from selected recipe.')
    nodes = [n for n in bundle['plan_record']['nodes'] if n['operation'] == 'delivery.encode@1'
             and n['parameters'].get('variant') == args['variant_id']
             and n['node_id'] == producer['producer']['node_id']]
    if len(nodes) != 1:
        raise ContractError('OUTPUT_UNAVAILABLE', 'Output is not the selected variant delivery candidate.')
    from .editorial_admission import ProducerLineage
    lineage = ProducerLineage(runtime, pid, bundle)
    candidate, by_id, _ = lineage.resolve(dict(kind='artifact', artifact=args['artifact']), lineage.nodes, 'candidate')
    if candidate != nodes[0]:
        raise ContractError('HASH_MISMATCH', 'Candidate producer differs from selected delivery.')
    variants = documents['variants', 'project']['value']
    variant = next((v for v in variants if v['variant_id'] == args['variant_id']), None)
    if variant is None or variant['duration_frames'] != selected['timeline']['duration_frames']:
        raise ContractError('HASH_MISMATCH', 'Producing variant differs from selected timing.')
    expected_variant = next((v for v in selected.get('variants', []) if v['variant_id'] == args['variant_id']), None)
    if expected_variant is None or variant != expected_variant:
        raise ContractError('HASH_MISMATCH', 'Producing variant differs from frozen editorial profile.')
    if caption and variant['captions'] == 'none':
        raise ContractError('OUTPUT_UNAVAILABLE', 'Selected caption cannot bind a caption-free delivery.')
    from .editorial_admission import media_chain, caption_placement, audio_chain
    burns = media_chain(runtime, pid, nodes[0], by_id, selected['timeline'], documents, variant, lineage=lineage)
    audio_chain(nodes[0], by_id, documents, variant, lineage=lineage)
    if burns and (caption is None or variant['captions'] not in ('burn', 'both')):
        raise ContractError('HASH_MISMATCH', 'Unexpected caption burn in selected output.')
    if caption and variant['captions'] in ('burn', 'both'):
        if len(burns) != 1:
            raise ContractError('HASH_MISMATCH', 'Selected caption burn is not the actual media producer.')
        caption_placement(runtime, pid, burns[0], caption, documents, variant)
    if caption and variant['captions'] in ('sidecar', 'both'):
        sidecars = nodes[0].get('inputs', {}).get('sidecars', [])
        if len(sidecars) != 1:
            raise ContractError('HASH_MISMATCH', 'Selected sidecar must be directly consumed by delivery.')
        exported, _, _ = lineage.resolve(sidecars[0], by_id, 'sidecar')
        if exported['operation'] != 'caption.export@1':
            raise ContractError('HASH_MISMATCH', 'Sidecar producer is not selected caption export.')
        caption_placement(runtime, pid, exported, caption, documents, variant, sidecar=True)
    # The actual media and caption input chains, not incidental DAG ancestry,
    # now establish the selected recipe's applied pixels and timing.
    return documents
