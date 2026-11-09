"""Exact production cadence and shared bounded geometry, without engine imports."""
from fractions import Fraction

SUPPORTED_RATES = ((24000, 1001), (24, 1), (25, 1), (30000, 1001),
                   (30, 1), (50, 1), (60000, 1001), (60, 1))
MAX_SECONDS = 3600


def fraction(value):
    result = Fraction(value['num'], value['den']) if isinstance(value, dict) else Fraction(value)
    if result not in {Fraction(n, d) for n, d in SUPPORTED_RATES}:
        raise ValueError('Unsupported cadence; select an explicit supported production rate')
    return result


def text(value):
    result = fraction(value)
    return f'{result.numerator}/{result.denominator}'


def bounds(width, height, frames, rate=None):
    from .limits import MAX_WIDTH, MAX_HEIGHT, MAX_FRAMES
    cadence = fraction(rate or {'num': 30, 'den': 1})
    if (not all(type(v) is int for v in (width, height, frames))
            or not 0 < width <= MAX_WIDTH or not 0 < height <= MAX_HEIGHT
            or width % 2 or height % 2 or not 0 < frames <= MAX_FRAMES
            or Fraction(frames, 1) / cadence > MAX_SECONDS):
        raise ValueError('Canvas/range exceeds even 4096px axes, 216000 frames or one-hour bounds')


def samples(frames, rate, sample_rate):
    result = Fraction(frames * sample_rate, 1) / fraction(rate)
    if result.denominator != 1:
        raise ValueError('Frame endpoint falls between audio samples; choose a sample-exact endpoint')
    return int(result)


def observed(stream):
    """Nominal rational cadence, with explicit Matroska rounding declaration.

    Matroska's integer-nanosecond DefaultDuration may make ffprobe report an
    approximation for 60000/1001. Do not round arbitrary source rates silently.
    Tagged FFV1 additionally requires full timestamp verification at collection.
    """
    actual = Fraction(stream['r_frame_rate'])
    try:
        return fraction(actual)
    except ValueError:
        tags = {k.lower(): v for k,v in stream.get('tags',{}).items()}
        selected = fraction(tags['motion_rate'])
        if stream.get('codec_name') != 'ffv1' or abs(actual-selected) > Fraction(1,100000):
            raise ValueError('Observed cadence differs from the explicitly tagged FFV1 rate')
        return selected


def stamp(value):
    return ['-metadata:s:v:0', 'motion_rate='+text(value)]


def timestamp_evidence(stream, frames, run):
    """Check each frame against declared cadence within one container clock tick."""
    import json
    cadence = observed(stream)
    if Fraction(stream['r_frame_rate']) == cadence:
        return dict(nominal_rate=text(cadence),observed_rate=stream['r_frame_rate'])
    output = run(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
        '-show_entries','frame=best_effort_timestamp','-of','json','pipe:0'])
    timestamps = json.loads(output)['frames']
    tick = Fraction(stream['time_base'])
    if len(timestamps) != frames:
        raise ValueError('Rational-cadence timestamp coverage is incomplete')
    maximum = Fraction(0)
    previous = None
    for index, frame in enumerate(timestamps):
        actual = int(frame['best_effort_timestamp'])*tick
        error = abs(actual-Fraction(index,1)/cadence)
        if error > tick or (previous is not None and actual <= previous):
            raise ValueError('Frame timestamps exceed the declared cadence/container quantization bound')
        maximum=max(maximum,error)
        previous=actual
    return dict(nominal_rate=text(cadence),observed_rate=stream['r_frame_rate'],
        checked_timestamps=frames,container_tick_seconds=str(tick),max_error_seconds=str(maximum))
