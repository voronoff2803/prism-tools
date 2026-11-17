"""The scene as files of the game: segments/*.xml and their visuals, looks/<room>.json, rooms/<room>.lua, levels/<level>.xml.

Nothing here depends on the time or on dictionary luck: the same scene gives the same bytes.
"""
import json
import math
import os
import struct
import zlib
from xml.sax.saxutils import quoteattr

import bpy
from mathutils import Matrix, Vector

from . import built
from . import mapping as M

ROOT_COLLECTION = "Prism"
# Blender's watts to the game's radiance factor at 1 m.
WATTS_TO_INTENSITY = 1 / (4 * math.pi)
# A lamp with no reach of its own ends where it has faded to this.
LIGHT_FADED = 0.02
MAX_VERTICES_PER_PART = 60000
# In a visual's BODS block: the body stands until it breaks (`Physics: Held`).
HELD_BIT = 0x80000000


def segments(scene):
    """Segment collections in the scene, by name."""
    found = [c for c in _walk(scene.collection) if c.prism.is_segment]
    return sorted(found, key=lambda c: c.name)


def _walk(collection):
    for c in collection.children:
        yield c
        yield from _walk(c)


def room_segments(scene):
    return [c for c in segments(scene) if c.prism.in_room]


def segment_objects(collection):
    """Every object of a segment with its matrix in the scene; instances of a kit are looked into."""
    def visit(objects, parent):
        for o in objects:
            m = parent @ o.matrix_world
            if o.instance_type == 'COLLECTION' and o.instance_collection:
                c = o.instance_collection
                yield from visit(c.all_objects, m @ Matrix.Translation(-Vector(c.instance_offset)))
            else:
                yield o, m
    return list(visit(collection.all_objects, Matrix.Identity(4)))


def room_length_before(scene, collection):
    return sum(c.prism.length * c.prism.repeat for c in room_segments(scene) if c.name < collection.name)


def surface_of(obj):
    for slot in obj.material_slots:
        if slot.material:
            return slot.material.name
    return None


def _box_of(obj, m):
    """Centre, half extents and rotation of a box object, without going through a matrix when it has no rotation: numbers stay exact."""
    corners = [Vector(c) for c in obj.bound_box]
    lo = Vector(min(c[i] for c in corners) for i in range(3))
    hi = Vector(max(c[i] for c in corners) for i in range(3))
    is_unit = all(abs(lo[i] + 1) < 1e-6 and abs(hi[i] - 1) < 1e-6 for i in range(3))
    q = m.to_quaternion()
    straight = abs(abs(q.w) - 1) < 1e-6
    if is_unit and straight and obj.parent is None and m == obj.matrix_world:
        return tuple(obj.location), tuple(abs(s) for s in obj.scale), True
    scale = m.to_scale()
    half = [(hi[i] - lo[i]) / 2 * abs(scale[i]) for i in range(3)]
    center = m @ ((lo + hi) / 2)
    return tuple(center), tuple(half), straight


def _rot_attr(obj, m):
    if obj.prism.has_game_rot:
        was = M.game_euler_to_rotation(tuple(obj.prism.game_rot)).to_quaternion()
        if abs(abs(was.dot(m.to_quaternion())) - 1) < 1e-6:
            return obj.prism.game_rot_text
    rot = M.rotation_to_game_euler(m)
    return M.words(rot) if any(abs(v) > 1e-6 for v in rot) else None


def _attrs(pairs):
    return " ".join(f"{k}={quoteattr(str(v))}" for k, v in pairs if v is not None)


