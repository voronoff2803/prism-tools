"""Operators and panels. The sidebar of the viewport (N, tab Prism) has what is used all day."""
import os

import bpy

from . import catalog, exporter, importer, live, project, validate

_problems = []


def _refresh(scene):
    importer.sync_viewport_colors()
    _problems[:] = validate.check(scene)
    return _problems


class PRISM_OT_validate(bpy.types.Operator):
    bl_idname = "prism.validate"
    bl_label = "Check"
    bl_description = "Look for what would go wrong in the game"

    def execute(self, context):
        problems = _refresh(context.scene)
        errors = sum(1 for p in problems if p[0] == 'ERROR')
        self.report({'ERROR' if errors else 'INFO'}, f"{errors} errors, {len(problems) - errors} warnings")
        return {'FINISHED'}


class PRISM_OT_export(bpy.types.Operator):
    bl_idname = "prism.export"
    bl_label = "Export"
    bl_description = "Write the level into Content/: the repository's, or a Content folder beside the .blend"

    def execute(self, context):
        problems = _refresh(context.scene)
        if any(p[0] == 'ERROR' for p in problems):
            self.report({'ERROR'}, "Errors in the Prism panel: nothing written")
            return {'CANCELLED'}
        target = project.content()
        if not target:
            self.report({'ERROR'}, "Save the .blend first: what is exported goes into a Content folder beside it")
            return {'CANCELLED'}
        os.makedirs(target, exist_ok=True)
        written = exporter.write(target, exporter.files(context.scene))
        self.report({'INFO'}, f"{len(written)} files changed" if written else "Nothing changed")
        return {'FINISHED'}


class PRISM_OT_live(bpy.types.Operator):
    bl_idname = "prism.live"
    bl_label = "Live window"
    bl_description = "Open the game beside Blender: the camera follows the viewport, edits arrive as they happen"

    def execute(self, context):
        if live.is_on():
            live.stop()
            return {'FINISHED'}
        message = live.start(context.scene)
        _refresh(context.scene)
        if message:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        return {'FINISHED'}


class PRISM_OT_browser(bpy.types.Operator):
    bl_idname = "prism.browser"
    bl_label = "Browser"
    bl_description = ("Open the game in a browser beside Blender, on any system: the camera follows the viewport, edits arrive as "
                      "they happen. The first time the game is fetched, which takes a while")

    def execute(self, context):
        if live.is_on():
            live.stop()
            return {'FINISHED'}
        message = live.start_browser(context.scene)
        _refresh(context.scene)
        if message:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        return {'FINISHED'}


class PRISM_OT_play(bpy.types.Operator):
    bl_idname = "prism.play"
    bl_label = "Play from here"
    bl_description = "Play the level in the live window from where the viewport is along the corridor"

    @classmethod
    def poll(cls, context):
        return live.is_on()

    def execute(self, context):
        live.play_from_here(context.scene)
        return {'FINISHED'}


class PRISM_OT_back_to_edit(bpy.types.Operator):
    bl_idname = "prism.edit"
    bl_label = "Back to the viewport"

    @classmethod
    def poll(cls, context):
        return live.is_on()

    def execute(self, context):
        live.back_to_edit(context.scene)
        return {'FINISHED'}


class PRISM_OT_layout(bpy.types.Operator):
    bl_idname = "prism.layout"
    bl_label = "Lay out segments"
    bl_description = "Place the segments of the room end to end, as the game does"

    def execute(self, context):
        y = 0.0
        for c in exporter.room_segments(context.scene):
            delta = y - c.prism.origin_y
            if delta:
                for o in c.objects:
                    if o.parent is None:
                        o.location.y += delta
            c.prism.origin_y = y
            y += c.prism.length * c.prism.repeat
        _refresh(context.scene)
        return {'FINISHED'}


