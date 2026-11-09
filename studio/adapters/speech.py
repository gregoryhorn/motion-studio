"""Existing local faster-whisper binding; no downloads, fallback or startup on read.

This module is called only by the approved local job runner. Discovery inspects
package metadata and model files only. Corrected-text forced alignment belongs
to the separate optional WhisperX extension in alignment.py, never to an ASR
prompt. This module exports lazy entrypoints for that owned adapter.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import subprocess
from ..captions import validate_caption, fail, check
from ..contracts import canonical
from ..project import _id

ADAPTER_ID='local.faster-whisper'
VERSION='1.0'
REQUIRED_MODEL_FILES=('model.bin','config.json','tokenizer.json','vocabulary.txt')

def discover(model_path=None):
    """Read-only discovery. No imports of engine, network, model loads or scans
    of user media. A runtime is selected only by an explicit absolute directory.
    """
    installed=importlib.util.find_spec('faster_whisper') is not None
    info={'adapter_id':ADAPTER_ID,'implementation_version':VERSION,'installed':installed,
          'engine_version':importlib.metadata.version('faster-whisper') if installed else None,
          'model_path':str(model_path) if model_path is not None else None,
          'model_files_present':False,'transcribe_available':False,'align_available':False,
          'alignment_blocker':'Faster-whisper is not a forced aligner; select local.whisperx-align with its own explicit pinned local CTC model.',
          'features':{'granularities':['segment','word'],'diarization':False,'network':False}}
    if model_path is not None:
        p=Path(model_path)
        info['model_files_present']=p.is_absolute() and p.is_dir() and all((p/f).is_file() and (p/f).stat().st_size>0 for f in REQUIRED_MODEL_FILES)
        info['transcribe_available']=installed and info['model_files_present']
    return info

def model_identity(model_path):
    """Hash actual selected runtime files for a frozen execution receipt."""
    files=[]
    for name in REQUIRED_MODEL_FILES:
        p=Path(model_path)/name; h=hashlib.sha256()
        with p.open('rb') as stream:
            while chunk:=stream.read(1024*1024): h.update(chunk)
        files.append({'name':name,'sha256':'sha256:'+h.hexdigest(),'size_bytes':p.stat().st_size})
    return files

def transcribe(audio_path,source_audio,output_dir,*,model_path,language,granularity,diarize=False,ffprobe='/usr/bin/ffprobe'):
    """Actual engine output -> canonical caption plus original-time evidence.

    Explicit existing CPU int8 runtime, local_files_only=True. Caller stages
    immutable input and allocates fresh output_dir under the accepted attempt;
    returned paths are NOT yet adopted or registered project artifacts. B07
    collector must hash/publish the source transcript and timing artifacts and
    call finalize_caption with their real refs. No fabricated artifact refs.
    """
    check(source_audio,'ArtifactRef')
    if granularity not in ['segment','word'] or (language is not None and type(language)!=str): fail('Unsupported transcription parameters.')
    if diarize: fail('Selected faster-whisper binding does not diarize.','UNSUPPORTED_FEATURE')
    if not discover(model_path)['transcribe_available']: fail('Existing selected local faster-whisper model/runtime unavailable.','CAPABILITY_UNAVAILABLE')
    path=Path(audio_path)
    if not path.is_file() or path.is_symlink(): fail('Expected staged regular audio file.','PATH_UNSAFE')
    sha='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
    if sha!=source_audio['sha256']: fail('Source audio pin changed.','HASH_MISMATCH')
    # Decode metadata in the owned engine process; no private ffprobe child.
    import av
    with av.open(str(path)) as container:
        streams=list(container.streams.audio)
        if len(streams)!=1: fail('Require exactly one explicit source audio stream.','UNSUPPORTED_FEATURE')
        sample_rate=int(streams[0].codec_context.sample_rate)
        duration_samples=sum(frame.samples for frame in container.decode(audio=0))
    if duration_samples <= 0: fail('Empty source audio.')
    from faster_whisper import WhisperModel
    runtime=WhisperModel(str(model_path),device='cpu',compute_type='int8',local_files_only=True)
    generated,info=runtime.transcribe(str(path),language=language,word_timestamps=granularity=='word',vad_filter=False)
    segments=[]; raw=[]; conversions=[]
    def sample(seconds):
        original=Decimal(str(seconds)); index=int((original*sample_rate).to_integral_value(rounding=ROUND_HALF_EVEN))
        conversions.append({'seconds':str(original),'sample':index,'sample_rate':sample_rate,'rounding':'nearest_even','error_seconds':str(Decimal(index)/sample_rate-original)})
        return index
    for i,s in enumerate(generated):
        words=[]; original_words=[]
        for j,w in enumerate(s.words or []) if granularity=='word' else []:
            words.append({'word_id':f's{i}_w{j}','text':w.word,'start_sample':sample(w.start),'end_sample':sample(w.end),'confidence':str(w.probability)})
            original_words.append({'word':w.word,'start_seconds':str(w.start),'end_seconds':str(w.end),'probability':str(w.probability)})
        segments.append({'segment_id':f's{i}','text':s.text,'start_sample':sample(s.start),'end_sample':sample(s.end),'sample_rate':sample_rate,'speaker':None,'confidence':None,'words':words})
        raw.append({'id':s.id,'text':s.text,'start_seconds':str(s.start),'end_seconds':str(s.end),'avg_logprob':str(s.avg_logprob),'no_speech_prob':str(s.no_speech_prob),'words':original_words})
    # Empty decoding alone does not establish silence; do not manufacture it.
    if not segments: fail('Engine returned no segments; silence needs independently retained audio evidence.','REVIEW_REQUIRED')
    draft={'schema':'motion/v1/caption','caption_id':_id('cap'),'revision':1,'source_audio':source_audio,
           'language':info.language,'language_source':'supplied' if language is not None else 'detected',
           'granularity':granularity,'segments':segments,'corrections':[],'timing_state':'aligned',
           'timing_decisions':[],'silence':False}
    evidence={'engine':'faster-whisper','engine_version':importlib.metadata.version('faster-whisper'),'implementation_version':VERSION,
              'source_audio':source_audio,'sample_rate':sample_rate,'duration_samples':duration_samples,'model_files':model_identity(model_path),'language_probability':str(info.language_probability),
              'segments':raw,'sample_conversions':conversions,'controls':{'device':'cpu','compute_type':'int8','local_files_only':True,'vad_filter':False}}
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=False)
    source_path=out/'source-transcript.json'; source_path.write_bytes(canonical(evidence))
    draft_path=out/'caption-draft.json'; draft_path.write_bytes(canonical(draft))
    return {'caption_draft':draft,'source_transcript_path':str(source_path),'caption_draft_path':str(draft_path),'source_sha256':'sha256:'+hashlib.sha256(source_path.read_bytes()).hexdigest()}

def finalize_caption(draft,source_transcript,timing_evidence):
    """Core collector supplies verified immutable artifacts, not invented IDs."""
    import copy
    c=copy.deepcopy(draft); c['source_transcript']=source_transcript; c['timing_evidence']=timing_evidence
    return validate_caption(c)

def align(*args,**kwargs):
    """Owned-worker entrypoint for genuine corrected-text CTC alignment.

    This is not a faster-whisper option. Use alignment_registration() and
    LocalAlignmentAdapter for the public B06/B07 job route.
    """
    from .alignment import align as force_align
    return force_align(*args,**kwargs)


def alignment_registration():
    from .alignment import registration as register_alignment
    return register_alignment()


def alignment_discover(model_path=None):
    from .alignment import discover as discover_alignment
    return discover_alignment(model_path)


MODEL_OPTIONS = 'motion/v1/local-faster-whisper/existing-model'


def registration():
    """Metadata-only ABI. Explicit local model identity is frozen in options.

    No implicit model choice, startup, network, or cache traversal. The caller
    supplies an existing absolute model_path plus model_files_sha256 (digest of
    model_identity(path)) as RegisteredOptions when compiling the job.
    """
    from ..adapters import alternative
    from ..capabilities import PARAMS, expanded
    from ..contracts import obj, TEXT, DIGEST
    meta = alternative.registration(alternative.ESPEAK_ID)
    decl = meta['declaration']
    decl.update(adapter_id=ADAPTER_ID, label='Offline faster-whisper CPU int8',
                implementation_version=VERSION)
    op = decl['operations'][0]
    op.update(operation='speech.transcribe@1',
              request_schema='motion/v1/local-faster-whisper/transcribe-request',
              result_schema='motion/v1/local-faster-whisper/transcribe-result',
              features=['speech.words'], default_timeout_seconds=120)
    op['constraints'].update(media_types=['audio/wav', 'audio/x-wav', 'audio/flac', 'application/json'],
                             codecs=[], languages=['en'], timing='word')
    decl['dependencies'] = [dict(name='faster-whisper', kind='library',
        version_constraint=None, required=True)]
    result_schema = next(v for k,v in meta['schemas'].items() if k.endswith('-result'))
    meta.update(implementation_sha256='sha256:'+hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        schemas={op['request_schema']:expanded(PARAMS['speech.transcribe@1']),
                 op['result_schema']:result_schema,
                 MODEL_OPTIONS:obj(dict(model_path=TEXT, model_files_sha256=DIGEST))},
        outputs={'speech.transcribe@1':[dict(port='caption', kind='caption', media_type='application/json')]})
    return meta


def validate_timing(project_id, request, input_metadata, documents, *, resolve_artifact):
    """Pure compatibility seam; never starts a decoder or speech engine."""
    from ..contracts import ContractError
    if request.get('adapter_id') != ADAPTER_ID or request.get('operation') != 'speech.transcribe@1':
        raise ContractError('DEPENDENCY_UNAVAILABLE', 'No speech timing validator for this binding.')
    params = request['parameters']
    if params['diarize'] or params['language'] not in ('en', None) or params['granularity'] not in ('word', 'segment'):
        raise ContractError('UNSUPPORTED_FEATURE', 'Only non-diarized English source transcription is qualified.')
    inputs = request.get('inputs', {})
    audio = inputs.get('audio', {})
    records = input_metadata.get('audio', [])
    if (set(inputs) != {'audio'} or audio.get('kind') != 'artifact' or len(records) != 1
            or records[0].get('kind') != 'audio'
            or records[0].get('media_type') not in ('audio/wav', 'audio/x-wav', 'audio/flac')):
        raise ContractError('TIMING_INVALID', 'One existing pinned audio source required; no guessed/generated source timing.')
    pin = audio['artifact']
    check(pin, 'ArtifactRef')
    if any(records[0].get(key) != pin[key] for key in ('artifact_id', 'sha256')):
        raise ContractError('HASH_MISMATCH', 'Timing metadata differs from pinned source.')
    source = Path(resolve_artifact(pin))
    if source.is_symlink() or not source.is_file():
        raise ContractError('PATH_UNSAFE', 'Pinned audio must resolve to a regular file.')
    if 'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest() != pin['sha256']:
        raise ContractError('HASH_MISMATCH', 'Pinned audio changed before compilation.')
    # Source-domain transcription performs no project/frame-rate conversion.
    # Sample rate/duration are deliberately unmeasured here: the owned child
    # decodes the audio and finalization validates actual samples and bounds.
    return []


class LocalSpeechAdapter:
    """B06/B07 facade: the sole engine process is WorkerContext.run-owned.

    Evidence is core-published immutable ancillary JSON before finalization;
    final canonical caption bytes are published by B07, not by the engine.
    Unadopted ancillary evidence confers no content or acceptance authority.
    """
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, binding

    def validate_request(self, request):
        from ..contracts import ContractError, digest
        if request.get('operation') != 'speech.transcribe@1':
            raise ContractError('UNSUPPORTED_OPERATION', 'Only actual transcription is implemented.')
        expected = self.runtime.registry.binding(ADAPTER_ID, request['operation'],
            request['parameters'], request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Frozen speech binding differs.')
        options = request.get('binding_parameters')
        if not options or options['schema_id'] != MODEL_OPTIONS:
            raise ContractError('INVALID_ARGUMENT', 'Explicit existing-model options required.')
        model = Path(options['values']['model_path'])
        if not model.is_absolute() or not discover(model)['transcribe_available']:
            raise ContractError('CAPABILITY_UNAVAILABLE', 'Explicit local model/runtime unavailable.')
        if digest(model_identity(model)) != options['values']['model_files_sha256']:
            raise ContractError('HASH_MISMATCH', 'Selected model identity changed.')
        params = request['parameters']
        if params['diarize'] or params['language'] not in ('en', None):
            raise ContractError('UNSUPPORTED_FEATURE', 'Only non-diarized English transcription is qualified.')
        declaration = registration()['declaration']
        effects = declaration['effects']
        advertised = next(op['features'] for op in declaration['operations']
                          if op['operation'] == request['operation'])
        if (request.get('effects', effects) != effects
                or not set(request.get('required_features', [])).issubset(advertised)):
            raise ContractError('ADAPTER_INCOMPATIBLE', 'Effects/features differ from speech declaration.')
        return {'valid':True, 'effects':effects}

    def execute(self, request, attempt, context=None):
        import sys
        from datetime import datetime, timezone
        from ..contracts import ContractError, digest
        from ..captions import validate_imported_caption
        from .alternative import _relative, _result, file_digest
        if context is None or not callable(getattr(context, 'run', None)):
            raise ContractError('PERMISSION_DENIED', 'Owned WorkerContext.run is required.')
        started = False
        try:
            self.validate_request(request)
            if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
                raise ValueError('Authority or attempt identity missing')
            if set(request['inputs']) != {'audio'}:
                raise ValueError('Exactly one pinned audio input required')
            pin = request['inputs']['audio']
            check(pin, 'ArtifactRef')
            source = Path(self.runtime.artifact_path(request['project_id'], pin))
            if source.is_symlink() or not source.is_file() or file_digest(source) != pin['sha256']:
                raise ValueError('Immutable source audio differs')
            root = self.runtime.projects._filesystem().root.resolve()
            out = _relative(root, attempt['output_dir'])
            out.mkdir(parents=True, exist_ok=False)
            options = request['binding_parameters']['values']
            config = dict(audio_path=str(source), source_audio=pin,
                output_dir=str(out/'engine'), model_path=options['model_path'],
                model_files_sha256=options['model_files_sha256'], **request['parameters'])
            # Isolated interpreter imports this exact installed source tree only;
            # offline flags are set before faster_whisper/HF imports. No parent
            # environment/config changes, no ffprobe or nested engine child.
            code = ('import sys; sys.path.insert(0, '+repr(str(Path(__file__).resolve().parents[2]))+'); '
                    'from studio.adapters.speech import _owned_child; _owned_child()')
            deadline = datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00'))
            timeout = min(120, (deadline-datetime.now(timezone.utc)).total_seconds())
            if timeout <= 0:
                raise TimeoutError('Attempt deadline elapsed')
            started = True
            proc = context.run([sys.executable, '-I', '-c', code], input=canonical(config),
                timeout=timeout, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out/'engine.log').write_bytes(proc.stdout)
            if proc.returncode:
                raise RuntimeError('Owned ASR child failed; inspect engine.log, exit '+str(proc.returncode))
            if file_digest(source) != pin['sha256']:
                raise ValueError('Source audio changed during inference')
            from ..artifacts import read_bounded_json
            with (out/'engine/source-transcript.json').open('rb') as stream:
                evidence = read_bounded_json(stream)
            with (out/'engine/caption-draft.json').open('rb') as stream:
                draft = read_bounded_json(stream)
            if (evidence['source_audio'] != pin or draft['source_audio'] != pin
                    or digest(evidence['model_files']) != options['model_files_sha256']):
                raise ValueError('Engine evidence/source/model identity differs')
            # Core helper hashes real engine bytes. Its ancillary record is NOT
            # a B07 output nor a claim of derived-media/human provenance; the
            # retained payload and final job input/producer trace identify ASR.
            evidence_pin = self.runtime.artifacts.publish_json(request['project_id'], evidence, kind='report')
            caption = finalize_caption(draft, evidence_pin, [evidence_pin])
            validate_imported_caption(caption, source_sample_rate=evidence['sample_rate'],
                                      duration_samples=evidence['duration_samples'])
            target = out/'caption.json'
            target.write_bytes(canonical(caption))
            return _result([dict(port='caption', relative_path='caption.json',
                media_type='application/json', claimed_sha256=file_digest(target))], started=True)
        except Exception as exc:
            return _result(error=exc, started=started)


def _owned_child():
    """Private entrypoint invoked exclusively by the owned facade."""
    import os
    import sys
    from ..contracts import digest
    if not os.environ.get('MOTION_WORKER_TOKEN'):
        raise RuntimeError('Owned worker token required')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      OMP_NUM_THREADS='1')
    config = json.loads(sys.stdin.buffer.read(65537))
    expected = config.pop('model_files_sha256')
    if digest(model_identity(config['model_path'])) != expected:
        raise RuntimeError('Pinned model changed before engine initialization')
    transcribe(**config)

