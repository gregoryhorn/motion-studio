"""Pinned self-contained SDR input/working/output color conversion via FFmpeg.

This route is not an OCIO/ACES or HDR implementation. A recipe declares all
three spaces; FFmpeg colorspace performs actual primaries/transfer/matrix/range
conversion, rather than only adding output tags. No external LUTs or URLs.
"""
import json
import subprocess
from fractions import Fraction
from . import ffmpeg, rates

PRIMARIES = {'bt709', 'bt2020', 'smpte170m', 'bt470bg'}
TRANSFERS = {'bt709', 'gamma22', 'gamma28', 'smpte170m', 'linear'}
MATRICES = {'bt709', 'bt2020nc', 'smpte170m', 'bt470bg'}


def space(value):
    if (set(value) != {'primaries', 'transfer', 'matrix', 'range'}
            or value['primaries'] not in PRIMARIES or value['transfer'] not in TRANSFERS
            or value['matrix'] not in MATRICES or value['range'] not in ('full', 'limited')):
        raise ValueError('Recipe uses a color space outside the selected SDR transform subset')
    return value


def _filter(source, target):
    opts = [('iprimaries', source['primaries']), ('itrc', source['transfer']),
            ('ispace', source['matrix']), ('irange', {'full': 'pc', 'limited': 'tv'}[source['range']]),
            ('primaries', target['primaries']), ('trc', target['transfer']), ('space', target['matrix']),
            ('range', {'full': 'pc', 'limited': 'tv'}[target['range']]), ('format', 'yuv444p12'), ('dither', 'fsb')]
    return 'colorspace=' + ':'.join(f'{key}={value}' for key, value in opts)


def transform(context, source, config, target, parameters):
    recipe = json.loads(config.read_bytes())
    if (set(recipe) != {'schema', 'input_space', 'working_space', 'output_space', 'spaces'}
            or recipe['schema'] != 'motion/v1/sdr-color-pipeline'
            or recipe['input_space'] != parameters['input_space']
            or recipe['output_space'] != parameters['output_space']
            or parameters['range_policy'] != 'clip'):
        raise ValueError('Color recipe identity differs from selected input/working/output pipeline')
    if not isinstance(recipe['spaces'], dict) or not 1 <= len(recipe['spaces']) <= 8:
        raise ValueError('Color recipe must contain one to eight explicit spaces')
    spaces = {name: space(value) for name, value in recipe['spaces'].items()}
    incoming, working, outgoing = (spaces[recipe[key]] for key in ('input_space', 'working_space', 'output_space'))
    if outgoing != parameters['output_color']:
        raise ValueError('Recipe output differs from frozen requested output color')
    def run(argv):
        return context.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    facts = json.loads(run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-of', 'json', str(source)]).stdout)
    if len(facts['streams']) != 1 or facts['streams'][0]['codec_type'] != 'video':
        raise ValueError('Color conversion requires a silent single-stream video')
    stream = facts['streams'][0]
    if 'a' in stream.get('pix_fmt', '').replace('gray', '') or stream.get('pix_fmt') in ('rgba', 'bgra', 'argb', 'abgr'):
        raise ValueError('This SDR conversion route does not transform or discard alpha')
    count = int(stream['nb_read_frames'])
    cadence = rates.observed(stream)
    rates.bounds(stream['width'], stream['height'], count, cadence)
    tags = {'color_primaries': incoming['primaries'], 'color_transfer': incoming['transfer'],
            'color_space': incoming['matrix'], 'color_range': {'full': 'pc', 'limited': 'tv'}[incoming['range']]}
    for key, value in tags.items():
        if stream.get(key) not in (None, 'unknown', 'unspecified', value):
            raise ValueError('Pinned input color contradicts actual stream tags')
    filters = _filter(incoming, working) + ',' + _filter(working, outgoing)
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(source),
        '-map', '0:v:0', '-an', '-vf', filters, '-c:v', 'ffv1', '-pix_fmt', 'yuv444p12le',
        '-threads', '1', '-r', rates.text(cadence), *rates.stamp(cadence),
        '-metadata', 'motion_color_recipe_sha256=' + ffmpeg.digest(config), str(target)])
    final = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(target)]).stdout)['streams'][0]
    expected = {'color_primaries': outgoing['primaries'], 'color_transfer': outgoing['transfer'],
                'color_space': outgoing['matrix'], 'color_range': {'full': 'pc', 'limited': 'tv'}[outgoing['range']]}
    if any(final.get(key) != value for key, value in expected.items()):
        raise ValueError('Converted output tags do not describe the selected pixel transform')
    return dict(schema='motion/v1/color-transform', source_sha256=ffmpeg.digest(source),
                config_sha256=ffmpeg.digest(config), output_sha256=ffmpeg.digest(target),
                recipe=recipe, filters=filters, range_policy='clip', intermediate_bits=12,
                warning='Selected SDR matrix/transfer/primaries pipeline; not OCIO, ACES or HDR certification')


def delivery_filter(stream):
    """Avoid reapplying a color transform to already converted BT.709 pixels."""
    expected = {'color_primaries': 'bt709', 'color_transfer': 'bt709', 'color_space': 'bt709', 'color_range': 'tv'}
    if all(stream.get(key) == value for key, value in expected.items()):
        return 'null'
    known = {key: stream[key] for key in expected if stream.get(key) not in (None, 'unknown', 'unspecified')}
    rgb_tags = {'color_range': 'pc', 'color_space': 'gbr'}
    if (any(rgb_tags.get(key) != value for key, value in known.items())
            or stream.get('pix_fmt') not in ('bgr0', 'rgb24')):
        raise ValueError('Explicit media.color transform required before BT.709 delivery')
    # Existing authored display-RGB scene contract; no input primaries conversion.
    return ('scale=in_range=full:out_range=limited:out_color_matrix=bt709,'
            'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited')