class PRISM_OT_new_segment(bpy.types.Operator):
    bl_idname = "prism.new_segment"
    bl_label = "New segment"
    bl_description = "A collection for a new piece of corridor, after the last one"

    name: bpy.props.StringProperty(name="Name", default="new/segment")
    length: bpy.props.FloatProperty(name="Length", default=16, min=0.01, unit='LENGTH')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        importer.prepare_scene(context.scene)
        c = bpy.data.collections.new(self.name)
        importer.root_collection(context.scene).children.link(c)
        c.prism.is_segment = True
        c.prism.length = self.length
        room = [s for s in exporter.room_segments(context.scene) if s != c]
        c.prism.origin_y = sum(s.prism.length * s.prism.repeat for s in room)
        return {'FINISHED'}


class PRISM_OT_import_segment(bpy.types.Operator):
    bl_idname = "prism.import_segment"
    bl_label = "Import segment"
    bl_description = "A segment of the game as a collection: its name as under segments/, without .xml"

    name: bpy.props.StringProperty(name="Name", default="basic/basic/start", search=lambda self, context, text: catalog.segments())

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        data = project.read_base(f"segments/{self.name}.xml")
        if not data:
            self.report({'ERROR'}, f"No segment {self.name}" + ("" if project.root() else
                        ": the game's own are known once the scene has been opened in a browser"))
            return {'CANCELLED'}
        importer.prepare_scene(context.scene)
        importer.import_segment(context.scene, self.name, data, project.read_base("templates.xml") or {})
        return {'FINISHED'}


class PRISM_OT_import_look(bpy.types.Operator):
    bl_idname = "prism.import_look"
    bl_label = "Import look"
    bl_description = "A look of the game into this scene: its light, fog and palette"

    name: bpy.props.StringProperty(name="Room", default="default", search=lambda self, context, text: catalog.looks())

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        data = project.read_base(f"looks/{self.name}.json")
        if not data:
            self.report({'ERROR'}, f"No look {self.name}")
            return {'CANCELLED'}
        importer.prepare_scene(context.scene)
        importer.import_look(context.scene, data)
        return {'FINISHED'}


def _segment_for_new(context):
    """The segment new things go into: the active collection's, or the room's first."""
    found = exporter.segments(context.scene)
    active = context.collection
    return active if active in found else (found[0] if found else None)


def _place(context, obj, collection):
    collection.objects.link(obj)
    obj.location = context.scene.cursor.location
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class PRISM_OT_start_room(bpy.types.Operator):
    bl_idname = "prism.start_room"
    bl_label = "Start a room"
    bl_description = "A first segment with a floor and walls, a sun and the game's camera: something to open in the browser and build on"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        importer.prepare_scene(scene)
        if exporter.segments(scene):
            self.report({'INFO'}, "The scene has segments already")
            return {'CANCELLED'}
        c = bpy.data.collections.new(scene.prism.room + "/01")
        importer.root_collection(scene).children.link(c)
        c.prism.is_segment = True
        c.prism.length = 16
        # Blender's axes: the corridor along +Y, Z up. Scale is half the size.
        for name, surface, at, half in (("floor", "floor", (0, 8, -0.5), (3, 8, 0.5)), ("wall.left", "wall", (-3.5, 8, 2), (0.5, 8, 3)),
                                        ("wall.right", "wall", (3.5, 8, 2), (0.5, 8, 3)), ("step", "step", (0, 10, 0.5), (0.5, 0.5, 0.5))):
            o = bpy.data.objects.new(name, importer.unit_box_mesh())
            c.objects.link(o)
            o.location, o.scale = at, half
            o.prism.kind = 'BOX'
            importer._assign(o, importer.material(surface))
        if not any(o.type == 'LIGHT' and o.data.type == 'SUN' for o in scene.objects):
            sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
            scene.collection.objects.link(sun)
            sun.location = (0, 0, 20)
            sun.data.energy = 3
            sun.rotation_euler = (0.7, 0.2, 0.5)
        importer.sync_viewport_colors()
        _refresh(scene)
        return {'FINISHED'}


