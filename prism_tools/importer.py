"""Files of the game back into a scene: segments and looks made before this add-on."""
import json
import math
import os
import xml.etree.ElementTree as ET

import bpy
from mathutils import Vector

from . import mapping as M
from .exporter import ROOT_COLLECTION

ROLE_COLORS = {"floor": (0.5, 0.58, 0.74), "wall": (0.93, 0.95, 0.98), "ceiling": (0.93, 0.95, 0.98), "step": (0.02, 0.2, 0.9), "frame": (0.93, 0.95, 0.98)}
ROLE_ROUGHNESS = {"floor": 0.14, "wall": 0.6, "ceiling": 0.7, "step": 0.32, "frame": 0.4}
CASTER_TOP = 3.0


def templates(game_data):
    """`game_data`: the folder that has templates.xml, or that file's bytes."""
    if isinstance(game_data, dict):
        return game_data
    if isinstance(game_data, (bytes, bytearray)):
        tree = ET.fromstring(game_data)
    else:
        path = os.path.join(game_data or "", "templates.xml")
        if not os.path.exists(path):
            return {}
        tree = ET.parse(path).getroot()
    out = {}
    for t in tree.iter("template"):
        props = t.find("properties")
        out[t.get("name", "")] = dict(props.attrib) if props is not None else {}
    return out


def _vec(text, default=(0, 0, 0)):
    parts = (text or "").split()
    return tuple(float(parts[i]) if i < len(parts) else default[i] for i in range(3))


def unit_box_mesh():
    mesh = bpy.data.meshes.get("PrismBox")
    if mesh:
        return mesh
    mesh = bpy.data.meshes.new("PrismBox")
    v = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(v, [], f)
    mesh.update()
    return mesh


def role(pos, half):
    """As `Remaster.role` in the game: what a box is by where it is."""
    top, bottom = M.f32(pos[1] + half[1]), M.f32(pos[1] - half[1])
    if bottom >= 4.5:
        return "ceiling"
    if top <= M.f32(0.01):
        return "floor"
    if half[1] >= M.f32(1.8):
        return "wall" if M.f32(abs(pos[0]) + half[0]) > M.f32(2.9) else "frame"
    return "step" if top <= CASTER_TOP else "frame"


def material(name):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Base Color"].default_value = (*M.color_to_blender(ROLE_COLORS.get(name, (0.8, 0.8, 0.8))), 1)
    bsdf.inputs["Roughness"].default_value = ROLE_ROUGHNESS.get(name, 0.5)
    m.diffuse_color = bsdf.inputs["Base Color"].default_value
    m.prism.casts = name in ("step", "frame")
    if name == "floor":
        m.prism.detail, m.prism.large_receiver = 0.2, True
    return m


def sync_viewport_colors():
    """Solid view shows a material's viewport colour, which Base Color does not reach by itself."""
    for m in bpy.data.materials:
        if m.use_nodes and m.node_tree:
            bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf and tuple(m.diffuse_color) != tuple(bsdf.inputs["Base Color"].default_value):
                m.diffuse_color = bsdf.inputs["Base Color"].default_value


def root_collection(scene):
    root = scene.collection.children.get(ROOT_COLLECTION)
    if root is None:
        root = bpy.data.collections.new(ROOT_COLLECTION)
        scene.collection.children.link(root)
    return root


def _link(collection, obj):
    collection.objects.link(obj)
    return obj


def import_segment(scene, name, path, game_data):
    """`path`: the segment's file, or its bytes. `game_data`: as for `templates`."""
    t = templates(game_data)
    root = ET.fromstring(path) if isinstance(path, (bytes, bytearray)) else ET.parse(path).getroot()

    def merged(attrib):
        base = t.get(attrib.get("template", ""), {})
        return {**base, **attrib}

    head = merged(root.attrib)
    collection = bpy.data.collections.new(name)
    root_collection(scene).children.link(collection)
    collection.prism.is_segment = True
    collection.prism.length = _vec(head.get("size"), (12, 10, 16))[2]
    order = 0
    for node in root:
        a = merged(node.attrib)
        pos = _vec(a.get("pos"))
        if node.tag == "box":
            half = _vec(a.get("size"))
            o = _link(collection, bpy.data.objects.new(f"box.{order:03}", unit_box_mesh()))
            o.location = M.point_to_blender(pos)
            o.scale = M.half_to_blender(half)
            o.prism.kind = 'BOX' if a.get("visible", "1") != "0" else 'COLLIDER'
            if o.prism.kind == 'BOX':
                _assign(o, material(a.get("surface") or role(pos, half)))
            o.display_type = 'TEXTURED' if o.prism.kind == 'BOX' else 'WIRE'
        elif node.tag in ("obstacle", "powerup"):
            o = _link(collection, bpy.data.objects.new(f"{node.tag}.{order:03}.{a.get('type', '')}", None))
            o.location = M.point_to_blender(pos)
            o.empty_display_type = 'SPHERE' if node.tag == "powerup" else 'ARROWS'
            o.empty_display_size = 0.4
            o.prism.kind = node.tag.upper()
            o.prism.type = a.get("type", "")
            difficulty = (a.get("difficulty") or "0 1").split()
            o.prism.difficulty = (float(difficulty[0]), float(difficulty[1]) if len(difficulty) > 1 else 1)
            if node.tag == "obstacle":
                o.prism.mode = int(a.get("mode", "255"), 0)
                rot = _vec(a.get("rot"))
                o.rotation_mode = 'QUATERNION'
                o.rotation_quaternion = M.game_euler_to_rotation(rot).to_quaternion()
                if a.get("rot"):
                    o.prism.game_rot, o.prism.has_game_rot, o.prism.game_rot_text = rot, True, a["rot"]
                for i in range(12):
                    if f"param{i}" in a:
                        o.prism.params.add().value = a[f"param{i}"]
        else:
            continue
        o.prism.order = order
        order += 1
    return collection


