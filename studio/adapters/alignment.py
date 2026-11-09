"""Owned corrected-text CTC forced alignment using optional offline WhisperX.

Discovery reads metadata/files only. Execution loads one explicitly pinned local
HuggingFace Wav2Vec2 CTC model; there is no ASR, prompt, model selection, network
fallback, interpolated word time, or engine subprocess outside WorkerContext.run.
"""
from __future__ import annotations
import copy
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import subprocess
import unicodedata
from ..captions import check, fail, validate_caption, validate_imported_caption
from ..contracts import canonical, digest, ContractError

ADAPTER_ID = 'local.whisperx-align'
VERSION = '1.0'
MODEL_OPTIONS = 'motion/v1/local-whisperx-align/existing-model'
REQUEST_SCHEMA = 'motion/v1/local-whisperx-align/align-request'
RESULT_SCHEMA = 'motion/v1/local-whisperx-align/align-result'
REQUIRED_FILES = ('config.json', 'preprocessor_config.json', 'tokenizer_config.json', 'vocab.json')


def _model_files(model_path):
    root = Path(model_path)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        fail('Aligner model_path must be an existing absolute regular directory.', 'CAPABILITY_UNAVAILABLE')
    files = sorted(p for p in root.rglob('*') if p.is_file())
    if any(p.is_symlink() for p in root.rglob('*')):
        fail('Materialize pinned model files; symlinked model trees are unsupported.', 'PATH_UNSAFE')
    names = {p.name for p in files if p.stat().st_size > 0}
    weights = any(name in names for name in ('model.safetensors', 'pytorch_model.bin'))
    # Sharded weights are valid only with their index and every referenced shard.
    for name in ('model.safetensors.index.json', 'pytorch_model.bin.index.json'):
        index = root/name
        if index.is_file():
            shards = set(json.loads(index.read_text())['weight_map'].values())
            weights = weights or bool(shards) and all(
                Path(s).name == s and (root/s).is_file() and (root/s).stat().st_size > 0 for s in shards)
    if not set(REQUIRED_FILES).issubset(names) or not weights:
        fail('Pinned local Wav2Vec2 CTC config/tokenizer/processor/weights are incomplete.', 'CAPABILITY_UNAVAILABLE')
    config = json.loads((root/'config.json').read_text())
    if config.get('model_type') != 'wav2vec2' or 'Wav2Vec2ForCTC' not in config.get('architectures', []):
        fail('WhisperX binding requires an explicit HuggingFace Wav2Vec2ForCTC model.', 'UNSUPPORTED_FEATURE')
    return root, files


def discover(model_path=None):
    """No optional imports, model loads, cache traversal, decodes or downloads."""
    try:
        version = importlib.metadata.version('whisperx')
    except importlib.metadata.PackageNotFoundError:
        version = None
    result = dict(adapter_id=ADAPTER_ID, implementation_version=VERSION,
                  engine_version=version, installed=version is not None,
                  model_path=str(model_path) if model_path is not None else None,
                  model_files_present=False, align_available=False, network=False,
                  blocker='Select an installed WhisperX runtime and explicit local Wav2Vec2ForCTC directory.')
    if model_path is not None:
        try:
            _model_files(model_path)
            result.update(model_files_present=True, align_available=version is not None,
                          blocker=None if version else 'Optional WhisperX package is not installed.')
        except (ContractError, OSError, ValueError, KeyError) as exc:
            result['blocker'] = str(exc)
    return result


def model_identity(model_path):
    root, files = _model_files(model_path)
    result = []
    for path in files:
        h = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024*1024):
                h.update(chunk)
        result.append(dict(name=path.relative_to(root).as_posix(), size_bytes=path.stat().st_size,
                           sha256='sha256:'+h.hexdigest()))
    return result