class PRISM_OT_add_box(bpy.types.Operator):
    bl_idname = "prism.add_box"
    bl_label = "Box"
    bl_description = "A box at the 3D cursor, drawn and collided with: floors, walls, steps. Scale it; its material is its surface"
    bl_options = {'REGISTER', 'UNDO'}

    collider: bpy.props.BoolProperty(name="Collider only", default=False, description="Collides and is not drawn")

    def execute(self, context):
        c = _segment_for_new(context)
        if c is None:
            self.report({'ERROR'}, "No segment yet: 'Start a room' or 'New segment'")
            return {'CANCELLED'}
        o = bpy.data.objects.new("collider" if self.collider else "box", importer.unit_box_mesh())
        _place(context, o, c)
        o.scale = (0.5, 0.5, 0.5)
        o.prism.kind = 'COLLIDER' if self.collider else 'BOX'
        if self.collider:
            o.display_type = 'WIRE'
        else:
            importer._assign(o, importer.material("step"))
            importer.sync_viewport_colors()
        return {'FINISHED'}


def _fill_parameters(obj):
    """The parameters the obstacle's script reads, each with what it is without one, beside those already given."""
    given = {p.value.split("=", 1)[0] for p in obj.prism.params}
    added = 0
    for name, _, default in catalog.obstacle_parameters(obj.prism.type):
        if name not in given:
            obj.prism.params.add().value = f"{name}={default}"
            added += 1
    return added


class PRISM_OT_add_obstacle(bpy.types.Operator):
    bl_idname = "prism.add_obstacle"
    bl_label = "Obstacle"
    bl_description = "An obstacle of the game at the 3D cursor: an Empty that names its script, with the parameters the script reads"
    bl_options = {'REGISTER', 'UNDO'}

    type: bpy.props.StringProperty(name="Type", default="scoretop", description="obstacles/<type>.lua",
                                   search=lambda self, context, text: catalog.obstacles())

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        c = _segment_for_new(context)
        if c is None:
            self.report({'ERROR'}, "No segment yet: 'Start a room' or 'New segment'")
            return {'CANCELLED'}
        o = bpy.data.objects.new(f"obstacle.{self.type}", None)
        _place(context, o, c)
        o.empty_display_type, o.empty_display_size = 'ARROWS', 0.4
        o.rotation_mode = 'QUATERNION'
        o.prism.kind, o.prism.type = 'OBSTACLE', self.type
        _fill_parameters(o)
        return {'FINISHED'}


class PRISM_OT_add_powerup(bpy.types.Operator):
    bl_idname = "prism.add_powerup"
    bl_label = "Powerup"
    bl_description = "A powerup at the 3D cursor"
    bl_options = {'REGISTER', 'UNDO'}

    type: bpy.props.EnumProperty(name="Type", items=[(k, k, "") for k in sorted(validate.POWERUPS)], default="ballfrenzy")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        c = _segment_for_new(context)
        if c is None:
            self.report({'ERROR'}, "No segment yet: 'Start a room' or 'New segment'")
            return {'CANCELLED'}
        o = bpy.data.objects.new(f"powerup.{self.type}", None)
        _place(context, o, c)
        o.empty_display_type, o.empty_display_size = 'SPHERE', 0.4
        o.prism.kind, o.prism.type = 'POWERUP', self.type
        return {'FINISHED'}


class PRISM_OT_fill_params(bpy.types.Operator):
    bl_idname = "prism.fill_params"
    bl_label = "Parameters of the script"
    bl_description = "Add the parameters this obstacle's script reads, each with the value it has when not given"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.prism.kind == 'OBSTACLE' and bool(context.object.prism.type)

    def execute(self, context):
        added = _fill_parameters(context.object)
        self.report({'INFO'}, f"{added} added" if added else "Nothing to add: the script reads no others, or is not known here yet")
        return {'FINISHED'}