def _assign(obj, mat):
    """Material on the object, not the mesh all boxes share."""
    if not obj.data.materials:
        obj.data.materials.append(None)
    obj.material_slots[0].link = 'OBJECT'
    obj.material_slots[0].material = mat


def import_look(scene, path):
    """`path`: the look's file, or its bytes."""
    if isinstance(path, (bytes, bytearray)):
        d = json.loads(path)
    else:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    p = scene.prism
    fog, sun, ambient, image = d["fog"], d["sun"], d["ambient"], d["image"]
    p.fog_start, p.fog_distance, p.fog_lower, p.fog_upper = fog["start"], fog["distance"], fog["lower"], fog["upper"]
    p.height_density, p.height_falloff, p.height_color = fog["heightDensity"], fog["heightFalloff"], fog["heightColor"]
    p.shadow_radius, p.shadow_softness = sun["shadowRadius"], sun["shadowSoftness"]
    p.ambient_sky, p.ambient_ground, p.ground_shade = ambient["sky"], ambient["ground"], ambient["groundShade"]
    p.ao_strength, p.ao_radius = ambient["aoStrength"], ambient["aoRadius"]
    p.exposure, p.grade, p.vignette, p.specular_filter = image["exposure"], image["grade"], image["vignette"], image["specularFilter"]
    p.glass_dispersion, p.glass_noise = d["glass"]["dispersion"], d["glass"]["noise"]
    p.bloom_intensity, p.bloom_threshold = d["bloom"]["intensity"], d["bloom"]["threshold"]
    r = d["reflections"]
    p.trace_scale, p.rough_steps, p.max_distance, p.sparse_blur = str(r["traceScale"]), r["roughSteps"], r["maxDistance"], r["sparseBlur"]
    view = d.get("view", {})
    p.glow = d.get("glow", (1, 1, 1, 0.2))
    p.far, p.draw_distance = view.get("far", 100), view.get("drawDistance", 40)
    glow = fog.get("glow", [0, 0, 0, 0])
    p.fog_glow, p.fog_glow_tightness = glow[:3], glow[3]
    p.camera_lamps.clear()
    for lamp in d.get("cameraLamps", []):
        l = p.camera_lamps.add()
        l.offset, l.color, l.intensity, l.radius, l.source = lamp["offset"], lamp["color"], lamp["intensity"], lamp["radius"], lamp["source"]
    p.softboxes.clear()
    for b in d["softboxes"]:
        s = p.softboxes.add()
        s.direction, s.up, s.size, s.color, s.softness = b["direction"], b["up"], b["size"], b["color"], b["softness"]
    for name, s in d["surfaces"].items():
        m = material(name)
        bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        bsdf.inputs["Base Color"].default_value = (*M.color_to_blender(s["color"]), 1)
        bsdf.inputs["Roughness"].default_value = s["roughness"]
        bsdf.inputs["Metallic"].default_value = s.get("metallic", 0)
        bsdf.inputs["Emission Strength"].default_value = s.get("emissive", 0)
        m.prism.casts = s.get("casts", False)
        m.prism.detail = s.get("detail", 0)
        m.prism.large_receiver = s.get("largeReceiver", False)
        m.prism.shading = s.get("shading", "default")
        m.prism.shading_params = (list(s.get("params", [])) + [0, 0, 0])[:3]
        g = s.get("glass")
        m.prism.is_glass = g is not None
        if g is not None:
            m.prism.frost = g.get("frost", s["roughness"])
            m.prism.relief = g.get("relief", "none")
            m.prism.relief_strength = g.get("strength", 0.26)
            m.prism.relief_density = g.get("density", 26)
            m.prism.frost_pattern = g.get("frostPattern", "all")
            m.prism.scatter = g.get("scatter", 0)
            m.prism.absorption = g.get("absorption", 0)
            m.prism.opal = g.get("opal", 0)
            m.prism.film = g.get("film", 0)
        if s.get("emissive"):
            bsdf.inputs["Emission Color"].default_value = (*M.color_to_blender(s["color"]), 1)
        # Kept while no object uses it: the room's palette is complete.
        m.use_fake_user = True
    sync_viewport_colors()
    light = next((o for o in scene.objects if o.type == 'LIGHT' and o.data.type == 'SUN'), None)
    if light is None:
        data = bpy.data.lights.new("Sun", 'SUN')
        light = bpy.data.objects.new("Sun", data)
        scene.collection.objects.link(light)
        light.location = (0, 0, 20)
    light.data.color = M.color_to_blender(sun["color"])
    light.data.energy = sun["intensity"]
    towards = M.point_to_blender(sun["direction"])
    light.rotation_mode = 'QUATERNION'
    light.rotation_quaternion = Vector(towards).normalized().to_track_quat('Z', 'Y')


def prepare_scene(scene):
    """What makes Blender show colours the way the game's files mean them."""
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.view_settings.use_curve_mapping = False
    scene.render.dither_intensity = 0
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.unit_settings.system = 'METRIC'
    # The game's lens, seen from the middle of the corridor.
    if scene.camera is None:
        data = bpy.data.cameras.new("Game camera")
        data.sensor_fit = 'HORIZONTAL'
        data.lens_unit = 'FOV'
        data.angle = math.radians(60)
        data.clip_start, data.clip_end = 0.2, 100
        camera = bpy.data.objects.new("Game camera", data)
        camera.prism.kind = 'IGNORE'
        scene.collection.objects.link(camera)
        camera.location = (0, 0, 1)
        camera.rotation_euler = (math.pi / 2, 0, 0)
        scene.camera = camera
