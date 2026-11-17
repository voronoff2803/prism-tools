"""Obstacles built in Blender, without a script written by hand.

An Empty of kind Obstacle that has children is built from them, and its script is written here:

* a mesh child is a **part**: a body of the obstacle. A mesh parented to a part is one more shape of that part's body
  (glass in its frame); every loose piece of a mesh is a convex shape of its own. Glass is a material with Glass ticked;
  anything else is steel.
* a part **moves** as its Motion says: stands (Fixed), falls and hangs (Free), follows its keyframes (Animated), turns
  (Spin), or waits for the camera and is pushed (Launch).
* an Empty child of kind Joint, parented to a part, **holds** it: a pin, a hinge, a slider or a rope, to another part or
  to the room.

Everything is said in the obstacle's own frame (the Empty's), in the game's axes; the script's calls are those of
Docs/Scripting.md, as the game's own obstacles use them.
"""
import math
import re

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from . import mapping as M

# The game's updates a second: an animation is sampled at them.
RATE = 60
# Longer animations are cut: a minute of poses is the script's size already.
MAX_SAMPLES = 60 * RATE
# Corners of a convex shape: more make every contact slower and look no different.
MAX_HULL_POINTS = 48
# Half the thickness a pane drawn as a plane gets.
PANE_HALF = 0.02
CLEAN = re.compile(r"[^A-Za-z0-9_\-.]")


def owner(obj):
    """The built obstacle this object is a part or a joint of; None for the obstacle itself and for anything else."""
    o = obj.parent
    while o is not None:
        if o.type == 'EMPTY' and o.prism.kind == 'OBSTACLE':
            return o
        o = o.parent
    return None


def descendants(obj):
    for child in sorted(obj.children, key=lambda c: c.name):
        yield child
        yield from descendants(child)


def parts(empty):
    return [o for o in descendants(empty) if o.type == 'MESH' and o.prism.kind != 'IGNORE']


def joints(empty):
    return [o for o in descendants(empty) if o.type == 'EMPTY' and o.prism.kind == 'JOINT']


def is_built(obj):
    return obj.type == 'EMPTY' and obj.prism.kind == 'OBSTACLE' and owner(obj) is None and bool(parts(obj))


def root(part):
    """The part whose body this one belongs to: the topmost mesh under the obstacle."""
    o = part
    while o.parent is not None and o.parent.type == 'MESH' and o.parent.prism.kind != 'IGNORE':
        o = o.parent
    return o


def type_name(scene, empty):
    """The obstacle's type in the game: its script is obstacles/<type>.lua."""
    return f"{scene.prism.room}/{CLEAN.sub('_', empty.name)}"


def is_glass(material):
    return bool(material and material.prism.is_glass)


def _color(material):
    if material and material.use_nodes and material.node_tree:
        bsdf = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            return M.color_to_game(bsdf.inputs["Base Color"].default_value)
    return M.color_to_game(material.diffuse_color) if material else [1, 1, 1]


def _n(x):
    """A number as Lua reads it, short: a millimetre and a thousandth of a radian are enough."""
    text = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _words(values):
    return ", ".join(_n(v) for v in values)


def _frame(empty):
    """The obstacle's frame in the scene, without its scale: the script's numbers carry the sizes."""
    loc, rot, _ = empty.matrix_world.decompose()
    return Matrix.LocRotScale(loc, rot, None)


def _pose(local):
    """Position and angles in the game's axes of a matrix said in the obstacle's frame."""
    return list(M.point_to_game(local.translation)) + list(M.rotation_to_game_euler(local))


def _unscaled(m):
    loc, rot, _ = m.decompose()
    return Matrix.LocRotScale(loc, rot, None)


def _islands(mesh):
    """The loose pieces of a mesh: lists of vertex indices."""
    parent = list(range(len(mesh.vertices)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for e in mesh.edges:
        a, b = find(e.vertices[0]), find(e.vertices[1])
        if a != b:
            parent[a] = b
    groups = {}
    for i in range(len(mesh.vertices)):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) >= 4]


