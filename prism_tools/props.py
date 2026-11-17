"""What Blender itself has no field for. Colour, roughness, metal and glow of a material are Principled BSDF's; the sun is a Sun lamp."""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)

GRADES = [(g, g.capitalize(), "") for g in ("neutral", "warm", "cool", "tealOrange", "bleach", "pastel", "vivid")]


class PrismSoftbox(bpy.types.PropertyGroup):
    # In the game's axes: towards it from the scene, Y up.
    direction: FloatVectorProperty(name="Direction", size=3, default=(0, 1, 0))
    up: FloatVectorProperty(name="Up", size=3, default=(0, 1, 0))
    size: FloatVectorProperty(name="Size", size=2, default=(0.5, 0.5), min=0)
    color: FloatVectorProperty(name="Colour", size=3, default=(3, 3, 3), min=0, soft_max=8)
    softness: FloatProperty(name="Softness", default=0.1, min=0, max=1)


class PrismCameraLamp(bpy.types.PropertyGroup):
    # In the game's axes, from the camera: -Z is ahead.
    offset: FloatVectorProperty(name="From the camera", size=3, default=(0, 2, -24))
    color: FloatVectorProperty(name="Colour", size=3, default=(0.5, 0.7, 1), min=0, soft_max=1, subtype='COLOR')
    intensity: FloatProperty(name="Intensity", default=100, min=0)
    radius: FloatProperty(name="Reach", default=40, min=0.1, unit='LENGTH')
    source: FloatProperty(name="Source", default=2, min=0)


