"""Fail-closed semantic admission of the actual editorial media chain."""
import json
from pathlib import Path
from typing import NoReturn

from .contracts import ContractError, digest


def pin(record):
    return dict(kind=record['kind'], id=record['id'], revision=record['revision'], sha256=digest(record))


def reject(message) -> NoReturn:
    raise ContractError('HASH_MISMATCH', message)


def node_binding(binding, nodes):
    if not isinstance(binding, dict) or binding.get('kind') != 'node_output':
        reject('Editorial output requires an explicit producing media chain.')
    node = nodes.get(binding.get('node_id'))
    if node is None:
        reject('Editorial producing media node is missing.')
    return node


class ProducerLineage:
    """Resolve only retained, succeeded owned outputs in job-local graphs.

    ArtifactCatalog rehashes the bytes; the owning JobStore output-port map,
    rather than a caller receipt or a producer's node ID alone, identifies the
    operation. Walks are bounded even if retained lineage is corrupt/cyclic.
    """
    def __init__(self, runtime, pid, bundle):
        self.runtime, self.pid = runtime, pid
        self.graphs, self.owners = {}, {}
        self.visits = 0
        self.nodes = self.graph(bundle)

    def graph(self, bundle):
        job = bundle['job']
        jid = job.get('job_id')
        if not jid or not job.get('project_id'):
            reject('Editorial producing media chain has no retained owning job.')
        if job['project_id'] != self.pid or job['state'] != 'succeeded':
            reject('Editorial producer must be an owned succeeded job.')
        if jid not in self.graphs:
            if len(self.graphs) >= 16:
                reject('Editorial producer lineage job limit exceeded.')
            rows = bundle['plan_record']['nodes']
            graph = {n['node_id']: n for n in rows}
            if len(graph) != len(rows):
                reject('Editorial producer node identity is ambiguous.')
            self.graphs[jid] = graph
            self.owners[id(graph)] = bundle
        return self.graphs[jid]

    def resolve(self, binding, nodes, port, trail=()):
        self.visits += 1
        if self.visits > 64 or len(trail) >= 16:
            reject('Editorial producer lineage visit/depth limit exceeded.')
        if not isinstance(binding, dict):
            reject('Editorial producing media binding is missing.')
        if binding.get('kind') == 'artifact':
            artifact = binding['artifact']
            record = self.runtime.artifacts.resolve(self.pid, artifact)
            jid = record.get('producer', {}).get('job_id')
            if not jid:
                reject('Editorial input has no owned succeeded producer.')
            nodes = self.graph(self.runtime.jobs().read(self.pid, jid))
            nid = record['producer'].get('node_id')
        elif binding.get('kind') == 'node_output':
            if binding.get('port') != port:
                reject('Editorial producing output port differs.')
            nid = binding.get('node_id')
            owner = self.owners.get(id(nodes))
            if owner is None:
                reject('Editorial producing graph is missing.')
            artifact = owner.get('output_ports', {}).get(nid, {}).get(port)
            if artifact is None:
                reject('Editorial producing output port is missing.')
            record = self.runtime.artifacts.resolve(self.pid, artifact)
        else:
            reject('Editorial output requires an explicit producing media chain.')
        owner = self.owners[id(nodes)]
        jid = owner['job']['job_id']
        key = (jid, nid, port)
        if key in trail:
            reject('Cyclic editorial producer lineage.')
        matches = [(n, p) for n, ports in owner.get('output_ports', {}).items()
                   for p, value in ports.items() if value == artifact]
        state = next((n for n in owner['job']['node_states'] if n['node_id'] == nid), None)
        origin = record.get('producer', {})
        if binding.get('kind') == 'node_output' and (origin.get('job_id'), origin.get('node_id')) != (jid, nid):
            # Ordinary reuse retains the original artifact producer. Follow it
            # only when this succeeded node explicitly reused that exact port
            # and its semantic fingerprint equals the original producing node.
            fingerprint = nodes.get(nid, {}).get('fingerprint')
            if (record.get('project_id') != self.pid or matches != [(nid, port)]
                    or state is None or state['state'] != 'succeeded'
                    or artifact not in state.get('reused', []) or artifact not in state['outputs']
                    or not fingerprint
                    or not any(o.get('port') == port for o in nodes[nid].get('expected_outputs', []))):
                reject('Editorial reused output mapping is not an exact succeeded reuse.')
            actual, graph, followed = self.resolve(dict(kind='artifact', artifact=artifact), nodes, port, (*trail, key))
            if actual.get('fingerprint') != fingerprint:
                reject('Editorial reused output fingerprint differs from its original producer.')
            return actual, graph, followed
        if (record.get('project_id') != self.pid
                or record.get('producer', {}).get('job_id') != jid
                or record['producer'].get('node_id') != nid
                or matches != [(nid, port)] or nid not in nodes
                or not any(o.get('port') == port for o in nodes[nid].get('expected_outputs', []))
                or state is None or state['state'] != 'succeeded' or artifact not in state['outputs']):
            reject('Editorial producer/output port mapping differs from owned output.')
        return nodes[nid], nodes, (*trail, key)


