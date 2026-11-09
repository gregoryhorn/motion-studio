"""Static Blender >=4.2 background helper. Run only by the owned scene adapter.

Not a sandbox: .blend parsing and trusted installed engines execute native code.
No source strings or argv fragments are evaluated from the JSON config.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys


def _closure(bpy, root, members):
    """Fail closed on external file dependencies and unsupported live simulations."""
    allowed = {(root/name).resolve(strict=True) for name in members}
    if bpy.data.libraries:
        raise ValueError('Linked .blend libraries unsupported; make linked datablocks local before packaging')
    # The native dependency inventory includes images, fonts, sounds, volumes,
    # clips and caches. Packed datablocks are intrinsically in the .blend pin.
    dependencies = []
    for raw in bpy.utils.blend_paths(absolute=True, packed=False, local=False):
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = Path(bpy.path.abspath(raw))
        resolved = path.resolve(strict=True)
        if resolved not in allowed or not resolved.is_file():
            raise ValueError('Native dependency outside declared source closure: '+str(raw))
        dependencies.append(resolved.relative_to(root).as_posix())
    for image in bpy.data.images:
        if image.source in ('SEQUENCE', 'MOVIE', 'TILED'):
            raise ValueError('Movie, tiled/UDIM and image-sequence textures unsupported; use packed stills')
    if len(bpy.data.movieclips) or len(bpy.data.volumes) or len(bpy.data.cache_files):
        raise ValueError('Movie clips, volumes and external cache datablocks unsupported')
    for scene in bpy.data.scenes:
        if scene.sequence_editor:
            strips = getattr(scene.sequence_editor, 'strips', None)
            if strips is None:
                strips = getattr(scene.sequence_editor, 'sequences', ())
            if len(strips):
                raise ValueError('Video sequencer sources unsupported by physical scene route')
        if scene.rigidbody_world:
            raise ValueError('Live rigid-body simulation unsupported; bake animation to editable keyframes')
    unsupported = {'FLUID', 'CLOTH', 'SOFT_BODY', 'PARTICLE_SYSTEM', 'DYNAMIC_PAINT', 'MESH_CACHE', 'MESH_SEQUENCE_CACHE'}
    for item in bpy.data.objects:
        if any(modifier.type in unsupported for modifier in item.modifiers):
            raise ValueError('Live simulation/cache modifier unsupported; bake geometry/keyframes before packaging')
    trees = [group for group in bpy.data.node_groups]
    for scene in bpy.data.scenes:
        # Blender 5 moved the scene compositor to a reusable node group.
        # Inspect both APIs without losing the external-output checks on 4.x.
        for name in ('node_tree', 'compositing_node_group'):
            tree = getattr(scene, name, None)
            if tree is not None and tree not in trees:
                trees.append(tree)
    for tree in trees:
        for node in tree.nodes:
            if node.bl_idname in ('CompositorNodeOutputFile', 'GeometryNodeSimulationInput',
                                  'GeometryNodeSimulationOutput', 'GeometryNodeBake'):
                raise ValueError('External file outputs or live/baked simulation nodes unsupported')
    return sorted(set(dependencies))


def render(config):
    import bpy  # type: ignore[import-not-found]  # Only inside the real Blender child.
    if bpy.app.version < (4, 2, 0):
        raise ValueError('Blender >=4.2 required')
    root = Path(config['root']).resolve(strict=True)
    entry = root/config['entry']
    entry.resolve(strict=True).relative_to(root)
    bpy.ops.wm.open_mainfile(filepath=str(entry), load_ui=False, use_scripts=False)
    dependencies = _closure(bpy, root, config['members'])
    scene = bpy.context.scene
    if scene.camera is None or scene.camera.type != 'CAMERA':
        raise ValueError('Native scene must have an authored active camera')
    engines = ('CYCLES', 'BLENDER_EEVEE_NEXT', 'BLENDER_WORKBENCH')
    engine = config['engine'] or scene.render.engine
    if engine not in engines:
        raise ValueError('Only safe known built-in render engines supported')
    scene.render.engine = engine
    # Cycles CPU prevents a hidden GPU requirement; samples, bounces, materials,
    # lights, camera, color management and authored motion stay native and intact.
    if engine == 'CYCLES':
        scene.cycles.device = 'CPU'
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 1
    scene.render.resolution_x = config['canvas']['width_px']
    scene.render.resolution_y = config['canvas']['height_px']
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.0
    num, den = config['rate']['num'], config['rate']['den']
    native_fps = max(1, round(num/den))
    native_base = native_fps*den/num
    scene.render.fps = native_fps
    scene.render.fps_base = native_base
    if scene.render.fps != native_fps or not math.isclose(scene.render.fps_base, native_base, rel_tol=1e-6):
        raise ValueError('Native Blender fps/fps_base cannot represent explicit requested rate')
    scene.frame_start = config['start'] + 1
    scene.frame_end = config['end']
    scene.frame_step = 1
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA' if config['alpha'] == 'straight' else 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.compression = 15
    scene.render.film_transparent = config['alpha'] == 'straight'
    scene.render.use_file_extension = True
    scene.render.use_overwrite = False
    scene.render.use_placeholder = False
    # Save a usable relative render destination, not the host attempt path.
    scene.render.filepath = '//renders/'
    bpy.context.preferences.filepaths.save_version = 0
    scene.frame_set(config['start'] + 1)
    bpy.ops.wm.save_as_mainfile(filepath=str(entry), check_existing=False, relative_remap=True)
    dependencies = _closure(bpy, root, config['members'])
    native_path = scene.render.filepath
    frames = Path(config['frames']).resolve(strict=True)
    for index, frame in enumerate(range(config['start'], config['end'])):
        scene.frame_set(frame + 1)
        scene.render.filepath = str(frames/f'{index:08d}.png')
        bpy.ops.render.render(write_still=True, scene=scene.name)
        if not (frames/f'{index:08d}.png').is_file():
            raise ValueError('Blender did not write the requested PNG frame')
    scene.render.filepath = native_path
    # The saved .blend has authored scene state plus explicit render settings;
    # no ephemeral output path or active last-render frame is written into it.
    report = dict(schema='motion/v1/blender-observed', blender_version=bpy.app.version_string,
                  scene=scene.name, engine=scene.render.engine, camera=scene.camera.name,
                  canvas=dict(width_px=scene.render.resolution_x, height_px=scene.render.resolution_y),
                  rate=config['rate'], native_fps=scene.render.fps, native_fps_base=str(scene.render.fps_base),
                  frames=config['end']-config['start'], alpha=config['alpha'],
                  native_frame_range=dict(start=scene.frame_start, end=scene.frame_end), dependencies=dependencies,
                  color=dict(display_device=scene.display_settings.display_device,
                             view_transform=scene.view_settings.view_transform,
                             look=scene.view_settings.look, exposure=str(scene.view_settings.exposure),
                             gamma=str(scene.view_settings.gamma)),
                  scripts_autoexec=False, sandbox=False)
    Path(config['report']).write_text(json.dumps(report, sort_keys=True), encoding='utf-8')


def main():
    args = sys.argv[sys.argv.index('--')+1:]
    if len(args) != 1:
        raise ValueError('One owned config path required')
    render(json.loads(Path(args[0]).read_bytes()))


if __name__ == '__main__':
    main()