class PrismScene(bpy.types.PropertyGroup):
    room: StringProperty(name="Room", description="Room name: looks/<room>.json and rooms/<room>.lua", default="new/room")
    level: StringProperty(name="Level", description="levels/<level>.xml", default="new")
    generate_room: BoolProperty(name="Generate script and level", default=True,
                                description="Off: the room has a hand-written script, only segments and the look are written")
    music: StringProperty(name="Music", description="Track from game-data/music, without extension", default="1")
    showcase: BoolProperty(name="Still scene", default=False,
                           description="Nothing moves: the camera starts at the scene camera and orbits the point it is focused on (Depth of Field > Focus distance)")

    fog_start: FloatProperty(name="Start", default=16, min=0, unit='LENGTH')
    fog_distance: FloatProperty(name="Distance", default=22, min=0.01, unit='LENGTH')
    fog_lower: FloatVectorProperty(name="Below", subtype='COLOR_GAMMA', size=3, default=(0.98, 0.98, 0.99), min=0, soft_max=1)
    fog_upper: FloatVectorProperty(name="Above", subtype='COLOR_GAMMA', size=3, default=(1, 1, 1), min=0, soft_max=1)
    height_density: FloatProperty(name="Height density", default=0, min=0)
    height_falloff: FloatProperty(name="Height falloff", default=1.2, min=0)
    height_color: FloatVectorProperty(name="Height colour", subtype='COLOR_GAMMA', size=3, default=(0.98, 0.98, 0.99), min=0, soft_max=1)

    fog_glow: FloatVectorProperty(name="Glow ahead", size=3, default=(0, 0, 0), min=0, soft_max=2, subtype='COLOR',
                                  description="Light the fog holds towards where the corridor leads")
    fog_glow_tightness: FloatProperty(name="Glow tightness", default=0, min=0, soft_max=30, description="0: none; higher: closer around the way ahead")
    camera_lamps: CollectionProperty(type=PrismCameraLamp)

    shadow_radius: FloatProperty(name="Shadow radius", default=24, min=1, unit='LENGTH')
    shadow_softness: FloatProperty(name="Shadow softness", default=14, min=0)

    ambient_sky: FloatVectorProperty(name="From above", size=3, default=(0.85, 0.918, 1.054), min=0, soft_max=2, subtype='XYZ')
    ambient_ground: FloatVectorProperty(name="From below", size=3, default=(0.408, 0.442, 0.68), min=0, soft_max=2, subtype='XYZ')
    ground_shade: FloatVectorProperty(name="Ground shade", size=2, default=(0.35, 5), min=0,
                                      description="Light lost at the foot of walls, and the height where it is whole again")
    ao_strength: FloatProperty(name="AO", default=0.85, min=0, max=1)
    ao_radius: FloatProperty(name="AO radius", default=0.7, min=0, unit='LENGTH')

    exposure: FloatProperty(name="Exposure", default=0.8, min=0, soft_max=3)
    grade: EnumProperty(name="Grade", items=GRADES, default="vivid")
    vignette: FloatProperty(name="Vignette", default=0.16, min=0, max=1)
    specular_filter: FloatProperty(name="Specular filter", default=0.3, min=0, max=1)
    glass_dispersion: FloatProperty(name="Glass dispersion", default=0.08, min=0)
    glass_noise: FloatProperty(name="Glass noise", default=0.1, min=0)

    softboxes: CollectionProperty(type=PrismSoftbox)

    bloom_intensity: FloatProperty(name="Bloom", default=0.12, min=0)
    bloom_threshold: FloatProperty(name="Bloom threshold", default=1.8, min=0)

    trace_scale: EnumProperty(name="Rays", items=[("1", "Every pixel", ""), ("2", "Per 2x2", ""), ("4", "Per 4x4", "")], default="2")
    rough_steps: FloatProperty(name="Rough steps", default=0.5, min=0, max=1)
    max_distance: FloatProperty(name="Reflection distance", default=40, min=0, unit='LENGTH')
    sparse_blur: FloatProperty(name="Sparse blur", default=1, min=0)

    glow: FloatVectorProperty(name="Target glow", subtype='COLOR_GAMMA', size=4, default=(1, 1, 1, 0.2), min=0, max=1)
    far: FloatProperty(name="Far", default=100, min=1, unit='LENGTH', description="How far the camera sees")
    draw_distance: FloatProperty(name="Draw distance", default=40, min=1, unit='LENGTH', description="How far ahead segments are there")

    near_blur_on: BoolProperty(name="Near blur", default=True, description="What is near the camera softens")
    tinted_sun: BoolProperty(name="Glass colours the sun", default=False, description="Colour on what the sun reaches through glass, reliefs drawn in light")
    tint_in: EnumProperty(name="Where", default='ALL', items=[
        ('ALL', "Light and rays", "Colour and relief on what the sun falls on, and in the rays"),
        ('RAYS', "Only the rays", "The glass colours the rays of the sun in the air; what the sun falls on keeps its own colour")])
    gobo: EnumProperty(name="Sun through", default="none", items=[(k, k.capitalize(), "") for k in ("none", "caustics", "leaves", "blinds", "lattice")])
    gobo_strength: FloatProperty(name="Pattern strength", default=1, min=0, max=1)
    gobo_scale: FloatProperty(name="Repeats per metre", default=0.25, min=0.001)
    gobo_drift: FloatProperty(name="Drift", default=0, min=0)
    gobo_layer: FloatProperty(name="Second layer", default=0, min=0, description="Scale of a second copy drifting over the first: water. 0: none")
    matte_reflection: FloatProperty(name="Matte reflection", default=0, min=0, soft_max=4, description="What rough surfaces reflect, from coarse rays")
    colour_bounce: FloatProperty(name="Colour bounce", default=0, min=0, soft_max=4, description="Corners and contact shadows take the hue of what is near them, without getting lighter")
    lamp_halo: FloatProperty(name="Lamp glow in air", default=0, min=0, soft_max=1)
    shafts: BoolProperty(name="Rays of the sun in the air", default=False,
                         description="Light in the air where the sun reaches it, shadow where it does not. Costs about a tenth of a frame")
    shaft_density: FloatProperty(name="Strength", default=0.03, min=0.001, soft_max=0.3, description="How thick the air is")
    shaft_falloff: FloatProperty(name="Thins with height", default=0.2, min=0)
    shaft_base: FloatProperty(name="Base height", default=0)
    shaft_reach: FloatProperty(name="Reach", default=30, min=1, unit='LENGTH')
    shaft_anisotropy: FloatProperty(name="Towards the sun", default=0.6, min=-0.9, max=0.9)
    shaft_ambient: FloatVectorProperty(name="Air colour", size=3, default=(0.5, 0.55, 0.65), min=0, soft_max=2, subtype='XYZ')
    shaft_ambient_share: FloatProperty(name="Air colour share", default=0.5, min=0, soft_max=2)
    shaft_noise: FloatProperty(name="Clouds", default=0, min=0, max=1)
    shaft_noise_scale: FloatProperty(name="Cloud scale", default=0.25, min=0.001)

    # The game's rules, each written into the level's file only where it is not the game's own (GameRules in the game).
    rule_start_balls: IntProperty(name="Balls at the start", default=25, min=1, soft_max=500)
    rule_crash_penalty: IntProperty(name="Balls lost in a crash", default=10, min=0, soft_max=100)
    rule_crash_grace: FloatProperty(name="Safe after a crash", default=1, min=0, soft_max=5, unit='TIME_ABSOLUTE', description="Seconds nothing can hit the camera again")
    rule_streak_tier: IntProperty(name="Hits for one more ball", default=10, min=1, soft_max=50, description="Every this many crystals in a row a shot is one ball more")
    rule_powerup_duration: FloatProperty(name="A powerup lasts", default=7, min=0.5, soft_max=30, unit='TIME_ABSOLUTE')
    rule_powerup_stack: IntProperty(name="Powerups held", default=4, min=1, max=8)
    rule_frenzy_interval: FloatProperty(name="Frenzy: between shots", default=0.1, min=0.01, soft_max=1, unit='TIME_ABSOLUTE')
    rule_slow_motion: FloatProperty(name="Slow motion: speed", default=0.3333, min=0.05, max=1, description="Share of the normal speed")
    rule_ball_speed: FloatProperty(name="Ball speed", default=20, min=1, soft_max=60, description="Metres a second, against a camera at rest")

    live_port: IntProperty(name="Port", default=47811, min=1024, max=65535)
    live_settle: IntProperty(name="F12 settle", default=30, min=2, description="Updates before the frame")