def media_chain(runtime, pid, producer, nodes, timeline, docs, variant, *, lineage=None):
    """An assembly elsewhere in the DAG is not proof of encoded pixels."""
    binding = producer.get('inputs', {}).get('media')
    trail = ()
    if lineage:
        node, nodes, trail = lineage.resolve(binding, nodes, 'media', trail)
    else:
        node = node_binding(binding, nodes)
    burns = []
    if node['operation'] == 'caption.render@1':
        if not lineage and binding.get('port') != 'media':
            reject('Caption media output port differs.')
        burns.append(node)
        binding = node.get('inputs', {}).get('background')
        if lineage:
            node, nodes, trail = lineage.resolve(binding, nodes, 'media', trail)
        else:
            node = node_binding(binding, nodes)
    if node['operation'] != 'edit.assemble@1' or (not lineage and binding.get('port') != 'media'):
        reject('Undeclared transform in editorial media chain.')
    if node.get('inputs', {}).get('timeline') != dict(kind='document', document=pin(docs['timeline', 'project'])):
        reject('Assembly does not consume the producing timeline pin.')
    params = node.get('parameters', {})
    if (params.get('range') != dict(start_frame=0, end_frame=timeline['duration_frames'])
            or params.get('rate') != variant['rate']
            or params.get('canvas') != dict(width_px=variant['width_px'], height_px=variant['height_px'])):
        reject('Assembly range, canvas or rate differs from selected output.')
    sources = node.get('inputs', {}).get('media', [])
    expected = []
    scenes = set()
    for track in timeline['tracks']:
        if track['kind'] != 'video':
            continue
        for item in track['items']:
            subject = item['subject']
            if subject['kind'] == 'scene':
                scenes.add(subject['scene_id'])
            elif subject['kind'] == 'artifact' and subject['artifact'] not in expected:
                expected.append(subject['artifact'])
    if scenes:
        if len(scenes) != 1 or len(sources) != 1 or expected:
            reject('Editorial scene/render mapping is ambiguous.')
        source, source_nodes = sources[0], nodes
        if lineage:
            rendered, _, _ = lineage.resolve(source, source_nodes, 'media', trail)
            source = dict(port='media')
        else:
            if source.get('kind') == 'artifact':
                record = runtime.artifacts.resolve(pid, source['artifact'])
                origin = record.get('producer', {})
                if not origin.get('job_id'):
                    reject('Scene input has no succeeded producing render.')
                bundle = runtime.jobs().read(pid, origin['job_id'])
                fallback = ProducerLineage(runtime, pid, bundle)
                rendered, _, _ = fallback.resolve(source, fallback.nodes, 'media')
                source = dict(port='media')
            else:
                rendered = node_binding(source, source_nodes)
        scene = docs['scene', next(iter(scenes))]
        if (source.get('port') != 'media' or rendered['operation'] != 'scene.render@1'
                or rendered.get('parameters', {}).get('scene') != pin(scene)
                or rendered.get('parameters', {}).get('range') != dict(start_frame=0, end_frame=scene['value']['duration_frames'])
                or rendered.get('parameters', {}).get('rate') != variant['rate']):
            reject('Assembly scene input is not its selected full-range render.')
    elif (len(sources) != len(expected)
            or any(s.get('kind') != 'artifact' or s.get('artifact') not in expected for s in sources)
            or any(not any(s.get('artifact') == p for s in sources) for p in expected)):
        reject('Assembly source media differs from selected timeline.')
    return burns


