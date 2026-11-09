"""Canonical captions: closed schemas, pure edits, exact placement, core store seam.

No renderer/model is started by a tool handler. Execution convenience actions
must be supplied a B06/B07 compile-and-submit callback by the integration owner.
Artifact resolution/publication and verified actor provenance are injected core
services, never caller-provided approval flags. Import has no shared mutations.
"""
from __future__ import annotations
import copy
from decimal import Decimal
from fractions import Fraction
import functools
import json
import re
from typing import NoReturn
from .contracts import (D, MAX_INT, TEXT, KEY, ADAPTER, DIGEST, DECIMAL, STAMP,
                        UUID_PATTERN, BOOL, ContractError, obj, arr, ref, enum,
                        integer, ident, nullable, string, validate, digest, canonical)
from .project import ProjectStore, _id, _now

DEFS = copy.deepcopy(D)
DEFS['Actor'] = obj({'kind':enum('system','agent','user'),'actor_ref':TEXT})
DEFS['Word'] = obj({'word_id':KEY,'text':TEXT,'start_sample':integer(),'end_sample':integer(1),'confidence':nullable(DECIMAL)})
DEFS['CaptionSegment'] = obj({'segment_id':KEY,'text':TEXT,'start_sample':integer(),'end_sample':integer(1),'sample_rate':integer(1),'speaker':nullable(TEXT),'confidence':nullable(DECIMAL),'words':arr(ref('Word'))})
DEFS['Correction'] = obj({'segment_id':KEY,'before_text':TEXT,'after_text':TEXT,'mode':enum('spelling','preserve_timing_review','realign'),'author':ref('Actor'),'reason':TEXT})
DEFS['CaptionDocument'] = obj({'schema':{'const':'motion/v1/caption'},'caption_id':ident('cap'),'revision':integer(1),'source_audio':ref('ArtifactRef'),'language':TEXT,'language_source':enum('detected','supplied'),'granularity':enum('segment','word'),'segments':arr(ref('CaptionSegment')),'source_transcript':ref('ArtifactRef'),'corrections':arr(ref('Correction')),'timing_state':enum('aligned','reviewed','needs_alignment','review_needed'),'timing_evidence':arr(ref('ArtifactRef')),'timing_decisions':arr(ref('ArtifactRef')),'silence':BOOL})
DEFS['Edit'] = obj({'segment_id':KEY,'text':TEXT,'mode':enum('spelling','preserve_timing_review','realign'),'reason':TEXT})
DEFS['CaptionStyle'] = obj({'schema':{'const':'motion/v1/caption-style'},'style_id':ident('sty'),'revision':integer(1),'fonts':arr(ref('FontRef'),1),'font_size_px':integer(1),'fill':string(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?'),'outline':obj({'color':string(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?'),'width_px':integer()}),'box':nullable(obj({'color':string(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?'),'padding_px':integer()})),'anchor':enum('top','center','bottom'),'margin_px':integer(),'max_width_px':integer(1),'max_lines':integer(1),'line_height':DECIMAL,'align':enum('left','center','right'),'direction':enum('auto','ltr','rtl'),'line_breaks':enum('authored','wrap'),'highlight':enum('none','word'),'animation':enum('none','fade','pop'),'safe_zone':ref('Rect'),'renderer':obj({'adapter_id':ADAPTER,'implementation_version':TEXT,'schema_sha256':DIGEST})})
DEFS['RateSigned'] = obj({'num':integer(-MAX_INT),'den':integer(1)})
DEFS['CaptionPlacementSpan'] = obj({'item_id':KEY,'source_start_sample':integer(),'source_end_sample':integer(1),'source_sample_rate':integer(1),'output_start_seconds':ref('RateSigned'),'output_end_seconds':ref('RateSigned')})
DEFS['CaptionPlacement'] = obj({'schema':{'const':'motion/v1/caption-placement'},'placement_id':KEY,'caption':ref('DocumentRef'),'source_audio':ref('ArtifactRef'),'timeline':ref('DocumentRef'),'variant':ref('DocumentRef'),'project_rate':ref('Rate'),'output_rate':ref('Rate'),'conversion_receipts':arr(ref('ArtifactRef')),'spans':arr(ref('CaptionPlacementSpan'))})
DEFS['ReviewedRange'] = obj({'start_sample':integer(),'end_sample':integer(1),'sample_rate':integer(1)})
review_fields={'source_audio':ref('ArtifactRef'),'timing_content_sha256':DIGEST,'result':enum('approve','reject'),'method':enum('agent_audio','user'),'reviewed_ranges':arr(ref('ReviewedRange'),1),'evidence':arr(ref('ArtifactRef'),1),'reason':TEXT}
DEFS['CaptionTimingDecision'] = obj({'schema':{'const':'motion/v1/caption-timing-decision'},'receipt_id':ident('rcp'),'caption':ref('DocumentRef'),**review_fields,'author':ref('Actor'),'created_at':STAMP})
common={'project_id':ident('prj')}
mutation={**common,'expected_revision':integer(1),'request_id':string(UUID_PATTERN)}
execution={**mutation,'authority_ref':TEXT}
page={'limit':integer(1,100),'cursor':TEXT,'snapshot_id':ident('snp')}
new_style=copy.deepcopy(DEFS['CaptionStyle']); new_style['required'].remove('style_id')
DEFS['CaptionRequest']={'oneOf':[
    obj({'action':{'const':'transcribe'},**execution,'audio':ref('ArtifactRef'),'language':nullable(TEXT),'granularity':enum('segment','word'),'diarize':BOOL,'adapter_id':ADAPTER},optional=['authority_ref','diarize']),
    obj({'action':{'const':'align'},**execution,'caption':ref('DocumentRef'),'audio':ref('ArtifactRef'),'adapter_id':ADAPTER,
         'model':obj({'model_path':TEXT,'model_files_sha256':DIGEST,'language':TEXT})},optional=['authority_ref']),
    obj({'action':{'const':'adopt'},**mutation,'caption_artifact':ref('ArtifactRef'),'source_audio':ref('ArtifactRef')},optional=['source_audio']),
    obj({'action':{'const':'get'},**common,'caption_id':ident('cap'),'revision':integer(1),'section':enum('summary','segments','corrections'),**page},optional=['revision','section',*page]),
    obj({'action':{'const':'correct'},**mutation,'caption':ref('DocumentRef'),'edits':arr(ref('Edit'),1)}),
    obj({'action':{'const':'style'},**mutation,'caption':ref('DocumentRef'),'style':new_style}),
    obj({'action':{'const':'timing_review'},**mutation,'caption':ref('DocumentRef'),**review_fields}),
    obj({'action':{'const':'preview'},**execution,'caption':ref('DocumentRef'),'placement':ref('ArtifactRef'),'timeline_item_ids':arr(KEY,1,True),'style':ref('DocumentRef'),'variant_id':KEY,'background':ref('ArtifactRef'),'frames':arr(integer(),1,True),'adapter_id':ADAPTER},optional=['authority_ref','placement','timeline_item_ids']),
    obj({'action':{'const':'export'},**execution,'caption':ref('DocumentRef'),'time_origin':enum('source','delivery'),'placement':ref('ArtifactRef'),'timeline_item_ids':arr(KEY,1,True),'variant_id':KEY,'format':enum('srt','vtt','ass'),'adapter_id':ADAPTER,'rounding':enum('nearest_even','coverage')},optional=['authority_ref','placement','timeline_item_ids','variant_id','rounding'])]}

@functools.lru_cache(None)
def expanded(name):
    def expand(v):
        if isinstance(v,dict):
            if '$ref' in v: return expand(DEFS[v['$ref'].split('/')[-1]])
            return {k:expand(x) for k,x in v.items()}
        if isinstance(v,list): return [expand(x) for x in v]
        return v
    return expand(DEFS[name])

def schema_document(name):
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',**copy.deepcopy(DEFS[name]),'$defs':copy.deepcopy(DEFS)}

def check(value,name): validate(value,expanded(name))
def fail(message, code='INVALID_ARGUMENT') -> NoReturn:
    raise ContractError(code,message)

def validate_imported_caption(data, *, source_sample_rate=None, duration_samples=None):
    """Parent B04 canonical JSON import hook; validates, never transcribes.

    Core still verifies all source/audio/evidence artifacts via AssetRegistry
    and checks the canonical source document's ownership and immutable bytes.
    Supply actual probe sample rate/duration for source-boundary validation.
    No caller source_audio override is accepted for canonical JSON.
    """
    validate_caption(data)
    for segment in data['segments']:
        if source_sample_rate is not None and segment['sample_rate']!=source_sample_rate:
            fail('Caption sample rate differs from probed source audio.','HASH_MISMATCH')
        if duration_samples is not None and segment['end_sample']>duration_samples:
            fail('Caption extends beyond probed source audio.')
    return data
def pin(document):
    return {'kind':document['kind'],'id':document['id'],'revision':document['revision'],'sha256':digest(document)}
def caption_pin(c):
    # Pure helper pin is for an unwrapped canonical artifact. Store receipt uses
    # the persisted document pin supplied explicitly by review_timing.
    return {'kind':'caption','id':c['caption_id'],'revision':c['revision'],'sha256':digest(c)}
def _bump(n):
    if n >= MAX_INT: fail('Revision exhausted.','LIMIT_EXCEEDED')
    return n+1

def validate_caption_request(args):
    check(args,'CaptionRequest')
    action=args['action']
    for key in ['caption','style']:
        if key in args and not (action=='style' and key=='style'):
            if args[key]['kind'] != ('caption_style' if key=='style' else 'caption'): fail('Wrong document reference kind.')
    if action in ['preview','export']:
        chosen=int('placement' in args)+int('timeline_item_ids' in args)
        if action=='preview' or args.get('time_origin')=='delivery':
            if chosen!=1 or 'variant_id' not in args: fail('Exactly one placement or timeline item selection and target variant required.')
        elif chosen or 'variant_id' in args: fail('Source export forbids placement and variant.')
    if action=='get' and args.get('section','summary')=='summary' and any(k in args for k in page): fail('Summary is not paginated.')

def validate_caption(c):
    check(c,'CaptionDocument')
    if c['silence'] and c['segments']: fail('Silence must contain no segments.')
    if not c['timing_evidence']: fail('Audio/timing evidence required; silence is not inferred from empty text.')
    if len({s['sample_rate'] for s in c['segments']})>1: fail('One source audio requires one actual sample rate.')
    ids=set(); previous={}
    for s in c['segments']:
        if s['segment_id'] in ids: fail('Duplicate segment ID.')
        ids.add(s['segment_id'])
        if s['end_sample']<=s['start_sample']: fail('Empty/reversed segment.')
        for value in [s['confidence'],*[w['confidence'] for w in s['words']]]:
            if value is not None and not Decimal(0)<=Decimal(value)<=Decimal(1): fail('Confidence must be 0..1.')
        speaker=s['speaker']; start=Fraction(s['start_sample'],s['sample_rate'])
        if speaker in previous and start < previous[speaker]: fail('Same-speaker segments overlap or are not monotonic.')
        previous[speaker]=Fraction(s['end_sample'],s['sample_rate'])
        if c['granularity']=='segment' and s['words']: fail('Segment granularity forbids word timing.')
        end=s['start_sample']; word_ids=set()
        for w in s['words']:
            if w['word_id'] in word_ids or w['start_sample']<end or w['end_sample']<=w['start_sample'] or w['end_sample']>s['end_sample']: fail('Invalid word ID/order/bounds.')
            end=w['end_sample']; word_ids.add(w['word_id'])
    if any(e['segment_id'] not in ids for e in c['corrections']): fail('Correction references unknown segment.')
    return c

def word_text_spans(segment):
    """Bind explicit word IDs to exact authored character ranges, never retime.

    Whitespace may separate words (including authored line breaks). Every visible
    character must be covered exactly; punctuation belongs to an aligned word.
    This rejects stale text/word associations rather than guessing via token count.
    """
    cursor=0; result=[]
    for word in segment['words']:
        while cursor<len(segment['text']) and segment['text'][cursor].isspace(): cursor+=1
        text=word['text']
        if not text or not text.strip() or not segment['text'].startswith(text,cursor):
            fail('Word highlighting requires exact aligned word/text correspondence.','REVIEW_REQUIRED')
        end=cursor+len(text)
        result.append({'word_id':word['word_id'],'text_start':cursor,'text_end':end})
        cursor=end
    if segment['text'][cursor:].strip():
        fail('Word highlighting requires timing for every visible word.','REVIEW_REQUIRED')
    return result


def require_word_highlight(c):
    """Additional word-level admission; require_renderable owns timing approval."""
    if c['granularity']!='word':
        fail('Word highlighting requires explicit aligned word timestamps.','UNSUPPORTED_FEATURE')
    for segment in c['segments']:
        if segment['text'].strip() and not segment['words']:
            fail('Word highlighting cannot infer missing word timestamps.','REVIEW_REQUIRED')
        word_text_spans(segment)


def timing_content_hash(c):
    validate_caption(c)
    return digest({k:c[k] for k in ['source_audio','segments']})

def correct_caption(c,edits,actor):
    validate_caption(c); validate(edits,arr(expanded('Edit'),1)); check(actor,'Actor')
    ids=[e['segment_id'] for e in edits]
    if len(set(ids))!=len(ids): fail('Duplicate segment edits.')
    out=copy.deepcopy(c); segments={s['segment_id']:s for s in out['segments']}
    state=c['timing_state']
    for e in edits:
        if e['segment_id'] not in segments: fail('Unknown corrected segment.')
        s=segments[e['segment_id']]; before=s['text']; old_tokens=before.split(); new_tokens=e['text'].split()
        out['corrections'].append({'segment_id':e['segment_id'],'before_text':before,'after_text':e['text'],'mode':e['mode'],'author':copy.deepcopy(actor),'reason':e['reason']})
        s['text']=e['text']
        if e['mode']=='realign' or (e['mode']=='spelling' and len(old_tokens)!=len(new_tokens)):
            state='needs_alignment'
        elif e['mode']=='preserve_timing_review' and state!='needs_alignment': state='review_needed'
        # Word spellings can only be updated one-to-one; no redistributed times.
        if len(s['words'])==len(new_tokens):
            for w,t in zip(s['words'],new_tokens): w['text']=t
        elif s['words']:
            s['words']=[]; state='needs_alignment' if e['mode']!='preserve_timing_review' else 'review_needed'
    if state=='reviewed' and timing_content_hash(out)!=timing_content_hash(c): state='review_needed'
    out['timing_state']=state; out['revision']=_bump(c['revision'])
    return validate_caption(out)

def review_timing(c,args,actor,document_pin=None):
    validate_caption(c); validate(args,obj({k:expanded('CaptionTimingDecision')['properties'][k] for k in review_fields})); check(actor,'Actor')
    if not actor['actor_ref'] or actor['kind']=='system' or (args['method']=='user' and actor['kind']!='user'): fail('Verified review actor required.','PERMISSION_DENIED')
    if c['source_audio']!=args['source_audio'] or timing_content_hash(c)!=args['timing_content_sha256']: fail('Timing/audio pin changed.','HASH_MISMATCH')
    # Conservatively require complete source segment coverage, stronger than only
    # edited ranges; overlapping adjacent review ranges may jointly cover it.
    for r in args['reviewed_ranges']:
        if r['end_sample']<=r['start_sample']: fail('Empty review range.')
    for s in c['segments']:
        cursor=Fraction(s['start_sample'],s['sample_rate']); end=Fraction(s['end_sample'],s['sample_rate'])
        for a,b in sorted((Fraction(r['start_sample'],r['sample_rate']),Fraction(r['end_sample'],r['sample_rate'])) for r in args['reviewed_ranges']):
            if a<=cursor: cursor=max(cursor,b)
        if cursor<end: fail('Review does not cover caption timing.')
    receipt={'schema':'motion/v1/caption-timing-decision','receipt_id':_id('rcp'),'caption':document_pin or caption_pin(c),**copy.deepcopy(args),'author':copy.deepcopy(actor),'created_at':_now()}
    check(receipt,'CaptionTimingDecision')
    out=copy.deepcopy(c); out['revision']=_bump(c['revision']); out['timing_state']='reviewed' if args['result']=='approve' else 'review_needed'
    return out,receipt

def require_renderable(c,decisions):
    validate_caption(c)
    if c['timing_state']=='aligned': return
    if c['timing_state']!='reviewed': fail('Caption needs alignment/timing approval.','REVIEW_REQUIRED')
    for d in decisions:
        check(d,'CaptionTimingDecision')
        if (any(p['sha256']==digest(d) for p in c['timing_decisions']) and d['caption']['id']==c['caption_id']
                and d['caption']['revision']<c['revision'] and d['result']=='approve' and d['source_audio']==c['source_audio']
                and d['timing_content_sha256']==timing_content_hash(c)): return
    fail('Current approved timing decision missing.','REVIEW_REQUIRED')

def rational(r):
    check(r,'RateSigned'); f=Fraction(r['num'],r['den'])
    if (f.numerator,f.denominator)!=(r['num'],r['den']): fail('Rational must be reduced.')
    return f

def map_segments(c,spans):
    validate_caption(c); validate(spans,arr(expanded('CaptionPlacementSpan')))
    result=[]; last=Fraction(0); ids=set()
    for span in spans:
        a,b=span['source_start_sample'],span['source_end_sample']; start=rational(span['output_start_seconds']); end=rational(span['output_end_seconds'])
        if a>=b or start<last or end<=start or span['item_id'] in ids: fail('Placement spans must be ordered, nonempty and nonoverlapping.')
        last=end; ids.add(span['item_id'])
        def mapped(sample): return start+Fraction(sample-a,b-a)*(end-start)
        for s in c['segments']:
            if s['sample_rate']!=span['source_sample_rate']: fail('Sample rate conversion needs explicit receipt.','CONVERSION_REQUIRED')
            lo=max(a,s['start_sample']); hi=min(b,s['end_sample'])
            if lo>=hi or not s['text']: continue
            words=[]
            for w in s['words']:
                x,y=max(lo,w['start_sample']),min(hi,w['end_sample'])
                if x<y: words.append({**w,'start':mapped(x),'end':mapped(y)})
            result.append({**copy.deepcopy(s),'item_id':span['item_id'],'start':mapped(lo),'end':mapped(hi),'words':words})
    return result

def compile_placement(caption_ref,c,timeline_ref,timeline,variant_ref,variant,project_rate,item_ids):
    """Pure current-pin compiler; refuses retiming/rate conversion, never guesses."""
    validate_caption(c); validate(caption_ref,D['DocumentRef']); validate(timeline_ref,D['DocumentRef']); validate(variant_ref,D['DocumentRef'])
    if caption_ref['kind']!='caption' or caption_ref['id']!=c['caption_id'] or caption_ref['revision']!=c['revision'] or timeline_ref['kind']!='timeline' or variant_ref['kind']!='variants': fail('Wrong placement document pins.')
    validate(item_ids,arr(KEY,1,True)); validate(project_rate,D['Rate']); validate(variant,D['Variant']); validate(timeline,D['Timeline'])
    pr=Fraction(project_rate['num'],project_rate['den']); vr=Fraction(variant['rate']['num'],variant['rate']['den'])
    if vr!=pr: fail('Output frame-rate conversion needs a pinned conversion receipt.','CONVERSION_REQUIRED')
    # Captions can bind directly to their actual audio placement. This keeps
    # sample trim and timeline origin identical without a duplicate cue track.
    items=[i for track in timeline['tracks'] if track['kind'] in ('caption','audio') for i in track['items'] if i['item_id'] in item_ids]
    if len(items)!=len(item_ids): fail('Missing/ambiguous caption timeline items.')
    rates={s['sample_rate'] for s in c['segments']}
    if len(rates)!=1: fail('Placement requires known single actual source sample rate.')
    sr=next(iter(rates)); spans=[]
    for item in sorted(items,key=lambda i:i['start_frame']):
        if item['subject'] not in ({'kind':'caption','caption':caption_ref}, {'kind':'artifact','artifact':c['source_audio']}): fail('Timeline caption/audio source pin differs.')
        source=item.get('source_in')
        if source is None: sample=0
        elif source['domain']=='sample' and source['origin']=='source' and source.get('source_artifact')==c['source_audio'] and source['rate']=={'num':sr,'den':1}: sample=source['index']
        else: fail('Source trim needs explicit sample-domain source-audio pin.','CONVERSION_REQUIRED')
        start=Fraction(item['start_frame'],1)/pr; end=Fraction(item['end_frame'],1)/pr; length=(end-start)*sr
        if sample<0 or length.denominator!=1: fail('Placement sample rounding/conform needs receipt.','CONVERSION_REQUIRED')
        def rat(f):
            r={'num':f.numerator,'den':f.denominator}; check(r,'RateSigned'); return r
        spans.append({'item_id':item['item_id'],'source_start_sample':sample,'source_end_sample':sample+int(length),'source_sample_rate':sr,'output_start_seconds':rat(start),'output_end_seconds':rat(end)})
    placement={'schema':'motion/v1/caption-placement','placement_id':'placement','caption':caption_ref,'source_audio':c['source_audio'],'timeline':timeline_ref,'variant':variant_ref,'project_rate':project_rate,'output_rate':variant['rate'],'conversion_receipts':[],'spans':spans}
    check(placement,'CaptionPlacement'); map_segments(c,spans)
    return placement

class CaptionStore(ProjectStore):
    """Small extension of the existing core store, not a second storage/queue.

    Core integration must route CaptionTransaction validation to this class and
    teach its document identity/schema readers these two kinds. `artifacts` is
    a trusted service with read_json(fs,pointer,pin), verify(fs,pointer,pin),
    and publish_json(fs,pointer,value,kind) -> ArtifactRef. Publication must stage
    immutable bytes/records; the caption transaction publishes their closure.
    """
    def __init__(self,root=None,*,artifacts=None,actor=None,execute=None,review_verifier=None,**kwargs):
        super().__init__(root,**kwargs); self.artifacts=artifacts; self.actor=actor; self.execute=execute; self.review_verifier=review_verifier

    def _load(self, fs, pointer):
        snapshot, documents = super()._load(fs, pointer)
        validate_caption_snapshot(self, fs, pointer, snapshot, documents)
        return snapshot, documents

    @staticmethod
    def _safe_document_identity(kind,key):
        if kind in ['caption','caption_style']: validate(key,ident('cap' if kind=='caption' else 'sty')); return
        ProjectStore._safe_document_identity(kind,key)

    @staticmethod
    def _document_schema(kind):
        if kind not in ['caption','caption_style']: return ProjectStore._document_schema(kind)
        return obj({'schema':{'const':'motion/v1/document'},'project_id':ident('prj'),'kind':enum(kind),'id':TEXT,'revision':integer(1),'created_at':STAMP,'value':expanded('CaptionDocument' if kind=='caption' else 'CaptionStyle')})

    def _affected_nodes(self, fs, pointer, before_documents, after_documents):
        """Include committed caption-artifact consumers, not just document pins.

        Caption ports consume canonical payload artifacts. Resolve those actual
        artifacts before matching caption identity; do not infer lineage from a
        label or replace old plan/output records. Ordinary style/document edits
        continue through ProjectStore's existing invalidation implementation.
        """
        affected={item['node_id']:item for item in super()._affected_nodes(
            fs,pointer,before_documents,after_documents)}
        changed={key[1] for key,before in before_documents.items()
            if key[0]=='caption' and before!=after_documents.get(key)}
        if not changed or self.artifacts is None:
            return [affected[key] for key in sorted(affected)]
        from .plans import PlanCompiler
        from .capabilities import CapabilityRegistry
        from .reviews import invalidated_descendants
        compiler=PlanCompiler(self,CapabilityRegistry())
        for plan_id in fs.names(self._base(pointer['project_id'])+'/plans'):
            commit=fs.read(f"{self._base(pointer['project_id'])}/plans/{plan_id}/plan.json")
            plan=compiler.load(pointer['project_id'],compiler.plan_ref(commit['plan']),fs=fs)
            seeds=set()
            for node in plan['nodes']:
                for port in ('caption','captions'):
                    bindings=node['inputs'].get(port,[])
                    for binding in bindings if isinstance(bindings,list) else [bindings]:
                        if binding.get('kind')!='artifact':continue
                        record=self.artifacts.verify(fs,pointer,binding['artifact'])
                        if record['kind']!='caption':continue
                        value=self.artifacts.read_json(fs,pointer,binding['artifact'])
                        validate_caption(value)
                        current=after_documents.get(('caption',value['caption_id']))
                        if value['caption_id'] in changed and (current is None or value!=current['value']):
                            seeds.add(node['node_id'])
            graph={node['node_id']:node['dependencies'] for node in plan['nodes']}
            for node_id in invalidated_descendants(graph,seeds):
                affected.setdefault(node_id,dict(node_id=node_id,reason=(
                    'Consumed canonical caption artifact changed.' if node_id in seeds else 'Upstream caption artifact consumer is stale.')))
        return [affected[key] for key in sorted(affected)]

    @staticmethod
    def _request_hash(args): return digest({'tool':'motion_caption',**{k:v for k,v in args.items() if k!='request_id'}})

    def _transaction(self,fs,pointer):
        tx=fs.read(f"{self._base(pointer['project_id'])}/revisions/{pointer['revision']}/transaction.json")
        if tx.get('schema')=='motion/v1/caption-transaction':
            validate_caption_transaction(tx,pointer); _,docs=self._load(fs,pointer)
            document=docs.get(('caption',tx['caption_id']))
            if document is None or document['revision']!=tx['caption_revision'] or tx['result']['data']['caption']!=pin(document) or tx['document']['sha256']!=digest(document['value']):
                fail('Caption transaction document/artifact closure differs.','HASH_MISMATCH')
            return tx
        return super()._transaction(fs,pointer)

    def dispatch(self,args):
        action=args.get('action') if isinstance(args,dict) else ''
        try:
            validate_caption_request(args)
            if action in ['transcribe','align','preview','export']:
                if self.execute is None: fail('B06/B07 compiled execution route not connected.','CAPABILITY_UNAVAILABLE')
                # Callback must compile explicit registered operations and pass
                # real host authority checks; no private execution here.
                data=self.execute(copy.deepcopy(args))
                return {'ok':True,'tool':'motion_caption','action':action,'status':'ok','summary':'Caption execution submitted through core.','data':data}
            fs=self._filesystem(write=action!='get'); pid=args['project_id']; pointer=self._pointer(fs,pid)
            if action=='get':
                selected=pointer
                if 'revision' in args:
                    while selected:
                        _,docs=self._load(fs,selected)
                        d=docs.get(('caption',args['caption_id']))
                        if d and d['revision']==args['revision']: break
                        selected=self._transaction(fs,selected)['previous']
                    if selected is None: fail('Caption revision unavailable.','NOT_FOUND')
                _,docs=self._load(fs,selected); document=docs.get(('caption',args['caption_id']))
                if document is None: fail('Caption not found.','NOT_FOUND')
                c=validate_caption(document['value']); section=args.get('section','summary')
                if section=='summary':
                    if self.artifacts is None: fail('Artifact publication/resolution not connected.','CAPABILITY_UNAVAILABLE')
                    tx=self._transaction(fs,selected)
                    # Canonical artifact ref is retained in the accepting tx.
                    while tx and not (tx.get('caption_id')==c['caption_id'] and tx.get('caption_revision')==c['revision']):
                        prev=tx['previous']; tx=self._transaction(fs,prev) if prev else None
                    if tx is None: fail('Caption artifact closure unavailable.','OUTPUT_UNAVAILABLE')
                    data={'caption':pin(document),**{k:c[k] for k in ['language','granularity','timing_state','silence','source_audio']},'segment_count':len(c['segments']),'document':tx['document']}
                else:
                    data=self._page(fs,args,None if any(k in args for k in ['cursor','snapshot_id']) else c[section])
                return {'ok':True,'tool':'motion_caption','action':action,'status':'ok','summary':'Caption read.','project_id':pid,'project_revision':pointer['revision'],'data':data}
            if self.artifacts is None or self.actor is None: fail('Trusted artifact and actor core services required.','CAPABILITY_UNAVAILABLE')
            check(self.actor,'Actor')
            base=self._base(pid)
            with fs.lock(base+'/locks/content.lock'):
                pointer=self._pointer(fs,pid)
                replay=self._replay(fs,pointer,args)
                if replay is not None: return replay
                if pointer['revision']!=args['expected_revision']: fail('Project revision changed.','REVISION_CONFLICT')
                snapshot,docs=self._load(fs,pointer); before_docs=copy.deepcopy(docs); docs=copy.deepcopy(docs); slots=copy.deepcopy(snapshot['caption_slots']); decision=None
                if action=='adopt':
                    if 'source_audio' in args: fail('Raw sidecar import is not implemented by this binding.','UNSUPPORTED_FEATURE')
                    c=copy.deepcopy(self.artifacts.read_json(fs,pointer,args['caption_artifact'])); validate_caption(c)
                    if c['timing_state']=='reviewed':
                        decisions=[self.artifacts.read_json(fs,pointer,p) for p in c['timing_decisions']]
                        require_renderable(c,decisions)
                    if ('caption',c['caption_id']) in docs: fail('Adoption cannot overwrite existing caption identity.','REVISION_CONFLICT')
                    for artifact in [c['source_audio'],c['source_transcript'],*c['timing_evidence'],*c['timing_decisions']]: self.artifacts.verify(fs,pointer,artifact)
                    document={'schema':'motion/v1/document','project_id':pid,'kind':'caption','id':c['caption_id'],'revision':c['revision'],'created_at':_now(),'value':c}
                else:
                    p=args['caption']; document=docs.get(('caption',p['id']))
                    if document is None or pin(document)!=p: fail('Caption document pin changed.','REVISION_CONFLICT')
                    c=validate_caption(document['value'])
                    if action=='correct': c=correct_caption(c,args['edits'],self.actor)
                    elif action=='timing_review':
                        review={k:args[k] for k in review_fields}
                        for evidence in review['evidence']: self.artifacts.verify(fs,pointer,evidence)
                        if self.review_verifier is None or self.review_verifier(fs,pointer,c,review,self.actor) is not True:
                            fail('Actual audition/timing-inspection evidence and runtime actor provenance must be verified by core.','REVIEW_REQUIRED')
                        c,decision=review_timing(c,review,self.actor,p)
                        decision=self.artifacts.publish_json(fs,pointer,decision,'report'); c['timing_decisions'].append(decision)
                    elif action=='style':
                        style=copy.deepcopy(args['style']); sid=style.get('style_id') or _id('sty'); old=docs.get(('caption_style',sid))
                        if 'style_id' in style and old is None: fail('New style IDs are core-assigned; supplied style must exist.','NOT_FOUND')
                        if style['revision']!=(old['revision'] if old else 1): fail('Style revision changed.','REVISION_CONFLICT')
                        style['style_id']=sid; style['revision']=_bump(old['revision']) if old else 1; check(style,'CaptionStyle')
                        if Decimal(style['line_height'])<=0: fail('Line height must be positive.')
                        for font in style['fonts']:
                            self.artifacts.verify(fs,pointer,font['face_artifact'])
                            if 'rights_ref' in font:
                                self.artifacts.verify(fs,pointer,font['rights_ref'])
                        sd={'schema':'motion/v1/document','project_id':pid,'kind':'caption_style','id':sid,'revision':style['revision'],'created_at':_now(),'value':style}; docs['caption_style',sid]=sd
                    if action!='style': document={**document,'revision':c['revision'],'created_at':_now(),'value':c}
                docs['caption',c['caption_id']]=document
                slots[c['caption_id']]={'caption':pin(document),'style':pin(sd) if action=='style' else slots.get(c['caption_id'],{}).get('style')}
                invalidated=self._affected_nodes(fs,pointer,before_docs,docs)
                artifact=self.artifacts.publish_json(fs,pointer,c,'caption')
                staged_pins=[artifact] + ([decision] if decision is not None else [])
                if not hasattr(self.artifacts, 'staged_records'):
                    fail('Trusted caption publication must provide staged ArtifactRecords.','OUTPUT_UNAVAILABLE')
                artifact_records=self.artifacts.staged_records(fs,pointer,staged_pins)
                allocated=[int(n) for n in fs.names(base+'/revisions') if n.isascii() and n.isdigit()]; revision=_bump(max(allocated+[pointer['revision']]))
                new={**pointer,'revision':revision,'updated_at':_now(),'manifest_path':f'revisions/{revision}/snapshot.json'}
                snapshot={**snapshot,'revision':revision,'documents':[pin(d) for _,d in sorted(docs.items())],'caption_slots':slots}; new['snapshot_sha256']=digest(snapshot)
                data={'caption':pin(document),'document':artifact,'project_revision':revision}
                if action=='correct': data.update(timing_state=c['timing_state'],invalidated=invalidated)
                if action=='style': data['style']=pin(sd)
                if action=='timing_review': data.update(decision=decision,timing_state=c['timing_state'])
                result={'ok':True,'tool':'motion_caption','action':action,'status':'ok','summary':'Caption content committed.','project_id':pid,'project_revision':revision,'data':data}
                tx={'schema':'motion/v1/caption-transaction','action':action,'request_id':args['request_id'],'request_sha256':self._request_hash(args),'previous':pointer,'pointer':new,'caption_id':c['caption_id'],'caption_revision':c['revision'],'document':artifact,'artifacts':artifact_records,'result':result}
                validate_caption_transaction(tx,new)
                validate_caption_artifacts(self,fs,new,tx,docs)
                dest=base+f'/revisions/{revision}'
                for d in docs.values(): fs.write(dest+f"/documents/{d['kind']}/{d['id']}.json",d)
                fs.write(dest+'/snapshot.json',snapshot); fs.write(dest+'/transaction.json',tx); fs.write(base+'/project.json',new,replace=True)
                return result
        except ContractError as exc:
            result=self._error(action,exc); result['tool']='motion_caption'; return result
        except (OSError,ValueError,TypeError,KeyError):
            result=self._error(action,ContractError('OUTPUT_UNAVAILABLE','Caption dependency/storage is unavailable or invalid.')); result['tool']='motion_caption'; return result

# Strict descriptor at the parent integration seam; action results are bounded
# by the same closed tool envelope's operation-specific data, not caller input.
from .assets import schema_document as asset_schema_document
_asset_record_schema = asset_schema_document('ArtifactRecord')
DEFS.update(copy.deepcopy(_asset_record_schema['$defs']))
DEFS['ArtifactRecord'] = {k: v for k, v in _asset_record_schema.items() if k not in ('$schema', '$id', '$defs')}
DEFS['CaptionTransaction']=obj({'schema':{'const':'motion/v1/caption-transaction'},'action':enum('adopt','correct','style','timing_review'),'request_id':string(UUID_PATTERN),'request_sha256':DIGEST,'previous':ref('ProjectRecord'),'pointer':ref('ProjectRecord'),'caption_id':ident('cap'),'caption_revision':integer(1),'document':ref('ArtifactRef'),'artifacts':arr(ref('ArtifactRecord'),1),'result':obj({'ok':{'const':True},'tool':{'const':'motion_caption'},'action':enum('adopt','correct','style','timing_review'),'status':{'const':'ok'},'summary':TEXT,'project_id':ident('prj'),'project_revision':integer(1),'data':obj({'caption':ref('DocumentRef'),'document':ref('ArtifactRef'),'project_revision':integer(1),'style':ref('DocumentRef'),'timing_state':enum('aligned','reviewed','needs_alignment','review_needed'),'invalidated':arr(obj({'node_id':ident('nod'),'reason':TEXT})),'decision':ref('ArtifactRef')},optional=['style','timing_state','invalidated','decision'])})})

def validate_caption_transaction(tx,pointer):
    check(tx,'CaptionTransaction')
    if tx['pointer']!=pointer or tx['previous']['project_id']!=pointer['project_id'] or tx['previous']['revision']>=pointer['revision']: fail('Caption transaction pointer mismatch.','HASH_MISMATCH')
    if (tx['result']['project_id']!=pointer['project_id'] or tx['result']['project_revision']!=pointer['revision']
            or tx['result']['action']!=tx['action'] or tx['result']['data']['project_revision']!=pointer['revision']
            or tx['result']['data']['document']!=tx['document'] or tx['result']['data']['caption']['id']!=tx['caption_id']
            or tx['result']['data']['caption']['revision']!=tx['caption_revision']): fail('Caption result context mismatch.','HASH_MISMATCH')
    expected = [tx['document']]
    if tx['action'] == 'timing_review':
        if 'decision' not in tx['result']['data']:
            fail('Timing review requires a published decision.', 'HASH_MISMATCH')
        expected.append(tx['result']['data']['decision'])
    actual = [{k:r[k] for k in ('artifact_id','sha256')} for r in tx['artifacts']]
    if len({r['artifact_id'] for r in tx['artifacts']}) != len(actual) or actual != expected:
        fail('Caption artifact closure differs from exact operation outputs.', 'HASH_MISMATCH')
    for record in tx['artifacts']:
        if record['project_id'] != pointer['project_id']:
            fail('Caption output owner differs.', 'WRONG_PROJECT')
        if (record['storage'] != {'mode':'managed','relative_path':'caption-outputs/'+record['artifact_id']+'/payload.json'}
                or any(record['producer'].values()) or record['media_type'] != 'application/json'
                or record['probe_receipt_id'] is not None):
            fail('Caption output must use core-assigned immutable JSON storage.', 'PATH_UNSAFE')
    if tx['artifacts'][0]['kind'] != 'caption' or (len(actual)>1 and tx['artifacts'][1]['kind'] != 'report'):
        fail('Caption output kind differs.', 'HASH_MISMATCH')


def validate_caption_artifacts(store, fs, pointer, tx, documents):
    """Validate staged/committed bytes without recursively loading snapshots."""
    from .artifacts import ArtifactCatalog, read_bounded_json
    validate_caption_transaction(tx, pointer)
    document = documents.get(('caption',tx['caption_id']))
    if document is None or pin(document) != tx['result']['data']['caption']:
        fail('Caption transaction document pin differs.', 'HASH_MISMATCH')
    c = validate_caption(document['value'])
    if (document['project_id'] != pointer['project_id'] or c['caption_id'] != document['id']
            or c['revision'] != document['revision'] or digest(c) != tx['document']['sha256']):
        fail('Caption transaction canonical content differs.', 'HASH_MISMATCH')
    catalog = ArtifactCatalog(store)
    staged = {r['artifact_id']:r for r in tx['artifacts']}
    for record in tx['artifacts']:
        catalog._verify(fs,pointer['project_id'],{k:record[k] for k in ('artifact_id','sha256')},record)
    def resolve(p):
        r = staged.get(p['artifact_id'])
        if r is not None:
            return catalog._verify(fs,pointer['project_id'],p,r)
        return catalog.resolve_at(fs,tx['previous'],p)
    for p in [c['source_audio'],c['source_transcript'],*c['timing_evidence'],*c['timing_decisions']]:
        resolve(p)
    for r in tx['artifacts']:
        with catalog.assets.open_artifact(fs,r) as stream:
            value = read_bounded_json(stream)
        if r['artifact_id'] == tx['document']['artifact_id'] and value != c:
            fail('Caption payload differs from document content.', 'HASH_MISMATCH')
        if r['kind'] == 'report':
            check(value,'CaptionTimingDecision')
        dependencies = ([value['source_audio'], value['source_transcript'], *value['timing_evidence'], *value['timing_decisions']]
                        if r['kind'] == 'caption' else [value['source_audio'], *value['evidence']])
        inputs = []
        for dependency in dependencies:
            if dependency not in inputs:
                inputs.append(dependency)
        if r['inputs'] != inputs:
            fail('Caption artifact input lineage differs.', 'HASH_MISMATCH')
        for dependency in inputs:
            resolve(dependency)
    if c['timing_state'] == 'reviewed':
        decisions = []
        for p in c['timing_decisions']:
            with catalog.open_record(fs,resolve(p)) as stream:
                decisions.append(read_bounded_json(stream))
        require_renderable(c,decisions)
    if 'style' in tx['result']['data']:
        style_pin=tx['result']['data']['style']; style=documents.get(('caption_style',style_pin['id']))
        if style is None or pin(style) != style_pin:
            fail('Caption style document pin differs.', 'HASH_MISMATCH')
        for font in style['value']['fonts']:
            resolve(font['face_artifact'])
            if 'rights_ref' in font:
                resolve(font['rights_ref'])


def validate_caption_snapshot(store, fs, pointer, snapshot, documents):
    """Core _load hook: validate slots and ALL caption-history artifact bytes.

    Does not call _load/_transaction; safe for ProjectStore's own load path.
    """
    captions={key[1]:value for key,value in documents.items() if key[0]=='caption'}
    if set(snapshot['caption_slots']) != set(captions):
        fail('Caption slots differ from caption documents.', 'HASH_MISMATCH')
    for cid,slot in snapshot['caption_slots'].items():
        if slot['caption'] != pin(captions[cid]):
            fail('Caption slot document pin differs.', 'HASH_MISMATCH')
        if slot['style'] is not None:
            style=documents.get(('caption_style',slot['style']['id']))
            if style is None or pin(style) != slot['style']:
                fail('Caption slot style pin differs.', 'HASH_MISMATCH')
    selected=pointer; seen=set(); accepted=set()
    while selected:
        if selected['revision'] in seen:
            fail('Caption history contains a cycle.', 'INVALID_GRAPH')
        seen.add(selected['revision'])
        tx=fs.read(f"{store._base(pointer['project_id'])}/revisions/{selected['revision']}/transaction.json")
        if tx.get('pointer') != selected:
            fail('Caption history pointer differs.', 'HASH_MISMATCH')
        if tx.get('schema') == 'motion/v1/caption-transaction':
            validate_caption_transaction(tx,selected)
            dest=f"{store._base(pointer['project_id'])}/revisions/{selected['revision']}/documents/"
            d=fs.read(dest+'caption/'+tx['caption_id']+'.json')
            validate(d,store._document_schema('caption'))
            historical={('caption',tx['caption_id']):d}
            if 'style' in tx['result']['data']:
                sid=tx['result']['data']['style']['id']
                historical['caption_style',sid]=fs.read(dest+'caption_style/'+sid+'.json')
                validate(historical['caption_style',sid],store._document_schema('caption_style'))
            validate_caption_artifacts(store,fs,selected,tx,historical)
            accepted.add((d['id'],digest(d)))
        previous=tx['previous']
        if previous and (previous['revision'] >= selected['revision'] or previous['project_id'] != pointer['project_id']):
            fail('Caption history must stay in project and decrease.', 'INVALID_GRAPH')
        selected=previous
    if any((d['id'],digest(d)) not in accepted for d in captions.values()):
        fail('Caption document has no committed accepting artifact closure.', 'OUTPUT_UNAVAILABLE')

def caption_tool_schema():
    return {'name':'motion_caption','description':'Read/adopt/correct/style/review captions; execution requires core frozen plans and authority.','parameters':schema_document('CaptionRequest')}

def caption_handler(args,**context):
    return CaptionStore(artifacts=context.get('caption_artifacts'),actor=context.get('verified_actor'),execute=context.get('caption_execute'),review_verifier=context.get('caption_review_verifier')).dispatch(args)
