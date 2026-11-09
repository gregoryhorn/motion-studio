"""Materialize the original Fieldnotes example's editable, self-contained source.

This is example authoring code, not another runtime or scene vocabulary.
"""
from pathlib import Path
import shutil
from PIL import Image, ImageDraw
from studio.adapters import filmmaking as film
from studio.contracts import canonical

HERE = Path(__file__).resolve().parent


def artwork(path):
    """Original test illustration; no generated-provider or acquired-photo claim."""
    image = Image.new('RGBA', (800, 800), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((150, 665, 650, 730), fill='#b8b99b')
    draw.polygon([(238,425),(562,425),(525,690),(275,690)], fill='#b45032')
    draw.rounded_rectangle((220,403,580,460), radius=15, fill='#cf6d45')
    draw.line([(400,430),(400,225),(480,150)], fill='#203a2c', width=18)
    draw.ellipse((250,225,405,332), fill='#526d43')
    draw.ellipse((398,140,575,252), fill='#3e5a35')
    draw.ellipse((307,100,407,241), fill='#78935b')
    image.save(path)


def source(root, width, height, panel, *, revised=False, revision_accent=None, runtime=None, project_id=None, panel_id=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    (root/'fonts').mkdir()
    for name in ('Archivo.ttf','InstrumentSans.ttf','OFL-Archivo.txt','OFL-InstrumentSans.txt'):
        shutil.copyfile(film.RESOURCES/'kinetic/fonts'/name, root/'fonts'/name)
    shutil.copyfile(HERE/'scene.mjs', root/'scene.mjs')
    if revision_accent is not None:
        scene=(root/'scene.mjs').read_text()
        (root/'scene.mjs').write_text(scene.replace('g.fillStyle=accent;', 'g.fillStyle='+repr(revision_accent)+';',1))
    shutil.copyfile(film.RESOURCES/'scene.mjs', root/'scene-runtime.mjs')
    kinetic = film.RESOURCES/'kinetic'
    for name in ('core.js', 'LICENSE-Scenario-MIT.txt', 'NOTICE.md', 'UPSTREAM.json'):
        shutil.copyfile(kinetic/name, root/name)
    shutil.copytree(kinetic/'core', root/'core')
    artwork(root/'seed.png')
    (root/'config.json').write_bytes(canonical(dict(width=width,height=height,panel=panel,revised=revised)))
    (root/'index.html').write_text('''<!doctype html><html><head><meta charset="utf-8">
<title>Fieldnotes - original local verification film</title><style>
@font-face{font-family:Archivo;src:url(fonts/Archivo.ttf)}
@font-face{font-family:Inst;src:url(fonts/InstrumentSans.ttf)}
html,body{margin:0;overflow:hidden;background:#f0ebdc}canvas{display:block}
</style></head><body><canvas></canvas><script type="module" src="scene.mjs"></script></body></html>''')
    members = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
    if runtime is not None:
        manifest = film.package_storyboard_source(runtime,project_id,panel_id,root,'index.html',members)
    else:
        manifest = film.package_source(root,'index.html',members)
    path = root/'source.json'
    path.write_bytes(canonical(manifest))
    return path