def segment_xml(collection, visual_file):
    """The text of the segment file, and the meshes for its visual file (in the game's axes, by surface)."""
    origin = Vector((0, collection.prism.origin_y, 0))
    size = f"12 10 {M.number(collection.prism.length)}"
    lines = []
    meshes = {}
    objects = sorted(segment_objects(collection), key=lambda p: (p[0].prism.order, p[0].name))
    # Bodies by group, numbered from 1 in file order: the game makes one body of each.
    groups = {}
    for o, m in objects:
        p = o.prism
        # The parts and joints of an obstacle built here are in its script.
        if p.kind == 'IGNORE' or built.owner(o) is not None:
            continue
        if o.type == 'LIGHT':
            if o.data.type in ('POINT', 'SPOT') and not o.hide_render:
                lines.append(_light_xml(o, m, origin))
            continue
        if p.kind == 'VISUAL':
            if o.type == 'MESH':
                if p.physics in ('BODY', 'HELD'):
                    group = p.body_group or "\0" + o.name
                    body = groups.setdefault(group, len(groups) + 1)
                    # The high bit: it stands until it breaks.
                    _add_mesh(meshes, o, m, origin, body=body | (HELD_BIT if p.physics == 'HELD' else 0))
                else:
                    _add_mesh(meshes, o, m, origin)
                if p.physics == 'STATIC':
                    # What it stands in, for balls and bodies: a box without a surface of its own, never drawn.
                    center, half, straight = _box_of(o, m)
                    pos = M.point_to_game((center[0] - origin[0], center[1] - origin[1], center[2] - origin[2]))
                    attrs = [("size", M.words(M.half_to_game(half))), ("pos", M.words(pos))]
                    if not straight:
                        attrs.append(("rot", _rot_attr(o, m)))
                    attrs.append(("visible", "0"))
                    lines.append(f"\t<box {_attrs(attrs)}/>")
            continue
        if p.kind in ('BOX', 'COLLIDER') and o.type == 'MESH':
            center, half, straight = _box_of(o, m)
            pos = M.point_to_game((center[0] - origin[0], center[1] - origin[1], center[2] - origin[2]))
            visible = p.kind == 'BOX' and straight
            surface = surface_of(o)
            attrs = [("size", M.words(M.half_to_game(half))), ("pos", M.words(pos))]
            if not straight:
                attrs.append(("rot", _rot_attr(o, m)))
                # Only straight boxes are drawn as boxes.
                if p.kind == 'BOX':
                    _add_mesh(meshes, o, m, origin)
            if not visible:
                attrs.append(("visible", "0"))
            elif surface:
                attrs.append(("surface", surface))
            material = o.material_slots[0].material if o.material_slots else None
            if material:
                if material.prism.friction != 1:
                    attrs.append(("friction", M.number(material.prism.friction)))
                if material.prism.restitution != 0:
                    attrs.append(("restitution", M.number(material.prism.restitution)))
            lines.append(f"\t<box {_attrs(attrs)}/>")
        elif p.kind in ('OBSTACLE', 'POWERUP'):
            pos = M.point_to_game(tuple(m.translation - origin) if m != o.matrix_world or o.parent else
                                  (o.location[0] - origin[0], o.location[1] - origin[1], o.location[2] - origin[2]))
            made = p.kind == 'OBSTACLE' and built.is_built(o)
            attrs = [("type", built.type_name(bpy.context.scene, o) if made else p.type), ("pos", M.words(pos))]
            if not (p.difficulty[0] == 0 and p.difficulty[1] == 1):
                attrs.append(("difficulty", M.words(p.difficulty)))
            if p.kind == 'OBSTACLE':
                attrs.append(("rot", _rot_attr(o, m)))
                if p.mode != 255:
                    attrs.append(("mode", str(p.mode)))
                for i, param in enumerate(() if made else p.params):
                    attrs.append((f"param{i}", param.value))
            lines.append(f"\t<{p.kind.lower()} {_attrs(attrs)}/>")
    head = [("size", size)]
    if meshes:
        head.append(("visual", visual_file))
    text = f"<segment {_attrs(head)}>\n" + "\n".join(lines) + ("\n" if lines else "") + "</segment>\n"
    return text, meshes