def caption_placement(runtime, pid, node, caption_pin, docs, variant, *, sidecar=False):
    from .captions import compile_placement
    if node.get('inputs', {}).get('caption') != dict(kind='document', document=caption_pin):
        reject('Caption producer does not consume selected caption.')
    binding = node.get('inputs', {}).get('placement', {})
    if binding.get('kind') != 'artifact':
        reject('Caption placement must be an exact published artifact.')
    actual = json.loads(Path(runtime.artifact_path(pid, binding['artifact'])).read_bytes())
    caption = docs['caption', caption_pin['id']]['value']
    timeline = docs['timeline', 'project']
    items = [i['item_id'] for t in timeline['value']['tracks'] if t['kind'] == 'caption'
             for i in t['items'] if i['subject'] == dict(kind='caption', caption=caption_pin)]
    if not items:
        items = [i['item_id'] for t in timeline['value']['tracks'] if t['kind'] == 'audio'
                 for i in t['items'] if i['subject'] == dict(kind='artifact', artifact=caption['source_audio'])]
    expected = compile_placement(caption_pin, caption, pin(timeline), timeline['value'],
        pin(docs['variants', 'project']), variant, docs['settings', 'project']['value']['rate'], items)
    if actual != expected:
        reject('Caption placement differs from selected extract mapping or output clock.')
    if sidecar and node.get('parameters', {}).get('time_origin') != 'delivery':
        reject('Editorial sidecar must use delivery-relative timing.')
    if not sidecar and node.get('parameters', {}).get('range') != dict(start_frame=0, end_frame=timeline['value']['duration_frames']):
        reject('Caption burn range differs from selected extract.')


def audio_chain(producer, nodes, docs, variant, *, lineage=None):
    """Require the actually consumed mix, including source trims and gains."""
    from fractions import Fraction
    binding = producer.get('inputs', {}).get('audio')
    if variant['audio']['mode'] == 'none':
        if binding is not None:
            reject('Silent editorial output consumes unexpected audio.')
        return
    mixer = lineage.resolve(binding, nodes, 'audio')[0] if lineage else node_binding(binding, nodes)
    timeline = docs['timeline', 'project']
    if ((not lineage and binding.get('port') != 'audio') or mixer['operation'] != 'audio.mix@1'
            or mixer.get('inputs', {}).get('cue_sheet') != dict(kind='document', document=pin(timeline))):
        reject('Editorial audio is not the selected timeline mix.')
    expected_sources = []
    for track in timeline['value']['tracks']:
        if track['kind'] == 'audio':
            for item in track['items']:
                subject = item['subject']
                if subject['kind'] != 'artifact':
                    reject('Editorial audio requires explicit artifact sources.')
                if subject['artifact'] not in expected_sources:
                    expected_sources.append(subject['artifact'])
    sources = mixer.get('inputs', {}).get('audio', [])
    if (len(sources) != len(expected_sources)
            or any(s.get('kind') != 'artifact' or s.get('artifact') not in expected_sources for s in sources)
            or any(not any(s.get('artifact') == p for s in sources) for p in expected_sources)):
        reject('Editorial mix source audio differs from selected timeline.')
    cadence = variant['rate']
    sample_count = Fraction(timeline['value']['duration_frames'] * variant['audio']['sample_rate'] * cadence['den'], cadence['num'])
    params = mixer.get('parameters', {})
    if (sample_count.denominator != 1 or params.get('duration_samples') != sample_count.numerator
            or params.get('sample_rate') != variant['audio']['sample_rate']
            or params.get('channels') != variant['audio']['channels']
            or params.get('rate', dict(num=30, den=1)) != cadence
            or params.get('loudness_lufs') is not None or params.get('true_peak_dbtp') is not None):
        reject('Editorial audio mix clock/layout differs from selected output.')
