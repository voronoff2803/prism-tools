"""What would go wrong in the game, said while it is still in the editor. Errors stop an export, warnings do not."""
import os
import re

from mathutils import Vector

from . import built, exporter, project

# Budgets of a segment on the phone; a guess until a level shows otherwise.
MAX_TRIANGLES_PER_SEGMENT = 30000
MAX_CASTER_TRIANGLES_PER_SEGMENT = 8000
MAX_LAMPS_PER_SEGMENT = 4
# A room lasts one music loop of 32 s: this is the camera's speed in another form.
MIN_ROOM_LENGTH, MAX_ROOM_LENGTH = 100, 450
# PowerupType in the game.
POWERUPS = {"balls", "barrel", "slowmotion", "multiball", "ballfrenzy", "nitroballs", "freebie", "antigravity", "rewind", "shield", "homing"}
NAME = re.compile(r"^[A-Za-z0-9_\-./]+$")
OUTSIDE_SHOWN = 5


def refusal(scene):
    """Why the scene cannot go to the game, said with its first error; None when it can."""
    errors = [(where, what) for level, where, what in check(scene) if level == 'ERROR']
    if not errors:
        return None
    more = f" (and {len(errors) - 1} more in the Problems panel)" if len(errors) > 1 else ""
    return f"{errors[0][0]}: {errors[0][1]}{more}"


def check(scene):
    """(severity, where, what), most important first."""
    out = []
    add = lambda level, where, what: out.append((level, where, what))
    p = scene.prism
    if not NAME.match(p.room) or not NAME.match(p.level):
        add('ERROR', "Scene", "Room and level names: latin letters, digits, _ - . /")

    lamps = [o for o in scene.objects if o.type == 'LIGHT' and not o.hide_render]
    suns = [o for o in lamps if o.data.type == 'SUN']
    in_segments = {o for c in exporter.segments(scene) for o in c.all_objects}
    for o in lamps:
        if o.data.type not in ('SUN', 'POINT', 'SPOT'):
            add('ERROR', o.name, f"{o.data.type} lamp: the game has one sun, point lamps (tubes too) and spots")
    # Nothing goes wrong in the game with these: they are only not there.
    outside = [o for o in scene.objects if o not in in_segments and o.prism.kind != 'IGNORE' and not o.hide_render
               and (o.type == 'MESH' or o in lamps and o.data.type in ('POINT', 'SPOT')
                    or o.type == 'EMPTY' and o.prism.kind in ('OBSTACLE', 'POWERUP'))]
    for o in outside[:OUTSIDE_SHOWN]:
        add('WARNING', o.name, "Outside the segments, so not in the game: move it into a segment's collection, or Kind: Ignore")
    if len(outside) > OUTSIDE_SHOWN:
        add('WARNING', "Scene", f"{len(outside) - OUTSIDE_SHOWN} more objects outside the segments")
    if len(suns) > 1:
        add('ERROR', suns[1].name, "A second sun: the game has one")
    if not suns and not any(o.data.type in ('POINT', 'SPOT') for o in lamps):
        add('WARNING', "Scene", "No lamps: only ambient light and what glows")
    if len(p.softboxes) > 4:
        add('ERROR', "Scene", "More than 4 softboxes")

    for m in exporter.used_materials():
        if not m.use_nodes or not any(n.type == 'BSDF_PRINCIPLED' for n in m.node_tree.nodes):
            add('WARNING', m.name, "No Principled BSDF: the colour of the viewport display is used")
        elif any(n.type == 'TEX_IMAGE' for n in m.node_tree.nodes) and not m.prism.map:
            add('WARNING', m.name, "Image in the nodes: only the maps of the Prism panel reach the game")
        if not NAME.match(m.name):
            add('ERROR', m.name, "Material name: latin letters, digits, _ - . /")

    segs = exporter.segments(scene)
    if not segs:
        add('ERROR', "Scene", "No segments: mark a collection as a segment")
    origin = 0.0
    for c in exporter.room_segments(scene):
        if abs(c.prism.origin_y - origin) > 1e-3:
            add('WARNING', c.name, f"Starts at {c.prism.origin_y:.3f} m, the room has it at {origin:.3f} m: 'Lay out segments'")
        origin += c.prism.length * c.prism.repeat
    if p.generate_room:
        length = origin
        if length < MIN_ROOM_LENGTH or length > MAX_ROOM_LENGTH:
            add('WARNING', "Scene", f"Room of {length:.0f} m: a room lasts 32 s, that is {length / 32:.1f} m/s (the game runs 4-12)")
        if not project.exists_in_content(f"music/{p.music}.ogg"):
            add('ERROR', "Scene", f"No music/{p.music}.ogg")
    for c in segs:
        _check_segment(c, add)
    order = {'ERROR': 0, 'WARNING': 1}
    return sorted(out, key=lambda r: order[r[0]])