def _light_xml(o, m, origin):
    intensity = o.data.energy * WATTS_TO_INTENSITY
    radius = o.prism.light_radius or math.sqrt(intensity / LIGHT_FADED)
    attrs = [("pos", M.words(M.point_to_game(tuple(m.translation - origin)))), ("color", M.words(M.rounded(o.data.color, 4))),
             ("intensity", M.number(round(intensity, 3))), ("radius", M.number(round(radius, 3))), ("source", M.number(round(o.data.shadow_soft_size, 3)))]
    if abs(o.data.specular_factor - 1) > 1e-4:
        attrs.append(("specular", M.number(round(o.data.specular_factor, 3))))
    axis = m.to_3x3().normalized() @ Vector((0, 0, 1))
    if o.data.type == 'POINT' and o.prism.light_tube > 0:
        # A tube along the lamp's own Z: from its middle to one end.
        attrs.append(("tube", M.words(M.rounded(M.point_to_game(tuple(axis * o.prism.light_tube / 2)), 4))))
    if o.data.type == 'SPOT':
        # Where it points (its -Z) and the cosine of half its cone.
        attrs.append(("spot", M.words(M.rounded(M.point_to_game(tuple(-axis)), 4) + [round(math.cos(o.data.spot_size / 2), 4)])))
    return f"\t<light {_attrs(attrs)}/>"


