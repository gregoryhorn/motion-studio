"""One real Pillow frame evaluator for both preview and encoded caption burn.

Word-highlight/static/seekable animated captions with pinned whole-line fallback and optional
Pillow/libraqm (HarfBuzz/FriBidi) shaping. No substitute fonts or fake RTL. No execution on import. Caller is the approved
B07 local runner, not a tool handler. Background frames must be supplied at the
exact output-rate presentation time by the assembly adapter.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import struct
import subprocess
from decimal import Decimal
from fractions import Fraction
from ..captions import (check, fail, map_segments, require_renderable,
                        require_word_highlight, word_text_spans,
                        schema_document, rational)
from ..contracts import digest, MAX_INT

ADAPTER_ID='local.pillow-captions'
VERSION='1.1'

def fingerprint():
    import PIL
    from .caption_shaping import runtime_identity
    return digest({'adapter_id':ADAPTER_ID,'implementation_version':VERSION,
                   'shaping':runtime_identity(),
                   'shaping_source_sha256':'sha256:'+hashlib.sha256(Path(__file__).with_name('caption_shaping.py').read_bytes()).hexdigest(),
                   'animation_source_sha256':'sha256:'+hashlib.sha256(Path(__file__).with_name('caption_animation.py').read_bytes()).hexdigest(),
                   'pillow':PIL.__version__,'source_sha256':'sha256:'+hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'style_schema_sha256':digest(schema_document('CaptionStyle'))})

def glyphs(face):
    """Read actual SFNT Unicode cmap; no font-name/environment fallback."""
    data=Path(face).read_bytes()
    def u16(p): return struct.unpack_from('>H',data,p)[0]
    def u32(p): return struct.unpack_from('>I',data,p)[0]
    tables={data[12+i*16:16+i*16]:u32(20+i*16) for i in range(u16(4))}
    cmap=tables.get(b'cmap')
    if cmap is None: fail('Selected font has no Unicode cmap.','UNSUPPORTED_FEATURE')
    supported=set()
    for i in range(u16(cmap+2)):
        record=cmap+4+8*i; platform=u16(record); encoding=u16(record+2)
        if platform!=0 and not (platform==3 and encoding in [1,10]): continue
        base=cmap+u32(record+4); fmt=u16(base)
        if fmt==12:
            for j in range(u32(base+12)):
                pos=base+16+12*j; start,end,glyph=u32(pos),u32(pos+4),u32(pos+8)
                if end>0x10ffff or end<start: fail('Invalid font cmap.')
                supported.update(cp for cp in range(start,end+1) if glyph+cp-start!=0)
        elif fmt==4:
            count=u16(base+6)//2; ends=base+14; starts=ends+2*count+2; deltas=starts+2*count; offsets=deltas+2*count
            for j in range(count):
                start,end=u16(starts+2*j),u16(ends+2*j); delta=u16(deltas+2*j); offset=u16(offsets+2*j)
                for cp in range(start,end+1):
                    index=(cp+delta)&0xffff if not offset else u16(offsets+2*j+offset+2*(cp-start))
                    if offset and index: index=(index+delta)&0xffff
                    if index and cp!=0xffff: supported.add(cp)
    if not supported: fail('Selected font has no supported Unicode cmap.','UNSUPPORTED_FEATURE')
    return supported

def validate_style(style,font_path,text):
    check(style,'CaptionStyle')
    expected={'adapter_id':ADAPTER_ID,'implementation_version':VERSION,'schema_sha256':digest(schema_document('CaptionStyle'))}
    if style['renderer']!=expected: fail('Style renderer implementation/schema pin differs.','HASH_MISMATCH')
    # Pillow exposes no HarfBuzz glyph-cluster positions. Do not invent RTL or
    # complex-script word masks from independently shaped substring widths.
    # Whole-line static/fade/pop still support the full shaping path.
    if style['highlight']=='word' and (style['direction']=='rtl' or any(ord(c)>127 for c in text)):
        fail('Word highlighting currently requires ASCII LTR text; complex-script cluster masks are not implemented.','UNSUPPORTED_FEATURE')
    from .caption_shaping import resolve_fonts, LineShaper
    paths=resolve_fonts(style,font_path,glyphs)
    shaper=LineShaper(style,paths)
    for line in text.split('\n'): shaper.select(line)
    if Decimal(style['line_height'])<=0: fail('Line height must be positive.')
    # Preserve the historical one-font return shape for direct callers.
    return paths[0][0] if len(paths)==1 else [p for p,_ in paths]

def render_frame(caption,placement,style,frame,background,font_path,*,decisions=(),font_usage=None):
    """Evaluate the exact frame; returns a Pillow RGB image, no hidden encoder."""
    from PIL import Image, ImageDraw
    from .caption_animation import animation_state, composite_animation, HIGHLIGHT_FILL
    from .caption_shaping import LineShaper, resolve_fonts, layout_lines
    require_renderable(caption,decisions); check(placement,'CaptionPlacement')
    if type(frame)!=int or not 0<=frame<=MAX_INT: fail('Frame must be bounded integer.')
    if placement['caption']['id']!=caption['caption_id'] or placement['caption']['revision']!=caption['revision'] or placement['source_audio']!=caption['source_audio']: fail('Placement is stale for caption/audio.','HASH_MISMATCH')
    text='\n'.join(s['text'] for s in caption['segments'])
    validate_style(style,font_path,text)
    if style['highlight']=='word': require_word_highlight(caption)
    shaper=LineShaper(style,resolve_fonts(style,font_path,glyphs))
    # Validate all authored lines even when this particular frame is inactive.
    for line in text.split('\n'): shaper.select(line)
    rate=placement['output_rate']; t=Fraction(frame*rate['den'],rate['num'])
    active=[s for s in map_segments(caption,placement['spans']) if s['start']<=t<s['end']]
    if len(active)>1: fail('Overlapping captions require explicit renderer support.','UNSUPPORTED_FEATURE')
    image=background.convert('RGB').copy()
    if not active: return image
    safe=style['safe_zone']; x0,y0=safe['x_px'],safe['y_px']; w,h=safe['width_px'],safe['height_px']
    if x0<0 or y0<0 or x0+w>image.width or y0+h>image.height: fail('Safe zone outside output canvas.','LAYOUT_OVERFLOW')
    overlay=Image.new('RGBA',image.size,(0,0,0,0))
    draw=ImageDraw.Draw(overlay)
    margin=style['margin_px']; outline=style['outline']['width_px']; padding=style['box']['padding_px'] if style['box'] else 0
    width=min(style['max_width_px'],w-2*(margin+padding+outline))
    if width<=0: fail('No caption layout width.','LAYOUT_OVERFLOW')
    lines=layout_lines(draw,active[0]['text'],shaper,style,width)
    metrics=[shaper.metrics(line) for line in lines]
    ascent=max(a for a,_ in metrics); descent=max(d for _,d in metrics)
    step=int(Decimal(ascent+descent)*Decimal(style['line_height']))
    height=(len(lines)-1)*step+ascent+descent
    if height+2*(margin+padding+outline)>h: fail('Caption height exceeds safe zone.','LAYOUT_OVERFLOW')
    if style['anchor']=='top': y=y0+margin+padding+outline
    elif style['anchor']=='bottom': y=y0+h-margin-padding-outline-height
    else: y=y0+(h-height)//2
    # Opaque colors only: reject unsupported alpha rather than discard it.
    colors=[style['fill'],style['outline']['color']]+([style['box']['color']] if style['box'] else [])
    if any(len(c)!=7 for c in colors): fail('Alpha caption colors not advertised.','UNSUPPORTED_FEATURE')
    segment=active[0]
    original=next(s for s in caption['segments'] if s['segment_id']==segment['segment_id'])
    ranges={s['word_id']:(s['text_start'],s['text_end']) for s in word_text_spans(original)} if style['highlight']=='word' else {}
    current_words=[word for word in segment['words'] if word['start']<=t<word['end']] if ranges else []
    if len(current_words)>1: fail('Overlapping word highlighting is not supported.','UNSUPPORTED_FEATURE')
    # layout_lines preserves visible text but may discard inter-line whitespace.
    # Recover exact authored offsets monotonically, not by repeated-word lookup.
    cursor=0
    for line in lines:
        line_start=original['text'].find(line,cursor)
        if line_start<0: fail('Wrapped caption cannot be associated with authored text.','LAYOUT_OVERFLOW')
        cursor=line_start+len(line)
        lw=shaper.measure(draw,line)
        x=x0+margin+padding+outline if style['align']=='left' else (x0+w-margin-padding-outline-lw if style['align']=='right' else x0+(w-lw)/2)
        if style['box']:
            # Layout extents are half-open, but Pillow rectangles include both
            # endpoints. Reserve padding/outline above, then convert the far
            # edges to inclusive pixel indices rather than painting one extra
            # row/column into the safe-zone margin (notably at bottom/right).
            import math
            box_bounds=(math.floor(x-padding-outline),y-padding-outline,
                        math.ceil(x+lw+padding+outline)-1,y+ascent+descent+padding+outline-1)
            if box_bounds[0]<x0+margin or box_bounds[2]>=x0+w-margin or box_bounds[1]<y0+margin or box_bounds[3]>=y0+h-margin:
                fail('Caption box exceeds safe zone.','LAYOUT_OVERFLOW')
            draw.rectangle(box_bounds,fill=style['box']['color'])
        bbox_font,bbox_options,font_index=shaper.select(line)
        bounds=draw.textbbox((x,y),line,font=bbox_font,anchor='lt',stroke_width=outline,**bbox_options)
        if bounds[0]<x0+margin or bounds[2]>x0+w-margin or bounds[1]<y0+margin or bounds[3]>y0+h-margin:
            fail('Shaped ink/combining marks exceed caption safe zone.','LAYOUT_OVERFLOW')
        shaper.draw(draw,(x,y),line,anchor='lt',fill=style['fill'],stroke_width=outline,stroke_fill=style['outline']['color'])
        if current_words:
            lo,hi=ranges[current_words[0]['word_id']]
            left=max(lo,line_start)-line_start; right=min(hi,cursor)-line_start
            if left<right:
                # Recolor a clipped FULL shaping line, never draw split word runs.
                # Prefix advance includes the boundary pair's kerning. ASCII-only
                # admission above makes these visual/logical intervals coherent.
                def advance(index):
                    if index==0: return 0
                    if index==len(line): return lw
                    return draw.textlength(line[:index+1],font=bbox_font,**bbox_options)-draw.textlength(line[index:index+1],font=bbox_font,**bbox_options)
                import math
                clip=(max(0,math.floor(x+advance(left))),max(0,math.floor(bounds[1])),
                      min(image.width,math.ceil(x+advance(right))),min(image.height,math.ceil(bounds[3])))
                mask=Image.new('L',image.size,0)
                shaper.draw(ImageDraw.Draw(mask),(x,y),line,anchor='lt',fill=255,stroke_width=outline,stroke_fill=0)
                if clip[0]<clip[2] and clip[1]<clip[3]:
                    # Recolor fill only; preserve box, outline, and exact alpha
                    # silhouette (including antialias pixels) from the base line.
                    alpha=overlay.getchannel('A')
                    overlay.paste(HIGHLIGHT_FILL,clip,mask.crop(clip))
                    overlay.putalpha(alpha)
        if font_usage is not None:
            font_usage.add(font_index)
        y+=step
    # Actual raster bounds protect accents, outlines, boxes and future changes;
    # the bounded transform only shrinks inside this already checked rectangle.
    ink=overlay.getbbox()
    if ink and (ink[0]<x0+margin or ink[1]<y0+margin or ink[2]>x0+w-margin or ink[3]>y0+h-margin):
        fail('Caption pixels exceed safe zone.','LAYOUT_OVERFLOW')
    return composite_animation(image,overlay,animation_state(style['animation'],t,segment['start'],segment['end']))

def export_sidecar(caption,*,format,time_origin,placement=None,rounding='nearest_even',decisions=()):
    """Pure UTF-8 SRT/VTT conversion with exact final-unit rounding receipt.

    B07 runner publishes returned bytes and the receipt as real artifacts.
    Source origin is never presented as an approved delivery sidecar.
    ASS is not advertised; a style-aware ASS serializer is still required.
    """
    require_renderable(caption,decisions)
    if format not in ['srt','vtt']: fail('Only SRT/VTT export is implemented.','UNSUPPORTED_FEATURE')
    if rounding not in ['nearest_even','coverage'] or time_origin not in ['source','delivery']: fail('Invalid sidecar conversion parameters.')
    if time_origin=='source':
        if placement is not None: fail('Source export forbids placement.')
        segments=[{**s,'start':Fraction(s['start_sample'],s['sample_rate']),'end':Fraction(s['end_sample'],s['sample_rate'])} for s in caption['segments'] if s['text']]
    else:
        if placement is None: fail('Delivery export requires pinned placement.')
        check(placement,'CaptionPlacement')
        if placement['caption']['id']!=caption['caption_id'] or placement['caption']['revision']!=caption['revision'] or placement['source_audio']!=caption['source_audio']: fail('Stale sidecar placement.','HASH_MISMATCH')
        segments=map_segments(caption,placement['spans'])
    import html
    cues=[]; conversions=[]
    def stamp(ms):
        hours,rem=divmod(ms,3600000); minutes,rem=divmod(rem,60000); seconds,millis=divmod(rem,1000)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'+(',' if format=='srt' else '.')+f'{millis:03d}'
    for i,s in enumerate(segments):
        start=s['start']*1000; end=s['end']*1000
        lo=round(start) if rounding=='nearest_even' else start.numerator//start.denominator
        hi=round(end) if rounding=='nearest_even' else -(-end.numerator//end.denominator)
        if lo<0 or hi<=lo: fail('Sidecar precision collapses caption range.','CONVERSION_REQUIRED')
        text=html.escape(s['text'],quote=False)
        cues.append(f'{i+1}\n{stamp(lo)} --> {stamp(hi)}\n{text}\n')
        def rational_value(f): return {'num':f.numerator,'den':f.denominator}
        conversions.append({'segment_id':s['segment_id'],'item_id':s.get('item_id'),'start_seconds':rational_value(s['start']),'end_seconds':rational_value(s['end']),
                            'start_ms':lo,'end_ms':hi,'start_error_seconds':rational_value(Fraction(lo,1000)-s['start']),'end_error_seconds':rational_value(Fraction(hi,1000)-s['end'])})
    text=('WEBVTT\n\n' if format=='vtt' else '')+'\n'.join(cues)
    payload=text.encode('utf-8')
    receipt={'format':format,'encoding':'UTF-8','time_origin':time_origin,'rounding':rounding,'delivery_sidecar_eligible':time_origin=='delivery',
             'visual_semantics':{'word_highlight':'not_represented','animation':'not_represented','style':'not_represented','text_and_segment_timing':'preserved'},
             'caption_content_sha256':digest(caption),'placement_sha256':digest(placement) if placement is not None else None,
             'output_sha256':'sha256:'+hashlib.sha256(payload).hexdigest(),'conversions':conversions}
    return payload,receipt


def encode_frames(caption,placement,style,backgrounds,font_path,output,*,start_frame=0,decisions=(),ffmpeg='/usr/bin/ffmpeg'):
    """Lossless RGB FFV1 candidate using render_frame, exact same evaluator.

    No implicit frame rate/audio/color conversion. Explicit RGB FFV1 Matroska
    is this adapter's sole advertised encode profile, not a delivery master.
    """
    from itertools import chain
    iterator=iter(backgrounds)
    try: first=next(iterator)
    except StopIteration: fail('No input frames.')
    rate=placement['output_rate']; path=Path(output)
    if path.exists(): fail('Owned output already exists.','PATH_UNSAFE')
    command=[ffmpeg,'-v','error','-nostdin','-n','-f','rawvideo','-pix_fmt','rgb24','-s',f'{first.width}x{first.height}',
             '-r',f"{rate['num']}/{rate['den']}",'-i','pipe:0','-an','-c:v','ffv1','-level','3','-pix_fmt','bgr0',str(path)]
    count=0; font_usage=set()
    with subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE) as proc:
        try:
            for i,bg in enumerate(chain([first],iterator)):
                if bg.size!=first.size: fail('Background frame geometry changed.')
                rendered=render_frame(caption,placement,style,start_frame+i,bg,font_path,decisions=decisions,font_usage=font_usage)
                proc.stdin.write(rendered.tobytes()); count+=1
            proc.stdin.close(); error=proc.stderr.read(); status=proc.wait(timeout=60)
            if status: fail('Caption encode failed: '+error.decode('utf-8','replace')[:1000],'ADAPTER_FAILED')
        except BaseException:
            proc.kill(); proc.wait(); raise
    return {'path':str(path),'frame_count':count,'renderer_fingerprint':fingerprint(),'font_sha256':style['fonts'][0]['face_artifact']['sha256'],
            'font_sha256_role':'first_declared_face_not_usage',
            'declared_font_pins':[face['face_artifact'] for face in style['fonts']],
            'used_font_pins':[style['fonts'][i]['face_artifact'] for i in sorted(font_usage)],
            'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()}
