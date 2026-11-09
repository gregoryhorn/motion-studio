"""B05 exact, pure timing and explicit temporal-transform validation.

No media execution, guessed source timestamps, or conversion receipts are made
here. Fractions are internal; signed rational diagnostics use RateSigned JSON.
"""
from __future__ import annotations

import copy
from fractions import Fraction
from math import ceil, floor

from .contracts import (D, MAX_INT, ContractError, domain, enum, integer, obj,
                        ref, validate)


def _timing(message):
    raise ContractError('TIMING_INVALID', message)


def _integer(value, minimum=0):
    validate(value, integer(minimum))
    return value


def rate_fraction(rate):
    """Accept precisely the existing positive, reduced Rate contract."""
    validate(rate, D['Rate'])
    domain(rate)
    return Fraction(rate['num'], rate['den'])


def _signed(value):
    return {'num': value.numerator, 'den': value.denominator}


def _seconds(value):
    # Never let Fraction(float) introduce binary approximation into timing.
    if type(value) is not int and not isinstance(value, Fraction):
        _timing('Seconds must be an integer or exact Fraction, not a float.')
    return Fraction(value)


def frame_seconds(frame, rate):
    return Fraction(_integer(frame), 1) / rate_fraction(rate)


def _nearest(position, target_rate):
    index = round(position * target_rate)  # Fraction.__round__: ties to even.
    _integer(index)
    return {'index': index, 'rounding': 'nearest_even',
            'error_seconds': _signed(Fraction(index, target_rate) - position)}


def frame_to_frame(frame, source_rate, output_rate):
    """Derived output frame only: preserve original frame/rate in source state."""
    return _nearest(frame_seconds(frame, source_rate), rate_fraction(output_rate))


def frame_to_sample(frame, rate, sample_rate):
    """Nearest sample with signed (quantized minus exact) seconds error."""
    return _nearest(frame_seconds(frame, rate), _integer(sample_rate, 1))


def sample_to_sample(sample, source_rate, output_rate):
    return _nearest(Fraction(_integer(sample), _integer(source_rate, 1)),
                    _integer(output_rate, 1))


def frame_sample_coverage(start_frame, end_frame, rate, sample_rate):
    """Cover a nonempty half-open frame interval; do not round endpoints nearest."""
    start = frame_seconds(start_frame, rate)
    end = frame_seconds(end_frame, rate)
    if end <= start:
        _timing('Frame range must be nonempty and half-open.')
    sample_rate = _integer(sample_rate, 1)
    first, last = floor(start * sample_rate), ceil(end * sample_rate)
    _integer(first)
    _integer(last)
    return {'start_sample': first, 'end_sample': last, 'rounding': 'coverage',
            'start_error_seconds': _signed(Fraction(first, sample_rate) - start),
            'end_error_seconds': _signed(Fraction(last, sample_rate) - end)}


def source_tick_seconds(pts, time_base, start_pts, duration_ticks=None, *, allow_end=False):
    """Raw stream PTS -> source-relative seconds, preserving negative raw PTS.

    start_pts must be known. A point is in [start_pts,start_pts+duration_ticks);
    allow_end is solely for an interval's exclusive endpoint. A missing duration
    does not establish an upper bound; callers requiring it must reject unknowns.
    """
    _integer(pts, -MAX_INT)
    if start_pts is None:
        _timing('Unknown start_pts cannot define source-relative timing.')
    _integer(start_pts, -MAX_INT)
    base = rate_fraction(time_base)
    relative = pts - start_pts
    if relative < 0:
        _timing('Source point precedes first presentation instant.')
    if duration_ticks is not None:
        _integer(duration_ticks)
        if relative > duration_ticks or (relative == duration_ticks and not allow_end):
            _timing('Source point is outside half-open stream bounds.')
    return relative * base


def validate_timepoint(point, project_rate, sample_rate):
    validate(point, D['TimePoint'])
    domain(point)
    rate_fraction(project_rate)
    _integer(sample_rate, 1)
    if point['domain'] != 'source_tick' and point['index'] < 0:
        _timing('Only raw source ticks may have negative positions.')
    if point['domain'] == 'frame' and point['rate'] != project_rate:
        _timing('Canonical frame time points use the fixed project rate; preserve raw source PTS as ticks.')
    if point['domain'] == 'sample' and point['rate']['den'] != 1:
        _timing('Sample timing requires an integer actual sample rate.')
    if point['origin'] == 'project':
        expected = project_rate if point['domain'] == 'frame' else {'num': sample_rate, 'den': 1}
        if point['domain'] == 'source_tick' or point['rate'] != expected:
            _timing('Project time point rate/domain differs from fixed settings.')
    return None


