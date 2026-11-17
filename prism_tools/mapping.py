"""Where Blender and the game disagree, in one place: axes, colour space, number format.

Blender is Z up with the corridor along +Y; the game is Y up with the corridor along -Z.
The change of axes is a rotation, so the winding of triangles stays as it is.
"""
import struct

from mathutils import Matrix, Vector

TO_GAME = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
TO_BLENDER = TO_GAME.inverted()


def point_to_game(v):
    return (v[0], v[2], -v[1])


def point_to_blender(v):
    return (v[0], -v[2], v[1])


def half_to_blender(h):
    return (h[0], h[2], h[1])


def half_to_game(h):
    return (h[0], h[2], h[1])


def matrix_to_game(m):
    """A rotation and position in Blender's world, with its local axes as they are: both sides look along local -Z with Y up."""
    return TO_GAME @ m


def rotation_to_game_euler(m):
    """Angles for the game's `rot` (about X, then Y, then Z as quaternions multiplied in that order)."""
    r = (TO_GAME @ m.to_quaternion().to_matrix().to_4x4() @ TO_BLENDER).to_3x3()
    e = r.to_euler('ZYX')
    return (e.x, e.y, e.z)


def game_euler_to_rotation(r):
    """The inverse of `rotation_to_game_euler`: a matrix for an object in Blender."""
    from mathutils import Euler
    return (TO_BLENDER @ Euler(r, 'ZYX').to_matrix().to_4x4() @ TO_GAME).to_3x3()


def f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]


def number(x):
    """The shortest text that reads back as the same float32; files stay readable and stable."""
    x = f32(float(x))
    if x == 0:
        return "0"
    for p in range(1, 10):
        s = f"{x:.{p}g}"
        if f32(float(s)) == x:
            if "e" in s:
                s = f"{float(s):f}".rstrip("0").rstrip(".")
            return s
    return repr(x)


def words(values):
    return " ".join(number(v) for v in values)


def linear_to_srgb(c):
    c = max(c, 0.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def color_to_game(linear):
    """Blender holds colours linear, the game's files sRGB. Rounded: the trip through both is not exact, and vertex colours have 8 bits."""
    return [round(linear_to_srgb(c), 4) for c in list(linear)[:3]]


def color_to_blender(srgb):
    return [srgb_to_linear(c) for c in srgb]


def rounded(values, digits=5):
    return [round(float(v), digits) for v in values]