def _add_mesh(meshes, obj, m, origin, body=0):
    """Triangles of the evaluated mesh (modifiers applied), one vertex per position and normal. A body's are its own meshes."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    normal_matrix = m.to_3x3().inverted_safe().transposed()
    corner = mesh.corner_normals
    fallback = surface_of(obj) or "frame"
    names = [s.material.name if s.material else fallback for s in obj.material_slots] or [fallback]
    world = [m @ v.co for v in mesh.vertices]
    uv_layer = mesh.uv_layers.active.uv if mesh.uv_layers.active else None
    for tri in mesh.loop_triangles:
        name = names[min(tri.material_index, len(names) - 1)]
        # The game's indices are 16 bits: a large mesh goes in parts.
        base = f"{name}@{obj.name}" if body else name
        part, key_part = 1, base
        while key_part in meshes and len(meshes[key_part]["positions"]) // 3 > MAX_VERTICES_PER_PART:
            part += 1
            key_part = f"{base}#{part}"
        out = meshes.setdefault(key_part, {"surface": name, "positions": [], "normals": [], "uvs": [], "indices": [], "seen": {}, "body": body})
        corners = list(zip(tri.loops, tri.vertices))
        # The game draws only fronts: two sides are two triangles, back to back.
        for corner_order, sign in ((corners, 1), (corners[::-1], -1)) if obj.prism.two_sided else ((corners, 1),):
            for li, vi in corner_order:
                co = world[vi] - origin
                n = (normal_matrix @ corner[li].vector).normalized() * sign
                p = M.rounded(M.point_to_game(co), 4)
                g = M.rounded(M.point_to_game(n), 4)
                # v runs down the image in the game.
                t = M.rounded((uv_layer[li].vector[0], 1 - uv_layer[li].vector[1]), 4) if uv_layer else [0.0, 0.0]
                key = (*p, *g, *t)
                index = out["seen"].get(key)
                if index is None:
                    index = len(out["positions"]) // 3
                    out["seen"][key] = index
                    out["positions"] += p
                    out["normals"] += g
                    out["uvs"] += t
                out["indices"].append(index)
    evaluated.to_mesh_clear()


def visual_bytes(meshes):
    """See `SegmentDef.Visual` in the game."""
    def block(fmt, values):
        data = struct.pack(f"<{len(values)}{fmt}", *values)
        return data + b"\0" * (-len(data) % 4)

    out = [b"PVIS", struct.pack("<I", len(meshes))]
    for key in sorted(meshes):
        mesh = meshes[key]
        material = bpy.data.materials.get(mesh["surface"])
        has_uvs = bool(material and (material.prism.map or material.prism.data_map))
        name = mesh["surface"].encode()
        out += [struct.pack("<I", len(name)), name + b"\0" * (-len(name) % 4),
                struct.pack("<III", len(mesh["positions"]) // 3, len(mesh["indices"]), int(has_uvs)),
                block("f", mesh["positions"]), block("f", mesh["normals"])]
        if has_uvs:
            out.append(block("f", mesh["uvs"]))
        out.append(block("H", mesh["indices"]))
    # Which body each mesh belongs to (0: the room's), only where there are bodies: other files stay as they were.
    if any(meshes[key].get("body", 0) for key in meshes):
        out += [b"BODS", struct.pack(f"<{len(meshes)}I", *(meshes[key].get("body", 0) for key in sorted(meshes)))]
    return b"".join(out)


def _principled(material):
    if material.use_nodes and material.node_tree:
        for n in material.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                return n
    return None


def surface_json(material):
    p = material.prism
    bsdf = _principled(material)
    if bsdf:
        color = bsdf.inputs["Base Color"].default_value
        roughness = bsdf.inputs["Roughness"].default_value
        metallic = bsdf.inputs["Metallic"].default_value
        emissive = bsdf.inputs["Emission Strength"].default_value
    else:
        color, roughness, metallic, emissive = material.diffuse_color, material.roughness, material.metallic, 0
    s = {"color": M.color_to_game(color), "roughness": round(float(roughness), 4)}
    if metallic > 0:
        s["metallic"] = round(float(metallic), 4)
    if emissive > 0:
        s["emissive"] = round(float(emissive), 4)
    if p.detail > 0:
        s["detail"] = round(p.detail, 4)
    if p.large_receiver:
        s["largeReceiver"] = True
    if p.casts:
        s["casts"] = True
    if p.map:
        s["map"] = map_path(p.map)
    if p.data_map:
        s["dataMap"] = map_path(p.data_map)
    if p.shading != "default":
        s["shading"] = p.shading
        s["params"] = M.rounded(p.shading_params, 4)
    if p.is_glass:
        g = {"frost": round(p.frost, 4)}
        if p.relief != "none":
            g.update(relief=p.relief, strength=round(p.relief_strength, 4), density=round(p.relief_density, 3))
        if p.frost_pattern != "all":
            g.update(frostPattern=p.frost_pattern, density=round(p.relief_density, 3))
        for key, value in (("scatter", p.scatter), ("absorption", p.absorption), ("opal", p.opal), ("film", p.film)):
            if value > 0:
                g[key] = round(value, 4)
        s["glass"] = g
    return s


def map_path(image):
    return f"textures/{bpy.path.clean_name(image.name)}.png"


_png_cache = {}


def _png(image):
    """The image's stored values as PNG, with no view transform on the way: maps are data. Encoded once per image."""
    import numpy as np
    key = (image.name, tuple(image.size), image.is_dirty)
    if key in _png_cache and not image.is_dirty:
        return _png_cache[key]
    w, h = image.size
    px = np.zeros(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    rows = (np.clip(px, 0, 1) * 255 + 0.5).astype(np.uint8).reshape(h, w, 4)[::-1]
    raw = b"".join(b"\x00" + rows[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    _png_cache[key] = png
    return png


def sun_of(scene):
    for o in scene.objects:
        if o.type == 'LIGHT' and o.data.type == 'SUN' and not o.hide_render:
            return o
    return None


def used_materials():
    return sorted((m for m in bpy.data.materials if m.users > 0 and not m.is_grease_pencil), key=lambda m: m.name)


def look_dict(scene):
    p = scene.prism
    sun = sun_of(scene)
    if sun:
        towards = (sun.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        direction, color, intensity = M.rounded(M.point_to_game(towards)), M.color_to_game(sun.data.color), round(sun.data.energy, 4)
    else:
        direction, color, intensity = [0, 1, 0], [1, 1, 1], 0
    view = {"far": round(p.far, 3), "drawDistance": round(p.draw_distance, 3)} if p.far != 100 or p.draw_distance != 40 else None
    out = {
        "surfaces": {m.name: surface_json(m) for m in used_materials()},
        "fog": {"start": round(p.fog_start, 4), "distance": round(p.fog_distance, 4), "lower": M.rounded(p.fog_lower, 4), "upper": M.rounded(p.fog_upper, 4),
                "heightDensity": round(p.height_density, 4), "heightFalloff": round(p.height_falloff, 4), "heightColor": M.rounded(p.height_color, 6)},
        "sun": {"direction": direction, "color": color, "intensity": intensity,
                "shadowRadius": round(p.shadow_radius, 4), "shadowSoftness": round(p.shadow_softness, 4)},
        "ambient": {"sky": M.rounded(p.ambient_sky, 6), "ground": M.rounded(p.ambient_ground, 6), "groundShade": M.rounded(p.ground_shade, 4),
                    "aoStrength": round(p.ao_strength, 4), "aoRadius": round(p.ao_radius, 4)},
        "image": {"exposure": round(p.exposure, 4), "grade": p.grade, "vignette": round(p.vignette, 4), "specularFilter": round(p.specular_filter, 4)},
        "glass": {"dispersion": round(p.glass_dispersion, 4), "noise": round(p.glass_noise, 4)},
        "softboxes": [{"direction": M.rounded(b.direction), "up": M.rounded(b.up), "size": M.rounded(b.size), "color": M.rounded(b.color), "softness": round(b.softness, 4)}
                      for b in p.softboxes],
        "bloom": {"intensity": round(p.bloom_intensity, 4), "threshold": round(p.bloom_threshold, 4)},
        "reflections": {"traceScale": int(p.trace_scale), "roughSteps": round(p.rough_steps, 4), "maxDistance": round(p.max_distance, 4), "sparseBlur": round(p.sparse_blur, 4)},
    }
    if view:
        out["view"] = view
    effects = {}
    if not p.near_blur_on:
        effects["nearBlur"] = [-10, 0.001]
    if p.tinted_sun:
        effects["tintedSun"] = True
        if p.tint_in == 'RAYS':
            effects["tintedSunAir"] = True
    if p.gobo != "none":
        effects["gobo"] = {"kind": p.gobo, "strength": round(p.gobo_strength, 4), "scale": round(p.gobo_scale, 4), "drift": round(p.gobo_drift, 4), "layer": round(p.gobo_layer, 4)}
    if p.matte_reflection > 0 or p.colour_bounce > 0:
        effects["matte"] = [round(p.matte_reflection, 4), round(p.colour_bounce, 4)]
    if p.lamp_halo > 0:
        effects["halo"] = round(p.lamp_halo, 4)
    if p.shafts:
        effects["shafts"] = {"density": round(p.shaft_density, 5), "falloff": round(p.shaft_falloff, 4), "base": round(p.shaft_base, 4), "reach": round(p.shaft_reach, 3),
                             "anisotropy": round(p.shaft_anisotropy, 3), "ambient": M.rounded(p.shaft_ambient, 4), "ambientShare": round(p.shaft_ambient_share, 4),
                             "noise": round(p.shaft_noise, 3), "noiseScale": round(p.shaft_noise_scale, 4)}
    if effects:
        out["effects"] = effects
    if p.fog_glow_tightness > 0:
        out["fog"]["glow"] = [*M.rounded(p.fog_glow, 4), round(p.fog_glow_tightness, 3)]
    if p.camera_lamps:
        out["cameraLamps"] = [{"offset": M.rounded(l.offset, 3), "color": M.rounded(l.color, 4), "intensity": round(l.intensity, 3), "radius": round(l.radius, 3), "source": round(l.source, 3)}
                              for l in p.camera_lamps]
    if any(abs(a - b) > 1e-6 for a, b in zip(p.glow, (1, 1, 1, 0.2))):
        out["glow"] = M.rounded(p.glow, 4)
    return out


def look_json(scene):
    return json.dumps(look_dict(scene), indent=1, sort_keys=True) + "\n"


def room_lua(scene):
    p = scene.prism
    lines = ["-- Written by the Prism add-on from " + (os.path.basename(bpy.data.filepath) or "an unsaved scene") + ": change it there.",
             "function init()", f'\tmgMusic("{p.music}")', "\tlocal l = 0"]
    lines += [f'\tl = l + mgSegment("{c.name}", -l)' for c in room_segments(scene) for _ in range(c.prism.repeat)]
    lines += ["\tmgLength(l)", "end", "", "function tick()", "end", ""]
    return "\n".join(lines)


# Where a still scene's camera orbits when its focus distance was left at zero.
SHOWCASE_FOCUS = 5


# A rule of the scene, its name in the level's file (GameRules.init(attributes:) in the game).
RULES = (("rule_start_balls", "startBalls"), ("rule_crash_penalty", "crashBallPenalty"), ("rule_crash_grace", "crashGraceTime"),
         ("rule_streak_tier", "streakTier"), ("rule_powerup_duration", "powerupDuration"), ("rule_powerup_stack", "powerupStackSize"),
         ("rule_frenzy_interval", "frenzyShotInterval"), ("rule_slow_motion", "slowMotionScale"), ("rule_ball_speed", "ballSpeed"))


def rules_xml(scene):
    """`<rules .../>` of what is not the game's own value, or nothing."""
    p = scene.prism
    own = []
    for prop, name in RULES:
        value, default = getattr(p, prop), p.bl_rna.properties[prop].default
        if abs(value - default) > 1e-6:
            own.append(f'{name}="{M.number(value)}"')
    return "\t<rules " + " ".join(own) + "/>" if own else None


def level_xml(scene):
    p = scene.prism
    length = sum(c.prism.length * c.prism.repeat for c in room_segments(scene))
    lines = [f'\t<room type={quoteattr(p.room)} length="{int(round(length))}"/>']
    rules = rules_xml(scene)
    if rules:
        lines.append(rules)
    view = showcase_view(scene)
    if view:
        eye, target, fov = view
        lines.append(f'\t<view eye="{M.words(eye)}" target="{M.words(target)}" fov="{M.number(fov)}"/>')
    return "<level>\n" + "\n".join(lines) + "\n</level>\n"


def showcase_view(scene):
    """A still scene: where its camera starts, the point it orbits (its focus) and its horizontal angle, in the game's axes."""
    camera = scene.camera
    if not scene.prism.showcase or camera is None or camera.type != 'CAMERA':
        return None
    m = camera.matrix_world.normalized()
    eye = m.to_translation()
    ahead = (m.to_3x3() @ Vector((0, 0, -1))).normalized()
    focus = camera.data.dof.focus_distance or SHOWCASE_FOCUS
    target = eye + ahead * focus
    return (tuple(round(x, 4) for x in M.point_to_game(eye)), tuple(round(x, 4) for x in M.point_to_game(target)), round(math.degrees(camera.data.angle_x), 3))


def files(scene):
    """Everything to write: path relative to the content root -> text."""
    out = {}
    for c in segments(scene):
        visual = c.name + ".visual"
        xml, meshes = segment_xml(c, visual)
        out[f"segments/{c.name}.xml"] = xml
        if meshes:
            out[f"segments/{visual}"] = visual_bytes(meshes)
        # The scripts of the obstacles built in the scene, and the convex meshes they name.
        for o, _ in segment_objects(c):
            if built.is_built(o):
                out.update(built.build(scene, o)[1])
    p = scene.prism
    out[f"looks/{p.room}.json"] = look_json(scene)
    for m in used_materials():
        for image in (m.prism.map, m.prism.data_map):
            if image:
                out[map_path(image)] = _png(image)
    if p.generate_room:
        out[f"rooms/{p.room}.lua"] = room_lua(scene)
        out[f"levels/{p.level}.xml"] = level_xml(scene)
    return out


def write(target, texts):
    """Only what differs is touched. Returns the paths written."""
    written = []
    for rel, text in sorted(texts.items()):
        path = os.path.join(target, rel)
        if os.path.exists(path):
            with open(path, "rb") as f:
                if f.read() == (text if isinstance(text, bytes) else text.encode()):
                    continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(text if isinstance(text, bytes) else text.encode())
        written.append(rel)
    return written