def validate_timeline(timeline, project_rate, sample_rate, *, scenes=None):
    """Additional B05 validation for a resolved canonical Timeline.

    Parent storage retains ownership, overlap/graph checks and caption handling.
    Optional scenes maps scene IDs to canonical Scene values for trim-aware bounds.
    Source media bounds require probe facts and are checked with source_tick_seconds
    and map_source_range; absence of probe facts never proves media compatibility.
    """
    validate(timeline, D['Timeline'])
    domain(timeline)
    rate = rate_fraction(project_rate)
    _integer(sample_rate, 1)
    for track in timeline['tracks']:
        for item in track['items']:
            if not item['start_frame'] < item['end_frame'] <= timeline['duration_frames']:
                _timing('Timeline item must be nonempty and within output duration.')
            point = item.get('source_in')
            if point is not None:
                validate_timepoint(point, project_rate, sample_rate)
                if item['subject']['kind'] == 'artifact' and point['origin'] == 'source':
                    if point['source_artifact'] != item['subject']['artifact']:
                        _timing('Source trim must pin the placed source artifact.')
            if scenes is not None and item['subject']['kind'] == 'scene':
                scene = scenes.get(item['subject']['scene_id'])
                if scene is None:
                    raise ContractError('INVALID_GRAPH', 'Placed scene is unresolved.')
                offset = Fraction(0)
                if point is not None:
                    if point['origin'] != 'project':
                        _timing('Canonical scene trim requires project-domain timing.')
                    offset = Fraction(point['index']) / rate_fraction(point['rate'])
                length = Fraction(item['end_frame'] - item['start_frame']) / rate
                if offset + length > Fraction(_integer(scene['duration_frames'], 1)) / rate:
                    _timing('Trim plus placed duration exceeds scene bounds.')
    return None


_TEMPORAL_SPECS = {
    'rate_conform': obj({'rate': ref('Rate'), 'method': enum('drop_duplicate', 'optical_flow')}),
    'sample_conform': obj({'sample_rate': integer(1)}),
    'retime': obj({'speed': ref('Rate'), 'preserve_audio_pitch': {'type': 'boolean'}}),
}


def validate_temporal_transform(parameters):
    """Validate only the documented temporal media.transform@1 parameters.

    This is a plan input, never an executed transform or ConversionRecord.
    Adapter feature support (optical flow/pitch) is negotiated in B06.
    """
    validate(parameters, {'oneOf': [obj({'kind': {'const': kind}, 'spec': spec})
                                   for kind, spec in _TEMPORAL_SPECS.items()]})
    domain(parameters)
    return copy.deepcopy(parameters)


def require_temporal_compatibility(stream, vfr, project_rate, sample_rate, transforms=()):
    """Require explicit conform parameters; never insert a conversion silently.

    stream is a StreamFacts entry, vfr is its containing ProbeReceipt's fact.
    Returned list is validated requested parameters, not a graph/job/receipt.
    Unknown video cadence needs explicit conform even if nominal rates match.
    Unknown audio sample rate is not inferred from nominal/video rate.
    """
    rate_fraction(project_rate)
    _integer(sample_rate, 1)
    validate(vfr, enum('yes', 'no', 'unknown'))
    if type(stream) is not dict or stream.get('type') not in ('video', 'audio'):
        _timing('Temporal compatibility requires a video or audio StreamFacts entry.')
    operations = [validate_temporal_transform(op) for op in transforms]
    kinds = [op['kind'] for op in operations]
    if len(set(kinds)) != len(kinds):
        _timing('Duplicate temporal transforms have ambiguous timing.')
    by_kind = {op['kind']: op['spec'] for op in operations}
    if stream['type'] == 'video':
        if 'sample_conform' in by_kind:
            _timing('Sample conform requires an audio stream.')
        source_rate = stream.get('rate')
        if source_rate is not None:
            rate_fraction(source_rate)
        conform = by_kind.get('rate_conform')
        if conform is not None and conform['rate'] != project_rate:
            _timing('Explicit conform rate differs from target rate.')
        if (vfr != 'no' or source_rate != project_rate) and conform is None:
            _timing('VFR/unknown cadence or differing rate requires explicit rate_conform.')
    else:
        if 'rate_conform' in by_kind:
            _timing('Frame-rate conform requires a video stream.')
        actual = stream.get('sample_rate')
        if actual is None:
            _timing('Unknown actual source sample rate blocks sample mapping.')
        _integer(actual, 1)
        conform = by_kind.get('sample_conform')
        if conform is not None and conform['sample_rate'] != sample_rate:
            _timing('Explicit sample conform differs from target sample rate.')
        if actual != sample_rate and conform is None:
            _timing('Differing actual sample rate requires explicit sample_conform.')
    return operations


def map_source_range(start, end, *, source_start, source_end, source_rate,
                     output_start, output_end, speed):
    """Clip source samples to a bounded span and map exactly to output seconds.

    speed uses the retime Rate (source seconds / output seconds); unity must also
    be explicit. Caller supplies pinned span bounds, not invented source duration.
    A disjoint/touching cue returns None; exclusive ends remain exclusive.
    No frame rounding occurs here, including when output rate differs.
    """
    for value in (start, end, source_start, source_end):
        _integer(value)
    _integer(source_rate, 1)
    first, last = _seconds(output_start), _seconds(output_end)
    factor = rate_fraction(speed)
    if end <= start or source_end <= source_start or first < 0 or last <= first:
        _timing('Source and output intervals must be nonempty, nonnegative and half-open.')
    if last - first != Fraction(source_end - source_start, source_rate) / factor:
        _timing('Source/output bounds disagree with explicit speed mapping.')
    a, b = max(start, source_start), min(end, source_end)
    if a >= b:
        return None
    return (first + Fraction(a - source_start, source_rate) / factor,
            first + Fraction(b - source_start, source_rate) / factor)