class PrismMaterial(bpy.types.PropertyGroup):
    casts: BoolProperty(name="Casts shadow", default=True,
                        description="Off for large walls and floors: fewer faces, and nothing in the shadow map")
    detail: FloatProperty(name="Detail", default=0, min=0, max=1, description="Polish patches and fine normals")
    large_receiver: BoolProperty(name="Large receiver", default=False, description="Large reflective surface: reflections smooth their holes on it")
    friction: FloatProperty(name="Friction", default=1, min=0, description="On boxes of this material")
    restitution: FloatProperty(name="Bounce", default=0, min=0, max=1, description="On boxes of this material")
    map: PointerProperty(name="Colour map", type=bpy.types.Image, description="RGB colour, alpha emission; meshes use their first UV map")
    data_map: PointerProperty(name="Data map", type=bpy.types.Image, description="RG normal, B roughness, A metal; the last two scale the values above")
    shading: EnumProperty(name="Shading", default="default", items=[(k, k.capitalize(), d) for k, d in (
        ("default", "Plain PBR"),
        ("clearcoat", "Lacquer over paint. Roughness: of the coat. Parameters: base roughness, flakes"),
        ("sheen", "Velvet, cloth. Parameters: sheen, tightness"),
        ("subsurface", "Wax, soap, jade. Parameters: wrap, light going through"),
        ("anisotropic", "Brushed metal. Parameters: anisotropy, direction (0 up, 0.5 x, 1 along)"),
        ("pearl", "Colour of reflection turns with angle. Parameters: film, strength"),
        ("ghost", "Lit from within at the rim. Parameters: tightness, strength"),
        ("thin", "Paper, leaf: light through to the other side. Parameters: share let through"),
    )])
    shading_params: FloatVectorProperty(name="Parameters", size=3, default=(0, 0, 0), min=0, max=1)
    is_glass: BoolProperty(name="Glass", default=False, description="Refracts the scene: the shader's colour is its tint")
    frost: FloatProperty(name="Frost", default=0, min=0, max=1)
    relief: EnumProperty(name="Relief", default="none", items=[(k, k.capitalize(), "") for k in ("none", "reed", "ripple", "hammer", "block", "diamond", "prism", "ice")])
    relief_strength: FloatProperty(name="Relief strength", default=0.26, min=0, max=1)
    relief_density: FloatProperty(name="Repeats per metre", default=26, min=0.1, max=255)
    frost_pattern: EnumProperty(name="Frost where", default="all", items=[(k, k.capitalize(), "") for k in ("all", "stripes", "rising", "dots", "band", "grid")])
    scatter: FloatProperty(name="Milky", default=0, min=0, max=1, description="Light scatters in the body")
    absorption: FloatProperty(name="Absorption", default=0, min=0, max=16, description="Tint by the real path through the body, per metre")
    opal: FloatProperty(name="Opal", default=0, min=0, max=1, description="Blue where it scatters, warm where it lets through")
    film: FloatProperty(name="Dichroic film", default=0, min=0, max=1, description="What it reflects turns from gold to blue with the angle, what passes takes the other colour")