def registration():
    """Complete metadata-only ABI for parent registry/factory/resolver wiring."""
    from .speech import registration as speech_registration
    from ..capabilities import PARAMS, expanded
    from ..contracts import obj, TEXT, DIGEST
    meta = speech_registration()
    decl = meta['declaration']
    decl.update(adapter_id=ADAPTER_ID, implementation_version=VERSION,
                label='Offline WhisperX corrected-text forced alignment')
    op = decl['operations'][0]
    op.update(operation='speech.align@1', request_schema=REQUEST_SCHEMA,
              result_schema=RESULT_SCHEMA, features=['speech.words'], default_timeout_seconds=120)
    # Language model compatibility is enforced by explicit language + local model;
    # empty language constraints mean no registry-level language whitelist.
    op['constraints'].update(languages=[], timing='word',
                            media_types=['audio/wav', 'audio/x-wav', 'audio/flac', 'application/json'])
    decl['dependencies'] = [dict(name='whisperx', kind='library', version_constraint=None, required=True)]
    result_schema = next(value for key, value in meta['schemas'].items() if key.endswith('-result'))
    meta.update(implementation_sha256=digest(dict(
        alignment='sha256:'+hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        speech='sha256:'+hashlib.sha256(Path(__file__).with_name('speech.py').read_bytes()).hexdigest())),
        schemas={REQUEST_SCHEMA: expanded(PARAMS['speech.align@1']), RESULT_SCHEMA: result_schema,
                 MODEL_OPTIONS: obj(dict(model_path=TEXT, model_files_sha256=DIGEST, language=TEXT))},
        outputs={'speech.align@1': [dict(port='caption', kind='caption', media_type='application/json')]})
    return meta


