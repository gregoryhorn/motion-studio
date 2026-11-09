"""Small seekable caption vocabulary; exact clocks, no mutable playback state.

Durations are seconds in presentation time, not source samples or frame counts.
Pop only shrinks the fully checked caption group, never grows beyond its bounds.
"""
from fractions import Fraction
from ..captions import fail

HIGHLIGHT_FILL = '#ffd54f'
FADE_SECONDS = Fraction(3, 25)
POP_SECONDS = Fraction(4, 25)


def animation_state(kind, time, start, end):
    """Return rational opacity/scale at a half-open mapped segment interval."""
    if kind not in ('none', 'fade', 'pop'):
        fail('Unknown bounded caption animation.', 'UNSUPPORTED_FEATURE')
    if not all(isinstance(v, Fraction) for v in (time, start, end)) or end <= start:
        fail('Caption animation requires exact rational times and nonempty range.')
    if not start <= time < end:
        return {'opacity': Fraction(0), 'scale': Fraction(1)}
    opacity = scale = Fraction(1)
    if kind == 'fade':
        ramp = min(FADE_SECONDS, (end-start)/2)
        opacity = min(Fraction(1), (time-start)/ramp, (end-time)/ramp)
    elif kind == 'pop':
        ramp = min(POP_SECONDS, (end-start)/2)
        phase = min(Fraction(1), (time-start)/ramp)
        # Monotonic quadratic ease-out from 80% to 100%, no spring overshoot.
        scale = Fraction(1) - (1-phase)**2/5
    return {'opacity': opacity, 'scale': scale}


def composite_animation(background, overlay, state):
    """Transform only caption ink/box, never the background; keep group center."""
    from PIL import Image
    bounds = overlay.getbbox()
    if bounds is None:
        return background
    group = overlay.crop(bounds)
    if state['scale'] != 1:
        scale = state['scale']
        width = max(1, group.width*scale.numerator//scale.denominator)
        height = max(1, group.height*scale.numerator//scale.denominator)
        group = group.resize((width, height), Image.Resampling.LANCZOS)
    opacity = state['opacity']
    if opacity != 1:
        group.putalpha(group.getchannel('A').point(
            [i*opacity.numerator//opacity.denominator for i in range(256)]))
    x = bounds[0]+(bounds[2]-bounds[0]-group.width)//2
    y = bounds[1]+(bounds[3]-bounds[1]-group.height)//2
    result = background.convert('RGBA')
    result.alpha_composite(group, (x, y))
    return result.convert('RGB')
