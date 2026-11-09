"""Pinned whole-line font fallback and optional Pillow/libraqm shaping.

No optional packages are imported at module load or metadata discovery. Keeping
one font for an entire line preserves HarfBuzz joining and FriBidi context; we
never fake complex shaping by independently drawing codepoints or reversed text.
"""
from __future__ import annotations
import hashlib
import importlib.metadata
from pathlib import Path
import unicodedata
from ..captions import fail


def discover():
    """Metadata only; actual RAQM availability is checked inside rendering."""
    try:
        version = importlib.metadata.version('Pillow')
    except importlib.metadata.PackageNotFoundError:
        version = None
    return dict(pillow_version=version, shaping_backend='Pillow/libraqm',
                shaping_available=None, requires_runtime_feature_check=True,
                fallback='first selected pinned font covering the entire line')


def runtime_identity():
    from PIL import features
    return {name: dict(available=features.check_feature(name),
                       version=features.version_feature(name))
            for name in ('raqm', 'harfbuzz', 'fribidi')}


def resolve_fonts(style, font_paths, glyph_reader):
    """Resolve every declared pin, in style order; never consult system fonts.

    Single path remains compatible. Multiple faces require an equally ordered
    path list/tuple, or a mapping keyed by face artifact_id. No implicit lookup.
    """
    pins = [face['face_artifact'] for face in style['fonts']]
    if isinstance(font_paths, dict):
        if set(font_paths) != {pin['artifact_id'] for pin in pins}:
            fail('Font resolver mapping differs from selected font pins.', 'HASH_MISMATCH')
        paths = [font_paths[pin['artifact_id']] for pin in pins]
    elif isinstance(font_paths, (list, tuple)):
        paths = list(font_paths)
    else:
        paths = [font_paths]
    if len(paths) != len(pins):
        fail('Resolve every selected fallback font in declared order.', 'INVALID_ARGUMENT')
    resolved = []
    for pin, value in zip(pins, paths):
        path = Path(value)
        if path.is_symlink() or not path.is_file():
            fail('Font must resolve to an immutable regular file.', 'PATH_UNSAFE')
        if 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']:
            fail('Pinned font bytes changed.', 'HASH_MISMATCH')
        resolved.append((path, glyph_reader(path)))
    return resolved


def required_codepoints(text):
    # Joiners, directional controls and variation selectors are consumed by the
    # shaping engine rather than requiring independent visible cmap entries.
    return {ord(c) for c in text if not c.isspace()
            and unicodedata.category(c) != 'Cf'
            and not (0xfe00 <= ord(c) <= 0xfe0f or 0xe0100 <= ord(c) <= 0xe01ef)}


def needs_shaping(text, direction):
    # Basic layout is deliberately restricted to ASCII; this also catches Indic
    # conjuncts that have no combining class and must not slip through a guard.
    return direction == 'rtl' or any(ord(c) > 127 for c in text)


class LineShaper:
    """One line is one mature shaping operation, shared by measure and draw."""
    def __init__(self, style, resolved):
        from PIL import ImageFont, features
        self.style, self.resolved, self.cache = style, resolved, {}
        self.raqm = features.check_feature('raqm')
        self.ImageFont = ImageFont

    def select(self, text):
        required = required_codepoints(text)
        for index, (path, coverage) in enumerate(self.resolved):
            if required.issubset(coverage):
                complex_text = needs_shaping(text, self.style['direction'])
                if complex_text and not self.raqm:
                    fail('Multilingual/RTL captions require installed Pillow with libraqm '
                         '(HarfBuzz/FriBidi); BASIC layout cannot substitute.', 'CAPABILITY_UNAVAILABLE')
                use_raqm = self.raqm
                key = index, use_raqm
                if key not in self.cache:
                    engine = self.ImageFont.Layout.RAQM if use_raqm else self.ImageFont.Layout.BASIC
                    self.cache[key] = self.ImageFont.truetype(str(path), self.style['font_size_px'], layout_engine=engine)
                options = {}
                if use_raqm and self.style['direction'] != 'auto':
                    options['direction'] = self.style['direction']
                return self.cache[key], options, index
        fail('No selected pinned font covers this complete shaping line. Select a '
             'covering fallback face or author separate lines; unsafe split-run '
             'fallback is not implemented.', 'UNSUPPORTED_FEATURE')

    def measure(self, draw, text):
        font, options, _ = self.select(text)
        return draw.textlength(text, font=font, **options)

    def metrics(self, text):
        font, _, _ = self.select(text)
        return font.getmetrics()

    def draw(self, draw, xy, text, **kwargs):
        font, options, _ = self.select(text)
        draw.text(xy, text, font=font, **options, **kwargs)


def layout_lines(draw, text, shaper, style, width):
    lines = []
    for authored in text.split('\n'):
        if style['line_breaks'] == 'authored':
            lines.append(authored)
            continue
        # Preserve the authored whitespace rather than silently normalize text.
        import re
        current = ''
        for token in re.findall(r'\S+\s*|\s+', authored):
            candidate = current + token
            if current and shaper.measure(draw, candidate.rstrip()) > width:
                lines.append(current.rstrip())
                current = token.lstrip()
            else:
                current = candidate
        lines.append(current.rstrip())
    if len(lines) > style['max_lines'] or any(shaper.measure(draw, line) > width for line in lines):
        fail('Caption text exceeds declared line/width limits.', 'LAYOUT_OVERFLOW')
    return lines
