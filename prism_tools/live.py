"""The game beside Blender: the camera follows the viewport, edits arrive as they happen. In a browser on any system
(web.py: the web build, served from this machine), or in the Mac app's window where the repository has it built."""
import json
import os
import socket
import subprocess
import time
import webbrowser

import bpy

from . import exporter, mapping as M, project, validate, web

_socket = None
_process = None
# 'APP': the Mac window over its socket. 'BROWSER': pages over web.py. None: off.
_mode = None
_last_camera = None
_last_files = None
_last_own = None
_own_checked = 0.0
_dirty_at = None
_playing = False
_shown = None
OVERLAY = "live"
DEBOUNCE = 0.25
TICK = 1 / 30
# The modeller's own files by the scene are looked at this often for changes (a script edited in another program).
OWN_EVERY = 1.0


def is_on():
    return _mode is not None


def mode():
    return _mode


def send(command, wait_reply=False):
    if _mode == 'BROWSER':
        web.publish(command)
        return None
    if _socket is None:
        return None
    try:
        if wait_reply:
            command = dict(command, reply=True)
        _socket.sendall((json.dumps(command, separators=(",", ":")) + "\n").encode())
        if wait_reply:
            data = b""
            while not data.endswith(b"\n"):
                chunk = _socket.recv(1 << 16)
                if not chunk:
                    raise OSError("closed")
                data += chunk
            return json.loads(data)
    except OSError:
        stop()
    return None


def camera_command(scene):
    """The first 3D viewport's view, or the scene camera when there is none or it looks through it."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            view = area.spaces.active.region_3d
            if view.view_perspective == 'CAMERA' or not view.is_perspective:
                break
            m = view.view_matrix.inverted()
            fov = 2 * _atan_deg(1 / view.window_matrix[0][0])
            return _camera(m, fov)
    return scene_camera_command(scene)


def _atan_deg(x):
    import math
    return math.degrees(math.atan(x))


def scene_camera_command(scene, width=None, height=None):
    camera = scene.camera
    if camera is None:
        return None
    render = scene.render
    w = width or render.resolution_x
    h = height or render.resolution_y
    projection = camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=w, y=h,
                                           scale_x=render.pixel_aspect_x, scale_y=render.pixel_aspect_y)
    return _camera(camera.matrix_world, 2 * _atan_deg(1 / projection[0][0]))


def _camera(m, fov):
    g = M.matrix_to_game(m.normalized())
    # Column by column.
    return {"cmd": "camera", "matrix": [g[r][c] for c in range(4) for r in range(4)], "fov": fov}


def _preview_level(scene):
    """The level itself, or the first segment where the room's script is written by hand."""
    p = scene.prism
    if p.generate_room:
        return p.level
    found = exporter.segments(scene)
    return f"segment:{found[0].name}" if found else None


def _bytes(texts):
    return {k: v if isinstance(v, bytes) else v.encode() for k, v in texts.items()}


def _own():
    """The modeller's own files by the scene, as (path -> (file, when it changed))."""
    found = {}
    for rel, path in project.own_files().items():
        try:
            found[rel] = (path, os.path.getmtime(path), os.path.getsize(path))
        except OSError:
            pass
    return found


def _read(paths):
    out = {}
    for rel, path in paths.items():
        try:
            with open(path, "rb") as f:
                out[rel] = f.read()
        except OSError:
            pass
    return out


def _export(scene):
    """To the scratch copy of Content/, or to the pages. Errors stay in the panel; the window keeps what it has."""
    global _last_files
    if any(level == 'ERROR' for level, _, _ in validate.check(scene)):
        return False
    texts = exporter.files(scene)
    if texts == _last_files:
        return False
    only_look = _last_files is not None and set(texts) == set(_last_files) and all(
        texts[k] == _last_files[k] for k in texts if not k.startswith("looks/"))
    command = ({"cmd": "look", "room": scene.prism.room, "look": exporter.look_dict(scene)} if only_look
               else {"cmd": "reload", "level": _preview_level(scene), "lookOverride": scene.prism.room})
    if _mode == 'BROWSER':
        before = _last_files or {}
        changed = {k: v for k, v in texts.items() if before.get(k) != v}
        # What the scene no longer writes: the modeller's own file of that name shows again, if there is one.
        gone = [k for k in before if k not in texts]
        own = _read({k: p for k, (p, _, _) in (_last_own or {}).items() if k in gone})
        web.publish(command, dict(_bytes(changed), **own), [k for k in gone if k not in own])
    else:
        exporter.write(os.path.join(project.root(), "out", OVERLAY), texts)
        send(command)
    _last_files = texts
    return True


def _own_changed(scene):
    """The modeller's own files by the scene, read again where they changed: the level starts again with them."""
    global _last_own
    now = _own()
    before = _last_own or {}
    if now == before:
        return
    exported = _last_files or {}
    changed = _read({k: v[0] for k, v in now.items() if before.get(k) != v and k not in exported})
    removed = [k for k in before if k not in now and k not in exported]
    _last_own = now
    if changed or removed:
        web.publish({"cmd": "reload", "level": _preview_level(scene), "lookOverride": scene.prism.room}, changed, removed)


