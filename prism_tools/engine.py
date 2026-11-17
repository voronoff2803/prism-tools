"""F12 through the game's renderer: `prism render` on a scratch copy of Content/ where the repository has the tool built,
and a frame from the page the scene is open in (live.py, web.py) anywhere else."""
import os
import subprocess
import tempfile

import bpy
import numpy as np

from . import exporter, live, mapping as M, project, validate, web

COMPATIBLE_PANELS = ("MATERIAL_PT_", "EEVEE_MATERIAL_PT_", "DATA_PT_", "RENDER_PT_format", "RENDER_PT_output", "RENDER_PT_color_management")


class PrismRenderEngine(bpy.types.RenderEngine):
    bl_idname = "PRISM"
    bl_label = "Prism"
    bl_use_preview = False
    bl_use_postprocess = False

    def render(self, depsgraph):
        scene = bpy.context.scene if depsgraph is None else depsgraph.scene_eval.original
        scale = scene.render.resolution_percentage / 100
        w, h = int(scene.render.resolution_x * scale), int(scene.render.resolution_y * scale)
        try:
            pixels = render_frame(scene, w, h)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return
        result = self.begin_result(0, 0, w, h)
        result.layers[0].passes["Combined"].rect = pixels.reshape(-1, 4)
        self.end_result(result)


def render_frame(scene, w, h):
    """Linear RGBA floats, first row at the bottom, as a render result holds them."""
    r = project.root()
    errors = [what for level, _, what in validate.check(scene) if level == 'ERROR']
    if errors:
        raise RuntimeError("; ".join(errors[:3]))
    camera = live.scene_camera_command(scene, w, h)
    if not camera:
        raise RuntimeError("The scene has no camera")
    if not r or not os.path.exists(project.tool(r)):
        return _from_browser(scene, camera, w, h)
    overlay = project.scratch_overlay("render")
    exporter.write(overlay, exporter.files(scene))
    out = os.path.join(r, "out", "render", "frame.png")
    p = scene.prism
    level = p.level if p.generate_room else f"segment:{exporter.segments(scene)[0].name}"
    command = [project.tool(r), "render", project.game_data(r), level, "--camera", " ".join(repr(v) for v in camera["matrix"]),
               "--fov", repr(camera["fov"]), "--size", f"{w}x{h}", "--out", out, "--overlay", overlay, "--shaders", project.shaders(r),
               "--look", p.room, "--settle", str(p.live_settle)]
    done = subprocess.run(command, capture_output=True, text=True, cwd=r)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or "prism render failed").strip()[-400:])
    return _pixels(out, w, h)


def _from_browser(scene, camera, w, h):
    """The frame as the page the scene is open in draws it."""
    if live.mode() != 'BROWSER':
        raise RuntimeError("F12 is drawn by the page the scene is open in: press 'Browser' in the Prism panel first")
    if web.listeners() == 0:
        raise RuntimeError(f"No page is open on the scene: {web.address()}")
    live.flush(scene)
    png = web.capture({"width": w, "height": h, "camera": camera, "settle": scene.prism.live_settle})
    live.resend_camera()
    if not png:
        raise RuntimeError("The page did not send the frame")
    out = os.path.join(tempfile.gettempdir(), "prism-frame.png")
    with open(out, "wb") as f:
        f.write(png)
    return _pixels(out, w, h)


def _pixels(out, w, h):
    image = bpy.data.images.load(out, check_existing=False)
    try:
        if tuple(image.size) != (w, h):
            raise RuntimeError(f"The frame came {image.size[0]}x{image.size[1]}, not {w}x{h}")
        px = np.zeros(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(image)
    # The file is what the screen shows. Blender's view transform (Standard, see 'Prepare scene') puts sRGB back on.
    rgb = px[0::4], px[1::4], px[2::4]
    for c in rgb:
        c[:] = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    px[3::4] = 1
    return px


def _panels():
    for name in dir(bpy.types):
        panel = getattr(bpy.types, name)
        if hasattr(panel, "COMPAT_ENGINES") and name.startswith(COMPATIBLE_PANELS):
            yield panel


def register():
    bpy.utils.register_class(PrismRenderEngine)
    # Materials and lamps stay editable while Prism is the render engine.
    for panel in _panels():
        panel.COMPAT_ENGINES.add(PrismRenderEngine.bl_idname)


def unregister():
    for panel in _panels():
        panel.COMPAT_ENGINES.discard(PrismRenderEngine.bl_idname)
    bpy.utils.unregister_class(PrismRenderEngine)