class PRISM_MT_main(bpy.types.Menu):
    bl_idname = "PRISM_MT_main"
    bl_label = "Prism"

    def draw(self, context):
        layout = self.layout
        layout.operator("prism.add_box", icon='MESH_CUBE')
        layout.operator("prism.add_box", text="Collider", icon='SHADING_BBOX').collider = True
        layout.operator("prism.add_obstacle", icon='EMPTY_ARROWS')
        layout.operator("prism.add_powerup", icon='SPHERE')
        layout.separator()
        layout.operator("prism.new_segment", icon='ADD')
        layout.operator("prism.start_room", icon='HOME')
        layout.separator()
        layout.operator("prism.browser", text="Close browser view" if live.mode() == 'BROWSER' else "Open in browser", icon='URL')
        layout.operator("prism.play", icon='PLAY')
        layout.operator("prism.edit", icon='VIEW3D')
        layout.separator()
        layout.operator("prism.validate", icon='CHECKMARK')
        layout.operator("prism.export", icon='EXPORT')


def _menu(self, context):
    self.layout.menu(PRISM_MT_main.bl_idname)


# As the tools modellers of this game know have them: Shift Alt and a letter.
SHORTCUTS = (("prism.add_box", 'D'), ("prism.add_obstacle", 'F'), ("prism.add_powerup", 'C'), ("prism.browser", 'E'), ("prism.export", 'R'))
_keys = []


class PRISM_OT_add_softbox(bpy.types.Operator):
    bl_idname = "prism.add_softbox"
    bl_label = "Add softbox"

    def execute(self, context):
        context.scene.prism.softboxes.add()
        return {'FINISHED'}


class PRISM_OT_remove_softbox(bpy.types.Operator):
    bl_idname = "prism.remove_softbox"
    bl_label = "Remove softbox"
    index: bpy.props.IntProperty()

    def execute(self, context):
        context.scene.prism.softboxes.remove(self.index)
        return {'FINISHED'}


class PRISM_OT_add_camera_lamp(bpy.types.Operator):
    bl_idname = "prism.add_camera_lamp"
    bl_label = "Add lamp"

    def execute(self, context):
        context.scene.prism.camera_lamps.add()
        return {'FINISHED'}


class PRISM_OT_remove_camera_lamp(bpy.types.Operator):
    bl_idname = "prism.remove_camera_lamp"
    bl_label = "Remove lamp"
    index: bpy.props.IntProperty()

    def execute(self, context):
        context.scene.prism.camera_lamps.remove(self.index)
        return {'FINISHED'}


class PRISM_OT_add_param(bpy.types.Operator):
    bl_idname = "prism.add_param"
    bl_label = "Add parameter"

    def execute(self, context):
        context.object.prism.params.add().value = "key=value"
        return {'FINISHED'}


class PRISM_OT_remove_param(bpy.types.Operator):
    bl_idname = "prism.remove_param"
    bl_label = "Remove parameter"
    index: bpy.props.IntProperty()

    def execute(self, context):
        context.object.prism.params.remove(self.index)
        return {'FINISHED'}


class PrismPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Prism"


class PRISM_PT_level(PrismPanel, bpy.types.Panel):
    bl_label = "Level"

    def draw(self, context):
        layout = self.layout
        p = context.scene.prism
        layout.prop(p, "room")
        layout.prop(p, "generate_room")
        if p.generate_room:
            layout.prop(p, "level")
            layout.prop(p, "music")
            layout.prop(p, "showcase")
        row = layout.row(align=True)
        row.operator("prism.validate", icon='CHECKMARK')
        row.operator("prism.export", icon='EXPORT')
        row = layout.row(align=True)
        on = live.mode()
        if on != 'APP':
            row.operator("prism.browser", text="Close browser view" if on else "Browser", icon='URL', depress=bool(on))
        # The Mac app's own window, where the repository has it built.
        r = project.root()
        if on != 'BROWSER' and r and os.path.exists(project.app(r)):
            row.operator("prism.live", text="Close live window" if on else "Live window", icon='WINDOW', depress=bool(on))
        said = live.problem()
        if said:
            layout.label(text=said, icon='ERROR')
        # What the scene's scripts print in the page, their errors too.
        said = [line for line in live.script_lines() if not line.startswith(("\t", "stack traceback"))]
        for line in said[-3:]:
            layout.label(text=line[:120], icon='SCRIPT')
        row = layout.row(align=True)
        if live.is_playing():
            row.operator("prism.edit", icon='VIEW3D')
        else:
            row.operator("prism.play", icon='PLAY')
        if not exporter.segments(context.scene):
            layout.operator("prism.start_room", icon='HOME')
        row = layout.row(align=True)
        row.operator("prism.add_box", icon='MESH_CUBE')
        row.operator("prism.add_obstacle", icon='EMPTY_ARROWS')
        row.operator("prism.add_powerup", icon='SPHERE')
        col = layout.column(align=True)
        col.operator("prism.new_segment", icon='ADD')
        col.operator("prism.layout", icon='ALIGN_JUSTIFY')
        row = col.row(align=True)
        row.operator("prism.import_segment", text="Import segment", icon='IMPORT')
        row.operator("prism.import_look", text="Import look", icon='IMPORT')