class PrismParam(bpy.types.PropertyGroup):
    value: StringProperty(name="Value", description="key=value")


class PrismObject(bpy.types.PropertyGroup):
    kind: EnumProperty(name="Kind", default='VISUAL', items=[
        ('VISUAL', "Visual", "Drawn, no collision"),
        ('BOX', "Box", "Drawn and collides"),
        ('COLLIDER', "Collider", "Collides, not drawn"),
        ('OBSTACLE', "Obstacle", "Empty: an obstacle script placed here, or an obstacle built of the Empty's children"),
        ('JOINT', "Joint", "Empty in a built obstacle, child of the part it holds: a pin, a hinge, a slider or a rope"),
        ('POWERUP', "Powerup", "Empty: a powerup placed here"),
        ('IGNORE', "Ignore", "Not exported: guides and references"),
    ])
    type: StringProperty(name="Type", description="Obstacle: obstacles/<type>.lua; powerup: its name")
    mode: IntProperty(name="Mode mask", default=255, min=0, max=255)
    difficulty: FloatVectorProperty(name="Difficulty", size=2, default=(0, 1), min=0, max=1)
    params: CollectionProperty(type=PrismParam)
    two_sided: BoolProperty(name="Two sides", default=False, description="Draw both sides of a Visual, at twice the triangles: for scenes whose faces look any way")
    physics: EnumProperty(name="Physics", default='NONE', items=[
        ('NONE', "None", "Drawn only: nothing hits it"),
        ('STATIC', "Static", "Collides where it stands (its bounding box), never moves: floors, walls"),
        ('BODY', "Body", "A body of its own (its convex hull): balls knock it about. Still scenes"),
        ('HELD', "Held", "Stands where it is until it breaks, then its pieces fall: glass in a wall. Still scenes"),
    ], description="What a Visual does in the physics")
    body_group: StringProperty(name="Body group", description="Bodies of one group are one body (a sofa of seat, back and base): empty, a body of its own")
    # A built obstacle (built.py): the Empty, its parts and its joints.
    balls: IntProperty(name="Gives balls", default=0, min=0, description="Balls for breaking all of its glass; 0: none")
    part_motion: EnumProperty(name="Motion", default='FIXED', items=[
        ('FIXED', "Fixed", "Stands where it is. Glass breaks and its pieces fall"),
        ('FREE', "Free", "A body of its own from the start: it falls, and hangs on its pins, hinges and ropes"),
        ('ANIMATED', "Animated", "Follows its keyframes of location and rotation, whatever hits it"),
        ('SPIN', "Spin", "Turns about one of its own axes"),
        ('LAUNCH', "Launch", "Stands until the camera is near, then is let go with a push"),
    ], description="What this part of the obstacle does")
    part_shape: EnumProperty(name="Shape", default='AUTO', items=[
        ('AUTO', "Auto", "A box where the mesh is one; otherwise the convex hull of each loose piece"),
        ('HULL', "Hull", "The convex hull of each loose piece, a box too"),
    ], description="What the part is in the game: always convex, piece by piece")
    part_strength: FloatProperty(name="Glass strength", default=0.1, min=0, description="The knock that breaks its glass: 0.1 goes at a ball's touch")
    part_bevel: FloatProperty(name="Bevel", default=0, min=0, unit='LENGTH', description="Rounded edges of its steel boxes")
    spin_axis: EnumProperty(name="Axis", default='Z', items=[('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")], description="The part's own axis it turns about")
    spin_speed: FloatProperty(name="Turns a second", default=0.25)
    anim_loop: EnumProperty(name="Repeat", default='LOOP', items=[
        ('LOOP', "Loop", "From the start again"), ('PINGPONG', "There and back", ""), ('ONCE', "Once", "Stays at its last pose")])
    trigger: FloatProperty(name="Starts at", default=0, min=0, unit='LENGTH',
                           description="The camera this near starts it; 0: an animation runs from when the obstacle appears, a launch waits for 8 m")
    push: FloatVectorProperty(name="Push", size=3, default=(0, 0, 0), subtype='VELOCITY', description="Its speed when let go, in the obstacle's axes as Blender shows them")
    push_spin: FloatVectorProperty(name="Push spin", size=3, default=(0, 0, 0), description="Turns a second about the obstacle's axes when let go")
    joint_type: EnumProperty(name="Joint", default='PIN', items=[
        ('PIN', "Pin", "Holds a point of the part: it turns about it freely"),
        ('HINGE', "Hinge", "The part turns about the Empty's Z axis only"),
        ('SLIDER', "Slider", "The part slides along the Empty's Z axis only"),
        ('ROPE', "Rope", "From here along the Empty's Z axis to the first wall, floor or ceiling, or as far as its length says"),
    ])
    joint_to: PointerProperty(name="To", type=bpy.types.Object, description="The other part it holds to; empty: the room")
    joint_length: FloatProperty(name="Length", default=0, min=0, unit='LENGTH', description="A rope's length; 0: to the first surface of the room")
    joint_slack: FloatProperty(name="Slack", default=0, unit='LENGTH', description="A rope this much longer than the way between its ends; below 0 it pulls")
    light_radius: FloatProperty(name="Reach", default=0, min=0, unit='LENGTH', description="Where a lamp ends; 0: where it fades to almost nothing")
    light_tube: FloatProperty(name="Tube length", default=0, min=0, unit='LENGTH',
                              description="A point lamp drawn out into a tube along its own Z (neon): its highlight is a line. 0: a point")
    # File order counts in the game: placing things draws random numbers.
    order: IntProperty(name="Order", default=1 << 20)
    # What was read, so an untouched rotation goes back exactly (Euler angles do not survive the trip).
    game_rot: FloatVectorProperty(size=3)
    has_game_rot: BoolProperty(default=False)
    game_rot_text: StringProperty()


class PrismCollection(bpy.types.PropertyGroup):
    is_segment: BoolProperty(name="Segment", default=False)
    length: FloatProperty(name="Length", default=16, min=0.01, unit='LENGTH', description="Along the corridor")
    origin_y: FloatProperty(name="Origin", default=0, unit='LENGTH', description="Where this segment starts in the scene")
    in_room: BoolProperty(name="In the room", default=True, description="Part of the generated room, in order of name")
    warn_beyond: BoolProperty(name="Stay within the length", default=True, description="Off for what deliberately reaches far beyond: a backdrop")
    repeat: IntProperty(name="Repeat", default=1, min=1, description="Times in a row in the generated room")


CLASSES = (PrismSoftbox, PrismCameraLamp, PrismScene, PrismMaterial, PrismParam, PrismObject, PrismCollection)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.prism = PointerProperty(type=PrismScene)
    bpy.types.Material.prism = PointerProperty(type=PrismMaterial)
    bpy.types.Object.prism = PointerProperty(type=PrismObject)
    bpy.types.Collection.prism = PointerProperty(type=PrismCollection)


def unregister():
    del bpy.types.Collection.prism
    del bpy.types.Object.prism
    del bpy.types.Material.prism
    del bpy.types.Scene.prism
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