def _triangles(obj):
    import bpy
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    n = sum(len(poly.vertices) - 2 for poly in mesh.polygons)
    evaluated.to_mesh_clear()
    return n


def _check_segment(c, add):
    if not NAME.match(c.name):
        add('ERROR', c.name, "Segment name: latin letters, digits, _ - . /")
    tris = casters = colliders = lamps = 0
    y0, y1 = c.prism.origin_y, c.prism.origin_y + c.prism.length
    for o, m in exporter.segment_objects(c):
        p = o.prism
        if p.kind == 'IGNORE':
            continue
        if built.owner(o) is not None:
            # A part or a joint of an obstacle built here: the obstacle answers for it.
            if o.type == 'LIGHT':
                add('WARNING', o.name, "A lamp inside a built obstacle is not in the game: parent it to nothing")
            continue
        if built.is_built(o):
            for problem in built.problems(o):
                add(*problem)
            continue
        if o.type == 'EMPTY' and p.kind == 'JOINT':
            add('WARNING', o.name, "A joint outside a built obstacle does nothing: parent it to a part of one")
            continue
        if o.type == 'MESH':
            if p.kind in ('BOX', 'COLLIDER'):
                colliders += 1
                if m.determinant() < 0:
                    add('ERROR', o.name, "Negative scale on a box")
                if len(o.data.vertices) != 8:
                    add('WARNING', o.name, "Collides as its bounding box: only boxes collide")
            if p.kind in ('VISUAL', 'BOX'):
                n = _triangles(o) * (2 if p.two_sided else 1)
                tris += n
                if not o.material_slots or not any(s.material for s in o.material_slots):
                    add('WARNING', o.name, "No material: drawn as 'frame'")
                elif any(s.material and s.material.prism.casts for s in o.material_slots):
                    casters += n
                ys = [(m @ Vector(b)).y for b in o.bound_box]
                # Half a metre of slack: a frame may lap over a joint.
                if c.prism.warn_beyond and (min(ys) < y0 - 0.5 or max(ys) > y1 + 0.5):
                    add('WARNING', o.name, f"Beyond the ends of the segment ({y0:.1f}...{y1:.1f} m): it pops in with the next")
        elif o.type == 'EMPTY' and p.kind in ('OBSTACLE', 'POWERUP'):
            if not p.type:
                add('ERROR', o.name, f"{p.kind.capitalize()} without a type")
            elif p.kind == 'OBSTACLE' and not project.exists_in_content(f"obstacles/{p.type}.lua"):
                add('ERROR', o.name, f"No obstacles/{p.type}.lua")
            elif p.kind == 'POWERUP' and p.type not in POWERUPS:
                add('WARNING', o.name, f"Powerup '{p.type}' is not one of the game's")
            for param in p.params:
                if "=" not in param.value:
                    add('ERROR', o.name, f"Parameter '{param.value}': expected key=value")
        elif o.type == 'MESH' and p.kind in ('OBSTACLE', 'POWERUP'):
            add('ERROR', o.name, "An obstacle or powerup is an Empty")
        if o.type == 'LIGHT' and o.data.type in ('POINT', 'SPOT'):
            lamps += 1
    if lamps > MAX_LAMPS_PER_SEGMENT:
        add('WARNING', c.name, f"{lamps} point lamps, budget {MAX_LAMPS_PER_SEGMENT}: each one lights its whole reach every frame")
    if colliders == 0:
        add('WARNING', c.name, "Nothing collides: balls fall through")
    if tris > MAX_TRIANGLES_PER_SEGMENT:
        add('WARNING', c.name, f"{tris} triangles, budget {MAX_TRIANGLES_PER_SEGMENT}")
    if casters > MAX_CASTER_TRIANGLES_PER_SEGMENT:
        add('WARNING', c.name, f"{casters} triangles in the shadow map, budget {MAX_CASTER_TRIANGLES_PER_SEGMENT}")