class PRISM_PT_rules(PrismPanel, bpy.types.Panel):
    bl_label = "Rules"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.prism.generate_room

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        p = context.scene.prism
        for prop, _ in exporter.RULES:
            layout.prop(p, prop)
        layout.label(text="Only what differs from the game's goes into the level", icon='INFO')


class PRISM_PT_problems(PrismPanel, bpy.types.Panel):
    bl_label = "Problems"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        if not _problems:
            self.layout.label(text="None found (press Check)", icon='CHECKMARK')
        for level, where, what in _problems:
            self.layout.label(text=f"{where}: {what}", icon='ERROR' if level == 'ERROR' else 'INFO')


class PRISM_PT_scene(bpy.types.Panel):
    bl_label = "Prism"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        p = context.scene.prism
        layout.label(text="The sun is the Sun lamp of the scene: its direction, colour and strength", icon='LIGHT_SUN')
        for title, names in (("Fog", ("fog_start", "fog_distance", "fog_lower", "fog_upper", "fog_glow", "fog_glow_tightness", "height_density", "height_falloff", "height_color")),
                             ("Shadow", ("shadow_radius", "shadow_softness")),
                             ("Ambient", ("ambient_sky", "ambient_ground", "ground_shade", "ao_strength", "ao_radius")),
                             ("Image", ("exposure", "grade", "vignette", "specular_filter", "bloom_intensity", "bloom_threshold", "near_blur_on")),
                             ("Air", ("shafts", "shaft_density", "shaft_falloff", "shaft_noise", "lamp_halo")),
                             ("Sun", ("tinted_sun", "tint_in", "gobo", "gobo_strength", "gobo_scale", "gobo_drift", "gobo_layer")),
                             ("Matte light", ("matte_reflection", "colour_bounce")),
                             ("View", ("far", "draw_distance", "glow")),
                             ("Reflections", ("trace_scale", "rough_steps", "max_distance", "sparse_blur")),
                             ("Glass", ("glass_dispersion", "glass_noise")),
                             ("Tools", ("live_port", "live_settle"))):
            box = layout.box()
            box.label(text=title)
            for n in names:
                # A switch hides what it switches off.
                if (n.startswith("shaft_") and not p.shafts) or (n == "tint_in" and not p.tinted_sun):
                    continue
                box.prop(p, n)
        box = layout.box()
        box.label(text="Lamps that keep their distance from the camera: light fading towards it")
        for i, l in enumerate(p.camera_lamps):
            sub = box.box()
            for n in ("offset", "color", "intensity", "radius", "source"):
                sub.prop(l, n)
            sub.operator("prism.remove_camera_lamp", text="Remove", icon='X').index = i
        box.operator("prism.add_camera_lamp", icon='ADD')
        box = layout.box()
        box.label(text="Softboxes (what glossy surfaces reflect, at most 4)")
        for i, s in enumerate(p.softboxes):
            sub = box.box()
            for n in ("direction", "up", "size", "color", "softness"):
                sub.prop(s, n)
            sub.operator("prism.remove_softbox", text="Remove", icon='X').index = i
        box.operator("prism.add_softbox", icon='ADD')