def _json_safe(value):
    """Canonical evidence contains decimal strings, never NaN/JSON floats."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else None
    if value is None or isinstance(value, (str, bool, int)):
        return value
    return _json_safe(value.item()) if hasattr(value, 'item') else str(value)


def _decode_audio(path):
    """Decode once in the owned child; retain original decoded sample domain.

    PyAV resampling is explicit, zero-origin mono 16k for CTC only. Source
    samples and canonical caption times always use the original source rate.
    """
    import av
    import numpy as np
    arrays = []
    with av.open(str(path)) as container:
        streams = list(container.streams.audio)
        if len(streams) != 1:
            fail('Forced alignment requires exactly one audio stream.', 'UNSUPPORTED_FEATURE')
        rate = int(streams[0].codec_context.sample_rate)
        resampler = av.AudioResampler(format='flt', layout='mono', rate=16000)
        samples = 0
        for frame in container.decode(audio=0):
            if frame.sample_rate != rate:
                fail('Variable source sample rates require an explicit conform.', 'UNSUPPORTED_FEATURE')
            samples += frame.samples
            # Establish the same source origin as the canonical decoded transcript,
            # not container timestamp zero (which may be nonzero or discontinuous).
            frame.pts = None
            for converted in resampler.resample(frame):
                arrays.append(converted.to_ndarray().reshape(-1))
        for converted in resampler.resample(None):
            arrays.append(converted.to_ndarray().reshape(-1))
    if not samples or not arrays:
        fail('Empty alignment audio.', 'INVALID_ARGUMENT')
    audio = np.concatenate(arrays).astype(np.float32, copy=False)
    receipt = dict(source_sample_rate=rate, source_duration_samples=samples,
                   target_sample_rate=16000, target_duration_samples=int(audio.size),
                   channel_layout='mono', format='float32', engine='PyAV AudioResampler',
                   origin='first decoded source sample', source_timing_retained=True)
    return audio, rate, samples, receipt


def _sample(seconds, rate, conversions):
    value = Decimal(str(seconds))
    if not value.is_finite():
        return None
    index = int((value*rate).to_integral_value(rounding=ROUND_HALF_EVEN))
    conversions.append(dict(seconds=str(value), sample=index, sample_rate=rate,
                            rounding='nearest_even', error_seconds=str(Decimal(index)/rate-value)))
    return index


def _convert_segment(segment, aligned, rate, conversions, model_dictionary):
    """Use actual char alignments only; never interpolate unsupported words.

    WhisperX may sentence-split output; map the exact non-whitespace character
    sequence back to corrected source character offsets. On any mismatch keep
    the corrected text and mark all its tokens untimed rather than fuzzy-match.
    """
    text = segment['text']
    chars = [char for part in aligned.get('segments', []) for char in part.get('chars', [])
             if not char.get('char', '').isspace()]
    offsets = [index for index, char in enumerate(text) if not char.isspace()]
    matching = ''.join(c.get('char', '') for c in chars) == ''.join(text[i] for i in offsets)
    by_offset = dict(zip(offsets, chars)) if matching else {}
    records, words = [], []
    cursor = segment['start_sample']
    for index, match in enumerate(re.finditer(r'\S+', text)):
        required = [i for i in range(match.start(), match.end())
                    if unicodedata.category(text[i])[0] not in ('P', 'Z', 'C')]
        selected = [by_offset.get(i, {}) for i in required]
        supported = all(text[i].lower() in model_dictionary for i in required)
        valid = supported and bool(selected) and all(c.get('start') is not None and c.get('end') is not None for c in selected)
        start = end = None
        reason = 'unsupported_or_unaligned_characters' if matching else 'character_sequence_mismatch'
        if not supported:
            # WhisperX can assign a high-scoring wildcard to unknown glyphs.
            # Those are not observed model-character timing, even without interpolation.
            reason = 'unsupported_model_characters'
        confidence = None
        if valid:
            start = _sample(min(Decimal(str(c['start'])) for c in selected), rate, conversions)
            end = _sample(max(Decimal(str(c['end'])) for c in selected), rate, conversions)
            valid = (start is not None and end is not None and cursor <= start < end <= segment['end_sample'])
            if valid and start is not None and end is not None:
                scores = [Decimal(str(c['score'])) for c in selected if c.get('score') is not None]
                if scores and all(s.is_finite() and 0 <= s <= 1 for s in scores):
                    confidence = str(min(scores))
                words.append(dict(word_id=f'wa{index}', text=match.group(),
                                  start_sample=start, end_sample=end, confidence=confidence))
                cursor = end
                reason = None if confidence is not None else 'confidence_unreported'
            else:
                reason = 'nonpositive_overlapping_or_out_of_source_window_timing'
        records.append(dict(text=match.group(), char_start=match.start(), char_end=match.end(),
                            start_sample=start if valid else None, end_sample=end if valid else None,
                            confidence=confidence if valid else None, untimed=not valid, uncertainty=reason))
    out = copy.deepcopy(segment)
    out['confidence'] = None
    out['words'] = words
    complete = bool(records) and all(not record['untimed'] for record in records)
    if complete:
        out['start_sample'], out['end_sample'] = words[0]['start_sample'], words[-1]['end_sample']
    # Partial segments retain old segment windows solely for review. They must
    # never be represented as successfully aligned or silently renderable.
    return out, records, complete


def _sentence_tokenizer(language):
    """Require local Punkt data before WhisperX can invoke its implicit downloader."""
    import nltk  # type: ignore[import-not-found]  # Optional execution environment only.
    from nltk.tokenize import PunktTokenizer  # type: ignore[import-not-found]
    from whisperx.alignment import PUNKT_LANGUAGES  # type: ignore[import-not-found]
    selected = PUNKT_LANGUAGES.get(language, 'english')
    try:
        PunktTokenizer(selected)
        root = Path(str(nltk.data.find('tokenizers/punkt_tab/'+selected+'/')))
    except LookupError:
        fail('Prepare local NLTK punkt_tab data under NLTK_DATA before offline alignment.', 'CAPABILITY_UNAVAILABLE')
    files = []
    for name in ('abbrev_types.txt', 'collocations.tab', 'ortho_context.tab', 'sent_starters.txt'):
        path = root/name
        if not path.is_file() or path.is_symlink():
            fail('Materialize regular local Punkt data files before alignment.', 'CAPABILITY_UNAVAILABLE')
        files.append(dict(name=name, sha256='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()))
    def refuse_download(*args, **kwargs):
        fail('Implicit NLTK downloads are forbidden inside the alignment worker.', 'CAPABILITY_UNAVAILABLE')
    nltk.download = refuse_download
    return dict(engine='nltk.punkt_tab', engine_version=importlib.metadata.version('nltk'),
                language=selected, files=files, downloads='blocked')


def align(audio_path, source_audio, caption, output_dir, *, model_path, language, granularity):
    """Actual corrected-text alignment, invoked only by _owned_child.

    Caller publishes timing evidence before adopting caption-draft. Original
    source_transcript, corrections, source pin, IDs and exact text are retained.
    """
    import os
    if not os.environ.get('MOTION_WORKER_TOKEN'):
        fail('Forced alignment requires the owned worker child.', 'PERMISSION_DENIED')
    validate_caption(caption)
    if caption['source_audio'] != source_audio or caption['language'] != language:
        fail('Caption audio/language differs from explicit alignment selection.', 'HASH_MISMATCH')
    if granularity not in ('segment', 'word') or caption['silence'] or not caption['segments']:
        fail('Alignment requires corrected spoken segments and a supported granularity.', 'INVALID_ARGUMENT')
    if not discover(model_path)['align_available']:
        fail(discover(model_path)['blocker'], 'CAPABILITY_UNAVAILABLE')
    path = Path(audio_path)
    if path.is_symlink() or not path.is_file():
        fail('Alignment input must be staged regular audio.', 'PATH_UNSAFE')
    if 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest() != source_audio['sha256']:
        fail('Alignment source audio changed.', 'HASH_MISMATCH')
    try:
        from whisperx.alignment import load_align_model, align as force_align  # type: ignore[import-not-found]
        sentence_tokenizer = _sentence_tokenizer(language)
        audio, rate, samples, resampling = _decode_audio(path)
    except (ImportError, OSError) as exc:
        fail('Optional local WhisperX/PyAV/torch alignment dependencies unavailable: '+str(exc), 'CAPABILITY_UNAVAILABLE')
    validate_imported_caption(caption, source_sample_rate=rate, duration_samples=samples)
    model, metadata = load_align_model(language_code=language, device='cpu', model_name=str(Path(model_path)),
                                      model_cache_only=True)
    draft = copy.deepcopy(caption)
    draft['revision'] += 1
    draft['granularity'] = granularity
    draft['timing_decisions'] = []
    segments, retained, conversions = [], [], []
    complete = True
    for segment in caption['segments']:
        # Existing segment windows are the explicit search boundaries, never ASR
        # prompts. Float conversion is retained along with source sample bounds.
        start, end = segment['start_sample']/rate, segment['end_sample']/rate
        requested = dict(start=start, end=end, text=segment['text'])
        result = force_align([requested], model, metadata, audio, 'cpu',
                             interpolate_method='ignore', return_char_alignments=True, print_progress=False)
        converted, words, aligned_ok = _convert_segment(segment, _json_safe(result), rate, conversions,
                                                       metadata['dictionary'])
        if granularity == 'segment':
            converted['words'] = []
        segments.append(converted)
        complete = complete and aligned_ok
        retained.append(dict(segment_id=segment['segment_id'], corrected_text=segment['text'],
                             search_window_samples=dict(start=segment['start_sample'], end=segment['end_sample']),
                             requested_seconds=_json_safe(requested), words=words, complete=aligned_ok,
                             raw_alignment=_json_safe(result)))
    if _sentence_tokenizer(language) != sentence_tokenizer:
        fail('Sentence tokenizer data changed during alignment.', 'HASH_MISMATCH')
    draft.update(segments=segments, timing_state='aligned' if complete else 'review_needed')
    validate_imported_caption(draft, source_sample_rate=rate, duration_samples=samples)
    evidence = dict(schema='motion/v1/forced-alignment-evidence', adapter_id=ADAPTER_ID,
                    implementation_version=VERSION, engine_version=importlib.metadata.version('whisperx'),
                    source_audio=source_audio, input_caption_sha256=digest(caption),
                    original_source_transcript=caption['source_transcript'], corrected_caption=caption,
                    model_files=model_identity(model_path), sentence_tokenizer=sentence_tokenizer,
                    language=language, sample_rate=rate,
                    duration_samples=samples, resampling=resampling, segments=retained,
                    sample_conversions=conversions, complete=complete,
                    controls=dict(device='cpu', network=False, interpolation='ignore',
                                  search_domain='existing source segment windows', confidence_threshold=None))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    evidence_path = out/'alignment-evidence.json'
    evidence_path.write_bytes(canonical(evidence))
    draft_path = out/'caption-draft.json'
    draft_path.write_bytes(canonical(draft))
    return dict(caption_draft=draft, timing_evidence_path=str(evidence_path), caption_draft_path=str(draft_path))


def _caption_value(data):
    """Accept canonical caption bytes or their immutable project document."""
    if data.get('schema') == 'motion/v1/document':
        from ..project import ProjectStore
        from ..contracts import validate
        validate(data, ProjectStore._document_schema('caption'))
        if data['kind'] != 'caption':
            fail('Alignment requires a caption document.', 'INVALID_ARGUMENT')
        data = data['value']
    return validate_caption(data)


def validate_timing(project_id, request, input_metadata, documents, *, resolve_artifact):
    """Pure compile-time input compatibility; no optional imports or decoding."""
    if request.get('adapter_id') != ADAPTER_ID or request.get('operation') != 'speech.align@1':
        fail('No alignment timing validator for this binding.', 'DEPENDENCY_UNAVAILABLE')
    inputs = request.get('inputs', {})
    if set(inputs) != {'audio', 'caption'} or inputs['audio'].get('kind') != 'artifact':
        fail('Explicit pinned audio and corrected caption inputs required.', 'TIMING_INVALID')
    audio = inputs['audio']['artifact']
    check(audio, 'ArtifactRef')
    records = input_metadata.get('audio', [])
    if len(records) != 1 or records[0].get('kind') != 'audio' or any(
            records[0].get(key) != audio[key] for key in ('artifact_id', 'sha256')):
        fail('Alignment source metadata differs from pinned audio.', 'HASH_MISMATCH')
    path = Path(resolve_artifact(audio))
    if path.is_symlink() or not path.is_file() or 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest() != audio['sha256']:
        fail('Alignment audio bytes changed.', 'HASH_MISMATCH')
    selected = inputs['caption']
    if selected.get('kind') == 'document':
        pin = selected['document']
        check(pin, 'DocumentRef')
        document = documents.get(('caption', pin['id']))
        if document is None or pin['kind'] != 'caption' or digest(document) != pin['sha256'] or document['revision'] != pin['revision']:
            fail('Alignment requires the exact corrected caption document revision.', 'HASH_MISMATCH')
        caption = _caption_value(document)
    elif selected.get('kind') == 'artifact':
        from ..artifacts import read_bounded_json
        pin = selected['artifact']
        check(pin, 'ArtifactRef')
        source = Path(resolve_artifact(pin))
        if source.is_symlink() or not source.is_file() or 'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest() != pin['sha256']:
            fail('Corrected caption bytes changed.', 'HASH_MISMATCH')
        with source.open('rb') as stream:
            caption = _caption_value(read_bounded_json(stream))
    else:
        fail('Alignment requires an existing corrected caption, not a generated script.', 'TIMING_INVALID')
    params = request['parameters']
    if (caption['source_audio'] != audio or caption['language'] != params['language']
            or caption['silence'] or not caption['segments']):
        fail('Corrected caption source/language/spoken-segment closure differs.', 'TIMING_INVALID')
    return []


class LocalAlignmentAdapter:
    """B06/B07 facade. Sole inference process is owned by WorkerContext.run."""
    owned_local = True

    def __init__(self, runtime, binding):
        self.runtime, self.binding = runtime, binding

    def validate_request(self, request):
        if request.get('operation') != 'speech.align@1':
            fail('Only corrected-text forced alignment is implemented.', 'UNSUPPORTED_OPERATION')
        expected = self.runtime.registry.binding(ADAPTER_ID, request['operation'],
                                                request['parameters'], request.get('binding_parameters'))
        if self.binding != expected or request.get('binding') != expected:
            fail('Frozen alignment binding differs.', 'ADAPTER_INCOMPATIBLE')
        options = request.get('binding_parameters')
        if not options or options['schema_id'] != MODEL_OPTIONS:
            fail('Explicit pinned existing aligner-model options required.', 'INVALID_ARGUMENT')
        values = options['values']
        found = discover(values['model_path'])
        if not found['align_available']:
            fail(found['blocker'], 'CAPABILITY_UNAVAILABLE')
        if digest(model_identity(values['model_path'])) != values['model_files_sha256']:
            fail('Selected aligner model identity changed.', 'HASH_MISMATCH')
        if request['parameters']['language'] != values['language']:
            fail('Requested language differs from pinned model-language selection.', 'ADAPTER_INCOMPATIBLE')
        decl = registration()['declaration']
        if request.get('effects', decl['effects']) != decl['effects'] or not set(
                request.get('required_features', [])).issubset(decl['operations'][0]['features']):
            fail('Effects/features differ from alignment declaration.', 'ADAPTER_INCOMPATIBLE')
        return dict(valid=True, effects=decl['effects'])

    def execute(self, request, attempt, context=None):
        import sys
        from datetime import datetime, timezone
        from .alternative import _relative, _result, file_digest
        from ..artifacts import read_bounded_json
        if context is None or not callable(getattr(context, 'run', None)):
            fail('Owned WorkerContext.run is required for alignment.', 'PERMISSION_DENIED')
        started = False
        try:
            self.validate_request(request)
            if attempt['node_id'] != request['node_id'] or not attempt['authority_evidence_ref']:
                fail('Alignment authority/attempt identity missing.', 'PERMISSION_DENIED')
            if set(request['inputs']) != {'audio', 'caption'}:
                fail('Exactly audio and corrected caption inputs required.')
            pins = request['inputs']
            paths = {}
            for name, pin in pins.items():
                check(pin, 'ArtifactRef')
                path = Path(self.runtime.artifact_path(request['project_id'], pin))
                if path.is_symlink() or not path.is_file() or file_digest(path) != pin['sha256']:
                    fail('Immutable alignment input differs: '+name, 'HASH_MISMATCH')
                paths[name] = path
            with paths['caption'].open('rb') as stream:
                caption = _caption_value(read_bounded_json(stream))
            if caption['source_audio'] != pins['audio'] or caption['language'] != request['parameters']['language']:
                fail('Corrected caption/source/language closure differs.', 'HASH_MISMATCH')
            root = self.runtime.projects._filesystem().root.resolve()
            from .ffmpeg import _output_dir
            expected_dir = (self.runtime.projects._base(request['project_id']) + '/jobs/' +
                            attempt['job_id'] + '/attempts/' + attempt['attempt_id'])
            if attempt['output_dir'] != expected_dir:
                fail('Alignment output differs from exact owning attempt.', 'PATH_UNSAFE')
            out = _output_dir(root, attempt['output_dir'])
            values = request['binding_parameters']['values']
            config = dict(audio_path=str(paths['audio']), source_audio=pins['audio'],
                          caption_path=str(paths['caption']), caption_sha256=pins['caption']['sha256'],
                          output_dir=str(out/'engine'), model_path=values['model_path'],
                          model_files_sha256=values['model_files_sha256'], **request['parameters'])
            code = ('import sys; sys.path.insert(0, '+repr(str(Path(__file__).resolve().parents[2]))+'); '
                    'from studio.adapters.alignment import _owned_child; _owned_child()')
            deadline = datetime.fromisoformat(attempt['deadline_at'].replace('Z', '+00:00'))
            timeout = min(120, (deadline-datetime.now(timezone.utc)).total_seconds())
            if timeout <= 0:
                raise TimeoutError('Alignment attempt deadline elapsed')
            started = True
            process = context.run([sys.executable, '-I', '-c', code], input=canonical(config),
                                  timeout=timeout, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out/'engine.log').write_bytes(process.stdout)
            if process.returncode:
                detail = process.stdout.decode('utf-8', 'replace')[-1200:]
                fail('Owned forced aligner failed; inspect engine.log (exit '+str(process.returncode)+'): '+detail, 'ADAPTER_FAILED')
            for name, path in paths.items():
                if file_digest(path) != pins[name]['sha256']:
                    fail('Alignment input changed during inference.', 'HASH_MISMATCH')
            with (out/'engine/alignment-evidence.json').open('rb') as stream:
                evidence = read_bounded_json(stream)
            with (out/'engine/caption-draft.json').open('rb') as stream:
                draft = read_bounded_json(stream)
            if (evidence['source_audio'] != pins['audio'] or evidence['input_caption_sha256'] != digest(caption)
                    or evidence['corrected_caption'] != caption
                    or digest(evidence['model_files']) != values['model_files_sha256']
                    or draft['source_audio'] != caption['source_audio']
                    or draft['source_transcript'] != caption['source_transcript']
                    or draft['corrections'] != caption['corrections']
                    or [(s['segment_id'], s['text']) for s in draft['segments']] !=
                       [(s['segment_id'], s['text']) for s in caption['segments']]):
                fail('Alignment evidence/corrected text/model closure differs.', 'HASH_MISMATCH')
            evidence_pin = self.runtime.artifacts.publish_json(request['project_id'], evidence, kind='report')
            draft['timing_evidence'] = [*caption['timing_evidence'], evidence_pin]
            validate_imported_caption(draft, source_sample_rate=evidence['sample_rate'],
                                      duration_samples=evidence['duration_samples'])
            target = out/'caption.json'
            target.write_bytes(canonical(draft))
            return _result([dict(port='caption', relative_path='caption.json', media_type='application/json',
                                 claimed_sha256=file_digest(target))], started=True)
        except Exception as exc:
            return _result(error=exc, started=started)


def _owned_child():
    import os
    import sys
    if not os.environ.get('MOTION_WORKER_TOKEN'):
        raise RuntimeError('Owned worker token required')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      OMP_NUM_THREADS='1', TOKENIZERS_PARALLELISM='false')
    config = json.loads(sys.stdin.buffer.read(65537))
    expected = config.pop('model_files_sha256')
    if digest(model_identity(config['model_path'])) != expected:
        fail('Aligner model changed before initialization.', 'HASH_MISMATCH')
    path = Path(config.pop('caption_path'))
    expected_caption = config.pop('caption_sha256')
    if path.is_symlink() or not path.is_file() or 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest() != expected_caption:
        fail('Corrected caption changed before alignment.', 'HASH_MISMATCH')
    from ..artifacts import read_bounded_json
    with path.open('rb') as stream:
        config['caption'] = _caption_value(read_bounded_json(stream))
    align(**config)