def _tick():
    global _last_camera, _dirty_at
    if not is_on():
        return None
    if _process is not None and _process.poll() is not None:
        stop()
        return None
    global _own_checked, _shown
    scene = bpy.context.scene
    if _mode == 'BROWSER' and time.monotonic() - _own_checked > OWN_EVERY:
        _own_checked = time.monotonic()
        _own_changed(scene)
        # The panel shows what the page says; Blender draws it again only when told.
        now = (problem(), tuple(script_lines()))
        if now != _shown:
            _shown = now
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
    # The level has the camera now; edits wait for the way back.
    if _playing:
        return TICK
    camera = camera_command(scene)
    if camera and camera != _last_camera:
        _last_camera = camera
        send(camera)
    if _dirty_at is not None and time.monotonic() - _dirty_at > DEBOUNCE:
        _dirty_at = None
        _export(scene)
    return TICK


@bpy.app.handlers.persistent
def _on_change(scene, depsgraph):
    global _dirty_at
    if is_on():
        _dirty_at = time.monotonic()


def start_browser(scene, open_page=True):
    """The scene in a browser: serves the web build and the scene's files from this machine and opens the page. An error
    message, or None."""
    global _mode, _last_files, _last_own, _last_camera, _playing, _dirty_at
    _playing = False
    if is_on():
        return "Already on"
    if any(l == 'ERROR' for l, _, _ in validate.check(scene)):
        return "Fix the errors in the Prism panel first"
    texts = exporter.files(scene)
    own = _own()
    files = _read({k: v[0] for k, v in own.items()})
    files.update(_bytes(texts))
    prefs = project.preferences()
    message = web.start(prefs.browser_port if prefs else 47812, web.Runtime(project.runtime(), project.runtime_cache()), files,
                        _preview_level(scene), scene.prism.room, camera_command(scene))
    if message:
        return message
    _mode = 'BROWSER'
    _last_files = texts
    _last_own = own
    _last_camera = None
    _dirty_at = None
    if _on_change not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_change)
    bpy.app.timers.register(_tick, first_interval=TICK)
    if open_page:
        webbrowser.open(web.address())
    return None


def start(scene, launch=True):
    global _socket, _process, _last_files, _last_camera, _playing, _mode
    _playing = False
    if is_on():
        return "Already on"
    r = project.root()
    if not r:
        return "No Prism repository: save the .blend inside it or set the add-on's preferences"
    port = scene.prism.live_port
    if launch and not os.path.exists(project.app(r)):
        return f"No {project.app(r)}: build the Prism scheme (Release) with -derivedDataPath build"
    overlay = project.scratch_overlay(OVERLAY)
    level = _preview_level(scene)
    _last_files = None
    _last_camera = None
    if any(l == 'ERROR' for l, _, _ in validate.check(scene)):
        return "Fix the errors in the Prism panel first"
    texts = exporter.files(scene)
    exporter.write(overlay, texts)
    _last_files = texts
    if launch:
        environment = dict(os.environ, PRISM_LIVE=str(port), PRISM_OVERLAY=overlay)
        if level:
            environment["PRISM_LEVEL"] = level
        _process = subprocess.Popen([project.app(r)], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 20
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            break
        except OSError:
            if time.monotonic() > deadline:
                stop()
                return "The Prism window did not answer"
            time.sleep(0.1)
    s.settimeout(10)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    _socket = s
    _mode = 'APP'
    send({"cmd": "reload", "level": level, "lookOverride": scene.prism.room})
    if _on_change not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_change)
    bpy.app.timers.register(_tick, first_interval=TICK)
    return None


def stop():
    global _socket, _process, _dirty_at, _mode
    if _on_change in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_change)
    if _mode == 'BROWSER':
        web.stop()
    _mode = None
    if _socket is not None:
        try:
            _socket.close()
        except OSError:
            pass
        _socket = None
    if _process is not None:
        _process.terminate()
        _process = None
    _dirty_at = None


def is_playing():
    return _playing


def play_from_here(scene):
    """Plays from where the viewport is along the corridor."""
    global _playing
    camera = camera_command(scene)
    if not camera:
        return
    # Game z is along -Blender y: column 3, row 2.
    distance = max(0.0, -camera["matrix"][14])
    _playing = True
    send({"cmd": "play", "distance": distance})


def back_to_edit(scene):
    global _playing, _last_camera, _dirty_at
    _playing = False
    _last_camera = None
    _dirty_at = time.monotonic()
    camera = camera_command(scene)
    if camera:
        send(camera)
    send({"cmd": "reload"})


def flush(scene):
    """What changed since the last export, sent now: before a frame is asked for."""
    global _dirty_at
    if is_on() and not _playing:
        _dirty_at = None
        _export(scene)


def script_lines():
    """What the scene's scripts last printed in the page."""
    return web.said() if _mode == 'BROWSER' else []


def resend_camera():
    """The viewport's camera again at the next tick: something else moved the game's."""
    global _last_camera
    _last_camera = None


def problem():
    """What keeps the browser from showing the scene, in a line for the panel; None when nothing does."""
    if _mode != 'BROWSER':
        return None
    r = web.runtime()
    if r and r.problem:
        return "The game for the browser: " + r.problem
    said = web.status()
    if said and said.get("error"):
        return "The scene did not start: " + said["error"].splitlines()[-1]
    if web.listeners() == 0:
        return "No page is open on the scene: " + web.address()
    return None