class PRISM_PT_material(bpy.types.Panel):
    bl_label = "Prism"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        m = context.material
        bsdf = exporter._principled(m)
        if bsdf:
            for name in ("Base Color", "Roughness", "Metallic", "Emission Strength"):
                layout.prop(bsdf.inputs[name], "default_value", text=name)
        else:
            layout.label(text="No Principled BSDF: viewport colour is used", icon='INFO')
        layout.separator()
        for n in ("casts", "detail", "large_receiver", "friction", "restitution", "map", "data_map", "shading", "shading_params", "is_glass", "frost", "relief", "relief_strength", "relief_density", "frost_pattern", "scatter", "absorption", "opal", "film"):
            layout.prop(m.prism, n)


class PRISM_PT_object(bpy.types.Panel):
    bl_label = "Prism"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        p = context.object.prism
        if context.object.type == 'LIGHT':
            layout.prop(p, "light_radius")
            if context.object.data.type == 'POINT':
                layout.prop(p, "light_tube")
            return
        layout.prop(p, "kind")
        if p.kind == 'VISUAL':
            layout.prop(p, "two_sided")
            layout.prop(p, "physics")
            if p.physics in ('BODY', 'HELD'):
                layout.prop(p, "body_group")
        if p.kind in ('OBSTACLE', 'POWERUP'):
            layout.prop(p, "type")
            layout.prop(p, "difficulty")
        if p.kind == 'OBSTACLE':
            layout.prop(p, "mode")
            for i, param in enumerate(p.params):
                row = layout.row(align=True)
                row.prop(param, "value", text=f"Parameter {i}")
                row.operator("prism.remove_param", text="", icon='X').index = i
            row = layout.row(align=True)
            row.operator("prism.add_param", icon='ADD')
            row.operator("prism.fill_params", icon='PRESET')


class PRISM_PT_collection(bpy.types.Panel):
    bl_label = "Prism"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"

    @classmethod
    def poll(cls, context):
        return context.collection is not None and context.collection != context.scene.collection

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        p = context.collection.prism
        layout.prop(p, "is_segment")
        if p.is_segment:
            layout.prop(p, "length")
            layout.prop(p, "origin_y")
            layout.prop(p, "in_room")
            layout.prop(p, "repeat")
            layout.prop(p, "warn_beyond")


CLASSES = (PRISM_OT_validate, PRISM_OT_export, PRISM_OT_live, PRISM_OT_browser, PRISM_OT_play, PRISM_OT_back_to_edit, PRISM_OT_layout,
           PRISM_OT_new_segment, PRISM_OT_import_segment, PRISM_OT_import_look, PRISM_OT_add_softbox, PRISM_OT_remove_softbox, PRISM_OT_add_camera_lamp, PRISM_OT_remove_camera_lamp,
           PRISM_OT_add_param, PRISM_OT_remove_param, PRISM_OT_start_room, PRISM_OT_add_box, PRISM_OT_add_obstacle, PRISM_OT_add_powerup,
           PRISM_OT_fill_params, PRISM_MT_main, PRISM_PT_level, PRISM_PT_rules, PRISM_PT_problems, PRISM_PT_scene, PRISM_PT_material,
           PRISM_PT_object, PRISM_PT_collection)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_editor_menus.append(_menu)
    # No key configuration without a window (tests, renders).
    config = bpy.context.window_manager.keyconfigs.addon
    if config:
        keymap = config.keymaps.new(name="3D View", space_type='VIEW_3D')
        for operator, key in SHORTCUTS:
            _keys.append((keymap, keymap.keymap_items.new(operator, key, 'PRESS', shift=True, alt=True)))


def unregister():
    live.stop()
    for keymap, item in _keys:
        keymap.keymap_items.remove(item)
    _keys.clear()
    bpy.types.VIEW3D_MT_editor_menus.remove(_menu)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