def _hull(points):
    """The corners of the convex hull of the points, thinned when there are many."""
    import bmesh
    bm = bmesh.new()
    for p in points:
        bm.verts.new(p)
    result = bmesh.ops.convex_hull(bm, input=bm.verts)
    inside = {v for v in result.get("geom_interior", []) if isinstance(v, bmesh.types.BMVert)}
    corners = [v.co.copy() for v in bm.verts if v not in inside]
    bm.free()
    if len(corners) > MAX_HULL_POINTS:
        step = len(corners) / MAX_HULL_POINTS
        corners = [corners[int(i * step)] for i in range(MAX_HULL_POINTS)]
    return corners


def _flat(mesh, indices):
    """The axis of the mesh these vertices have no extent along, or None: a plane has no inside to be a shape."""
    points = [mesh.vertices[i].co for i in indices]
    extent = [max(p[k] for p in points) - min(p[k] for p in points) for k in range(3)]
    thin = min(range(3), key=lambda k: extent[k])
    return thin if extent[thin] <= 1e-5 * max(max(extent), 1e-9) else None


def _box(mesh, indices, scale):
    """(centre, half) when these eight vertices are a box along the mesh's own axes, or four a rectangle across one of
    them (a pane drawn as a plane: it gets the thickness of glass); None otherwise."""
    points = [mesh.vertices[i].co for i in indices]
    lo = Vector(min(p[k] for p in points) for k in range(3))
    hi = Vector(max(p[k] for p in points) for k in range(3))
    size = max(hi - lo)
    thin = _flat(mesh, indices)
    if len(indices) == 4 and thin is not None and size > 0:
        if len({tuple(round((p[k] - lo[k]) / (hi[k] - lo[k])) for k in range(3) if k != thin) for p in points}) != 4:
            return None
        half = (hi - lo) / 2
        half[thin] = PANE_HALF / max(abs(scale[thin]), 1e-9)
        return (lo + hi) / 2, half
    if len(indices) != 8:
        return None
    if size <= 0 or min(hi - lo) <= 0:
        return None
    for p in points:
        if any(min(abs(p[k] - lo[k]), abs(p[k] - hi[k])) > 1e-4 * size for k in range(3)):
            return None
    if len({tuple(round((p[k] - lo[k]) / (hi[k] - lo[k])) for k in range(3)) for p in points}) != 8:
        return None
    return (lo + hi) / 2, (hi - lo) / 2


def _shapes(part, body_frame, frame):
    """The shapes a part gives its body: ("box", material, smooth, pose in the body, half) or ("hull", material, smooth, points in the body)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = part.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    # The part in its body's frame, both in the obstacle's.
    local = body_frame.inverted() @ frame.inverted() @ part.matrix_world
    slots = [s.material for s in part.material_slots]
    material_of = {}
    for poly in mesh.polygons:
        for v in poly.vertices:
            material_of.setdefault(v, (poly.material_index, poly.use_smooth))
    out = []
    for indices in _islands(mesh):
        slot, smooth = material_of.get(indices[0], (0, False))
        material = slots[slot] if slot < len(slots) else None
        loc, rot, scale = local.decompose()
        box = _box(mesh, indices, scale) if part.prism.part_shape != 'HULL' or len(indices) == 4 else None
        if box:
            centre, half = box
            pose = _pose(Matrix.LocRotScale(local @ centre, rot, None))
            out.append(("box", material, smooth, pose, M.half_to_game([abs(half[k] * scale[k]) for k in range(3)])))
        elif _flat(mesh, indices) is None:
            points = _hull([local @ mesh.vertices[i].co for i in indices])
            if len(points) >= 4:
                out.append(("hull", material, smooth, [M.point_to_game(p) for p in points]))
    evaluated.to_mesh_clear()
    return out


def _fcurves(obj):
    """The curves of the object's action, with Blender's layered actions and the ones before them."""
    data = obj.animation_data
    action = data.action if data else None
    if action is None:
        return []
    if hasattr(action, "layers"):
        slot = getattr(data, "action_slot", None)
        for layer in action.layers:
            for strip in layer.strips:
                bag = strip.channelbag(slot) if slot is not None and hasattr(strip, "channelbag") else None
                if bag is not None:
                    return list(bag.fcurves)
        return []
    return list(action.fcurves)


def is_animated(part):
    return any(c.data_path in ("location", "rotation_euler", "rotation_quaternion") for c in _fcurves(part))


def _samples(part, frame, scene):
    """The part's poses in the obstacle's frame through its animation, one per update of the game. Read from the curves:
    the scene's frame is not touched, so an export while the timeline plays is the same export."""
    curves = [c for c in _fcurves(part) if c.data_path in ("location", "rotation_euler", "rotation_quaternion")]
    if not curves:
        return []
    start = min(c.range()[0] for c in curves)
    end = max(c.range()[1] for c in curves)
    fps = scene.render.fps / scene.render.fps_base
    count = min(max(int(round((end - start) / fps * RATE)), 1), MAX_SAMPLES)
    by = {(c.data_path, c.array_index): c for c in curves}

    def value(path, index, at, otherwise):
        c = by.get((path, index))
        return c.evaluate(at) if c else otherwise
    above = (part.parent.matrix_world if part.parent else Matrix.Identity(4)) @ part.matrix_parent_inverse
    poses = []
    before = None
    for k in range(count + 1):
        at = start + k / RATE * fps
        loc = Vector(value("location", i, at, part.location[i]) for i in range(3))
        if part.rotation_mode == 'QUATERNION':
            rot = Quaternion([value("rotation_quaternion", i, at, part.rotation_quaternion[i]) for i in range(4)]).normalized()
        else:
            rot = Euler([value("rotation_euler", i, at, part.rotation_euler[i]) for i in range(3)], part.rotation_mode).to_quaternion()
        local = frame.inverted() @ above @ Matrix.LocRotScale(loc, rot, None)
        r = (M.TO_GAME @ _unscaled(local).to_quaternion().to_matrix().to_4x4() @ M.TO_BLENDER).to_3x3()
        # Angles that go on from the last ones: the script reads between two poses.
        e = r.to_euler('ZYX', before) if before is not None else r.to_euler('ZYX')
        before = e
        poses.append(list(M.point_to_game(local.translation)) + [e.x, e.y, e.z])
    return poses


HELPERS = '''
-- A pose of an animation at sample t, read between the two beside it.
local function pose(frames, t, mode)
	local n = #frames - 1
	if mode == "once" then
		t = math.min(t, n)
	elseif mode == "pingpong" then
		t = t % (2 * n)
		if t > n then t = 2 * n - t end
	else
		t = t % n
	end
	local i = math.min(math.floor(t), n - 1)
	local f = t - i
	local a, b = frames[i + 1], frames[i + 2]
	return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f,
		a[4] + (b[4] - a[4]) * f, a[5] + (b[5] - a[5]) * f, a[6] + (b[6] - a[6]) * f
end
'''


def build(scene, empty):
    """(type, files): the obstacle's script and the convex meshes it names, path -> text."""
    name = type_name(scene, empty)
    frame = _frame(empty)
    roots = [p for p in parts(empty) if root(p) is p]
    index = {r.name: i + 1 for i, r in enumerate(roots)}
    files = {}
    init = []
    tick = []
    tables = []
    glass_bodies = []
    glass_centre = None
    uses_pose = False

    # Where the ropes end, before any body is there to be hit by their rays.
    ropes = []
    for j in joints(empty):
        part = j.parent if j.parent is not None and j.parent.type == 'MESH' else None
        if part is None or root(part).name not in index:
            continue
        local = frame.inverted() @ j.matrix_world
        at = M.point_to_game(local.translation)
        axis = M.point_to_game((local.to_3x3() @ Vector((0, 0, 1))).normalized())
        a = index[root(part).name]
        to = j.prism.joint_to
        b = index.get(root(to).name, 0) if to is not None and to.type == 'MESH' and owner(to) is empty else 0
        other = f"bodies[{b}]" if b else "0"
        kind = j.prism.joint_type
        if kind == 'ROPE':
            k = len(ropes) + 1
            ropes.append(j)
            length = j.prism.joint_length
            far = [at[i] + axis[i] * (length if length > 0 else 100) for i in range(3)]
            init.append(f"\t-- rope \"{j.name}\"")
            if length > 0:
                init.append(f"\tlocal x{k}, y{k}, z{k} = {_words(far)}")
            else:
                # The room only: its walls, floor and ceiling.
                init.append(f"\tlocal hit{k}, x{k}, y{k}, z{k} = mgRaycast({_words(at)}, {_words(far)}, 128)")
                init.append(f"\tif not hit{k} then x{k}, y{k}, z{k} = {_words([at[i] + axis[i] * 3 for i in range(3)])} end")
            tables.append((j, f"\tmgCreateRope(bodies[{a}], {other}, {_words(at)}, x{k}, y{k}, z{k}, {_n(j.prism.joint_slack)})"))
        elif kind == 'PIN':
            tables.append((j, f"\tmgCreateBallJoint(bodies[{a}], {other}, {_words(at)})"))
        else:
            call = "mgCreateHingeJoint" if kind == 'HINGE' else "mgCreateSliderJoint"
            tables.append((j, f"\t{call}(bodies[{a}], {other}, {_words(at)}, {_words(axis)})"))

    init.append("\tbodies = {}")
    animations = []
    for r in roots:
        i = index[r.name]
        p = r.prism
        motion = p.part_motion
        samples = _samples(r, frame, scene) if motion == 'ANIMATED' else []
        if motion == 'ANIMATED' and not samples:
            motion = 'FIXED'
        local = _unscaled(frame.inverted() @ r.matrix_world)
        home = samples[0] if samples else _pose(local)
        # The body's frame as the shapes are said in: where the part stands now.
        init.append(f"\t-- \"{r.name}\": {motion.lower()}")
        init.append(f"\tbodies[{i}] = mgCreateBody({_words(home)})")
        members = [m for m in parts(empty) if root(m) is r]
        shapes = [s for m in members for s in _shapes(m, local, frame)]
        only_glass = all(is_glass(s[1]) for s in shapes)
        has_glass = any(is_glass(s[1]) for s in shapes)
        hull_count = 0
        for s in shapes:
            kind, material, smooth = s[0], s[1], s[2]
            glass = is_glass(material)
            init.append("\tmgShapeReset()")
            init.append(f"\tmgMaterial(\"{'glass' if glass else 'steel'}\")")
            init.append(f"\tmgColor({_words(_color(material))})")
            if glass:
                init.append(f"\tmgForceLimit({_n(p.part_strength)})")
            if smooth:
                init.append("\tmgRoundness(1)")
            if motion == 'FIXED':
                # Steel stands for good; glass alone stands until it breaks; glass in a frame breaks out of it.
                init.append(f"\tmgStatic({3 if glass and only_glass else 0 if glass else 1})")
            if kind == "box":
                pose, half = s[3], s[4]
                init.append(f"\tmgShapeChamfer({_n(0 if glass else p.part_bevel)})")
                init.append(f"\tmgCreateBox(bodies[{i}], {_words(half)}, {_words(pose)})")
            else:
                hull_count += 1
                mesh_name = f"{name}_{i}_{hull_count}"
                files[f"meshes/{mesh_name}.xml"] = "<convex>" + "".join(f"<v>{' '.join(_n(c) for c in v)}</v>" for v in s[3]) + "</convex>\n"
                init.append(f"\tmgCreateMesh(bodies[{i}], \"{mesh_name}\")")
        if has_glass:
            glass_bodies.append(i)
            if glass_centre is None:
                glass_centre = home[:3]
        if motion == 'ANIMATED':
            uses_pose = True
            animations.append(f"local frames{i} = {{" + ",".join("{" + ",".join(_n(v) for v in s) + "}" for s in samples) + "}")
            mode = p.anim_loop.lower()
            init.append(f"\tmgMove(bodies[{i}], {_words(home[:3])})")
            init.append(f"\tmgRotate(bodies[{i}], {_words(home[3:])})")
            if p.trigger > 0:
                tick.append(f"\tif not started{i} and mgCameraDistance() < {_n(p.trigger)} then started{i} = mgObstacleTime() end")
                tick.append(f"\tlocal t{i} = started{i} and (mgObstacleTime() - started{i}) * {RATE} or 0")
            else:
                tick.append(f"\tlocal t{i} = mgObstacleTime() * {RATE}")
            tick.append(f"\tlocal x, y, z, rx, ry, rz = pose(frames{i}, t{i}, \"{mode}\")")
            tick.append(f"\tmgMove(bodies[{i}], x, y, z)")
            tick.append(f"\tmgRotate(bodies[{i}], rx, ry, rz)")
        elif motion == 'SPIN':
            axis = (local.to_3x3() @ Vector({'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[p.spin_axis])).normalized()
            axis = M.point_to_game(axis)
            w = [a * p.spin_speed * 2 * math.pi for a in axis]
            init.append(f"\tmgCreateHingeJoint(bodies[{i}], 0, {_words(home[:3])}, {_words(axis)})")
            tick.append(f"\tmgSetAngVel(bodies[{i}], {_words(w)})")
        elif motion == 'LAUNCH':
            init.append(f"\tmgMove(bodies[{i}], {_words(home[:3])})")
            init.append(f"\tmgRotate(bodies[{i}], {_words(home[3:])})")
            v = M.point_to_game(p.push)
            w = [a * 2 * math.pi for a in M.point_to_game(p.push_spin)]
            tick.append(f"\tif not launched{i} and mgCameraDistance() < {_n(p.trigger if p.trigger > 0 else 8)} then")
            tick.append(f"\t\tlaunched{i} = true")
            tick.append(f"\t\tmgReleaseMotion(bodies[{i}])")
            tick.append(f"\t\tmgSetVel(bodies[{i}], {_words(v)})")
            tick.append(f"\t\tmgSetAngVel(bodies[{i}], {_words(w)})")
            tick.append("\tend")

    for j, line in tables:
        init.append(f"\t-- {j.prism.joint_type.lower()} \"{j.name}\"")
        init.append(line)

    balls = empty.prism.balls
    if balls > 0:
        centre = glass_centre or [0, 1, 0]
        init.insert(0, f"\tmgScore({balls})")
        init.insert(1, f"\tmgGlow({_words(centre)})")
    if glass_bodies:
        # Its glass broken is the obstacle done: the balls it gives, and the streak.
        broken = " and ".join(f"mgBodyIsBroken(bodies[{i}])" for i in glass_bodies)
        tick.append(f"\tif not mgIsCleared() and {broken} then mgClear() end")

    text = [f"-- Written by Prism Tools from the obstacle \"{empty.name}\": change it in Blender, not here."]
    if uses_pose:
        text.append(HELPERS.rstrip("\n"))
    text += animations
    text += ["", "function init()"] + init + ["end", "", "function tick()"] + tick + ["end", ""]
    files[f"obstacles/{name}.lua"] = "\n".join(text)
    return name, files


def problems(empty):
    """(severity, where, what) of a built obstacle."""
    out = []
    for j in joints(empty):
        if j.parent is None or j.parent.type != 'MESH':
            out.append(('ERROR', j.name, "A joint is the child of the part it holds: parent it to that mesh"))
        elif j.prism.joint_to is not None and (j.prism.joint_to.type != 'MESH' or owner(j.prism.joint_to) is not empty):
            out.append(('ERROR', j.name, "A joint holds to a part of its own obstacle, or to the room when 'To' is empty"))
        elif j.prism.joint_to is not None and root(j.prism.joint_to) is root(j.parent):
            out.append(('ERROR', j.name, "Both ends of the joint are one body"))
    frame = _frame(empty)
    for p in parts(empty):
        if not _shapes(p, Matrix.Identity(4), frame):
            out.append(('ERROR', p.name, "Nothing of this part is a shape: a mesh without thickness or without faces. Give it one (Solidify)"))
        if root(p) is not p:
            continue
        if p.prism.part_motion == 'ANIMATED' and not is_animated(p):
            out.append(('WARNING', p.name, "Motion is Animated, and it has no keyframes of location or rotation: it stands"))
        if p.prism.part_motion == 'SPIN' and p.prism.spin_speed == 0:
            out.append(('WARNING', p.name, "Motion is Spin at 0 turns a second"))
        if p.prism.part_motion == 'FREE' and not any(j.parent is not None and root(j.parent) is p or
                                                     (j.prism.joint_to is not None and root(j.prism.joint_to) is p) for j in joints(empty)):
            out.append(('WARNING', p.name, "Motion is Free and nothing holds it: it falls as soon as the obstacle appears"))
    return out
